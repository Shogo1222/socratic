#!/usr/bin/env python3
"""Host-gated fail-closed entrypoint for Socratic Review-only mutation runs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


ENTRYPOINT = "socratic/scripts/run_review.py"
SOCRATIC_VERSION = "0.3.0-alpha.8"
ARTIFACT_FILES = {
    "contract": "intent-contract.draft.json",
    "report": "mutation-report.draft.json",
    "review": "canonical-review.draft.json",
}
ARTIFACT_SCHEMAS = {
    "contract": "intent-contract.schema.json",
    "report": "mutation-report-draft.schema.json",
    "review": "canonical-review.schema.json",
}
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


class ClaudeSocketHostAdapter:
    """Obtain a run grant from the live launcher-owned Unix socket."""

    def __init__(self, socket_path: Path, token: str):
        self.socket_path = socket_path
        self.token = token

    @classmethod
    def from_environment(cls) -> "ClaudeSocketHostAdapter":
        path = os.environ.get("SOCRATIC_HOST_SOCKET", "")
        token = os.environ.get("SOCRATIC_HOST_TOKEN", "")
        if not path or len(token) < 32:
            raise RunGateError("trusted Claude Host broker is unavailable")
        return cls(Path(path), token)

    def begin_review_run(self, primary_root: Path) -> HostGrant:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1)
                client.connect(str(self.socket_path))
                client.sendall(json.dumps({"action": "grant", "token": self.token}).encode())
                response = json.loads(client.recv(65536).decode())
            grant = response["grant"]
        except (OSError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as error:
            raise RunGateError("trusted Claude Host broker rejected the run") from error
        return HostGrant(
            adapter_id=grant["adapter_id"], run_id=grant["run_id"],
            run_nonce=grant["run_nonce"], storage_root=Path(grant["storage_root"]),
            protection_mode=grant["protection_mode"],
            protection_details=grant["protection_details"],
        )


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


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False):
        names[:] = sorted(name for name in names if name not in IGNORED_NAMES)
        relative_directory = Path(directory).relative_to(root)
        for filename in sorted(filenames):
            if (
                filename in IGNORED_NAMES
                or filename.startswith(".env.")
                or filename.endswith(".pyc")
            ):
                continue
            path = Path(directory) / filename
            relative = (relative_directory / filename).as_posix()
            digest.update(relative.encode("utf-8") + b"\0")
            if path.is_symlink():
                digest.update(b"symlink\0" + os.readlink(path).encode("utf-8"))
            elif path.is_file():
                digest.update(b"file\0")
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
            else:
                digest.update(b"other\0")
    return digest.hexdigest()


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
            "artifact_root": str(artifact_root),
            "artifact_index_path": str(artifact_index_path),
            "primary_sha256": _tree_hash(primary_root),
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
    _outside(Path(manifest["host"]["storage_root"]), primary_root, "host storage", strict=True)
    _outside(Path(manifest["artifact_root"]), primary_root, "artifact root", strict=True)
    _outside(
        Path(manifest["artifact_index_path"]), primary_root, "artifact index", strict=True
    )
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


def _write_index(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.unlink(missing_ok=True)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_canonical_bytes(value))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _artifact_index(manifest: dict[str, Any]) -> dict[str, Any]:
    index = _load_json(Path(manifest["artifact_index_path"]))
    if index.get("version") != 1 or index.get("run_id") != manifest["run_id"]:
        raise RunGateError("Host artifact index does not match this run")
    if not isinstance(index.get("artifacts"), dict):
        raise RunGateError("Host artifact index is malformed")
    return index


def _validator_module():
    return _load_module(
        "socratic_validate_and_render",
        Path(__file__).resolve().with_name("validate_and_render.py"),
    )


def _record_validation_error(manifest: dict[str, Any], kind: str, message: str) -> None:
    path = Path(manifest["artifact_root"]) / "validation-errors.json"
    current: dict[str, Any] = {
        "version": 1,
        "run_id": manifest["run_id"],
        "errors": [],
    }
    if path.is_file():
        loaded = _load_json(path)
        if isinstance(loaded, dict) and isinstance(loaded.get("errors"), list):
            current = loaded
    current["errors"].append({"artifact": kind, "message": message})
    _write_index(path, current)


def stage_artifact(
    manifest_path: Path,
    kind: str,
    schema_root: Path | None = None,
) -> dict[str, Any]:
    manifest = _ready_manifest(manifest_path)
    if kind not in ARTIFACT_FILES:
        raise RunGateError(f"unknown artifact kind: {kind}")
    index = _artifact_index(manifest)
    if kind in index["artifacts"]:
        raise RunGateError(f"artifact is already staged and create-once: {kind}")
    artifact_path = Path(manifest["artifact_root"]) / ARTIFACT_FILES[kind]
    if (
        not artifact_path.is_file()
        or artifact_path.is_symlink()
        or artifact_path.parent.resolve(strict=True) != Path(manifest["artifact_root"]).resolve(strict=True)
    ):
        raise RunGateError(f"draft artifact is missing from the Host staging channel: {kind}")
    document = _load_json(artifact_path)
    if not isinstance(document, dict):
        raise RunGateError(f"draft artifact root must be an object: {kind}")
    validator = _validator_module()
    try:
        validator.validate_document(document, ARTIFACT_SCHEMAS[kind], schema_root)
    except validator.ArtifactError as error:
        _record_validation_error(manifest, kind, str(error))
        raise RunGateError(str(error)) from error
    record = {
        "path": str(artifact_path),
        "sha256": _sha256_path(artifact_path),
        "schema": ARTIFACT_SCHEMAS[kind],
    }
    index["artifacts"][kind] = record
    _write_index(Path(manifest["artifact_index_path"]), index)
    (Path(manifest["artifact_root"]) / "validation-errors.json").unlink(missing_ok=True)
    return record


def _staged_artifacts(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index = _artifact_index(manifest)
    if set(index["artifacts"]) != set(ARTIFACT_FILES):
        missing = sorted(set(ARTIFACT_FILES) - set(index["artifacts"]))
        raise RunGateError(f"finish requires all staged artifacts: {missing}")
    documents: dict[str, dict[str, Any]] = {}
    for kind, filename in ARTIFACT_FILES.items():
        record = index["artifacts"][kind]
        path = Path(manifest["artifact_root"]) / filename
        if record.get("path") != str(path) or record.get("sha256") != _sha256_path(path):
            raise RunGateError(f"staged artifact changed after Host indexing: {kind}")
        document = _load_json(path)
        if not isinstance(document, dict):
            raise RunGateError(f"staged artifact root must be an object: {kind}")
        documents[kind] = document
    return documents


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
        _append_event(manifest, {
            "run_id": manifest["run_id"], "kind": "command", "phase": phase,
            "mutation_id": mutation_id, "argv": command, "timeout_seconds": timeout_seconds,
            "result": "timeout", "returncode": None, "environment": manifest["environment"],
        })
        raise RunGateError(f"sandbox command timed out after {timeout_seconds}s") from error
    _append_event(manifest, {
        "run_id": manifest["run_id"], "kind": "command", "phase": phase,
        "mutation_id": mutation_id, "argv": command, "timeout_seconds": timeout_seconds,
        "result": "completed", "returncode": completed.returncode,
        "environment": manifest["environment"],
    })
    return completed.returncode


def _attested_report(
    manifest: dict[str, Any],
    contract: dict[str, Any],
    draft: dict[str, Any],
    ledger: list[dict[str, Any]],
    *,
    manifest_sha256: str,
    ledger_head: str,
) -> dict[str, Any]:
    guarded = [item for item in ledger if item.get("kind") == "guarded-write"]
    registered = [
        item for item in ledger if item.get("kind") in {"guarded-write", "prebuilt"}
    ]
    if guarded:
        strategy = "guarded-file-write"
    elif registered:
        strategy = "prebuilt-mutant"
    else:
        strategy = "comparison-only"
    protection = manifest["protection"]
    protected = protection["mode"] in {"os-read-only", "permission-read-only"}
    monitored = protection["mode"] in {"host-events", "os-audit"}
    unresolved = [item["id"] for item in contract.get("unresolved", [])]
    baselines = [
        item for item in ledger
        if item.get("kind") == "command" and item.get("phase") == "baseline"
    ]
    mutation_executions = [
        item for item in ledger
        if item.get("kind") == "command" and item.get("phase") == "mutation"
    ]

    def raw_outcome(item: dict[str, Any]) -> str:
        if item.get("result") == "timeout":
            return "timeout"
        return "passed" if item.get("returncode") == 0 else "failed"

    report = {
        "version": 8,
        "mode": draft["mode"],
        "write_mode": "review-only",
        "run": {
            "id": manifest["run_id"],
            "entrypoint": ENTRYPOINT,
            "host_adapter": manifest["host"]["adapter_id"],
            "run_nonce": manifest["host"]["run_nonce"],
            "manifest_sha256": manifest_sha256,
            "ledger_head": ledger_head,
        },
        "intent_contract": {
            "path": "host-artifact://intent-contract",
            "status": contract["status"],
        },
        "baseline": draft["baseline"],
        "assessment": draft["assessment"],
        "mutations": draft["mutations"],
        "not_challenged": draft["not_challenged"],
        "unresolved": unresolved,
        "test_changes": draft["test_changes"],
        "test_handoff": draft["test_handoff"],
        "authorized_workspace_changes": draft["authorized_workspace_changes"],
        "execution_evidence": {
            "source": "host-ledger",
            "baseline": [
                {
                    "attempt": attempt,
                    "outcome": raw_outcome(item),
                    "exit_code": item.get("returncode"),
                }
                for attempt, item in enumerate(baselines, 1)
            ],
            "mutations": [
                {
                    "mutation_id": item["mutation_id"],
                    "attempt": attempt,
                    "outcome": raw_outcome(item),
                    "exit_code": item.get("returncode"),
                }
                for mutation_id in sorted({
                    item["mutation_id"] for item in mutation_executions
                })
                for attempt, item in enumerate(
                    [
                        event for event in mutation_executions
                        if event["mutation_id"] == mutation_id
                    ],
                    1,
                )
            ],
        },
        "isolation": {
            "execution_strategy": strategy,
            "primary_root": manifest["primary_root"],
            "sandbox_root": manifest["sandbox_root"],
            "host_protection": {
                "mode": protection["mode"] if protected else "unavailable",
                "verified": protected,
                "details": protection["details"] if protected else "not used",
            },
            "write_monitor": {
                "mode": protection["mode"] if monitored else "unavailable",
                "verified": monitored,
                "details": protection["details"] if monitored else "not used",
            },
            "mutation_targets": [
                {
                    "mutation_id": item["mutation_id"],
                    "requested_path": item["requested_path"],
                    "resolved_path": item["resolved_path"],
                    "within_sandbox": True,
                }
                for item in guarded
            ],
            "write_events": [
                {
                    "target": item["resolved_path"],
                    "bytes": item["bytes"],
                    "within_sandbox": True,
                }
                for item in guarded
            ],
        },
        "persistent_side_effects": draft["persistent_side_effects"],
        "canonical_output": {
            "renderer": "socratic/scripts/validate_and_render.py",
            "sha256": "0" * 64,
            "extra_prose": False,
        },
        "postflight": {
            "primary_written_during_run": False,
            "primary_final_hash_unchanged": True,
            "working_tree_final_status": "primary content hash matched preflight",
            "production_mutation_free": True,
            "sandbox_destroyed": True,
            "notes": "Host protection accepted; disposable sandbox removed before rendering.",
        },
    }
    return report


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
    baseline = report.get("baseline", {})
    if baseline.get("attempts") != len(baselines):
        raise RunGateError("report baseline attempts do not match baseline execution evidence")
    baseline_results = [item.get("result", "completed") for item in baselines]
    baseline_codes = [item.get("returncode") for item in baselines]
    baseline_status = baseline.get("status")
    if baseline_status == "green" and (
        any(result != "completed" for result in baseline_results)
        or any(code != 0 for code in baseline_codes)
    ):
        raise RunGateError("green baseline does not match successful execution evidence")
    if baseline_status == "baseline-red" and not any(
        result == "completed" and code != 0
        for result, code in zip(baseline_results, baseline_codes)
    ):
        raise RunGateError("baseline-red does not match failing execution evidence")
    if baseline_status == "not-runnable" and not any(
        result == "timeout" for result in baseline_results
    ):
        raise RunGateError("not-runnable baseline has no timeout execution evidence")
    if baseline_status == "flaky-reduced" and not (
        any(result == "completed" and code == 0 for result, code in zip(baseline_results, baseline_codes))
        and baseline.get("excluded_tests")
    ):
        raise RunGateError("flaky-reduced baseline lacks a green execution and excluded tests")
    if set(mutations) != registered or set(mutations) != set(executions):
        raise RunGateError("every reported mutation requires guarded mutation and execution evidence")
    for mutation_id, mutation in mutations.items():
        mutation_executions = executions[mutation_id]
        completed_codes = [
            item.get("returncode") for item in mutation_executions
            if item.get("result", "completed") == "completed"
        ]
        timed_out = any(item.get("result") == "timeout" for item in mutation_executions)
        interpretation = mutation.get("outcome_interpretation", {}).get("kind")
        failed = any(code != 0 for code in completed_codes)
        passed = bool(completed_codes) and all(code == 0 for code in completed_codes)
        if interpretation == "passed" and (timed_out or not passed):
            raise RunGateError(
                f"passed interpretation contradicts raw execution: {mutation_id}"
            )
        if interpretation in {
            "behavioral-failure",
            "infrastructure-failure",
            "process-crash",
            "unparseable",
        } and not failed:
            raise RunGateError(
                f"failure interpretation has no failing execution: {mutation_id}"
            )
        if interpretation == "timeout" and not timed_out:
            raise RunGateError(
                f"timeout interpretation has no timeout execution: {mutation_id}"
            )
        if mutation["result"] == "killed" and not any(code != 0 for code in completed_codes):
            raise RunGateError(f"killed mutation has no failing execution: {mutation_id}")
        if (
            mutation["result"] == "killed"
            and interpretation != "behavioral-failure"
        ):
            raise RunGateError(
                f"killed mutation is not classified as a behavioral failure: {mutation_id}"
            )
        if mutation["result"] == "survived" and (
            timed_out or not completed_codes or any(code != 0 for code in completed_codes)
        ):
            raise RunGateError(f"survived mutation has a failing execution: {mutation_id}")
        if mutation["result"] == "survived" and interpretation != "passed":
            raise RunGateError(
                f"survived mutation is not classified as passed: {mutation_id}"
            )
        if mutation["result"] == "timeout" and not timed_out:
            raise RunGateError(f"timeout mutation has no timeout execution: {mutation_id}")
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


def _record_host_output(
    manifest: dict[str, Any],
    kind: str,
    filename: str,
    content: bytes,
    schema: str,
) -> Path:
    path = Path(manifest["artifact_root"]) / filename
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
    index = _artifact_index(manifest)
    index["artifacts"][kind] = {
        "path": str(path),
        "sha256": _sha256_path(path),
        "schema": schema,
        "host_generated": True,
    }
    _write_index(Path(manifest["artifact_index_path"]), index)
    return path


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


def finish(manifest_path: Path, schema_root: Path | None = None) -> str:
    manifest = _ready_manifest(manifest_path)
    sandbox = Path(manifest["sandbox_root"])
    try:
        documents = _staged_artifacts(manifest)
        ledger = _ledger_events(manifest)
        current_primary_hash = _tree_hash(Path(manifest["primary_root"]))
        if current_primary_hash != manifest["primary_sha256"]:
            raise RunGateError("Primary content hash changed during the Review-only run")
        if sandbox.exists():
            shutil.rmtree(sandbox)
        if sandbox.exists():
            raise RunGateError("disposable sandbox still exists after cleanup")
        report = _attested_report(
            manifest,
            documents["contract"],
            documents["report"],
            ledger,
            manifest_sha256=_sha256_path(manifest_path),
            ledger_head=_ledger_head(manifest),
        )
        finish_document(
            manifest, report, documents["review"], ledger,
            manifest_sha256=_sha256_path(manifest_path), ledger_head=_ledger_head(manifest),
        )
        validator = _validator_module()
        try:
            validator.validate_document(
                documents["contract"], "intent-contract.schema.json", schema_root
            )
            validator.validate_document(
                report, "mutation-report.schema.json", schema_root
            )
            validator.validate_document(
                documents["review"], "canonical-review.schema.json", schema_root
            )
            validator.validate_cross_artifact(documents["contract"], report)
            rendered = validator.render_review(documents["review"])
            report["canonical_output"]["sha256"] = _sha256_bytes(
                rendered.encode("utf-8")
            )
            validator.validate_with_schemas(
                documents["contract"], report, documents["review"], schema_root
            )
        except validator.ArtifactError as error:
            raise RunGateError(str(error)) from error
        _record_host_output(
            manifest,
            "attested-report",
            "mutation-report.attested.json",
            _canonical_bytes(report),
            "mutation-report.schema.json",
        )
        _record_host_output(
            manifest,
            "renderer-output",
            "renderer-output.txt",
            rendered.encode("utf-8"),
            "canonical renderer stdout",
        )
        return rendered
    except BaseException as failure:
        try:
            _record_validation_error(manifest, "finish", str(failure))
        except BaseException:
            pass
        cleanup_errors = _cleanup_loaded(manifest, manifest_path)
        if cleanup_errors:
            raise RunGateError("; ".join(cleanup_errors)) from failure
        raise


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pre = commands.add_parser("preflight")
    pre.add_argument("--primary", required=True, type=Path)
    pre.add_argument("--host-socket", type=Path)
    pre.add_argument("--host-token")
    mutate_parser = commands.add_parser("mutate")
    mutate_parser.add_argument("--manifest", required=True, type=Path)
    mutate_parser.add_argument("--mutation-id", required=True)
    mutate_parser.add_argument("--relative-path", required=True)
    mutate_parser.add_argument("--content-file", required=True, type=Path)
    register_parser = commands.add_parser("register-prebuilt")
    register_parser.add_argument("--manifest", required=True, type=Path)
    register_parser.add_argument("--mutation-id", required=True)
    register_parser.add_argument("--relative-path", required=True)
    execute_parser = commands.add_parser("execute")
    execute_parser.add_argument("--manifest", required=True, type=Path)
    execute_parser.add_argument("--phase", required=True, choices=("baseline", "mutation"))
    execute_parser.add_argument("--mutation-id")
    execute_parser.add_argument("--timeout", type=int, default=120)
    execute_parser.add_argument("argv", nargs=argparse.REMAINDER)
    stage_parser = commands.add_parser("stage-artifact")
    stage_parser.add_argument("--manifest", required=True, type=Path)
    stage_parser.add_argument(
        "--kind", required=True, choices=tuple(ARTIFACT_FILES)
    )
    stage_parser.add_argument("--schema-root", type=Path)
    finish_parser = commands.add_parser("finish")
    finish_parser.add_argument("--manifest", required=True, type=Path)
    finish_parser.add_argument("--schema-root", type=Path)
    cleanup_parser = commands.add_parser("cleanup")
    cleanup_parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "preflight":
        try:
            adapter = (
                ClaudeSocketHostAdapter(args.host_socket, args.host_token)
                if args.host_socket is not None and args.host_token is not None
                else ClaudeSocketHostAdapter.from_environment()
            )
            manifest, manifest_path = preflight_with_host(
                args.primary, adapter
            )
        except RunGateError:
            print(json.dumps(blocked_preflight(args.primary), sort_keys=True))
            return 2
        print(json.dumps({
            "status": "ready", "run_id": manifest["run_id"],
            "manifest_path": str(manifest_path),
            "sandbox_root": manifest["sandbox_root"],
            "artifact_root": manifest["artifact_root"],
            "next": "stage contract, report, and review drafts after guarded executions",
            "allowed_operations": [
                "mutate", "register-prebuilt", "execute", "stage-artifact",
                "finish", "cleanup",
            ],
        }, sort_keys=True))
        return 0
    try:
        if args.command == "mutate":
            mutate(args.manifest, args.mutation_id, args.relative_path, args.content_file.read_bytes())
        elif args.command == "register-prebuilt":
            register_prebuilt(args.manifest, args.mutation_id, args.relative_path)
        elif args.command == "execute":
            if not args.argv:
                raise RunGateError("execute requires a command after --")
            argv = args.argv[1:] if args.argv[0] == "--" else args.argv
            return execute(args.manifest, args.phase, args.mutation_id, argv, args.timeout)
        elif args.command == "stage-artifact":
            print(json.dumps(
                stage_artifact(args.manifest, args.kind, args.schema_root),
                sort_keys=True,
            ))
        elif args.command == "finish":
            sys.stdout.write(finish(args.manifest, args.schema_root))
        elif args.command == "cleanup":
            cleanup(args.manifest)
        return 0
    except (OSError, RunGateError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
