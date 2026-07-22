[English](README.md) | 日本語

# デモ

「`$socratic`を実行すると、ターミナルに何が出て、何を聞かれ、どう答えると、何が返ってくるのか」——それを見せるのがこのディレクトリです。

## まずWalkthroughを読む(各2分)

3つのよくある場面について、セッションの実況をそのまま収録しています。開始状態→実行→調査の出力→構造化質問のUIとあなたの回答→結果→後処理の質問、の順です。

1. [機能追加のPRをレビューする](subscription_renewal/walkthrough.ja.md) — 仕様質問2つに答えると、3つの重大インシデントを検知するテストが証明付きで提案され、「適用する?」と聞かれる
2. [「ただのリファクタリング」をレビューする](refactor_guard/walkthrough.ja.md) — 静かに変わった期限境界が事実として提示され、「意図した変更?」に答えると貼るだけのコメント候補が出る
3. [AIが整理したテストを評価する](test_assessment/walkthrough.ja.md) — GreenなSuiteの裏で「保護が1つ増え、1つ壊れ、1つは最初から無い」ことが示される

## 次にエンジンを動かす(各10秒)

各Walkthroughの土台になっている検証エンジンを、決定的な実行可能デモとして再現できます。Python標準ライブラリのみで動作し、本番モジュールを編集せず、期待どおりの結果でStatus `0`終了します。

```bash
python3 -m demo.subscription_renewal.run_demo
python3 -m demo.refactor_guard.run_demo
python3 -m demo.test_assessment.run_demo
```

## Fixtureについて

各デモ同梱の`intent-contract.json`と`expected-elenchus-report.json`はSchema適合Fixtureを兼ねており、3つでHarden・Catch・Assessmentの全Report Modeを網羅します。CIで`schemas/`に対して検証されます。

```bash
python3 scripts/validate_fixtures.py   # 要: jsonschema, referencing
```

これらのデモは、事前作成したMutantとCohortを使う教材Fixtureです。実際の実行では、Elenchus安全Contractの下でDisposable Snapshot内にMutationとCohortを生成します。ここにあるものは将来の本番Mutation Runnerではありません。
