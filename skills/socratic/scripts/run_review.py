#!/usr/bin/env python3
"""Mandatory fail-closed entrypoint for Socratic Review-only mutation runs."""

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
import uuid
from pathlib import Path
from typing import Any


ENTRYPOINT = "socratic/scripts/run_review.py"
SOCRATIC_VERSION = "0.2.6"
IGNORED_NAMES = {
    ".git", ".hg", ".svn", ".env", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next", "dist", "build",
}


class RunGateError(RuntimeError):
    """Raised when a run cannot satisfy the mandatory safety boundary."""


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


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value))


def _ignored(_directory: str, names: list[str]) -> set[str]:
    return {
        name for name in names
        if name in IGNORED_NAMES or name.startswith(".env.") or name.endswith(".pyc")
    }


def _protection(attestation_path: Path | None, primary_root: Path) -> dict[str, Any]:
    unavailable = {
        "mode": "unavailable", "verified": False,
        "primary_root": str(primary_root),
        "details": "No verified host read-only or repository-wide write-monitor attestation was supplied.",
    }
    if attestation_path is None:
        return unavailable
    value = _load_json(attestation_path)
    if not isinstance(value, dict):
        return unavailable
    allowed = {"os-read-only", "permission-read-only", "host-events", "os-audit"}
    if (
        value.get("mode") not in allowed
        or value.get("verified") is not True
        or Path(value.get("primary_root", "")).resolve(strict=False) != primary_root
        or not isinstance(value.get("details"), str)
        or not value["details"]
    ):
        return unavailable
    return {
        "mode": value["mode"], "verified": True,
        "primary_root": str(primary_root), "details": value["details"],
    }


def preflight(
    primary_path: Path,
    manifest_path: Path,
    protection_attestation: Path | None,
) -> dict[str, Any]:
    primary_root = _repository_root(primary_path)
    protection = _protection(protection_attestation, primary_root)
    run_id = uuid.uuid4().hex
    ledger_path = manifest_path.resolve().parent / f"{run_id}-mutation-ledger.json"
    manifest: dict[str, Any] = {
        "version": 1,
        "run_id": run_id,
        "status": "blocked",
        "write_mode": "review-only",
        "socratic_version": SOCRATIC_VERSION,
        "entrypoint": ENTRYPOINT,
        "skill_root": str(_skills_root()),
        "primary_root": str(primary_root),
        "sandbox_root": None,
        "protection": protection,
        "environment": {
            key: str(manifest_path.resolve().parent / "blocked")
            for key in ("HOME", "TMPDIR", "XDG_CACHE_HOME", "npm_config_cache")
        },
        "ledger_path": str(ledger_path),
        "blocked_reason": "verified primary protection is required before snapshot creation",
    }
    if protection["verified"]:
        sandbox = Path(tempfile.mkdtemp(prefix=f"socratic-{run_id}-"))
        try:
            shutil.copytree(
                primary_root,
                sandbox,
                dirs_exist_ok=True,
                symlinks=True,
                ignore=_ignored,
            )
            (sandbox / ".socratic-disposable").write_text(f"{run_id}\n", encoding="utf-8")
            environment_root = sandbox / ".socratic-runtime"
            environment = {
                "HOME": environment_root / "home",
                "TMPDIR": environment_root / "tmp",
                "XDG_CACHE_HOME": environment_root / "cache",
                "npm_config_cache": environment_root / "npm-cache",
            }
            for path in environment.values():
                path.mkdir(parents=True, exist_ok=True)
            manifest.update(
                status="ready",
                sandbox_root=str(sandbox.resolve()),
                environment={key: str(path.resolve()) for key, path in environment.items()},
            )
            manifest.pop("blocked_reason", None)
            _write_json(ledger_path, [])
        except BaseException:
            shutil.rmtree(sandbox, ignore_errors=True)
            ledger_path.unlink(missing_ok=True)
            raise
    _write_json(manifest_path, manifest)
    return manifest


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
    if not isinstance(manifest, dict) or manifest.get("status") != "ready":
        raise RunGateError("run manifest is blocked or invalid")
    if manifest.get("entrypoint") != ENTRYPOINT:
        raise RunGateError("run manifest was not created by the mandatory entrypoint")
    if manifest.get("protection", {}).get("verified") is not True:
        raise RunGateError("verified primary protection is required")
    return manifest


def mutate(
    manifest_path: Path,
    mutation_id: str,
    relative_target: str,
    content: bytes,
) -> dict[str, Any]:
    manifest = _ready_manifest(manifest_path)
    if not mutation_id.startswith("MUT-") or not mutation_id[4:].isdigit():
        raise RunGateError(f"invalid mutation id: {mutation_id}")
    sandbox = Path(manifest["sandbox_root"])
    if Path(relative_target).is_absolute() or ".." in Path(relative_target).parts:
        raise RunGateError("mutation target must be a safe sandbox-relative path")
    isolation = _load_module(
        "socratic_isolation_gate",
        _skills_root() / "elenchus" / "scripts" / "isolation_gate.py",
    )
    gate = isolation.IsolationGate(Path(manifest["primary_root"]), sandbox)
    evidence = gate.write_bytes(sandbox / relative_target, content)
    event = {
        "run_id": manifest["run_id"],
        "mutation_id": mutation_id,
        "kind": "guarded-write",
        "requested_path": relative_target,
        "resolved_path": evidence.resolved_target,
        "bytes": len(content),
        "within_sandbox": True,
    }
    ledger_path = Path(manifest["ledger_path"])
    ledger = _load_json(ledger_path)
    if not isinstance(ledger, list):
        raise RunGateError("mutation ledger is invalid")
    ledger.append(event)
    _write_json(ledger_path, ledger)
    return event


def register_prebuilt(
    manifest_path: Path,
    mutation_id: str,
    relative_path: str,
) -> dict[str, Any]:
    manifest = _ready_manifest(manifest_path)
    if not mutation_id.startswith("MUT-") or not mutation_id[4:].isdigit():
        raise RunGateError(f"invalid mutation id: {mutation_id}")
    relative = Path(relative_path)
    sandbox = Path(manifest["sandbox_root"])
    unresolved = sandbox / relative
    isolation = _load_module(
        "socratic_isolation_gate",
        _skills_root() / "elenchus" / "scripts" / "isolation_gate.py",
    )
    gate = isolation.IsolationGate(Path(manifest["primary_root"]), sandbox)
    evidence = gate.authorize(unresolved)
    candidate = Path(evidence.resolved_target)
    try:
        candidate.relative_to(sandbox.resolve())
    except ValueError as error:
        raise RunGateError("prebuilt mutant must be a sandbox-relative regular file") from error
    if relative.is_absolute() or ".." in relative.parts or unresolved.is_symlink() or not candidate.is_file():
        raise RunGateError("prebuilt mutant must be a sandbox-relative regular file")
    event = {
        "run_id": manifest["run_id"],
        "mutation_id": mutation_id,
        "kind": "prebuilt",
        "resolved_path": str(candidate),
        "sha256": _sha256_path(candidate),
    }
    ledger_path = Path(manifest["ledger_path"])
    ledger = _load_json(ledger_path)
    if not isinstance(ledger, list):
        raise RunGateError("mutation ledger is invalid")
    ledger.append(event)
    _write_json(ledger_path, ledger)
    return event


def execute(
    manifest_path: Path,
    command: list[str],
    timeout_seconds: int,
) -> int:
    """Run a test/build command only inside the prepared sandbox environment."""
    manifest = _ready_manifest(manifest_path)
    if not command:
        raise RunGateError("sandbox command must not be empty")
    environment = os.environ.copy()
    environment.update(manifest["environment"])
    sandbox = Path(manifest["sandbox_root"])
    try:
        completed = subprocess.run(
            command,
            cwd=sandbox,
            env=environment,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RunGateError(f"sandbox command timed out after {timeout_seconds}s") from error
    ledger_path = Path(manifest["ledger_path"])
    ledger = _load_json(ledger_path)
    if not isinstance(ledger, list):
        raise RunGateError("mutation ledger is invalid")
    ledger.append({
        "run_id": manifest["run_id"],
        "kind": "command",
        "argv": command,
        "cwd": str(sandbox),
        "timeout_seconds": timeout_seconds,
        "returncode": completed.returncode,
        "environment": manifest["environment"],
    })
    _write_json(ledger_path, ledger)
    return completed.returncode


def finish_document(
    manifest: dict[str, Any],
    report: dict[str, Any],
    review: dict[str, Any],
    ledger: list[dict[str, Any]],
    *,
    manifest_sha256: str | None = None,
    ledger_sha256: str | None = None,
) -> None:
    if manifest.get("status") != "ready" or manifest.get("protection", {}).get("verified") is not True:
        raise RunGateError("run did not pass preflight")
    postflight = report.get("postflight", {})
    if report.get("write_mode") == "review-only" and postflight.get("primary_written_during_run") is not False:
        raise RunGateError("Review-only run wrote to the primary repository, even if later restored")
    run = report.get("run", {})
    if run.get("id") != manifest.get("run_id"):
        raise RunGateError("report and manifest run identities differ")
    if manifest_sha256 is not None and run.get("manifest_sha256") != manifest_sha256:
        raise RunGateError("report manifest hash does not match the preflight manifest")
    if ledger_sha256 is not None and run.get("ledger_sha256") != ledger_sha256:
        raise RunGateError("report ledger hash does not match guarded mutation evidence")
    mutation_ids = {item.get("id") for item in report.get("mutations", [])}
    ledger_ids = {
        item.get("mutation_id")
        for item in ledger if item.get("kind") in {"guarded-write", "prebuilt"}
    }
    if mutation_ids != ledger_ids:
        raise RunGateError(
            f"reported mutations do not match guarded write ledger: report={sorted(mutation_ids)}, ledger={sorted(ledger_ids)}"
        )
    if report.get("isolation", {}).get("primary_root") != manifest.get("primary_root"):
        raise RunGateError("report primary root differs from preflight repository root")
    if report.get("isolation", {}).get("sandbox_root") != manifest.get("sandbox_root"):
        raise RunGateError("report sandbox root differs from preflight sandbox root")
    protection = manifest["protection"]
    isolation = report.get("isolation", {})
    evidence = (
        isolation.get("host_protection", {})
        if protection["mode"] in {"os-read-only", "permission-read-only"}
        else isolation.get("write_monitor", {})
    )
    if evidence.get("mode") != protection["mode"] or evidence.get("verified") is not True:
        raise RunGateError("report protection evidence differs from the preflight attestation")
    targets = {
        (item.get("mutation_id"), item.get("resolved_path"))
        for item in isolation.get("mutation_targets", [])
    }
    guarded_targets = {
        (item.get("mutation_id"), item.get("resolved_path"))
        for item in ledger if item.get("kind") == "guarded-write"
    }
    if targets != guarded_targets:
        raise RunGateError("report mutation targets do not match the guarded write ledger")


def finish(
    manifest_path: Path,
    contract: dict[str, Any],
    report: dict[str, Any],
    review: dict[str, Any],
    schema_root: Path | None = None,
) -> str:
    manifest = _ready_manifest(manifest_path)
    ledger_path = Path(manifest["ledger_path"])
    sandbox = Path(manifest["sandbox_root"])
    result: str | None = None
    failure: BaseException | None = None
    try:
        ledger = _load_json(ledger_path)
        if not isinstance(ledger, list):
            raise RunGateError("mutation ledger is invalid")
        manifest_hash = _sha256_path(manifest_path)
        ledger_hash = _sha256_path(ledger_path)
        finish_document(
            manifest, report, review, ledger,
            manifest_sha256=manifest_hash, ledger_sha256=ledger_hash,
        )
        validator = _load_module(
            "socratic_validate_and_render",
            Path(__file__).resolve().with_name("validate_and_render.py"),
        )
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
    """Remove all ephemeral state for a failed, timed-out, or interrupted run."""
    if not manifest_path.is_file():
        return
    manifest = _load_json(manifest_path)
    if isinstance(manifest, dict):
        sandbox_value = manifest.get("sandbox_root")
        if isinstance(sandbox_value, str):
            shutil.rmtree(Path(sandbox_value), ignore_errors=True)
        ledger_value = manifest.get("ledger_path")
        if isinstance(ledger_value, str):
            Path(ledger_value).unlink(missing_ok=True)
    manifest_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pre = commands.add_parser("preflight")
    pre.add_argument("--primary", required=True, type=Path)
    pre.add_argument("--manifest", required=True, type=Path)
    pre.add_argument("--protection-attestation", type=Path)
    mutation = commands.add_parser("mutate")
    mutation.add_argument("--manifest", required=True, type=Path)
    mutation.add_argument("--mutation-id", required=True)
    mutation.add_argument("--target", required=True)
    mutation.add_argument("--content-file", required=True, type=Path)
    prebuilt = commands.add_parser("register-prebuilt")
    prebuilt.add_argument("--manifest", required=True, type=Path)
    prebuilt.add_argument("--mutation-id", required=True)
    prebuilt.add_argument("--path", required=True)
    run_command = commands.add_parser("execute")
    run_command.add_argument("--manifest", required=True, type=Path)
    run_command.add_argument("--timeout", type=int, default=300)
    run_command.add_argument("argv", nargs=argparse.REMAINDER)
    end = commands.add_parser("finish")
    end.add_argument("--manifest", required=True, type=Path)
    end.add_argument("--contract", required=True, type=Path)
    end.add_argument("--report", required=True, type=Path)
    end.add_argument("--review", required=True, type=Path)
    end.add_argument("--schema-root", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "preflight":
            manifest = preflight(args.primary, args.manifest, args.protection_attestation)
            print(json.dumps(manifest, sort_keys=True))
            return 0 if manifest["status"] == "ready" else 2
        if args.command == "mutate":
            print(json.dumps(mutate(args.manifest, args.mutation_id, args.target, args.content_file.read_bytes()), sort_keys=True))
            return 0
        if args.command == "register-prebuilt":
            print(json.dumps(register_prebuilt(args.manifest, args.mutation_id, args.path), sort_keys=True))
            return 0
        if args.command == "execute":
            argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
            return execute(args.manifest, argv, args.timeout)
        contract = _load_json(args.contract)
        report = _load_json(args.report)
        review = _load_json(args.review)
        sys.stdout.write(finish(args.manifest, contract, report, review, args.schema_root))
        return 0
    except KeyboardInterrupt:
        if hasattr(args, "manifest"):
            abort(args.manifest)
        print("ERROR: interrupted; disposable run state was removed", file=sys.stderr)
        return 130
    except (OSError, RunGateError) as error:
        if args.command in {"mutate", "register-prebuilt", "execute", "finish"}:
            abort(args.manifest)
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
