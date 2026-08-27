#!/usr/bin/env python3
"""Repository validator for the Fabric Agent Adapter distribution."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Tuple


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/fabric-agent-adapter"
SKILL_NAMES = ("adapting-projects-to-fabric", "creating-fabric-agents")
SKILLS = {name: PLUGIN / "skills" / name for name in SKILL_NAMES}
VERSION = "0.3.0"
EXPECTED_FILES = tuple(
    [
        ROOT / ".claude-plugin/marketplace.json",
        PLUGIN / ".claude-plugin/plugin.json",
        ROOT / "README.md",
        ROOT / "CHANGELOG.md",
        ROOT / "LICENSE",
        ROOT / "CONTRIBUTING.md",
        ROOT / "SECURITY.md",
        ROOT / "SKILL-CARD.md",
        ROOT / "package.json",
        ROOT / "install.sh",
        ROOT / "bin/fabric-agent-adapter.js",
        ROOT / ".github/workflows/release.yml",
    ]
    + [SKILLS[name] / "SKILL.md" for name in SKILL_NAMES]
    + [ROOT / "test/evals" / name / "triggers.json" for name in SKILL_NAMES]
    + [ROOT / "test/evals" / name / "scenarios.json" for name in SKILL_NAMES]
)
STDLIB_IMPORTS = {
    "__future__", "argparse", "ast", "datetime", "hashlib", "importlib", "json",
    "os", "pathlib", "re", "subprocess", "sys", "tempfile", "typing", "unittest",
    "urllib",
}


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    try:
        raw, body = text[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise ValueError("SKILL.md frontmatter is not closed") from exc
    data: Dict[str, Any] = {}
    nested: Dict[str, str] = {}
    nested_key = None
    for line in raw.splitlines():
        if line.startswith("  ") and nested_key:
            key, sep, value = line.strip().partition(":")
            if not sep:
                raise ValueError("invalid nested frontmatter line: %s" % line)
            nested[key] = value.strip().strip('"')
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ValueError("invalid frontmatter line: %s" % line)
        key = key.strip()
        value = value.strip()
        if value:
            data[key] = value.strip('"')
            nested_key = None
        else:
            nested = {}
            data[key] = nested
            nested_key = key
    return data, body


def validate_metadata(data: Dict[str, Any], expected_name: str) -> List[str]:
    errors: List[str] = []
    name = data.get("name", "")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        errors.append("skill name must use lowercase kebab-case")
    if name != expected_name:
        errors.append("skill name must match its directory")
    if len(name) > 64:
        errors.append("skill name exceeds 64 characters")
    description = data.get("description", "")
    if not description.startswith("Use when "):
        errors.append("description must start with 'Use when '")
    if "NOT for" not in description:
        errors.append("description must include a NOT-for boundary")
    if len(description) > 1024:
        errors.append("description exceeds 1024 characters")
    if data.get("license") != "MIT":
        errors.append("skill license must be MIT")
    if len(data.get("compatibility", "")) > 500:
        errors.append("compatibility exceeds 500 characters")
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        errors.append("metadata must be a string-valued mapping")
    else:
        if any(not isinstance(value, str) for value in metadata.values()):
            errors.append("all metadata values must be strings")
        if metadata.get("version") != VERSION:
            errors.append("skill metadata version is out of sync")
    return errors


def local_markdown_links(path: Path) -> List[str]:
    text = path.read_text(encoding="utf-8")
    return [target for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
            if not re.match(r"^[a-z]+://", target) and not target.startswith("#")]


def validate_links(errors: List[str]) -> None:
    for path in ROOT.rglob("*.md"):
        if ".git" in path.parts:
            continue
        for target in local_markdown_links(path):
            clean = target.split("#", 1)[0]
            if clean and not (path.parent / clean).resolve().exists():
                errors.append("broken markdown link in %s: %s" % (path.relative_to(ROOT), target))


def validate_python_imports(path: Path, errors: List[str]) -> None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        errors.append("python syntax error in %s: %s" % (path.relative_to(ROOT), exc))
        return
    for node in ast.walk(tree):
        names: List[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            if name.split(".", 1)[0] not in STDLIB_IMPORTS:
                errors.append("non-stdlib import in %s: %s" % (path.relative_to(ROOT), name))


def validate_skill(name: str, errors: List[str]) -> None:
    skill_dir = SKILLS[name]
    skill_file = skill_dir / "SKILL.md"
    skill_text = skill_file.read_text(encoding="utf-8")
    try:
        frontmatter, body = parse_frontmatter(skill_text)
        errors.extend("%s: %s" % (name, e) for e in validate_metadata(frontmatter, name))
    except ValueError as exc:
        errors.append("%s: %s" % (name, exc))
        body = ""

    if len(skill_text.splitlines()) >= 500:
        errors.append("%s: SKILL.md must stay below 500 lines" % name)
    if len(skill_text.split()) >= 4750:
        errors.append("%s: SKILL.md exceeds the 5%% token/word headroom" % name)
    if re.search(r"[А-Яа-яЁё]", body):
        errors.append("%s: Cyrillic prose is allowed in trigger metadata, not the skill body" % name)

    linked_refs = set(re.findall(r"\]\(references/([^)]+)\)", skill_text))
    actual_refs = {path.name for path in (skill_dir / "references").glob("*.md")}
    if linked_refs != actual_refs:
        errors.append("%s: every reference must be directly linked exactly once from SKILL.md" % name)
    for ref in (skill_dir / "references").glob("*.md"):
        text = ref.read_text(encoding="utf-8")
        if len(text.splitlines()) > 100 and "## Contents" not in text:
            errors.append("%s: reference over 100 lines needs Contents: %s" % (name, ref.name))

    triggers = json.loads((ROOT / "test/evals" / name / "triggers.json").read_text(encoding="utf-8"))
    if triggers.get("skill") != name:
        errors.append("%s: triggers.json must name its skill" % name)
    queries = triggers.get("queries", [])
    positives = sum(item.get("shouldTrigger") is True for item in queries)
    negatives = sum(item.get("shouldTrigger") is False for item in queries)
    if len(queries) < 18 or positives < 8 or negatives < 8:
        errors.append("%s: trigger evals need about twenty balanced positive/negative queries" % name)
    scenarios = json.loads((ROOT / "test/evals" / name / "scenarios.json").read_text(encoding="utf-8"))
    if scenarios.get("skill") != name:
        errors.append("%s: scenarios.json must name its skill" % name)
    if len(scenarios.get("scenarios", [])) < 3:
        errors.append("%s: at least three behaviour scenarios are required" % name)


def validate_repo() -> List[str]:
    errors: List[str] = []
    for path in EXPECTED_FILES:
        if not path.is_file():
            errors.append("missing required file: %s" % path.relative_to(ROOT))
    if errors:
        return errors

    for name in SKILL_NAMES:
        validate_skill(name, errors)

    skill_files = sorted(path for path in ROOT.rglob("SKILL.md") if ".git" not in path.parts)
    if skill_files != sorted(SKILLS[name] / "SKILL.md" for name in SKILL_NAMES):
        errors.append("distribution must expose exactly the canonical SKILL.md files")

    marketplace = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    plugin = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    entry = marketplace["plugins"][0]
    for label, value in (("marketplace", entry), ("plugin", plugin)):
        if value.get("name") != "fabric-agent-adapter":
            errors.append("%s name is out of sync" % label)
        if value.get("version") != VERSION:
            errors.append("%s version is out of sync" % label)
        if value.get("displayName") != "Fabric Agent Adapter":
            errors.append("%s displayName is missing" % label)
        if value.get("license") != "MIT":
            errors.append("%s license is out of sync" % label)
    if not marketplace.get("$schema") or not plugin.get("$schema"):
        errors.append("both plugin manifests need $schema")
    if entry.get("source") != "./plugins/fabric-agent-adapter":
        errors.append("marketplace source is incorrect")

    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    if pkg.get("name") != "@passioncode-ai/fabric-agent-adapter":
        errors.append("package.json name must be @passioncode-ai/fabric-agent-adapter")
    if pkg.get("version") != VERSION:
        errors.append("package.json version is out of sync")
    if pkg.get("publishConfig", {}).get("access") != "public":
        errors.append("scoped package needs publishConfig.access public")
    for entry_name in ("bin", "plugins"):
        if entry_name not in pkg.get("files", []):
            errors.append("package.json files whitelist must ship %s" % entry_name)

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^## ([0-9]+\.[0-9]+\.[0-9]+)", changelog, re.MULTILINE)
    if not match or match.group(1) != VERSION:
        errors.append("top changelog version is out of sync")

    for path in ROOT.rglob("*.json"):
        if ".git" not in path.parts:
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                errors.append("invalid JSON in %s: %s" % (path.relative_to(ROOT), exc))
    for path in ROOT.rglob("*.py"):
        if ".git" not in path.parts:
            validate_python_imports(path, errors)
    validate_links(errors)

    workflow = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")
    for command in (
        "python3 test/validate.py",
        "claude plugin validate ./plugins/fabric-agent-adapter --strict",
        "claude plugin validate . --strict",
    ):
        if command not in workflow:
            errors.append("CI is missing: %s" % command)
    return errors


def validator_self_test() -> List[str]:
    legal = {
        "name": "adapting-projects-to-fabric",
        "description": "Use when adapting a provider to Fabric. NOT for general design.",
        "license": "MIT",
        "compatibility": "Python 3.9+",
        "metadata": {"version": VERSION},
    }
    if validate_metadata(legal, "adapting-projects-to-fabric"):
        return ["validator self-test rejected legal metadata"]
    illegal = dict(legal)
    illegal["name"] = "Bad_Name"
    illegal["description"] = "A vague helper."
    detected = validate_metadata(illegal, "adapting-projects-to-fabric")
    if len(detected) < 3:
        return ["validator self-test did not detect bad name/description/boundary"]
    return []


def main() -> int:
    errors = validator_self_test() + validate_repo()
    if errors:
        for error in errors:
            print("ERROR: %s" % error)
        return 1
    print("OK: Fabric Agent Adapter distribution is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
