[英語正本](../../../skills/elenchus/references/safety.md)

> この文書は確認用の日本語訳です。実行時の正式な指示は英語正本です。

# Mutation安全Contract

すべてのMutationを、破壊的な一時状態として扱う。

## 必須規則

- 主要Working Treeへ直接Mutationを適用しない。
- 実行前に対象範囲のFilesystem ManifestとContent Hashを記録し、実行後に比較する。
- Mutantごとに新しい使い捨てWorkspaceを使用する。
- 許可された未Commit変更を含め、正確なテスト対象状態を維持する。
- Mutantは1件ずつ実行する。
- BuildとTestへTimeoutを設定する。
- Production Deploy、Migration、破壊的Integration、Live Service Commandを実行しない。
- Testにも外部副作用があり得るため、先にリポジトリの指示とテスト設定を確認する。
- 成功、失敗、Timeout、中断のすべてで使い捨てMutation状態を削除または破棄する。
- 本番コードにMutationが残っていないことを確認せず完了と報告しない。
- ローカルまたはRemoteのGit状態を決して変更せず、その許可も求めない。
- 検証済みSandbox Rootへ`.socratic-disposable`を作成し、すべてのMutation書き込みを`IsolationGate.write_bytes`または`write_text`へ通す。認可CLIだけを実行した後に別の書き込みを行わない。
- Targetを各書き込み直前にResolve・検証する。Sandbox外、主要Root内、Sandbox内Symlink経由のTargetはHard Abortし、BackupとRestoreを隔離として認めない。
- Primary Rootを包含するGit Repository Rootへ解決する。DependencyやBuild ToolのLinkを含め、Sandbox内のどのSymlinkでもRepository内へ解決するものは拒否する。
- Cache、一時Directory、Package Manager State、Framework Build OutputをDisposable Sandbox内へRedirectする。
- Repository Root全体を覆う検証済みHost Read-only保護またはOS/Host Write-event Monitorがある場合だけ、`primary_written_during_run: false`を記録する。

## Git境界

ローカルGitの利用は、`git diff`、`git show`、`git log`、`git rev-parse`、`git merge-base`、`git ls-files`、`git archive`による読み取り専用の根拠収集とSnapshot出力に限定する。

`git add`、`commit`、`amend`、`push`、`pull`、`fetch`、`checkout`、`switch`、`reset`、`stash`、`merge`、`rebase`、`cherry-pick`、`branch`、`tag`、`worktree`を実行しない。`gh`を呼び出さず、Pull Requestを作成せず、レビューコメントを投稿せず、Code HostのWrite APIを呼び出さない。BaseまたはHeadのObjectがローカルにない場合、Fetchせず利用不能として報告する。

## 隔離方法の選択

次の順序で優先する。

1. Hostまたはユーザーが提供した展開済みのBase・Head Directory
2. ローカルにあるImmutable Objectから読み取り専用Gitで出力したTemporary Filesystem Snapshot
3. 許可されたWorking Tree変更を保持しつつ、Repository Metadata、Cache、Secret、複製不要なDependencyを除外したTemporary Filesystem Copy
4. 復元保証が文書化され、Git状態を変更しないFramework固有のMutation Sandbox

BranchやWorktreeを作成・切替しない。Stash、Reset、Checkoutによる復元、広範な削除を安全策として使わない。これらはユーザーの作業を上書きする可能性がある。

## 実行前の証跡

次を記録する。

- 主要Repository Path
- BaseまたはHead Snapshotの識別子と対象変更の説明
- 対象範囲の本番ファイルManifestとContent Hash
- Sandbox Path
- 対象テストコマンドとTimeout
- 関連する環境の隔離状態
- Resolve済みの主要Root・Sandbox Root、HostのRead-only保護Mode、認可された全Mutation Target

## 実行後の証跡

次を分離して確認・記録する。

- 実行中に主要Pathへ書き込んだか
- 許可されたTest・Doc変更を除き、最終Hashが実行前証跡と一致するか
- 最終Working Tree Status、Resolve済みMutation Target、Write Event、Sandbox破棄Status
- Mutation MarkerまたはMutant Patchが本番ファイルに存在しない
- 使い捨てWorkspaceが削除されている。Cleanupが阻害された場合は明示的に報告する
- 元コードが関連テストに成功する

いずれかの確認に失敗した場合は処理を停止し、正確なPathと差分を報告する。明示的な許可なく破壊的な復旧を試みない。
