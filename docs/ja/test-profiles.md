# Narrow Runner Test Profile

Test Profileは型付きSelectionを決定論的なRunner Commandへ変換する。Agentは意味上のTest Identityを選ぶが、argvを指定しない。

## Prototype Profile: `python-unittest`

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

## 後続Profile

PytestとNode Profileには、それぞれ固有の型付きSelection SchemaとParserが必要である。Custom argv Fieldで代用しない。Custom Profileは、Hostを介した人間の承認Protocolと署名済みProfile Digestが存在した後だけ許可する。
