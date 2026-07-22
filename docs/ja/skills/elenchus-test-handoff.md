[英語正本](../../../skills/elenchus/references/test-handoff.md)

> この文書は確認用の日本語訳です。実行時の正式な指示は英語正本です。

# 証明済みテストの引き渡し

未変更の本番コードで成功し、少なくとも1件の妥当なMutationに対して意図した振る舞いAssertionで失敗したテストだけを引き渡し対象にする。この引き渡しにより、Review-only実行は主要Workspaceを変更せず、後からまったく同じ証明済みテストを適用候補として提示できる。

Manifestは`test-handoff.schema.json`で検証する。

## 内容

次の2ファイルをリポジトリのWorking Tree外に保持する。

- リポジトリ相対Pathを使った、テスト変更だけのUnified Patch
- Patch Hash、Snapshot識別子、本番・テストファイルの適用前Hash、テストファイルの適用後Hash、Contract ID、対象テストコマンド、検知したMutation ID、広いSuiteの結果、Lifecycle Statusを持つJSON Manifest

対象テストファイルが存在しなかった場合だけ、適用前Hashを`null`にする。提案テストが観測する本番ファイルと、Patchが変更するすべてのテストファイルを含める。Patchへ本番コードやドキュメントの変更を含めない。

POSIX形式のリポジトリ相対Pathだけを使う。出力または適用前に、絶対Path、Backslash、`..`によるTraversal、Symlink Target、主要リポジトリ外へ解決されるPathを拒否する。

## 処理方法

正準のReview Surface後に、引き渡しBatchごとに1件の構造化選択を提示する。

1. **テストを適用** — Apply tests modeへ移る明示的な許可
2. **Patchを出力** — Working Treeを変更せずPatchを表示
3. **破棄** — PatchとManifestを削除

対応するOracleが未解決の間は「テストを適用」を提示しない。無回答は破棄として扱う。Cleanup前にManifest Statusを`applied`、`output`、`discarded`、`stale`のいずれかへ更新する。

## 引き渡しを適用する

適用前に次を確認する。

1. PatchのSHA-256
2. 主要Workspaceに対するすべての本番・テストPrecondition
3. Patchがテストファイルだけを変更し、確認済みIntentを引き続き表すこと

Preconditionが1件でも異なる場合はPatchを強制適用しない。`stale`として記録し、許可され実行可能なら現在のWorkspaceに対して再生成し、双方向の証明をやり直す。前回実行で破棄済み、またはProcess再起動で引き渡しが存在しない場合は、再利用したと主張せず再生成する。

適用後は、すべてのテストファイルの適用後Hash、未変更の本番コードに対する対象テスト、Disposable環境での帰属可能なMutation、実用的な場合は広い関連Suite、通常の本番ファイルPostflight監査を確認する。すべてを終えて初めて、テストが適用され永続化されたと報告する。

適用、出力、破棄、Stale、失敗、Timeout、中断の後は、一時PatchとManifestを削除する。Cleanupに失敗した場合は残ったPathを正確に報告する。
