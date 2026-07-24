<p align="center">
  <img src="./assets/socratic-logo.png" alt="Socratic" height="120">
</p>

[Website](https://shogo1222.github.io/socratic/) | English | [日本語](README.ja.md)

# Socratic

[![CI](https://github.com/Shogo1222/socratic/actions/workflows/ci.yml/badge.svg)](https://github.com/Shogo1222/socratic/actions/workflows/ci.yml)
[![GitHub Release](https://img.shields.io/github/v/release/Shogo1222/socratic?include_prereleases)](https://github.com/Shogo1222/socratic/releases)

> Don't review every line. Review the decisions that matter.

Socratic is a host-gated review workflow for AI-generated changes. It keeps the AI focused on the work that requires reasoning — inferring intent, exposing consequential uncertainty, designing realistic accidents, and interpreting behavioral evidence — while a deterministic Runner owns commands, disposable clones, mutations, schemas, hashes, reports, and cleanup.

The workflow is delivered as three Agent Skills. Their names follow the Socratic method: recognize what is not yet known and inquire (Socratic), draw intent out through dialogue (Maieutic, the art of midwifery), and examine claims by refutation (Elenchus).

- **Socratic** — the orchestrator. It frames the change as observable intent, preserved invariants, realistic accidents, and residual risk; asks only the decisions repository evidence cannot settle; and delivers the four-block review surface with copy-ready comment candidates. **Outcome**: instead of reading the whole diff, you review a handful of decisions and paste-ready comments.
- **Maieutic** — the elicitation skill. It converts expectations the implementation alone cannot establish into concrete questions a specification owner can answer, and records the answers in the Intent Contract linked to their tests. **Outcome**: vague unease becomes answerable specification questions and a test-backed record of confirmed intent.
- **Elenchus** — the refutation skill. It challenges focused behavior tests with realistic, intent-linked mutations. Run standalone, it assesses the protection supplied by existing and changed test cohorts (Test Assessment). **Outcome**: not "the tests are green" but proof that injecting the bug actually makes a test fail.

The current integration preview is **v0.5.0-alpha.7** for Claude Code, Codex, and local Cursor Desktop.

## The problem

When AI writes most of the code, reviewers face:

- diffs too large to scrutinize line by line;
- implementation intent that the code alone cannot establish;
- green tests that may not detect important bugs;
- lingering doubt that a refactoring changed behavior;
- investigation and wording costs for every review comment;
- AI reviewers flooding PRs with low-value comments.

Socratic lets a reviewer grasp four things quickly:

1. what changes from the user's point of view;
2. where a human specification decision is required;
3. which incidents are plausible;
4. whether the tests would actually detect them.

## How a review runs

```text
Trusted Host preflight
        ↓
Mission + Review Type confirmation
        ↓
Bounded diff inspection + Diff understanding confirmation
        ↓
Intent Contract
        ↓
Prepare dependencies once + probe the focused tests
        ↓
One parallel batch of realistic accident mutations
        ↓
Interpret raw outcomes
        ↓
Runner-attested review + cleanup
```

The human is asked at four checkpoints, not between every mechanical step:

1. **Review Type** — Bug Fix Review, Feature Review, Refactor Guard, or Test Assessment.
2. **Diff understanding** — the problem, changed behavior, behavior to preserve, new observable, and consequential uncertainty.
3. **Intent/oracle decision** — only when repository evidence cannot settle an important observable expectation. Repository-established intent is recorded without asking.
4. **Final interpretation and disposition** — what the evidence proves, what remains at risk, and whether temporary artifacts or proven test changes should be kept.

At startup the Runner supplies a runbook with the ID glossary, gate order, editable fields, and exact next command. The agent explains the plan in the user's language and announces each phase. It does not hand-write schemas, run IDs, hashes, ledgers, or final reports.

For mutation work, dependencies are installed once. The Runner probes one focused command, seals installed packages as a shared dependency layer, then branches a fresh copy-on-write source sandbox for every mutation. Each sandbox keeps its own HOME, temp, package cache, and runtime directories such as `node_modules/.vite`, so fast sharing does not turn normal test-cache writes into dependency tampering.

## IDs, states, and result vocabulary

You do not need to write these values yourself. The Runner's runbook and scaffolds supply the valid fields; this reference explains what you see in progress messages and artifacts.

### Contract IDs

| Prefix | Meaning | Example |
|---|---|---|
| `DEC` | a settled decision about expected observable behavior | whether a redirect should emit an event |
| `INV` | existing observable behavior that must remain true | real application errors are still logged |
| `FX` | a required or prohibited side effect | emit once; never drain twice |
| `UNR` | an important question repository evidence cannot settle | whether absence or a normal event is intended |
| `CMD` | a focused test command the Runner successfully probed | the exact Vitest command reused for mutations |
| `MUT` | a realistic accident injected into a disposable clone | remove the navigation-signal guard |

`UNR-*` is a gate, not a finding label: only mutations linked to that unresolved oracle stop. Independent, settled Contract items may continue.

### Intent Contract lifecycle

```text
provisional
    ├─ multiple plausible oracles → needs-decision → confirmed
    └─ authoritative evidence ─────────────────────→ confirmed
confirmed → tested → challenged → hardened
```

| Status | Meaning |
|---|---|
| `provisional` | the diff and repository evidence support an intent hypothesis |
| `needs-decision` | multiple reasonable expectations would produce different test oracles |
| `confirmed` | a specification owner or authoritative repository evidence resolved the required oracle |
| `tested` | stable, persistent tests protect the confirmed Contract |
| `challenged` | risk-directed mutations were executed against stable tests |
| `hardened` | selected high-risk mutants were killed and every unchallenged risk is explicit |

A passing implementation is not confirmation. A Review-only proof that depends only on a proposed, disposable test cannot advance to `tested` or `hardened` until that test is applied.

Decision provenance records *who or what established the oracle*:

| Value | Meaning |
|---|---|
| `repository-established` | authoritative repository evidence settles it; no human question is needed |
| `user-confirmed` | a specification owner or authorized proxy explicitly decides |
| `reviewer-selected-benchmark-assumption` | a reviewer without specification authority chooses an evaluation assumption |

### Elenchus modes

| Mode | Purpose |
|---|---|
| `assessment` | measure what existing and changed test cohorts detect; do not create tests by default |
| `harden` | challenge confirmed behavior and prove protection against realistic accidents |
| `catch` | use parent-side accidents to expose a possible behavior change before intent is confirmed |

### Mutation results

| Result | Meaning |
|---|---|
| `killed` | a stable relevant test failed for the intended behavioral reason |
| `survived` | stable relevant tests stayed green; the represented risk is not detected |
| `invalid` | the mutation could not exercise the intended risk |
| `equivalent` | evidence proves no observable Contract difference |
| `timeout` | the bounded execution timed out |
| `inconclusive` | infrastructure, flaky, crash, or unrelated failure prevents judgment |
| `weak-catch` | a candidate catches a parent-side accident and exposes a possible behavior difference |
| `strong-catch` | the owner confirms that caught behavior is unintended |
| `false-positive` | the owner confirms that the caught behavior is intended |
| `not-comparable` | parent and proposed revisions cannot run the candidate comparably |
| `no-catch` | the candidate does not expose the proposed difference |

<details>
<summary>Additional report enums</summary>

- Raw outcome `kind`: `passed`, `behavioral-failure`, `infrastructure-failure`, `process-crash`, `timeout`, or `unparseable`. A nonzero process exit becomes `killed` only when the assertion evidence shows the intended Contract violation.
- Intent `confidence`: `high`, `medium`, or `low` describes the strength of the cited evidence, not an overall review score.
- Mutation `severity`: `critical`, `high`, `medium`, or `low` describes impact if the represented incident occurs. `likelihood`: `high`, `medium`, or `low` describes plausibility; neither is a test outcome.
- Test `disposition`: `existing` at run start, `proposed` and proven only in a disposable workspace, or `applied` after explicit authorization.
- `not_challenged.reason`: `budget`, `not-observable`, `not-applicable`, `deferred`, or `blocked`. Every entry carries its residual risk.
- Assessment scope: `current-change`, `changed-tests`, or `broader-target`.
- Cohort comparison: `existing-protection`, `incremental-protection`, `protection-regression`, `unprotected`, `not-comparable`, or `inconclusive`.
- Catch `human_verdict`: `intended`, `unintended`, `unanswered`, or `not-requested`.
- `Review This` kind: `confirmed-behavior`, `behavior-difference`, `test-gap`, or `needs-decision`.
- Copy-ready comment tag: `Intent decision`, `Behavior difference`, or `Test gap`.

The bundled [schemas](schemas/) are the machine-readable authority; the [Intent Testing Protocol](docs/protocol.md) explains their lifecycle and gates.

</details>

## Installation

Socratic targets Claude Code, Codex, and local Cursor Desktop. Other agent hosts are not supported by this integration preview. The current preview release is [v0.5.0-alpha.7](https://github.com/Shogo1222/socratic/releases/tag/v0.5.0-alpha.7).

### Claude Code

Add the repository as a Claude Code Marketplace and install the Plugin:

```text
/plugin marketplace add Shogo1222/socratic
/plugin install socratic@socratic-marketplace
```

To receive a published version bump, refresh the catalog and update the Plugin:

```text
/plugin marketplace update socratic-marketplace
/plugin update socratic@socratic-marketplace
/reload-plugins
```

Then start Claude normally in a trusted Git repository and invoke the Marketplace command shown as `/socratic`. Include a PR target in the first invocation when reviewing a GitHub pull request so the Host can materialize its exact historical Base and Head before the run starts:

```text
/socratic https://github.com/owner/repository/pull/123
```

The Plugin automatically starts a session-scoped Host broker before Claude processes the request and denies direct Primary writes and unguarded Bash through `PreToolUse`. Direct Maieutic and Elenchus invocation uses the same gate. A `Stop` event preserves the broker while a run manifest exists so human decisions can span turns, then cleans it after finish or abort; an idle TTL and later Host events collect abandoned or stale brokers. No separate launcher command is required.

Review and trust the bundled hook through `/hooks`, then start a new thread. If the hook is untrusted, disabled, or unavailable, do not use Socratic. Plugin-hook trust is user-controlled; an organization that needs an undeletable boundary must deploy the same gate as a managed hook through `requirements.toml` and OS/device management.

### Codex

Add the Codex marketplace, install the Plugin, and review its bundled hooks through `/hooks`:

```bash
codex plugin marketplace add Shogo1222/socratic
codex plugin add socratic@socratic-marketplace

# refresh the Marketplace snapshot before installing a published update
codex plugin marketplace upgrade socratic-marketplace
codex plugin add socratic@socratic-marketplace
```

Invoke `$socratic` in a trusted local Git repository. The Codex Plugin starts the same session-scoped Host broker and denies direct Primary writes and unguarded commands through `PreToolUse`. It preserves active run state across turns and cleans completed, aborted, or idle sessions.

```text
$socratic https://github.com/owner/repository/pull/123
```

### Cursor Desktop

The repository also contains a native Cursor Plugin under `.cursor-plugin/`. Install it as a local Plugin in Cursor Desktop and reload the window before invoking `$socratic` with a local diff or PR target. The Plugin uses fail-closed `beforeSubmitPrompt`, `preToolUse`, and `beforeShellExecution` hooks. Cursor CLI, remote workspaces, and cloud agents are not supported because their current hook coverage cannot establish the same boundary. Public Cursor Marketplace installation remains unavailable until the Plugin has passed Cursor's separate submission process.

### Standalone Maieutic and Elenchus

Standalone Agent Skills remain available for Maieutic and Elenchus analysis in Codex or Cursor, but a standalone Skill install is not the compliant mutation-capable `$socratic` entrypoint:

```bash
# choose skills and install them for Codex or Cursor interactively
gh skill install Shogo1222/socratic

# install all three skills
gh skill install Shogo1222/socratic --all

# pin standalone resources to an integration-preview release
gh skill install Shogo1222/socratic --all --pin v0.5.0-alpha.7
```

Alternatively, use the Agent Skills CLI and select Codex or Cursor as the target:

```bash
npx skills add Shogo1222/socratic --skill '*'
```

Invoke `$maieutic` or `$elenchus` directly for standalone analysis. Use each Host's Plugin above for the integrated `$socratic` workflow.

The mandatory review runner requires Python 3 with `jsonschema` and `referencing`. Each Host Plugin resolves these dependencies before the agent starts. If they are absent, the Hook creates an isolated virtual environment in the Plugin's writable data directory and installs pinned versions there; it never changes the repository or global Python environment. The first run therefore requires package-index access. Bootstrap failure stops Socratic before the agent runs. Organizations may pre-provision the same pinned dependencies in a managed Python runtime to avoid first-run network access.

For organizational rollout — release verification, preview, and project scope — follow the [enterprise installation guide](docs/enterprise-installation.md).

## Who it is for

- senior engineers and tech leads reviewing AI-generated PRs;
- reviewers who want to know quickly which decisions a large diff actually needs;
- teams that want to check whether AI-added tests really protect anything.

How Socratic positions itself:

- it does not replace review; it prepares the material that lets the reviewer focus on important decisions;
- it never posts to GitHub — it generates copy-ready inline comment candidates, and the reviewer decides what to post, edit, or discard;
- specification questions are answered by the specification owner: the PR author, reviewer, product owner, domain expert, tech lead, or the owner of the API or data;
- when AI generated the code, the AI is neither specification evidence nor an answerer;
- when the reviewer lacks the authority to decide, the comment candidates are their tool for confirming with the owner.

## Use cases

### Bug Fix Review

For a change that fixes a reported failure, confirm the failure is removed without broadening the fix into unrelated behavior. The accident plan should cover both reintroducing the bug and plausible overcorrections.

```text
Reported failure
      ↓
Expected fixed behavior
      +
Established behavior to preserve
      ↓
Focused baseline + accident mutations
```

### Feature Review

For a PR that introduces new behavior or changes a specification, extract the expectations the implementation alone cannot establish.

```markdown
Is renewal intended to succeed when the contract end date equals the renewal date?

The expectation at this boundary depends on whether the end date is inside the valid period. The repository does not resolve this, so we would like to confirm the expected behavior.
```

Confirmed specifications are recorded in the Intent Contract and linked to their tests.

### Refactor Guard

For a refactoring that claims to preserve behavior, use the Host-materialized Base/Head diff to establish the observable invariants that must remain stable, then challenge the focused tests on the prepared Head snapshot.

```text
Exact Base / Head snapshots
          ↓
Preserved observable invariant
          ↓
Focused Head baseline passes
          ↓
Realistic mutant must fail
```

When repository or focused comparison evidence reveals a behavior difference, ask a human whether it is an intended change or a regression.

```markdown
This refactoring appears to change the expiry-boundary behavior.

When the contract end date equals the execution date, renewal succeeded before the change and is rejected after it.

If this refactoring is meant to preserve behavior, this may be an unintended change. Is it intended?
```

For Refactor Guard to be trustworthy, comparison tests must verify observable behavior, not internal structure. False positives produced by implementation-coupled tests are never reported as behavior diffs.

### Test Assessment

For evaluating the tests themselves — especially tests an AI just added — run `$elenchus` standalone. It compares the same risk mutations against the existing and changed test suites and separates existing protection, incremental protection, protection regressions, and unprotected risks. See [Run Elenchus independently](#run-elenchus-independently).

## Behavior diff classification

When a stable behavior comparison is available for both Base and Head, classify it as follows. Infrastructure failures and mutation outcomes are not substituted for this comparison.

| Base | Head | Classification |
|---|---|---|
| Pass | Pass | the verified behavior is preserved |
| Pass | Fail | existing behavior was changed or removed |
| Fail | Pass | new behavior was added or fixed |
| Fail | Fail | not valid as a comparison test, or not implemented |

Test compile failures, environment errors, timeouts, and flaky failures are never treated as behavior diffs.

`Base pass / head fail` is never automatically a bug. The base is not the specification; it is the behavior observed before the change.

- In a refactor PR, an unintended change is likely.
- In a feature PR, an intended specification change is possible.
- When neither can be established, ask a human.

## Output

The terminal output is fixed to four blocks:

- **Review This** — what needs a human decision: unresolved intent, behavior diffs not yet confirmed as intended, and design risks that need an acceptance decision.
- **We Verified** — what is confirmed: preserved behavior, changes the specification owner confirmed as intended, tests applied to the working tree and proven, tests proposed and proven in a disposable workspace, resolved test gaps, and detection ability proven by mutation.
- **Still at Risk** — what was not verified: unchallenged behavior, execution-environment constraints, nondeterministic processing, and ranges that could not be compared.
- **Copy-ready Comments** — candidates the reviewer can use, with target file, target line, comment body, and internal generation evidence.

Test provenance is always relative to the start of the Socratic run, not to the broader conversation or Git history. Reviewer-facing output identifies each test as **existing at run start**, **proposed and proven in disposable workspace**, or **applied by this run after explicit request**. A Review-only run whose postflight matches preflight also says **Working tree unchanged during this Review-only run**.

When Review-only proves a proposed test, Socratic preserves an exact test-only patch and its hash-validated handoff outside the working tree until you choose **Apply tests**, **Output patch**, or **Discard**. This operational choice appears after the four review blocks. A stale or missing handoff is regenerated and re-proved instead of being forced or described as reused.

Findings route by state, not type:

```text
Behavior diff
  unconfirmed            -> Review This
  confirmed intended     -> We Verified

Test gap
  unresolved                                   -> Review This
  proposed and proven in disposable workspace  -> We Verified
                                                  + Still at Risk: protection not applied yet
  applied to working tree and proven           -> We Verified

Residual risk
  -> Still at Risk
```

An example run:

```text
Socratic Review

Review This:
  ! Expiry-date behavior changed; the specification owner must decide whether it is intended.

We Verified:
  ✓ Existing boundary tests detect duplicate renewal and incorrect event emission.
  ✓ Working tree unchanged during this Review-only run

Still at Risk:
  △ Timezone behavior was not verified because the clock cannot be controlled.

Copy-ready Comments:
  1 comment for src/subscription.ts:52
```

Merge readiness, confidence levels, and overall scores are never displayed. Socratic reports the verified scope, decisions or findings, and unverified scope; the merge decision stays with the reviewer. Detailed artifacts are temporary by default and are discarded after rendering unless the user chooses local or Markdown output before `complete`.

## Human decisions and comments

An unresolved behavior difference becomes a structured question in the host's native UI:

```text
Behavior diff
  → structured decision
  → Intent Contract
  → test and mutation evidence
```

Each batch contains one to three questions, concrete mutually exclusive options, their observable consequences, and a defer-to-owner option when authority is unclear. Claude Code renders them with `AskUserQuestion`; Codex uses `request_user_input`; other environments receive copyable Markdown.

The main agent asks the questions. The Host supplies the target and the Runner performs bounded inspection and execution. Socratic then generates at most three copy-ready comments tagged `Intent decision`, `Behavior difference`, or `Test gap`; it never posts them. Each comment states the observed behavior, the needed decision or missing protection, why it matters, and what each answer changes. Unanchored issues stay under Still at Risk.

## Test design and mutation principles

Socratic tests a unit of **observable behavior**, not a class, method, or internal call sequence:

```text
client goal
  → operation
  → output, final state, or external-boundary communication
  → smallest stable test at the appropriate level
```

- Prefer output values, then observable final state, then communication crossing the application boundary.
- Use focused integration tests for important managed state and a small number of E2E tests for boundary contracts.
- Do not assert internal method order, replaceable algorithms, repository call counts, or intermediate state with no observable effect.
- Balance regression protection, refactoring resistance, feedback speed, and maintainability according to the risk; no single test level maximizes all four.

Mutation testing is the internal proof that the selected test detects a realistic accident:

```text
Prepared Head baseline  → pass
Fresh mutant clone      → fail for the represented Contract violation
```

If a mutation survives, Socratic investigates the missing scenario, weak oracle, boundary gap, or unresolved intent. Mutations that preserve observable behavior are not forced into detection, and mutation score is never the success criterion. The detailed method is in [QA Techniques](skills/maieutic/references/qa-techniques.md), [Mutation Design](skills/elenchus/references/mutation-design.md), and the [Intent Testing Protocol](docs/protocol.md).

## Write policy

The default mode is **Review-only**: nothing is written to the PR, GitHub, or the repository working tree.

- no automatic posting to GitHub;
- no changes to head production code;
- comparison tests and mutations run in isolated workspaces;
- proven proposed tests remain available as a temporary test-only patch until you apply, output, or discard them;
- run artifacts are temporary by default — before `complete`, an explicit keep choice is recorded; no answer means discard;
- only comment candidates are presented.

Only when the user explicitly asks for test additions — including selecting **Apply tests** for a proven handoff — does Socratic switch to **Apply tests** and add tests, based on confirmed intent, to the working tree. It verifies handoff preconditions before application and repeats the focused original-code and mutation proof afterward. Version-control operations stay with the user in both modes.

The Socratic agent may use allowlisted, read-only local Git commands to inspect the materialized change. It never stages, commits, pushes, fetches, switches branches, creates worktrees, contacts a remote, invokes `gh`, creates a pull request, or posts a comment. When the invocation includes a GitHub PR URL or `PR #<number>`, the trusted Host—not the agent—resolves metadata with `gh`, fetches the exact Base and Head commits into private Host storage, verifies both SHAs, and gives the Runner read-only snapshots. The Base is fetched by its immutable historical SHA, never by the current tip of its branch, so merged and older PRs remain reproducible after the target branch advances. Failure to resolve or verify either commit blocks the run with the failed materialization stage. All version-control writes remain with the user.

The Host also injects a compact review context containing the exact target, changed-file list, package-manager hint, and fixed fast path. Deterministic diff and environment discovery are not delegated to subagents. The Intent Contract is staged before mutation; each challenge names its Contract IDs, and the Runner blocks unresolved oracles before creating a mutant. Canonical `Review This` items are Contract-linked, and attested reports include measured baseline and mutation durations. A terminal `complete` failure cleans the disposable run and produces no canonical review; the agent reports the failure and starts a fresh run if another attempt is needed, rather than hand-writing a substitute or retrying a deleted manifest.

## Internal architecture

```text
Pull Request / Local Diff
          |
          v
Trusted Host
  - materialize exact target
  - start the broker and tool gate
  - issue run identity and protected storage
          |
          +-------------------------------+
          |                               |
          v                               v
AI reasoning                         Deterministic Runner
  - infer observable intent            - bounded inspect
  - expose consequential uncertainty   - prepare dependencies once
  - design realistic accidents         - probe the focused command
  - interpret raw outcomes             - clone and mutate in parallel
  - write reviewer-facing claims       - validate, attest, render, cleanup
          |                               |
          +---------------+---------------+
                          v
        Review This / We Verified / Still at Risk
                          |
                          v
                 Copy-ready Comments
```

The AI may edit only three semantic inputs in protected Host storage: the Intent Contract, Challenge Plan, and Review Analysis. Every one starts from a Runner-generated document and fixed absolute path. The first `Write` creates the file; corrections use `Read` followed by `Edit`. The Runner, not the AI, owns report identity, execution evidence, hashes, the append-only ledger, the final renderer, and cleanup.

Maieutic and Elenchus are connected by the [Intent Contract](docs/protocol.md), a temporary run artifact by default, written to `.socratic/intent-contract.json` only when you choose to keep it. It is a small, traceable record of decisions, invariants, side effects, evidence, and test coverage.

The names describe their relationship:

- **Socratic** is the whole method: recognize uncertainty, inquire, and test claims by refutation.
- **Maieutic** is the elicitation stage: help humans articulate intent the implementation cannot establish.
- **Elenchus** is the refutation stage: challenge whether tests actually defend that intent.

## Run Elenchus independently

Invoke `$elenchus` without memorizing a mode or writing a detailed prompt. A standalone run first inspects the diff and test topology, then asks one structured scope question with a detected recommendation:

1. **Current change: existing and changed tests (Recommended)** — evaluate existing protection and the incremental effect of added, modified, or removed tests.
2. **Changed tests only** — evaluate the test diff and its pre-change counterparts with a smaller budget.
3. **Broader target** — select a module or repository-wide scope with higher execution cost.

If production code changed without test changes, Elenchus audits the relevant existing suite. If tests changed, it compares the same risk mutations against the existing and changed test cohorts. It distinguishes:

| Existing tests | Changed tests | Outcome |
| --- | --- | --- |
| detect | detect | Existing Protection |
| miss | detect | Incremental Protection |
| detect | miss | Protection Regression |
| miss | miss | Still at Risk |

The standalone output is **Assessment Scope**, **Existing Protection**, **Changed Test Contribution**, **Still at Risk**, and **Test Quality Concerns**. Assessment is Review-only and does not create missing tests by default. Ask Elenchus to harden a confirmed gap to prove a proposed test in a disposable workspace; ask separately to apply tests to the working tree.

When Socratic invokes Elenchus, it passes the already-confirmed scope, so Elenchus does not ask the scope question again and maps the same evidence into Socratic's canonical four-block review surface.

## Repository layout

```text
skills/
  socratic/   End-to-end orchestration
  maieutic/   Intent elicitation and test design/completion
  elenchus/   Existing/changed-test assessment and intent-mutation validation
docs/
  protocol.md Shared concepts and lifecycle
hooks/
  *_preflight.py   Host startup and target materialization
  *_tool_gate.py   Review-only tool enforcement
schemas/
  intent-contract.schema.json
  challenge-plan.schema.json
  review-analysis.schema.json
  mutation-result.schema.json
  mutation-report.schema.json
  run-manifest.schema.json
  test-handoff.schema.json
tests/
  schema/        Schema contracts
  distribution/ Release and bundle integrity
  hosts/         Claude Code, Codex, and Cursor integration
  runner/        Guarded execution and rendering
  security/      Isolation boundaries
  workflow/      Intent and lifecycle gates
.github/workflows/
  ci.yml         Repository validation
  release.yml    Tag and GitHub Release creation
```

Each directory under `skills/` is an Agent Skill. The native Host Plugins package all three for the integrated Socratic workflow. `$maieutic` and `$elenchus` can also be invoked independently when only one analysis stage is needed.

The v0.5 integration has moved canonical mutation mechanics out of agent instructions and into the Host-gated Runner. Its accepted decisions and typed test-profile boundary are documented in [Runner Architecture Decisions](docs/runner-architecture.md) and [Runner Test Profiles](docs/test-profiles.md). The narrower `local-copy` experiment path can emit unsigned evidence for development, but it cannot produce the canonical attested review surface.

## Non-goals

Socratic does not promise:

- full behavioral equivalence of base and head;
- detection of every bug;
- review of every changed line;
- automatic comment posting to GitHub;
- mutation-score maximization;
- maximizing all four pillars at once;
- treating the base implementation as the correct specification;
- changing production design unnecessarily for the sake of tests.

## Research foundation

This project is inspired by two complementary research directions, represented by three papers:

- [Harden and Catch for Just-in-Time Assured LLM-Based Software Testing](https://arxiv.org/abs/2504.16472) formally defines hardening tests, catching tests, and the Catching JiTTest Challenge.
- [Just-in-Time Catching Test Generation at Meta](https://arxiv.org/abs/2601.22832) applies that framing at industrial scale, reporting results for diff-aware and intent-aware catching tests and demonstrating low-friction human sense-checks for deciding whether changed behavior is expected.
- [Intent-Based Mutation Testing: From Naturally Written Programming Intents to Mutants](https://arxiv.org/abs/2607.05149) generates implementations from natural-language intent variants and finds partially non-overlapping mutant behaviors compared with syntax-based mutation in its 29-program evaluation.

The test design principles follow Vladimir Khorikov's *Unit Testing Principles, Practices, and Patterns*.

Socratic connects these ideas. The explicit human-confirmed Intent Contract, Maieutic intent elicitation, Contract-ID links between tests and mutations, the canonical four-block output, and copy-ready comment candidates are Socratic's own design, not claims of the papers or the book. Socratic is an independent open implementation, not an implementation published or endorsed by the authors of these works or their institutions.

## Security

For organizational adoption, review the [security model](docs/security-model.md) and follow the [enterprise installation guide](docs/enterprise-installation.md). Report suspected vulnerabilities privately according to the [security policy](SECURITY.md).

The skills define reviewable boundaries for Git operations, workspace writes, credentials, repository-supplied instructions, disposable mutations, and cleanup. Mutation writes routed through the bundled Isolation Gate receive mechanical path enforcement, while host-level read-only mounts, network policy, provider contracts, and normal human review remain independent protections.

## Status

**v0.5.0-alpha.7** is the current integration preview. It includes native Host paths for Claude Code, Codex, and local Cursor Desktop; exact GitHub PR materialization; a Runner-owned runbook and scaffold guides; one-time dependency preparation; a probed focused command; parallel copy-on-write mutation sandboxes; separated runtime caches; strict run-artifact validation; Mutation Report v10; a canonical four-block renderer; and terminal cleanup.

Standalone mutation execution remains intentionally blocked. A trusted Host must issue the run nonce, protected external storage, and repository-wide read-only or write-monitor capability. The preview has been dogfooded on a real pull request, but it is still an alpha: host-specific live runs, more repositories and test runners, failure recovery, and performance remain active validation areas.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the initial contribution boundaries.

## License

Socratic is available under the [MIT License](LICENSE).

Source: [github.com/Shogo1222/socratic](https://github.com/Shogo1222/socratic)
