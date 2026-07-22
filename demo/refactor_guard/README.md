English | [日本語](README.ja.md)

# Refactor Guard demo

A change presented as a pure readability refactoring — extracting an `_is_active` helper — silently flips the expiry boundary. The same behavior probes run against Base and Head, and the diff appears as a fact, not a verdict. For the full session experience, read the [walkthrough](walkthrough.md) first.

## Story

[base.py](base.py) allows renewal through the exact end date. [head.py](head.py) claims to be a refactoring of it, but the extracted helper compares with `<` instead of `<=`, so renewal on the end date now raises `ExpiredSubscriptionError`.

Three behavior probes were generated against Base, observing outputs and exceptions only:

| Probe | Base | Head | Classification |
|---|---|---|---|
| renews well before the end date | pass | pass | preserved |
| rejects well after the end date | pass | pass | preserved |
| renews on the exact end date | pass | fail | behavior changed or removed |

The Base is treated as an observed fact, never as the specification. The demo ends with the question a real run would send to the specification owner: is this change intended? The bundled [intent-contract.json](intent-contract.json) records that question as unresolved, and [expected-elenchus-report.json](expected-elenchus-report.json) shows the completed Catch Mode run after the owner answered "unintended", classifying the diff as a strong catch.

## Run

From the repository root:

```bash
python3 -m demo.refactor_guard.run_demo
```

A successful demo prints the probe matrix, reports exactly one behavior diff, and exits with status `0`.

## Safety note

Base and Head are separate modules, so the demo never edits production code. This is a deterministic teaching fixture; real comparisons follow the snapshot isolation and postflight rules in the Elenchus safety contract.
