#!/usr/bin/env python3
"""Validate Socratic run artifacts and render exactly the canonical four blocks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class ArtifactError(ValueError):
    """Raised when run artifacts cannot safely be treated as complete."""


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


def validate_cross_artifact(contract: dict[str, Any], report: dict[str, Any]) -> None:
    known = _contract_ids(contract)
    unresolved = {item["id"] for item in contract.get("unresolved", [])}
    errors: list[str] = []

    for mutation in report.get("mutations", []):
        missing = sorted(set(mutation.get("contract_ids", [])) - known)
        if missing:
            errors.append(f"{mutation.get('id', '<unknown>')} references unknown Contract IDs: {missing}")

    report_unresolved = set(report.get("unresolved", []))
    if report_unresolved - unresolved:
        errors.append(
            f"report references unknown unresolved IDs: {sorted(report_unresolved - unresolved)}"
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

    if errors:
        raise ArtifactError("; ".join(errors))


def validate_with_schemas(
    contract: dict[str, Any],
    report: dict[str, Any],
    review: dict[str, Any],
    schema_root: Path | None = None,
) -> None:
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
    except ImportError as error:
        raise ArtifactError("jsonschema and referencing are required for artifact validation") from error

    schema_names = (
        "intent-contract.schema.json",
        "mutation-result.schema.json",
        "mutation-report.schema.json",
        "test-handoff.schema.json",
        "canonical-review.schema.json",
    )
    if schema_root is not None:
        schema_paths = {name: schema_root / name for name in schema_names}
    else:
        skills_root = Path(__file__).resolve().parents[2]
        schema_paths = {
            "intent-contract.schema.json": skills_root / "elenchus" / "references" / "intent-contract.schema.json",
            "mutation-result.schema.json": skills_root / "elenchus" / "references" / "mutation-result.schema.json",
            "mutation-report.schema.json": skills_root / "elenchus" / "references" / "mutation-report.schema.json",
            "test-handoff.schema.json": skills_root / "elenchus" / "references" / "test-handoff.schema.json",
            "canonical-review.schema.json": skills_root / "socratic" / "references" / "canonical-review.schema.json",
        }
    schemas = {name: load_strict_json(schema_paths[name]) for name in schema_names}
    registry = Registry().with_resources(
        [(name, Resource.from_contents(schema)) for name, schema in schemas.items()]
    )
    for name, document in (
        ("intent-contract.schema.json", contract),
        ("mutation-report.schema.json", report),
        ("canonical-review.schema.json", review),
    ):
        validator = Draft202012Validator(schemas[name], registry=registry)
        errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
        if errors:
            detail = "; ".join(error.message for error in errors)
            raise ArtifactError(f"{name} validation failed: {detail}")
    validate_cross_artifact(contract, report)


def render_review(review: dict[str, Any]) -> str:
    lines: list[str] = []
    sections = (
        ("Review This", review["review_this"]),
        ("We Verified", review["we_verified"]),
        ("Still at Risk", review["still_at_risk"]),
    )
    for title, items in sections:
        lines.append(f"{title}:")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--schema-root", type=Path)
    args = parser.parse_args()

    try:
        contract = load_strict_json(args.contract)
        report = load_strict_json(args.report)
        review = load_strict_json(args.review)
        validate_with_schemas(contract, report, review, args.schema_root)
    except ArtifactError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    sys.stdout.write(render_review(review))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
