#!/usr/bin/env python3
"""Compare two recorded devloop runs (default: the two most recent)."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from pathlib import Path

DEVLOOP_HOME = Path(os.environ.get("SOCRATIC_DEVLOOP_HOME", Path.home() / ".socratic-devloop"))
RUNS_DIR = DEVLOOP_HOME / "runs"

META_KEYS = ("duration_s", "num_turns", "is_error", "subtype",
             "permission_denials", "target_tree_clean", "total_cost_usd")


def load(name: str) -> tuple:
    path = RUNS_DIR / name
    meta = json.loads((path / "meta.json").read_text())
    review = (path / "review.md").read_text()
    return meta, review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="*", help="two run directory names; default: latest two")
    args = parser.parse_args()

    if args.runs:
        if len(args.runs) != 2:
            parser.error("pass exactly two run names, or none for the latest two")
        old_name, new_name = args.runs
    else:
        recorded = sorted(p.name for p in RUNS_DIR.iterdir() if (p / "meta.json").is_file())
        if len(recorded) < 2:
            print("need at least two recorded runs")
            return 1
        old_name, new_name = recorded[-2], recorded[-1]

    old_meta, old_review = load(old_name)
    new_meta, new_review = load(new_name)

    print("old:", old_name, "| socratic", old_meta["socratic"]["rev"],
          old_meta["socratic"]["working_tree_digest"] if old_meta["socratic"]["dirty"] else "clean")
    print("new:", new_name, "| socratic", new_meta["socratic"]["rev"],
          new_meta["socratic"]["working_tree_digest"] if new_meta["socratic"]["dirty"] else "clean")
    print()
    for key in META_KEYS:
        old_value, new_value = old_meta.get(key), new_meta.get(key)
        marker = "  " if old_value == new_value else "->"
        print("{} {:<20} {} | {}".format(marker, key, old_value, new_value))
    print()

    diff = list(difflib.unified_diff(
        old_review.splitlines(keepends=True), new_review.splitlines(keepends=True),
        fromfile=old_name + "/review.md", tofile=new_name + "/review.md"))
    if diff:
        sys.stdout.writelines(diff)
    else:
        print("review.md identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
