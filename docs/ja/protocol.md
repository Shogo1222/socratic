[English](../protocol.md) | 日本語

# Intent Testing Protocol

## 目的

このプロトコルは、仕様の根拠とコードの振る舞いを分離し、Socraticが統合するMaieuticからElenchusへの受け渡しを永続化して監査可能にします。

## 永続化する成果物

- `.socratic/intent-contract.json`: Maieuticが作成する現在のIntent Contract
- `.socratic/elenchus-report.json`: Elenchusが作成する最新のCatchまたはHarden Report

両方とも、インストールされたスキルへ同梱されたSchemaで検証します。会話内だけのContractはFallbackであり、通常の受け渡し方法ではありません。

## メインライフサイクル

```text
PROVISIONAL（暫定）
  Diffとリポジトリの根拠から意図の仮説を作る。

NEEDS_DECISION（判断待ち）
  複数の妥当な期待値が異なるテストオラクルを生む。

CONFIRMED（確認済み）
  責任を持つ人間または権威ある根拠が必要なオラクルを確定する。

TESTED（テスト済み）
  安定したテストが確認済みの判断と不変条件を保護する。

CHALLENGED（反証済み）
  リスクを考慮したMutationを安定したテストへ実行した。

HARDENED（強化済み）
  選択した高リスクMutantを検知し、未挑戦リスクを明示した。
```

未解決項目は`TESTED`へ進めません。実装が成功することは仕様確認ではありません。予算切れだけでは`HARDENED`にならず、未挑戦項目と残存リスクの明示的な受容が必要です。

## Catch分岐

Catch Modeは`PROVISIONAL`または`NEEDS_DECISION`から分岐します。

```text
Parentで成功しMutantで失敗するCandidate Test
  -> 提案Diffで実行
  -> 振る舞いとして失敗: WEAK_CATCH
  -> 人間が意図しないと回答: STRONG_CATCH
  -> 人間が意図したと回答: FALSE_POSITIVE
  -> 無回答: NEEDS_DECISION
```

ParentとDiffの両方で比較可能にBuild・実行できないテストは`not-comparable`であり、Weak Catchではありません。Infrastructure、Flaky、Missing Symbol、無関係な失敗は判定不能です。

## 中核となる記録

### Intent Contract

正式な機械可読形式は[intent-contract.schema.json](../../schemas/intent-contract.schema.json)です。変更範囲、ライフサイクル状態、観測可能な意図と根拠、確認済み判断と由来、不変条件、副作用、未解決判断、テストとの対応を保持します。

Decision Provenanceは次の2値だけです。

- `user-confirmed`
- `repository-established`

未確認の推論は`intent.evidence`、未解決のオラクル選択は`unresolved`へ記録します。

### Mutation ResultとReport

[mutation-result.schema.json](../../schemas/mutation-result.schema.json)は、Candidate設計から実行までの1つのIntent MutationをCatch分類を含めて表現します。[mutation-report.schema.json](../../schemas/mutation-report.schema.json)は、Baseline証跡、未挑戦Contract ID、未解決判断、追加テスト、Mutation除去の実行後証跡を含む実行全体を表現します。

## 人間が判断する境界

次のすべてを満たす場合だけ質問します。

1. 複数の合理的な期待値が残る
2. 品質確認済みのリポジトリ根拠では解決できない
3. 回答が観測可能なオラクルまたは重要な副作用を変える
4. 誤った推測に無視できないコストがある

最小で具体的な振る舞いの差または明示的な選択肢を提示します。順位付けでは重大度、確信度、人間のDismiss Costを考慮します。無回答なら`needs-decision`を永続化し、独立した確認済み作業だけを続け、回答を捏造しません。

## 根拠の境界

既存テストをオラクル確定へ使えるのは、Diffより前から存在し、Diffで変更されておらず、安定していて、MaieuticのQA Reviewを通過した場合だけです。変更済み、弱い、Flaky、矛盾、実装依存のテストは推論の補助にのみ使います。現在の実装は最も優先度の低い根拠です。

## Mutationの境界

次の順序でMutationを生成します。

1. 確認済みまたは暫定の意図に対する、もっともらしい誤解
2. Contractに関係する副作用の欠落または破壊
3. 状態、認可、時間、Collection、失敗方針の逸脱
4. 特定リスクを実現する従来型の構文Mutation

`equivalent`には根拠を必須とします。Contractにない観測可能な振る舞いは、Maieuticへ戻すMissing Invariant候補です。Mutation数とScoreは診断情報にすぎません。

## BaselineとScopeの境界

Mutation分類には安定したGreen Testが必要です。失敗を1回再実行し、再現する赤Baselineでは停止します。Flaky Testの除外は、安定した部分集合がContractを観測できる場合だけ許可し、縮小したScopeをすべて報告します。

巨大な変更は、観測可能な振る舞いまたはリスクDomainで分割します。予算、観測不能、適用不能、Blockerによって対象外となった全Contract IDを、残存リスクとともに`not_challenged`へ記録します。

Unit Testで観測できないArtifactには、リポジトリが対応する最小の決定的な検証を使い、Unit Test済みではないことを明示します。

## 安全性の境界

本番コードのMutationは使い捨てWorkspaceだけに存在させます。主要Workspaceへ反映できるのは許可されたテストまたはドキュメント変更だけで、一時的な本番Mutationは反映しません。実行前後の証跡を必須とし、CompileまたはInfrastructure Failureを振る舞い上のKillやCatchとして数えません。
