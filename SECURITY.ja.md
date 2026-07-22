# セキュリティポリシー

[English](SECURITY.md)

## 脆弱性の報告

[GitHubの非公開脆弱性報告フォーム](https://github.com/Shogo1222/socratic/security/advisories/new)から非公開で報告してください。疑わしい脆弱性を公開Issue、Discussion、Pull Requestへ記載しないでください。

非公開フォームを利用できない場合は、Xのダイレクトメッセージでメンテナーの[@kubop1992](https://x.com/kubop1992)へ連絡してください。最初のメッセージには、秘密情報、業務上非公開のSource Code、Exploitの詳細を含めないでください。

影響するReleaseまたはCommit、Host AgentとOS、再現手順、想定される影響、機密情報を含まない最小限のProof of Conceptがあると調査しやすくなります。

セキュリティ上重要な問題には、次のものが含まれます。

- Git、Write Mode、Artifact、Cleanup、Mutation隔離の境界を回避できる問題
- 秘密情報やCredentialを読み取らせる指示
- Repository ContentをAgentへの命令として実行する問題
- Mutationや一時ArtifactがDisposable環境外へ残る問題
- Releaseまたは配布物のIntegrityに関する問題

## サポート対象Version

| Version | サポート |
| --- | --- |
| 最新の公開Release | サポート対象 |
| `main` | Best Effortで調査。本番導入ではReleaseを使用してください |
| 過去のRelease | サポート対象外。可能であれば更新後に報告してください |

## 対応目標

以下はService Levelの保証ではなく、対応目標です。

- 5営業日以内に受領を連絡
- 10営業日以内に初期Triage
- Criticalは14日以内、Highは30日以内、その他の受理した問題は90日以内または次回Releaseでの修正・緩和を目標とする

メンテナーは報告者と公開時期を調整し、利用者の対応が必要な場合はSecurity Advisoryを公開します。

## セキュリティモデル

組織で導入する前に[セキュリティモデル](docs/ja/security-model.md)を読んでください。この自然言語Skillが扱うFile、Command、外部通信、信頼境界、限界を説明しています。承認チェックリストには[企業向け導入ガイド](docs/ja/enterprise-installation.md)を利用できます。
