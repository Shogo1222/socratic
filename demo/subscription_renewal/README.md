English | [日本語](README.ja.md)

# Subscription renewal demo

This executable demo shows the full Socratic workflow from Maieutic to Elenchus without external dependencies or temporary production edits. For the full session experience — what the terminal shows and what you are asked — read the [walkthrough](walkthrough.md) first.

## Story

The weak tests check only a clearly expired account and the returned success value. They do not establish:

- behavior at the exact expiry boundary;
- whether a successful renewal charges the account;
- whether a retry is idempotent.

The [Maieutic session](maieutic-session.md) draws out those decisions and records them in [intent-contract.json](intent-contract.json). Elenchus then represents three plausible misunderstandings as prebuilt demo mutants and records the completed run in [expected-elenchus-report.json](expected-elenchus-report.json):

| Mutant | Changed intent | Risk |
|---|---|---|
| MUT-001 | Equality is still eligible | Renewal after expiry |
| MUT-002 | Success does not require charging | Service without payment |
| MUT-003 | Retry may charge again | Duplicate payment |

All three mutants survive [the weak tests](test_weak.py). After the confirmed intent is encoded in [the hardened tests](test_hardened.py), all three are killed.

## Run

From the repository root:

```bash
python3 -m demo.subscription_renewal.run_demo
```

Expected summary:

```text
Original / weak          PASS   baseline passes
MUT-001 / weak           PASS   SURVIVED
MUT-002 / weak           PASS   SURVIVED
MUT-003 / weak           PASS   SURVIVED
Original / hardened      PASS   baseline passes
MUT-001 / hardened       FAIL   KILLED
MUT-002 / hardened       FAIL   KILLED
MUT-003 / hardened       FAIL   KILLED
```

The failing test processes are expected and captured by the runner. A successful demo exits with status `0`.

## Safety note

The demo keeps mutants as separate modules so it never edits `subscription.py`. This is a deterministic teaching fixture, not the future production mutation runner. Real repository mutations must follow the isolation and postflight rules in the Elenchus safety contract.
