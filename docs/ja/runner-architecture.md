# Narrow Runner Architecture Decision

Status: v0.4 Prototype向けに確定。

判定基準は次です。

> これは推論か手続きか。推論はAgentが扱えるように残し、手続きはRunnerへ移す。

最初のVertical Sliceは、1回の`python-unittest` Round、既存Dependency、`replace-exact`／`delete-exact` Mutation、`attested: false`だけを発行できる`local-copy` Backendに限定する。Differential DevelopmentとDogfooding用であり、正準Socratic Reviewには使用しない。

## D1: 型付きTest Profile

AgentはProfile固有の構造でTestを選び、argvやCLI Optionを指定できない。PrototypeはPythonのModule、Class、Method Identifierを受理する。Dependency Preparationは`use-existing`とし、将来のInstall ProfileではHost承認済みPreparation PhaseとOfflineのBaseline／Mutation実行を分離する。

将来のCustom Profileは、正確なargv、Working Directory、Environment Allowlist、Network Policy、承認Provenance、Profile DigestをHost Evidenceへ結び付ける。

## D2: Host所有のEvidence真正性

`run_nonce`はAgentから見えるため署名鍵にしない。将来の準拠Hostは署名鍵を非公開にし、任意の署名操作を公開しない。BrokerがPlan Pathを検証し、Trusted Runnerを自ら起動し、Runner完了後にHost StorageのCreate-once Evidence Pathを読み、その固定Documentへの署名を内部処理として行う。

署名はRun／Round Identity、Source・Plan・Runner・Evidence・Profile Digest、Host Adapter Identity、有効期間を束縛する。BrokerはRun／Roundごとの最小issued／consumed Stateを保持し、二重発行とReplayを拒否する。Agentから見えるSocket Credentialで任意ByteやPathへ署名できない。

Prototypeは署名を実装せず、`local-copy` Evidenceの`signature`は必ず`null`とする。

## D3: 型付きMutationの制限

1 Mutationは、明示列挙したTarget Path、Preimage Hash、順序付きOperationで構成する。Prototypeは1 Mutationあたり最大4 File、1 Fileあたり最大8 Operationを許可する。絶対Path、Backslash、親Traversal、glob、任意Python、任意Shell、Binary、Symlinkは後続Runner検証で拒否する。

Prototype Operationは`replace-exact`と`delete-exact`。どちらも一意な完全一致Preimageを要求する。Schema検証だけでは不十分であり、RunnerはPathを解決し、Symlinkを拒否し、書き込み直前にHashを検証し、変更総量を制限する。

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

## Prototype完了条件

1回のPlan呼び出しでLocal Copyを作り、完全Python unittest Baselineを実行し、Fresh Copyへ型付きMutationを適用し、Plan順の決定的Raw Evidenceを返し、全Disposable Workspaceを削除できればPrototypeは動作したとする。そのEvidenceを正準Socratic ReviewとしてRenderしてはならない。
