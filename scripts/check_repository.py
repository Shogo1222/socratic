#!/usr/bin/env python3
import json
import re
import stat
import sys
from pathlib import Path

from audit_distribution import EXPECTED_FILES, EXPECTED_PLUGIN_FILES


ROOT = Path(__file__).resolve().parent.parent
JAPANESE = re.compile(r"[ぁ-んァ-ヶ一-龠]")
SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")
EXPECTED_DISTRIBUTION_FILE_COUNT = len(EXPECTED_FILES)
EXPECTED_PLUGIN_FILE_COUNT = len(EXPECTED_PLUGIN_FILES)
DISTRIBUTION_COUNT_DOCUMENTS = (
    "docs/security-model.md",
    "docs/ja/security-model.md",
    "docs/enterprise-installation.md",
    "docs/ja/enterprise-installation.md",
)

SCHEMA_MIRRORS = {
    "schemas/intent-contract.schema.json": (
        "skills/maieutic/references/intent-contract.schema.json",
        "skills/elenchus/references/intent-contract.schema.json",
    ),
    "schemas/mutation-result.schema.json": (
        "skills/elenchus/references/mutation-result.schema.json",
    ),
    "schemas/mutation-report.schema.json": (
        "skills/elenchus/references/mutation-report.schema.json",
    ),
    "schemas/test-handoff.schema.json": (
        "skills/elenchus/references/test-handoff.schema.json",
    ),
    "schemas/canonical-review.schema.json": (
        "skills/socratic/references/canonical-review.schema.json",
    ),
    "schemas/run-manifest.schema.json": (
        "skills/socratic/references/run-manifest.schema.json",
    ),
}

TRANSLATION_PAIRS = {
    "README.md": "README.ja.md",
    "CONTRIBUTING.md": "CONTRIBUTING.ja.md",
    "CODE_OF_CONDUCT.md": "CODE_OF_CONDUCT.ja.md",
    "SECURITY.md": "SECURITY.ja.md",
    "docs/protocol.md": "docs/ja/protocol.md",
    "docs/security-model.md": "docs/ja/security-model.md",
    "docs/enterprise-installation.md": "docs/ja/enterprise-installation.md",
    "skills/socratic/SKILL.md": "docs/ja/skills/socratic.md",
    "skills/maieutic/SKILL.md": "docs/ja/skills/maieutic.md",
    "skills/maieutic/references/intent-contract.md": "docs/ja/skills/maieutic-intent-contract.md",
    "skills/maieutic/references/qa-techniques.md": "docs/ja/skills/maieutic-qa-techniques.md",
    "skills/elenchus/SKILL.md": "docs/ja/skills/elenchus.md",
    "skills/elenchus/references/mutation-design.md": "docs/ja/skills/elenchus-mutation-design.md",
    "skills/elenchus/references/safety.md": "docs/ja/skills/elenchus-safety.md",
    "skills/elenchus/references/test-handoff.md": "docs/ja/skills/elenchus-test-handoff.md",
    "demo/README.md": "demo/README.ja.md",
    "demo/subscription_renewal/README.md": "demo/subscription_renewal/README.ja.md",
    "demo/subscription_renewal/walkthrough.md": "demo/subscription_renewal/walkthrough.ja.md",
    "demo/refactor_guard/walkthrough.md": "demo/refactor_guard/walkthrough.ja.md",
    "demo/test_assessment/walkthrough.md": "demo/test_assessment/walkthrough.ja.md",
    "demo/subscription_renewal/maieutic-session.md": "demo/subscription_renewal/maieutic-session.ja.md",
    "demo/refactor_guard/README.md": "demo/refactor_guard/README.ja.md",
    "demo/test_assessment/README.md": "demo/test_assessment/README.ja.md",
}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_schema_mirrors() -> None:
    for source, mirrors in SCHEMA_MIRRORS.items():
        source_bytes = (ROOT / source).read_bytes()
        json.loads(source_bytes)
        for mirror in mirrors:
            if (ROOT / mirror).read_bytes() != source_bytes:
                fail(f"schema mirror is stale: {mirror} != {source}")


def check_release_version() -> None:
    raw = (ROOT / "VERSION").read_text(encoding="utf-8")
    version = raw.strip()
    if raw != f"{version}\n" or not SEMVER.fullmatch(version):
        fail("VERSION must contain exactly one semantic version followed by a newline")


def check_distribution_documentation() -> None:
    expected_marker = (
        f"<!-- socratic-distribution-file-count: {EXPECTED_DISTRIBUTION_FILE_COUNT} -->"
    )
    marker_pattern = re.compile(r"<!-- socratic-distribution-file-count: ([0-9]+) -->")
    expected_plugin_marker = f"<!-- socratic-plugin-file-count: {EXPECTED_PLUGIN_FILE_COUNT} -->"
    plugin_marker_pattern = re.compile(r"<!-- socratic-plugin-file-count: ([0-9]+) -->")
    for relative in DISTRIBUTION_COUNT_DOCUMENTS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        markers = marker_pattern.findall(text)
        if markers != [str(EXPECTED_DISTRIBUTION_FILE_COUNT)] or text.count(expected_marker) != 1:
            fail(
                f"documented distribution file count is stale: {relative} "
                f"(expected {EXPECTED_DISTRIBUTION_FILE_COUNT})"
            )
        plugin_markers = plugin_marker_pattern.findall(text)
        if plugin_markers != [str(EXPECTED_PLUGIN_FILE_COUNT)] or text.count(expected_plugin_marker) != 1:
            fail(
                f"documented Plugin file count is stale: {relative} "
                f"(expected {EXPECTED_PLUGIN_FILE_COUNT})"
            )


def check_plugin_gate() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    if manifest.get("name") != "socratic":
        fail("plugin name must be socratic")
    if manifest.get("version") != version:
        fail("plugin version must match VERSION")
    if manifest.get("skills") != "./skills/":
        fail("plugin must bundle the repository skills directory")
    if manifest.get("hooks") != "./hooks/codex-hooks.json":
        fail("plugin must declare the pre-agent hooks manifest")

    hooks_path = ROOT / "hooks/codex-hooks.json"
    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
    try:
        groups = hooks["hooks"]["UserPromptSubmit"]
        handlers = groups[0]["hooks"]
        handler = handlers[0]
    except (KeyError, IndexError, TypeError):
        fail("plugin must define exactly one UserPromptSubmit gate")
    if len(groups) != 1 or len(handlers) != 1:
        fail("plugin must define exactly one UserPromptSubmit gate")
    if handler.get("type") != "command" or handler.get("command") != (
        'python3 "$PLUGIN_ROOT/hooks/socratic_preflight.py"'
    ):
        fail("plugin UserPromptSubmit gate must invoke the bundled preflight hook")

    hook_script = ROOT / "hooks/socratic_preflight.py"
    if not hook_script.is_file():
        fail("plugin preflight hook is missing")
    if stat.S_IMODE(hook_script.stat().st_mode) & 0o111:
        fail("plugin preflight hook must not have a POSIX execute bit")
    hook_script.read_text(encoding="utf-8")

    claude_manifest = json.loads(
        (ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8")
    )
    if claude_manifest.get("name") != "socratic" or claude_manifest.get("version") != version:
        fail("Claude Plugin identity and version must match VERSION")
    claude_hooks = json.loads((ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))
    claude_handler = claude_hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]
    if "${CLAUDE_PLUGIN_ROOT}/hooks/claude_preflight.py" not in claude_handler.get("command", ""):
        fail("Claude Plugin must invoke its Claude-format preflight hook")

    metadata = (ROOT / "skills/socratic/agents/openai.yaml").read_text(encoding="utf-8")
    if "allow_implicit_invocation: false" not in metadata:
        fail("Socratic must disable implicit invocation so the Host hook can identify every run")


def check_schema_references() -> None:
    for path in ROOT.rglob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        pending = [schema]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                reference = value.get("$ref")
                if isinstance(reference, str) and not reference.startswith(("#", "http://", "https://")):
                    target = reference.split("#", 1)[0]
                    if target and not (path.parent / target).is_file():
                        fail(f"broken schema reference: {path.relative_to(ROOT)} -> {reference}")
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)


def check_translations() -> None:
    for english, japanese in TRANSLATION_PAIRS.items():
        source = ROOT / english
        if not source.is_file():
            fail(f"missing English source: {english}")
        translated = ROOT / japanese
        if not translated.is_file():
            fail(f"missing Japanese translation: {japanese}")
        text = translated.read_text(encoding="utf-8")
        if not JAPANESE.search(text):
            fail(f"Japanese translation has no Japanese text: {japanese}")
        if english.startswith("skills/"):
            source_headings = len(re.findall(r"^#{1,6} ", source.read_text(encoding="utf-8"), re.MULTILINE))
            translated_headings = len(re.findall(r"^#{1,6} ", text, re.MULTILINE))
            if source_headings != translated_headings:
                fail(f"translation heading count differs: {japanese} != {english}")


def check_markdown_links() -> None:
    link_pattern = re.compile(r"\]\(([^)]+)\)")
    for path in ROOT.rglob("*.md"):
        for link in link_pattern.findall(path.read_text(encoding="utf-8")):
            if link.startswith(("http://", "https://", "#")):
                continue
            relative = link.split("#", 1)[0]
            if relative and not (path.parent / relative).resolve().exists():
                fail(f"broken Markdown link: {path.relative_to(ROOT)} -> {link}")


def check_runtime_skills_are_english_only() -> None:
    for path in (ROOT / "skills").rglob("*"):
        if path.suffix not in {".md", ".yaml", ".json"}:
            continue
        text = path.read_text(encoding="utf-8")
        if path.name == "SKILL.md" and text.startswith("---\n"):
            text = text.split("---\n", 2)[-1]
        if JAPANESE.search(text):
            fail(f"runtime skill file contains Japanese text: {path.relative_to(ROOT)}")


def check_skill_structure() -> None:
    expected = {"socratic", "maieutic", "elenchus"}
    actual = {path.name for path in (ROOT / "skills").iterdir() if path.is_dir()}
    if actual != expected:
        fail(f"skill directories differ: expected {sorted(expected)}, found {sorted(actual)}")

    for skill_name in expected:
        path = ROOT / "skills" / skill_name / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        if not re.search(rf"^name: {re.escape(skill_name)}$", text, re.MULTILINE):
            fail(f"skill name does not match directory: {skill_name}")

    orchestrator = (ROOT / "skills/socratic/SKILL.md").read_text(encoding="utf-8")
    for dependency in ("$maieutic", "$elenchus"):
        if dependency not in orchestrator:
            fail(f"Socratic orchestrator does not reference {dependency}")


def main() -> int:
    check_release_version()
    check_distribution_documentation()
    check_plugin_gate()
    check_schema_mirrors()
    check_schema_references()
    check_translations()
    check_markdown_links()
    check_runtime_skills_are_english_only()
    check_skill_structure()
    print("Repository consistency checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
