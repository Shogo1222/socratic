#!/usr/bin/env python3
"""Contract tests for the local Cursor Desktop Plugin Host integration."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import ROOT, load_module


class CursorHostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.host = load_module("socratic_cursor_shared_host", ROOT / "scripts/claude_host.py")
        cls.hook = load_module(
            "socratic_cursor_preflight", ROOT / "hooks/cursor_preflight.py"
        )
        cls.gate = load_module("socratic_cursor_gate", ROOT / "hooks/cursor_tool_gate.py")
        cls.runner = load_module(
            "socratic_cursor_runner", ROOT / "skills/socratic/scripts/run_review.py"
        )

    def test_local_desktop_run_issues_grant_and_denies_primary_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repository"
            (repository / ".git").mkdir(parents=True)
            (repository / "source.py").write_text("value = 1\n", encoding="utf-8")
            session_id = "cursor-local-fixture"
            try:
                decision = self.hook.evaluate({
                    "hook_event_name": "beforeSubmitPrompt",
                    "prompt": "$socratic review",
                    "conversation_id": session_id,
                    "workspace_roots": [str(repository)],
                })
                self.assertTrue(decision["continue"])
                self.assertIn("Trusted Socratic Host is ready", decision["agent_message"])
                self.assertIn("Host review context:", decision["agent_message"])
                self.assertIn("Start by stating the injected Mission", decision["agent_message"])
                self.assertIn("recommended Review Type", decision["agent_message"])
                self.assertIn(
                    "problem, changed behavior, preserved behavior",
                    decision["agent_message"],
                )
                state = self.host.load_session(session_id)
                adapter = self.runner.ClaudeSocketHostAdapter(
                    Path(state["socket_path"]), state["token"]
                )
                manifest, manifest_path = self.runner.preflight_with_host(repository, adapter)
                self.assertEqual(manifest["host"]["adapter_id"], "cursor-desktop-hook-host-v1")
                review_analysis = (
                    Path(state["artifact_root"]) / "review-analysis.json"
                )
                allowed_artifact = self.gate.evaluate({
                    "hook_event_name": "preToolUse",
                    "conversation_id": session_id,
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(review_analysis)},
                })
                self.assertEqual(allowed_artifact["permission"], "allow")
                review_analysis.write_text("{}", encoding="utf-8")
                denied_rewrite = self.gate.evaluate({
                    "hook_event_name": "preToolUse",
                    "conversation_id": session_id,
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(review_analysis)},
                })
                self.assertEqual(denied_rewrite["permission"], "deny")
                self.assertIn("Read it", denied_rewrite["user_message"])
                allowed_edit = self.gate.evaluate({
                    "hook_event_name": "preToolUse",
                    "conversation_id": session_id,
                    "tool_name": "Edit",
                    "tool_input": {"file_path": str(review_analysis)},
                })
                self.assertEqual(allowed_edit["permission"], "allow")
                allowed_challenge_plan = self.gate.evaluate({
                    "hook_event_name": "preToolUse",
                    "conversation_id": session_id,
                    "tool_name": "Write",
                    "tool_input": {
                        "file_path": str(
                            Path(state["artifact_root"]) / "challenge-plan.json"
                        )
                    },
                })
                self.assertEqual(allowed_challenge_plan["permission"], "allow")
                allowed_experiment_plan = self.gate.evaluate({
                    "hook_event_name": "preToolUse",
                    "conversation_id": session_id,
                    "tool_name": "Write",
                    "tool_input": {
                        "file_path": str(
                            Path(state["artifact_root"]) / "experiment-plan.json"
                        )
                    },
                })
                self.assertEqual(allowed_experiment_plan["permission"], "allow")
                denied_self_asserted_evidence = self.gate.evaluate({
                    "hook_event_name": "preToolUse",
                    "conversation_id": session_id,
                    "tool_name": "Write",
                    "tool_input": {
                        "file_path": str(
                            Path(state["artifact_root"]) / "evidence-bundle.json"
                        )
                    },
                })
                self.assertEqual(
                    denied_self_asserted_evidence["permission"], "deny"
                )
                denied_arbitrary_temp = self.gate.evaluate({
                    "hook_event_name": "preToolUse",
                    "conversation_id": session_id,
                    "tool_name": "Write",
                    "tool_input": {"file_path": "/tmp/not-host-issued.json"},
                })
                self.assertEqual(denied_arbitrary_temp["permission"], "deny")
                denied = self.gate.evaluate({
                    "hook_event_name": "preToolUse",
                    "conversation_id": session_id,
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(repository / "source.py")},
                })
                self.assertEqual(denied["permission"], "deny")
                denied_shell = self.gate.evaluate({
                    "hook_event_name": "beforeShellExecution",
                    "conversation_id": session_id,
                    "command": "npm test",
                })
                self.assertEqual(denied_shell["permission"], "deny")
                allowed_runner = self.gate.evaluate({
                    "hook_event_name": "beforeShellExecution",
                    "conversation_id": session_id,
                    "command": (
                        "python3 "
                        f"{ROOT / 'skills/socratic/scripts/run_review.py'} preflight"
                    ),
                })
                self.assertEqual(allowed_runner["permission"], "allow")
                planted_runner = repository / "run_review.py"
                planted_runner.write_text("print('planted')\n", encoding="utf-8")
                denied_foreign_runner = self.gate.evaluate({
                    "hook_event_name": "beforeShellExecution",
                    "conversation_id": session_id,
                    "command": f"python3 {planted_runner} preflight",
                })
                self.assertEqual(denied_foreign_runner["permission"], "deny")
                denied_archive = self.gate.evaluate({
                    "hook_event_name": "beforeShellExecution",
                    "conversation_id": session_id,
                    "command": "git --no-pager archive -o /tmp/leak.tar HEAD",
                })
                self.assertEqual(denied_archive["permission"], "deny")
                denied_background = self.gate.evaluate({
                    "hook_event_name": "beforeShellExecution",
                    "conversation_id": session_id,
                    "command": (
                        "python3 /plugin/skills/socratic/scripts/"
                        "run_review.py challenge-batch"
                    ),
                    "tool_input": {"run_in_background": True},
                })
                self.assertEqual(denied_background["permission"], "deny")
                denied_shell_background = self.gate.evaluate({
                    "hook_event_name": "beforeShellExecution",
                    "conversation_id": session_id,
                    "command": (
                        "python3 /plugin/skills/socratic/scripts/"
                        "run_review.py challenge-batch &"
                    ),
                })
                self.assertEqual(denied_shell_background["permission"], "deny")
                self.runner.abort(manifest_path)
            finally:
                self.host.cleanup_session(session_id)

    def test_unsupported_or_malformed_socratic_surface_fails_closed(self) -> None:
        decision = self.hook.evaluate({
            "hook_event_name": "beforeSubmitPrompt",
            "prompt": "$socratic review",
            "conversation_id": "missing-workspace",
        })
        self.assertFalse(decision["continue"])
        self.assertIn("blocked", decision["agent_message"])

    def test_materialization_failure_is_reported_by_the_hook(self) -> None:
        with patch.object(self.hook, "_host_module", return_value=self.host), patch.object(
            self.host,
            "prepare_or_retarget_session",
            side_effect=RuntimeError(
                "Host could not materialize the exact pull-request base commit"
            ),
        ):
            decision = self.hook.evaluate({
                "hook_event_name": "beforeSubmitPrompt",
                "prompt": "$socratic PR #438",
                "conversation_id": "cursor-materialization-error",
                "workspace_roots": [str(ROOT)],
            })
        self.assertEqual(
            decision["agent_message"],
            "blocked: Host could not materialize the exact pull-request base commit",
        )

    def test_late_pull_request_selection_is_host_retargeted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repository"
            (repository / ".git").mkdir(parents=True)
            session_id = "cursor-late-pr"
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
                        "hook_event_name": "beforeSubmitPrompt", "prompt": "PR438 日本語で",
                        "conversation_id": session_id,
                        "workspace_roots": [str(repository)],
                    })
                state = self.host.load_session(session_id)
                self.assertNotEqual(state["run_id"], first["run_id"])
                self.assertEqual(state["change_context"]["number"], 438)
                self.assertIn("Discard all scope, findings, plans", decision["agent_message"])
            finally:
                self.host.cleanup_session(session_id)

    def test_direct_maieutic_and_elenchus_require_desktop_context(self) -> None:
        for prompt in ("$maieutic confirm intent", "$elenchus assess tests"):
            with self.subTest(prompt=prompt):
                decision = self.hook.evaluate({
                    "hook_event_name": "beforeSubmitPrompt", "prompt": prompt,
                    "conversation_id": "missing-workspace",
                })
                self.assertFalse(decision["continue"])

    def test_manifest_declares_desktop_hooks(self) -> None:
        manifest = json.loads((ROOT / ".cursor-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "socratic")
        self.assertEqual(manifest["hooks"], "./hooks/cursor-hooks.json")
        hooks = json.loads((ROOT / "hooks/cursor-hooks.json").read_text(encoding="utf-8"))
        self.assertTrue(hooks["hooks"]["beforeSubmitPrompt"][0]["failClosed"])
        self.assertTrue(hooks["hooks"]["preToolUse"][0]["failClosed"])
        self.assertTrue(hooks["hooks"]["beforeShellExecution"][0]["failClosed"])


if __name__ == "__main__":
    unittest.main()
