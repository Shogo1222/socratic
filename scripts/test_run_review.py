#!/usr/bin/env python3
"""Fail-closed regression tests for the mandatory Socratic run entrypoint."""

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import subprocess
import unittest
from pathlib import Path
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
            self.runner.register_prebuilt(manifest_path, "MUT-001", "packages/app/mutant-1.ts")
            self.assertEqual(
                self.runner.execute(manifest_path, "mutation", "MUT-001", [sys.executable, "-c", "raise SystemExit(1)"], 10),
                1,
            )

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
            os.symlink(repository / "packages", Path(manifest["sandbox_root"]) / "late-link")
            with self.assertRaises(Exception):
                self.runner.mutate(manifest_path, "MUT-001", "packages/app/source.ts", b"mutant\n")

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
            contract = json.loads((ROOT / "demo/subscription_renewal/intent-contract.json").read_text())
            report = json.loads((ROOT / "demo/subscription_renewal/expected-elenchus-report.json").read_text())
            review = json.loads((ROOT / "demo/subscription_renewal/canonical-review.json").read_text())
            report["run"] = {
                "id": manifest["run_id"],
                "entrypoint": "socratic/scripts/run_review.py",
                "host_adapter": manifest["host"]["adapter_id"],
                "run_nonce": manifest["host"]["run_nonce"],
                "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "ledger_head": self.runner._ledger_head(manifest),
            }
            report["isolation"].update({
                "primary_root": manifest["primary_root"],
                "sandbox_root": manifest["sandbox_root"],
                "host_protection": {
                    "mode": "os-read-only", "verified": True,
                    "details": "fixture host denied a Primary write probe",
                },
                "write_monitor": {"mode": "unavailable", "verified": False, "details": "not needed"},
            })
            rendered = self.runner.finish(manifest_path, contract, report, review, ROOT / "schemas")
            self.assertTrue(rendered.startswith("Review This:\n"))
            self.assertFalse(manifest_path.exists())
            self.assertFalse(Path(manifest["ledger_path"]).exists())
            self.assertFalse(Path(manifest["sandbox_root"]).exists())


if __name__ == "__main__":
    unittest.main()
