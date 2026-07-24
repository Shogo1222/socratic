#!/usr/bin/env python3
"""Enforce the active Socratic boundary in a local Cursor Desktop session."""

from __future__ import annotations

import importlib.util
import json
import shlex
import sys
from pathlib import Path
from typing import Any


DRAFT_FILENAMES = {
    "challenge-plan.json",
    "experiment-plan.json",
    "intent-contract.draft.json",
    "review-analysis.json",
}


def _host_module():
    path = Path(__file__).resolve().parent.parent / "scripts/claude_host.py"
    spec = importlib.util.spec_from_file_location("socratic_cursor_host_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _deny(reason: str) -> dict[str, str]:
    return {"permission": "deny", "user_message": reason, "agent_message": reason}


def _inside_artifact_root(state: dict[str, Any], raw_path: Any) -> bool:
    if not isinstance(raw_path, str) or not raw_path:
        return False
    raw_root = state.get("artifact_root")
    if not isinstance(raw_root, str) or not raw_root:
        return False
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        return False
    try:
        root = Path(raw_root).resolve(strict=True)
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


def _session_id(payload: dict[str, Any]) -> str | None:
    for key in ("conversation_id", "session_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _plugin_runner_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent / "skills/socratic/scripts/run_review.py"
    )


def _runner_command(command: Any, tool_input: Any = None) -> bool:
    """Trust only this Plugin's own Runner by exact resolved path, never by basename."""
    if not isinstance(command, str):
        return False
    if isinstance(tool_input, dict) and any(
        tool_input.get(key) is True
        for key in ("run_in_background", "background")
    ):
        return False
    if any(marker in command for marker in (";", "&&", "||", "|", ">", "<", "`", "$(", "\n")):
        return False
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    if "&" in argv or len(argv) < 2 or not Path(argv[0]).name.startswith("python"):
        return False
    candidate = Path(argv[1])
    if not candidate.is_absolute():
        return False
    try:
        return candidate.resolve(strict=True) == _plugin_runner_path()
    except OSError:
        return False


def _read_only_git_command(command: Any, tool_input: Any = None) -> bool:
    if not isinstance(command, str):
        return False
    if isinstance(tool_input, dict) and any(
        tool_input.get(key) is True
        for key in ("run_in_background", "background")
    ):
        return False
    if any(marker in command for marker in (";", "&&", "||", "|", ">", "<", "`", "$(", "\n")):
        return False
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    if "&" in argv or len(argv) < 3 or argv[:2] != ["git", "--no-pager"]:
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
    # "archive" is excluded: `archive -o <path>` writes an arbitrary file.
    if subcommand in {"rev-parse", "merge-base", "ls-files"}:
        return True
    return False


def evaluate(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return _deny("Socratic Cursor gate received malformed input")
    event = payload.get("hook_event_name")
    if event not in {"preToolUse", "beforeShellExecution"}:
        return {"permission": "allow"}
    session_id = _session_id(payload)
    state = _host_module().load_live_session(session_id) if session_id is not None else None
    if state is None:
        return {"permission": "allow"}
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input", {})
    if tool in {"Write", "StrReplace", "Delete", "Edit", "MultiEdit", "NotebookEdit"}:
        path = None
        if isinstance(tool_input, dict):
            path = tool_input.get("file_path") or tool_input.get("path")
        if _inside_artifact_root(state, path):
            artifact = Path(path)
            if tool == "Write":
                if artifact.exists():
                    return _deny(
                        "The Runner scaffold already exists; read it, then edit instead of rewriting it"
                    )
                return {"permission": "allow"}
            if artifact.is_file():
                return {"permission": "allow"}
            return _deny(
                "Create the Runner-generated scaffold with its one allowed Write before editing it"
            )
        return _deny("Socratic Review-only forbids direct Primary writes; use the guarded Runner sandbox")
    if tool == "apply_patch":
        paths = _patch_paths(tool_input.get("patch") if isinstance(tool_input, dict) else None)
        if paths and all(_inside_artifact_root(state, path) for path in paths):
            return {"permission": "allow"}
        return _deny("Socratic apply_patch may write only absolute paths under the Host artifact root")
    if event == "beforeShellExecution" or tool in {"Shell", "Bash"}:
        command = payload.get("command")
        if command is None and isinstance(tool_input, dict):
            command = tool_input.get("command")
        if _runner_command(command, tool_input) or _read_only_git_command(command, tool_input):
            return {"permission": "allow"}
        return _deny("Socratic tests and mutations must run through run_review.py")
    return {"permission": "allow"}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = None
    print(json.dumps(evaluate(payload), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
