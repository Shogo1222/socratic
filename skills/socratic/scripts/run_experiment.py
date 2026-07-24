#!/usr/bin/env python3
"""Deterministic local-copy prototype for typed Socratic experiments."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from validate_and_render import ArtifactError, load_strict_json, validate_document


RUNNER_VERSION = "0.5.0-beta.1"
OUTPUT_TAIL_BYTES = 16_384
DIFF_TAIL_BYTES = 16_384
MAX_CHANGED_BYTES = 65_536
IGNORED_NAMES = {".git", "__pycache__", ".pytest_cache", ".mypy_cache"}
FAILED_TEST = re.compile(r"^(?P<id>\S+) \([^\n]+\) \.\.\. (?:FAIL|ERROR)$", re.MULTILINE)


class ExperimentError(RuntimeError):
    """Raised when the typed experiment cannot be executed safely."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_entries(root: Path) -> list[Path]:
    entries: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in IGNORED_NAMES for part in relative.parts):
            continue
        if path.is_symlink():
            raise ExperimentError(f"source contains a symlink: {relative}")
        if path.is_file():
            entries.append(path)
        elif not path.is_dir():
            raise ExperimentError(f"source contains a non-regular entry: {relative}")
    return sorted(entries, key=lambda path: path.relative_to(root).as_posix())


def source_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in _source_entries(root):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _copy_source(source: Path, destination: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return set(names).intersection(IGNORED_NAMES)

    shutil.copytree(source, destination, symlinks=False, ignore=ignore)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_output_path(output_path: Path, source_root: Path) -> None:
    resolved_parent = output_path.parent.resolve(strict=True)
    resolved_output = resolved_parent / output_path.name
    if _inside(resolved_output, source_root):
        raise ExperimentError("evidence path must be outside the source root")
    if output_path.exists() or output_path.is_symlink():
        raise ExperimentError("evidence path already exists")


def _test_ids(selection: dict[str, Any]) -> list[str]:
    modules = selection["modules"]
    classes = selection["classes"]
    methods = selection["methods"]
    if not classes:
        return list(modules)
    if not methods:
        return [f"{module}.{class_name}" for module in modules for class_name in classes]
    return [
        f"{module}.{class_name}.{method}"
        for module in modules
        for class_name in classes
        for method in methods
    ]


def _validate_selection(source: Path, selection: dict[str, Any]) -> None:
    for module in selection["modules"]:
        relative = Path(*module.split("."))
        module_file = source / relative.with_suffix(".py")
        package_file = source / relative / "__init__.py"
        if not module_file.is_file() and not package_file.is_file():
            raise ExperimentError(f"selected test module is not in Source: {module}")


def _validate_mutations(mutations: list[dict[str, Any]]) -> None:
    identifiers = [mutation["id"] for mutation in mutations]
    if len(identifiers) != len(set(identifiers)):
        raise ExperimentError("mutation IDs must be unique")
    for mutation in mutations:
        paths = [target["path"] for target in mutation["targets"]]
        if len(paths) != len(set(paths)):
            raise ExperimentError(
                f"mutation target paths must be unique: {mutation['id']}"
            )
        changed_bytes = sum(
            len(operation["before"].encode("utf-8"))
            + len(operation.get("after", "").encode("utf-8"))
            for target in mutation["targets"]
            for operation in target["operations"]
        )
        if changed_bytes > MAX_CHANGED_BYTES:
            raise ExperimentError(
                f"mutation exceeds aggregate change-size limit: {mutation['id']}"
            )


def _clean_environment(runtime_root: Path) -> dict[str, str]:
    allowed = {
        "COMSPEC", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "PATHEXT",
        "SYSTEMDRIVE", "SYSTEMROOT", "TZ", "WINDIR",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in allowed
    }
    home = runtime_root / "home"
    temporary = runtime_root / "tmp"
    cache = runtime_root / "cache"
    for directory in (home, temporary, cache):
        directory.mkdir(parents=True, exist_ok=True)
    environment.update(
        {
            "HOME": str(home),
            "TMPDIR": str(temporary),
            "XDG_CACHE_HOME": str(cache),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return environment


def _bounded_output(value: bytes) -> dict[str, Any]:
    tail = value[-OUTPUT_TAIL_BYTES:]
    return {
        "tail": tail.decode("utf-8", errors="replace"),
        "truncated": len(value) > OUTPUT_TAIL_BYTES,
        "sha256": sha256_bytes(value),
    }


def _failed_tests(stdout: bytes, stderr: bytes) -> list[str] | None:
    text = (stdout + b"\n" + stderr).decode("utf-8", errors="replace")
    matches = sorted(set(match.group("id") for match in FAILED_TEST.finditer(text)))
    if matches:
        return matches
    if re.search(r"^FAILED \(", text, re.MULTILINE):
        return None
    return []


def _probe_runtime(runtime_root: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    modules = ("jsonschema", "referencing")
    script = (
        "import importlib, json\n"
        "missing = []\n"
        f"for name in {modules!r}:\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "    except Exception:\n"
        "        missing.append(name)\n"
        "print(json.dumps(missing))\n"
    )
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [sys.executable, "-B", "-c", script],
            env=_clean_environment(runtime_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        try:
            missing = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            missing = list(modules)
        if (
            completed.returncode != 0
            or not isinstance(missing, list)
            or any(name not in modules for name in missing)
        ):
            missing = list(modules)
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or b""
        stderr = error.stderr or b""
        missing = list(modules)
    duration_ms = max(0, round((time.monotonic() - started) * 1000))
    runtime = {
        "implementation": sys.implementation.name,
        "version": platform.python_version(),
        "executable_sha256": sha256_file(Path(sys.executable).resolve()),
        "environment": (
            "virtual-environment" if sys.prefix != sys.base_prefix else "system"
        ),
        "probe": "failed" if missing else "passed",
        "missing_dependencies": missing,
    }
    if not missing:
        return runtime, None
    return runtime, {
        "outcome": "runner-error",
        "exit_code": None,
        "failed_tests": None,
        "duration_ms": duration_ms,
        "reason": "profile runtime dependency unavailable",
        "missing_dependencies": missing,
        "stdout": _bounded_output(stdout),
        "stderr": _bounded_output(stderr),
    }


def _execute_tests(
    workspace: Path,
    runtime_root: Path,
    selection: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    argv = [sys.executable, "-B", "-m", "unittest", "-v", *_test_ids(selection)]
    started = time.monotonic()
    process = subprocess.Popen(
        argv,
        cwd=workspace,
        env=_clean_environment(runtime_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        exit_code: int | None = process.returncode
        outcome = "passed" if exit_code == 0 else "failed"
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        exit_code = None
        outcome = "timeout"
    duration_ms = max(0, round((time.monotonic() - started) * 1000))
    return {
        "outcome": outcome,
        "exit_code": exit_code,
        "failed_tests": _failed_tests(stdout, stderr),
        "duration_ms": duration_ms,
        "stdout": _bounded_output(stdout),
        "stderr": _bounded_output(stderr),
    }


def _safe_target(workspace: Path, relative: str) -> Path:
    target = workspace.joinpath(*relative.split("/"))
    resolved_parent = target.parent.resolve(strict=True)
    resolved_target = resolved_parent / target.name
    if not _inside(resolved_target, workspace.resolve()):
        raise ExperimentError(f"mutation target escapes workspace: {relative}")
    if target.is_symlink() or not target.is_file():
        raise ExperimentError(f"mutation target is not a regular file: {relative}")
    return target


def _apply_target(workspace: Path, target_plan: dict[str, Any]) -> dict[str, Any]:
    relative = target_plan["path"]
    target = _safe_target(workspace, relative)
    original_bytes = target.read_bytes()
    planned_preimage = target_plan["preimage_sha256"]
    if (
        planned_preimage != "runner-computed"
        and sha256_bytes(original_bytes) != planned_preimage
    ):
        raise ExperimentError(f"preimage hash mismatch: {relative}")
    try:
        original = original_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ExperimentError(f"mutation target is not UTF-8 text: {relative}") from error

    changed = original
    for operation in target_plan["operations"]:
        before = operation["before"]
        if changed.count(before) != 1:
            raise ExperimentError(
                f"{operation['type']} requires exactly one match in {relative}"
            )
        after = operation.get("after", "")
        changed = changed.replace(before, after, 1)
    changed_bytes = changed.encode("utf-8")
    target.write_bytes(changed_bytes)

    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            changed.splitlines(keepends=True),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
        )
    ).encode("utf-8")
    diff_tail = diff[-DIFF_TAIL_BYTES:]
    return {
        "path": relative,
        "preimage_sha256": sha256_bytes(original_bytes),
        "postimage_sha256": sha256_bytes(changed_bytes),
        "diff_tail": diff_tail.decode("utf-8", errors="replace"),
        "diff_truncated": len(diff) > DIFF_TAIL_BYTES,
        "diff_sha256": sha256_bytes(diff),
    }


def _write_create_once(path: Path, document: dict[str, Any]) -> None:
    payload = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def assess(source_root: Path, plan_path: Path, evidence_path: Path) -> dict[str, Any]:
    source = source_root.resolve(strict=True)
    if not source.is_dir():
        raise ExperimentError("source root must be a directory")
    plan = load_strict_json(plan_path)
    validate_document(plan, "experiment-plan.schema.json")
    _validate_output_path(evidence_path, source)
    _validate_selection(source, plan["profile"]["selection"])
    _validate_mutations(plan["mutations"])

    actual_source_digest = source_digest(source)
    planned_source_digest = plan["source"]["sha256"]
    if (
        planned_source_digest != "runner-computed"
        and planned_source_digest != actual_source_digest
    ):
        raise ExperimentError("source digest does not match the Experiment Plan")

    runner_path = Path(__file__).resolve()
    selection = plan["profile"]["selection"]
    timeout_seconds = plan["round"]["timeout_seconds"]
    run_root = Path(tempfile.mkdtemp(prefix="socratic-experiment-"))
    remaining_paths: list[str] = []
    evidence: dict[str, Any] | None = None
    try:
        runtime, runtime_error = _probe_runtime(run_root / "runtime-probe")
        mutations = []
        if runtime_error is not None:
            baseline = runtime_error
        else:
            prepared = run_root / "prepared"
            _copy_source(source, prepared)
            if source_digest(prepared) != actual_source_digest:
                raise ExperimentError("prepared copy digest does not match source")

            baseline_workspace = run_root / "baseline"
            _copy_source(prepared, baseline_workspace)
            baseline = _execute_tests(
                baseline_workspace,
                run_root / "runtime-baseline",
                selection,
                timeout_seconds,
            )

            if baseline["outcome"] == "passed":
                for mutation_plan in plan["mutations"]:
                    workspace = run_root / mutation_plan["id"]
                    _copy_source(prepared, workspace)
                    changes = [
                        _apply_target(workspace, target)
                        for target in mutation_plan["targets"]
                    ]
                    execution = _execute_tests(
                        workspace,
                        run_root / f"runtime-{mutation_plan['id']}",
                        selection,
                        timeout_seconds,
                    )
                    mutations.append(
                        {
                            "id": mutation_plan["id"],
                            "changes": changes,
                            "execution": execution,
                        }
                    )

            if source_digest(prepared) != actual_source_digest:
                raise ExperimentError("prepared copy changed during execution")
        evidence = {
            "version": 1,
            "run": secrets.token_hex(16),
            "round": "ROUND-001",
            "source": {"sha256": actual_source_digest},
            "plan_sha256": sha256_bytes(canonical_bytes(plan)),
            "runner": {
                "version": RUNNER_VERSION,
                "sha256": sha256_file(runner_path),
            },
            "profile": {
                "name": "python-unittest",
                "digest": sha256_bytes(canonical_bytes(plan["profile"])),
            },
            "runtime": runtime,
            "backend": {"kind": "local-copy", "attested": False},
            "baseline": baseline,
            "mutations": mutations,
            "cleanup": {"completed": False, "remaining_paths": []},
            "signature": None,
        }
    finally:
        try:
            shutil.rmtree(run_root)
        except OSError:
            remaining_paths = [str(run_root)] if run_root.exists() else []

    if evidence is None:
        raise ExperimentError("experiment did not produce evidence")
    evidence["cleanup"] = {
        "completed": not remaining_paths,
        "remaining_paths": remaining_paths,
    }
    validate_document(evidence, "evidence-bundle.schema.json")
    _write_create_once(evidence_path, evidence)
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    assess_parser = subparsers.add_parser(
        "assess", help="run one typed experiment in disposable local copies"
    )
    assess_parser.add_argument("--source-root", type=Path, required=True)
    assess_parser.add_argument("--plan", type=Path, required=True)
    assess_parser.add_argument("--evidence", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        assess(args.source_root, args.plan, args.evidence)
    except (ArtifactError, ExperimentError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(str(args.evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
