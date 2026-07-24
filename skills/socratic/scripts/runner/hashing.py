"""Canonical bytes, digests, and the byte-compatible content-hash walkers."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from runner.constants import (
    DEPENDENCY_DIRECTORY_NAMES,
    IGNORED_NAMES,
    RUNTIME_DIRECTORY_NAME,
    VIRTUAL_ENV_DIRECTORY_NAMES,
)


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _write_exclusive(path: Path, value: Any) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(_canonical_bytes(value))


def _ignored(_directory: str, names: list[str]) -> set[str]:
    return {
        name for name in names
        if name in IGNORED_NAMES or name.startswith(".env.") or name.endswith(".pyc")
    }


def _ignored_file(filename: str, ignored: set[str]) -> bool:
    return (
        filename in ignored
        or filename.startswith(".env.")
        or filename.endswith(".pyc")
    )


def _digest_entry(digest: Any, relative: str, path: Path) -> bool:
    """Digest one entry's name and content marker; True when it was consumed.

    Symlink and file markers are identical across all three walkers; each
    walker keeps its own traversal order and directory/other markers because
    those differences are part of the sealed digest format.
    """
    digest.update(relative.encode("utf-8") + b"\0")
    if path.is_symlink():
        digest.update(b"symlink\0" + os.readlink(path).encode("utf-8"))
        return True
    if path.is_file():
        digest.update(b"file\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return True
    return False


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False):
        names[:] = sorted(name for name in names if name not in IGNORED_NAMES)
        relative_directory = Path(directory).relative_to(root)
        for filename in sorted(filenames):
            if _ignored_file(filename, IGNORED_NAMES):
                continue
            path = Path(directory) / filename
            relative = (relative_directory / filename).as_posix()
            if not _digest_entry(digest, relative, path):
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
            if _ignored_file(filename, ignored):
                continue
            path = Path(directory) / filename
            relative = (relative_directory / filename).as_posix()
            _digest_entry(digest, relative, path)
    return digest.hexdigest()


def _dependency_hash(root: Path) -> str:
    """Hash every dependency-layer entry, including node_modules and venvs."""
    digest = hashlib.sha256()
    directories = [root]
    while directories:
        directory = directories.pop()
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                _digest_entry(digest, relative, path)
            elif path.is_dir():
                digest.update(relative.encode("utf-8") + b"\0")
                digest.update(b"directory\0")
                directories.append(path)
            elif not _digest_entry(digest, relative, path):
                digest.update(b"other\0")
    return digest.hexdigest()
