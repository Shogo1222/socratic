English | [日本語](README.ja.md)

# Demos

This directory answers one question: when you run `$socratic`, what appears in the terminal, what are you asked, how do you answer, and what comes back?

## Start with the walkthroughs (2 minutes each)

Three common situations, recorded as play-by-play sessions: starting state → run → investigation output → the structured question UI and your answer → result → follow-up questions.

1. [Reviewing a feature PR](subscription_renewal/walkthrough.md) — answer two specification questions and three critical incidents get detection tests, proven and offered with "apply them?"
2. [Reviewing a "pure refactoring"](refactor_guard/walkthrough.md) — a silently flipped expiry boundary is shown as a fact; answering "is this intended?" yields a paste-ready comment
3. [Assessing AI-edited tests](test_assessment/walkthrough.md) — behind a green suite, one protection was gained, one silently lost, and one never existed

## Then run the engines (10 seconds each)

The verification engine underneath each walkthrough is reproduced as a deterministic executable demo. Standard library only; production modules are never edited; the expected outcome exits `0`.

```bash
python3 -m demo.subscription_renewal.run_demo
python3 -m demo.refactor_guard.run_demo
python3 -m demo.test_assessment.run_demo
```

## About the fixtures

The bundled `intent-contract.json` and `expected-elenchus-report.json` files double as schema-conformance fixtures and together cover the Harden, Catch, and Assessment report modes. CI validates them against `schemas/`.

```bash
python3 scripts/validate_fixtures.py   # requires jsonschema, referencing
```

These demos are teaching fixtures with prebuilt mutants and cohorts. Real runs generate mutations and cohorts in disposable snapshots under the Elenchus safety contract; nothing here is the future production mutation runner.
