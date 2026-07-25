English | [日本語](CONTRIBUTING.ja.md)

# Contributing

Socratic is in its initial design stage. Contributions should preserve the central boundary: humans decide unresolved intent; automation gathers evidence and proves that tests protect the decision.

## Good first contribution areas

- realistic fixture repositories and end-to-end evaluation scenarios;
- language-specific test discovery adapters;
- deterministic isolated mutation execution;
- false-positive filters for generated tests;
- Intent Contract import and export integrations;
- documentation corrections and clearer behavioral examples.

## Requirements

- Do not treat current implementation behavior as authoritative specification.
- Add or update tests for executable changes.
- Keep production mutations isolated and automatically reversible.
- Link mutation operators to a behavioral risk rather than mutation-score growth.
- Avoid introducing a required hosted service into the core protocol.
- Document any command that can execute repository code or contact an external service.
- Update the matching Japanese document whenever an English user-facing document changes. English remains normative.
- Keep bundled skill schemas byte-identical to the normative files under `schemas/`.

Run repository consistency checks before submitting:

```bash
python3 scripts/check_repository.py
python3 -B -m unittest discover -s tests -t . -p 'test_*.py'
python3 -m demo.subscription_renewal.run_demo
python3 -m demo.refactor_guard.run_demo
python3 -m demo.test_assessment.run_demo
python3 scripts/validate_fixtures.py
python3 scripts/audit_distribution.py
gh skill publish --dry-run
```

`-B` prevents local `__pycache__` directories from contaminating distribution checks. Tests are grouped by concern under `tests/`; `-t .` keeps repository-root imports stable from every group.

Fixture validation needs `jsonschema` and `referencing` (`python3 -m pip install jsonschema referencing`); everything else uses the standard library.

The distribution audit intentionally fixes the shipped standalone Skill file set at 43 UTF-8 text files and the Plugin bundle at 63 UTF-8 text files. Any added Skill, Plugin manifest, Host hook, external URL host, executable bit, binary, or symbolic link requires an explicit audit-policy change in the same pull request.

## Current scope

The v0.5 integration preview targets changes where:

- a trusted Host (Claude Code, Codex, or local Cursor Desktop) can start the session broker and tool gate;
- an existing test environment is available and the focused test command can be probed locally;
- return values, exceptions, state, and side effects are deterministically observable;
- Bug Fix Review, Feature Review, Refactor Guard, or Test Assessment can be identified as the purpose;
- the Runner owns commands, disposable clones, mutations, schemas, hashes, reports, and cleanup — one prepared dependency layer, one probed focused command, one parallel challenge-batch;
- only important, intent-linked mutations are selected;
- nothing is auto-posted to GitHub;
- comment candidates carry file names and line numbers;
- unverified scope and test-strategy trade-offs are always reported.

## CI and releases

GitHub Actions runs the same repository consistency check documented above for every pull request and push to `main`. It also validates Agent Skills metadata and the pre-agent Plugin gate, runs the distribution-audit tests, rejects unexpected, executable, binary, or symbolic-link files in either distribution, restricts external URL hosts, verifies required safety rules, and performs an actual standalone Skill installation of the full audited file set into a temporary directory. Separate Skill and Plugin distribution manifests and per-file hashes are uploaded as CI evidence. All third-party Actions are pinned to commit SHAs.

Release conditions CI cannot prove — live per-Host fresh-install E2E runs — are tracked in the [release checklist](docs/release-checklist.md); notable changes per version line are summarized in the [changelog](CHANGELOG.md).

The root [`VERSION`](VERSION) file declares the next release version. Change it to the next semantic version in a pull request. After that pull request is merged to `main` and CI succeeds, the Release workflow checks out the exact validated commit and publishes the new version automatically. If the corresponding tag already exists, the workflow exits successfully without publishing a duplicate. Manual workflow dispatch remains available on `main` for recovery and reads the same `VERSION` file.

For a new version such as `0.5.0`, the workflow validates the repository, distribution, installation result, and version; creates an annotated `v0.5.0` tag; and publishes per-skill and suite ZIP files with `SHA256SUMS`, `SKILL_SHA256SUMS`, a JSON file manifest, and generated release notes. Prerelease identifiers such as `0.5.0-beta.1` are marked as prereleases automatically.

The release workflow does not modify source files. The Git tag is the immutable identity of a published release. Published releases require repository release immutability and are verified together with every attached asset before the workflow succeeds. The immutable release attestation, rather than an Actions-held private signing key, is the first release trust anchor.

Verify a published release and a downloaded asset with GitHub CLI:

```bash
gh release verify v0.5.0-beta.1 --repo Shogo1222/socratic
gh release verify-asset v0.5.0-beta.1 ./socratic-v0.5.0-beta.1.zip \
  --repo Shogo1222/socratic
```

Contributions are accepted under the repository's [MIT License](LICENSE) and are governed by the [Code of Conduct](CODE_OF_CONDUCT.md).
