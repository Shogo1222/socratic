#!/usr/bin/env python3
"""Regression requirements from the v0.2.4 realistic-use workflow review."""

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


artifacts = load_module(
    "validate_and_render_workflow_gates",
    ROOT / "skills" / "socratic" / "scripts" / "validate_and_render.py",
)


def minimal_contract(*, status: str, unresolved: list[dict[str, str]]) -> dict[str, object]:
    return {
        "status": status,
        "decisions": [],
        "invariants": [],
        "side_effects": {"required": [], "prohibited": []},
        "unresolved": unresolved,
    }


def minimal_report(*, status: str, unresolved: list[str]) -> dict[str, object]:
    return {
        "write_mode": "review-only",
        "intent_contract": {"status": status},
        "mutations": [],
        "unresolved": unresolved,
        "isolation": {
            "execution_strategy": "comparison-only",
            "primary_root": "/primary",
            "sandbox_root": "/sandbox",
            "host_protection": {
                "mode": "os-read-only",
                "verified": True,
                "details": "fixture",
            },
            "mutation_targets": [],
            "write_events": [],
        },
        "postflight": {
            "primary_written_during_run": False,
            "primary_final_hash_unchanged": True,
            "working_tree_final_status": "clean",
            "production_mutation_free": True,
            "sandbox_destroyed": True,
            "notes": "fixture",
        },
    }


class ContractLifecycleGateTest(unittest.TestCase):
    def test_tested_contract_with_unresolved_item_is_rejected(self) -> None:
        contract = minimal_contract(
            status="tested",
            unresolved=[{"id": "UNR-001", "statement": "choice", "test_impact": "oracle"}],
        )
        report = minimal_report(status="tested", unresolved=["UNR-001"])
        with self.assertRaises(artifacts.ArtifactError):
            artifacts.validate_cross_artifact(contract, report)

    def test_contract_and_report_status_and_unresolved_sets_must_match(self) -> None:
        contract = minimal_contract(
            status="needs-decision",
            unresolved=[{"id": "UNR-001", "statement": "choice", "test_impact": "oracle"}],
        )
        report = minimal_report(status="tested", unresolved=[])
        with self.assertRaises(artifacts.ArtifactError):
            artifacts.validate_cross_artifact(contract, report)

    def test_elenchus_gate_blocks_only_contract_ids_mapped_to_unresolved_oracles(self) -> None:
        self.assertTrue(hasattr(artifacts, "assert_elenchus_allowed"))
        contract = {
            **minimal_contract(
                status="needs-decision",
                unresolved=[
                    {
                        "id": "UNR-001",
                        "statement": "wrapped cause behavior",
                        "test_impact": "DEC-002",
                    }
                ],
            ),
            "decisions": [{"id": "DEC-001"}],
        }
        artifacts.assert_elenchus_allowed(contract, ["DEC-001"])
        with self.assertRaises(artifacts.ArtifactError):
            artifacts.assert_elenchus_allowed(contract, ["DEC-002"])


class DecisionRoutingTest(unittest.TestCase):
    def test_repository_established_evidence_skips_question(self) -> None:
        self.assertTrue(hasattr(artifacts, "route_intent_decision"))
        route = artifacts.route_intent_decision(
            evidence_resolves=True,
            multiple_reasonable_expectations=False,
            answer_changes_oracle=True,
            answerer_has_authority=None,
        )
        self.assertEqual(route, "repository-established")

    def test_unresolved_oracle_routes_to_structured_question(self) -> None:
        self.assertTrue(hasattr(artifacts, "route_intent_decision"))
        route = artifacts.route_intent_decision(
            evidence_resolves=False,
            multiple_reasonable_expectations=True,
            answer_changes_oracle=True,
            answerer_has_authority=True,
        )
        self.assertEqual(route, "ask-structured-question")

    def test_unknown_answer_authority_offers_defer_to_specification_owner(self) -> None:
        self.assertTrue(hasattr(artifacts, "decision_options"))
        options = artifacts.decision_options(
            ["Preserve current behavior", "Adopt proposed behavior"],
            answerer_has_authority=None,
        )
        self.assertIn("Defer / confirm with specification owner", options)

    def test_benchmark_assumption_is_not_user_confirmed_specification(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "intent-contract.schema.json").read_text(encoding="utf-8")
        )
        provenance = schema["$defs"]["decision"]["properties"]["provenance"]["enum"]
        self.assertIn("reviewer-selected-benchmark-assumption", provenance)


class PersistentSideEffectGateTest(unittest.TestCase):
    def test_memory_writes_require_separate_explicit_authorization(self) -> None:
        socratic = (ROOT / "skills" / "socratic" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(
            "Never write memory, profile, or persistent learning files unless the user explicitly requests that separate persistent side effect.",
            socratic,
        )
        self.assertIn(
            "Artifact retention does not authorize memory or profile writes.",
            socratic,
        )

    def test_report_records_repository_external_persistent_writes(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "mutation-report.schema.json").read_text(encoding="utf-8")
        )
        self.assertIn("persistent_side_effects", schema["required"])
        effects = schema["properties"]["persistent_side_effects"]
        self.assertIn("writes", effects["required"])
        self.assertIn("authorization", effects["properties"])


class TerminalBlockedPreflightTest(unittest.TestCase):
    def test_english_and_japanese_skills_fix_the_terminal_blocked_sequence(self) -> None:
        english = (ROOT / "skills/socratic/SKILL.md").read_text(encoding="utf-8")
        japanese = (ROOT / "docs/ja/skills/socratic.md").read_text(encoding="utf-8")
        english_rules = (
            "The current Socratic run terminates immediately.",
            "Do not run repository-defined commands or tests.",
            "Do not invoke Maieutic or Elenchus.",
            "Do not reuse findings from the conversation or previous runs.",
            "Do not render `Review This`, `We Verified`, `Still at Risk`, or `Copy-ready Comments`.",
            "Do not offer Stryker, Apply tests, or another mutation path.",
            "Output only the blocked reason and the missing Host capability.",
        )
        japanese_rules = (
            "現在のSocratic Runを直ちに終了する。",
            "Repository定義のCommandまたはTestを実行しない。",
            "MaieuticまたはElenchusを呼び出さない。",
            "会話または以前のRunのFindingを再利用しない。",
            "`Review This`、`We Verified`、`Still at Risk`、`Copy-ready Comments`をRenderしない。",
            "Stryker、Apply tests、別のMutation Pathを提示しない。",
            "Blocked Reasonと不足しているHost Capabilityだけを出力する。",
        )
        for rule in english_rules:
            self.assertIn(rule, english)
        for rule in japanese_rules:
            self.assertIn(rule, japanese)


if __name__ == "__main__":
    unittest.main()
