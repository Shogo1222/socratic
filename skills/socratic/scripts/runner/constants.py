"""Shared constants, the run gate error, and foundation helpers for the Runner.

This is the lowest layer of the runner package: every sibling module may import
it, and it imports no sibling. Helpers used across several layers (module
loading, strict JSON, bounded reads, timing) live here so no module has to
import upward.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any


ENTRYPOINT = "socratic/scripts/run_review.py"
SOCRATIC_VERSION = "0.5.0-beta.1"
MAX_INSPECT_BYTES = 64 * 1024
MAX_INSPECT_MATCHES = 200
ARTIFACT_FILES = {
    "contract": "intent-contract.draft.json",
    "report": "mutation-report.draft.json",
    "review": "canonical-review.draft.json",
}
ARTIFACT_SCHEMAS = {
    "contract": "intent-contract.schema.json",
    "report": "mutation-report-draft.schema.json",
    "review": "canonical-review.schema.json",
}
REVIEW_TYPES = (
    "Bug Fix Review",
    "Feature Review",
    "Refactor Guard",
    "Test Assessment",
)
IGNORED_NAMES = {
    ".git", ".hg", ".svn", ".env", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next", "dist", "build",
}
DEPENDENCY_DIRECTORY_NAMES = {"node_modules"}
VIRTUAL_ENV_DIRECTORY_NAMES = {".venv", "venv"}
NODE_RUNTIME_DIRECTORY_NAMES = {".cache", ".vite", ".vitest"}
RUNTIME_DIRECTORY_NAME = ".socratic-runtime"
SANDBOX_ENV_DEFAULTS = {
    # Sandbox executions are non-interactive, and dependency state is sealed by
    # the prepared snapshot: package managers must neither prompt nor reinstall.
    # pnpm otherwise detects the cloned path change, purges node_modules, and
    # rebuilds dependencies once per mutant clone.
    "CI": "true",
    "npm_config_verify_deps_before_run": "false",
    "PYTHONDONTWRITEBYTECODE": "1",
    # The prepared snapshot intentionally contains no .git, so VCS-based
    # version backends cannot compute a version. setuptools-scm and hatch-vcs
    # honor this variable; versioningit has no env override and needs its
    # project-side default-version (surfaced through _infrastructure_hint).
    "SETUPTOOLS_SCM_PRETEND_VERSION": "0.0.0",
}

GITLESS_BUILD_SIGNATURES = (
    "versioningit",
    "setuptools-scm",
    "setuptools_scm",
    "hatch-vcs",
    "not a git repository",
    "NotVCSError",
    "unable to detect version",
)

PYTHON_MISMATCH_SIGNATURES = (
    "Requires-Python",
    "requires-python",
    "requires a different Python",
    "python_requires",
)

MISSING_EXECUTABLE_SIGNATURES = (
    "No such file or directory",
    "command not found",
)

DOCTOR_TOOLS = (
    "python3", "python", "node", "npm", "pnpm", "yarn", "uv", "pytest", "vitest",
)

# The absolute location of the pinned CLI entrypoint. Schemas, hooks, and docs
# all name socratic/scripts/run_review.py, so next-step argv and helper loads
# must keep resolving against the scripts directory, not this package.
SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT_PATH = SCRIPTS_ROOT / "run_review.py"


class RunGateError(RuntimeError):
    """Raised when a run cannot satisfy the mandatory safety boundary."""


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RunGateError(f"cannot load required helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _skills_root() -> Path:
    return SCRIPTS_ROOT.parents[1]


def _validator_module():
    return _load_module(
        "socratic_validate_and_render",
        SCRIPTS_ROOT / "validate_and_render.py",
    )


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RunGateError(f"strict JSON load failed for {path}: {error}") from error


def _safe_relative_path(raw: str) -> Path:
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts or "\\" in raw:
        raise RunGateError("path must be a safe repository-relative path")
    if any(
        part == ".env"
        or part.startswith(".env.")
        or part in {".git", ".hg", ".svn", "node_modules"}
        for part in relative.parts
    ):
        raise RunGateError("path is excluded from Socratic inspection")
    return relative


def _bounded_text(path: Path, *, limit: int = MAX_INSPECT_BYTES) -> str:
    if path.is_symlink() or not path.is_file():
        raise RunGateError(f"inspection target is not a regular file: {path}")
    payload = path.read_bytes()
    if len(payload) > limit:
        raise RunGateError(f"inspection target exceeds {limit} bytes: {path}")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RunGateError(f"inspection target is not UTF-8 text: {path}") from error


@contextlib.contextmanager
def _timed(timings: dict, label: str):
    """Accumulate wall-clock milliseconds for a Runner-internal segment.

    Ledger command events record external subprocess time only; Runner
    overhead (content hashing, clone creation, sandbox removal, validation)
    was invisible in every report. Timings stay out of the hash-chained
    ledger: they are exposed through public command results and stderr.
    """
    started = time.monotonic()
    try:
        yield
    finally:
        timings[label] = timings.get(label, 0) + max(
            0, round((time.monotonic() - started) * 1000)
        )


def _emit_runner_timings(phase: str, timings: dict) -> None:
    print(
        json.dumps({"runner_timings_ms": {"phase": phase, **timings}}, sort_keys=True),
        file=sys.stderr,
    )
