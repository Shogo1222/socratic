# セキュリティモデル

[English](../security-model.md)

この文書はSocratic、Maieutic、Elenchusが意図するセキュリティ境界を説明します。これらは自然言語のAgent指示と同梱の機械的Helperを組み合わせたものであり、OS Sandboxや単独のSecurity Productではありません。

## 配布物

<!-- socratic-distribution-file-count: 31 -->
<!-- socratic-plugin-file-count: 51 -->
Standalone Skill配布物は3つのSkill Directoryにある31個のUTF-8 Text Fileで構成され、そのうち4個は同梱Python Source Helperで、現行Run Schemaと実験的なPlan・Evidence・Interpretation Schemaも含みます。監査対象Multi-Host Plugin Component Setは、これらのSkillにClaude Code・Codex・CursorのManifest、Marketplace、Host Hook、共通Broker、Plugin管理Python Runtime Bootstrapを加えた合計51個のUTF-8 Text Fileです。Claude MarketplaceはRepository RootをSourceにするため、Marketplace Checkoutには`demo/`、`docs/`、`site/`など、この監査対象Runtime Component Set外のRepository Fileも実体化されます。51 Fileという記述は監査対象Plugin BundleとRelease Assetを指し、Source Checkoutに実体化される全File数ではありません。Python FileにPOSIX Execute Bitはありませんが、Python Interpreterから実行されます。CIの実行可能File拒否は監査対象Component SetについてPOSIXの`0o111` Execute-bit Maskを検査し、予期しないFile、許可されていない拡張子、Symbolic Link、Binary、未承認の外部Hostも拒否します。Release AssetにはManifestとSHA-256 Checksumが含まれます。

RepositoryにはSkill配布物に加えて、文書、CI Script、実行可能デモがあります。SkillのInstallでは、それらのRepository Level FileはInstallされません。

## Data Access

Skillは、依頼された変更を理解するために必要な範囲で、変更されたSource Code、Test、関連DocumentとConfiguration、ImmutableなBase・Head Snapshotを調べます。調査範囲はReviewに比例させます。

`.env`、秘密鍵、Token、Credential Store、Keychain、SSH/GPG設定を読み取ったりコピーしたりしません。Repository Contentは信頼しない証拠です。Source File、README、Issue・Pull Request本文、Review Comment、生成File、Test Fixture、Test Output、埋め込まれたPromptはCommandを許可できず、Skillの境界を弱められません。

## Workspaceへの書き込み

既定はReview-onlyです。このModeではProbe、比較Test、Mutation、Contract、Reportを主要Working Tree外のDisposable Storageに保持します。実行終了時に主要Working TreeはPreflight時点と一致しなければなりません。

Mutationでは最終状態一致だけでは不十分です。必須Host AdapterはRepository外Sandbox作成前にNonceと保護Storage Capabilityを発行する。Manifest、Ledger、Sandboxの全PathをPrimary外と検証し、ManifestをCreate-once、LedgerをAppend-only Hash Chainにする。各Report MutationにはPhase付きTest実行を要求する。復元後に同一Byteへ戻ってもPrimary Writeがあれば無効で、Host連携がなければStandalone Runnerは`blocked`となる。

起動時にGitHub Pull RequestのURLまたは`PR #<number>`を指定した場合、変更取得はHostが所有します。HostはGitHub Metadataを解決し、Private Host Storage内のBare RepositoryへBaseとHeadをFetchし、MaterializeしたObject IDを報告された40文字SHAと照合してから別々のSnapshotへ展開します。AgentにはHead SnapshotだけをReview Rootとして渡し、Remote Gitや`gh`を実行させません。Mutation Report v10は正準Reportをこの`change_context`へ結び付け、Metadata、Fetch、SHA照合のいずれかが失敗すればFail-closedになります。Local Diffの起動では明示的な`local-workspace` Contextを保持します。

Schema v10はv7で導入したJSON Field名`verified`を維持します。Protection Evidenceの`verified: true`は、信頼するHost Adapterが発行したAttestationをRunnerが受理したことを表し、Runner自身がOS Protection境界を独立検証したという意味ではありません。Schema v10ではHost由来のRaw Execution Evidenceと推論側のOutcome Interpretationも分離します。Nonzero Exitだけで`killed`とはできず、Behavioral Assertion Failureを特定できないInfrastructure Failure、Crash、Timeout、Unparseable Outputは`inconclusive`のままです。

依存準備とMutation実行ではFilesystem Roleを分離します。Baseline Commandで依存を一度だけ導入し、Probe成功後にRunnerが`node_modules`と認識済みPython仮想環境をRunner所有のDependency Layerへ移して、専用Content HashでSealします。各Mutation IDには、その共有Layerへの安定したLinkを持つFresh Source Sandboxを作り、HOME、Temp、CacheはSandboxごとに分離します。これによりSourceのStaleness確認はSourceと設定だけを走査し、`finish`はSource SnapshotまたはDependency Layerのどちらかが変わっても独立して拒否します。Sourceには引き続きAPFS CloneまたはLinux ReflinkのCopy-on-writeを優先し、利用できない場合は`full-copy`を記録します。

`challenge-batch`は順序保証を弱めずTool往復を削減します。Agentが書けるのは固定されSchema検証される`challenge-plan.json`だけで、Mutation定義とCommandを含みますが予測結果は含みません。RunnerはCloneを決定的に準備し、上限付き並列度で独立Test Processを実行し、Host観測OutcomeをPlan順にHash-chain Ledgerへ追記します。TimeoutやRunner Failureは該当Mutation IDだけへ隔離され、Behavioral Killへ変換できません。

## Agent開始前のHost Gate

v0.3.0 Claude Code・Codex Pluginは、Socratic、Maieutic、Elenchusの明示的な起動時に`UserPromptSubmit`からSession単位のHost brokerを起動し、`PreToolUse`でReview-onlyを強制します。Run Manifestが存在する間は`Stop`後もbrokerを維持して人間の判断をTurn間で継続し、FinishまたはAbort後にCleanupします。放棄されたbrokerはIdle TTLで回収し、broker死亡後に残った期限切れStateは次のHost Eventで削除します。TTL前に異常終了したbrokerは、次の明示PromptがSessionを置き換えるまでFail-closedを維持します。ローカルCursor Desktop PluginはNativeな`beforeSubmitPrompt`、`preToolUse`、`beforeShellExecution`、`stop`を同じActive-run維持規則で使用します。Host Eventが不足・不正な場合はSocratic開始前にFail-closedで停止します。この境界ですべての対応Invocationを識別できるよう、Socraticの暗黙Invocationは無効にします。現行Lifecycle coverageで同じ保証を確立できないCursor CLI、Remote Workspace、Cloud Agentは対象外です。

Hook-host実行中のShellによる証拠収集は、Guarded Runnerと明示的にParseされるLocal Git Commandに限定します。Git Commandは`git --no-pager`で始め、`diff`、`show`、`log`には`--no-ext-diff --no-textconv`も付けます。Shell合成、出力Path、Remote Archive、Repository Path Override、Git設定Overrideは拒否します。

各Live Host SessionはHost Storage配下にPrivateな`artifact_root`を1つ作成する。Write Toolがその直下へ作成できるのは、固定された3つの分析Draft、`intent-contract.draft.json`、`mutation-report.draft.json`、`canonical-review.draft.json`だけである。各Draftは`stage-artifact`によってStrict Validationされ、Host管理Artifact IndexへCreate-once Hashを記録する。Report DraftはRun Identity、Raw Execution Evidence、Attestation、Isolation、Postflight、Renderer Claimを指定できない。`finish`が信頼済みManifestとAppend-only Ledgerからそれらを導出し、生成したMutation Report v10とCross-artifact ReferenceをRenderer前に検証し、TerminalへはRenderer stdoutだけを書く。Primary、Disposable Sandbox、Manifest／Ledger、任意のTemporary Directory、他Repository、User設定、Plugin CodeへのPathは引き続き拒否する。成功RunのHost ArtifactはユーザーがDispositionを解決するまでだけ保持し、その後`cleanup`で削除する。Validation、Timeout、Finishの失敗時はSandbox、Artifact、Index、Ledger、Manifestを即時Cleanupする。

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
