#!/usr/bin/env python3
"""Host-gated fail-closed entrypoint for Socratic Review-only mutation runs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


ENTRYPOINT = "socratic/scripts/run_review.py"
SOCRATIC_VERSION = "0.3.0-alpha.2"
IGNORED_NAMES = {
    ".git", ".hg", ".svn", ".env", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next", "dist", "build",
}


class RunGateError(RuntimeError):
    """Raised when a run cannot satisfy the mandatory safety boundary."""


@dataclass(frozen=True)
class HostGrant:
    """Capability issued by a trusted host adapter outside the agent boundary."""

    adapter_id: str
    run_id: str
    run_nonce: str
    storage_root: Path
    protection_mode: str
    protection_details: str


class HostAdapter(Protocol):
    """Host integration point. The standalone CLI intentionally has no implementation."""

    def begin_review_run(self, primary_root: Path) -> HostGrant: ...


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RunGateError(f"cannot load required helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _skills_root() -> Path:
    return Path(__file__).resolve().parents[2]


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


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RunGateError(f"strict JSON load failed for {path}: {error}") from error


def _write_exclusive(path: Path, value: Any) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(_canonical_bytes(value))


def _ignored(_directory: str, names: list[str]) -> set[str]:
    return {
        name for name in names
        if name in IGNORED_NAMES or name.startswith(".env.") or name.endswith(".pyc")
    }


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
    manifest_path = _outside(storage_root / "run-manifest.json", primary_root, "manifest")
    ledger_path = _outside(storage_root / "mutation-ledger.jsonl", primary_root, "ledger")
    sandbox: Path | None = None
    ledger_created = False
    manifest_created = False
    try:
        sandbox = Path(tempfile.mkdtemp(prefix=f"workspace-{grant.run_id}-", dir=storage_root))
        _outside(sandbox, primary_root, "sandbox", strict=True)
        shutil.copytree(primary_root, sandbox, dirs_exist_ok=True, symlinks=True, ignore=_ignored)
        (sandbox / ".socratic-disposable").write_text(f"{grant.run_id}\n", encoding="utf-8")
        environment_root = sandbox / ".socratic-runtime"
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
            "status": "ready",
            "write_mode": "review-only",
            "socratic_version": SOCRATIC_VERSION,
            "entrypoint": ENTRYPOINT,
            "skill_root": str(_skills_root()),
            "primary_root": str(primary_root),
            "sandbox_root": str(sandbox.resolve()),
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
        }
        _write_exclusive(ledger_path, {"header": {"run_id": grant.run_id, "run_nonce": grant.run_nonce}})
        ledger_created = True
        _write_exclusive(manifest_path, manifest)
        manifest_created = True
        return manifest, manifest_path
    except BaseException:
        if sandbox is not None:
            shutil.rmtree(sandbox, ignore_errors=True)
        if ledger_created:
            ledger_path.unlink(missing_ok=True)
        if manifest_created:
            manifest_path.unlink(missing_ok=True)
        raise


def _ready_manifest(manifest_path: Path) -> dict[str, Any]:
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
    _outside(Path(manifest["sandbox_root"]), primary_root, "sandbox", strict=True)
    _outside(Path(manifest["host"]["storage_root"]), primary_root, "host storage", strict=True)
    if manifest.get("status") != "ready" or manifest.get("entrypoint") != ENTRYPOINT:
        raise RunGateError("run manifest is blocked or was not created by the mandatory entrypoint")
    if manifest.get("protection", {}).get("verified") is not True:
        raise RunGateError("a trusted Host protection attestation is required")
    return manifest


def _ledger_events(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    path = Path(manifest["ledger_path"])
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0])
    except (OSError, IndexError, json.JSONDecodeError) as error:
        raise RunGateError("append-only mutation ledger is invalid") from error
    if header != {"header": {"run_id": manifest["run_id"], "run_nonce": manifest["host"]["run_nonce"]}}:
        raise RunGateError("ledger header does not match the host-issued run nonce")
    previous = _sha256_bytes(_canonical_bytes(header))
    events: list[dict[str, Any]] = []
    for sequence, line in enumerate(lines[1:], 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise RunGateError("append-only mutation ledger contains invalid JSON") from error
        event = record.get("event")
        expected = _sha256_bytes(
            manifest["host"]["run_nonce"].encode() + previous.encode() + _canonical_bytes(event)
        )
        if record.get("sequence") != sequence or record.get("previous") != previous or record.get("digest") != expected:
            raise RunGateError("append-only mutation ledger chain is invalid")
        events.append(event)
        previous = expected
    return events


def _ledger_head(manifest: dict[str, Any]) -> str:
    path = Path(manifest["ledger_path"])
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) == 1:
        return _sha256_bytes((lines[0] + "\n").encode())
    return json.loads(lines[-1])["digest"]


def _append_event(manifest: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    events = _ledger_events(manifest)
    path = Path(manifest["ledger_path"])
    lines = path.read_text(encoding="utf-8").splitlines()
    previous = _sha256_bytes((lines[0] + "\n").encode()) if not events else json.loads(lines[-1])["digest"]
    digest = _sha256_bytes(
        manifest["host"]["run_nonce"].encode() + previous.encode() + _canonical_bytes(event)
    )
    record = {"sequence": len(events) + 1, "previous": previous, "digest": digest, "event": event}
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
    with os.fdopen(descriptor, "ab") as stream:
        stream.write(_canonical_bytes(record))
    return event


def mutate(manifest_path: Path, mutation_id: str, relative_target: str, content: bytes) -> dict[str, Any]:
    manifest = _ready_manifest(manifest_path)
    if not mutation_id.startswith("MUT-") or not mutation_id[4:].isdigit():
        raise RunGateError(f"invalid mutation id: {mutation_id}")
    sandbox = Path(manifest["sandbox_root"])
    if Path(relative_target).is_absolute() or ".." in Path(relative_target).parts:
        raise RunGateError("mutation target must be a safe sandbox-relative path")
    isolation = _load_module("socratic_isolation_gate", _skills_root() / "elenchus/scripts/isolation_gate.py")
    evidence = isolation.IsolationGate(Path(manifest["primary_root"]), sandbox).write_bytes(
        sandbox / relative_target, content
    )
    return _append_event(manifest, {
        "run_id": manifest["run_id"], "mutation_id": mutation_id, "kind": "guarded-write",
        "requested_path": relative_target, "resolved_path": evidence.resolved_target,
        "content_sha256": _sha256_bytes(content), "bytes": len(content), "within_sandbox": True,
    })


def register_prebuilt(manifest_path: Path, mutation_id: str, relative_path: str) -> dict[str, Any]:
    manifest = _ready_manifest(manifest_path)
    if not mutation_id.startswith("MUT-") or not mutation_id[4:].isdigit():
        raise RunGateError(f"invalid mutation id: {mutation_id}")
    relative = Path(relative_path)
    sandbox = Path(manifest["sandbox_root"])
    unresolved = sandbox / relative
    isolation = _load_module("socratic_isolation_gate", _skills_root() / "elenchus/scripts/isolation_gate.py")
    evidence = isolation.IsolationGate(Path(manifest["primary_root"]), sandbox).authorize(unresolved)
    candidate = Path(evidence.resolved_target)
    if relative.is_absolute() or ".." in relative.parts or unresolved.is_symlink() or not candidate.is_file():
        raise RunGateError("prebuilt mutant must be a sandbox-relative regular file")
    return _append_event(manifest, {
        "run_id": manifest["run_id"], "mutation_id": mutation_id, "kind": "prebuilt",
        "resolved_path": str(candidate), "sha256": _sha256_path(candidate),
    })


def execute(
    manifest_path: Path,
    phase: str,
    mutation_id: str | None,
    command: list[str],
    timeout_seconds: int,
) -> int:
    manifest = _ready_manifest(manifest_path)
    if phase not in {"baseline", "mutation"}:
        raise RunGateError("execute phase must be baseline or mutation")
    if phase == "baseline" and mutation_id is not None:
        raise RunGateError("baseline execution must not have a mutation id")
    if phase == "mutation" and mutation_id is None:
        raise RunGateError("mutation execution requires --mutation-id")
    if not command:
        raise RunGateError("sandbox command must not be empty")
    registered = {
        item.get("mutation_id") for item in _ledger_events(manifest)
        if item.get("kind") in {"guarded-write", "prebuilt"}
    }
    if phase == "mutation" and mutation_id not in registered:
        raise RunGateError(f"mutation execution has no guarded mutation evidence: {mutation_id}")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG"} or key.startswith("LC_")
    }
    environment.update(manifest["environment"])
    try:
        completed = subprocess.run(
            command, cwd=Path(manifest["sandbox_root"]), env=environment,
            timeout=timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RunGateError(f"sandbox command timed out after {timeout_seconds}s") from error
    _append_event(manifest, {
        "run_id": manifest["run_id"], "kind": "command", "phase": phase,
        "mutation_id": mutation_id, "argv": command, "timeout_seconds": timeout_seconds,
        "returncode": completed.returncode, "environment": manifest["environment"],
    })
    return completed.returncode


def finish_document(
    manifest: dict[str, Any], report: dict[str, Any], review: dict[str, Any],
    ledger: list[dict[str, Any]], *, manifest_sha256: str, ledger_head: str,
) -> None:
    if manifest.get("status") != "ready" or manifest.get("protection", {}).get("verified") is not True:
        raise RunGateError("run did not pass trusted Host-attested preflight")
    if report.get("write_mode") == "review-only" and report.get("postflight", {}).get("primary_written_during_run") is not False:
        raise RunGateError("Review-only run wrote to the primary repository, even if later restored")
    run = report.get("run", {})
    expected_run = {
        "id": manifest["run_id"], "entrypoint": ENTRYPOINT,
        "host_adapter": manifest["host"]["adapter_id"],
        "run_nonce": manifest["host"]["run_nonce"],
        "manifest_sha256": manifest_sha256, "ledger_head": ledger_head,
    }
    if run != expected_run:
        raise RunGateError("report run identity does not match the host-issued manifest and ledger chain")
    mutations = {item["id"]: item for item in report.get("mutations", [])}
    registered = {
        item.get("mutation_id") for item in ledger
        if item.get("kind") in {"guarded-write", "prebuilt"}
    }
    executions: dict[str, list[dict[str, Any]]] = {}
    baselines = [item for item in ledger if item.get("kind") == "command" and item.get("phase") == "baseline"]
    for item in ledger:
        if item.get("kind") == "command" and item.get("phase") == "mutation":
            executions.setdefault(item["mutation_id"], []).append(item)
    if not baselines:
        raise RunGateError("run has no baseline execution evidence")
    if set(mutations) != registered or set(mutations) != set(executions):
        raise RunGateError("every reported mutation requires guarded mutation and execution evidence")
    for mutation_id, mutation in mutations.items():
        returncodes = [item["returncode"] for item in executions[mutation_id]]
        if mutation["result"] == "killed" and not any(code != 0 for code in returncodes):
            raise RunGateError(f"killed mutation has no failing execution: {mutation_id}")
        if mutation["result"] == "survived" and any(code != 0 for code in returncodes):
            raise RunGateError(f"survived mutation has a failing execution: {mutation_id}")
    isolation = report.get("isolation", {})
    if isolation.get("primary_root") != manifest["primary_root"] or isolation.get("sandbox_root") != manifest["sandbox_root"]:
        raise RunGateError("report roots differ from trusted host preflight")
    protection = manifest["protection"]
    evidence = isolation.get("host_protection", {}) if protection["mode"] in {"os-read-only", "permission-read-only"} else isolation.get("write_monitor", {})
    if evidence.get("mode") != protection["mode"] or evidence.get("verified") is not True:
        raise RunGateError("report protection evidence differs from the trusted Host attestation")
    targets = {(item.get("mutation_id"), item.get("resolved_path")) for item in isolation.get("mutation_targets", [])}
    guarded = {
        (item.get("mutation_id"), item.get("resolved_path"))
        for item in ledger if item.get("kind") == "guarded-write"
    }
    if targets != guarded:
        raise RunGateError("report mutation targets do not match the guarded write ledger")


def finish(
    manifest_path: Path, contract: dict[str, Any], report: dict[str, Any],
    review: dict[str, Any], schema_root: Path | None = None,
) -> str:
    manifest = _ready_manifest(manifest_path)
    ledger_path = Path(manifest["ledger_path"])
    sandbox = Path(manifest["sandbox_root"])
    result: str | None = None
    failure: BaseException | None = None
    try:
        ledger = _ledger_events(manifest)
        finish_document(
            manifest, report, review, ledger,
            manifest_sha256=_sha256_path(manifest_path), ledger_head=_ledger_head(manifest),
        )
        validator = _load_module("socratic_validate_and_render", Path(__file__).resolve().with_name("validate_and_render.py"))
        try:
            validator.validate_with_schemas(contract, report, review, schema_root)
        except validator.ArtifactError as error:
            raise RunGateError(str(error)) from error
        result = validator.render_review(review)
    except BaseException as error:
        failure = error
    cleanup_errors: list[str] = []
    try:
        if sandbox.exists():
            shutil.rmtree(sandbox)
    except OSError as error:
        cleanup_errors.append(f"sandbox cleanup failed: {error}")
    for path in (ledger_path, manifest_path):
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            cleanup_errors.append(f"artifact cleanup failed for {path}: {error}")
    if cleanup_errors:
        raise RunGateError("; ".join(cleanup_errors)) from failure
    if failure is not None:
        raise failure
    assert result is not None
    return result


def abort(manifest_path: Path) -> None:
    if not manifest_path.is_file():
        return
    manifest = _load_json(manifest_path)
    if isinstance(manifest, dict):
        if isinstance(manifest.get("sandbox_root"), str):
            shutil.rmtree(Path(manifest["sandbox_root"]), ignore_errors=True)
        if isinstance(manifest.get("ledger_path"), str):
            Path(manifest["ledger_path"]).unlink(missing_ok=True)
    manifest_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pre = commands.add_parser("preflight")
    pre.add_argument("--primary", required=True, type=Path)
    for name in ("mutate", "register-prebuilt", "execute", "finish"):
        commands.add_parser(name)
    args, _unknown = parser.parse_known_args()
    if args.command == "preflight":
        print(json.dumps(blocked_preflight(args.primary), sort_keys=True))
        return 2
    print(
        "ERROR: mutation phases require a trusted HostAdapter integration; standalone CLI execution is blocked",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
