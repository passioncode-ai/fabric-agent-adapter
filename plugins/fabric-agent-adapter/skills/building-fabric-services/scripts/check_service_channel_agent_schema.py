"""The schema half of the probe's channel-agent rule (FAA-197, DEC-0150 FAC-SEM-162): the vendored
`service-channel-agent-extension.schema.json` at the contract pin, a JSON Schema reader for exactly the keywords that
file uses, giving Ajv's errors in Ajv's order (allErrors, verbose), and the contract's reading of those errors as
places (`src/channel-agent.ts`: widths, oversize's names, placedToken, allowed, placed, messagePlaces, schemaErrors).

No place carries a declared value: a member name the schema does not declare is written `*` (CA-5). Not a kit module:
the probe has no Node twin and kit.json does not list it. Standard library only, Python 3.9+."""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fabric_jsvalue import double, is_number, js_keys, js_string, json_equal  # noqa: E402

SCHEMA_FILE = Path(__file__).resolve().parent / "service-channel-agent-extension.schema.json"
#: FAC-SEM-162's one answer when the schema itself cannot run on a value.
TOO_LARGE = "the value is too large to check"
#: A string value or a member name longer than this, in code points, is refused before the schema runs (CA-2).
LONGEST_STRING = 4096
#: The arrays the schema declares: a numeric token after one of them is an index a path may carry.
ARRAYS = frozenset(("projects", "codes", "tiers", "channels", "sources", "declined_sources", "handoff_queues", "recorded_decisions"))
ENUM_VALUES = 8
PATTERN_CHARACTERS = 80
_INDEX = re.compile(r"(?:0|[1-9][0-9]{0,8})\Z")
_NONE_FORM_AT = re.compile(r"(?:^|/)projects/[0-9]+/(?:question_route|gap_registry|tickets/pd_check|channels/[0-9]+/texts/final)\Z")
_TEXTS_AT = re.compile(r"(?:^|/)channels/[0-9]+/texts(?:/holding)?\Z")
_CLOSED_TEXTS_AT = re.compile(r"/channels/[0-9]+/texts\Z")

# Ajv's keyword groups in the order its generated code runs them (ajv 8, draft 2020-12): the untyped group first, then
# one group per data type, each keyword in its vocabulary's order. Only what the vendored schema uses is read.
_GROUPS = (
    (None, ("$ref", "const", "enum", "not", "oneOf", "if")),
    ("number", ("maximum", "minimum")),
    ("string", ("maxLength", "minLength", "pattern", "format")),
    ("array", ("maxItems", "minItems", "items")),
    ("object", ("maxProperties", "minProperties", "required", "propertyNames", "additionalProperties", "properties")),
)
_GROUP_KEYS = {group: keys for group, keys in _GROUPS if group is not None}
#: Members a schema node may carry that change nothing: metadata, and `then`/`else`, which `if` reads.
_INERT = frozenset(("$schema", "$id", "title", "description", "$defs", "then", "else", "type"))
SUPPORTED = frozenset(k for _, keys in _GROUPS for k in keys) | _INERT
#: What Ajv counts as a rule beside a `$ref` (a `$ref` with none is read as the reference alone).
_RULES = SUPPORTED - frozenset(("$schema", "$id", "title", "description", "$defs"))
_FORMATS = ("date",)

_schema: Optional[Dict[str, Any]] = None
_names: Optional[Set[str]] = None
_patterns: Dict[str, "re.Pattern[str]"] = {}


def schema() -> Dict[str, Any]:
    """The vendored schema, read once."""
    global _schema
    if _schema is None:
        _schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    return _schema


def unsupported(node: Any = None) -> List[str]:
    """The keywords and formats a schema node (default: the vendored schema) uses that this reader does not read."""
    found: List[str] = []
    stack = [schema() if node is None else node]
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, dict):
            for key, value in item.items():
                if key not in SUPPORTED:
                    found.append(key)
                elif key == "format" and value not in _FORMATS:
                    found.append("format %s" % value)
                if key in ("properties", "$defs"):
                    stack.extend(value.values())
                elif key not in ("enum", "const", "required", "pattern", "description", "title"):
                    stack.append(value)
    return sorted(set(found))


def _pattern(text: str) -> "re.Pattern[str]":
    """An ECMAScript pattern (u flag) as Python reads it: `$` outside a class is the end of input only (\\Z)."""
    if text not in _patterns:
        out, i, in_class = [], 0, False
        while i < len(text):
            char = text[i]
            if char == "\\":
                out.append(text[i:i + 2])
                i += 2
                continue
            if char == "[":
                in_class = True
            elif char == "]":
                in_class = False
            out.append("\\Z" if char == "$" and not in_class else char)
            i += 1
        _patterns[text] = re.compile("".join(out))
    return _patterns[text]


def _is(data: Any, kind: str) -> bool:
    if kind == "object":
        return isinstance(data, dict)
    if kind == "array":
        return isinstance(data, list)
    if kind == "string":
        return isinstance(data, str)
    if kind == "boolean":
        return isinstance(data, bool)
    if kind == "null":
        return data is None
    if kind in ("number", "integer"):
        if not is_number(data) or not math.isfinite(double(data)):
            return False
        return kind == "number" or double(data) % 1 == 0
    return False


_DAYS = (0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _date(text: str) -> bool:
    """ajv-formats' full `date`: YYYY-MM-DD with a real month and day, leap years counted."""
    match = re.match(r"([0-9]{4})-([0-9]{2})-([0-9]{2})\Z", text)
    if not match:
        return False
    year, month, day = (int(part) for part in match.groups())
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    return 1 <= month <= 12 and 1 <= day <= (29 if month == 2 and leap else _DAYS[month])


def _pointer(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def _has_ref(node: Any) -> bool:
    if isinstance(node, dict):
        return "$ref" in node or any(_has_ref(value) for key, value in node.items() if key not in ("enum", "const"))
    return isinstance(node, list) and any(_has_ref(item) for item in node)


class _Reader:
    """Ajv's allErrors validation of one value, errors in its order with keyword, instancePath, schemaPath, params,
    the keyword's schema (verbose) and, inside propertyNames, the member name. A definition that refers to no other is
    inlined, so its errors' schemaPath starts `#/$defs/<name>`; one that does is its own function, whose paths start `#`."""

    def __init__(self, root: Dict[str, Any]):
        self.defs = root.get("$defs") or {}

    def node(self, sch: Any, data: Any, ip: str, sp: str, errs: List[Dict[str, Any]], pn: Optional[str]) -> bool:
        start = len(errs)
        if sch is True:
            return True
        if sch is False or not isinstance(sch, dict):
            errs.append(self.error("false schema", ip, sp, {}, False, pn))
            return False
        if "$ref" in sch and not any(key in _RULES for key in sch if key != "$ref"):
            return self.ref(sch["$ref"], data, ip, errs, pn)
        types = [sch["type"]] if isinstance(sch.get("type"), str) else list(sch.get("type") or [])
        used = {group: any(key in sch for key in keys) for group, keys in _GROUP_KEYS.items()}
        type_first = bool(types) and not (len(types) == 1 and used.get(types[0], False))
        if type_first and not any(_is(data, kind) for kind in types):
            errs.append(self.error("type", ip, sp + "/type", {"type": sch["type"]}, sch["type"], pn))
        for group, keys in _GROUPS:
            if group is not None and not used[group]:
                continue
            if group is not None and not _is(data, group):
                if types == [group] and not type_first:
                    errs.append(self.error("type", ip, sp + "/type", {"type": sch["type"]}, sch["type"], pn))
                continue
            for key in keys:
                if key in sch:
                    getattr(self, "k_" + key.lstrip("$"))(sch, sch[key], data, ip, sp, errs, pn)
        return len(errs) == start

    def error(self, keyword: str, ip: str, sp: str, params: Dict[str, Any], value: Any, pn: Optional[str]) -> Dict[str, Any]:
        error = {"keyword": keyword, "instancePath": ip, "schemaPath": sp, "params": params, "schema": value}
        if pn is not None:
            error["propertyName"] = pn
        return error

    def ref(self, ref: str, data: Any, ip: str, errs: List[Dict[str, Any]], pn: Optional[str]) -> bool:
        name = ref[len("#/$defs/"):]
        target = self.defs[name]
        return self.node(target, data, ip, "#" if _has_ref(target) else "#/$defs/" + name, errs, pn)

    def k_ref(self, sch, value, data, ip, sp, errs, pn) -> None:
        self.ref(value, data, ip, errs, pn)

    def k_const(self, sch, value, data, ip, sp, errs, pn) -> None:
        if not json_equal(data, value):
            errs.append(self.error("const", ip, sp + "/const", {"allowedValue": value}, value, pn))

    def k_enum(self, sch, value, data, ip, sp, errs, pn) -> None:
        if not any(json_equal(data, item) for item in value):
            errs.append(self.error("enum", ip, sp + "/enum", {"allowedValues": value}, value, pn))

    def k_not(self, sch, value, data, ip, sp, errs, pn) -> None:
        if self.node(value, data, ip, sp + "/not", [], pn):
            errs.append(self.error("not", ip, sp + "/not", {}, value, pn))

    def k_oneOf(self, sch, value, data, ip, sp, errs, pn) -> None:
        start, passing = len(errs), []
        for i, branch in enumerate(value):
            if self.node(branch, data, ip, "%s/oneOf/%d" % (sp, i), errs, pn):
                passing.append(i)
        if len(passing) == 1:
            del errs[start:]
        else:
            errs.append(self.error("oneOf", ip, sp + "/oneOf", {"passingSchemas": passing[:2] or None}, value, pn))

    def k_if(self, sch, value, data, ip, sp, errs, pn) -> None:
        branch = "then" if self.node(value, data, ip, sp + "/if", [], pn) else "else"
        if branch in sch and not self.node(sch[branch], data, ip, "%s/%s" % (sp, branch), errs, pn):
            errs.append(self.error("if", ip, sp + "/if", {"failingKeyword": branch}, value, pn))

    def k_maximum(self, sch, value, data, ip, sp, errs, pn) -> None:
        if double(data) > value:
            errs.append(self.error("maximum", ip, sp + "/maximum", {"comparison": "<=", "limit": value}, value, pn))

    def k_minimum(self, sch, value, data, ip, sp, errs, pn) -> None:
        if double(data) < value:
            errs.append(self.error("minimum", ip, sp + "/minimum", {"comparison": ">=", "limit": value}, value, pn))

    def k_maxLength(self, sch, value, data, ip, sp, errs, pn) -> None:
        if len(data) > value:  # code points, as Ajv's ucs2length counts them
            errs.append(self.error("maxLength", ip, sp + "/maxLength", {"limit": value}, value, pn))

    def k_minLength(self, sch, value, data, ip, sp, errs, pn) -> None:
        if len(data) < value:
            errs.append(self.error("minLength", ip, sp + "/minLength", {"limit": value}, value, pn))

    def k_pattern(self, sch, value, data, ip, sp, errs, pn) -> None:
        if not _pattern(value).search(data):
            errs.append(self.error("pattern", ip, sp + "/pattern", {"pattern": value}, value, pn))

    def k_format(self, sch, value, data, ip, sp, errs, pn) -> None:
        if value == "date" and not _date(data):
            errs.append(self.error("format", ip, sp + "/format", {"format": value}, value, pn))

    def k_maxItems(self, sch, value, data, ip, sp, errs, pn) -> None:
        if len(data) > value:
            errs.append(self.error("maxItems", ip, sp + "/maxItems", {"limit": value}, value, pn))

    def k_minItems(self, sch, value, data, ip, sp, errs, pn) -> None:
        if len(data) < value:
            errs.append(self.error("minItems", ip, sp + "/minItems", {"limit": value}, value, pn))

    def k_items(self, sch, value, data, ip, sp, errs, pn) -> None:
        for i, item in enumerate(data):
            self.node(value, item, "%s/%d" % (ip, i), sp + "/items", errs, pn)

    def k_maxProperties(self, sch, value, data, ip, sp, errs, pn) -> None:
        if len(data) > value:
            errs.append(self.error("maxProperties", ip, sp + "/maxProperties", {"limit": value}, value, pn))

    def k_minProperties(self, sch, value, data, ip, sp, errs, pn) -> None:
        if len(data) < value:
            errs.append(self.error("minProperties", ip, sp + "/minProperties", {"limit": value}, value, pn))

    def k_required(self, sch, value, data, ip, sp, errs, pn) -> None:
        for name in value:
            if name not in data:
                errs.append(self.error("required", ip, sp + "/required", {"missingProperty": name}, value, pn))

    def k_propertyNames(self, sch, value, data, ip, sp, errs, pn) -> None:
        for key in js_keys(data):
            if not self.node(value, key, ip, sp + "/propertyNames", errs, key):
                errs.append(self.error("propertyNames", ip, sp + "/propertyNames", {"propertyName": key}, value, pn))

    def k_additionalProperties(self, sch, value, data, ip, sp, errs, pn) -> None:
        declared = sch.get("properties") or {}
        for key in js_keys(data):
            if key in declared:
                continue
            if value is False:
                errs.append(self.error("additionalProperties", ip, sp + "/additionalProperties", {"additionalProperty": key}, value, pn))
            elif value is not True:
                self.node(value, data[key], ip + "/" + _pointer(key), sp + "/additionalProperties", errs, pn)

    def k_properties(self, sch, value, data, ip, sp, errs, pn) -> None:
        for name, sub in value.items():
            if name in data:
                self.node(sub, data[name], ip + "/" + _pointer(name), "%s/properties/%s" % (sp, name), errs, pn)


def validate(value: Any) -> List[Dict[str, Any]]:
    """The schema's errors on a value, as Ajv lists them; an empty list when it is valid."""
    errs: List[Dict[str, Any]] = []
    _Reader(schema()).node(schema(), value, "", "#", errs, None)
    return errs


def schema_names() -> Set[str]:
    """Every member name the schema declares: a path token that is not one (a text's language, an unknown member) is `*`."""
    global _names
    if _names is None:
        names: Set[str] = set()
        stack: List[Any] = [schema()]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                if isinstance(node.get("properties"), dict):
                    names.update(node["properties"])
                stack.extend(node.values())
        _names = names
    return _names


def is_none(value: Any) -> bool:
    """The standard's form for a required member a project does not have: an object with a `none` member (CA-2)."""
    return isinstance(value, dict) and "none" in value


def placed_token(previous: Optional[str], before: Optional[str], token: str, index: bool, names: Set[str],
                 none_form: bool = False) -> str:
    """A member's token in a FAC-SEM-162 place: a declared name, or an index of a declared array, else `*`."""
    if none_form and before == "texts" and previous == "final" and token in ("none", "until"):
        return token
    if before == "texts" and previous in ("holding", "final"):
        return "*"
    if index:
        return token if previous is not None and previous in ARRAYS and _INDEX.match(token) else "*"
    return token if token in names else "*"


def resolved(node: Any, defs: Dict[str, Any], value: Any = None) -> Dict[str, Any]:
    """A schema node with its `$ref` followed and a member that takes the none form resolved to the value's branch."""
    at = node
    while True:
        if isinstance(at, dict) and isinstance(at.get("$ref"), str):
            at = defs[at["$ref"][len("#/$defs/"):]]
        elif isinstance(at, dict) and all(k in at for k in ("if", "then", "else")) and "properties" not in at:
            at = at["then"] if is_none(value) else at["else"]
        else:
            return at if isinstance(at, dict) else {}


def widths(value: Any) -> List[str]:
    """The places of every array past its maxItems, map past its maxProperties and closed object with more members than
    it declares, read before the schema runs so it never makes one error per member (CA-2)."""
    root = schema()
    defs = root["$defs"]
    found: List[str] = []
    stack: List[Any] = [(value, root, "")]
    while stack:
        item, node, at = stack.pop()
        rule = resolved(node, defs, item)
        if isinstance(item, list):
            if is_number(rule.get("maxItems")) and len(item) > rule["maxItems"]:
                found.append("maxItems at %s (at most %s items)" % (at, js_string(rule["maxItems"])))
            elif "items" in rule:
                for i in range(len(item) - 1, -1, -1):
                    stack.append((item[i], rule["items"], "%s/%d" % (at, i)))
        elif isinstance(item, dict):
            count = len(item)
            declared = rule.get("properties") if isinstance(rule.get("properties"), dict) else None
            if declared is not None and rule.get("additionalProperties") is False and count > len(declared):
                elsewhere = "; only texts.final takes the none form (Narrowings)" if _CLOSED_TEXTS_AT.search(at) and "none" in item else ""
                found.append("maxProperties at %s (more members than the schema declares%s)" % (at or "/", elsewhere))
            elif is_number(rule.get("maxProperties")) and count > rule["maxProperties"]:
                found.append("maxProperties at %s (at most %s members)" % (at, js_string(rule["maxProperties"])))
            elif declared is not None:
                present = [name for name in declared if name in item]
                for name in reversed(present):
                    stack.append((item[name], declared[name], "%s/%s" % (at, name)))
    return found


def type_of(branch: Any) -> Optional[str]:
    """A branch's type, through its `$ref`s into the schema's own `$defs`."""
    if not isinstance(branch, dict):
        return None
    if isinstance(branch.get("type"), str):
        return branch["type"]
    if isinstance(branch.get("$ref"), str):
        return type_of(schema()["$defs"].get(branch["$ref"][len("#/$defs/"):]))
    return None


def name_rule(rule: Dict[str, Any]) -> str:
    """What a `propertyNames` schema takes, from the schema alone: its pattern, its length, the name it refuses."""
    parts = []
    if isinstance(rule.get("pattern"), str):
        parts.append("matching %s" % rule["pattern"])
    if is_number(rule.get("maxLength")):
        parts.append("at most %s code points" % js_string(rule["maxLength"]))
    if isinstance(rule.get("not"), dict) and "const" in rule["not"]:
        parts.append("other than %s" % js_string(rule["not"]["const"]))
    return "a member name %s" % ", ".join(parts) if parts else "a member name the schema takes"


def allowed(error: Dict[str, Any], names: Set[str], at: str = "") -> str:
    """What the schema allows at a failed place, from the schema alone, never the instance."""
    params = error.get("params") or {}
    keyword, rule = error["keyword"], error.get("schema")
    texts = bool(_TEXTS_AT.search(at))
    elsewhere = "; only texts.final takes the none form (Narrowings)" if texts and "none" in (params.get("additionalProperty"), params.get("propertyName")) else ""
    if keyword == "required" and isinstance(params.get("missingProperty"), str) and params["missingProperty"] in names:
        return " (%s)" % params["missingProperty"]
    if keyword == "additionalProperties":
        return " (only declared members are taken%s)" % elsewhere
    if keyword == "propertyNames" and isinstance(rule, dict):
        return " (%s%s)" % (name_rule(rule), elsewhere)
    if keyword == "enum" and isinstance(params.get("allowedValues"), list):
        values = [js_string(v) for v in params["allowedValues"]]
        rest = " and %d more" % (len(values) - ENUM_VALUES) if len(values) > ENUM_VALUES else ""
        return " (one of %s%s)" % (", ".join(values[:ENUM_VALUES]), rest)
    if keyword == "const" and "allowedValue" in params:
        return " (%s)" % js_string(params["allowedValue"])
    if keyword == "pattern" and isinstance(params.get("pattern"), str):
        pattern = params["pattern"]
        return " (pattern %s)" % (pattern[:PATTERN_CHARACTERS] + "\u2026" if len(pattern) > PATTERN_CHARACTERS else pattern)
    limit = params.get("limit") if is_number(params.get("limit")) else None
    if limit is not None:
        def count(word: str) -> str:
            return "%s %s%s" % (js_string(limit), word, "" if limit == 1 else "s")
        words = {"maxLength": "at most %s" % count("code point"), "minLength": "at least %s" % count("code point"),
                 "maxItems": "at most %s" % count("item"), "minItems": "at least %s" % count("item"),
                 "maxProperties": "at most %s" % count("member"), "minProperties": "at least %s" % count("member")}
        if keyword in words:
            return " (%s)" % words[keyword]
        if keyword in ("minimum", "maximum"):
            return " (%s %s)" % (js_string(params.get("comparison")), js_string(limit))
    if keyword == "format" and isinstance(params.get("format"), str):
        return " (format %s)" % params["format"]
    if keyword == "not" and isinstance(rule, dict) and isinstance(rule.get("required"), list):
        return " (%s only with not_yet)" % ", ".join(rule["required"])
    if keyword == "not" and isinstance(rule, dict) and "const" in rule:
        return " (a value other than %s)" % js_string(rule["const"])
    if keyword == "type" and isinstance(params.get("type"), (str, list)):
        form = ", or the none form {none: not_yet, until} / {none: not_used}" if _NONE_FORM_AT.search(at) else ""
        kinds = params["type"] if isinstance(params["type"], list) else [params["type"]]
        return " (%s%s)" % (" or ".join(kinds), form)
    if keyword == "oneOf":
        if isinstance(rule, list):
            kinds = [type_of(branch) for branch in rule]
            types = [kind for kind in kinds if kind is not None and kind != "null"]
            if "null" in kinds and types:
                return " (%s %s or null)" % ("an" if re.match(r"[aeiou]", types[0]) else "a", " or ".join(types))
        return " (exactly one of its forms)"
    return ""


def placed(error: Dict[str, Any], or_null: bool = False) -> str:
    """An error as its keyword and its place, every free member name replaced by `*`, never a declared value."""
    names = schema_names()
    tokens = [t.replace("~1", "/").replace("~0", "~") for t in error["instancePath"].split("/")[1:]]
    none_form = isinstance(error.get("schemaPath"), str) and not error["schemaPath"].startswith("#/$defs/texts")
    at = "/".join(placed_token(tokens[i - 1] if i >= 1 else None, tokens[i - 2] if i >= 2 else None, token,
                               bool(_INDEX.match(token)), names, none_form) for i, token in enumerate(tokens))
    return "%s at /%s%s%s" % (error["keyword"], at, allowed(error, names, at), ", or null" if or_null else "")


def message_places(places: List[str]) -> List[str]:
    """The places a message names, each distinct pattern spelled once; a later one reads `(pattern as above)`."""
    seen: Set[str] = set()
    out = []
    for written in places:
        or_null = ", or null" if written.endswith(", or null") else ""
        place = written[:len(written) - len(or_null)]
        at = place.find(" (pattern ")
        if at < 0:
            out.append(written)
            continue
        pattern = place[at:]
        if pattern in seen:
            out.append("%s (pattern as above)%s" % (place[:at], or_null))
        else:
            seen.add(pattern)
            out.append(written)
    return out


def schema_errors(value: Any, validator: Callable[[Any], List[Dict[str, Any]]] = validate) -> List[str]:
    """The schema's errors on a value as places: a nullable member fails in one line, its value branch's, ending
    ", or null"; `if` lines and a member name's inner lines (its propertyNames line states them) are dropped."""
    try:
        errors = validator(value)
    except RecursionError:
        return [TOO_LARGE]
    if not errors:
        return []
    nullable = {e["instancePath"] for e in errors
                if e["keyword"] == "oneOf" and isinstance(e.get("schema"), list) and any(type_of(b) == "null" for b in e["schema"])}
    kept = [e for e in errors if e["keyword"] != "if"
            and not (e["keyword"] != "propertyNames" and e.get("propertyName") is not None)
            and not (e["keyword"] == "type" and (e.get("params") or {}).get("type") == "null")
            and not (e["keyword"] == "oneOf" and e["instancePath"] in nullable)]
    return list(dict.fromkeys(placed(e, e["instancePath"] in nullable) for e in kept))
