#!/usr/bin/env python3
"""Fail-closed mutation target validation for disposable Elenchus sandboxes."""

from __future__ import annotations

import argparse
import json
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path


class IsolationViolation(RuntimeError):
    """Raised before a mutation write can escape its disposable sandbox."""


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.path.normpath(os.fspath(path))))


def _resolved(path: Path) -> Path:
    return path.resolve(strict=False)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise IsolationViolation(f"symlink component is not allowed: {current}")


def _reject_symlinks_below(root: Path, target: Path) -> None:
    try:
        relative = target.relative_to(root)
    except ValueError:
        return
    current = root
    for component in relative.parts:
        current /= component
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise IsolationViolation(f"symlink component is not allowed: {current}")


@dataclass(frozen=True)
class TargetEvidence:
    primary_root: str
    sandbox_root: str
    requested_target: str
    resolved_target: str
    authorized: bool = True


class IsolationGate:
    """Authorize mutation targets and perform writes only after authorization."""

    MARKER = ".socratic-disposable"

    def __init__(self, primary_root: Path, sandbox_root: Path) -> None:
        self.requested_primary_root = _absolute(primary_root)
        self.requested_sandbox_root = _absolute(sandbox_root)
        self.primary_root = _resolved(_absolute(primary_root))
        self.sandbox_root = _resolved(_absolute(sandbox_root))
        self.write_events: list[dict[str, object]] = []

        if self.primary_root == self.sandbox_root:
            raise IsolationViolation("primary and sandbox roots must differ")
        if _is_within(self.sandbox_root, self.primary_root):
            raise IsolationViolation("sandbox root must not be inside the primary root")
        if _is_within(self.primary_root, self.sandbox_root):
            raise IsolationViolation("primary root must not be inside the sandbox root")
        if not self.sandbox_root.is_dir():
            raise IsolationViolation(f"sandbox root does not exist: {self.sandbox_root}")
        if self.requested_sandbox_root.is_symlink():
            raise IsolationViolation("sandbox root itself must not be a symlink")
        _reject_symlink_components(self.sandbox_root)
        marker = self.sandbox_root / self.MARKER
        if marker.is_symlink() or not marker.is_file():
            raise IsolationViolation(
                f"sandbox is not explicitly disposable; missing {self.MARKER}"
            )

    def authorize(self, target: Path) -> TargetEvidence:
        requested = _absolute(target)
        _reject_symlinks_below(self.requested_sandbox_root, requested)
        resolved = _resolved(requested)

        if not _is_within(resolved, self.sandbox_root):
            raise IsolationViolation(f"mutation target is outside sandbox: {resolved}")
        if _is_within(resolved, self.primary_root):
            raise IsolationViolation(f"mutation target is inside primary workspace: {resolved}")
        if resolved == self.sandbox_root:
            raise IsolationViolation("mutation target must be a file below the sandbox root")

        return TargetEvidence(
            primary_root=str(self.primary_root),
            sandbox_root=str(self.sandbox_root),
            requested_target=str(requested),
            resolved_target=str(resolved),
        )

    def write_bytes(self, target: Path, content: bytes) -> TargetEvidence:
        evidence = self.authorize(target)
        resolved = Path(evidence.resolved_target)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        # Re-authorize after parent creation to close a path-change window.
        evidence = self.authorize(resolved)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(resolved, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        self.write_events.append(
            {
                "target": evidence.resolved_target,
                "bytes": len(content),
                "within_sandbox": True,
            }
        )
        return evidence

    def write_text(self, target: Path, content: str, *, encoding: str = "utf-8") -> TargetEvidence:
        return self.write_bytes(target, content.encode(encoding))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-root", required=True, type=Path)
    parser.add_argument("--sandbox-root", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    args = parser.parse_args()

    try:
        evidence = IsolationGate(args.primary_root, args.sandbox_root).authorize(args.target)
    except IsolationViolation as error:
        print(json.dumps({"authorized": False, "error": str(error)}))
        return 2
    print(json.dumps(asdict(evidence), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
