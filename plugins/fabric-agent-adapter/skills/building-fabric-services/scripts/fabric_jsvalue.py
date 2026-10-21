"""JavaScript's view of JSON values, once for the whole kit (FAA-65, layer L0).

The contract's answers are computed by TypeScript, so a kit that reads JSON the way Python does disagrees with them on
the edges: `5.0` is a count, an integer beyond a double is Infinity, `String({"toString": 1})` throws, object keys
that look like array indexes come first. Every reader in the kit takes those semantics from here:

- ``js_string`` (``String()``), ``show`` (the contract's ``show``: ``String()``, or JSON where it would throw),
  ``json_stringify`` (``JSON.stringify``), ``js_to_number`` (``Number()``), ``double``, ``safe_integer``;
- ``same`` (``===``) and ``contains``, ``get`` with the ``MISSING`` sentinel for an absent member;
- ``jcs`` (RFC 8785 canonical JSON) and the number formatting it shares with ``js_string``.

Standard library only; nothing here imports another kit module.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Tuple


def js_number_string(value: float) -> str:
    """ECMAScript Number::toString, which RFC 8785 §3.2.2.3 prescribes."""
    if value == 0:
        return "0"
    if value < 0:
        return "-" + js_number_string(-value)
    digits, exponent = _shortest(value)
    k, n = len(digits), len(digits) + exponent
    if k <= n <= 21:
        return digits + "0" * (n - k)
    if 0 < n <= 21:
        return digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return "0." + "0" * (-n) + digits
    e = n - 1
    mantissa = digits if k == 1 else digits[0] + "." + digits[1:]
    return "%se%s%d" % (mantissa, "+" if e >= 0 else "-", abs(e))


def _shortest(value: float) -> Tuple[str, int]:
    """The shortest round-trip digits of a positive finite double (Python's repr is shortest round-trip)."""
    text = repr(value)
    mantissa, _, exp = text.partition("e")
    whole, _, frac = mantissa.partition(".")
    digits = (whole + frac).lstrip("0")
    exponent = (int(exp) if exp else 0) - len(frac)
    if not digits:
        return "0", 0
    stripped = digits.rstrip("0")
    exponent += len(digits) - len(stripped)
    return stripped, exponent


JSON_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def json_string_literal(value: str) -> str:
    out = ['"']
    for ch in value:
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            raise TypeError("a lone surrogate has no canonical form")
        if ch in JSON_ESCAPES:
            out.append(JSON_ESCAPES[ch])
        elif code < 0x20:
            out.append("\\u%04x" % code)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def jcs(value: Any) -> str:
    """RFC 8785: members sorted by UTF-16 code units, numbers in ECMAScript form, strings as JSON.stringify
    escapes them. Refuses what has no canonical form: a non-finite number, a lone surrogate, a non-JSON value.
    A JSON number is a double: an integer beyond 2**53 is written as JavaScript would write it."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if abs(value) < 2 ** 53:
            return str(value)
        try:
            return js_number_string(float(value))
        except OverflowError:
            raise TypeError("a number beyond a double has no canonical form") from None
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("a non-finite number has no canonical form")
        return js_number_string(value)
    if isinstance(value, str):
        return json_string_literal(value)
    if isinstance(value, list):
        return "[" + ",".join(jcs(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("only string member names have a canonical form")
        keys = sorted(value, key=lambda key: key.encode("utf-16-be", "surrogatepass"))
        return "{" + ",".join(json_string_literal(key) + ":" + jcs(value[key]) for key in keys) + "}"
    raise TypeError("%s has no canonical form" % type(value).__name__)


MISSING = object()


def js_string(value: Any) -> str:
    """String(value) for a JSON value."""
    if value is MISSING:
        return "undefined"
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return js_number_string(value)
    if isinstance(value, int):
        if abs(value) < 2 ** 53:
            return str(value)
        try:
            return js_number_string(float(value))
        except OverflowError:  # a JSON number beyond a double is Infinity in JavaScript
            return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, dict):
        return "[object Object]"
    if isinstance(value, list):
        return ",".join("" if item is None else js_string(item) for item in value)
    return str(value)


def get(value: Any, key: str) -> Any:
    return value.get(key, MISSING) if isinstance(value, dict) else MISSING


def get_string(value: Any, key: str) -> str:
    return js_string(get(value, key))


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def double(value: Any) -> float:
    """A JSON number as JavaScript holds it: the nearest double, and an integer beyond the double range ±Infinity."""
    try:
        return float(value)
    except OverflowError:
        return math.inf if value > 0 else -math.inf


def same(a: Any, b: Any) -> bool:
    """JavaScript's === (and a Set's SameValueZero) on parsed JSON: an object equals only itself."""
    if a is MISSING or b is MISSING:
        return a is b
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if is_number(a) and is_number(b):
        return double(a) == double(b)  # 2**53 + 1 is 2**53 in JavaScript
    return type(a) is type(b) and a == b


def contains(items: List[Any], value: Any) -> bool:
    return any(same(item, value) for item in items)


#: The characters JavaScript's StringToNumber trims: WhiteSpace and LineTerminator (ECMA-262 §12.2, §12.3).
_JS_SPACE = "\t\n\v\f\r                  　﻿"


_JS_DECIMAL = re.compile(r"[+-]?(?:(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|Infinity)", re.ASCII)


_JS_RADIX = re.compile(r"0(?:[xX](?P<x>[0-9a-fA-F]+)|[oO](?P<o>[0-7]+)|[bB](?P<b>[01]+))", re.ASCII)


def js_to_number(value: Any) -> float:
    """Number(value) for a JSON value, as JavaScript reads it; NaN for what it cannot read as a number."""
    if value is MISSING:
        return math.nan
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if is_number(value):
        try:
            return float(value)
        except OverflowError:
            return math.inf if value > 0 else -math.inf
    if isinstance(value, list):
        return js_to_number(js_string(value))  # Number([2]) is Number("2"); Number([]) is 0
    if isinstance(value, str):
        text = value.strip(_JS_SPACE)
        if text == "":
            return 0.0
        if _JS_DECIMAL.fullmatch(text):
            return float(text.replace("Infinity", "inf"))
        radix = _JS_RADIX.fullmatch(text)
        if radix:
            digits, base = next((radix.group(k), b) for k, b in (("x", 16), ("o", 8), ("b", 2)) if radix.group(k))
            return double(int(digits, base))
    return math.nan


def safe_integer(value: Any) -> bool:
    if isinstance(value, int) and not isinstance(value, bool):
        return abs(value) <= 2 ** 53 - 1  # checked before any float: a 400-digit integer would overflow
    return isinstance(value, float) and math.isfinite(value) and value.is_integer() and abs(value) <= 2 ** 53 - 1


def objects(value: Any) -> List[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def indexed_objects(value: Any) -> List[Tuple[Dict[str, Any], int]]:
    """The object items of an array with their index in the array as written, so an instancePath names the item it
    flags even when a non-object precedes it (the contract's ``indexed``)."""
    return [(item, i) for i, item in enumerate(value) if isinstance(item, dict)] if isinstance(value, list) else []


class Unshowable(Exception):
    pass


def strict_string(value: Any) -> str:
    """String(value), raising where JavaScript's String() throws: an object whose own ``toString`` is not a function
    (every own member of parsed JSON is data), directly or inside an array it joins."""
    if isinstance(value, dict):
        if "toString" in value:
            raise Unshowable()
        return "[object Object]"
    if isinstance(value, list):
        return ",".join("" if item is None else strict_string(item) for item in value)
    return js_string(value)


_INDEX_KEY = re.compile(r"0|[1-9][0-9]*", re.ASCII)


def js_keys(value: Dict[str, Any]) -> List[str]:
    """An object's own keys in the order JavaScript lists them: array-index keys ("0" … "4294967294", no leading zero)
    ascending, then the others in the order written."""
    index = sorted((k for k in value if _INDEX_KEY.fullmatch(k) and int(k) <= 2 ** 32 - 2), key=int)
    taken = set(index)
    return index + [k for k in value if k not in taken]


def json_string(text: str) -> str:
    """JSON.stringify of a string (well-formed, ES2019): a lone surrogate is escaped as \\uXXXX, never refused."""
    out = ['"']
    for ch in text:
        code = ord(ch)
        if ch in JSON_ESCAPES:
            out.append(JSON_ESCAPES[ch])
        elif code < 0x20 or 0xD800 <= code <= 0xDFFF:
            out.append("\\u%04x" % code)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def json_stringify(value: Any) -> str:
    """JSON.stringify for a parsed JSON value: members in JavaScript's key order, numbers as JavaScript writes them, a
    lone surrogate escaped."""
    if isinstance(value, dict):
        return "{" + ",".join(json_string(k) + ":" + json_stringify(value[k]) for k in js_keys(value)) + "}"
    if isinstance(value, list):
        return "[" + ",".join(json_stringify(v) for v in value) + "]"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if is_number(value):
        text = js_string(value)
        return "null" if text in ("NaN", "Infinity", "-Infinity") else text
    return json_string(value)


def show(value: Any) -> str:
    """The contract's ``show``: String(value), or the value's JSON where String() would throw."""
    try:
        return strict_string(value)
    except Unshowable:
        return json_stringify(value)


def key_of(*parts: Any) -> str:
    """The contract's ``keyOf``: a collision-free key over JSON values, JSON.stringify of the parts (an absent value
    is null inside an array, as JavaScript writes it)."""
    return json_stringify([None if part is MISSING else part for part in parts])
from typing import Any


def json_equal(a: Any, b: Any) -> bool:
    """The contract's jsonEqual: arrays in order, objects by their members, primitives as JavaScript's ===."""
    if isinstance(a, list) or isinstance(b, list):
        return isinstance(a, list) and isinstance(b, list) and len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) or isinstance(b, dict):
        return isinstance(a, dict) and isinstance(b, dict) and len(a) == len(b) and all(k in b and json_equal(a[k], b[k]) for k in a)
    return same(a, b)
