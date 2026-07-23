# Narrow Runner Architecture Decisions

Status: accepted for the v0.4 prototype.

The decision rule is:

> Is this reasoning or procedure? Keep reasoning available to the agent; move procedure into the Runner.

The first vertical slice intentionally supports one `python-unittest` round, existing dependencies, `replace-exact` and `delete-exact` mutations, and a `local-copy` backend that can emit only `attested: false` evidence. It is for differential development and dogfooding, not canonical Socratic reviews.

## D1: typed test profiles

The agent selects tests through a profile-specific structure and cannot supply argv or CLI options. The prototype accepts Python module, class, and method identifiers. Dependency preparation is `use-existing`; later installation profiles must separate a Host-approved preparation phase from offline baseline and mutation execution.

A future custom profile must bind exact argv, working directory, environment allowlist, network policy, approval provenance, and profile digest to Host evidence.

## D2: Host-owned evidence authenticity

`run_nonce` is agent-visible and is not a signing key. A future compliant Host keeps its signing key private and exposes no arbitrary sign operation. The Broker validates a Plan path, launches the trusted Runner itself, reads the create-once Evidence path from Host storage after Runner completion, and signs that fixed document as an internal step.

The signature binds run and round identities, Source, Plan, Runner, Evidence and Profile digests, Host Adapter identity, and validity times. The Broker retains minimal issued/consumed state per run and round to reject duplicate issuance and replay. Agent-visible socket credentials never authorize signing arbitrary bytes or paths.

The prototype does not implement signing. Its `local-copy` evidence must contain `signature: null`.

## D3: typed mutation limits

One mutation contains explicitly listed target paths, preimage identity, and ordered operations. The prototype permits at most four files per mutation and eight operations per file. Use `runner-computed` when the Runner owns Source materialization; use an explicit SHA-256 only to pin a previously observed preimage. Absolute paths, backslashes, parent traversal, globs, arbitrary Python, arbitrary shell, binaries, and symlinks are rejected by Runner validation.

The prototype operations are `replace-exact` and `delete-exact`. Both require one unique, exact text match. Schema validation is necessary but not sufficient; the Runner resolves paths, rejects symlinks, verifies an explicit hash immediately before writing, records the actual preimage and postimage hashes, and enforces bounded aggregate change size.

## D4: Run and round lifecycle

A Run owns Source identity, Test Profile digest, Prepared Snapshot, and preparation evidence. The prototype implements one full-baseline round. Later rounds reuse only a hash-unchanged Prepared Snapshot, use fresh Mutation IDs, and follow the profile's baseline policy. Changing flaky exclusions requires another full baseline.

Finish will accept one or more Evidence Bundles sharing one Run and Source identity. Every interpreted mutation must map to exactly one Evidence entry.

## D5: execution backends

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

## Implemented prototype

`run_review.py assess` now performs one complete local experiment: it computes Source identity, creates a prepared copy, runs a full Python unittest baseline in a separate copy, applies each typed mutation to another fresh copy, returns raw Evidence in Plan order, and removes all disposable workspaces in a `finally` path. Baseline failure stops mutation execution. Environment credentials and `SOCRATIC_*` values are omitted from test processes.

This path is deliberately not an isolation or authenticity claim: `local-copy` cannot disable network or establish an OS boundary. Its Evidence is always unsigned and must never be rendered as a canonical Socratic review.
