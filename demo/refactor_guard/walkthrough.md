English | [日本語](walkthrough.ja.md)

# Walkthrough: reviewing a "pure refactoring" with `$socratic`

A play-by-play of the session on a refactoring PR: what appears when a behavior diff is found, what you are asked, and what happens after you answer.

## 1. State

The PR description says "readability refactoring, no behavior change". The diff only seems to extract an `_is_active()` helper from `renew()`. In reality the comparison silently changed from `<=` to `<` during the extraction.

## 2. Run

```text
> $socratic review this refactoring PR
```

## 3. Terminal (comparison phase)

```text
Socratic: the change claims to preserve behavior — proceeding as Refactor Guard.

  Materializing Base and Head as disposable snapshots...
  - generated 3 probes observing important Base behavior
    (outputs and exceptions only; internal structure is never asserted)
  - running the same probes against both Base and Head

  Probe                          Base   Head
  renews well before the end     pass   pass
  rejects well after the end     pass   pass
  renews on the exact end date   pass   FAIL   <- behavior diff
```

## 4. Question (structured UI)

The Base is presented as an observed fact, never as the specification.

```text
┌ Question 1/1 ── behavior difference ───────────────────────────┐
│ This refactoring changes the expiry-boundary behavior          │
│                                                                │
│   Before: renewal succeeded on the exact end date              │
│   After:  ExpiredSubscriptionError                             │
│                                                                │
│ Is this change intended?                                       │
│                                                                │
│   1. Intended                                                  │
│      Recorded as the new expectation and pinned by a test      │
│ ▸ 2. Unintended                                                │
│      Reported as a regression introduced by the refactoring    │
│   3. Other (free text)                                         │
└────────────────────────────────────────────────────────────────┘
You: 2. Unintended
```

## 5. Result (the canonical four blocks)

```text
Socratic Review

Review This:
  (no human decision remains — the behavior diff was confirmed unintended)

We Verified:
  ✓ renewal before the end date and rejection after it are preserved
    (2 probes passing on both Base and Head)
  ✓ the boundary regression is detected by a probe proposed and proven
    in disposable workspace (strong catch)
  ✓ Working tree unchanged during this Review-only run

Still at Risk:
  △ the boundary probe is not applied yet
    the next regression of this kind is not auto-detected until it is

Copy-ready Comments:
  1 comment for subscription/renew.py:12
```

## 6. The comment candidate (paste-ready)

```markdown
This refactoring appears to change the expiry-boundary behavior.

When the contract end date equals the execution date, renewal succeeded
before the change and is rejected after it (ExpiredSubscriptionError).

Since this is described as a behavior-preserving refactoring, this may be
unintended. Could you either restore `<=` in the extracted _is_active, or
state the boundary change explicitly as the new specification?
```

Posting, editing, or discarding it is your call. Socratic never posts.

## 7. Follow-up

```text
Proven probe: Apply tests / Output patch / Discard
You: Output patch
  -> the test-only patch for the boundary probe is printed (working tree untouched)

Run artifacts: Discard (default) / Save locally / Output as Markdown
You: Discard
```

## Run this scenario yourself

```bash
python3 -m demo.refactor_guard.run_demo
```

Reproduces the same probe matrix up to the "is this change intended?" question in ten seconds.
