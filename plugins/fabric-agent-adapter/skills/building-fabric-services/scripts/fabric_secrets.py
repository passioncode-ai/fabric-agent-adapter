#!/usr/bin/env python3
"""The contract's one credential detector (Fabric Agent Contract DEC-0044, `src/secret-shape.ts` at the pin): a name
that can only carry a credential, a value shaped like one, a launch argument that carries one, and a URL that does
(LC-21). A port held to the contract's own answers by test/fixtures/contract/profile-vectors.json. Standard library
only. The dashboard kit's fabric-button.js carries its own copy of the name and value checks (FL-4).

It reads as the contract's ECMAScript does (FAA-136): ECMAScript's whitespace (Python's `\\s` also takes U+0085 and
U+001C to U+001F, and not U+FEFF), `.` stopping at every line terminator, ASCII case folding, an ASCII word boundary."""
# Example URLs write their scheme in angle brackets: read `<https>` as `https` (FAA-212).

from __future__ import annotations

import bisect
import ipaddress
import re
from typing import Dict, List, Optional, Sequence, Tuple
import unicodedata
import urllib.parse

CREDENTIAL_WORDS = (
    "token", "secret", "password", "passwd", "pass", "passphrase", "credential", "credentials", "cookie", "authorization",
    "bearer", "jwt", "otp", "apikey", "signature", "sig",
    "accesstoken", "idtoken", "authtoken", "refreshtoken", "sessionid", "sessiontoken", "logincode", "authcode", "privatekey",
    "clientsecret", "secretkey", "accesskey",
)
CREDENTIAL_PAIRS: Dict[str, tuple] = {
    "key": ("private", "api", "access", "secret", "session", "auth", "signing", "encryption", "master", "client", "login", "refresh"),
    "auth": ("token", "code", "header"),
    "session": ("token", "id"),
    "code": ("login", "auth", "access", "session"),
}
#: ECMAScript's \s, as a character class body.
JS_SPACE = "\t\n\x0b\x0c\r \xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
_NOT_LINE_END = "[^\n\r\u2028\u2029]"  # ECMAScript's `.` without the s flag
JWT_SHAPE = re.compile(r"eyJ[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]*")
_URL_BASE64_RUN = re.compile(r"[A-Za-z0-9_-]*")


def jwt_spans(text: str, first: bool = False) -> List[Tuple[int, int]]:
    """The spans JWT_SHAPE matches in a text, leftmost and not overlapping, read in one pass (the contract's `jwtSpans`,
    FAA-313): the regular expression backtracks from every `eyJ` of a long run, quadratic in it, while every `eyJ` of
    one run shares that run's end, so only its first is tried, and a match ends where its third segment's run ends.
    `first` stops at the first match."""
    spans: List[Tuple[int, int]] = []
    at = text.find("eyJ")
    while at >= 0:
        one = _URL_BASE64_RUN.match(text, at + 3).end()
        resume = one
        if one - at - 3 >= 2 and text[one:one + 1] == ".":
            two = _URL_BASE64_RUN.match(text, one + 1).end()
            if two - one - 1 >= 2 and text[two:two + 1] == ".":
                three = _URL_BASE64_RUN.match(text, two + 1).end()
                spans.append((at, three))
                if first:
                    break
                resume = three
        at = text.find("eyJ", resume)
    return spans


def has_jwt(text: str) -> bool:
    """Whether JWT_SHAPE matches anywhere in a text, read in one pass (the contract's `hasJwt`, FAA-313)."""
    return bool(jwt_spans(text, True))
#: Where a provider key's prefix may start (DEC-0151): the start of a value, a character that is no ASCII letter or
#: digit, or an escape (a percent-escape, single or double, a backslash escape, an octal, `\\x` with two hex digits,
#: `\\u` with four, an ESC colour sequence, raw or escaped). A consuming group, as the contract writes it.
_KEY_BOUNDARY = (r"(?:^|[^A-Za-z0-9]|%[0-9A-Fa-f]{2}|\\[nrt\"']|\\u[0-9A-Fa-f]{4}|\\x[0-9A-Fa-f]{2}|\\[bfv0ae]|\\[0-7]{1,3}"
                 r"|%25[0-9A-Fa-f]{2}|\x1b\[[0-9;:]*m|(?:\\u001[bB]|\\x1[bB]|\\e|\\033|\\33)\[[0-9;:]*m)")
#: The provider keys' shapes, prefixes in their canonical case only (DEC-0151 item 7: `SK-` or `GHP_` is no key). An
#: `sk-` key holds, within 256 characters, a digit and an upper-case letter with 16 or more characters, or a digit with
#: 32 or more; the look-aheads are bounded to 255 characters and lazy, so a long run of prefixes reads in linear time.
_PROVIDER_KEYS = (r"(?:sk-(?=[A-Za-z0-9_-]{0,255}?[0-9])(?:(?=[A-Za-z0-9_-]{0,255}?[A-Z])[A-Za-z0-9_-]{16,}|[A-Za-z0-9_-]{32,})"
                  r"|gh[pousr]_[A-Za-z0-9]{20,}|xox[abposr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|glpat-[A-Za-z0-9_-]{20,})")
#: The contract's SECRET_VALUE at the pin (DEC-0151): `Bearer ` at a value's start in any case, or a provider key after a
#: boundary. No case-insensitive flag; digits are ASCII. A match includes its boundary character: callers test, never
#: read the matched text or its index.
SECRET_VALUE = re.compile("(^[Bb][Ee][Aa][Rr][Ee][Rr][" + JS_SPACE + "]" + _NOT_LINE_END + "+|" + _KEY_BOUNDARY + _PROVIDER_KEYS + ")")
_LONG_RUN = re.compile(r"[A-Za-z0-9+/=_-]{40,}")
_BEARER_INSIDE = re.compile(r"(?<![A-Za-z0-9_])bearer[%s]+(?=[A-Za-z0-9._~+/-]*[0-9])[A-Za-z0-9._~+/-]{12,}=*" % JS_SPACE,
                            re.IGNORECASE | re.ASCII)
_PATH_LIKE = re.compile(r"^(?:[/~.]|[A-Za-z]:[\\/]|[a-z][a-z0-9+.-]*://)", re.IGNORECASE | re.ASCII)
_WORD_SPLIT = re.compile("[%s._-]+" % JS_SPACE)
_ARGUMENT_SPLIT = re.compile("[%s=]" % JS_SPACE)
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
#: WHATWG's special schemes that carry an authority with user information (file has none).
_SPECIAL = ("ftp", "http", "https", "ws", "wss")


def name_words(name: str) -> List[str]:
    """A name's words: split at `.`, `_`, `-` and camelCase humps, lowercased (`APIKey` is `api key`)."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    return [w.lower() for w in _WORD_SPLIT.split(spaced) if w]


def _with_singulars(words: List[str]) -> List[str]:
    return words + [w[:-1] for w in words if len(w) > 2 and w.endswith("s")]


def credential_name(name: str) -> bool:
    """Whether a name — a parameter, a header, an environment variable, a config key — can only carry a credential."""
    split = name_words(name)
    words = _with_singulars(split)
    if any(w in CREDENTIAL_WORDS for w in words):
        return True
    if len(split) == 1 and any(w in CREDENTIAL_PAIRS for w in words):
        return True
    return any(word in words and any(p in words for p in partners) for word, partners in CREDENTIAL_PAIRS.items())


def _long_secret(value: str) -> bool:
    return any(re.search(r"[a-z]", run) and re.search(r"[A-Z]", run) and re.search(r"[0-9]", run) for run in _LONG_RUN.findall(value))


def secret_value(value: str) -> bool:
    """A JWT anywhere, a provider key or `Bearer …`, or a long base64 run mixing upper case, lower case and digits."""
    return bool(has_jwt(value) or SECRET_VALUE.search(value) or _long_secret(value))


def _path_like(piece: str) -> bool:
    return bool(_PATH_LIKE.match(piece)) or (
        bool(re.search(r"[\\/]", piece))
        and (bool(re.search(r"\.[A-Za-z0-9]{1,8}\Z", piece)) or any(re.fullmatch(r"[a-z][a-z0-9_-]{2,}", s) for s in re.split(r"[\\/]", piece))))


def secret_argument(value: str) -> bool:
    """The same for a launch argument or a server's command and URL: a long run is looked for between path separators,
    so a folder path holding a session id is not taken for a key."""
    if has_jwt(value) or SECRET_VALUE.search(value) or _BEARER_INSIDE.search(value):
        return True
    for piece in _ARGUMENT_SPLIT.split(value):
        if _path_like(piece):
            if any(_long_secret(part) for part in re.split(r"[\\/]", piece)):
                return True
        elif _long_secret(piece):
            return True
    return False


def _decode_keeping_plus(raw: str) -> str:
    """decodeURIComponent: a malformed escape or bytes that are not UTF-8 leave the raw text."""
    if re.search(r"%(?![0-9A-Fa-f]{2})", raw):
        return raw
    try:
        return urllib.parse.unquote_to_bytes(raw).decode("utf-8")
    except UnicodeDecodeError:
        return raw


def _form_name(text: str) -> str:
    # URLSearchParams drops one leading `?` from the text it is given (0.56.0 unit r7).
    pairs = urllib.parse.parse_qsl(text[1:] if text.startswith("?") else text, keep_blank_values=True)
    return pairs[0][0] if pairs else ""


def raw_values(query: str) -> Dict[str, List[str]]:
    """Each query or fragment piece's raw value by its decoded name, with `+` kept."""
    values: Dict[str, List[str]] = {}
    for piece in query.split("&"):
        if piece == "":
            continue
        at = piece.find("=")
        name = _form_name(piece if at < 0 else piece[:at])
        values.setdefault(name, []).append("" if at < 0 else _decode_keeping_plus(piece[at + 1:]))
    return values


#: The C0 controls and space, U+0000 to U+0020: what WHATWG URL parsing trims from a URL's ends.
_C0_OR_SPACE = "".join(map(chr, range(0x21)))


_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


# The WHATWG host parser, enough to know when `new URL` refuses a host (FAA-98, moved here from fabric_connections for
# secret_url in FAA-309, so the module still ships alone in adapting-projects-to-fabric).
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


def _percent_encode(text: str, also: str) -> str:
    """WHATWG's percent-encoding of a query or a fragment: every C0 control, space, `"`, `<`, `>`, every code point
    above U+007E and the characters in `also`, as UTF-8 %XX (a lone surrogate as U+FFFD, as a USVString reads it).
    `new URL` hands the contract's secretUrl the text in this form, so a malformed escape left in it is read the same
    way by both ports (0.56.0 unit r8)."""
    out = []
    for char in _LONE_SURROGATE.sub("\ufffd", text):
        if ord(char) <= 0x20 or ord(char) > 0x7E or char in '"<>' or char in also:
            out.append("".join("%%%02X" % byte for byte in char.encode("utf-8")))
        else:
            out.append(char)
    return "".join(out)


def url_parts(value: str) -> Tuple[str, str, str]:
    """The password, query and fragment of an absolute URL as WHATWG URL parsing splits them, read by hand: urlsplit
    refuses a `[` or `]` outside an IPv6 host (`<https>://u:p[w@h/`), where `new URL` reads the password (0.56.0 unit
    r7). The fragment starts at the first `#`, the query at the first `?` before it. A special scheme's authority starts
    after every slash or backslash that follows `scheme:` (the special authority ignore slashes state) and ends at the
    next slash, backslash, `?` or `#`, so `<https>:u:p@h` and `<https>:\\u:p@h` carry the password p; any other scheme
    has an authority only after `//`, and `file` has no user information. The user information ends at the authority's
    last `@`, and the password follows its first `:`. The host is not checked here: secret_url refuses first a URL
    whose host or port `new URL` refuses (url_refused, FAA-309)."""
    scheme, _, rest = value.partition(":")
    rest, _, fragment = rest.partition("#")
    rest, _, query = rest.partition("?")
    lowered = scheme.lower()
    if lowered in _SPECIAL:
        authority = rest.replace("\\", "/").lstrip("/").partition("/")[0]
    elif lowered != "file" and rest.startswith("//"):
        authority = rest[2:].partition("/")[0]
    else:
        authority = ""
    userinfo, at, _ = authority.rpartition("@")
    return ((userinfo.partition(":")[2] if at else ""), _percent_encode(query, "'" if lowered in _SPECIAL or lowered == "file" else ""),  # file is special too
            _percent_encode(fragment, "`"))


_url_parts = url_parts  # the name before FAA-250, kept for code that reached it


def url_refused(value: str) -> bool:
    """Whether `new URL` refuses an absolute URL (trimmed as secret_url trims it) for its host or port (FAA-309), read
    with the same authority url_parts reads: a special scheme's host through the WHATWG host parser and the IDNA reading
    of FAA-98 (`_domain_ok`), never empty; `file`'s host, after `//`, the same, empty allowed; another scheme's host,
    after `//`, without a forbidden host code point, and empty only with no user information and no `:` after it (an
    empty port is refused too); a port of ASCII digits up to 65535. Where the reading is unsure, the host is taken as
    valid (the detector's safe side)."""
    value = _LONE_SURROGATE.sub("\ufffd", value)
    scheme, _, rest = value.partition(":")
    rest = rest.partition("#")[0].partition("?")[0]
    lowered = scheme.lower()
    if lowered in _SPECIAL:
        authority = rest.replace("\\", "/").lstrip("/").partition("/")[0]
    elif lowered == "file":
        rest = rest.replace("\\", "/")
        if not rest.startswith("//"):
            return False
        host = rest[2:].partition("/")[0]
        return not (host == "" or re.fullmatch(r"[A-Za-z][:|]", host) or _domain_ok(host))
    elif rest.startswith("//"):
        authority = rest[2:].partition("/")[0]
    else:
        return False
    hostport = authority.rpartition("@")[2]
    if hostport.startswith("["):
        close = hostport.find("]")
        if close < 0:
            return True
        host, after = hostport[:close + 1], hostport[close + 1:]
        if after and not after.startswith(":"):
            return True
        port = after[1:]
    else:
        host, _, port = hostport.partition(":")
    if port and not (port.isascii() and port.isdigit() and int(port) <= 65535):
        return True
    if lowered in _SPECIAL:
        return host == "" or not _domain_ok(host)
    if host.startswith("["):
        return not _ipv6_ok(host[1:-1])
    return any(c in _FORBIDDEN_HOST for c in host) or (host == "" and ("@" in authority or ":" in hostport))


def secret_url(value: str) -> bool:
    """Whether a URL an MCP entry or a launch names carries a credential (LC-21): anything secret_argument finds, a
    password in its user information, or a query or fragment parameter whose name can only carry a credential and has
    a value, or whose value is shaped like one. A string that is not an absolute URL, or one whose host or port
    `new URL` refuses (url_refused, FAA-309), is checked as an argument only, as the Node twin's secretUrl reads it."""
    return _url_credential(value, hosts=True)


def _url_credential(value: str, hosts: bool) -> bool:
    """secret_url; with `hosts` False the host is not checked, as repository_credential reads a repository's parameters
    whatever its host (the Node twin's repositoryParts)."""
    if secret_argument(value):
        return True
    # What WHATWG URL parsing does first: trim C0 controls and space from the ends (never other Unicode spaces, which it
    # refuses), then remove every tab, CR and LF.
    value = re.sub(r"[\t\n\r]", "", value.strip(_C0_OR_SPACE))
    if not _SCHEME.match(value):
        return False  # not an absolute URL (WHATWG URL parsing refuses it)
    if hosts and url_refused(value):
        return False  # `new URL` refuses its host or port, so the Node twin reads it as an argument only (FAA-309)
    password, query, fragment = url_parts(value)
    if password:
        return True
    for part in (query, fragment):
        for name, raws in raw_values(part).items():
            if any((raw != "" and credential_name(name)) or secret_value(raw) for raw in raws):
                return True
    return False


_REPOSITORY_URI = re.compile(r"\A([A-Za-z][A-Za-z0-9+.-]*:(?://[^/?#]*)?)([^?#]*)(.*)\Z", re.S)
_REPOSITORY_NAME = re.compile(r"(?:[a-z0-9._-]+|[A-Za-z._-]+)\Z")  # lower case, or letters with no digit (readings 8)
_REPOSITORY_AUTHORITY = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
#: A repository name's own key shapes, boundary-free and case-sensitive (DEC-0151): SECRET_VALUE takes a consuming
#: boundary, so composed after a separator look-behind it would miss a key after `-`, `.` or `_`.
_REPOSITORY_KEYS = r"sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abposr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|glpat-[A-Za-z0-9_-]{20,}"
_KEY_AT_A_WORD = re.compile(r"(?:\A|(?<=[._-]))(?:%s)" % _REPOSITORY_KEYS)
_JWT_AT_A_WORD = re.compile(r"(?:\A|(?<=[._-]))%s" % JWT_SHAPE.pattern)


def repository_name(piece: str) -> bool:
    """Whether a path segment reads as a repository's name: lower case, or letters with no digit, with no provider
    key's or JWT's shape (`sk-`, `ghp_`, `xoxb-`, `AKIA`, `eyJ`) at its start or after a `.`, `_` or `-` (0.62.0
    readings 9 and 10), so a letters-only key is still a key while `task-pipeline-dashboard`, which holds an `sk-` shape
    inside a word, is a name."""
    return bool(_REPOSITORY_NAME.match(piece)) and not _KEY_AT_A_WORD.search(piece) and not _JWT_AT_A_WORD.search(piece)


def ascii_decoded(text: str) -> str:
    """Every `%XX` escape of an ASCII character decoded, the rest left as written: how a repository's path and user
    information are read as well as written, since git and hosts decode them (`%73k-` is `sk-`, `u%3Apw` is `u:pw`;
    0.62.0 readings 11). The Node twin is asciiDecoded."""
    return re.sub(r"%([0-7][0-9A-Fa-f])", lambda escape: chr(int(escape.group(1), 16)), text)


def repository_password(value: str) -> bool:
    """Whether a repository URI's user information holds a password, in any scheme, `file` too: every slash and
    backslash after the colon skipped, then up to the next `/`, `?` or `#`, a backslash kept in the user. That one
    reading holds git's (`<https>://h\\u:pw@x/r`), curl's (`<https>:///h\\u:pw@x`) and the URL standard's
    (`<https>:///u:pw@h`, which stops at a backslash, a prefix of it) (0.62.0 readings 10 to 14). The user information
    ends at the last `@`; a password follows its first `:`, as written or ascii_decoded. The Node twin is
    repositoryPassword."""
    value = re.sub(r"[\t\n\r]", "", value.strip(_C0_OR_SPACE))
    scheme, colon, rest = value.partition(":")
    authorities = [re.match(r"[^/?#]*", rest.lstrip("/\\")).group(0)] if colon else []
    users = [authority.rpartition("@")[0] for authority in authorities]
    return any(user.partition(":")[2] for user in users + [ascii_decoded(user) for user in users])


def repository_credential(value: str) -> bool:
    """FAA-198 (0.62.0 readings 6 and 7): whether a repository URI carries a credential: in its scheme and authority (a
    user), in its query or fragment as secret_url reads them, or as a path segment shaped like a key. A path segment in
    lower case, or of letters with no digit (task-pipeline-dashboard, Task-Pipeline-Dashboard), is the repository's
    name, never a key, though it reads as an `sk-` shape, unless a key's shape starts it or follows a `.`, `_` or `-` in
    it (repository_name); a segment is read as written and ascii_decoded. A
    user outside a URL's authority (an scp form, `https:user@host/path`) counts as one: a user is an authority's."""
    if "@" in value and not _REPOSITORY_AUTHORITY.match(value):
        return True
    match = _REPOSITORY_URI.match(value)
    if not match:
        return secret_argument(value)
    head, path, tail = match.groups()
    if repository_password(value):
        return True
    odd = [piece for written in (path, ascii_decoded(path)) for piece in re.split(r"[/\\:]", written)
           if piece and not repository_name(piece)]
    # the scheme and authority decoded too: git sends `https://%67hp_...@h` with its user decoded (unit reading 12)
    return _url_credential(head + tail, hosts=False) or secret_argument(ascii_decoded(head)) or any(secret_argument(piece) for piece in odd)
