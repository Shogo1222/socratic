# Narrow Runner Architecture Decision

Status: v0.4 Prototype向けに確定。以下の判定基準と境界は、v0.5の正準Runner Pipelineにも適用される。

判定基準は次です。

> これは推論か手続きか。推論はAgentが扱えるように残し、手続きはRunnerへ移す。

v0.5の正準Integrationはこの基準を端から端まで適用する: Host-gated Runner(`run_review.py`)がPreflight、Runbook、範囲制限付きInspection、1回だけの依存準備、Focused CommandのProbe、Copy-on-write Mutation Sandbox、並列`challenge-batch`、ReportのAttestation、Render、Cleanupを所有し、AgentはRunnerがScaffoldした意味的文書だけを供給して各Resultの`next.argv`に従う。以下の各節は、確定済みDecisionを元のv0.4 Prototypeの用語で記録する。

最初のVertical Sliceは、1回の`python-unittest` Round、既存Dependency、`replace-exact`／`delete-exact` Mutation、`attested: false`だけを発行できる`local-copy` Backendに限定する。Differential DevelopmentとDogfooding用であり、正準Socratic Reviewには使用しない。

## D1: 型付きTest Profile

AgentはProfile固有の構造でTestを選び、argvやCLI Optionを指定できない。PrototypeはPythonのModule、Class、Method Identifierを受理する。Dependency Preparationは`use-existing`とし、将来のInstall ProfileではHost承認済みPreparation PhaseとOfflineのBaseline／Mutation実行を分離する。

将来のCustom Profileは、正確なargv、Working Directory、Environment Allowlist、Network Policy、承認Provenance、Profile DigestをHost Evidenceへ結び付ける。

## D2: Host所有のEvidence真正性

`run_nonce`はAgentから見えるため署名鍵にしない。将来の準拠Hostは署名鍵を非公開にし、任意の署名操作を公開しない。BrokerがPlan Pathを検証し、Trusted Runnerを自ら起動し、Runner完了後にHost StorageのCreate-once Evidence Pathを読み、その固定Documentへの署名を内部処理として行う。

署名はRun／Round Identity、Source・Plan・Runner・Evidence・Profile Digest、Host Adapter Identity、有効期間を束縛する。BrokerはRun／Roundごとの最小issued／consumed Stateを保持し、二重発行とReplayを拒否する。Agentから見えるSocket Credentialで任意ByteやPathへ署名できない。

Prototypeは署名を実装せず、`local-copy` Evidenceの`signature`は必ず`null`とする。

## D3: 型付きMutationの制限

1 Mutationは、明示列挙したTarget Path、Preimage Identity、順序付きOperationで構成する。RunnerがSource Materializationを所有する場合は`runner-computed`を使い、既に観測したPreimageを固定する場合だけ明示SHA-256を使う。Prototypeは1 Mutationあたり最大4 File、1 Fileあたり最大8 Operationを許可する。絶対Path、Backslash、親Traversal、glob、任意Python、任意Shell、Binary、SymlinkはRunner検証で拒否する。

Prototype Operationは`replace-exact`と`delete-exact`。どちらも一意な完全一致Textを要求する。Schema検証だけでは不十分であり、RunnerはPathを解決し、Symlinkを拒否し、明示Hashを使う場合は書き込み直前に検証し、実際のPreimage／Postimage Hashを記録し、変更総量を制限する。

## D4: RunとRoundのLifecycle

RunはSource Identity、Test Profile Digest、Prepared Snapshot、Preparation Evidenceを所有する。Prototypeは完全Baselineを伴う1 Roundを実装する。追加RoundはHash不変のPrepared Snapshotだけを再利用し、Fresh Mutation IDとProfileのBaseline Policyを使用する。Flaky除外を変更した場合は完全Baselineを再実行する。

Finishは同じRun／Source Identityを共有する1個以上のEvidence Bundleを受理する。解釈対象の各Mutationは、ちょうど1つのEvidence Entryへ対応しなければならない。

## D5: Execution Backend

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

## 実装済みPrototype

`run_review.py assess`は、1回のLocal Experimentを完結できる。Source Identityを計算し、Prepared Copyを作り、別Copyで完全Python unittest Baselineを実行し、各型付きMutationを別のFresh Copyへ適用し、Plan順のRaw Evidenceを返し、`finally`経路で全Disposable Workspaceを削除する。Baseline失敗時はMutationを実行しない。Test ProcessへCredentialと`SOCRATIC_*`値を渡さない。

Baseline前に、Testと同じSanitized Environmentから`jsonschema`と`referencing`をProbeする。Dependencyが不足する場合は、多数のTest Failureを発生させず、Mutationを実行せずに1件の構造化`runner-error`を生成する。EvidenceにはPython Implementation、Version、Executable Hash、Virtual Environment状態、Probe結果を記録する。Plugin Runtimeは、隔離`-I` Probeに成功した場合だけCurrent Interpreterを採用し、User Siteだけに依存する場合はPlugin管理Virtual EnvironmentをProvisionする。

このPathはIsolationや真正性を主張しない。`local-copy`はNetworkを無効化できず、OS境界も確立しない。Evidenceは常に未署名であり、正準Socratic ReviewとしてRenderしてはならない。
