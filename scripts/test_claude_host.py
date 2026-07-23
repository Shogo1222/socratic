#!/usr/bin/env python3
"""Tests for the launcher-owned Claude Host broker."""

import importlib.util
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ClaudeHostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.host = load("socratic_claude_host", ROOT / "scripts/claude_host.py")
        cls.hook = load("socratic_claude_hook", ROOT / "hooks/claude_preflight.py")
        cls.tool_gate = load("socratic_tool_gate", ROOT / "hooks/claude_tool_gate.py")
        cls.cleanup_hook = load("socratic_claude_cleanup", ROOT / "hooks/claude_cleanup.py")
        cls.runner = load("socratic_runner_host", ROOT / "skills/socratic/scripts/run_review.py")

    def test_live_broker_allows_hook_and_issues_runner_grant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            (repository / ".git").mkdir(parents=True)
            (repository / "source.py").write_text("value = 1\n")
            session_id = "automatic-host-fixture"
            try:
                decision = self.hook.evaluate({
                    "hook_event_name": "UserPromptSubmit", "prompt": "/socratic:socratic review",
                    "session_id": session_id, "cwd": str(repository),
                })
                context = decision["hookSpecificOutput"]["additionalContext"]
                self.assertIn("Trusted Socratic Host is ready", context)
                state = self.host.load_session(session_id)
                self.assertIsNotNone(state)
                adapter = self.runner.ClaudeSocketHostAdapter(
                    Path(state["socket_path"]), state["token"]
                )
                manifest, manifest_path = self.runner.preflight_with_host(repository, adapter)
                self.assertEqual(manifest["status"], "ready")
                self.assertEqual(manifest["host"]["adapter_id"], "claude-code-hook-host-v1")
                artifact_path = Path(state["artifact_root"]) / "intent-contract.json"
                allowed_artifact = self.tool_gate.evaluate({
                    "hook_event_name": "PreToolUse", "session_id": session_id,
                    "tool_name": "Write", "tool_input": {"file_path": str(artifact_path)},
                })
                self.assertEqual(allowed_artifact, {})
                denied_arbitrary_temp = self.tool_gate.evaluate({
                    "hook_event_name": "PreToolUse", "session_id": session_id,
                    "tool_name": "Write", "tool_input": {"file_path": "/tmp/not-host-issued.json"},
                })
                self.assertEqual(
                    denied_arbitrary_temp["hookSpecificOutput"]["permissionDecision"], "deny"
                )
                allowed_artifact_patch = self.tool_gate.evaluate({
                    "hook_event_name": "PreToolUse", "session_id": session_id,
                    "tool_name": "apply_patch", "tool_input": {
                        "patch": f"*** Begin Patch\n*** Add File: {artifact_path}\n+{{}}\n*** End Patch"
                    },
                })
                self.assertEqual(allowed_artifact_patch, {})
                denied_manifest = self.tool_gate.evaluate({
                    "hook_event_name": "PreToolUse", "session_id": session_id,
                    "tool_name": "Write", "tool_input": {
                        "file_path": str(Path(state["storage_root"]) / "run-manifest.json")
                    },
                })
                self.assertEqual(
                    denied_manifest["hookSpecificOutput"]["permissionDecision"], "deny"
                )
                with patch.object(
                    sys, "stdin", io.StringIO(json.dumps({"session_id": session_id}))
                ), redirect_stdout(io.StringIO()):
                    self.cleanup_hook.main()
                preserved = self.host.load_session(session_id)
                self.assertEqual(preserved["run_id"], state["run_id"])
                follow_up = self.hook.evaluate({
                    "hook_event_name": "UserPromptSubmit", "prompt": "continue",
                    "session_id": session_id, "cwd": str(repository),
                })
                self.assertIn("Trusted Socratic Host is ready", follow_up["hookSpecificOutput"]["additionalContext"])
                denied = self.tool_gate.evaluate({
                    "hook_event_name": "PreToolUse", "session_id": session_id,
                    "tool_name": "Edit", "tool_input": {"file_path": str(repository / "source.py")},
                })
                self.assertEqual(
                    denied["hookSpecificOutput"]["permissionDecision"], "deny"
                )
                denied_bash = self.tool_gate.evaluate({
                    "hook_event_name": "PreToolUse", "session_id": session_id,
                    "tool_name": "Bash", "tool_input": {"command": "npm test"},
                })
                self.assertEqual(
                    denied_bash["hookSpecificOutput"]["permissionDecision"], "deny"
                )
                allowed_runner = self.tool_gate.evaluate({
                    "hook_event_name": "PreToolUse", "session_id": session_id,
                    "tool_name": "Bash", "tool_input": {
                        "command": "python3 /plugin/skills/socratic/scripts/run_review.py preflight"
                    },
                })
                self.assertEqual(allowed_runner, {})
                for command in (
                    "git --no-pager status --short",
                    "git --no-pager diff --no-ext-diff --no-textconv HEAD~1 HEAD",
                    "git --no-pager show --no-ext-diff --no-textconv HEAD",
                    "git --no-pager log --no-ext-diff --no-textconv -3",
                ):
                    self.assertEqual(self.tool_gate.evaluate({
                        "hook_event_name": "PreToolUse", "session_id": session_id,
                        "tool_name": "Bash", "tool_input": {"command": command},
                    }), {})
                unsafe_git = self.tool_gate.evaluate({
                    "hook_event_name": "PreToolUse", "session_id": session_id,
                    "tool_name": "Bash", "tool_input": {
                        "command": "git --no-pager diff --output=/tmp/leak HEAD"
                    },
                })
                self.assertEqual(
                    unsafe_git["hookSpecificOutput"]["permissionDecision"], "deny"
                )
                conflicting_git = self.tool_gate.evaluate({
                    "hook_event_name": "PreToolUse", "session_id": session_id,
                    "tool_name": "Bash", "tool_input": {
                        "command": "git --no-pager diff --no-ext-diff --no-textconv --ext-diff HEAD"
                    },
                })
                self.assertEqual(
                    conflicting_git["hookSpecificOutput"]["permissionDecision"], "deny"
                )
                self.runner.abort(manifest_path)
                with patch.object(
                    sys, "stdin", io.StringIO(json.dumps({"session_id": session_id}))
                ), redirect_stdout(io.StringIO()):
                    self.cleanup_hook.main()
                self.assertIsNone(self.host.load_session(session_id))
            finally:
                self.host.cleanup_session(session_id)

    def test_missing_or_wrong_broker_token_stays_blocked(self) -> None:
        payload = {"hook_event_name": "UserPromptSubmit", "prompt": "/socratic:socratic"}
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.hook.evaluate(payload)["decision"], "block")

    def test_each_explicit_skill_starts_the_host(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repository"
            (repository / ".git").mkdir(parents=True)
            for index, prompt in enumerate(("/socratic", "/maieutic", "/elenchus")):
                session_id = f"explicit-skill-{index}"
                try:
                    decision = self.hook.evaluate({
                        "hook_event_name": "UserPromptSubmit", "prompt": prompt,
                        "session_id": session_id, "cwd": str(repository),
                    })
                    self.assertIn("Trusted Socratic Host is ready", decision["hookSpecificOutput"]["additionalContext"])
                finally:
                    self.host.cleanup_session(session_id)

    def test_dead_broker_stays_fail_closed_until_expired_then_is_collected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repository"
            (repository / ".git").mkdir(parents=True)
            session_id = "stale-broker-fixture"
            state = self.host.prepare_session(session_id, repository)
            os.kill(int(state["pid"]), 15)
            for _ in range(50):
                if self.host.request(Path(state["socket_path"]), state["token"]) == {"status": "blocked"}:
                    break
                time.sleep(0.02)
            payload = {
                "hook_event_name": "PreToolUse", "session_id": session_id,
                "tool_name": "Edit", "tool_input": {"file_path": str(repository / "source.py")},
            }
            still_blocked = self.tool_gate.evaluate(payload)
            self.assertEqual(
                still_blocked["hookSpecificOutput"]["permissionDecision"], "deny"
            )
            state_path = self.host.session_root(session_id) / "state.json"
            expired = time.time() - self.host.BROKER_IDLE_TTL_SECONDS - 1
            os.utime(state_path, (expired, expired))
            decision = self.tool_gate.evaluate(payload)
            self.assertEqual(decision, {})
            self.assertFalse(self.host.session_root(session_id).exists())

    def test_launcher_runs_claude_only_in_disposable_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            primary = Path(directory) / "primary"
            (primary / ".git").mkdir(parents=True)
            (primary / "source.py").write_text("original\n")
            observed = {}

            def fake_run(argv, *, cwd, env, check):
                observed.update({"argv": argv, "cwd": Path(cwd), "env": env, "check": check})
                self.assertNotEqual(Path(cwd).resolve(), primary.resolve())
                self.assertEqual((Path(cwd) / "source.py").read_text(), "original\n")
                self.assertEqual(
                    self.host.request(Path(env["SOCRATIC_HOST_SOCKET"]), env["SOCRATIC_HOST_TOKEN"]),
                    {"status": "ready"},
                )
                return type("Completed", (), {"returncode": 0})()

            with patch.object(self.host.subprocess, "run", side_effect=fake_run):
                self.assertEqual(self.host.launch(primary, ROOT, "claude", ["--model", "sonnet"]), 0)
            self.assertEqual((primary / "source.py").read_text(), "original\n")
            self.assertFalse(observed["cwd"].exists())
            self.assertEqual(observed["argv"][:2], ["claude", "--plugin-dir"])


if __name__ == "__main__":
    unittest.main()
