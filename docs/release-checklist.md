# Release Checklist

CI validates the repository, distribution, and installation mechanically on Ubuntu with Python 3.12. The items below are the release conditions CI cannot prove: live Host integration on each supported surface. Record the result of each item per release — an automated run where possible, otherwise a dated, signed manual verification note attached to the release.

## Per-Host fresh-install E2E

For each of Claude Code (Marketplace), Codex (Plugin), and local Cursor Desktop (local Plugin):

1. **Fresh install** from the published release artifact on a machine without a previous installation.
2. **First-run runtime bootstrap** — the Plugin-managed Python runtime resolves `jsonschema`/`referencing` (or a pre-provisioned managed runtime is detected) and a missing runtime fails closed before the agent runs.
3. **Normal completion** — a full Review-only run on a non-sensitive repository: preflight → runbook → contract → prepare → probe → challenge-batch → analysis → `complete`, ending with the four-block surface and cleanup.
4. **Host-unavailable fail-closed** — invoking without the trusted Host capability stops with the blocked sequence and runs nothing.
5. **Broker death recovery** — killing the broker mid-session produces a diagnosable `broker.log`, and the next explicit invocation recycles the session instead of blocking until the idle TTL.
6. **Stop / cleanup** — ending the session removes the session directory, socket, and logs unless a run manifest is mid-decision.
7. **PR retarget** — selecting a different PR mid-session terminates the old run and materializes the new target.
8. **Quoted mention does not arm** — a prompt that merely quotes `$socratic`/`$maieutic`/`$elenchus` (inline code, fenced block, pasted report) neither starts the broker nor arms the tool gate.
9. **Write-bypass denials** — during an active run, representative denied operations stay denied: direct Primary writes, `git archive -o`, a planted `run_review.py` outside the Plugin, an unrecognized (MCP) write tool, and backgrounded Runner commands.

## Cross-cutting release conditions

- All tests green with `ResourceWarning` escalated to errors; no child processes remain after the suite.
- At least three complete baseline → mutation → `complete` → cleanup runs against real external repositories, recorded with their run evidence.
- `VERSION`, [CHANGELOG](../CHANGELOG.md), and migration notes updated in the same pull request as the release bump.
- Documentation surfaces (README, site, enterprise guide) name the same invocation command and the released version.
