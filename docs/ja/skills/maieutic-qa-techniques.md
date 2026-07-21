[英語正本](../../../skills/maieutic/references/qa-techniques.md)

> この文書は確認用の日本語訳です。実行時の正式な指示は英語正本です。

# QA技法の選択

変更された振る舞いとリスクから必要な技法を選び、すべてを機械的に適用しない。

| 変更に見られる特徴 | 技法 | テスト設計で最低限確認すること |
|---|---|---|
| 入力カテゴリやモード | 同値分割 | 振る舞いが異なる有効・無効クラスの代表値は何か |
| 比較、制限、範囲 | 境界値分析 | 各境界の直前、境界上、直後で何が起きるか |
| ライフサイクルや可変状態 | 状態遷移 | 許可、拒否、冪等となる遷移は何か |
| 複数の独立条件 | Decision Table | 意味のある組み合わせと優先順位を網羅しているか |
| Validationや失敗経路 | 異常系・例外処理 | 何を返す／Throwするか、その後に何が起きてはいけないか |
| 呼び出し、書き込み、Message、Event | Side Effect | 必須、禁止、順序、Exactly-onceとなる効果は何か |
| Retry可能なCommandやHandler | 冪等性 | 繰り返しても結果を維持し、副作用を重複させないか |
| Clock、日付、有効期限、Schedule | Time依存 | Timezone、等号、日付切替、Clock制御を確認したか |
| Empty、Singleton、複数、重複Data | Collection | 順序、個数、Filter、部分失敗が定義されているか |
| Count、金額、Index、計算 | 数値境界 | Zero、Negative、Maximum、Overflow、Rounding、Off-by-oneを確認したか |

## リスクによる絞り込み

次を保護するテストを優先する。

- Authorization、Privacy、Money、Data Loss、不可逆処理
- 後方互換性と公開Contract
- 外部から観測可能な副作用
- Diffによって追加または削除された振る舞い
- 人間による意図確認が必要だったBranch

Privateな制御フローを写すだけのテスト、Contract上の理由なくMock呼び出し詳細を検証するテスト、既存の振る舞いオラクルと重複するテストは優先度を下げる。
