# セキュリティモデル

[English](../security-model.md)

この文書はSocratic、Maieutic、Elenchusが意図するセキュリティ境界を説明します。これらは自然言語のAgent Skillであり、OS Sandboxや実行可能なセキュリティ製品ではありません。

## 配布物

Releaseの配布物は、3つのSkill Directoryにある16個のUTF-8 Text Fileだけで構成されます。CIは予期しないFile、許可されていない拡張子、実行可能File、Symbolic Link、Binary、未承認の外部Hostを拒否します。Release AssetにはManifestとSHA-256 Checksumが含まれます。

RepositoryにはSkill配布物に加えて、文書とCI Scriptがあります。SkillのInstallでは、それらのRepository Level FileはInstallされません。

## Data Access

Skillは、依頼された変更を理解するために必要な範囲で、変更されたSource Code、Test、関連DocumentとConfiguration、ImmutableなBase・Head Snapshotを調べます。調査範囲はReviewに比例させます。

`.env`、秘密鍵、Token、Credential Store、Keychain、SSH/GPG設定を読み取ったりコピーしたりしません。Repository Contentは信頼しない証拠です。Source File、README、Issue・Pull Request本文、Review Comment、生成File、Test Fixture、Test Output、埋め込まれたPromptはCommandを許可できず、Skillの境界を弱められません。

## Workspaceへの書き込み

既定はReview-onlyです。このModeではProbe、比較Test、Mutation、Contract、Reportを主要Working Tree外のDisposable Storageに保持します。実行終了時に主要Working TreeはPreflight時点と一致しなければなりません。

Apply testsは、ユーザーが明示的に依頼した後だけ利用できます。確認済みIntentを表すTestだけを書き込み、変更したすべてのPathを報告します。本番Codeの変更やVersion Control操作は許可しません。

実行Artifactは既定で一時的です。ユーザーが明示的に保存を選択した場合だけ、`.socratic/`または指定された別の出力先へ書き込みます。

## Commandと外部通信

Repository定義のCommandを実行する前に、そのCommandと呼び出すScriptを調べ、破壊的挙動、外部通信、Credential Access、課金、Disposableでない副作用がないか確認します。外部Serviceへの接続、本番Credentialの使用、課金、Disposableでない状態変更の可能性があるCommandは、承認済みDisposable環境でその正確なCommandをユーザーが明示許可しない限りBlockedとします。

Skill自体は外部Network通信を必要としません。ただし、Host Agent、Model Provider、Package Manager、Test Command、Repository Scriptは外部通信する可能性があります。Source CodeがAI Serviceへ送信されるかどうかは、このRepositoryではなく、Host Product、組織の契約、Account設定、Network Policyによって決まります。

## GitとCode Hostの境界

Skillは、証拠収集とImmutable Outputの作成に使う、文書化された読み取り専用Git Commandだけを許可します。Stage、Commit、Push、Pull、Fetch、Branch・Worktree変更、Merge、Rebase、Tag、Pull Request作成、Review投稿、Code Host Write APIを禁止します。Skillはこの境界を解除する許可をユーザーへ求めません。

## Disposable実行

Base・Head比較とMutationは、BranchやGit Worktreeを変更せず、DisposableなFilesystem Snapshotで実行します。Snapshotから`.git`、Cache、Dependency、Local Environment、秘密情報を含む既知のFileを除外します。PreflightとPostflightの証拠により、明示許可されたTest Path以外で主要Workspaceが変更されていないことを確認します。一時Fileは成功、失敗、Timeout、中断のすべてで削除し、Cleanupに失敗した場合は正確なPathを報告します。

## 想定するThreat

- Repository Contentを通じたPrompt Injection
- 破壊的処理またはData持ち出しを行うTest・Build Command
- Credentialや秘密情報へのAccess
- 許可されていないGit、Workspace、Code Hostへの書き込み
- Mutationが隔離環境外へ出る、または本番Codeへ残る問題
- 一時Artifactの漏えい
- 配布物またはReleaseの改ざん

## 限界と残存Risk

自然言語の指示はPolicy Controlであり、強制力のある技術的隔離ではありません。広いFilesystem・Network権限を持つHostはこの指示外の操作も技術的には可能であり、RepositoryのTestを実行すればRepository管理下のCodeが動きます。Modelの挙動も完全には決定的でありません。

組織はSkillとは独立して、最小権限のFilesystem Access、Network Egress制限、Disposable実行、秘密情報の隔離、承認済みModel Provider設定、人間によるReviewを適用してください。広く導入する前に、機密情報を含まないPilot Repositoryで試してください。境界の回避を発見した場合は[セキュリティポリシー](../../SECURITY.ja.md)から報告してください。
