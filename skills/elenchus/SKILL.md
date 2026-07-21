---
name: elenchus
description: Evaluate whether tests detect plausible bugs by generating risk-ranked mutations from programming intent, applying each mutation only in an isolated workspace, analyzing catches and survivors, adding missing tests, and proving tests kill the mutation. Use for intent-aware catching, regression hardening, test-quality assessment, critical diff validation, or requests such as「ミューテーションテストして」「テストがバグを検知できるか確認して」「変更リスクを反証して」.
---

# Elenchus

Challenge a test suite with plausible misunderstandings of programming intent. Optimize for confidence in important behavior, not mutation score.

## Required references

Read [references/mutation-design.md](references/mutation-design.md) before generating mutants and [references/safety.md](references/safety.md) before changing or executing code. Validate inputs and outputs with the bundled [intent-contract.schema.json](references/intent-contract.schema.json), [mutation-result.schema.json](references/mutation-result.schema.json), and [mutation-report.schema.json](references/mutation-report.schema.json).

## Locate the Intent Contract

Load the contract in this order:

1. an explicit path supplied by the user, Maieutic, or the Socratic orchestrator;
2. `.socratic/intent-contract.json` in the repository;
3. a complete contract in the current conversation.

If none exists, stop and ask the user to run `$maieutic`, run the full `$socratic` workflow, or supply a contract. Do not reconstruct confirmed intent from implementation. Persist the final report at `.socratic/elenchus-report.json` unless the user supplies another path.

## Choose mode and preconditions

### Harden Mode — default

Require a `confirmed` or `tested` contract for every challenged oracle. Mutate confirmed intent and verify that tests kill the resulting code mutants.

### Catch Mode

Allow a `provisional` or `needs-decision` contract when both the parent revision and proposed diff are identified. Generate tests from risk mutants of the parent, then check whether the proposed diff exhibits the same risky behavior. A Catch Mode result may create decisions; it must not pretend intent was already confirmed.

For either mode, identify the exact revision, changed and high-risk locations, focused test command, isolation strategy, and baseline result. If no runnable tests exist, stop mutation execution and return to Maieutic for test-infrastructure selection; do not install a framework without authorization.

## Baseline policy

Run baselines only in a disposable workspace. If the focused baseline fails:

1. isolate the failing tests and rerun them once;
2. classify a repeatable failure as `baseline-red` and stop mutation classification;
3. classify an intermittent failure as flaky;
4. exclude flaky tests only when a stable green subset still observes the challenged contract;
5. otherwise stop as `inconclusive`.

Never use a flaky or pre-existing failure as evidence that a mutant was killed or survived. Record reduced test scope in the report.

## Catch Mode workflow

### 1. Build provisional risks

Map the proposed diff intent to provisional Contract IDs. Partition a large diff by observable behavior or risk domain. Rank severe regressions and record every out-of-budget item as `not_challenged`.

### 2. Mutate the parent

Generate a small set of intent-based mutants against the parent revision. For each mutant, state the changed intent, represented incident, code change, expected detection, and evidence that the mutant is behaviorally meaningful.

Reuse the isolation, one-mutant-at-a-time execution, timeout, restoration, and postflight rules from Harden Mode steps 3, 4, and 7, with the parent revision as the unmutated baseline.

### 3. Generate candidate catching tests

Generate or select a test that:

1. builds and passes on the unmodified parent;
2. builds and fails on the parent mutant for the intended behavioral assertion;
3. does not depend on reflection, private implementation details, or unrelated infrastructure.

A compile error, missing symbol, changed test API, test-runner failure, or unrelated exception is not a catching signal.

### 4. Run against the proposed diff

Run each candidate test on the proposed diff in a fresh disposable workspace:

- pass on parent and fail behaviorally on diff: `weak-catch`;
- cannot build or run comparably on both revisions: `not-comparable`;
- infrastructure or flaky result: `inconclusive`;
- pass on diff: no catch; retain the test only if it hardens useful confirmed behavior.

### 5. Resolve weak catches

Present the smallest observed parent-versus-diff behavior change through Maieutic, or through Socratic when it is orchestrating the run. Classify:

- human says unintended: `strong-catch`;
- human says intended: `false-positive`;
- no answer: keep `weak-catch`, persist the unresolved decision, and exit at `needs-decision`.

Do not land a catching test with an obsolete oracle. After intent confirmation, rewrite it as a hardening test for desired behavior when useful.

## Harden Mode workflow

### 1. Rank the risk surface

Map changed behavior to Contract IDs. Prioritize authorization, privacy, money, data integrity, compatibility, irreversible effects, state transitions, and externally visible interactions.

For a large change, partition by behavior or risk domain and assign a mutation budget to each selected partition. Normally select three to five diverse high-value mutants per run. Record every Contract ID that receives no mutant under `not_challenged` with its reason and residual risk.

### 2. Generate intent mutations

For each selected item:

1. state confirmed intent;
2. create a nearby plausible misunderstanding;
3. name the incident it represents;
4. rate severity and likelihood;
5. describe the smallest attributable code change;
6. name the observable test expected to kill it.

Prefer semantic and omission faults. Use traditional operator mutations only when they represent a real boundary or interpretation risk. Reject irrelevant, uncompilable-by-design, or broad unattributable rewrites.

### 3. Establish isolation and baseline

Follow every rule in `references/safety.md`. Capture primary workspace status and diff, create a disposable workspace with the exact target state, and apply the Baseline Policy there.

### 4. Execute one mutant at a time

For each mutant:

1. start from a fresh disposable copy of the unmutated revision;
2. apply only that mutant and inspect its diff;
3. compile or run the narrowest stable tests with a timeout;
4. classify the result;
5. discard mutated state before the next mutant.

Use:

- `killed`: a stable relevant test fails for the intended behavioral reason;
- `survived`: stable relevant tests pass;
- `invalid`: the mutant cannot exercise the intended risk;
- `equivalent`: evidence proves no observable contract difference;
- `timeout`: execution exceeds its bound;
- `inconclusive`: infrastructure, flaky, or unrelated failure prevents judgment.

A compilation failure is not a useful kill unless compilation is the protected contract. Record concrete equivalence evidence. If a mutant changes observable behavior that the contract does not mention, treat it as a missing-invariant candidate and return it to Maieutic; do not classify it as equivalent.

### 5. Investigate survivors

Determine whether each survivor is caused by a missing scenario, weak assertion, boundary gap, unobserved side effect or state transition, ambiguous specification, implementation-coupled test, or unreached path.

Return unresolved intent to Maieutic rather than generating an oracle. Persist `needs-decision` and continue only independent confirmed items.

### 6. Add and prove tests

When the contract is resolved, add the smallest behavioral test that fails on the mutant and passes on original code. Apply test changes to the primary workspace only when authorized.

Verify both directions:

1. original production code plus new test passes;
2. isolated mutant plus new test fails for the expected assertion.

Then run the broader relevant unit-test suite. Do not weaken assertions or alter production behavior merely to kill a mutant.

### 7. Restore and audit

Discard all mutation sandboxes. Compare primary workspace state with preflight evidence. Confirm no production mutation remains and preserve only authorized test or documentation changes.

## Persisted report

Write `.socratic/elenchus-report.json` using the bundled report schema. Include:

- mode, contract path, and stable baseline evidence;
- each mutation record and classification;
- catching outcomes and human verdicts when applicable;
- tests added and bidirectional proof;
- every `not_challenged` Contract ID and reason;
- unresolved decisions and reduced test scope;
- postflight proof that primary production code is mutation-free.

Mutation score may be secondary context, never the success criterion. Never equate budget exhaustion with a fully hardened contract.
