# Devloop

Iterate on the Socratic plugin without reinstalling or restarting: every run loads the
current working tree via `claude -p --plugin-dir`, reviews the same PR fixture, and
records the outcome for comparison.

Runs and fixtures live under `~/.socratic-devloop` (override with
`SOCRATIC_DEVLOOP_HOME`), outside the repository and outside the plugin root.

## Loop

```bash
# 1. edit plugin code, then run once (first run builds the fixture)
python3 devloop/loop.py run --label after-gate-fix

# 2. see what changed against the previous run
python3 devloop/compare.py

# 3. ask a headless agent for plugin fix proposals from the latest record
python3 devloop/propose.py --backend claude
```

`loop.py list` shows all runs with the plugin revision (and a working-tree digest when
dirty) that produced each one, so a result is always traceable to the exact code state.
`loop.py clean-sessions` removes `/tmp/socratic-sessions` entries left by devloop
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
