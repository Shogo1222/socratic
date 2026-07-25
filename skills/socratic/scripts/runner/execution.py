"""Sandboxed command execution, guarded mutation, probes, and challenge batches."""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from runner.constants import (
    ARTIFACT_FILES,
    DOCTOR_TOOLS,
    GITLESS_BUILD_SIGNATURES,
    MAX_INSPECT_BYTES,
    MISSING_EXECUTABLE_SIGNATURES,
    PYTHON_MISMATCH_SIGNATURES,
    RunGateError,
    SANDBOX_ENV_DEFAULTS,
    _bounded_text,
    _load_json,
    _load_module,
    _safe_relative_path,
    _skills_root,
    _timed,
    _validator_module,
)
from runner.hashing import (
    _prepared_hash,
    _sha256_bytes,
    _sha256_path,
    _write_exclusive,
)
from runner.ledger import _append_event, _artifact_index, _ledger_events
from runner.lifecycle import _ready_manifest
from runner.scaffolds import _next_step, _record_validation_error
from runner.snapshots import (
    _clone_prepared,
    _copy_prepared,
    _materialize_dependency_layer,
    _runtime_environment,
    _seal_dependency_layer,
)


def _inherited_environment() -> dict[str, str]:
    """Allowlist the host environment a sandbox command may inherit."""
    return {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG"} or key.startswith("LC_")
    }


def _infrastructure_hint(output: str, argv: list[str] | None = None) -> str | None:
    """Map a sandbox failure to the environment cause the agent cannot inspect.

    The tool gate correctly blocks ad-hoc diagnostics inside a hosted run, so
    the Runner must name the sandbox-environment causes itself: the .git-less
    prepared snapshot, an interpreter the project rejects, and HOME-based tool
    shims that do not resolve after HOME redirection.
    """
    hints: list[str] = []
    if any(signature in output for signature in GITLESS_BUILD_SIGNATURES):
        hints.append(
            "the prepared snapshot intentionally contains no .git directory, so "
            "VCS-based version backends cannot compute a version; "
            "SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 is preset for setuptools-scm "
            "and hatch-vcs, while versioningit has no env override and needs "
            "tool.versioningit.default-version in the project or an install "
            "path that does not rebuild version metadata from the source tree"
        )
    if any(signature in output for signature in PYTHON_MISMATCH_SIGNATURES):
        hints.append(
            "the command ran with an interpreter the project rejects; rerun "
            "with the project's own interpreter by absolute path — the "
            "injected plugin runtime Python exists only for run_review.py"
        )
    if any(signature in output for signature in MISSING_EXECUTABLE_SIGNATURES):
        name = argv[0] if argv else "the command"
        hints.append(
            f"{name} was not found in the sandbox environment; the sandbox "
            "inherits only PATH, LANG, and LC_* and redirects HOME into the "
            "sandbox, so HOME-based tool shims (uv, nvm, pyenv) may not "
            "resolve — invoke the tool by absolute path"
        )
    return "; ".join(hints) if hints else None


def _bounded_tool_version(executable: str, environment: dict[str, str], cwd: Path) -> str:
    try:
        completed = _run_sandboxed(
            [executable, "--version"], cwd=cwd, env=environment,
            timeout_seconds=5, capture=True,
        )
    except subprocess.TimeoutExpired:
        return "timeout"
    except OSError as error:
        return f"error: {error}"
    output = (completed.stdout or b"") + b" " + (completed.stderr or b"")
    lines = output.decode("utf-8", errors="replace").strip().splitlines()
    return lines[0][:200] if lines else ""


def _project_requirements(prepared: Path) -> dict[str, Any]:
    """Extract interpreter and build-backend requirements from the snapshot, bounded."""
    requirements: dict[str, Any] = {
        "requires_python": None,
        "build_backend": None,
        "vcs_version_backends": [],
        "node_engines": None,
    }
    pyproject = prepared / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8", errors="replace")[:MAX_INSPECT_BYTES]
        match = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', text)
        if match:
            requirements["requires_python"] = match.group(1)
        match = re.search(r'build-backend\s*=\s*["\']([^"\']+)["\']', text)
        if match:
            requirements["build_backend"] = match.group(1)
        requirements["vcs_version_backends"] = sorted({
            name
            for name in ("hatch-vcs", "setuptools-scm", "setuptools_scm", "versioningit")
            if name in text
        })
    package_json = prepared / "package.json"
    if package_json.is_file():
        try:
            data = json.loads(
                package_json.read_text(encoding="utf-8", errors="replace")[:MAX_INSPECT_BYTES]
            )
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("engines"), dict):
            requirements["node_engines"] = data["engines"]
    return requirements


def _last_failed_command(manifest: dict[str, Any]) -> dict[str, Any] | None:
    """Summarize the most recent non-mutation command that did not complete green."""
    for event in reversed(_ledger_events(manifest)):
        kind = event.get("kind")
        if kind not in {"command", "command-probe"}:
            continue
        if kind == "command" and event.get("phase") == "mutation":
            # A nonzero mutation execution is an expected killed mutant.
            continue
        if event.get("result") == "completed" and event.get("returncode") == 0:
            continue
        return {
            "kind": kind,
            "phase": event.get("phase"),
            "command_id": event.get("command_id"),
            "argv": event.get("argv"),
            "result": event.get("result"),
            "returncode": event.get("returncode"),
            "timeout_seconds": event.get("timeout_seconds"),
        }
    return None


def doctor(manifest_path: Path) -> dict[str, Any]:
    """Report the sandbox toolchain and environment, read-only and secret-free.

    The tool gate rightly denies ad-hoc diagnostics during a hosted run, so
    this Runner-owned report is the sanctioned way to investigate an
    infrastructure failure: it shows the PATH sandbox commands actually get,
    which toolchain executables resolve there and their versions, what the
    project requires, and why VCS-version build backends need the preset
    workaround in the .git-less snapshot. It writes nothing and uses no
    network beyond running local `--version` probes.
    """
    manifest = _ready_manifest(manifest_path)
    prepared = Path(manifest["prepared_root"])
    environment = _inherited_environment()
    environment.update(_runtime_environment(prepared))
    path_value = environment.get("PATH", "")
    tools: dict[str, Any] = {}
    for name in DOCTOR_TOOLS:
        located = shutil.which(name, path=path_value or None)
        tools[name] = (
            {
                "path": located,
                "version": _bounded_tool_version(located, environment, prepared),
            }
            if located
            else None
        )
    project = _project_requirements(prepared)
    return {
        "status": "ok",
        "sandbox_path": path_value,
        "home_redirected_to": environment.get("HOME"),
        "runner_python_version": sys.version.split()[0],
        "tools": tools,
        "project": project,
        "vcs_metadata": {
            "prepared_snapshot_has_git": (prepared / ".git").exists(),
            "vcs_version_backends_detected": project["vcs_version_backends"],
            "pretend_version_preset": SANDBOX_ENV_DEFAULTS.get(
                "SETUPTOOLS_SCM_PRETEND_VERSION"
            ),
        },
        "last_failed_command": _last_failed_command(manifest),
        "note": (
            "read-only report; runner_python_version runs run_review.py only and "
            "must not run project commands — fix the named cause, then rerun the "
            "failed command through its next.argv using the project's own "
            "toolchain by absolute path"
        ),
    }


def _authorize_contract_challenge(
    manifest: dict[str, Any], contract_ids: list[str]
) -> None:
    index = _artifact_index(manifest)
    record = index["artifacts"].get("contract")
    path = Path(manifest["artifact_root"]) / ARTIFACT_FILES["contract"]
    if (
        not record
        or record.get("path") != str(path)
        or record.get("sha256") != _sha256_path(path)
    ):
        raise RunGateError(
            "Intent Contract must be validated and staged before mutation"
        )
    contract = _load_json(path)
    if not isinstance(contract, dict):
        raise RunGateError("staged Intent Contract is invalid")
    validator = _validator_module()
    try:
        validator.assert_elenchus_allowed(contract, contract_ids)
    except validator.ArtifactError as error:
        raise RunGateError(str(error)) from error


def _begin_guarded_mutation(
    manifest_path: Path, mutation_id: str, contract_ids: list[str]
) -> dict[str, Any]:
    """Shared entry gate for every mutation registration path."""
    manifest = _ready_manifest(manifest_path)
    _authorize_contract_challenge(manifest, contract_ids)
    if not mutation_id.startswith("MUT-") or not mutation_id[4:].isdigit():
        raise RunGateError(
            f"invalid mutation id: {mutation_id}; expected MUT-<digits>, e.g. MUT-001"
        )
    return manifest


def _isolation_gate_module():
    return _load_module(
        "socratic_isolation_gate", _skills_root() / "elenchus/scripts/isolation_gate.py"
    )


def mutate(
    manifest_path: Path,
    mutation_id: str,
    contract_ids: list[str],
    relative_target: str,
    content: bytes,
) -> dict[str, Any]:
    manifest = _begin_guarded_mutation(manifest_path, mutation_id, contract_ids)
    sandbox, clone_strategy, prepared_sha256 = _clone_prepared(manifest, mutation_id)
    if Path(relative_target).is_absolute() or ".." in Path(relative_target).parts:
        shutil.rmtree(sandbox, ignore_errors=True)
        raise RunGateError("mutation target must be a safe sandbox-relative path")
    isolation = _isolation_gate_module()
    try:
        evidence = isolation.IsolationGate(
            Path(manifest["primary_root"]), sandbox
        ).write_bytes(sandbox / relative_target, content)
    except BaseException:
        shutil.rmtree(sandbox, ignore_errors=True)
        raise
    return _append_event(manifest, {
        "run_id": manifest["run_id"], "mutation_id": mutation_id, "kind": "guarded-write",
        "requested_path": relative_target, "resolved_path": evidence.resolved_target,
        "content_sha256": _sha256_bytes(content), "bytes": len(content), "within_sandbox": True,
        "sandbox_root": str(sandbox), "clone_strategy": clone_strategy,
        "prepared_sha256": prepared_sha256,
    })


def _anchored_postimage(root: Path, mutation: dict[str, Any]) -> tuple[str, bytes]:
    relative = _safe_relative_path(mutation["relative_path"])
    target = root / relative
    original = _bounded_text(target, limit=2 * 1024 * 1024)
    before = mutation["before"]
    if original.count(before) != 1:
        raise RunGateError(
            f"{mutation['kind']} requires exactly one anchor match: {relative}"
        )
    after = mutation.get("after", "")
    changed = original.replace(before, after, 1)
    return relative.as_posix(), changed.encode("utf-8")


def mutate_anchored(
    manifest_path: Path,
    mutation_id: str,
    contract_ids: list[str],
    mutation: dict[str, Any],
) -> dict[str, Any]:
    """Apply a bounded exact edit without accepting a caller-built full file."""
    manifest = _begin_guarded_mutation(manifest_path, mutation_id, contract_ids)
    relative_target, content = _anchored_postimage(
        Path(manifest["prepared_root"]), mutation
    )
    sandbox, clone_strategy, prepared_sha256 = _clone_prepared(
        manifest, mutation_id
    )
    isolation = _isolation_gate_module()
    try:
        evidence = isolation.IsolationGate(
            Path(manifest["primary_root"]), sandbox
        ).write_bytes(sandbox / relative_target, content)
    except BaseException:
        shutil.rmtree(sandbox, ignore_errors=True)
        raise
    return _append_event(manifest, {
        "run_id": manifest["run_id"],
        "mutation_id": mutation_id,
        "kind": "guarded-write",
        "requested_path": relative_target,
        "resolved_path": evidence.resolved_target,
        "content_sha256": _sha256_bytes(content),
        "bytes": len(content),
        "within_sandbox": True,
        "sandbox_root": str(sandbox),
        "clone_strategy": clone_strategy,
        "prepared_sha256": prepared_sha256,
        "operation": mutation["kind"],
        "anchor_sha256": _sha256_bytes(mutation["before"].encode("utf-8")),
    })


def register_prebuilt(
    manifest_path: Path,
    mutation_id: str,
    contract_ids: list[str],
    relative_path: str,
) -> dict[str, Any]:
    manifest = _begin_guarded_mutation(manifest_path, mutation_id, contract_ids)
    relative = Path(relative_path)
    sandbox, clone_strategy, prepared_sha256 = _clone_prepared(manifest, mutation_id)
    unresolved = sandbox / relative
    isolation = _isolation_gate_module()
    try:
        evidence = isolation.IsolationGate(
            Path(manifest["primary_root"]), sandbox
        ).authorize(unresolved)
        candidate = Path(evidence.resolved_target)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or unresolved.is_symlink()
            or not candidate.is_file()
        ):
            raise RunGateError("prebuilt mutant must be a sandbox-relative regular file")
    except BaseException:
        shutil.rmtree(sandbox, ignore_errors=True)
        raise
    return _append_event(manifest, {
        "run_id": manifest["run_id"], "mutation_id": mutation_id, "kind": "prebuilt",
        "resolved_path": str(candidate), "sha256": _sha256_path(candidate),
        "sandbox_root": str(sandbox), "clone_strategy": clone_strategy,
        "prepared_sha256": prepared_sha256,
    })


def execute(
    manifest_path: Path,
    phase: str,
    mutation_id: str | None,
    command: list[str],
    timeout_seconds: int,
    cwd_relative: str | None = None,
) -> int:
    manifest = _ready_manifest(manifest_path)
    if phase not in {"prepare", "baseline", "mutation"}:
        raise RunGateError("execute phase must be prepare, baseline, or mutation")
    if phase in {"prepare", "baseline"} and mutation_id is not None:
        raise RunGateError(f"{phase} execution must not have a mutation id")
    if phase == "mutation" and mutation_id is None:
        raise RunGateError("mutation execution requires --mutation-id")
    if not command:
        raise RunGateError("sandbox command must not be empty")
    ledger = _ledger_events(manifest)
    if phase in {"prepare", "baseline"} and any(
        item.get("kind") == "prepared-snapshot" for item in ledger
    ):
        raise RunGateError(f"{phase} cannot run after the prepared snapshot is sealed")
    if phase == "prepare" and any(
        item.get("kind") == "validated-command" for item in ledger
    ):
        raise RunGateError("prepare cannot run after a command has been validated")
    registrations = {
        item.get("mutation_id"): item for item in ledger
        if item.get("kind") in {"guarded-write", "prebuilt"}
    }
    registered = set(registrations)
    if phase == "mutation" and mutation_id not in registered:
        raise RunGateError(f"mutation execution has no guarded mutation evidence: {mutation_id}")
    environment = _inherited_environment()
    execution_root = (
        Path(manifest["prepared_root"])
        if phase in {"prepare", "baseline"}
        else Path(registrations[mutation_id]["sandbox_root"])
    )
    runtime_environment = (
        {**manifest["environment"], **SANDBOX_ENV_DEFAULTS}
        if phase == "baseline"
        else _runtime_environment(execution_root)
    )
    environment.update(runtime_environment)
    if phase == "mutation":
        _verify_registered_content(registrations, mutation_id)
    try:
        started = time.monotonic()
        completed = _run_sandboxed(
            command, cwd=_execution_cwd(execution_root, cwd_relative),
            env=environment, timeout_seconds=timeout_seconds, capture=False,
        )
    except subprocess.TimeoutExpired as error:
        _append_event(manifest, {
            "run_id": manifest["run_id"], "kind": "command", "phase": phase,
            "mutation_id": mutation_id, "argv": command, "cwd": cwd_relative,
            "timeout_seconds": timeout_seconds,
            "result": "timeout", "returncode": None,
            "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
            "environment": runtime_environment, "sandbox_root": str(execution_root),
        })
        raise RunGateError(f"sandbox command timed out after {timeout_seconds}s") from error
    _append_event(manifest, {
        "run_id": manifest["run_id"], "kind": "command", "phase": phase,
        "mutation_id": mutation_id, "argv": command, "cwd": cwd_relative,
        "timeout_seconds": timeout_seconds,
        "result": "completed", "returncode": completed.returncode,
        "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
        "environment": runtime_environment, "sandbox_root": str(execution_root),
    })
    return completed.returncode


def _run_sandboxed(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
    capture: bool,
) -> subprocess.CompletedProcess[bytes]:
    """Run a sandbox command in its own session and kill the whole group on timeout.

    subprocess.run's timeout kills only the direct child: a test-runner worker
    that survives keeps running as an orphan, and a grandchild holding the
    stdout pipe hangs the Runner forever.
    """
    pipe = subprocess.PIPE if capture else None
    process = subprocess.Popen(
        command, cwd=cwd, env=env, stdout=pipe, stderr=pipe,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            command, timeout_seconds, output=stdout, stderr=stderr
        )
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _verify_registered_content(
    registrations: dict[Any, dict[str, Any]], mutation_id: str | None
) -> None:
    """Require the mutant file to still match its guarded ledger evidence."""
    registration = registrations.get(mutation_id, {})
    recorded = registration.get("content_sha256") or registration.get("sha256")
    target = Path(str(registration.get("resolved_path", "")))
    if not recorded or not target.is_file() or _sha256_path(target) != recorded:
        raise RunGateError(
            f"mutation sandbox content no longer matches its guarded evidence: {mutation_id}"
        )


def _execution_cwd(root: Path, cwd_relative: str | None) -> Path:
    """Resolve a validated working directory for sandbox command execution.

    Package-manager wrappers re-resolve workspace paths in clones and
    reinstall dependencies; running the direct test binary from the package
    directory avoids that, so probes and batch executions accept a
    sandbox-relative cwd.
    """
    if cwd_relative is None:
        return root
    relative = _safe_relative_path(cwd_relative)
    cwd = root / relative
    if not cwd.is_dir() or cwd.is_symlink():
        raise RunGateError(f"execution cwd must be a directory inside the sandbox: {cwd_relative}")
    if not cwd.resolve().is_relative_to(root.resolve()):
        raise RunGateError(f"execution cwd escapes the sandbox: {cwd_relative}")
    return cwd


def probe_command(
    manifest_path: Path,
    command_id: str,
    command: list[str],
    timeout_seconds: int,
    cwd_relative: str | None = None,
) -> dict[str, Any]:
    """Validate a focused test command in a fresh clone before issuing Mutation IDs."""
    manifest = _ready_manifest(manifest_path)
    if not re.fullmatch(r"CMD-[0-9]{3,}", command_id):
        raise RunGateError(
            f"invalid command id: {command_id}; expected CMD-<three or more digits>, e.g. --command-id CMD-001"
        )
    if not command:
        raise RunGateError("probe command must not be empty")
    events = _ledger_events(manifest)
    if any(
        item.get("kind") == "validated-command"
        and item.get("command_id") == command_id
        for item in events
    ):
        raise RunGateError(f"command id is already validated: {command_id}")
    if any(item.get("kind") == "prepared-snapshot" for item in events):
        raise RunGateError("command probe must run before the prepared snapshot is sealed")

    prepared = Path(manifest["prepared_root"])
    _execution_cwd(prepared, cwd_relative)
    runner_timings: dict[str, int] = {}
    _materialize_dependency_layer(manifest, runner_timings)
    with _timed(runner_timings, "source_snapshot_hash"):
        prepared_sha256 = _prepared_hash(prepared)
    probe_root = Path(manifest["sandbox_root"]) / "command-probes" / command_id
    with _timed(runner_timings, "clone"):
        strategy = _copy_prepared(prepared, probe_root)
    runtime_environment = _runtime_environment(probe_root)
    environment = _inherited_environment()
    environment.update(runtime_environment)
    started = time.monotonic()
    try:
        completed = _run_sandboxed(
            command,
            cwd=_execution_cwd(probe_root, cwd_relative),
            env=environment,
            timeout_seconds=timeout_seconds,
            capture=True,
        )
        result = "completed"
        returncode: int | None = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        result = "timeout"
        returncode = None
        stdout = error.stdout or b""
        stderr = error.stderr or b""
    except OSError as error:
        result = "runner-error"
        returncode = None
        stdout = b""
        stderr = str(error).encode("utf-8")
    finally:
        duration_ms = max(0, round((time.monotonic() - started) * 1000))

    event = {
        "run_id": manifest["run_id"],
        "kind": "command-probe",
        "command_id": command_id,
        "argv": command,
        "cwd": cwd_relative,
        "timeout_seconds": timeout_seconds,
        "result": result,
        "returncode": returncode,
        "duration_ms": duration_ms,
        "environment": runtime_environment,
        "sandbox_root": str(probe_root),
        "clone_strategy": strategy,
        "stdout_sha256": _sha256_bytes(stdout),
        "stderr_sha256": _sha256_bytes(stderr),
    }
    try:
        _append_event(manifest, event)
        if result == "completed" and returncode == 0:
            # The probe may legitimately warm dependency-owned tool caches. Seal
            # the shared layer only after that baseline behavior has completed.
            _seal_dependency_layer(manifest, runner_timings)
        limit = 16 * 1024
        public = {
            "status": "ready" if result == "completed" and returncode == 0 else "blocked",
            "command_id": command_id,
            "outcome": (
                "passed"
                if result == "completed" and returncode == 0
                else "timeout"
                if result == "timeout"
                else "infrastructure-failure"
            ),
            "returncode": returncode,
            "duration_ms": duration_ms,
            "runner_timings_ms": {**runner_timings, "external_command": duration_ms},
            "stdout": stdout[-limit:].decode("utf-8", errors="replace"),
            "stderr": stderr[-limit:].decode("utf-8", errors="replace"),
            "output_truncated": len(stdout) > limit or len(stderr) > limit,
        }
        if public["status"] == "ready":
            public["next"] = _next_step(
                "scaffold-plan", "--manifest", str(manifest_path),
                note="the plan binds this validated command; fill the challenges, then follow next.argv",
            )
        else:
            hint = _infrastructure_hint(
                public["stdout"] + "\n" + public["stderr"], command
            )
            if hint:
                public["hint"] = hint
            public["diagnose"] = _next_step(
                "doctor", "--manifest", str(manifest_path),
                note=(
                    "read-only sandbox toolchain and environment report; run it "
                    "before changing tools or arguments"
                ),
            )
            public["next"] = _next_step(
                "probe-command", "--manifest", str(manifest_path),
                "--command-id", command_id, "--", "<corrected-focused-argv>",
                note=(
                    "the probe did not pass; inspect stdout, stderr, and any hint "
                    "above, fix the focused command or its cwd, then probe again"
                ),
            )
        if public["status"] == "ready":
            _append_event(manifest, {
                "run_id": manifest["run_id"],
                "kind": "validated-command",
                "command_id": command_id,
                "argv": command,
                "cwd": cwd_relative,
                "timeout_seconds": timeout_seconds,
                "probe_duration_ms": duration_ms,
                "clone_strategy": strategy,
                "prepared_sha256": prepared_sha256,
            })
            _append_event(manifest, {
                "run_id": manifest["run_id"],
                "kind": "command",
                "phase": "baseline",
                "mutation_id": None,
                "argv": command,
                "cwd": cwd_relative,
                "timeout_seconds": timeout_seconds,
                "result": "completed",
                "returncode": 0,
                "duration_ms": duration_ms,
                "environment": runtime_environment,
                "sandbox_root": str(probe_root),
                "command_id": command_id,
            })
    finally:
        shutil.rmtree(probe_root, ignore_errors=True)
    return public


def _validated_command(
    manifest: dict[str, Any], command_id: str
) -> dict[str, Any]:
    matches = [
        item for item in _ledger_events(manifest)
        if item.get("kind") == "validated-command"
        and item.get("command_id") == command_id
    ]
    if len(matches) != 1:
        raise RunGateError(
            f"challenge plan requires one successful command probe: {command_id}"
        )
    record = matches[0]
    if record.get("prepared_sha256") != _prepared_hash(
        Path(manifest["prepared_root"])
    ):
        raise RunGateError(
            f"validated command is stale for the prepared snapshot: {command_id}"
        )
    return record


def _batch_command(
    challenge: dict[str, Any],
    registration: dict[str, Any],
    inherited_environment: dict[str, str],
) -> dict[str, Any]:
    sandbox = Path(registration["sandbox_root"])
    runtime_environment = _runtime_environment(sandbox)
    environment = dict(inherited_environment)
    environment.update(runtime_environment)
    command = challenge["command"]
    timeout_seconds = challenge["timeout_seconds"]
    _verify_registered_content({challenge["id"]: registration}, challenge["id"])
    started = time.monotonic()
    try:
        completed = _run_sandboxed(
            command,
            cwd=_execution_cwd(sandbox, challenge.get("cwd")),
            env=environment,
            timeout_seconds=timeout_seconds,
            capture=True,
        )
        result = "completed"
        returncode: int | None = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        result = "timeout"
        returncode = None
        stdout = error.stdout or b""
        stderr = error.stderr or b""
    limit = 16 * 1024
    return {
        "mutation_id": challenge["id"],
        "argv": command,
        "cwd": challenge.get("cwd"),
        "timeout_seconds": timeout_seconds,
        "result": result,
        "returncode": returncode,
        "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
        "environment": runtime_environment,
        "sandbox_root": str(sandbox),
        "stdout_sha256": _sha256_bytes(stdout),
        "stderr_sha256": _sha256_bytes(stderr),
        "stdout": stdout[-limit:].decode("utf-8", errors="replace"),
        "stderr": stderr[-limit:].decode("utf-8", errors="replace"),
        "output_truncated": len(stdout) > limit or len(stderr) > limit,
    }


def challenge_batch(
    manifest_path: Path, schema_root: Path | None = None
) -> dict[str, Any]:
    manifest = _ready_manifest(manifest_path)
    plan_path = Path(manifest["artifact_root"]) / "challenge-plan.json"
    if (
        not plan_path.is_file()
        or plan_path.is_symlink()
        or plan_path.parent.resolve(strict=True)
        != Path(manifest["artifact_root"]).resolve(strict=True)
    ):
        raise RunGateError("challenge plan is missing from the fixed Host staging path")
    plan = _load_json(plan_path)
    if not isinstance(plan, dict):
        raise RunGateError("challenge plan root must be an object")
    validator = _validator_module()
    try:
        validator.validate_document(plan, "challenge-plan.schema.json", schema_root)
    except validator.ArtifactError as error:
        _record_validation_error(manifest, "challenge-plan", str(error))
        raise RunGateError(str(error)) from error
    ids = [item["id"] for item in plan["challenges"]]
    if len(ids) != len(set(ids)):
        raise RunGateError("challenge plan mutation IDs must be unique")
    existing = {
        item.get("mutation_id")
        for item in _ledger_events(manifest)
        if item.get("kind") in {"guarded-write", "prebuilt"}
    }
    duplicates = sorted(set(ids) & existing)
    if duplicates:
        raise RunGateError(f"challenge plan reuses mutation IDs: {duplicates}")
    runner_timings: dict[str, int] = {}
    with _timed(runner_timings, "staleness_source_hash"):
        command_record = _validated_command(manifest, plan["command_id"])
    for challenge in plan["challenges"]:
        _authorize_contract_challenge(manifest, challenge["contract_ids"])
        _anchored_postimage(Path(manifest["prepared_root"]), challenge["mutation"])
    plan_sha256 = _sha256_path(plan_path)
    registrations: dict[str, dict[str, Any]] = {}
    with _timed(runner_timings, "clones"):
        for challenge in plan["challenges"]:
            runtime_challenge = dict(challenge)
            runtime_challenge["command"] = command_record["argv"]
            runtime_challenge["cwd"] = command_record.get("cwd")
            runtime_challenge["timeout_seconds"] = command_record["timeout_seconds"]
            challenge["_runtime"] = runtime_challenge
            registration = mutate_anchored(
                manifest_path,
                challenge["id"],
                challenge["contract_ids"],
                challenge["mutation"],
            )
            registrations[challenge["id"]] = registration

    inherited_environment = _inherited_environment()
    results_by_id: dict[str, dict[str, Any]] = {}
    execution_started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(plan["max_parallel"], len(plan["challenges"]))
    ) as executor:
        futures = {
            executor.submit(
                _batch_command,
                challenge["_runtime"],
                registrations[challenge["id"]],
                inherited_environment,
            ): challenge["id"]
            for challenge in plan["challenges"]
        }
        for future in concurrent.futures.as_completed(futures):
            mutation_id = futures[future]
            try:
                results_by_id[mutation_id] = future.result()
            except BaseException as error:
                results_by_id[mutation_id] = {
                    "mutation_id": mutation_id,
                    "argv": next(
                        item["_runtime"]["command"]
                        for item in plan["challenges"]
                        if item["id"] == mutation_id
                    ),
                    "timeout_seconds": next(
                        item["_runtime"]["timeout_seconds"]
                        for item in plan["challenges"]
                        if item["id"] == mutation_id
                    ),
                    "result": "runner-error",
                    "returncode": None,
                    "environment": {},
                    "sandbox_root": registrations[mutation_id]["sandbox_root"],
                    "stdout_sha256": _sha256_bytes(b""),
                    "stderr_sha256": _sha256_bytes(str(error).encode("utf-8")),
                    "stdout": "",
                    "stderr": str(error),
                    "output_truncated": False,
                }

    public_results: list[dict[str, Any]] = []
    detailed_results: list[dict[str, Any]] = []
    tail_limit = 2000
    for challenge in plan["challenges"]:
        result = results_by_id[challenge["id"]]
        ledger_event = {
            key: value
            for key, value in result.items()
            if key not in {"stdout", "stderr", "output_truncated"}
        }
        ledger_event.update({
            "run_id": manifest["run_id"],
            "kind": "command",
            "phase": "mutation",
            "batch_plan_sha256": plan_sha256,
        })
        _append_event(manifest, ledger_event)
        outcome = (
            "runner-error"
            if result["result"] == "runner-error"
            else
            "timeout"
            if result["result"] == "timeout"
            else "passed"
            if result["result"] == "completed" and result["returncode"] == 0
            else "failed"
        )
        detailed_results.append({
            "mutation_id": result["mutation_id"],
            "outcome": outcome,
            "returncode": result["returncode"],
            "duration_ms": result.get("duration_ms"),
            "cwd": result.get("cwd"),
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "output_truncated": result["output_truncated"],
        })
        # The compact view keeps stdout readable in one screen: full output goes
        # to the details artifact, and only non-green outcomes carry a tail here
        # so detecting tests and failure causes stay diagnosable inline.
        entry: dict[str, Any] = {
            "mutation_id": result["mutation_id"],
            "outcome": outcome,
            "returncode": result["returncode"],
            "duration_ms": result.get("duration_ms"),
        }
        if outcome != "passed":
            entry["stdout_tail"] = result["stdout"][-tail_limit:]
            entry["stderr_tail"] = result["stderr"][-tail_limit:]
        public_results.append(entry)
    details_path = Path(manifest["artifact_root"]) / "challenge-results.json"
    _write_exclusive(details_path, {
        "run_id": manifest["run_id"],
        "plan_sha256": plan_sha256,
        "command_id": plan["command_id"],
        "results": detailed_results,
    })
    return {
        "status": "completed",
        "plan_sha256": plan_sha256,
        "command_id": plan["command_id"],
        "max_parallel": plan["max_parallel"],
        "results": public_results,
        "details_path": str(details_path),
        "runner_timings_ms": {
            **runner_timings,
            "external_commands_window": max(
                0, round((time.monotonic() - execution_started) * 1000)
            ),
        },
        "next": _next_step(
            "scaffold-analysis", "--manifest", str(manifest_path),
            "--mode", "<assessment|harden|catch>",
            note="pick the mode of this run's branch, interpret raw outcomes, then follow next.argv",
        ),
    }
