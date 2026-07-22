[English](walkthrough.md) | 日本語

# Walkthrough: AIが整理したテストを`$elenchus`で評価する

`$elenchus`単独実行のセッション実況です。Scope質問から、Cohort比較、Standaloneの評価結果までを示します。

## 1. 状態

AIが価格計算のテストを「整理」したPRがあります。Bulk割引のテストを1つ追加し、Volume境界のAssertionを「何かしら割引されている」に弱め、負の数量のテストを「冗長」として削除しました。SuiteはGreenのままです。

## 2. 実行

```text
> $elenchus 追加された単体テストが有効か確認して
```

## 3. 質問(Scope選択)

Mutant生成の前に、評価範囲を1問だけ聞かれます。検出したファイル数と概算コストが選択肢に添えられます。

```text
┌ 質問 1/1 ── 評価Scope ────────────────────────────────────┐
│ どの範囲を評価しますか?                                    │
│                                                            │
│ ▸ 1. 今回の変更: 既存+変更テスト (推奨)                    │
│      pricing.py周辺の既存保護と、テスト変更の増減を評価    │
│      (本番1ファイル / テスト2ファイル / Mutation 4件想定)  │
│   2. 変更テストのみ                                        │
│      テスト差分だけを高速に評価。既存Suiteの監査はしない   │
│   3. より広い対象                                          │
│      Moduleやリポジトリ全体を指定。実行時間が増えます      │
└────────────────────────────────────────────────────────────┘
あなた: 1. 今回の変更
```

## 4. ターミナル(比較フェーズ)

```text
Elenchus: Existing Cohort(変更前テスト)とChanged Cohort(変更後テスト)を
  Disposable Snapshotとして構築しました。

  リスクをAssertionの中身より先に導出 (Holdout 1件を含む4件)。
  同じMutantを両Cohortの新しいCopyへ実行します...
```

## 5. 結果(Standaloneの評価Surface)

```text
Assessment Scope:
  今回の変更 / pricing.py / tests_existing.py + tests_changed.py / Mutation 4件

Existing Protection:
  ✓ Volume割引の欠落は、変更前から検知できていました
    (今回のテスト変更はこのインシデントには中立)

Changed Test Contribution:
  + 増分保護: 新しいBulk層テストが「100個で20%にならない」を検知
    — 以前はどのテストも守っていませんでした
  - 保護の退行: 境界Assertionの弱体化により、「割引開始が1個ずれる」を
    検知できなくなりました。変更前のSuiteは検知できていました

Still at Risk:
  △ 負の数量の受け入れは、変更前後どちらのSuiteも検知できません
  △ 「負の数量を拒否する」が仕様かどうかは未確定です
    -> 仕様オーナーへの確認事項として記録しました (UNR-001)

Test Quality Concerns:
  ! test_volume_orders_get_some_discount は「1200未満」という
    弱いAssertionです。正確な期待値に戻すことを推奨します

今回のReview-only実行中、Working Treeは不変です。
評価のみを行い、テストは作成していません。
```

マージ可否やスコアは表示されません。GreenなSuiteの裏で「保護が1つ増え、1つ壊れ、1つは最初から無い」ことが、そのまま提示されます。

## 6. 後処理

```text
生存したGapを固めますか? (確定した仕様が必要です)
あなた: いまはしない

実行時の成果物: 保存しない(既定) / ローカルに保存 / Markdownとして出力
あなた: Markdownとして出力
  -> 評価ReportがそのままChatへ展開されます (チームへ共有できます)
```

## この題材を自分で動かす

```bash
python3 -m demo.test_assessment.run_demo
```

同じ4 Mutant×2 Cohortの比較行列と4つの分類を10秒で再現します。
