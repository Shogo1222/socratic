#!/usr/bin/env python3
"""Host-gated fail-closed entrypoint for Socratic Review-only mutation runs."""

# This file stays a thin compatibility entrypoint on purpose: the run-manifest
# and report schemas pin run.entrypoint to the const socratic/scripts/
# run_review.py, Host hooks inject and trust that exact resolved path, and the
# docs and tests load this file directly. The implementation lives in the
# runner/ package next to this file; every public and underscore-prefixed name
# is re-exported here so loading this module keeps behaving like the previous
# single-file Runner.

import sys
from pathlib import Path

_SCRIPTS_DIRECTORY = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIRECTORY not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIRECTORY)

from runner import (  # noqa: E402 - sys.path bootstrap must run first
    cli,
    constants,
    execution,
    hashing,
    hostapi,
    inspection,
    ledger,
    lifecycle,
    reporting,
    scaffolds,
    snapshots,
)

# Merge each module's namespace in dependency order so later layers win on any
# collision, exactly as the original top-to-bottom module definition order did.
for _runner_module in (
    constants,
    hashing,
    hostapi,
    ledger,
    lifecycle,
    snapshots,
    scaffolds,
    inspection,
    execution,
    reporting,
    cli,
):
    globals().update({
        key: value
        for key, value in vars(_runner_module).items()
        if not key.startswith("__")
    })
del _runner_module


if __name__ == "__main__":
    raise SystemExit(main())
