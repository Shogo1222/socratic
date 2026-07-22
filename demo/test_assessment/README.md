English | [日本語](README.ja.md)

# Test Assessment demo

An AI "cleaned up" the pricing tests: it added one genuinely good test, weakened one assertion, and deleted one as redundant. Both suites are green. The cohort comparison shows what actually happened to protection. For the full session experience, read the [walkthrough](walkthrough.md) first.

## Story

[pricing.py](pricing.py) applies a 10% volume discount from 10 items and a 20% bulk discount from 100 items, and rejects negative quantities. The [existing tests](tests_existing.py) pin the volume boundary exactly; the [changed tests](tests_changed.py) are the suite after the AI's edit.

Four prebuilt mutants — each a plausible incident — run against fresh copies of both cohorts:

| Mutant | Incident | Existing | Changed | Classification |
|---|---|---|---|---|
| MUT-001 | discount starts one item too late | killed | survived | protection-regression |
| MUT-002 | volume discount omitted | killed | killed | existing-protection |
| MUT-003 | negative quantity accepted | survived | survived | unprotected |
| MUT-004 | bulk tier falls back to 10% | survived | killed | incremental-protection |

The one comparison delivers all four verdicts at once: the new bulk-tier test is real incremental protection, the weakened boundary assertion is a regression nobody would spot from a green run, the volume-discount omission was already covered, and negative quantities were never protected by either suite. The bundled [intent-contract.json](intent-contract.json) and [expected-elenchus-report.json](expected-elenchus-report.json) record the same run as Assessment Mode fixtures, with the unprotected gap routed to the specification owner as an unresolved decision.

## Run

From the repository root:

```bash
python3 -m demo.test_assessment.run_demo
```

A successful demo verifies both baselines, prints the comparison matrix, and exits with status `0`.

## Safety note

Cohorts and mutants are separate modules, so the demo never edits `pricing.py`. This is a deterministic teaching fixture; real assessments build cohorts in disposable snapshots per the Elenchus safety contract.
