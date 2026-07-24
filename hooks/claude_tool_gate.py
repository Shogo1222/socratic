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
    "challenge-plan.json",
    "experiment-plan.json",
    "intent-contract.draft.json",
    "review-analysis.json",
}

WRITE_TOOLS = {"Edit", "MultiEdit", "NotebookEdit", "Write"}

SHELL_TOOLS = {"Bash", "Shell", "local_shell", "shell"}

READ_ONLY_TOOLS = {
    "Agent",
    "AskUserQuestion",
    "BashOutput",
    "EnterPlanMode",
    "ExitPlanMode",
    "Explore",
    "Glob",
    "Grep",
    "KillShell",
    "LS",
    "NotebookRead",
    "Read",
    "Skill",
    "SlashCommand",
    "Task",
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "TodoRead",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
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
    # "archive" is excluded: `archive -o <path>` writes an arbitrary file, so it
    # is not a read-only evidence command even though safety.md allows it for
    # ungated standalone snapshot export.
    if subcommand in {"rev-parse", "merge-base", "ls-files"}:
        return True
    return False


def _plugin_runner_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent / "skills/socratic/scripts/run_review.py"
    )


def _is_plugin_runner_command(argv: list[str]) -> bool:
    """Trust only this Plugin's own Runner by exact resolved path, never by basename."""
    if len(argv) < 2 or not Path(argv[0]).name.startswith("python"):
        return False
    candidate = Path(argv[1])
    if not candidate.is_absolute():
        return False
    try:
        return candidate.resolve(strict=True) == _plugin_runner_path()
    except OSError:
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
    if tool in WRITE_TOOLS:
        path = None
        if isinstance(tool_input, dict):
            path = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("notebook_path")
        if _inside_artifact_root(state, path):
            artifact = Path(path)
            if tool == "Write":
                if artifact.exists():
                    return _deny(
                        "The Runner scaffold already exists; Read it, then use Edit instead of Write"
                    )
                return {}
            if artifact.is_file():
                return {}
            return _deny(
                "Create the Runner-generated scaffold with its one allowed Write before editing it"
            )
        return _deny("Socratic Review-only forbids direct Primary writes; use the guarded Runner sandbox")
    if tool == "apply_patch":
        paths = _patch_paths(tool_input.get("patch") if isinstance(tool_input, dict) else None)
        if paths and all(_inside_artifact_root(state, path) for path in paths):
            return {}
        return _deny("Socratic apply_patch may write only absolute paths under the Host artifact root")
    if tool in SHELL_TOOLS:
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if not isinstance(command, str):
            return _deny("Socratic requires a structured guarded Runner command")
        if isinstance(tool_input, dict) and any(
            tool_input.get(key) is True
            for key in ("run_in_background", "background")
        ):
            return _deny(
                "Socratic Runner commands must finish synchronously in the foreground"
            )
        try:
            argv = shlex.split(command)
        except ValueError:
            return _deny("Socratic rejected an unparsable shell command")
        if "&" in argv:
            return _deny(
                "Socratic Runner commands must finish synchronously in the foreground"
            )
        if any(marker in command for marker in (";", "&&", "||", "|", ">", "<", "`", "$(", "\n")):
            return _deny("Socratic forbids shell composition outside the guarded Runner")
        if _is_plugin_runner_command(argv):
            return {}
        if _read_only_git_command(command):
            return {}
        return _deny("Socratic tests and mutations must run through run_review.py")
    if tool in READ_ONLY_TOOLS:
        return {}
    return _deny(
        f"Socratic Review-only denies the unrecognized tool {tool!r}; "
        "use the guarded Runner, read-only inspection, or the structured question tool"
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = None
    print(json.dumps(evaluate(payload), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
