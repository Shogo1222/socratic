# Runner Test Profiles

Test Profileは、Test選択と実行の間の型付き境界である: Agentは何を実行するかを意味的に選び、決定論的なRunnerが正確なCommandを所有する。v0.5の正準Pipelineはこの境界を1つのProbe済みFocused Commandとして実現する。v0.4 Prototypeは型付き`python-unittest` Selectionとして実現しており、実験的なNarrow Runnerの記録として以下に保持する。

## 正準Profile: Probe済みFocused Command

正準RunnerはFramework固有のSelectionを解析せず、1つの検証済みCommandの周囲に境界を型付けする。AgentはPrepared Snapshot内の直接のTest Executableを`inspect search`で特定し、Sandbox相対のWorking Directoryとともに`probe-command`へ1回だけ提出する。

```text
<trusted-python> run_review.py probe-command \
  --manifest <host-manifest> \
  --command-id CMD-001 \
  --cwd <package-directory-or-dot> \
  -- <direct-test-executable> <focused-test-arguments>
```

HoistedなWorkspaceでは、典型的には`--cwd packages/<package>`を付けた`../../node_modules/.bin/vitest run <test file>`になる。RunnerはPrepared SnapshotのFresh Cloneでこのargvを実行し、成功したRunだけがCommand IDを記録する: `CMD-001`は正確なargv、Working Directory、Timeoutを束縛する。Challenge PlanはそのCommand IDを名指しし、`challenge-batch`は記録済みargvとcwdをすべてのMutantに対してそのまま再利用する——PlanはMutantごとのargvを供給できないため、すべてのMutationが同じ検証済みCommandで測定される。

`pnpm exec`や`npm run`のようなPackage Manager Wrapperではなく、直接のTest ExecutableをProbeする: WrapperはClone内でWorkspace Pathを再解決したりDependencyを再Installすることがあり、直接のBinaryはSeal済みの共有Dependency Layerに対して即座に実行される。SandboxのCommandはProject自身のToolchainを絶対Pathで使う。注入されたRuntime Pythonは`run_review.py`のためだけに存在する。

成功しなかったProbeは`blocked`を返し、上限付きのstdout／stderr Tail、Runnerが原因を認識した場合のEnvironment `hint`、そして2つの正確なFollow-up——読み取り専用`doctor` Reportのための`diagnose.argv`と、修正したProbeを再実行するための`next.argv`——を含む。`scaffold-plan`へ到達できるのは、検証済みCommand IDが存在した後だけである。

## Prototype Profile: `python-unittest`

v0.4のNarrow Runner実験は、この境界をCommandではなくSelection構造として型付けする。Agentは意味上のTest Identityを選ぶが、argvを指定しない。

Dependency Policy:

```json
{ "mode": "use-existing" }
```

Selection:

```json
{
  "modules": ["tests.runner.test_run_review"],
  "classes": ["RunReviewTest"],
  "methods": ["test_execute_records_timeout_before_failing"]
}
```

RunnerはPython Identifierを検証し、選択済みModule／Class内のMethodだけを解決し、内部でargvを構築する。ClassとMethodの空配列は、選択済みModule内の全Testを意味する。Test実行にNetwork Preparation Phaseはない。

Profile Parserは取得可能なら完全なunittest Test IDを返す。Outputを解析できなければ、Evidenceへ`failed_tests: null`を記録し、上限付きstdout／stderr Tailと全文Hashを保持する。

Runnerは内部で次を実行する。

```text
<trusted-python> -B -m unittest -v <derived-test-ids>
```

Prototypeは既存のGuarded Entrypointから呼び出す。

```text
<trusted-python> run_review.py assess \
  --source-root <host-review-root> \
  --plan <host-artifact-root>/experiment-plan.json \
  --evidence <host-artifact-root>/evidence-bundle.json
```

通常の1回呼び出しでは、SourceとTarget Preimage Identityに`runner-computed`を指定する。EvidenceはRunnerがCreate-onceで書き込み、Agentは`evidence-bundle.json`を作成・編集してはならない。

注入されたPythonは隔離Runtime Dependency Probeに成功しなければならない。Sanitized `HOME`で見えなくなるUser Site InstallationはTrusted Runtimeとして受理しない。Probe失敗時は`runtime.missing_dependencies`と`baseline.reason`を確認し、Behavioral Test Failureとして解釈しない。

## 後続Profile

正準Pathは直接のExecutableをProbeすることで追加のFrameworkを既にCoverしており、pytestやNodeのProjectにPrototype式のSelection Schemaは不要である。Narrow Runner実験自体を拡張する場合は、依然としてそれぞれ固有の型付きSelection SchemaとParserが必要であり、Custom argv Fieldで代用しない。CustomのPrototype Profileは、Hostを介した人間の承認Protocolと署名済みProfile Digestが存在した後だけ許可する。
