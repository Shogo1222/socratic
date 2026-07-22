[English](maieutic-session.md) | 日本語

# Maieuticによる問答例

## 観測された振る舞い

提案された比較処理は、`now`より前に期限切れとなったAccountを区別しますが、`expires_at == now`の場合の振る舞いを確定していません。また、Renewal後に成功を返しますが、既存テストはChargeやRetry時の振る舞いを観測していません。

## 人間による判断

```text
変更前: 有効期限と等しい境界はテストされていませんでした。
この変更後: expires_at == nowの場合もAccountを利用可能として扱う可能性があります。
この変化は意図したものですか？

人間: いいえ。有効期限と等しい時刻では、すでに期限切れです。
```

```text
変更前: テストは返された結果だけを検証していました。
この変更後: Chargeせず成功を返す、またはRetry時に再度Chargeする可能性があります。
成功したRenewalは、一連のRetryを通じて正確に1回だけChargeすべきですか？

人間: はい。最初の有効なRenewalで1回Chargeし、Retryでは再度Chargeしません。
```

これらの回答から、`intent-contract.json`の`DEC-001`、`DEC-002`、`INV-001`、`INV-002`を確定します。
