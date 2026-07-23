#!/usr/bin/env python3
"""Pre-agent fail-closed gate for explicit Socratic plugin requests."""

from __future__ import annotations

import json
import re
import sys
from typing import Any


BLOCKED_REASON = "blocked: trusted Host Adapter capability is unavailable"
SOCRATIC_INVOCATION = re.compile(r"(?<![0-9A-Za-z_-])(?:\$|/)socratic\b", re.IGNORECASE)


def _blocked() -> dict[str, Any]:
    return {"continue": False, "stopReason": BLOCKED_REASON}


def evaluate(payload: Any) -> dict[str, Any]:
    """Return the Host lifecycle decision without reading the repository."""
    if not isinstance(payload, dict):
        return _blocked()
    if payload.get("hook_event_name") != "UserPromptSubmit":
        return _blocked()
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return _blocked()
    if SOCRATIC_INVOCATION.search(prompt) is None:
        return {"continue": True}
    return _blocked()


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = None
    print(json.dumps(evaluate(payload), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
