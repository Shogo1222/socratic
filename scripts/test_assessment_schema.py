#!/usr/bin/env python3
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class AssessmentSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.report = json.loads(
            (ROOT / "schemas" / "mutation-report.schema.json").read_text(encoding="utf-8")
        )
        self.result = json.loads(
            (ROOT / "schemas" / "mutation-result.schema.json").read_text(encoding="utf-8")
        )

    def test_assessment_mode_is_versioned_and_required(self) -> None:
        self.assertEqual(self.report["properties"]["version"]["const"], 8)
        self.assertIn("run", self.report["required"])
        self.assertIn("assessment", self.report["required"])
        self.assertIn("assessment", self.report["properties"]["mode"]["enum"])
        self.assertIn("assessment", self.result["properties"]["mode"]["enum"])

    def test_comparison_classifications_are_complete(self) -> None:
        assessment = self.report["properties"]["assessment"]["oneOf"][1]
        comparison = assessment["properties"]["comparisons"]["items"]
        self.assertEqual(
            set(comparison["properties"]["classification"]["enum"]),
            {
                "existing-protection",
                "incremental-protection",
                "protection-regression",
                "unprotected",
                "not-comparable",
                "inconclusive",
            },
        )

    def test_isolation_and_run_time_write_evidence_are_required(self) -> None:
        self.assertIn("isolation", self.report["required"])
        isolation = self.report["properties"]["isolation"]
        self.assertEqual(
            set(isolation["required"]),
            {
                "execution_strategy",
                "primary_root",
                "sandbox_root",
                "host_protection",
                "write_monitor",
                "mutation_targets",
                "write_events",
            },
        )
        postflight = self.report["properties"]["postflight"]
        self.assertIn("primary_written_during_run", postflight["required"])
        self.assertIn("primary_final_hash_unchanged", postflight["required"])
        self.assertIn("sandbox_destroyed", postflight["required"])

    def test_killed_result_requires_contract_violation_attribution(self) -> None:
        self.assertIn("observed_failure_reason", self.result["required"])
        self.assertIn("contract_violation_observed", self.result["required"])
        killed_rule = next(
            rule["then"]["properties"]
            for rule in self.result["allOf"]
            if "contract_violation_observed"
            in rule.get("then", {}).get("properties", {})
        )
        self.assertEqual(killed_rule["contract_violation_observed"]["const"], True)
        self.assertEqual(killed_rule["observed_failure_reason"]["minLength"], 1)

    def test_report_requires_canonical_and_persistent_side_effect_ledgers(self) -> None:
        self.assertIn("canonical_output", self.report["required"])
        self.assertIn("persistent_side_effects", self.report["required"])
        self.assertIn("execution_evidence", self.report["required"])
        self.assertEqual(
            self.report["properties"]["execution_evidence"]["properties"]["source"][
                "const"
            ],
            "host-ledger",
        )


if __name__ == "__main__":
    unittest.main()
