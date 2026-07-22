#!/usr/bin/env python3
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
