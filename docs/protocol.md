English | [日本語](ja/protocol.md)

# Intent Testing Protocol

## Purpose

The protocol keeps specification evidence separate from code behavior and makes the Maieutic-to-Elenchus handoff, orchestrated by Socratic, persistent and auditable.

## Persistent artifacts

- `.socratic/intent-contract.json`: active Intent Contract produced by Maieutic;
- `.socratic/elenchus-report.json`: latest Catch or Harden report produced by Elenchus.

Both artifacts are validated against schemas bundled with the installed skills. A conversation-only contract is a fallback, not the normal handoff.

## Main lifecycle

```text
PROVISIONAL
  Diff and repository evidence produce an intent hypothesis.

NEEDS_DECISION
  Multiple plausible expectations create different test oracles.

CONFIRMED
  A responsible human or authoritative source resolves required oracles.

TESTED
  Stable tests protect confirmed decisions and invariants.

CHALLENGED
  Risk-directed mutations have been executed against stable tests.

HARDENED
  Selected high-risk mutants are killed and unchallenged risk is explicit.
```

An unresolved item cannot advance to `TESTED`. Passing implementation behavior is not confirmation. Budget exhaustion is not `HARDENED` unless unchallenged items and residual risk are explicitly accepted.

## Catch branch

Catch Mode branches from `PROVISIONAL` or `NEEDS_DECISION`:

```text
Parent-pass + mutant-fail candidate test
  -> run on proposed diff
  -> behaviorally fails: WEAK_CATCH
  -> human says unintended: STRONG_CATCH
  -> human says intended: FALSE_POSITIVE
  -> no answer: NEEDS_DECISION
```

A test that does not build or run comparably on parent and diff is `not-comparable`, not a weak catch. Infrastructure, flaky, missing-symbol, and unrelated failures are inconclusive.

## Core records

### Intent Contract

The normative machine-readable shape is [intent-contract.schema.json](../schemas/intent-contract.schema.json). It contains the change boundary, lifecycle status, observable intent and evidence, confirmed decisions and provenance, invariants, side effects, unresolved decisions, and test mappings.

Decision provenance has two values only:

- `user-confirmed`;
- `repository-established`.

Unconfirmed reasoning belongs in `intent.evidence`. Unresolved oracle choices belong in `unresolved`.

### Mutation Result and Report

[mutation-result.schema.json](../schemas/mutation-result.schema.json) represents one intent mutation from candidate design through execution, including Catch classifications. [mutation-report.schema.json](../schemas/mutation-report.schema.json) wraps the run with baseline evidence, unchallenged Contract IDs, unresolved decisions, added tests, and postflight mutation-removal proof.

## Human decision boundary

Escalate a question only when:

1. multiple reasonable expectations remain;
2. reviewed repository evidence cannot resolve them;
3. the answer changes an observable oracle or important side effect;
4. a wrong guess has meaningful cost.

Present the smallest concrete behavior delta or explicit options. Ranking considers severity, confidence, and human dismissal cost. If no answer arrives, persist `needs-decision`, continue independent confirmed work only, and never invent an answer.

## Evidence boundary

Pre-existing tests can establish an oracle only when they predate the diff, remain untouched, are stable, and pass Maieutic's QA review. Changed, weak, flaky, contradictory, or implementation-coupled tests support inference only. Current implementation remains the lowest-precedence evidence.

## Mutation boundary

Generate mutations in this order:

1. plausible misunderstanding of confirmed or provisional intent;
2. omission or corruption of a Contract-relevant side effect;
3. state, authorization, time, collection, or failure-policy deviation;
4. traditional syntactic mutation that realizes a specific risk.

Require evidence for `equivalent`. Observable behavior missing from the Contract becomes a missing-invariant candidate for Maieutic. Mutation count and score remain diagnostics.

## Baseline and scope boundary

Mutation classification requires stable green tests. Rerun a failure once, stop on a repeatable red baseline, and exclude flaky tests only when a stable subset still observes the Contract. Report all reduced scope.

Partition large changes by observable behavior or risk domain. Every Contract ID omitted because of budget, observability, applicability, or a blocker appears under `not_challenged` with residual risk.

When unit tests cannot observe an artifact, use the narrowest deterministic repository-supported validation and state that the item is not unit-tested.

## Safety boundary

All production mutations live only in disposable workspaces. The primary workspace may receive authorized test or documentation changes, never temporary production mutations. Preflight and postflight evidence is required, and no compile or infrastructure failure counts as a behavioral kill or catch.
