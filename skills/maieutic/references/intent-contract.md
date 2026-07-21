# Intent Contract

Persist the active contract at `.socratic/intent-contract.json`. Validate it with `intent-contract.schema.json`. YAML below is illustrative; the persisted form is JSON.

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
    provenance: user-confirmed | repository-established

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

## Contract quality checks

- Express decisions as observable behavior.
- Include important negative guarantees and side effects.
- Give each test a reason to exist by linking it to a contract ID.
- Keep inferences in `intent.evidence` and unresolved choices in `unresolved`.
- Do not leave expectations implicit when they control compatibility, security, money, permissions, or destructive behavior.
- Persist and validate the contract before handing it to another skill or session.
