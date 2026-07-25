# Runner Test Profiles

A Test Profile is the typed boundary between test selection and execution: the agent chooses what to run in semantic terms, and the deterministic Runner owns the exact command. The v0.5 canonical pipeline realizes this boundary as one probed focused command; the v0.4 prototype realized it as a typed `python-unittest` selection and is retained below as the experimental narrow-runner record.

## Canonical profile: the probed focused command

The canonical Runner does not parse framework-specific selections; it types the boundary around one validated command. The agent locates the direct test executable in the prepared snapshot with `inspect search` and submits it once to `probe-command` with a sandbox-relative working directory:

```text
<trusted-python> run_review.py probe-command \
  --manifest <host-manifest> \
  --command-id CMD-001 \
  --cwd <package-directory-or-dot> \
  -- <direct-test-executable> <focused-test-arguments>
```

In a hoisted workspace this is typically `../../node_modules/.bin/vitest run <test file>` with `--cwd packages/<package>`. The Runner executes the argv in a fresh clone of the prepared snapshot, and only a passing run records the command ID: `CMD-001` binds the exact argv, working directory, and timeout. The challenge plan names that command ID, and `challenge-batch` reuses the recorded argv and cwd verbatim for every mutant — the plan cannot supply per-mutant argv, so every mutation is measured by the same validated command.

Probe the direct test executable, never a package-manager wrapper such as `pnpm exec` or `npm run`: wrappers may re-resolve workspace paths or reinstall dependencies in clones, while the direct binary runs immediately against the sealed shared dependency layer. Sandbox commands use the project's own toolchain by absolute path; the injected runtime Python exists only for `run_review.py`.

A probe that does not pass returns `blocked` with bounded stdout and stderr tails, an environment `hint` when the Runner recognizes the cause, and two exact follow-ups: `diagnose.argv` for the read-only `doctor` report and `next.argv` to rerun the corrected probe. `scaffold-plan` is reachable only after a validated command ID exists.

## Prototype profile: `python-unittest`

The v0.4 narrow-runner experiment types the boundary as a selection structure instead of a command. Agents select semantic test identities; they never supply argv.

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

The Runner internally executes:

```text
<trusted-python> -B -m unittest -v <derived-test-ids>
```

Invoke the prototype through the existing guarded entrypoint:

```text
<trusted-python> run_review.py assess \
  --source-root <host-review-root> \
  --plan <host-artifact-root>/experiment-plan.json \
  --evidence <host-artifact-root>/evidence-bundle.json
```

Set Source and target preimage identities to `runner-computed` for the normal one-call path. The Runner writes Evidence create-once; the agent must not create or edit `evidence-bundle.json`.

The injected Python must pass the isolated runtime dependency probe. A user-site installation that disappears with sanitized `HOME` is not accepted as a trusted runtime. When the probe fails, inspect `runtime.missing_dependencies` and `baseline.reason`; do not interpret the result as a failed behavioral test.

## Later profiles

The canonical path already covers additional frameworks by probing their direct executables, so pytest and Node projects need no prototype-style selection schema there. Extending the narrow-runner experiment itself still requires its own typed selection schemas and parsers; do not emulate them through a custom argv field. A custom prototype profile is permitted only after a Host-mediated human approval protocol and signed Profile digest exist.
