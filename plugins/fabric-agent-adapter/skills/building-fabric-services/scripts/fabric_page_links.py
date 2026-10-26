#!/usr/bin/env python3
"""A service's pages as Fabric Dashboards' open_link (Fabric Agent Contract DEC-0123, PL-1 to PL-4, FAC-SEM-143;
`src/page-link-rules.ts` at the pin): build and read the open_link, tell a raw local address, and the findings on a
link a document hands a person and on a URL-mode input request. A port held to the contract's answers by
test/fixtures/contract/page-link-vectors.json and page-link-extra-vectors.json. Part of the service kit (FAA-65,
layer L3).

Standard library only, Python 3.9+. The reference reads URLs with WHATWG `URL` and `URLSearchParams`; the parts of
that reading it relies on are written here by hand (decision D11 of the 0.51.0 brief): the host parser of an http or
https URL (IPv4 numbers in decimal, octal and hex and their short forms, IPv6 and its serialisation, a trailing dot,
percent-encoded and full-width hosts), whether a string parses as a `fabric-dashboards:` URL at all, dot-segment
removal with `%2e`, `application/x-www-form-urlencoded` reading and writing, JavaScript's `\\s`, the C0-and-space
strip at the ends and the tab-and-newline removal inside, a lone surrogate as U+FFFD after encoding, and string
lengths in UTF-16 code units. A host that is not ASCII after mapping is read by an approximation of UTS 46 (NFKC,
lower case, the ideographic full stops, the ignored characters, the Bidi rule, Punycode), which decides only whether
such a name is `localhost` or a name under it; a differential run against Node's URL found no difference. The credential detector is the one fabric_connections reads FAC-SEM-127 with: the contract's,
with ECMAScript's whitespace, `.` and case folding."""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple
import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))

from fabric_base import ServiceError, _ID, _INSTANCE  # noqa: E402
from fabric_jsvalue import _JS_SPACE, js_keys  # noqa: E402 - JavaScript's \s, and its key order
from fabric_secrets import raw_values  # noqa: E402 - the contract's detector (DEC-0044)
# The detector read as the reference's ECMAScript reads it (its \s, `.` and case folding), as FAC-SEM-127 reads it.
from fabric_connections import _credential_name as credential_name, _secret_value as secret_value  # noqa: E402

#: A service id and an instance, as `service-common.schema.json` defines them.
SERVICE_ID = _ID
INSTANCE = _INSTANCE
_NOT_SPACE = "[^%s]" % re.escape(_JS_SPACE)
#: A path on the service origin, as `service-common.schema.json` `originPath` writes it: no whitespace (JavaScript's).
ORIGIN_PATH = re.compile(r"^/(?!/)%s*\Z" % _NOT_SPACE)
#: What the host's `safePath` refuses anywhere in a path: a backslash and a C0 or DEL control character.
_HOST_REFUSED = re.compile(r"[\\\x00-\x1f\x7f]")
#: The host's limit on a path; the link around it is bounded only to keep a reader's work finite.
MAX_PAGE_PATH_LENGTH = 2048
MAX_PAGE_LINK_LENGTH = 20000

_GRAMMAR = "not fabric-dashboards://service/<id>.<instance>[?path=<path>]"
_PREFIX = re.compile(r"^fabric-dashboards://service/", re.I | re.A)
_SHAPE = re.compile(r"^fabric-dashboards://service/([^/?#]+)/?(?:\?([^#]*))?\Z")
_LOGIN = re.compile(r"^/fabric/+v1/+login(?:/|\Z)", re.I | re.A)
_DASHBOARDS_SCHEME = re.compile(r"^[%s]*fabric-dashboards:" % re.escape(_JS_SPACE), re.I | re.A)
#: The hosts only this computer reaches, as WHATWG URL writes them (the contract's LOOPBACK).
_LOOPBACK = re.compile(r"^(?:127(?:\.\d{1,3}){3}|0\.0\.0\.0|\[::1?\]|\[::ffff:7f[0-9a-f]{2}:[0-9a-f]{1,4}\]|localhost"
                       r"|[a-z0-9.-]+\.localhost)\Z", re.I | re.A)


class PageLinkError(ServiceError, ValueError):
    """What `dashboards_link` raises for an id, an instance or a path the grammar refuses."""


# --- JavaScript strings ----------------------------------------------------------------------------------------------

def _js_length(text: str) -> int:
    """`text.length`: UTF-16 code units, so a character beyond the BMP counts twice."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _scalars(text: str) -> str:
    """The string a JavaScript engine encodes: a high and a low surrogate side by side are one character, a lone one is
    U+FFFD (what UTF-8 encoding a JavaScript string does)."""
    if not re.search("[\ud800-\udfff]", text):
        return text
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def _lone_surrogate(text: str) -> bool:
    """A surrogate without its pair (the reference's LONE_SURROGATE): one is left once the pairs are joined."""
    if not re.search("[\ud800-\udfff]", text):
        return False
    joined = text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")
    return re.search("[\ud800-\udfff]", joined) is not None


# --- WHATWG pieces the reference relies on ---------------------------------------------------------------------------

def _url_input(url: str) -> str:
    """The basic URL parser's first steps: C0 controls and space off both ends, every tab and newline removed."""
    return re.sub(r"[\t\n\r]", "", re.sub(r"^[\x00-\x20]+|[\x00-\x20]+\Z", "", url))


_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")


def _percent_decode(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        if data[i] == 0x25 and re.match(rb"[0-9A-Fa-f]{2}", data[i + 1:i + 3]):
            out.append(int(data[i + 1:i + 3], 16))
            i += 3
        else:
            out.append(data[i])
            i += 1
    return bytes(out)


def _utf8(data: bytes) -> str:
    """UTF-8 decode without BOM: a BOM is kept, a malformed sequence is U+FFFD."""
    return data.decode("utf-8", "replace")


def _form_parse(text: str) -> List[Tuple[str, str]]:
    """`application/x-www-form-urlencoded` parsing, as `URLSearchParams` does it: `&` separates, the first `=` splits,
    `+` is a space, escapes are decoded as UTF-8."""
    pairs = []
    for piece in _scalars(text).encode("utf-8").split(b"&"):
        if not piece:
            continue
        name, _, value = piece.partition(b"=")
        pairs.append((_utf8(_percent_decode(name.replace(b"+", b" "))), _utf8(_percent_decode(value.replace(b"+", b" ")))))
    return pairs


_FORM_SAFE = frozenset(b"*-._0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def _form_encode(text: str) -> str:
    """The `application/x-www-form-urlencoded` serializer: a space is `+`, `*-._` and alphanumerics stay, the rest is
    `%XX` (so `~` is `%7E` and `*` is kept, the other way round from urllib.parse)."""
    return "".join(chr(b) if b in _FORM_SAFE else "+" if b == 0x20 else "%%%02X" % b for b in _scalars(text).encode("utf-8"))


def _resolved_pathname(path: str) -> str:
    """`new URL(path, base).pathname` for a path-absolute string with no backslash or control character: the path up to
    its query or fragment, dot segments (`.`, `%2e`, `..`, `.%2e`, ...) removed."""
    raw = re.split(r"[?#]", path, maxsplit=1)[0]
    segments: List[str] = []
    parts = raw[1:].split("/")
    for index, segment in enumerate(parts):
        last = index == len(parts) - 1
        lowered = segment.lower()
        if lowered in ("..", ".%2e", "%2e.", "%2e%2e"):
            if segments:
                segments.pop()
            if last:
                segments.append("")
        elif lowered in (".", "%2e"):
            if last:
                segments.append("")
        else:
            segments.append(segment)
    return "/" + "/".join(segments)


def _ipv4_number(text: str) -> Optional[int]:
    if text == "":
        return None
    radix, digits = 10, r"[0-9]+"
    if text[:2] in ("0x", "0X"):
        text, radix, digits = text[2:], 16, r"[0-9A-Fa-f]+"
    elif len(text) >= 2 and text[0] == "0":
        text, radix, digits = text[1:], 8, r"[0-7]+"
    if text == "":
        return 0
    return int(text, radix) if re.fullmatch(digits, text, re.A) else None


def _ends_in_number(domain: str) -> bool:
    parts = domain.split(".")
    if parts[-1] == "":
        if len(parts) == 1:
            return False
        parts.pop()
    last = parts[-1]
    return (last != "" and re.fullmatch(r"[0-9]+", last, re.A) is not None) or _ipv4_number(last) is not None


def _ipv4(domain: str) -> Optional[str]:
    parts = domain.split(".")
    if parts[-1] == "" and len(parts) > 1:
        parts.pop()
    if len(parts) > 4:
        return None
    numbers = [_ipv4_number(part) for part in parts]
    if any(n is None for n in numbers) or any(n > 255 for n in numbers[:-1]):  # type: ignore[operator]
        return None
    if numbers[-1] >= 256 ** (5 - len(numbers)):  # type: ignore[operator]
        return None
    address = numbers[-1] + sum(n * 256 ** (3 - i) for i, n in enumerate(numbers[:-1]))  # type: ignore[operator]
    return ".".join(str((address >> shift) & 255) for shift in (24, 16, 8, 0))


def _ipv6(text: str) -> Optional[List[int]]:
    """The WHATWG IPv6 parser: eight pieces, or None."""
    address = [0] * 8
    piece, compress, i, n = 0, None, 0, len(text)
    at = lambda k: text[k] if k < n else ""  # noqa: E731
    hexdigit = lambda c: c != "" and c in "0123456789abcdefABCDEF"  # noqa: E731
    if at(0) == ":":
        if at(1) != ":":
            return None
        i, piece = 2, 1
        compress = piece
    while at(i) != "":
        if piece == 8:
            return None
        if at(i) == ":":
            if compress is not None:
                return None
            i += 1
            piece += 1
            compress = piece
            continue
        value = length = 0
        while length < 4 and hexdigit(at(i)):
            value = value * 16 + int(at(i), 16)
            i += 1
            length += 1
        if at(i) == ".":
            if length == 0:
                return None
            i -= length
            if piece > 6:
                return None
            seen = 0
            while at(i) != "":
                v4: Optional[int] = None
                if seen > 0:
                    if at(i) == "." and seen < 4:
                        i += 1
                    else:
                        return None
                if at(i) == "" or at(i) not in "0123456789":
                    return None
                while at(i) != "" and at(i) in "0123456789":
                    digit = int(at(i))
                    if v4 is None:
                        v4 = digit
                    elif v4 == 0:
                        return None
                    else:
                        v4 = v4 * 10 + digit
                    if v4 > 255:
                        return None
                    i += 1
                address[piece] = address[piece] * 0x100 + v4  # type: ignore[operator]
                seen += 1
                if seen in (2, 4):
                    piece += 1
            if seen != 4:
                return None
            break
        elif at(i) == ":":
            i += 1
            if at(i) == "":
                return None
        elif at(i) != "":
            return None
        address[piece] = value
        piece += 1
    if compress is not None:
        swaps, piece = piece - compress, 7
        while piece != 0 and swaps > 0:
            address[piece], address[compress + swaps - 1] = address[compress + swaps - 1], address[piece]
            piece -= 1
            swaps -= 1
    elif piece != 8:
        return None
    return address


def _ipv6_text(address: List[int]) -> str:
    best, best_len, run, run_len = None, 1, None, 0
    for index, value in enumerate(address + [1]):
        if value == 0:
            run, run_len = (index if run is None else run), run_len + 1
            continue
        if run is not None and run_len > best_len:
            best, best_len = run, run_len
        run, run_len = None, 0
    out, index = "", 0
    while index < 8:
        if index == best:
            out += "::" if index == 0 else ":"
            index += best_len
            continue
        out += "%x" % address[index] + (":" if index < 7 else "")
        index += 1
    return out


_FORBIDDEN_HOST = set("\x00\t\n\r #/:<>?@[\\]^|")
_FORBIDDEN_DOMAIN = _FORBIDDEN_HOST | set(chr(c) for c in range(0x20)) | {"%", "\x7f"}
_FULL_STOPS = re.compile("[\u3002\uff0e\uff61]")
#: Characters UTS 46 maps to nothing.
_IGNORED = re.compile("[\u00ad\u034f\u180b-\u180d\u180f\u200b\u2060\u2064\ufe00-\ufe0f\ufeff\U0001bca0-\U0001bca3"
                      "\U000e0100-\U000e01ef]")


def _label_ok(label: str) -> bool:
    """A label UTS 46 keeps: no control, unassigned, private-use or space character, no U+FFFD, no leading mark."""
    if label and unicodedata.category(label[0]).startswith("M"):
        return False
    return all(c != "\ufffd" and unicodedata.category(c) not in ("Cc", "Cf", "Cs", "Co", "Cn", "Zs", "Zl", "Zp") for c in label)


def _domain_to_ascii(domain: str) -> Optional[str]:
    """Domain to ASCII with beStrict false, as the reference's `URL` (Node's) does it: an ASCII name is lower cased,
    an `xn--` label in it included, unchecked; a name that is not ASCII goes through UTS 46 processing, approximated
    (module docstring), where an `xn--` label must decode to a valid label."""
    if domain.isascii():
        return domain.lower()
    stops = _IGNORED.sub("", _FULL_STOPS.sub(".", domain))
    if any(ord(c) > 0x7F and "." in unicodedata.normalize("NFKC", c) for c in stops):
        return None  # a character that maps to a dot (one dot leader, small full stop, ...) is disallowed
    mapped = unicodedata.normalize("NFC", unicodedata.normalize("NFKC", stops).lower())
    labels = []  # each label in Unicode, the form UTS 46 checks
    for label in mapped.split("."):
        if label[:4] == "xn--":
            try:
                decoded = label[4:].encode("ascii").decode("punycode")
            except (UnicodeError, ValueError):
                return None
            if decoded == "" or decoded.isascii() or unicodedata.normalize("NFC", decoded) != decoded:
                return None
            label = decoded
        if not _label_ok(label):
            return None
        labels.append(label)
    if not _bidi_ok(labels):
        return None
    result = ".".join(label if label.isascii() else "xn--" + label.encode("punycode").decode("ascii") for label in labels)
    return result or None


_RTL = ("R", "AL", "AN")


def _bidi_ok(labels: List[str]) -> bool:
    """CheckBidi (RFC 5893 section 2): in a name with a right-to-left label, every label keeps the Bidi rule."""
    classes = [[unicodedata.bidirectional(c) for c in label] for label in labels]
    if not any(c in _RTL for label in classes for c in label):
        return True
    for label in classes:
        if not label:
            continue
        if label[0] not in ("L", "R", "AL"):
            return False
        core = list(label)
        while len(core) > 1 and core[-1] == "NSM":
            core.pop()
        if label[0] == "L":
            allowed, ends = ("L", "EN", "ES", "CS", "ET", "ON", "BN", "NSM"), ("L", "EN")
        else:
            allowed, ends = ("R", "AL", "AN", "EN", "ES", "CS", "ET", "ON", "BN", "NSM"), ("R", "AL", "EN", "AN")
            if "EN" in label and "AN" in label:
                return False
        if any(c not in allowed for c in label) or core[-1] not in ends:
            return False
    return True


def _special_host(text: str) -> Optional[str]:
    """The host parser for an http or https URL: the serialised host, or None (failure)."""
    if text.startswith("["):
        if not text.endswith("]"):
            return None
        address = _ipv6(text[1:-1])
        return None if address is None else "[%s]" % _ipv6_text(address)
    domain = _utf8(_percent_decode(_scalars(text).encode("utf-8")))
    ascii_domain = _domain_to_ascii(domain)
    if ascii_domain is None or any(c in _FORBIDDEN_DOMAIN for c in ascii_domain):
        return None
    return _ipv4(ascii_domain) if _ends_in_number(ascii_domain) else ascii_domain


def _host_and_port(authority: str) -> Optional[Tuple[str, str]]:
    """The host state: the host up to a `:` outside brackets, and the port after it (digits, at most 65535)."""
    host, inside, port = "", False, None
    for index, c in enumerate(authority):
        if c == ":" and not inside:
            port = authority[index + 1:]
            break
        inside = True if c == "[" else False if c == "]" else inside
        host += c
    if port is not None:
        if host == "" or (port != "" and (not re.fullmatch(r"[0-9]+", port, re.A) or int(port) > 65535)):
            return None
    return host, port or ""


def _http_hostname(url: str) -> Optional[str]:
    """`new URL(url).hostname` when the URL parses with scheme http or https; None otherwise."""
    text = _url_input(url)
    scheme = _SCHEME.match(text)
    if not scheme or scheme.group(1).lower() not in ("http", "https"):
        return None
    rest = text[scheme.end():].lstrip("/\\")  # the special authority (ignore) slashes states
    authority = re.split(r"[/\\?#]", rest, maxsplit=1)[0]
    if "@" in authority:
        authority = authority[authority.rfind("@") + 1:]
        if authority == "":
            return None
    split = _host_and_port(authority)
    if split is None or split[0] == "":
        return None
    return _special_host(split[0])


def _parses_as_dashboards(url: str) -> bool:
    """`new URL(url).protocol === "fabric-dashboards:"`: the scheme, then the authority of a non-special URL (an opaque
    host, or an IPv6 address in brackets, and a port) is the only part that can fail."""
    text = _url_input(url)
    scheme = _SCHEME.match(text)
    if not scheme or scheme.group(1).lower() != "fabric-dashboards":
        return False
    rest = text[scheme.end():]
    if not rest.startswith("//"):
        return True  # a path or an opaque path
    authority = re.split(r"[/?#]", rest[2:], maxsplit=1)[0]
    if "@" in authority:
        authority = authority[authority.rfind("@") + 1:]
        if authority == "":
            return False
    split = _host_and_port(authority)
    if split is None:
        return False
    host = split[0]
    if host.startswith("["):
        return host.endswith("]") and _ipv6(host[1:-1]) is not None
    return not any(c in _FORBIDDEN_HOST for c in host)


# --- the contract's rules --------------------------------------------------------------------------------------------

def dashboards_link(service: str, instance: str, path: Optional[str] = None) -> str:
    """The open_link for the service `service.instance` (PL-1): its dashboard without `path`, or the page at `path` on
    its origin, encoded as Fabric Dashboards' `serviceLink` encodes it. Raises PageLinkError for what the grammar
    refuses, naming every problem."""
    problems = _link_problems(service, instance, path)
    if problems:
        raise PageLinkError("; ".join(problems))
    base = "fabric-dashboards://service/%s.%s" % (service, instance)
    return base if path is None or path == "" else "%s?path=%s" % (base, _form_encode(path))


def parse_dashboards_link(url: str) -> Dict[str, Any]:
    """Read an open_link: {"ok": True, "service", "instance", "path"?} or {"ok": False, "problems": [...]}."""
    if not isinstance(url, str):
        return {"ok": False, "problems": [_GRAMMAR]}
    if _js_length(url) > MAX_PAGE_LINK_LENGTH:
        return {"ok": False, "problems": ["an open_link is at most %d characters" % MAX_PAGE_LINK_LENGTH]}
    # The scheme and the host's verb are read without regard to case, as the host reads them.
    link = _PREFIX.sub("fabric-dashboards://service/", url, count=1)
    match = _SHAPE.match(link)
    if not match:
        return {"ok": False, "problems": [_GRAMMAR]}
    key = match.group(1)
    service, dot, instance = key.partition(".")
    if not match.group(2):
        problems = _link_problems(service, instance)
        return {"ok": False, "problems": problems} if problems else {"ok": True, "service": service, "instance": instance}
    # The parameters as the host's URL parser reads them: the query is the link's end, so the parser's strip of C0
    # and space at the end and its removal of tabs and newlines reach it; a second `?` stays part of a name.
    query = _form_parse(_url_input(match.group(2)))
    paths = [value for name, value in query if name == "path"]
    if len(paths) != 1:
        return {"ok": False, "problems": ["path is given more than once" if paths else "an open_link names its path"]}
    if any(name != "path" for name, _ in query):
        return {"ok": False, "problems": ["an open_link carries its path and nothing else"]}
    path = paths[0]
    if path == "":
        return {"ok": False, "problems": ["the path is empty; a link to the dashboard itself names no path"]}
    problems = _link_problems(service, instance, path)
    return {"ok": False, "problems": problems} if problems else {"ok": True, "service": service, "instance": instance, "path": path}


def _link_problems(service: Any, instance: Any, path: Any = None) -> List[str]:
    problems = []
    if not isinstance(service, str) or not SERVICE_ID.match(service):
        problems.append("the service is not a service id")
    if not isinstance(instance, str) or not INSTANCE.match(instance):
        problems.append("the instance is not an instance name")
    if path is None or path == "":
        return problems
    if not isinstance(path, str):
        problems.append("the path is not a path on the service origin")
    elif _js_length(path) > MAX_PAGE_PATH_LENGTH:
        problems.append("the path is at most %d characters" % MAX_PAGE_PATH_LENGTH)
    elif not ORIGIN_PATH.match(path) or _HOST_REFUSED.search(path) or _lone_surrogate(path):
        # The reference also asks that `new URL(path, base)` keeps the base's origin: a path-absolute string with no
        # backslash or control character always does, so the test is the three above.
        problems.append("the path is not a path on the service origin")
    elif _path_carries_credential(path):
        problems.append("the path could carry a token or a login code; signing in is the host's")
    return problems


def _path_carries_credential(path: str) -> bool:
    """A login-code route, or a query or fragment piece that could carry a credential (FL-7: a link carries none)."""
    path = _scalars(path)  # a surrogate pair is one character here, as in JavaScript (a lone one was refused)
    if _LOGIN.match(_resolved_pathname(path)):  # dot segments and letter case do not hide the route
        return True
    # The query and the fragment, a hash route's own query (`#/jobs?token=`) included, as pieces of one query.
    rest = re.sub(r"[#?]", "&", re.sub(r"^[?#]", "", re.sub(r"^[^?#]*", "", path, count=1), count=1))
    if not rest:
        return False
    raw = [value for values in raw_values(rest).values() for value in values]
    return (secret_value(rest) or any(secret_value(value) for value in raw)
            or any((value != "" and credential_name(name)) or secret_value(value) for name, value in _form_parse(rest)))


def is_loopback_page_url(url: Any) -> bool:
    """True for an `http` or `https` address on a loopback host: a local service's raw address."""
    if not isinstance(url, str):
        return False
    hostname = _http_hostname(url)
    return hostname is not None and _LOOPBACK.match(re.sub(r"\.\Z", "", hostname)) is not None


def _finding(instance_path: str, message: str) -> Dict[str, str]:
    return {"code": "FAC-SEM-143", "instancePath": instance_path, "message": message}


def page_link_findings(url: Any, instance_path: str, label: str) -> List[Dict[str, str]]:
    """FAC-SEM-143 for one link a document hands a person: a raw loopback address, or an open_link outside its
    grammar. A link is taken for an open_link behind JavaScript's whitespace, or as a URL parser sees it (C0 dropped
    around it, a tab or newline inside the scheme), and read as written."""
    if not isinstance(url, str):
        return []
    if is_loopback_page_url(url):
        return [_finding(instance_path, "%s hands a person a raw local address; give Fabric Dashboards' open_link (DEC-0123 PL-1)" % label)]
    bare = re.sub(r"^[\x00-\x20]+|[\x00-\x20]+\Z", "", url)
    if _DASHBOARDS_SCHEME.match(url) or _parses_as_dashboards(url):
        parsed = parse_dashboards_link(bare)
        if not parsed["ok"]:
            return [_finding(instance_path, "%s is not an open_link: %s (DEC-0123 PL-1)" % (label, "; ".join(parsed["problems"])))]
    return []


def input_request_link_findings(value: Any) -> List[Dict[str, str]]:
    """FAC-SEM-143 on an input request in URL mode (kind `interop-input-requests`): its `url` is a link a person opens."""
    requests = value.get("inputRequests") if isinstance(value, dict) else None
    if not isinstance(requests, dict):
        return []
    findings: List[Dict[str, str]] = []
    for key in js_keys(requests):
        request = requests[key]
        params = request.get("params") if isinstance(request, dict) else None
        if isinstance(params, dict) and params.get("mode") == "url":
            findings += page_link_findings(params.get("url"), "/inputRequests/%s/params/url" % key, "input request %s" % key)
    return findings


def page_link_rules(kind: str, value: Any) -> Optional[List[Dict[str, str]]]:
    """Kind `page-link` (`{url}`): a link a service, its tools or its messages hand a person, such as a tool answer's
    `open_link`. None for another kind."""
    if kind != "page-link":
        return None
    return page_link_findings(value.get("url") if isinstance(value, dict) else None, "/url", "the link")
