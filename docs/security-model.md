# Security Model

[日本語](ja/security-model.md)

This document explains the intended security boundaries of Socratic, Maieutic, and Elenchus. They combine natural-language agent instructions with bundled mechanical helpers; they are not an operating-system sandbox or a standalone security product.

## Distribution

<!-- socratic-distribution-file-count: 31 -->
<!-- socratic-plugin-file-count: 51 -->
The standalone Skill distribution contains exactly 31 UTF-8 text files under the three skill directories, including four bundled Python source helpers, the current run schemas, and the experimental Plan, Evidence, and Interpretation schemas. The audited multi-Host Plugin component set contains exactly 51 UTF-8 text files: those Skills plus Claude Code, Codex, and Cursor manifests, marketplaces, Host hooks, the shared broker, and the Plugin-managed Python runtime bootstrap. Claude Marketplace uses the repository root as its source, so its marketplace checkout can also contain repository files outside this audited runtime component set, such as `demo/`, `docs/`, and `site/`; the 51-file claim describes the audited Plugin bundle and release asset, not every file materialized by that source checkout. The Python files have no POSIX execute bits but are run by a Python interpreter. CI's executable-file rejection checks the POSIX `0o111` execute-bit mask; it also rejects unexpected files within the audited component set, unsupported extensions, symbolic links, binaries, and unapproved external hosts. Release assets include a manifest and SHA-256 checksums.

The repository contains documentation, CI scripts, and executable demos in addition to the skill distribution. Installing a skill does not install those repository-level files.

## Data access

The skills may inspect changed source code, tests, relevant documentation and configuration, and immutable Base and Head snapshots needed to understand the requested change. They must keep the inspected scope proportional to the review.

They must not read or copy `.env` files, private keys, tokens, credential stores, keychains, or SSH/GPG configuration. Repository content is untrusted evidence: source files, README files, issue and pull-request text, review comments, generated files, test fixtures, test output, and embedded prompts cannot authorize commands or weaken a skill boundary.

## Workspace writes

Review-only is the default. In this mode, probes, comparison tests, mutations, contracts, and reports remain outside the primary working tree in disposable storage. The primary working tree must match its preflight state when the run ends.

For mutation execution, final-state equality is necessary but not sufficient. The mandatory Host Adapter issues a nonce and protected storage capability before the runner creates a repository-external sandbox. Manifest, ledger, and sandbox paths are validated outside Primary; the manifest is create-once and ledger events form an append-only hash chain. Every reported mutation requires a phase-bound test execution. A Primary write invalidates the run even when restoration returns the tree to identical bytes. Without Host integration, the standalone runner remains `blocked`.

When an invocation names a GitHub pull request by URL or `PR #<number>`, the Host owns change acquisition. It resolves GitHub metadata, fetches Base and Head into a private bare repository under Host storage, verifies the materialized object IDs against the reported 40-character SHAs, and expands separate snapshots. The agent receives the Head snapshot as its review root and cannot invoke remote Git or `gh`. Mutation Report v10 binds the canonical report to this `change_context`; a metadata, fetch, or SHA mismatch fails closed. Local-diff invocations retain an explicit `local-workspace` context.

Schema v10 retains the JSON field name `verified` introduced in v7. In protection evidence, `verified: true` means that the Runner accepted an attestation issued by the trusted Host Adapter; it does not mean that the Runner independently verified an operating-system protection boundary. Schema v10 also separates Host-derived raw execution evidence from inference-owned outcome interpretation. A nonzero process exit cannot be reported as `killed` unless the analysis identifies a behavioral assertion failure; infrastructure failures, crashes, timeouts, and unparseable output remain `inconclusive`.

Dependency preparation and mutation execution use different filesystem roles. Baseline commands install dependencies once. After the successful probe, the Runner moves `node_modules` and recognized Python virtual environments into one Runner-owned dependency layer and seals that layer with its own content hash. Every Mutation ID receives a fresh source sandbox containing stable links to the shared layer; HOME, temp, and cache directories remain private to that sandbox. Source staleness checks therefore traverse only source and configuration, while `finish` independently rejects either a changed source snapshot or a changed dependency layer. The Runner still prefers APFS clone or Linux reflink copy-on-write for source and records `full-copy` when neither is available.

`challenge-batch` reduces tool round trips without weakening ordering. The agent writes only the fixed, schema-validated `challenge-plan.json`; it contains mutation definitions and commands but no predicted results. The Runner prepares clones deterministically, executes independent test processes with bounded parallelism, and appends their Host-observed outcomes to the hash-chained Ledger in plan order. Timeout or runner failure is isolated to its Mutation ID and cannot be converted into a behavioral kill.

## Pre-agent Host gate

The v0.3.0 Claude Code and Codex Plugins start a session-scoped Host broker from `UserPromptSubmit` for explicit Socratic, Maieutic, or Elenchus invocation and enforce Review-only through `PreToolUse`. `Stop` preserves a broker while its run manifest exists, allowing human decisions across turns, and cleans it after finish or abort; an idle TTL collects abandoned brokers, and a later Host event removes expired stale state after a broker has died. A broker that dies before TTL remains fail-closed until the next explicit prompt replaces its session. The local Cursor Desktop Plugin uses its native `beforeSubmitPrompt`, `preToolUse`, `beforeShellExecution`, and `stop` events with the same active-run retention rule. A missing or malformed Host event fails closed before Socratic runs. Implicit Socratic invocation is disabled so every supported invocation is identifiable at this boundary. Cursor CLI, remote workspaces, and cloud agents are excluded because their current lifecycle coverage cannot establish the same guarantee.

During an active hook-host run, shell evidence collection is limited to the guarded Runner and explicitly parsed local Git commands. Git commands must start with `git --no-pager`; `diff`, `show`, and `log` must also include `--no-ext-diff --no-textconv`. Shell composition, output paths, remote archive access, repository-path overrides, and Git configuration overrides are rejected.

Each live Host session creates one private `artifact_root` under Host storage. Write tools may create only the three fixed analysis drafts directly below that root: `intent-contract.draft.json`, `mutation-report.draft.json`, and `canonical-review.draft.json`. Each draft is strictly validated and create-once hashed into a Host-managed artifact index by `stage-artifact`. The Report draft cannot supply run identity, raw execution evidence, attestation, isolation, postflight, or renderer claims. `finish` derives those facts from the trusted Manifest and append-only Ledger, validates the resulting Mutation Report v10 and cross-artifact references before rendering, and writes only renderer stdout to the terminal. Paths in Primary, the disposable Sandbox, Manifest or Ledger locations, arbitrary temporary directories, other repositories, user configuration, and Plugin code remain denied. Successful runs retain Host artifacts only until the user resolves their disposition; `cleanup` then removes them. Any validation, timeout, or finish failure cleans the Sandbox, artifacts, index, Ledger, and Manifest immediately.

This plugin hook closes the no-Host path only after the user has reviewed and trusted it. A user can disable a normal plugin hook, and specialized hosted tools may not pass through local tool hooks. Organizations that require a non-bypassable policy must deploy a managed hook with hooks forced on through `requirements.toml`, keep the hook implementation in an OS-managed directory, and deny unmanaged hook sources. A Skill instruction, an MCP tool, or a user-trusted Plugin hook alone is not a complete Host security boundary.

Apply tests is available only after an explicit user request. It may write only tests that represent a confirmed intent and must report every changed path. It does not authorize production-code changes or version-control operations.

Run artifacts are ephemeral by default. A skill writes a local `.socratic/` artifact or another requested output only after the user explicitly chooses to preserve it.

## Commands and external communication

Before running a repository-defined command, the skill must inspect the command and the scripts it invokes for destructive behavior, external communication, credential access, cost, and non-disposable side effects. A command that may contact an external service, use production credentials, incur cost, or modify non-disposable state is blocked unless the user explicitly authorizes that exact command in an approved disposable environment.

The skills do not require external network communication. However, the host agent, model provider, package manager, test command, or repository script may communicate externally. Whether source code is sent to an AI service is controlled by the host product, organizational contract, account settings, and network policy—not by this repository.

## Git and code-host boundary

The skills permit only the documented read-only Git commands used to collect evidence and create immutable output. They prohibit staging, commits, pushes, pulls, fetches, branch or worktree changes, merges, rebases, tags, pull requests, review posting, and code-host write APIs. The skills must not ask the user to waive this boundary.

## Disposable execution

Base and Head comparisons and mutations run in disposable filesystem snapshots without changing branches or Git worktrees. The snapshot excludes `.git`, caches, dependencies, local environments, and known secret-bearing files. Each sandbox is explicitly marked disposable, and every mutation write is routed through the bundled Isolation Gate, which canonicalizes the target and rejects primary, out-of-sandbox, traversal, and sandbox-local symlink targets before writing. Postflight records primary writes during the run separately from final hash equality. Temporary files must be removed on success, failure, timeout, or interruption; cleanup failures are reported with their exact paths.

## Threats considered

- prompt injection through repository content;
- destructive or exfiltrating test and build commands;
- credential and secret access;
- unauthorized Git, workspace, or code-host writes;
- a mutation escaping isolation or remaining in production code;
- temporary artifact leakage; and
- distribution or release tampering.

## Limitations and residual risk

The bundled Isolation Gate mechanically protects writes routed through it, but it cannot prevent a host or agent with broad filesystem access from bypassing the helper. Host-level read-only mounts or equivalent least-privilege enforcement remain required for a complete boundary. Running repository tests also executes repository-controlled code, and model behavior is not perfectly deterministic.

Organizations should enforce least-privilege filesystem access, network egress restrictions, disposable execution, secret isolation, approved model-provider settings, and human review independently of the skill. Use a non-sensitive pilot repository before broader adoption. Report a boundary bypass through the [security policy](../SECURITY.md).
