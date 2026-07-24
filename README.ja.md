<p align="center">
  <img src="./assets/socratic-logo.png" alt="Socratic" height="120">
</p>

[Webサイト](https://shogo1222.github.io/socratic/) | [English](README.md) | 日本語

# Socratic

[![CI](https://github.com/Shogo1222/socratic/actions/workflows/ci.yml/badge.svg)](https://github.com/Shogo1222/socratic/actions/workflows/ci.yml)
[![GitHub Release](https://img.shields.io/github/v/release/Shogo1222/socratic?include_prereleases)](https://github.com/Shogo1222/socratic/releases)

> Don't review every line. Review the decisions that matter.

Socraticは、AI生成の変更を評価するHost-gatedなReview Workflowです。AIは、意図の推論、重要な不確実性の抽出、現実的な事故モデルの設計、振る舞い証拠の解釈という「推論が必要な仕事」に集中します。決定論的なRunnerが、Command、使い捨てClone、Mutation、Schema、Hash、Report、Cleanupを所有します。

このWorkflowは3つのAgent Skillとして提供します。名前はソクラテスの問答法に由来します——分かっていないことを自覚して問いを立て(Socratic)、対話によって相手から意図を引き出し(Maieutic: 産婆術)、反駁によって主張を吟味する(Elenchus: 論駁)という関係です。

- **Socratic** — 全体のOrchestrator。変更をObservable Intent、維持すべきInvariant、現実的な事故、Residual Riskとして整理し、Repository Evidenceで確定できない判断だけを質問して、4ブロックのレビュー結果とコピーして使えるコメント候補を届けます。**アウトカム**: 大きなDiffを全部読む代わりに、少数の判断と貼るだけのコメントをレビューすればよい状態。
- **Maieutic** — 意図の引き出し役。実装だけでは確定できない期待値を、仕様オーナーが回答できる具体的な質問へ変換し、回答をIntent Contractへ記録して対応するテストと関連付けます。**アウトカム**: 「なんとなく不安」が、答えられる仕様質問と、テストに裏付けられた確定仕様の記録に変わる。
- **Elenchus** — 反証役。Focused Behavior Testを、Intentに結び付いた現実的なMutationでChallengeします。単独実行では、既存・変更Test Cohortが提供するProtectionを評価(Test Assessment)できます。**アウトカム**: 「テストがGreen」ではなく、「このバグを入れたら実際に落ちる」という証拠。

現在のIntegration Previewは、Claude Code・Codex・Local Cursor Desktop向けの**v0.5.0-beta.1**です。

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

## レビューの進み方

```text
Trusted Host Preflight
        ↓
MissionとReview Typeの確認
        ↓
範囲を限定したDiff調査とDiff理解の確認
        ↓
Intent Contract
        ↓
依存を一度だけ準備し、Focused TestをProbe
        ↓
現実的な事故Mutationを1 Batchで並列実行
        ↓
Raw Outcomeを解釈
        ↓
Runnerが証跡付きReviewを生成してCleanup
```

機械処理のたびに質問するのではなく、人間へ確認するのは次の4つのCheckpointです。

1. **Review Type** — Bug Fix Review、Feature Review、Refactor Guard、Test Assessment。
2. **Diff理解** — 解決する問題、変わる振る舞い、維持すべき振る舞い、新しいObservable、重要な不確実性。
3. **Intent／Oracle判断** — Repository Evidenceで重要な観測可能期待値を確定できない場合だけ。Repository内の証拠で確定できるIntentは質問せず記録する。
4. **最終解釈とDisposition** — 証拠から分かったこと、残るリスク、一時Artifactや証明済みTest変更を保持するか。

起動直後にRunnerが、ID用語集、Gate順序、編集可能Field、次の正確なCommandを含むRunbookを渡します。Agentは実行予定をユーザーの言語で説明し、各Phaseをアナウンスします。Schema、Run ID、Hash、Ledger、最終Reportを手書きしません。

Mutationでは依存を一度だけ導入します。RunnerがFocused CommandをProbeし、導入済みPackageを共有Dependency LayerとしてSealしてから、Mutationごとに新しいCopy-on-write Source Sandboxを分岐します。HOME、Temp、Package Cache、`node_modules/.vite`等のRuntime DirectoryはSandboxごとに分離するため、高速な共有が通常のTest Cache書き込みをDependency改変として誤検知しません。

## ID・状態・結果の早見表

これらの値を利用者が手書きする必要はありません。RunnerのRunbookとScaffoldが有効なFieldを用意します。ここでは進捗表示やArtifactに出てくる用語の意味だけを説明します。

### Contract ID

| Prefix | 意味 | 例 |
|---|---|---|
| `DEC` | 期待する観測可能な振る舞いについて確定した判断 | Redirect時にEventを出すか |
| `INV` | 変更後も維持すべき既存の観測可能な振る舞い | 本物のApplication Errorは引き続きLogする |
| `FX` | 必須または禁止される副作用 | Eventは1回だけEmitし、Drainを重複させない |
| `UNR` | Repository Evidenceだけでは決められない重要な質問 | 無Logと正常Eventのどちらが意図か |
| `CMD` | RunnerがProbeに成功したFocused Test Command | Mutationでも再利用するVitest Command |
| `MUT` | Disposable Cloneへ注入する現実的な事故 | Navigation Signal Guardを削除する |

`UNR-*`は単なるFinding名ではなくGateです。その未解決Oracleに紐づくMutationだけを停止し、独立した確定済みContract項目は継続できます。

### Intent ContractのLifecycle

```text
provisional
    ├─ 複数の合理的Oracle → needs-decision → confirmed
    └─ 権威ある証拠 ─────────────────────→ confirmed
confirmed → tested → challenged → hardened
```

| Status | 意味 |
|---|---|
| `provisional` | DiffとRepository EvidenceからIntentの仮説を立てた |
| `needs-decision` | 複数の合理的な期待があり、Test Oracleが分かれる |
| `confirmed` | 仕様決定者または権威あるRepository Evidenceが必要なOracleを確定した |
| `tested` | 安定して永続するTestが確定済みContractを保護している |
| `challenged` | 安定したTestへRisk-directed Mutationを実行した |
| `hardened` | 選んだHigh-risk MutantをKillし、未ChallengeのRiskを明示した |

実装がたまたまPassすることはIntentの確定ではありません。Review-onlyでDisposable Workspace上のProposed Testだけに依存する証明は、そのTestを適用するまで`tested`や`hardened`には進みません。

Decision provenanceは、*誰または何がOracleを確定したか*を表します。

| Value | 意味 |
|---|---|
| `repository-established` | 権威あるRepository Evidenceで確定できるため、人間への質問は不要 |
| `user-confirmed` | 仕様決定者または権限を委任された代理人が明示的に決定 |
| `reviewer-selected-benchmark-assumption` | 仕様決定権のないReviewerが評価用の前提を選択 |

### ElenchusのMode

| Mode | 目的 |
|---|---|
| `assessment` | Existing／Changed Test Cohortが何を検知するか測る。既定ではTestを作らない |
| `harden` | 確定済みの振る舞いをChallengeし、現実的な事故への保護を証明する |
| `catch` | Intent確定前にParent側の事故を使い、振る舞いの変化候補を表面化する |

### Mutation Result

| Result | 意味 |
|---|---|
| `killed` | 安定した関連Testが、意図した振る舞い違反を理由にFailした |
| `survived` | 安定した関連TestがGreenのままで、想定事故を検知できなかった |
| `invalid` | Mutationが想定Riskを発生させられなかった |
| `equivalent` | 観測可能なContract差がないことを証拠で確認した |
| `timeout` | 制限時間内に実行が終わらなかった |
| `inconclusive` | Infrastructure、Flaky、Crash、無関係な失敗により判断不能 |
| `weak-catch` | CandidateがParent側の事故を捉え、振る舞い差の可能性を示した |
| `strong-catch` | 仕様決定者が、捉えた振る舞いを意図しない変更だと確認した |
| `false-positive` | 仕様決定者が、捉えた振る舞いを意図した変更だと確認した |
| `not-comparable` | ParentとProposed RevisionでCandidateを同条件実行できない |
| `no-catch` | CandidateがProposed Diffを捉えなかった |

<details>
<summary>その他のReport enum</summary>

- Raw Outcomeの`kind`: `passed`、`behavioral-failure`、`infrastructure-failure`、`process-crash`、`timeout`、`unparseable`。Processが非0終了しただけでは`killed`にならず、Assertion Evidenceが対象Contract違反を示す必要があります。
- Intentの`confidence`: `high`、`medium`、`low`は引用したEvidenceの強さを表し、Review全体のScoreではありません。
- Mutationの`severity`: `critical`、`high`、`medium`、`low`は想定事故が起きた場合の影響を表します。`likelihood`: `high`、`medium`、`low`は発生のもっともらしさで、どちらもTest Outcomeではありません。
- Testの`disposition`: Run開始時からある`existing`、Disposable Workspaceだけで証明した`proposed`、明示的な許可後に適用した`applied`。
- `not_challenged.reason`: `budget`、`not-observable`、`not-applicable`、`deferred`、`blocked`。各項目にはResidual Riskが付きます。
- Assessment Scope: `current-change`、`changed-tests`、`broader-target`。
- Cohort比較: `existing-protection`、`incremental-protection`、`protection-regression`、`unprotected`、`not-comparable`、`inconclusive`。
- Catchの`human_verdict`: `intended`、`unintended`、`unanswered`、`not-requested`。
- `Review This`のkind: `confirmed-behavior`、`behavior-difference`、`test-gap`、`needs-decision`。
- Copy-ready Commentのtag: `Intent decision`、`Behavior difference`、`Test gap`。

Machine-readableな正規定義は同梱の[schemas](schemas/)にあり、[Intent Testing Protocol](docs/ja/protocol.md)がLifecycleとGateを説明します。

</details>

## インストール

Socraticの対象HostはClaude Code・Codex・Local Cursor Desktopです。このIntegration Previewでは、それ以外のAgent Hostはサポートしません。現在のPreview Releaseは[v0.5.0-beta.1](https://github.com/Shogo1222/socratic/releases/tag/v0.5.0-beta.1)です。

### Claude Code

RepositoryをClaude Code Marketplaceとして追加し、PluginをInstallしてください。

```text
/plugin marketplace add Shogo1222/socratic
/plugin install socratic@socratic-marketplace
```

公開Versionの更新を取得する場合は、Catalogを更新してからPluginをUpdateします。

```text
/plugin marketplace update socratic-marketplace
/plugin update socratic@socratic-marketplace
/reload-plugins
```

その後、信頼済みGit Repositoryで通常どおりClaudeを起動し、Claude Codeが実際に表示するPlugin名前空間付きCommand `/socratic:socratic`をPromptの先頭で実行してください。GitHub Pull RequestをReviewする場合は、Hostが実行開始前に当時の正確なBase・HeadをMaterializeできるよう、最初の呼び出しへPRを含めます。

```text
/socratic:socratic https://github.com/owner/repository/pull/123 日本語で
```

PluginはClaudeがRequestを処理する前にSession単位のHost brokerを自動起動し、`PreToolUse`でPrimaryへの直接WriteとRunner外Bashを拒否します。MaieuticとElenchusの直接起動にも同じGateを使います。Run Manifestが存在する間は`Stop`後もbrokerを維持して人間の判断をTurn間で継続し、FinishまたはAbort後にCleanupします。放棄・stale状態のbrokerはIdle TTLと後続Host Eventで回収します。専用Launcher Commandは不要です。

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

```text
$socratic https://github.com/owner/repository/pull/123 日本語で
```

### Cursor Desktop

Repositoryには`.cursor-plugin/`配下のNative Cursor Pluginも含まれます。Cursor DesktopへLocal PluginとしてInstallし、WindowをReloadしてから、Local DiffまたはPRを指定して`$socratic`を実行します。Pluginは`beforeSubmitPrompt`、`preToolUse`、`beforeShellExecution`をFail-closedで使用します。現行Hook coverageでは同じ境界を証明できないため、Cursor CLI、Remote Workspace、Cloud Agentはサポートしません。Cursor Marketplaceからの公開Installは、Cursor側の別途Submission審査を通過するまで利用できません。

### Standalone Maieutic・Elenchus

Standalone Agent SkillはCodexまたはCursorでMaieutic・Elenchus分析に利用できますが、Standalone Skill InstallはMutationを実行できる準拠`$socratic` Entry Pointではありません。

```bash
# 対話式でSkillと導入先のCodexまたはCursorを選ぶ
gh skill install Shogo1222/socratic

# 3つのSkillをすべてインストール
gh skill install Shogo1222/socratic --all

# Integration Preview ReleaseへStandalone Resourceをピン留め
gh skill install Shogo1222/socratic --all --pin v0.5.0-beta.1
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

### Bug Fix Review

報告された不具合を直す変更では、Failureが解消され、Fixが無関係な振る舞いまで広がっていないことを確認します。事故Planでは、Bugの再導入と、もっともらしい過剰修正の両方を扱います。

```text
報告されたFailure
      ↓
期待する修正後の振る舞い
      +
維持すべき既存の振る舞い
      ↓
Focused Baseline + 事故Mutation
```

### Feature Review

新しい機能や仕様変更を含むPRに対して、実装だけでは確定できない期待値を抽出します。

```markdown
契約終了日と更新日が同日の場合も、更新を許可する意図でしょうか？

終了日当日を有効期間に含めるかによって、この境界条件の期待値が変わります。現在のリポジトリ内からは判断できなかったため、期待する振る舞いを確認したいです。
```

確定した仕様はIntent Contractへ記録し、対応するテストと関連付けます。

### Refactor Guard

振る舞いを維持するはずのリファクタリングでは、HostがMaterializeした正確なBase／Head Diffから維持すべきObservable Invariantを確定し、Prepared Head Snapshot上のFocused TestをMutationでChallengeします。

```text
正確なBase / Head Snapshot
          ↓
維持すべきObservable Invariant
          ↓
Focused Head BaselineがPass
          ↓
現実的なMutantはFailすべき
```

RepositoryまたはFocused Comparison Evidenceから差が見つかった場合は、意図した変更か回帰かを人間へ確認します。

```markdown
このリファクタリングでは、期限切れ判定の境界条件が変わっているようです。

契約終了日と実行日が同じケースについて、変更前は更新できますが、変更後は拒否されます。

振る舞いを維持するリファクタリングであれば、意図しない変更の可能性があります。この変更は意図したものでしょうか？
```

Refactor Guardが信頼できるためには、比較テストが内部構造ではなく観測可能な振る舞いを検証していなければなりません。実装依存のテストが生む偽陽性は、Behavior Diffとして報告しません。

### Test Assessment

テストそのもの——特にAIが追加したテスト——を評価するには、`$elenchus`を単独実行します。同じリスクMutationを既存・変更後の両テスト集合と比較し、既存Protection、増分Protection、Protection Regression、未保護のリスクを分離します。詳細は後述の「Elenchusを単独実行する」を参照してください。

## Behavior Diffの分類

BaseとHeadの両方について安定したBehavior Comparisonが得られた場合は、次のように分類します。Infrastructure FailureやMutation Outcomeをこの比較の代用にしません。

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
  ! 期限当日の振る舞いが変化。意図した変更か仕様オーナーの判断が必要。

We Verified:
  ✓ 既存の境界Testが二重更新と誤ったEvent送信を検知。
  ✓ 今回のReview-only実行中、Working Treeは不変

Still at Risk:
  △ Clockを制御できないためTimezone境界は未検証。

Copy-ready Comments:
  1 comment for src/subscription.ts:52
```

マージ可否、信頼度、総合スコアは表示しません。Socraticが報告するのは、検証した範囲、判断事項またはFinding、未検証範囲です。マージ判断はReviewerに残します。詳細Artifactは既定で一時的で、`complete`前にLocal保存またはMarkdown出力を選ばなければRender後に破棄します。

## 人間の判断とコメント

未解決のBehavior Diffは、HostネイティブUIの構造化質問になります。

```text
Behavior Diff
  → 構造化された判断
  → Intent Contract
  → TestとMutationの証拠
```

1回のBatchは1〜3問で、相互排他的な具体的選択肢、観測可能な影響、権限が不明な場合の仕様オーナーへ保留する選択を含みます。Claude Codeは`AskUserQuestion`、Codexは`request_user_input`、その他の環境はコピー可能なMarkdownで表示します。

質問するのはMain Agentです。HostがTargetを渡し、Runnerが範囲を限定した調査と実行を担当します。その後Socraticは、`Intent decision`、`Behavior difference`、`Test gap`のいずれかを付けたCopy-ready Commentを最大3件生成し、自動投稿はしません。各Commentには観測した振る舞い、必要な判断または不足する保護、その重要性、各回答で変わることを含めます。行へ固定できない問題はStill at Riskへ残します。

## テスト設計とMutationの原則

Socraticがテストする単位は、クラス、メソッド、内部呼び出し順序ではなく、**観測可能な振る舞い**です。

```text
クライアントの目標
  → 操作
  → 出力・最終状態・外部境界を越える通信
  → 適切なLevelの最小で安定したTest
```

- Oracleは、出力値、観測可能な最終状態、Application境界を越える通信の順に優先する。
- 重要な管理下StateにはFocused Integration Test、境界Contractには少数のE2E Testを使う。
- 内部Method順序、交換可能なAlgorithm、Repository呼び出し回数、結果へ影響しない中間状態をAssertionにしない。
- Riskに応じて退行保護、Refactoring耐性、Feedback速度、保守性を配分する。全てを最大化できる単一のTest Levelはない。

Mutation Testingは、選んだTestが現実的な事故を検知できることの内部証明です。

```text
Prepared Head Baseline  → Pass
Fresh Mutant Clone      → 対象Contract違反を理由にFail
```

MutationがSurviveした場合は、Scenario不足、弱いOracle、境界Gap、未解決Intentを調べます。観測可能な振る舞いを変えないMutationを無理に検知させず、Mutation Scoreも成功基準にしません。詳細は[QA Techniques](skills/maieutic/references/qa-techniques.md)、[Mutation Design](skills/elenchus/references/mutation-design.md)、[Intent Testing Protocol](docs/ja/protocol.md)にあります。

## 書き込みポリシー

既定のModeは**Review-only**です。PR、GitHub、リポジトリのWorking Treeのいずれへも書き込みません。

- GitHubへ自動投稿しない
- Headの本番コードを変更しない
- 比較テストとMutationは隔離環境で実行する
- 証明済み提案テストは、適用・Patch出力・破棄まで一時的なテスト専用Patchとして保持する
- 実行時の成果物は既定で一時的——`complete`前に明示的な保持選択を記録し、無回答なら破棄する
- コメント候補だけを提示する

ユーザーがテスト追加を明示的に依頼した場合——証明済み引き渡しで**テストを適用**を選んだ場合を含む——のみ**Apply tests**へ切り替え、確認済みIntentに基づくテストをWorking Treeへ追加します。適用前に引き渡しPreconditionを確認し、適用後に元コードの対象テストとMutation証明を繰り返します。Version Control操作はどちらのModeでもユーザーに残ります。

Socratic Agentは、HostがMaterializeした変更を確認するために、Allowlist化した読み取り専用のローカルGitコマンドだけを使えます。Stage、Commit、Push、Fetch、Branch切替、Worktree作成、Remote接続、`gh`呼び出し、Pull Request作成、コメント投稿は行いません。起動PromptにGitHub PR URLまたは`PR #<number>`が含まれる場合は、AgentではなくTrusted Hostが`gh`でMetadataを解決し、正確なBase・Head CommitをPrivate Host StorageへFetchして両SHAを検証し、RunnerへRead-only Snapshotを渡します。BaseはBranchの現在の先端ではなくImmutableな当時のSHAでFetchするため、Target Branchが進んだ後もMerged済み・過去のPRを再現できます。どちらかのCommitを解決・検証できなければ、失敗したMaterialization段階を示してRunはBlockedになります。Version Controlへの書き込みはすべてユーザーへ残します。

Hostは正確なTarget、変更File一覧、Package Manager Hint、固定Fast Pathを含む簡潔なReview Contextも注入します。決定論的なDiff・Environment調査をSubagentへ委譲しません。Mutation前にIntent ContractをStageし、各ChallengeへContract IDを持たせ、RunnerがMutant作成前に未解決OracleをBlockします。Canonicalな`Review This` ItemはContractへLinkし、Attested ReportへBaseline・Mutationの実測時間を含めます。終端となる`complete`失敗は使い捨てRunをCleanupし、Canonical Reviewを生成しません。Agentは失敗を報告し、必要ならFresh Runを開始します。手書きの代替出力や削除済みManifestでの再試行は行いません。

## 内部アーキテクチャ

```text
Pull Request / Local Diff
          |
          v
Trusted Host
  - 正確なTargetをMaterialize
  - BrokerとTool Gateを起動
  - Run Identityと保護Storageを発行
          |
          +-------------------------------+
          |                               |
          v                               v
AIの推論                            決定論的Runner
  - Observable Intentを推論            - 範囲限定Inspect
  - 重要な不確実性を抽出               - 依存を一度だけ準備
  - 現実的な事故を設計                 - Focused CommandをProbe
  - Raw Outcomeを解釈                  - 並列Clone・Mutation
  - Reviewer向けClaimを記述            - 検証・Attest・Render・Cleanup
          |                               |
          +---------------+---------------+
                          v
        Review This / We Verified / Still at Risk
                          |
                          v
                 Copy-ready Comments
```

AIが保護されたHost Storage内で編集できるSemantic Inputは、Intent Contract、Challenge Plan、Review Analysisの3つだけです。いずれもRunnerが生成したDocumentと固定絶対Pathから始めます。最初の`Write`でFileを作成し、修正時は`Read`後に`Edit`します。Report Identity、実行Evidence、Hash、Append-only Ledger、最終Renderer、CleanupはRunnerが所有します。

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
hooks/
  *_preflight.py   Host起動とTarget Materialization
  *_tool_gate.py   Review-only Tool Enforcement
schemas/
  intent-contract.schema.json
  challenge-plan.schema.json
  review-analysis.schema.json
  mutation-result.schema.json
  mutation-report.schema.json
  run-manifest.schema.json
  test-handoff.schema.json
tests/
  schema/        Schema Contract
  distribution/ ReleaseとBundleの整合性
  hosts/         Claude Code・Codex・Cursor統合
  runner/        Guarded実行とRendering
  security/      Isolation境界
  workflow/      IntentとLifecycle Gate
.github/workflows/
  ci.yml         リポジトリ検証
  release.yml    TagとGitHub Releaseの作成
```

`skills/`配下の各ディレクトリはAgent Skillです。Native Host Pluginが、統合Socratic Workflowに必要な3つすべてを同梱します。一方の分析Stageだけが必要な場合は`$maieutic`または`$elenchus`を独立して実行できます。

v0.5 Integrationでは、正準Mutation MechanicsをAgent InstructionからHost-gated Runnerへ移しました。確定したDecisionと型付きTest Profile境界は[Runner Architecture Decision](docs/ja/runner-architecture.md)と[Runner Test Profile](docs/ja/test-profiles.md)に記載しています。より限定的な`local-copy` Experiment Pathは開発用の未署名Evidenceを生成できますが、正準のAttested Review Surfaceは生成できません。

## 非ゴール

Socraticは次を約束しません。

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

**v0.5.0-beta.1**が現在のIntegration Previewです。Claude Code・Codex・Local Cursor DesktopのNative Host Path、正確なGitHub PR Materialization、Runner所有のRunbookとScaffold Guide、1回だけのDependency準備、Probe済みFocused Command、並列Copy-on-write Mutation Sandbox、Runtime Cache分離、厳格なRun Artifact検証、Mutation Report v10、正準4ブロックRenderer、終端Cleanupを含みます。

Standalone Mutation実行は意図的にBlockedです。信頼されたHostがRun Nonce、保護された外部Storage、Repository全体のRead-onlyまたはWrite Monitor Capabilityを発行する必要があります。このPreviewは実際のPull RequestでDogfooding済みですが、まだBetaです。Hostごとの実機E2E([Release Checklist](docs/release-checklist.md)で管理)、より多くのRepositoryとTest Runner、Failure Recovery、Performanceは継続検証対象で、信頼できないTest CodeへのOSレベル封じ込めはありません——手元でTest Suiteを実行できると既に信頼しているRepositoryにだけ使ってください。

初期のコントリビューション方針は[CONTRIBUTING.ja.md](CONTRIBUTING.ja.md)を参照してください。

## ライセンス

Socraticは[MIT License](LICENSE)で提供します。

ソース: [github.com/Shogo1222/socratic](https://github.com/Shogo1222/socratic)

## 日本語資料

[日本語ドキュメント一覧](docs/ja/README.md)を参照してください。
