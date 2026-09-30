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
SKILL_NAMES = ("adapting-projects-to-fabric", "building-fabric-services", "creating-fabric-agents")
SKILLS = {name: PLUGIN / "skills" / name for name in SKILL_NAMES}
VERSION = "0.5.0"
LICENSE_SPDX = "PolyForm-Noncommercial-1.0.0 OR LicenseRef-PolyForm-Internal-Use-1.0.0"
EXPECTED_FILES = tuple(
    [
        ROOT / ".claude-plugin/marketplace.json",
        PLUGIN / ".claude-plugin/plugin.json",
        ROOT / "README.md",
        ROOT / "CHANGELOG.md",
        ROOT / "LICENSE",
        ROOT / "CLA.md",
        ROOT / ".github/pull_request_template.md",
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
    "urllib", "base64", "errno", "fcntl", "hmac", "html", "http", "plistlib", "secrets", "socketserver",
    "shutil", "signal", "socket", "stat", "threading", "time",
}


# Front matter is read the way the STRICTEST consumer reads it, not the way Claude Code
# does. Claude Code tolerates an unquoted `description:` holding `: `; a YAML 1.2 reader
# answers "mapping values are not allowed here" and the agent drops the skill. Standard
# library only (the repository rule), so this is a deliberately small YAML subset: a flat
# mapping whose values are plain, quoted or block scalars, plus one level of nested
# mapping. Anything outside that subset is an error, never a guess.
FRONTMATTER_KEY = re.compile(r"[A-Za-z0-9_-]+")
BLOCK_HEADER = re.compile(r"([|>])([+-]?)")
# Characters that may not open a plain scalar at all (YAML 1.2, c-indicator).
PLAIN_FORBIDDEN_FIRST = set("[]{},#&*!|>'\"%@`")
# Characters that may open a plain scalar only when a non-space follows.
PLAIN_NEEDS_NONSPACE_NEXT = set("-?:")
DOUBLE_QUOTE_ESCAPES = {
    "0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v",
    "f": "\f", "r": "\r", "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\",
    "N": "\x85", "_": "\xa0", "L": " ", "P": " ",
}
HEX_ESCAPES = {"x": 2, "u": 4, "U": 8}


def _where(lineno: int, column: int) -> str:
    return "line %d, column %d" % (lineno, column)


def check_plain_scalar(value: str, lineno: int, column: int) -> str:
    """Return a plain scalar unchanged, or raise where a strict YAML reader would.

    `column` is the 1-based column of the scalar's first character, so every message
    points at the offending character the way PyYAML and libyaml do.
    """
    first = value[0]
    nxt = value[1:2]
    if first in PLAIN_FORBIDDEN_FIRST or (first in PLAIN_NEEDS_NONSPACE_NEXT and nxt in ("", " ", "\t")):
        raise ValueError(
            "%s: a plain scalar cannot start with %r; use a block scalar (>-) or quotes"
            % (_where(lineno, column), first))
    for index, ch in enumerate(value):
        if ch == ":" and value[index + 1:index + 2] in ("", " ", "\t"):
            raise ValueError(
                "%s: mapping values are not allowed here — an unquoted value holds ': ' "
                "or ends with ':'; use a block scalar (>-) or quotes"
                % _where(lineno, column + index))
        if ch == "#" and index and value[index - 1] in (" ", "\t"):
            raise ValueError(
                "%s: ' #' starts a comment inside an unquoted value, so the text after it "
                "is silently dropped; use a block scalar (>-) or quotes"
                % _where(lineno, column + index))
    return value


def _decode_double_quoted(value: str, lineno: int, column: int) -> str:
    out: List[str] = []
    index = 1
    while index < len(value):
        ch = value[index]
        if ch == '"':
            _check_after_quote(value[index + 1:], lineno, column + index + 1)
            return "".join(out)
        if ch == "\\":
            code = value[index + 1:index + 2]
            if code in DOUBLE_QUOTE_ESCAPES:
                out.append(DOUBLE_QUOTE_ESCAPES[code])
                index += 2
                continue
            if code in HEX_ESCAPES:
                width = HEX_ESCAPES[code]
                digits = value[index + 2:index + 2 + width]
                if len(digits) == width and all(c in "0123456789abcdefABCDEF" for c in digits):
                    out.append(chr(int(digits, 16)))
                    index += 2 + width
                    continue
            raise ValueError("%s: invalid escape in a double-quoted scalar" % _where(lineno, column + index))
        out.append(ch)
        index += 1
    raise ValueError("%s: double-quoted scalar is not closed on its line" % _where(lineno, column))


def _decode_single_quoted(value: str, lineno: int, column: int) -> str:
    out: List[str] = []
    index = 1
    while index < len(value):
        ch = value[index]
        if ch == "'":
            if value[index + 1:index + 2] == "'":
                out.append("'")
                index += 2
                continue
            _check_after_quote(value[index + 1:], lineno, column + index + 1)
            return "".join(out)
        out.append(ch)
        index += 1
    raise ValueError("%s: single-quoted scalar is not closed on its line" % _where(lineno, column))


def _check_after_quote(rest: str, lineno: int, column: int) -> None:
    stripped = rest.lstrip(" \t")
    if stripped and not (stripped.startswith("#") and stripped != rest):
        raise ValueError("%s: unexpected text after a closing quote" % _where(lineno, column))


def _scalar(value: str, lineno: int, column: int) -> str:
    if value.startswith('"'):
        return _decode_double_quoted(value, lineno, column)
    if value.startswith("'"):
        return _decode_single_quoted(value, lineno, column)
    return check_plain_scalar(value, lineno, column)


def _read_block_scalar(style: str, chomp: str, lines: List[str], start: int,
                       parent_indent: int, lineno: int) -> Tuple[str, int]:
    """Read the block scalar whose header sits on line `start - 1`; return (text, next)."""
    end = start
    while end < len(lines) and (not lines[end].strip() or
                                len(lines[end]) - len(lines[end].lstrip(" ")) > parent_indent):
        end += 1
    content = lines[start:end]
    while content and not content[-1].strip():  # trailing blank lines belong to chomping
        content.pop()
    if not content:
        raise ValueError("%s: block scalar has no content" % _where(lineno, len(lines[start - 1])))
    indent = min(len(l) - len(l.lstrip(" ")) for l in content if l.strip())
    if "\t" in "".join(l[:indent] for l in content if l.strip()):
        raise ValueError("%s: tabs cannot indent a block scalar" % _where(lineno + 1, 1))
    body = [l[indent:] if l.strip() else "" for l in content]
    if style == "|":
        text = "\n".join(body)
    else:  # folded: a line break between two non-empty, non-indented lines becomes a space
        parts: List[str] = []
        for i, line in enumerate(body):
            if i:
                prev = body[i - 1]
                more_indented = line.startswith((" ", "\t")) or prev.startswith((" ", "\t"))
                if line and prev and not more_indented:
                    parts.append(" ")
                elif prev or more_indented:
                    parts.append("\n")
            parts.append(line)
        text = "".join(parts)
    if chomp == "+":
        text += "\n" * (1 + (end - start - len(content)))
    elif chomp == "":
        text += "\n"
    return text, end


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Parse SKILL.md front matter strictly; raise ValueError with line and column."""
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    try:
        raw, body = text[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise ValueError("SKILL.md frontmatter is not closed") from exc
    lines = raw.split("\n")
    data: Dict[str, Any] = {}
    nested: Dict[str, Any] = {}
    nested_key = None
    index = 0
    while index < len(lines):
        line = lines[index]
        lineno = index + 2  # line 1 is the opening ---
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        if "\t" in line[:len(line) - len(line.lstrip())]:
            raise ValueError("%s: tabs cannot indent YAML" % _where(lineno, 1))
        indent = len(line) - len(line.lstrip(" "))
        if indent and nested_key is None:
            raise ValueError("%s: unexpected indented line — a multi-line value needs a "
                             "block scalar (>-) or quotes" % _where(lineno, 1))
        if indent not in (0, 2):
            raise ValueError("%s: nested keys must be indented by exactly two spaces" % _where(lineno, 1))
        target = nested if indent else data
        if not indent:
            _require_children(nested_key, nested, lineno)
            nested_key = None
        key, sep, rest = line[indent:].partition(":")
        if not sep or not FRONTMATTER_KEY.fullmatch(key) or (rest and not rest.startswith((" ", "\t"))):
            raise ValueError("%s: expected 'key: value'" % _where(lineno, indent + 1))
        if key in target:
            raise ValueError("%s: duplicate key %r" % (_where(lineno, indent + 1), key))
        value = rest.strip(" \t")
        column = indent + len(key) + 2 + (len(rest) - len(rest.lstrip(" \t")))
        header = BLOCK_HEADER.fullmatch(value.split(" #", 1)[0].rstrip()) if value else None
        if header:
            target[key], index = _read_block_scalar(header.group(1), header.group(2), lines,
                                                    index + 1, indent, lineno)
            continue
        if value.startswith("#"):
            raise ValueError("%s: the value of %r is a comment, so the key reads as null; quote "
                             "it or use a block scalar (>-)" % (_where(lineno, column), key))
        if value:
            target[key] = _scalar(value, lineno, column)
        elif indent:
            raise ValueError("%s: nested value for %r is empty" % (_where(lineno, indent + 1), key))
        else:
            nested = {}
            data[key] = nested
            nested_key = key
        index += 1
    _require_children(nested_key, nested, len(lines) + 1)
    return data, body


def _require_children(key: Any, nested: Dict[str, Any], lineno: int) -> None:
    if key is not None and not nested:
        raise ValueError("line %d: %r has no value — YAML reads it as null" % (lineno - 1, key))


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
    if data.get("license") != LICENSE_SPDX:
        errors.append("skill license must be %s" % LICENSE_SPDX)
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
            root = name.split(".", 1)[0]
            if (path.parent / (root + ".py")).is_file():
                continue  # a sibling module shipped in the same scripts directory
            if root not in STDLIB_IMPORTS:
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


# #region contract-pin — docs: README.md#contract-pin
# G-11: one contract pin. fabric-contract.lock.json is the pin; every live file that
# names a contract revision names that one. Dated records keep the revision of their
# day, and tests plant other revisions on purpose, so both are excluded. The same rule
# as the contract's `pnpm pin:check` (docs/specification/versioning.md#one-contract-pin).
PIN_FILE = ROOT / "fabric-contract.lock.json"
PIN_EXCLUDED = ("docs/evidence", "docs/handoffs", "test", "CHANGELOG.md", "fabric-contract.lock.json", "node_modules")
PIN_MENTION = re.compile(r"fabric[- ]agent[- ]contract|contract[-_ ]?(pin|commit|revision)|CONTRACT_COMMIT", re.IGNORECASE)
PIN_HEX = re.compile(r"(?<![0-9a-zA-Z:])[0-9a-f]{7,40}(?![0-9a-zA-Z])")


def contract_pin_drift(root: Path, commit: str) -> List[str]:
    drift: List[str] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if not path.is_file() or ".git" in path.parts or any(rel == x or rel.startswith(x + "/") for x in PIN_EXCLUDED):
            continue
        if path.suffix not in (".md", ".json", ".py", ".mjs", ".js", ".yml", ".yaml", ".toml", ".txt"):
            continue
        section = False
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if re.match(r"^#{1,6}\s", line):
                section = bool(PIN_MENTION.search(line))
            other_repo = "github.com/" in line and "fabric-agent-contract" not in line
            # In this repository a full 40-character commit is always a contract pin,
            # however the sentence around it is worded.
            candidates = [] if other_repo else [h for h in PIN_HEX.findall(line) if len(h) == 40]
            if section or PIN_MENTION.search(line):
                candidates = PIN_HEX.findall(line)
            for found in dict.fromkeys(candidates):
                if re.search(r"[a-f]", found) and re.search(r"[0-9]", found) and not commit.startswith(found):
                    drift.append("contract pin: %s:%d names %s; the pin is %s" % (rel, number, found, commit))
    return drift


def validate_contract_pin(errors: List[str], root: Path = ROOT) -> None:
    try:
        pin = json.loads((root / "fabric-contract.lock.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append("contract pin: fabric-contract.lock.json is missing or unreadable (%s)" % exc.__class__.__name__)
        return
    commit = str(pin.get("commit", ""))
    if pin.get("contract") != "fabric-agent-contract" or not re.fullmatch(r"[0-9a-f]{40}", commit) \
            or pin.get("repository") != "https://github.com/passioncode-ai/fabric-agent-contract":
        errors.append("contract pin: fabric-contract.lock.json needs contract, version, repository and a 40-character commit")
        return
    script = (SKILLS["adapting-projects-to-fabric"] / "scripts/adapt_project.py").read_text(encoding="utf-8")
    for constant, expected in (("CONTRACT_COMMIT", commit), ("CONTRACT_VERSION", pin.get("version"))):
        match = re.search(r'^%s = "([^"]+)"' % constant, script, re.MULTILINE)
        if not match or match.group(1) != expected:
            errors.append("contract pin: adapt_project.py %s is %s; the pin says %s" % (constant, match.group(1) if match else "missing", expected))
    errors.extend(contract_pin_drift(root, commit))
# #endregion contract-pin


def validate_repo() -> List[str]:
    errors: List[str] = []
    for path in EXPECTED_FILES:
        if not path.is_file():
            errors.append("missing required file: %s" % path.relative_to(ROOT))
    if errors:
        return errors

    for name in SKILL_NAMES:
        validate_skill(name, errors)
    validate_contract_pin(errors)

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
        if value.get("license") != LICENSE_SPDX:
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

    card = (ROOT / "SKILL-CARD.md").read_text(encoding="utf-8")
    card_versions = re.findall(r"^\| Version \| `([^`]+)` \|$", card, re.MULTILINE)
    if len(card_versions) != len(SKILL_NAMES) or set(card_versions) != {VERSION}:
        errors.append("SKILL-CARD.md needs one Version row per skill, each at %s" % VERSION)

    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    for name in SKILL_NAMES:
        if 'test -f "$HOME/.agents/skills/%s/SKILL.md"' % name not in release:
            errors.append("release smoke must check the agents hub install of %s" % name)
    if 'test -f "$HOME/.claude/skills/' in release:
        errors.append("release smoke expects ~/.claude/skills, where the installer no longer writes")
    if "validate.py\" --frontmatter" not in release:
        errors.append("release smoke must parse the installed SKILL.md front matter strictly")

    # The license is source-available; the README, the manifests and the skills say the
    # same thing, and contributions come in under the CLA the PR template asks for.
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    for needle in ("# PolyForm Noncommercial License 1.0.0", "# PolyForm Internal Use License 1.0.0",
                   "released under the MIT License"):
        if needle not in license_text:
            errors.append("LICENSE must carry both PolyForm texts and the MIT-history sentence (%r)" % needle)
    if re.search(r"(?<![\"\u201c])\bopen[- ]source\b|license-MIT", (ROOT / "README.md").read_text(encoding="utf-8"), re.IGNORECASE):
        errors.append("README.md calls the adapter open source or MIT; it is source-available")
    if "I agree to CLA.md" not in (ROOT / ".github/pull_request_template.md").read_text(encoding="utf-8"):
        errors.append("the PR template must carry the 'I agree to CLA.md' checkbox")
    if "CLA.md" not in (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8"):
        errors.append("CONTRIBUTING.md must say contributions are accepted under CLA.md")
    if pkg.get("license") != LICENSE_SPDX:
        errors.append("package.json license is out of sync")

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
        "license": LICENSE_SPDX,
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
    planted = "---\nname: x\ndescription: Use when X extension: which. NOT for Y.\n---\n"
    try:
        parse_frontmatter(planted)
    except ValueError:
        return []
    return ["validator self-test accepted an unquoted ': ' in a front-matter value"]


def check_frontmatter_files(paths: List[str]) -> List[str]:
    """Strictly parse the front matter of the given SKILL.md files (any location)."""
    errors: List[str] = []
    if not paths:
        return ["--frontmatter needs at least one SKILL.md path"]
    for raw in paths:
        path = Path(raw)
        try:
            data, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors.append("%s: %s" % (raw, exc))
            continue
        description = data.get("description")
        if not isinstance(description, str) or not description:
            errors.append("%s: description must be a non-empty string" % raw)
        elif len(description) > 1024:
            errors.append("%s: description exceeds 1024 characters (%d)" % (raw, len(description)))
    return errors


def main(argv: List[str]) -> int:
    if argv[:1] == ["--frontmatter"]:
        errors = check_frontmatter_files(argv[1:])
        for error in errors:
            print("ERROR: %s" % error)
        if not errors:
            print("OK: %d SKILL.md front matter block(s) parse strictly" % len(argv[1:]))
        return 1 if errors else 0
    if argv:
        print("usage: validate.py [--frontmatter SKILL.md ...]")
        return 2
    errors = validator_self_test() + validate_repo()
    if errors:
        for error in errors:
            print("ERROR: %s" % error)
        return 1
    print("OK: Fabric Agent Adapter distribution is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
