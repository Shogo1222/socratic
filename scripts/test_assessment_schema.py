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
        self.assertEqual(self.report["properties"]["version"]["const"], 4)
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


if __name__ == "__main__":
    unittest.main()
