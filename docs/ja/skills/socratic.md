[英語正本](../../../skills/socratic/SKILL.md)

> この文書は確認用の日本語訳です。実行時の正式な指示は英語正本です。

# Socratic

問答と反駁の完全なCycleを統合する。MaieuticでContractを発見・確定し、Elenchusでテストがそれを守るか反証する。人間の注意を未解決の仕様と重要な設計判断に集中させる。

## 必須スキル

次のSibling Skillを両方使う。

- `$maieutic`: 意図の引き出し、Intent Contractの永続化、QA Review、対象を絞ったテスト補完
- `$elenchus`: Catch ModeまたはHarden ModeによるMutation検証

いずれかが利用できない場合は、不足スキルを示してそのStageの前で停止する。安全性に関わるWorkflowを暗黙に簡略化しない。

## 運用原則

- Socraticを第三の仕様源ではなくOrchestratorとして扱う。
- Maieuticの判断境界を保ち、重要で観測可能なOracleまたは副作用を変える質問だけを行う。
- Elenchusの隔離境界を保ち、主要Workspaceに本番コードのMutationを残さない。
- Stage間で永続化した成果物を渡し、ContractまたはReportがある場合は会話の記憶だけに依存しない。
- TestまたはMutationを成功させるために確認済みDecisionを再解釈しない。
- 独立した人間の判断は、通常1〜3件の最小で有用な単位にまとめる。

## ワークフロー

### 1. Scopeを確定する

Diff、BaseとHead Revision、リポジトリ指示、影響する振る舞い、対象テストコマンド、Risk Partitionを特定する。対象外Partitionを明示し、通常のEnd-to-end依頼ではStandard Hardening Branch、意図確定前の提案変更が危険な振る舞いを持ち込んだか調べる場合はCatching Branchを選ぶ。

### 2. Maieuticを実行する

`$maieutic`を適用し、観測済み・推測・確認済み・未解決の意図を分離する。正当化できる判断だけを質問し、`.socratic/intent-contract.json`または変更別Pathを永続化・検証し、確認済み期待だけに対するテストをReview・補完する。Contract Path、Status、変更ファイル、テストコマンドと結果、Risk Rankingを受け取る。

関連項目が`needs-decision`の場合はその項目を一時停止し、独立した確認済み作業だけを続ける。未解決OracleにHarden Modeを開始しない。

### 3. Elenchusを実行する

正確なContract PathとMaieuticのHandoffを使って`$elenchus`を適用する。Standard Branchでは対象項目が`confirmed`または`tested`の場合だけHarden Modeを使う。Catching Branchでは、ParentとProposed Revisionを特定できれば`provisional`または`needs-decision`でCatch Modeを許可する。

隔離実行、安定したBaseline、1度に1つの帰属可能なMutant、明示的な`not_challenged`、本番Mutationが残っていない実行後証跡を必須とする。

### 4. 発見に応じてLoopする

- Oracle確認済みのテスト不足・弱さ: Elenchusで対象テストを追加し、双方向に証明する。
- Missing Invariantまたは曖昧なOracle: 具体的な振る舞いの質問としてMaieuticへ戻す。
- 意図したCatch Modeの振る舞い変更: `false-positive`を記録し、有用な場合はContractを更新する。
- 意図しない振る舞い変更: `strong-catch`を記録し、別途許可されない限り本番コードは変更しない。
- Invalid、Equivalent、Timeout、Flaky、Infrastructure結果: 分類と根拠を保持し、振る舞い上のKillに変換しない。

新しい人間の判断後はIntent Contractを更新・検証してからElenchusを再開する。より広いRegression Riskがなければ、影響するMutantだけを再実行する。

### 5. Cycleを完了する

必要な判断が確定または明示的に未解決で、元コードの対応テストが成功し、選択した高リスクMutantがKillまたは誠実に別分類され、未挑戦Contract IDと残存リスクが明示され、主要WorkspaceからMutationが除去され、ContractとElenchus Reportが最終状態を表す場合に完了する。

Mutation Score、Test数、Budget消費を信頼性と同一視しない。

## 最終報告

人間のReview Surfaceから報告する。残る判断と重要な設計選択、確認済み意図と保護したContract ID、変更テストと元コードの結果、CatchまたはHarden分類と双方向証明、未挑戦Scopeと残存リスク、Contract・Report Path、Mutation除去証跡を含める。人間の判断が残っていない場合は明示する。
