"""What an agent uses: `fabric-connections/0.1`, the extension keyed extensions/connections/0.1 (DEC-0096, FAC-SEM-127).
`connections_view` reads a well-known document as the contract's `connectionsView` does (it never raises);
`connections_extension` builds the `extensions` entry a service declares, `state` from its own checks and its
`degraded[]`. Part of the service kit (FAA-62, layer L3). Standard library only."""
from __future__ import annotations

import ipaddress
import re
import urllib.parse
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))

from fabric_base import ServiceError  # noqa: E402
from fabric_secrets import CREDENTIAL_PAIRS, CREDENTIAL_WORDS, JWT_SHAPE, _long_secret, raw_values  # noqa: E402

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


# The shared detector (DEC-0044) as the contract's ECMAScript reads it: ASCII case folding, ECMAScript's \s and `.`,
# an ASCII word boundary. The kit's fabric_secrets keeps Python's semantics for its other callers (LC-21); FAC-SEM-127
# is held to the reference, so this module reads with the reference's (blind reading of 0.44.0, finding 1).
_NOT_LINE_END = "[^\n\r\u2028\u2029]"
_SECRET_VALUE = re.compile(r"(^bearer[%s]%s+|sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abposr]-[A-Za-z0-9-]{10,}"
                           r"|AKIA[0-9A-Z]{16}|glpat-[A-Za-z0-9_-]{20,})" % (_JS_SPACE, _NOT_LINE_END), re.IGNORECASE | re.ASCII)
_BEARER = re.compile(r"(?<![A-Za-z0-9_])bearer[%s]+(?=[A-Za-z0-9._~+/-]*[0-9])[A-Za-z0-9._~+/-]{12,}=*" % _JS_SPACE,
                     re.IGNORECASE | re.ASCII)
_PATH_LIKE = re.compile(r"(?:[/~.]|[A-Za-z]:[\\/]|[a-z][a-z0-9+.-]*://)", re.IGNORECASE | re.ASCII)
_ARGUMENT_SPLIT = re.compile("[%s=]" % _JS_SPACE)


def _credential_name(name: str) -> bool:
    """fabric_secrets.credential_name with ECMAScript's whitespace in the word split (U+FEFF splits a name there)."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    split = [w.lower() for w in re.split("[%s._-]+" % _JS_SPACE, spaced) if w]
    words = split + [w[:-1] for w in split if len(w) > 2 and w.endswith("s")]
    if any(w in CREDENTIAL_WORDS for w in words) or (len(split) == 1 and any(w in CREDENTIAL_PAIRS for w in words)):
        return True
    return any(word in words and any(p in words for p in partners) for word, partners in CREDENTIAL_PAIRS.items())


def _secret_value(value: str) -> bool:
    return bool(JWT_SHAPE.search(value) or _SECRET_VALUE.search(value) or _long_secret(value))


def _path_like(piece: str) -> bool:
    return bool(_PATH_LIKE.match(piece)) or (
        bool(re.search(r"[\\/]", piece))
        and (bool(re.search(r"\.[A-Za-z0-9]{1,8}\Z", piece))
             or any(re.fullmatch(r"[a-z][a-z0-9_-]{2,}", segment) for segment in re.split(r"[\\/]", piece))))


def _secret_argument(value: str) -> bool:
    if JWT_SHAPE.search(value) or _SECRET_VALUE.search(value) or _BEARER.search(value):
        return True
    return any(any(_long_secret(part) for part in re.split(r"[\\/]", piece)) if _path_like(piece) else _long_secret(piece)
               for piece in _ARGUMENT_SPLIT.split(value))


_SPECIAL = ("http", "https", "ws", "wss", "ftp", "file")
_FORBIDDEN_HOST = set("\x00\t\n\r #/:<>?@[\\]^|")
_FORBIDDEN_DOMAIN = _FORBIDDEN_HOST | set(chr(c) for c in range(0x20)) | {"%", "\x7f"}


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
    # A non-ASCII host goes through UTS46 in WHATWG; this module does not port it. When unsure, the host is taken as
    # valid, so its URL's credentials are read: the doubt then hides a list rather than publish one (round-2 reading).
    if any(ord(c) > 0x7f for c in host):
        return True
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


def _whatwg_parts(value: str) -> Optional[Dict[str, str]]:
    """The password, query and fragment `new URL(value)` gives, or None where it throws. A subset of the WHATWG URL
    parser: an absolute URL with `//` authority, as the members that reach it are (_urls_in starts each at a scheme)."""
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
    fragment = tail.split("#", 1)[1] if "#" in tail else ""
    before = tail.split("#", 1)[0]
    query = before.split("?", 1)[1] if "?" in before else ""
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
               for part in (parts["query"], parts["fragment"]) for name, raws in raw_values(part).items() for raw in raws)


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
