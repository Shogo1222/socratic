#!/usr/bin/env python3
"""End-to-end tests for the Codex Plugin Host broker and lifecycle hooks."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CodexHostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.host = load("socratic_codex_shared_host", ROOT / "scripts/claude_host.py")
        cls.hook = load("socratic_codex_preflight", ROOT / "hooks/codex_preflight.py")
        cls.tool_gate = load("socratic_codex_gate", ROOT / "hooks/claude_tool_gate.py")
        cls.runner = load("socratic_codex_runner", ROOT / "skills/socratic/scripts/run_review.py")

    def test_live_codex_hooks_issue_grant_and_enforce_review_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repository"
            (repository / ".git").mkdir(parents=True)
            (repository / "source.py").write_text("value = 1\n", encoding="utf-8")
            session_id = "codex-native-host-fixture"
            try:
                decision = self.hook.evaluate({
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "$socratic review",
                    "session_id": session_id,
                    "cwd": str(repository),
                })
                self.assertTrue(decision["continue"])
                self.assertIn("Trusted Socratic Host is ready", decision["systemMessage"])
                state = self.host.load_session(session_id)
                self.assertIsNotNone(state)
                adapter = self.runner.ClaudeSocketHostAdapter(
                    Path(state["socket_path"]), state["token"]
                )
                manifest, manifest_path = self.runner.preflight_with_host(repository, adapter)
                self.assertEqual(manifest["status"], "ready")
                self.assertEqual(manifest["host"]["adapter_id"], "codex-plugin-hook-host-v1")
                denied = self.tool_gate.evaluate({
                    "hook_event_name": "PreToolUse",
                    "session_id": session_id,
                    "tool_name": "apply_patch",
                    "tool_input": {"patch": "*** Begin Patch"},
                })
                self.assertEqual(
                    denied["hookSpecificOutput"]["permissionDecision"], "deny"
                )
                self.runner.abort(manifest_path)
            finally:
                self.host.cleanup_session(session_id)

    def test_non_socratic_prompt_does_not_start_host(self) -> None:
        self.assertEqual(self.hook.evaluate({
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Explain this function",
        }), {"continue": True})


if __name__ == "__main__":
    unittest.main()
