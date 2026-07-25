# Runner Architecture Decisions

Status: D1–D5 are accepted decisions of the v0.4 prototype, retained as historical records; D6–D14 are accepted decisions of the v0.5 canonical Runner pipeline that shipped. One decision rule governs both.

The decision rule is:

> Is this reasoning or procedure? Keep reasoning available to the agent; move procedure into the Runner.

The v0.5 canonical integration applies this rule end to end. The Host-gated Runner (`run_review.py`) owns the fixed pipeline — `preflight`, `runbook` once, bounded `inspect`, `scaffold-contract`, `stage-artifact`, optional `execute --phase prepare`, one successful `probe-command`, `scaffold-plan`, one `challenge-batch`, `scaffold-analysis`, then `complete` — while the agent supplies only the semantic documents the Runner scaffolds and follows each result's `next.argv`. In Claude Code a run starts from the plugin-namespaced `/socratic:socratic` command; the Host Plugin starts the broker and injects the exact preflight command before the Skill runs.

## v0.4 prototype record

D1–D5 record the first vertical slice in its original terms: one `python-unittest` round, existing dependencies, `replace-exact` and `delete-exact` mutations, and a `local-copy` backend that can emit only `attested: false` evidence. This path remains available behind the `assess` subcommand for differential development and dogfooding, never for canonical Socratic reviews.

### D1: typed test profiles

The agent selects tests through a profile-specific structure and cannot supply argv or CLI options. The prototype accepts Python module, class, and method identifiers. Dependency preparation is `use-existing`; later installation profiles must separate a Host-approved preparation phase from offline baseline and mutation execution.

A future custom profile must bind exact argv, working directory, environment allowlist, network policy, approval provenance, and profile digest to Host evidence.

### D2: Host-owned evidence authenticity

`run_nonce` is agent-visible and is not a signing key. A future compliant Host keeps its signing key private and exposes no arbitrary sign operation. The Broker validates a Plan path, launches the trusted Runner itself, reads the create-once Evidence path from Host storage after Runner completion, and signs that fixed document as an internal step.

The signature binds run and round identities, Source, Plan, Runner, Evidence and Profile digests, Host Adapter identity, and validity times. The Broker retains minimal issued/consumed state per run and round to reject duplicate issuance and replay. Agent-visible socket credentials never authorize signing arbitrary bytes or paths.

The prototype does not implement signing. Its `local-copy` evidence must contain `signature: null`.

### D3: typed mutation limits

One mutation contains explicitly listed target paths, preimage identity, and ordered operations. The prototype permits at most four files per mutation and eight operations per file. Use `runner-computed` when the Runner owns Source materialization; use an explicit SHA-256 only to pin a previously observed preimage. Absolute paths, backslashes, parent traversal, globs, arbitrary Python, arbitrary shell, binaries, and symlinks are rejected by Runner validation.

The prototype operations are `replace-exact` and `delete-exact`. Both require one unique, exact text match. Schema validation is necessary but not sufficient; the Runner resolves paths, rejects symlinks, verifies an explicit hash immediately before writing, records the actual preimage and postimage hashes, and enforces bounded aggregate change size.

### D4: Run and round lifecycle

A Run owns Source identity, Test Profile digest, Prepared Snapshot, and preparation evidence. The prototype implements one full-baseline round. Later rounds reuse only a hash-unchanged Prepared Snapshot, use fresh Mutation IDs, and follow the profile's baseline policy. Changing flaky exclusions requires another full baseline.

Interpretation accepts one or more Evidence Bundles sharing one Run and Source identity. Every interpreted mutation must map to exactly one Evidence entry.

### D5: execution backends

`local-copy` is development-only and cannot produce attested evidence. It does not establish an operating-system boundary.

A compliant `isolated-host` backend must:

- omit Primary or mount it read-only;
- execute only a Host-materialized Source snapshot;
- isolate HOME, temporary and cache directories;
- omit credentials and `SOCRATIC_*` secrets;
- disable network during baseline and mutation execution;
- limit CPU, memory, processes, and time;
- make cleanup a Runner-owned unconditional operation.

Dependency downloads, when later supported, occur only in a separate Host-approved preparation phase without production credentials and with a fixed lockfile. Canonical Review remains unavailable until a conforming backend emits signed `attested: true` evidence.

### Implemented prototype

`run_review.py assess` performs one complete local experiment: it computes Source identity, creates a prepared copy, runs a full Python unittest baseline in a separate copy, applies each typed mutation to another fresh copy, returns raw Evidence in Plan order, and removes all disposable workspaces in a `finally` path. Baseline failure stops mutation execution. Environment credentials and `SOCRATIC_*` values are omitted from test processes.

Before Baseline, the Runner probes `jsonschema` and `referencing` from the same sanitized environment used by tests. Missing dependencies produce one structured `runner-error` with no Mutation execution instead of a cascade of test failures. Evidence records the Python implementation, version, executable hash, virtual-environment status, and probe result. The Plugin runtime accepts the current interpreter only when an isolated `-I` probe succeeds; user-site-only dependencies trigger provisioning of the Plugin-managed virtual environment.

This path is deliberately not an isolation or authenticity claim: `local-copy` cannot disable network or establish an OS boundary. Its Evidence is always unsigned and must never be rendered as a canonical Socratic review.

## v0.5 canonical pipeline decisions

D6–D14 record the decisions of the canonical pipeline that shipped in the v0.5 integration. They keep the same rule: the agent reasons about intent, accidents, and interpretation; the Runner owns every procedure.

### D6: Host-gated broker grant

The canonical pipeline never runs on self-assertion. A session-scoped Host broker, started by the Host Plugin before the agent processes the invocation, grants `preflight` the run capability: adapter identity, a 32-hex run ID, a nonce of at least 32 characters, protected storage outside the Primary repository, and one attested protection mode (`os-read-only`, `permission-read-only`, `host-events`, or `os-audit`). Preflight materializes the prepared source snapshot — a copy of the Primary without `.git` — inside a disposable sandbox marked `.socratic-disposable`, together with the change context and the Review Type recommendation. The standalone CLI always returns `blocked` and cannot accept self-asserted attestation JSON. In schema v10, `verified: true` means that the Runner accepted the trusted Host's attestation, not that the Runner independently verified the OS boundary.

### D7: runbook and next.argv guidance

The Runner, not skill prose, teaches the pipeline. Immediately after preflight the agent runs `runbook` exactly once: it states the Mission, the ID glossary (DEC/INV/FX/UNR/CMD/MUT), the gate order, the fields the agent may edit, and the hard rules, and returns the exact next command. Every successful Runner result carries `next.argv`; the agent runs it verbatim, replacing only `<angle-bracket>` placeholders. Argument mistakes return guided JSON pointing back to the runbook instead of a bare usage error, and phase transitions are announced from `next.announce` as human goals, never as internal command names.

### D8: Runner-scaffolded semantic documents

The agent edits exactly three semantic inputs in protected Host storage — `intent-contract.draft.json`, `challenge-plan.json`, and `review-analysis.json` — and every one starts from a Runner scaffold: `scaffold-contract`, `scaffold-plan` (available only after a successful probe; it binds the validated command ID), and `scaffold-analysis` (available only after the batch; it joins the Plan to raw outcomes, and a failed process starts as `inconclusive`, never automatically `killed`). Each scaffold returns a schema-valid `document`, its absolute `artifact_path`, `editable_fields`, and a Runner-owned `field_guide` with required keys, allowed enum values, conditional rules, and schema-valid element templates. The agent never reads schema files and never reconstructs a document from scratch: one `Write` creates the path, and corrections use `Read` then `Edit`.

### D9: create-once staged Contract and the hash-chained ledger

`stage-artifact` validates a draft against its bundled schema and indexes it create-once with its SHA-256. Mutation is rejected before a staged Intent Contract; every challenge names `contract_ids`, and a challenge mapped to an unresolved `UNR-*` oracle stays blocked. Every probe, guarded write, execution, and seal event is appended to a nonce-bound hash-chained ledger. `complete` accepts a Mutation ID only when the ledger holds both its guarded write/registration evidence and its execution evidence, and rejects any classification that contradicts the recorded raw outcome.

### D10: shared dependency layer and copy-on-write mutant sandboxes

Dependency installation runs at most once, through `execute --phase prepare`, before the source snapshot is sealed. After the successful probe the Runner moves `node_modules` and recognized Python virtual environments into a separately hashed shared dependency layer and re-attaches them through stable links; the layer hash is verified again before completion, so fast sharing cannot hide dependency tampering. Each Mutation ID then receives a fresh copy-on-write source clone (kernel clone or reflink, with a full copy as fallback) with private HOME, temp, and cache directories — runtime caches such as `node_modules/.vite` stay per-sandbox — so normal test-cache writes never look like dependency mutation and mutants never share mutable state.

### D11: one validated challenge-batch

Before any Mutation ID exists, `probe-command` runs the exact focused test argv in a fresh clone of the prepared snapshot and records a reusable command ID only on success. The challenge plan binds that command ID and contains only `replace-exact` and `delete-exact` anchored edits; it never embeds a complete source file, per-mutant argv, hashes, or ledger data. The single `challenge-batch` validates every anchor against the prepared source, creates every mutant clone, applies the edits itself, executes the recorded argv and cwd verbatim in parallel bounded by `max_parallel`, and returns raw outcomes in plan order. Classification happens only after all raw outcomes return.

### D12: guided errors and the read-only doctor

The tool gate rightly denies ad-hoc diagnostics during a hosted run, so the Runner names failure causes itself. A failed command returns structured JSON with bounded stdout and stderr, an environment `hint` when the Runner recognizes the cause — the `.git`-less prepared snapshot, an interpreter the project rejects, or a HOME-based tool shim that no longer resolves — and a `diagnose.argv`. That argv runs `doctor`: a read-only, secret-free report of the sandbox PATH, the toolchain executables that resolve there with their versions, the project's interpreter and build-backend requirements, the VCS-metadata situation, and the last failed command. It writes nothing and replaces ad-hoc shell probing.

### D13: failure receipt in Host storage

A terminal failure cleans the sandbox, artifacts, ledger, and manifest — which would otherwise erase the explanation of what happened. The Runner therefore leaves a small secret-free `failure-receipt.json` in Host storage recording the run ID, the failed phase, the error, the cleanup result, and whether the Primary postflight hash still matched preflight. The receipt explains how the run ended without preserving any repository content.

### D14: retention before complete

`complete` is the terminal command: it validates the semantic analysis, generates and stages the Report and Review Drafts, cross-checks every classification against raw evidence, builds the attested Mutation Report (schema v10), renders the canonical four-block surface, and performs cleanup in the same step. A retention question asked after rendering could no longer save anything, so the artifact-retention choice is resolved before `complete`, and the default `--retention discard` holds whenever no explicit keep choice was recorded. A `complete` failure is terminal: it cleans the disposable run, leaves the failure receipt, and requires a fresh run instead of retrying the deleted manifest.
