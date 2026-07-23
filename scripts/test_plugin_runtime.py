#!/usr/bin/env python3
"""Tests for automatic Plugin-managed Python dependency resolution."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "socratic_plugin_runtime_tested", ROOT / "scripts/plugin_runtime.py"
)
assert SPEC and SPEC.loader
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class PluginRuntimeTest(unittest.TestCase):
    def test_uses_current_interpreter_when_dependencies_exist(self) -> None:
        self.assertEqual(runtime.ensure_runtime(ROOT), Path(sys.executable).resolve())

    def test_bootstraps_isolated_runtime_when_dependencies_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            runtime.os.environ, {"PLUGIN_DATA": directory}, clear=True
        ), patch.object(runtime.importlib.util, "find_spec", return_value=None), patch.object(
            runtime, "_ready", side_effect=[False, True]
        ), patch.object(runtime.venv, "EnvBuilder") as builder, patch.object(
            runtime.subprocess, "run"
        ) as run:
            python = runtime.ensure_runtime(ROOT)
            self.assertTrue(python.is_relative_to(Path(directory).resolve()))
            builder.assert_called_once_with(with_pip=True, clear=True)
            run.assert_called_once()
            command = run.call_args.args[0]
            self.assertEqual(command[-2:], list(runtime.REQUIREMENTS))


if __name__ == "__main__":
    unittest.main()
