# Enterprise Installation Guide

[日本語](ja/enterprise-installation.md)

This guide is an approval checklist for using Socratic on an organization-managed computer. It does not replace your employer's security, legal, procurement, or AI-use policy.

## Before installation

Confirm all of the following with the responsible organization:

- the host agent and GitHub CLI are approved;
- the model-provider contract, data retention, training, and regional processing settings permit the repository's source code;
- the pilot repository contains no production credentials or regulated data;
- filesystem access and network egress follow least privilege;
- test commands can run in a disposable environment without production access or billable side effects; and
- the [security model](security-model.md) and [security policy](../SECURITY.md) have been reviewed.

Provide Python 3 with the runner's runtime dependencies in a Host-managed virtual environment or managed Python runtime, rather than installing them globally:

```bash
python3 -m pip install jsonschema referencing
```

If either dependency is unavailable, the mandatory runner fails closed and the review remains `blocked`.

## Verify a release

Use an immutable published release and pin the installation to its exact tag. Replace `v0.2.0` below with the approved release.

```bash
gh release verify v0.2.0 --repo Shogo1222/socratic
gh release download v0.2.0 --repo Shogo1222/socratic --pattern SHA256SUMS --pattern distribution-manifest.json
```

Preview the files and permissions before installing:

```bash
GH_TELEMETRY=false gh skill preview Shogo1222/socratic socratic@v0.2.0
GH_TELEMETRY=false gh skill preview Shogo1222/socratic maieutic@v0.2.0
GH_TELEMETRY=false gh skill preview Shogo1222/socratic elenchus@v0.2.0
```

<!-- socratic-distribution-file-count: 21 -->
<!-- socratic-plugin-file-count: 41 -->
The standalone Skill distribution contains 21 UTF-8 text files, including three Python source helpers. The audited multi-Host Plugin component set contains 41 UTF-8 text files across Claude Code, Codex, and local Cursor Desktop integration, including the Plugin-managed Python runtime bootstrap. A Claude Marketplace source checkout can contain additional repository-level files because its source is the repository root; those files are not part of the 41-file audited Plugin release asset. Those helpers have no POSIX execute bits but are run by a Python interpreter. The distribution audit's “executable” rejection specifically checks the POSIX `0o111` execute-bit mask. The audited distribution contains no binaries or symbolic links. Compare the preview with the release manifest and checksums.

For managed Codex deployment, do not rely on user-controlled Plugin hook trust. Deploy the pre-agent gate from an OS-managed absolute path through `requirements.toml`, force `[features].hooks = true`, and set `allow_managed_hooks_only = true`. Treat the v0.3.0 alpha as incomplete until that managed Host integration and a ready-run capability path are validated in the target environment.

## Install with project scope

Install into the current project only:

```bash
GH_TELEMETRY=false gh skill install Shogo1222/socratic \
  --all \
  --agent codex \
  --scope project \
  --pin v0.2.0
```

Project scope limits where the skill files are installed. It does not limit what the host agent can read or whether the model provider receives source code. Enforce those controls in the host, operating system, network, and organizational account.

## Pilot checklist

1. Start with a non-sensitive repository and no production credentials.
2. Run Socratic in its default Review-only mode.
3. Verify that the working tree is unchanged and no `.socratic/` artifact appears without an explicit save choice.
4. Confirm that Git writes, code-host writes, external-service tests, and credential-bearing commands are blocked.
5. Inspect the four-part result: Review This, We Verified, Still at Risk, and Copy-ready Comments.
6. Test interruption and failure paths and confirm that temporary paths are removed or reported.
7. Record the approved tag and checksum in the organization's software inventory.

Use Apply tests only after the team is comfortable with Review-only behavior and has explicitly requested the test changes. Continue to require normal code review for every applied change.

## Updating

Do not follow a moving branch for organizational use. Review the changelog, security impact, release manifest, and checksums for each new tag, then repeat the preview and pilot checks before changing the approved version.

To remove the skills, delete only the three project-scoped skill directories installed by the command after confirming their resolved paths: `socratic`, `maieutic`, and `elenchus`. Do not recursively delete a broader agent or project directory.
