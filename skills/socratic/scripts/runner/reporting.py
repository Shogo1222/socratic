"""Attested report generation, finish-time verification, and completion."""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path
from typing import Any

from runner.constants import (
    ARTIFACT_FILES,
    ENTRYPOINT,
    RunGateError,
    _emit_runner_timings,
    _load_json,
    _timed,
    _validator_module,
)
from runner.hashing import (
    _canonical_bytes,
    _prepared_hash,
    _sha256_bytes,
    _sha256_path,
    _tree_hash,
    _write_exclusive,
)
from runner.ledger import _artifact_index, _ledger_events, _ledger_head, _write_index
from runner.lifecycle import (
    _cleanup_loaded,
    _ready_manifest,
    _record_failure_receipt,
    cleanup,
)
from runner.snapshots import _verify_dependency_layer
from runner.execution import _validated_command
from runner.scaffolds import _record_validation_error, stage_artifact


def _staged_artifacts(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index = _artifact_index(manifest)
    if set(index["artifacts"]) != set(ARTIFACT_FILES):
        missing = sorted(set(ARTIFACT_FILES) - set(index["artifacts"]))
        raise RunGateError(f"finish requires all staged artifacts: {missing}")
    documents: dict[str, dict[str, Any]] = {}
    for kind, filename in ARTIFACT_FILES.items():
        record = index["artifacts"][kind]
        path = Path(manifest["artifact_root"]) / filename
        if record.get("path") != str(path) or record.get("sha256") != _sha256_path(path):
            raise RunGateError(f"staged artifact changed after Host indexing: {kind}")
        document = _load_json(path)
        if not isinstance(document, dict):
            raise RunGateError(f"staged artifact root must be an object: {kind}")
        documents[kind] = document
    return documents


def _attested_report(
    manifest: dict[str, Any],
    contract: dict[str, Any],
    draft: dict[str, Any],
    ledger: list[dict[str, Any]],
    *,
    manifest_sha256: str,
    ledger_head: str,
) -> dict[str, Any]:
    guarded = [item for item in ledger if item.get("kind") == "guarded-write"]
    registered = [
        item for item in ledger if item.get("kind") in {"guarded-write", "prebuilt"}
    ]
    if guarded:
        strategy = "guarded-file-write"
    elif registered:
        strategy = "prebuilt-mutant"
    else:
        strategy = "comparison-only"
    protection = manifest["protection"]
    protected = protection["mode"] in {"os-read-only", "permission-read-only"}
    monitored = protection["mode"] in {"host-events", "os-audit"}
    unresolved = [item["id"] for item in contract.get("unresolved", [])]
    baselines = [
        item for item in ledger
        if item.get("kind") == "command" and item.get("phase") == "baseline"
    ]
    mutation_executions = [
        item for item in ledger
        if item.get("kind") == "command" and item.get("phase") == "mutation"
    ]
    prepared_events = [
        item for item in ledger if item.get("kind") == "prepared-snapshot"
    ]
    if len(prepared_events) != 1:
        raise RunGateError("finish requires exactly one sealed prepared snapshot")
    prepared = prepared_events[0]
    clone_events = [
        item for item in registered
        if item.get("sandbox_root") and item.get("clone_strategy")
    ]

    def raw_outcome(item: dict[str, Any]) -> str:
        if item.get("result") == "timeout":
            return "timeout"
        return "passed" if item.get("returncode") == 0 else "failed"

    batch_timings: dict[str, list[int]] = {}
    individual_mutation_ms = 0
    for item in mutation_executions:
        duration = item.get("duration_ms", 0)
        batch = item.get("batch_plan_sha256")
        if batch:
            batch_timings.setdefault(batch, []).append(duration)
        else:
            individual_mutation_ms += duration
    mutation_wall_ms = individual_mutation_ms + sum(
        max(durations, default=0) for durations in batch_timings.values()
    )

    report = {
        "version": 10,
        "mode": draft["mode"],
        "write_mode": "review-only",
        "run": {
            "id": manifest["run_id"],
            "entrypoint": ENTRYPOINT,
            "host_adapter": manifest["host"]["adapter_id"],
            "run_nonce": manifest["host"]["run_nonce"],
            "manifest_sha256": manifest_sha256,
            "ledger_head": ledger_head,
        },
        "intent_contract": {
            "path": "host-artifact://intent-contract",
            "status": contract["status"],
        },
        "baseline": draft["baseline"],
        "assessment": draft["assessment"],
        "mutations": draft["mutations"],
        "not_challenged": draft["not_challenged"],
        "unresolved": unresolved,
        "test_changes": draft["test_changes"],
        "test_handoff": draft["test_handoff"],
        "authorized_workspace_changes": draft["authorized_workspace_changes"],
        "change_context": manifest["change_context"],
        "prepared_snapshot": {
            "root": prepared["root"],
            "sha256": prepared["sha256"],
            "protection": prepared["protection"],
            "dependency_layer": prepared["dependency_layer"],
            "clones": [
                {
                    "mutation_id": item["mutation_id"],
                    "sandbox_root": item["sandbox_root"],
                    "strategy": item["clone_strategy"],
                }
                for item in sorted(
                    clone_events, key=lambda event: event["mutation_id"]
                )
            ],
        },
        "execution_evidence": {
            "source": "host-ledger",
            "baseline": [
                {
                    "attempt": attempt,
                    "outcome": raw_outcome(item),
                    "exit_code": item.get("returncode"),
                    "duration_ms": item.get("duration_ms", 0),
                }
                for attempt, item in enumerate(baselines, 1)
            ],
            "mutations": [
                {
                    "mutation_id": item["mutation_id"],
                    "attempt": attempt,
                    "outcome": raw_outcome(item),
                    "exit_code": item.get("returncode"),
                    "duration_ms": item.get("duration_ms", 0),
                }
                for mutation_id in sorted({
                    item["mutation_id"] for item in mutation_executions
                })
                for attempt, item in enumerate(
                    [
                        event for event in mutation_executions
                        if event["mutation_id"] == mutation_id
                    ],
                    1,
                )
            ],
        },
        "phase_timings_ms": {
            "baseline": sum(item.get("duration_ms", 0) for item in baselines),
            "mutations": mutation_wall_ms,
        },
        "isolation": {
            "execution_strategy": strategy,
            "primary_root": manifest["primary_root"],
            "sandbox_root": manifest["sandbox_root"],
            "host_protection": {
                "mode": protection["mode"] if protected else "unavailable",
                "verified": protected,
                "details": protection["details"] if protected else "not used",
            },
            "write_monitor": {
                "mode": protection["mode"] if monitored else "unavailable",
                "verified": monitored,
                "details": protection["details"] if monitored else "not used",
            },
            "mutation_targets": [
                {
                    "mutation_id": item["mutation_id"],
                    "requested_path": item["requested_path"],
                    "resolved_path": item["resolved_path"],
                    "within_sandbox": True,
                }
                for item in guarded
            ],
            "write_events": [
                {
                    "target": item["resolved_path"],
                    "bytes": item["bytes"],
                    "within_sandbox": True,
                }
                for item in guarded
            ],
        },
        "persistent_side_effects": draft["persistent_side_effects"],
        "canonical_output": {
            "renderer": "socratic/scripts/validate_and_render.py",
            "sha256": "0" * 64,
            "extra_prose": False,
        },
        "postflight": {
            "primary_written_during_run": False,
            "primary_final_hash_unchanged": True,
            "working_tree_final_status": "primary content hash matched preflight",
            "production_mutation_free": True,
            "sandbox_destroyed": True,
            "notes": "Host protection accepted; disposable sandbox removed before rendering.",
        },
    }
    return report


def finish_document(
    manifest: dict[str, Any], report: dict[str, Any], review: dict[str, Any],
    ledger: list[dict[str, Any]], *, manifest_sha256: str, ledger_head: str,
) -> None:
    if manifest.get("status") != "ready" or manifest.get("protection", {}).get("verified") is not True:
        raise RunGateError("run did not pass trusted Host-attested preflight")
    if report.get("write_mode") == "review-only" and report.get("postflight", {}).get("primary_written_during_run") is not False:
        raise RunGateError("Review-only run wrote to the primary repository, even if later restored")
    run = report.get("run", {})
    expected_run = {
        "id": manifest["run_id"], "entrypoint": ENTRYPOINT,
        "host_adapter": manifest["host"]["adapter_id"],
        "run_nonce": manifest["host"]["run_nonce"],
        "manifest_sha256": manifest_sha256, "ledger_head": ledger_head,
    }
    if run != expected_run:
        raise RunGateError("report run identity does not match the host-issued manifest and ledger chain")
    mutations = {item["id"]: item for item in report.get("mutations", [])}
    registered = {
        item.get("mutation_id") for item in ledger
        if item.get("kind") in {"guarded-write", "prebuilt"}
    }
    executions: dict[str, list[dict[str, Any]]] = {}
    baselines = [item for item in ledger if item.get("kind") == "command" and item.get("phase") == "baseline"]
    for item in ledger:
        if item.get("kind") == "command" and item.get("phase") == "mutation":
            executions.setdefault(item["mutation_id"], []).append(item)
    if not baselines:
        raise RunGateError("run has no baseline execution evidence")
    baseline = report.get("baseline", {})
    if baseline.get("attempts") != len(baselines):
        raise RunGateError("report baseline attempts do not match baseline execution evidence")
    baseline_results = [item.get("result", "completed") for item in baselines]
    baseline_codes = [item.get("returncode") for item in baselines]
    baseline_status = baseline.get("status")
    if baseline_status == "green" and (
        any(result != "completed" for result in baseline_results)
        or any(code != 0 for code in baseline_codes)
    ):
        raise RunGateError("green baseline does not match successful execution evidence")
    if baseline_status == "baseline-red" and not any(
        result == "completed" and code != 0
        for result, code in zip(baseline_results, baseline_codes)
    ):
        raise RunGateError("baseline-red does not match failing execution evidence")
    if baseline_status == "not-runnable" and not any(
        result == "timeout" for result in baseline_results
    ):
        raise RunGateError("not-runnable baseline has no timeout execution evidence")
    if baseline_status == "flaky-reduced" and not (
        any(result == "completed" and code == 0 for result, code in zip(baseline_results, baseline_codes))
        and baseline.get("excluded_tests")
    ):
        raise RunGateError("flaky-reduced baseline lacks a green execution and excluded tests")
    if set(mutations) != registered or set(mutations) != set(executions):
        raise RunGateError("every reported mutation requires guarded mutation and execution evidence")
    for mutation_id, mutation in mutations.items():
        mutation_executions = executions[mutation_id]
        completed_codes = [
            item.get("returncode") for item in mutation_executions
            if item.get("result", "completed") == "completed"
        ]
        timed_out = any(item.get("result") == "timeout" for item in mutation_executions)
        runner_failed = any(
            item.get("result") == "runner-error" for item in mutation_executions
        )
        interpretation = mutation.get("outcome_interpretation", {}).get("kind")
        failed = any(code != 0 for code in completed_codes)
        passed = bool(completed_codes) and all(code == 0 for code in completed_codes)
        if interpretation == "passed" and (timed_out or not passed):
            raise RunGateError(
                f"passed interpretation contradicts raw execution: {mutation_id}"
            )
        if interpretation in {
            "behavioral-failure",
            "infrastructure-failure",
            "process-crash",
            "unparseable",
        } and not (failed or runner_failed):
            raise RunGateError(
                f"failure interpretation has no failing execution: {mutation_id}"
            )
        if interpretation == "timeout" and not timed_out:
            raise RunGateError(
                f"timeout interpretation has no timeout execution: {mutation_id}"
            )
        if mutation["result"] == "killed" and not any(code != 0 for code in completed_codes):
            raise RunGateError(f"killed mutation has no failing execution: {mutation_id}")
        if (
            mutation["result"] == "killed"
            and interpretation != "behavioral-failure"
        ):
            raise RunGateError(
                f"killed mutation is not classified as a behavioral failure: {mutation_id}"
            )
        if mutation["result"] == "survived" and (
            timed_out or not completed_codes or any(code != 0 for code in completed_codes)
        ):
            raise RunGateError(f"survived mutation has a failing execution: {mutation_id}")
        if mutation["result"] == "survived" and interpretation != "passed":
            raise RunGateError(
                f"survived mutation is not classified as passed: {mutation_id}"
            )
        if mutation["result"] == "timeout" and not timed_out:
            raise RunGateError(f"timeout mutation has no timeout execution: {mutation_id}")
    isolation = report.get("isolation", {})
    if isolation.get("primary_root") != manifest["primary_root"] or isolation.get("sandbox_root") != manifest["sandbox_root"]:
        raise RunGateError("report roots differ from trusted host preflight")
    protection = manifest["protection"]
    evidence = isolation.get("host_protection", {}) if protection["mode"] in {"os-read-only", "permission-read-only"} else isolation.get("write_monitor", {})
    if evidence.get("mode") != protection["mode"] or evidence.get("verified") is not True:
        raise RunGateError("report protection evidence differs from the trusted Host attestation")
    targets = {(item.get("mutation_id"), item.get("resolved_path")) for item in isolation.get("mutation_targets", [])}
    guarded = {
        (item.get("mutation_id"), item.get("resolved_path"))
        for item in ledger if item.get("kind") == "guarded-write"
    }
    if targets != guarded:
        raise RunGateError("report mutation targets do not match the guarded write ledger")
    prepared_events = [
        item for item in ledger if item.get("kind") == "prepared-snapshot"
    ]
    if len(prepared_events) != 1:
        raise RunGateError("report lacks a unique prepared snapshot event")
    prepared_report = report.get("prepared_snapshot", {})
    prepared_event = prepared_events[0]
    expected_prepared = {
        "root": prepared_event["root"],
        "sha256": prepared_event["sha256"],
        "protection": prepared_event["protection"],
        "dependency_layer": prepared_event["dependency_layer"],
        "clones": [
            {
                "mutation_id": item["mutation_id"],
                "sandbox_root": item["sandbox_root"],
                "strategy": item["clone_strategy"],
            }
            for item in sorted(
                [
                    event for event in ledger
                    if event.get("kind") in {"guarded-write", "prebuilt"}
                ],
                key=lambda event: event["mutation_id"],
            )
        ],
    }
    if prepared_report != expected_prepared:
        raise RunGateError("prepared snapshot evidence differs from the Host ledger")


def _record_host_output(
    manifest: dict[str, Any],
    kind: str,
    filename: str,
    content: bytes,
    schema: str,
) -> Path:
    path = Path(manifest["artifact_root"]) / filename
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
    index = _artifact_index(manifest)
    index["artifacts"][kind] = {
        "path": str(path),
        "sha256": _sha256_path(path),
        "schema": schema,
        "host_generated": True,
    }
    _write_index(Path(manifest["artifact_index_path"]), index)
    return path


def _analysis_drafts(
    manifest: dict[str, Any],
    analysis: dict[str, Any],
    plan: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    events = _ledger_events(manifest)
    baselines = [
        item for item in events
        if item.get("kind") == "command" and item.get("phase") == "baseline"
    ]
    if not baselines:
        raise RunGateError("complete requires one probed baseline command")
    command = _validated_command(manifest, plan["command_id"])
    challenges = {item["id"]: item for item in plan["challenges"]}
    classifications = {
        item["mutation_id"]: item for item in analysis["classifications"]
    }
    if len(classifications) != len(analysis["classifications"]):
        raise RunGateError("analysis classification IDs must be unique")
    if set(classifications) != set(challenges):
        raise RunGateError(
            "analysis must classify every planned challenge exactly once"
        )
    mutations: list[dict[str, Any]] = []
    for mutation_id in sorted(challenges):
        challenge = challenges[mutation_id]
        classification = classifications[mutation_id]
        operation = challenge["mutation"]
        item = {
            "id": mutation_id,
            "mode": analysis["mode"],
            "contract_ids": challenge["contract_ids"],
            "source_intent": classification["source_intent"],
            "changed_intent": classification["changed_intent"],
            "represented_risk": challenge["accident"],
            "severity": challenge["severity"],
            "likelihood": challenge["likelihood"],
            "code_change": (
                f"{operation['kind']} at exact anchor in "
                f"{operation['relative_path']}"
            ),
            "code_location": challenge["code_location"],
            "expected_detection": challenge["expected_detection"],
            "result": classification["result"],
            "detecting_tests": classification["detecting_tests"],
            "observed_failure_reason": classification["observed_failure_reason"],
            "contract_violation_observed": classification[
                "contract_violation_observed"
            ],
            "follow_up": classification["follow_up"],
            "outcome_interpretation": classification["outcome_interpretation"],
        }
        for optional in ("equivalence_evidence", "catch"):
            if optional in classification:
                item[optional] = classification[optional]
        mutations.append(item)
    report = {
        "version": 1,
        "mode": analysis["mode"],
        "baseline": {
            "command": shlex.join(command["argv"]),
            "status": "green",
            "attempts": len(baselines),
            "stable_tests": analysis["stable_tests"],
            "excluded_tests": analysis["excluded_tests"],
        },
        "assessment": analysis["assessment"],
        "mutations": mutations,
        "not_challenged": analysis["not_challenged"],
        "test_changes": analysis["test_changes"],
        "test_handoff": analysis["test_handoff"],
        "authorized_workspace_changes": [],
        "persistent_side_effects": analysis["persistent_side_effects"],
    }
    return report, analysis["review"]


def complete(
    manifest_path: Path,
    *,
    retention: str = "discard",
    schema_root: Path | None = None,
) -> str:
    """Generate mechanical Drafts, finish, and clean up in one Runner-owned step."""
    if retention not in {"discard", "keep"}:
        raise RunGateError("retention must be discard or keep")
    manifest = _ready_manifest(manifest_path)
    artifact_root = Path(manifest["artifact_root"])
    analysis_path = artifact_root / "review-analysis.json"
    plan_path = artifact_root / "challenge-plan.json"
    analysis = _load_json(analysis_path)
    plan = _load_json(plan_path)
    if not isinstance(analysis, dict) or not isinstance(plan, dict):
        raise RunGateError("complete inputs must be JSON objects")
    validator = _validator_module()
    try:
        validator.validate_document(
            analysis, "review-analysis.schema.json", schema_root
        )
        validator.validate_document(
            plan, "challenge-plan.schema.json", schema_root
        )
    except validator.ArtifactError as error:
        _record_validation_error(manifest, "complete-input", str(error))
        raise RunGateError(str(error)) from error
    runner_timings: dict[str, int] = {}
    with _timed(runner_timings, "draft_generation"):
        report, review = _analysis_drafts(manifest, analysis, plan)
        try:
            validator.validate_document(
                report, "mutation-report-draft.schema.json", schema_root
            )
            validator.validate_document(
                review, "canonical-review.schema.json", schema_root
            )
        except validator.ArtifactError as error:
            _record_validation_error(manifest, "complete-generated", str(error))
            raise RunGateError(str(error)) from error
        for kind, document in (("report", report), ("review", review)):
            path = artifact_root / ARTIFACT_FILES[kind]
            _write_exclusive(path, document)
            stage_artifact(manifest_path, kind, schema_root)
    with _timed(runner_timings, "finish_total"):
        rendered = finish(manifest_path, schema_root)
    if retention == "discard":
        with _timed(runner_timings, "artifact_cleanup"):
            cleanup(manifest_path)
    _emit_runner_timings("complete", runner_timings)
    return rendered


def finish(manifest_path: Path, schema_root: Path | None = None) -> str:
    manifest = _ready_manifest(manifest_path)
    sandbox = Path(manifest["sandbox_root"])
    runner_timings: dict[str, int] = {}
    try:
        with _timed(runner_timings, "load_and_validate"):
            documents = _staged_artifacts(manifest)
            if documents["contract"].get("unresolved"):
                raise RunGateError(
                    "finish is blocked until every unresolved Intent decision is answered"
                )
            ledger = _ledger_events(manifest)
        with _timed(runner_timings, "primary_postflight_hash"):
            current_primary_hash = _tree_hash(Path(manifest["primary_root"]))
        if current_primary_hash != manifest["primary_sha256"]:
            raise RunGateError("Primary content hash changed during the Review-only run")
        prepared_events = [
            item for item in ledger if item.get("kind") == "prepared-snapshot"
        ]
        with _timed(runner_timings, "source_snapshot_verify"):
            source_unchanged = len(prepared_events) == 1 and _prepared_hash(
                Path(manifest["prepared_root"])
            ) == prepared_events[0].get("sha256")
        if not source_unchanged:
            raise RunGateError("prepared source snapshot changed after it was sealed")
        dependency_evidence = (
            prepared_events[0].get("dependency_layer", {})
            if prepared_events
            else {}
        )
        with _timed(runner_timings, "dependency_layer_verify"):
            _verify_dependency_layer(manifest, dependency_evidence)
        with _timed(runner_timings, "sandbox_cleanup"):
            if sandbox.exists():
                shutil.rmtree(sandbox)
        if sandbox.exists():
            raise RunGateError("disposable sandbox still exists after cleanup")
        with _timed(runner_timings, "report_generation"):
            report = _attested_report(
                manifest,
                documents["contract"],
                documents["report"],
                ledger,
                manifest_sha256=_sha256_path(manifest_path),
                ledger_head=_ledger_head(manifest),
            )
            finish_document(
                manifest, report, documents["review"], ledger,
                manifest_sha256=_sha256_path(manifest_path), ledger_head=_ledger_head(manifest),
            )
        validator = _validator_module()
        try:
            with _timed(runner_timings, "schema_validation"):
                validator.validate_document(
                    documents["contract"], "intent-contract.schema.json", schema_root
                )
                validator.validate_document(
                    report, "mutation-report.schema.json", schema_root
                )
                validator.validate_document(
                    documents["review"], "canonical-review.schema.json", schema_root
                )
                validator.validate_cross_artifact(
                    documents["contract"], report, documents["review"]
                )
            with _timed(runner_timings, "render"):
                rendered = validator.render_review(documents["review"])
            report["canonical_output"]["sha256"] = _sha256_bytes(
                rendered.encode("utf-8")
            )
            with _timed(runner_timings, "schema_validation"):
                validator.validate_with_schemas(
                    documents["contract"], report, documents["review"], schema_root
                )
        except validator.ArtifactError as error:
            raise RunGateError(str(error)) from error
        with _timed(runner_timings, "host_output"):
            _record_host_output(
                manifest,
                "attested-report",
                "mutation-report.attested.json",
                _canonical_bytes(report),
                "mutation-report.schema.json",
            )
            _record_host_output(
                manifest,
                "renderer-output",
                "renderer-output.txt",
                rendered.encode("utf-8"),
                "canonical renderer stdout",
            )
        _emit_runner_timings("finish", runner_timings)
        return rendered
    except BaseException as failure:
        cleanup_errors = _cleanup_loaded(manifest, manifest_path)
        _record_failure_receipt(manifest, manifest_path, "finish", failure, cleanup_errors)
        if cleanup_errors:
            raise RunGateError("; ".join(cleanup_errors)) from failure
        raise RunGateError(
            f"{failure}; the run terminated and disposable state was cleaned; "
            "a failure receipt remains in Host storage; "
            "do not retry complete with this manifest"
        ) from failure
