#!/usr/bin/env python3
"""Validate repository JSON fixtures against the normative schemas in schemas/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FIXTURES = {
    "fixtures/subscription-renewal-intent-contract.json": "intent-contract.schema.json",
    "fixtures/subscription-renewal-expected-elenchus-report.json": "mutation-report.schema.json",
    "fixtures/subscription-renewal-canonical-review.json": "canonical-review.schema.json",
}

EXPECTED_REPORT_MODES = {
    "fixtures/subscription-renewal-expected-elenchus-report.json": "harden",
}


def main() -> int:
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
    except ImportError:
        print(
            "ERROR: jsonschema and referencing are required: "
            "python3 -m pip install jsonschema referencing",
            file=sys.stderr,
        )
        return 1

    schemas = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in (ROOT / "schemas").glob("*.schema.json")
    }
    for name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources(
        [(name, Resource.from_contents(schema)) for name, schema in schemas.items()]
    )

    failures = 0
    for fixture, schema_name in sorted(FIXTURES.items()):
        document = json.loads((ROOT / fixture).read_text(encoding="utf-8"))
        validator = Draft202012Validator(schemas[schema_name], registry=registry)
        errors = [error.message for error in validator.iter_errors(document)]

        expected_mode = EXPECTED_REPORT_MODES.get(fixture)
        if expected_mode is not None and document.get("mode") != expected_mode:
            errors.append(f"mode is {document.get('mode')!r}, expected {expected_mode!r}")

        if errors:
            failures += 1
            for message in errors:
                print(f"ERROR: {fixture}: {message}", file=sys.stderr)

    if failures:
        return 1

    print(
        f"Fixture validation passed: {len(FIXTURES)} fixtures validated against the normative schemas"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
