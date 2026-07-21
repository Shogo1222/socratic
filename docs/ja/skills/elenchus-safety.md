[英語正本](../../../skills/elenchus/references/safety.md)

> この文書は確認用の日本語訳です。実行時の正式な指示は英語正本です。

# Mutation安全Contract

すべてのMutationを、破壊的な一時状態として扱う。

## 必須規則

- 主要Working Treeへ直接Mutationを適用しない。
- 実行前に主要WorkspaceのStatusとDiffを記録し、実行後に比較する。
- Mutantごとに新しい使い捨てWorkspaceを使用する。
- 許可された未Commit変更を含め、正確なテスト対象状態を維持する。
- Mutantは1件ずつ実行する。
- BuildとTestへTimeoutを設定する。
- Production Deploy、Migration、破壊的Integration、Live Service Commandを実行しない。
- Testにも外部副作用があり得るため、先にリポジトリの指示とテスト設定を確認する。
- 成功、失敗、Timeout、中断のすべてで使い捨てMutation状態を削除または破棄する。
- 本番コードにMutationが残っていないことを確認せず完了と報告しない。

## 隔離方法の選択

次の順序で優先する。

1. 対象状態がCommit済みなら、Immutable RevisionのTemporary Git Worktree
2. 許可された未Commit変更があるなら、Temporary Worktreeと明示的に保存したPatch
3. Repository Metadata、Cache、Secret、複製不要なDependencyを除外したTemporary Filesystem Copy
4. 復元保証が文書化されたFramework固有のMutation Sandbox

主要な安全策としてStash、Reset、Checkoutによる復元、広範な削除を使わない。これらはユーザーの作業を上書きする可能性がある。

## 実行前の証跡

次を記録する。

- 主要Repository Path
- Revisionと対象Diff
- 簡潔なWorking Tree Status
- 本番DiffのHashまたは保存表現
- Sandbox Path
- 対象テストコマンドとTimeout
- 関連する環境の隔離状態

## 実行後の証跡

次を確認する。

- 許可されたテスト変更を除き、主要Statusと本番Diffが実行前と一致する
- Mutation MarkerまたはMutant Patchが本番ファイルに存在しない
- 使い捨てWorkspaceが削除されている。Cleanupが阻害された場合は明示的に報告する
- 元コードが関連テストに成功する

いずれかの確認に失敗した場合は処理を停止し、正確なPathと差分を報告する。明示的な許可なく破壊的な復旧を試みない。
