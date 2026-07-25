# Devloop

Iterate on the Socratic plugin without reinstalling or restarting: every run loads the
current working tree via `claude -p --plugin-dir`, reviews the same PR fixture, and
records the outcome for comparison.

Runs and fixtures live under `~/.socratic-devloop` (override with
`SOCRATIC_DEVLOOP_HOME`), outside the repository and outside the plugin root.

## Loop

```bash
# 1. edit plugin code, then run once (first run builds the fixture)
python3 tools/devloop/loop.py run --label after-gate-fix

# 2. see what changed against the previous run
python3 tools/devloop/compare.py

# 3. ask a headless agent for plugin fix proposals from the latest record
python3 tools/devloop/propose.py --backend claude
```

`tools/devloop/loop.py list` shows all runs with the plugin revision (and a working-tree digest when
dirty) that produced each one, so a result is always traceable to the exact code state.
`tools/devloop/loop.py clean-sessions` removes `/tmp/socratic-sessions` entries left by devloop
fixtures whose broker process is dead; live brokers are never touched.

## The fixture

`~/.socratic-devloop/fixtures/expiry_pr` is a two-commit git repository: base allows
subscription renewal through the end date (`<`), head rejects renewal on the end date
(`<=`), and the tests miss that boundary on both revisions. A healthy Socratic run
reports the boundary behavior difference and the test gap. Rebuild with
`--fresh-fixture`; review a real repository instead with `--target <path>`.

## What a run records

Each `~/.socratic-devloop/runs/<timestamp>-<label>/` contains `meta.json` (duration,
turns, errors, permission denials, plugin revision + content digest, per-check results,
new broker sessions), `transcript.jsonl` (every message), `review.md` (the canonical
four-block surface **extracted from the transcript** — the renderer emits it as a tool
result, so the final message alone cannot be trusted), `final-message.md`, copies of new
broker `state.json` files and surviving `host-storage` evidence (workspace payloads
excluded), and `proposal-*.md` files written by `propose.py`.

A run exits 0 only when every check passes: CLI exit 0, a result event with
`is_error=false` and `subtype=success`, the canonical surface extracted, the target
tree content-identical (HEAD + staged + unstaged + untracked contents digest), and no
broker session for the target left behind. `meta.json.checks` names any failure.

Records are written `0600` inside `0700` directories, and host tokens/nonces are
redacted before anything is persisted. `propose.py` treats run records as untrusted
data (prompt-injection guard) and runs the codex backend only with
`--sandbox read-only`, failing loudly if the flag is unsupported.

## Intent-question eval

`tools/devloop/intent_eval.py` measures one judgment: **does Socratic ask the human at the
right times?** When repository evidence already settles an expected observable behavior, a
run should record it (provenance `repository-established`, with citations the Runner
verifies) and spend no human question on it. When the repository does not settle it, the
run must ask and leave the oracle unresolved rather than claim the repository decided.

Two fixtures differ by exactly one sentence — same diff, same tests, same commit
subjects. `settled` states the boundary rule in `docs/renewal.md`; `unsettled` removes
that sentence and nothing else, so nothing in the repository decides which boundary is
intended.

```bash
python3 tools/devloop/intent_eval.py run --repeat 3 --fresh-fixture --label baseline
python3 tools/devloop/intent_eval.py report
python3 tools/devloop/loop.py clean-sessions   # the eval keeps artifacts on purpose
```

Each run is recorded through the same path as `loop.py run`, then scored into
`<record>/evaluation.json` (or `~/.socratic-devloop/evaluations/<run>/` when no record
directory was produced at all). One label per run:

| label | meaning |
| --- | --- |
| `correct-silent` | `settled`, no question, oracle recorded as repository-established **with** a citation |
| `correct-ask` | `unsettled`, and the run asked the human or kept the oracle unresolved |
| `spurious-question` | `settled`, but the run asked anyway: the answer was already in the repository |
| `missed-question` | neither asked, nor unresolved, nor backed by a citation — it proceeded on an oracle it never established |
| `unverified-claim` | **the dangerous cell**: an uncited `repository-established` decision, or an `unsettled` oracle silently recorded as repository-established |
| `inconclusive` | nothing was measured (no Contract in the record, unreadable record, infrastructure failure) |

`unverified-claim` is the failure that matters. A missed question costs a reviewer a
follow-up; a claim that the repository settled something it does not settle is the
harness reporting false confidence in its own oracle. `inconclusive` is never a pass:
`report` always prints a `not measured` section naming every excluded run and its
reason, and both commands exit non-zero unless every recorded run was measured and
correct. A silent run whose transcript contains the Markdown fallback question shape is
flagged as an advisory, because only the structured question tool (`AskUserQuestion`,
`request_user_input`) counts as asked.

Caveats, plainly: this measures agent judgment on two synthetic fixtures with a small
n. It does not prove behavior on real repositories, it aggregates provenance per
Contract rather than per decision (the fixtures carry one oracle each), and it scores
the recorded Contract and question tool calls — not the quality of the review. The eval
prompt asks for `--retention keep` so the Contract survives in the record, which leaves
the broker session alive and makes `loop.py`'s own `sessions_cleaned` check fail; the
Contract is otherwise recovered from the single `Write` in the transcript, without later
`Edit` corrections replayed. And headless sessions may render the decision prompt as
Markdown instead of calling the question tool, which reads as "stayed silent" — the
advisory exists for exactly that, and an interactive session is the stronger measurement.

The scoring functions are unit-tested in `tests/devloop/test_intent_eval.py`; the run
path has not yet been exercised against a live `claude` CLI, so treat the first `run` as
a smoke test of the harness as much as of the plugin.

## Limits

- Headless runs cannot answer `AskUserQuestion`; the default prompt tells the skill to
  take the recommended option and discard artifacts. Interactive decision-prompt UX
  still needs a manual session.
- `--plugin-dir` loads the repository root directly. The audited marketplace bundle is
  a different artifact — before a release, verify once through a real
  `/plugin marketplace add` + install.
- The fixture's `.claude/settings.json` allows all Bash inside the fixture only; the
  plugin's own PreToolUse gate stays active and is part of what runs verify.
- `propose.py --backend codex` requires a `codex` CLI on PATH.
- `intent_eval.py` scores what a run recorded. It cannot re-verify that a citation's
  quoted text exists, because the reviewed snapshot is gone by then; the Runner makes
  that check a precondition of staging the Contract.
