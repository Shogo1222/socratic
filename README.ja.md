<p align="center">
  <img src="./assets/socratic-logo.png" alt="Socratic" height="120">
</p>

[Webサイト](https://shogo1222.github.io/socratic/) | [English](README.md) | 日本語

# Socratic

[![CI](https://github.com/Shogo1222/socratic/actions/workflows/ci.yml/badge.svg)](https://github.com/Shogo1222/socratic/actions/workflows/ci.yml)
[![GitHub Release](https://img.shields.io/github/v/release/Shogo1222/socratic)](https://github.com/Shogo1222/socratic/releases)

> Don't review every line. Review the decisions that matter.

Socraticは、AI生成PRのレビューを支援する3つのAgent Skillです。

名前はソクラテスの問答法に由来します——分かっていないことを自覚して問いを立て(Socratic)、対話によって相手の中から考えを産み出させ(Maieutic: 産婆術)、反駁によって主張を吟味する(Elenchus: 論駁)という進め方を、そのままレビューの手順にしています。

- **Socratic** — 全体のOrchestrator。変更前後の振る舞いを比較し、人間が判断すべき仕様、意図しない可能性のある変更、既存テストが検知できない重要なリスクだけを抽出して、4ブロックのレビュー結果とコピーして使えるコメント候補を届けます。**アウトカム**: 大きなDiffを全部読む代わりに、少数の判断と貼るだけのコメントをレビューすればよい状態。
- **Maieutic** — 意図の引き出し役。実装だけでは確定できない期待値を、仕様オーナーが回答できる具体的な質問へ変換し、回答をIntent Contractへ記録して対応するテストと関連付けます。**アウトカム**: 「なんとなく不安」が、答えられる仕様質問と、テストに裏付けられた確定仕様の記録に変わる。
- **Elenchus** — 反証役。BaseとHeadへ同じBehavior Testを実行して振る舞い差を検出し、Mutationでテストの検知能力を証明します。単独実行では、既存・変更後テストの評価(Test Assessment)ができます。**アウトカム**: 「テストがGreen」ではなく、「このバグを入れたら実際に落ちる」という証拠。

## 解決したい現場の課題

AIが大量にコードを書くようになると、レビュアーは次の問題に直面します。

- Diffが大きく、すべてを精査できない
- コードだけでは実装意図を判断できない
- テストがGreenでも、重要なバグを検知できるか分からない
- リファクタリングで振る舞いが変わっていないか不安が残る
- レビューコメントを書くための調査と言語化に時間がかかる
- AIレビューによる大量の細かなコメントがノイズになる

Socraticは、レビュアーが次の4点を短時間で把握できるようにします。

1. ユーザーから見て何が変わるのか
2. 人間による仕様判断が必要なのはどこか
3. どのような事故が起こり得るのか
4. テストはその事故を本当に検知できるのか

## インストール

Socraticの対象HostはClaude Code・Codex・Cursorです。このIntegration Previewでは、それ以外のAgent Hostはサポートしません。

### Claude Code

v0.3.0 Integration Previewでは、RepositoryをClaude Code Marketplaceとして追加し、PluginをInstallしてください。

```text
/plugin marketplace add Shogo1222/socratic
/plugin install socratic@socratic-marketplace
```

公開Versionの更新を取得する場合は、Catalogを更新してからPluginをUpdateします。

```text
/plugin marketplace update socratic-marketplace
/plugin update socratic@socratic-marketplace
```

その後、信頼済みGit Repositoryで通常どおりClaudeを起動し、Marketplace Commandとして表示される`/socratic`を実行してください。PluginはClaudeがRequestを処理する前にSession単位のHost brokerを自動起動し、`PreToolUse`でPrimaryへの直接WriteとRunner外Bashを拒否します。MaieuticとElenchusの直接起動にも同じGateを使います。Run Manifestが存在する間は`Stop`後もbrokerを維持して人間の判断をTurn間で継続し、FinishまたはAbort後にCleanupします。放棄・stale状態のbrokerはIdle TTLと後続Host Eventで回収します。専用Launcher Commandは不要です。

`/hooks`で同梱HookをReview・Trustしてから新しいThreadを開始してください。Hookが未Trust、無効、利用不能な場合はSocraticを使用しません。Plugin HookのTrustはユーザーが変更できます。解除不能な境界が必要な組織は、同じGateを`requirements.toml`とOS・Device ManagementによるManaged Hookとして配布する必要があります。

### Codex

Codex Marketplaceを追加し、PluginをInstallして、同梱Hookを`/hooks`でReview・Trustします。

```bash
codex plugin marketplace add Shogo1222/socratic
codex plugin add socratic@socratic-marketplace

# 公開UpdateのInstall前にMarketplace Snapshotを更新
codex plugin marketplace upgrade socratic-marketplace
codex plugin add socratic@socratic-marketplace
```

信頼済みのローカルGit Repositoryで`$socratic`を実行します。Codex PluginもSession単位のHost brokerを自動起動し、`PreToolUse`でPrimaryへの直接Writeと未GuardのCommandを拒否します。実行中のStateはTurn間で維持し、完了・Abort・Idle時にCleanupします。

### Cursor Desktop

Repositoryには`.cursor-plugin/`配下のNative Cursor Pluginも含まれます。Cursor DesktopへLocal PluginとしてInstallし、WindowをReloadしてから`$socratic`を実行します。Pluginは`beforeSubmitPrompt`、`preToolUse`、`beforeShellExecution`をFail-closedで使用します。現行Hook coverageでは同じ境界を証明できないため、Cursor CLI、Remote Workspace、Cloud Agentはサポートしません。Cursor Marketplaceからの公開Installは、Cursor側の別途Submission審査を通過するまで利用できません。

### Standalone Maieutic・Elenchus

Standalone Agent SkillはCodexまたはCursorでMaieutic・Elenchus開発に利用できますが、準拠した`$socratic` Entry Pointではありません。

```bash
# 対話式でSkillと導入先のCodexまたはCursorを選ぶ
gh skill install Shogo1222/socratic

# 3つのSkillをすべてインストール
gh skill install Shogo1222/socratic --all

# Integration Preview ReleaseへStandalone Resourceをピン留め
gh skill install Shogo1222/socratic --all --pin v0.3.0-alpha.6
```

またはAgent Skills CLIを使い、導入先としてCodexまたはCursorを選択します。

```bash
npx skills add Shogo1222/socratic --skill '*'
```

Standalone分析では`$maieutic`または`$elenchus`を直接実行します。統合`$socratic` Workflowには上記の各Host Pluginを使用します。

必須Review RunnerにはPython 3の`jsonschema`と`referencing`が必要です。各Host PluginはAgent開始前にこれらを解決します。利用できない場合、HookがPluginの書き込み可能Data Directoryへ隔離Virtual Environmentを作り、固定VersionをInstallします。RepositoryやGlobal Python環境は変更しません。そのため初回実行だけPackage IndexへのAccessが必要です。Bootstrapに失敗した場合はAgent開始前にSocraticを停止します。組織環境では、初回Network Accessを避けるため、同じ固定DependencyをManaged Python Runtimeへ事前配備できます。

組織での導入(Releaseの検証・Preview・Project Scope)は[企業向け導入ガイド](docs/ja/enterprise-installation.md)を参照してください。

## 対象ユーザー

- AI生成PRをレビューするシニアエンジニアやTech Lead
- 大きなDiffの「どこを判断すべきか」を短時間で知りたいレビュアー
- AIが追加したテストが本当に守れているか確かめたいチーム

Socraticの立ち位置は次のとおりです。

- レビューを代替せず、重要な判断へ集中するための材料を作る
- GitHubへ自動投稿しない。コピーして使えるコメント候補だけを生成し、投稿・編集・破棄はレビュアーが決める
- 仕様質問に回答するのは仕様オーナー——PR作者、レビュアー、Product Owner、Domain Expert、Tech Lead、APIやデータのOwner
- AIがコードを生成した場合、AIは仕様の根拠にも回答者にもならない
- レビュアーに回答権限がない場合、コメント候補は仕様オーナーへ確認するための道具になる

## ユースケース

### Feature Review

新しい機能や仕様変更を含むPRに対して、実装だけでは確定できない期待値を抽出します。

```markdown
契約終了日と更新日が同日の場合も、更新を許可する意図でしょうか？

終了日当日を有効期間に含めるかによって、この境界条件の期待値が変わります。現在のリポジトリ内からは判断できなかったため、期待する振る舞いを確認したいです。
```

確定した仕様はIntent Contractへ記録し、対応するテストと関連付けます。

### Refactor Guard

振る舞いを維持するはずのリファクタリングに対して、BaseとHeadへ同じ振る舞いテストを実行します。

```text
同じBehavior Test
      |
      +-- Baseへ実行
      |
      +-- Headへ実行
      |
      v
Behavior Diffを抽出
```

差が見つかった場合は、意図した変更か回帰かを人間へ確認します。

```markdown
このリファクタリングでは、期限切れ判定の境界条件が変わっているようです。

契約終了日と実行日が同じケースについて、変更前は更新できますが、変更後は拒否されます。

振る舞いを維持するリファクタリングであれば、意図しない変更の可能性があります。この変更は意図したものでしょうか？
```

Refactor Guardが信頼できるためには、比較テストが内部構造ではなく観測可能な振る舞いを検証していなければなりません。実装依存のテストが生む偽陽性は、Behavior Diffとして報告しません。

### Test Assessment

テストそのもの——特にAIが追加したテスト——を評価するには、`$elenchus`を単独実行します。同じリスクMutationを既存・変更後の両テスト集合と比較し、既存Protection、増分Protection、Protection Regression、未保護のリスクを分離します。詳細は後述の「Elenchusを単独実行する」を参照してください。

## Behavior Diffの分類

| Base | Head | 分類 |
|---|---|---|
| Pass | Pass | 検証した振る舞いは維持されている |
| Pass | Fail | 既存の振る舞いが変更または削除された |
| Fail | Pass | 新しい振る舞いが追加または修正された |
| Fail | Fail | 比較テストとして不成立、または未実装 |

テストのコンパイル失敗、環境エラー、Timeout、Flaky FailureはBehavior Diffとして扱いません。

`Base Pass / Head Fail`を自動的にバグとは判定しません。Baseは仕様ではなく、変更前に観測された事実として扱います。

- Refactor PRなら、意図しない変更の可能性が高い
- Feature PRなら、意図した仕様変更の可能性がある
- どちらか確定できなければ、人間へ確認する

## 出力

端末出力は次の4ブロックへ固定します。

- **Review This** — 人間の判断が必要なもの。未確定のIntent、意図したか確認できていないBehavior Diff、受容判断が必要な設計リスク
- **We Verified** — 確認済みのもの。維持されている振る舞い、仕様オーナーが確認した意図的な変更、Working Treeへ適用して証明したテスト、Disposable環境で証明した提案テスト、修正済みのTest Gap、Mutationによる検知能力
- **Still at Risk** — 検証できていないもの。未挑戦の振る舞い、実行環境上の制約、非決定的な処理、比較不能だった範囲
- **Copy-ready Comments** — レビュアーが利用できるコメント候補。対象ファイル、対象行、コメント本文、内部向けの生成根拠

テストの出所は、会話全体やGit HistoryではなくSocratic実行開始時点を基準にします。レビュワー向け出力では、各テストを**実行開始時点で既存**、**Disposable環境で提案・証明済み**、**明示依頼後に今回の実行が適用**のいずれかとして明記します。Review-onlyのPostflightがPreflightと一致した場合は、**今回のReview-only実行中、Working Treeは不変**と報告します。

Review-onlyで提案テストを証明した場合、Socraticは正確なテスト専用PatchとHash検証済みの引き渡しをWorking Tree外へ保持し、**テストを適用**、**Patchを出力**、**破棄**のいずれかを選べるようにします。この運用上の選択は4つのReviewブロック後に提示します。Staleまたは欠落した引き渡しは、強制適用や再利用と表現せず、再生成・再証明します。

発見は種類ではなく状態で振り分けます。

```text
Behavior Diff
  未確定 → Review This
  意図的と確認済み → We Verified

Test Gap
  未解決 → Review This
  Disposable環境で証明済みの提案 → We Verified
                                    + Still at Risk: 保護は未適用
  Working Treeへ適用して証明済み → We Verified

Residual Risk
  → Still at Risk
```

実行結果の例:

```text
Socratic Review

Review This:
  ! 期限境界の振る舞い差を1件検出

    Before:
      終了日当日の更新に成功

    After:
      ExpiredSubscriptionError

    Required decision:
      この変更は意図したものか、仕様オーナーの確認が必要

We Verified:
  ✓ 二重更新を拒否する
  ✓ 更新後の契約期限を参照できる
  ✓ 外部Eventの内容と送信回数
  ✓ 実行開始時点で既存の境界テスト4件を評価
  ✓ Event送信欠落のMutationをDisposable環境で提案・証明済みのテストが検知
  ✓ 今回のReview-only実行中、Working Treeは不変

Still at Risk:
  △ タイムゾーン境界
    Clockを制御できないため未検証
  △ 提案テストは未適用
    Event送信欠落への保護は適用まで永続化されない

Copy-ready Comments:
  1 comment for src/subscription.ts:52
```

マージ可否、信頼度、総合スコアは表示しません。Socraticが報告するのは、検証した範囲、発見した問題または判断事項、検証できなかった範囲の3点であり、マージ判断はレビュアーに残します。詳細なIntent Contract、Mutation結果、証明済みテスト引き渡しのStatus、Test Strategy、実行コマンドは一時的な実行Artifactとして保持し、テスト引き渡しを処理した後に、保存しない(デフォルト)・ローカル保存・Markdown出力から選べます。

## Copy-ready Comments

主要成果物は、レビュアーがGitHubへコピーできるコメント候補です。種類は3つに絞ります。

- `Intent decision`: 実装から確定できない仕様
- `Behavior difference`: BaseとHeadで異なる振る舞い
- `Test gap`: 既存テストが検知できない重要な欠陥

各コメントは次の構造を持ちます。

1. 観測した振る舞い
2. 確認したい判断またはテスト不足
3. 判断が必要な理由
4. 回答によって変わる影響

コメント候補は原則1〜3件に絞り、細かな指摘を大量生成しません。行へ固定できない問題は`Residual risk`としてStill at Riskへ残します。

## Decision Prompt

振る舞い差は、仕様オーナーがHostネイティブのUIで回答できる構造化質問へ変換します。

```text
Behavior Diff
      ↓
Decision Prompt
      ↓
Codex / Claude Codeの選択UI
      ↓
Intent Contract
      ↓
Test + Mutationで固定・反証
```

質問の内容はHost中立です。1回のBatchで1〜3問、各質問に相互排他的な選択肢を2〜3個、選択肢ごとに観測可能な影響の1文、自由入力の受け付け、回答によって変わるOracleを含めます。Host固有なのは表示だけです。

- **Claude Code**: `AskUserQuestion`
- **Codex**: `request_user_input`
- **非対応環境**: 同じ質問をコピー可能なMarkdownで提示

構造化質問はメインエージェントだけが行います。サブエージェントは調査・テスト・Mutationを担当し、未解決の判断を返します。Socraticが保証するのは質問の内容であり、選択UIはHostの機能です。特定ベンダーへ依存する独自アプリは不要です。

## テスト設計の原則

『単体テストの考え方/使い方』(Vladimir Khorikov著、Unit Testing Principles, Practices, and Patternsの邦訳)を土台として、内部構造ではなく1単位の振る舞いをテストします。

### 1. クライアントの目標から始める

クラスやメソッドをテスト対象の単位にしません。

```text
誰が使うのか
    ↓
何を達成したいのか
    ↓
どの操作を行うのか
    ↓
何を結果として観測できるのか
```

### 2. 依存を分類してからOracleを選ぶ

- **プロセス内**: Domain Service、Repository abstraction、内部Event Handlerなど。内部コミュニケーションではなく、クライアントから観測できる最終結果を検証する
- **プロセス外・管理下**: アプリケーション専用Databaseや管理下のFile Storageなど。Repository呼び出し回数ではなく、実際の最終状態をFocused Integration Testで検証する
- **プロセス外・管理外**: 外部API、SMTP Service、他サービスが購読するMessage Bus、Payment Gatewayなど。アプリケーション境界で送信内容と送信回数をMockまたはSpyで検証する

分類は、AdapterやGatewayの実装、Infrastructure設定、Message Consumer、Databaseの所有関係、API仕様、既存テスト、Architecture Decision Recordなど、まずリポジトリから調査します。判断できず、分類によってOracleが変わる場合のみ仕様オーナーへの質問にします。

### 3. Oracleの優先順位

```text
出力値
  ↓
観測可能な最終状態
  ↓
アプリケーション境界を越えるコミュニケーション
```

### 4. 実装の詳細を検証しない

内部メソッドの呼び出し順序、内部クラスの構成、Repositoryメソッドの呼び出し回数、Stubから値を取得した回数、最終結果に影響しない中間状態、リファクタリングで自由に変更できるアルゴリズムは、原則として期待値にしません。

## 良いテストを構成する4本の柱

テストは、退行に対する保護、リファクタリングへの耐性、迅速なフィードバック、保守のしやすさの4観点で評価します。ただし、すべてを同時に最大化しようとしません。特に最初の3つにはトレードオフがあります。

| テスト | 退行への保護 | リファクタリング耐性 | フィードバック |
|---|---:|---:|---:|
| E2E | 高い | 高い | 遅い |
| 取るに足らないテスト | 低い | 高い | 速い |
| 実装依存テスト | 高くなり得る | 低い | 速い |
| 良い単体テスト | 中〜高 | 高い | 速い |

Socraticは、リファクタリングへの耐性を維持したうえで、変更リスクに応じて残りの柱を配分します。

```text
速いBehavior Test
        +
重要な状態を確認する少数のFocused Integration Test
        +
境界契約を確認するさらに少数のE2E Test
```

「常に単体テストを追加する」のではなく、そのリスクを最も費用対効果よく守るテストレベルを選びます。

## Mutation Testingの役割

Mutation Testingはユーザーへ売る機能ではなく、テストの検知能力を裏付ける内部機構です。

```text
Base      → Pass
Head      → Pass
Mutant    → Fail
```

この結果から、テストが変更前後で同じ振る舞いを観測し、対象のバグが入れば実際に失敗することを確認します。既存テストがMutationを検知できなかった場合は、テスト不足として調査します。

```text
外部Event送信を削除
      ↓
既存テストが成功
      ↓
境界契約のAssertionを追加
      ↓
元コードで成功
      ↓
同じMutationで失敗
```

ただし、内部メソッドの削除や呼び出し順序の変更など、観測可能な振る舞いを変えないMutationは、テストへ強制的に検知させません。Mutation Scoreは成功基準にしません。

## 書き込みポリシー

既定のModeは**Review-only**です。PR、GitHub、リポジトリのWorking Treeのいずれへも書き込みません。

- GitHubへ自動投稿しない
- Headの本番コードを変更しない
- 比較テストとMutationは隔離環境で実行する
- 証明済み提案テストは、適用・Patch出力・破棄まで一時的なテスト専用Patchとして保持する
- 実行時の成果物は既定で一時的——実行後に保存しない・ローカル保存・Markdown出力から選択する
- コメント候補だけを提示する

ユーザーがテスト追加を明示的に依頼した場合——証明済み引き渡しで**テストを適用**を選んだ場合を含む——のみ**Apply tests**へ切り替え、確認済みIntentに基づくテストをWorking Treeへ追加します。適用前に引き渡しPreconditionを確認し、適用後に元コードの対象テストとMutation証明を繰り返します。Version Control操作はどちらのModeでもユーザーに残ります。

Socraticは、変更確認とBase・Head Snapshot出力のために、Allowlist化した読み取り専用のローカルGitコマンドだけを使えます。Stage、Commit、Push、Fetch、Branch切替、Worktree作成、Remote接続、`gh`呼び出し、Pull Request作成、コメント投稿は行いません。その許可も求めず、Version Control操作はすべてユーザーへ残します。

## 内部アーキテクチャ

```text
Pull Request / Local Diff
          |
          v
      Socratic
          |
          +-- Maieutic
          |     - クライアントの目標を特定
          |     - 観測可能な振る舞いを抽出
          |     - 依存を分類してOracleを選ぶ
          |     - 未確定のIntentを整理
          |     - 回答しやすい質問を生成
          |     - Intent Contractを管理
          |
          +-- Elenchus
                - BaseとHeadを隔離実行
                - 同じBehavior Testで比較
                - Intent Mutationを生成
                - テストの検知能力を評価
                - 既存・変更後のTest Cohortを比較
                - Behavior Diffを分類
          |
          v
Review This / We Verified / Still at Risk
          |
          v
Copy-ready Comments
```

MaieuticとElenchusをつなぐのは[Intent Contract](docs/ja/protocol.md)です。既定では一時的な実行Artifactであり、保存を選択した場合のみ`.socratic/intent-contract.json`へ書き込みます。判断、不変条件、副作用、根拠、テストによる保護状況を、小さく追跡可能な記録として保持します。

名前は次の関係を表します。

- **Socratic/ソクラティック**: 無知を自覚し、問い、反駁によって主張を検証する全体の方法
- **Maieutic/マウエティック**: 実装からは確定できない意図を人間から引き出すStage
- **Elenchus/エレンコス**: テストがその意図を実際に守るか反証するStage

## Elenchusを単独実行する

Modeや詳細Promptを覚えず、`$elenchus`だけで実行できる。Standalone実行では最初にDiffとTest構成を調べ、検出結果を反映した構造化質問を1つ提示する。

1. **今回の変更: 既存Testと変更Test(推奨)** — 既存Protectionと、追加・変更・削除されたTestの増分効果を評価する。
2. **変更Testのみ** — 小さいBudgetでTest Diffと変更前の対応Testを評価する。
3. **対象を広げる** — 実行Costが増えることを示したうえで、ModuleまたはRepository全体を選択する。

本番Codeだけが変わった場合、関連する既存Suiteを監査する。Testも変わった場合、同じRisk MutationをExisting・Changed Test Cohortへ実行して比較する。

| 既存Test | 変更Test | Outcome |
| --- | --- | --- |
| 検知 | 検知 | Existing Protection |
| 未検知 | 検知 | Incremental Protection |
| 検知 | 未検知 | Protection Regression |
| 未検知 | 未検知 | Still at Risk |

Standalone Outputは**Assessment Scope**、**Existing Protection**、**Changed Test Contribution**、**Still at Risk**、**Test Quality Concerns**とする。AssessmentはReview-onlyで、既定では不足Testを作らない。確認済みGapのHardeningを依頼するとDisposable環境で提案Testを証明し、Working Treeへの適用には別の明示依頼を必要とする。

Socraticから呼び出された場合は確定済みScopeを継承するため、ElenchusはScopeを再質問せず、同じ証拠をSocraticの正準4ブロックへ振り分ける。

## リポジトリ構成

```text
skills/
  socratic/   End-to-end Orchestration
  maieutic/   意図の引き出しとテスト設計・補完
  elenchus/   既存・変更TestのAssessmentとIntent Mutationによる検証
docs/
  protocol.md 共通概念とライフサイクル
schemas/
  intent-contract.schema.json
  mutation-result.schema.json
  mutation-report.schema.json
  test-handoff.schema.json
.github/workflows/
  ci.yml         リポジトリ検証
  release.yml    TagとGitHub Releaseの作成
```

`skills/`配下の各ディレクトリは、CodexとClaude Codeで利用できるAgent Skillです。統合された`$socratic` Workflowには3つすべてをインストールします。一方のStageだけが必要な場合は`$maieutic`または`$elenchus`を独立して実行できます。

## 非ゴール

v0.2では次を約束しません。

- BaseとHeadの完全な振る舞い同値性
- すべてのバグの検出
- すべての変更行のレビュー
- GitHubへの自動コメント投稿
- Mutation Scoreの最大化
- 4本の柱をすべて最大化すること
- Baseの実装を正しい仕様として扱うこと
- テストのために本番設計を不必要に変更すること

## 研究上の基盤

本プロジェクトは、相互補完的な2つの研究分野を代表する3本の論文から着想を得ています。

- [Harden and Catch for Just-in-Time Assured LLM-Based Software Testing](https://arxiv.org/abs/2504.16472)は、Hardening Test、Catching Test、およびCatching JiTTest Challengeを正式に定義した基礎論文です。
- [Just-in-Time Catching Test Generation at Meta](https://arxiv.org/abs/2601.22832)は、この枠組みを産業規模で適用し、Diff-awareおよびIntent-awareなCatching Testの結果と、人間が振る舞いの変化を意図したか判断するための低負荷な確認方法を報告しています。
- [Intent-Based Mutation Testing: From Naturally Written Programming Intents to Mutants](https://arxiv.org/abs/2607.05149)は、自然言語で表現された意図のVariantから実装を生成し、29プログラムを対象とした評価で、構文ベースMutationとは一部重ならない振る舞いとSubsumption関係を確認しています。

テスト設計の原則は、『単体テストの考え方/使い方』(Vladimir Khorikov著、Unit Testing Principles, Practices, and Patternsの邦訳)に基づきます。

Socraticはこれらの考え方を接続します。明示的なHuman-confirmed Intent Contract、Maieuticによる意図確定、Contract IDによるテストとMutationの対応付け、正準の4ブロック出力、Copy-readyなコメント候補は、論文や書籍の主張ではなくSocratic独自の設計です。本プロジェクトは独立したオープン実装であり、論文や書籍の著者または所属機関による実装や推奨ではありません。

## セキュリティ

組織で導入する場合は[セキュリティモデル](docs/ja/security-model.md)をReviewし、[企業向け導入ガイド](docs/ja/enterprise-installation.md)に従ってください。疑わしい脆弱性は[セキュリティポリシー](SECURITY.ja.md)に沿って非公開で報告してください。

Skillは、Git操作、Workspaceへの書き込み、Credential、Repository由来の指示、Disposable Mutation、Cleanupについて検証可能な境界を定義します。同梱Isolation Gateを通るMutation書き込みはPathを機械的に検証しますが、Host側のRead-only Mount、Network Policy、Provider契約、通常のHuman Reviewは独立した防御として必要です。

## 現在の状態

v0.2はリリース済みです。3スキルはピン留めしたGitHub Releaseからインストールでき、StandaloneのTest Assessment ModeとCI・自動Release Pipelineが利用可能です。現在のSourceには必須Host Adapter Review-only Entry Point、Fail-closed Isolation Gate、厳格な実行Artifact検証、Mutation Report v7、正準4ブロックRendererを追加しています。Standalone Mutation実行はBlockedで、信頼されたHostがRun Nonce、保護された外部Storage、Repository全体のRead-onlyまたはWrite Monitor Capabilityを発行する必要があります。

初期のコントリビューション方針は[CONTRIBUTING.ja.md](CONTRIBUTING.ja.md)を参照してください。

## ライセンス

Socraticは[MIT License](LICENSE)で提供します。

ソース: [github.com/Shogo1222/socratic](https://github.com/Shogo1222/socratic)

## 日本語資料

[日本語ドキュメント一覧](docs/ja/README.md)を参照してください。
