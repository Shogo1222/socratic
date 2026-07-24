"""Bounded, read-only evidence inspection over the reviewed change."""

from __future__ import annotations

import difflib
import os
import re
from pathlib import Path
from typing import Any

from runner.constants import (
    IGNORED_NAMES,
    MAX_INSPECT_BYTES,
    MAX_INSPECT_MATCHES,
    RunGateError,
    _bounded_text,
    _safe_relative_path,
)
from runner.lifecycle import _ready_manifest
from runner.scaffolds import _next_step


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
