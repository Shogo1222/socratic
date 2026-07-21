---
name: socratic
description: Orchestrate the complete human-confirmed intent-testing workflow by using Maieutic to expose uncertainty, confirm intent, and complete tests, then using Elenchus to challenge those tests with risk-directed mutations and loop survivors back into clarification. Use for end-to-end review and hardening of pull requests, local diffs, or AI-generated changes, or requests such as「変更の意図確認からMutation検証までやって」「人間の判断だけ聞いてテストを強化して」「Socraticワークフローを実行して」.
---

# Socratic

Orchestrate a full cycle of inquiry and refutation. Use Maieutic to discover and confirm the contract, then Elenchus to challenge whether tests defend it. Keep human attention on unresolved specification and important design decisions.

## Required skills

Use both sibling skills:

- `$maieutic` for intent elicitation, Intent Contract persistence, QA review, and focused test completion;
- `$elenchus` for Catch or Harden Mode mutation validation.

If either skill is unavailable, identify the missing skill and stop before its stage. Do not silently approximate its safety-critical workflow.

## Operating rules

- Treat Socratic as the orchestrator, not a third source of specification.
- Preserve Maieutic's decision boundary: ask only questions that change an important observable oracle or side effect.
- Preserve Elenchus's isolation boundary: never leave a production mutation in the primary workspace.
- Pass persisted artifacts between stages; do not rely on conversational recollection when a contract or report exists.
- Never reinterpret a confirmed decision merely to make tests or mutations pass.
- Batch independent human decisions into the smallest useful set, normally one to three questions.

## Workflow

### 1. Establish scope

Identify the diff, base and head revisions, repository instructions, affected behavior, focused test command, and risk partitions. State any excluded partition. Choose the branch:

- use the standard hardening branch for an ordinary end-to-end request;
- use the catching branch when the user asks whether a proposed change introduced risky behavior before intent is fully confirmed.

### 2. Run Maieutic

Apply `$maieutic` to the scoped change. Require it to:

1. separate observed behavior, inferred intent, confirmed intent, and unresolved intent;
2. ask only justified human decisions;
3. persist and validate `.socratic/intent-contract.json`, or a non-overwriting change-specific path;
4. review and complete focused tests only for confirmed expectations;
5. return the contract path, status, changed files, test command, results, and risk ranking.

If relevant items remain `needs-decision`, pause those items. Continue only independent confirmed work. Do not start Harden Mode for an unresolved oracle.

### 3. Run Elenchus

Apply `$elenchus` with the exact contract path and Maieutic handoff.

For the standard branch, use Harden Mode only when challenged items are `confirmed` or `tested`. For the catching branch, allow Catch Mode with a `provisional` or `needs-decision` contract when parent and proposed revisions are identified.

Require isolated execution, a stable baseline, one attributable mutant at a time, explicit `not_challenged` items, and postflight proof that no production mutation remains.

### 4. Loop on discoveries

Route findings by type:

- missing or weak test with confirmed oracle: let Elenchus add and prove the focused test;
- missing invariant or ambiguous oracle: return it to Maieutic as a concrete behavior question;
- intended Catch Mode behavior change: record `false-positive` and update the contract when useful;
- unintended Catch Mode behavior change: record `strong-catch` and report it without changing production code unless separately authorized;
- invalid, equivalent, timeout, flaky, or infrastructure result: retain the classification and evidence; never convert it into a behavioral kill.

After a new human decision, update and validate the Intent Contract before resuming Elenchus. Re-run only affected mutants unless broader regression risk justifies more.

### 5. Complete the cycle

Finish when:

1. required decisions are confirmed or explicitly unresolved;
2. mapped original-code tests pass;
3. selected high-risk mutants are killed or honestly classified otherwise;
4. unchallenged Contract IDs and residual risks are explicit;
5. the primary workspace is mutation-free;
6. the persisted contract and Elenchus report reflect the final state.

Do not equate mutation score, test count, or exhausted budget with confidence.

## Final report

Lead with the human review surface. Report:

- decisions still needed and important design choices;
- confirmed intent and protected Contract IDs;
- tests added or changed and original-code results;
- Catch or Harden classifications and bidirectional proof;
- unchallenged scope, residual risk, and execution blockers;
- Intent Contract and Elenchus report paths;
- postflight mutation-removal evidence.

If no human decision remains, say so explicitly.
