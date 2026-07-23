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
import tempfile
import threading
from pathlib import Path


def _serve(server: socket.socket, token: str, grant: dict[str, str], stop: threading.Event) -> None:
    server.settimeout(0.25)
    while not stop.is_set():
        try:
            connection, _ = server.accept()
        except (TimeoutError, socket.timeout):
            continue
        except OSError:
            if stop.is_set():
                break
            raise
        with connection:
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
    parser.add_argument("--primary", type=Path, default=Path.cwd())
    parser.add_argument("--plugin", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--claude", default="claude")
    parser.add_argument("claude_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    claude_args = args.claude_args[1:] if args.claude_args[:1] == ["--"] else args.claude_args
    return launch(args.primary, args.plugin, args.claude, claude_args)


if __name__ == "__main__":
    raise SystemExit(main())
