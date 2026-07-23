#!/usr/bin/env python3
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from typing import Dict, Optional
from unittest.mock import patch

import check_repository


class ReleaseVersionTest(unittest.TestCase):
    def test_accepts_exact_semantic_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "VERSION").write_text("0.2.1\n", encoding="utf-8")

            with patch.object(check_repository, "ROOT", root):
                check_repository.check_release_version()

    def test_rejects_invalid_or_padded_version(self) -> None:
        for value in ("v0.2.1\n", "0.2\n", " 0.2.1\n", "0.2.1\n\n"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "VERSION").write_text(value, encoding="utf-8")

                with patch.object(check_repository, "ROOT", root):
                    with redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit):
                            check_repository.check_release_version()


class DistributionDocumentationTest(unittest.TestCase):
    DOCUMENTS = (
        "docs/security-model.md",
        "docs/ja/security-model.md",
        "docs/enterprise-installation.md",
        "docs/ja/enterprise-installation.md",
    )

    def make_documents(self, root: Path, counts: Optional[Dict[str, int]] = None) -> None:
        counts = counts or {}
        for relative in self.DOCUMENTS:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            count = counts.get(relative, 21)
            path.write_text(
                f"<!-- socratic-distribution-file-count: {count} -->\n"
                "<!-- socratic-plugin-file-count: 28 -->\n",
                encoding="utf-8",
            )

    def test_distribution_count_matches_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_documents(root)
            with patch.object(check_repository, "ROOT", root), patch.object(
                check_repository, "EXPECTED_DISTRIBUTION_FILE_COUNT", 21
            ), patch.object(check_repository, "EXPECTED_PLUGIN_FILE_COUNT", 28):
                check_repository.check_distribution_documentation()

    def test_rejects_expected_files_change_without_documentation_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_documents(root)
            with patch.object(check_repository, "ROOT", root), patch.object(
                check_repository, "EXPECTED_DISTRIBUTION_FILE_COUNT", 22
            ), patch.object(check_repository, "EXPECTED_PLUGIN_FILE_COUNT", 28), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    check_repository.check_distribution_documentation()

    def test_rejects_english_or_japanese_count_mismatch(self) -> None:
        for stale_document in (
            "docs/enterprise-installation.md", "docs/ja/enterprise-installation.md"
        ):
            with self.subTest(stale_document=stale_document), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_documents(root, {stale_document: 16})
                with patch.object(check_repository, "ROOT", root), patch.object(
                    check_repository, "EXPECTED_DISTRIBUTION_FILE_COUNT", 21
                ), patch.object(check_repository, "EXPECTED_PLUGIN_FILE_COUNT", 28), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        check_repository.check_distribution_documentation()


class PluginStructureTest(unittest.TestCase):
    def make_plugin(self, root: Path, *, version: str = "0.3.0-alpha.3") -> None:
        (root / ".codex-plugin").mkdir(parents=True)
        (root / ".claude-plugin").mkdir(parents=True)
        (root / "hooks").mkdir()
        (root / "skills/socratic/agents").mkdir(parents=True)
        (root / "VERSION").write_text("0.3.0-alpha.3\n", encoding="utf-8")
        (root / ".claude-plugin/plugin.json").write_text(
            json.dumps({"name": "socratic", "version": version}), encoding="utf-8"
        )
        (root / ".codex-plugin/plugin.json").write_text(
            json.dumps(
                {
                    "name": "socratic",
                    "version": version,
                    "skills": "./skills/",
                    "hooks": "./hooks/codex-hooks.json",
                }
            ),
            encoding="utf-8",
        )
        codex_hooks = {
            "hooks": {"UserPromptSubmit": [{"hooks": [{
                "type": "command",
                "command": 'python3 "$PLUGIN_ROOT/hooks/socratic_preflight.py"',
            }]}]}
        }
        (root / "hooks/codex-hooks.json").write_text(json.dumps(codex_hooks), encoding="utf-8")
        (root / "hooks/hooks.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "UserPromptSubmit": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/claude_preflight.py"',
                                    }
                                ]
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        (root / "hooks/socratic_preflight.py").write_text("# fixture\n", encoding="utf-8")
        (root / "hooks/claude_preflight.py").write_text("# fixture\n", encoding="utf-8")
        (root / "skills/socratic/agents/openai.yaml").write_text(
            "policy:\n  allow_implicit_invocation: false\n", encoding="utf-8"
        )

    def test_accepts_versioned_pre_agent_plugin_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_plugin(root)
            with patch.object(check_repository, "ROOT", root):
                check_repository.check_plugin_gate()

    def test_rejects_plugin_version_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_plugin(root, version="0.2.8")
            with patch.object(check_repository, "ROOT", root), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    check_repository.check_plugin_gate()


if __name__ == "__main__":
    unittest.main()
