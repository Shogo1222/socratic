#!/usr/bin/env python3
"""Stable Golden Paths for the four Socratic Review Types.

These scenarios intentionally assert semantic state, not model prose or the
exact ordering of internal commands. Live model dogfooding belongs in a
separate, non-blocking suite.
"""

import json
import unittest
from pathlib import Path

from tests.support import ROOT, load_module

SCENARIOS = Path(__file__).with_name("scenarios")
EXPECTED_REVIEW_TYPES = {
    "Bug Fix Review",
    "Feature Review",
    "Refactor Guard",
    "Test Assessment",
}
EXPECTED_MODES = {
    "Bug Fix Review": "harden",
    "Feature Review": "harden",
    "Refactor Guard": "catch",
    "Test Assessment": "assessment",
}

host = load_module("claude_host_scenario_e2e", ROOT / "scripts" / "claude_host.py")
artifacts = load_module(
    "validate_and_render_scenario_e2e",
    ROOT / "skills" / "socratic" / "scripts" / "validate_and_render.py",
)


def load_scenarios() -> list[dict[str, object]]:
    return [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(SCENARIOS.glob("*.json"))
    ]


class ReviewTypeGoldenPathTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scenarios = load_scenarios()

    def test_exactly_one_golden_path_exists_for_each_review_type(self) -> None:
        review_types = [scenario["review_type"] for scenario in self.scenarios]
        self.assertEqual(len(review_types), 4)
        self.assertEqual(set(review_types), EXPECTED_REVIEW_TYPES)
        self.assertEqual(len(review_types), len(set(review_types)))

    def test_host_recommends_the_scenario_review_type(self) -> None:
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario["id"]):
                recommendation = host.recommend_review_type(
                    {"head_root": str(ROOT), "title": scenario["title"]},
                    str(scenario["prompt"]),
                )
                self.assertEqual(recommendation, scenario["review_type"])

    def test_each_scenario_routes_intent_and_elenchus_semantically(self) -> None:
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario["id"]):
                intent = scenario["intent"]
                route = artifacts.route_intent_decision(
                    evidence_resolves=intent["evidence_resolves"],
                    multiple_reasonable_expectations=intent["multiple_reasonable_expectations"],
                    answer_changes_oracle=intent["answer_changes_oracle"],
                    answerer_has_authority=intent["answerer_has_authority"],
                )
                self.assertEqual(route, intent["expected_route"])
                self.assertEqual(
                    scenario["workflow"]["elenchus_mode"],
                    EXPECTED_MODES[scenario["review_type"]],
                )

    def test_feature_waits_for_the_answer_before_challenging_the_oracle(self) -> None:
        scenario = self._scenario("Feature Review")
        contract_id = scenario["intent"]["contract_id"]
        unresolved = {
            "status": "needs-decision",
            "decisions": [{"id": contract_id}],
            "unresolved": [
                {
                    "id": "UNR-001",
                    "statement": scenario["intent"]["question"],
                    "test_impact": contract_id,
                }
            ],
        }
        with self.assertRaises(artifacts.ArtifactError):
            artifacts.assert_elenchus_allowed(unresolved, [contract_id])

        confirmed = {
            "status": scenario["workflow"]["contract_status_after_answer"],
            "decisions": [
                {
                    "id": contract_id,
                    "statement": scenario["intent"]["answer"],
                    "provenance": scenario["intent"]["answer_provenance"],
                }
            ],
            "unresolved": [],
        }
        artifacts.assert_elenchus_allowed(confirmed, [contract_id])
        self.assertEqual(confirmed["decisions"][0]["provenance"], "user-confirmed")

    def test_refactor_guard_surfaces_a_subtle_difference_without_prejudging_it(self) -> None:
        scenario = self._scenario("Refactor Guard")
        workflow = scenario["workflow"]
        self.assertNotEqual(workflow["base_observation"], workflow["head_observation"])
        self.assertTrue(workflow["difference_requires_human_decision"])
        self.assertEqual(scenario["intent"]["expected_route"], "ask-structured-question")
        self.assertEqual(workflow["classification_after_answer"], "strong-catch")
        self.assertEqual(scenario["intent"]["answer_provenance"], "user-confirmed")

    def test_assessment_does_not_confuse_a_passing_test_with_protection(self) -> None:
        scenario = self._scenario("Test Assessment")
        workflow = scenario["workflow"]
        self.assertEqual(workflow["baseline_result"], "passed")
        self.assertEqual(workflow["realistic_mutation_result"], "survived")
        self.assertFalse(workflow["existing_protection"])
        self.assertFalse(workflow["apply_missing_tests"])

    def test_all_golden_paths_preserve_primary_and_cleanup(self) -> None:
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario["id"]):
                expected = scenario["expected"]
                self.assertEqual(expected["terminal_status"], "complete")
                self.assertFalse(expected["primary_written_during_run"])
                self.assertTrue(expected["sandbox_destroyed"])

    def _scenario(self, review_type: str) -> dict[str, object]:
        return next(
            scenario for scenario in self.scenarios if scenario["review_type"] == review_type
        )


if __name__ == "__main__":
    unittest.main()
