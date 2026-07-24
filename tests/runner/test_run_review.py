#!/usr/bin/env python3
"""Fail-closed regression tests for the mandatory Socratic run entrypoint."""

import hashlib
import io
import json
import os
import sys
import tempfile
import subprocess
import time
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch

from tests.support import ROOT, load_module


MODULE = ROOT / "skills/socratic/scripts/run_review.py"


def load_runner():
    return load_module("socratic_run_review", MODULE)


class RunReviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load_runner()

    def make_repository(self, root: Path) -> Path:
        repository = root / "repository"
        (repository / ".git").mkdir(parents=True)
        app = repository / "packages/app"
        app.mkdir(parents=True)
        (app / "source.ts").write_text("original\n")
        for index in range(1, 4):
            (app / f"mutant-{index}.ts").write_text(f"mutant {index}\n")
        (repository / ".env").write_text("SECRET=never-copy\n")
        (repository / "node_modules").mkdir()
        return repository

    def host(self, storage: Path):
        runner = self.runner

        class FixtureHost:
            def begin_review_run(self, primary_root: Path):
                return runner.HostGrant(
                    adapter_id="fixture-host-v1",
                    run_id="a" * 32,
                    run_nonce="host-issued-nonce-" + "b" * 32,
                    storage_root=storage,
                    protection_mode="os-read-only",
                    protection_details="fixture host denied a Primary write probe",
                    review_type={
                        "recommended": "Bug Fix Review",
                        "options": list(runner.REVIEW_TYPES),
                        "requires_human_confirmation": True,
                    },
                )

        return FixtureHost()

    def ready(self, root: Path, repository: Path):
        storage = root / "host-storage"
        storage.mkdir()
        return self.runner.preflight_with_host(repository, self.host(storage))

    def report_draft(self) -> dict:
        report = json.loads(
            (ROOT / "demo/subscription_renewal/expected-elenchus-report.json").read_text()
        )
        draft = {
            "version": 1,
            "mode": report["mode"],
            "baseline": report["baseline"],
            "assessment": report["assessment"],
            "mutations": report["mutations"],
            "not_challenged": report["not_challenged"],
            "test_changes": report["test_changes"],
            "test_handoff": report["test_handoff"],
            "authorized_workspace_changes": [],
            "persistent_side_effects": report["persistent_side_effects"],
        }
        for change in draft["test_changes"]:
            if change["disposition"] == "applied":
                change["disposition"] = "existing"
        return draft

    def stage_demo_artifacts(
        self, manifest: dict, *, report=None
    ) -> tuple[dict, dict]:
        artifact_root = Path(manifest["artifact_root"])
        contract = json.loads(
            (ROOT / "demo/subscription_renewal/intent-contract.json").read_text()
        )
        review = json.loads(
            (ROOT / "demo/subscription_renewal/canonical-review.json").read_text()
        )
        documents = {
            "contract": contract,
            "report": report if report is not None else self.report_draft(),
            "review": review,
        }
        staged = self.runner._artifact_index(manifest)["artifacts"]
        for kind, document in documents.items():
            if kind in staged:
                continue
            (artifact_root / self.runner.ARTIFACT_FILES[kind]).write_text(
                json.dumps(document), encoding="utf-8"
            )
            self.runner.stage_artifact(
                Path(manifest["host"]["storage_root"]) / "run-manifest.json",
                kind,
                ROOT / "schemas",
            )
        return contract, review

    def stage_contract(self, manifest: dict, contract=None) -> dict:
        document = contract or json.loads(
            (ROOT / "demo/subscription_renewal/intent-contract.json").read_text()
        )
        artifact = Path(manifest["artifact_root"]) / self.runner.ARTIFACT_FILES["contract"]
        artifact.write_text(json.dumps(document), encoding="utf-8")
        self.runner.stage_artifact(
            Path(manifest["host"]["storage_root"]) / "run-manifest.json",
            "contract",
            ROOT / "schemas",
        )
        return document

    def anchored_challenge(self, mutation_id: str, after: str) -> dict:
        return {
            "id": mutation_id,
            "contract_ids": ["DEC-001"],
            "accident": f"{mutation_id} changes the established value",
            "expected_detection": "The focused test detects the changed value",
            "severity": "high",
            "likelihood": "medium",
            "code_location": "packages/app/source.ts:1",
            "mutation": {
                "kind": "replace-exact",
                "relative_path": "packages/app/source.ts",
                "before": "original\n",
                "after": after,
            },
        }

    def test_standalone_preflight_is_blocked_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            before = set(root.iterdir())
            result = self.runner.blocked_preflight(repository)
            self.assertEqual(
                result,
                {
                    "status": "blocked",
                    "terminal": True,
                    "next_action": "stop",
                    "primary_root": str(repository.resolve()),
                    "blocked_reason": (
                        "a trusted HostAdapter capability is required; "
                        "self-asserted JSON is not accepted"
                    ),
                    "missing_host_capability": "trusted HostAdapter capability",
                },
            )
            self.assertIn("self-asserted JSON is not accepted", result["blocked_reason"])
            self.assertEqual(set(root.iterdir()), before)

    def test_host_preflight_creates_every_run_path_outside_primary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            for path in (
                manifest_path,
                Path(manifest["ledger_path"]),
                Path(manifest["sandbox_root"]),
                Path(manifest["dependency_root"]),
                Path(manifest["host"]["storage_root"]),
                Path(manifest["artifact_root"]),
                Path(manifest["artifact_index_path"]),
            ):
                self.assertFalse(path.resolve().is_relative_to(repository.resolve()))
            sandbox = Path(manifest["sandbox_root"])
            self.assertTrue((sandbox / ".socratic-disposable").is_file())
            self.assertFalse((sandbox / ".env").exists())
            self.assertFalse((sandbox / "node_modules").exists())

    def test_host_storage_inside_primary_is_rejected_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            storage = repository / "host-storage"
            storage.mkdir()
            with self.assertRaises(self.runner.RunGateError):
                self.runner.preflight_with_host(repository, self.host(storage))
            self.assertEqual(list(storage.iterdir()), [])

    def test_manifest_rejects_dependency_layer_outside_disposable_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            outside = root / "other-host-directory"
            outside.mkdir()
            manifest["dependency_root"] = str(outside)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(
                self.runner.RunGateError,
                "dependency layer must be inside the disposable sandbox",
            ):
                self.runner._ready_manifest(manifest_path)

    def test_manifest_write_failure_cleans_new_sandbox_and_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            storage = root / "host-storage"
            storage.mkdir()
            (storage / "run-manifest.json").write_text("host-owned existing file\n")
            with self.assertRaises(FileExistsError):
                self.runner.preflight_with_host(repository, self.host(storage))
            self.assertFalse((storage / "mutation-ledger.jsonl").exists())
            self.assertEqual(
                [path.name for path in storage.iterdir()], ["run-manifest.json"]
            )

    def test_execute_requires_phase_and_registered_mutation_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            with self.assertRaises(self.runner.RunGateError):
                self.runner.execute(manifest_path, "mutation", None, [sys.executable, "-c", "pass"], 10)
            with self.assertRaises(self.runner.RunGateError):
                self.runner.execute(manifest_path, "mutation", "MUT-001", [sys.executable, "-c", "pass"], 10)
            self.runner.execute(
                manifest_path, "baseline", None, [sys.executable, "-c", "pass"], 10
            )
            self.stage_contract(manifest)
            self.runner.register_prebuilt(
                manifest_path, "MUT-001", ["DEC-001"], "packages/app/mutant-1.ts"
            )
            self.assertEqual(
                self.runner.execute(manifest_path, "mutation", "MUT-001", [sys.executable, "-c", "raise SystemExit(1)"], 10),
                1,
            )

    def test_mutants_branch_from_one_dependency_prepared_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            install = (
                "import pathlib; "
                "pathlib.Path('node_modules/example').mkdir(parents=True); "
                "pathlib.Path('node_modules/example/index.js').write_text('installed once')"
            )
            self.runner.execute(
                manifest_path, "baseline", None, [sys.executable, "-c", install], 10
            )
            self.stage_contract(manifest)
            first = self.runner.register_prebuilt(
                manifest_path, "MUT-001", ["DEC-001"], "packages/app/mutant-1.ts"
            )
            second = self.runner.register_prebuilt(
                manifest_path, "MUT-002", ["DEC-001"], "packages/app/mutant-2.ts"
            )
            with self.assertRaisesRegex(
                self.runner.RunGateError, "prepared snapshot is sealed"
            ):
                self.runner.execute(
                    manifest_path,
                    "baseline",
                    None,
                    [sys.executable, "-c", "pass"],
                    10,
                )
            first_root = Path(first["sandbox_root"])
            second_root = Path(second["sandbox_root"])
            prepared_root = Path(manifest["prepared_root"])
            self.assertNotEqual(first_root, second_root)
            for sandbox in (prepared_root, first_root, second_root):
                self.assertEqual(
                    (sandbox / "node_modules/example/index.js").read_text(),
                    "installed once",
                )
            (first_root / "packages/app/source.ts").write_text("changed only in MUT-001\n")
            self.assertEqual(
                (second_root / "packages/app/source.ts").read_text(), "original\n"
            )
            self.assertEqual(
                (prepared_root / "packages/app/source.ts").read_text(), "original\n"
            )
            self.assertEqual(
                (first_root / "node_modules/example").resolve(),
                (second_root / "node_modules/example").resolve(),
            )
            first_cache = first_root / "node_modules/.vite/results.json"
            first_cache.parent.mkdir()
            first_cache.write_text("MUT-001 cache\n")
            self.assertFalse(
                (second_root / "node_modules/.vite/results.json").exists()
            )
            (first_root / ".socratic-runtime/home/private.txt").write_text("first")
            self.assertFalse(
                (second_root / ".socratic-runtime/home/private.txt").exists()
            )
            prepared_events = [
                item
                for item in self.runner._ledger_events(manifest)
                if item.get("kind") == "prepared-snapshot"
            ]
            self.assertEqual(len(prepared_events), 1)

    def test_challenge_batch_runs_fresh_mutants_in_parallel_and_records_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            self.runner.probe_command(
                manifest_path,
                "CMD-001",
                [sys.executable, "-c", "import time; time.sleep(0.4)"],
                10,
            )
            self.stage_contract(manifest)
            challenges = [
                self.anchored_challenge(mutation_id, f"changed {index}\n")
                for index, mutation_id in enumerate(
                    ("MUT-001", "MUT-002", "MUT-003"), 1
                )
            ]
            plan_path = Path(manifest["artifact_root"]) / "challenge-plan.json"
            plan_path.write_text(json.dumps({
                "version": 2,
                "command_id": "CMD-001",
                "max_parallel": 3,
                "challenges": challenges,
            }))
            started = time.monotonic()
            result = self.runner.challenge_batch(
                manifest_path, ROOT / "schemas"
            )
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 1.0)
            self.assertEqual(
                [item["mutation_id"] for item in result["results"]],
                ["MUT-001", "MUT-002", "MUT-003"],
            )
            self.assertEqual(
                [item["outcome"] for item in result["results"]],
                ["passed", "passed", "passed"],
            )
            command_events = [
                item
                for item in self.runner._ledger_events(manifest)
                if item.get("kind") == "command" and item.get("phase") == "mutation"
            ]
            self.assertEqual(
                [item["mutation_id"] for item in command_events],
                ["MUT-001", "MUT-002", "MUT-003"],
            )
            self.assertEqual(
                len({item["sandbox_root"] for item in command_events}), 3
            )
            self.assertTrue(
                all(item["batch_plan_sha256"] == result["plan_sha256"]
                    for item in command_events)
            )

    def test_probe_cwd_is_recorded_and_reused_by_challenge_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            code = (
                "import os, pathlib; "
                "pathlib.Path('command-cwd.txt').write_text(os.getcwd())"
            )
            probe = self.runner.probe_command(
                manifest_path, "CMD-001", [sys.executable, "-c", code], 10,
                cwd_relative="packages/app",
            )
            self.assertEqual(probe["status"], "ready")
            validated = [
                item for item in self.runner._ledger_events(manifest)
                if item.get("kind") == "validated-command"
            ]
            self.assertEqual(validated[0]["cwd"], "packages/app")
            self.stage_contract(manifest)
            plan_path = Path(manifest["artifact_root"]) / "challenge-plan.json"
            plan_path.write_text(json.dumps({
                "version": 2,
                "command_id": "CMD-001",
                "max_parallel": 1,
                "challenges": [self.anchored_challenge("MUT-001", "changed 1\n")],
            }))
            result = self.runner.challenge_batch(manifest_path, ROOT / "schemas")
            self.assertEqual(result["results"][0]["outcome"], "passed")
            command_events = [
                item for item in self.runner._ledger_events(manifest)
                if item.get("kind") == "command" and item.get("phase") == "mutation"
            ]
            self.assertEqual(command_events[0]["cwd"], "packages/app")
            mutant_root = Path(command_events[0]["sandbox_root"])
            self.assertEqual(
                (mutant_root / "packages/app/command-cwd.txt").read_text(),
                str((mutant_root / "packages/app").resolve()),
            )

    def test_runbook_explains_ids_gates_and_next_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            document = self.runner.runbook(manifest_path)
            self.assertEqual(
                set(document["id_glossary"]), {"DEC", "INV", "FX", "UNR", "CMD", "MUT"}
            )
            for key in ("mission", "gates", "agent_edits", "runner_owns",
                        "hard_rules", "execution_plan", "announcement_rules"):
                self.assertIn(key, document)
            self.assertEqual(document["run_id"], manifest["run_id"])
            self.assertEqual(document["checkpoint"]["id"], "review-type")
            self.assertTrue(document["checkpoint"]["required_before_next"])
            self.assertEqual(
                document["checkpoint"]["recommended"], "Bug Fix Review"
            )
            self.assertIn("inspect", document["next"]["argv"])
            self.assertIn("diff", document["next"]["argv"])
            self.assertEqual(document["next"]["announce"], "Reviewing what changed")
            self.assertEqual(
                [step["id"] for step in document["execution_plan"]],
                ["inspect", "intent", "prepare", "baseline",
                 "challenge", "report", "cleanup"],
            )

    def test_probe_success_returns_exact_next_argv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            probe = self.runner.probe_command(
                manifest_path, "CMD-001", [sys.executable, "-c", "pass"], 10
            )
            argv = probe["next"]["argv"]
            self.assertIn("scaffold-plan", argv)
            self.assertIn(str(manifest_path), argv)

    def test_argument_mistakes_return_guided_invalid_command(self) -> None:
        stdout = io.StringIO()
        with patch.object(sys, "argv",
                          ["run_review.py", "scaffold-plan", "--command-id", "CMD-001"]):
            with redirect_stdout(stdout):
                code = self.runner.main()
        self.assertEqual(code, 2)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "invalid-command")
        self.assertIn("runbook", payload["error"])

    def test_probe_and_batch_expose_runner_timings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            prepared_dependency = (
                Path(manifest["prepared_root"]) / "node_modules/example/index.js"
            )
            prepared_dependency.parent.mkdir(parents=True)
            prepared_dependency.write_text("installed\n")
            with patch.object(
                self.runner,
                "_dependency_hash",
                wraps=self.runner._dependency_hash,
            ) as dependency_hash:
                probe = self.runner.probe_command(
                    manifest_path, "CMD-001", [sys.executable, "-c", "pass"], 10
                )
                self.assertEqual(dependency_hash.call_count, 1)
            for key in (
                "dependency_layer_move",
                "dependency_layer_hash",
                "source_snapshot_hash",
                "clone",
                "external_command",
            ):
                self.assertIn(key, probe["runner_timings_ms"])
            self.stage_contract(manifest)
            plan_path = Path(manifest["artifact_root"]) / "challenge-plan.json"
            plan_path.write_text(json.dumps({
                "version": 2,
                "command_id": "CMD-001",
                "max_parallel": 1,
                "challenges": [self.anchored_challenge("MUT-001", "changed\n")],
            }))
            with patch.object(
                self.runner,
                "_dependency_hash",
                wraps=self.runner._dependency_hash,
            ) as dependency_hash:
                result = self.runner.challenge_batch(manifest_path, ROOT / "schemas")
                self.assertEqual(dependency_hash.call_count, 0)
            for key in (
                "staleness_source_hash",
                "clones",
                "external_commands_window",
            ):
                self.assertIn(key, result["runner_timings_ms"])

    def test_probe_command_rejects_invalid_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            with self.assertRaises(self.runner.RunGateError):
                self.runner.probe_command(
                    manifest_path, "CMD-001", [sys.executable, "-c", "pass"], 10,
                    cwd_relative="../escape",
                )
            with self.assertRaises(self.runner.RunGateError):
                self.runner.probe_command(
                    manifest_path, "CMD-002", [sys.executable, "-c", "pass"], 10,
                    cwd_relative="missing-directory",
                )

    def test_challenge_batch_returns_compact_results_and_details_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            check = (
                "import pathlib, sys; "
                "text = pathlib.Path('packages/app/source.ts').read_text(); "
                "sys.stdout.write('checked ' + text); "
                "sys.exit(0 if text == 'original\\n' else 1)"
            )
            self.runner.probe_command(
                manifest_path, "CMD-001", [sys.executable, "-c", check], 10
            )
            self.stage_contract(manifest)
            survived_challenge = self.anchored_challenge("MUT-002", "changed\n")
            survived_challenge["mutation"] = {
                "kind": "replace-exact",
                "relative_path": "packages/app/mutant-1.ts",
                "before": "mutant 1\n",
                "after": "unrelated change\n",
            }
            plan_path = Path(manifest["artifact_root"]) / "challenge-plan.json"
            plan_path.write_text(json.dumps({
                "version": 2,
                "command_id": "CMD-001",
                "max_parallel": 2,
                "challenges": [
                    self.anchored_challenge("MUT-001", "broken\n"),
                    survived_challenge,
                ],
            }))
            result = self.runner.challenge_batch(manifest_path, ROOT / "schemas")
            killed, survived = result["results"]
            self.assertEqual(killed["outcome"], "failed")
            self.assertIn("checked broken", killed["stdout_tail"])
            self.assertEqual(survived["outcome"], "passed")
            self.assertNotIn("stdout_tail", survived)
            for entry in result["results"]:
                self.assertNotIn("stdout", entry)
                self.assertNotIn("stderr", entry)
                self.assertGreaterEqual(entry["duration_ms"], 0)
            details = json.loads(Path(result["details_path"]).read_text())
            self.assertEqual(
                [item["mutation_id"] for item in details["results"]],
                ["MUT-001", "MUT-002"],
            )
            self.assertIn("checked broken", details["results"][0]["stdout"])
            self.assertIn("checked original", details["results"][1]["stdout"])

    def test_resolve_inspect_kind_accepts_both_invocation_forms(self) -> None:
        resolve = self.runner._resolve_inspect_kind
        self.assertEqual(resolve(None, "diff"), "diff")
        self.assertEqual(resolve("file", None), "file")
        self.assertEqual(resolve("tests", "tests"), "tests")
        with self.assertRaisesRegex(self.runner.RunGateError, "two different kinds"):
            resolve("diff", "file")
        with self.assertRaisesRegex(self.runner.RunGateError, "inspect --kind diff"):
            resolve(None, None)

    def test_probe_command_rejects_malformed_id_with_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            with self.assertRaisesRegex(self.runner.RunGateError, "expected CMD-"):
                self.runner.probe_command(
                    manifest_path, "CMD1", [sys.executable, "-c", "pass"], 10
                )

    def test_scaffold_contract_generates_document_for_first_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            document = self.runner.scaffold_contract(manifest_path, ROOT / "schemas")
            artifact = (
                Path(manifest["artifact_root"]) / "intent-contract.draft.json"
            )
            self.assertFalse(artifact.exists())
            self.assertEqual(document["status"], "provisional")
            artifact.write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(json.loads(artifact.read_text()), document)
            with self.assertRaisesRegex(self.runner.RunGateError, "already exists"):
                self.runner.scaffold_contract(manifest_path, ROOT / "schemas")

    def test_scaffold_contract_cli_returns_runner_owned_field_guide(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            stdout = io.StringIO()
            with patch.object(sys, "argv", [
                "run_review.py",
                "scaffold-contract",
                "--manifest", str(manifest_path),
                "--schema-root", str(ROOT / "schemas"),
            ]), redirect_stdout(stdout):
                code = self.runner.main()
            self.assertEqual(code, 0)
            result = json.loads(stdout.getvalue())
            self.assertEqual(
                result["field_guide"]["coverage[*]"]["required_keys"],
                ["contract_id", "tests"],
            )
            self.assertEqual(
                result["document"]["coverage"], []
            )
            artifact = (
                Path(manifest["artifact_root"]) / "intent-contract.draft.json"
            )
            self.assertEqual(result["artifact_path"], str(artifact))
            self.assertFalse(artifact.exists())
            self.assertIn("Write exactly once", result["write_protocol"]["first_write"])
            self.assertIn("stage-artifact", result["next"]["argv"])

    def test_scaffold_guides_expose_required_shapes_and_enum_values(self) -> None:
        contract = self.runner.SCAFFOLD_FIELD_GUIDES["contract"]
        self.assertEqual(
            contract["coverage[*]"]["required_keys"],
            ["contract_id", "tests"],
        )
        self.assertIn(
            "repository-established",
            contract["decisions[*]"]["allowed_provenance"],
        )
        plan = self.runner.SCAFFOLD_FIELD_GUIDES["plan"]
        self.assertEqual(
            set(plan["challenges[*].mutation"]["variants"]),
            {"replace-exact", "delete-exact"},
        )
        analysis = self.runner.SCAFFOLD_FIELD_GUIDES["analysis"]
        self.assertIn(
            "behavioral-failure",
            analysis["classifications[*]"]["allowed_outcome_kind"],
        )
        self.assertEqual(
            analysis["not_challenged[*]"]["required_keys"],
            ["contract_id", "reason", "residual_risk"],
        )
        self.assertEqual(
            analysis["review.copy_ready_comments[*]"]["required_keys"],
            ["tag", "file", "line", "body", "evidence"],
        )
        for path in (
            "assessment",
            "not_challenged[*]",
            "test_changes[*]",
            "review.copy_ready_comments[*]",
        ):
            self.assertIn(path, self.runner.SCAFFOLD_EDITABLE_FIELDS["analysis"])

    def test_scaffold_guides_do_not_drift_from_canonical_schemas(self) -> None:
        contract_schema = json.loads(
            (ROOT / "schemas/intent-contract.schema.json").read_text()
        )
        plan_schema = json.loads(
            (ROOT / "schemas/challenge-plan.schema.json").read_text()
        )
        result_schema = json.loads(
            (ROOT / "schemas/mutation-result.schema.json").read_text()
        )
        report_schema = json.loads(
            (ROOT / "schemas/mutation-report.schema.json").read_text()
        )
        review_schema = json.loads(
            (ROOT / "schemas/canonical-review.schema.json").read_text()
        )
        contract = self.runner.SCAFFOLD_FIELD_GUIDES["contract"]
        self.assertEqual(
            contract["status"]["allowed"],
            contract_schema["properties"]["status"]["enum"],
        )
        self.assertEqual(
            contract["decisions[*]"]["allowed_provenance"],
            contract_schema["$defs"]["decision"]["properties"]["provenance"]["enum"],
        )
        plan = self.runner.SCAFFOLD_FIELD_GUIDES["plan"]
        challenge_properties = plan_schema["properties"]["challenges"]["items"][
            "properties"
        ]
        self.assertEqual(
            plan["challenges[*]"]["allowed_severity"],
            challenge_properties["severity"]["enum"],
        )
        self.assertEqual(
            plan["challenges[*]"]["allowed_likelihood"],
            challenge_properties["likelihood"]["enum"],
        )
        analysis = self.runner.SCAFFOLD_FIELD_GUIDES["analysis"]
        self.assertCountEqual(
            analysis["classifications[*]"]["allowed_result"],
            result_schema["properties"]["result"]["enum"],
        )
        self.assertCountEqual(
            analysis["classifications[*]"]["allowed_outcome_kind"],
            result_schema["properties"]["outcome_interpretation"]["properties"][
                "kind"
            ]["enum"],
        )
        self.assertEqual(
            analysis["not_challenged[*]"]["allowed_reason"],
            report_schema["properties"]["not_challenged"]["items"]["properties"][
                "reason"
            ]["enum"],
        )
        self.assertEqual(
            analysis["review.copy_ready_comments[*]"]["allowed_tag"],
            review_schema["properties"]["copy_ready_comments"]["items"][
                "properties"
            ]["tag"]["enum"],
        )

    def test_contract_guide_templates_validate_without_reading_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            _manifest, manifest_path = self.ready(root, repository)
            document = self.runner.scaffold_contract(
                manifest_path, ROOT / "schemas"
            )
            guide = self.runner.SCAFFOLD_FIELD_GUIDES["contract"]
            document["coverage"] = [dict(guide["coverage[*]"]["template"])]
            document["side_effects"]["required"] = [
                dict(guide["side_effects.required[*]"]["template"])
            ]
            self.runner._validator_module().validate_document(
                document, "intent-contract.schema.json", ROOT / "schemas"
            )
            document["status"] = "needs-decision"
            document["unresolved"] = [
                dict(guide["unresolved[*]"]["template"])
            ]
            self.runner._validator_module().validate_document(
                document, "intent-contract.schema.json", ROOT / "schemas"
            )

    def test_scaffold_plan_requires_probe_and_binds_command_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            with self.assertRaisesRegex(self.runner.RunGateError, "probe-command"):
                self.runner.scaffold_plan(manifest_path, ROOT / "schemas")
            self.runner.probe_command(
                manifest_path, "CMD-007", [sys.executable, "-c", "pass"], 10
            )
            document = self.runner.scaffold_plan(manifest_path, ROOT / "schemas")
            self.assertEqual(document["command_id"], "CMD-007")
            artifact = Path(manifest["artifact_root"]) / "challenge-plan.json"
            self.assertFalse(artifact.exists())
            artifact.write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(json.loads(artifact.read_text()), document)
            delete_template = self.runner.SCAFFOLD_FIELD_GUIDES["plan"][
                "challenges[*].mutation"
            ]["variants"]["delete-exact"]["template"]
            document["challenges"][0]["mutation"] = dict(delete_template)
            self.runner._validator_module().validate_document(
                document, "challenge-plan.schema.json", ROOT / "schemas"
            )

    def test_preflight_records_run_start_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, _manifest_path = self.ready(root, repository)
            self.assertGreater(manifest["started_at_epoch"], 0)

    def test_unresolved_intent_blocks_mapped_challenge_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            self.runner.probe_command(
                manifest_path, "CMD-001", [sys.executable, "-c", "pass"], 10
            )
            contract = json.loads(
                (ROOT / "demo/subscription_renewal/intent-contract.json").read_text()
            )
            contract["status"] = "needs-decision"
            contract["unresolved"] = [{
                "id": "UNR-001",
                "statement": "Whether the observable event should exist",
                "test_impact": "Changes the DEC-001 oracle",
                "blocked_contract_ids": ["DEC-001"],
            }]
            self.stage_contract(manifest, contract)
            plan = {
                "version": 2,
                "command_id": "CMD-001",
                "max_parallel": 1,
                "challenges": [self.anchored_challenge("MUT-001", "changed\n")],
            }
            (Path(manifest["artifact_root"]) / "challenge-plan.json").write_text(
                json.dumps(plan)
            )
            with self.assertRaisesRegex(
                self.runner.RunGateError, "blocked for unresolved Contract IDs"
            ):
                self.runner.challenge_batch(manifest_path, ROOT / "schemas")
            self.assertFalse(
                any(
                    item.get("kind") in {"guarded-write", "prebuilt"}
                    for item in self.runner._ledger_events(manifest)
                )
            )

    def test_challenge_plan_rejects_full_file_payload_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            self.runner.probe_command(
                manifest_path, "CMD-001", [sys.executable, "-c", "pass"], 10
            )
            self.stage_contract(manifest)
            challenge = self.anchored_challenge("MUT-001", "changed\n")
            challenge["mutation"] = {
                "kind": "write",
                "relative_target": "packages/app/source.ts",
                "content_utf8": "changed\n",
            }
            (Path(manifest["artifact_root"]) / "challenge-plan.json").write_text(
                json.dumps({
                    "version": 2,
                    "command_id": "CMD-001",
                    "max_parallel": 1,
                    "challenges": [challenge],
                })
            )
            with self.assertRaises(self.runner.RunGateError):
                self.runner.challenge_batch(manifest_path, ROOT / "schemas")
            self.assertFalse(any(
                item.get("kind") in {"guarded-write", "prebuilt"}
                for item in self.runner._ledger_events(manifest)
            ))

    def test_command_probe_failure_registers_no_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            self.stage_contract(manifest)
            result = self.runner.probe_command(
                manifest_path,
                "CMD-001",
                [sys.executable, "-c", "import time; time.sleep(2)"],
                1,
            )
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["outcome"], "timeout")
            events = [
                item
                for item in self.runner._ledger_events(manifest)
                if item.get("kind") in {"guarded-write", "prebuilt"}
            ]
            self.assertEqual(events, [])
            self.assertFalse(any(
                item.get("kind") == "validated-command"
                for item in self.runner._ledger_events(manifest)
            ))

    def test_validated_command_is_bound_to_prepared_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            self.assertEqual(
                self.runner.probe_command(
                    manifest_path, "CMD-001", [sys.executable, "-c", "pass"], 10
                )["status"],
                "ready",
            )
            with self.assertRaisesRegex(
                self.runner.RunGateError, "prepare cannot run"
            ):
                self.runner.execute(
                    manifest_path,
                    "prepare",
                    None,
                    [sys.executable, "-c", "pass"],
                    10,
                )
            (Path(manifest["prepared_root"]) / "packages/app/source.ts").write_text(
                "tampered\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(
                self.runner.RunGateError, "validated command is stale"
            ):
                self.runner._validated_command(manifest, "CMD-001")

    def test_structured_inspection_is_bounded_and_blocks_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            file_result = self.runner.inspect_review(
                manifest_path,
                "file",
                relative_path="packages/app/source.ts",
                start_line=1,
                end_line=10,
            )
            self.assertEqual(file_result["text"], "original")
            self.assertEqual(
                file_result["checkpoint"]["id"], "diff-understanding"
            )
            self.assertTrue(
                file_result["checkpoint"]["required_before_next"]
            )
            self.assertIn("scaffold-contract", file_result["next"]["argv"])
            self.assertEqual(
                file_result["next"]["announce"],
                "Establishing the intended behavior",
            )
            search = self.runner.inspect_review(
                manifest_path, "search", query="original"
            )
            self.assertEqual(
                [(item["path"], item["line"]) for item in search["matches"]],
                [("packages/app/source.ts", 1)],
            )
            with self.assertRaisesRegex(
                self.runner.RunGateError, "excluded"
            ):
                self.runner.inspect_review(
                    manifest_path, "file", relative_path=".env"
                )

    def test_probe_next_has_exact_root_cwd_option_and_announcement(self) -> None:
        manifest_path = Path("/host/run-manifest.json")
        step = self.runner._probe_next(manifest_path)
        self.assertIn("<package-directory-or-dot>", step["argv"])
        self.assertNotIn("<package-directory-or-omit>", step["argv"])
        self.assertEqual(step["announce"], "Running the current tests")

    def test_staged_contract_offers_exact_prepare_and_no_install_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            document = self.runner.scaffold_contract(
                manifest_path, ROOT / "schemas"
            )
            (
                Path(manifest["artifact_root"]) / "intent-contract.draft.json"
            ).write_text(json.dumps(document), encoding="utf-8")
            stdout = io.StringIO()
            with patch.object(sys, "argv", [
                "run_review.py",
                "stage-artifact",
                "--manifest", str(manifest_path),
                "--kind", "contract",
                "--schema-root", str(ROOT / "schemas"),
            ]), redirect_stdout(stdout):
                code = self.runner.main()
            self.assertEqual(code, 0)
            result = json.loads(stdout.getvalue())
            self.assertIn("execute", result["next"]["argv"])
            self.assertIn(
                "probe-command",
                result["skip_if_dependencies_ready"]["argv"],
            )
            self.assertEqual(
                result["skip_if_dependencies_ready"]["announce"],
                "Running the current tests",
            )

    def test_complete_generates_drafts_renders_and_discards_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            self.stage_contract(manifest)
            command = [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; "
                    "raise SystemExit(0 if "
                    "Path('packages/app/source.ts').read_text() == 'original\\n' "
                    "else 1)"
                ),
            ]
            probe = self.runner.probe_command(
                manifest_path, "CMD-001", command, 10
            )
            self.assertEqual(probe["status"], "ready")
            plan = {
                "version": 2,
                "command_id": "CMD-001",
                "max_parallel": 1,
                "challenges": [
                    self.anchored_challenge("MUT-001", "changed\n")
                ],
            }
            artifact_root = Path(manifest["artifact_root"])
            plan_path = artifact_root / "challenge-plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            self.assertLess(plan_path.stat().st_size, 2048)
            batch = self.runner.challenge_batch(manifest_path, ROOT / "schemas")
            self.assertEqual(batch["results"][0]["outcome"], "failed")
            scaffold = self.runner.scaffold_analysis(
                manifest_path, "harden", ROOT / "schemas"
            )
            self.assertEqual(scaffold["classifications"], 1)
            analysis_path = artifact_root / "review-analysis.json"
            self.assertFalse(analysis_path.exists())
            analysis = scaffold["document"]
            classification = analysis["classifications"][0]
            self.assertEqual(classification["result"], "inconclusive")
            classification.update({
                "source_intent": "The source retains its established value",
                "changed_intent": "The source silently changes value",
                "result": "killed",
                "detecting_tests": ["focused source behavior"],
                "observed_failure_reason": "The focused behavior check failed",
                "contract_violation_observed": True,
                "outcome_interpretation": {
                    "kind": "behavioral-failure",
                    "reason": "The changed value violated DEC-001",
                },
            })
            analysis["stable_tests"] = ["focused source behavior"]
            analysis["test_changes"] = [{
                "name": "focused source behavior",
                "disposition": "existing",
            }]
            analysis["review"]["we_verified"] = [
                "The focused behavior was detected by a test existing at run start"
            ]
            analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
            rendered = self.runner.complete(
                manifest_path, retention="discard", schema_root=ROOT / "schemas"
            )
            self.assertIn("We Verified:", rendered)
            self.assertFalse(manifest_path.exists())
            self.assertFalse(artifact_root.exists())

    def test_analysis_scaffold_uses_raw_outcomes_without_claiming_kills(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            self.stage_contract(manifest)
            command = [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; "
                    "raise SystemExit(0 if "
                    "Path('packages/app/source.ts').read_text() == 'original\\n' "
                    "else 1)"
                ),
            ]
            self.runner.probe_command(manifest_path, "CMD-001", command, 10)
            artifact_root = Path(manifest["artifact_root"])
            (artifact_root / "challenge-plan.json").write_text(json.dumps({
                "version": 2,
                "command_id": "CMD-001",
                "max_parallel": 1,
                "challenges": [
                    self.anchored_challenge("MUT-001", "changed\n")
                ],
            }))
            self.runner.challenge_batch(manifest_path, ROOT / "schemas")
            stdout = io.StringIO()
            with patch.object(sys, "argv", [
                "run_review.py",
                "scaffold-analysis",
                "--manifest", str(manifest_path),
                "--mode", "assessment",
                "--schema-root", str(ROOT / "schemas"),
            ]), redirect_stdout(stdout):
                code = self.runner.main()
            self.assertEqual(code, 0)
            response = json.loads(stdout.getvalue())
            result = response["scaffold"]
            self.assertEqual(result["status"], "generated")
            self.assertEqual(
                response["artifact_path"],
                str(artifact_root / "review-analysis.json"),
            )
            self.assertIn(
                "Write exactly once",
                response["write_protocol"]["first_write"],
            )
            self.assertFalse((artifact_root / "review-analysis.json").exists())
            analysis = response["document"]
            self.assertIsInstance(analysis["assessment"], dict)
            self.assertEqual(
                analysis["assessment"]["selected_scope"], "current-change"
            )
            classification = analysis["classifications"][0]
            self.assertEqual(classification["result"], "inconclusive")
            self.assertEqual(
                classification["outcome_interpretation"]["kind"], "unparseable"
            )
            classification.update({
                "source_intent": "The source retains its established value",
                "changed_intent": "The source silently changes value",
                "result": "killed",
                "detecting_tests": ["focused source behavior"],
                "observed_failure_reason": "The focused behavior check failed",
                "contract_violation_observed": True,
                "outcome_interpretation": {
                    "kind": "behavioral-failure",
                    "reason": "The changed value violated DEC-001",
                },
            })
            guide = self.runner.SCAFFOLD_FIELD_GUIDES["analysis"]
            analysis["not_challenged"] = [
                dict(guide["not_challenged[*]"]["template"])
            ]
            analysis["test_changes"] = [
                dict(guide["test_changes[*]"]["template"])
            ]
            analysis["review"]["review_this"] = [
                dict(guide["review.review_this[*]"]["template"])
            ]
            analysis["review"]["copy_ready_comments"] = [
                dict(guide["review.copy_ready_comments[*]"]["template"])
            ]
            self.runner._validator_module().validate_document(
                analysis, "review-analysis.schema.json", ROOT / "schemas"
            )
            (artifact_root / "review-analysis.json").write_text(
                json.dumps(analysis), encoding="utf-8"
            )
            rendered = self.runner.complete(
                manifest_path, retention="discard", schema_root=ROOT / "schemas"
            )
            self.assertIn("Review This:", rendered)
            self.assertFalse(manifest_path.exists())

    def test_execute_forces_home_temp_and_caches_into_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            script = (
                "import os,pathlib; "
                "[pathlib.Path(os.environ[k]).joinpath('probe').write_text('ok') "
                "for k in ('HOME','TMPDIR','XDG_CACHE_HOME','npm_config_cache')]"
            )
            self.assertEqual(
                self.runner.execute(manifest_path, "baseline", None, [sys.executable, "-c", script], 10), 0
            )
            sandbox = Path(manifest["sandbox_root"])
            for value in manifest["environment"].values():
                self.assertTrue(Path(value, "probe").is_file())
                self.assertTrue(Path(value).is_relative_to(sandbox))

    def test_execute_passes_only_allowlisted_and_manifest_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            output = Path(manifest["sandbox_root"]) / "environment.json"
            inherited = {
                "PATH": os.environ.get("PATH", ""),
                "LANG": "en_US.UTF-8",
                "LC_TEST": "allowed-locale",
                "GITHUB_TOKEN": "github-secret-value",
                "OPENAI_API_KEY": "openai-secret-value",
                "UNKNOWN_SECRET": "unknown-secret-value",
                "PYTHONPATH": "/secret/pythonpath",
                "NODE_OPTIONS": "--require=/secret/hook.js",
            }
            script = (
                "import json,os,pathlib; "
                f"pathlib.Path({str(output)!r}).write_text(json.dumps(dict(os.environ), sort_keys=True))"
            )
            with patch.dict(os.environ, inherited, clear=True):
                self.assertEqual(
                    self.runner.execute(
                        manifest_path, "baseline", None, [sys.executable, "-c", script], 10
                    ),
                    0,
                )

            child_environment = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(child_environment["LANG"], "en_US.UTF-8")
            self.assertEqual(child_environment["LC_TEST"], "allowed-locale")
            for key, value in manifest["environment"].items():
                self.assertEqual(child_environment[key], value)
            for key in (
                "GITHUB_TOKEN", "OPENAI_API_KEY", "UNKNOWN_SECRET", "PYTHONPATH", "NODE_OPTIONS"
            ):
                self.assertNotIn(key, child_environment)

            ledger_text = Path(manifest["ledger_path"]).read_text(encoding="utf-8")
            for secret in (
                "GITHUB_TOKEN", "github-secret-value", "OPENAI_API_KEY", "openai-secret-value",
                "UNKNOWN_SECRET", "unknown-secret-value", "PYTHONPATH", "/secret/pythonpath",
                "NODE_OPTIONS", "--require=/secret/hook.js",
            ):
                self.assertNotIn(secret, ledger_text)

    def test_execute_records_timeout_before_failing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            timeout = subprocess.TimeoutExpired(["test-command"], 5)
            with patch.object(self.runner.subprocess, "run", side_effect=timeout):
                with self.assertRaisesRegex(self.runner.RunGateError, "timed out"):
                    self.runner.execute(manifest_path, "baseline", None, ["test-command"], 5)
            event = self.runner._ledger_events(manifest)[-1]
            self.assertEqual(event["result"], "timeout")
            self.assertIsNone(event["returncode"])
            self.assertEqual(event["phase"], "baseline")
            self.runner.abort(manifest_path)
            self.assertFalse(Path(manifest["artifact_root"]).exists())

    def test_host_preflight_binds_materialized_pull_request_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = root / "host-storage"
            base = storage / "change/base"
            head = storage / "change/head"
            for snapshot, content in ((base, "base\n"), (head, "head\n")):
                (snapshot / ".git").mkdir(parents=True)
                (snapshot / "source.py").write_text(content, encoding="utf-8")
            change_context = {
                "source": "github-pull-request",
                "number": 7,
                "url": "https://github.com/Shogo1222/socratic/pull/7",
                "base_ref": "main",
                "base_sha": "1" * 40,
                "head_ref": "feature",
                "head_sha": "2" * 40,
                "base_root": str(base),
                "head_root": str(head),
            }
            runner = self.runner

            class MaterializedHost:
                def begin_review_run(self, primary_root: Path):
                    return runner.HostGrant(
                        adapter_id="fixture-host-v1",
                        run_id="c" * 32,
                        run_nonce="host-issued-nonce-" + "d" * 32,
                        storage_root=storage,
                        protection_mode="os-read-only",
                        protection_details="fixture materialization",
                        change_context=change_context,
                    )

            manifest, manifest_path = runner.preflight_with_host(head, MaterializedHost())
            self.assertEqual(manifest["change_context"], change_context)
            self.assertEqual(
                (Path(manifest["prepared_root"]) / "source.py").read_text(), "head\n"
            )
            runner.abort(manifest_path)
            self.assertFalse(Path(manifest["artifact_root"]).exists())

    def test_finish_rejects_green_baseline_with_failing_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            self.runner.execute(
                manifest_path, "baseline", None,
                [sys.executable, "-c", "raise SystemExit(1)"], 10,
            )
            report = json.loads(
                (ROOT / "demo/subscription_renewal/expected-elenchus-report.json").read_text()
            )
            report["run"] = {
                "id": manifest["run_id"], "entrypoint": self.runner.ENTRYPOINT,
                "host_adapter": manifest["host"]["adapter_id"],
                "run_nonce": manifest["host"]["run_nonce"],
                "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "ledger_head": self.runner._ledger_head(manifest),
            }
            with self.assertRaisesRegex(self.runner.RunGateError, "green baseline"):
                self.runner.finish_document(
                    manifest, report, {}, self.runner._ledger_events(manifest),
                    manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                    ledger_head=self.runner._ledger_head(manifest),
                )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_mutation_rechecks_primary_directed_symlinks_created_after_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            os.symlink(
                repository / "packages", Path(manifest["prepared_root"]) / "late-link"
            )
            self.runner.execute(
                manifest_path, "baseline", None, [sys.executable, "-c", "pass"], 10
            )
            self.stage_contract(manifest)
            with self.assertRaises(Exception):
                self.runner.mutate(
                    manifest_path, "MUT-001", ["DEC-001"],
                    "late-link/app/source.ts", b"mutant\n"
                )

    def test_ledger_chain_detects_rewritten_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            self.runner.execute(manifest_path, "baseline", None, [sys.executable, "-c", "pass"], 10)
            ledger_path = Path(manifest["ledger_path"])
            raw = ledger_path.read_text().replace('"returncode":0', '"returncode":1')
            ledger_path.write_text(raw)
            with self.assertRaises(self.runner.RunGateError):
                self.runner._ledger_events(manifest)

    def test_mutant_clone_shares_dependencies_and_gets_fresh_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            prepared = Path(manifest["prepared_root"])
            dependency_marker = prepared / "node_modules/.bin/vitest"
            dependency_marker.parent.mkdir(parents=True, exist_ok=True)
            dependency_marker.write_text("#!/bin/sh\n")
            store_marker = (
                prepared / ".socratic-runtime/home/install-store-marker.txt"
            )
            store_marker.parent.mkdir(parents=True, exist_ok=True)
            store_marker.write_text("install-time store\n")
            self.runner.execute(
                manifest_path, "baseline", None, [sys.executable, "-c", "pass"], 10
            )
            self.stage_contract(manifest)
            event = self.runner.mutate(
                manifest_path, "MUT-001", ["DEC-001"],
                "packages/app/source.ts", b"mutant\n",
            )
            clone = Path(event["sandbox_root"])
            self.assertEqual(
                (clone / "node_modules/.bin/vitest").read_text(), "#!/bin/sh\n"
            )
            self.assertTrue((clone / "node_modules").is_dir())
            self.assertFalse((clone / "node_modules").is_symlink())
            self.assertTrue((clone / "node_modules/.bin").is_symlink())
            self.assertTrue((prepared / "node_modules").is_dir())
            self.assertFalse((prepared / "node_modules").is_symlink())
            self.assertEqual(
                (
                    Path(manifest["dependency_root"])
                    / "install-runtime/home/install-store-marker.txt"
                ).read_text(),
                "install-time store\n",
            )
            self.assertFalse(
                (
                    clone / ".socratic-runtime/home/install-store-marker.txt"
                ).exists()
            )

    def test_dependency_layer_is_hashed_separately_from_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, _manifest_path = self.ready(root, repository)
            prepared = Path(manifest["prepared_root"])
            dependency = prepared / "node_modules/example/index.js"
            dependency.parent.mkdir(parents=True)
            dependency.write_text("installed\n")
            install_cache = prepared / "node_modules/.vite/install-cache.json"
            install_cache.parent.mkdir()
            install_cache.write_text("discarded attachment\n")
            source_sha256 = self.runner._prepared_hash(prepared)

            self.runner._materialize_dependency_layer(manifest)
            evidence = self.runner._seal_dependency_layer(manifest)

            self.assertEqual(self.runner._prepared_hash(prepared), source_sha256)
            self.assertEqual(evidence["attached_paths"], ["node_modules"])
            self.assertTrue((prepared / "node_modules").is_dir())
            self.assertTrue((prepared / "node_modules/example").is_symlink())
            self.assertFalse((prepared / "node_modules/.vite").exists())
            self.runner._verify_dependency_layer(manifest, evidence)
            runtime_cache = prepared / "node_modules/.vite/results.json"
            runtime_cache.parent.mkdir()
            runtime_cache.write_text("runtime cache\n")
            self.runner._verify_dependency_layer(manifest, evidence)
            dependency.write_text("tampered\n")
            self.assertEqual(self.runner._prepared_hash(prepared), source_sha256)
            with self.assertRaisesRegex(
                self.runner.RunGateError, "shared dependency layer changed"
            ):
                self.runner._verify_dependency_layer(manifest, evidence)

    def test_python_virtual_environment_is_attached_as_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, _manifest_path = self.ready(root, repository)
            prepared = Path(manifest["prepared_root"])
            virtual_environment = prepared / ".venv"
            virtual_environment.mkdir()
            (virtual_environment / "pyvenv.cfg").write_text("home = /python\n")
            (virtual_environment / "marker").write_text("installed\n")

            self.runner._materialize_dependency_layer(manifest)
            evidence = self.runner._seal_dependency_layer(manifest)

            self.assertEqual(evidence["attached_paths"], [".venv"])
            self.assertTrue(virtual_environment.is_symlink())
            self.assertEqual((virtual_environment / "marker").read_text(), "installed\n")

    def test_sandbox_executions_receive_dependency_reuse_env(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self.runner._runtime_environment(Path(directory))
            self.assertEqual(environment["CI"], "true")
            self.assertEqual(
                environment["npm_config_verify_deps_before_run"], "false"
            )

    def test_baseline_execution_receives_dependency_reuse_env(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            probe = Path(manifest["prepared_root"]) / "env-probe.txt"
            code = (
                "import os, pathlib; "
                f"pathlib.Path({str(probe)!r}).write_text("
                "os.environ.get('CI', '') + ' ' + "
                "os.environ.get('npm_config_verify_deps_before_run', ''))"
            )
            self.runner.execute(
                manifest_path, "baseline", None, [sys.executable, "-c", code], 10
            )
            self.assertEqual(probe.read_text(), "true false")

    def test_finish_rejects_registered_mutation_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            self.runner.execute(manifest_path, "baseline", None, [sys.executable, "-c", "pass"], 10)
            self.stage_contract(manifest)
            self.runner.register_prebuilt(
                manifest_path, "MUT-001", ["DEC-001"], "packages/app/mutant-1.ts"
            )
            report = json.loads((ROOT / "demo/subscription_renewal/expected-elenchus-report.json").read_text())
            report["mutations"] = report["mutations"][:1]
            with self.assertRaises(self.runner.RunGateError):
                self.runner.finish_document(
                    manifest, report, {}, self.runner._ledger_events(manifest),
                    manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                    ledger_head=self.runner._ledger_head(manifest),
                )

    def test_finish_rejects_infrastructure_failure_reported_as_killed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            self.runner.execute(
                manifest_path, "baseline", None, [sys.executable, "-c", "pass"], 10
            )
            self.stage_contract(manifest)
            self.runner.register_prebuilt(
                manifest_path, "MUT-001", ["DEC-001"], "packages/app/mutant-1.ts"
            )
            self.runner.execute(
                manifest_path,
                "mutation",
                "MUT-001",
                [sys.executable, "-c", "raise SystemExit(1)"],
                10,
            )
            contract = json.loads(
                (ROOT / "demo/subscription_renewal/intent-contract.json").read_text()
            )
            draft = self.report_draft()
            draft["mutations"] = draft["mutations"][:1]
            draft["mutations"][0]["outcome_interpretation"] = {
                "kind": "infrastructure-failure",
                "reason": "The test runner failed before collecting assertions.",
            }
            ledger = self.runner._ledger_events(manifest)
            report = self.runner._attested_report(
                manifest,
                contract,
                draft,
                ledger,
                manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                ledger_head=self.runner._ledger_head(manifest),
            )
            with self.assertRaisesRegex(
                self.runner.RunGateError, "not classified as a behavioral failure"
            ):
                self.runner.finish_document(
                    manifest,
                    report,
                    {},
                    ledger,
                    manifest_sha256=hashlib.sha256(
                        manifest_path.read_bytes()
                    ).hexdigest(),
                    ledger_head=self.runner._ledger_head(manifest),
                )

            report["mutations"][0]["result"] = "inconclusive"
            self.runner.finish_document(
                manifest,
                report,
                {},
                ledger,
                manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                ledger_head=self.runner._ledger_head(manifest),
            )

    def test_end_to_end_requires_baseline_and_every_mutation_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            self.runner.execute(manifest_path, "baseline", None, [sys.executable, "-c", "pass"], 10)
            self.stage_contract(manifest)
            for index, mutation_id in enumerate(("MUT-001", "MUT-002", "MUT-003"), 1):
                self.runner.register_prebuilt(
                    manifest_path, mutation_id, ["DEC-001"],
                    f"packages/app/mutant-{index}.ts"
                )
                self.runner.execute(
                    manifest_path, "mutation", mutation_id,
                    [sys.executable, "-c", "raise SystemExit(1)"], 10,
                )
            _contract, review = self.stage_demo_artifacts(manifest)
            rendered = self.runner._validator_module().render_review(review)
            stdout = io.StringIO()
            with patch.object(
                sys,
                "argv",
                [
                    "run_review.py", "finish", "--manifest", str(manifest_path),
                    "--schema-root", str(ROOT / "schemas"),
                ],
            ), redirect_stdout(stdout):
                self.assertEqual(self.runner.main(), 0)
            self.assertEqual(stdout.getvalue(), rendered)
            self.assertTrue(rendered.startswith("Review This:\n"))
            self.assertTrue(manifest_path.exists())
            self.assertTrue(Path(manifest["ledger_path"]).exists())
            self.assertFalse(Path(manifest["sandbox_root"]).exists())
            attested_path = Path(manifest["artifact_root"]) / "mutation-report.attested.json"
            attested = json.loads(attested_path.read_text(encoding="utf-8"))
            self.assertEqual(attested["run"]["id"], manifest["run_id"])
            self.assertEqual(attested["version"], 10)
            self.assertEqual(attested["change_context"], manifest["change_context"])
            self.assertEqual(
                attested["prepared_snapshot"]["protection"],
                "host-managed-hash-verified",
            )
            self.assertEqual(
                attested["prepared_snapshot"]["dependency_layer"]["root"],
                manifest["dependency_root"],
            )
            self.assertEqual(
                attested["prepared_snapshot"]["dependency_layer"]["protection"],
                "runner-shared-hash-verified",
            )
            self.assertEqual(
                [item["mutation_id"] for item in attested["prepared_snapshot"]["clones"]],
                ["MUT-001", "MUT-002", "MUT-003"],
            )
            self.assertTrue(
                all(
                    item["strategy"] in {"kernel-clone", "copy-on-write", "full-copy"}
                    for item in attested["prepared_snapshot"]["clones"]
                )
            )
            self.assertEqual(
                len({
                    item["sandbox_root"]
                    for item in attested["prepared_snapshot"]["clones"]
                }),
                3,
            )
            self.assertEqual(attested["execution_evidence"]["source"], "host-ledger")
            self.assertEqual(
                [
                    {
                        key: item[key]
                        for key in ("attempt", "outcome", "exit_code")
                    }
                    for item in attested["execution_evidence"]["baseline"]
                ],
                [{"attempt": 1, "outcome": "passed", "exit_code": 0}],
            )
            self.assertGreaterEqual(
                attested["execution_evidence"]["baseline"][0]["duration_ms"], 0
            )
            self.assertIn("phase_timings_ms", attested)
            self.assertEqual(
                [
                    item["outcome"]
                    for item in attested["execution_evidence"]["mutations"]
                ],
                ["failed", "failed", "failed"],
            )
            self.assertEqual(
                attested["run"]["ledger_head"], self.runner._ledger_head(manifest)
            )
            self.assertFalse(attested["canonical_output"]["extra_prose"])
            self.assertEqual(
                (Path(manifest["artifact_root"]) / "renderer-output.txt").read_text(),
                rendered,
            )
            self.runner.cleanup(manifest_path)
            self.runner.cleanup(manifest_path)
            self.assertFalse(manifest_path.exists())
            self.assertFalse(Path(manifest["ledger_path"]).exists())
            self.assertFalse(Path(manifest["artifact_root"]).exists())

    def test_finish_rejects_changed_shared_dependency_layer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            dependency = (
                Path(manifest["prepared_root"]) / "node_modules/example/index.js"
            )
            dependency.parent.mkdir(parents=True)
            dependency.write_text("installed\n")
            self.runner.execute(
                manifest_path,
                "baseline",
                None,
                [sys.executable, "-c", "pass"],
                10,
            )
            self.stage_contract(manifest)
            for index, mutation_id in enumerate(
                ("MUT-001", "MUT-002", "MUT-003"), 1
            ):
                self.runner.register_prebuilt(
                    manifest_path,
                    mutation_id,
                    ["DEC-001"],
                    f"packages/app/mutant-{index}.ts",
                )
                self.runner.execute(
                    manifest_path,
                    "mutation",
                    mutation_id,
                    [sys.executable, "-c", "raise SystemExit(1)"],
                    10,
                )
            self.stage_demo_artifacts(manifest)
            dependency.write_text("changed during mutation\n")

            with self.assertRaisesRegex(
                self.runner.RunGateError,
                "shared dependency layer changed.*do not retry complete",
            ):
                self.runner.finish(manifest_path, ROOT / "schemas")
            self.assertFalse(manifest_path.exists())
            self.assertFalse(Path(manifest["sandbox_root"]).exists())

    def test_stage_rejects_invalid_draft_and_records_all_schema_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            invalid = {"version": 1, "mode": "harden", "test_changes": ["wrong"]}
            path = Path(manifest["artifact_root"]) / self.runner.ARTIFACT_FILES["report"]
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(self.runner.RunGateError, "validation failed"):
                self.runner.stage_artifact(
                    manifest_path, "report", ROOT / "schemas"
                )
            errors = json.loads(
                (Path(manifest["artifact_root"]) / "validation-errors.json").read_text()
            )
            message = errors["errors"][0]["message"]
            self.assertIn("'baseline' is a required property", message)
            self.assertIn("'wrong' is not of type 'object'", message)
            self.runner.abort(manifest_path)

    def test_staged_artifact_is_create_once_and_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            self.stage_demo_artifacts(manifest)
            artifact = Path(manifest["artifact_root"]) / self.runner.ARTIFACT_FILES["report"]
            with self.assertRaisesRegex(self.runner.RunGateError, "create-once"):
                self.runner.stage_artifact(manifest_path, "report", ROOT / "schemas")
            artifact.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(self.runner.RunGateError, "staged artifact changed"):
                self.runner._staged_artifacts(manifest)
            self.runner.abort(manifest_path)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_stage_rejects_symlinked_draft(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            outside = root / "outside.json"
            outside.write_text(json.dumps(self.report_draft()), encoding="utf-8")
            artifact = Path(manifest["artifact_root"]) / self.runner.ARTIFACT_FILES["report"]
            os.symlink(outside, artifact)
            with self.assertRaisesRegex(self.runner.RunGateError, "missing"):
                self.runner.stage_artifact(manifest_path, "report", ROOT / "schemas")
            self.runner.abort(manifest_path)

    def test_finish_cross_artifact_failure_cleans_without_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            self.runner.execute(
                manifest_path, "baseline", None, [sys.executable, "-c", "pass"], 10
            )
            self.stage_contract(manifest)
            for index, mutation_id in enumerate(("MUT-001", "MUT-002", "MUT-003"), 1):
                self.runner.register_prebuilt(
                    manifest_path, mutation_id, ["DEC-001"],
                    f"packages/app/mutant-{index}.ts"
                )
                self.runner.execute(
                    manifest_path, "mutation", mutation_id,
                    [sys.executable, "-c", "raise SystemExit(1)"], 10,
                )
            draft = self.report_draft()
            draft["mutations"][0]["contract_ids"] = ["DEC-999"]
            self.stage_demo_artifacts(manifest, report=draft)
            validator = self.runner._validator_module()
            with patch.object(
                validator, "render_review", side_effect=AssertionError("renderer called")
            ):
                with patch.object(
                    self.runner, "_validator_module", return_value=validator
                ):
                    with self.assertRaisesRegex(
                        self.runner.RunGateError, "unknown Contract IDs"
                    ):
                        self.runner.finish(manifest_path, ROOT / "schemas")
            self.assertFalse(manifest_path.exists())
            self.assertFalse(Path(manifest["artifact_root"]).exists())

    def test_primary_hash_change_invalidates_finish_and_cleans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            self.stage_demo_artifacts(manifest)
            (repository / "packages/app/source.ts").write_text("changed\n")
            with self.assertRaisesRegex(self.runner.RunGateError, "Primary content hash changed"):
                self.runner.finish(manifest_path, ROOT / "schemas")
            self.assertFalse(manifest_path.exists())
            self.assertFalse(Path(manifest["artifact_root"]).exists())


if __name__ == "__main__":
    unittest.main()
