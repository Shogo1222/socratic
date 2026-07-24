"""Hash-chained mutation ledger access and the Host artifact index."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from runner.constants import RunGateError, _load_json
from runner.hashing import _canonical_bytes, _sha256_bytes


def _ledger_events(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    path = Path(manifest["ledger_path"])
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0])
    except (OSError, IndexError, json.JSONDecodeError) as error:
        raise RunGateError("append-only mutation ledger is invalid") from error
    if header != {"header": {"run_id": manifest["run_id"], "run_nonce": manifest["host"]["run_nonce"]}}:
        raise RunGateError("ledger header does not match the host-issued run nonce")
    previous = _sha256_bytes(_canonical_bytes(header))
    events: list[dict[str, Any]] = []
    for sequence, line in enumerate(lines[1:], 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise RunGateError("append-only mutation ledger contains invalid JSON") from error
        event = record.get("event")
        expected = _sha256_bytes(
            manifest["host"]["run_nonce"].encode() + previous.encode() + _canonical_bytes(event)
        )
        if record.get("sequence") != sequence or record.get("previous") != previous or record.get("digest") != expected:
            raise RunGateError("append-only mutation ledger chain is invalid")
        events.append(event)
        previous = expected
    return events


def _ledger_head(manifest: dict[str, Any]) -> str:
    path = Path(manifest["ledger_path"])
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) == 1:
        return _sha256_bytes((lines[0] + "\n").encode())
    return json.loads(lines[-1])["digest"]


def _append_event(manifest: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    events = _ledger_events(manifest)
    path = Path(manifest["ledger_path"])
    lines = path.read_text(encoding="utf-8").splitlines()
    previous = _sha256_bytes((lines[0] + "\n").encode()) if not events else json.loads(lines[-1])["digest"]
    digest = _sha256_bytes(
        manifest["host"]["run_nonce"].encode() + previous.encode() + _canonical_bytes(event)
    )
    record = {"sequence": len(events) + 1, "previous": previous, "digest": digest, "event": event}
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
    with os.fdopen(descriptor, "ab") as stream:
        stream.write(_canonical_bytes(record))
    return event


def _write_index(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.unlink(missing_ok=True)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_canonical_bytes(value))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _artifact_index(manifest: dict[str, Any]) -> dict[str, Any]:
    index = _load_json(Path(manifest["artifact_index_path"]))
    if index.get("version") != 1 or index.get("run_id") != manifest["run_id"]:
        raise RunGateError("Host artifact index does not match this run")
    if not isinstance(index.get("artifacts"), dict):
        raise RunGateError("Host artifact index is malformed")
    return index
