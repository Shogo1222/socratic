# Runner Architecture Decisions

Status: D1〜D5はv0.4 Prototypeで確定したDecisionであり、歴史的記録として保持する。D6〜D14はv0.5の正準Runner Pipelineとして出荷済みのDecisionである。両者を1つの判定基準が貫く。

判定基準は次です。

> これは推論か手続きか。推論はAgentが扱えるように残し、手続きはRunnerへ移す。

v0.5の正準Integrationはこの基準を端から端まで適用する。Host-gated Runner(`run_review.py`)が固定Pipeline——`preflight`、1回の`runbook`、範囲制限付き`inspect`、`scaffold-contract`、`stage-artifact`、任意の`execute --phase prepare`、1回成功する`probe-command`、`scaffold-plan`、1回の`challenge-batch`、`scaffold-analysis`、最後に`complete`——を所有し、AgentはRunnerがScaffoldした意味的Documentだけを供給して各Resultの`next.argv`に従う。Claude CodeではPlugin名前空間付きの`/socratic:socratic` Commandから実行が始まり、Host PluginがSkillの実行前にBrokerを起動して正確なPreflight Commandを注入する。

## v0.4 Prototypeの記録

D1〜D5は最初のVertical Sliceを当時の用語のまま記録する: 1回の`python-unittest` Round、既存Dependency、`replace-exact`／`delete-exact` Mutation、`attested: false`だけを発行できる`local-copy` Backend。このPathは`assess` Subcommandの背後でDifferential DevelopmentとDogfooding用に残り、正準Socratic Reviewには決して使用しない。

### D1: 型付きTest Profile

AgentはProfile固有の構造でTestを選び、argvやCLI Optionを指定できない。PrototypeはPythonのModule、Class、Method Identifierを受理する。Dependency Preparationは`use-existing`とし、将来のInstall ProfileではHost承認済みPreparation PhaseとOfflineのBaseline／Mutation実行を分離する。

将来のCustom Profileは、正確なargv、Working Directory、Environment Allowlist、Network Policy、承認Provenance、Profile DigestをHost Evidenceへ結び付ける。

### D2: Host所有のEvidence真正性

`run_nonce`はAgentから見えるため署名鍵にしない。将来の準拠Hostは署名鍵を非公開にし、任意の署名操作を公開しない。BrokerがPlan Pathを検証し、Trusted Runnerを自ら起動し、Runner完了後にHost StorageのCreate-once Evidence Pathを読み、その固定Documentへの署名を内部処理として行う。

署名はRun／Round Identity、Source・Plan・Runner・Evidence・Profile Digest、Host Adapter Identity、有効期間を束縛する。BrokerはRun／Roundごとの最小issued／consumed Stateを保持し、二重発行とReplayを拒否する。Agentから見えるSocket Credentialで任意ByteやPathへ署名できない。

Prototypeは署名を実装せず、`local-copy` Evidenceの`signature`は必ず`null`とする。

### D3: 型付きMutationの制限

1 Mutationは、明示列挙したTarget Path、Preimage Identity、順序付きOperationで構成する。RunnerがSource Materializationを所有する場合は`runner-computed`を使い、既に観測したPreimageを固定する場合だけ明示SHA-256を使う。Prototypeは1 Mutationあたり最大4 File、1 Fileあたり最大8 Operationを許可する。絶対Path、Backslash、親Traversal、glob、任意Python、任意Shell、Binary、SymlinkはRunner検証で拒否する。

Prototype Operationは`replace-exact`と`delete-exact`。どちらも一意な完全一致Textを要求する。Schema検証だけでは不十分であり、RunnerはPathを解決し、Symlinkを拒否し、明示Hashを使う場合は書き込み直前に検証し、実際のPreimage／Postimage Hashを記録し、変更総量を制限する。

### D4: RunとRoundのLifecycle

RunはSource Identity、Test Profile Digest、Prepared Snapshot、Preparation Evidenceを所有する。Prototypeは完全Baselineを伴う1 Roundを実装する。追加RoundはHash不変のPrepared Snapshotだけを再利用し、Fresh Mutation IDとProfileのBaseline Policyを使用する。Flaky除外を変更した場合は完全Baselineを再実行する。

Interpretationは同じRun／Source Identityを共有する1個以上のEvidence Bundleを受理する。解釈対象の各Mutationは、ちょうど1つのEvidence Entryへ対応しなければならない。

### D5: Execution Backend

`local-copy`は開発専用で、Attested Evidenceを生成できない。OS境界を確立しない。

準拠`isolated-host` Backendは次を満たす。

- Primaryを含めない、またはRead-only Mountにする
- HostがMaterializeしたSource Snapshotだけを実行する
- HOME、Temporary、Cache Directoryを隔離する
- Credentialと`SOCRATIC_*` Secretを渡さない
- Baseline／Mutation実行中のNetworkを無効にする
- CPU、Memory、Process数、時間を制限する
- CleanupをRunner所有の無条件処理にする

将来Dependency Downloadを許可する場合も、Production Credentialを持たず固定Lockfileを使うHost承認済みPreparation Phaseだけで行う。準拠Backendが署名済み`attested: true` Evidenceを発行するまでCanonical Reviewを生成しない。

### 実装済みPrototype

`run_review.py assess`は、1回のLocal Experimentを完結できる。Source Identityを計算し、Prepared Copyを作り、別Copyで完全Python unittest Baselineを実行し、各型付きMutationを別のFresh Copyへ適用し、Plan順のRaw Evidenceを返し、`finally`経路で全Disposable Workspaceを削除する。Baseline失敗時はMutationを実行しない。Test ProcessへCredentialと`SOCRATIC_*`値を渡さない。

Baseline前に、Testと同じSanitized Environmentから`jsonschema`と`referencing`をProbeする。Dependencyが不足する場合は、多数のTest Failureを発生させず、Mutationを実行せずに1件の構造化`runner-error`を生成する。EvidenceにはPython Implementation、Version、Executable Hash、Virtual Environment状態、Probe結果を記録する。Plugin Runtimeは、隔離`-I` Probeに成功した場合だけCurrent Interpreterを採用し、User Siteだけに依存する場合はPlugin管理Virtual EnvironmentをProvisionする。

このPathはIsolationや真正性を主張しない。`local-copy`はNetworkを無効化できず、OS境界も確立しない。Evidenceは常に未署名であり、正準Socratic ReviewとしてRenderしてはならない。

## v0.5正準PipelineのDecision

D6〜D14は、v0.5 Integrationとして出荷済みの正準PipelineのDecisionを記録する。基準は同じである: AgentはIntent、Accident、Interpretationを推論し、Runnerがすべての手続きを所有する。

### D6: Host-gated BrokerのGrant

正準Pipelineは自己申告では決して動かない。AgentがInvocationを処理する前にHost Pluginが起動するSession-scopedなHost Brokerが、`preflight`へRun Capabilityを付与する: Adapter Identity、32桁16進のRun ID、32文字以上のNonce、Primary Repository外の保護されたStorage、そしてAttest済みのProtection Mode(`os-read-only`、`permission-read-only`、`host-events`、`os-audit`のいずれか)である。PreflightはPrepared Source Snapshot——`.git`を持たないPrimaryのCopy——を`.socratic-disposable`でMarkした使い捨てSandbox内にMaterializeし、Change ContextとReview Typeの推奨をあわせて記録する。Standalone CLIは常に`blocked`を返し、自己申告のAttestation JSONを受理できない。Schema v10の`verified: true`は、信頼されたHostのAttestationをRunnerが受理したことを意味し、RunnerがOS境界を独立に検証したことを意味しない。

### D7: Runbookとnext.argvによる誘導

Pipelineを教えるのはSkillの散文ではなくRunnerである。Preflight直後にAgentは`runbook`をちょうど1回実行する: Mission、ID Glossary(DEC/INV/FX/UNR/CMD/MUT)、Gateの順序、Agentが編集してよいField、Hard Ruleを説明し、正確な次のCommandを返す。成功した各Runner Resultは`next.argv`を持ち、Agentは`<angle-bracket>` Placeholderだけを置き換えてそのまま実行する。引数の誤りは素のUsage Errorではなく、Runbookへ導く誘導付きJSONを返す。Phaseの遷移は`next.announce`から人間の目標として告知し、内部Command名では決して告知しない。

### D8: RunnerがScaffoldする意味的Document

Agentが編集するのは、保護されたHost Storage内のちょうど3つの意味的Input——`intent-contract.draft.json`、`challenge-plan.json`、`review-analysis.json`——であり、どれもRunnerのScaffoldから始まる: `scaffold-contract`、`scaffold-plan`(Probe成功後だけ利用でき、検証済みCommand IDを束縛する)、`scaffold-analysis`(Batch後だけ利用でき、PlanとRaw Outcomeを結合する。失敗したProcessは`inconclusive`から始まり、自動的に`killed`にはならない)。各ScaffoldはSchema-validな`document`、その絶対`artifact_path`、`editable_fields`、そしてRunner所有の`field_guide`——必須Key、許可されたEnum値、条件付きRule、Schema-validなElement Template——を返す。AgentはSchema Fileを決して読まず、Documentをゼロから再構築しない: 1回の`Write`でPathを作成し、修正は`Read`と`Edit`で行う。

### D9: Create-onceでStageするContractとHash-chained Ledger

`stage-artifact`はDraftを同梱Schemaで検証し、SHA-256とともにCreate-onceでIndexへ登録する。StageされたIntent Contractより前のMutationは拒否され、各Challengeは`contract_ids`を名指しし、未解決の`UNR-*` OracleへMapされたChallengeはBlockされたままになる。すべてのProbe、Guarded Write、Execution、Sealの各EventはNonceに束縛されたHash-chained Ledgerへ追記される。`complete`は、Guarded Write／Registration証跡とExecution証跡の両方をLedgerが保持するMutation IDだけを受理し、記録済みRaw Outcomeと矛盾する分類を拒否する。

### D10: 共有Dependency LayerとCopy-on-write Mutant Sandbox

Dependency Installは、Source Snapshotのsealより前に`execute --phase prepare`で最大1回だけ実行する。Probe成功後、Runnerは`node_modules`と認識済みPython Virtual Environmentを個別にHashした共有Dependency Layerへ移し、安定したLinkで再接続する。LayerのHashはCompletion前に再検証されるため、高速な共有がDependency改変を隠せない。その後、各Mutation IDはFreshなCopy-on-write Source Clone(Kernel CloneまたはReflink、FallbackはFull Copy)を受け取り、HOME、Temp、Cache Directoryを専有する——`node_modules/.vite`のようなRuntime CacheはSandboxごとに私有のままである——ので、通常のTest Cache書き込みがDependency Mutationに見えることはなく、Mutant同士が可変状態を共有することもない。

### D11: 1回の検証済みchallenge-batch

Mutation IDが存在する前に、`probe-command`が正確なFocused Test argvをPrepared SnapshotのFresh Cloneで実行し、成功した場合だけ再利用可能なCommand IDを記録する。Challenge PlanはそのCommand IDを束縛し、`replace-exact`と`delete-exact`のAnchor付きEditだけを含む。完全なSource File、Mutantごとのargv、Hash、Ledger Dataは決して埋め込まない。1回だけの`challenge-batch`は、各AnchorをPrepared Sourceに対して検証し、各Mutant Cloneを作成し、Editを自ら適用し、記録済みargvとcwdを`max_parallel`で制限した並列でそのまま実行し、Raw OutcomeをPlan順で返す。分類はすべてのRaw Outcomeが返った後だけ行う。

### D12: 誘導付きErrorと読み取り専用doctor

Tool GateはHosted Run中のAd-hoc診断を正当に拒否するため、失敗原因はRunner自身が名指しする。失敗したCommandは、上限付きstdout／stderr、Runnerが原因を認識した場合のEnvironment `hint`——`.git`を持たないPrepared Snapshot、Projectが拒否するInterpreter、解決しなくなったHOMEベースのTool Shim——、そして`diagnose.argv`を含む構造化JSONを返す。そのargvは`doctor`を実行する: SandboxのPATH、そこで解決するToolchain ExecutableとそのVersion、ProjectのInterpreterとBuild Backend要件、VCS Metadataの状況、最後に失敗したCommandを報告する、読み取り専用でSecret-freeなReportである。何も書き込まず、Ad-hocなShell調査を置き換える。

### D13: Host Storageに残すFailure Receipt

Terminalな失敗はSandbox、Artifact、Ledger、Manifestを削除するため、そのままでは何が起きたかの説明も消える。そこでRunnerは、Run ID、失敗したPhase、Error、Cleanup結果、PrimaryのPostflight HashがPreflightと一致したままかどうかを記録した、小さくSecret-freeな`failure-receipt.json`をHost Storageへ残す。ReceiptはRepositoryの内容を一切保持せずに、Runの終わり方を説明する。

### D14: completeより前のRetention確定

`complete`はTerminal Commandである: 意味的Analysisを検証し、ReportとReview Draftを生成してStageし、すべての分類をRaw Evidenceと突き合わせ、Attest済みMutation Report(Schema v10)を構築し、正準4ブロックSurfaceをRenderし、同じStepでCleanupを実行する。Render後に尋ねるRetention質問では何も保存できないため、ArtifactのRetention選択は`complete`より前に確定し、明示的なKeep選択が記録されていない限り既定の`--retention discard`が成立する。`complete`の失敗はTerminalである: Disposable Runを削除し、Failure Receiptを残し、削除済みManifestへの再試行ではなくFreshなRunを必要とする。
