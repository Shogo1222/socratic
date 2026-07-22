[English](README.md) | 日本語

# Subscription Renewalデモ

この実行可能デモでは、外部Dependencyや本番コードへの一時変更なしで、MaieuticからElenchusまでのSocratic Workflowを確認できます。実際のセッション体験——ターミナルに何が出て、何を聞かれるか——は、先に[Walkthrough](walkthrough.ja.md)を読んでください。

## シナリオ

弱いテストは、明確に期限切れのAccountと、返された成功値だけを確認しています。次の仕様は確定していません。

- 有効期限と現在時刻が等しい場合の振る舞い
- 成功したRenewalがAccountをChargeするか
- Retryが冪等か

[Maieuticの問答例](maieutic-session.ja.md)でこれらの判断を引き出し、[intent-contract.json](intent-contract.json)へ記録します。Elenchusは、もっともらしい3つの誤解を事前作成したデモ用Mutantとして表現し、完了結果を[expected-elenchus-report.json](expected-elenchus-report.json)へ記録します。

| Mutant | 変異した意図 | リスク |
|---|---|---|
| MUT-001 | 有効期限と等しい時刻ではまだ利用可能 | 期限切れ後のRenewal |
| MUT-002 | 成功にChargeは必要ない | 未課金でのService提供 |
| MUT-003 | Retry時に再度Chargeしてよい | 二重課金 |

3件すべてが[弱いテスト](test_weak.py)では生存します。確認済みの意図を[補完後のテスト](test_hardened.py)へ追加すると、すべて検知されます。

## 実行方法

リポジトリRootから実行します。

```bash
python3 -m demo.subscription_renewal.run_demo
```

期待する概要は次のとおりです。

```text
Original / weak          PASS   baseline passes
MUT-001 / weak           PASS   SURVIVED
MUT-002 / weak           PASS   SURVIVED
MUT-003 / weak           PASS   SURVIVED
Original / hardened      PASS   baseline passes
MUT-001 / hardened       FAIL   KILLED
MUT-002 / hardened       FAIL   KILLED
MUT-003 / hardened       FAIL   KILLED
```

失敗するTest Processは期待された結果であり、RunnerがCaptureします。デモ全体が期待どおりなら終了Statusは`0`です。

## 安全性

デモではMutantを別Moduleとして保持するため、`subscription.py`を編集しません。これは決定的に動作する学習用Fixtureであり、将来の本番Mutation Runnerではありません。実リポジトリのMutationでは、ElenchusのSafety Contractに定めた隔離と実行後検証へ従う必要があります。
