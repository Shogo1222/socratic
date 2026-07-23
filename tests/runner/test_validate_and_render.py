#!/usr/bin/env python3
import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tests.support import ROOT, load_module


MODULE_PATH = ROOT / "skills" / "socratic" / "scripts" / "validate_and_render.py"
validate_and_render = load_module("validate_and_render", MODULE_PATH)


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

    def test_false_primary_write_claim_requires_verified_protection_or_monitor(self) -> None:
        contract = {"status": "confirmed", "decisions": [], "unresolved": []}
        report = {
            "write_mode": "review-only",
            "intent_contract": {"status": "confirmed"},
            "mutations": [],
            "unresolved": [],
            "isolation": {
                "execution_strategy": "comparison-only",
                "primary_root": "/primary",
                "sandbox_root": "/sandbox",
                "host_protection": {"verified": False},
                "write_monitor": {"verified": False},
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

    def test_artifact_renderer_emits_only_strict_json_code_block(self) -> None:
        rendered = validate_and_render.render_artifact_json({"b": 2, "a": 1})
        self.assertEqual(rendered, '```json\n{\n  "a": 1,\n  "b": 2\n}\n```\n')

    def test_canonical_hash_is_renderer_stdout_hash(self) -> None:
        review = {
            "review_this": [], "we_verified": [], "still_at_risk": [],
            "copy_ready_comments": [],
        }
        expected = hashlib.sha256(
            validate_and_render.render_review(review).encode("utf-8")
        ).hexdigest()
        self.assertEqual(len(expected), 64)

    @unittest.skipUnless(
        importlib.util.find_spec("jsonschema") and importlib.util.find_spec("referencing"),
        "schema validation dependencies unavailable",
    )
    def test_report_draft_rejects_attestation_fields(self) -> None:
        draft = {
            "version": 1,
            "mode": "harden",
            "baseline": {
                "command": "test", "status": "green", "attempts": 1,
                "stable_tests": ["test"], "excluded_tests": [],
            },
            "assessment": None,
            "mutations": [],
            "not_challenged": [],
            "test_changes": [],
            "test_handoff": None,
            "authorized_workspace_changes": [],
            "persistent_side_effects": {
                "authorization": "not-requested", "writes": [],
            },
            "run": {"id": "agent-authored"},
        }
        with self.assertRaisesRegex(
            validate_and_render.ArtifactError, "Additional properties"
        ):
            validate_and_render.validate_document(
                draft, "mutation-report-draft.schema.json", ROOT / "schemas"
            )

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

    def test_direct_cli_is_disabled_in_favor_of_mandatory_run_entrypoint(self) -> None:
        self.assertEqual(validate_and_render.main([]), 2)

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
        review = json.loads(
            (ROOT / "demo" / "subscription_renewal" / "canonical-review.json").read_text(
                encoding="utf-8"
            )
        )
        validate_and_render.validate_with_schemas(contract, report, review, ROOT / "schemas")

    @unittest.skipUnless(
        importlib.util.find_spec("jsonschema") and importlib.util.find_spec("referencing"),
        "schema validation dependencies unavailable",
    )
    def test_schema_rejects_infrastructure_failure_claimed_as_killed(self) -> None:
        report = json.loads(
            (
                ROOT
                / "demo"
                / "subscription_renewal"
                / "expected-elenchus-report.json"
            ).read_text(encoding="utf-8")
        )
        mutation = report["mutations"][0]
        mutation["outcome_interpretation"] = {
            "kind": "infrastructure-failure",
            "reason": "The test runner failed before collecting assertions.",
        }
        with self.assertRaisesRegex(
            validate_and_render.ArtifactError, "behavioral-failure"
        ):
            validate_and_render.validate_document(
                mutation, "mutation-result.schema.json", ROOT / "schemas"
            )


if __name__ == "__main__":
    unittest.main()
