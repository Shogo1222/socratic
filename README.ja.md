[English](README.md) | 日本語

# Socratic

AI支援ソフトウェア開発のための、問答と反駁によるHuman-confirmed Intent Testingです。

Socraticは、コードレビューの対象を、人間の判断が必要な振る舞いと設計上の決定に絞るEnd-to-end Workflowです。Maieuticが意図を引き出してテストを補完し、ElenchusがRisk-directed Intent Mutationでそのテストを反証にさらします。

> Maieuticは未確定の意図を可視化します。Elenchusは、その意図を守ると主張するテストの反証を試みます。Socraticは両者を1つの監査可能なCycleへつなぎます。

## なぜ必要か

AIが生成したコードをすべて人間が読む方法はスケールしません。一方、正しさをAIへ完全に委任することもできません。実装自身を仕様の根拠にはできず、成功するテストにも弱いオラクルや誤ったオラクルが含まれ得るためです。

このプロジェクトは、人間との接点を次の範囲へ絞ります。

1. 変更から意図とリスクを推測する
2. 重要な期待値を変える判断だけを確定する
3. 判断を単体テストとして固定する
4. 確認済みの意図を、もっともらしいバグへ変異させる
5. テストがそのバグを検知できることを証明する

人間は、曖昧な仕様と重要な設計判断に責任を持ちます。エージェントは、リポジトリ調査、QAテスト設計、テスト実装、敵対的検証を担当します。

## アーキテクチャ

```text
コード変更
    |
    v
Socratic
  |
  +-- Maieutic
  |     - 分かっていない点を可視化
  |     - 根拠から観測可能な意図を推測
  |     - 回答しやすい振る舞いの質問を提示
  |     - Intent Contractを確定
  |     - 単体テストをレビュー・補完
  |
  +-- Elenchus
        - 確認済みの意図を変異
        - 高リスクな変異を隔離環境で実現
        - 対象を絞った単体テストを実行
        - 曖昧さをMaieuticへ戻す
        - 不足テストを追加して再検証
    |
    v
人間のレビューを未確定の意図と設計リスクへ集中
```

MaieuticとElenchusをつなぐのは、既定で`.socratic/intent-contract.json`へ保存する[Intent Contract](docs/ja/protocol.md)です。判断、不変条件、副作用、根拠、テストによる保護状況を、小さく追跡可能な記録として保持します。Socraticは第三の仕様源にはならず、このCycleを統合します。

名前は次の関係を表します。

- **Socratic**: 無知を自覚し、問い、反駁によって主張を検証する全体の方法
- **Maieutic**: 実装からは確定できない意図を人間から引き出すStage
- **Elenchus**: テストがその意図を実際に守るか反証するStage

## 2つの検証モード

### Catch Mode

親リビジョンでは成功し、リスクを表すMutantでは失敗するテストを生成し、提案された変更へ実行します。親では成功し変更後では失敗する結果は、人間がその振る舞いの変化を意図したものかどうか確認するまでWeak Catchとして扱います。

### Harden Mode

意図の確定後、変更後コードに対して、もっともらしい誤解を表すIntent Mutationを生成します。生存したMutantは、シナリオ不足、Assertion不足、境界値不足、観測されていない副作用、曖昧な仕様、または実装依存テストを示します。

## リポジトリ構成

```text
skills/
  socratic/   End-to-end Orchestration
  maieutic/   意図の引き出しとQA観点による単体テスト
  elenchus/   Intent Mutationによる検証
docs/
  protocol.md 共通概念とライフサイクル
schemas/
  intent-contract.schema.json
  mutation-result.schema.json
  mutation-report.schema.json
```

`skills/`配下の各ディレクトリは、CodexとClaude Codeで利用できるAgent Skillです。統合された`$socratic` Workflowには3つすべてをインストールします。一方のStageだけが必要な場合は`$maieutic`または`$elenchus`を独立して実行できます。

## インストール

[Shogo1222/socratic](https://github.com/Shogo1222/socratic)から3スキルすべてをインストールします。

GitHub CLIのAgent Skills機能を使う場合は次のとおりです。

```bash
gh skill install Shogo1222/socratic --all
```

または、オープンなAgent Skills CLIを使います。

```bash
npx skills add Shogo1222/socratic --skill '*'
```

その後、コード変更に対して`$socratic`を実行します。一方のStageだけが必要な場合は`$maieutic`または`$elenchus`を直接実行します。

## 設計原則

- 実装を仕様とみなさない
- 重要なテストオラクルを変える質問だけを行う
- テストコードを人間に読ませる前に、観測可能な変更前後の振る舞いを提示する
- 重要なテストとMutationを、確認済みContract項目へ関連付ける
- Mutation Scoreではなく、重大インシデントを表す少数のMutationを優先する
- 本番コードへMutationを残さない
- 意味的なIntent Mutationと従来の構文Mutationを相互補完として扱う。評価対象のTaskでは、どちらも他方を一貫してSubsumptionしなかった

## 研究上の基盤

本プロジェクトは、相互補完的な2つの研究分野を代表する3本の論文から着想を得ています。

- [Harden and Catch for Just-in-Time Assured LLM-Based Software Testing](https://arxiv.org/abs/2504.16472)は、Hardening Test、Catching Test、およびCatching JiTTest Challengeを正式に定義した基礎論文です。
- [Just-in-Time Catching Test Generation at Meta](https://arxiv.org/abs/2601.22832)は、この枠組みを産業規模で適用し、Diff-awareおよびIntent-awareなCatching Testの結果と、人間が振る舞いの変化を意図したか判断するための低負荷な確認方法を報告しています。
- [Intent-Based Mutation Testing: From Naturally Written Programming Intents to Mutants](https://arxiv.org/abs/2607.05149)は、自然言語で表現された意図のVariantから実装を生成し、29プログラムを対象とした評価で、構文ベースMutationとは一部重ならない振る舞いとSubsumption関係を確認しています。

Socraticはこれらの考え方を接続します。明示的なHuman-confirmed Intent Contract、Maieuticによる意図確定、Contract IDによるテストとMutationの対応付け、重大インシデント順のMutation選定、未挑戦リスクの明示、ElenchusによるHardening Loopは、論文の主張ではなくSocratic独自の設計です。本プロジェクトは独立したオープン実装であり、論文の著者または所属機関による実装や推奨ではありません。

## 現在の状態

現在はスキル設計の初期段階です。プロトコルとエージェントワークフローは利用できますが、決定的な言語別アダプターと、隔離されたMutation Runnerは今後の実装対象です。

初期のコントリビューション方針は[CONTRIBUTING.ja.md](CONTRIBUTING.ja.md)を参照してください。

## ライセンス

Socraticは[MIT License](LICENSE)で提供します。

ソース: [github.com/Shogo1222/socratic](https://github.com/Shogo1222/socratic)

## 日本語資料

[日本語ドキュメント一覧](docs/ja/README.md)を参照してください。
