#!/usr/bin/env python3
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "skills" / "socratic" / "scripts" / "validate_and_render.py"
SPEC = importlib.util.spec_from_file_location("validate_and_render", MODULE_PATH)
assert SPEC and SPEC.loader
validate_and_render = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validate_and_render
SPEC.loader.exec_module(validate_and_render)


class ValidateAndRenderTest(unittest.TestCase):
    def test_rejects_broken_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            path.write_text('{"broken": "quote}', encoding="utf-8")
            with self.assertRaises(validate_and_render.ArtifactError):
                validate_and_render.load_strict_json(path)

    def test_cross_validation_rejects_unknown_contract_id(self) -> None:
        contract = {"decisions": [{"id": "DEC-001"}], "unresolved": []}
        report = {
            "write_mode": "review-only",
            "mutations": [{"id": "MUT-001", "contract_ids": ["DEC-999"]}],
            "unresolved": [],
            "isolation": {
                "execution_strategy": "prebuilt-mutant",
                "primary_root": "/primary",
                "sandbox_root": "/sandbox",
                "mutation_targets": [],
            },
            "postflight": {
                "primary_written_during_run": False,
                "production_mutation_free": True,
                "sandbox_destroyed": True,
            },
        }
        with self.assertRaises(validate_and_render.ArtifactError):
            validate_and_render.validate_cross_artifact(contract, report)

    def test_cross_validation_rejects_primary_write(self) -> None:
        contract = {"decisions": [], "unresolved": []}
        report = {
            "write_mode": "review-only",
            "mutations": [],
            "unresolved": [],
            "isolation": {
                "execution_strategy": "prebuilt-mutant",
                "primary_root": "/primary",
                "sandbox_root": "/sandbox",
                "mutation_targets": [],
            },
            "postflight": {
                "primary_written_during_run": True,
                "production_mutation_free": True,
                "sandbox_destroyed": True,
            },
        }
        with self.assertRaises(validate_and_render.ArtifactError):
            validate_and_render.validate_cross_artifact(contract, report)

    def test_guarded_mutation_requires_target_evidence(self) -> None:
        contract = {"decisions": [{"id": "DEC-001"}], "unresolved": []}
        report = {
            "write_mode": "review-only",
            "mutations": [{"id": "MUT-001", "contract_ids": ["DEC-001"]}],
            "unresolved": [],
            "isolation": {
                "execution_strategy": "guarded-file-write",
                "primary_root": "/primary",
                "sandbox_root": "/sandbox",
                "mutation_targets": [],
            },
            "postflight": {
                "primary_written_during_run": False,
                "production_mutation_free": True,
                "sandbox_destroyed": True,
            },
        }
        with self.assertRaises(validate_and_render.ArtifactError):
            validate_and_render.validate_cross_artifact(contract, report)

    def test_renders_exactly_four_blocks(self) -> None:
        review = {
            "review_this": [],
            "we_verified": ["A verified behavior"],
            "still_at_risk": ["An excluded boundary"],
            "copy_ready_comments": [
                {
                    "tag": "Test gap",
                    "file": "src/example.py",
                    "line": 12,
                    "body": "Please cover the boundary.",
                    "evidence": "The boundary incident survived.",
                }
            ],
        }
        rendered = validate_and_render.render_review(review)
        self.assertEqual(
            [line for line in rendered.splitlines() if line.endswith(":")],
            ["Review This:", "We Verified:", "Still at Risk:", "Copy-ready Comments:"],
        )
        self.assertTrue(rendered.startswith("Review This:\n"))
        self.assertTrue(rendered.endswith("Evidence: The boundary incident survived.\n"))

    @unittest.skipUnless(
        importlib.util.find_spec("jsonschema") and importlib.util.find_spec("referencing"),
        "schema validation dependencies unavailable",
    )
    def test_validates_complete_demo_artifacts(self) -> None:
        contract = json.loads(
            (ROOT / "demo" / "subscription_renewal" / "intent-contract.json").read_text(
                encoding="utf-8"
            )
        )
        report = json.loads(
            (
                ROOT
                / "demo"
                / "subscription_renewal"
                / "expected-elenchus-report.json"
            ).read_text(encoding="utf-8")
        )
        review = {
            "review_this": [],
            "we_verified": ["Three incidents were detected by tests existing at run start"],
            "still_at_risk": [],
            "copy_ready_comments": [],
        }
        validate_and_render.validate_with_schemas(contract, report, review, ROOT / "schemas")


if __name__ == "__main__":
    unittest.main()
