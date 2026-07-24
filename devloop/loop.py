#!/usr/bin/env python3
"""Devloop: run the working-tree Socratic plugin against a fixed PR fixture, keep every result.

Commands:
  run            execute one headless review against the fixture and record the outcome
  list           list recorded runs
  clean-sessions remove /tmp/socratic-sessions entries whose broker is dead and whose
                 primary resolves inside the devloop home

Runs and fixtures live outside the repository (default ~/.socratic-devloop,
override with SOCRATIC_DEVLOOP_HOME). Records are written 0600 inside 0700
directories, and host tokens/nonces are redacted before anything is persisted.
A run exits 0 only when the CLI succeeded, the canonical four-block surface was
extracted, the target tree content is byte-identical, and no broker session for
the target survived the run.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
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

CANONICAL_MARKERS = ("Review This", "We Verified", "Still at Risk", "Copy-ready")

REDACTIONS = [
    (re.compile(r"(--host-token[ =])[A-Za-z0-9_\-.]+"), r"\1[REDACTED]"),
    (re.compile(r"(SOCRATIC_HOST_TOKEN[= ])[A-Za-z0-9_\-.]+"), r"\1[REDACTED]"),
    (re.compile(r'("(?:token|run_nonce)"\s*:\s*")[^"]+(")'), r"\1[REDACTED]\2"),
    (re.compile(r'(\\"(?:token|run_nonce)\\"\s*:\s*\\")(?:[^"\\]|\\(?!"))+(\\")'), r"\1[REDACTED]\2"),
]

DEFAULT_PROMPT = (
    "/socratic:socratic review the change from main to HEAD in this repository. "
    "This is a non-interactive run: when you would ask a structured question, "
    "choose the recommended option, say so, and continue. Execute every Runner "
    "command synchronously in the foreground; never background one or end the "
    "turn to wait. Discard run artifacts at the end."
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


def redact(text: str) -> str:
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def _secure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _secure_write(path: Path, text: str) -> None:
    path.write_text(redact(text), encoding="utf-8")
    os.chmod(path, 0o600)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "devloop", "GIT_AUTHOR_EMAIL": "devloop@local",
             "GIT_COMMITTER_NAME": "devloop", "GIT_COMMITTER_EMAIL": "devloop@local"},
    )
    return result.stdout.strip()


def _git_bytes(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True
    ).stdout


def content_digest(repo: Path) -> str:
    """Digest HEAD, staged and unstaged diffs, and untracked file contents.

    `git status` alone cannot prove an unchanged tree: a file that was already
    modified before the run keeps the same status line when it is modified
    again, and untracked contents never appear in it.
    """
    hasher = hashlib.sha256()

    def feed(label: str, data: bytes) -> None:
        hasher.update(label.encode())
        hasher.update(b"\0")
        hasher.update(data)
        hasher.update(b"\0")

    feed("head", _git_bytes(repo, "rev-parse", "HEAD"))
    feed("status", _git_bytes(repo, "status", "--porcelain=v1", "-z"))
    feed("unstaged", _git_bytes(repo, "diff", "--binary"))
    feed("staged", _git_bytes(repo, "diff", "--cached", "--binary"))
    untracked = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--others", "--exclude-standard", "-z"],
        check=False, capture_output=True, text=True,
    ).stdout
    for name in sorted(part for part in untracked.split("\0") if part):
        target = repo / name
        try:
            data = target.read_bytes()
        except OSError:
            data = b"<unreadable>"
        feed("untracked:" + name, data)
    return hasher.hexdigest()


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


def _write_settings(fixture: Path) -> None:
    settings_dir = fixture / ".claude"
    settings_dir.mkdir(exist_ok=True)
    (settings_dir / "settings.json").write_text(json.dumps(FIXTURE_SETTINGS, indent=2) + "\n")


def socratic_state() -> dict:
    rev = _git(SOCRATIC_ROOT, "rev-parse", "--short", "HEAD")
    status = _git(SOCRATIC_ROOT, "status", "--porcelain")
    return {
        "rev": rev,
        "dirty": bool(status),
        "working_tree_digest": content_digest(SOCRATIC_ROOT)[:12],
    }


def _session_dirs() -> set:
    if not SESSIONS_DIR.is_dir():
        return set()
    return {p.name for p in SESSIONS_DIR.iterdir() if p.is_dir()}


def _session_primary(name: str) -> str:
    try:
        state = json.loads((SESSIONS_DIR / name / "state.json").read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    return state.get("primary_root", "")


def extract_canonical_surface(transcript_lines: list) -> str | None:
    """Return the last transcript text carrying all four canonical block headers.

    The renderer output arrives as a tool result, not necessarily as the final
    assistant message, so the final message alone cannot be trusted as the
    review surface.
    """
    candidates = []
    for line in transcript_lines:
        try:
            event = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            continue
        message = event.get("message") or {}
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            texts = []
            if block.get("type") == "text" and block.get("text"):
                texts.append(block["text"])
            if block.get("type") == "tool_result":
                content = block.get("content")
                if isinstance(content, str):
                    texts.append(content)
                elif isinstance(content, list):
                    texts.extend(
                        item.get("text", "") for item in content
                        if isinstance(item, dict) and item.get("type") == "text"
                    )
            for text in texts:
                if all(marker in text for marker in CANONICAL_MARKERS):
                    candidates.append(text)
    return candidates[-1] if candidates else None


def run_once(args: argparse.Namespace) -> int:
    _secure_dir(DEVLOOP_HOME)
    _secure_dir(RUNS_DIR)
    target = Path(args.target).resolve() if args.target else build_fixture(fresh=args.fresh_fixture)
    prompt = args.prompt or DEFAULT_PROMPT
    label = args.label or "run"
    started = _dt.datetime.now(_dt.timezone.utc)
    record = _secure_dir(RUNS_DIR / (started.strftime("%Y%m%dT%H%M%SZ") + "-" + label))

    before_digest = content_digest(target)
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

    transcript_lines = cli.stdout.splitlines()
    _secure_write(record / "transcript.jsonl", cli.stdout)
    if cli.stderr:
        _secure_write(record / "stderr.log", cli.stderr)

    payload = {}
    assistant_texts = []
    for line in transcript_lines:
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
    canonical = extract_canonical_surface(transcript_lines)

    _secure_write(record / "assistant-messages.md",
                  "\n\n---\n\n".join(assistant_texts) or "(no assistant text)\n")
    _secure_write(record / "cli.json", json.dumps(payload, indent=2))
    _secure_write(record / "final-message.md", payload.get("result") or "(no result text)\n")
    _secure_write(record / "review.md",
                  canonical or "(canonical four-block surface not found in transcript)\n")

    # Attribute sessions by primary_root: concurrent interactive runs on other
    # repositories must not leak into this record.
    new_sessions = []
    for name in sorted(_session_dirs() - before_sessions):
        primary = _session_primary(name)
        if not primary:
            continue
        try:
            if Path(primary).resolve() != target:
                continue
        except OSError:
            continue
        new_sessions.append(name)
    for name in new_sessions:
        state_file = SESSIONS_DIR / name / "state.json"
        if state_file.is_file():
            _secure_write(record / ("session-" + name + ".json"), state_file.read_text())
        storage = SESSIONS_DIR / name / "host-storage"
        if storage.is_dir() and any(storage.rglob("*")):
            # Copy evidence only: workspace-* holds materialized clones with
            # node_modules, and copytree flattens copy-on-write clones into
            # real bytes (a single run record once reached 33GB).
            copy_root = record / ("host-storage-" + name)
            shutil.copytree(storage, copy_root, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("workspace-*"))
            for path in copy_root.rglob("*"):
                if path.is_dir():
                    os.chmod(path, 0o700)
                elif path.suffix == ".json" or path.suffix == ".jsonl":
                    _secure_write(path, path.read_text(errors="replace"))
                else:
                    os.chmod(path, 0o600)

    try:
        socratic = socratic_state()
    except Exception as error:  # noqa: BLE001
        socratic = {"error": str(error)}
    try:
        after_digest = content_digest(target)
    except Exception as error:  # noqa: BLE001
        after_digest = "error: " + str(error)

    checks = {
        "cli_exit_zero": cli.returncode == 0,
        "result_event_present": bool(payload),
        "result_not_error": payload.get("is_error") is False,
        "result_subtype_success": payload.get("subtype") == "success",
        "canonical_surface_found": canonical is not None,
        "target_tree_unchanged": after_digest == before_digest,
        "sessions_cleaned": not new_sessions,
    }
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
        "target_tree_clean": checks["target_tree_unchanged"],
        "new_socratic_sessions": new_sessions,
        "checks": checks,
        "success": all(checks.values()),
    }
    _secure_write(record / "meta.json", json.dumps(meta, indent=2))

    print("recorded:", record)
    print(json.dumps({k: meta[k] for k in (
        "success", "duration_s", "subtype", "is_error", "num_turns",
        "permission_denials", "target_tree_clean", "socratic")}, indent=2))
    if not meta["success"]:
        failed = [name for name, passed in checks.items() if not passed]
        print("failed checks:", ", ".join(failed))
    return 0 if meta["success"] else 1


def list_runs(_args: argparse.Namespace) -> int:
    if not RUNS_DIR.is_dir():
        print("no runs yet")
        return 0
    for path in sorted(RUNS_DIR.iterdir()):
        meta_file = path / "meta.json"
        if not meta_file.is_file():
            continue
        meta = json.loads(meta_file.read_text())
        print("{}  ok={} {:>6}s  turns={:<3} rev={}{} tree_clean={}".format(
            path.name, meta.get("success"), meta.get("duration_s"),
            meta.get("num_turns"), meta.get("socratic", {}).get("rev"),
            "+dirty:" + meta["socratic"]["working_tree_digest"]
            if meta.get("socratic", {}).get("dirty") else "",
            meta.get("target_tree_clean")))
    return 0


def clean_sessions(_args: argparse.Namespace) -> int:
    removed = []
    home = DEVLOOP_HOME.resolve()
    for name in sorted(_session_dirs()):
        primary = _session_primary(name)
        if not primary:
            continue
        try:
            resolved = Path(primary).resolve()
        except OSError:
            continue
        if not resolved.is_relative_to(home):
            continue
        state_file = SESSIONS_DIR / name / "state.json"
        try:
            pid = json.loads(state_file.read_text()).get("pid")
        except (OSError, json.JSONDecodeError):
            pid = None
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
