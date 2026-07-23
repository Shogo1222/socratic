#!/usr/bin/env python3
"""Clean the automatic Socratic Host session after Cursor stops."""

import importlib.util
import json
import sys
from pathlib import Path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        session_id = payload.get("conversation_id") or payload.get("session_id")
        if isinstance(session_id, str):
            path = Path(__file__).resolve().parent.parent / "scripts/claude_host.py"
            spec = importlib.util.spec_from_file_location("socratic_cursor_host_cleanup", path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.cleanup_session(session_id)
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
