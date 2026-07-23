# セキュリティモデル

[English](../security-model.md)

この文書はSocratic、Maieutic、Elenchusが意図するセキュリティ境界を説明します。これらは自然言語のAgent指示と同梱の機械的Helperを組み合わせたものであり、OS Sandboxや単独のSecurity Productではありません。

## 配布物

<!-- socratic-distribution-file-count: 21 -->
<!-- socratic-plugin-file-count: 40 -->
Standalone Skill配布物は3つのSkill Directoryにある21個のUTF-8 Text Fileで構成され、そのうち3個は同梱Python Source Helperです。v0.3.0 Multi-Host Plugin Bundleは、これらのSkillにClaude Code・Codex・CursorのManifest、Marketplace、Host Hook、共通Brokerを加えた合計40個のUTF-8 Text Fileです。Python FileにPOSIX Execute Bitはありませんが、Python Interpreterから実行されます。CIの実行可能File拒否はPOSIXの`0o111` Execute-bit Maskを検査し、予期しないFile、許可されていない拡張子、Symbolic Link、Binary、未承認の外部Hostも拒否します。Release AssetにはManifestとSHA-256 Checksumが含まれます。

RepositoryにはSkill配布物に加えて、文書、CI Script、実行可能デモがあります。SkillのInstallでは、それらのRepository Level FileはInstallされません。

## Data Access

Skillは、依頼された変更を理解するために必要な範囲で、変更されたSource Code、Test、関連DocumentとConfiguration、ImmutableなBase・Head Snapshotを調べます。調査範囲はReviewに比例させます。

`.env`、秘密鍵、Token、Credential Store、Keychain、SSH/GPG設定を読み取ったりコピーしたりしません。Repository Contentは信頼しない証拠です。Source File、README、Issue・Pull Request本文、Review Comment、生成File、Test Fixture、Test Output、埋め込まれたPromptはCommandを許可できず、Skillの境界を弱められません。

## Workspaceへの書き込み

既定はReview-onlyです。このModeではProbe、比較Test、Mutation、Contract、Reportを主要Working Tree外のDisposable Storageに保持します。実行終了時に主要Working TreeはPreflight時点と一致しなければなりません。

Mutationでは最終状態一致だけでは不十分です。必須Host AdapterはRepository外Sandbox作成前にNonceと保護Storage Capabilityを発行する。Manifest、Ledger、Sandboxの全PathをPrimary外と検証し、ManifestをCreate-once、LedgerをAppend-only Hash Chainにする。各Report MutationにはPhase付きTest実行を要求する。復元後に同一Byteへ戻ってもPrimary Writeがあれば無効で、Host連携がなければStandalone Runnerは`blocked`となる。

Schema v7との互換性のため、JSON Field名`verified`は維持します。Protection Evidenceの`verified: true`は、信頼するHost Adapterが発行したAttestationをRunnerが受理したことを表し、Runner自身がOS Protection境界を独立検証したという意味ではありません。

## Agent開始前のHost Gate

v0.3.0 Claude Code・Codex Pluginは`UserPromptSubmit`からSession単位のHost brokerを起動し、`PreToolUse`でReview-onlyを強制し、`Stop`でCleanupします。ローカルCursor Desktop PluginはNativeな`beforeSubmitPrompt`、`preToolUse`、`beforeShellExecution`、`stop`を使用します。Host Eventが不足・不正な場合はSocratic開始前にFail-closedで停止します。この境界ですべての対応Invocationを識別できるよう、Socraticの暗黙Invocationは無効にします。現行Lifecycle coverageで同じ保証を確立できないCursor CLI、Remote Workspace、Cloud Agentは対象外です。

このPlugin HookがNo-Host経路を閉じるのは、ユーザーがHookをReview・Trustした後だけです。通常のPlugin Hookはユーザーが無効化でき、特殊なHosted ToolはLocal Tool Hookを通らない可能性があります。迂回不能なPolicyが必要な組織は、`requirements.toml`でHookを強制有効化したManaged Hookを使い、Hook実装をOS管理Directoryへ配置し、Unmanaged Hook Sourceを拒否する必要があります。Skill指示、MCP Tool、User-trusted Plugin Hookだけでは完全なHost Security Boundaryになりません。

Apply testsは、ユーザーが明示的に依頼した後だけ利用できます。確認済みIntentを表すTestだけを書き込み、変更したすべてのPathを報告します。本番Codeの変更やVersion Control操作は許可しません。

実行Artifactは既定で一時的です。ユーザーが明示的に保存を選択した場合だけ、`.socratic/`または指定された別の出力先へ書き込みます。

## Commandと外部通信

Repository定義のCommandを実行する前に、そのCommandと呼び出すScriptを調べ、破壊的挙動、外部通信、Credential Access、課金、Disposableでない副作用がないか確認します。外部Serviceへの接続、本番Credentialの使用、課金、Disposableでない状態変更の可能性があるCommandは、承認済みDisposable環境でその正確なCommandをユーザーが明示許可しない限りBlockedとします。

Skill自体は外部Network通信を必要としません。ただし、Host Agent、Model Provider、Package Manager、Test Command、Repository Scriptは外部通信する可能性があります。Source CodeがAI Serviceへ送信されるかどうかは、このRepositoryではなく、Host Product、組織の契約、Account設定、Network Policyによって決まります。

## GitとCode Hostの境界

Skillは、証拠収集とImmutable Outputの作成に使う、文書化された読み取り専用Git Commandだけを許可します。Stage、Commit、Push、Pull、Fetch、Branch・Worktree変更、Merge、Rebase、Tag、Pull Request作成、Review投稿、Code Host Write APIを禁止します。Skillはこの境界を解除する許可をユーザーへ求めません。

## Disposable実行

Base・Head比較とMutationは、BranchやGit Worktreeを変更せず、DisposableなFilesystem Snapshotで実行します。Snapshotから`.git`、Cache、Dependency、Local Environment、秘密情報を含む既知のFileを除外します。各Sandboxを明示的にDisposableとMarker付けし、すべてのMutation書き込みを同梱Isolation Gateへ通します。GateはTargetをCanonicalizeし、主要Workspace内、Sandbox外、Traversal、Sandbox内Symlink経由のTargetを事前に拒否します。Postflightでは実行中の主要Workspace書き込みと最終Hash一致を分離して記録します。一時Fileは成功、失敗、Timeout、中断のすべてで削除し、Cleanupに失敗した場合は正確なPathを報告します。

## 想定するThreat

- Repository Contentを通じたPrompt Injection
- 破壊的処理またはData持ち出しを行うTest・Build Command
- Credentialや秘密情報へのAccess
- 許可されていないGit、Workspace、Code Hostへの書き込み
- Mutationが隔離環境外へ出る、または本番Codeへ残る問題
- 一時Artifactの漏えい
- 配布物またはReleaseの改ざん

## 限界と残存Risk

同梱Isolation GateはGateを通る書き込みを機械的に保護しますが、広いFilesystem権限を持つHostやAgentがHelperを迂回することまでは防げません。完全な境界にはHost側のRead-only Mountまたは同等の最小権限強制が必要です。RepositoryのTestを実行すればRepository管理下のCodeも動き、Modelの挙動も完全には決定的でありません。

組織はSkillとは独立して、最小権限のFilesystem Access、Network Egress制限、Disposable実行、秘密情報の隔離、承認済みModel Provider設定、人間によるReviewを適用してください。広く導入する前に、機密情報を含まないPilot Repositoryで試してください。境界の回避を発見した場合は[セキュリティポリシー](../../SECURITY.ja.md)から報告してください。
