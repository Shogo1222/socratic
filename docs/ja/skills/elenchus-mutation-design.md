[英語正本](../../../skills/elenchus/references/mutation-design.md)

> この文書は確認用の日本語訳です。実行時の正式な指示は英語正本です。

# Intent駆動Mutation設計

もっともらしい誤ったIntentからMutantを作り、そのIntentを実現する最小で原因特定可能なCode Changeを適用する。

## Mutation Record

Candidate生成から永続化Resultまで同じFieldを使う。

```yaml
id: MUT-001
mode: harden | catch
contract_ids: [INV-001]
source_intent: <Hardenでは確認済みの振る舞い。Catchでは暫定Intent>
changed_intent: <近接した誤解>
represented_risk: <FailureまたはIncident>
severity: critical | high | medium | low
likelihood: high | medium | low
code_change: <最小の実現方法>
code_location: <PathとSymbol>
expected_detection: <観測可能なAssertionまたは禁止副作用>
result: <実行分類>
detecting_tests: [<テスト名>]
equivalence_evidence: <Equivalentの場合は必須>
follow_up: <テスト、判断、またはなし>
```

`changed_intent`をコード構文と独立して説明できないCandidateは採用しない。

## 高価値な意味的Mutation軸

境界、対象集合、状態遷移、Omission、Side Effect、失敗方針、順序、冪等性、Time、Collection、Authorization、数値動作を優先する。

## 従来Operator

`<`／`<=`、Boolean・Null反転、条件否定、Early Return・Exception削除、定数変更、Off-by-oneは、Intent軸とContract IDへ関連付けた後だけ使う。Score目的で任意の呼び出しを削除しない。

## 選択

Severity、現実的な誤解、明確な観測、最小実装範囲を優先する。同じAssertionが同じ理由でKillする冗長Mutantを避け、選ばなかったContract IDを隠さず記録する。

## 妥当性

意図したRiskを実行でき、確認済みまたは暫定Intentと観測可能な差があり、無関係な振る舞いを維持し、可逆・隔離され、Test Oracleへ到達可能であることを求める。

`equivalent`には根拠を必須とする。Contractにない観測可能な振る舞いはMissing Invariant候補であり、Equivalentではない。
