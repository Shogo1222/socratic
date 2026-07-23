#!/usr/bin/env python3
"""Resolve or provision the Plugin-managed Python runtime used by Socratic."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import time
import venv
from pathlib import Path


REQUIREMENTS = ("jsonschema==4.25.1", "referencing==0.36.2")


def _ready(python: Path) -> bool:
    with tempfile.TemporaryDirectory(prefix="socratic-runtime-probe-") as directory:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {
                "COMSPEC", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "PATHEXT",
                "SYSTEMDRIVE", "SYSTEMROOT", "TZ", "WINDIR",
            }
        }
        environment.update({
            "HOME": directory,
            "TMPDIR": directory,
            "XDG_CACHE_HOME": directory,
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        try:
            completed = subprocess.run(
                [str(python), "-I", "-c", "import jsonschema, referencing"],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
            return completed.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False


def _data_root(plugin_root: Path) -> Path:
    for key in ("PLUGIN_DATA", "CLAUDE_PLUGIN_DATA", "CURSOR_PLUGIN_DATA"):
        value = os.environ.get(key)
        if value:
            return Path(value).resolve(strict=False) / "python-runtime"
    digest = hashlib.sha256(str(plugin_root.resolve()).encode()).hexdigest()[:20]
    return Path(tempfile.gettempdir()) / "socratic-plugin-runtime" / digest


def ensure_runtime(plugin_root: Path) -> Path:
    current = Path(sys.executable).resolve()
    if _ready(current):
        return current

    root = _data_root(plugin_root)
    python = (
        root / "venv" / "Scripts" / "python.exe"
        if os.name == "nt"
        else root / "venv" / "bin" / "python3"
    )
    if _ready(python):
        return python
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    lock = root / "bootstrap.lock"
    owner = False
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        owner = True
    except FileExistsError:
        for _ in range(120):
            if _ready(python):
                return python
            time.sleep(0.5)
        raise RuntimeError("Plugin runtime bootstrap did not complete")

    try:
        venv.EnvBuilder(with_pip=True, clear=True).create(root / "venv")
        subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", *REQUIREMENTS],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=180,
        )
        if not _ready(python):
            raise RuntimeError("Plugin runtime dependencies remain unavailable")
        return python
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("Plugin runtime dependency bootstrap failed") from error
    finally:
        if owner:
            lock.unlink(missing_ok=True)
