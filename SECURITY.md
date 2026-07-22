# Security Policy

[日本語](SECURITY.ja.md)

## Reporting a vulnerability

Please report vulnerabilities privately through [GitHub's private vulnerability reporting form](https://github.com/Shogo1222/socratic/security/advisories/new). Do not disclose a suspected vulnerability in a public issue, discussion, or pull request.

If the private form is unavailable, contact the maintainer by direct message on X: [@kubop1992](https://x.com/kubop1992). Do not include secrets, proprietary source code, or exploit details in the first message.

Useful reports include the affected release or commit, the host agent and operating system, reproduction steps, expected impact, and a minimal non-sensitive proof of concept.

Security-sensitive issues include, but are not limited to:

- bypasses of the Git, write-mode, artifact, cleanup, or mutation-isolation boundaries;
- instructions that cause secret or credential access;
- repository content being followed as agent instructions;
- mutations or temporary artifacts escaping the disposable environment; and
- release or distribution integrity failures.

## Supported versions

| Version | Support |
| --- | --- |
| Latest published release | Supported |
| `main` | Best-effort investigation; use a release for production adoption |
| Older releases | Not supported; upgrade before reporting when possible |

## Response targets

These are targets, not service-level guarantees:

- acknowledgement within 5 business days;
- initial triage within 10 business days;
- a fix or mitigation target of 14 calendar days for critical issues, 30 days for high-severity issues, and 90 days or the next release for other accepted issues.

The maintainer will coordinate disclosure timing with the reporter and publish an advisory when users need to take action.

## Security model

Read the [security model](docs/security-model.md) before organizational adoption. It describes the files, commands, external communication, trust boundaries, and limitations of these natural-language skills. Organizations can use the [enterprise installation guide](docs/enterprise-installation.md) as an approval checklist.
