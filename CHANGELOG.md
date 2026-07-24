# Changelog

Every release is published on [GitHub Releases](https://github.com/Shogo1222/socratic/releases) with generated notes, an annotated tag, ZIP assets, checksums, and attestation. This file summarizes the notable changes per version line; the release notes remain the per-tag detail.

## 0.5.0-alpha (integration preview, current)

- The Host-gated Runner (`run_review.py`) owns the canonical pipeline end to end: preflight, a Runner-generated runbook with `next.argv` guidance, bounded `inspect`, scaffolded semantic documents with `editable_fields` and `field_guide`, one-time dependency preparation sealed as a shared dependency layer, a probed focused command, copy-on-write mutation sandboxes with private runtime caches, one parallel `challenge-batch`, Mutation Report v10 attestation, the canonical four-block renderer, and terminal cleanup.
- Exact GitHub pull-request materialization by historical Base SHA; a session-scoped Host broker and `PreToolUse` tool gate for Claude Code, Codex, and local Cursor Desktop.
- Four Review Types (Bug Fix Review, Feature Review, Refactor Guard, Test Assessment) behind four human checkpoints.

**Migrating from 0.4**: invoke the plugin-namespaced command `/socratic:socratic` (Claude Code) or `$socratic` (Codex/Cursor) at the start of the prompt; canonical mutation mechanics moved out of the agent instructions into the Runner, and hand-driven `mutate`/`execute` sequences are replaced by the scaffolded plan plus one `challenge-batch`. The v0.4 `assess` prototype path remains available for dogfooding and still emits only unsigned, non-canonical evidence.

## 0.4.0

- Mission, Review Type, and Diff-understanding checkpoints; the deterministic local experiment Runner prototype (`experiment-plan` / `evidence-bundle` / `interpretation`); narrow Runner contracts and the isolated prototype Python runtime.

## 0.3.0

- Claude Code and Codex Plugin/Marketplace integration preview: session-scoped Host broker, pre-agent fail-closed gate, and Review-only tool enforcement.

## 0.2.x

- Initial public line of the three Agent Skills (Socratic, Maieutic, Elenchus) with the Intent Contract, mutation safety contract, canonical review surface, and release attestation workflow.
