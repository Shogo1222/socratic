# Mutation Safety Contract

Treat every mutation as destructive temporary state.

## Non-negotiable rules

- Never apply a mutation directly to the primary working tree.
- Capture primary status and diff before execution and compare them afterward.
- Use a fresh disposable workspace for each mutant.
- Preserve the exact code-under-test state, including authorized uncommitted changes.
- Run one mutant at a time.
- Bound builds and tests with timeouts.
- Do not run production deployment, migration, destructive integration, or live-service commands.
- Assume tests may have external side effects; inspect repository instructions and test configuration first.
- Remove or abandon all disposable mutant state on success, failure, timeout, and interruption.
- Never report completion without verifying that no production mutation remains.

## Isolation selection

Prefer, in order:

1. a temporary Git worktree at an immutable revision when the target state is committed;
2. a temporary worktree plus an explicitly captured patch for authorized uncommitted changes;
3. a temporary filesystem copy that excludes repository metadata, caches, secrets, and dependencies that should not be duplicated;
4. a framework-native mutation sandbox with documented restoration guarantees.

Do not use stash, reset, checkout restoration, or broad deletion as the primary safety mechanism. Those operations can overwrite user work.

## Preflight evidence

Record:

- primary repository path;
- revision and target diff;
- concise working-tree status;
- hash or saved representation of the production diff;
- sandbox path;
- focused test command and timeout;
- relevant environment isolation.

## Postflight evidence

Verify:

- primary status and production diff match the preflight state except for authorized test changes;
- no mutation marker or mutant patch exists in production files;
- disposable workspaces are removed or clearly reported if cleanup was blocked;
- original code passes the relevant tests.

If any verification fails, stop and report the exact paths and differences. Do not attempt destructive recovery without explicit authorization.
