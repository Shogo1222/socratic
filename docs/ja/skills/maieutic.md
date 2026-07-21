[英語正本](../../../skills/maieutic/SKILL.md)

> この文書は確認用の日本語訳です。実行時の正式な指示は英語正本です。

# Maieutic

コード差分を、少数の人間による判断と、永続化された実行可能な単体テストContractへ変換する。コードは意図を推測する根拠として扱い、最終仕様とはみなさない。

## 必須の参照資料

判断を記録する前に[Intent Contract](maieutic-intent-contract.md)を読み、保存したContractを同梱Schemaで検証する。テスト選択時は[QA技法の選択](maieutic-qa-techniques.md)を読む。

## 運用原則

- 複数の合理的な回答が観測可能な期待値または重要な副作用を変える場合だけ質問する。
- リポジトリ指示、Issue、権威あるドキュメント、呼び出し元、履歴、品質確認済みの根拠から分かることは質問しない。
- 観測された振る舞い、推測した意図、確認済みの意図、未解決の意図を区別する。
- 抽象的な仕様質問より具体的な振る舞い比較を優先する。
- リスクと人間の確認コストを最小化する。
- ユーザーが別途許可しない限り、テストを通すために本番コードを変更しない。
- 確認済みの期待値だけをテストへ追加し、疑わしいバグを回帰テストとして固定しない。

## ワークフロー

### 1. 変更範囲を確定する

現在のBranchまたはユーザー依頼から対象DiffとBase Revisionを特定する。リポジトリ指示、Test Framework、対象テストコマンド、変更ファイル、近接する呼び出し元とDomain Type、既存テスト、Issue・PR・Commit・ドキュメントを確認する。

Baseが曖昧でも低リスクに推測できる場合は前提を明示する。巨大Diffは独立して観測可能な振る舞いまたはRisk Domainで分割し、現在のReview Budgetに含む／含まない範囲を示す。

テストがない場合、既に設定済みまたは言語標準のFrameworkで選択が明確なら利用する。それ以外はTest Infrastructure不足を報告し、FrameworkやDependency追加前に許可を得る。

### 2. 振る舞いモデルを作る

観測可能な変更、推測した意図と根拠、影響する入力・出力・状態遷移・例外・副作用、起こり得る回帰、未確定の期待値を要約する。編集行の言い換えではなく、変更前後の振る舞いを説明する。

### 3. 人間への質問を判定する

次のすべてを満たす場合だけ質問する。

1. 少なくとも2つの妥当な期待値が残る
2. リポジトリの根拠では解決できない
3. 回答がTest Oracle、互換性、重大な副作用を変える
4. 誤った推測に無視できないコストがある

通常は関連する1〜3件へ絞り、状況に合う形式を使う。

```text
振る舞いの変化:
  変更前: <観測可能な振る舞い>
  この変更後: <観測可能な振る舞い>
  この変化は期待どおりですか？

選択肢:
  判断: <質問>
  Option A: <期待値とテストへの影響>
  Option B: <期待値とテストへの影響>

新しい振る舞い:
  提案された振る舞い: <以前の挙動がない新規機能>
  必要な判断: <境界、失敗方針、副作用>
  テストへの影響: <回答でオラクルがどう変わるか>
```

人間の判断が必要な理由を1文で加える。

### 4. Intent Contractを永続化する

安定したIDを付け、情報を次のとおり振り分ける。

- 明示的回答はDecisionの`user-confirmed`
- 権威あるリポジトリ根拠はDecisionの`repository-established`
- 未確認の推論は`intent.evidence`であり`decisions`には入れない
- 未解決のオラクルは`unresolved`であり`decisions`には入れない

現在のContractを既定で`.socratic/intent-contract.json`へ保存し、同梱Schemaで検証する。確認のたびに更新してPathを報告する。既存ファイルが別の変更を表す場合は上書きせず、`.socratic/contracts/<change-id>.json`へ保存してElenchusへ明示的に渡す。

関連する未解決項目がある間は`needs-decision`、必要な判断が解決したら`confirmed`、対応テストが成功したら`tested`にする。

必要な質問が無回答なら未解決として永続化し、その振る舞いを`needs-decision`で停止する。独立した確認済み項目だけを続行する。非対話実行では一度だけ判断事項を報告して終了し、Pollingや回答の捏造をしない。

### 5. 既存単体テストをレビューする

テストをDecisionとInvariantへ対応付け、関連するQA技法だけを選ぶ。既存テストを仕様根拠に使えるのは、Diffより前から存在し、Diffで未変更で、この品質Reviewを通過した場合だけとする。変更済み、弱い、矛盾、Flaky、実装依存のテストは推論の補助にしか使えない。

不足をScenario、Assertion、Boundary、状態・副作用、実装依存、曖昧仕様へ分類する。Coverageだけを増やすテストは追加しない。

Unit Testで観測不能なArtifactには、Schema Validation、Parser Check、Migration Dry Run、Snapshot、Focused Integration Testなど、リポジトリが既に対応する最小の決定的な方法を使い、Unit Test済みではないことを報告する。

### 6. 対象を絞ったテストを追加する

必要な期待値が確認済みなら、重大な不足を解消する最小で保守可能なテストを追加する。既存規約に従い、Contractに対応した名前を付ける。テスト対象自体をMockせず、外部Collaboratorは必要なInteraction観測のためだけにMockする。

### 7. 検証して報告する

対象テストから実行し、実用的なら広いSuiteも実行する。保存済みContractのCoverageとStatusを更新する。変更、意図、判断、Contract Path・Status、保護したID、テスト変更、未Review Partition、残存リスク、未解決事項、コマンドと結果を報告する。

実行不能なら正確なBlockerと未検証事項を示し、静的確認だけで完了としない。

## SocraticまたはElenchusへの引き継ぎ

Harden Modeには`confirmed`または`tested`のContract Path、変更ファイル、対象テストコマンド、Risk Rankingを渡す。Catch Modeには、ParentとDiffを特定できれば`provisional`または`needs-decision`でよい。`$socratic`内で実行している場合はこれらの成果物をOrchestratorへ返し、それ以外はElenchusへ直接渡す。Elenchusは永続化されたContractを読み、確認済みIntentを再解釈しない。
