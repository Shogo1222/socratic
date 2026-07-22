English | [日本語](ja/protocol.md)

# Intent Testing Protocol

## Purpose

The protocol keeps specification evidence separate from code behavior and makes the Maieutic-to-Elenchus handoff, orchestrated by Socratic, persistent and auditable.

## Run artifacts

Run artifacts are chat-first and ephemeral by default. During a run, the Intent Contract and the Catch or Harden report are temporary artifacts outside the repository working tree, validated against schemas bundled with the installed skills and handed between stages by path. A conversation-only contract is a fallback, not the normal handoff.

When Review-only proves a missing test, Elenchus also creates a temporary proven-test handoff outside the working tree: a test-only patch plus a validated manifest. The handoff remains available only until the user chooses Apply tests, Output patch, or Discard. It is not a substitute for persistent tests.

After the final surface is rendered, proven tests are resolved first through a structured Apply tests / Output patch / Discard question. The separate run-artifact question then offers discard (default), save locally, or output as Markdown. When saved locally, the canonical paths are:

- `.socratic/intent-contract.json`: active Intent Contract produced by Maieutic;
- `.socratic/elenchus-report.json`: latest Catch or Harden report produced by Elenchus.

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

An unresolved item cannot advance to `TESTED`. Passing implementation behavior is not confirmation. Budget exhaustion is not `HARDENED` unless unchallenged items and residual risk are explicitly accepted. `TESTED` and `HARDENED` also require tests that persist beyond the run — pre-existing tests or tests applied to the working tree; a Review-only run whose proof rests on proposed tests stops at `CONFIRMED` or `CHALLENGED`.

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

### Mutation Result, Report, and Test Handoff

[mutation-result.schema.json](../schemas/mutation-result.schema.json) represents one intent mutation from candidate design through execution, including Assessment and Catch classifications. [test-handoff.schema.json](../schemas/test-handoff.schema.json) represents an exact proven test patch, its file-hash preconditions and postimages, Contract mappings, and bidirectional proof. [mutation-report.schema.json](../schemas/mutation-report.schema.json) wraps the run with the write mode, baseline evidence, Test Assessment scope and cohort comparisons, unchallenged Contract IDs, unresolved decisions, test changes and handoff status, authorized workspace changes, and postflight mutation-removal proof.

## Human decision boundary

Escalate a question only when:

1. multiple reasonable expectations remain;
2. reviewed repository evidence cannot resolve them;
3. the answer changes an observable oracle or important side effect;
4. a wrong guess has meaningful cost.

Present the smallest concrete behavior delta or explicit options. Ranking considers severity, confidence, and human dismissal cost. If no answer arrives, persist `needs-decision`, continue independent confirmed work only, and never invent an answer.

Decisions are presented through the host's structured question tool when available — `AskUserQuestion` on Claude Code, `request_user_input` on Codex — and as copyable Markdown otherwise. A batch is one to three questions, each with two or three mutually exclusive options, a one-sentence observable consequence per option, a free-form alternative, and the oracle the answer changes. Only the main agent asks; subagents investigate, test, and mutate, and return open decisions. The protocol guarantees the structured question content; rendering it belongs to the host.

## Elenchus assessment-scope boundary

A direct `$elenchus` invocation defaults to Test Assessment Mode. It discovers changed production files, related existing tests, and changed tests, then asks one structured scope question before generating mutants: current change with existing and changed tests (recommended), changed tests only, or a broader user-selected target. Socratic passes its exact scope and suppresses this duplicate question.

Assessment compares the same risk mutants against disposable existing and changed test cohorts. Report `existing-protection`, `incremental-protection`, `protection-regression`, `unprotected`, and non-comparable or inconclusive outcomes separately. Derive risks before inspecting changed assertions and include a holdout risk when practical. Without confirmed intent, a provisional assessment can prove detection of represented behavior but cannot prove that behavior is correct.

Standalone assessment is Review-only and does not create tests by default. Hardening a surviving gap requires a separate request and confirmed intent; applying the resulting test requires another explicit authorization.

## Review output boundary

The reviewer-facing surface is exactly four blocks: Review This, We Verified, Still at Risk, and Copy-ready Comments. Findings route by state, not type: unconfirmed behavior differences and unresolved decisions are Review This; confirmed intended changes, applied or proposed-and-proven tests, resolved test gaps, and proven detection are We Verified; everything unverified is Still at Risk. A resolution that rests on a proposed test also appears under Still at Risk as protection not applied yet. This four-block surface governs Socratic-orchestrated review output; a standalone Test Assessment run uses the assessment surface defined under the Elenchus assessment-scope boundary.

The operational proven-test choice appears after those four blocks through the host's structured question UI, not as a fifth review block.

Comment candidates are at most one to three, tagged `Intent decision`, `Behavior difference`, or `Test gap`, anchored to file and line. The answerer of an `Intent decision` is the specification owner; an AI code author is neither specification evidence nor an answerer. Skills never post to a code host and never report merge readiness, a confidence level, or an overall score — the merge decision stays with the reviewer. Details such as the contract, mutation results, test strategy, and executed commands live in the run artifacts.

## Write-mode boundary

Review-only is the default: probes, comparison tests, and mutations exist only in disposable environments, the working tree is untouched, and proven missing tests are reported as proposals. Apply tests requires an explicit user request and adds only tests that encode confirmed intent. Version-control operations remain prohibited in both modes.

Before disposing a sandbox that contains a proven proposed test, export a test-only patch and validate its handoff manifest. Apply tests verifies the patch hash, production and test precondition hashes, confirmed Contract mappings, and test-file postimages. A mismatch makes the handoff stale; regenerate and repeat the original-pass / mutant-fail proof instead of forcing it. Missing or previously discarded handoffs are regenerated, never described as reused.

After successful application, update the Contract and report to applied state and render the canonical four-block surface again. The preceding Review-only surface provided context for the disposition choice; it is not the terminal Apply tests result.

Test disposition is relative to preflight at the start of the Socratic run, not to the surrounding conversation or Git history. A test present at preflight is `existing` even if an earlier request in the same conversation created it; a disposable-only test is `proposed`; only a test written to the primary workspace by this explicitly authorized run is `applied`. Reviewer-facing text must verbalize those states as **existing at run start**, **proposed and proven in disposable workspace**, or **applied by this run after explicit request**. A matching Review-only postflight is reported as **Working tree unchanged during this Review-only run**.

## Oracle selection boundary

Classify dependencies before choosing oracles: in-process dependencies are verified through the client-observable final result; managed out-of-process state through its actual final state; unmanaged out-of-process dependencies through message content and count at the application boundary. Prefer output values, then observable final state, then boundary communication.

Implementation details — internal call order and counts, intermediate state, freely replaceable algorithms — are never oracles. A probe coupled to them produces false positives and must not be reported as a behavior difference, and a mutation that preserves client-observable behavior must not be forced into detection.

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

Review-only mutation execution has one normative Host Adapter entrypoint in `skills/socratic/scripts/run_review.py`. The standalone CLI is intentionally blocked and cannot accept self-asserted attestation JSON. A trusted host issues the run ID, nonce, protected external storage, and repository-wide protection capability. Baseline and mutation-specific `execute` events join guarded mutation evidence in a nonce-bound append-only chain, and `finish` requires each reported Mutation ID to have both write/registration and execution evidence. Helper omission, Primary mutation followed by restoration, hand-written artifacts, and renderer-like prose are not valid protocol implementations.

All production mutations live only in disposable workspaces marked with `.socratic-disposable`. Every mutation write passes through the bundled Isolation Gate immediately before the write; backup and restore is not isolation. The primary workspace may receive authorized test or documentation changes, never temporary production mutations. Reports record run-time primary writes separately from final hash equality, and no compile or infrastructure failure counts as a behavioral kill or catch.

## Version-control safety boundary

Skills may use only allowlisted, read-only local Git commands to inspect evidence and export immutable Base and Head snapshots. They never stage, commit, amend, push, pull, fetch, create or switch branches, check out files, reset, stash, merge, rebase, cherry-pick, tag, create worktrees, invoke `gh`, create pull requests, or post comments. They do not request permission for prohibited operations; every version-control decision remains with the user.

Base and Head are snapshot identities, not branches the skill manages. Materialize them as host-provided directories or disposable filesystem snapshots. If a required object is unavailable locally and would require a remote operation, mark the comparison blocked. Mutation safety uses scoped filesystem manifests and content hashes, not Git restoration.
