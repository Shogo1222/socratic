"""Runbook, next-step guidance, artifact staging, and JSON scaffolds."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from runner.constants import (
    ARTIFACT_FILES,
    ARTIFACT_SCHEMAS,
    ENTRYPOINT_PATH,
    REVIEW_TYPES,
    RunGateError,
    SOCRATIC_VERSION,
    _load_json,
    _validator_module,
)
from runner.hashing import _sha256_path
from runner.ledger import _artifact_index, _ledger_events, _write_index
from runner.lifecycle import _ready_manifest


def _next_step(*arguments: str, note: str | None = None) -> dict[str, Any]:
    """Exact argv for the next pipeline step. Agents run it verbatim.

    Placeholders in angle brackets mark the only parts an agent supplies;
    everything else must not be guessed or reordered.
    """
    announcements = {
        "runbook": "Explaining the review plan",
        "inspect": "Reviewing what changed",
        "scaffold-contract": "Establishing the intended behavior",
        "stage-artifact": "Validating the intended behavior",
        "execute": "Preparing the isolated test environment",
        "probe-command": "Running the current tests",
        "scaffold-plan": "Designing realistic accident patterns",
        "challenge-batch": "Verifying the accident patterns",
        "scaffold-analysis": "Interpreting what the tests protect",
        "complete": "Assembling the verified review and cleaning up",
    }
    step: dict[str, Any] = {
        "argv": [sys.executable, str(ENTRYPOINT_PATH), *arguments],
        "announce": announcements.get(
            arguments[0] if arguments else "", "Continuing the verified review"
        ),
    }
    if note:
        step["note"] = note
    return step


def _probe_next(manifest_path: Path) -> dict[str, Any]:
    return _next_step(
        "probe-command", "--manifest", str(manifest_path),
        "--command-id", "CMD-001",
        "--cwd", "<package-directory-or-dot>",
        "--", "<focused-test-argv>",
        note=(
            "replace placeholders with the package directory (or .) and direct "
            "test executable located via inspect search; never use a "
            "package-manager wrapper"
        ),
    )


SCAFFOLD_EDITABLE_FIELDS = {
    "contract": [
        "status",
        "change.base", "change.head", "change.summary",
        "intent.statement", "intent.confidence", "intent.evidence[*]",
        "decisions[*]", "invariants[*]",
        "side_effects.required[*]", "side_effects.prohibited[*]",
        "unresolved[*]", "coverage[*]",
    ],
    "plan": [
        "max_parallel",
        "challenges[*].id", "challenges[*].contract_ids",
        "challenges[*].accident", "challenges[*].expected_detection",
        "challenges[*].severity", "challenges[*].likelihood",
        "challenges[*].code_location", "challenges[*].mutation",
    ],
    "analysis": [
        "stable_tests[*]",
        "excluded_tests[*]",
        "assessment",
        "classifications[*].source_intent",
        "classifications[*].changed_intent",
        "classifications[*].result",
        "classifications[*].detecting_tests",
        "classifications[*].observed_failure_reason",
        "classifications[*].contract_violation_observed",
        "classifications[*].follow_up",
        "classifications[*].outcome_interpretation",
        "classifications[*].equivalence_evidence",
        "classifications[*].catch",
        "not_challenged[*]",
        "test_changes[*]",
        "test_handoff",
        "persistent_side_effects",
        "review.review_this[*]",
        "review.we_verified[*]",
        "review.still_at_risk[*]",
        "review.copy_ready_comments[*]",
    ],
}

SCAFFOLD_FIELD_GUIDES = {
    "contract": {
        "status": {
            "allowed": [
                "provisional", "needs-decision", "confirmed",
                "tested", "challenged", "hardened",
            ],
            "rule": (
                "Use needs-decision exactly when unresolved has an item; a "
                "resolved pre-test Contract normally remains provisional or confirmed."
            ),
        },
        "intent.confidence": {"allowed": ["high", "medium", "low"]},
        "intent.evidence[*]": {
            "required_keys": ["source", "supports"],
            "template": {
                "source": "path/to/repository-evidence",
                "supports": "What this evidence establishes",
            },
        },
        "decisions[*]": {
            "required_keys": ["id", "question", "expected", "provenance"],
            "allowed_provenance": [
                "user-confirmed",
                "repository-established",
                "reviewer-selected-benchmark-assumption",
            ],
            "template": {
                "id": "DEC-001",
                "question": "What observable behavior is expected?",
                "expected": "Describe the expected observable behavior",
                "provenance": "repository-established",
            },
        },
        "invariants[*]": {
            "required_keys": ["id", "statement", "severity"],
            "allowed_severity": ["critical", "high", "medium", "low"],
            "template": {
                "id": "INV-001",
                "statement": "Describe behavior that must remain unchanged",
                "severity": "high",
            },
        },
        "side_effects.required[*]": {
            "required_keys": ["id", "statement"],
            "template": {
                "id": "FX-001",
                "statement": "Describe a required observable side effect",
            },
        },
        "side_effects.prohibited[*]": {
            "required_keys": ["id", "statement"],
            "template": {
                "id": "FX-002",
                "statement": "Describe a prohibited observable side effect",
            },
        },
        "unresolved[*]": {
            "required_keys": ["id", "statement", "test_impact"],
            "optional_keys": ["blocked_contract_ids"],
            "rule": (
                "Adding an item requires status=needs-decision. Include "
                "blocked_contract_ids when the affected DEC/INV/FX IDs are known."
            ),
            "template": {
                "id": "UNR-001",
                "statement": "Describe the unresolved observable decision",
                "test_impact": "Explain how the answer changes the oracle",
                "blocked_contract_ids": ["DEC-001"],
            },
        },
        "coverage[*]": {
            "required_keys": ["contract_id", "tests"],
            "rule": "tests is a non-empty array of test names or paths, never a disposition object.",
            "template": {
                "contract_id": "DEC-001",
                "tests": ["path/to/test: test name"],
            },
        },
    },
    "plan": {
        "max_parallel": {"type": "integer", "minimum": 1, "maximum": 8},
        "challenges[*]": {
            "required_keys": [
                "id", "contract_ids", "accident", "expected_detection",
                "severity", "likelihood", "code_location", "mutation",
            ],
            "allowed_severity": ["low", "medium", "high", "critical"],
            "allowed_likelihood": ["low", "medium", "high"],
            "rule": (
                "contract_ids is a non-empty DEC/INV/FX array. Use only an "
                "exact anchored mutation; never embed a full source file."
            ),
        },
        "challenges[*].mutation": {
            "variants": {
                "replace-exact": {
                    "required_keys": ["kind", "relative_path", "before", "after"],
                    "template": {
                        "kind": "replace-exact",
                        "relative_path": "path/to/source",
                        "before": "exact unique source anchor",
                        "after": "mutated source anchor",
                    },
                },
                "delete-exact": {
                    "required_keys": ["kind", "relative_path", "before"],
                    "template": {
                        "kind": "delete-exact",
                        "relative_path": "path/to/source",
                        "before": "exact unique source anchor",
                    },
                },
            },
        },
    },
    "analysis": {
        "stable_tests[*]": {"item_type": "non-empty string"},
        "excluded_tests[*]": {"item_type": "non-empty string"},
        "assessment": {
            "rule": (
                "Required as an object in assessment mode; leave null in harden "
                "or catch unless a cohort comparison is being reported."
            ),
            "required_keys": [
                "selected_scope", "selection_reason", "production_files",
                "existing_tests", "changed_tests", "excluded_scope", "comparisons",
            ],
            "allowed_selected_scope": [
                "current-change", "changed-tests", "broader-target",
            ],
            "comparison_required_keys": [
                "mutation_id", "existing_result", "changed_result", "classification",
            ],
            "allowed_comparison_results": [
                "killed", "survived", "not-run", "not-comparable", "inconclusive",
            ],
            "allowed_comparison_classification": [
                "existing-protection", "incremental-protection",
                "protection-regression", "unprotected",
                "not-comparable", "inconclusive",
            ],
            "comparison_template": {
                "mutation_id": "MUT-001",
                "existing_result": "not-run",
                "changed_result": "killed",
                "classification": "incremental-protection",
            },
        },
        "classifications[*]": {
            "runner_created": True,
            "allowed_result": [
                "killed", "survived", "timeout", "invalid", "equivalent",
                "inconclusive", "weak-catch", "strong-catch",
                "false-positive", "not-comparable", "no-catch",
            ],
            "allowed_follow_up": [
                "none", "harden-test", "clarify-intent",
                "replace-mutant", "investigate-flake", "fix-infrastructure",
            ],
            "allowed_outcome_kind": [
                "passed", "behavioral-failure", "infrastructure-failure",
                "process-crash", "timeout", "unparseable",
            ],
            "rules": [
                "killed requires outcome kind behavioral-failure, at least one detecting test, and contract_violation_observed=true",
                "survived requires outcome kind passed",
                "timeout requires outcome kind timeout",
                "inconclusive uses infrastructure-failure, process-crash, timeout, or unparseable",
                "equivalent requires equivalence_evidence",
            ],
        },
        "classifications[*].catch": {
            "required_in_mode": "catch",
            "allowed_outcome": ["pass", "fail", "not-runnable"],
            "allowed_human_verdict": [
                "intended", "unintended", "unanswered", "not-requested",
            ],
            "template": {
                "parent_outcome": "not-runnable",
                "mutant_outcome": "not-runnable",
                "change_outcome": "not-runnable",
                "human_verdict": "unanswered",
            },
        },
        "not_challenged[*]": {
            "required_keys": ["contract_id", "reason", "residual_risk"],
            "allowed_reason": [
                "budget", "not-observable", "not-applicable", "deferred", "blocked",
            ],
            "template": {
                "contract_id": "INV-001",
                "reason": "not-applicable",
                "residual_risk": "Describe what remains unverified",
            },
        },
        "test_changes[*]": {
            "required_keys": ["name", "disposition"],
            "allowed_disposition": ["existing", "proposed"],
            "template": {
                "name": "path/to/test: test name",
                "disposition": "existing",
            },
        },
        "test_handoff": {
            "rule": (
                "Leave null in Review-only unless the Runner produced a Proven "
                "Test Handoff through an explicitly authorized test-change workflow."
            ),
        },
        "persistent_side_effects": {
            "rule": (
                "Keep authorization=not-requested and writes=[] unless the human "
                "separately authorized a persistent memory/profile/learning write."
            ),
        },
        "review.review_this[*]": {
            "required_keys": ["kind", "body", "contract_ids"],
            "allowed_kind": [
                "confirmed-behavior", "behavior-difference",
                "test-gap", "needs-decision",
            ],
            "template": {
                "kind": "test-gap",
                "body": "Describe the reviewer decision or gap",
                "contract_ids": ["INV-001"],
            },
        },
        "review.we_verified[*]": {"item_type": "non-empty string"},
        "review.still_at_risk[*]": {"item_type": "non-empty string"},
        "review.copy_ready_comments[*]": {
            "required_keys": ["tag", "file", "line", "body", "evidence"],
            "allowed_tag": ["Intent decision", "Behavior difference", "Test gap"],
            "maximum_items": 3,
            "template": {
                "tag": "Test gap",
                "file": "path/to/source",
                "line": 1,
                "body": "Copy-ready review comment",
                "evidence": "Repository or mutation evidence supporting the comment",
            },
        },
    },
}


def runbook(manifest_path: Path) -> dict[str, Any]:
    """One document that explains the whole run: read once after preflight.

    Generated from the loaded Runner so it cannot drift from the version that
    actually executes. It explains meaning and order, never raw JSON Schema.
    """
    manifest = _ready_manifest(manifest_path)
    m = str(manifest_path)
    review_type = manifest.get("review_type") or {
        "recommended": None,
        "options": list(REVIEW_TYPES),
        "requires_human_confirmation": True,
    }
    return {
        "socratic_version": SOCRATIC_VERSION,
        "run_id": manifest["run_id"],
        "mission": (
            "Infer intended observable behavior from repository evidence, expose "
            "only consequential uncertainty, and design realistic accidents that "
            "test whether the suite protects that intent. The Runner owns "
            "commands, mutation mechanics, JSON structure, hashes, ledgers, "
            "reports, and cleanup."
        ),
        "id_glossary": {
            "DEC": "a settled decision about expected observable behavior",
            "INV": "existing behavior that must not break after the change",
            "FX": "a side effect that is required or prohibited",
            "UNR": "an open question repository evidence cannot settle; blocks its mutations",
            "CMD": "a focused test command the Runner probed successfully and will reuse",
            "MUT": "one realistic accident model injected into a disposable clone",
        },
        "gates": [
            "unresolved UNR present -> Contract status needs-decision; mutations for its Contract IDs stay blocked",
            "Contract staged and resolved -> probe the focused command",
            "probe success -> CMD issued; scaffold the challenge plan",
            "challenge-batch complete -> scaffold the analysis and interpret raw outcomes",
            "classification complete -> complete generates, renders, and cleans up",
        ],
        "agent_edits": [
            "intent", "decisions", "invariants", "side effects",
            "accident models", "classification reasons", "detecting tests",
            "reviewer-facing claims",
        ],
        "runner_owns": [
            "JSON structure", "command IDs", "run identity", "hashes",
            "ledger", "attestation", "report mechanics", "cleanup",
        ],
        "hard_rules": [
            "run every Runner command synchronously in the foreground; never background one",
            "never read schema files; every JSON starts from a Runner scaffold and follows its field_guide",
            "follow next.argv verbatim; never guess or reorder arguments",
            "do not delegate deterministic discovery to subagents",
            "one challenge-batch per run",
            "present the renderer output verbatim; never translate, summarize, or append",
            "sandbox commands use the project's own toolchain by absolute path; the injected runtime Python exists only for run_review.py",
            "after an infrastructure failure, run the doctor command from the result's diagnose.argv before changing tools or arguments",
        ],
        "execution_plan": [
            {"id": "inspect", "label": "Review what changed"},
            {"id": "intent", "label": "Establish the intent and the behavior to protect"},
            {"id": "prepare", "label": "Prepare the isolated test environment"},
            {"id": "baseline", "label": "Run the current tests"},
            {"id": "challenge", "label": "Verify realistic accident patterns"},
            {"id": "report", "label": "Assemble the verified review"},
            {"id": "cleanup", "label": "Remove the disposable environment"},
        ],
        "announcement_rules": [
            "before the first step, show the execution plan to the user in their language",
            "before each next.argv, translate next.announce into the user's language",
            "if one phase exceeds 30 seconds, say why and report elapsed time",
            "never show an unfounded percentage",
        ],
        "checkpoint": {
            "id": "review-type",
            "required_before_next": True,
            "recommended": review_type["recommended"],
            "options": review_type["options"],
            "instruction": (
                "State the Mission and execution plan in the user's language, "
                "then obtain confirmation or correction of the Host-recommended "
                "Review Type before running next.argv. A null recommendation means "
                "the Host supplied no routing hint, so ask the human to select one."
            ),
        },
        "next": _next_step(
            "inspect", "--manifest", m, "--kind", "diff",
            note=(
                "run after Review Type confirmation; use further bounded inspect "
                "calls if needed, then complete the Diff understanding checkpoint"
            ),
        ),
    }


def _record_validation_error(manifest: dict[str, Any], kind: str, message: str) -> None:
    path = Path(manifest["artifact_root"]) / "validation-errors.json"
    current: dict[str, Any] = {
        "version": 1,
        "run_id": manifest["run_id"],
        "errors": [],
    }
    if path.is_file():
        loaded = _load_json(path)
        if isinstance(loaded, dict) and isinstance(loaded.get("errors"), list):
            current = loaded
    current["errors"].append({"artifact": kind, "message": message})
    _write_index(path, current)


def stage_artifact(
    manifest_path: Path,
    kind: str,
    schema_root: Path | None = None,
) -> dict[str, Any]:
    manifest = _ready_manifest(manifest_path)
    if kind not in ARTIFACT_FILES:
        raise RunGateError(f"unknown artifact kind: {kind}")
    index = _artifact_index(manifest)
    if kind in index["artifacts"]:
        raise RunGateError(f"artifact is already staged and create-once: {kind}")
    artifact_path = Path(manifest["artifact_root"]) / ARTIFACT_FILES[kind]
    if (
        not artifact_path.is_file()
        or artifact_path.is_symlink()
        or artifact_path.parent.resolve(strict=True) != Path(manifest["artifact_root"]).resolve(strict=True)
    ):
        raise RunGateError(f"draft artifact is missing from the Host staging channel: {kind}")
    document = _load_json(artifact_path)
    if not isinstance(document, dict):
        raise RunGateError(f"draft artifact root must be an object: {kind}")
    validator = _validator_module()
    try:
        validator.validate_document(document, ARTIFACT_SCHEMAS[kind], schema_root)
    except validator.ArtifactError as error:
        _record_validation_error(manifest, kind, str(error))
        raise RunGateError(str(error)) from error
    record = {
        "path": str(artifact_path),
        "sha256": _sha256_path(artifact_path),
        "schema": ARTIFACT_SCHEMAS[kind],
    }
    index["artifacts"][kind] = record
    _write_index(Path(manifest["artifact_index_path"]), index)
    (Path(manifest["artifact_root"]) / "validation-errors.json").unlink(missing_ok=True)
    return record


def _scaffold_document(
    manifest: dict[str, Any],
    filename: str,
    document: dict[str, Any],
    schema_name: str,
    schema_root: Path | None,
) -> dict[str, Any]:
    validator = _validator_module()
    try:
        validator.validate_document(document, schema_name, schema_root)
    except validator.ArtifactError as error:
        raise RunGateError(f"scaffold failed self-validation: {error}") from error
    artifact = Path(manifest["artifact_root"]) / filename
    if artifact.exists():
        raise RunGateError(
            f"{filename} already exists; edit it in place instead of scaffolding"
        )
    return document


def _scaffold_write_protocol(
    manifest: dict[str, Any], filename: str
) -> dict[str, Any]:
    path = Path(manifest["artifact_root"]) / filename
    return {
        "artifact_path": str(path),
        "write_protocol": {
            "first_write": (
                "Use Write exactly once to create artifact_path from the returned "
                "document after replacing semantic placeholders."
            ),
            "correction": (
                "If the file already exists, Read it and use Edit; never call "
                "Write on an existing scaffold."
            ),
        },
    }


def scaffold_contract(
    manifest_path: Path, schema_root: Path | None = None
) -> dict[str, Any]:
    """Generate a structurally valid Intent Contract for one first Write.

    Agents fill every replace-me value from repository evidence and never need
    to read the schema files; stage-artifact validates the written content.
    """
    manifest = _ready_manifest(manifest_path)
    document = {
        "version": 1,
        "status": "provisional",
        "change": {
            "base": "replace-me: Base identity (SHA or snapshot label)",
            "head": "replace-me: Head identity",
            "summary": "replace-me: one-sentence observable change summary",
        },
        "intent": {
            "statement": "replace-me: the intended observable behavior",
            "confidence": "low",
            "evidence": [
                {
                    "source": "replace-me: repository evidence path",
                    "supports": "replace-me: what this evidence establishes",
                }
            ],
        },
        "decisions": [
            {
                "id": "DEC-001",
                "question": "replace-me: the observable behavior question",
                "expected": "replace-me: the expected observable answer",
                "provenance": "repository-established",
            }
        ],
        "invariants": [
            {
                "id": "INV-001",
                "statement": "replace-me: behavior that must not change",
                "severity": "high",
            }
        ],
        "side_effects": {"required": [], "prohibited": []},
        "unresolved": [],
        "coverage": [],
    }
    return _scaffold_document(
        manifest, ARTIFACT_FILES["contract"], document,
        "intent-contract.schema.json", schema_root,
    )


def scaffold_plan(
    manifest_path: Path, schema_root: Path | None = None
) -> dict[str, Any]:
    """Write a structurally valid challenge-plan template bound to the validated command."""
    manifest = _ready_manifest(manifest_path)
    validated = [
        item for item in _ledger_events(manifest)
        if item.get("kind") == "validated-command"
    ]
    if not validated:
        raise RunGateError("scaffold-plan requires a successful probe-command first")
    document = {
        "version": 2,
        "command_id": validated[-1]["command_id"],
        "max_parallel": 2,
        "challenges": [
            {
                "id": "MUT-001",
                "contract_ids": ["DEC-001"],
                "accident": "replace-me: the realistic accident this mutation represents",
                "expected_detection": "replace-me: the observable failure that should catch it",
                "severity": "high",
                "likelihood": "medium",
                "code_location": "replace-me/relative/path:1",
                "mutation": {
                    "kind": "replace-exact",
                    "relative_path": "replace-me/relative/path",
                    "before": "replace-me: exact unique anchor text",
                    "after": "replace-me: mutated text",
                },
            }
        ],
    }
    return _scaffold_document(
        manifest, "challenge-plan.json", document,
        "challenge-plan.schema.json", schema_root,
    )


def scaffold_analysis(
    manifest_path: Path,
    mode: str,
    schema_root: Path | None = None,
) -> dict[str, Any]:
    """Generate a valid semantic-only analysis scaffold from Plan and raw outcomes."""
    if mode not in {"assessment", "harden", "catch"}:
        raise RunGateError("analysis mode must be assessment, harden, or catch")
    manifest = _ready_manifest(manifest_path)
    artifact_root = Path(manifest["artifact_root"])
    plan = _load_json(artifact_root / "challenge-plan.json")
    if not isinstance(plan, dict):
        raise RunGateError("challenge plan root must be an object")
    validator = _validator_module()
    try:
        validator.validate_document(
            plan, "challenge-plan.schema.json", schema_root
        )
    except validator.ArtifactError as error:
        raise RunGateError(str(error)) from error
    executions = {
        item["mutation_id"]: item
        for item in _ledger_events(manifest)
        if item.get("kind") == "command" and item.get("phase") == "mutation"
    }
    planned_ids = [item["id"] for item in plan["challenges"]]
    if set(executions) != set(planned_ids):
        raise RunGateError(
            "analysis scaffold requires raw execution for every planned challenge"
        )
    classifications = []
    for mutation_id in planned_ids:
        event = executions[mutation_id]
        if event.get("result") == "timeout":
            result = "timeout"
            kind = "timeout"
            reason = "The Runner recorded a timeout; confirm the residual risk"
        elif event.get("result") == "runner-error":
            result = "inconclusive"
            kind = "infrastructure-failure"
            reason = "The Runner failed before a behavioral result was available"
        elif event.get("returncode") == 0:
            result = "survived"
            kind = "passed"
            reason = "The focused tests remained green for this accident"
        else:
            result = "inconclusive"
            kind = "unparseable"
            reason = (
                "The process failed; classify whether the failure is behavioral "
                "or infrastructure from the raw outcome"
            )
        classification: dict[str, Any] = {
            "mutation_id": mutation_id,
            "source_intent": f"Describe the protected intent for {mutation_id}",
            "changed_intent": f"Describe the accidental behavior for {mutation_id}",
            "result": result,
            "detecting_tests": [],
            "observed_failure_reason": reason,
            "contract_violation_observed": False,
            "follow_up": "none",
            "outcome_interpretation": {"kind": kind, "reason": reason},
        }
        if mode == "catch":
            classification["catch"] = {
                "parent_outcome": "not-runnable",
                "mutant_outcome": "not-runnable",
                "change_outcome": "not-runnable",
                "human_verdict": "unanswered",
            }
        classifications.append(classification)
    assessment = (
        {
            "selected_scope": "current-change",
            "selection_reason": "replace-me: why this assessment scope was selected",
            "production_files": [],
            "existing_tests": [],
            "changed_tests": [],
            "excluded_scope": [],
            "comparisons": [],
        }
        if mode == "assessment"
        else None
    )
    document = {
        "version": 1,
        "mode": mode,
        "stable_tests": [],
        "excluded_tests": [],
        "assessment": assessment,
        "classifications": classifications,
        "not_challenged": [],
        "test_changes": [],
        "test_handoff": None,
        "persistent_side_effects": {
            "authorization": "not-requested",
            "writes": [],
        },
        "review": {
            "review_this": [],
            "we_verified": [],
            "still_at_risk": [],
            "copy_ready_comments": [],
        },
    }
    try:
        validator.validate_document(
            document, "review-analysis.schema.json", schema_root
        )
    except validator.ArtifactError as error:
        raise RunGateError(str(error)) from error
    path = artifact_root / "review-analysis.json"
    if path.exists():
        raise RunGateError(
            "review-analysis.json already exists; edit it in place instead of scaffolding"
        )
    return {
        "status": "generated",
        "path": str(path),
        "document": document,
        "classifications": len(classifications),
        "next": (
            "write the returned document once after editing semantic intent, "
            "classification, detecting tests, and review claims; do not add run "
            "identity, hashes, commands, or evidence mechanics"
        ),
    }
