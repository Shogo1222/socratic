#!/usr/bin/env python3
"""Launch Claude Code in a disposable Socratic workspace with a live Host broker."""

from __future__ import annotations

import argparse
import json
import os
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


SESSION_ROOT = Path("/tmp/socratic-sessions")
BROKER_IDLE_TTL_SECONDS = 2 * 60 * 60


def session_root(session_id: str) -> Path:
    return SESSION_ROOT / hashlib.sha256(session_id.encode()).hexdigest()[:20]


def prepare_session(
    session_id: str,
    primary: Path,
    *,
    adapter_id: str = "claude-code-hook-host-v1",
    host_name: str = "Claude Code",
) -> dict[str, str]:
    primary = primary.resolve(strict=True)
    if not (primary / ".git").exists():
        raise RuntimeError("Socratic must start at a Git repository root")
    root = session_root(session_id)
    if root.exists():
        cleanup_session(session_id)
    root.mkdir(parents=True, mode=0o700)
    storage = root / "host-storage"
    storage.mkdir(mode=0o700)
    state = {
        "session_id": session_id,
        "primary_root": str(primary),
        "socket_path": str(root / "host.sock"),
        "token": secrets.token_urlsafe(48),
        "adapter_id": adapter_id,
        "run_id": secrets.token_hex(16),
        "run_nonce": secrets.token_urlsafe(48),
        "storage_root": str(storage),
        "protection_mode": "host-events",
        "protection_details": f"{host_name} tool gate denies Primary writes and unguarded execution",
    }
    state_path = root / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    state_path.chmod(0o600)
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "broker", "--state", str(state_path)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    state["pid"] = str(process.pid)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    for _ in range(40):
        if request(Path(state["socket_path"]), state["token"]) == {"status": "ready"}:
            return state
        time.sleep(0.025)
    cleanup_session(session_id)
    raise RuntimeError("trusted Host broker did not start")


def load_session(session_id: str) -> dict[str, str] | None:
    try:
        return json.loads((session_root(session_id) / "state.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def cleanup_session(session_id: str) -> None:
    root = session_root(session_id)
    state = load_session(session_id)
    if state and str(state.get("pid", "")).isdigit():
        try:
            os.kill(int(state["pid"]), 15)
        except (OSError, ProcessLookupError):
            pass
    shutil.rmtree(root, ignore_errors=True)


def run_broker(state_path: Path) -> int:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    grant = {key: state[key] for key in (
        "adapter_id", "run_id", "run_nonce", "storage_root",
        "protection_mode", "protection_details",
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
    }
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
