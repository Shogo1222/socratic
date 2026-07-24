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
SOCRATIC_INVOCATION = re.compile(
    r"(?<![0-9A-Za-z_-])(?:\$|/)(?:socratic|maieutic|elenchus)\b", re.IGNORECASE
)


def _host_module():
    path = Path(__file__).resolve().parent.parent / "scripts/claude_host.py"
    spec = importlib.util.spec_from_file_location("socratic_codex_host_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Host helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runtime_python() -> Path:
    path = Path(__file__).resolve().parent.parent / "scripts/plugin_runtime.py"
    spec = importlib.util.spec_from_file_location("socratic_codex_plugin_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Plugin runtime helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ensure_runtime(Path(__file__).resolve().parent.parent)


def _blocked(detail: str | None = None) -> dict[str, Any]:
    reason = f"blocked: {detail}" if detail else BLOCKED_REASON
    return {"continue": False, "stopReason": reason}


def evaluate(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "UserPromptSubmit":
        return _blocked()
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return _blocked()
    session_id = payload.get("session_id")
    cwd = payload.get("cwd")
    if not isinstance(session_id, str) or not isinstance(cwd, str):
        return _blocked() if SOCRATIC_INVOCATION.search(prompt) else {"continue": True}
    host = _host_module()
    state = host.load_live_session(session_id)
    active = bool(
        state and host.request(Path(state["socket_path"]), state["token"]) == {"status": "ready"}
    )
    if SOCRATIC_INVOCATION.search(prompt) is None and not active:
        return {"continue": True}
    try:
        state, retargeted = host.prepare_or_retarget_session(
            session_id,
            Path(cwd),
            prompt,
            adapter_id="codex-plugin-hook-host-v1",
            host_name="Codex",
        )
        runtime_python = _runtime_python()
    except RuntimeError as error:
        return _blocked(str(error))
    except OSError:
        return _blocked()
    assert state is not None
    runner = Path(__file__).resolve().parent.parent / "skills/socratic/scripts/run_review.py"
    retarget_context = (
        "The user selected a new pull-request target. The Host terminated the "
        "previous run and materialized a fresh review root. Discard all scope, "
        "findings, plans, and agent results from the previous run. Do not use "
        "git fetch, gh, or a subagent to obtain the pull request.\n"
        if retargeted else ""
    )
    review_context = json.dumps(
        state["review_context"], ensure_ascii=False, sort_keys=True
    )
    context = retarget_context + (
        f"Host review context: {review_context}\n"
        "Start by stating the injected Mission in the user's language. Before "
        "repository commands or tests, present the recommended Review Type and "
        "obtain human confirmation or correction. Then use this context and the "
        "materialized snapshots directly. Do not launch subagents for deterministic "
        "diff or environment discovery. After bounded read-only inspection and "
        "before tests, present exactly: problem, changed behavior, preserved behavior, "
        "new observable behavior, and consequential uncertainty. Obtain human "
        "confirmation or correction of that diff understanding. Stage the "
        "Intent Contract before mutation; if an observable oracle remains unresolved, "
        "ask the user a structured question and stop that challenge.\n"
        "Trusted Socratic Host is ready. Run mandatory preflight with: "
        f"{shlex.quote(str(runtime_python))} {shlex.quote(str(runner))} preflight "
        f"--primary {shlex.quote(state['review_root'])} "
        f"--host-socket {shlex.quote(state['socket_path'])} "
        f"--host-token {shlex.quote(state['token'])}\n"
        "All inspection, preparation, tests, mutations, rendering, and cleanup "
        "must use that Runner manifest. Write only challenge-plan.json, "
        "intent-contract.draft.json, and review-analysis.json directly under "
        f"{shlex.quote(state['artifact_root'])}; "
        "the v0.4 prototype may instead write experiment-plan.json there, "
        "but only the Runner may create evidence-bundle.json. "
        "For canonical runs, read the runbook once via the preflight next.argv, then follow each result's next.argv verbatim, synchronously in the foreground (never in a background task): runbook, inspect, scaffold-contract, execute --phase prepare, probe-command, scaffold-plan, "
        "one challenge-batch, scaffold-analysis, then complete. The challenge plan contains only exact "
        "anchored edits and a validated command ID; never embed a complete source file. "
        "The Runner generates Report and Review Drafts, renders, and cleans up. "
        "Edit only semantic judgments in the Runner-created analysis scaffold. "
        "Do not read schemas or hand-write run identity, Host evidence, postflight, "
        "report mechanics, or renderer hashes."
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
