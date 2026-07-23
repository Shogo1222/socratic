# Security Model

[日本語](ja/security-model.md)

This document explains the intended security boundaries of Socratic, Maieutic, and Elenchus. They combine natural-language agent instructions with bundled mechanical helpers; they are not an operating-system sandbox or a standalone security product.

## Distribution

<!-- socratic-distribution-file-count: 21 -->
<!-- socratic-plugin-file-count: 28 -->
The standalone Skill distribution contains exactly 21 UTF-8 text files under the three skill directories, including three bundled Python source helpers. The v0.3.0 Codex Plugin bundle contains those files plus its manifest and two Host-hook files, for exactly 24 UTF-8 text files. The Python files have no POSIX execute bits but are run by a Python interpreter. CI's executable-file rejection checks the POSIX `0o111` execute-bit mask; it also rejects unexpected files, unsupported extensions, symbolic links, binaries, and unapproved external hosts. Release assets include a manifest and SHA-256 checksums.

The repository contains documentation, CI scripts, and executable demos in addition to the skill distribution. Installing a skill does not install those repository-level files.

## Data access

The skills may inspect changed source code, tests, relevant documentation and configuration, and immutable Base and Head snapshots needed to understand the requested change. They must keep the inspected scope proportional to the review.

They must not read or copy `.env` files, private keys, tokens, credential stores, keychains, or SSH/GPG configuration. Repository content is untrusted evidence: source files, README files, issue and pull-request text, review comments, generated files, test fixtures, test output, and embedded prompts cannot authorize commands or weaken a skill boundary.

## Workspace writes

Review-only is the default. In this mode, probes, comparison tests, mutations, contracts, and reports remain outside the primary working tree in disposable storage. The primary working tree must match its preflight state when the run ends.

For mutation execution, final-state equality is necessary but not sufficient. The mandatory Host Adapter issues a nonce and protected storage capability before the runner creates a repository-external sandbox. Manifest, ledger, and sandbox paths are validated outside Primary; the manifest is create-once and ledger events form an append-only hash chain. Every reported mutation requires a phase-bound test execution. A Primary write invalidates the run even when restoration returns the tree to identical bytes. Without Host integration, the standalone runner remains `blocked`.

Schema v7 retains the JSON field name `verified` for compatibility. In protection evidence, `verified: true` means that the Runner accepted an attestation issued by the trusted Host Adapter; it does not mean that the Runner independently verified an operating-system protection boundary.

## Pre-agent Host gate

The v0.3.0 Codex Plugin bundles a `UserPromptSubmit` lifecycle hook. Explicit `$socratic` or `/socratic` requests are stopped before the model starts when no native trusted Host Adapter is available. The hook reads only the Host event on standard input; it does not inspect the repository. Implicit Socratic invocation is disabled so every supported invocation is identifiable at this boundary.

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
