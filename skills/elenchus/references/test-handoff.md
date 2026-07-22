# Proven Test Handoff

Create a handoff only for a test that passes on unmodified production code and fails on at least one valid mutation for the intended behavioral assertion. The handoff lets a Review-only run offer the exact proven test for later application without modifying the primary workspace.

Validate the manifest with `test-handoff.schema.json`.

## Contents

Keep both files outside the repository working tree:

- a test-only unified patch with repository-relative paths;
- a JSON manifest containing the patch hash, snapshot identity, scoped production and test precondition hashes, expected test-file postimage hashes, Contract IDs, focused test command, detecting Mutation IDs, broader-suite result, and lifecycle status.

Use `null` as a precondition hash only when a target test file did not exist. Include every production file whose behavior the proposed tests observe and every test file the patch changes. Never include production or documentation edits in the patch.

Use POSIX repository-relative paths only. Reject absolute paths, backslashes, `..` traversal, symlink targets, and any resolved path outside the primary repository before output or application.

## Disposition

After the canonical review surface, offer one structured choice for each handoff batch:

1. **Apply tests** — explicit authorization to enter Apply tests mode.
2. **Output patch** — show the patch without changing the working tree.
3. **Discard** — delete the patch and manifest.

Do not offer Apply tests while a mapped oracle is unresolved. Treat no answer as Discard. Update the manifest status to `applied`, `output`, `discarded`, or `stale` before cleanup.

## Applying a handoff

Before applying:

1. verify the patch SHA-256;
2. verify every production and test precondition against the primary workspace;
3. confirm that the patch changes test files only and still encodes confirmed intent.

If any precondition differs, do not force the patch. Mark it `stale`, then regenerate and repeat both directions of proof against the current workspace when authorized and practical. If the handoff is missing because a prior run discarded it or the process restarted, regenerate it rather than claiming to reuse it.

After applying, verify every test-file postimage hash, run the focused tests on unmodified production code, re-run the attributable mutations in disposable workspaces, run the broader relevant suite when practical, and perform the normal production-file postflight audit. Only then report the tests as applied and persistent.

Delete temporary patch and manifest files after application, output, discard, staleness, failure, timeout, or interruption. Report exact remaining paths if cleanup fails.
