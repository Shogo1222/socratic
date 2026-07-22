# Intent-Driven Mutation Design

Generate a mutant from a plausible wrong intent, then implement the smallest attributable code change that realizes it.

## Mutation record

Use the same fields from candidate generation through persisted result:

```yaml
id: MUT-001
mode: assessment | harden | catch
contract_ids: [INV-001]
source_intent: <confirmed behavior in Harden Mode or provisional evidence in Assessment/Catch Mode>
changed_intent: <nearby misunderstanding>
represented_risk: <failure or incident>
severity: critical | high | medium | low
likelihood: high | medium | low
code_change: <minimal realization>
code_location: <path and symbol>
expected_detection: <observable assertion or prohibited side effect>
result: <execution classification>
detecting_tests: [<test names>]
equivalence_evidence: <required when result is equivalent>
follow_up: <test, decision, or none>
```

In Assessment Mode, `source_intent` may be provisional assessment evidence rather than confirmed intent. State that limitation in `follow_up`; a kill proves detection of the represented behavior, not that the behavior is correct. Generate assessment risks before inspecting the changed tests' assertion details and include a holdout risk when the budget permits.

Reject a candidate if `changed_intent` cannot be stated independently of code syntax.

## High-value semantic axes

| Intent axis | Example misunderstanding |
|---|---|
| Boundary | Expiry is exclusive instead of inclusive |
| Population | Apply a rule to all users instead of eligible users |
| State transition | Permit a transition from a terminal state |
| Omission | Skip validation, cleanup, persistence, or notification |
| Side effect | Return the right value but omit or duplicate an external effect |
| Failure policy | Continue after partial failure instead of rolling back |
| Ordering | Publish before persistence instead of after commit |
| Idempotency | Retry repeats payment, event, or write |
| Time | Use local time, stale time, or the wrong equality behavior |
| Collection | Lose order, multiplicity, empty behavior, or one element |
| Authorization | Check authentication but not ownership or scope |
| Numeric behavior | Change rounding, sign, zero, maximum, or overflow policy |

## Traditional operators as realizations

Use `<`/`<=`, boolean or null reversal, condition negation, early-return removal, exception removal, constant changes, and off-by-one edits only after linking them to an intent axis and Contract ID.

Repository call, event, cache, and persistence deletion are valuable when the missing side effect represents an invariant. Do not delete arbitrary calls for score inflation.

## Selection

Prefer candidates with high severity, credible developer misunderstanding, clear observability, and minimal implementation scope. Avoid redundant mutants killed by the same assertion for the same reason. Record unselected Contract IDs rather than hiding the mutation budget.

## Mutant validity

A useful mutant must:

- compile or execute far enough to exercise the intended risk;
- differ observably from confirmed or provisional intent;
- preserve unrelated behavior sufficiently to attribute the failure;
- be reversible and isolated;
- have a plausible path to a test oracle.

Require evidence before using `equivalent`. Observable contract-silent behavior is a missing-invariant candidate, not equivalence.
