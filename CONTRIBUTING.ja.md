[English](CONTRIBUTING.md) | 日本語

# コントリビューションガイド

Socraticは、現在初期設計段階です。コントリビューションでは、「人間が未解決の意図を判断し、自動化が根拠を収集して、その判断をテストが守ることを証明する」という中心的な境界を維持してください。

## 最初のコントリビューションに適した領域

- 現実的なFixtureリポジトリとEnd-to-End評価シナリオ
- 言語別のテスト探索アダプター
- 決定的で隔離されたMutation実行
- 生成テストに対するFalse Positive Filter
- Intent ContractのImport／Export連携
- ドキュメント修正と、より明確な振る舞いの例

## 要件

- 現在の実装の振る舞いを、権威ある仕様とみなさない
- 実行可能な変更には、テストを追加または更新する
- 本番コードのMutationを隔離し、自動的に破棄可能にする
- Mutation Scoreの向上ではなく、振る舞いのリスクにMutation Operatorを関連付ける
- Core Protocolへ必須のHosted Serviceを導入しない
- リポジトリコードを実行するコマンド、または外部サービスへ接続するコマンドを文書化する
- 英語の利用者向け文書を変更した場合は、対応する日本語文書も更新する。英語を正本とする
- スキルへ同梱したSchemaを、`schemas/`配下の正本とByte単位で一致させる

提出前にリポジトリの整合性を確認します。

```bash
python3 scripts/check_repository.py
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 scripts/audit_distribution.py
gh skill publish --dry-run
```

Distribution Auditでは、配布するSkill Fileを14個のUTF-8 Text Fileへ意図的に固定しています。Skill Resource、外部URL Host、実行権限、Binary、Symbolic Linkを追加する場合は、同じPull RequestでAudit Policyを明示的に変更してください。

コントリビューションはリポジトリの[MIT License](LICENSE)で受け入れ、[行動規範](CODE_OF_CONDUCT.ja.md)を適用します。
