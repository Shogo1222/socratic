#!/usr/bin/env python3
"""Host-gated fail-closed entrypoint for Socratic Review-only mutation runs."""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import ctypes
import ctypes.util
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


ENTRYPOINT = "socratic/scripts/run_review.py"
SOCRATIC_VERSION = "0.5.0-beta.1"
MAX_INSPECT_BYTES = 64 * 1024
MAX_INSPECT_MATCHES = 200
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
REVIEW_TYPES = (
    "Bug Fix Review",
    "Feature Review",
    "Refactor Guard",
    "Test Assessment",
)
IGNORED_NAMES = {
    ".git", ".hg", ".svn", ".env", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next", "dist", "build",
}
DEPENDENCY_DIRECTORY_NAMES = {"node_modules"}
VIRTUAL_ENV_DIRECTORY_NAMES = {".venv", "venv"}
NODE_RUNTIME_DIRECTORY_NAMES = {".cache", ".vite", ".vitest"}
RUNTIME_DIRECTORY_NAME = ".socratic-runtime"
SANDBOX_ENV_DEFAULTS = {
    # Sandbox executions are non-interactive, and dependency state is sealed by
    # the prepared snapshot: package managers must neither prompt nor reinstall.
    # pnpm otherwise detects the cloned path change, purges node_modules, and
    # rebuilds dependencies once per mutant clone.
    "CI": "true",
    "npm_config_verify_deps_before_run": "false",
    "PYTHONDONTWRITEBYTECODE": "1",
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
    review_type: dict[str, Any] | None = None


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
            review_type=(
                grant.get("review_context", {}).get("review_type")
                if isinstance(grant.get("review_context"), dict)
                else None
            ),
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


def _safe_relative_path(raw: str) -> Path:
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts or "\\" in raw:
        raise RunGateError("path must be a safe repository-relative path")
    if any(
        part == ".env"
        or part.startswith(".env.")
        or part in {".git", ".hg", ".svn", "node_modules"}
        for part in relative.parts
    ):
        raise RunGateError("path is excluded from Socratic inspection")
    return relative


def _bounded_text(path: Path, *, limit: int = MAX_INSPECT_BYTES) -> str:
    if path.is_symlink() or not path.is_file():
        raise RunGateError(f"inspection target is not a regular file: {path}")
    payload = path.read_bytes()
    if len(payload) > limit:
        raise RunGateError(f"inspection target exceeds {limit} bytes: {path}")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RunGateError(f"inspection target is not UTF-8 text: {path}") from error


def _review_files(root: Path):
    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False):
        names[:] = sorted(
            name
            for name in names
            if name not in IGNORED_NAMES and not name.startswith(".env")
        )
        for filename in sorted(filenames):
            if filename in IGNORED_NAMES or filename.startswith(".env"):
                continue
            path = Path(directory) / filename
            if path.is_file() and not path.is_symlink():
                yield path


def _resolve_inspect_kind(
    kind_flag: str | None, kind_positional: str | None
) -> str:
    """Accept both `inspect diff` and `inspect --kind diff` invocation forms."""
    if kind_flag and kind_positional and kind_flag != kind_positional:
        raise RunGateError(
            f"inspect received two different kinds: --kind {kind_flag} and {kind_positional}"
        )
    kind = kind_flag or kind_positional
    if not kind:
        raise RunGateError(
            "inspect requires a kind: use `inspect diff|file|search|tests` or `inspect --kind diff`"
        )
    return kind


def inspect_review(
    manifest_path: Path,
    kind: str,
    *,
    relative_path: str | None = None,
    query: str | None = None,
    start_line: int = 1,
    end_line: int = 200,
) -> dict[str, Any]:
    """Return bounded, read-only evidence without exposing a general shell."""
    manifest = _ready_manifest(manifest_path)
    change = manifest["change_context"]
    head = Path(change["head_root"]).resolve(strict=True)

    def guided(result: dict[str, Any]) -> dict[str, Any]:
        result["checkpoint"] = {
            "id": "diff-understanding",
            "required_before_next": True,
            "present_in_user_language": [
                "problem",
                "changed_behavior",
                "preserved_behavior",
                "new_observable_behavior",
                "consequential_uncertainty",
            ],
            "accepted_responses": [
                "confirm",
                "correct",
                "defer-to-specification-owner",
                "proceed-from-repository-evidence",
            ],
            "instruction": (
                "Continue bounded inspect calls until the evidence is sufficient. "
                "Then present this checkpoint once and wait for the human response "
                "before running next.argv."
            ),
        }
        result["next"] = _next_step(
            "scaffold-contract", "--manifest", str(manifest_path),
            note=(
                "run only after the Diff understanding checkpoint is answered; "
                "incorporate corrections and fill every replace-me value from evidence"
            ),
        )
        return result

    if kind == "diff":
        if change["source"] != "github-pull-request":
            return guided({
                "kind": "diff",
                "available": False,
                "reason": "local-workspace has no Host-materialized Base snapshot",
                "changed_files": [],
            })
        base = Path(change["base_root"]).resolve(strict=True)
        selected = (
            [_safe_relative_path(relative_path).as_posix()]
            if relative_path
            else list(change.get("changed_files", []))
        )
        chunks: list[str] = []
        truncated = False
        for raw in selected:
            relative = _safe_relative_path(raw)
            before_path = base / relative
            after_path = head / relative
            before = _bounded_text(before_path) if before_path.exists() else ""
            after = _bounded_text(after_path) if after_path.exists() else ""
            diff = "".join(difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{relative.as_posix()}",
                tofile=f"b/{relative.as_posix()}",
            ))
            if sum(len(item.encode("utf-8")) for item in chunks) + len(
                diff.encode("utf-8")
            ) > MAX_INSPECT_BYTES:
                truncated = True
                break
            chunks.append(diff)
        return guided({
            "kind": "diff",
            "available": True,
            "changed_files": selected,
            "text": "".join(chunks),
            "truncated": truncated,
        })
    if kind == "file":
        if not relative_path:
            raise RunGateError("file inspection requires --relative-path")
        relative = _safe_relative_path(relative_path)
        if start_line < 1 or end_line < start_line or end_line - start_line > 400:
            raise RunGateError("file inspection line range is invalid or too large")
        lines = _bounded_text(head / relative).splitlines()
        return guided({
            "kind": "file",
            "path": relative.as_posix(),
            "start_line": start_line,
            "end_line": min(end_line, len(lines)),
            "text": "\n".join(lines[start_line - 1:end_line]),
        })
    if kind == "tests":
        tests: list[str] = []
        for path in _review_files(head):
            if len(tests) >= MAX_INSPECT_MATCHES:
                break
            relative = path.relative_to(head)
            name = path.name.casefold()
            if (
                "test" in relative.parts
                or "tests" in relative.parts
                or re.search(r"(?:^|[._-])(?:test|spec)(?:[._-]|$)", name)
            ):
                tests.append(relative.as_posix())
        return guided({
            "kind": "tests",
            "paths": tests,
            "truncated": len(tests) == MAX_INSPECT_MATCHES,
        })
    if kind == "search":
        if not query or len(query) > 200:
            raise RunGateError("search requires a query of at most 200 characters")
        matches: list[dict[str, Any]] = []
        for path in _review_files(head):
            if len(matches) >= MAX_INSPECT_MATCHES:
                break
            relative = path.relative_to(head)
            try:
                text = _bounded_text(path, limit=1024 * 1024)
            except RunGateError:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if query in line:
                    matches.append({
                        "path": relative.as_posix(),
                        "line": number,
                        "text": line[:1000],
                    })
                    if len(matches) >= MAX_INSPECT_MATCHES:
                        break
        return guided({
            "kind": "search",
            "query": query,
            "matches": matches,
            "truncated": len(matches) == MAX_INSPECT_MATCHES,
        })
    raise RunGateError(f"unsupported inspection kind: {kind}")


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
    """Hash mutable review source without traversing attached dependencies.

    Dependency trees are sealed separately.  Directory symlinks created by
    `_materialize_dependency_layer` are intentionally excluded here so a
    staleness check remains proportional to source size.
    """
    digest = hashlib.sha256()
    ignored = {
        ".git", ".hg", ".svn", ".env", "__pycache__",
        RUNTIME_DIRECTORY_NAME,
    }
    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False):
        names[:] = sorted(
            name
            for name in names
            if name not in ignored
            and name not in DEPENDENCY_DIRECTORY_NAMES
            and not (
                name in VIRTUAL_ENV_DIRECTORY_NAMES
                and (Path(directory) / name / "pyvenv.cfg").is_file()
            )
        )
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


def _dependency_hash(root: Path) -> str:
    """Hash every dependency-layer entry, including node_modules and venvs."""
    digest = hashlib.sha256()
    directories = [root]
    while directories:
        directory = directories.pop()
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode("utf-8") + b"\0")
            if path.is_symlink():
                digest.update(b"symlink\0" + os.readlink(path).encode("utf-8"))
            elif path.is_dir():
                digest.update(b"directory\0")
                directories.append(path)
            elif path.is_file():
                digest.update(b"file\0")
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
            else:
                digest.update(b"other\0")
    return digest.hexdigest()


def _dependency_directories(root: Path) -> list[Path]:
    """Return top-level dependency trees for the shared verified layer."""
    dependencies: list[Path] = []
    for directory, names, _filenames in os.walk(
        root, topdown=True, followlinks=False
    ):
        current = Path(directory)
        kept: list[str] = []
        for name in sorted(names):
            candidate = current / name
            is_dependency = (
                name in DEPENDENCY_DIRECTORY_NAMES
                or (
                    name in VIRTUAL_ENV_DIRECTORY_NAMES
                    and (candidate / "pyvenv.cfg").is_file()
                )
            )
            if is_dependency and not candidate.is_symlink():
                dependencies.append(candidate)
            else:
                kept.append(name)
        names[:] = kept
    return dependencies


def _dependency_layer_event(manifest: dict[str, Any]) -> dict[str, Any] | None:
    events = [
        item
        for item in _ledger_events(manifest)
        if item.get("kind") == "dependency-layer-sealed"
    ]
    if len(events) > 1:
        raise RunGateError("dependency layer was materialized more than once")
    return events[0] if events else None


def _materialize_dependency_layer(
    manifest: dict[str, Any], timings: dict[str, int] | None = None
) -> dict[str, Any]:
    """Move installed dependencies out of the cloned source tree once.

    Each source branch receives stable links to installed packages plus a
    fresh `.socratic-runtime`.  A node_modules attachment is a shallow local
    directory whose installed entries link into the shared layer; this keeps
    runtime caches such as node_modules/.vite private to each branch.  The
    shared layer is content-hashed when created and verified again before
    formal completion.
    """
    materialized = [
        item
        for item in _ledger_events(manifest)
        if item.get("kind") == "dependency-layer-materialized"
    ]
    if len(materialized) > 1:
        raise RunGateError("dependency layer was materialized more than once")
    if materialized:
        return materialized[0]

    measured = timings if timings is not None else {}
    prepared = Path(manifest["prepared_root"])
    dependency_root = Path(manifest["dependency_root"])
    attached: list[str] = []
    with _timed(measured, "dependency_layer_move"):
        trees_root = dependency_root / "trees"
        trees_root.mkdir(parents=True, exist_ok=False)
        for source in _dependency_directories(prepared):
            relative = source.relative_to(prepared)
            destination = trees_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)
            if source.name == "node_modules":
                source.mkdir()
                for entry in sorted(destination.iterdir(), key=lambda item: item.name):
                    if entry.name in NODE_RUNTIME_DIRECTORY_NAMES:
                        continue
                    (source / entry.name).symlink_to(
                        entry, target_is_directory=entry.is_dir()
                    )
            else:
                source.symlink_to(destination, target_is_directory=True)
            attached.append(relative.as_posix())

        runtime_source = prepared / RUNTIME_DIRECTORY_NAME
        runtime_seed = dependency_root / "install-runtime"
        if runtime_source.exists():
            runtime_source.replace(runtime_seed)
        _runtime_environment(prepared)

    event = {
        "run_id": manifest["run_id"],
        "kind": "dependency-layer-materialized",
        "root": str(dependency_root),
        "attached_paths": sorted(attached),
        "protection": "runner-shared-hash-verified",
    }
    return _append_event(manifest, event)


def _seal_dependency_layer(
    manifest: dict[str, Any], timings: dict[str, int] | None = None
) -> dict[str, Any]:
    sealed = _dependency_layer_event(manifest)
    if sealed is not None:
        return sealed
    materialized = _materialize_dependency_layer(manifest, timings)
    measured = timings if timings is not None else {}
    with _timed(measured, "dependency_layer_hash"):
        dependency_sha256 = _dependency_hash(Path(manifest["dependency_root"]))
    return _append_event(
        manifest,
        {
            **materialized,
            "kind": "dependency-layer-sealed",
            "sha256": dependency_sha256,
        },
    )


def _verify_dependency_layer(
    manifest: dict[str, Any], evidence: dict[str, Any]
) -> None:
    dependency_root = Path(manifest["dependency_root"])
    if (
        evidence.get("root") != str(dependency_root)
        or evidence.get("protection") != "runner-shared-hash-verified"
        or _dependency_hash(dependency_root) != evidence.get("sha256")
    ):
        raise RunGateError("shared dependency layer changed after it was sealed")


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
    resolved = {key: str(path.resolve()) for key, path in paths.items()}
    resolved.update(SANDBOX_ENV_DEFAULTS)
    return resolved


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
    dependency = _dependency_layer_event(manifest)
    if dependency is None:
        dependency = _seal_dependency_layer(manifest)
    event = {
        "run_id": manifest["run_id"],
        "kind": "prepared-snapshot",
        "root": str(prepared),
        "sha256": _prepared_hash(prepared),
        "protection": "host-managed-hash-verified",
        "dependency_layer": {
            key: dependency[key]
            for key in ("root", "sha256", "attached_paths", "protection")
        },
    }
    return _append_event(manifest, event)


def _next_step(*arguments: str, note: str | None = None) -> dict[str, Any]:
    """Exact argv for the next pipeline step. Agents run it verbatim.

    Placeholders in angle brackets mark the only parts an agent supplies;
    everything else must not be guessed or reordered.
    """
    announcements = {
        "runbook": "Explaining the review plan",
        "inspect": "Reviewing what changed",
        "scaffold-contract": "Establishing the intended behavior",
        "stage-artifact": "Validating the intended behavior",
        "execute": "Preparing the isolated test environment",
        "probe-command": "Running the current tests",
        "scaffold-plan": "Designing realistic accident patterns",
        "challenge-batch": "Verifying the accident patterns",
        "scaffold-analysis": "Interpreting what the tests protect",
        "complete": "Assembling the verified review and cleaning up",
    }
    step: dict[str, Any] = {
        "argv": [sys.executable, str(Path(__file__).resolve()), *arguments],
        "announce": announcements.get(
            arguments[0] if arguments else "", "Continuing the verified review"
        ),
    }
    if note:
        step["note"] = note
    return step


SCAFFOLD_EDITABLE_FIELDS = {
    "contract": [
        "status",
        "change.base", "change.head", "change.summary",
        "intent.statement", "intent.confidence", "intent.evidence[*]",
        "decisions[*]", "invariants[*]",
        "side_effects.required[*]", "side_effects.prohibited[*]",
        "unresolved[*]", "coverage[*]",
    ],
    "plan": [
        "max_parallel",
        "challenges[*].id", "challenges[*].contract_ids",
        "challenges[*].accident", "challenges[*].expected_detection",
        "challenges[*].severity", "challenges[*].likelihood",
        "challenges[*].code_location", "challenges[*].mutation",
    ],
    "analysis": [
        "stable_tests[*]",
        "excluded_tests[*]",
        "assessment",
        "classifications[*].source_intent",
        "classifications[*].changed_intent",
        "classifications[*].result",
        "classifications[*].detecting_tests",
        "classifications[*].observed_failure_reason",
        "classifications[*].contract_violation_observed",
        "classifications[*].follow_up",
        "classifications[*].outcome_interpretation",
        "classifications[*].equivalence_evidence",
        "classifications[*].catch",
        "not_challenged[*]",
        "test_changes[*]",
        "test_handoff",
        "persistent_side_effects",
        "review.review_this[*]",
        "review.we_verified[*]",
        "review.still_at_risk[*]",
        "review.copy_ready_comments[*]",
    ],
}

SCAFFOLD_FIELD_GUIDES = {
    "contract": {
        "status": {
            "allowed": [
                "provisional", "needs-decision", "confirmed",
                "tested", "challenged", "hardened",
            ],
            "rule": (
                "Use needs-decision exactly when unresolved has an item; a "
                "resolved pre-test Contract normally remains provisional or confirmed."
            ),
        },
        "intent.confidence": {"allowed": ["high", "medium", "low"]},
        "intent.evidence[*]": {
            "required_keys": ["source", "supports"],
            "template": {
                "source": "path/to/repository-evidence",
                "supports": "What this evidence establishes",
            },
        },
        "decisions[*]": {
            "required_keys": ["id", "question", "expected", "provenance"],
            "allowed_provenance": [
                "user-confirmed",
                "repository-established",
                "reviewer-selected-benchmark-assumption",
            ],
            "template": {
                "id": "DEC-001",
                "question": "What observable behavior is expected?",
                "expected": "Describe the expected observable behavior",
                "provenance": "repository-established",
            },
        },
        "invariants[*]": {
            "required_keys": ["id", "statement", "severity"],
            "allowed_severity": ["critical", "high", "medium", "low"],
            "template": {
                "id": "INV-001",
                "statement": "Describe behavior that must remain unchanged",
                "severity": "high",
            },
        },
        "side_effects.required[*]": {
            "required_keys": ["id", "statement"],
            "template": {
                "id": "FX-001",
                "statement": "Describe a required observable side effect",
            },
        },
        "side_effects.prohibited[*]": {
            "required_keys": ["id", "statement"],
            "template": {
                "id": "FX-002",
                "statement": "Describe a prohibited observable side effect",
            },
        },
        "unresolved[*]": {
            "required_keys": ["id", "statement", "test_impact"],
            "optional_keys": ["blocked_contract_ids"],
            "rule": (
                "Adding an item requires status=needs-decision. Include "
                "blocked_contract_ids when the affected DEC/INV/FX IDs are known."
            ),
            "template": {
                "id": "UNR-001",
                "statement": "Describe the unresolved observable decision",
                "test_impact": "Explain how the answer changes the oracle",
                "blocked_contract_ids": ["DEC-001"],
            },
        },
        "coverage[*]": {
            "required_keys": ["contract_id", "tests"],
            "rule": "tests is a non-empty array of test names or paths, never a disposition object.",
            "template": {
                "contract_id": "DEC-001",
                "tests": ["path/to/test: test name"],
            },
        },
    },
    "plan": {
        "max_parallel": {"type": "integer", "minimum": 1, "maximum": 8},
        "challenges[*]": {
            "required_keys": [
                "id", "contract_ids", "accident", "expected_detection",
                "severity", "likelihood", "code_location", "mutation",
            ],
            "allowed_severity": ["low", "medium", "high", "critical"],
            "allowed_likelihood": ["low", "medium", "high"],
            "rule": (
                "contract_ids is a non-empty DEC/INV/FX array. Use only an "
                "exact anchored mutation; never embed a full source file."
            ),
        },
        "challenges[*].mutation": {
            "variants": {
                "replace-exact": {
                    "required_keys": ["kind", "relative_path", "before", "after"],
                    "template": {
                        "kind": "replace-exact",
                        "relative_path": "path/to/source",
                        "before": "exact unique source anchor",
                        "after": "mutated source anchor",
                    },
                },
                "delete-exact": {
                    "required_keys": ["kind", "relative_path", "before"],
                    "template": {
                        "kind": "delete-exact",
                        "relative_path": "path/to/source",
                        "before": "exact unique source anchor",
                    },
                },
            },
        },
    },
    "analysis": {
        "stable_tests[*]": {"item_type": "non-empty string"},
        "excluded_tests[*]": {"item_type": "non-empty string"},
        "assessment": {
            "rule": (
                "Required as an object in assessment mode; leave null in harden "
                "or catch unless a cohort comparison is being reported."
            ),
            "required_keys": [
                "selected_scope", "selection_reason", "production_files",
                "existing_tests", "changed_tests", "excluded_scope", "comparisons",
            ],
            "allowed_selected_scope": [
                "current-change", "changed-tests", "broader-target",
            ],
            "comparison_required_keys": [
                "mutation_id", "existing_result", "changed_result", "classification",
            ],
            "allowed_comparison_results": [
                "killed", "survived", "not-run", "not-comparable", "inconclusive",
            ],
            "allowed_comparison_classification": [
                "existing-protection", "incremental-protection",
                "protection-regression", "unprotected",
                "not-comparable", "inconclusive",
            ],
            "comparison_template": {
                "mutation_id": "MUT-001",
                "existing_result": "not-run",
                "changed_result": "killed",
                "classification": "incremental-protection",
            },
        },
        "classifications[*]": {
            "runner_created": True,
            "allowed_result": [
                "killed", "survived", "timeout", "invalid", "equivalent",
                "inconclusive", "weak-catch", "strong-catch",
                "false-positive", "not-comparable", "no-catch",
            ],
            "allowed_follow_up": [
                "none", "harden-test", "clarify-intent",
                "replace-mutant", "investigate-flake", "fix-infrastructure",
            ],
            "allowed_outcome_kind": [
                "passed", "behavioral-failure", "infrastructure-failure",
                "process-crash", "timeout", "unparseable",
            ],
            "rules": [
                "killed requires outcome kind behavioral-failure, at least one detecting test, and contract_violation_observed=true",
                "survived requires outcome kind passed",
                "timeout requires outcome kind timeout",
                "inconclusive uses infrastructure-failure, process-crash, timeout, or unparseable",
                "equivalent requires equivalence_evidence",
            ],
        },
        "classifications[*].catch": {
            "required_in_mode": "catch",
            "allowed_outcome": ["pass", "fail", "not-runnable"],
            "allowed_human_verdict": [
                "intended", "unintended", "unanswered", "not-requested",
            ],
            "template": {
                "parent_outcome": "not-runnable",
                "mutant_outcome": "not-runnable",
                "change_outcome": "not-runnable",
                "human_verdict": "unanswered",
            },
        },
        "not_challenged[*]": {
            "required_keys": ["contract_id", "reason", "residual_risk"],
            "allowed_reason": [
                "budget", "not-observable", "not-applicable", "deferred", "blocked",
            ],
            "template": {
                "contract_id": "INV-001",
                "reason": "not-applicable",
                "residual_risk": "Describe what remains unverified",
            },
        },
        "test_changes[*]": {
            "required_keys": ["name", "disposition"],
            "allowed_disposition": ["existing", "proposed"],
            "template": {
                "name": "path/to/test: test name",
                "disposition": "existing",
            },
        },
        "test_handoff": {
            "rule": (
                "Leave null in Review-only unless the Runner produced a Proven "
                "Test Handoff through an explicitly authorized test-change workflow."
            ),
        },
        "persistent_side_effects": {
            "rule": (
                "Keep authorization=not-requested and writes=[] unless the human "
                "separately authorized a persistent memory/profile/learning write."
            ),
        },
        "review.review_this[*]": {
            "required_keys": ["kind", "body", "contract_ids"],
            "allowed_kind": [
                "confirmed-behavior", "behavior-difference",
                "test-gap", "needs-decision",
            ],
            "template": {
                "kind": "test-gap",
                "body": "Describe the reviewer decision or gap",
                "contract_ids": ["INV-001"],
            },
        },
        "review.we_verified[*]": {"item_type": "non-empty string"},
        "review.still_at_risk[*]": {"item_type": "non-empty string"},
        "review.copy_ready_comments[*]": {
            "required_keys": ["tag", "file", "line", "body", "evidence"],
            "allowed_tag": ["Intent decision", "Behavior difference", "Test gap"],
            "maximum_items": 3,
            "template": {
                "tag": "Test gap",
                "file": "path/to/source",
                "line": 1,
                "body": "Copy-ready review comment",
                "evidence": "Repository or mutation evidence supporting the comment",
            },
        },
    },
}


def runbook(manifest_path: Path) -> dict[str, Any]:
    """One document that explains the whole run: read once after preflight.

    Generated from the loaded Runner so it cannot drift from the version that
    actually executes. It explains meaning and order, never raw JSON Schema.
    """
    manifest = _ready_manifest(manifest_path)
    m = str(manifest_path)
    review_type = manifest.get("review_type") or {
        "recommended": None,
        "options": list(REVIEW_TYPES),
        "requires_human_confirmation": True,
    }
    return {
        "socratic_version": SOCRATIC_VERSION,
        "run_id": manifest["run_id"],
        "mission": (
            "Infer intended observable behavior from repository evidence, expose "
            "only consequential uncertainty, and design realistic accidents that "
            "test whether the suite protects that intent. The Runner owns "
            "commands, mutation mechanics, JSON structure, hashes, ledgers, "
            "reports, and cleanup."
        ),
        "id_glossary": {
            "DEC": "a settled decision about expected observable behavior",
            "INV": "existing behavior that must not break after the change",
            "FX": "a side effect that is required or prohibited",
            "UNR": "an open question repository evidence cannot settle; blocks its mutations",
            "CMD": "a focused test command the Runner probed successfully and will reuse",
            "MUT": "one realistic accident model injected into a disposable clone",
        },
        "gates": [
            "unresolved UNR present -> Contract status needs-decision; mutations for its Contract IDs stay blocked",
            "Contract staged and resolved -> probe the focused command",
            "probe success -> CMD issued; scaffold the challenge plan",
            "challenge-batch complete -> scaffold the analysis and interpret raw outcomes",
            "classification complete -> complete generates, renders, and cleans up",
        ],
        "agent_edits": [
            "intent", "decisions", "invariants", "side effects",
            "accident models", "classification reasons", "detecting tests",
            "reviewer-facing claims",
        ],
        "runner_owns": [
            "JSON structure", "command IDs", "run identity", "hashes",
            "ledger", "attestation", "report mechanics", "cleanup",
        ],
        "hard_rules": [
            "run every Runner command synchronously in the foreground; never background one",
            "never read schema files; every JSON starts from a Runner scaffold and follows its field_guide",
            "follow next.argv verbatim; never guess or reorder arguments",
            "do not delegate deterministic discovery to subagents",
            "one challenge-batch per run",
            "present the renderer output verbatim; never translate, summarize, or append",
        ],
        "execution_plan": [
            {"id": "inspect", "label": "Review what changed"},
            {"id": "intent", "label": "Establish the intent and the behavior to protect"},
            {"id": "prepare", "label": "Prepare the isolated test environment"},
            {"id": "baseline", "label": "Run the current tests"},
            {"id": "challenge", "label": "Verify realistic accident patterns"},
            {"id": "report", "label": "Assemble the verified review"},
            {"id": "cleanup", "label": "Remove the disposable environment"},
        ],
        "announcement_rules": [
            "before the first step, show the execution plan to the user in their language",
            "before each next.argv, translate next.announce into the user's language",
            "if one phase exceeds 30 seconds, say why and report elapsed time",
            "never show an unfounded percentage",
        ],
        "checkpoint": {
            "id": "review-type",
            "required_before_next": True,
            "recommended": review_type["recommended"],
            "options": review_type["options"],
            "instruction": (
                "State the Mission and execution plan in the user's language, "
                "then obtain confirmation or correction of the Host-recommended "
                "Review Type before running next.argv. A null recommendation means "
                "the Host supplied no routing hint, so ask the human to select one."
            ),
        },
        "next": _next_step(
            "inspect", "--manifest", m, "--kind", "diff",
            note=(
                "run after Review Type confirmation; use further bounded inspect "
                "calls if needed, then complete the Diff understanding checkpoint"
            ),
        ),
    }


def _probe_next(manifest_path: Path) -> dict[str, Any]:
    return _next_step(
        "probe-command", "--manifest", str(manifest_path),
        "--command-id", "CMD-001",
        "--cwd", "<package-directory-or-dot>",
        "--", "<focused-test-argv>",
        note=(
            "replace placeholders with the package directory (or .) and direct "
            "test executable located via inspect search; never use a "
            "package-manager wrapper"
        ),
    )


@contextlib.contextmanager
def _timed(timings: dict, label: str):
    """Accumulate wall-clock milliseconds for a Runner-internal segment.

    Ledger command events record external subprocess time only; Runner
    overhead (content hashing, clone creation, sandbox removal, validation)
    was invisible in every report. Timings stay out of the hash-chained
    ledger: they are exposed through public command results and stderr.
    """
    started = time.monotonic()
    try:
        yield
    finally:
        timings[label] = timings.get(label, 0) + max(
            0, round((time.monotonic() - started) * 1000)
        )


def _emit_runner_timings(phase: str, timings: dict) -> None:
    print(
        json.dumps({"runner_timings_ms": {"phase": phase, **timings}}, sort_keys=True),
        file=sys.stderr,
    )


def _copy_prepared(prepared: Path, destination: Path) -> str:
    """Create one disposable source branch, preferring filesystem copy-on-write.

    Installed dependencies have already been replaced by stable symlinks into
    one Runner-owned dependency layer. Only source, configuration, those
    symlinks, and a fresh runtime skeleton are cloned per mutant.

    On APFS clonefile(2) still avoids copying source file data. More
    importantly, it no longer traverses node_modules or virtual environments.
    """
    destination.parent.mkdir(mode=0o700, exist_ok=True)
    if destination.exists():
        raise RunGateError(f"disposable clone already exists: {destination.name}")

    if sys.platform == "darwin":
        try:
            libsystem = ctypes.CDLL(ctypes.util.find_library("System"), use_errno=True)
            if libsystem.clonefile(
                os.fsencode(prepared), os.fsencode(destination), 0
            ) == 0:
                return "kernel-clone"
        except (OSError, AttributeError, TypeError):
            pass
        shutil.rmtree(destination, ignore_errors=True)

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
    return strategy


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
    strategy = _copy_prepared(prepared, destination)

    (destination / ".socratic-disposable").write_text(
        f"{manifest['run_id']}:{mutation_id}\n", encoding="utf-8"
    )
    # Runtime/cache paths stay private even though dependency code is shared.
    _runtime_environment(destination)
    return destination, strategy, snapshot["sha256"]


def _authorize_contract_challenge(
    manifest: dict[str, Any], contract_ids: list[str]
) -> None:
    index = _artifact_index(manifest)
    record = index["artifacts"].get("contract")
    path = Path(manifest["artifact_root"]) / ARTIFACT_FILES["contract"]
    if (
        not record
        or record.get("path") != str(path)
        or record.get("sha256") != _sha256_path(path)
    ):
        raise RunGateError(
            "Intent Contract must be validated and staged before mutation"
        )
    contract = _load_json(path)
    if not isinstance(contract, dict):
        raise RunGateError("staged Intent Contract is invalid")
    validator = _validator_module()
    try:
        validator.assert_elenchus_allowed(contract, contract_ids)
    except validator.ArtifactError as error:
        raise RunGateError(str(error)) from error


def mutate(
    manifest_path: Path,
    mutation_id: str,
    contract_ids: list[str],
    relative_target: str,
    content: bytes,
) -> dict[str, Any]:
    manifest = _ready_manifest(manifest_path)
    _authorize_contract_challenge(manifest, contract_ids)
    if not mutation_id.startswith("MUT-") or not mutation_id[4:].isdigit():
        raise RunGateError(
            f"invalid mutation id: {mutation_id}; expected MUT-<digits>, e.g. MUT-001"
        )
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


def _anchored_postimage(root: Path, mutation: dict[str, Any]) -> tuple[str, bytes]:
    relative = _safe_relative_path(mutation["relative_path"])
    target = root / relative
    original = _bounded_text(target, limit=2 * 1024 * 1024)
    before = mutation["before"]
    if original.count(before) != 1:
        raise RunGateError(
            f"{mutation['kind']} requires exactly one anchor match: {relative}"
        )
    after = mutation.get("after", "")
    changed = original.replace(before, after, 1)
    return relative.as_posix(), changed.encode("utf-8")


def mutate_anchored(
    manifest_path: Path,
    mutation_id: str,
    contract_ids: list[str],
    mutation: dict[str, Any],
) -> dict[str, Any]:
    """Apply a bounded exact edit without accepting a caller-built full file."""
    manifest = _ready_manifest(manifest_path)
    _authorize_contract_challenge(manifest, contract_ids)
    if not mutation_id.startswith("MUT-") or not mutation_id[4:].isdigit():
        raise RunGateError(
            f"invalid mutation id: {mutation_id}; expected MUT-<digits>, e.g. MUT-001"
        )
    relative_target, content = _anchored_postimage(
        Path(manifest["prepared_root"]), mutation
    )
    sandbox, clone_strategy, prepared_sha256 = _clone_prepared(
        manifest, mutation_id
    )
    isolation = _load_module(
        "socratic_isolation_gate",
        _skills_root() / "elenchus/scripts/isolation_gate.py",
    )
    try:
        evidence = isolation.IsolationGate(
            Path(manifest["primary_root"]), sandbox
        ).write_bytes(sandbox / relative_target, content)
    except BaseException:
        shutil.rmtree(sandbox, ignore_errors=True)
        raise
    return _append_event(manifest, {
        "run_id": manifest["run_id"],
        "mutation_id": mutation_id,
        "kind": "guarded-write",
        "requested_path": relative_target,
        "resolved_path": evidence.resolved_target,
        "content_sha256": _sha256_bytes(content),
        "bytes": len(content),
        "within_sandbox": True,
        "sandbox_root": str(sandbox),
        "clone_strategy": clone_strategy,
        "prepared_sha256": prepared_sha256,
        "operation": mutation["kind"],
        "anchor_sha256": _sha256_bytes(mutation["before"].encode("utf-8")),
    })


def register_prebuilt(
    manifest_path: Path,
    mutation_id: str,
    contract_ids: list[str],
    relative_path: str,
) -> dict[str, Any]:
    manifest = _ready_manifest(manifest_path)
    _authorize_contract_challenge(manifest, contract_ids)
    if not mutation_id.startswith("MUT-") or not mutation_id[4:].isdigit():
        raise RunGateError(
            f"invalid mutation id: {mutation_id}; expected MUT-<digits>, e.g. MUT-001"
        )
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
    cwd_relative: str | None = None,
) -> int:
    manifest = _ready_manifest(manifest_path)
    if phase not in {"prepare", "baseline", "mutation"}:
        raise RunGateError("execute phase must be prepare, baseline, or mutation")
    if phase in {"prepare", "baseline"} and mutation_id is not None:
        raise RunGateError(f"{phase} execution must not have a mutation id")
    if phase == "mutation" and mutation_id is None:
        raise RunGateError("mutation execution requires --mutation-id")
    if not command:
        raise RunGateError("sandbox command must not be empty")
    ledger = _ledger_events(manifest)
    if phase in {"prepare", "baseline"} and any(
        item.get("kind") == "prepared-snapshot" for item in ledger
    ):
        raise RunGateError(f"{phase} cannot run after the prepared snapshot is sealed")
    if phase == "prepare" and any(
        item.get("kind") == "validated-command" for item in ledger
    ):
        raise RunGateError("prepare cannot run after a command has been validated")
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
        if phase in {"prepare", "baseline"}
        else Path(registrations[mutation_id]["sandbox_root"])
    )
    runtime_environment = (
        {**manifest["environment"], **SANDBOX_ENV_DEFAULTS}
        if phase == "baseline"
        else _runtime_environment(execution_root)
    )
    environment.update(runtime_environment)
    if phase == "mutation":
        _verify_registered_content(registrations, mutation_id)
    try:
        started = time.monotonic()
        completed = _run_sandboxed(
            command, cwd=_execution_cwd(execution_root, cwd_relative),
            env=environment, timeout_seconds=timeout_seconds, capture=False,
        )
    except subprocess.TimeoutExpired as error:
        _append_event(manifest, {
            "run_id": manifest["run_id"], "kind": "command", "phase": phase,
            "mutation_id": mutation_id, "argv": command, "cwd": cwd_relative,
            "timeout_seconds": timeout_seconds,
            "result": "timeout", "returncode": None,
            "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
            "environment": runtime_environment, "sandbox_root": str(execution_root),
        })
        raise RunGateError(f"sandbox command timed out after {timeout_seconds}s") from error
    _append_event(manifest, {
        "run_id": manifest["run_id"], "kind": "command", "phase": phase,
        "mutation_id": mutation_id, "argv": command, "cwd": cwd_relative,
        "timeout_seconds": timeout_seconds,
        "result": "completed", "returncode": completed.returncode,
        "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
        "environment": runtime_environment, "sandbox_root": str(execution_root),
    })
    return completed.returncode


def _run_sandboxed(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
    capture: bool,
) -> subprocess.CompletedProcess[bytes]:
    """Run a sandbox command in its own session and kill the whole group on timeout.

    subprocess.run's timeout kills only the direct child: a test-runner worker
    that survives keeps running as an orphan, and a grandchild holding the
    stdout pipe hangs the Runner forever.
    """
    pipe = subprocess.PIPE if capture else None
    process = subprocess.Popen(
        command, cwd=cwd, env=env, stdout=pipe, stderr=pipe,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            command, timeout_seconds, output=stdout, stderr=stderr
        )
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _verify_registered_content(
    registrations: dict[Any, dict[str, Any]], mutation_id: str | None
) -> None:
    """Require the mutant file to still match its guarded ledger evidence."""
    registration = registrations.get(mutation_id, {})
    recorded = registration.get("content_sha256") or registration.get("sha256")
    target = Path(str(registration.get("resolved_path", "")))
    if not recorded or not target.is_file() or _sha256_path(target) != recorded:
        raise RunGateError(
            f"mutation sandbox content no longer matches its guarded evidence: {mutation_id}"
        )


def _execution_cwd(root: Path, cwd_relative: str | None) -> Path:
    """Resolve a validated working directory for sandbox command execution.

    Package-manager wrappers re-resolve workspace paths in clones and
    reinstall dependencies; running the direct test binary from the package
    directory avoids that, so probes and batch executions accept a
    sandbox-relative cwd.
    """
    if cwd_relative is None:
        return root
    relative = _safe_relative_path(cwd_relative)
    cwd = root / relative
    if not cwd.is_dir() or cwd.is_symlink():
        raise RunGateError(f"execution cwd must be a directory inside the sandbox: {cwd_relative}")
    if not cwd.resolve().is_relative_to(root.resolve()):
        raise RunGateError(f"execution cwd escapes the sandbox: {cwd_relative}")
    return cwd


def probe_command(
    manifest_path: Path,
    command_id: str,
    command: list[str],
    timeout_seconds: int,
    cwd_relative: str | None = None,
) -> dict[str, Any]:
    """Validate a focused test command in a fresh clone before issuing Mutation IDs."""
    manifest = _ready_manifest(manifest_path)
    if not re.fullmatch(r"CMD-[0-9]{3,}", command_id):
        raise RunGateError(
            f"invalid command id: {command_id}; expected CMD-<three or more digits>, e.g. --command-id CMD-001"
        )
    if not command:
        raise RunGateError("probe command must not be empty")
    events = _ledger_events(manifest)
    if any(
        item.get("kind") == "validated-command"
        and item.get("command_id") == command_id
        for item in events
    ):
        raise RunGateError(f"command id is already validated: {command_id}")
    if any(item.get("kind") == "prepared-snapshot" for item in events):
        raise RunGateError("command probe must run before the prepared snapshot is sealed")

    prepared = Path(manifest["prepared_root"])
    _execution_cwd(prepared, cwd_relative)
    runner_timings: dict[str, int] = {}
    _materialize_dependency_layer(manifest, runner_timings)
    with _timed(runner_timings, "source_snapshot_hash"):
        prepared_sha256 = _prepared_hash(prepared)
    probe_root = Path(manifest["sandbox_root"]) / "command-probes" / command_id
    with _timed(runner_timings, "clone"):
        strategy = _copy_prepared(prepared, probe_root)
    runtime_environment = _runtime_environment(probe_root)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG"} or key.startswith("LC_")
    }
    environment.update(runtime_environment)
    started = time.monotonic()
    try:
        completed = _run_sandboxed(
            command,
            cwd=_execution_cwd(probe_root, cwd_relative),
            env=environment,
            timeout_seconds=timeout_seconds,
            capture=True,
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
    except OSError as error:
        result = "runner-error"
        returncode = None
        stdout = b""
        stderr = str(error).encode("utf-8")
    finally:
        duration_ms = max(0, round((time.monotonic() - started) * 1000))

    event = {
        "run_id": manifest["run_id"],
        "kind": "command-probe",
        "command_id": command_id,
        "argv": command,
        "cwd": cwd_relative,
        "timeout_seconds": timeout_seconds,
        "result": result,
        "returncode": returncode,
        "duration_ms": duration_ms,
        "environment": runtime_environment,
        "sandbox_root": str(probe_root),
        "clone_strategy": strategy,
        "stdout_sha256": _sha256_bytes(stdout),
        "stderr_sha256": _sha256_bytes(stderr),
    }
    try:
        _append_event(manifest, event)
        if result == "completed" and returncode == 0:
            # The probe may legitimately warm dependency-owned tool caches. Seal
            # the shared layer only after that baseline behavior has completed.
            _seal_dependency_layer(manifest, runner_timings)
        limit = 16 * 1024
        public = {
            "status": "ready" if result == "completed" and returncode == 0 else "blocked",
            "command_id": command_id,
            "outcome": (
                "passed"
                if result == "completed" and returncode == 0
                else "timeout"
                if result == "timeout"
                else "infrastructure-failure"
            ),
            "returncode": returncode,
            "duration_ms": duration_ms,
            "runner_timings_ms": {**runner_timings, "external_command": duration_ms},
            "stdout": stdout[-limit:].decode("utf-8", errors="replace"),
            "stderr": stderr[-limit:].decode("utf-8", errors="replace"),
            "output_truncated": len(stdout) > limit or len(stderr) > limit,
        }
        if public["status"] == "ready":
            public["next"] = _next_step(
                "scaffold-plan", "--manifest", str(manifest_path),
                note="the plan binds this validated command; fill the challenges, then follow next.argv",
            )
        else:
            public["next"] = _next_step(
                "probe-command", "--manifest", str(manifest_path),
                "--command-id", command_id, "--", "<corrected-focused-argv>",
                note=(
                    "the probe did not pass; inspect stdout and stderr above, fix "
                    "the focused command or its cwd, then probe again"
                ),
            )
        if public["status"] == "ready":
            _append_event(manifest, {
                "run_id": manifest["run_id"],
                "kind": "validated-command",
                "command_id": command_id,
                "argv": command,
                "cwd": cwd_relative,
                "timeout_seconds": timeout_seconds,
                "probe_duration_ms": duration_ms,
                "clone_strategy": strategy,
                "prepared_sha256": prepared_sha256,
            })
            _append_event(manifest, {
                "run_id": manifest["run_id"],
                "kind": "command",
                "phase": "baseline",
                "mutation_id": None,
                "argv": command,
                "cwd": cwd_relative,
                "timeout_seconds": timeout_seconds,
                "result": "completed",
                "returncode": 0,
                "duration_ms": duration_ms,
                "environment": runtime_environment,
                "sandbox_root": str(probe_root),
                "command_id": command_id,
            })
    finally:
        shutil.rmtree(probe_root, ignore_errors=True)
    return public


def _validated_command(
    manifest: dict[str, Any], command_id: str
) -> dict[str, Any]:
    matches = [
        item for item in _ledger_events(manifest)
        if item.get("kind") == "validated-command"
        and item.get("command_id") == command_id
    ]
    if len(matches) != 1:
        raise RunGateError(
            f"challenge plan requires one successful command probe: {command_id}"
        )
    record = matches[0]
    if record.get("prepared_sha256") != _prepared_hash(
        Path(manifest["prepared_root"])
    ):
        raise RunGateError(
            f"validated command is stale for the prepared snapshot: {command_id}"
        )
    return record


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
    _verify_registered_content({challenge["id"]: registration}, challenge["id"])
    started = time.monotonic()
    try:
        completed = _run_sandboxed(
            command,
            cwd=_execution_cwd(sandbox, challenge.get("cwd")),
            env=environment,
            timeout_seconds=timeout_seconds,
            capture=True,
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
        "cwd": challenge.get("cwd"),
        "timeout_seconds": timeout_seconds,
        "result": result,
        "returncode": returncode,
        "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
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
    runner_timings: dict[str, int] = {}
    with _timed(runner_timings, "staleness_source_hash"):
        command_record = _validated_command(manifest, plan["command_id"])
    for challenge in plan["challenges"]:
        _authorize_contract_challenge(manifest, challenge["contract_ids"])
        _anchored_postimage(Path(manifest["prepared_root"]), challenge["mutation"])
    plan_sha256 = _sha256_path(plan_path)
    registrations: dict[str, dict[str, Any]] = {}
    with _timed(runner_timings, "clones"):
        for challenge in plan["challenges"]:
            runtime_challenge = dict(challenge)
            runtime_challenge["command"] = command_record["argv"]
            runtime_challenge["cwd"] = command_record.get("cwd")
            runtime_challenge["timeout_seconds"] = command_record["timeout_seconds"]
            challenge["_runtime"] = runtime_challenge
            registration = mutate_anchored(
                manifest_path,
                challenge["id"],
                challenge["contract_ids"],
                challenge["mutation"],
            )
            registrations[challenge["id"]] = registration

    inherited_environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG"} or key.startswith("LC_")
    }
    results_by_id: dict[str, dict[str, Any]] = {}
    execution_started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(plan["max_parallel"], len(plan["challenges"]))
    ) as executor:
        futures = {
            executor.submit(
                _batch_command,
                challenge["_runtime"],
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
                        item["_runtime"]["command"]
                        for item in plan["challenges"]
                        if item["id"] == mutation_id
                    ),
                    "timeout_seconds": next(
                        item["_runtime"]["timeout_seconds"]
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
    detailed_results: list[dict[str, Any]] = []
    tail_limit = 2000
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
        outcome = (
            "runner-error"
            if result["result"] == "runner-error"
            else
            "timeout"
            if result["result"] == "timeout"
            else "passed"
            if result["result"] == "completed" and result["returncode"] == 0
            else "failed"
        )
        detailed_results.append({
            "mutation_id": result["mutation_id"],
            "outcome": outcome,
            "returncode": result["returncode"],
            "duration_ms": result.get("duration_ms"),
            "cwd": result.get("cwd"),
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "output_truncated": result["output_truncated"],
        })
        # The compact view keeps stdout readable in one screen: full output goes
        # to the details artifact, and only non-green outcomes carry a tail here
        # so detecting tests and failure causes stay diagnosable inline.
        entry: dict[str, Any] = {
            "mutation_id": result["mutation_id"],
            "outcome": outcome,
            "returncode": result["returncode"],
            "duration_ms": result.get("duration_ms"),
        }
        if outcome != "passed":
            entry["stdout_tail"] = result["stdout"][-tail_limit:]
            entry["stderr_tail"] = result["stderr"][-tail_limit:]
        public_results.append(entry)
    details_path = Path(manifest["artifact_root"]) / "challenge-results.json"
    _write_exclusive(details_path, {
        "run_id": manifest["run_id"],
        "plan_sha256": plan_sha256,
        "command_id": plan["command_id"],
        "results": detailed_results,
    })
    return {
        "status": "completed",
        "plan_sha256": plan_sha256,
        "command_id": plan["command_id"],
        "max_parallel": plan["max_parallel"],
        "results": public_results,
        "details_path": str(details_path),
        "runner_timings_ms": {
            **runner_timings,
            "external_commands_window": max(
                0, round((time.monotonic() - execution_started) * 1000)
            ),
        },
        "next": _next_step(
            "scaffold-analysis", "--manifest", str(manifest_path),
            "--mode", "<assessment|harden|catch>",
            note="pick the mode of this run's branch, interpret raw outcomes, then follow next.argv",
        ),
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

    batch_timings: dict[str, list[int]] = {}
    individual_mutation_ms = 0
    for item in mutation_executions:
        duration = item.get("duration_ms", 0)
        batch = item.get("batch_plan_sha256")
        if batch:
            batch_timings.setdefault(batch, []).append(duration)
        else:
            individual_mutation_ms += duration
    mutation_wall_ms = individual_mutation_ms + sum(
        max(durations, default=0) for durations in batch_timings.values()
    )

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
            "dependency_layer": prepared["dependency_layer"],
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
                    "duration_ms": item.get("duration_ms", 0),
                }
                for attempt, item in enumerate(baselines, 1)
            ],
            "mutations": [
                {
                    "mutation_id": item["mutation_id"],
                    "attempt": attempt,
                    "outcome": raw_outcome(item),
                    "exit_code": item.get("returncode"),
                    "duration_ms": item.get("duration_ms", 0),
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
        "phase_timings_ms": {
            "baseline": sum(item.get("duration_ms", 0) for item in baselines),
            "mutations": mutation_wall_ms,
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
        "dependency_layer": prepared_event["dependency_layer"],
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


def _analysis_drafts(
    manifest: dict[str, Any],
    analysis: dict[str, Any],
    plan: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    events = _ledger_events(manifest)
    baselines = [
        item for item in events
        if item.get("kind") == "command" and item.get("phase") == "baseline"
    ]
    if not baselines:
        raise RunGateError("complete requires one probed baseline command")
    command = _validated_command(manifest, plan["command_id"])
    challenges = {item["id"]: item for item in plan["challenges"]}
    classifications = {
        item["mutation_id"]: item for item in analysis["classifications"]
    }
    if len(classifications) != len(analysis["classifications"]):
        raise RunGateError("analysis classification IDs must be unique")
    if set(classifications) != set(challenges):
        raise RunGateError(
            "analysis must classify every planned challenge exactly once"
        )
    mutations: list[dict[str, Any]] = []
    for mutation_id in sorted(challenges):
        challenge = challenges[mutation_id]
        classification = classifications[mutation_id]
        operation = challenge["mutation"]
        item = {
            "id": mutation_id,
            "mode": analysis["mode"],
            "contract_ids": challenge["contract_ids"],
            "source_intent": classification["source_intent"],
            "changed_intent": classification["changed_intent"],
            "represented_risk": challenge["accident"],
            "severity": challenge["severity"],
            "likelihood": challenge["likelihood"],
            "code_change": (
                f"{operation['kind']} at exact anchor in "
                f"{operation['relative_path']}"
            ),
            "code_location": challenge["code_location"],
            "expected_detection": challenge["expected_detection"],
            "result": classification["result"],
            "detecting_tests": classification["detecting_tests"],
            "observed_failure_reason": classification["observed_failure_reason"],
            "contract_violation_observed": classification[
                "contract_violation_observed"
            ],
            "follow_up": classification["follow_up"],
            "outcome_interpretation": classification["outcome_interpretation"],
        }
        for optional in ("equivalence_evidence", "catch"):
            if optional in classification:
                item[optional] = classification[optional]
        mutations.append(item)
    report = {
        "version": 1,
        "mode": analysis["mode"],
        "baseline": {
            "command": shlex.join(command["argv"]),
            "status": "green",
            "attempts": len(baselines),
            "stable_tests": analysis["stable_tests"],
            "excluded_tests": analysis["excluded_tests"],
        },
        "assessment": analysis["assessment"],
        "mutations": mutations,
        "not_challenged": analysis["not_challenged"],
        "test_changes": analysis["test_changes"],
        "test_handoff": analysis["test_handoff"],
        "authorized_workspace_changes": [],
        "persistent_side_effects": analysis["persistent_side_effects"],
    }
    return report, analysis["review"]


def _scaffold_document(
    manifest: dict[str, Any],
    filename: str,
    document: dict[str, Any],
    schema_name: str,
    schema_root: Path | None,
) -> dict[str, Any]:
    validator = _validator_module()
    try:
        validator.validate_document(document, schema_name, schema_root)
    except validator.ArtifactError as error:
        raise RunGateError(f"scaffold failed self-validation: {error}") from error
    artifact = Path(manifest["artifact_root"]) / filename
    if artifact.exists():
        raise RunGateError(
            f"{filename} already exists; edit it in place instead of scaffolding"
        )
    return document


def _scaffold_write_protocol(
    manifest: dict[str, Any], filename: str
) -> dict[str, Any]:
    path = Path(manifest["artifact_root"]) / filename
    return {
        "artifact_path": str(path),
        "write_protocol": {
            "first_write": (
                "Use Write exactly once to create artifact_path from the returned "
                "document after replacing semantic placeholders."
            ),
            "correction": (
                "If the file already exists, Read it and use Edit; never call "
                "Write on an existing scaffold."
            ),
        },
    }


def scaffold_contract(
    manifest_path: Path, schema_root: Path | None = None
) -> dict[str, Any]:
    """Generate a structurally valid Intent Contract for one first Write.

    Agents fill every replace-me value from repository evidence and never need
    to read the schema files; stage-artifact validates the written content.
    """
    manifest = _ready_manifest(manifest_path)
    document = {
        "version": 1,
        "status": "provisional",
        "change": {
            "base": "replace-me: Base identity (SHA or snapshot label)",
            "head": "replace-me: Head identity",
            "summary": "replace-me: one-sentence observable change summary",
        },
        "intent": {
            "statement": "replace-me: the intended observable behavior",
            "confidence": "low",
            "evidence": [
                {
                    "source": "replace-me: repository evidence path",
                    "supports": "replace-me: what this evidence establishes",
                }
            ],
        },
        "decisions": [
            {
                "id": "DEC-001",
                "question": "replace-me: the observable behavior question",
                "expected": "replace-me: the expected observable answer",
                "provenance": "repository-established",
            }
        ],
        "invariants": [
            {
                "id": "INV-001",
                "statement": "replace-me: behavior that must not change",
                "severity": "high",
            }
        ],
        "side_effects": {"required": [], "prohibited": []},
        "unresolved": [],
        "coverage": [],
    }
    return _scaffold_document(
        manifest, ARTIFACT_FILES["contract"], document,
        "intent-contract.schema.json", schema_root,
    )


def scaffold_plan(
    manifest_path: Path, schema_root: Path | None = None
) -> dict[str, Any]:
    """Write a structurally valid challenge-plan template bound to the validated command."""
    manifest = _ready_manifest(manifest_path)
    validated = [
        item for item in _ledger_events(manifest)
        if item.get("kind") == "validated-command"
    ]
    if not validated:
        raise RunGateError("scaffold-plan requires a successful probe-command first")
    document = {
        "version": 2,
        "command_id": validated[-1]["command_id"],
        "max_parallel": 2,
        "challenges": [
            {
                "id": "MUT-001",
                "contract_ids": ["DEC-001"],
                "accident": "replace-me: the realistic accident this mutation represents",
                "expected_detection": "replace-me: the observable failure that should catch it",
                "severity": "high",
                "likelihood": "medium",
                "code_location": "replace-me/relative/path:1",
                "mutation": {
                    "kind": "replace-exact",
                    "relative_path": "replace-me/relative/path",
                    "before": "replace-me: exact unique anchor text",
                    "after": "replace-me: mutated text",
                },
            }
        ],
    }
    return _scaffold_document(
        manifest, "challenge-plan.json", document,
        "challenge-plan.schema.json", schema_root,
    )


def scaffold_analysis(
    manifest_path: Path,
    mode: str,
    schema_root: Path | None = None,
) -> dict[str, Any]:
    """Generate a valid semantic-only analysis scaffold from Plan and raw outcomes."""
    if mode not in {"assessment", "harden", "catch"}:
        raise RunGateError("analysis mode must be assessment, harden, or catch")
    manifest = _ready_manifest(manifest_path)
    artifact_root = Path(manifest["artifact_root"])
    plan = _load_json(artifact_root / "challenge-plan.json")
    if not isinstance(plan, dict):
        raise RunGateError("challenge plan root must be an object")
    validator = _validator_module()
    try:
        validator.validate_document(
            plan, "challenge-plan.schema.json", schema_root
        )
    except validator.ArtifactError as error:
        raise RunGateError(str(error)) from error
    executions = {
        item["mutation_id"]: item
        for item in _ledger_events(manifest)
        if item.get("kind") == "command" and item.get("phase") == "mutation"
    }
    planned_ids = [item["id"] for item in plan["challenges"]]
    if set(executions) != set(planned_ids):
        raise RunGateError(
            "analysis scaffold requires raw execution for every planned challenge"
        )
    classifications = []
    for mutation_id in planned_ids:
        event = executions[mutation_id]
        if event.get("result") == "timeout":
            result = "timeout"
            kind = "timeout"
            reason = "The Runner recorded a timeout; confirm the residual risk"
        elif event.get("result") == "runner-error":
            result = "inconclusive"
            kind = "infrastructure-failure"
            reason = "The Runner failed before a behavioral result was available"
        elif event.get("returncode") == 0:
            result = "survived"
            kind = "passed"
            reason = "The focused tests remained green for this accident"
        else:
            result = "inconclusive"
            kind = "unparseable"
            reason = (
                "The process failed; classify whether the failure is behavioral "
                "or infrastructure from the raw outcome"
            )
        classification: dict[str, Any] = {
            "mutation_id": mutation_id,
            "source_intent": f"Describe the protected intent for {mutation_id}",
            "changed_intent": f"Describe the accidental behavior for {mutation_id}",
            "result": result,
            "detecting_tests": [],
            "observed_failure_reason": reason,
            "contract_violation_observed": False,
            "follow_up": "none",
            "outcome_interpretation": {"kind": kind, "reason": reason},
        }
        if mode == "catch":
            classification["catch"] = {
                "parent_outcome": "not-runnable",
                "mutant_outcome": "not-runnable",
                "change_outcome": "not-runnable",
                "human_verdict": "unanswered",
            }
        classifications.append(classification)
    assessment = (
        {
            "selected_scope": "current-change",
            "selection_reason": "replace-me: why this assessment scope was selected",
            "production_files": [],
            "existing_tests": [],
            "changed_tests": [],
            "excluded_scope": [],
            "comparisons": [],
        }
        if mode == "assessment"
        else None
    )
    document = {
        "version": 1,
        "mode": mode,
        "stable_tests": [],
        "excluded_tests": [],
        "assessment": assessment,
        "classifications": classifications,
        "not_challenged": [],
        "test_changes": [],
        "test_handoff": None,
        "persistent_side_effects": {
            "authorization": "not-requested",
            "writes": [],
        },
        "review": {
            "review_this": [],
            "we_verified": [],
            "still_at_risk": [],
            "copy_ready_comments": [],
        },
    }
    try:
        validator.validate_document(
            document, "review-analysis.schema.json", schema_root
        )
    except validator.ArtifactError as error:
        raise RunGateError(str(error)) from error
    path = artifact_root / "review-analysis.json"
    if path.exists():
        raise RunGateError(
            "review-analysis.json already exists; edit it in place instead of scaffolding"
        )
    return {
        "status": "generated",
        "path": str(path),
        "document": document,
        "classifications": len(classifications),
        "next": (
            "write the returned document once after editing semantic intent, "
            "classification, detecting tests, and review claims; do not add run "
            "identity, hashes, commands, or evidence mechanics"
        ),
    }


def complete(
    manifest_path: Path,
    *,
    retention: str = "discard",
    schema_root: Path | None = None,
) -> str:
    """Generate mechanical Drafts, finish, and clean up in one Runner-owned step."""
    if retention not in {"discard", "keep"}:
        raise RunGateError("retention must be discard or keep")
    manifest = _ready_manifest(manifest_path)
    artifact_root = Path(manifest["artifact_root"])
    analysis_path = artifact_root / "review-analysis.json"
    plan_path = artifact_root / "challenge-plan.json"
    analysis = _load_json(analysis_path)
    plan = _load_json(plan_path)
    if not isinstance(analysis, dict) or not isinstance(plan, dict):
        raise RunGateError("complete inputs must be JSON objects")
    validator = _validator_module()
    try:
        validator.validate_document(
            analysis, "review-analysis.schema.json", schema_root
        )
        validator.validate_document(
            plan, "challenge-plan.schema.json", schema_root
        )
    except validator.ArtifactError as error:
        _record_validation_error(manifest, "complete-input", str(error))
        raise RunGateError(str(error)) from error
    runner_timings: dict[str, int] = {}
    with _timed(runner_timings, "draft_generation"):
        report, review = _analysis_drafts(manifest, analysis, plan)
        try:
            validator.validate_document(
                report, "mutation-report-draft.schema.json", schema_root
            )
            validator.validate_document(
                review, "canonical-review.schema.json", schema_root
            )
        except validator.ArtifactError as error:
            _record_validation_error(manifest, "complete-generated", str(error))
            raise RunGateError(str(error)) from error
        for kind, document in (("report", report), ("review", review)):
            path = artifact_root / ARTIFACT_FILES[kind]
            _write_exclusive(path, document)
            stage_artifact(manifest_path, kind, schema_root)
    with _timed(runner_timings, "finish_total"):
        rendered = finish(manifest_path, schema_root)
    if retention == "discard":
        with _timed(runner_timings, "artifact_cleanup"):
            cleanup(manifest_path)
    _emit_runner_timings("complete", runner_timings)
    return rendered


def finish(manifest_path: Path, schema_root: Path | None = None) -> str:
    manifest = _ready_manifest(manifest_path)
    sandbox = Path(manifest["sandbox_root"])
    runner_timings: dict[str, int] = {}
    try:
        with _timed(runner_timings, "load_and_validate"):
            documents = _staged_artifacts(manifest)
            if documents["contract"].get("unresolved"):
                raise RunGateError(
                    "finish is blocked until every unresolved Intent decision is answered"
                )
            ledger = _ledger_events(manifest)
        with _timed(runner_timings, "primary_postflight_hash"):
            current_primary_hash = _tree_hash(Path(manifest["primary_root"]))
        if current_primary_hash != manifest["primary_sha256"]:
            raise RunGateError("Primary content hash changed during the Review-only run")
        prepared_events = [
            item for item in ledger if item.get("kind") == "prepared-snapshot"
        ]
        with _timed(runner_timings, "source_snapshot_verify"):
            source_unchanged = len(prepared_events) == 1 and _prepared_hash(
                Path(manifest["prepared_root"])
            ) == prepared_events[0].get("sha256")
        if not source_unchanged:
            raise RunGateError("prepared source snapshot changed after it was sealed")
        dependency_evidence = (
            prepared_events[0].get("dependency_layer", {})
            if prepared_events
            else {}
        )
        with _timed(runner_timings, "dependency_layer_verify"):
            _verify_dependency_layer(manifest, dependency_evidence)
        with _timed(runner_timings, "sandbox_cleanup"):
            if sandbox.exists():
                shutil.rmtree(sandbox)
        if sandbox.exists():
            raise RunGateError("disposable sandbox still exists after cleanup")
        with _timed(runner_timings, "report_generation"):
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
            with _timed(runner_timings, "schema_validation"):
                validator.validate_document(
                    documents["contract"], "intent-contract.schema.json", schema_root
                )
                validator.validate_document(
                    report, "mutation-report.schema.json", schema_root
                )
                validator.validate_document(
                    documents["review"], "canonical-review.schema.json", schema_root
                )
                validator.validate_cross_artifact(
                    documents["contract"], report, documents["review"]
                )
            with _timed(runner_timings, "render"):
                rendered = validator.render_review(documents["review"])
            report["canonical_output"]["sha256"] = _sha256_bytes(
                rendered.encode("utf-8")
            )
            with _timed(runner_timings, "schema_validation"):
                validator.validate_with_schemas(
                    documents["contract"], report, documents["review"], schema_root
                )
        except validator.ArtifactError as error:
            raise RunGateError(str(error)) from error
        with _timed(runner_timings, "host_output"):
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
        _emit_runner_timings("finish", runner_timings)
        return rendered
    except BaseException as failure:
        cleanup_errors = _cleanup_loaded(manifest, manifest_path)
        _record_failure_receipt(manifest, manifest_path, "finish", failure, cleanup_errors)
        if cleanup_errors:
            raise RunGateError("; ".join(cleanup_errors)) from failure
        raise RunGateError(
            f"{failure}; the run terminated and disposable state was cleaned; "
            "a failure receipt remains in Host storage; "
            "do not retry complete with this manifest"
        ) from failure


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


class _GuidedParser(argparse.ArgumentParser):
    """Raise instead of exiting so argument mistakes return guided JSON."""

    def error(self, message):  # noqa: A003 - argparse API
        raise RunGateError(
            f"invalid-command: {message}; the usage is: {self.format_usage().strip()}; "
            "follow next.argv from the previous Runner result, or run runbook for the pipeline"
        )


def main() -> int:
    parser = _GuidedParser(description=__doc__)
    commands = parser.add_subparsers(
        dest="command", required=True, parser_class=_GuidedParser
    )
    runbook_parser = commands.add_parser("runbook")
    runbook_parser.add_argument("--manifest", required=True, type=Path)
    pre = commands.add_parser("preflight")
    pre.add_argument("--primary", required=True, type=Path)
    pre.add_argument("--host-socket", type=Path)
    pre.add_argument("--host-token")
    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("--manifest", required=True, type=Path)
    inspect_parser.add_argument(
        "--kind", choices=("diff", "file", "search", "tests")
    )
    inspect_parser.add_argument(
        "kind_positional", nargs="?", choices=("diff", "file", "search", "tests"),
        metavar="kind",
        help="inspect kind; `inspect diff` and `inspect --kind diff` are equivalent",
    )
    inspect_parser.add_argument("--relative-path")
    inspect_parser.add_argument("--query")
    inspect_parser.add_argument("--start-line", type=int, default=1)
    inspect_parser.add_argument("--end-line", type=int, default=200)
    mutate_parser = commands.add_parser("mutate")
    mutate_parser.add_argument("--manifest", required=True, type=Path)
    mutate_parser.add_argument("--mutation-id", required=True)
    mutate_parser.add_argument("--contract-id", action="append", required=True)
    mutate_parser.add_argument("--relative-path", required=True)
    mutate_parser.add_argument("--content-file", required=True, type=Path)
    register_parser = commands.add_parser("register-prebuilt")
    register_parser.add_argument("--manifest", required=True, type=Path)
    register_parser.add_argument("--mutation-id", required=True)
    register_parser.add_argument("--contract-id", action="append", required=True)
    register_parser.add_argument("--relative-path", required=True)
    execute_parser = commands.add_parser("execute")
    execute_parser.add_argument("--manifest", required=True, type=Path)
    execute_parser.add_argument(
        "--phase", required=True, choices=("prepare", "baseline", "mutation")
    )
    execute_parser.add_argument("--mutation-id")
    execute_parser.add_argument("--timeout", type=int, default=120)
    execute_parser.add_argument(
        "--cwd", default=None,
        help="sandbox-relative working directory, e.g. the focused package",
    )
    execute_parser.add_argument("argv", nargs=argparse.REMAINDER)
    probe_parser = commands.add_parser("probe-command")
    probe_parser.add_argument("--manifest", required=True, type=Path)
    probe_parser.add_argument("--command-id", required=True)
    probe_parser.add_argument("--timeout", type=int, default=120)
    probe_parser.add_argument(
        "--cwd", default=None,
        help="sandbox-relative working directory, e.g. the focused package",
    )
    probe_parser.add_argument("argv", nargs=argparse.REMAINDER)
    batch_parser = commands.add_parser("challenge-batch")
    batch_parser.add_argument("--manifest", required=True, type=Path)
    batch_parser.add_argument("--schema-root", type=Path)
    scaffold_contract_parser = commands.add_parser("scaffold-contract")
    scaffold_contract_parser.add_argument("--manifest", required=True, type=Path)
    scaffold_contract_parser.add_argument("--schema-root", type=Path)
    scaffold_plan_parser = commands.add_parser("scaffold-plan")
    scaffold_plan_parser.add_argument("--manifest", required=True, type=Path)
    scaffold_plan_parser.add_argument("--schema-root", type=Path)
    scaffold_parser = commands.add_parser("scaffold-analysis")
    scaffold_parser.add_argument("--manifest", required=True, type=Path)
    scaffold_parser.add_argument(
        "--mode", required=True, choices=("assessment", "harden", "catch")
    )
    scaffold_parser.add_argument("--schema-root", type=Path)
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
    complete_parser = commands.add_parser("complete")
    complete_parser.add_argument("--manifest", required=True, type=Path)
    complete_parser.add_argument(
        "--retention", choices=("discard", "keep"), default="discard"
    )
    complete_parser.add_argument("--schema-root", type=Path)
    assess_parser = commands.add_parser(
        "assess", help="run the unsigned v0.4 local-copy prototype"
    )
    assess_parser.add_argument("--source-root", required=True, type=Path)
    assess_parser.add_argument("--plan", required=True, type=Path)
    assess_parser.add_argument("--evidence", required=True, type=Path)
    try:
        args = parser.parse_args()
    except RunGateError as error:
        print(json.dumps(
            {"status": "invalid-command", "error": str(error)}, sort_keys=True
        ))
        return 2
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
        except (OSError, RunGateError) as error:
            try:
                blocked = blocked_preflight(args.primary)
            except (OSError, RunGateError):
                blocked = {
                    "status": "blocked",
                    "terminal": True,
                    "next_action": "stop",
                    "primary_root": str(args.primary),
                    "blocked_reason": str(error),
                    "missing_host_capability": "trusted HostAdapter capability",
                }
            print(json.dumps(blocked, sort_keys=True))
            return 2
        print(json.dumps({
            "status": "ready", "run_id": manifest["run_id"],
            "manifest_path": str(manifest_path),
            "sandbox_root": manifest["sandbox_root"],
            "prepared_root": manifest["prepared_root"],
            "dependency_root": manifest["dependency_root"],
            "artifact_root": manifest["artifact_root"],
            "next": _next_step(
                "runbook", "--manifest", str(manifest_path),
                note=(
                    "read the runbook once: it explains the IDs, the gates, the "
                    "fields you may edit, and returns the exact next command. "
                    "Every later Runner result carries next.argv — run it "
                    "verbatim instead of guessing arguments"
                ),
            ),
            "allowed_operations": [
                "runbook", "inspect", "execute", "probe-command",
                "scaffold-contract", "stage-artifact", "scaffold-plan",
                "challenge-batch", "scaffold-analysis", "complete", "cleanup",
            ],
        }, sort_keys=True))
        return 0
    try:
        if args.command == "runbook":
            print(json.dumps(
                runbook(args.manifest), ensure_ascii=False, sort_keys=True
            ))
        elif args.command == "inspect":
            print(json.dumps(inspect_review(
                args.manifest,
                _resolve_inspect_kind(args.kind, args.kind_positional),
                relative_path=args.relative_path,
                query=args.query,
                start_line=args.start_line,
                end_line=args.end_line,
            ), ensure_ascii=False, sort_keys=True))
        elif args.command == "mutate":
            mutate(
                args.manifest, args.mutation_id, args.contract_id,
                args.relative_path, args.content_file.read_bytes(),
            )
        elif args.command == "register-prebuilt":
            register_prebuilt(
                args.manifest, args.mutation_id, args.contract_id, args.relative_path
            )
        elif args.command == "execute":
            if not args.argv:
                raise RunGateError("execute requires a command after --")
            argv = args.argv[1:] if args.argv[0] == "--" else args.argv
            returncode = execute(
                args.manifest, args.phase, args.mutation_id, argv, args.timeout,
                cwd_relative=args.cwd,
            )
            if args.phase == "prepare" and returncode == 0:
                print(json.dumps({
                    "phase": "prepare", "returncode": returncode,
                    "next": _probe_next(args.manifest),
                }, ensure_ascii=False, sort_keys=True))
            return returncode
        elif args.command == "probe-command":
            if not args.argv:
                raise RunGateError("probe-command requires a command after --")
            argv = args.argv[1:] if args.argv[0] == "--" else args.argv
            result = probe_command(
                args.manifest, args.command_id, argv, args.timeout,
                cwd_relative=args.cwd
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result["status"] == "ready" else 2
        elif args.command == "challenge-batch":
            print(json.dumps(
                challenge_batch(args.manifest, args.schema_root), sort_keys=True
            ))
        elif args.command == "scaffold-contract":
            manifest = _ready_manifest(args.manifest)
            print(json.dumps({
                "artifact": ARTIFACT_FILES["contract"],
                **_scaffold_write_protocol(
                    manifest, ARTIFACT_FILES["contract"]
                ),
                "editable_fields": SCAFFOLD_EDITABLE_FIELDS["contract"],
                "field_guide": SCAFFOLD_FIELD_GUIDES["contract"],
                "document": scaffold_contract(args.manifest, args.schema_root),
                "next": _next_step(
                    "stage-artifact", "--manifest", str(args.manifest),
                    "--kind", "contract",
                    note=(
                        "fill every replace-me value, then Write document once to "
                        "artifact_path; the Runner owns the JSON structure"
                    ),
                ),
            }, ensure_ascii=False, sort_keys=True))
        elif args.command == "scaffold-plan":
            manifest = _ready_manifest(args.manifest)
            print(json.dumps({
                "artifact": "challenge-plan.json",
                **_scaffold_write_protocol(manifest, "challenge-plan.json"),
                "editable_fields": SCAFFOLD_EDITABLE_FIELDS["plan"],
                "field_guide": SCAFFOLD_FIELD_GUIDES["plan"],
                "document": scaffold_plan(args.manifest, args.schema_root),
                "next": _next_step(
                    "challenge-batch", "--manifest", str(args.manifest),
                    note=(
                        "fill the placeholder challenge, then Write document once "
                        "to artifact_path; run synchronously in the foreground"
                    ),
                ),
            }, ensure_ascii=False, sort_keys=True))
        elif args.command == "scaffold-analysis":
            scaffold = scaffold_analysis(args.manifest, args.mode, args.schema_root)
            manifest = _ready_manifest(args.manifest)
            print(json.dumps({
                "artifact": "review-analysis.json",
                **_scaffold_write_protocol(manifest, "review-analysis.json"),
                "editable_fields": SCAFFOLD_EDITABLE_FIELDS["analysis"],
                "field_guide": SCAFFOLD_FIELD_GUIDES["analysis"],
                "document": scaffold["document"],
                "scaffold": scaffold,
                "next": _next_step(
                    "complete", "--manifest", str(args.manifest),
                    "--retention", "discard",
                    note=(
                        "edit only semantic judgments, Write document once to "
                        "artifact_path, then complete renders and cleans up; use "
                        "--retention keep only after an explicit user choice"
                    ),
                ),
            }, ensure_ascii=False, sort_keys=True))
        elif args.command == "stage-artifact":
            staged = stage_artifact(args.manifest, args.kind, args.schema_root)
            if args.kind == "contract":
                staged = dict(staged)
                staged["next"] = _next_step(
                    "execute", "--phase", "prepare",
                    "--manifest", str(args.manifest),
                    "--", "<dependency-install-argv>",
                    note=(
                        "install dependencies once; if the repository needs no "
                        "install, skip straight to probe-command"
                    ),
                )
                staged["skip_if_dependencies_ready"] = _probe_next(args.manifest)
            print(json.dumps(staged, ensure_ascii=False, sort_keys=True))
        elif args.command == "finish":
            sys.stdout.write(finish(args.manifest, args.schema_root))
        elif args.command == "cleanup":
            cleanup(args.manifest)
        elif args.command == "complete":
            sys.stdout.write(complete(
                args.manifest,
                retention=args.retention,
                schema_root=args.schema_root,
            ))
        elif args.command == "assess":
            print(json.dumps(
                assess_experiment(args.source_root, args.plan, args.evidence),
                sort_keys=True,
            ))
        return 0
    except (OSError, RunGateError) as error:
        guided: dict[str, Any] = {
            "status": "error",
            "command": args.command,
            "error": str(error),
        }
        manifest_argument = getattr(args, "manifest", None)
        if manifest_argument is not None:
            guided["next"] = _next_step(
                "runbook", "--manifest", str(manifest_argument),
                note=(
                    "review the runbook gate order, fix the reported cause, then "
                    "rerun the failed command; after a terminal complete failure, "
                    "start a fresh run instead of retrying this manifest"
                ),
            )
        print(json.dumps(guided, ensure_ascii=False, sort_keys=True))
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
