# Intent Contract

Maintain the active contract as a temporary run artifact validated with `intent-contract.schema.json`; write it to `.socratic/intent-contract.json` only when the user chooses local saving under the artifact policy. YAML below is illustrative; the stored form is JSON.

```yaml
version: 1
status: provisional | needs-decision | confirmed | tested | challenged | hardened
change:
  base: <revision-or-description>
  head: <revision-or-working-tree>
  summary: <observable behavior change>

intent:
  statement: <human-readable objective>
  confidence: high | medium | low
  evidence:
    - source: <path, issue, user answer, or command result>
      supports: <claim supported by this evidence>

decisions:
  - id: DEC-001
    question: <decision that changes the oracle>
    expected: <confirmed expectation>
    provenance: user-confirmed | repository-established | reviewer-selected-benchmark-assumption

invariants:
  - id: INV-001
    statement: <property that must remain true>
    severity: critical | high | medium | low

side_effects:
  required:
    - id: FX-001
      statement: <interaction or state change that must occur>
  prohibited:
    - id: FX-002
      statement: <interaction or state change that must not occur>

unresolved:
  - id: UNR-001
    statement: <remaining ambiguity>
    test_impact: <tests blocked by the ambiguity>

coverage:
  - contract_id: DEC-001
    tests:
      - <test name or path>
```

## Evidence precedence

Use this default precedence while respecting repository-specific authority:

1. explicit answer from the responsible human;
2. accepted specification, issue, or decision record;
3. public API contract and authoritative documentation;
4. pre-diff, untouched tests that pass Maieutic's test-quality review, plus consistent call-site expectations;
5. repository conventions and history;
6. current implementation.

Edited, weak, flaky, contradictory, or implementation-coupled tests cannot establish an oracle. Treat them as supporting evidence only. Conflicting evidence creates an unresolved decision; it does not authorize choosing the current implementation.

## Status lifecycle

`provisional` and `needs-decision` precede confirmation; `confirmed` requires every mapped oracle resolved. `tested` requires mapped passing tests that persist beyond the run. Elenchus advances the contract further: set `challenged` when risk-directed mutations have executed against those stable tests, and `hardened` when the selected high-risk mutants are killed and every unchallenged risk is explicit in the report. A Review-only proof that rests only on proposed, disposable tests never advances past `confirmed`.

## Contract quality checks

- Express decisions as observable behavior.
- Include important negative guarantees and side effects.
- Give each test a reason to exist by linking it to a contract ID.
- Keep inferences in `intent.evidence` and unresolved choices in `unresolved`.
- Do not leave expectations implicit when they control compatibility, security, money, permissions, or destructive behavior.
- Validate the contract and hand its artifact path to another skill or session; save it only on the user's explicit choice.
