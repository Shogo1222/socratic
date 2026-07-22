English | [日本語](walkthrough.ja.md)

# Walkthrough: assessing AI-edited tests with `$elenchus`

A play-by-play of a standalone `$elenchus` session: the scope question, the cohort comparison, and the standalone assessment surface.

## 1. State

A PR where an AI "cleaned up" the pricing tests: it added one bulk-discount test, weakened the volume-boundary assertion to "some discount exists", and deleted the negative-quantity test as redundant. The suite is still green.

## 2. Run

```text
> $elenchus check whether the added unit tests are effective
```

## 3. Question (scope selection)

Before any mutant is generated, you are asked exactly one scope question, with detected file counts and rough cost attached to the options.

```text
┌ Question 1/1 ── assessment scope ──────────────────────────────┐
│ What should be assessed?                                       │
│                                                                │
│ ▸ 1. Current change: existing and changed tests (recommended)  │
│      Existing protection around pricing.py plus the effect of  │
│      the test changes                                          │
│      (1 production file / 2 test files / ~4 mutations)         │
│   2. Changed tests only                                        │
│      Faster; assesses the test diff without auditing the       │
│      existing suite                                            │
│   3. Broader target                                            │
│      Name a module or the whole repository; execution cost     │
│      increases                                                 │
└────────────────────────────────────────────────────────────────┘
You: 1. Current change
```

## 4. Terminal (comparison phase)

```text
Elenchus: built the existing cohort (pre-change tests) and the changed
  cohort (post-change tests) as disposable snapshots.

  Risks derived before inspecting assertion details (4, incl. 1 holdout).
  Running the same mutants against fresh copies of both cohorts...
```

## 5. Result (the standalone assessment surface)

```text
Assessment Scope:
  current change / pricing.py / tests_existing.py + tests_changed.py / 4 mutations

Existing Protection:
  ✓ omitting the volume discount was already detected before the change
    (the test edit is neutral for this incident)

Changed Test Contribution:
  + incremental protection: the new bulk-tier test detects "100 items
    not getting 20%" — nothing protected this before
  - protection regression: weakening the boundary assertion un-detects
    "the discount starting one item late"; the pre-change suite caught it

Still at Risk:
  △ accepting a negative quantity is detected by neither suite
  △ whether rejecting negative quantities is a requirement is unresolved
    -> recorded as a question for the specification owner (UNR-001)

Test Quality Concerns:
  ! test_volume_orders_get_some_discount asserts only "less than 1200";
    restoring an exact expected total is recommended

Working tree unchanged during this Review-only run.
Assessment only; no tests were created.
```

No merge verdict, no score. Behind the green suite, "one protection gained, one silently lost, one never there" is shown as-is.

## 6. Follow-up

```text
Harden the surviving gap? (requires confirmed intent)
You: not now

Run artifacts: Discard (default) / Save locally / Output as Markdown
You: Output as Markdown
  -> the assessment report is rendered into the chat (shareable with the team)
```

## Run this scenario yourself

```bash
python3 -m demo.test_assessment.run_demo
```

Reproduces the same 4-mutant × 2-cohort matrix and all four classifications in ten seconds.
