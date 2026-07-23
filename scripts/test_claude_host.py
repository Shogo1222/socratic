#!/usr/bin/env python3
"""Tests for the launcher-owned Claude Host broker."""

import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ClaudeHostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.host = load("socratic_claude_host", ROOT / "scripts/claude_host.py")
        cls.hook = load("socratic_claude_hook", ROOT / "hooks/claude_preflight.py")
        cls.runner = load("socratic_runner_host", ROOT / "skills/socratic/scripts/run_review.py")

    def test_live_broker_allows_hook_and_issues_runner_grant(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            root = Path(directory)
            repository = root / "repository"
            (repository / ".git").mkdir(parents=True)
            (repository / "source.py").write_text("value = 1\n")
            storage = root / "storage"
            storage.mkdir()
            socket_path = root / "host.sock"
            token = "t" * 48
            grant = {
                "adapter_id": "claude-code-disposable-host-v1",
                "run_id": "a" * 32,
                "run_nonce": "n" * 48,
                "storage_root": str(storage),
                "protection_mode": "host-events",
                "protection_details": "fixture disposable workspace",
            }
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(socket_path))
            server.listen(4)
            stop = threading.Event()
            thread = threading.Thread(
                target=self.host._serve, args=(server, token, grant, stop), daemon=True
            )
            thread.start()
            environment = {
                "SOCRATIC_HOST_SOCKET": str(socket_path),
                "SOCRATIC_HOST_TOKEN": token,
            }
            try:
                with patch.dict(os.environ, environment, clear=False):
                    decision = self.hook.evaluate({
                        "hook_event_name": "UserPromptSubmit", "prompt": "/socratic:socratic review"
                    })
                    self.assertEqual(decision, {})
                    adapter = self.runner.ClaudeSocketHostAdapter.from_environment()
                    manifest, manifest_path = self.runner.preflight_with_host(repository, adapter)
                    self.assertEqual(manifest["status"], "ready")
                    self.assertEqual(manifest["host"]["adapter_id"], grant["adapter_id"])
                    self.runner.abort(manifest_path)
            finally:
                stop.set()
                server.close()
                thread.join(timeout=1)

    def test_missing_or_wrong_broker_token_stays_blocked(self) -> None:
        payload = {"hook_event_name": "UserPromptSubmit", "prompt": "/socratic:socratic"}
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.hook.evaluate(payload)["decision"], "block")

    def test_launcher_runs_claude_only_in_disposable_copy(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            primary = Path(directory) / "primary"
            (primary / ".git").mkdir(parents=True)
            (primary / "source.py").write_text("original\n")
            observed = {}

            def fake_run(argv, *, cwd, env, check):
                observed.update({"argv": argv, "cwd": Path(cwd), "env": env, "check": check})
                self.assertNotEqual(Path(cwd).resolve(), primary.resolve())
                self.assertEqual((Path(cwd) / "source.py").read_text(), "original\n")
                self.assertEqual(
                    self.host.request(Path(env["SOCRATIC_HOST_SOCKET"]), env["SOCRATIC_HOST_TOKEN"]),
                    {"status": "ready"},
                )
                return type("Completed", (), {"returncode": 0})()

            with patch.object(self.host.subprocess, "run", side_effect=fake_run):
                self.assertEqual(self.host.launch(primary, ROOT, "claude", ["--model", "sonnet"]), 0)
            self.assertEqual((primary / "source.py").read_text(), "original\n")
            self.assertFalse(observed["cwd"].exists())
            self.assertEqual(observed["argv"][:2], ["claude", "--plugin-dir"])


if __name__ == "__main__":
    unittest.main()
