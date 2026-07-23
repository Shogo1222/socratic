#!/usr/bin/env python3
"""Validate Socratic run artifacts and render exactly the canonical four blocks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


class ArtifactError(ValueError):
    """Raised when run artifacts cannot safely be treated as complete."""


CONTRACT_ID_PATTERN = re.compile(r"\b(?:DEC|INV|FX)-[0-9]{3,}\b")
ARTIFACT_SCHEMAS = (
    "challenge-plan.schema.json",
    "evidence-bundle.schema.json",
    "experiment-plan.schema.json",
    "interpretation.schema.json",
    "intent-contract.schema.json",
    "mutation-result.schema.json",
    "mutation-report.schema.json",
    "mutation-report-draft.schema.json",
    "review-analysis.schema.json",
    "test-handoff.schema.json",
    "canonical-review.schema.json",
)


def load_strict_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ArtifactError(f"strict JSON parse failed for {path}: {error}") from error
    if not isinstance(value, dict):
        raise ArtifactError(f"artifact root must be an object: {path}")
    return value


def _contract_ids(contract: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    ids.update(item["id"] for item in contract.get("decisions", []))
    ids.update(item["id"] for item in contract.get("invariants", []))
    side_effects = contract.get("side_effects", {})
    ids.update(item["id"] for item in side_effects.get("required", []))
    ids.update(item["id"] for item in side_effects.get("prohibited", []))
    return ids


def validate_cross_artifact(
    contract: dict[str, Any],
    report: dict[str, Any],
    review: dict[str, Any] | None = None,
) -> None:
    known = _contract_ids(contract)
    unresolved = {item["id"] for item in contract.get("unresolved", [])}
    errors: list[str] = []

    for mutation in report.get("mutations", []):
        missing = sorted(set(mutation.get("contract_ids", [])) - known)
        if missing:
            errors.append(f"{mutation.get('id', '<unknown>')} references unknown Contract IDs: {missing}")

    report_unresolved = set(report.get("unresolved", []))
    if report_unresolved != unresolved:
        errors.append(
            "Contract and report unresolved IDs differ: "
            f"contract={sorted(unresolved)}, report={sorted(report_unresolved)}"
        )

    contract_status = contract.get("status")
    report_status = report.get("intent_contract", {}).get("status")
    if contract_status != report_status:
        errors.append(
            f"Contract and report statuses differ: {contract_status!r} != {report_status!r}"
        )
    if unresolved and contract_status != "needs-decision":
        errors.append("a Contract with unresolved items must have status needs-decision")
    if not unresolved and contract_status == "needs-decision":
        errors.append("needs-decision requires at least one unresolved item")
    if review is not None:
        review_known = known | unresolved
        for index, item in enumerate(review.get("review_this", []), 1):
            references = set(item.get("contract_ids", []))
            missing = sorted(references - review_known)
            if missing:
                errors.append(
                    f"Review This item {index} references unknown Contract IDs: {missing}"
                )
            needs_decision = item.get("kind") == "needs-decision"
            if needs_decision and not references.intersection(unresolved):
                errors.append(
                    f"Review This item {index} claims needs-decision without an unresolved ID"
                )
            if not needs_decision and references.intersection(unresolved):
                errors.append(
                    f"Review This item {index} hides an unresolved ID as a resolved finding"
                )

    isolation = report.get("isolation", {})
    sandbox_root = Path(isolation.get("sandbox_root", "/__missing_sandbox__")).resolve(strict=False)
    primary_root = Path(isolation.get("primary_root", "/__missing_primary__")).resolve(strict=False)
    for target in isolation.get("mutation_targets", []):
        resolved = Path(target.get("resolved_path", "")).resolve(strict=False)
        try:
            resolved.relative_to(sandbox_root)
        except ValueError:
            errors.append(f"mutation target is outside reported sandbox: {resolved}")
        try:
            resolved.relative_to(primary_root)
        except ValueError:
            pass
        else:
            errors.append(f"mutation target is inside reported primary root: {resolved}")

    if isolation.get("execution_strategy") == "guarded-file-write":
        mutation_ids = {mutation.get("id") for mutation in report.get("mutations", [])}
        target_ids = {target.get("mutation_id") for target in isolation.get("mutation_targets", [])}
        missing_targets = sorted(mutation_ids - target_ids)
        if missing_targets:
            errors.append(f"guarded mutations lack resolved target evidence: {missing_targets}")

    postflight = report.get("postflight", {})
    if report.get("write_mode") == "review-only" and postflight.get("primary_written_during_run"):
        errors.append("Review-only report records a primary workspace write")
    if not postflight.get("production_mutation_free", False):
        errors.append("production mutation remains after the run")
    if not postflight.get("sandbox_destroyed", False):
        errors.append("mutation sandbox was not destroyed")
    host_verified = isolation.get("host_protection", {}).get("verified", False)
    monitor_verified = isolation.get("write_monitor", {}).get("verified", False)
    if (
        postflight.get("primary_written_during_run") is False
        and not host_verified
        and not monitor_verified
    ):
        errors.append(
            "primary_written_during_run=false requires an accepted Host protection or write-monitor attestation"
        )

    persistent = report.get("persistent_side_effects", {})
    writes = persistent.get("writes", [])
    if writes and persistent.get("authorization") != "explicitly-authorized":
        errors.append("persistent writes require separate explicit authorization")
    if any(not write.get("authorized", False) for write in writes):
        errors.append("persistent side-effect ledger contains an unauthorized write")

    if errors:
        raise ArtifactError("; ".join(errors))


def _blocked_contract_ids(unresolved_item: dict[str, Any]) -> set[str]:
    explicit = set(unresolved_item.get("blocked_contract_ids", []))
    if explicit:
        return explicit
    return set(CONTRACT_ID_PATTERN.findall(unresolved_item.get("test_impact", "")))


def assert_elenchus_allowed(contract: dict[str, Any], contract_ids: list[str]) -> None:
    blocked: set[str] = set()
    for item in contract.get("unresolved", []):
        mapped = _blocked_contract_ids(item)
        # Missing mappings fail closed for every challenged oracle.
        if not mapped:
            blocked.update(contract_ids)
        else:
            blocked.update(mapped)
    challenged = sorted(set(contract_ids) & blocked)
    if challenged:
        raise ArtifactError(
            f"Elenchus is blocked for unresolved Contract IDs: {challenged}"
        )


def route_intent_decision(
    *,
    evidence_resolves: bool,
    multiple_reasonable_expectations: bool,
    answer_changes_oracle: bool,
    answerer_has_authority: bool | None,
) -> str:
    if evidence_resolves:
        return "repository-established"
    if not multiple_reasonable_expectations or not answer_changes_oracle:
        return "no-question"
    if answerer_has_authority is False:
        return "defer-to-specification-owner"
    return "ask-structured-question"


def decision_options(options: list[str], *, answerer_has_authority: bool | None) -> list[str]:
    result = list(options)
    if answerer_has_authority is not True:
        result.append("Defer / confirm with specification owner")
    return result


def _schema_paths(schema_root: Path | None) -> dict[str, Path]:
    if schema_root is not None:
        return {name: schema_root / name for name in ARTIFACT_SCHEMAS}
    skills_root = Path(__file__).resolve().parents[2]
    return {
        "challenge-plan.schema.json": (
            skills_root / "socratic" / "references" / "challenge-plan.schema.json"
        ),
        "evidence-bundle.schema.json": (
            skills_root / "socratic" / "references" / "evidence-bundle.schema.json"
        ),
        "experiment-plan.schema.json": (
            skills_root / "socratic" / "references" / "experiment-plan.schema.json"
        ),
        "interpretation.schema.json": (
            skills_root / "socratic" / "references" / "interpretation.schema.json"
        ),
        "intent-contract.schema.json": (
            skills_root / "elenchus" / "references" / "intent-contract.schema.json"
        ),
        "mutation-result.schema.json": (
            skills_root / "elenchus" / "references" / "mutation-result.schema.json"
        ),
        "mutation-report.schema.json": (
            skills_root / "elenchus" / "references" / "mutation-report.schema.json"
        ),
        "mutation-report-draft.schema.json": (
            skills_root / "socratic" / "references" / "mutation-report-draft.schema.json"
        ),
        "review-analysis.schema.json": (
            skills_root / "socratic" / "references" / "review-analysis.schema.json"
        ),
        "test-handoff.schema.json": (
            skills_root / "elenchus" / "references" / "test-handoff.schema.json"
        ),
        "canonical-review.schema.json": (
            skills_root / "socratic" / "references" / "canonical-review.schema.json"
        ),
    }


def validate_document(
    document: dict[str, Any],
    schema_name: str,
    schema_root: Path | None = None,
) -> None:
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
    except ImportError as error:
        raise ArtifactError("jsonschema and referencing are required for artifact validation") from error
    if schema_name not in ARTIFACT_SCHEMAS:
        raise ArtifactError(f"unknown artifact schema: {schema_name}")
    paths = _schema_paths(schema_root)
    schemas = {name: load_strict_json(paths[name]) for name in ARTIFACT_SCHEMAS}
    registry = Registry().with_resources(
        [(name, Resource.from_contents(schema)) for name, schema in schemas.items()]
    )
    validator = Draft202012Validator(schemas[schema_name], registry=registry)
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        detail = "; ".join(error.message for error in errors)
        raise ArtifactError(f"{schema_name} validation failed: {detail}")


def validate_with_schemas(
    contract: dict[str, Any],
    report: dict[str, Any],
    review: dict[str, Any],
    schema_root: Path | None = None,
) -> None:
    for name, document in (
        ("intent-contract.schema.json", contract),
        ("mutation-report.schema.json", report),
        ("canonical-review.schema.json", review),
    ):
        validate_document(document, name, schema_root)
    validate_cross_artifact(contract, report, review)
    rendered = render_review(review)
    canonical_output = report.get("canonical_output", {})
    rendered_hash = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    if canonical_output.get("sha256") != rendered_hash:
        raise ArtifactError("canonical output hash does not match renderer stdout")


def render_review(review: dict[str, Any]) -> str:
    lines: list[str] = []
    sections = (
        ("Review This", review["review_this"]),
        ("We Verified", review["we_verified"]),
        ("Still at Risk", review["still_at_risk"]),
    )
    for title, items in sections:
        lines.append(f"{title}:")
        if title == "Review This":
            lines.extend(f"- {item['body']}" for item in items)
        else:
            lines.extend(f"- {item}" for item in items)
        if not items:
            lines.append("- None")
        lines.append("")

    lines.append("Copy-ready Comments:")
    comments = review["copy_ready_comments"]
    if not comments:
        lines.append("- None")
    for index, comment in enumerate(comments, 1):
        lines.extend(
            (
                f"{index}. [{comment['tag']}] {comment['file']}:{comment['line']}",
                f"   {comment['body']}",
                f"   Evidence: {comment['evidence']}",
            )
        )
    return "\n".join(lines) + "\n"


def render_artifact_json(artifact: dict[str, Any]) -> str:
    """Render an already validated artifact without translating or summarizing it."""
    encoded = json.dumps(artifact, indent=2, ensure_ascii=False, sort_keys=True)
    return f"```json\n{encoded}\n```\n"


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    print(
        "ERROR: direct rendering is disabled; use socratic/scripts/run_review.py complete "
        "with a valid preflight manifest and guarded mutation ledger",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
