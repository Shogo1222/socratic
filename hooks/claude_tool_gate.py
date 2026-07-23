#!/usr/bin/env python3
"""Enforce the active Socratic session boundary before Claude tools run."""

from __future__ import annotations

import importlib.util
import json
import shlex
import sys
from pathlib import Path
from typing import Any


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


def evaluate(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "PreToolUse":
        return {}
    session_id = payload.get("session_id")
    if not isinstance(session_id, str):
        return {}
    state = _host_module().load_session(session_id)
    if not state:
        return {}
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input", {})
    if tool in {"Edit", "Write", "NotebookEdit", "apply_patch"}:
        return _deny("Socratic Review-only forbids direct Primary writes; use the guarded Runner sandbox")
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
