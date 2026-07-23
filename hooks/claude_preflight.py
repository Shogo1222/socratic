#!/usr/bin/env python3
"""Fail-closed Claude Code gate for explicit Socratic requests."""

from __future__ import annotations

import json
import importlib.util
import os
import re
import shlex
import sys
from typing import Any
from pathlib import Path


BLOCKED_REASON = "blocked: trusted Host Adapter capability is unavailable"
SOCRATIC_INVOCATION = re.compile(
    r"(?<![0-9A-Za-z_-])(?:\$|/)(?:socratic|maieutic|elenchus)\b", re.IGNORECASE
)


def _blocked() -> dict[str, str]:
    return {"decision": "block", "reason": BLOCKED_REASON}


def _host_module():
    path = Path(__file__).resolve().parent.parent / "scripts/claude_host.py"
    spec = importlib.util.spec_from_file_location("socratic_claude_host_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Host helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runtime_python() -> Path:
    path = Path(__file__).resolve().parent.parent / "scripts/plugin_runtime.py"
    spec = importlib.util.spec_from_file_location("socratic_claude_plugin_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Plugin runtime helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ensure_runtime(Path(__file__).resolve().parent.parent)


def evaluate(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return _blocked()
    if payload.get("hook_event_name") != "UserPromptSubmit":
        return _blocked()
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return _blocked()
    session_id = payload.get("session_id")
    cwd = payload.get("cwd")
    if not isinstance(session_id, str) or not isinstance(cwd, str):
        return _blocked() if SOCRATIC_INVOCATION.search(prompt) else {}
    host = _host_module()
    state = host.load_live_session(session_id)
    active = bool(
        state and host.request(Path(state["socket_path"]), state["token"]) == {"status": "ready"}
    )
    if SOCRATIC_INVOCATION.search(prompt) or active:
        try:
            if not active:
                state = host.prepare_session(session_id, Path(cwd))
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
            "Write only challenge-plan.json, intent-contract.draft.json, "
            "mutation-report.draft.json, and "
            f"canonical-review.draft.json directly under {shlex.quote(state['artifact_root'])}; "
            "run challenge-batch for each plan, stage the three Drafts, then call finish. "
            "Do not hand-write run identity, Host evidence, postflight, or renderer hashes."
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
