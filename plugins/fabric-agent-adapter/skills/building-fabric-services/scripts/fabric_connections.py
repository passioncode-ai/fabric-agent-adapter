"""What an agent uses: `fabric-connections/0.1`, the extension keyed extensions/connections/0.1 (DEC-0096, FAC-SEM-127).
`connections_view` reads a well-known document as the contract's `connectionsView` does (it never raises);
`connections_extension` builds the `extensions` entry a service declares, `state` from its own checks and its
`degraded[]`. Part of the service kit (FAA-62, layer L3). Standard library only."""
from __future__ import annotations

import bisect
import ipaddress
import re
import unicodedata
import urllib.parse
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))

from fabric_base import ServiceError  # noqa: E402
from fabric_secrets import (  # noqa: E402
    JWT_SHAPE, _BEARER_INSIDE as _BEARER, _long_secret, credential_name, raw_values, secret_argument, secret_value,
)

CONNECTIONS_EXTENSION_KEY = "https://fabric.passioncode.ai/agent-contract/extensions/connections/0.1"
KINDS = ("service", "model", "connector", "store", "channel")
STATES = ("ok", "degraded", "down", "unknown")
MAX_CONNECTIONS = 64
_MEMBERS = ("id", "kind", "target", "capability", "state", "label", "purpose", "reason", "lastAt")
_STRING_MEMBERS = ("id", "target", "capability", "label", "purpose", "reason")

# ECMAScript's \s, which the schema's patterns and the contract's splits use: Python's \s differs (it takes \x1c-\x1f
# and \x85, and leaves U+FEFF out).
_JS_SPACE = "\t\n\x0b\x0c\r    -     　﻿"
_SPACES = re.compile("[%s]+" % _JS_SPACE)
_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_TARGET = re.compile("[^%s]+" % _JS_SPACE)
_SERVICE_TARGET = re.compile(r"[a-z0-9][a-z0-9-]{0,63}(?:\.[a-z0-9][a-z0-9-]{0,63})?")
_CAPABILITY = re.compile(r"[a-z][a-z0-9._-]{1,127}")
_LINE = re.compile("[^\n\r]+")

# ajv-formats `date-time` in its full mode (the contract's validator): a date, `t` or a space, a time with a zone.
_DT_SEPARATOR = re.compile("[tT%s]" % _JS_SPACE)
_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_TIME = re.compile(r"([0-9]{2}):([0-9]{2}):([0-9]{2}(?:\.[0-9]+)?)(z|([+-])([0-9]{2})(?::?([0-9]{2}))?)?", re.IGNORECASE | re.ASCII)
_DAYS = (0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

# The contract's KEY_SHAPE (src/connections.ts): a provider key where it starts a word, case-sensitive prefixes, the
# `sk-` rules and a Telegram bot token.
_KEY_SHAPE = re.compile(
    r"(?:^|[^A-Za-z0-9])(?:sk-(?=[A-Za-z0-9_-]*[0-9])(?:(?=[A-Za-z0-9_-]*[A-Z])[A-Za-z0-9_-]{16,}|[A-Za-z0-9_-]{32,})"
    r"|gh[pousr]_[A-Za-z0-9]{20,}|xox[abposr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|glpat-[A-Za-z0-9_-]{20,}"
    r"|(?:bot)?[0-9]{6,12}:(?=[A-Za-z0-9_-]*[A-Z])(?=[A-Za-z0-9_-]*[a-z])[A-Za-z0-9_-]{34,35}(?![A-Za-z0-9_-]))")
_URL_SCHEME = re.compile(r"[a-z][a-z0-9+.-]*://", re.IGNORECASE | re.ASCII)
_CLOSING = ")]}>\"'.,;:!?"
_TRIED_BACK = 1


def _date(value: str) -> bool:
    match = _DATE.fullmatch(value)
    if not match:
        return False
    year, month, day = (int(g) for g in match.groups())
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    return 1 <= month <= 12 and 1 <= day <= (29 if month == 2 and leap else _DAYS[month])


def _time(value: str) -> bool:
    match = _TIME.fullmatch(value)
    if not match:
        return False
    hour, minute, second = int(match.group(1)), int(match.group(2)), float(match.group(3))
    zone, sign = match.group(4), -1 if match.group(5) == "-" else 1
    zone_h, zone_m = int(match.group(6) or 0), int(match.group(7) or 0)
    if zone_h > 23 or zone_m > 59 or not zone:
        return False
    if hour <= 23 and minute <= 59 and second < 60:
        return True
    utc_min = minute - zone_m * sign  # a leap second, at 23:59 UTC only
    utc_hour = hour - zone_h * sign - (1 if utc_min < 0 else 0)
    return utc_hour in (23, -1) and utc_min in (59, -1) and second < 61


def date_time(value: str) -> bool:
    """The `date-time` format as the contract's validator (ajv-formats, full mode) reads it."""
    parts = _DT_SEPARATOR.split(value)
    return len(parts) == 2 and _date(parts[0]) and _time(parts[1])


def _length(value: str) -> int:
    return len(value)  # code points, as ajv counts them


def _shape_problems(value: Any) -> List[str]:
    """service-connections-extension.schema.json, read as the contract's validator reads it."""
    if not isinstance(value, dict):
        return ["/ type: must be object"]
    # A member's name is never echoed: a secret-shaped name would reach the error text and a probe's evidence.
    problems = ["/ additionalProperties: a member other than connections" for key in value if key != "connections"]
    if "connections" not in value:
        return problems + ["/ required: connections"]
    connections = value["connections"]
    if not isinstance(connections, list):
        return problems + ["/connections type: must be array"]
    if len(connections) > MAX_CONNECTIONS:
        problems.append("/connections maxItems: at most %d" % MAX_CONNECTIONS)
    for index, item in enumerate(connections):
        at = "/connections/%d" % index
        if not isinstance(item, dict):
            problems.append("%s type: must be object" % at)
            continue
        problems += ["%s required: %s" % (at, key) for key in ("id", "kind", "target", "state") if key not in item]
        problems += ["%s additionalProperties: a member the schema does not name" % at for key in item if key not in _MEMBERS]
        for key in _STRING_MEMBERS + ("lastAt",):
            if key in item and not isinstance(item[key], str):
                problems.append("%s/%s type: must be string" % (at, key))
        text = {k: v for k, v in item.items() if isinstance(v, str)}
        if "id" in text and not _ID.fullmatch(text["id"]):
            problems.append("%s/id pattern" % at)
        if "kind" in item and item["kind"] not in KINDS:
            problems.append("%s/kind enum" % at)
        if "state" in item and item["state"] not in STATES:
            problems.append("%s/state enum" % at)
        if "target" in text and not (1 <= _length(text["target"]) <= 200 and _TARGET.fullmatch(text["target"])):
            problems.append("%s/target length or pattern" % at)
        if "capability" in text and not _CAPABILITY.fullmatch(text["capability"]):
            problems.append("%s/capability pattern" % at)
        for key in ("label", "purpose", "reason"):
            if key in text and not (1 <= _length(text[key]) <= 300 and _LINE.fullmatch(text[key])):
                problems.append("%s/%s length or pattern" % (at, key))
        if "lastAt" in text and not date_time(text["lastAt"]):
            problems.append("%s/lastAt format: date-time" % at)
        if "kind" in item:
            if item["kind"] != "service" and "capability" in item:
                problems.append("%s/capability: only a service connection names a capability" % at)
            if item["kind"] == "service" and "target" in text and not _SERVICE_TARGET.fullmatch(text["target"]):
                problems.append("%s/target pattern: a service target is an id.instance key or a product id" % at)
    return problems


def _urls_in(value: str) -> List[str]:
    """The URLs a member may hold, from every scheme in each whitespace-delimited piece, without the closing brackets,
    quotes and punctuation that end a sentence, and with _TRIED_BACK of them put back (`]` closes an IPv6 host)."""
    urls: List[str] = []
    for piece in _SPACES.split(value):
        for match in _URL_SCHEME.finditer(piece):
            url = piece[match.start():]
            end = len(url)
            while end > 0 and url[end - 1] in _CLOSING:
                end -= 1
            back = 0
            while back <= _TRIED_BACK and end + back <= len(url):
                urls.append(url[:end + back])
                back += 1
    return urls


def _long_run(value: str) -> bool:
    """A long secret-shaped run in a piece read whole; in a piece that holds a URL, the text before its first scheme's
    `://` (the URL itself is read by secret_url)."""
    for piece in _SPACES.split(value):
        found = _URL_SCHEME.search(piece)
        cut = piece.find("://", found.start()) if found else -1
        if _long_secret(piece if cut < 0 else piece[:cut]):
            return True
    return False


# The shared detector (DEC-0044) as the contract's ECMAScript reads it: fabric_secrets reads so since 0.56.0 (FAA-136;
# before, this module kept its own copy, blind reading of 0.44.0, finding 1).
_credential_name, _secret_value, _secret_argument = credential_name, secret_value, secret_argument


_SPECIAL = ("http", "https", "ws", "wss", "ftp", "file")
_FORBIDDEN_HOST = set("\x00\t\n\r #/:<>?@[\\]^|")
_FORBIDDEN_DOMAIN = _FORBIDDEN_HOST | set(chr(c) for c in range(0x20)) | {"%", "\x7f"}


# FAA-98: UTS46 narrowed, not ported. A non-ASCII host is refused only where every Node from 20 to 26 refuses it, so
# the doubt stays on the closed side (its URL's credentials are read). The two tables are measured by
# test/fixtures/idna/make_idna_tables.mjs (idna-tables.json, held equal by test_the_idna_tables_are_the_measured_ones):
# code points refused in every context, and code points removed between letters. The contextual rules read Unicode 3.2
# classes (`unicodedata.ucd_3_2_0`) and skip what that Unicode does not know, since Node's own UTS46 data lags its
# Unicode: an Arabic letter of Unicode 14 is no right-to-left letter to it.
_IDNA_DISALLOWED = (
    (0x80, 0xa0), (0xa8, 0xa8), (0xaf, 0xaf), (0xb4, 0xb4), (0xb8, 0xb8), (0x2d8, 0x2dd), (0x37a, 0x37a),
    (0x384, 0x385), (0x600, 0x605), (0x61c, 0x61c), (0x6dd, 0x6dd), (0x70f, 0x70f), (0x890, 0x891), (0x8e2, 0x8e2),
    (0x1680, 0x1680), (0x1fbd, 0x1fbd), (0x1fbf, 0x1fc1), (0x1fcd, 0x1fcf), (0x1fdd, 0x1fdf), (0x1fed, 0x1fee),
    (0x1ffd, 0x1ffe), (0x2000, 0x200a), (0x200e, 0x200f), (0x2017, 0x2017), (0x2024, 0x2026), (0x2028, 0x202f),
    (0x203e, 0x203e), (0x2047, 0x2049), (0x205f, 0x205f), (0x2066, 0x2069), (0x2100, 0x2101), (0x2105, 0x2106),
    (0x2488, 0x249b), (0x2a74, 0x2a74), (0x2ff0, 0x3000), (0x309b, 0x309c), (0x31ef, 0x31ef), (0x33c2, 0x33c2),
    (0x33c7, 0x33c7), (0x33d8, 0x33d8), (0xe000, 0xf8ff), (0xfc5e, 0xfc63), (0xfdfa, 0xfdfb), (0xfe12, 0xfe13),
    (0xfe16, 0xfe16), (0xfe19, 0xfe19), (0xfe30, 0xfe30), (0xfe47, 0xfe4c), (0xfe52, 0xfe52), (0xfe55, 0xfe56),
    (0xfe5f, 0xfe5f), (0xfe64, 0xfe65), (0xfe68, 0xfe68), (0xfe6a, 0xfe6b), (0xfe70, 0xfe70), (0xfe72, 0xfe72),
    (0xfe74, 0xfe74), (0xfe76, 0xfe76), (0xfe78, 0xfe78), (0xfe7a, 0xfe7a), (0xfe7c, 0xfe7c), (0xfe7e, 0xfe7e),
    (0xff03, 0xff03), (0xff05, 0xff05), (0xff0f, 0xff0f), (0xff1a, 0xff1a), (0xff1c, 0xff1c), (0xff1e, 0xff20),
    (0xff3b, 0xff3e), (0xff5c, 0xff5c), (0xffe3, 0xffe3), (0xfff9, 0xfffd), (0x110bd, 0x110bd), (0x110cd, 0x110cd),
    (0x13430, 0x1343f), (0x1f100, 0x1f100), (0xe0001, 0xe0001), (0xe0020, 0xe007f), (0xf0000, 0xffffd),
    (0x100000, 0x10fffd),
)
_IDNA_IGNORED = (
    (0xad, 0xad), (0x34f, 0x34f), (0x180b, 0x180d), (0x180f, 0x180f), (0x200b, 0x200b), (0x2060, 0x2060),
    (0x2064, 0x2064), (0xfe00, 0xfe0f), (0xfeff, 0xfeff), (0x1bca0, 0x1bca3), (0xe0100, 0xe01ef),
)
_IDNA_DOTS = re.compile("[.\u3002\uff0e\uff61]")
_U32 = unicodedata.ucd_3_2_0
_RTL_OK = {"R", "AL", "AN", "EN", "ES", "CS", "ET", "ON", "BN", "NSM"}
_JOINERS = "\u200c\u200d"


def _in_ranges(ranges: Sequence[tuple], cp: int) -> bool:
    i = bisect.bisect_right(ranges, (cp, 0x10ffff)) - 1
    return i >= 0 and ranges[i][0] <= cp <= ranges[i][1]


def _known(c: str) -> bool:
    return _U32.category(c) != "Cn" and unicodedata.category(c) != "Cn"


def _joiner_refused(label: str, i: int) -> bool:
    """CheckJoiners as Node 20 to 26 all read it: they find a joining context, or a virama, anywhere in the label
    (`\u0628a\u200c\u0627` and `\u0628\u200c\u0627\u200d` parse), so only a joiner with nothing but ASCII beside it
    in its label has none for certain."""
    return all(c.isascii() for j, c in enumerate(label) if j != i)


def _bidi_refused(label: str) -> bool:
    """RFC 5893 as Node 20 to 26 all read it: only a label holding R, AL or AN is judged, and its first code point is
    not (Node 26 alone refuses a label opening with a digit or a hyphen)."""
    if not label or not all(_known(c) for c in label) or any(c in _JOINERS for c in label):
        return False  # Node 20 to 26 pass a label holding a joiner over (`\u05d0a\u094d\u200d` parses)
    k = [_U32.bidirectional(c) for c in label]
    if not any(x in ("R", "AL", "AN") for x in k):
        return False
    body = list(k)
    while body and body[-1] == "NSM":
        body.pop()
    if not body or body[-1] not in ("R", "AL", "EN", "AN"):
        return True
    return k[0] in ("R", "AL") and (any(x not in _RTL_OK for x in k) or ("EN" in k and "AN" in k))


def _idna_host(host: str) -> Optional[str]:
    """None where WHATWG's domain-to-ASCII refuses a non-ASCII host for certain; else the host as UTS46 maps it, read
    as NFKC with case folding (exact enough for the ASCII rules that follow, which read digits and dots)."""
    if any(_in_ranges(_IDNA_DISALLOWED, ord(c)) for c in host):
        return None
    kept = "".join(c for c in host if not _in_ranges(_IDNA_IGNORED, ord(c)))
    if kept == "":
        return None  # nothing left: an empty host
    if not all(_known(c) for c in kept):
        return host  # a code point this Python's Unicode does not know: the contextual rules are not read
    mapped = unicodedata.normalize("NFC", unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", kept).casefold()))
    for label in _IDNA_DOTS.split(mapped):
        first = label[:1]
        if first and first not in "\u17b4\u17b5" and _U32.category(first)[0] == "M" and unicodedata.category(first)[0] == "M":
            return None  # a label opening with a mark (U+17B4 and U+17B5 are ignored by the newer Nodes)
        if any(c in _JOINERS and _joiner_refused(label, i) for i, c in enumerate(label)):
            return None
        if _bidi_refused(label):
            return None
    return _IDNA_DOTS.sub(".", mapped)


def _ipv4_number(part: str) -> Optional[int]:
    if part == "":
        return None  # an empty part fails WHATWG's IPv4 parser (`1..2`); `0x` alone is 0
    base = 10
    if part[:2].lower() == "0x":
        part, base = part[2:], 16
    elif len(part) > 1 and part[0] == "0":
        part, base = part[1:], 8
    if part == "":
        return 0
    digits = {10: "0123456789", 16: "0123456789abcdefABCDEF", 8: "01234567"}[base]
    return int(part, base) if all(c in digits for c in part) else None


def _domain_ok(host: str) -> bool:
    """The WHATWG host parser on a special scheme's host, enough to know when `new URL` refuses it."""
    if host.startswith("["):
        return host.endswith("]") and _ipv6_ok(host[1:-1])
    if re.search(r"%(?![0-9A-Fa-f]{2})", host) is None:
        try:
            host = urllib.parse.unquote_to_bytes(host).decode("utf-8")
        except UnicodeDecodeError:
            return False
    if any(c in _FORBIDDEN_DOMAIN for c in host):
        return False
    # A non-ASCII host goes through UTS46 in WHATWG; this module reads it narrowly (_idna_host, FAA-98). When unsure,
    # the host is taken as valid, so its URL's credentials are read: the doubt then hides a list rather than publish one
    # (round-2 reading). A host UTS46 maps to ASCII is read by the ASCII rules below (`１２７.０.０.１` is an address).
    if any(ord(c) > 0x7f for c in host):
        mapped = _idna_host(host)
        if mapped is None:
            return False
        if not mapped.isascii() or any(c in _FORBIDDEN_DOMAIN for c in mapped):
            return True
        host = mapped
    labels = host.split(".")
    if labels and labels[-1] == "" and len(labels) > 1:
        labels = labels[:-1]
    last = labels[-1] if labels else ""
    if not (last and (last.isdigit() and last.isascii() or re.fullmatch(r"0[xX][0-9A-Fa-f]*", last))):
        return host != ""
    numbers = [_ipv4_number(label) for label in labels]
    if len(numbers) > 4 or any(n is None for n in numbers):
        return False
    return all(n <= 255 for n in numbers[:-1]) and numbers[-1] < 256 ** (5 - len(numbers))


def _ipv6_ok(text: str) -> bool:
    if "%" in text:
        return False  # a zone id: `ipaddress` takes one, WHATWG does not
    try:
        ipaddress.IPv6Address(text)
        return True
    except ValueError:
        return False


_SURROGATE = re.compile("[\ud800-\udfff]")
_QUERY_ENCODE = set(chr(c) for c in range(0x21)) | set('"#<>')
_FRAGMENT_ENCODE = set(chr(c) for c in range(0x21)) | set('"<>`')


def _serialize(text: str, encode: set) -> str:
    """A query or fragment as WHATWG serializes it (`url.search`, `url.hash`): the set's ASCII and every code point
    above U+007E as UTF-8 percent-escapes in upper-case hex; `%` stays as written (round-3 reading of 0.44.0)."""
    out = []
    for c in text:
        if c in encode or ord(c) > 0x7e:
            out.append("".join("%%%02X" % b for b in c.encode("utf-8")))
        else:
            out.append(c)
    return "".join(out)


def _whatwg_parts(value: str) -> Optional[Dict[str, str]]:
    """The password, query and fragment `new URL(value)` gives, or None where it throws. A subset of the WHATWG URL
    parser: an absolute URL with `//` authority, as the members that reach it are (_urls_in starts each at a scheme)."""
    # A JavaScript string becomes a USV string first: an unpaired surrogate is U+FFFD (json.loads keeps one).
    value = _SURROGATE.sub("\ufffd", value)
    value = re.sub(r"[\t\n\r]", "", value.strip("".join(chr(c) for c in range(0x21))))
    match = re.match(r"([A-Za-z][A-Za-z0-9+.-]*):", value)
    if not match:
        return None
    scheme, rest = match.group(1).lower(), value[match.end():]
    special = scheme in _SPECIAL
    if special:
        cut = min([i for i in (rest.find("?"), rest.find("#")) if i >= 0] or [len(rest)])
        rest = rest[:cut].replace("\\", "/") + rest[cut:]  # a backslash is a slash before the query only
    if not rest.startswith("//"):
        return {"password": "", "query": "", "fragment": ""} if not special else None
    rest = rest[2:].lstrip("/") if special and scheme != "file" else rest[2:]
    end = len(rest)
    for stop in "/?#":
        at = rest.find(stop)
        if at >= 0:
            end = min(end, at)
    authority, tail = rest[:end], rest[end:]
    fragment = _serialize(tail.split("#", 1)[1], _FRAGMENT_ENCODE) if "#" in tail else ""
    before = tail.split("#", 1)[0]
    query = _serialize(before.split("?", 1)[1], _QUERY_ENCODE | ({"'"} if special else set())) if "?" in before else ""
    if scheme == "file":
        # A drive letter (`C:`, `c|`) is an empty host and the start of the path.
        if authority == "" or re.fullmatch(r"[A-Za-z][:|]", authority) or _domain_ok(authority):
            return {"password": "", "query": query, "fragment": fragment}
        return None
    userinfo, _, hostport = authority.rpartition("@")
    password = userinfo.split(":", 1)[1] if ":" in userinfo else ""
    if hostport.startswith("["):
        close = hostport.find("]")
        if close < 0:
            return None
        host, after = hostport[:close + 1], hostport[close + 1:]
        if after and not after.startswith(":"):
            return None
        port = after[1:]
    else:
        host, _, port = hostport.partition(":")
    if port and not (port.isascii() and port.isdigit() and int(port) <= 65535):
        return None
    if special:
        if host == "" or not _domain_ok(host):
            return None
    elif host.startswith("["):
        if not _ipv6_ok(host[1:-1]):
            return None
    elif any(c in _FORBIDDEN_HOST for c in host):
        return None
    elif host == "" and ("@" in authority or port):
        return None
    return {"password": password, "query": query, "fragment": fragment}


def _raw_values(query: str) -> Dict[str, List[str]]:
    """fabric_secrets.raw_values with the name read as URLSearchParams reads it: one leading `?` of the raw piece is
    dropped before decoding (`??token` names `?token`, `%3Ftoken` names `?token`; round-3 reading). raw_values drops
    that one `?` itself since 0.56.0, so the piece's name is handed over as it stands (seam r8)."""
    values: Dict[str, List[str]] = {}
    for piece in query.split("&"):
        if piece == "":
            continue
        at = piece.find("=")
        raw_name = piece if at < 0 else piece[:at]
        merged = raw_values(raw_name)
        name = next(iter(merged), "")
        values.setdefault(name, []).extend(raw_values("x" + piece[at:])["x"] if at >= 0 else [""])
    return values


def _secret_url(value: str) -> bool:
    """The contract's secretUrl (DEC-0044): what _secret_argument finds, a password, or a query or fragment value
    named or shaped like a credential, in a URL WHATWG parses; one it refuses is read as an argument only."""
    if _secret_argument(value):
        return True
    parts = _whatwg_parts(value)
    if parts is None:
        return False
    if parts["password"]:
        return True
    return any((raw != "" and _credential_name(name)) or _secret_value(raw)
               for part in (parts["query"], parts["fragment"]) for name, raws in _raw_values(part).items() for raw in raws)


def _credential(value: str, runs: bool) -> bool:
    return bool(JWT_SHAPE.search(value) or _KEY_SHAPE.search(value) or _BEARER.search(value)
                or (runs and _long_run(value)) or any(_secret_url(url) for url in _urls_in(value)))


def _beyond_shape(connections: Sequence[Dict[str, Any]]) -> List[str]:
    """What the schema cannot state: an id named twice, a credential in any string member."""
    problems: List[str] = []
    seen = set()
    for index, connection in enumerate(connections):
        if connection["id"] in seen:
            problems.append("/connections/%d/id duplicate: it is named twice" % index)
        seen.add(connection["id"])
        for member in _STRING_MEMBERS:
            value = connection.get(member)
            runs = member not in ("id", "capability") and not (member == "target" and connection.get("kind") == "model")
            if isinstance(value, str) and _credential(value, runs):
                problems.append("/connections/%d/%s credential: a connection never carries a credential" % (index, member))
    return problems


def connections_view(well_known: Any) -> Dict[str, Any]:
    """A host's reading of a well-known document's connections (the contract's connectionsView): never raises. Without
    the key nothing is declared; an invalid value (the schema, a repeated id, a credential) is not declared and is
    `reported`; a valid list comes back with `failing` set on each connection a `degraded[].source` names."""
    none: Dict[str, Any] = {"declared": False, "reported": False, "connections": [], "errors": []}
    extensions = well_known.get("extensions") if isinstance(well_known, dict) else None
    if not isinstance(extensions, dict) or CONNECTIONS_EXTENSION_KEY not in extensions:
        return none
    value = extensions[CONNECTIONS_EXTENSION_KEY]
    errors = _shape_problems(value)
    if not errors:
        errors = _beyond_shape(value["connections"])
    if errors:
        return dict(none, reported=True, errors=errors)
    degraded = well_known.get("degraded")
    failing = {entry["source"] for entry in (degraded if isinstance(degraded, list) else [])
               if isinstance(entry, dict) and isinstance(entry.get("source"), str)}
    return {"declared": True, "reported": False, "errors": [],
            "connections": [dict(c, failing=c["id"] in failing) for c in value["connections"]]}


def connections_rules(well_known: Any) -> List[Dict[str, str]]:
    """FAC-SEM-127: the connections a well-known document declares are valid, each id once, no credential."""
    view = connections_view(well_known)
    at = "/extensions/" + CONNECTIONS_EXTENSION_KEY.replace("~", "~0").replace("/", "~1")
    return [{"code": "FAC-SEM-127", "instancePath": at,
             "message": "the connections declaration is invalid (%s); a host treats it as not declared and reports it "
                        "(DEC-0096)" % error} for error in view["errors"]]


def connections_extension(declared: Iterable[Mapping[str, Any]], degraded: Sequence[Mapping[str, Any]] = (),
                          states: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """The `extensions` entry a service declares (DEC-0096): what it uses, each connection's `state` from the service's
    own checks (`states`, by id), else `degraded` when a `degraded[].source` names it, else `unknown`. A declared
    `state` is kept. Raises ServiceError on a declaration a host would hide (the schema, a repeated id, a credential):
    a service never publishes one that reads as "declared nothing"."""
    if declared is None or isinstance(declared, (str, bytes, Mapping)) or not isinstance(declared, Iterable):
        raise ServiceError("Connections declaration: declared is a list of connections.")
    if degraded is None:
        degraded = ()
    if states is None:
        states = {}
    if isinstance(degraded, (str, bytes, Mapping)) or not isinstance(degraded, Iterable) or not isinstance(states, Mapping):
        raise ServiceError("Connections declaration: degraded is a list of entries and states a mapping by id.")
    failing = {entry.get("source") for entry in degraded if isinstance(entry, Mapping) and isinstance(entry.get("source"), str)}
    connections: List[Any] = []
    for item in declared:
        if not isinstance(item, Mapping):
            connections.append(item)  # the shape check names it and the declaration is refused
            continue
        connection = dict(item)
        if "state" not in connection:
            ident = connection.get("id") if isinstance(connection.get("id"), str) else None
            if ident is not None and ident in states:
                connection["state"] = states[ident]  # an invalid check value is refused by the shape check
            else:
                connection["state"] = "degraded" if ident in failing else "unknown"
        connections.append(connection)
    value = {"connections": connections}
    view = connections_view({"extensions": {CONNECTIONS_EXTENSION_KEY: value}})
    if view["reported"]:
        raise ServiceError("Connections declaration: %s." % "; ".join(view["errors"]))
    return {CONNECTIONS_EXTENSION_KEY: value}
