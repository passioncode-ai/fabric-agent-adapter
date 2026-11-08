#!/usr/bin/env python3
"""Check an agent template folder against the template schema (fabric-workspace S2, decision W0-Q8; FAA-265).

    python3 template_check.py [--legacy] [--json] <template-folder> [...]

Reads only; writes nothing. Exit 0 when no folder has an error, 1 when one has, 2 on a usage error.

The rules come from the JSON Schema files in ../schemas/template/, read by a small interpreter of the subset they use,
so the schema and this check cannot drift apart. On top of the schemas it checks what one file cannot: the header's id
is the folder's name, manifest.json names the same template and version, every variant a file names is declared in the
header, TEMPLATE.md inherits the operating rules A1 to A12 by reference, and the folder holds its other parts.

--legacy reads the older spellings the first templates used (`class` for `source_class`, `withApproval`, a level
called `architect`, `spend` for `budget`, ...), names each one as a warning with its canonical form, and checks the
rest as if it were written canonically. Without it an older spelling is an error.
"""
import json
import re
import sys
from pathlib import Path

SCHEMAS = Path(__file__).resolve().parent.parent / "schemas" / "template"
JSON_FILES = {"manifest.json": "manifest", "connections.json": "connections", "access.json": "access",
              "data-rooms.json": "data-rooms"}
PROSE_FILES = ("TEMPLATE.md", "assembly.md", "CHANGELOG.md")
LEVELS = ("owner", "administrator", "project_architect", "member")
PER_VARIANT = ("placement", "doors", "models", "dashboard", "budget")


def load_schema(name):
    return json.loads((SCHEMAS / ("%s.schema.json" % name)).read_text(encoding="utf-8"))


# A JSON Schema interpreter for the subset the template schemas use. Each problem is (path, message).

TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _is_type(value, name):
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, TYPES[name])


def _resolve(ref, root):
    if not ref.startswith("#/"):
        raise ValueError("only local references are supported: %s" % ref)
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def check(value, schema, root, path="$"):
    if "$ref" in schema:
        return check(value, _resolve(schema["$ref"], root), root, path)
    problems = []
    if "oneOf" in schema:
        passing = [s for s in schema["oneOf"] if not check(value, s, root, path)]
        if len(passing) != 1:
            best = min((check(value, s, root, path) for s in schema["oneOf"]), key=len)
            return best or [(path, "matches more than one allowed form")]
    kinds = schema.get("type")
    if kinds is not None:
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if not any(_is_type(value, k) for k in kinds):
            return [(path, "must be %s" % " or ".join(kinds))]
    if "enum" in schema and value not in schema["enum"]:
        return [(path, "must be one of %s" % ", ".join(json.dumps(v) for v in schema["enum"]))]
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            problems.append((path, "must not be empty"))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            problems.append((path, "is longer than %d characters" % schema["maxLength"]))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            problems.append((path, "does not match %s" % schema["pattern"]))
    if _is_type(value, "number") and "minimum" in schema and value < schema["minimum"]:
        problems.append((path, "must be at least %s" % schema["minimum"]))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            problems.append((path, "needs at least %d item(s)" % schema["minItems"]))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            problems.append((path, "must hold at most %d item(s)" % schema["maxItems"]))
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            problems.append((path, "repeats an item"))
        if "items" in schema:
            for i, item in enumerate(value):
                problems += check(item, schema["items"], root, "%s[%d]" % (path, i))
    if isinstance(value, dict):
        if len(value) < schema.get("minProperties", 0):
            problems.append((path, "needs at least %d key(s)" % schema["minProperties"]))
        for key in schema.get("required", ()):
            if key not in value:
                problems.append((path, "lacks %s" % key))
        props = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            where = "%s.%s" % (path, key)
            if key in props:
                problems += check(item, props[key], root, where)
                continue
            matched = [p for p in patterns if re.search(p, key)]
            for p in matched:
                problems += check(item, patterns[p], root, where)
            if matched:
                continue
            if extra is False:
                problems.append((where, "is not a key of this file's schema"))
            elif isinstance(extra, dict):
                problems += check(item, extra, root, where)
    return problems


# The header of TEMPLATE.md: front matter holding one `template:` mapping of scalars and inline lists.

def _scalar(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [_scalar(part) for part in inner.split(",")] if inner else []
    if re.fullmatch(r"-?(0|[1-9][0-9]*)", text):
        return int(text)
    return text


def read_header(text):
    """The `template:` header as a dict, or raise ValueError naming what is wrong."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("does not start with a front matter block (---)")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ValueError("its front matter block is not closed (---)")
    header, current, last = {}, None, None
    for number, line in enumerate(lines[1:end], start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = re.sub(r"\s+#.*$", "", line)
        indent = len(stripped) - len(stripped.lstrip())
        match = re.fullmatch(r"([A-Za-z_][\w-]*):\s*(.*)", stripped.strip())
        if indent and match is None and current is not None and last is not None:
            # A continuation line of a long inline list.
            previous = current[last]
            if isinstance(previous, str) and previous.startswith("["):
                current[last] = previous + " " + stripped.strip()
                continue
        if match is None:
            raise ValueError("line %d is not `key: value`" % number)
        key, value = match.groups()
        if indent == 0:
            if value:
                header[key] = _scalar(value)
                current = None
            else:
                current = header[key] = {}
            last = None
        elif current is None:
            raise ValueError("line %d is indented under a key that holds a value" % number)
        else:
            current[key] = value
            last = key
    for block in header.values():
        if isinstance(block, dict):
            for key, value in list(block.items()):
                if isinstance(value, str) and value.startswith("[") and not value.endswith("]"):
                    raise ValueError("%s's list is not closed" % key)
                block[key] = _scalar(value) if isinstance(value, str) else value
    return header


# Older spellings (--legacy): each rewrite returns the canonical value and appends (path, message) warnings.

ARCHITECT = {"project architect", "project-architect", "architect", "projectArchitect"}
CAMEL = {"withApproval": "with_approval", "withoutAsking": "without_asking"}
CALLS = ("call", "ask", "respond", "proxy", "transport", "inference", "local")


def _direction(text):
    words = text.lower()
    reads = "read" in words
    writes = any(w in words for w in ("write", "spend", "sign", "send", "draw", "release", "upload", "order", "reply"))
    if reads and writes:
        return "read-write"
    if reads:
        return "read"
    if writes:
        return "write"
    if any(w in words for w in CALLS):
        return "call"
    return None


def _prose_to_enum(item, key, path, warnings, target):
    value = item.pop(key)
    if not isinstance(value, str):
        item[target] = value
        return
    enum = value if value in ("read", "write", "read-write", "call") else _direction(value)
    if enum is None:
        item[target] = value
        return
    item[target] = enum
    if enum != value or key != target:
        warnings.append(("%s.%s" % (path, key), "write %s: %s%s" % (
            target, json.dumps(enum), (", scope: %s" % json.dumps(value)) if enum != value else "")))
        if enum != value and "scope" not in item:
            item["scope"] = value


def _legacy_variants(item, path, warnings):
    key = "variants" if "variants" in item else "variant" if "variant" in item else None
    if key is None:
        return
    value = item.pop(key)
    values = value if isinstance(value, list) else [value]
    split = [v.strip() for part in values if isinstance(part, str) for v in part.split(",") if v.strip()]
    split += [v for v in values if not isinstance(v, str)]
    if any(isinstance(v, str) and v.lower() in ("all", "both", "every", "any") for v in split):
        warnings.append(("%s.%s" % (path, key), "every variant: leave variants out"))
        return
    item["variants"] = split
    if key != "variants" or split != value:
        warnings.append(("%s.%s" % (path, key), "write variants as a list of variant ids"))


def legacy_connections(items, warnings):
    if not isinstance(items, list):
        return items
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        path = "$[%d]" % i
        if "class" in item and "source_class" not in item:
            item["source_class"] = item.pop("class")
            warnings.append((path + ".class", "write source_class"))
        _legacy_variants(item, path, warnings)
        for key in ("direction", "mode", "access"):
            if key in item and (key != "direction" or item[key] not in ("read", "write", "read-write", "call")):
                if key != "direction" and "direction" in item:
                    continue
                _prose_to_enum(item, key, path, warnings, "direction")
                break
        required = item.get("required")
        if isinstance(required, str):
            lowered = required.lower()
            if lowered.startswith(("optional", "required")):
                item["required"] = lowered.startswith("required")
                rest = re.sub(r"^(optional|required)[\s,:;(]*", "", required, flags=re.I).rstrip(")").strip()
                if rest and "when" not in item:
                    item["when"] = rest
                warnings.append((path + ".required", "write required as true or false%s" % (
                    ", the condition in when" if rest else "")))
    return items


def legacy_access(doc, warnings):
    if not isinstance(doc, dict):
        return doc
    if "levels" not in doc:
        found = [k for k in list(doc) if k in LEVELS or k in ARCHITECT]
        if found:
            doc["levels"] = {k: doc.pop(k) for k in found}
            warnings.append(("$", "put the levels under levels"))
    levels = doc.get("levels")
    if isinstance(levels, dict):
        for key in list(levels):
            if key in ARCHITECT:
                levels["project_architect"] = levels.pop(key)
                warnings.append(("$.levels.%s" % key, "write project_architect"))
        for name, level in levels.items():
            if isinstance(level, dict):
                for key in list(level):
                    if key in CAMEL:
                        level[CAMEL[key]] = level.pop(key)
                        warnings.append(("$.levels.%s.%s" % (name, key), "write %s" % CAMEL[key]))
    for key in list(doc):
        if key != "never" and key.startswith("never") and isinstance(doc[key], list):
            doc.setdefault("never", [])
            doc["never"] = doc["never"] + doc.pop(key)
            warnings.append(("$.%s" % key, "write never"))
    if "never" not in doc:
        doc["never"] = []
        warnings.append(("$", "add never: what the agent never does at any level ([] when nothing)"))
    allowed = set(load_schema("access")["properties"])
    for key in list(doc):
        if key not in allowed and not key.startswith("x-"):
            slug = "x-" + re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")
            doc[slug] = doc.pop(key)
            warnings.append(("$.%s" % key, "a key of this template's own: write %s" % slug))
    return doc


def legacy_rooms(items, warnings):
    if not isinstance(items, list):
        return items
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        path = "$[%d]" % i
        if "block" in item and "blocks" not in item:
            value = item.pop("block")
            item["blocks"] = value if isinstance(value, list) else [value]
            warnings.append((path + ".block", "write blocks as a list"))
        _legacy_variants(item, path, warnings)
        if "writers" in item and "notes" not in item:
            item["notes"] = "writers: " + ", ".join(map(str, item.pop("writers")))
            warnings.append((path + ".writers", "a room's writers belong in the room's own template; noted"))
        if "why" in item and "use" not in item:
            item["use"] = item.pop("why")
            warnings.append((path + ".why", "write use"))
        if "access" in item and item["access"] not in ("read", "write", "read-write"):
            _prose_to_enum(item, "access", path, warnings, "access")
    return items


def _legacy_protocol(entry, path, warnings):
    if isinstance(entry, dict):
        for key in ("checkedAgainst", "checked"):
            if key in entry and "checked_against" not in entry:
                entry["checked_against"] = entry.pop(key)
                warnings.append(("%s.%s" % (path, key), "write checked_against"))


def legacy_manifest(doc, warnings):
    if not isinstance(doc, dict):
        return doc
    if "spend" in doc and "budget" not in doc:
        doc["budget"] = doc.pop("spend")
        warnings.append(("$.spend", "write budget"))
    contract = doc.get("contract")
    if isinstance(contract, dict):
        if "name" in contract or "checkedAgainst" in contract or "checked" in contract:
            _legacy_protocol(contract, "$.contract", warnings)
        else:
            for key, entry in contract.items():
                _legacy_protocol(entry, "$.contract.%s" % key, warnings)
    for key in ("interop",):
        if key in doc and isinstance(contract, dict) and "name" not in contract:
            contract[key] = doc.pop(key)
            warnings.append(("$.%s" % key, "put it in contract.%s" % key))
            _legacy_protocol(contract[key], "$.contract.%s" % key, warnings)
    allowed = set(load_schema("manifest")["properties"])
    for key in list(doc):
        if key not in allowed and not key.startswith("x-"):
            slug = "x-" + re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")
            doc[slug] = doc.pop(key)
            warnings.append(("$.%s" % key, "a key of this template's own: write %s" % slug))
    return doc


# Gaps no rewrite can fill: a warning under --legacy, an error otherwise.
LEGACY_GAPS = {("connections", "$[]", "lacks direction"), ("manifest", "$", "lacks version")}

LEGACY = {"connections": legacy_connections, "access": legacy_access, "data-rooms": legacy_rooms,
          "manifest": legacy_manifest}


def _variants_named(doc):
    named = set()
    if isinstance(doc, list):
        for item in doc:
            if isinstance(item, dict) and isinstance(item.get("variants"), list):
                named.update(v for v in item["variants"] if isinstance(v, str))
    return named


def check_folder(folder, legacy=False):
    """Every finding for one template folder: dicts {level, file, path, message}."""
    folder = Path(folder)
    findings = []

    def add(level, file, path, message):
        findings.append({"level": level, "file": file, "path": path, "message": message})

    if not folder.is_dir():
        add("error", ".", "$", "is not a folder")
        return findings
    header = None
    template_md = folder / "TEMPLATE.md"
    for name in PROSE_FILES:
        path = folder / name
        if not path.is_file():
            add("error", name, "$", "is missing")
        elif not path.read_text(encoding="utf-8", errors="replace").strip():
            add("error", name, "$", "is empty")
    if template_md.is_file():
        text = template_md.read_text(encoding="utf-8", errors="replace")
        try:
            header = read_header(text)
        except ValueError as error:
            add("error", "TEMPLATE.md", "$", str(error))
        if header is not None:
            schema = load_schema("template-header")
            for where, message in check(header, schema, schema):
                add("error", "TEMPLATE.md", where, message)
        if not (re.search(r"\bA1\b", text) and re.search(r"\bA12\b", text)):
            add("error", "TEMPLATE.md", "$", "does not inherit the operating rules A1 to A12 by reference")
    meta = header.get("template") if isinstance(header, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    template_id, version = meta.get("id"), meta.get("version")
    declared = set(meta.get("variants") or []) if isinstance(meta.get("variants"), list) else set()
    if isinstance(template_id, str) and template_id != folder.resolve().name:
        add("error", "TEMPLATE.md", "$.template.id", "is %s, the folder is %s" % (
            json.dumps(template_id), json.dumps(folder.resolve().name)))
    checks = folder / "checks"
    if not checks.is_dir() or not any(p.is_file() for p in checks.rglob("*")):
        add("error", "checks/", "$", "holds no acceptance check")
    changelog = folder / "CHANGELOG.md"
    if isinstance(version, str) and changelog.is_file() and version not in changelog.read_text(
            encoding="utf-8", errors="replace"):
        add("error", "CHANGELOG.md", "$", "has no entry for version %s" % version)

    docs = {}
    for file, schema_name in JSON_FILES.items():
        path = folder / file
        if not path.is_file():
            add("error", file, "$", "is missing")
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            add("error", file, "$", "is not JSON: %s" % error)
            continue
        if legacy:
            warnings = []
            doc = LEGACY[schema_name](doc, warnings)
            for where, message in warnings:
                add("warning", file, where, message)
        schema = load_schema(schema_name)
        for where, message in check(doc, schema, schema):
            gap = legacy and (schema_name, re.sub(r"\[\d+\]", "[]", where), message) in LEGACY_GAPS
            add("warning" if gap else "error", file, where, message + ("; required from schema 1 on" if gap else ""))
        docs[schema_name] = doc

    manifest = docs.get("manifest")
    if isinstance(manifest, dict):
        if template_id is not None and manifest.get("template") not in (None, template_id):
            add("error", "manifest.json", "$.template", "is %s, TEMPLATE.md names %s" % (
                json.dumps(manifest.get("template")), json.dumps(template_id)))
        if version is not None and manifest.get("version") not in (None, version):
            add("error", "manifest.json", "$.version", "is %s, TEMPLATE.md names %s" % (
                json.dumps(manifest.get("version")), json.dumps(version)))
        variants = manifest.get("variants") if isinstance(manifest.get("variants"), dict) else {}
        for name in sorted(set(variants) - declared):
            add("error", "manifest.json", "$.variants.%s" % name, "is not a variant TEMPLATE.md declares")
        for key in PER_VARIANT:
            if key in manifest:
                continue
            missing = [v for v in sorted(variants) if not isinstance(variants[v], dict) or key not in variants[v]]
            if not variants:
                add("error", "manifest.json", "$", "lacks %s" % key)
            elif missing:
                add("error", "manifest.json", "$", "lacks %s, at the top or in variants %s" % (key, ", ".join(missing)))
    for file, schema_name in (("connections.json", "connections"), ("data-rooms.json", "data-rooms")):
        for name in sorted(_variants_named(docs.get(schema_name)) - declared):
            add("error", file, "$", "names variant %s that TEMPLATE.md does not declare" % json.dumps(name))
    return findings


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    unknown = flags - {"--legacy", "--json"}
    if unknown or not args:
        sys.stderr.write("usage: template_check.py [--legacy] [--json] <template-folder> [...]\n")
        return 2
    report, failed = {}, False
    for folder in args:
        findings = check_folder(folder, legacy="--legacy" in flags)
        report[folder] = findings
        failed = failed or any(f["level"] == "error" for f in findings)
    if "--json" in flags:
        print(json.dumps({"ok": not failed, "folders": report}, indent=2, ensure_ascii=False))
    else:
        for folder, findings in report.items():
            errors = sum(f["level"] == "error" for f in findings)
            warnings = len(findings) - errors
            print("%s: %s" % (folder, "ok" if not findings else "%d error(s), %d warning(s)" % (errors, warnings)))
            for f in findings:
                print("  %s %s %s: %s" % (f["level"], f["file"], f["path"], f["message"]))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
