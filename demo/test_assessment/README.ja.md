[English](README.md) | 日本語

# Test Assessmentデモ

AIが価格計算のテストを「整理」しました。本当に良いテストを1つ追加し、Assertionを1つ弱め、1つを冗長として削除。どちらのSuiteもGreenです。Cohort比較が、保護に実際に何が起きたかを明らかにします。実際のセッション体験は、先に[Walkthrough](walkthrough.ja.md)を読んでください。

## シナリオ

[pricing.py](pricing.py)は、10個から10%のVolume割引、100個から20%のBulk割引を適用し、負の数量を拒否します。[既存テスト](tests_existing.py)はVolume境界を正確に固定しています。[変更後テスト](tests_changed.py)はAIの編集後のSuiteです。

事前作成した4つのMutant——それぞれが起こりそうなインシデント——を、両Cohortの新しいCopyへ実行します。

| Mutant | インシデント | Existing | Changed | 分類 |
|---|---|---|---|---|
| MUT-001 | 割引開始が1個ずれる | killed | survived | protection-regression |
| MUT-002 | Volume割引の欠落 | killed | killed | existing-protection |
| MUT-003 | 負の数量を受け入れる | survived | survived | unprotected |
| MUT-004 | Bulk層が10%へ後退 | survived | killed | incremental-protection |

1回の比較で4つの評価が同時に得られます。新しいBulk層テストは本物の増分保護、弱められた境界AssertionはGreenの実行からは見えない保護の退行、Volume割引の欠落は既存で保護済み、負の数量はどちらのSuiteでも保護されていません。同梱の[intent-contract.json](intent-contract.json)と[expected-elenchus-report.json](expected-elenchus-report.json)は、同じ実行をAssessment ModeのFixtureとして記録し、未保護のギャップを未解決の判断として仕様オーナーへ回します。

## 実行方法

リポジトリRootから実行します。

```bash
python3 -m demo.test_assessment.run_demo
```

成功すると両CohortのBaselineを確認し、比較行列を表示して、Status `0`で終了します。

## 安全上の注意

CohortとMutantは別モジュールのため、デモが`pricing.py`を編集することはありません。これは決定的な教材Fixtureであり、実際の評価はElenchus安全Contractに従ってDisposable Snapshot内でCohortを構築します。
