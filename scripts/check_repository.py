#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
JAPANESE = re.compile(r"[ぁ-んァ-ヶ一-龠]")
SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")

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
}

TRANSLATION_PAIRS = {
    "README.md": "README.ja.md",
    "CONTRIBUTING.md": "CONTRIBUTING.ja.md",
    "CODE_OF_CONDUCT.md": "CODE_OF_CONDUCT.ja.md",
    "docs/protocol.md": "docs/ja/protocol.md",
    "skills/socratic/SKILL.md": "docs/ja/skills/socratic.md",
    "skills/maieutic/SKILL.md": "docs/ja/skills/maieutic.md",
    "skills/maieutic/references/intent-contract.md": "docs/ja/skills/maieutic-intent-contract.md",
    "skills/maieutic/references/qa-techniques.md": "docs/ja/skills/maieutic-qa-techniques.md",
    "skills/elenchus/SKILL.md": "docs/ja/skills/elenchus.md",
    "skills/elenchus/references/mutation-design.md": "docs/ja/skills/elenchus-mutation-design.md",
    "skills/elenchus/references/safety.md": "docs/ja/skills/elenchus-safety.md",
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
    check_schema_mirrors()
    check_translations()
    check_markdown_links()
    check_runtime_skills_are_english_only()
    check_skill_structure()
    print("Repository consistency checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
