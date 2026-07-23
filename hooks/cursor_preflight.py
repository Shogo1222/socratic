#!/usr/bin/env python3
"""Start the trusted Socratic Host for a local Cursor Desktop request."""

from __future__ import annotations

import importlib.util
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any


BLOCKED_REASON = "blocked: trusted Cursor Desktop Host Adapter capability is unavailable"
SOCRATIC_INVOCATION = re.compile(r"(?<![0-9A-Za-z_-])(?:\$|/)socratic\b", re.IGNORECASE)


def _host_module():
    path = Path(__file__).resolve().parent.parent / "scripts/claude_host.py"
    spec = importlib.util.spec_from_file_location("socratic_cursor_host_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Host helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runtime_python() -> Path:
    path = Path(__file__).resolve().parent.parent / "scripts/plugin_runtime.py"
    spec = importlib.util.spec_from_file_location("socratic_cursor_plugin_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Plugin runtime helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ensure_runtime(Path(__file__).resolve().parent.parent)


def _blocked() -> dict[str, Any]:
    return {"continue": False, "user_message": BLOCKED_REASON, "agent_message": BLOCKED_REASON}


def _session_id(payload: dict[str, Any]) -> str | None:
    for key in ("conversation_id", "session_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _primary(payload: dict[str, Any]) -> Path | None:
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        return Path(cwd)
    roots = payload.get("workspace_roots")
    if isinstance(roots, list) and len(roots) == 1 and isinstance(roots[0], str):
        return Path(roots[0])
    return None


def evaluate(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "beforeSubmitPrompt":
        return _blocked()
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return _blocked()
    session_id = _session_id(payload)
    primary = _primary(payload)
    if session_id is None or primary is None:
        return _blocked() if SOCRATIC_INVOCATION.search(prompt) else {"continue": True}
    host = _host_module()
    state = host.load_session(session_id)
    active = bool(
        state and host.request(Path(state["socket_path"]), state["token"]) == {"status": "ready"}
    )
    if SOCRATIC_INVOCATION.search(prompt) is None and not active:
        return {"continue": True}
    try:
        if not active:
            state = host.prepare_session(
                session_id,
                primary,
                adapter_id="cursor-desktop-hook-host-v1",
                host_name="Cursor Desktop",
            )
        runtime_python = _runtime_python()
    except (OSError, RuntimeError):
        return _blocked()
    assert state is not None
    runner = Path(__file__).resolve().parent.parent / "skills/socratic/scripts/run_review.py"
    context = (
        "Trusted Socratic Host is ready. Run mandatory preflight with: "
        f"{shlex.quote(str(runtime_python))} {shlex.quote(str(runner))} preflight "
        f"--primary {shlex.quote(state['primary_root'])} "
        f"--host-socket {shlex.quote(state['socket_path'])} "
        f"--host-token {shlex.quote(state['token'])}\n"
        "All mutations and tests must use that Runner manifest. "
        f"Write Contract, Report, and Review JSON only under {shlex.quote(state['artifact_root'])}."
    )
    return {"continue": True, "agent_message": context}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = None
    print(json.dumps(evaluate(payload), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
