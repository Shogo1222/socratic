# QA Technique Selection

Select techniques from changed behavior and risk; do not apply every technique mechanically.

| Signal in the change | Technique | Minimum questions for the test design |
|---|---|---|
| Input categories or modes | Equivalence partitioning | Which representative valid and invalid classes behave differently? |
| Comparisons, limits, ranges | Boundary-value analysis | What happens immediately below, at, and above each boundary? |
| Lifecycle or mutable status | State transition | Which transitions are allowed, rejected, and idempotent? |
| Multiple independent conditions | Decision table | Are meaningful combinations and precedence rules covered? |
| Validation or failure paths | Error and exception behavior | What is returned or thrown, and what must not happen afterward? |
| Calls, writes, messages, events | Side effects | Which effects are required, forbidden, ordered, or exactly-once? |
| Retryable commands or handlers | Idempotency | Does repetition preserve the result and avoid duplicate effects? |
| Clock, dates, expiration, scheduling | Time dependence | Are timezone, equality, rollover, and controllable clock cases covered? |
| Empty, singleton, many, duplicate data | Collections | Are order, multiplicity, filtering, and partial failure specified? |
| Counts, money, indices, arithmetic | Numeric boundaries | Are zero, negative, maximum, overflow, rounding, and off-by-one covered? |

## Risk filters

Prioritize tests that protect:

- authorization, privacy, money, data loss, or irreversible actions;
- backward compatibility and public contracts;
- externally visible side effects;
- behavior introduced or removed by the diff;
- branches whose intent required human confirmation.

Deprioritize tests that only mirror private control flow, assert mock call details without a contract reason, or duplicate an existing behavioral oracle.
