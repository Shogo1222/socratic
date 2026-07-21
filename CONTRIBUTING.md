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
```

Contributions are accepted under the repository's [MIT License](LICENSE) and are governed by the [Code of Conduct](CODE_OF_CONDUCT.md).
