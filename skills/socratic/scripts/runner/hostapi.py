"""Host capability types and the launcher-owned broker socket adapter."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from runner.constants import RunGateError


@dataclass(frozen=True)
class HostGrant:
    """Capability issued by a trusted host adapter outside the agent boundary."""

    adapter_id: str
    run_id: str
    run_nonce: str
    storage_root: Path
    protection_mode: str
    protection_details: str
    change_context: dict[str, Any] | None = None
    review_type: dict[str, Any] | None = None


class HostAdapter(Protocol):
    """Host integration point. The standalone CLI intentionally has no implementation."""

    def begin_review_run(self, primary_root: Path) -> HostGrant: ...


class ClaudeSocketHostAdapter:
    """Obtain a run grant from the live launcher-owned Unix socket."""

    def __init__(self, socket_path: Path, token: str):
        self.socket_path = socket_path
        self.token = token

    @classmethod
    def from_environment(cls) -> "ClaudeSocketHostAdapter":
        path = os.environ.get("SOCRATIC_HOST_SOCKET", "")
        token = os.environ.get("SOCRATIC_HOST_TOKEN", "")
        if not path or len(token) < 32:
            raise RunGateError("trusted Claude Host broker is unavailable")
        return cls(Path(path), token)

    def begin_review_run(self, primary_root: Path) -> HostGrant:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1)
                client.connect(str(self.socket_path))
                client.sendall(json.dumps({"action": "grant", "token": self.token}).encode())
                response = json.loads(client.recv(65536).decode())
            grant = response["grant"]
        except (OSError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as error:
            raise RunGateError("trusted Claude Host broker rejected the run") from error
        return HostGrant(
            adapter_id=grant["adapter_id"], run_id=grant["run_id"],
            run_nonce=grant["run_nonce"], storage_root=Path(grant["storage_root"]),
            protection_mode=grant["protection_mode"],
            protection_details=grant["protection_details"],
            change_context=grant.get("change_context"),
            review_type=(
                grant.get("review_context", {}).get("review_type")
                if isinstance(grant.get("review_context"), dict)
                else None
            ),
        )
