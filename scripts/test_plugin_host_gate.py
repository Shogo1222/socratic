#!/usr/bin/env python3
"""Regression tests for the pre-agent Socratic plugin gate."""

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks/socratic_preflight.py"
CLAUDE_HOOK = ROOT / "hooks/claude_preflight.py"
FIXTURE = ROOT / "fixtures/pr438-blocked-bypass.json"


def load_hook():
    spec = importlib.util.spec_from_file_location("socratic_preflight_hook", HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PluginHostGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.hook = load_hook()
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_pr438_fixture_stops_before_agent_callback(self) -> None:
        agent_events = []
        repository_commands = []

        def start_agent() -> None:
            agent_events.append("agent-started")
            repository_commands.append("git status --short")

        decision = self.hook.evaluate(self.fixture["hook_input"])
        if decision.get("continue", True):
            start_agent()

        self.assertEqual(decision, self.fixture["expected_hook_output"])
        self.assertEqual(agent_events, [])
        self.assertEqual(repository_commands, [])
        self.assertEqual(self.fixture["expected_events_after_hook"], [])
        self.assertEqual(
            decision["stopReason"], self.fixture["expected_terminal_text"]
        )
        rendered = json.dumps(decision)
        for forbidden in (
            "Review This", "We Verified", "Still at Risk", "Copy-ready Comments",
            "MUT-", "killed", "survived", "Apply tests", "Stryker",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_pr438_fixture_models_the_fresh_session_and_bypass_pressure(self) -> None:
        self.assertEqual(
            self.fixture["transcript"], ["/clear", "/socratic", "日本語で PR438"]
        )
        self.assertTrue(self.fixture["prior_conversation_contains_findings"])
        self.assertTrue(self.fixture["broken_test_shim_present"])
        self.assertIn("git", self.fixture["forbidden_commands_after_hook"])
        self.assertIn("vitest", self.fixture["forbidden_commands_after_hook"])
        self.assertIn("C5 needs-decision", self.fixture["invalid_prior_evidence"])

    def test_cli_emits_only_terminal_hook_json(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(self.fixture["hook_input"]),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(json.loads(completed.stdout), self.fixture["expected_hook_output"])

    def test_non_socratic_prompt_is_not_intercepted(self) -> None:
        decision = self.hook.evaluate(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "Explain this Python function.",
            }
        )
        self.assertEqual(decision, {"continue": True})

    def test_slash_and_case_variants_are_intercepted(self) -> None:
        for prompt in ("/socratic 日本語で PR438", "Use $SoCrAtIc for this review"):
            with self.subTest(prompt=prompt):
                self.assertEqual(
                    self.hook.evaluate(
                        {"hook_event_name": "UserPromptSubmit", "prompt": prompt}
                    ),
                    self.fixture["expected_hook_output"],
                )

    def test_malformed_hook_input_fails_closed(self) -> None:
        self.assertEqual(self.hook.evaluate({}), self.fixture["expected_hook_output"])

    def test_plugin_disables_implicit_socratic_invocation(self) -> None:
        metadata = (ROOT / "skills/socratic/agents/openai.yaml").read_text(encoding="utf-8")
        self.assertIn("allow_implicit_invocation: false", metadata)

    def test_plugin_manifest_bundles_skills_and_pre_agent_hook(self) -> None:
        manifest = json.loads(
            (ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["name"], "socratic")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["hooks"], "./hooks/codex-hooks.json")
        hooks = json.loads((ROOT / "hooks/codex-hooks.json").read_text(encoding="utf-8"))
        groups = hooks["hooks"]["UserPromptSubmit"]
        self.assertEqual(len(groups), 1)
        self.assertIn("$PLUGIN_ROOT/hooks/socratic_preflight.py", groups[0]["hooks"][0]["command"])

    def test_claude_plugin_uses_native_block_schema(self) -> None:
        spec = importlib.util.spec_from_file_location("claude_preflight_hook", CLAUDE_HOOK)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        expected = {
            "decision": "block",
            "reason": "blocked: trusted Host Adapter capability is unavailable",
        }
        self.assertEqual(module.evaluate(self.fixture["hook_input"]), expected)
        self.assertEqual(module.evaluate({"hook_event_name": "UserPromptSubmit", "prompt": "hello"}), {})
        manifest = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "0.3.0-alpha.3")
        hooks = json.loads((ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))
        command = hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/claude_preflight.py", command)
        self.assertIn("PreToolUse", hooks["hooks"])
        self.assertIn("Stop", hooks["hooks"])


if __name__ == "__main__":
    unittest.main()
