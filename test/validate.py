#!/usr/bin/env python3
"""Repository validator for the Fabric Agent Adapter distribution."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/fabric-agent-adapter"
SKILL_NAMES = ("adapting-projects-to-fabric", "building-fabric-services", "creating-fabric-agents", "working-with-fabric")
# The skills that BUILD an agent's repository carry the repository-standard rule; working-with-fabric builds
# nothing, it teaches a coding agent to work through Fabric.
BUILDER_SKILLS = ("adapting-projects-to-fabric", "building-fabric-services", "creating-fabric-agents")
SKILLS = {name: PLUGIN / "skills" / name for name in SKILL_NAMES}
VERSION = "0.55.0"
# Fabric ADR-0092. The three files are byte for byte the templates in fabric-workspace
# knowledge/templates/ (LICENSE-AGPL-3.0.txt, COMMERCIAL-LICENSE.md, CLA.md); the hashes pin them
# here because that repository is not readable from this one's CI.
LICENSE_SPDX = "AGPL-3.0-only OR LicenseRef-PassionCode-Commercial"
FIRST_AGPL_VERSION = "0.5.3"
TEMPLATE_SHA256 = {
    "LICENSE": "0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0",
    "COMMERCIAL-LICENSE.md": "893b4bb9e4597b19b178ad69f56b799b4e5d468463ecb2d05ab05f0eee92804a",
    "CLA.md": "cf44ce2b052fd75e9ef48f8124fb6eed71513c9152aac90eede0a2132951e408",
}
EXPECTED_FILES = tuple(
    [
        ROOT / ".claude-plugin/marketplace.json",
        PLUGIN / ".claude-plugin/plugin.json",
        ROOT / "README.md",
        ROOT / "CHANGELOG.md",
        ROOT / "LICENSE",
        ROOT / "COMMERCIAL-LICENSE.md",
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
    "shutil", "signal", "socket", "ssl", "stat", "threading", "time",
    "random", "io", "contextlib", "textwrap", "traceback", "difflib",
    "copy", "ctypes", "msvcrt",  # ctypes and msvcrt: the Windows paths of the service kit (DEC-0032)
    "email",  # email.utils: the probe reads a cookie's Expires date (DEC-0039)
    "xml",  # the supervisor tests read the Task Scheduler XML back (FAA-21)
    "ntpath", "posixpath",  # the lock name the Node kit holds, computed for either system (FAA-21)
    "ipaddress", "math", "struct",  # the delegation verifier: a loopback key-set URL, Ed25519 and claim checks (DEC-0039)
    "tomllib", "shlex",  # install-host-hooks reads Kimi Code's config.toml back and quotes the hook's path (FAA-12a)
    "collections", "queue",  # native bridge mappings and isolated no-model host probes (FAA-48)
    "unicodedata",  # the page-link port maps a host that is not ASCII as UTS 46 does (DEC-0123, FAA-132)
}
RECIPES = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/recipes"
KIT_MODULES = {e["module"] for e in json.loads(
    (ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/kit.json").read_text(encoding="utf-8"))["python"]}
NATIVE_HOST_IMPORTS = {
    "plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/hosts/hermes/__init__.py": {"hermes_cli.config"},
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
                "%s: mapping values are not allowed here: an unquoted value holds ': ' "
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
            raise ValueError("%s: unexpected indented line; a multi-line value needs a "
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
        raise ValueError("line %d: %r has no value: YAML reads it as null" % (lineno - 1, key))


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


#: Directories that hold other checkouts, not this tree: `.git`, and `.worktrees/` (git worktrees of this repository,
#: git-ignored). A walk that entered one validated another branch's files as this tree's (FAA-50).
NOT_THIS_TREE = (".git", ".worktrees")


def in_this_tree(path: Path, root: Path = ROOT) -> bool:
    """Whether a path the walk found belongs to this checkout, not to `.git` or a worktree beside it."""
    return not any(part in NOT_THIS_TREE for part in path.relative_to(root).parts)


def validate_links(errors: List[str]) -> None:
    for path in ROOT.rglob("*.md"):
        if not in_this_tree(path):
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
            if root in KIT_MODULES and RECIPES in path.parents:
                continue  # a recipe runs on the service kit: fabric_kit.py install copies these beside it (FAA-65)
            if root not in STDLIB_IMPORTS and name not in NATIVE_HOST_IMPORTS.get(path.relative_to(ROOT).as_posix(), set()):
                errors.append("non-stdlib import in %s: %s" % (path.relative_to(ROOT), name))


# A public skill page never defers to a source its reader cannot open (release iteration 1, N-12; USR-014).
# fabric-workspace is private to the organization: a page may cite it for provenance, but a paragraph that
# links or names it must not say that it "wins" or that this page is the defect. The public page is the rule.
PRIVATE_SOURCE = re.compile(r"fabric-workspace")
DEFERRAL = re.compile(r"\bwins\b|is the defect|takes precedence|\bprevails\b|is authoritative", re.IGNORECASE)


def private_source_deferrals(text: str) -> List[str]:
    """Each paragraph that names a private source and defers to it, as `line N: <start of the paragraph>`."""
    found: List[str] = []
    line = 1
    for paragraph in re.split(r"\n[ \t]*\n", text):
        if PRIVATE_SOURCE.search(paragraph) and DEFERRAL.search(paragraph):
            found.append("line %d: %s" % (line, " ".join(paragraph.split())[:80]))
        line += paragraph.count("\n") + 2
    return found


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
    # The repository the skill builds follows the PassionCode.ai standard when it is one; an agent
    # someone builds for themselves is outside the organization and its licence is its owner's.
    flat = " ".join(body.split())
    if name in BUILDER_SKILLS and ("For a PassionCode.ai repository" not in flat
                                   or "knowledge/repository-standard.md" not in flat):
        errors.append("%s: SKILL.md must send a PassionCode.ai repository to the repository standard "
                      "(knowledge/repository-standard.md)" % name)
    if name in BUILDER_SKILLS and ("builds for themselves" not in flat or "its owner's choice" not in flat):
        errors.append("%s: SKILL.md must say an agent someone builds for themselves is outside the standard "
                      "and its licence is its owner's choice" % name)
    if name == "creating-fabric-agents":
        # FAA-52: an agent that writes text for people carries the no-em-dash rule from its first commit.
        if "Text for people?" not in flat or "U+2014" not in flat:
            errors.append("%s: SKILL.md's grill must ask whether the agent writes text people read "
                          "and carry the no-em-dash rule (U+2014)" % name)
        resilience = " ".join((skill_dir / "references/resilience-and-autonomy.md").read_text(encoding="utf-8").split())
        if "U+2014" not in resilience or "no em dash" not in resilience.split("## Checklist", 1)[-1]:
            errors.append("%s: resilience-and-autonomy.md must state the no-em-dash rule (U+2014) "
                          "and ask for its check in the checklist" % name)
        # FAA-58: the knowledge a new agent starts from (where it runs, models and keys, orchestration and learning,
        # the practices), asked at the grill, linked from the skill, each reference closed by its checklist.
        if not all(q in flat for q in ("Where does it run, for whom?", "Which models?", "Who pays?", "How does it learn?")):
            errors.append("%s: SKILL.md's grill must ask where it runs, which models, who pays and how it learns" % name)
        for ref in ("where-agents-run.md", "models-and-providers.md", "orchestration-and-learning.md", "practices.md"):
            if "](references/%s)" % ref not in skill_text:
                errors.append("%s: SKILL.md must link references/%s" % (name, ref))
            path = skill_dir / "references" / ref
            if ref != "practices.md" and (not path.is_file() or "## The checklist" not in path.read_text(encoding="utf-8")):
                errors.append("%s: references/%s must end with its checklist" % (name, ref))
        scenarios_text = (ROOT / "test/evals" / name / "scenarios.json").read_text(encoding="utf-8")
        if "agent-for-a-personal-and-an-organization-cloud" not in scenarios_text:
            errors.append("%s: scenarios.json must cover an agent for clouds and models "
                          "(scenario agent-for-a-personal-and-an-organization-cloud)" % name)
        if "text-for-people-carries-no-em-dash" not in scenarios_text:
            errors.append("%s: scenarios.json must cover text for people "
                          "(scenario text-for-people-carries-no-em-dash)" % name)

    linked_refs = set(re.findall(r"\]\(references/([^)]+)\)", skill_text))
    actual_refs = {path.name for path in (skill_dir / "references").glob("*.md")}
    if linked_refs != actual_refs:
        errors.append("%s: every reference must be directly linked exactly once from SKILL.md" % name)
    for ref in (skill_dir / "references").glob("*.md"):
        text = ref.read_text(encoding="utf-8")
        if len(text.splitlines()) > 100 and "## Contents" not in text:
            errors.append("%s: reference over 100 lines needs Contents: %s" % (name, ref.name))
    for page in sorted(skill_dir.rglob("*.md")):
        for where in private_source_deferrals(page.read_text(encoding="utf-8")):
            errors.append("%s: %s defers to a private source (fabric-workspace); a public page states the rule "
                          "itself and cites the private page for provenance only (%s)"
                          % (name, page.relative_to(skill_dir), where))

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
# names a default contract revision names that one. The exact immutable supported
# declaration is the sole compatibility exception. Dated records keep the revision of their
# day, and tests plant other revisions on purpose, so both are excluded. The same rule
# as the contract's `pnpm pin:check` (docs/specification/versioning.md#one-contract-pin).
PIN_FILE = ROOT / "fabric-contract.lock.json"
PIN_EXCLUDED = ("docs/evidence", "docs/handoffs", "docs/reports", "test", "CHANGELOG.md", "fabric-contract.lock.json", "node_modules", ".agent-sync")
PIN_MENTION = re.compile(r"fabric[- ]agent[- ]contract|contract[-_ ]?(pin|commit|revision)|CONTRACT_COMMIT", re.IGNORECASE)
PIN_HANDOFF_LINK = re.compile(r"\]\((?:\.\./)*(?:docs/)?handoffs/[^)\s]*\)")
ACTION_PIN = re.compile(r"^(\s*(?:-\s+)?uses:\s*[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@)[0-9a-f]{40}(?![0-9a-zA-Z])")
PIN_HEX = re.compile(r"(?<![0-9a-zA-Z:])[0-9a-f]{7,40}(?![0-9a-zA-Z])")
PIN_ADAPTER = "plugins/fabric-agent-adapter/skills/adapting-projects-to-fabric/scripts/adapt_project.py"
PIN_DEFAULT_COMMIT = "00e050ba7429c0c60261cec871779e0fd6aeeb28"
PIN_PREVIOUS_COMMITS = ("1197a90dc4b57152cabcc71ad17db7559f35a27f", "e6c4fc16b415eec3190dd34d924d269405359dc9", "a3a66eb0052043847f6556348e37d34ca873a629", "52c7d798b9f4eb784eb4e29e717038a8912c759d", "2f020a696453ae299b123517f14957f6a1354379", "87d384ffce2757081b7ab227e5dad3dddd08328f", "0a4ce773c4b9e6bec40c6387eb3f988af7152c0e", "e742016dc396aa31e5a13a893489e43f15786c69", "bfa9a67aa3c6cb808c093e7d83cd59799f1ee7d0", "c55f2d5a11c9a0197e958e87212fca7ae1154769", "07042181bfae2a481aa0da1a5651f24c76669c48", "d8146cfb0a1c74fc6432284c4356bb0c864b37b5", "82e163665e156a08aa3b92e4711015582c06162c", "1636fa97262f4a26e2086572d540c2ee701e0010", "f00a7685e3861c27f7899c033fb850a145a1708f", "a046f57cf46ea9e3da57ff8ce6a3ed4d26d8774b", "fe55fc67cba1a9e34a736da7d148d4fe2a8fbfa0", "b291bf09e0a9f9fd3c16cf540832cd021203b7d1", "0cacd08b0e95b6abf131eae1206b60792138bc3c", "2eb91c00e852d9c31d804310d38fad91589fcbac", "8e49fbd5fbbf230e32c1969cd24ac3c22422f0a5", "a83bec6b47776af688402c18efec507143061f68", "52da526d7cc1e063d74c5b520dbc03d0ace15246", "78b2da018d2c4bd9ac1bde1dc3b7f1a110a175f5", "623bf61358c339cb10297807b3f024b5d9f1f327", "23f9fda4c05f8a3852246ee98d4f2adf74ed0875", "9091d3d6606b0c4b5591a38c3674356a01fd7f55", "df55c8c54a23251342a7ee57ba95642b7eb39e61", "2ce392291c6668598d12cd38327e24696b5ca15c")
PIN_SUPPORTED_DECLARATION = 'SUPPORTED_CONTRACT_COMMITS = (CONTRACT_COMMIT, "1197a90dc4b57152cabcc71ad17db7559f35a27f", "e6c4fc16b415eec3190dd34d924d269405359dc9", "a3a66eb0052043847f6556348e37d34ca873a629", "52c7d798b9f4eb784eb4e29e717038a8912c759d", "2f020a696453ae299b123517f14957f6a1354379", "87d384ffce2757081b7ab227e5dad3dddd08328f", "0a4ce773c4b9e6bec40c6387eb3f988af7152c0e", "e742016dc396aa31e5a13a893489e43f15786c69", "bfa9a67aa3c6cb808c093e7d83cd59799f1ee7d0", "c55f2d5a11c9a0197e958e87212fca7ae1154769", "07042181bfae2a481aa0da1a5651f24c76669c48", "d8146cfb0a1c74fc6432284c4356bb0c864b37b5", "82e163665e156a08aa3b92e4711015582c06162c", "1636fa97262f4a26e2086572d540c2ee701e0010", "f00a7685e3861c27f7899c033fb850a145a1708f", "a046f57cf46ea9e3da57ff8ce6a3ed4d26d8774b", "fe55fc67cba1a9e34a736da7d148d4fe2a8fbfa0", "b291bf09e0a9f9fd3c16cf540832cd021203b7d1", "0cacd08b0e95b6abf131eae1206b60792138bc3c", "2eb91c00e852d9c31d804310d38fad91589fcbac", "8e49fbd5fbbf230e32c1969cd24ac3c22422f0a5", "a83bec6b47776af688402c18efec507143061f68", "52da526d7cc1e063d74c5b520dbc03d0ace15246", "78b2da018d2c4bd9ac1bde1dc3b7f1a110a175f5", "623bf61358c339cb10297807b3f024b5d9f1f327", "23f9fda4c05f8a3852246ee98d4f2adf74ed0875", "9091d3d6606b0c4b5591a38c3674356a01fd7f55", "df55c8c54a23251342a7ee57ba95642b7eb39e61", "2ce392291c6668598d12cd38327e24696b5ca15c")'


def contract_pin_drift(root: Path, commit: str) -> List[str]:
    drift: List[str] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if not path.is_file() or not in_this_tree(path, root) or any(rel == x or rel.startswith(x + "/") for x in PIN_EXCLUDED):
            continue
        if path.suffix not in (".md", ".json", ".py", ".mjs", ".js", ".yml", ".yaml", ".toml", ".txt"):
            continue
        section = False
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if rel == PIN_ADAPTER and line == PIN_SUPPORTED_DECLARATION:
                continue
            # A link to a dated handoff names a historical file (docs/handoffs is itself excluded),
            # not the pin: its target is not scanned.
            line = PIN_HANDOFF_LINK.sub("]()", line)
            # A workflow step pins an action to the commit its release tag points at (FAA-73): that commit is the
            # action's, not the contract's. Only the ref after `uses: owner/repo@` is exempt; the rest of the line is scanned.
            if rel.startswith(".github/workflows/"):
                line = ACTION_PIN.sub(r"\1", line)
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
    if commit != PIN_DEFAULT_COMMIT:
        errors.append("contract pin: default commit must be the reviewed current revision")
    if pin.get("contract") != "fabric-agent-contract" or not re.fullmatch(r"[0-9a-f]{40}", commit) \
            or pin.get("repository") != "https://github.com/passioncode-ai/fabric-agent-contract" \
            or pin.get("version") != "0.1.0":
        errors.append("contract pin: fabric-contract.lock.json needs contract, version, repository and a 40-character commit")
        return
    script = (root / PIN_ADAPTER).read_text(encoding="utf-8")
    if script.splitlines().count(PIN_SUPPORTED_DECLARATION) != 1:
        errors.append("contract pin: supported immutable revision declaration must equal the reviewed list")
    try:
        tree = ast.parse(script)
    except SyntaxError as exc:
        errors.append("contract pin: adapt_project.py cannot be parsed (%s)" % exc)
        return
    expected_literals = {"CONTRACT_COMMIT": commit, "CONTRACT_VERSION": pin.get("version"),
                         "CONTRACT_REPOSITORY": pin.get("repository")}
    protected = set(expected_literals) | {"SUPPORTED_CONTRACT_COMMITS"}
    declarations = {}
    for constant in protected:
        bindings = [node for node in ast.walk(tree) if (
            isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id == constant
            or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == constant
            or isinstance(node, ast.arg) and node.arg == constant
            or isinstance(node, ast.ExceptHandler) and node.name == constant
            or isinstance(node, ast.alias) and (node.asname or node.name.split(".")[0]) == constant
            or type(node).__name__ in ("MatchAs", "MatchStar") and node.name == constant
            or type(node).__name__ == "MatchMapping" and node.rest == constant
        )]
        plain = [node for node in tree.body if isinstance(node, ast.Assign)
                 and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                 and node.targets[0].id == constant]
        if len(bindings) != 1 or len(plain) != 1:
            errors.append("contract pin: %s must have exactly one immutable declaration (plain top-level assignment)" % constant)
        else:
            declarations[constant] = plain[0].value
    for constant, expected in expected_literals.items():
        value = declarations.get(constant)
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str) or value.value != expected:
            errors.append("contract pin: adapt_project.py %s must be an exact string literal equal to %s" % (constant, expected))
    supported = declarations.get("SUPPORTED_CONTRACT_COMMITS")
    # The reviewed immutable earlier revisions: DEC-0035, DEC-0033, DEC-0031, DEC-0024, DEC-0021, DEC-0020 and DEC-0019.
    if not (isinstance(supported, ast.Tuple) and len(supported.elts) == 1 + len(PIN_PREVIOUS_COMMITS)
            and isinstance(supported.elts[0], ast.Name) and supported.elts[0].id == "CONTRACT_COMMIT"
            and all(isinstance(e, ast.Constant) and e.value == v for e, v in zip(supported.elts[1:], PIN_PREVIOUS_COMMITS))):
        errors.append("contract pin: SUPPORTED_CONTRACT_COMMITS must be the reviewed static tuple")
    # A portable scaffolder has no reason to mutate its module namespace dynamically.
    reflection = {"globals", "locals", "vars", "exec", "eval", "setattr", "delattr", "__dict__"}
    if any(isinstance(node, ast.Name) and node.id in reflection
           or isinstance(node, ast.Attribute) and (node.attr in reflection
               or node.attr in protected and isinstance(node.ctx, (ast.Store, ast.Del)))
           for node in ast.walk(tree)):
        errors.append("contract pin: dynamic namespace definitions or attribute mutations are forbidden")
    errors.extend(contract_pin_drift(root, commit))
# #endregion contract-pin


def validate_plugin_lifecycle(errors: List[str], plugin: Path) -> None:
    """FAA-22 (LC-19) and FAA-23 (LC-21) for the adapter's own plugin: it declares no MCP server — nothing starts per
    session but its one SessionStart hook — and no hook command carries a credential."""
    spec = importlib.util.spec_from_file_location(
        "fabric_secrets", ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_secrets.py")
    fabric_secrets = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fabric_secrets)
    manifest = plugin / ".claude-plugin" / "plugin.json"
    try:
        declared = json.loads(manifest.read_text(encoding="utf-8")).get("mcpServers") if manifest.is_file() else None
    except ValueError:
        declared = None
    if (plugin / ".mcp.json").exists() or declared:
        errors.append("LC-19: the plugin declares an MCP server; a plugin's server starts in every session that enables it")
    hooks = plugin / "hooks" / "hooks.json"
    if hooks.is_file():
        def commands(node: Any) -> List[str]:
            if isinstance(node, dict):
                found = [node["command"]] if isinstance(node.get("command"), str) else []
                return found + [c for v in node.values() for c in commands(v)]
            if isinstance(node, list):
                return [c for v in node for c in commands(v)]
            return []
        for command in commands(json.loads(hooks.read_text(encoding="utf-8"))):
            if fabric_secrets.secret_argument(command):
                errors.append("LC-21: a hook command carries a credential; argv is visible to every process")


def malformed_board_rows(text: str) -> List[str]:
    """Rows of a task table that do not split into its header's columns. The common-backlog aggregator splits a row on
    every `|`, an escaped `\\|` included, so a cell that holds one breaks the workspace's publication."""
    problems: List[str] = []
    width = None
    for number, line in enumerate(text.splitlines(), 1):
        if not line.startswith("|"):
            width = None
            continue
        cells = len(line.strip().strip("|").split("|"))
        if width is None:
            width = cells  # the header row
        elif not re.fullmatch(r"\|[\s:|-]+\|?", line.strip()) and cells != width:
            problems.append("docs/backlog.md:%d: a task row with %d cells in a table of %d (a `|` inside a cell, escaped or not, splits it)"
                            % (number, cells, width))
    return problems


# R1 (twin drift, audit 2026-10-22): in Python `$` also matches just before a trailing newline, so
# `re.match(r"^[a-z]+$", "abc\n")` accepts a value the Node twin's `/^[a-z]+$/.test` refuses. A pattern that
# validates a whole value ends in `\Z`, or is applied with `re.fullmatch` (which is why a direct `re.fullmatch`
# call is not checked: fullmatch already demands the end of the string).
DOLLAR_SCOPES = (
    ("plugins/fabric-agent-adapter/skills", "*/scripts/**/*.py"),  # every skill's scripts (FAA-72)
)
DOLLAR_CALLS = ("compile", "match", "search")
# (repository-relative path, the pattern exactly as written) -> why `$` is right there. A legitimate entry is a
# multiline use (re.MULTILINE, where `$` means "end of a line"). Entries that no longer match anything fail, so the
# list only shrinks by hand and never hides a new pattern.
DOLLAR_ALLOW = {
    ('plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/fabric_session_env.py',
     '^\\s*\\[\\s*"?mcp_servers"?\\s*\\.\\s*"?fabric"?\\s*\\]\\s*$'): "re.MULTILINE over a whole config.toml: `$` is the end of each line on purpose",
}


def _ends_in_unescaped_dollar(pattern: str) -> bool:
    if not pattern.endswith("$"):
        return False
    body = pattern[:-1]
    return (len(body) - len(body.rstrip("\\"))) % 2 == 0


def dollar_anchored_patterns(source: str) -> List[Tuple[int, str, str]]:
    """Each `re.compile/match/search(<literal ending in an unescaped $>, ...)` as (line, call, pattern)."""
    found: List[Tuple[int, str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "re"
                and node.func.attr in DOLLAR_CALLS and node.args):
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str) and _ends_in_unescaped_dollar(first.value):
            found.append((node.lineno, node.func.attr, first.value))
    return found


def dollar_anchor_problems(root: Path = ROOT, allow: Optional[Dict[Tuple[str, str], str]] = None) -> List[str]:
    allow = DOLLAR_ALLOW if allow is None else allow
    problems: List[str] = []
    used = set()
    for folder, glob in DOLLAR_SCOPES:
        for path in sorted((root / folder).glob(glob)):
            rel = path.relative_to(root).as_posix()
            try:
                found = dollar_anchored_patterns(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                problems.append("%s: cannot be parsed for the R1 check (%s)" % (rel, exc))
                continue
            for lineno, call, pattern in found:
                if (rel, pattern) in allow:
                    used.add((rel, pattern))
                    continue
                problems.append("%s:%d re.%s(%r) ends in `$`, which also matches before a trailing newline; "
                                "end it with \\Z or use re.fullmatch (R1), or allowlist a multiline use in "
                                "DOLLAR_ALLOW with its reason" % (rel, lineno, call, pattern))
    for (rel, pattern), reason in sorted(allow.items()):
        if not reason.strip():
            problems.append("DOLLAR_ALLOW entry for %s %r has no reason" % (rel, pattern))
        if (rel, pattern) not in used:
            problems.append("DOLLAR_ALLOW entry for %s %r matches nothing any more: remove it" % (rel, pattern))
    return problems


# R5 and FAA-72/FAA-73: the hosted gates must be able to fail. Text checks, no YAML library (standard library only).
WORKFLOW_USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$")
PINNED_ACTION = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}")


def workflow_problems(root: Path = ROOT) -> List[str]:
    problems: List[str] = []
    workflows = sorted((root / ".github/workflows").glob("*.yml"))
    for path in workflows:
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            match = WORKFLOW_USES.match(line)
            if match and not match.group(1).startswith("./"):
                if not PINNED_ACTION.fullmatch(match.group(1)) or not re.match(r"\s*#\s*v\d", match.group(2)):
                    problems.append("%s:%d pins %s to a moving ref; use the full commit SHA and a `# vX.Y.Z` comment"
                                    % (rel, lineno, match.group(1)))
            if re.search(r"@latest\b", line):
                problems.append("%s:%d installs @latest; name an exact release" % (rel, lineno))
        runs_on = len(re.findall(r"^    runs-on:", text, re.MULTILINE))
        timeouts = len(re.findall(r"^    timeout-minutes:\s*\d+", text, re.MULTILINE))
        if runs_on != timeouts:
            problems.append("%s: %d job(s) run on a runner but %d carry timeout-minutes; every job needs one"
                            % (rel, runs_on, timeouts))
    validate_yml = root / ".github/workflows/validate.yml"
    text = validate_yml.read_text(encoding="utf-8") if validate_yml.is_file() else ""
    needles = (
        ("schedule:", "a nightly schedule (the organization's CI batch)"),
        ("cron:", "a nightly schedule (the organization's CI batch)"),
        ("workflow_dispatch:", "workflow_dispatch"),
        ("workflow_call:", "workflow_call (release.yml runs it)"),
        ("cancel-in-progress: true", "a concurrency group that cancels superseded runs"),
        ("FABRIC_CONTRACT_NEW:", "a job that sets FABRIC_CONTRACT_NEW to an installed contract checkout"),
        ("FABRIC_CONTRACT_OLD:", "a job that sets FABRIC_CONTRACT_OLD to an installed contract checkout"),
        ("--frozen-lockfile", "the contract installed from its lockfile"),
        ('python-version: "3.9"', "a Python 3.9 run (the stated floor)"),
        ('node-version: "18"', "a Node 18 run (package.json engines)"),
        ("runs-on: macos-", "a macOS job (launchd is the first supervisor)"),
        ('-p "test_fabric_session.py"', "the session hooks on Windows"),
    )
    for needle, what in needles:
        if needle not in text:
            problems.append(".github/workflows/validate.yml must carry %s (%r)" % (what, needle))
    for trigger in ("push:", "pull_request:", "pull_request_target:"):
        if re.search(r"^  %s" % re.escape(trigger), text, re.MULTILINE):
            problems.append(".github/workflows/validate.yml must not run on %s (the nightly batch rule)" % trigger.rstrip(":"))
    release = root / ".github/workflows/release.yml"
    rtext = release.read_text(encoding="utf-8") if release.is_file() else ""
    smoke, create = rtext.find("npx --yes --package"), rtext.find("gh release create")
    if smoke < 0 or create < 0 or smoke > create:
        problems.append(".github/workflows/release.yml must run the packed-tarball smoke test before `gh release create`")
    return problems


def validate_repo() -> List[str]:
    errors: List[str] = []
    validate_plugin_lifecycle(errors, ROOT / "plugins/fabric-agent-adapter")
    for path in EXPECTED_FILES:
        if not path.is_file():
            errors.append("missing required file: %s" % path.relative_to(ROOT))
    if errors:
        return errors

    for name in SKILL_NAMES:
        validate_skill(name, errors)
    validate_contract_pin(errors)
    errors.extend(malformed_board_rows((ROOT / "docs/backlog.md").read_text(encoding="utf-8")))

    skill_files = sorted(path for path in ROOT.rglob("SKILL.md") if in_this_tree(path))
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
    for entry_name in ("bin", "plugins", "LICENSE", "COMMERCIAL-LICENSE.md"):
        if entry_name not in pkg.get("files", []):
            errors.append("package.json files whitelist must ship %s" % entry_name)

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^## ([0-9]+\.[0-9]+\.[0-9]+)", changelog, re.MULTILINE)
    if not match or match.group(1) != VERSION:
        errors.append("top changelog version is out of sync")

    for path in ROOT.rglob("*.json"):
        if in_this_tree(path) and ".agent-sync" not in path.parts:
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                errors.append("invalid JSON in %s: %s" % (path.relative_to(ROOT), exc))
    for path in ROOT.rglob("*.py"):
        if in_this_tree(path):
            validate_python_imports(path, errors)
    validate_links(errors)

    # The session hooks name the adapter's version to Fabric in clientInfo (`fabric-agent-adapter-hooks`); 0.51.1
    # shipped it at 0.51.0 because nothing read it here.
    hooks_env = (ROOT / "plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/fabric_session_env.py").read_text(encoding="utf-8")
    hooks_version = re.search(r'^VERSION = "([^"]+)"$', hooks_env, re.MULTILINE)
    if not hooks_version or hooks_version.group(1) != VERSION:
        errors.append("fabric_session_env.py VERSION is out of sync")

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

    # The licence (Fabric ADR-0092): the three files are the knowledge base templates, the README
    # says it in the organization's wording and names the PolyForm and MIT releases before it, and
    # contributions come in under the CLA the PR template asks for.
    template_names = {"LICENSE": "the AGPL-3.0 template", "COMMERCIAL-LICENSE.md": "the knowledge base template",
                      "CLA.md": "the knowledge base template"}
    for name, digest in TEMPLATE_SHA256.items():
        path = ROOT / name
        if not path.is_file():
            continue  # already reported as a missing file
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            errors.append("%s is not %s byte for byte (fabric-workspace knowledge/templates/)" % (name, template_names[name]))
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    if re.search(r"license-source--available|license-MIT|Source-available under|^Source-available", readme_text, re.IGNORECASE | re.MULTILINE):
        errors.append("README.md still states the retired licence (source-available / MIT); it is AGPL-3.0 or commercial")
    license_section = readme_text.split("\n## License\n", 1)[1] if "\n## License\n" in readme_text else ""
    for needle in ("Open source under the [GNU AGPL-3.0](LICENSE)", "[commercial license](COMMERCIAL-LICENSE.md)",
                   "https://passioncode.ai/business/", "Versions before %s were released under" % FIRST_AGPL_VERSION):
        if needle not in license_section:
            errors.append("README.md ## License must carry the licensing wording: %r" % needle)
    # Release state is CHANGELOG.md's and the GitHub releases': prose that says which version a checkout is, or which one
    # is the latest published, is stale by the next release (README said 0.21.0 until 0.40.0).
    for stale in re.finditer(r"(?:source checkout is|latest published[^.\n]*release)", readme_text, re.IGNORECASE):
        errors.append("README.md states release state (%r): link CHANGELOG.md instead" % stale.group(0))
    # The operator's rule: text a person reads carries no em dash (U+2014). CHANGELOG.md and docs/ are dated records.
    people = [ROOT / n for n in ("README.md", "AGENTS.md", "SKILL-CARD.md", "CONTRIBUTING.md", "SECURITY.md")]
    people += sorted((ROOT / "plugins/fabric-agent-adapter/skills").glob("*/SKILL.md"))
    people += sorted((ROOT / "plugins/fabric-agent-adapter/skills").glob("*/references/*.md"))
    people += sorted((ROOT / "plugins/fabric-agent-adapter/skills").glob("*/recipes/*/README.md"))  # FAA-111
    people += sorted((ROOT / "test/evals").glob("*/*.json"))
    # What the installer, the CLI and the kit's demo print or show to a person (code comments elsewhere are not scanned).
    people += [ROOT / "install.sh", ROOT / "bin/fabric-agent-adapter.js"]
    people += sorted((ROOT / "plugins/fabric-agent-adapter/skills").glob("*/assets/**/*.html"))
    # R6: the workflows print release titles and messages a person reads on GitHub (FAA-73).
    people += sorted(path for path in (ROOT / ".github").rglob("*") if path.is_file())
    for path in people:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if path.is_file() else ():
            if "\u2014" in line:
                errors.append("%s:%d carries an em dash (U+2014); use a full stop, comma, colon or parentheses"
                              % (path.relative_to(ROOT), lineno))
    pr_template = (ROOT / ".github/pull_request_template.md").read_text(encoding="utf-8")
    if "means you agree to the repository's `CLA.md`" not in pr_template:
        errors.append("the PR template must say that opening the pull request means agreeing to CLA.md")
    if re.search(r"- \[[ xX]\][^\n]*CLA", pr_template):
        errors.append("the PR template must not ask anyone to tick a CLA checkbox")
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
    errors.extend(workflow_problems())
    errors.extend(dollar_anchor_problems())
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
    deferring = ("Intro.\n\nThis page implements [the contract](https://github.com/passioncode-ai/fabric-workspace/"
                 "blob/main/knowledge/lifecycle.md). Where the two differ, the contract\nwins and this page is the defect.\n")
    found = private_source_deferrals(deferring)
    if len(found) != 1 or not found[0].startswith("line 3: This page implements"):
        return ["validator self-test missed a page that defers to a private source"]
    if private_source_deferrals("Provenance: fabric-workspace LC-14.\n\nThe operator's intent wins.\n"):
        return ["validator self-test flagged a deferral in a paragraph that names no private source"]
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
