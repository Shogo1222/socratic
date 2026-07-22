[English](README.md) | 日本語

# Socratic

[![CI](https://github.com/Shogo1222/socratic/actions/workflows/ci.yml/badge.svg)](https://github.com/Shogo1222/socratic/actions/workflows/ci.yml)
[![GitHub Release](https://img.shields.io/github/v/release/Shogo1222/socratic)](https://github.com/Shogo1222/socratic/releases)

> Don't review every line. Review the decisions that matter.

Socraticは、Pull Requestのコードをすべて説明するツールではありません。変更前後の振る舞いを比較し、人間が判断すべき仕様、意図しない可能性のある変更、既存テストが検知できない重要なリスクだけを抽出します。

PRの「なんとなく不安」を、仕様オーナーが回答できる具体的な質問と、根拠のある振る舞い差へ変換します。

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

## 対象ユーザー

最初の対象は、AI生成PRをレビューするシニアエンジニアとTech Leadです。Socraticはレビューを代替せず、レビュアーが重要な判断へ集中するための材料を作ります。GitHubへ自動投稿せず、対象行へコピーできるインラインコメント候補を生成します。投稿、編集、破棄の判断はレビュアーが行います。

仕様質問の回答者は、コードの作者とは限りません。PR作者、レビュアー、Product Owner、Domain Expert、Tech Lead、APIやデータのOwnerといった、その仕様のオーナーが回答します。AIがコードを生成した場合、AIは仕様の根拠にも回答者にもなりません。レビュアーが回答権限を持たない場合は、コメント候補を仕様オーナーへ確認するために使います。

## 2つのユースケース

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

マージ可否、信頼度、総合スコアは表示しません。Socraticが報告するのは、検証した範囲、発見した問題または判断事項、検証できなかった範囲の3点であり、マージ判断はレビュアーに残します。詳細なIntent Contract、Mutation結果、Test Strategy、実行コマンドは一時的な実行Artifactとして保持し、実行後に保存しない(デフォルト)・ローカル保存・Markdown出力から選べます。

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
- 実行時の成果物は既定で一時的——実行後に保存しない・ローカル保存・Markdown出力から選択する
- コメント候補だけを提示する

ユーザーがテスト追加を明示的に依頼した場合のみ**Apply tests**へ切り替え、確認済みIntentに基づくテストをWorking Treeへ追加します。Version Control操作はどちらのModeでもユーザーに残ります。

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

- **Socratic**: 無知を自覚し、問い、反駁によって主張を検証する全体の方法
- **Maieutic**: 実装からは確定できない意図を人間から引き出すStage
- **Elenchus**: テストがその意図を実際に守るか反証するStage

## リポジトリ構成

```text
skills/
  socratic/   End-to-end Orchestration
  maieutic/   意図の引き出しとテスト設計・補完
  elenchus/   Base/Head比較とIntent Mutationによる検証
docs/
  protocol.md 共通概念とライフサイクル
schemas/
  intent-contract.schema.json
  mutation-result.schema.json
  mutation-report.schema.json
.github/workflows/
  ci.yml         リポジトリ検証
  release.yml    TagとGitHub Releaseの作成
```

`skills/`配下の各ディレクトリは、CodexとClaude Codeで利用できるAgent Skillです。統合された`$socratic` Workflowには3つすべてをインストールします。一方のStageだけが必要な場合は`$maieutic`または`$elenchus`を独立して実行できます。

## インストール

[Shogo1222/socratic](https://github.com/Shogo1222/socratic)から3スキルすべてをインストールします。

会社管理端末では、固定したReleaseをPreviewしてからProject ScopeへInstallします。

```bash
GH_TELEMETRY=false gh skill preview \
  Shogo1222/socratic socratic@v0.2.0

GH_TELEMETRY=false gh skill install \
  Shogo1222/socratic \
  --all \
  --agent codex \
  --scope project \
  --pin v0.2.0
```

GitHub CLIのAgent Skills Commandは現在Previewです。会社でCLIと対象AI Hostが許可されていることを確認してください。Project ScopeはInstall先を現在のRepositoryへ限定しますが、HostがRepository DataをAI Providerへ送信するかどうかは制御しません。

互換手段としてOpen Agent Skills CLIも残しますが、次の固定されていないCommandは個人評価用であり、企業向けの推奨Install経路ではありません。

```bash
npx skills add Shogo1222/socratic --skill '*'
```

その後、コード変更に対して`$socratic`を実行します。一方のStageだけが必要な場合は`$maieutic`または`$elenchus`を直接実行します。

## MVPの範囲

v0.2では、次の条件へ対象を絞ります。

- 既存のテスト環境がある
- BaseとHeadをローカルで実行できる
- 戻り値、例外、状態、副作用を決定的に観測できる
- Feature ReviewかRefactor Guardか判断できる
- 重要なBehavior Probeを最大3〜5件に限定する
- BaseとHeadへ同一テストを実行する
- 重要なMutationだけを選択する
- GitHubへ自動投稿しない
- ファイル名と行番号付きのコメント候補を生成する
- 未検証範囲とテスト戦略上のトレードオフを報告する

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

## CIとRelease

GitHub Actionsは、すべてのPull Requestと`main`へのPushに対して、[CONTRIBUTING.ja.md](CONTRIBUTING.ja.md)に記載したものと同じリポジトリ整合性Checkを実行します。さらにAgent Skills Metadata、配布監査Test、`skills/`配下の想定外File・実行権限・Binary・Symbolic Link、外部URL Host、必須安全規則を検証し、一時Directoryへ実際に14 FileをInstallします。File ManifestとFile単位のHashはCI証跡としてUploadします。第三者ActionはすべてCommit SHAへ固定します。

Maintainerは`main`上で **Actions → Release → Run workflow** を開き、Releaseを作成します。`0.2.0`のようなSemantic Versionを入力します。先頭の`v`も受け付けます。WorkflowはRepository、配布物、Install結果、Versionを検証し、既存Tagとの重複を拒否したうえで、Annotated Tag `v0.2.0`、Skill別・Suite ZIP、`SHA256SUMS`、`SKILL_SHA256SUMS`、JSON File Manifest、自動生成Release Noteを公開します。DraftとPrereleaseにも対応します。

Release WorkflowはSource Fileを変更しません。Git TagをRelease Versionの正本とします。公開ReleaseではRepositoryのImmutable Releasesを必須とし、Workflow完了前にReleaseと全添付Assetを検証します。最初のReleaseでは、Actionsへ秘密署名鍵を保持させず、Immutable Release Attestationを信頼の基点にします。

公開済みReleaseとDownloadしたAssetはGitHub CLIで検証できます。

```bash
gh release verify v0.2.0 --repo Shogo1222/socratic
gh release verify-asset v0.2.0 ./socratic-v0.2.0.zip \
  --repo Shogo1222/socratic
```

## 現在の状態

現在はv0.2のスキル設計段階です。プロトコルとエージェントワークフローは利用できますが、決定的な言語別アダプターと、隔離されたBase/Head比較・Mutation Runnerは今後の実装対象です。

初期のコントリビューション方針は[CONTRIBUTING.ja.md](CONTRIBUTING.ja.md)を参照してください。

## ライセンス

Socraticは[MIT License](LICENSE)で提供します。

ソース: [github.com/Shogo1222/socratic](https://github.com/Shogo1222/socratic)

## 日本語資料

[日本語ドキュメント一覧](docs/ja/README.md)を参照してください。
