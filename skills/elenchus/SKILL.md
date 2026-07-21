---
name: elenchus
description: Evaluate whether tests detect plausible bugs by generating risk-ranked mutations from programming intent, applying each mutation only in an isolated workspace, analyzing catches and survivors, adding missing tests, proving tests kill the mutation, and contributing Behavior difference and Test gap findings as copy-ready review material. Use for intent-aware catching, regression hardening, refactor guarding, test-quality assessment, critical diff validation, or requests such as「ミューテーションテストして」「テストがバグを検知できるか確認して」「リファクタリングで振る舞いが変わっていないか確認して」.
---

# Elenchus

Challenge a test suite with plausible misunderstandings of programming intent. Optimize for confidence in important behavior, not mutation score. Mutation is the internal evidence engine, not the headline: report each result as the incident it represents, never as an operator name or a score.

## Required references

Read [references/mutation-design.md](references/mutation-design.md) before generating mutants and [references/safety.md](references/safety.md) before changing or executing code. Validate inputs and outputs with the bundled [intent-contract.schema.json](references/intent-contract.schema.json), [mutation-result.schema.json](references/mutation-result.schema.json), and [mutation-report.schema.json](references/mutation-report.schema.json).

## Git safety boundary

Use local Git only for strictly read-only evidence gathering and immutable snapshot export. Allowed commands are limited to `git diff`, `git show`, `git log`, `git rev-parse`, `git merge-base`, `git ls-files`, and `git archive`. Never change local or remote Git state. Never run any staging, commit, amend, push, pull, fetch, checkout, switch, reset, stash, merge, rebase, cherry-pick, branch, tag, or worktree operation. Never invoke `gh` or a code-host write API. Do not request permission to perform a prohibited operation.

Materialize Base and Head as disposable filesystem snapshots without branch switching or Git worktrees. If the required object is unavailable locally and obtaining it would require `fetch`, stop and report the snapshot as unavailable.

## Locate the Intent Contract

Load the contract in this order:

1. an explicit path supplied by the user, Maieutic, or the Socratic orchestrator, including a temporary run artifact;
2. `.socratic/intent-contract.json` in the repository, present when a previous run saved locally;
3. a complete contract in the current conversation.

If none exists, stop and ask the user to run `$maieutic`, run the full `$socratic` workflow, or supply a contract. Do not reconstruct confirmed intent from implementation. Keep the final report as a temporary run artifact outside the working tree; write `.socratic/elenchus-report.json` only when the user chooses local saving under the artifact policy, or another explicitly supplied path.

## Choose mode and preconditions

### Harden Mode — default

Require a `confirmed` or `tested` contract for every challenged oracle. Mutate confirmed intent and verify that tests kill the resulting code mutants.

### Catch Mode

Allow a `provisional` or `needs-decision` contract when both the parent revision and proposed diff are identified. Generate tests from risk mutants of the parent, then check whether the proposed diff exhibits the same risky behavior. A Catch Mode result may create decisions; it must not pretend intent was already confirmed.

For either mode, identify the exact immutable snapshot identity, changed and high-risk locations, focused test command, isolation strategy, and baseline result. If no runnable tests exist, stop mutation execution and return to Maieutic for test-infrastructure selection; do not install a framework without authorization.

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

Build each probe on observable behavior — output values first, then observable final state, then application-boundary communication for unmanaged dependencies. A probe coupled to internal call order, call counts, or intermediate state produces false positives: never use it, and never report its failure as a behavior difference.

### 4. Run against the proposed diff

Run each candidate test on the proposed diff in a fresh disposable workspace:

- pass on parent and fail behaviorally on diff: `weak-catch`;
- cannot build or run comparably on both revisions: `not-comparable`;
- infrastructure or flaky result: `inconclusive`;
- pass on diff: no catch; retain the test only if it hardens useful confirmed behavior.

### 5. Resolve weak catches

Present the smallest observed parent-versus-diff behavior change through Maieutic, or through Socratic when it is orchestrating the run; the structured question itself is asked by the main agent, never by a subagent. Shape it as a copy-ready `Behavior difference` comment anchored to the changed file and line — the parent behavior, the head behavior, and the question whether the change is intended — addressed to the specification owner. Treat the parent as an observed fact, never as the specification. Classify:

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

Prefer semantic and omission faults. Use traditional operator mutations only when they represent a real boundary or interpretation risk. Reject irrelevant, uncompilable-by-design, or broad unattributable rewrites. Mutate only client-observable behavior: never force tests to detect a mutation that preserves observable behavior, such as a change to internal call order or intermediate state.

### 3. Establish isolation and baseline

Follow every rule in `references/safety.md`. Capture a scoped filesystem manifest and content hashes for the primary workspace, create a disposable filesystem snapshot with the exact target state, and apply the Baseline Policy there. Do not use Git status, a branch switch, or a Git worktree as the isolation or restoration mechanism.

### 4. Execute one mutant at a time

For each mutant:

1. start from a fresh disposable copy of the unmutated snapshot;
2. apply only that mutant and inspect the changed files;
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

When the contract is resolved, add the smallest behavioral test that fails on the mutant and passes on original code. In Review-only mode, the default, keep the proven test in the disposable workspace and report it as a proposed test; apply test changes to the primary workspace only in Apply tests mode, when the user has explicitly requested test additions. A proposed test proves detectability within the run only: it does not advance the contract to `tested` or `hardened`, and the report must note as residual risk that the protection is not yet persistent.

Verify both directions:

1. original production code plus new test passes;
2. isolated mutant plus new test fails for the expected assertion.

Then run the broader relevant unit-test suite. Do not weaken assertions, couple tests to implementation details, or alter production behavior merely to kill a mutant.

Report each resolved survivor as a `Test gap` finding: the incident the mutant represents, the assertion added, and both directions of proof — for example, "deleting the event emission left existing tests green; a boundary-contract assertion was added and now fails on that mutation".

### 7. Restore and audit

Discard all mutation sandboxes. Compare the scoped primary-workspace manifest and content hashes with preflight evidence. Confirm no production mutation remains and preserve only authorized test or documentation changes. Never use Git restoration and never stage, commit, or push preserved changes.

## Reviewer-facing summary

Contribute findings to the canonical four-block surface, routed by state, not type: unconfirmed behavior differences and unresolved decisions to Review This; confirmed intended changes, applied or proposed-and-proven tests, resolved test gaps, and proven detection to We Verified; unchallenged Contract IDs, reduced scope, and non-comparable ranges to Still at Risk. A resolution that rests on a proposed test also appears under Still at Risk as protection not applied yet. Emit at most one to three copy-ready comment candidates (`Behavior difference` or `Test gap`) with file, line, comment body, and generation evidence; never post them. Never report merge readiness, a confidence level, or a score.

## Report artifact

Produce the report against the bundled report schema as a temporary run artifact; it is written to `.socratic/elenchus-report.json` only when the user chooses local saving under the artifact policy. Include:

- mode, contract path, and stable baseline evidence;
- each mutation record and classification;
- catching outcomes and human verdicts when applicable;
- the write mode, every test change with its disposition (existing, proposed, or applied), authorized workspace changes, and bidirectional proof;
- every `not_challenged` Contract ID and reason;
- unresolved decisions and reduced test scope;
- postflight proof that primary production code is mutation-free.

Mutation score may be secondary context, never the success criterion. Never equate budget exhaustion with a fully hardened contract.

Delete the temporary report on every exit path — success, failure, timeout, or interruption — unless the user chose to keep it, and report the exact path if a deletion fails.
