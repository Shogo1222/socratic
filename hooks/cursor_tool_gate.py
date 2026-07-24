#!/usr/bin/env python3
"""Enforce the active Socratic boundary in a local Cursor Desktop session.

This file is an adapter only: it translates Cursor hook payloads into the
shared gate's vocabulary, delegates every decision to claude_tool_gate.py,
and translates the verdict back into Cursor's permission schema. Keeping the
decision logic in one implementation prevents hand-copied variants from
drifting apart.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


TOOL_ALIASES = {
    "Delete": "Edit",
    "Shell": "Bash",
    "StrReplace": "Edit",
}


def _shared_gate():
    path = Path(__file__).resolve().parent / "claude_tool_gate.py"
    spec = importlib.util.spec_from_file_location("socratic_cursor_shared_gate", path)
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


def evaluate(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return _deny("Socratic Cursor gate received malformed input")
    event = payload.get("hook_event_name")
    if event not in {"preToolUse", "beforeShellExecution"}:
        return {"permission": "allow"}
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    tool_input = dict(tool_input) if isinstance(tool_input, dict) else {}
    if event == "beforeShellExecution":
        tool = "Bash"
        if "command" not in tool_input and isinstance(payload.get("command"), str):
            tool_input["command"] = payload["command"]
    verdict = _shared_gate().evaluate({
        "hook_event_name": "PreToolUse",
        "session_id": _session_id(payload),
        "tool_name": TOOL_ALIASES.get(tool, tool),
        "tool_input": tool_input,
    })
    if not verdict:
        return {"permission": "allow"}
    reason = verdict.get("hookSpecificOutput", {}).get(
        "permissionDecisionReason", "Socratic denied the tool call"
    )
    return _deny(reason)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = None
    print(json.dumps(evaluate(payload), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
