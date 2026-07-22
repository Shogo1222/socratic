#!/usr/bin/env python3
"""Fail-closed regression tests for the mandatory Socratic run entrypoint."""

import importlib.util
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "skills" / "socratic" / "scripts" / "run_review.py"


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
        (repository / "packages" / "app").mkdir(parents=True)
        (repository / "packages" / "app" / "source.ts").write_text("original\n")
        (repository / ".env").write_text("SECRET=never-copy\n")
        (repository / "node_modules").mkdir()
        return repository

    def write_attestation(self, root: Path, repository: Path) -> Path:
        path = root / "protection.json"
        path.write_text(json.dumps({
            "mode": "os-read-only",
            "verified": True,
            "primary_root": str(repository.resolve()),
            "details": "host fixture denied a write probe"
        }))
        return path

    def test_preflight_without_verified_protection_is_blocked_and_creates_no_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest_path = root / "manifest.json"
            manifest = self.runner.preflight(repository / "packages" / "app", manifest_path, None)
            self.assertEqual(manifest["status"], "blocked")
            self.assertIsNone(manifest["sandbox_root"])
            self.assertFalse(manifest["protection"]["verified"])

    def test_preflight_creates_external_copy_and_sandbox_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            attestation = self.write_attestation(root, repository)
            manifest = self.runner.preflight(
                repository / "packages" / "app", root / "manifest.json", attestation
            )
            sandbox = Path(manifest["sandbox_root"])
            self.assertEqual(manifest["status"], "ready")
            self.assertEqual(Path(manifest["primary_root"]), repository.resolve())
            self.assertFalse(sandbox.is_relative_to(repository.resolve()))
            self.assertTrue((sandbox / ".socratic-disposable").is_file())
            self.assertFalse((sandbox / ".env").exists())
            self.assertFalse((sandbox / "node_modules").exists())
            for value in manifest["environment"].values():
                self.assertTrue(Path(value).is_relative_to(sandbox))

    def test_guarded_mutation_is_bound_to_manifest_and_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest_path = root / "manifest.json"
            manifest = self.runner.preflight(
                repository, manifest_path, self.write_attestation(root, repository)
            )
            evidence = self.runner.mutate(
                manifest_path, "MUT-001", "packages/app/source.ts", b"mutant\n"
            )
            ledger = json.loads(Path(manifest["ledger_path"]).read_text())
            self.assertEqual(evidence["mutation_id"], "MUT-001")
            self.assertEqual(ledger[0]["run_id"], manifest["run_id"])
            self.assertEqual(repository.joinpath("packages/app/source.ts").read_text(), "original\n")

    def test_execute_forces_home_temp_and_caches_into_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest_path = root / "manifest.json"
            manifest = self.runner.preflight(
                repository, manifest_path, self.write_attestation(root, repository)
            )
            script = (
                "import os,pathlib; "
                "[pathlib.Path(os.environ[k]).joinpath('probe').write_text('ok') "
                "for k in ('HOME','TMPDIR','XDG_CACHE_HOME','npm_config_cache')]"
            )
            self.assertEqual(
                self.runner.execute(manifest_path, [sys.executable, "-c", script], 10), 0
            )
            sandbox = Path(manifest["sandbox_root"])
            for value in manifest["environment"].values():
                self.assertTrue(Path(value, "probe").is_file())
                self.assertTrue(Path(value).is_relative_to(sandbox))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_mutation_rechecks_primary_directed_symlinks_created_after_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest_path = root / "manifest.json"
            manifest = self.runner.preflight(
                repository, manifest_path, self.write_attestation(root, repository)
            )
            os.symlink(repository / "packages", Path(manifest["sandbox_root"]) / "late-link")
            with self.assertRaises(Exception):
                self.runner.mutate(manifest_path, "MUT-001", "packages/app/source.ts", b"mutant\n")

    def test_finish_rejects_missing_manifest_and_primary_write_even_after_restore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(self.runner.RunGateError):
                self.runner.finish(root / "missing.json", {}, {}, {})
            manifest = {
                "status": "ready", "run_id": "a" * 32,
                "primary_root": "/primary", "sandbox_root": "/sandbox",
            }
            report = {
                "write_mode": "review-only",
                "postflight": {
                    "primary_written_during_run": True,
                    "primary_final_hash_unchanged": True,
                },
            }
            with self.assertRaises(self.runner.RunGateError):
                self.runner.finish_document(manifest, report, {}, [])

    def test_abort_removes_manifest_ledger_and_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest_path = root / "manifest.json"
            manifest = self.runner.preflight(
                repository, manifest_path, self.write_attestation(root, repository)
            )
            self.runner.abort(manifest_path)
            self.assertFalse(manifest_path.exists())
            self.assertFalse(Path(manifest["ledger_path"]).exists())
            self.assertFalse(Path(manifest["sandbox_root"]).exists())

    def test_end_to_end_finish_binds_identity_validates_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.make_repository(root)
            manifest_path = root / "manifest.json"
            manifest = self.runner.preflight(
                repository, manifest_path, self.write_attestation(root, repository)
            )
            for mutation_id in ("MUT-001", "MUT-002", "MUT-003"):
                self.runner.register_prebuilt(
                    manifest_path, mutation_id, "packages/app/source.ts"
                )
            ledger_path = Path(manifest["ledger_path"])
            contract = json.loads(
                (ROOT / "demo/subscription_renewal/intent-contract.json").read_text()
            )
            report = json.loads(
                (ROOT / "demo/subscription_renewal/expected-elenchus-report.json").read_text()
            )
            review = json.loads(
                (ROOT / "demo/subscription_renewal/canonical-review.json").read_text()
            )
            report["run"] = {
                "id": manifest["run_id"],
                "entrypoint": "socratic/scripts/run_review.py",
                "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "ledger_sha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
            }
            report["isolation"].update({
                "primary_root": manifest["primary_root"],
                "sandbox_root": manifest["sandbox_root"],
                "host_protection": {
                    "mode": "os-read-only", "verified": True,
                    "details": "host fixture denied a write probe",
                },
                "write_monitor": {
                    "mode": "unavailable", "verified": False, "details": "not needed",
                },
            })
            rendered = self.runner.finish(
                manifest_path, contract, report, review, ROOT / "schemas"
            )
            self.assertTrue(rendered.startswith("Review This:\n"))
            self.assertFalse(manifest_path.exists())
            self.assertFalse(ledger_path.exists())
            self.assertFalse(Path(manifest["sandbox_root"]).exists())


if __name__ == "__main__":
    unittest.main()
