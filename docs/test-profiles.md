# Narrow Runner Test Profiles

Test Profiles convert typed selections into deterministic Runner commands. Agents select semantic test identities; they never supply argv.

## Prototype profile: `python-unittest`

Dependency policy:

```json
{ "mode": "use-existing" }
```

Selection:

```json
{
  "modules": ["tests.runner.test_run_review"],
  "classes": ["RunReviewTest"],
  "methods": ["test_execute_records_timeout_before_failing"]
}
```

The Runner validates Python identifiers, resolves methods only within the selected modules and classes, and builds argv internally. Empty class and method arrays mean all tests inside the selected modules. Test execution has no network preparation step.

The profile parser returns full unittest test IDs when available. If output cannot be parsed, Evidence records `failed_tests: null` and retains bounded stdout/stderr tails with full hashes.

## Later profiles

Pytest and Node profiles require their own typed selection schemas and parsers. Do not emulate them through a custom argv field. A custom profile is permitted only after a Host-mediated human approval protocol and signed Profile digest exist.
