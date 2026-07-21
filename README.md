English | [日本語](README.ja.md)

# Socratic

Human-confirmed intent testing through inquiry and refutation.

Socratic is an end-to-end workflow that reduces code review to the behavior and design decisions requiring human judgment. Maieutic draws out intended behavior and completes its tests. Elenchus then challenges those tests with risk-directed, intent-based mutations.

> Maieutic makes unknown intent explicit. Elenchus attempts to refute the tests that claim to defend it. Socratic connects both into one auditable cycle.

## Why

Reviewing every line of AI-generated code does not scale. Fully delegating correctness to an AI does not work either: implementation cannot establish its own specification, and passing tests may contain weak or incorrect oracles.

This project creates a narrower human interface:

1. infer intent and risk from a change;
2. resolve only decisions that change important expectations;
3. encode those decisions as unit tests;
4. mutate the confirmed intent into plausible bugs;
5. prove the tests detect those bugs.

Humans remain responsible for ambiguous specifications and important design choices. The agent handles repository analysis, QA test design, test implementation, and adversarial validation.

## Architecture

```text
Code change
    |
    v
Socratic
  |
  +-- Maieutic
  |     - expose what is not known
  |     - infer observable intent from evidence
  |     - ask low-friction behavior questions
  |     - establish an Intent Contract
  |     - review and complete unit tests
  |
  +-- Elenchus
        - mutate confirmed intent
        - realize high-risk mutations in isolation
        - execute focused unit tests
        - return ambiguity to Maieutic
        - add and prove missing tests
    |
    v
Human review focuses on unresolved intent and design risk
```

The persistent [Intent Contract](docs/protocol.md), stored by default at `.socratic/intent-contract.json`, connects Maieutic and Elenchus. It is a small, traceable record of decisions, invariants, side effects, evidence, and test coverage. Socratic orchestrates the cycle without becoming another source of specification.

The names describe their relationship:

- **Socratic** is the whole method: recognize uncertainty, inquire, and test claims by refutation.
- **Maieutic** is the elicitation stage: help humans articulate intent the implementation cannot establish.
- **Elenchus** is the refutation stage: challenge whether tests actually defend that intent.

## Two verification modes

### Catch Mode

Generate tests that pass on a parent revision but fail on a risk mutant, then run them against the proposed change. A parent-pass/change-fail result is a weak catch until a human confirms whether the behavior change was intended.

### Harden Mode

After intent is confirmed, generate plausible wrong-intent variants of the changed code. A surviving mutant reveals a missing scenario, weak assertion, boundary gap, unobserved side effect, ambiguous specification, or implementation-coupled test.

## Repository layout

```text
skills/
  socratic/   End-to-end orchestration
  maieutic/   Intent elicitation and QA-driven unit testing
  elenchus/   Intent-based mutation validation
docs/
  protocol.md Shared concepts and lifecycle
schemas/
  intent-contract.schema.json
  mutation-result.schema.json
  mutation-report.schema.json
```

Each directory under `skills/` is an Agent Skill compatible with Codex and Claude Code. Install all three to use the integrated `$socratic` workflow. `$maieutic` and `$elenchus` can also be invoked independently when only one stage is needed.

## Installation

Install all three skills from [Shogo1222/socratic](https://github.com/Shogo1222/socratic).

With GitHub CLI's Agent Skills support:

```bash
gh skill install Shogo1222/socratic --all
```

Or with the open Agent Skills CLI:

```bash
npx skills add Shogo1222/socratic --skill '*'
```

Then invoke `$socratic` on a code change. Invoke `$maieutic` or `$elenchus` directly when only that stage is needed.

## Design principles

- Never treat implementation as specification.
- Ask only questions whose answers change an important oracle.
- Prefer observable before/after behavior over test-code review.
- Link every important test and mutation to a confirmed contract item.
- Prefer a few incident-representative mutations over mutation-score optimization.
- Never leave mutations in production code.
- Treat semantic intent mutations and traditional syntactic mutations as complementary; neither consistently subsumed the other across the evaluated tasks.

## Research foundation

This project is inspired by two complementary research directions, represented by three papers:

- [Harden and Catch for Just-in-Time Assured LLM-Based Software Testing](https://arxiv.org/abs/2504.16472) formally defines hardening tests, catching tests, and the Catching JiTTest Challenge.
- [Just-in-Time Catching Test Generation at Meta](https://arxiv.org/abs/2601.22832) applies that framing at industrial scale, reporting results for diff-aware and intent-aware catching tests and demonstrating low-friction human sense-checks for deciding whether changed behavior is expected.
- [Intent-Based Mutation Testing: From Naturally Written Programming Intents to Mutants](https://arxiv.org/abs/2607.05149) generates implementations from natural-language intent variants and finds partially non-overlapping mutant behaviors compared with syntax-based mutation in its 29-program evaluation.

Socratic connects these ideas. Our design adds elements that are not claims of either paper: the explicit human-confirmed Intent Contract, Maieutic intent elicitation, Contract-ID links between tests and mutations, incident-ranked mutation selection, explicit unchallenged risk, and the Elenchus hardening loop. Socratic is an independent open implementation, not an implementation published or endorsed by the paper authors or their institutions.

## Status

The project is at the initial skill-design stage. The protocol and agent workflows are usable, while deterministic language adapters and an isolated mutation runner remain future work.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the initial contribution boundaries.

## License

Socratic is available under the [MIT License](LICENSE).

Source: [github.com/Shogo1222/socratic](https://github.com/Shogo1222/socratic)
