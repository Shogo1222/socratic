#!/usr/bin/env python3
"""Launch Claude Code in a disposable Socratic workspace with a live Host broker."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import hashlib
from pathlib import Path
from typing import Any


SESSION_ROOT = Path("/tmp/socratic-sessions")
BROKER_IDLE_TTL_SECONDS = 2 * 60 * 60
BROKER_PROCESSES: dict[str, subprocess.Popen] = {}
GITHUB_PR_URL = re.compile(
    r"https://github\.com/([^/\s]+)/([^/\s]+)/pull/([0-9]+)\b", re.IGNORECASE
)
PR_NUMBER = re.compile(r"\bPR\s*#?\s*([0-9]+)\b", re.IGNORECASE)
GITHUB_REMOTE = re.compile(
    r"(?:https://github\.com/|git@github\.com:)([^/\s:]+/[^/\s]+?)(?:\.git)?$",
    re.IGNORECASE,
)


def requested_pull_request(prompt: str) -> str | int | None:
    url = GITHUB_PR_URL.search(prompt)
    if url:
        return url.group(0)
    number = PR_NUMBER.search(prompt)
    return int(number.group(1)) if number else None


def session_target_matches(state: dict[str, Any], requested: str | int) -> bool:
    """Return whether an active Host session already represents the requested PR."""
    change = state.get("change_context")
    if not isinstance(change, dict) or change.get("source") != "github-pull-request":
        return False
    try:
        requested_number = (
            int(requested.rsplit("/", 1)[1]) if isinstance(requested, str) else requested
        )
        current_number = int(change["number"])
    except (KeyError, TypeError, ValueError):
        return False
    if current_number != requested_number:
        return False
    if isinstance(requested, str):
        current_url = change.get("url")
        return (
            isinstance(current_url, str)
            and current_url.rstrip("/") == requested.rstrip("/")
        )
    return True


def prepare_or_retarget_session(
    session_id: str,
    primary: Path,
    prompt: str,
    *,
    adapter_id: str = "claude-code-hook-host-v1",
    host_name: str = "Claude Code",
) -> tuple[dict[str, Any], bool]:
    """Start a Host session or replace it when a later prompt selects another PR."""
    state = load_live_session(session_id)
    if state is not None and request(
        Path(state.get("socket_path", "")), str(state.get("token", ""))
    ) != {"status": "ready"}:
        raise RuntimeError("existing trusted Host session is unavailable")
    requested = requested_pull_request(prompt)
    if state is not None and requested is not None and not session_target_matches(
        state, requested
    ):
        state = prepare_session(
            session_id,
            primary,
            adapter_id=adapter_id,
            host_name=host_name,
            prompt=prompt,
        )
        return state, True
    if state is not None:
        return state, False
    return (
        prepare_session(
            session_id,
            primary,
            adapter_id=adapter_id,
            host_name=host_name,
            prompt=prompt,
        ),
        False,
    )


def materialize_pull_request(
    primary: Path, storage: Path, requested: str | int
) -> dict[str, str | int]:
    number = int(requested.rsplit("/", 1)[1]) if isinstance(requested, str) else requested
    metadata_process = subprocess.run(
        [
            "gh", "pr", "view", str(requested),
            "--json",
            "number,url,title,baseRefName,baseRefOid,headRefName,headRefOid",
        ],
        cwd=primary,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )
    if metadata_process.returncode != 0:
        raise RuntimeError("Host could not resolve the requested GitHub pull request")
    try:
        metadata = json.loads(metadata_process.stdout)
        if (
            metadata["number"] != number
            or (
                isinstance(requested, str)
                and metadata["url"].rstrip("/") != requested.rstrip("/")
            )
            or not re.fullmatch(r"[0-9a-f]{40}", metadata["baseRefOid"])
            or not re.fullmatch(r"[0-9a-f]{40}", metadata["headRefOid"])
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("GitHub returned malformed pull-request provenance") from error
    remote_process = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=primary,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
    )
    remote = remote_process.stdout.strip()
    if remote_process.returncode != 0 or not remote:
        raise RuntimeError("Host could not resolve the repository origin")
    if isinstance(requested, str):
        requested_match = GITHUB_PR_URL.fullmatch(requested)
        remote_match = GITHUB_REMOTE.fullmatch(remote)
        requested_repository = (
            f"{requested_match.group(1)}/{requested_match.group(2)}"
            if requested_match else ""
        )
        if (
            remote_match is None
            or remote_match.group(1).casefold() != requested_repository.casefold()
        ):
            raise RuntimeError(
                "Requested pull request does not belong to the repository origin"
            )
    mirror = storage / "materialized.git"
    subprocess.run(["git", "init", "--bare", str(mirror)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fetch_base = subprocess.run(
        [
            "git", "--git-dir", str(mirror), "fetch", "--no-tags", remote,
            f"+{metadata['baseRefOid']}:refs/socratic/base",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
    )
    if fetch_base.returncode != 0:
        raise RuntimeError(
            "Host could not materialize the exact pull-request base commit"
        )
    fetch_head = subprocess.run(
        [
            "git", "--git-dir", str(mirror), "fetch", "--no-tags", remote,
            f"+refs/pull/{number}/head:refs/socratic/head",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
    )
    if fetch_head.returncode != 0:
        raise RuntimeError(
            "Host could not materialize the exact pull-request head commit"
        )
    for reference, expected in (
        ("refs/socratic/base", metadata["baseRefOid"]),
        ("refs/socratic/head", metadata["headRefOid"]),
    ):
        resolved = subprocess.run(
            ["git", "--git-dir", str(mirror), "rev-parse", reference],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        if resolved.returncode != 0 or resolved.stdout.strip() != expected:
            raise RuntimeError("Materialized Git state does not match GitHub provenance")
    diff = subprocess.run(
        [
            "git", "--git-dir", str(mirror), "diff", "--name-only",
            "refs/socratic/base", "refs/socratic/head",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )
    if diff.returncode != 0:
        raise RuntimeError("Host could not summarize the materialized pull request")
    changed_files = [
        line for line in diff.stdout.splitlines() if line and "\0" not in line
    ]
    snapshots = storage / "change"
    base = snapshots / "base"
    head = snapshots / "head"
    base.mkdir(parents=True)
    head.mkdir(parents=True)
    for reference, target in (("refs/socratic/base", base), ("refs/socratic/head", head)):
        checkout = subprocess.run(
            [
                "git", "--git-dir", str(mirror), "--work-tree", str(target),
                "checkout", "--force", reference, "--", ".",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
        if checkout.returncode != 0:
            raise RuntimeError("Host could not expand a pull-request snapshot")
        (target / ".git").mkdir()
    provenance: dict[str, str | int] = {
        "source": "github-pull-request",
        "number": number,
        "url": metadata["url"],
        "title": metadata.get("title", ""),
        "base_ref": metadata["baseRefName"],
        "base_sha": metadata["baseRefOid"],
        "head_ref": metadata["headRefName"],
        "head_sha": metadata["headRefOid"],
        "base_root": str(base.resolve()),
        "head_root": str(head.resolve()),
        "changed_files": changed_files,
    }
    (storage / "change-provenance.json").write_text(
        json.dumps(provenance, sort_keys=True), encoding="utf-8"
    )
    return provenance


REVIEW_TYPES = (
    "Bug Fix Review",
    "Feature Review",
    "Refactor Guard",
    "Test Assessment",
)

MISSION = (
    "Infer the intended observable behavior from repository evidence, expose only "
    "consequential uncertainty, and design realistic accidents that test whether "
    "the suite protects that intent. The Runner owns commands, mutation mechanics, "
    "JSON schemas, hashes, ledgers, reports, and cleanup."
)


def recommend_review_type(change: dict[str, Any], prompt: str = "") -> str:
    """Recommend a workflow without turning the recommendation into specification."""
    title = str(change.get("title", ""))
    signal = f"{prompt}\n{title}".casefold()
    if re.search(r"\btest(?:s|ing)? assessment\b|テスト(?:評価|アセスメント)", signal):
        return "Test Assessment"
    if re.search(r"\brefactor(?:ing)?\b|リファクタ", signal):
        return "Refactor Guard"
    if re.search(r"\b(?:fix|bug|regression|hotfix)\b|修正|不具合|バグ", signal):
        return "Bug Fix Review"
    return "Feature Review"


def build_review_context(change: dict[str, Any], prompt: str = "") -> dict[str, Any]:
    head = Path(str(change["head_root"]))
    package_manager = next(
        (
            name
            for filename, name in (
                ("pnpm-lock.yaml", "pnpm"),
                ("yarn.lock", "yarn"),
                ("package-lock.json", "npm"),
                ("uv.lock", "uv"),
                ("poetry.lock", "poetry"),
                ("Cargo.lock", "cargo"),
            )
            if (head / filename).is_file()
        ),
        "unknown",
    )
    target = {
        key: change[key]
        for key in ("source", "number", "url", "title", "base_sha", "head_sha")
        if key in change
    }
    return {
        "mission": MISSION,
        "target": target,
        "changed_files": change.get("changed_files", []),
        "environment_hints": {"package_manager": package_manager},
        "review_type": {
            "recommended": recommend_review_type(change, prompt),
            "options": list(REVIEW_TYPES),
            "requires_human_confirmation": True,
        },
        "checkpoints": [
            "review-type",
            "diff-understanding",
            "intent-oracle",
            "final-interpretation",
        ],
        "fast_path": [
            "state the Mission, then obtain review-type confirmation",
            "run Runner inspect for bounded read-only evidence; do not delegate discovery",
            "present problem, changed behavior, preserved behavior, new observable, "
            "and uncertainty; obtain diff-understanding confirmation",
            "stage intent-contract.draft.json before any mutation",
            "ask a structured question and stop if an observable oracle is unresolved",
            "prepare dependencies once, then probe the focused command in a fresh clone",
            "submit one parallel anchored challenge-batch with no full-file content",
            "run scaffold-analysis, edit semantic judgments only, then let complete render and cleanup",
        ],
        "delegation_policy": (
            "Do not delegate deterministic diff or environment discovery; "
            "do not use gh or git fetch."
        ),
    }


def session_root(session_id: str) -> Path:
    return SESSION_ROOT / hashlib.sha256(session_id.encode()).hexdigest()[:20]


def prepare_session(
    session_id: str,
    primary: Path,
    *,
    adapter_id: str = "claude-code-hook-host-v1",
    host_name: str = "Claude Code",
    prompt: str = "",
) -> dict[str, Any]:
    primary = primary.resolve(strict=True)
    if not (primary / ".git").exists():
        raise RuntimeError("Socratic must start at a Git repository root")
    root = session_root(session_id)
    if root.exists():
        cleanup_session(session_id)
    root.mkdir(parents=True, mode=0o700)
    storage = root / "host-storage"
    storage.mkdir(mode=0o700)
    artifacts = storage / "artifacts"
    artifacts.mkdir(mode=0o700)
    pull_request = requested_pull_request(prompt)
    try:
        change = (
            materialize_pull_request(primary, storage, pull_request)
            if pull_request is not None
            else {
                "source": "local-workspace",
                "head_root": str(primary),
            }
        )
    except (OSError, RuntimeError, subprocess.SubprocessError):
        shutil.rmtree(root, ignore_errors=True)
        raise
    manifest_change = {
        key: value for key, value in change.items() if key != "title"
    }
    state = {
        "session_id": session_id,
        "primary_root": str(primary),
        "review_root": str(change["head_root"]),
        "socket_path": str(root / "host.sock"),
        "token": secrets.token_urlsafe(48),
        "adapter_id": adapter_id,
        "run_id": secrets.token_hex(16),
        "run_nonce": secrets.token_urlsafe(48),
        "storage_root": str(storage),
        "artifact_root": str(artifacts),
        "protection_mode": "host-events",
        "protection_details": f"{host_name} tool gate denies Primary writes and unguarded execution",
        "change_context": manifest_change,
        "review_context": build_review_context(change, prompt),
    }
    state_path = root / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    state_path.chmod(0o600)
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "broker", "--state", str(state_path)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    BROKER_PROCESSES[session_id] = process
    state["pid"] = str(process.pid)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    for _ in range(40):
        if request(Path(state["socket_path"]), state["token"]) == {"status": "ready"}:
            return state
        time.sleep(0.025)
    cleanup_session(session_id)
    raise RuntimeError("trusted Host broker did not start")


def load_session(session_id: str) -> dict[str, Any] | None:
    try:
        return json.loads((session_root(session_id) / "state.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def load_live_session(session_id: str) -> dict[str, Any] | None:
    """Return active or fail-closed state, collecting only expired dead brokers."""
    state = load_session(session_id)
    if state is None:
        return None
    if request(Path(state.get("socket_path", "")), state.get("token", "")) == {"status": "ready"}:
        return state
    pid_text = str(state.get("pid", ""))
    process_alive = False
    if pid_text.isdigit():
        pid = int(pid_text)
        try:
            waited, _status = os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            waited = 0
        if waited == 0:
            try:
                os.kill(pid, 0)
                process_alive = True
            except (OSError, ProcessLookupError):
                pass
    state_path = session_root(session_id) / "state.json"
    try:
        expired = time.time() - state_path.stat().st_mtime >= BROKER_IDLE_TTL_SECONDS
    except OSError:
        expired = False
    if not process_alive and expired:
        cleanup_session(session_id)
        return None
    return state


def cleanup_session(session_id: str) -> None:
    root = session_root(session_id)
    state = load_session(session_id)
    process = BROKER_PROCESSES.pop(session_id, None)
    if process is not None:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=0.2)
    elif state and str(state.get("pid", "")).isdigit():
        pid = int(state["pid"])
        try:
            os.kill(pid, 15)
        except (OSError, ProcessLookupError):
            pass
        else:
            for _ in range(20):
                try:
                    waited, _status = os.waitpid(pid, os.WNOHANG)
                except (ChildProcessError, OSError):
                    break
                if waited == pid:
                    break
                time.sleep(0.01)
    shutil.rmtree(root, ignore_errors=True)


def run_broker(state_path: Path) -> int:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    grant = {key: state[key] for key in (
        "adapter_id", "run_id", "run_nonce", "storage_root",
        "protection_mode", "protection_details", "change_context", "review_context",
    )}
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(state["socket_path"])
    server.listen(8)
    stop = threading.Event()
    try:
        _serve(server, state["token"], grant, stop)
    finally:
        server.close()
    return 0


def _serve(server: socket.socket, token: str, grant: dict[str, str], stop: threading.Event) -> None:
    server.settimeout(0.25)
    last_request = time.monotonic()
    while not stop.is_set():
        if time.monotonic() - last_request > BROKER_IDLE_TTL_SECONDS:
            break
        try:
            connection, _ = server.accept()
        except (TimeoutError, socket.timeout):
            continue
        except OSError:
            if stop.is_set():
                break
            raise
        with connection:
            last_request = time.monotonic()
            try:
                request = json.loads(connection.recv(65536).decode())
                if not secrets.compare_digest(str(request.get("token", "")), token):
                    response = {"status": "blocked"}
                elif request.get("action") == "grant":
                    response = {"status": "ready", "grant": grant}
                else:
                    response = {"status": "ready"}
            except (OSError, UnicodeError, json.JSONDecodeError):
                response = {"status": "blocked"}
            connection.sendall((json.dumps(response) + "\n").encode())


def request(socket_path: Path, token: str, action: str = "ping") -> dict[str, object]:
    if not socket_path.is_socket():
        return {"status": "blocked"}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(str(socket_path))
            client.sendall(json.dumps({"action": action, "token": token}).encode())
            return json.loads(client.recv(65536).decode())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"status": "blocked"}


def launch(primary: Path, plugin: Path, claude: str, extra: list[str]) -> int:
    primary = primary.resolve(strict=True)
    plugin = plugin.resolve(strict=True)
    if not (primary / ".git").exists():
        raise SystemExit("primary must be a Git repository root")
    run_root = Path(tempfile.mkdtemp(prefix="socratic-claude-"))
    workspace = run_root / "workspace"
    host_storage = run_root / "host-storage"
    host_storage.mkdir(mode=0o700)
    shutil.copytree(
        primary,
        workspace,
        symlinks=True,
        ignore=shutil.ignore_patterns(".env", ".env.*", "node_modules", "__pycache__"),
    )
    token = secrets.token_urlsafe(48)
    socket_path = run_root / "host.sock"
    grant = {
        "adapter_id": "claude-code-disposable-host-v1",
        "run_id": secrets.token_hex(16),
        "run_nonce": secrets.token_urlsafe(48),
        "storage_root": str(host_storage),
        "protection_mode": "host-events",
        "protection_details": "Claude runs only in a disposable copy; the user Primary is outside the agent workspace",
        "change_context": {
            "source": "local-workspace",
            "head_root": str(workspace),
        },
    }
    grant["review_context"] = build_review_context(
        grant["change_context"], "Socratic review"
    )
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(8)
    stop = threading.Event()
    thread = threading.Thread(target=_serve, args=(server, token, grant, stop), daemon=True)
    thread.start()
    environment = os.environ.copy()
    environment.update({
        "SOCRATIC_HOST_SOCKET": str(socket_path),
        "SOCRATIC_HOST_TOKEN": token,
        "SOCRATIC_USER_PRIMARY": str(primary),
    })
    try:
        return subprocess.run(
            [claude, "--plugin-dir", str(plugin), *extra], cwd=workspace,
            env=environment, check=False,
        ).returncode
    finally:
        stop.set()
        server.close()
        thread.join(timeout=1)
        shutil.rmtree(run_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command")
    broker = subcommands.add_parser("broker")
    broker.add_argument("--state", required=True, type=Path)
    parser.add_argument("--primary", type=Path, default=Path.cwd())
    parser.add_argument("--plugin", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--claude", default="claude")
    parser.add_argument("claude_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command == "broker":
        return run_broker(args.state)
    claude_args = args.claude_args[1:] if args.claude_args[:1] == ["--"] else args.claude_args
    return launch(args.primary, args.plugin, args.claude, claude_args)


if __name__ == "__main__":
    raise SystemExit(main())
