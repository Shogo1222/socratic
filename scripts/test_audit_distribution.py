#!/usr/bin/env python3
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from audit_distribution import EXPECTED_FILES, ROOT, inspect_tree


class DistributionAuditTest(unittest.TestCase):
    def copy_skills(self, destination: Path) -> Path:
        skill_root = destination / "skills"
        shutil.copytree(ROOT / "skills", skill_root)
        return skill_root

    def test_current_distribution_passes(self) -> None:
        entries, errors = inspect_tree(ROOT / "skills", require_safety_text=True)
        self.assertEqual(errors, [])
        self.assertEqual(len(entries), len(EXPECTED_FILES))

    def test_rejects_executable_and_unexpected_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            skill_root = self.copy_skills(Path(directory))
            unexpected = skill_root / "socratic" / "run.sh"
            unexpected.write_text("#!/bin/sh\n", encoding="utf-8")
            unexpected.chmod(0o755)

            _, errors = inspect_tree(skill_root, require_safety_text=True)
            self.assertTrue(any("unexpected distribution file" in error for error in errors))
            self.assertTrue(any("executable file is not allowed" in error for error in errors))

    def test_rejects_symbolic_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            skill_root = self.copy_skills(Path(directory))
            os.symlink("SKILL.md", skill_root / "socratic" / "linked.md")

            _, errors = inspect_tree(skill_root, require_safety_text=True)
            self.assertTrue(any("symbolic link is not allowed" in error for error in errors))

    def test_rejects_unapproved_external_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            skill_root = self.copy_skills(Path(directory))
            skill = skill_root / "socratic" / "SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8") + "\nhttps://unapproved.example/test\n", encoding="utf-8")

            _, errors = inspect_tree(skill_root, require_safety_text=True)
            self.assertTrue(any("external URL host is not approved" in error for error in errors))

    def test_rejects_missing_safety_rule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            skill_root = self.copy_skills(Path(directory))
            skill = skill_root / "socratic" / "SKILL.md"
            text = skill.read_text(encoding="utf-8").replace(
                "Never change local or remote Git state.",
                "Git state may be changed.",
                1,
            )
            skill.write_text(text, encoding="utf-8")

            _, errors = inspect_tree(skill_root, require_safety_text=True)
            self.assertTrue(any("required safety rule is missing" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
