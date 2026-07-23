# 企業向け導入ガイド

[English](../enterprise-installation.md)

このGuideは、組織管理のPCでSocraticを利用するための承認Checklistです。勤務先のSecurity、Legal、Procurement、AI利用Policyに代わるものではありません。

## Install前の確認

組織の責任者と次の項目をすべて確認してください。

- Host AgentとGitHub CLIが承認済みである
- Model Providerとの契約、Data Retention、学習利用、処理Regionの設定が対象RepositoryのSource Codeを許容する
- Pilot Repositoryに本番Credentialや規制対象Dataが含まれない
- Filesystem AccessとNetwork Egressが最小権限である
- Test Commandを本番Accessや課金を伴う副作用なしにDisposable環境で実行できる
- [セキュリティモデル](security-model.md)と[セキュリティポリシー](../../SECURITY.ja.md)をReview済みである

RunnerのRuntime Dependencyは、Global環境ではなく、Host管理のVirtual EnvironmentまたはManaged Python Runtimeへ導入してください。

```bash
python3 -m pip install jsonschema referencing
```

どちらかの依存Packageが利用できない場合、必須RunnerはFail-closedとなりReviewは`blocked`のままです。

## Releaseの検証

Immutableな公開Releaseを使い、Installする正確なTagを固定してください。以下の`v0.2.0`は、承認済みReleaseへ置き換えます。

```bash
gh release verify v0.2.0 --repo Shogo1222/socratic
gh release download v0.2.0 --repo Shogo1222/socratic --pattern SHA256SUMS --pattern distribution-manifest.json
```

Install前にFileと権限をPreviewします。

```bash
GH_TELEMETRY=false gh skill preview Shogo1222/socratic socratic@v0.2.0
GH_TELEMETRY=false gh skill preview Shogo1222/socratic maieutic@v0.2.0
GH_TELEMETRY=false gh skill preview Shogo1222/socratic elenchus@v0.2.0
```

<!-- socratic-distribution-file-count: 21 -->
<!-- socratic-plugin-file-count: 40 -->
Standalone Skill配布物は21個のUTF-8 Text Fileで、そのうち3個はPython Source Helperです。Multi-Host Plugin BundleはClaude Code・Codex・ローカルCursor Desktop統合を含む40個のUTF-8 Text Fileです。HelperにPOSIX Execute Bitはありませんが、Python Interpreterから実行されます。配布Auditの「実行可能」拒否は、具体的にはPOSIXの`0o111` Execute-bit Maskを検査します。配布物にBinaryやSymbolic Linkは含まれません。PreviewをReleaseのManifestとChecksumと比較してください。

Managed Codex導入では、ユーザーが変更できるPlugin Hook Trustへ依存しません。OS管理のAbsolute PathからPre-agent Gateを`requirements.toml`で配布し、`[features].hooks = true`を強制し、`allow_managed_hooks_only = true`を設定してください。対象環境でManaged Host IntegrationとReady-run Capability Pathを検証するまで、v0.3.0 Alphaを完成扱いにしません。

## Project ScopeでのInstall

現在のProjectだけへInstallします。

```bash
GH_TELEMETRY=false gh skill install Shogo1222/socratic \
  --all \
  --agent codex \
  --scope project \
  --pin v0.2.0
```

Project Scopeが制限するのはSkill FileのInstall先です。Host Agentが読める範囲や、Model ProviderへSource Codeが送信されるかどうかは制限しません。それらはHost、OS、Network、組織Accountで制御してください。

## Pilot Checklist

1. 本番Credentialを持たない、機密情報を含まないRepositoryから始めます。
2. 既定のReview-only ModeでSocraticを実行します。
3. Working Treeが変更されず、明示的な保存選択なしに`.socratic/` Artifactが作られないことを確認します。
4. Git Write、Code Host Write、外部Serviceへ接続するTest、Credentialを含むCommandがBlockedになることを確認します。
5. Review This、We Verified、Still at Risk、Copy-ready Commentsの4部構成の結果を確認します。
6. 中断・失敗経路を試し、一時Pathが削除されるか、削除失敗として報告されることを確認します。
7. 承認したTagとChecksumを組織のSoftware Inventoryへ記録します。

Apply testsは、TeamがReview-onlyの挙動を確認し、Test変更を明示依頼した後だけ利用してください。適用されたすべての変更には通常のCode Reviewを継続してください。

## Update

組織利用では移動するBranchを参照しないでください。新しいTagごとにChangelog、Security Impact、Release Manifest、ChecksumをReviewし、承認Versionを変更する前にPreviewとPilot確認を繰り返してください。

Skillを削除する場合は、CommandがInstallしたProject Scopeの3つのSkill Directory `socratic`、`maieutic`、`elenchus`について、解決済みのPathを確認してから、そのDirectoryだけを削除してください。より広いAgent DirectoryやProject Directoryを再帰削除しないでください。
