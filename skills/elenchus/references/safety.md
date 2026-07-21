# Mutation Safety Contract

Treat every mutation as destructive temporary state.

## Non-negotiable rules

- Never apply a mutation directly to the primary working tree.
- Capture a scoped filesystem manifest and content hashes before execution and compare them afterward.
- Use a fresh disposable workspace for each mutant.
- Preserve the exact code-under-test state, including authorized uncommitted changes.
- Run one mutant at a time.
- Bound builds and tests with timeouts.
- Do not run production deployment, migration, destructive integration, or live-service commands.
- Assume tests may have external side effects; inspect repository instructions and test configuration first.
- Remove or abandon all disposable mutant state on success, failure, timeout, and interruption.
- Never report completion without verifying that no production mutation remains.
- Never change local or remote Git state and never request permission to do so.

## Git boundary

Local Git use is limited to read-only evidence and snapshot export through `git diff`, `git show`, `git log`, `git rev-parse`, `git merge-base`, `git ls-files`, and `git archive`.

Never run `git add`, `commit`, `amend`, `push`, `pull`, `fetch`, `checkout`, `switch`, `reset`, `stash`, `merge`, `rebase`, `cherry-pick`, `branch`, `tag`, or `worktree`. Never invoke `gh`, create a pull request, post a review comment, or call a code-host write API. If a Base or Head object is not available locally, report it as unavailable instead of fetching it.

## Isolation selection

Prefer, in order:

1. an already-materialized Base or Head directory supplied by the host or user;
2. a temporary filesystem snapshot exported from a locally available immutable object with read-only Git;
3. a temporary filesystem copy that preserves authorized working-tree changes while excluding repository metadata, caches, secrets, and dependencies that should not be duplicated;
4. a framework-native mutation sandbox with documented restoration guarantees and no Git state changes.

Do not create or switch branches or worktrees. Do not use stash, reset, checkout restoration, or broad deletion as a safety mechanism. Those operations can overwrite user work.

## Preflight evidence

Record:

- primary repository path;
- Base or Head snapshot identity and target change description;
- scoped production-file manifest and content hashes;
- sandbox path;
- focused test command and timeout;
- relevant environment isolation.

## Postflight evidence

Verify:

- the scoped primary manifest and content hashes match preflight evidence except for authorized test or documentation changes;
- no mutation marker or mutant patch exists in production files;
- disposable workspaces are removed or clearly reported if cleanup was blocked;
- original code passes the relevant tests.

If any verification fails, stop and report the exact paths and differences. Do not attempt destructive recovery without explicit authorization.
