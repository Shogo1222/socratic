#!/usr/bin/env python3
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "skills" / "elenchus" / "scripts" / "isolation_gate.py"
SPEC = importlib.util.spec_from_file_location("isolation_gate", MODULE_PATH)
assert SPEC and SPEC.loader
isolation_gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = isolation_gate
SPEC.loader.exec_module(isolation_gate)
IsolationGate = isolation_gate.IsolationGate
IsolationViolation = isolation_gate.IsolationViolation


class IsolationGateTest(unittest.TestCase):
    def make_roots(self, root: Path) -> tuple[Path, Path]:
        primary = root / "primary"
        sandbox = root / "sandbox"
        primary.mkdir()
        sandbox.mkdir()
        (sandbox / IsolationGate.MARKER).write_text("disposable\n", encoding="utf-8")
        return primary, sandbox

    def test_allows_and_records_only_sandbox_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            primary, sandbox = self.make_roots(Path(directory))
            gate = IsolationGate(primary, sandbox)
            target = sandbox / "src" / "handler.ts"

            gate.write_text(target, "mutant\n")

            self.assertEqual(target.read_text(encoding="utf-8"), "mutant\n")
            self.assertEqual(gate.write_events[0]["target"], str(target.resolve()))

    def test_rejects_primary_target_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            primary, sandbox = self.make_roots(Path(directory))
            target = primary / "handler.ts"
            target.write_text("original\n", encoding="utf-8")

            with self.assertRaises(IsolationViolation):
                IsolationGate(primary, sandbox).write_text(target, "mutant\n")

            self.assertEqual(target.read_text(encoding="utf-8"), "original\n")

    def test_rejects_traversal_and_outside_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary, sandbox = self.make_roots(root)
            gate = IsolationGate(primary, sandbox)

            for target in (sandbox / ".." / "primary" / "handler.ts", root / "other.ts"):
                with self.subTest(target=target), self.assertRaises(IsolationViolation):
                    gate.authorize(target)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary, sandbox = self.make_roots(root)
            os.symlink(primary, sandbox / "escape")

            with self.assertRaises(IsolationViolation):
                IsolationGate(primary, sandbox).write_text(
                    sandbox / "escape" / "handler.ts", "mutant\n"
                )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_rejects_symlink_sandbox_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary, sandbox = self.make_roots(root)
            linked = root / "linked-sandbox"
            os.symlink(sandbox, linked)
            with self.assertRaises(IsolationViolation):
                IsolationGate(primary, linked)

    def test_rejects_unmarked_or_overlapping_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = root / "primary"
            primary.mkdir()
            unmarked = root / "unmarked"
            unmarked.mkdir()

            with self.assertRaises(IsolationViolation):
                IsolationGate(primary, unmarked)
            with self.assertRaises(IsolationViolation):
                IsolationGate(primary, primary)

            nested = primary / "sandbox"
            nested.mkdir()
            (nested / IsolationGate.MARKER).write_text("disposable\n", encoding="utf-8")
            with self.assertRaises(IsolationViolation):
                IsolationGate(primary, nested)


if __name__ == "__main__":
    unittest.main()
