"""fabric-package/1, the schema reading: the package schema bundled from the contract at the pin, read by a JSON Schema
2020-12 subset with JavaScript's patterns, lengths in code points and the formats the contract uses, as
fabric-package.mjs reads it. fabric_package checks, packs, signs and verifies on it and re-exports these names. Part of
the service kit (FAA-92, split from fabric_package; layer L2). Standard library only, Python 3.9+."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))

# What pack refuses to list is matched with JavaScript's `.`; fabric_package reads it from here.
_JS_DOT = "[^\n\r\u2028\u2029]"

#: JavaScript's whitespace, what String.prototype.trim and the regular expression class \s take (ECMA-262 WhiteSpace
#: and LineTerminator), so a key file and a URI are read as fabric-package.mjs reads them.
JS_WHITESPACE = "\t\n\x0b\x0c\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"

SCHEMA_PATH = Path(__file__).resolve().parent / "fabric-package.schema.json"

# --- the schema (bundled from the contract at the pin) ------------------------------------------------

_SCHEMA_CACHE: Dict[str, Any] = {}


def _schema() -> Dict[str, Any]:
    if "s" not in _SCHEMA_CACHE:
        _SCHEMA_CACHE["s"] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE["s"]


from fabric_jsvalue import json_equal as _json_equal  # noqa: E402 - the core's (FAA-65)


def _type_of(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


# ASCII digits only and the whole string (fullmatch): Python's \d takes any Unicode digit and its $ a trailing newline,
# which JavaScript's do not (FAA-78, finding 43).
_DATE_TIME = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]+)?([Zz]|[+-]([0-9]{2}):([0-9]{2}))")
_URI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:[^%s]*" % JS_WHITESPACE)
_MONTH_DAYS = (0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _format_ok(fmt: str, value: Any) -> bool:
    if not isinstance(value, str):
        return True
    if fmt == "date-time":
        m = _DATE_TIME.fullmatch(value)
        if not m:
            return False
        year, month, day, hour, minute, second = (int(g) for g in m.groups()[:6])
        # The proleptic calendar the contract's ajv-formats checks: year 0000 exists and is a leap year (0000-02-29
        # holds). datetime starts at year 1, so the days are counted here, as fabric-package.mjs counts them.
        if not 1 <= month <= 12 or not 1 <= day <= (29 if month == 2 and _leap(year) else _MONTH_DAYS[month]):
            return False
        if hour > 23 or minute > 59 or second > 59:
            return False
        return m.group(8) in ("Z", "z") or (int(m.group(9)) < 24 and int(m.group(10)) < 60)
    if fmt == "uri":
        return bool(_URI.fullmatch(value))
    return True


_PATTERNS: Dict[str, Any] = {}


def _js_pattern(source: str) -> Any:
    """A schema's ECMAScript pattern (``u`` flag) as Python reads it the same way: ``$`` is the end of the string, not
    the end before a final newline; ``.`` stops at JavaScript's line terminators (\\n, \\r, U+2028, U+2029); ``\\d`` and
    ``\\w`` are ASCII. Escapes and character classes are copied as written."""
    if source not in _PATTERNS:
        out: List[str] = []
        i, in_class = 0, False
        while i < len(source):
            ch = source[i]
            if ch == "\\":
                out.append(source[i:i + 2])
                i += 2
                continue
            if in_class:
                in_class = ch != "]"
            elif ch == "[":
                in_class = True
            elif ch == "$":
                ch = r"\Z"
            elif ch == ".":
                ch = _JS_DOT
            out.append(ch)
            i += 1
        _PATTERNS[source] = re.compile("".join(out), re.ASCII)
    return _PATTERNS[source]


def _pointer(token: Any) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def _validate(schema: Any, value: Any, at: str, out: List[Dict[str, str]]) -> None:
    """The JSON Schema 2020-12 keywords the package schema uses, nothing more."""
    if schema is True:
        return
    if schema is False:
        out.append({"instancePath": at, "message": "is not allowed here"})
        return
    if "$ref" in schema:
        target = _schema()
        for token in schema["$ref"].lstrip("#/").split("/"):
            target = target[token.replace("~1", "/").replace("~0", "~")]
        _validate(target, value, at, out)
    kind = _type_of(value)
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not (kind in allowed or (kind == "integer" and "number" in allowed)):
            out.append({"instancePath": at, "message": "must be %s" % " or ".join(allowed)})
            return
    if "const" in schema and not _json_equal(schema["const"], value):
        out.append({"instancePath": at, "message": "must be %s" % json.dumps(schema["const"])})
    if "enum" in schema and not any(_json_equal(item, value) for item in schema["enum"]):
        out.append({"instancePath": at, "message": "must be one of %s" % ", ".join(json.dumps(i) for i in schema["enum"])})
    if kind == "string":
        length = len(value)  # code points, as JSON Schema counts
        if length < schema.get("minLength", 0):
            out.append({"instancePath": at, "message": "is shorter than %d" % schema["minLength"]})
        if "maxLength" in schema and length > schema["maxLength"]:
            out.append({"instancePath": at, "message": "is longer than %d" % schema["maxLength"]})
        if "pattern" in schema and not _js_pattern(schema["pattern"]).search(value):
            out.append({"instancePath": at, "message": "does not match %s" % schema["pattern"]})
        if "format" in schema and not _format_ok(schema["format"], value):
            out.append({"instancePath": at, "message": "is not a %s" % schema["format"]})
    if kind in ("integer", "number") and "minimum" in schema and value < schema["minimum"]:
        out.append({"instancePath": at, "message": "is below %s" % schema["minimum"]})
    if kind == "array":
        if len(value) < schema.get("minItems", 0):
            out.append({"instancePath": at, "message": "has fewer than %d items" % schema["minItems"]})
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append({"instancePath": at, "message": "has more than %d items" % schema["maxItems"]})
        if schema.get("uniqueItems") and any(_json_equal(value[i], value[j]) for i in range(len(value)) for j in range(i)):
            out.append({"instancePath": at, "message": "has duplicate items"})
        if "items" in schema:
            for index, item in enumerate(value):
                _validate(schema["items"], item, "%s/%d" % (at, index), out)
        if "contains" in schema:
            matches = sum(1 for item in value if not _problems(schema["contains"], item))
            if matches < schema.get("minContains", 1):
                out.append({"instancePath": at, "message": "has fewer than %d matching items" % schema.get("minContains", 1)})
            if "maxContains" in schema and matches > schema["maxContains"]:
                out.append({"instancePath": at, "message": "has more than %d matching items" % schema["maxContains"]})
    if kind == "object":
        for name in schema.get("required", []):
            if name not in value:
                out.append({"instancePath": at, "message": "must have %s" % name})
        properties = schema.get("properties", {})
        for name, member in value.items():
            if name in properties:
                _validate(properties[name], member, "%s/%s" % (at, _pointer(name)), out)
            elif "additionalProperties" in schema:
                if schema["additionalProperties"] is False:
                    out.append({"instancePath": "%s/%s" % (at, _pointer(name)), "message": "is not a member of this object"})
                else:
                    _validate(schema["additionalProperties"], member, "%s/%s" % (at, _pointer(name)), out)
            if "propertyNames" in schema:
                _validate(schema["propertyNames"], name, "%s/%s" % (at, _pointer(name)), out)
    for sub in schema.get("allOf", []):
        _validate(sub, value, at, out)
    if "not" in schema and not _problems(schema["not"], value):
        out.append({"instancePath": at, "message": "must not match"})
    if "if" in schema:
        branch = schema.get("then") if not _problems(schema["if"], value) else schema.get("else")
        if branch is not None:
            _validate(branch, value, at, out)


def _problems(schema: Any, value: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    _validate(schema, value, "", out)
    return out


def schema_problems(pkg: Any) -> List[Dict[str, str]]:
    """Where the package breaks ``fabric-package.schema.json`` (the contract's, bundled at the pin)."""
    return _problems(_schema(), pkg)


# --- the contract's rules (FAC-SEM-064…066, FAC-SEM-102) ------------------------------------------------
