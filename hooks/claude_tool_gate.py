#!/usr/bin/env python3
"""Enforce the active Socratic session boundary before Claude tools run."""

from __future__ import annotations

import importlib.util
import json
import shlex
import sys
from pathlib import Path
from typing import Any


DRAFT_FILENAMES = {
    "intent-contract.draft.json",
    "mutation-report.draft.json",
    "canonical-review.draft.json",
}


def _host_module():
    path = Path(__file__).resolve().parent.parent / "scripts/claude_host.py"
    spec = importlib.util.spec_from_file_location("socratic_claude_host_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _deny(reason: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}


def _inside_artifact_root(state: dict[str, Any], raw_path: Any) -> bool:
    if not isinstance(raw_path, str) or not raw_path:
        return False
    root = Path(state.get("artifact_root", "/__missing_artifact_root__")).resolve(strict=True)
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        return False
    try:
        candidate.resolve(strict=False).relative_to(root)
        return (
            candidate.resolve(strict=False).parent == root
            and candidate.name in DRAFT_FILENAMES
        )
    except (OSError, ValueError):
        return False


def _patch_paths(patch: Any) -> list[str] | None:
    if not isinstance(patch, str):
        return None
    paths: list[str] = []
    for line in patch.splitlines():
        for marker in ("*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: "):
            if line.startswith(marker):
                paths.append(line[len(marker):].strip())
                break
    return paths or None


def _read_only_git_command(command: str) -> bool:
    """Accept only non-composed Git evidence commands with risky helpers disabled."""
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    if len(argv) < 3 or argv[:2] != ["git", "--no-pager"]:
        return False
    subcommand, arguments = argv[2], argv[3:]
    forbidden = {
        "-c", "--config-env", "--exec-path", "--git-dir", "--work-tree",
        "--paginate", "--no-index", "--ext-diff", "--textconv", "--exec",
    }
    if any(
        arg in forbidden
        or arg.startswith(("--output", "--remote", "--add-file", "--add-virtual-file"))
        for arg in arguments
    ):
        return False
    if subcommand == "status":
        return all(
            arg in {"--short", "--branch", "--porcelain", "--porcelain=v1", "--untracked-files=no"}
            for arg in arguments
        )
    if subcommand in {"diff", "show", "log"}:
        return "--no-ext-diff" in arguments and "--no-textconv" in arguments
    if subcommand in {"rev-parse", "merge-base", "ls-files", "archive"}:
        return True
    return False


def evaluate(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "PreToolUse":
        return {}
    session_id = payload.get("session_id")
    if not isinstance(session_id, str):
        return {}
    state = _host_module().load_live_session(session_id)
    if not state:
        return {}
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input", {})
    if tool in {"Edit", "Write", "NotebookEdit"}:
        path = None
        if isinstance(tool_input, dict):
            path = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("notebook_path")
        if _inside_artifact_root(state, path):
            return {}
        return _deny("Socratic Review-only forbids direct Primary writes; use the guarded Runner sandbox")
    if tool == "apply_patch":
        paths = _patch_paths(tool_input.get("patch") if isinstance(tool_input, dict) else None)
        if paths and all(_inside_artifact_root(state, path) for path in paths):
            return {}
        return _deny("Socratic apply_patch may write only absolute paths under the Host artifact root")
    if tool == "Bash":
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if not isinstance(command, str):
            return _deny("Socratic requires a structured guarded Runner command")
        try:
            argv = shlex.split(command)
        except ValueError:
            return _deny("Socratic rejected an unparsable shell command")
        if any(marker in command for marker in (";", "&&", "||", "|", ">", "<", "`", "$(", "\n")):
            return _deny("Socratic forbids shell composition outside the guarded Runner")
        if len(argv) >= 2 and Path(argv[1]).name == "run_review.py" and Path(argv[0]).name.startswith("python"):
            return {}
        if _read_only_git_command(command):
            return {}
        return _deny("Socratic tests and mutations must run through run_review.py")
    return {}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = None
    print(json.dumps(evaluate(payload), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
