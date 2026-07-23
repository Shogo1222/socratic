#!/usr/bin/env python3
"""Enforce the active Socratic boundary in a local Cursor Desktop session."""

from __future__ import annotations

import importlib.util
import json
import shlex
import sys
from pathlib import Path
from typing import Any


def _host_module():
    path = Path(__file__).resolve().parent.parent / "scripts/claude_host.py"
    spec = importlib.util.spec_from_file_location("socratic_cursor_host_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _deny(reason: str) -> dict[str, str]:
    return {"permission": "deny", "user_message": reason, "agent_message": reason}


def _session_id(payload: dict[str, Any]) -> str | None:
    for key in ("conversation_id", "session_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _runner_command(command: Any) -> bool:
    if not isinstance(command, str):
        return False
    if any(marker in command for marker in (";", "&&", "||", "|", ">", "<", "`", "$(", "\n")):
        return False
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    return len(argv) >= 2 and Path(argv[1]).name == "run_review.py" and Path(argv[0]).name.startswith("python")


def evaluate(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return _deny("Socratic Cursor gate received malformed input")
    event = payload.get("hook_event_name")
    if event not in {"preToolUse", "beforeShellExecution"}:
        return {"permission": "allow"}
    session_id = _session_id(payload)
    if session_id is None or not _host_module().load_session(session_id):
        return {"permission": "allow"}
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input", {})
    if tool in {"Write", "StrReplace", "Delete", "Edit", "apply_patch"}:
        return _deny("Socratic Review-only forbids direct Primary writes; use the guarded Runner sandbox")
    if event == "beforeShellExecution" or tool in {"Shell", "Bash"}:
        command = payload.get("command")
        if command is None and isinstance(tool_input, dict):
            command = tool_input.get("command")
        if _runner_command(command):
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
