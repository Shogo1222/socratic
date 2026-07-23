#!/usr/bin/env python3
from __future__ import annotations

import copy
import unittest

from tests.support import ROOT, load_module


VALIDATOR = load_module(
    "narrow_runner_validator",
    ROOT / "skills" / "socratic" / "scripts" / "validate_and_render.py",
)


def output(digest: str = "f" * 64) -> dict:
    return {"tail": "", "truncated": False, "sha256": digest}


def execution(*, outcome: str = "passed", failed_tests: list[str] | None = None) -> dict:
    result = {
        "outcome": outcome,
        "exit_code": (
            0 if outcome == "passed"
            else None if outcome in {"timeout", "runner-error"}
            else 1
        ),
        "failed_tests": [] if failed_tests is None else failed_tests,
        "duration_ms": 1,
        "stdout": output(),
        "stderr": output(),
    }
    if outcome == "runner-error":
        result["reason"] = "profile runtime dependency unavailable"
        result["missing_dependencies"] = ["jsonschema"]
        result["failed_tests"] = None
    return result


def plan() -> dict:
    return {
        "version": 1,
        "source": {"sha256": "a" * 64},
        "profile": {
            "name": "python-unittest",
            "dependency_policy": {"mode": "use-existing"},
            "selection": {
                "modules": ["tests.schema.test_assessment_schema"],
                "classes": [],
                "methods": [],
            },
        },
        "round": {"baseline": "full", "timeout_seconds": 60},
        "mutations": [
            {
                "id": "MUT-001",
                "contract_ids": ["INV-001"],
                "accident": "The validator accepts a report without assessment evidence.",
                "oracle": "The selected unittest fails for the missing evidence.",
                "targets": [
                    {
                        "path": "skills/socratic/scripts/validate_and_render.py",
                        "preimage_sha256": "b" * 64,
                        "operations": [
                            {
                                "type": "replace-exact",
                                "before": 'raise ArtifactError("invalid")',
                                "after": "return None",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def evidence() -> dict:
    return {
        "version": 1,
        "run": "a" * 32,
        "round": "ROUND-001",
        "source": {"sha256": "b" * 64},
        "plan_sha256": "c" * 64,
        "runner": {"version": "0.4.0-alpha.11", "sha256": "d" * 64},
        "profile": {"name": "python-unittest", "digest": "e" * 64},
        "runtime": {
            "implementation": "cpython",
            "version": "3.12.0",
            "executable_sha256": "9" * 64,
            "environment": "virtual-environment",
            "probe": "passed",
            "missing_dependencies": [],
        },
        "backend": {"kind": "local-copy", "attested": False},
        "baseline": execution(),
        "mutations": [
            {
                "id": "MUT-001",
                "changes": [
                    {
                        "path": "module.py",
                        "preimage_sha256": "1" * 64,
                        "postimage_sha256": "2" * 64,
                        "diff_tail": "-old\n+new\n",
                        "diff_truncated": False,
                        "diff_sha256": "3" * 64,
                    }
                ],
                "execution": execution(
                    outcome="failed",
                    failed_tests=["tests.test_module.ContractTest.test_contract"],
                ),
            }
        ],
        "cleanup": {"completed": True, "remaining_paths": []},
        "signature": None,
    }


def interpretation() -> dict:
    return {
        "version": 1,
        "interpretations": [
            {
                "mutation_ref": "MUT-001",
                "contract_refs": ["INV-001"],
                "accident_model": "The mutation removes contract enforcement.",
                "classification": "killed",
                "outcome": {
                    "kind": "behavioral-failure",
                    "reason": "The contract assertion failed.",
                    "test_refs": ["tests.test_module.ContractTest.test_contract"],
                },
            }
        ],
        "canonical_review": {
            "review_this": [],
            "we_verified": ["The existing test detected MUT-001."],
            "still_at_risk": [],
            "copy_ready_comments": [],
        },
    }


class NarrowRunnerSchemaTest(unittest.TestCase):
    def validate(self, document: dict, schema: str) -> None:
        VALIDATOR.validate_document(document, schema, ROOT / "schemas")

    def assert_invalid(self, document: dict, schema: str) -> None:
        with self.assertRaises(VALIDATOR.ArtifactError):
            self.validate(document, schema)

    def test_accepts_typed_python_unittest_plan(self) -> None:
        self.validate(plan(), "experiment-plan.schema.json")
        computed = plan()
        computed["source"]["sha256"] = "runner-computed"
        self.validate(computed, "experiment-plan.schema.json")

    def test_plan_rejects_shell_commands_and_unsafe_paths(self) -> None:
        command_plan = plan()
        command_plan["command"] = ["python", "-m", "unittest"]
        self.assert_invalid(command_plan, "experiment-plan.schema.json")

        traversal_plan = plan()
        traversal_plan["mutations"][0]["targets"][0]["path"] = "../primary.py"
        self.assert_invalid(traversal_plan, "experiment-plan.schema.json")

    def test_method_selection_requires_a_class(self) -> None:
        method_plan = plan()
        method_plan["profile"]["selection"]["methods"] = ["test_contract"]
        self.assert_invalid(method_plan, "experiment-plan.schema.json")

    def test_accepts_unsigned_local_copy_evidence(self) -> None:
        self.validate(evidence(), "evidence-bundle.schema.json")

    def test_accepts_baseline_failure_without_mutation_results(self) -> None:
        stopped = evidence()
        stopped["baseline"] = execution(
            outcome="failed", failed_tests=["tests.test_module.BaselineTest.test_red"]
        )
        stopped["mutations"] = []
        self.validate(stopped, "evidence-bundle.schema.json")

    def test_execution_outcome_must_match_exit_code(self) -> None:
        inconsistent = evidence()
        inconsistent["baseline"]["outcome"] = "passed"
        inconsistent["baseline"]["exit_code"] = 1
        self.assert_invalid(inconsistent, "evidence-bundle.schema.json")

    def test_accepts_structured_runtime_dependency_failure(self) -> None:
        unavailable = evidence()
        unavailable["runtime"]["probe"] = "failed"
        unavailable["runtime"]["missing_dependencies"] = ["jsonschema"]
        unavailable["baseline"] = execution(outcome="runner-error")
        unavailable["mutations"] = []
        self.validate(unavailable, "evidence-bundle.schema.json")

    def test_local_copy_cannot_claim_attestation_or_signature(self) -> None:
        claimed = evidence()
        claimed["backend"]["attested"] = True
        self.assert_invalid(claimed, "evidence-bundle.schema.json")

        signed = evidence()
        signed["signature"] = {
            "algorithm": "host-hmac-sha256",
            "host_adapter": "self-asserted",
            "evidence_sha256": "4" * 64,
            "issued_at": "2026-07-23T00:00:00Z",
            "expires_at": "2026-07-23T00:05:00Z",
            "value": "A" * 43,
        }
        self.assert_invalid(signed, "evidence-bundle.schema.json")

    def test_accepts_semantic_interpretation(self) -> None:
        self.validate(interpretation(), "interpretation.schema.json")
        prototype = interpretation()
        del prototype["canonical_review"]
        self.validate(prototype, "interpretation.schema.json")

    def test_interpretation_rejects_transport_evidence(self) -> None:
        claimed = interpretation()
        claimed["interpretations"][0]["exit_code"] = 1
        self.assert_invalid(claimed, "interpretation.schema.json")

    def test_killed_requires_behavioral_failure_and_test_reference(self) -> None:
        invalid = copy.deepcopy(interpretation())
        invalid["interpretations"][0]["outcome"] = {
            "kind": "process-crash",
            "reason": "The interpreter crashed.",
            "test_refs": [],
        }
        self.assert_invalid(invalid, "interpretation.schema.json")


if __name__ == "__main__":
    unittest.main()
