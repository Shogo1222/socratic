[English](../protocol.md) | 日本語

# Intent Testing Protocol

## 目的

このプロトコルは、仕様の根拠とコードの振る舞いを分離し、Socraticが統合するMaieuticからElenchusへの受け渡しを永続化して監査可能にします。

## 実行時の成果物

実行時の成果物はChat-firstかつ既定でEphemeralです。実行中、Intent ContractとCatchまたはHarden Reportは、リポジトリのWorking Tree外の一時Artifactとして、インストールされたスキルへ同梱されたSchemaで検証され、Path経由でStage間を受け渡されます。会話内だけのContractはFallbackであり、通常の受け渡し方法ではありません。

Review-onlyで不足テストを証明した場合、ElenchusはWorking Tree外へ一時的な証明済みテスト引き渡しも作成します。これは、テスト専用Patchと検証済みManifestからなり、ユーザーが「テストを適用」「Patchを出力」「破棄」のいずれかを選ぶまでだけ保持します。永続的なテストの代わりにはなりません。

最終Surfaceの描画後、まず構造化質問で証明済みテストを「適用・Patch出力・破棄」のいずれかに処理します。別の実行Artifact質問では、保存しない(デフォルト)、ローカルに保存、Markdownとして出力の3択を提示します。ローカル保存を選んだ場合の正準Pathは次のとおりです。

- `.socratic/intent-contract.json`: Maieuticが作成する現在のIntent Contract
- `.socratic/elenchus-report.json`: Elenchusが作成する最新のCatchまたはHarden Report

## メインライフサイクル

```text
PROVISIONAL（暫定）
  Diffとリポジトリの根拠から意図の仮説を作る。

NEEDS_DECISION（判断待ち）
  複数の妥当な期待値が異なるテストオラクルを生む。

CONFIRMED（確認済み）
  責任を持つ人間または権威ある根拠が必要なオラクルを確定する。

TESTED（テスト済み）
  安定したテストが確認済みの判断と不変条件を保護する。

CHALLENGED（反証済み）
  リスクを考慮したMutationを安定したテストへ実行した。

HARDENED（強化済み）
  選択した高リスクMutantを検知し、未挑戦リスクを明示した。
```

未解決項目は`TESTED`へ進めません。実装が成功することは仕様確認ではありません。予算切れだけでは`HARDENED`にならず、未挑戦項目と残存リスクの明示的な受容が必要です。`TESTED`と`HARDENED`には、実行後も残るテスト——既存テスト、またはWorking Treeへ適用済みのテスト——が必要です。証明が提案テストだけに依存するReview-only実行は、`CONFIRMED`または`CHALLENGED`で止まります。

## Catch分岐

Catch Modeは`PROVISIONAL`または`NEEDS_DECISION`から分岐します。

```text
Parentで成功しMutantで失敗するCandidate Test
  -> 提案Diffで実行
  -> 振る舞いとして失敗: WEAK_CATCH
  -> 人間が意図しないと回答: STRONG_CATCH
  -> 人間が意図したと回答: FALSE_POSITIVE
  -> 無回答: NEEDS_DECISION
```

ParentとDiffの両方で比較可能にBuild・実行できないテストは`not-comparable`であり、Weak Catchではありません。Infrastructure、Flaky、Missing Symbol、無関係な失敗は判定不能です。

## 中核となる記録

### Intent Contract

正式な機械可読形式は[intent-contract.schema.json](../../schemas/intent-contract.schema.json)です。変更範囲、ライフサイクル状態、観測可能な意図と根拠、確認済み判断と由来、不変条件、副作用、未解決判断、テストとの対応を保持します。

Decision Provenanceは次の2値だけです。

- `user-confirmed`
- `repository-established`

未確認の推論は`intent.evidence`、未解決のオラクル選択は`unresolved`へ記録します。

### Mutation Result、Report、Test Handoff

[mutation-result.schema.json](../../schemas/mutation-result.schema.json)は、Candidate設計から実行までの1つのIntent MutationをAssessment・Catch分類を含めて表現します。[test-handoff.schema.json](../../schemas/test-handoff.schema.json)は、証明済みテストの正確なPatch、ファイルHashのPreconditionとPostimage、Contract対応、双方向証跡を表現します。[mutation-report.schema.json](../../schemas/mutation-report.schema.json)は、Write Mode、Baseline証跡、Test AssessmentのScopeとCohort比較、未挑戦Contract ID、未解決判断、Test Changeと引き渡しStatus、許可されたWorkspace変更、Mutation除去の実行後証跡を含む実行全体を表現します。

## 人間が判断する境界

次のすべてを満たす場合だけ質問します。

1. 複数の合理的な期待値が残る
2. 品質確認済みのリポジトリ根拠では解決できない
3. 回答が観測可能なオラクルまたは重要な副作用を変える
4. 誤った推測に無視できないコストがある

最小で具体的な振る舞いの差または明示的な選択肢を提示します。順位付けでは重大度、確信度、人間のDismiss Costを考慮します。無回答なら`needs-decision`を永続化し、独立した確認済み作業だけを続け、回答を捏造しません。

判断は、利用可能ならHostの構造化質問ツール——Claude Codeでは`AskUserQuestion`、Codexでは`request_user_input`——で提示し、利用できなければコピー可能なMarkdownとして提示します。1回のBatchは1〜3問で、各質問に相互排他的な選択肢を2〜3個、選択肢ごとに観測可能な影響の1文、自由入力の受け付け、回答によって変わるOracleを含めます。質問はメインエージェントだけが行い、サブエージェントは調査・テスト・Mutationを担当して未解決の判断を返します。プロトコルが保証するのは構造化された質問内容であり、その表示はHostの機能です。

## Elenchus Assessment Scopeの境界

直接の`$elenchus`実行はTest Assessment Modeを既定とします。変更本番File、関連する既存Test、変更Testを検出し、Mutant生成前に1つの構造化Scope質問を行います。選択肢は、今回の変更と既存・変更Test(推奨)、変更Testのみ、ユーザー指定の広いTargetです。Socraticは正確なScopeを渡し、この重複質問を抑止します。

Assessmentでは同一のRisk MutantをDisposableなExisting・Changed Test Cohortへ実行し、`existing-protection`、`incremental-protection`、`protection-regression`、`unprotected`、比較不能・判定不能を分けて報告します。変更Assertionを調べる前にRiskを導出し、実用的ならHoldout Riskを含めます。確認済みIntentがなければ、暫定Assessmentが証明できるのは表現した振る舞いの検知であり、その振る舞いの正しさではありません。

Standalone AssessmentはReview-onlyで、既定ではTestを作りません。Surviving GapのHardeningには別の依頼と確認済みIntentを必要とし、そのTestの適用にはさらに明示的な許可を必要とします。

## Review出力の境界

レビュアー向けのSurfaceは、Review This、We Verified、Still at Risk、Copy-ready Commentsの4ブロックだけです。発見は種類ではなく状態で振り分けます。未確定のBehavior Diffと未解決の判断はReview This、意図的と確認済みの変更・適用済みまたは証明済み提案のテスト・解決済みTest Gap・実証した検知能力はWe Verified、未検証のすべてはStill at Riskです。提案テストに依存する解決は、あわせてStill at Riskへ「保護は未適用」として記載します。この4ブロックSurfaceはSocraticが統合するReview出力に適用されます。StandaloneのTest Assessment実行は、Elenchus Assessment Scopeの境界で定義するAssessment Surfaceを使います。

証明済みテストをどう処理するかという運用上の選択は、この4ブロックの後にHostの構造化質問UIで提示し、5つ目のReviewブロックにはしません。

コメント候補は最大1〜3件で、`Intent decision`、`Behavior difference`、`Test gap`のTagとファイル・行番号を持ちます。`Intent decision`の回答者は仕様オーナーであり、AIがコードを生成した場合、AIは仕様の根拠にも回答者にもなりません。スキルはCode Hostへ投稿せず、マージ可否、信頼度、総合スコアを報告しません。マージ判断はレビュアーに残します。Contract、Mutation結果、Test Strategy、実行コマンドなどの詳細は実行時の成果物に保持します。

## Write Modeの境界

既定はReview-onlyです。Probe、比較テスト、MutationはDisposable環境だけに存在し、Working Treeへ触れず、証明済みの不足テストは提案として報告します。Apply testsはユーザーの明示的な依頼を必要とし、確認済みIntentを表すテストだけを追加します。Version Control操作はどちらのModeでも禁止のままです。

証明済み提案テストを含むSandboxを破棄する前に、テスト専用Patchを出力し、引き渡しManifestを検証します。Apply testsではPatch Hash、本番・テストPrecondition Hash、確認済みContract対応、テストファイルPostimageを検証します。不一致なら引き渡しをStaleとし、強制適用せず再生成して「元コード成功・Mutant失敗」の証明を繰り返します。欠落または破棄済みの引き渡しは、再利用と表現せず再生成します。

適用成功後はContractとReportをApplied状態へ更新し、正準の4ブロックSurfaceを再描画します。先のReview-only Surfaceは処理方法を選ぶためのContextであり、Apply testsの最終結果ではありません。

テストのDispositionは、周辺の会話やGit HistoryではなくSocratic実行開始時のPreflightを基準にします。Preflight時点で存在するテストは、同じ会話の先の依頼で作成された場合でも`existing`、Disposable環境だけのテストは`proposed`、明示許可された今回の実行が主要Workspaceへ書き込んだテストだけが`applied`です。レビュワー向けの文章では、**実行開始時点で既存**、**Disposable環境で提案・証明済み**、**明示依頼後に今回の実行が適用**と明記します。Write Ledgerが実行中の主要Workspace書き込みなしを示し、かつ最終HashがPreflightと一致する場合だけ、**今回のReview-only実行中、Working Treeは不変**と報告します。

## Oracle選択の境界

Oracleを選ぶ前に依存を分類します。プロセス内の依存はクライアントから観測できる最終結果で、管理下のプロセス外状態は実際の最終状態で、管理外のプロセス外依存はアプリケーション境界での送信内容と回数で検証します。出力値を最優先し、次に観測可能な最終状態、最後に境界のコミュニケーションを使います。

実装の詳細——内部の呼び出し順序と回数、中間状態、自由に変更できるアルゴリズム——はOracleにしません。それらへ結び付いたProbeは偽陽性を生むためBehavior Diffとして報告せず、クライアントから観測可能な振る舞いを変えないMutationを強制的に検知させません。

## 根拠の境界

既存テストをオラクル確定へ使えるのは、Diffより前から存在し、Diffで変更されておらず、安定していて、MaieuticのQA Reviewを通過した場合だけです。変更済み、弱い、Flaky、矛盾、実装依存のテストは推論の補助にのみ使います。現在の実装は最も優先度の低い根拠です。

## Mutationの境界

次の順序でMutationを生成します。

1. 確認済みまたは暫定の意図に対する、もっともらしい誤解
2. Contractに関係する副作用の欠落または破壊
3. 状態、認可、時間、Collection、失敗方針の逸脱
4. 特定リスクを実現する従来型の構文Mutation

`equivalent`には根拠を必須とします。Contractにない観測可能な振る舞いは、Maieuticへ戻すMissing Invariant候補です。Mutation数とScoreは診断情報にすぎません。

## BaselineとScopeの境界

Mutation分類には安定したGreen Testが必要です。失敗を1回再実行し、再現する赤Baselineでは停止します。Flaky Testの除外は、安定した部分集合がContractを観測できる場合だけ許可し、縮小したScopeをすべて報告します。

巨大な変更は、観測可能な振る舞いまたはリスクDomainで分割します。予算、観測不能、適用不能、Blockerによって対象外となった全Contract IDを、残存リスクとともに`not_challenged`へ記録します。

Unit Testで観測できないArtifactには、リポジトリが対応する最小の決定的な検証を使い、Unit Test済みではないことを明示します。

## 安全性の境界

Review-only Mutation実行の正規Entry Pointは`run_review.py`のHost Adapter APIだけである。Standalone CLIは自己申告Attestation JSONを受理せず常に`blocked`となる。信頼されたHostがRun ID、Nonce、保護された外部Storage、Repository全体の保護Capabilityを発行する。BaselineとMutation ID付き`execute`をGuarded Mutation証跡とNonce付きAppend-only Chainへ結合し、各Report Mutationに両方の証跡を要求する。

本番コードのMutationは`.socratic-disposable`でMarker付けした使い捨てWorkspaceだけに存在させます。すべてのMutation書き込みを直前に同梱Isolation Gateへ通し、BackupとRestoreを隔離として認めません。主要Workspaceへ反映できるのは許可されたテストまたはドキュメント変更だけです。Reportでは実行中の主要Workspace書き込みと最終Hash一致を分離し、CompileまたはInfrastructure Failureを振る舞い上のKillやCatchとして数えません。

## Version Controlの安全性境界

スキルは、根拠確認とImmutableなBase・Head Snapshot出力のために、Allowlist化した読み取り専用のローカルGitコマンドだけを使用できます。Stage、Commit、Amend、Push、Pull、Fetch、Branchの作成・切替、Checkout、Reset、Stash、Merge、Rebase、Cherry-pick、Tag、Worktree作成、`gh`呼び出し、Pull Request作成、コメント投稿は行いません。禁止操作の許可を求めず、Version Control上の判断をすべてユーザーへ残します。

BaseとHeadは、スキルが管理するBranchではなくSnapshotの識別子です。Host提供Directoryまたは使い捨てFilesystem Snapshotとして展開します。必要なObjectがローカルになくRemote操作が必要なら、その比較をBlockedとします。Mutationの安全確認にはGit復元ではなく、対象範囲のFilesystem ManifestとContent Hashを使います。
