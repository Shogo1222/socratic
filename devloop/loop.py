#!/usr/bin/env python3
"""Devloop: run the working-tree Socratic plugin against a fixed PR fixture, keep every result.

Commands:
  run            execute one headless review against the fixture and record the outcome
  list           list recorded runs
  clean-sessions remove /tmp/socratic-sessions entries whose broker is dead and whose
                 primary points at a devloop fixture

Runs and fixtures live outside the repository (default ~/.socratic-devloop,
override with SOCRATIC_DEVLOOP_HOME) so the plugin working tree stays clean and
the fixture is never nested inside the plugin root.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

SOCRATIC_ROOT = Path(__file__).resolve().parent.parent
DEVLOOP_HOME = Path(os.environ.get("SOCRATIC_DEVLOOP_HOME", Path.home() / ".socratic-devloop"))
RUNS_DIR = DEVLOOP_HOME / "runs"
FIXTURES_DIR = DEVLOOP_HOME / "fixtures"
SESSIONS_DIR = Path("/tmp/socratic-sessions")

DEFAULT_PROMPT = (
    "/socratic:socratic review the change from main to HEAD in this repository. "
    "This is a non-interactive run: when you would ask a structured question, "
    "choose the recommended option and continue. Discard run artifacts at the end."
)

FIXTURE_BASE_SOURCE = '''\
from dataclasses import dataclass
from datetime import date, timedelta


class RenewalError(Exception):
    pass


PLAN_DAYS = {"monthly": 30, "annual": 365}


@dataclass
class Subscription:
    plan: str
    end_date: date


def renew(subscription: Subscription, today: date) -> Subscription:
    if subscription.end_date < today:
        raise RenewalError("subscription expired")
    days = PLAN_DAYS[subscription.plan]
    return Subscription(subscription.plan, subscription.end_date + timedelta(days=days))
'''

# Head flips the expiry boundary: renewal on the end date itself is now rejected.
FIXTURE_HEAD_SOURCE = FIXTURE_BASE_SOURCE.replace(
    "if subscription.end_date < today:",
    "if subscription.end_date <= today:",
)

# Deliberately misses the end_date == today boundary on both revisions.
FIXTURE_TESTS = '''\
from datetime import date

import pytest

from subscription import PLAN_DAYS, RenewalError, Subscription, renew


def test_renew_extends_active_subscription():
    subscription = Subscription("monthly", date(2026, 8, 10))
    renewed = renew(subscription, date(2026, 7, 1))
    assert (renewed.end_date - subscription.end_date).days == PLAN_DAYS["monthly"]


def test_renew_rejects_expired_subscription():
    subscription = Subscription("monthly", date(2026, 6, 1))
    with pytest.raises(RenewalError):
        renew(subscription, date(2026, 7, 1))
'''

# Write/Edit stay listed so the plugin's own PreToolUse gate — not headless
# auto-deny — is the layer that decides write attempts during a run.
FIXTURE_SETTINGS = {
    "permissions": {
        "allow": ["Bash", "Bash(*)", "Read", "Read(*)", "Grep", "Glob", "Write", "Edit"],
    }
}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "devloop", "GIT_AUTHOR_EMAIL": "devloop@local",
             "GIT_COMMITTER_NAME": "devloop", "GIT_COMMITTER_EMAIL": "devloop@local"},
    )
    return result.stdout.strip()


def _write_settings(fixture: Path) -> None:
    settings_dir = fixture / ".claude"
    settings_dir.mkdir(exist_ok=True)
    (settings_dir / "settings.json").write_text(json.dumps(FIXTURE_SETTINGS, indent=2) + "\n")


def build_fixture(fresh: bool = False) -> Path:
    fixture = FIXTURES_DIR / "expiry_pr"
    if fixture.exists():
        if not fresh:
            _write_settings(fixture)
            return fixture
        shutil.rmtree(fixture)
    fixture.mkdir(parents=True)
    _git(fixture, "init", "-q", "-b", "main")
    (fixture / "subscription.py").write_text(FIXTURE_BASE_SOURCE)
    (fixture / "test_subscription.py").write_text(FIXTURE_TESTS)
    _git(fixture, "add", "-A")
    _git(fixture, "commit", "-qm", "base: renewal allowed through the end date")
    _git(fixture, "checkout", "-qb", "pr/expiry-boundary")
    (fixture / "subscription.py").write_text(FIXTURE_HEAD_SOURCE)
    _git(fixture, "add", "-A")
    _git(fixture, "commit", "-qm", "head: reject renewal on the end date")
    _write_settings(fixture)
    return fixture


def socratic_state() -> dict:
    rev = _git(SOCRATIC_ROOT, "rev-parse", "--short", "HEAD")
    status = _git(SOCRATIC_ROOT, "status", "--porcelain")
    diff = subprocess.run(
        ["git", "-C", str(SOCRATIC_ROOT), "diff"], capture_output=True, text=True
    ).stdout
    digest = hashlib.sha256((status + "\n" + diff).encode()).hexdigest()[:12]
    return {"rev": rev, "dirty": bool(status), "working_tree_digest": digest}


def _session_dirs() -> set:
    if not SESSIONS_DIR.is_dir():
        return set()
    return {p.name for p in SESSIONS_DIR.iterdir() if p.is_dir()}


def _tree_snapshot(repo: Path) -> str:
    head = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "status", "--porcelain")
    return head + "\n" + status


def run_once(args: argparse.Namespace) -> int:
    target = Path(args.target).resolve() if args.target else build_fixture(fresh=args.fresh_fixture)
    prompt = args.prompt or DEFAULT_PROMPT
    label = args.label or "run"
    started = _dt.datetime.now(_dt.timezone.utc)
    record = RUNS_DIR / (started.strftime("%Y%m%dT%H%M%SZ") + "-" + label)
    record.mkdir(parents=True)

    before_tree = _tree_snapshot(target)
    before_sessions = _session_dirs()
    t0 = time.monotonic()
    cli = subprocess.run(
        ["claude", "-p", prompt,
         "--plugin-dir", str(SOCRATIC_ROOT),
         "--output-format", "stream-json", "--verbose",
         "--max-turns", str(args.max_turns)],
        cwd=target, capture_output=True, text=True,
    )
    duration = round(time.monotonic() - t0, 1)

    # stream-json records every message, so checkpoint ordering (Mission first,
    # Review Type, Diff understanding) is verifiable — the final result alone isn't.
    (record / "transcript.jsonl").write_text(cli.stdout)
    if cli.stderr:
        (record / "stderr.log").write_text(cli.stderr)
    payload = {}
    assistant_texts = []
    for line in cli.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            payload = event
        elif event.get("type") == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                    assistant_texts.append(block["text"])
    (record / "assistant-messages.md").write_text(
        "\n\n---\n\n".join(assistant_texts) or "(no assistant text)\n")
    (record / "cli.json").write_text(json.dumps(payload, indent=2))
    (record / "review.md").write_text(payload.get("result") or "(no result text)\n")

    # Attribute sessions by primary_root: concurrent interactive runs on other
    # repositories must not leak into this record.
    new_sessions = []
    for name in sorted(_session_dirs() - before_sessions):
        state = SESSIONS_DIR / name / "state.json"
        try:
            primary = json.loads(state.read_text()).get("primary_root", "")
        except (OSError, json.JSONDecodeError):
            continue
        if Path(primary).resolve() != target:
            continue
        new_sessions.append(name)
    for name in new_sessions:
        state = SESSIONS_DIR / name / "state.json"
        if state.is_file():
            shutil.copy(state, record / ("session-" + name + ".json"))
        storage = SESSIONS_DIR / name / "host-storage"
        if storage.is_dir() and any(storage.rglob("*")):
            # Copy evidence only: workspace-* holds materialized clones with
            # node_modules, and copytree flattens copy-on-write clones into
            # real bytes (a single run record once reached 33GB).
            shutil.copytree(
                storage, record / ("host-storage-" + name), dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("workspace-*"),
            )

    # Post-run bookkeeping must never lose the record: a stale index.lock or a
    # killed inner task can make these git calls fail after a 15-minute run.
    try:
        socratic = socratic_state()
    except Exception as error:  # noqa: BLE001
        socratic = {"error": str(error)}
    try:
        tree_clean = _tree_snapshot(target) == before_tree
    except Exception as error:  # noqa: BLE001
        tree_clean = "unknown: " + str(error)

    meta = {
        "label": label,
        "started_utc": started.isoformat(),
        "duration_s": duration,
        "prompt": prompt,
        "target": str(target),
        "socratic": socratic,
        "exit_code": cli.returncode,
        "subtype": payload.get("subtype"),
        "is_error": payload.get("is_error"),
        "num_turns": payload.get("num_turns"),
        "total_cost_usd": payload.get("total_cost_usd"),
        "session_id": payload.get("session_id"),
        "permission_denials": len(payload.get("permission_denials") or []),
        "target_tree_clean": tree_clean,
        "new_socratic_sessions": new_sessions,
    }
    (record / "meta.json").write_text(json.dumps(meta, indent=2))

    print("recorded:", record)
    print(json.dumps({k: meta[k] for k in (
        "duration_s", "subtype", "is_error", "num_turns",
        "permission_denials", "target_tree_clean", "socratic")}, indent=2))
    return 0 if not meta["is_error"] else 1


def list_runs(_args: argparse.Namespace) -> int:
    if not RUNS_DIR.is_dir():
        print("no runs yet")
        return 0
    for path in sorted(RUNS_DIR.iterdir()):
        meta_file = path / "meta.json"
        if not meta_file.is_file():
            continue
        meta = json.loads(meta_file.read_text())
        print("{}  {:>6}s  turns={:<3} err={}  rev={}{} tree_clean={}".format(
            path.name, meta.get("duration_s"), meta.get("num_turns"),
            meta.get("is_error"), meta["socratic"]["rev"],
            "+dirty:" + meta["socratic"]["working_tree_digest"] if meta["socratic"]["dirty"] else "",
            meta.get("target_tree_clean")))
    return 0


def clean_sessions(_args: argparse.Namespace) -> int:
    removed = []
    for name in sorted(_session_dirs()):
        state_file = SESSIONS_DIR / name / "state.json"
        try:
            state = json.loads(state_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        primary = state.get("primary_root", "")
        if str(DEVLOOP_HOME) not in primary and "fixture-repo" not in primary:
            continue
        pid = state.get("pid")
        if pid:
            try:
                os.kill(int(pid), 0)
                continue  # broker still alive; leave it to its own lifecycle
            except (OSError, ValueError):
                pass
        shutil.rmtree(SESSIONS_DIR / name, ignore_errors=True)
        removed.append(name)
    print("removed:", removed or "nothing")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="execute one recorded review run")
    run_parser.add_argument("--label", help="short name embedded in the run directory")
    run_parser.add_argument("--target", help="existing repo to review (default: built-in expiry fixture)")
    run_parser.add_argument("--prompt", help="override the review prompt")
    run_parser.add_argument("--max-turns", type=int, default=120)
    run_parser.add_argument("--fresh-fixture", action="store_true", help="rebuild the fixture from scratch")
    run_parser.set_defaults(func=run_once)

    list_parser = sub.add_parser("list", help="list recorded runs")
    list_parser.set_defaults(func=list_runs)

    clean_parser = sub.add_parser("clean-sessions", help="remove dead devloop broker sessions")
    clean_parser.set_defaults(func=clean_sessions)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
