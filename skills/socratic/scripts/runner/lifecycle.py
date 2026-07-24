"""Run lifecycle: path boundaries, preflight, manifest validation, cleanup."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from runner.constants import (
    ENTRYPOINT,
    REVIEW_TYPES,
    RunGateError,
    SOCRATIC_VERSION,
    _load_json,
    _skills_root,
)
from runner.hashing import _ignored, _tree_hash, _write_exclusive
from runner.hostapi import HostAdapter


def _repository_root(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    start = resolved if resolved.is_dir() else resolved.parent
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate.resolve()
    raise RunGateError(f"primary path is not inside a Git repository: {path}")


def _outside(path: Path, primary_root: Path, label: str, *, strict: bool = False) -> Path:
    resolved = path.resolve(strict=strict)
    try:
        resolved.relative_to(primary_root)
    except ValueError:
        return resolved
    raise RunGateError(f"{label} must be outside the primary repository: {resolved}")


def _inside(path: Path, root: Path, label: str, *, strict: bool = False) -> Path:
    resolved = path.resolve(strict=strict)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise RunGateError(f"{label} must be inside trusted Host storage: {resolved}") from error
    if resolved == root:
        raise RunGateError(f"{label} cannot be the Host storage root")
    return resolved


def blocked_preflight(primary_path: Path) -> dict[str, Any]:
    primary_root = _repository_root(primary_path)
    return {
        "status": "blocked",
        "terminal": True,
        "next_action": "stop",
        "primary_root": str(primary_root),
        "blocked_reason": "a trusted HostAdapter capability is required; self-asserted JSON is not accepted",
        "missing_host_capability": "trusted HostAdapter capability",
    }


def preflight_with_host(primary_path: Path, host_adapter: HostAdapter) -> tuple[dict[str, Any], Path]:
    primary_root = _repository_root(primary_path)
    grant = host_adapter.begin_review_run(primary_root)
    allowed_modes = {"os-read-only", "permission-read-only", "host-events", "os-audit"}
    if (
        not grant.adapter_id
        or len(grant.run_id) != 32
        or any(character not in "0123456789abcdef" for character in grant.run_id)
        or len(grant.run_nonce) < 32
        or grant.protection_mode not in allowed_modes
        or not grant.protection_details
    ):
        raise RunGateError("trusted host adapter returned an invalid capability")
    storage_root = _outside(grant.storage_root, primary_root, "host storage", strict=True)
    if not storage_root.is_dir():
        raise RunGateError("host storage root must already exist")
    change_context = grant.change_context or {
        "source": "local-workspace",
        "head_root": str(primary_root),
    }
    if grant.review_type is None:
        review_type = {
            "recommended": None,
            "options": list(REVIEW_TYPES),
            "requires_human_confirmation": True,
        }
    elif isinstance(grant.review_type, dict):
        review_type = grant.review_type
    else:
        raise RunGateError(
            "trusted host adapter returned an invalid Review Type context"
        )
    if (
        review_type.get("recommended") not in (*REVIEW_TYPES, None)
        or review_type.get("options") != list(REVIEW_TYPES)
        or review_type.get("requires_human_confirmation") is not True
    ):
        raise RunGateError("trusted host adapter returned an invalid Review Type context")
    if Path(change_context["head_root"]).resolve(strict=True) != primary_root:
        raise RunGateError("change context head root differs from the reviewed Primary")
    if change_context["source"] == "github-pull-request":
        _inside(primary_root, storage_root, "materialized head snapshot", strict=True)
        _inside(
            Path(change_context["base_root"]),
            storage_root,
            "materialized base snapshot",
            strict=True,
        )
    manifest_path = _outside(storage_root / "run-manifest.json", primary_root, "manifest")
    ledger_path = _outside(storage_root / "mutation-ledger.jsonl", primary_root, "ledger")
    artifact_root = _outside(storage_root / "artifacts", primary_root, "artifact root")
    artifact_index_path = _outside(
        storage_root / "artifact-index.json", primary_root, "artifact index"
    )
    sandbox: Path | None = None
    ledger_created = False
    manifest_created = False
    artifact_index_created = False
    artifact_root_created = False
    try:
        if artifact_root.exists():
            if not artifact_root.is_dir() or artifact_root.is_symlink():
                raise RunGateError("Host artifact root must be a regular directory")
            if any(artifact_root.iterdir()):
                raise RunGateError("Host artifact root must be empty before preflight")
        else:
            artifact_root.mkdir(mode=0o700)
            artifact_root_created = True
        sandbox = Path(tempfile.mkdtemp(prefix=f"workspace-{grant.run_id}-", dir=storage_root))
        _outside(sandbox, primary_root, "sandbox", strict=True)
        prepared = sandbox / "prepared"
        dependency_root = sandbox / "dependencies"
        shutil.copytree(primary_root, prepared, symlinks=True, ignore=_ignored)
        dependency_root.mkdir(mode=0o700)
        (sandbox / ".socratic-disposable").write_text(f"{grant.run_id}\n", encoding="utf-8")
        environment_root = prepared / ".socratic-runtime"
        environment = {
            "HOME": environment_root / "home",
            "TMPDIR": environment_root / "tmp",
            "XDG_CACHE_HOME": environment_root / "cache",
            "npm_config_cache": environment_root / "npm-cache",
        }
        for path in environment.values():
            path.mkdir(parents=True, exist_ok=True)
        manifest = {
            "version": 1,
            "run_id": grant.run_id,
            "started_at_epoch": round(time.time(), 3),
            "status": "ready",
            "write_mode": "review-only",
            "socratic_version": SOCRATIC_VERSION,
            "entrypoint": ENTRYPOINT,
            "skill_root": str(_skills_root()),
            "primary_root": str(primary_root),
            "sandbox_root": str(sandbox.resolve()),
            "prepared_root": str(prepared.resolve()),
            "dependency_root": str(dependency_root.resolve()),
            "host": {
                "adapter_id": grant.adapter_id,
                "run_nonce": grant.run_nonce,
                "storage_root": str(storage_root),
            },
            "protection": {
                "mode": grant.protection_mode,
                "verified": True,
                "primary_root": str(primary_root),
                "details": grant.protection_details,
            },
            "environment": {key: str(path.resolve()) for key, path in environment.items()},
            "ledger_path": str(ledger_path),
            "artifact_root": str(artifact_root),
            "artifact_index_path": str(artifact_index_path),
            "primary_sha256": _tree_hash(primary_root),
            "change_context": change_context,
            "review_type": review_type,
        }
        _write_exclusive(ledger_path, {"header": {"run_id": grant.run_id, "run_nonce": grant.run_nonce}})
        ledger_created = True
        _write_exclusive(
            artifact_index_path,
            {"version": 1, "run_id": grant.run_id, "artifacts": {}},
        )
        artifact_index_created = True
        _write_exclusive(manifest_path, manifest)
        manifest_created = True
        return manifest, manifest_path
    except BaseException:
        if sandbox is not None:
            shutil.rmtree(sandbox, ignore_errors=True)
        if ledger_created:
            ledger_path.unlink(missing_ok=True)
        if artifact_index_created:
            artifact_index_path.unlink(missing_ok=True)
        if artifact_root_created:
            artifact_root.rmdir()
        if manifest_created:
            manifest_path.unlink(missing_ok=True)
        raise


def _ready_manifest(
    manifest_path: Path, *, allow_missing_sandbox: bool = False
) -> dict[str, Any]:
    if not manifest_path.is_file():
        raise RunGateError("a valid run manifest is required")
    manifest = _load_json(manifest_path)
    try:
        from jsonschema import Draft202012Validator
    except ImportError as error:
        raise RunGateError("jsonschema is required to validate the run manifest") from error
    schema = _load_json(_skills_root() / "socratic" / "references" / "run-manifest.schema.json")
    errors = sorted(Draft202012Validator(schema).iter_errors(manifest), key=lambda item: list(item.path))
    if errors:
        raise RunGateError("run manifest schema validation failed: " + "; ".join(item.message for item in errors))
    primary_root = Path(manifest["primary_root"]).resolve(strict=True)
    _outside(manifest_path, primary_root, "manifest", strict=True)
    _outside(Path(manifest["ledger_path"]), primary_root, "ledger", strict=True)
    _outside(
        Path(manifest["sandbox_root"]),
        primary_root,
        "sandbox",
        strict=not allow_missing_sandbox,
    )
    _outside(
        Path(manifest["prepared_root"]),
        primary_root,
        "prepared snapshot",
        strict=not allow_missing_sandbox,
    )
    dependency_root = manifest.get("dependency_root")
    if dependency_root is not None:
        resolved_dependency_root = _outside(
            Path(dependency_root),
            primary_root,
            "dependency layer",
            strict=not allow_missing_sandbox,
        )
        sandbox_root = Path(manifest["sandbox_root"]).resolve(
            strict=not allow_missing_sandbox
        )
        if allow_missing_sandbox and not sandbox_root.exists():
            pass
        elif not resolved_dependency_root.is_relative_to(sandbox_root):
            raise RunGateError(
                "dependency layer must be inside the disposable sandbox"
            )
    storage_root = _outside(
        Path(manifest["host"]["storage_root"]), primary_root, "host storage", strict=True
    )
    _outside(Path(manifest["artifact_root"]), primary_root, "artifact root", strict=True)
    _outside(
        Path(manifest["artifact_index_path"]), primary_root, "artifact index", strict=True
    )
    if manifest.get("status") != "ready" or manifest.get("entrypoint") != ENTRYPOINT:
        raise RunGateError("run manifest is blocked or was not created by the mandatory entrypoint")
    if manifest.get("protection", {}).get("verified") is not True:
        raise RunGateError("a trusted Host protection attestation is required")
    change = manifest["change_context"]
    if Path(change["head_root"]).resolve(strict=True) != primary_root:
        raise RunGateError("change context head root differs from the reviewed Primary")
    if change["source"] == "github-pull-request":
        _inside(primary_root, storage_root, "materialized head snapshot", strict=True)
        _inside(
            Path(change["base_root"]),
            storage_root,
            "materialized base snapshot",
            strict=True,
        )
    return manifest


def _cleanup_loaded(manifest: dict[str, Any], manifest_path: Path) -> list[str]:
    errors: list[str] = []
    sandbox = Path(manifest["sandbox_root"])
    artifact_root = Path(manifest["artifact_root"])
    if sandbox.exists():
        try:
            shutil.rmtree(sandbox)
        except OSError as error:
            errors.append(f"sandbox cleanup failed: {error}")
    if artifact_root.exists():
        try:
            shutil.rmtree(artifact_root)
        except OSError as error:
            errors.append(f"artifact cleanup failed: {error}")
    for path in (
        Path(manifest["ledger_path"]),
        Path(manifest["artifact_index_path"]),
        manifest_path,
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            errors.append(f"run cleanup failed for {path}: {error}")
    return errors


def cleanup(manifest_path: Path) -> None:
    if not manifest_path.is_file():
        return
    manifest = _ready_manifest(manifest_path, allow_missing_sandbox=True)
    errors = _cleanup_loaded(manifest, manifest_path)
    if errors:
        raise RunGateError("; ".join(errors))


def _record_failure_receipt(
    manifest: dict[str, Any],
    manifest_path: Path,
    phase: str,
    failure: BaseException,
    cleanup_errors: list[str],
) -> Path | None:
    """Keep a small secret-free receipt in Host storage after a terminal failure.

    Cleanup removes the sandbox, artifacts, ledger, and manifest, so without
    this receipt nothing explains why the run ended or whether the Primary
    stayed untouched.
    """
    try:
        primary_postflight_ok: bool | None
        try:
            primary_postflight_ok = _tree_hash(
                Path(manifest["primary_root"])
            ) == manifest["primary_sha256"]
        except (KeyError, OSError, RunGateError):
            primary_postflight_ok = None
        receipt = {
            "version": 1,
            "run_id": manifest.get("run_id"),
            "phase": phase,
            "error_class": type(failure).__name__,
            "error": str(failure),
            "cleanup_ok": not cleanup_errors,
            "cleanup_errors": cleanup_errors,
            "primary_postflight_ok": primary_postflight_ok,
            "recorded_at_epoch": round(time.time(), 3),
        }
        path = manifest_path.parent / "failure-receipt.json"
        path.write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        path.chmod(0o600)
        return path
    except BaseException:
        return None


def abort(manifest_path: Path) -> None:
    if not manifest_path.is_file():
        return
    manifest = _load_json(manifest_path)
    if not isinstance(manifest, dict):
        manifest_path.unlink(missing_ok=True)
        return
    required = {
        "sandbox_root", "artifact_root", "ledger_path", "artifact_index_path"
    }
    if required.issubset(manifest):
        _cleanup_loaded(manifest, manifest_path)
    else:
        manifest_path.unlink(missing_ok=True)
