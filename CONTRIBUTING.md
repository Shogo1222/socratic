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
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 scripts/audit_distribution.py
gh skill publish --dry-run
```

The distribution audit intentionally fixes the shipped Skill file set at 16 UTF-8 text files. Any added Skill resource, external URL host, executable bit, binary, or symbolic link requires an explicit audit-policy change in the same pull request.

## v0.2 scope

v0.2 narrows its target to changes where:

- an existing test environment is available;
- base and head can be run locally;
- return values, exceptions, state, and side effects are deterministically observable;
- Feature Review, Refactor Guard, or Test Assessment can be identified as the purpose;
- important behavior probes are limited to three to five;
- the same tests run on both base and head;
- only important mutations are selected;
- nothing is auto-posted to GitHub;
- comment candidates carry file names and line numbers;
- unverified scope and test-strategy trade-offs are always reported.

## CI and releases

GitHub Actions runs the same repository consistency check documented above for every pull request and push to `main`. It also validates Agent Skills metadata, runs the distribution-audit tests, rejects any unexpected, executable, binary, or symbolic-link file under `skills/`, restricts external URL hosts, verifies required safety rules, and performs an actual 16-file installation into a temporary directory. The file manifest and per-file hashes are uploaded as CI evidence. All third-party Actions are pinned to commit SHAs.

The root [`VERSION`](VERSION) file declares the next release version. Change it to the next semantic version in a pull request. After that pull request is merged to `main` and CI succeeds, the Release workflow checks out the exact validated commit and publishes the new version automatically. If the corresponding tag already exists, the workflow exits successfully without publishing a duplicate. Manual workflow dispatch remains available on `main` for recovery and reads the same `VERSION` file.

For a new version such as `0.2.1`, the workflow validates the repository, distribution, installation result, and version; creates an annotated `v0.2.1` tag; and publishes per-skill and suite ZIP files with `SHA256SUMS`, `SKILL_SHA256SUMS`, a JSON file manifest, and generated release notes.

The release workflow does not modify source files. The Git tag is the immutable identity of a published release. Published releases require repository release immutability and are verified together with every attached asset before the workflow succeeds. The immutable release attestation, rather than an Actions-held private signing key, is the first release trust anchor.

Verify a published release and a downloaded asset with GitHub CLI:

```bash
gh release verify v0.2.3 --repo Shogo1222/socratic
gh release verify-asset v0.2.3 ./socratic-v0.2.3.zip \
  --repo Shogo1222/socratic
```

Contributions are accepted under the repository's [MIT License](LICENSE) and are governed by the [Code of Conduct](CODE_OF_CONDUCT.md).
