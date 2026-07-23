#!/usr/bin/env python3
"""Apply the Socratic Review-only tool boundary to an active Codex session."""

import importlib.util
import json
import sys
from pathlib import Path


def main() -> int:
    path = Path(__file__).resolve().parent / "claude_tool_gate.py"
    spec = importlib.util.spec_from_file_location("socratic_codex_tool_gate", path)
    if spec is None or spec.loader is None:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "Socratic Codex gate is unavailable",
        }}))
        return 0
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        payload = json.load(sys.stdin)
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = None
    print(json.dumps(module.evaluate(payload), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
