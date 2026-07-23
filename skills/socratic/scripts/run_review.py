#!/usr/bin/env python3
"""Host-gated fail-closed entrypoint for Socratic Review-only mutation runs."""

from __future__ import annotations

import argparse
import concurrent.futures
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
SOCRATIC_VERSION = "0.4.0-alpha.4"
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
    change_context: dict[str, Any] | None = None


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
            change_context=grant.get("change_context"),
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


def _inside(path: Path, root: Path, label: str, *, strict: bool = False) -> Path:
    resolved = path.resolve(strict=strict)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise RunGateError(f"{label} must be inside trusted Host storage: {resolved}") from error
    if resolved == root:
        raise RunGateError(f"{label} cannot be the Host storage root")
    return resolved


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


def _prepared_hash(root: Path) -> str:
    digest = hashlib.sha256()
    ignored = {".git", ".hg", ".svn", ".env", "__pycache__"}
    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False):
        names[:] = sorted(name for name in names if name not in ignored)
        relative_directory = Path(directory).relative_to(root)
        for filename in sorted(filenames):
            if filename in ignored or filename.startswith(".env.") or filename.endswith(".pyc"):
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
    change_context = grant.change_context or {
        "source": "local-workspace",
        "head_root": str(primary_root),
    }
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
        shutil.copytree(primary_root, prepared, symlinks=True, ignore=_ignored)
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
            "status": "ready",
            "write_mode": "review-only",
            "socratic_version": SOCRATIC_VERSION,
            "entrypoint": ENTRYPOINT,
            "skill_root": str(_skills_root()),
            "primary_root": str(primary_root),
            "sandbox_root": str(sandbox.resolve()),
            "prepared_root": str(prepared.resolve()),
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


def _runtime_environment(root: Path) -> dict[str, str]:
    environment_root = root / ".socratic-runtime"
    paths = {
        "HOME": environment_root / "home",
        "TMPDIR": environment_root / "tmp",
        "XDG_CACHE_HOME": environment_root / "cache",
        "npm_config_cache": environment_root / "npm-cache",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return {key: str(path.resolve()) for key, path in paths.items()}


def _prepared_snapshot(manifest: dict[str, Any]) -> dict[str, Any]:
    events = _ledger_events(manifest)
    sealed = [item for item in events if item.get("kind") == "prepared-snapshot"]
    if len(sealed) > 1:
        raise RunGateError("prepared snapshot was sealed more than once")
    if sealed:
        return sealed[0]
    baselines = [
        item for item in events
        if item.get("kind") == "command" and item.get("phase") == "baseline"
    ]
    if not baselines or any(
        item.get("result") != "completed" or item.get("returncode") != 0
        for item in baselines
    ):
        raise RunGateError("a successful baseline must precede prepared snapshot sealing")
    prepared = Path(manifest["prepared_root"])
    event = {
        "run_id": manifest["run_id"],
        "kind": "prepared-snapshot",
        "root": str(prepared),
        "sha256": _prepared_hash(prepared),
        "protection": "host-managed-hash-verified",
    }
    return _append_event(manifest, event)


def _clone_prepared(
    manifest: dict[str, Any], mutation_id: str
) -> tuple[Path, str, str]:
    events = _ledger_events(manifest)
    if any(
        item.get("mutation_id") == mutation_id
        and item.get("kind") in {"guarded-write", "prebuilt"}
        for item in events
    ):
        raise RunGateError(f"mutation already has a sandbox: {mutation_id}")
    snapshot = _prepared_snapshot(manifest)
    prepared = Path(manifest["prepared_root"])
    destination = Path(manifest["sandbox_root"]) / "mutants" / mutation_id
    destination.parent.mkdir(mode=0o700, exist_ok=True)
    if destination.exists():
        raise RunGateError(f"mutation sandbox already exists: {mutation_id}")

    strategy = "full-copy"
    commands: list[list[str]] = []
    if sys.platform == "darwin":
        commands.append(["cp", "-cR", str(prepared), str(destination)])
    elif sys.platform.startswith("linux"):
        commands.append(
            ["cp", "--reflink=always", "-a", str(prepared), str(destination)]
        )
    for command in commands:
        completed = subprocess.run(
            command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if completed.returncode == 0 and destination.is_dir():
            strategy = "copy-on-write"
            break
        shutil.rmtree(destination, ignore_errors=True)
    else:
        shutil.copytree(prepared, destination, symlinks=True)

    (destination / ".socratic-disposable").write_text(
        f"{manifest['run_id']}:{mutation_id}\n", encoding="utf-8"
    )
    runtime = destination / ".socratic-runtime"
    shutil.rmtree(runtime, ignore_errors=True)
    _runtime_environment(destination)
    return destination, strategy, snapshot["sha256"]


def mutate(manifest_path: Path, mutation_id: str, relative_target: str, content: bytes) -> dict[str, Any]:
    manifest = _ready_manifest(manifest_path)
    if not mutation_id.startswith("MUT-") or not mutation_id[4:].isdigit():
        raise RunGateError(f"invalid mutation id: {mutation_id}")
    sandbox, clone_strategy, prepared_sha256 = _clone_prepared(manifest, mutation_id)
    if Path(relative_target).is_absolute() or ".." in Path(relative_target).parts:
        shutil.rmtree(sandbox, ignore_errors=True)
        raise RunGateError("mutation target must be a safe sandbox-relative path")
    isolation = _load_module("socratic_isolation_gate", _skills_root() / "elenchus/scripts/isolation_gate.py")
    try:
        evidence = isolation.IsolationGate(
            Path(manifest["primary_root"]), sandbox
        ).write_bytes(sandbox / relative_target, content)
    except BaseException:
        shutil.rmtree(sandbox, ignore_errors=True)
        raise
    return _append_event(manifest, {
        "run_id": manifest["run_id"], "mutation_id": mutation_id, "kind": "guarded-write",
        "requested_path": relative_target, "resolved_path": evidence.resolved_target,
        "content_sha256": _sha256_bytes(content), "bytes": len(content), "within_sandbox": True,
        "sandbox_root": str(sandbox), "clone_strategy": clone_strategy,
        "prepared_sha256": prepared_sha256,
    })


def register_prebuilt(manifest_path: Path, mutation_id: str, relative_path: str) -> dict[str, Any]:
    manifest = _ready_manifest(manifest_path)
    if not mutation_id.startswith("MUT-") or not mutation_id[4:].isdigit():
        raise RunGateError(f"invalid mutation id: {mutation_id}")
    relative = Path(relative_path)
    sandbox, clone_strategy, prepared_sha256 = _clone_prepared(manifest, mutation_id)
    unresolved = sandbox / relative
    isolation = _load_module("socratic_isolation_gate", _skills_root() / "elenchus/scripts/isolation_gate.py")
    try:
        evidence = isolation.IsolationGate(
            Path(manifest["primary_root"]), sandbox
        ).authorize(unresolved)
        candidate = Path(evidence.resolved_target)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or unresolved.is_symlink()
            or not candidate.is_file()
        ):
            raise RunGateError("prebuilt mutant must be a sandbox-relative regular file")
    except BaseException:
        shutil.rmtree(sandbox, ignore_errors=True)
        raise
    return _append_event(manifest, {
        "run_id": manifest["run_id"], "mutation_id": mutation_id, "kind": "prebuilt",
        "resolved_path": str(candidate), "sha256": _sha256_path(candidate),
        "sandbox_root": str(sandbox), "clone_strategy": clone_strategy,
        "prepared_sha256": prepared_sha256,
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
    ledger = _ledger_events(manifest)
    if phase == "baseline" and any(
        item.get("kind") == "prepared-snapshot" for item in ledger
    ):
        raise RunGateError("baseline cannot run after the prepared snapshot is sealed")
    registrations = {
        item.get("mutation_id"): item for item in ledger
        if item.get("kind") in {"guarded-write", "prebuilt"}
    }
    registered = set(registrations)
    if phase == "mutation" and mutation_id not in registered:
        raise RunGateError(f"mutation execution has no guarded mutation evidence: {mutation_id}")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG"} or key.startswith("LC_")
    }
    execution_root = (
        Path(manifest["prepared_root"])
        if phase == "baseline"
        else Path(registrations[mutation_id]["sandbox_root"])
    )
    runtime_environment = (
        manifest["environment"]
        if phase == "baseline"
        else _runtime_environment(execution_root)
    )
    environment.update(runtime_environment)
    try:
        completed = subprocess.run(
            command, cwd=execution_root, env=environment,
            timeout=timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired as error:
        _append_event(manifest, {
            "run_id": manifest["run_id"], "kind": "command", "phase": phase,
            "mutation_id": mutation_id, "argv": command, "timeout_seconds": timeout_seconds,
            "result": "timeout", "returncode": None,
            "environment": runtime_environment, "sandbox_root": str(execution_root),
        })
        raise RunGateError(f"sandbox command timed out after {timeout_seconds}s") from error
    _append_event(manifest, {
        "run_id": manifest["run_id"], "kind": "command", "phase": phase,
        "mutation_id": mutation_id, "argv": command, "timeout_seconds": timeout_seconds,
        "result": "completed", "returncode": completed.returncode,
        "environment": runtime_environment, "sandbox_root": str(execution_root),
    })
    return completed.returncode


def _batch_command(
    challenge: dict[str, Any],
    registration: dict[str, Any],
    inherited_environment: dict[str, str],
) -> dict[str, Any]:
    sandbox = Path(registration["sandbox_root"])
    runtime_environment = _runtime_environment(sandbox)
    environment = dict(inherited_environment)
    environment.update(runtime_environment)
    command = challenge["command"]
    timeout_seconds = challenge["timeout_seconds"]
    try:
        completed = subprocess.run(
            command,
            cwd=sandbox,
            env=environment,
            timeout=timeout_seconds,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        result = "completed"
        returncode: int | None = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        result = "timeout"
        returncode = None
        stdout = error.stdout or b""
        stderr = error.stderr or b""
    limit = 16 * 1024
    return {
        "mutation_id": challenge["id"],
        "argv": command,
        "timeout_seconds": timeout_seconds,
        "result": result,
        "returncode": returncode,
        "environment": runtime_environment,
        "sandbox_root": str(sandbox),
        "stdout_sha256": _sha256_bytes(stdout),
        "stderr_sha256": _sha256_bytes(stderr),
        "stdout": stdout[-limit:].decode("utf-8", errors="replace"),
        "stderr": stderr[-limit:].decode("utf-8", errors="replace"),
        "output_truncated": len(stdout) > limit or len(stderr) > limit,
    }


def challenge_batch(
    manifest_path: Path, schema_root: Path | None = None
) -> dict[str, Any]:
    manifest = _ready_manifest(manifest_path)
    plan_path = Path(manifest["artifact_root"]) / "challenge-plan.json"
    if (
        not plan_path.is_file()
        or plan_path.is_symlink()
        or plan_path.parent.resolve(strict=True)
        != Path(manifest["artifact_root"]).resolve(strict=True)
    ):
        raise RunGateError("challenge plan is missing from the fixed Host staging path")
    plan = _load_json(plan_path)
    if not isinstance(plan, dict):
        raise RunGateError("challenge plan root must be an object")
    validator = _validator_module()
    try:
        validator.validate_document(plan, "challenge-plan.schema.json", schema_root)
    except validator.ArtifactError as error:
        _record_validation_error(manifest, "challenge-plan", str(error))
        raise RunGateError(str(error)) from error
    ids = [item["id"] for item in plan["challenges"]]
    if len(ids) != len(set(ids)):
        raise RunGateError("challenge plan mutation IDs must be unique")
    existing = {
        item.get("mutation_id")
        for item in _ledger_events(manifest)
        if item.get("kind") in {"guarded-write", "prebuilt"}
    }
    duplicates = sorted(set(ids) & existing)
    if duplicates:
        raise RunGateError(f"challenge plan reuses mutation IDs: {duplicates}")
    plan_sha256 = _sha256_path(plan_path)
    registrations: dict[str, dict[str, Any]] = {}
    for challenge in plan["challenges"]:
        mutation = challenge["mutation"]
        if mutation["kind"] == "write":
            registration = mutate(
                manifest_path,
                challenge["id"],
                mutation["relative_target"],
                mutation["content_utf8"].encode("utf-8"),
            )
        else:
            registration = register_prebuilt(
                manifest_path, challenge["id"], mutation["relative_path"]
            )
        registrations[challenge["id"]] = registration

    inherited_environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG"} or key.startswith("LC_")
    }
    results_by_id: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(plan["max_parallel"], len(plan["challenges"]))
    ) as executor:
        futures = {
            executor.submit(
                _batch_command,
                challenge,
                registrations[challenge["id"]],
                inherited_environment,
            ): challenge["id"]
            for challenge in plan["challenges"]
        }
        for future in concurrent.futures.as_completed(futures):
            mutation_id = futures[future]
            try:
                results_by_id[mutation_id] = future.result()
            except BaseException as error:
                results_by_id[mutation_id] = {
                    "mutation_id": mutation_id,
                    "argv": next(
                        item["command"]
                        for item in plan["challenges"]
                        if item["id"] == mutation_id
                    ),
                    "timeout_seconds": next(
                        item["timeout_seconds"]
                        for item in plan["challenges"]
                        if item["id"] == mutation_id
                    ),
                    "result": "runner-error",
                    "returncode": None,
                    "environment": {},
                    "sandbox_root": registrations[mutation_id]["sandbox_root"],
                    "stdout_sha256": _sha256_bytes(b""),
                    "stderr_sha256": _sha256_bytes(str(error).encode("utf-8")),
                    "stdout": "",
                    "stderr": str(error),
                    "output_truncated": False,
                }

    public_results: list[dict[str, Any]] = []
    for challenge in plan["challenges"]:
        result = results_by_id[challenge["id"]]
        ledger_event = {
            key: value
            for key, value in result.items()
            if key not in {"stdout", "stderr", "output_truncated"}
        }
        ledger_event.update({
            "run_id": manifest["run_id"],
            "kind": "command",
            "phase": "mutation",
            "batch_plan_sha256": plan_sha256,
        })
        _append_event(manifest, ledger_event)
        public_results.append({
            "mutation_id": result["mutation_id"],
            "outcome": (
                "timeout"
                if result["result"] == "timeout"
                else "passed"
                if result["result"] == "completed" and result["returncode"] == 0
                else "failed"
            ),
            "returncode": result["returncode"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "output_truncated": result["output_truncated"],
        })
    return {
        "status": "completed",
        "plan_sha256": plan_sha256,
        "max_parallel": plan["max_parallel"],
        "results": public_results,
    }


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
    prepared_events = [
        item for item in ledger if item.get("kind") == "prepared-snapshot"
    ]
    if len(prepared_events) != 1:
        raise RunGateError("finish requires exactly one sealed prepared snapshot")
    prepared = prepared_events[0]
    clone_events = [
        item for item in registered
        if item.get("sandbox_root") and item.get("clone_strategy")
    ]

    def raw_outcome(item: dict[str, Any]) -> str:
        if item.get("result") == "timeout":
            return "timeout"
        return "passed" if item.get("returncode") == 0 else "failed"

    report = {
        "version": 10,
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
        "change_context": manifest["change_context"],
        "prepared_snapshot": {
            "root": prepared["root"],
            "sha256": prepared["sha256"],
            "protection": prepared["protection"],
            "clones": [
                {
                    "mutation_id": item["mutation_id"],
                    "sandbox_root": item["sandbox_root"],
                    "strategy": item["clone_strategy"],
                }
                for item in sorted(
                    clone_events, key=lambda event: event["mutation_id"]
                )
            ],
        },
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
        runner_failed = any(
            item.get("result") == "runner-error" for item in mutation_executions
        )
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
        } and not (failed or runner_failed):
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
    prepared_events = [
        item for item in ledger if item.get("kind") == "prepared-snapshot"
    ]
    if len(prepared_events) != 1:
        raise RunGateError("report lacks a unique prepared snapshot event")
    prepared_report = report.get("prepared_snapshot", {})
    prepared_event = prepared_events[0]
    expected_prepared = {
        "root": prepared_event["root"],
        "sha256": prepared_event["sha256"],
        "protection": prepared_event["protection"],
        "clones": [
            {
                "mutation_id": item["mutation_id"],
                "sandbox_root": item["sandbox_root"],
                "strategy": item["clone_strategy"],
            }
            for item in sorted(
                [
                    event for event in ledger
                    if event.get("kind") in {"guarded-write", "prebuilt"}
                ],
                key=lambda event: event["mutation_id"],
            )
        ],
    }
    if prepared_report != expected_prepared:
        raise RunGateError("prepared snapshot evidence differs from the Host ledger")


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
        prepared_events = [
            item for item in ledger if item.get("kind") == "prepared-snapshot"
        ]
        if len(prepared_events) != 1 or _prepared_hash(
            Path(manifest["prepared_root"])
        ) != prepared_events[0].get("sha256"):
            raise RunGateError("prepared snapshot changed after it was sealed")
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


def assess_experiment(source_root: Path, plan: Path, evidence: Path) -> dict[str, Any]:
    """Delegate the untrusted prototype path to the typed local-copy Runner."""
    script_root = str(Path(__file__).resolve().parent)
    if script_root not in sys.path:
        sys.path.insert(0, script_root)
    try:
        from run_experiment import assess

        return assess(source_root, plan, evidence)
    except (OSError, ValueError, RuntimeError) as error:
        raise RunGateError(str(error)) from error


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
    batch_parser = commands.add_parser("challenge-batch")
    batch_parser.add_argument("--manifest", required=True, type=Path)
    batch_parser.add_argument("--schema-root", type=Path)
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
    assess_parser = commands.add_parser(
        "assess", help="run the unsigned v0.4 local-copy prototype"
    )
    assess_parser.add_argument("--source-root", required=True, type=Path)
    assess_parser.add_argument("--plan", required=True, type=Path)
    assess_parser.add_argument("--evidence", required=True, type=Path)
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
            "prepared_root": manifest["prepared_root"],
            "artifact_root": manifest["artifact_root"],
            "next": "stage contract, report, and review drafts after guarded executions",
            "allowed_operations": [
                "mutate", "register-prebuilt", "execute", "stage-artifact",
                "challenge-batch", "finish", "cleanup",
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
        elif args.command == "challenge-batch":
            print(json.dumps(
                challenge_batch(args.manifest, args.schema_root), sort_keys=True
            ))
        elif args.command == "stage-artifact":
            print(json.dumps(
                stage_artifact(args.manifest, args.kind, args.schema_root),
                sort_keys=True,
            ))
        elif args.command == "finish":
            sys.stdout.write(finish(args.manifest, args.schema_root))
        elif args.command == "cleanup":
            cleanup(args.manifest)
        elif args.command == "assess":
            print(json.dumps(
                assess_experiment(args.source_root, args.plan, args.evidence),
                sort_keys=True,
            ))
        return 0
    except (OSError, RunGateError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
