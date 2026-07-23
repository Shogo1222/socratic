#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import ROOT, load_module


SKILL_SCRIPTS = ROOT / "skills" / "socratic" / "scripts"
if str(SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS))
RUNNER = load_module("run_experiment_under_test", SKILL_SCRIPTS / "run_experiment.py")


class RunExperimentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        (self.source / "tests").mkdir(parents=True)
        (self.source / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (self.source / "calculator.py").write_text(
            "def is_positive(value):\n"
            "    return value > 0\n",
            encoding="utf-8",
        )
        (self.source / "tests" / "test_calculator.py").write_text(
            "import os\n"
            "import unittest\n"
            "from calculator import is_positive\n"
            "\n"
            "class CalculatorTest(unittest.TestCase):\n"
            "    def test_positive(self):\n"
            "        self.assertTrue(is_positive(1))\n"
            "\n"
            "    def test_zero(self):\n"
            "        self.assertFalse(is_positive(0))\n"
            "\n"
            "    def test_credentials_are_absent(self):\n"
            "        self.assertNotIn('SOCRATIC_TEST_SECRET', os.environ)\n",
            encoding="utf-8",
        )
        self.plan_path = self.root / "plan.json"
        self.evidence_path = self.root / "evidence.json"

    def make_plan(self, mutations: list[dict] | None = None) -> dict:
        target = self.source / "calculator.py"
        if mutations is None:
            mutations = [
                {
                    "id": "MUT-001",
                    "contract_ids": ["INV-001"],
                    "accident": "Zero is treated as positive.",
                    "oracle": "test_zero fails.",
                    "targets": [
                        {
                            "path": "calculator.py",
                            "preimage_sha256": "runner-computed",
                            "operations": [
                                {
                                    "type": "replace-exact",
                                    "before": "return value > 0",
                                    "after": "return True",
                                }
                            ],
                        }
                    ],
                },
                {
                    "id": "MUT-002",
                    "contract_ids": ["INV-001"],
                    "accident": "Positive values are rejected.",
                    "oracle": "test_positive fails.",
                    "targets": [
                        {
                            "path": "calculator.py",
                            "preimage_sha256": "runner-computed",
                            "operations": [
                                {
                                    "type": "replace-exact",
                                    "before": "return value > 0",
                                    "after": "return False",
                                }
                            ],
                        }
                    ],
                },
            ]
        return {
            "version": 1,
            "source": {"sha256": "runner-computed"},
            "profile": {
                "name": "python-unittest",
                "dependency_policy": {"mode": "use-existing"},
                "selection": {
                    "modules": ["tests.test_calculator"],
                    "classes": [],
                    "methods": [],
                },
            },
            "round": {"baseline": "full", "timeout_seconds": 10},
            "mutations": mutations,
        }

    def write_plan(self, plan: dict) -> None:
        self.plan_path.write_text(json.dumps(plan), encoding="utf-8")

    def test_assess_runs_baseline_and_fresh_mutations_then_cleans_up(self) -> None:
        self.write_plan(self.make_plan())
        source_before = RUNNER.source_digest(self.source)
        run_root = self.root / "disposable-run"

        with patch.dict(os.environ, {"SOCRATIC_TEST_SECRET": "must-not-leak"}), patch.object(
            RUNNER.tempfile, "mkdtemp", return_value=str(run_root)
        ):
            evidence = RUNNER.assess(self.source, self.plan_path, self.evidence_path)

        self.assertEqual(evidence["baseline"]["outcome"], "passed")
        self.assertEqual(
            [mutation["id"] for mutation in evidence["mutations"]],
            ["MUT-001", "MUT-002"],
        )
        self.assertEqual(
            [mutation["execution"]["outcome"] for mutation in evidence["mutations"]],
            ["failed", "failed"],
        )
        self.assertIn(
            "test_zero", " ".join(evidence["mutations"][0]["execution"]["failed_tests"])
        )
        self.assertIn(
            "test_positive",
            " ".join(evidence["mutations"][1]["execution"]["failed_tests"]),
        )
        self.assertEqual(evidence["backend"], {"kind": "local-copy", "attested": False})
        self.assertIsNone(evidence["signature"])
        self.assertEqual(evidence["cleanup"], {"completed": True, "remaining_paths": []})
        self.assertFalse(run_root.exists())
        self.assertEqual(RUNNER.source_digest(self.source), source_before)
        self.assertEqual(
            json.loads(self.evidence_path.read_text(encoding="utf-8")), evidence
        )

    def test_guarded_entrypoint_exposes_one_operation_assess(self) -> None:
        self.write_plan(self.make_plan())
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SKILL_SCRIPTS / "run_review.py"),
                "assess",
                "--source-root",
                str(self.source),
                "--plan",
                str(self.plan_path),
                "--evidence",
                str(self.evidence_path),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        rendered = json.loads(completed.stdout)
        self.assertEqual(rendered["baseline"]["outcome"], "passed")
        self.assertEqual(len(rendered["mutations"]), 2)
        self.assertTrue(rendered["cleanup"]["completed"])

    def test_baseline_failure_stops_before_mutation(self) -> None:
        test_path = self.source / "tests" / "test_calculator.py"
        test_path.write_text(
            test_path.read_text(encoding="utf-8")
            + "\nclass BrokenBaselineTest(unittest.TestCase):\n"
            "    def test_broken(self):\n"
            "        self.fail('baseline is red')\n",
            encoding="utf-8",
        )
        self.write_plan(self.make_plan())

        evidence = RUNNER.assess(self.source, self.plan_path, self.evidence_path)

        self.assertEqual(evidence["baseline"]["outcome"], "failed")
        self.assertEqual(evidence["mutations"], [])
        self.assertTrue(evidence["cleanup"]["completed"])

    def test_timeout_is_structured_and_stops_before_mutation(self) -> None:
        (self.source / "tests" / "test_calculator.py").write_text(
            "import time\n"
            "import unittest\n"
            "\n"
            "class SlowTest(unittest.TestCase):\n"
            "    def test_slow(self):\n"
            "        time.sleep(5)\n",
            encoding="utf-8",
        )
        plan = self.make_plan()
        plan["round"]["timeout_seconds"] = 1
        self.write_plan(plan)

        evidence = RUNNER.assess(self.source, self.plan_path, self.evidence_path)

        self.assertEqual(evidence["baseline"]["outcome"], "timeout")
        self.assertIsNone(evidence["baseline"]["exit_code"])
        self.assertEqual(evidence["mutations"], [])
        self.assertTrue(evidence["cleanup"]["completed"])

    def test_cleanup_failure_is_reported_in_evidence(self) -> None:
        self.write_plan(self.make_plan())
        run_root = self.root / "cleanup-failure"
        real_rmtree = RUNNER.shutil.rmtree

        with patch.object(RUNNER.tempfile, "mkdtemp", return_value=str(run_root)), patch.object(
            RUNNER.shutil, "rmtree", side_effect=OSError("busy")
        ):
            evidence = RUNNER.assess(
                self.source, self.plan_path, self.evidence_path
            )

        self.assertEqual(
            evidence["cleanup"],
            {"completed": False, "remaining_paths": [str(run_root)]},
        )
        real_rmtree(run_root)

    def test_preimage_mismatch_fails_without_writing_evidence(self) -> None:
        plan = self.make_plan()
        plan["mutations"][0]["targets"][0]["preimage_sha256"] = "0" * 64
        self.write_plan(plan)
        run_root = self.root / "failed-run"

        with patch.object(RUNNER.tempfile, "mkdtemp", return_value=str(run_root)):
            with self.assertRaisesRegex(RUNNER.ExperimentError, "preimage hash mismatch"):
                RUNNER.assess(self.source, self.plan_path, self.evidence_path)

        self.assertFalse(run_root.exists())
        self.assertFalse(self.evidence_path.exists())

    def test_rejects_evidence_inside_source_or_existing_output(self) -> None:
        self.write_plan(self.make_plan())
        with self.assertRaisesRegex(RUNNER.ExperimentError, "outside the source"):
            RUNNER.assess(
                self.source, self.plan_path, self.source / "evidence.json"
            )

        self.evidence_path.write_text("existing", encoding="utf-8")
        with self.assertRaisesRegex(RUNNER.ExperimentError, "already exists"):
            RUNNER.assess(self.source, self.plan_path, self.evidence_path)

    def test_rejects_external_test_modules_and_duplicate_mutation_ids(self) -> None:
        external = self.make_plan()
        external["profile"]["selection"]["modules"] = ["unittest"]
        self.write_plan(external)
        with self.assertRaisesRegex(RUNNER.ExperimentError, "not in Source"):
            RUNNER.assess(self.source, self.plan_path, self.evidence_path)

        duplicate = self.make_plan()
        duplicate["mutations"][1]["id"] = "MUT-001"
        self.write_plan(duplicate)
        with self.assertRaisesRegex(RUNNER.ExperimentError, "IDs must be unique"):
            RUNNER.assess(self.source, self.plan_path, self.evidence_path)

    def test_source_digest_rejects_symlinks(self) -> None:
        link = self.source / "linked.py"
        try:
            link.symlink_to(self.source / "calculator.py")
        except OSError:
            self.skipTest("symlinks are unavailable")
        with self.assertRaisesRegex(RUNNER.ExperimentError, "symlink"):
            RUNNER.source_digest(self.source)


if __name__ == "__main__":
    unittest.main()
