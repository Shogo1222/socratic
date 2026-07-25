"""Prepared snapshot sealing, dependency-layer handling, and mutant clones."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from runner.constants import (
    DEPENDENCY_DIRECTORY_NAMES,
    NODE_RUNTIME_DIRECTORY_NAMES,
    RUNTIME_DIRECTORY_NAME,
    RunGateError,
    SANDBOX_ENV_DEFAULTS,
    VIRTUAL_ENV_DIRECTORY_NAMES,
    _timed,
)
from runner.hashing import _dependency_hash, _prepared_hash
from runner.ledger import _append_event, _ledger_events


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
