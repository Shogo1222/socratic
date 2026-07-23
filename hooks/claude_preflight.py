#!/usr/bin/env python3
"""Fail-closed Claude Code gate for explicit Socratic requests."""

from __future__ import annotations

import json
import os
import re
import socket
import sys
from typing import Any


BLOCKED_REASON = "blocked: trusted Host Adapter capability is unavailable"
SOCRATIC_INVOCATION = re.compile(r"(?<![0-9A-Za-z_-])(?:\$|/)socratic\b", re.IGNORECASE)


def _blocked() -> dict[str, str]:
    return {"decision": "block", "reason": BLOCKED_REASON}


def _host_ready() -> bool:
    path = os.environ.get("SOCRATIC_HOST_SOCKET", "")
    token = os.environ.get("SOCRATIC_HOST_TOKEN", "")
    if not path or len(token) < 32:
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(path)
            client.sendall(json.dumps({"action": "ping", "token": token}).encode())
            response = json.loads(client.recv(65536).decode())
        return response == {"status": "ready"}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False


def evaluate(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return _blocked()
    if payload.get("hook_event_name") != "UserPromptSubmit":
        return _blocked()
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return _blocked()
    if SOCRATIC_INVOCATION.search(prompt) and not _host_ready():
        return _blocked()
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
