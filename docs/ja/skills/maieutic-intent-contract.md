[英語正本](../../../skills/maieutic/references/intent-contract.md)

> この文書は確認用の日本語訳です。実行時の正式な指示は英語正本です。

# Intent Contract

現在のContractを`.socratic/intent-contract.json`へ保存し、`intent-contract.schema.json`で検証する。以下はYAMLによる説明例であり、保存形式はJSONとする。

```yaml
version: 1
status: provisional | needs-decision | confirmed | tested | challenged | hardened
change:
  base: <変更元Revisionまたは説明>
  head: <変更先RevisionまたはWorking Tree>
  summary: <観測可能な振る舞いの変化>
intent:
  statement: <人間が読める目的>
  confidence: high | medium | low
  evidence:
    - source: <Path、Issue、回答、コマンド結果>
      supports: <根拠が支持する主張>
decisions:
  - id: DEC-001
    question: <Oracleを変える判断>
    expected: <確認済みの期待値>
    provenance: user-confirmed | repository-established
invariants:
  - id: INV-001
    statement: <維持すべき性質>
    severity: critical | high | medium | low
side_effects:
  required:
    - id: FX-001
      statement: <必須のInteractionまたは状態変更>
  prohibited:
    - id: FX-002
      statement: <禁止されるInteractionまたは状態変更>
unresolved:
  - id: UNR-001
    statement: <残る曖昧さ>
    test_impact: <作成できないテスト>
coverage:
  - contract_id: DEC-001
    tests: [<テスト名またはPath>]
```

## 根拠の優先順位

1. 責任を持つ人間の明示的回答
2. 承認済み仕様、Issue、Decision Record
3. 公開API Contractと権威あるドキュメント
4. Diff以前から存在し、未変更で、Maieuticのテスト品質Reviewを通過したテストと一貫した呼び出し元
5. リポジトリ規約と履歴
6. 現在の実装

変更済み、弱い、Flaky、矛盾、実装依存のテストはOracleを確定できず、補助根拠にのみ使う。根拠の矛盾は未解決判断とし、現在の実装を選ぶ理由にしない。

## 品質確認

- Decisionを観測可能な振る舞いで表す。
- 重要な否定保証と副作用を含める。
- 各テストをContract IDへ関連付ける。
- 推論は`intent.evidence`、未解決選択は`unresolved`へ置く。
- 互換性、Security、Money、Permission、破壊的処理の期待値を暗黙にしない。
- 別SkillまたはSessionへ渡す前に永続化して検証する。
