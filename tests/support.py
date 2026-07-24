"""Shared paths and dynamic imports for repository tests."""

import atexit
import contextlib
import gc
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType


def _reap_test_brokers() -> None:
    """Terminate Host brokers that hook-module instances left detached.

    Brokers detach on purpose (start_new_session) and outlive the hook process
    that spawned them, so a test that exercises a hook can end with a running
    broker whose Popen object no test can reach. Reaping them here keeps the
    suite from leaking processes and from warning about unreaped children.
    """
    for candidate in gc.get_objects():
        if not isinstance(candidate, subprocess.Popen) or candidate.returncode is not None:
            continue
        arguments = candidate.args if isinstance(candidate.args, list) else []
        if any(str(argument).endswith("claude_host.py") for argument in arguments):
            with contextlib.suppress(OSError):
                candidate.terminate()
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                candidate.wait(timeout=1)


atexit.register(_reap_test_brokers)


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# Keep every Host broker the suite starts inside a per-process directory so
# concurrent test runs never collide in the shared /tmp/socratic-sessions root.
# The directory must stay short: `<root>/<20-hex>/host.sock` has to fit within
# the ~104-byte AF_UNIX socket path limit, which rules out macOS $TMPDIR.
if not os.environ.get("SOCRATIC_SESSION_ROOT"):
    _session_root = tempfile.mkdtemp(prefix="socratic-t-", dir="/tmp")
    os.environ["SOCRATIC_SESSION_ROOT"] = _session_root
    atexit.register(shutil.rmtree, _session_root, True)


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
