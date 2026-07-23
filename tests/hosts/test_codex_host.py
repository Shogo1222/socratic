#!/usr/bin/env python3
"""End-to-end tests for the Codex Plugin Host broker and lifecycle hooks."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import ROOT, load_module


class CodexHostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.host = load_module("socratic_codex_shared_host", ROOT / "scripts/claude_host.py")
        cls.hook = load_module("socratic_codex_preflight", ROOT / "hooks/codex_preflight.py")
        cls.tool_gate = load_module("socratic_codex_gate", ROOT / "hooks/claude_tool_gate.py")
        cls.runner = load_module(
            "socratic_codex_runner", ROOT / "skills/socratic/scripts/run_review.py"
        )

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
                self.assertIn("Host review context:", decision["systemMessage"])
                state = self.host.load_session(session_id)
                self.assertIsNotNone(state)
                adapter = self.runner.ClaudeSocketHostAdapter(
                    Path(state["socket_path"]), state["token"]
                )
                manifest, manifest_path = self.runner.preflight_with_host(repository, adapter)
                self.assertEqual(manifest["status"], "ready")
                self.assertEqual(manifest["host"]["adapter_id"], "codex-plugin-hook-host-v1")
                artifact = (
                    Path(state["artifact_root"]) / "mutation-report.draft.json"
                )
                allowed_artifact = self.tool_gate.evaluate({
                    "hook_event_name": "PreToolUse",
                    "session_id": session_id,
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "patch": f"*** Begin Patch\n*** Add File: {artifact}\n+{{}}\n*** End Patch"
                    },
                })
                self.assertEqual(allowed_artifact, {})
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

    def test_materialization_failure_is_reported_by_the_hook(self) -> None:
        with patch.object(self.hook, "_host_module", return_value=self.host), patch.object(
            self.host,
            "prepare_or_retarget_session",
            side_effect=RuntimeError(
                "Host could not materialize the exact pull-request base commit"
            ),
        ):
            decision = self.hook.evaluate({
                "hook_event_name": "UserPromptSubmit",
                "prompt": "$socratic PR #438",
                "session_id": "codex-materialization-error",
                "cwd": str(ROOT),
            })
        self.assertEqual(
            decision["stopReason"],
            "blocked: Host could not materialize the exact pull-request base commit",
        )

    def test_late_pull_request_selection_is_host_retargeted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repository"
            (repository / ".git").mkdir(parents=True)
            session_id = "codex-late-pr"
            try:
                first = self.host.prepare_session(session_id, repository)

                def fake_materialize(primary, storage, requested):
                    head = storage / "change" / "head"
                    head.mkdir(parents=True)
                    return {
                        "source": "github-pull-request", "number": requested,
                        "url": f"https://github.com/example/repo/pull/{requested}",
                        "head_root": str(head),
                    }

                with patch.object(self.hook, "_host_module", return_value=self.host), patch.object(
                    self.host, "materialize_pull_request", side_effect=fake_materialize
                ):
                    decision = self.hook.evaluate({
                        "hook_event_name": "UserPromptSubmit", "prompt": "PR438 日本語で",
                        "session_id": session_id, "cwd": str(repository),
                    })
                state = self.host.load_session(session_id)
                self.assertNotEqual(state["run_id"], first["run_id"])
                self.assertEqual(state["change_context"]["number"], 438)
                self.assertIn("Discard all scope, findings, plans", decision["systemMessage"])
            finally:
                self.host.cleanup_session(session_id)

    def test_direct_maieutic_and_elenchus_require_host_context(self) -> None:
        for prompt in ("$maieutic confirm intent", "$elenchus assess tests"):
            with self.subTest(prompt=prompt):
                decision = self.hook.evaluate({
                    "hook_event_name": "UserPromptSubmit", "prompt": prompt,
                })
                self.assertFalse(decision["continue"])


if __name__ == "__main__":
    unittest.main()
