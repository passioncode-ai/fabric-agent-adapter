"""The probe's channel-agent rule (FAA-197): an agent that answers people on a channel declares
extensions/channel-agent/0.1 (Fabric Agent Contract DEC-0150) under provider.extensions of its manifest, or, for a
service with no manifest, under extensions of its well-known answer (CA-1). A port of the contract's
`src/channel-agent.ts` at the pin: channelAgentRules (FAC-SEM-162 to 165) and channelAgentView, held to the contract's
own vectors (test/fixtures/contract/channel-agent-vectors.json); the schema half is check_service_channel_agent_schema.py.

Strings are read as ECMAScript holds them where the contract counts or indexes UTF-16 units (an astral character is
two), and as code points where its regular expressions carry the `u` flag. No finding's message carries a declared
value: the instancePath places it (CA-5). Not a kit module (the probe has no Node twin). Standard library only."""
from __future__ import annotations

import ipaddress
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fabric_jsvalue import indexed_objects, js_keys  # noqa: E402
from fabric_secrets import JS_SPACE, JWT_SHAPE, SECRET_VALUE, _url_parts, raw_values, secret_argument, secret_url, secret_value  # noqa: E402
import check_service_channel_agent_schema as cas  # noqa: E402

KEY = "https://fabric.passioncode.ai/agent-contract/extensions/channel-agent/0.1"
#: Any version of the key: one other than 0.1 is not read until a decision moves it (CA-7).
KEY_PREFIX = "https://fabric.passioncode.ai/agent-contract/extensions/channel-agent/"
KEY_TOKEN = KEY.replace("~", "~0").replace("/", "~1")
CHANNEL_AGENT_PATHS = {"manifest": "/provider/extensions/" + KEY_TOKEN, "well-known": "/extensions/" + KEY_TOKEN}
TOKEN_SLOT = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}/[a-z][a-z0-9-]{0,31}/[A-Z][A-Z0-9_]{0,63}\Z")
NAME_CHARACTERS = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
SECRET_FINDINGS = 64
PATH_DEPTH = 64
DETECTOR_CODE_POINTS = 4097
LONGEST_STRING = cas.LONGEST_STRING
MESSAGE_ERRORS = 10
SECRET_BUDGET = 1_000_000
VISIT_COST = 16
PIECE_COST = 8 * VISIT_COST
ARG_PIECE_COST = 4
KEY_REREAD = 255
LONG_RUN_FLOOR = 40
SK_FLOOR = 16
PREFIX_FLOORS = ((re.compile(r"gh[pousr]_", re.I | re.A), 20), (re.compile(r"xox[abposr]-", re.I | re.A), 10),
                 (re.compile(r"akia", re.I | re.A), 16), (re.compile(r"glpat-", re.I | re.A), 20))
EM_DASH = "\u2014"
#: The 2 MiB cap Fabric Dashboards' probe puts on a well-known answer (until the contract's CT-223), and "near" it.
WELL_KNOWN_CAP = 2 * 1024 * 1024
WELL_KNOWN_NEAR = WELL_KNOWN_CAP * 3 // 4

_SK = re.compile(r"sk-", re.I | re.A)
_ESCAPE_BEFORE = re.compile(r"(?:%25[0-9A-Fa-f]{2}|%[0-9A-Fa-f]{2}|\\x[0-9A-Fa-f]{2}|\\u[0-9A-Fa-f]{4}|\\[0-7]{2,3}|\\[^\n\r\u2028\u2029])\Z")
_ESC_BEFORE = re.compile(r"(?:\x1b|\\x1[bB]|\\0?33|\\u001[bB]|\\e)\Z")
_SEPARATOR = re.compile("[%s=/\\\\]" % JS_SPACE)
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_HIGH_ESCAPE = re.compile(r"%[89A-Fa-f][0-9A-Fa-f]")
_RELATIVE_REF = re.compile(r"(?![/~])(?![A-Za-z][A-Za-z0-9+.-]*:)(?!(?:[^/]*/)*\.\.(?:/|\Z))[A-Za-z0-9._:/-]+\Z")
_OPAQUE_ID = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
_ASTRAL = re.compile("[\U00010000-\U0010ffff]")
_ID_MEMBERS = frozenset(("id", "code", "lead_agent", "owner", "decision", "answered_signal", "target", "spend_record", "project", "side"))
# Unicode's Default_Ignorable_Code_Point (DerivedCoreProperties), which Python's unicodedata does not carry.
_IGNORABLE = ((0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C), (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180F),
              (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F), (0x3164, 0x3164), (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF),
              (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3), (0x1D173, 0x1D17A), (0xE0000, 0xE0FFF))
_FILLERS = frozenset("\u115f\u1160\u3164\uffa0\u2800\ufffc")


def utf16(text: str) -> str:
    """The text as ECMAScript's UTF-16 units, one Python character each (an astral character is a surrogate pair)."""
    if not _ASTRAL.search(text):
        return text
    return "".join(c if ord(c) < 0x10000 else chr(0xD800 + ((ord(c) - 0x10000) >> 10)) + chr(0xDC00 + ((ord(c) - 0x10000) & 0x3FF))
                   for c in text)


def _blank_char(char: str) -> bool:
    code = ord(char)
    return (char in JS_SPACE or char in _FILLERS or unicodedata.category(char) in ("Cf", "Cc", "Zs", "Zl", "Zp")
            or any(low <= code <= high for low, high in _IGNORABLE))


def blank(text: str) -> bool:
    """Nothing left after white space, \\p{Cf}, \\p{Cc}, \\p{Z}, \\p{Default_Ignorable_Code_Point} and the fillers."""
    return all(_blank_char(char) for char in text)


class _Frame:
    __slots__ = ("container", "keys", "next", "at", "depth", "name", "parent", "collapsed", "role")

    def __init__(self, container: Any, at: str, depth: int, name: Optional[str], parent: Optional[str], collapsed: bool, role: Optional[str]):
        self.container = container
        self.keys = None if isinstance(container, list) else js_keys(container)
        self.next = 0
        self.at, self.depth, self.name, self.parent, self.collapsed, self.role = at, depth, name, parent, collapsed, role


class _Spot:
    __slots__ = ("frame", "key", "is_name")

    def __init__(self, frame: Optional[_Frame], key: str, is_name: bool):
        self.frame, self.key, self.is_name = frame, key, is_name


_ROLES = {"root": {"projects": "projects"}, "project": {"evals": "evals", "tickets": "tickets", "handoff_queues": "queues", "channels": "channels"},
          "channel": {"texts": "texts"}}


def _role_of(holder: Optional[str], key: str, index: bool) -> Optional[str]:
    if holder == "texts":
        return "texts"
    if index:
        return {"projects": "project", "queues": "queue", "channels": "channel"}.get(holder or "")
    return _ROLES.get(holder or "", {}).get(key)


def walk(value: Any, root: str, token_of: Callable[[_Frame, str, bool], Optional[str]], visit: Callable[[str, _Spot, Callable[[_Spot], str]], None],
         stop: Callable[[], bool] = lambda: False, on_enter: Callable[[], None] = lambda: None) -> None:
    """Every member name and string value under `value`, with an explicit stack of frames (the contract's `walk`)."""
    def token(frame: _Frame, key: str) -> Optional[str]:
        return None if frame.collapsed or frame.depth >= PATH_DEPTH else token_of(frame, key, frame.keys is None)

    def place(spot: _Spot) -> str:
        frame = spot.frame
        if frame is None:
            return root
        written = None if spot.is_name else token(frame, spot.key)
        return frame.at if written is None else "%s/%s" % (frame.at, written)

    if isinstance(value, str) and not stop():
        visit(value, _Spot(None, "", False), place)
    if not isinstance(value, (list, dict)):
        if not isinstance(value, str):
            on_enter()
        return
    on_enter()
    stack = [_Frame(value, root, 0, None, None, False, "root")]
    while stack and not stop():
        frame = stack[-1]
        length = len(frame.container) if frame.keys is None else len(frame.keys)
        if frame.next >= length:
            stack.pop()
            continue
        i = frame.next
        frame.next += 1
        index = frame.keys is None
        key = str(i) if index else frame.keys[i]
        child = frame.container[i] if index else frame.container[key]
        if not index:
            visit(key, _Spot(frame, key, True), place)
        if isinstance(child, str):
            visit(child, _Spot(frame, key, False), place)
        elif isinstance(child, (list, dict)):
            on_enter()
            if len(child) == 0:
                continue
            written = token(frame, key)
            stack.append(_Frame(child, frame.at if written is None else "%s/%s" % (frame.at, written), frame.depth + 1, key, frame.name,
                                written is None, _role_of(frame.role, key, index)))
        else:
            on_enter()


def oversize(value: Any) -> List[str]:
    """What is refused before the schema runs (CA-2): widths, and a string or name over LONGEST_STRING code points."""
    names = cas.schema_names()
    long: Dict[str, None] = {}

    def visit(text: str, spot: _Spot, place: Callable[[_Spot], str]) -> None:
        if len(text) > LONGEST_STRING:
            long["maxLength at %s (at most %d code points)" % (place(spot) or "/", LONGEST_STRING)] = None
    walk(value, "", lambda frame, key, index: cas.placed_token(frame.name, frame.parent, key, index, names, cas.is_none(frame.container)), visit)
    return cas.widths(value) + list(long)


def _extensions_at(doc: Dict[str, Any], site: str) -> Optional[Dict[str, Any]]:
    holder = doc.get("provider") if site == "manifest" else doc
    return holder["extensions"] if isinstance(holder, dict) and isinstance(holder.get("extensions"), dict) else None


def schema_view(doc: Any, site: str) -> Dict[str, Any]:
    """The schema's verdict on the declaration at one site (CA-1, CA-2), before the reader's rules."""
    extensions = _extensions_at(doc, site) if isinstance(doc, dict) else None
    if extensions is None or KEY not in extensions:
        return {"declared": False}
    value = extensions[KEY]
    refused = oversize(value)
    errors = refused if refused else cas.schema_errors(value)
    if errors:
        return {"declared": True, "valid": False, "errors": errors}
    return {"declared": True, "valid": True, "standard": value["standard"], "projects": value["projects"]}


# The detector (FAC-SEM-101's, fabric_secrets.py) and what reading with it costs.

def head(text: str) -> str:
    """The first DETECTOR_CODE_POINTS code points: all the detector reads."""
    return text[:DETECTOR_CODE_POINTS]


def read_as_url(read: str) -> bool:
    """A string's head is read as a URL when, leading C0 controls and spaces stripped and tab, line feed and carriage
    return removed, it is ASCII only, holds no percent-escape of a byte at or above 0x80 and opens with a scheme (CA-5)."""
    text = re.sub(r"[\t\n\r]", "", re.sub(r"\A[\x00-\x20]+", "", read))
    return text.isascii() and not _HIGH_ESCAPE.search(text) and bool(_SCHEME.match(text))


def _url_reading(read: str) -> bool:
    """secretUrl where read_as_url admits the head, secretArgument otherwise. The kit's secret_url also reads a URL the
    WHATWG parser refuses (the safe direction for its own callers); the contract's `new URL` throws there and finds only
    what secretArgument finds, so a refused URL is read by secret_argument alone here."""
    if not read_as_url(read):
        return secret_argument(read)
    return secret_argument(read) or (url_parts(read) is not None and secret_url(read))


def shaped_read(read: str) -> bool:
    return secret_value(read) or _url_reading(read)


def _key_shaped(text: str) -> bool:
    read = head(text)
    return bool(JWT_SHAPE.search(read) or SECRET_VALUE.search(read))


def plain_name(name: str) -> bool:
    return bool(NAME_CHARACTERS.match(name)) and not re.search(r"[0-9]{7}", re.sub(r"[-_]", "", name)) and not shaped_read(head(name))


def _relative_ref(text: str) -> bool:
    return 1 <= len(text) <= 256 and bool(_RELATIVE_REF.match(text))


def _run_from(text: str, start: int) -> int:
    end = start
    while end < len(text) and (text[end].isascii() and (text[end].isalnum() or text[end] in "_-")):
        end += 1
    return end


def jwt_rereads(text: str) -> int:
    """From each `eyJ`, its base64url run, `eyJ` included, and the dot and the run after it when the run ends at one."""
    cost, reach, run_end = 0, 0, 0
    at = text.find("eyJ")
    while at >= 0:
        if run_end <= at:
            run_end = _run_from(text, at)
            reach = _run_from(text, run_end + 1) if run_end < len(text) and text[run_end] == "." else run_end
        cost += reach - at
        at = text.find("eyJ", at + 1)
    return cost


def _units(text: str, limit: int, start: int) -> int:
    return max(0, min(limit, len(text) - start))


def _colour_before(text: str, at: int) -> bool:
    if at < 1 or text[at - 1] != "m":
        return False
    start = at - 2
    while start >= 0 and text[start] in "0123456789;:":
        start -= 1
    return start >= 0 and text[start] == "[" and bool(_ESC_BEFORE.search(text[max(0, start - 6):start]))


def key_rereads(text: str) -> int:
    """From each `sk-` at a boundary up to KEY_REREAD units, SK_FLOOR after one elsewhere, a floor after each other prefix."""
    cost = 0
    match = _SK.search(text)
    while match:
        at = match.start()
        before = text[at - 1] if at > 0 else ""
        boundary = (at == 0 or not (before.isascii() and before.isalnum()) or bool(_ESCAPE_BEFORE.search(text[max(0, at - 6):at]))
                    or _colour_before(text, at))
        cost += _units(text, KEY_REREAD, at) if boundary else _units(text, SK_FLOOR, at + 3)
        match = _SK.search(text, at + 1)
    for prefix, floor in PREFIX_FLOORS:
        match = prefix.search(text)
        while match:
            cost += _units(text, floor, match.end())
            match = prefix.search(text, match.start() + 1)
    return cost


def run_rereads(text: str) -> int:
    """For each maximal base64 run shorter than LONG_RUN_FLOOR in each of three partitions, min(length, 39) per unit."""
    def charge(run: int) -> int:
        return run * min(run, LONG_RUN_FLOOR - 1) if run < LONG_RUN_FLOOR else 0
    cost = whole = no_equals = no_slash = 0
    i, length = 0, len(text)
    while i <= length:
        c = ord(text[i]) if i < length else -1
        if 65 <= c <= 90 or 97 <= c <= 122 or 48 <= c <= 57 or c in (43, 95, 45):
            whole += 1
            no_equals += 1
            no_slash += 1
        elif c == 47:
            whole += 1
            no_equals += 1
            cost += charge(no_slash)
            no_slash = 0
        elif c == 61:
            whole += 1
            cost += charge(no_equals) + charge(no_slash)
            no_equals = no_slash = 0
        else:
            cost += charge(whole) + charge(no_equals) + charge(no_slash)
            whole = no_equals = no_slash = 0
            if 0xD800 <= c <= 0xDBFF and i + 1 < length and 0xDC00 <= ord(text[i + 1]) <= 0xDFFF:
                i += 1
        i += 1
    return cost


def argument_pieces(text: str) -> int:
    return ARG_PIECE_COST * len(_SEPARATOR.findall(text))


def _ipv4_number(part: str) -> Optional[int]:
    if part == "":
        return None
    base, digits = 10, part
    if len(part) >= 2 and part[:2] in ("0x", "0X"):
        base, digits = 16, part[2:]
    elif len(part) >= 2 and part[0] == "0":
        base, digits = 8, part[1:]
    if digits == "":
        return 0
    try:
        return int(digits, base) if re.fullmatch({10: "[0-9]+", 16: "[0-9A-Fa-f]+", 8: "[0-7]+"}[base], digits) else None
    except ValueError:
        return None


def _host_ok(host: str, special: bool) -> bool:
    """Whether the WHATWG URL parser takes an ASCII host (its failures only: forbidden code points, IPv6, IPv4)."""
    if host.startswith("["):
        if not host.endswith("]") or "%" in host:
            return False
        try:
            ipaddress.IPv6Address(host[1:-1])
            return True
        except ValueError:
            return False
    forbidden = "\x00\t\n\r #/:<>?@[\\]^|"
    if not special:
        return not any(c in forbidden for c in host)
    try:
        decoded = re.sub(r"%([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), host).lower()
    except ValueError:
        return False
    if decoded == "" or any(c in forbidden or c == "%" or ord(c) < 0x20 or ord(c) == 0x7F for c in decoded):
        return False
    # An `xn--` label is not decoded: Node's parser (the reference runs on it) takes every ASCII one.
    parts = decoded.split(".")
    if parts[-1] == "" and len(parts) > 1:
        parts = parts[:-1]
    last = parts[-1]
    if not (last and (last.isdigit() or (_ipv4_number(last) is not None and last[:2] in ("0x", "0X")))):
        return True
    numbers = [_ipv4_number(part) for part in parts]
    if len(parts) > 4 or any(n is None for n in numbers) or any(n > 255 for n in numbers[:-1]):
        return False
    return numbers[-1] < 256 ** (5 - len(numbers))


_SPECIAL = ("ftp", "http", "https", "ws", "wss", "file")


def url_parts(text: str) -> Optional[Tuple[str, str]]:
    """`new URL(text)`'s search and hash for an ASCII string read as a URL, or None where the parser throws."""
    text = re.sub(r"[\t\n\r]", "", text.strip("".join(map(chr, range(0x21)))))
    scheme, _, rest = text.partition(":")
    lowered = scheme.lower()
    special = lowered in _SPECIAL
    body = rest.partition("#")[0].partition("?")[0]
    authority: Optional[str] = None
    if special and lowered != "file":
        authority = re.split(r"[/\\]", body.lstrip("/\\"), maxsplit=1)[0]
    elif lowered == "file" and re.match(r"[/\\]{2}", body):
        authority = re.split(r"[/\\]", body[2:], maxsplit=1)[0]
    elif not special and body.startswith("//"):
        authority = body[2:].partition("/")[0]
    if authority is not None and lowered == "file":
        # A file host takes no user information and no port: the whole authority is the host.
        if authority and authority.lower() != "localhost" and not _host_ok(authority, True):
            return None
    elif authority is not None:
        userinfo, at, hostport = authority.rpartition("@")
        bracket = hostport.rfind("]")
        colon = hostport.rfind(":")
        host, port = (hostport[:colon], hostport[colon + 1:]) if colon > bracket else (hostport, "")
        if port and (not port.isdigit() or int(port) > 65535):
            return None
        if at and hostport == "":
            return None
        if host == "" and special and lowered != "file":
            return None
        if host and not _host_ok(host, special):
            return None
    _, query, fragment = _url_parts(text)
    has_query = "?" in rest.partition("#")[0]
    has_fragment = "#" in rest
    return ("?" + query if has_query and query else "", "#" + fragment if has_fragment and fragment else "")


def detector_cost(whole: str, is_head: bool = False) -> int:
    """The UTF-16 units FAC-SEM-165's detector may read in a string's head (the contract's detectorCost)."""
    text = whole if is_head else head(whole)
    units = utf16(text)
    cost = len(units) + jwt_rereads(units) + key_rereads(units) + run_rereads(units) + argument_pieces(units)
    if not read_as_url(text):
        return cost
    cost += PIECE_COST
    parts = url_parts(text)
    if parts is None:
        return cost
    for part in parts:
        cost += ARG_PIECE_COST * part.count("&")
        for name, values in raw_values(part[1:]).items():
            name_units = len(utf16(name))
            upper = bool(re.search(r"[A-Z]", name))
            for value in values:
                value_units = utf16(value)
                cost += PIECE_COST + name_units + len(value_units) + jwt_rereads(value_units) + key_rereads(value_units) + run_rereads(value_units)
                if value != "" and upper:
                    cost += name_units * (name_units + 1) // 2
    return cost


class Budget:
    """What is left of FAC-SEM-165's reading for one document, shared by every copy of its declaration."""

    def __init__(self) -> None:
        self.left = SECRET_BUDGET
        self.unread = False
        self.named = 0
        self.more = 0
        self.unread_at: Optional[str] = None
        self.copies: set = set()


def _finding(code: str, at: str, message: str) -> Dict[str, str]:
    return {"code": code, "instancePath": at, "message": message}


def secrets(value: Any, root: str, budget: Budget) -> List[Dict[str, str]]:
    """FAC-SEM-165: no member name and no string of the declaration is shaped like a credential (CA-5)."""
    findings: List[Dict[str, str]] = []
    names = cas.schema_names()
    more = [0]
    last: Dict[str, Any] = {"frame": None, "key": "", "plain": False}

    def flag(at: str, what: str, text: str, ident: bool) -> None:
        if budget.named < SECRET_FINDINGS:
            budget.named += 1
            rename = "; an id that starts with sk- is read as a key; rename it" if ident and re.match(r"sk-", text, re.I | re.A) else ""
            findings.append(_finding("FAC-SEM-165", at, "%s is shaped like a credential: a token is named by its vault slot, never written%s (DEC-0150 CA-5)" % (what, rename)))
        else:
            budget.more += 1
            more[0] += 1

    def afford(read: str) -> bool:
        if budget.unread:
            return False
        cost = (0 if read == "" else detector_cost(read, True)) + VISIT_COST
        if cost > budget.left:
            budget.unread, budget.unread_at = True, root
            return False
        budget.left -= cost
        return True

    def token_of(frame: _Frame, key: str, index: bool) -> Optional[str]:
        if index:
            return cas.placed_token(frame.name, frame.parent, key, index, names)
        plain = last["frame"] is frame and last["key"] == key and last["plain"]
        return cas.placed_token(frame.name, frame.parent, key, index, names, cas.is_none(frame.container)) if plain else None

    def in_texts(frame: Optional[_Frame]) -> bool:
        return frame is not None and frame.role == "texts"

    def visit(text: str, spot: _Spot, place: Callable[[_Spot], str]) -> None:
        read = head(text)
        if spot.is_name:
            last.update(frame=spot.frame, key=text, plain=False)
            if not afford(read):
                return
            is_shaped = shaped_read(read)
            last["plain"] = not is_shaped and bool(NAME_CHARACTERS.match(text)) and not re.search(r"[0-9]{7}", re.sub(r"[-_]", "", text))
            if is_shaped:
                flag(place(spot), "a member's name", text, not in_texts(spot.frame))
            return
        if not afford(read):
            return
        role = spot.frame.role if spot.frame is not None else None
        key = spot.key
        if role == "tickets" and key == "token_slot" and TOKEN_SLOT.match(text):
            found = any(secret_value(segment) for segment in text.split("/"))
        elif ((role == "evals" and key == "suite") or (role == "tickets" and key == "outbox")) and _relative_ref(text):
            found = _url_reading(read)
        elif role == "queue" and key == "recommendation" and _OPAQUE_ID.match(text):
            found = _key_shaped(text)
        else:
            found = shaped_read(read)
        if found:
            flag(place(spot), "a value", text, key in _ID_MEMBERS and not in_texts(spot.frame))

    def on_enter() -> None:
        if budget.unread:
            return
        if VISIT_COST > budget.left:
            budget.unread, budget.unread_at = True, root
            return
        budget.left -= VISIT_COST

    walk(value, root, token_of, visit, lambda: budget.unread, on_enter)
    if more[0] > 0:
        findings.append(_finding("FAC-SEM-165", root, "and %d more names or values shaped like a credential (DEC-0150 CA-5)" % more[0]))
    return findings


def summary(budget: Budget) -> List[Dict[str, str]]:
    """The document's closing FAC-SEM-165 finding, once: that the rest was not read."""
    if not budget.unread:
        return []
    at = budget.unread_at or ""
    fix = ("this copy is not read by a reader and should be removed" if at in budget.copies
           else "a reader treats the declaration as not declared; declare fewer or shorter texts or names")
    return [_finding("FAC-SEM-165", at, "reading the declarations for credentials takes more than %d UTF-16 units of reading; %s (DEC-0150 CA-5)" % (SECRET_BUDGET, fix))]


def misplaced(doc: Dict[str, Any], budget: Budget) -> List[Dict[str, str]]:
    """FAC-SEM-162 on a manifest: the key where a reader does not read it (the manifest's own extensions, a capability's)."""
    findings: List[Dict[str, str]] = []

    def flag(extensions: Dict[str, Any], at: str) -> None:
        root = "%s/%s" % (at, KEY_TOKEN)
        findings.append(_finding("FAC-SEM-162", root, "a reader reads a manifest's channel-agent declaration under provider.extensions only, so it is not read here (DEC-0150 CA-1)"))
        budget.copies.add(root)
        findings.extend(secrets(extensions[KEY], root, budget))
    if isinstance(doc.get("extensions"), dict) and KEY in doc["extensions"]:
        flag(doc["extensions"], "/extensions")
    for capability, i in indexed_objects(doc.get("capabilities")):
        if isinstance(capability.get("extensions"), dict) and KEY in capability["extensions"]:
            flag(capability["extensions"], "/capabilities/%d/extensions" % i)
    return findings


class _Cap:
    def __init__(self) -> None:
        self.named = 0
        self.more = 0


def _capped(findings: List[Dict[str, str]], cap: _Cap, code: str, at: Callable[[], str], message: str) -> None:
    if cap.named < SECRET_FINDINGS:
        cap.named += 1
        findings.append(_finding(code, at(), message))
    else:
        cap.more += 1


def closing(code: str, cap: _Cap, root: str) -> List[Dict[str, str]]:
    if cap.more == 0:
        return []
    what = ("repeated ids or decisions not named (DEC-0150 CA-3)" if code == "FAC-SEM-163" else
            "places that owe a text, a recommendation or a spend record, or carry a blank or refused text (DEC-0150 CA-4)")
    return [_finding(code, root, "and %d more %s" % (cap.more, what))]


def _repeats(items: List[Tuple[Dict[str, Any], int]], member: str) -> List[int]:
    seen: List[Any] = []
    found = []
    for item, i in items:
        value = item.get(member)
        if value in seen:
            found.append(i)
        seen.append(value)
    return found


def references(project: Dict[str, Any], at: str, cap: _Cap) -> List[Dict[str, str]]:
    """FAC-SEM-163: ids once, and every channel held by a decision names a recorded one (CA-3)."""
    findings: List[Dict[str, str]] = []

    def flag(path: str, message: str) -> None:
        _capped(findings, cap, "FAC-SEM-163", lambda: at + path, "%s (DEC-0150 CA-3)" % message)
    for i in _repeats(indexed_objects(project["taxonomy"].get("codes")), "code"):
        flag("/taxonomy/codes/%d/code" % i, "this category code repeats an earlier one")
    for i in _repeats(indexed_objects(project.get("tiers")), "code"):
        flag("/tiers/%d/code" % i, "this tier code repeats an earlier one")
    channels = indexed_objects(project.get("channels"))
    for i in _repeats(channels, "id"):
        flag("/channels/%d/id" % i, "this channel id repeats an earlier channel's")
    source_ids: List[Any] = []
    for member, message in (("sources", "this source id repeats an earlier source's"),
                            ("declined_sources", "this declined source's id repeats a source read or declined before it")):
        for source, i in indexed_objects(project.get(member)):
            if source.get("id") in source_ids:
                flag("/%s/%d/id" % (member, i), message)
            source_ids.append(source.get("id"))
    for i in _repeats(indexed_objects(project.get("handoff_queues")), "id"):
        flag("/handoff_queues/%d/id" % i, "this hand-off queue id repeats an earlier queue's")
    decisions = indexed_objects(project.get("recorded_decisions"))
    for i in _repeats(decisions, "id"):
        flag("/recorded_decisions/%d/id" % i, "this decision id repeats an earlier recorded decision's")
    recorded = [decision.get("id") for decision, _ in decisions]
    for channel, i in channels:
        if channel.get("decision") is None:
            if channel.get("replies_enabled") is False:
                flag("/channels/%d/decision" % i, "a channel with replies off names the recorded decision that holds it")
        elif channel["decision"] not in recorded:
            flag("/channels/%d/decision" % i, "this channel's decision is not one recorded_decisions lists")
    return findings


def obligations(project: Dict[str, Any], at: str, cap: _Cap) -> List[Dict[str, str]]:
    """FAC-SEM-164: what a channel, a queue and the budgets owe (CA-4)."""
    findings: List[Dict[str, str]] = []

    def flag(path: Callable[[], str], message: str) -> None:
        _capped(findings, cap, "FAC-SEM-164", lambda: at + path(), "%s (DEC-0150 CA-4)" % message)
    for channel, i in indexed_objects(project.get("channels")):
        texts = channel["texts"]
        replies, holding = channel.get("replies_enabled") is True, channel.get("holding_reply") is True
        final = texts.get("final")
        if replies and holding and "holding" not in texts:
            flag(lambda i=i: "/channels/%d/texts/holding" % i, "a channel that sends a holding reply declares the holding text")
        if replies and "final" not in texts:
            flag(lambda i=i: "/channels/%d/texts/final" % i, "a channel that replies declares the final text")
        if replies and holding and isinstance(final, dict) and final.get("none") == "not_used":
            flag(lambda i=i: "/channels/%d/texts/final" % i, "a channel that sends a holding reply owes a final reply, so its final text is not one it does not use")
        if channel.get("kind") == "store_review" and channel.get("clarifying_question") is True:
            flag(lambda i=i: "/channels/%d/clarifying_question" % i, "a store review gets one public reply and no clarifying question")
        for which in ("holding", "final"):
            if which == "final" and cas.is_none(final):
                continue
            entries = texts.get(which) or {}
            for language in js_keys(entries):
                text = entries[language]

                def place(i: int = i, which: str = which, language: str = language) -> str:
                    return "/channels/%d/texts/%s%s" % (i, which, "/*" if plain_name(language) else "")
                if blank(text):
                    flag(place, "a declared text is blank, and nothing empty is sent")
                elif EM_DASH in text:
                    flag(place, "a declared text carries U+2014, which a send's checks refuse")
    for tier, i in indexed_objects(project.get("tiers")):
        label = tier["label"]
        if blank(label):
            flag(lambda i=i: "/tiers/%d/label" % i, "a tier's label is blank, and nothing empty is shown")
        elif EM_DASH in label:
            flag(lambda i=i: "/tiers/%d/label" % i, "a tier's label carries U+2014, which a send's checks refuse")
    for queue, i in indexed_objects(project.get("handoff_queues")):
        if queue.get("answered_signal") == "none" and "recommendation" not in queue:
            flag(lambda i=i: "/handoff_queues/%d/recommendation" % i, "a hand-off queue with no answered signal names the recommendation to its owner")
        if queue.get("answered_signal") != "none" and "recommendation" in queue:
            flag(lambda i=i: "/handoff_queues/%d/recommendation" % i, "a hand-off queue with an answered signal needs no recommendation, and a reader does not read this one")
    evals = project["evals"]
    if (evals["judge_budget_usd"] > 0 or evals["replay_budget_usd"] > 0) and evals.get("spend_record") is None:
        flag(lambda: "/evals/spend_record", "a budget above 0 names the usage report's limit it is spent under; without one it reads 0")
    return findings


def _repeat(at: str, cap: _Cap) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    _capped(findings, cap, "FAC-SEM-163", lambda: at + "/project", "this project repeats an earlier entry's (DEC-0150 CA-3)")
    return findings


def channel_agent_rules(doc: Any, site: str = "manifest") -> List[Dict[str, str]]:
    """DEC-0150's checks on a manifest or a well-known answer: FAC-SEM-162 a misplaced (manifest only) or invalid
    declaration, FAC-SEM-165 credential shapes, FAC-SEM-163 and FAC-SEM-164 per project of a valid one."""
    if not isinstance(doc, dict):
        return []
    budget = Budget()
    view = schema_view(doc, site)
    root = CHANNEL_AGENT_PATHS[site]
    read = secrets(_extensions_at(doc, site)[KEY], root, budget) if view["declared"] else []
    findings = misplaced(doc, budget) if site == "manifest" else []
    if not view["declared"]:
        return findings + summary(budget)
    findings += read + summary(budget)
    if not view["valid"]:
        named = ", ".join(cas.message_places(view["errors"][:MESSAGE_ERRORS]))
        more = " and %d more" % (len(view["errors"]) - MESSAGE_ERRORS) if len(view["errors"]) > MESSAGE_ERRORS else ""
        findings.append(_finding("FAC-SEM-162", root, "the channel-agent declaration fails its schema: %s%s; a reader treats it as not declared and "
                                 "reports it (DEC-0150 CA-2). The grammars are in docs/specification/channel-agent.md#the-declaration" % (named, more)))
        return findings
    seen: List[Any] = []
    repeated, owing, owed = _Cap(), _Cap(), []
    for i, project in enumerate(view["projects"]):
        at = "%s/projects/%d" % (root, i)
        if project.get("project") in seen:
            findings += _repeat(at, repeated)
        seen.append(project.get("project"))
        findings += references(project, at, repeated)
        owed += obligations(project, at, owing)
    return findings + closing("FAC-SEM-163", repeated, root) + owed + closing("FAC-SEM-164", owing, root)


def view_line(finding: Dict[str, str]) -> str:
    """A view's line: the rule, the place and the finding's reason, its message without the decision it cites."""
    return "%s at %s: %s" % (finding["code"], finding["instancePath"] or "/", re.sub(r" \(DEC-0150 CA-[0-9]\)\Z", "", finding["message"]))


def schema_line(error: str) -> str:
    parts = re.match(r"(\S+) at (/\S*)(.*)\Z", error)
    return "FAC-SEM-162 at /: %s" % error if parts is None else "FAC-SEM-162 at %s: %s%s" % (parts.group(2), parts.group(1), parts.group(3))


def _once(lines: List[str]) -> List[str]:
    return list(dict.fromkeys(lines))


def channel_agent_view(doc: Any, site: str = "manifest") -> Dict[str, Any]:
    """The reader of extensions/channel-agent/0.1 at one site (CA-1, CA-2, CA-5): declared, reported and errors, and for
    a read and valid declaration its standard, projects and FAC-SEM-164's findings as obligations."""
    view = schema_view(doc, site)
    budget = Budget()
    if not view["declared"]:
        copies = misplaced(doc, budget) + summary(budget) if site == "manifest" and isinstance(doc, dict) else []
        return {"declared": False, "reported": True, "errors": _once([view_line(f) for f in copies])} if copies else {"declared": False, "reported": False, "errors": []}
    value = _extensions_at(doc, site)[KEY]
    credentials = [view_line(f) for f in secrets(value, "", budget) + summary(budget)]
    if not view["valid"]:
        lines = [schema_line(error) for error in view["errors"][:SECRET_FINDINGS]]
        if len(view["errors"]) > SECRET_FINDINGS:
            lines.append("FAC-SEM-162 at /: and %d more" % (len(view["errors"]) - SECRET_FINDINGS))
        return {"declared": False, "reported": True, "errors": _once(lines + credentials)}
    repeated, owing = _Cap(), _Cap()
    blocking: List[Dict[str, str]] = []
    owed: List[Dict[str, str]] = []
    seen: List[Any] = []
    for i, project in enumerate(view["projects"]):
        at = "/projects/%d" % i
        if project.get("project") in seen:
            blocking += _repeat(at, repeated)
        seen.append(project.get("project"))
        blocking += references(project, at, repeated)
        owed += obligations(project, at, owing)
    blocking += closing("FAC-SEM-163", repeated, "")
    errors = credentials + [view_line(f) for f in blocking]
    if errors:
        return {"declared": False, "reported": True, "errors": _once(errors)}
    return {"declared": True, "reported": False, "errors": [], "standard": view["standard"], "projects": view["projects"],
            "obligations": _once([view_line(f) for f in owed + closing("FAC-SEM-164", owing, "")])}


# The probe's rule (D1 to D4 of the 0.73.0 brief).

def _other_keys(doc: Any) -> List[str]:
    """Places of a channel-agent key of another version, which a reader does not read (CA-7)."""
    found: List[str] = []
    if not isinstance(doc, dict):
        return found
    holders = [("/provider/extensions", (doc.get("provider") or {}).get("extensions") if isinstance(doc.get("provider"), dict) else None),
               ("/extensions", doc.get("extensions"))]
    holders += [("/capabilities/%d/extensions" % i, c.get("extensions")) for c, i in indexed_objects(doc.get("capabilities"))]
    for at, extensions in holders:
        if isinstance(extensions, dict):
            for key in extensions:
                if key.startswith(KEY_PREFIX) and key != KEY:
                    version = key[len(KEY_PREFIX):]
                    found.append("%s (version %s)" % (at, version if re.fullmatch(r"[0-9]{1,4}(?:\.[0-9]{1,4}){0,3}", version) else "not written"))
    return found


def _shown(findings: List[Dict[str, str]], limit: int = 5) -> str:
    text = "; ".join("%s at %s" % (f["code"], f["instancePath"] or "/") for f in findings[:limit])
    return text + ("; and %d more" % (len(findings) - limit) if len(findings) > limit else "")


def _credential_shapes(findings: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """FAC-SEM-165's findings of a credential's shape, not its budget run-out: they fail the rule wherever they sit."""
    return [f for f in findings if f["code"] == "FAC-SEM-165" and "shaped like a credential" in f["message"]]


def _size_note(well_known_bytes: int) -> str:
    return ("the well-known answer is %d bytes, %s the 2 MiB cap of Fabric Dashboards' probe: keep a large declaration in "
            "the manifest (CT-223)" % (well_known_bytes, "over" if well_known_bytes > WELL_KNOWN_CAP else "near"))


def declaration_verdict(manifest: Optional[Dict[str, Any]], manifest_named: bool, manifest_problem: str,
                        well_known: Optional[Dict[str, Any]], well_known_bytes: Optional[int] = None) -> Tuple[str, str]:
    """`channel-agent.declaration`: PASS for a declaration read and free of findings; FAIL with its first findings when
    the contract's reader still reads it as declared (FAC-SEM-164's obligations) or a string is shaped like a credential
    (FAC-SEM-165), in the read declaration or in any copy beside it; NOT_RUN, never FAIL, when nothing is declared or the reader reads it as not declared (D3): a key
    where a reader does not read it, another version's key, a copy in the well-known answer of a service with a
    manifest (D1), or a declaration the schema or FAC-SEM-163 refuses (an older form)."""
    notes: List[str] = []
    wk_has = isinstance(well_known, dict) and KEY in (_extensions_at(well_known, "well-known") or {})
    if manifest_named and manifest is None:
        copy_shapes = _credential_shapes(channel_agent_rules(well_known, "well-known")) if wk_has else []
        if wk_has:
            notes.append("the well-known answer's copy is not read: a service with a manifest declares there only (CA-1)")
            if well_known_bytes is not None and well_known_bytes >= WELL_KNOWN_NEAR:
                notes.append(_size_note(well_known_bytes))
        if copy_shapes:
            return "FAIL", "the well-known answer's copy holds %d string(s) shaped like a credential: %s (DEC-0150 CA-5)%s" % (
                len(copy_shapes), _shown(copy_shapes), (" (%s)" % "; ".join(notes)) if notes else "")
        return "NOT_RUN", "the manifest the descriptor names is not read (%s); a service with a manifest declares there only (CA-1)%s" % (
            manifest_problem, (" (%s)" % "; ".join(notes)) if notes else "")
    site, doc = ("manifest", manifest) if manifest is not None else ("well-known", well_known)
    root = CHANNEL_AGENT_PATHS[site]
    findings = channel_agent_rules(doc, site)
    mine = [f["instancePath"] == root or f["instancePath"].startswith(root + "/") for f in findings]
    own = [f for f, ours in zip(findings, mine) if ours]
    others = [f for f, ours in zip(findings, mine) if not ours]
    if others:
        notes.append("not read, reported: %s" % _shown(others))
    other_keys = _other_keys(doc) + (_other_keys(well_known) if site == "manifest" else [])
    if other_keys:
        notes.append("a channel-agent key of another version is not read (CA-7): %s" % ", ".join(other_keys[:5]))
    copy: List[Dict[str, str]] = []
    if site == "manifest" and wk_has:
        copy = channel_agent_rules(well_known, "well-known")
        notes.append("the well-known answer's copy is ignored: a service with a manifest is read from it only (CA-1)%s"
                     % ("; the copy has %d finding(s): %s" % (len(copy), _shown(copy, 3)) if copy else ""))
    if wk_has and well_known_bytes is not None and well_known_bytes >= WELL_KNOWN_NEAR:
        notes.append(_size_note(well_known_bytes))
    tail = (" (%s)" % "; ".join(notes)) if notes else ""
    declared = isinstance(doc, dict) and KEY in (_extensions_at(doc, site) or {})
    where = "the manifest's provider.extensions" if site == "manifest" else "the well-known answer's extensions"
    shapes = _credential_shapes(others + copy)
    if shapes:  # a credential's shape in a copy no reader reads still sits in a document the service publishes (CA-5)
        return "FAIL", "%d string(s) shaped like a credential outside the read declaration: %s (DEC-0150 CA-5)%s" % (
            len(shapes), _shown(shapes), tail)
    if declared and own:
        if not channel_agent_view(doc, site)["declared"] and not _credential_shapes(own):
            # D3: what the contract's reader reads as not declared (an older form, a repeat, a dangling reference) is
            # reported while producers move to this revision; a credential's shape (FAC-SEM-165) always fails, while a
            # declaration too large to read for credentials is read as not declared.
            return "NOT_RUN", "read as not declared, never a failure while producers move to this revision: %d finding(s) on the declaration in %s: %s%s" % (
                len(own), where, _shown(own), tail)
        return "FAIL", "%d finding(s) on the declaration in %s: %s%s" % (len(own), where, _shown(own), tail)
    if declared:
        projects = schema_view(doc, site).get("projects") or []
        return "PASS", "declared in %s: channel-agent-standard/1, %d project(s), no finding on it%s" % (where, len(projects), tail)
    if notes:
        return "NOT_RUN", "read as not declared, never a failure while producers move to this revision%s" % tail
    return "NOT_RUN", "declares no %s in %s: not a channel agent" % (KEY, where)
