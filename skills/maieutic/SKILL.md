---
name: maieutic
description: Analyze a code change, expose what is not yet known, draw intended behavior from repository evidence and low-friction human questions, persist an Intent Contract, review unit tests with risk-appropriate QA techniques, add missing tests, and run them without treating implementation as specification. Use for pull requests, local diffs, AI-generated changes, regression-risk reviews, intent clarification, test-plan reviews, or requests such as「diffから意図を引き出して」「人間が判断すべき点だけ聞いて」「不足テストを追加して」.
---

# Maieutic

Turn a code diff into a small set of human decisions and a persistent, executable unit-test contract. Treat code as evidence of intent, never as the final specification.

## Required references

Read [references/intent-contract.md](references/intent-contract.md) before recording decisions. Validate persisted contracts with [references/intent-contract.schema.json](references/intent-contract.schema.json). Read [references/qa-techniques.md](references/qa-techniques.md) when selecting test cases.

## Operating rules

- Ask only when different reasonable answers change an observable expectation or important side effect.
- Do not ask for facts discoverable from repository instructions, issues, authoritative documentation, call sites, history, or reviewed evidence.
- Distinguish observed behavior, inferred intent, confirmed intent, and unresolved intent.
- Prefer a concrete behavior comparison over an abstract specification question.
- Optimize for human review cost as well as risk. Make each question quick to answer.
- Do not change production behavior to make a test pass unless the user separately authorizes a fix.
- Add tests only for confirmed expectations. Never freeze a suspected bug into a regression test.

## Workflow

### 1. Establish the change boundary

Identify the target diff and base revision from the current branch or user request. Read repository instructions and determine the test framework and focused test command. Inspect:

- changed production and test files;
- nearby call sites and domain types;
- existing tests for the changed behavior;
- issue, pull-request, commit, and documentation context when available.

If the base is ambiguous, state a low-risk assumption rather than asking. For a large diff, partition work by independently observable behavior or risk domain, rank the partitions, and state which partitions are in and out of the current review budget.

If no tests exist, use an already configured or language-standard framework when the choice is unambiguous. Otherwise report the missing test infrastructure and request authorization before adding a framework or dependency.

### 2. Build a behavior model

Summarize:

1. what observably changed;
2. the likely intent and its evidence;
3. affected inputs, outputs, state transitions, exceptions, and side effects;
4. plausible regressions;
5. unresolved expectations.

Do not merely paraphrase edited lines. Describe behavior before and after the change.

### 3. Decide whether a human question is justified

Ask only when all are true:

1. at least two plausible expectations remain;
2. repository evidence does not resolve them;
3. the answer changes a test oracle, compatibility rule, or high-impact side effect;
4. guessing incorrectly has meaningful cost.

Do not ask about naming, formatting, implementation strategy, or low-impact details unless they alter the external contract. Ask the smallest useful batch, normally one to three related decisions.

Use the template that fits:

```text
Behavior change:
  Previously: <observable behavior>
  With this change: <observable behavior>
  Is this change expected?

Choice:
  Decision: <question>
  Option A: <observable expectation and test impact>
  Option B: <observable expectation and test impact>

New behavior:
  Proposed behavior: <observable behavior with no predecessor>
  Decision needed: <boundary, failure policy, or side-effect choice>
  Test impact: <how the answer changes the oracle>
```

Always add one sentence explaining why a human decision is needed.

### 4. Persist the Intent Contract

Create the contract described in `references/intent-contract.md`. Give every decision and invariant a stable ID. Route information exactly as follows:

- use decision `provenance: user-confirmed` for explicit answers;
- use decision `provenance: repository-established` only for authoritative repository evidence;
- place unconfirmed inferences in `intent.evidence`, never in `decisions`;
- place unresolved oracle choices in `unresolved`, never in `decisions`.

Persist the active contract by default at `.socratic/intent-contract.json` and validate it with the bundled schema. Update it after every confirmed decision and report its path. If that file describes a different change, do not overwrite it; write `.socratic/contracts/<change-id>.json` and explicitly hand that path to Elenchus.

Set `status` to `needs-decision` while relevant unresolved items remain, `confirmed` when required decisions are resolved, and `tested` after mapped tests pass.

If a required question receives no answer, persist it as unresolved and stop that behavior at `needs-decision`. Continue only independent confirmed items. In non-interactive execution, report the required decisions once and exit without polling or inventing answers.

### 5. Review existing unit tests

Map existing tests to decisions and invariants. Select only relevant QA techniques from `references/qa-techniques.md`. Check both result assertions and prohibited side effects.

Treat existing tests as specification evidence only when they predate the diff, are untouched by it, and pass this quality review. Edited, weak, contradictory, flaky, or implementation-coupled tests may support an inference but cannot establish an oracle.

Classify each gap as:

- missing scenario;
- weak or absent assertion;
- wrong boundary;
- missing state or side-effect observation;
- implementation-coupled test;
- ambiguous specification.

Report ambiguity before writing a test. Avoid tests that only increase coverage without protecting a decision or invariant.

If the changed artifact cannot be meaningfully observed with a unit test, use the narrowest deterministic alternative already supported by the repository, such as schema validation, parser checks, migration dry runs, snapshots, or focused integration tests. Report that the item is not unit-tested; do not force it into a unit-test claim.

### 6. Add focused tests

When required expectations are confirmed, add the smallest maintainable unit tests that close material gaps. Follow existing conventions. Prefer one behavioral reason for failure per test and names tied to the contract rather than implementation details.

Do not mock the unit under test. Mock external collaborators only as needed to observe contract-relevant interactions.

### 7. Verify and report

Run the narrowest relevant tests first, then the broader unit-test suite when practical. Update the persisted contract coverage and status. Report:

- change and inferred intent;
- decisions requested and answers received;
- Intent Contract path and status;
- Contract IDs covered by tests;
- tests added or changed;
- unreviewed partitions, remaining risks, and unresolved items;
- commands run and results.

If tests cannot run, report the exact blocker and what remains unverified. Do not claim completion from static inspection alone.

## Handoff to Socratic or Elenchus

For Harden Mode, hand off a `confirmed` or `tested` contract path, changed files, focused test command, and risk ranking. For Catch Mode, a `provisional` or `needs-decision` contract is sufficient when the parent revision and proposed diff are identified. When running inside `$socratic`, return these artifacts to the orchestrator; otherwise hand them directly to Elenchus. Elenchus must load the persisted contract and must not reinterpret confirmed intent.
