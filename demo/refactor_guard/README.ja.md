[English](README.md) | 日本語

# Refactor Guardデモ

「読みやすさのためのリファクタリング」として提示された変更——`_is_active`ヘルパーの抽出——が、期限境界を静かに反転させます。同じBehavior ProbeをBaseとHeadへ実行し、差を判定ではなく事実として提示します。実際のセッション体験は、先に[Walkthrough](walkthrough.ja.md)を読んでください。

## シナリオ

[base.py](base.py)は契約終了日当日まで更新を許可します。[head.py](head.py)はそのリファクタリングを名乗りますが、抽出されたヘルパーが`<=`ではなく`<`で比較するため、終了日当日の更新が`ExpiredSubscriptionError`になります。

Baseを基準に生成した3つのBehavior Probeは、出力と例外だけを観測します。

| Probe | Base | Head | 分類 |
|---|---|---|---|
| 終了日よりかなり前の更新 | pass | pass | 維持 |
| 終了日よりかなり後の更新拒否 | pass | pass | 維持 |
| 終了日当日の更新 | pass | fail | 振る舞いが変更または削除された |

Baseは観測された事実であり、仕様とはみなしません。デモは、実際の実行が仕様オーナーへ送る質問——「この変更は意図したものですか?」——で終わります。同梱の[intent-contract.json](intent-contract.json)はこの質問を未解決として記録し、[expected-elenchus-report.json](expected-elenchus-report.json)はオーナーが「意図していない」と回答した後の完了済みCatch Mode実行(Strong Catch分類)を示します。

## 実行方法

リポジトリRootから実行します。

```bash
python3 -m demo.refactor_guard.run_demo
```

成功するとProbeの行列を表示し、Behavior Diffをちょうど1件報告して、Status `0`で終了します。

## 安全上の注意

BaseとHeadは別モジュールのため、デモが本番コードを編集することはありません。これは決定的な教材Fixtureであり、実際の比較はElenchus安全Contractのスナップショット隔離と実行後検証の規則に従います。
