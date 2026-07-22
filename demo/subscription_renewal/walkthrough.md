English | [日本語](walkthrough.ja.md)

# Walkthrough: reviewing a Feature Review PR with `$socratic`

This file is a play-by-play of a real session: what state you start from, what the terminal prints, what you are asked, how you answer, and what comes back.

## 1. State

A PR adds a subscription-renewal feature, `renew()`. There are only two tests — "reject when clearly expired" and "return success when valid" — and both are green. The expiry boundary, charging, and retry behavior cannot be established from the code.

## 2. Run

```text
> $socratic review this PR
```

## 3. Terminal (investigation phase)

```text
Socratic: proceeding as a Feature Review.

  Investigating...
  - change: subscription/renew.py (+31), tests/test_renew.py (+18)
  - snapshotted 2 tests existing at run start
  - dependency classification: charge (payment gateway) = out-of-process, unmanaged
    -> message content and count verified at the application boundary
  - 2 specifications cannot be established from the repository
```

## 4. Questions (structured UI)

The answerer is the specification owner. Every option carries the one-sentence test impact of choosing it.

```text
┌ Question 1/2 ── expiry boundary ───────────────────────────────┐
│ Should renewal succeed on the exact contract end date?         │
│                                                                │
│   1. Allow                                                     │
│      The end date stays inside the term; same-day renewal      │
│      success is pinned by a test                               │
│ ▸ 2. Reject                                                    │
│      Expired starting on the end date; same-day rejection is   │
│      pinned by a test                                          │
│   3. Other (free text)                                         │
└────────────────────────────────────────────────────────────────┘
You: 2. Reject

┌ Question 2/2 ── charging ──────────────────────────────────────┐
│ Across retries, how many times should a successful renewal     │
│ charge?                                                        │
│                                                                │
│ ▸ 1. Exactly once (recommended)                                │
│      A test forbids re-charging on retry                       │
│   2. Each retry may charge                                     │
│      No idempotency test is added                              │
│   3. Other (free text)                                         │
└────────────────────────────────────────────────────────────────┘
You: 1. Exactly once
```

## 5. Terminal (verification phase)

```text
Socratic: answers recorded in the Intent Contract (DEC-001, DEC-002).

  Designing and proving tests in a disposable workspace...
  - 3 proposed tests created
  - 3 critical incidents reproduced as mutations
  - passes on original code / fails on each mutant (both directions proven)
```

## 6. Result (the canonical four blocks)

```text
Socratic Review

Review This:
  (no human decision remains)

We Verified:
  ✓ 2 tests existing at run start were evaluated
  ✓ renewal after expiry is rejected — detected by a test proposed and proven in disposable workspace
  ✓ success without charging is detected — likewise proposed and proven
  ✓ double charging on retry is detected — likewise proposed and proven
  ✓ Working tree unchanged during this Review-only run

Still at Risk:
  △ 3 proposed tests not applied yet
    the protection above is not persistent until applied

Copy-ready Comments:
  (none — the specification was settled in this session)
```

## 7. The follow-up question

```text
┌ Proven tests ──────────────────────────────────────────────────┐
│ ▸ 1. Apply tests                                               │
│      Apply the verified patch to the working tree and repeat   │
│      the proof                                                 │
│   2. Output patch                                              │
│      Show the full patch without touching the working tree     │
│   3. Discard (default when unanswered)                         │
└────────────────────────────────────────────────────────────────┘
You: 1. Apply tests
```

## 8. Final state

```text
Socratic: handoff patch hash and preconditions verified; 3 tests applied.
  Re-proven: passes on original code, fails on each mutant.

Socratic Review (updated)

We Verified:
  ✓ 3 critical incidents detected by tests applied by this run after explicit request
  ✓ working tree changed: tests/test_renew.py

Still at Risk:
  (none remaining)

Keep the run artifacts (Intent Contract / report)?
  Discard (default) / Save locally / Output as Markdown
You: Discard
```

Nothing is committed or pushed. What happens to the applied tests stays with your normal Git flow.

## Run this scenario yourself

The executable demo in this directory reproduces the engine of the session above — weak tests missing three mutants, confirmed-intent tests killing them all — in ten seconds.

```bash
python3 -m demo.subscription_renewal.run_demo
```
