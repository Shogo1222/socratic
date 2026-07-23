#!/usr/bin/env python3
"""Fail-closed regression tests for the mandatory Socratic run entrypoint."""

import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import subprocess
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "skills/socratic/scripts/run_review.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("socratic_run_review", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
        for kind, document in documents.items():
            (artifact_root / self.runner.ARTIFACT_FILES[kind]).write_text(
                json.dumps(document), encoding="utf-8"
            )
            self.runner.stage_artifact(
                Path(manifest["host"]["storage_root"]) / "run-manifest.json",
                kind,
                ROOT / "schemas",
            )
        return contract, review

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
            self.runner.register_prebuilt(manifest_path, "MUT-001", "packages/app/mutant-1.ts")
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
            first = self.runner.register_prebuilt(
                manifest_path, "MUT-001", "packages/app/mutant-1.ts"
            )
            second = self.runner.register_prebuilt(
                manifest_path, "MUT-002", "packages/app/mutant-2.ts"
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
            prepared_events = [
                item
                for item in self.runner._ledger_events(manifest)
                if item.get("kind") == "prepared-snapshot"
            ]
            self.assertEqual(len(prepared_events), 1)

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
            with self.assertRaises(Exception):
                self.runner.mutate(
                    manifest_path, "MUT-001", "late-link/app/source.ts", b"mutant\n"
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

    def test_finish_rejects_registered_mutation_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest, manifest_path = self.ready(root, repository)
            self.runner.execute(manifest_path, "baseline", None, [sys.executable, "-c", "pass"], 10)
            self.runner.register_prebuilt(manifest_path, "MUT-001", "packages/app/mutant-1.ts")
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
            self.runner.register_prebuilt(
                manifest_path, "MUT-001", "packages/app/mutant-1.ts"
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
            for index, mutation_id in enumerate(("MUT-001", "MUT-002", "MUT-003"), 1):
                self.runner.register_prebuilt(
                    manifest_path, mutation_id, f"packages/app/mutant-{index}.ts"
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
            self.assertEqual(attested["version"], 9)
            self.assertEqual(
                attested["prepared_snapshot"]["protection"],
                "host-managed-hash-verified",
            )
            self.assertEqual(
                [item["mutation_id"] for item in attested["prepared_snapshot"]["clones"]],
                ["MUT-001", "MUT-002", "MUT-003"],
            )
            self.assertTrue(
                all(
                    item["strategy"] in {"copy-on-write", "full-copy"}
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
                attested["execution_evidence"]["baseline"],
                [{"attempt": 1, "outcome": "passed", "exit_code": 0}],
            )
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
            for index, mutation_id in enumerate(("MUT-001", "MUT-002", "MUT-003"), 1):
                self.runner.register_prebuilt(
                    manifest_path, mutation_id, f"packages/app/mutant-{index}.ts"
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
