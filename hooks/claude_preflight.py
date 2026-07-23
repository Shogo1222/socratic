#!/usr/bin/env python3
"""Fail-closed Claude Code gate for explicit Socratic requests."""

from __future__ import annotations

import json
import importlib.util
import os
import re
import socket
import shlex
import sys
from typing import Any
from pathlib import Path


BLOCKED_REASON = "blocked: trusted Host Adapter capability is unavailable"
SOCRATIC_INVOCATION = re.compile(r"(?<![0-9A-Za-z_-])(?:\$|/)socratic\b", re.IGNORECASE)


def _blocked() -> dict[str, str]:
    return {"decision": "block", "reason": BLOCKED_REASON}


def _host_ready() -> bool:
    path = os.environ.get("SOCRATIC_HOST_SOCKET", "")
    token = os.environ.get("SOCRATIC_HOST_TOKEN", "")
    if not path or len(token) < 32:
        return False


def _host_module():
    path = Path(__file__).resolve().parent.parent / "scripts/claude_host.py"
    spec = importlib.util.spec_from_file_location("socratic_claude_host_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Host helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
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
    if SOCRATIC_INVOCATION.search(prompt):
        session_id = payload.get("session_id")
        cwd = payload.get("cwd")
        if not isinstance(session_id, str) or not isinstance(cwd, str):
            return _blocked()
        try:
            state = _host_module().prepare_session(session_id, Path(cwd))
        except (OSError, RuntimeError):
            return _blocked()
        runner = Path(__file__).resolve().parent.parent / "skills/socratic/scripts/run_review.py"
        context = (
            "Trusted Socratic Host is ready. Run mandatory preflight with: "
            f"python3 {shlex.quote(str(runner))} preflight "
            f"--primary {shlex.quote(state['primary_root'])} "
            f"--host-socket {shlex.quote(state['socket_path'])} "
            f"--host-token {shlex.quote(state['token'])}\n"
            "All mutations and tests must use that Runner manifest."
        )
        return {"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit", "additionalContext": context
        }}
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
