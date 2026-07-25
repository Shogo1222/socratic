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
python3 -B -m unittest discover -s tests -t . -p 'test_*.py'
python3 -m demo.subscription_renewal.run_demo
python3 -m demo.refactor_guard.run_demo
python3 -m demo.test_assessment.run_demo
python3 scripts/validate_fixtures.py
python3 scripts/audit_distribution.py
gh skill publish --dry-run
```

`-B`によって、ローカルの`__pycache__`が配布Checkへ混入することを防ぎます。Testは`tests/`配下で関心ごとに分類し、`-t .`によって各GroupからのRepository Root Importを安定させます。

Fixture検証には`jsonschema`と`referencing`が必要です(`python3 -m pip install jsonschema referencing`)。それ以外は標準ライブラリだけで動作します。

Distribution Auditでは、配布するStandalone Skill Fileを43個、Plugin Bundleを63個のUTF-8 Text Fileへ意図的に固定しています。Skill、Plugin Manifest、Host Hook、外部URL Host、実行権限、Binary、Symbolic Linkを追加する場合は、同じPull RequestでAudit Policyを明示的に変更してください。

## 現在の範囲

v0.5 Integration Previewでは、次の条件へ対象を絞ります。

- 信頼されたHost(Claude Code、Codex、ローカルCursor Desktop)がSession BrokerとTool Gateを起動できる
- 既存のテスト環境があり、Focused Test Commandをローカルでプローブできる
- 戻り値、例外、状態、副作用を決定的に観測できる
- Bug Fix Review、Feature Review、Refactor Guard、Test Assessmentのいずれかを目的として判断できる
- Command、使い捨てClone、Mutation、Schema、Hash、Report、CleanupはRunnerが所有する——依存準備1回、Focused Commandのプローブ1回、並列challenge-batch 1回
- Intentに結び付いた重要なMutationだけを選択する
- GitHubへ自動投稿しない
- ファイル名と行番号付きのコメント候補を生成する
- 未検証範囲とテスト戦略上のトレードオフを報告する

## CIとRelease

GitHub Actionsは、すべてのPull Requestと`main`へのPushに対して、本書に記載したものと同じリポジトリ整合性Checkを実行します。さらにAgent Skills MetadataとPre-agent Plugin Gate、配布監査Test、両配布物の想定外File・実行権限・Binary・Symbolic Link、外部URL Host、必須安全規則を検証し、監査済みFile一式のStandalone Skill Installを一時Directoryへ実際に実行します。SkillとPluginの配布Manifest・File単位Hashを別々のCI証跡としてUploadします。第三者ActionはすべてCommit SHAへ固定します。

CIでは証明できないRelease条件——Hostごとの実機Fresh-install E2E——は[Release Checklist](docs/release-checklist.md)で管理し、Version Lineごとの主要変更は[Changelog](CHANGELOG.md)に要約します。

Rootの[`VERSION`](VERSION) Fileで次に公開するRelease Versionを宣言します。Pull Requestで次のSemantic Versionへ更新してください。そのPull Requestが`main`へMergeされ、CIが成功すると、Release Workflowは検証済みの正確なCommitをCheckoutし、新Versionを自動公開します。対応するTagが既に存在する場合は、重複Releaseを作らず正常終了します。障害復旧用のManual Workflow Dispatchも`main`で利用でき、同じ`VERSION` Fileを読み取ります。

`0.5.0`のような新Versionに対して、WorkflowはRepository、配布物、Install結果、Versionを検証し、Annotated Tag `v0.5.0`、Skill別・Suite ZIP、`SHA256SUMS`、`SKILL_SHA256SUMS`、JSON File Manifest、自動生成Release Noteを公開します。`0.5.0-beta.1`のようなPrerelease識別子は自動的にPrereleaseとして公開されます。

Release WorkflowはSource Fileを変更しません。Git Tagを公開済みReleaseのImmutableな識別子とします。公開ReleaseではRepositoryのImmutable Releasesを必須とし、Workflow完了前にReleaseと全添付Assetを検証します。最初のReleaseでは、Actionsへ秘密署名鍵を保持させず、Immutable Release Attestationを信頼の基点にします。

公開済みReleaseとDownloadしたAssetはGitHub CLIで検証できます。

```bash
gh release verify v0.5.0-beta.1 --repo Shogo1222/socratic
gh release verify-asset v0.5.0-beta.1 ./socratic-v0.5.0-beta.1.zip \
  --repo Shogo1222/socratic
```

コントリビューションはリポジトリの[MIT License](LICENSE)で受け入れ、[行動規範](CODE_OF_CONDUCT.ja.md)を適用します。
