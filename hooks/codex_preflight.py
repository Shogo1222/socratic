#!/usr/bin/env python3
"""Start the trusted Socratic Host before Codex processes an explicit request."""

from __future__ import annotations

import importlib.util
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any


BLOCKED_REASON = "blocked: trusted Host Adapter capability is unavailable"
SOCRATIC_INVOCATION = re.compile(r"(?<![0-9A-Za-z_-])(?:\$|/)socratic\b", re.IGNORECASE)


def _host_module():
    path = Path(__file__).resolve().parent.parent / "scripts/claude_host.py"
    spec = importlib.util.spec_from_file_location("socratic_codex_host_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Host helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _blocked() -> dict[str, Any]:
    return {"continue": False, "stopReason": BLOCKED_REASON}


def evaluate(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "UserPromptSubmit":
        return _blocked()
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return _blocked()
    if SOCRATIC_INVOCATION.search(prompt) is None:
        return {"continue": True}
    session_id = payload.get("session_id")
    cwd = payload.get("cwd")
    if not isinstance(session_id, str) or not isinstance(cwd, str):
        return _blocked()
    try:
        state = _host_module().prepare_session(
            session_id,
            Path(cwd),
            adapter_id="codex-plugin-hook-host-v1",
            host_name="Codex",
        )
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
    return {"continue": True, "systemMessage": context}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = None
    print(json.dumps(evaluate(payload), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
