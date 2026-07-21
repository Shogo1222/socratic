[英語正本](../../../skills/elenchus/SKILL.md)

> この文書は確認用の日本語訳です。実行時の正式な指示は英語正本です。

# Elenchus

プログラミング意図に対する、もっともらしい誤解でTest Suiteを反証する。Mutation Scoreではなく重要な振る舞いへの確信を目的とする。

## 必須の参照資料

Mutant生成前に[Intent駆動Mutation設計](elenchus-mutation-design.md)、コード変更・実行前に[Mutation安全Contract](elenchus-safety.md)を読む。同梱したIntent Contract、Mutation Result、Mutation ReportのSchemaで入出力を検証する。

## Intent Contractを取得する

次の順序で取得する。

1. ユーザー、Maieutic、またはSocratic Orchestratorから明示されたPath
2. リポジトリ内の`.socratic/intent-contract.json`
3. 現在の会話にある完全なContract

存在しない場合は停止し、`$maieutic`、統合された`$socratic` Workflowの実行、またはContract指定を求める。実装から確認済みIntentを再構築しない。別Pathの指定がなければ結果を`.socratic/elenchus-report.json`へ保存する。

## Modeと前提条件

### Harden Mode — Default

反証するOracleごとに`confirmed`または`tested`のContractを必要とする。確認済みIntentを変異させ、テストがCode Mutantを検知することを確認する。

### Catch Mode

Parent Revisionと提案Diffを特定できれば、`provisional`または`needs-decision`を許可する。ParentのRisk Mutantからテストを作り、提案Diffが同じ危険な振る舞いを持つか確認する。Catch結果は新しい判断を作り得るため、Intent確定済みと仮定しない。

どちらのModeでもRevision、変更・高リスク位置、対象テストコマンド、隔離方法、Baselineを特定する。実行可能なテストがない場合はMutation実行を停止し、Test Infrastructure選択をMaieuticへ戻す。許可なくFrameworkを追加しない。

## Baseline Policy

Baselineは使い捨てWorkspace内だけで実行する。失敗した場合は、失敗テストを分離して1回再実行する。再現する失敗は`baseline-red`として停止する。結果が変動する場合はFlakyとする。

Flaky Testを除外できるのは、安定したGreen Subsetが対象Contractを観測できる場合だけで、それ以外は`inconclusive`で停止する。Flakyまたは既存失敗をKillやSurviveの根拠にせず、縮小したScopeをReportへ記録する。

## Catch Mode Workflow

### 1. 暫定リスクを作る

提案DiffのIntentを暫定Contract IDへ対応付ける。巨大Diffは振る舞いまたはRisk Domainで分割し、重大な回帰を順位付けする。予算外の全項目を`not_challenged`へ記録する。

### 2. Parentを変異する

Parent Revisionへ少数のIntent-based Mutantを生成する。各Mutantについて、変異したIntent、Incident、Code Change、期待する検知、振る舞いとして意味がある根拠を記録する。

Harden ModeのStep 3・4・7にある隔離、1件ずつの実行、Timeout、復元、実行後確認を、Parentを未変異Baselineとして再利用する。

### 3. Candidate Catching Testを作る

次を満たすテストを生成または選択する。

1. 未変異ParentでBuild・成功する
2. Parent MutantでBuildされ、意図した振る舞いAssertionにより失敗する
3. Reflection、Private実装、無関係なInfrastructureへ依存しない

Compile Error、Missing Symbol、Test API変更、Test Runner Failure、無関係なExceptionはCatch Signalではない。

### 4. 提案Diffへ実行する

各Candidate Testを新しい使い捨てWorkspace内の提案Diffへ実行する。

- Parentで成功しDiffで振る舞いとして失敗: `weak-catch`
- 両Revisionで比較可能にBuild・実行できない: `not-comparable`
- InfrastructureまたはFlaky: `inconclusive`
- Diffで成功: Catchなし。確認済み挙動のHardeningに有用な場合だけ保持する

### 5. Weak Catchを解決する

ParentとDiffの最小の振る舞い差をMaieutic経由で提示する。Socraticが統合中の場合はSocratic経由で提示する。

- 人間が意図しないと回答: `strong-catch`
- 人間が意図したと回答: `false-positive`
- 無回答: `weak-catch`を維持して未解決判断を保存し、`needs-decision`で終了

古いOracleを持つCatching Testを追加しない。Intent確定後、有用なら期待する振る舞いのHardening Testへ書き換える。

## Harden Mode Workflow

### 1. リスク対象を順位付けする

変更をContract IDへ対応付け、Authorization、Privacy、Money、Data Integrity、Compatibility、不可逆効果、状態遷移、外部Interactionを優先する。

巨大変更は振る舞いまたはRisk Domainで分割し、選択Partitionごとに予算を割り当てる。通常は1回に3〜5件の多様で高価値なMutantを選ぶ。Mutantを割り当てなかった全Contract IDを、理由と残存リスク付きで`not_challenged`へ記録する。

### 2. Intent Mutationを生成する

確認済みIntent、近接した誤解、Incident、Severity・Likelihood、最小で原因特定可能なCode Change、検知すべき観測可能なテストを記録する。意味的欠陥とOmissionを優先し、従来Operatorは実際のRiskを表す場合だけ使う。

### 3. 隔離環境とBaselineを確立する

Safety規則に従い、主要WorkspaceのStatusとDiffを記録する。正確な対象状態を含む使い捨てWorkspaceを作り、**そのWorkspace内で**Baseline Policyを適用する。

### 4. Mutantを1件ずつ実行する

各Mutantを新しい使い捨てCopyへ単独適用し、Diffを確認して、安定した最小テストをTimeout付きで実行・分類する。次のMutant前に状態を破棄する。

- `killed`: 安定した関連テストが意図した振る舞い理由で失敗
- `survived`: 安定した関連テストが成功
- `invalid`: 意図したRiskを実行できない
- `equivalent`: 観測可能なContract差がないことを根拠で証明
- `timeout`: 実行上限超過
- `inconclusive`: Infrastructure、Flaky、無関係な失敗で判定不能

Compile FailureはCompile自体がContractでない限りKillではない。Equivalentには具体的な根拠を記録する。Contractにない観測可能な振る舞いを変えるMutantはMissing Invariant候補としてMaieuticへ戻し、Equivalentにしない。

### 5. Survivorを調査する

Scenario、Assertion、Boundary、副作用・状態遷移、曖昧仕様、実装依存、未到達Pathのどれが原因か特定する。未解決IntentはMaieuticへ戻し、`needs-decision`を保存して独立項目だけを続ける。

### 6. テストを追加して証明する

Contract解決済みなら、Mutantで失敗し元コードで成功する最小の振る舞いテストを追加する。主要WorkspaceへのTest変更は許可範囲内だけとする。

1. 元の本番コードと新テストが成功
2. 隔離Mutantと新テストが期待したAssertionで失敗

両方向を確認後、広い関連Suiteを実行する。Kill目的でAssertionを弱めたり本番コードを変更しない。

### 7. 復元状態を監査する

全Sandboxを破棄し、主要Workspaceを実行前証跡と比較する。本番Mutationがなく、許可されたTest・Doc変更だけが残ることを確認する。

## 永続化するReport

`.socratic/elenchus-report.json`を同梱Schemaで保存する。Mode、Contract Path、安定Baseline、Mutation分類、Catch結果と人間のVerdict、追加テストと双方向証明、全`not_challenged` ID、未解決判断、縮小Scope、本番Mutationがない実行後証跡を含める。

Mutation Scoreは補助情報であり成功基準ではない。予算切れをContract全体のHardening完了とみなさない。
