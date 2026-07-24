#!/usr/bin/env python3
"""Tests for the devloop harness: redaction, canonical extraction, content digests."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import ROOT, load_module

MODULE = ROOT / "devloop/loop.py"


class DevloopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.loop = load_module("devloop_loop", MODULE)

    def test_redact_masks_tokens_in_every_persisted_form(self) -> None:
        samples = {
            "cli flag": "run_review.py preflight --host-token s3cretTOKEN-value.x --primary /p",
            "env form": "SOCRATIC_HOST_TOKEN=s3cretTOKEN env pnpm test",
            "json field": '{"token": "s3cretTOKEN", "run_nonce": "n0nceVALUE"}',
            "escaped json": '"{\\"token\\": \\"s3cretTOKEN\\", \\"run_nonce\\": \\"n0nceVALUE\\"}"',
        }
        for label, text in samples.items():
            redacted = self.loop.redact(text)
            self.assertNotIn("s3cretTOKEN", redacted, label)
            self.assertNotIn("n0nceVALUE", redacted, label)
            self.assertIn("[REDACTED]", redacted, label)

    def _transcript_line(self, block: dict, event_type: str = "user") -> str:
        return json.dumps({"type": event_type, "message": {"content": [block]}})

    def test_extract_canonical_surface_prefers_tool_result_with_all_blocks(self) -> None:
        surface = ("Socratic Review\n\nReview This:\n  ! x\n\nWe Verified:\n  y\n\n"
                   "Still at Risk:\n  z\n\nCopy-ready Comments:\n  1 comment")
        lines = [
            self._transcript_line({"type": "text", "text": "Review This mention only"},
                                  "assistant"),
            self._transcript_line({"type": "tool_result",
                                   "content": [{"type": "text", "text": surface}]}),
            self._transcript_line({"type": "text", "text": "the blocks are above"},
                                  "assistant"),
        ]
        self.assertEqual(self.loop.extract_canonical_surface(lines), surface)

    def test_extract_canonical_surface_returns_none_without_all_markers(self) -> None:
        lines = [
            self._transcript_line({"type": "text",
                                   "text": "Review This: ...\nWe Verified: ..."},
                                  "assistant"),
            "not json at all",
        ]
        self.assertIsNone(self.loop.extract_canonical_surface(lines))

    def test_extract_canonical_surface_takes_the_last_candidate(self) -> None:
        def surface(tag: str) -> str:
            return ("Review This: {0}\nWe Verified: {0}\n"
                    "Still at Risk: {0}\nCopy-ready Comments: {0}").format(tag)
        lines = [
            self._transcript_line({"type": "tool_result", "content": surface("draft")}),
            self._transcript_line({"type": "tool_result", "content": surface("final")}),
        ]
        self.assertIn("final", self.loop.extract_canonical_surface(lines))

    def test_content_digest_sees_untracked_and_staged_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)

            def git(*args: str) -> None:
                subprocess.run(
                    ["git", "-C", str(repo), *args], check=True, capture_output=True,
                    env={"PATH": "/usr/bin:/bin:/usr/local/bin",
                         "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                         "HOME": directory},
                )

            git("init", "-q", "-b", "main")
            (repo / "tracked.txt").write_text("v1\n")
            git("add", "-A")
            git("commit", "-qm", "init")
            base = self.loop.content_digest(repo)

            (repo / "untracked.txt").write_text("first\n")
            with_untracked = self.loop.content_digest(repo)
            self.assertNotEqual(base, with_untracked)

            # Same `git status` output, different content: a status-only
            # snapshot reports this as unchanged.
            (repo / "untracked.txt").write_text("second\n")
            self.assertNotEqual(with_untracked, self.loop.content_digest(repo))

            (repo / "tracked.txt").write_text("v2\n")
            git("add", "tracked.txt")
            self.assertNotEqual(with_untracked, self.loop.content_digest(repo))


if __name__ == "__main__":
    unittest.main()
