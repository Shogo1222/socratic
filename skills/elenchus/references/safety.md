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
- Create `.socratic-disposable` in each verified sandbox root, then route every mutation write through `scripts/isolation_gate.py`'s `IsolationGate.write_bytes` or `write_text`. Never perform a separate write after using only the authorization CLI.
- Resolve and validate every target immediately before writing. A target outside the sandbox, inside the primary root, or reached through a sandbox-local symlink is a hard abort; backup and restore is never isolation.
- Resolve the primary root to the enclosing Git repository. Reject any symlink anywhere in the sandbox that resolves into that repository, including dependency and build-tool links.
- Redirect caches, temporary directories, package-manager state, and framework build output into the disposable sandbox.
- Record `primary_written_during_run: false` only with verified host read-only protection or a verified OS or host write-event monitor covering the entire repository root.

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
- resolved primary repository root, resolved sandbox root, host read-only protection mode, write-monitor mode, and every authorized mutation target.

## Postflight evidence

Verify and record separately:

- whether any primary path was written during the run;
- whether final primary hashes match preflight evidence except for authorized test or documentation changes;
- the final working-tree status, resolved mutation targets, write events, and sandbox destruction status;
- no mutation marker or mutant patch exists in production files;
- disposable workspaces are removed or clearly reported if cleanup was blocked;
- original code passes the relevant tests.

If any verification fails, stop and report the exact paths and differences. Do not attempt destructive recovery without explicit authorization.
