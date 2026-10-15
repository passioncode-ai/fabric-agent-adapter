"""Identifier equality (contract DEC-0076): two identifiers are the same when their normal forms are equal.

A port of the contract's `src/identifiers.ts`, held to its `fixtures/vectors/identifiers.json`. The normal form of a URI
is RFC 3986 §6.2.2 syntax-based normalization: the scheme and the host lower-cased and percent-encoding hex upper-cased
(§6.2.2.1), percent-encoded unreserved characters decoded (§6.2.2.2), dot segments removed from a hierarchical path
(§6.2.2.3), and only the leading ones from a rootless path; nothing scheme-based (§6.2.3). A `urn:` URI follows RFC 8141
§3.1 instead: the scheme and the NID lower-cased, percent-encoding hex upper-cased, nothing decoded, the NSS's case kept,
the r-, q- and f-components ignored. A string that is not a URI by RFC 3986's `URI` production is its own normal form.
Nothing here raises. Standard library only; this file is byte-identical in both skills' `scripts/`."""
from __future__ import annotations

import re
from typing import Any, Optional, Tuple

_UNRESERVED = r"A-Za-z0-9\-._~"
_SUB_DELIMS = r"!$&'()*+,;="
_PCT = r"%[0-9A-Fa-f]{2}"


def _run(chars: str) -> "re.Pattern[str]":
    """`*( <chars> / pct-encoded )`, linear: one character class beside one fixed triplet."""
    return re.compile(r"(?:[%s]|%s)*" % (chars, _PCT), re.ASCII)


_USERINFO = _run(_UNRESERVED + _SUB_DELIMS + ":")
_REG_NAME = _run(_UNRESERVED + _SUB_DELIMS)
_PATH = _run(_UNRESERVED + _SUB_DELIMS + ":@/")
_QUERY = _run(_UNRESERVED + _SUB_DELIMS + ":@/?")
_PORT = re.compile(r"[0-9]*", re.ASCII)
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*", re.ASCII)

# RFC 3986 §3.2.2: IP-literal = "[" ( IPv6address / IPvFuture ) "]".
_H16 = "[0-9A-Fa-f]{1,4}"
_DEC_OCTET = "(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
_IPV4 = r"%s(?:\.%s){3}" % (_DEC_OCTET, _DEC_OCTET)
_LS32 = "(?:%s:%s|%s)" % (_H16, _H16, _IPV4)
_IPV6 = "|".join([
    "(?:%s:){6}%s" % (_H16, _LS32),
    "::(?:%s:){5}%s" % (_H16, _LS32),
    "(?:%s)?::(?:%s:){4}%s" % (_H16, _H16, _LS32),
    "(?:(?:%s:){0,1}%s)?::(?:%s:){3}%s" % (_H16, _H16, _H16, _LS32),
    "(?:(?:%s:){0,2}%s)?::(?:%s:){2}%s" % (_H16, _H16, _H16, _LS32),
    "(?:(?:%s:){0,3}%s)?::%s:%s" % (_H16, _H16, _H16, _LS32),
    "(?:(?:%s:){0,4}%s)?::%s" % (_H16, _H16, _LS32),
    "(?:(?:%s:){0,5}%s)?::%s" % (_H16, _H16, _H16),
    "(?:(?:%s:){0,6}%s)?::" % (_H16, _H16),
])
_IP_LITERAL = re.compile(r"\[(?:%s|[Vv][0-9A-Fa-f]+\.[%s%s:]+)\]" % (_IPV6, _UNRESERVED, _SUB_DELIMS), re.ASCII)

# RFC 8141 §2: NID = (alphanum) 0*30(ldh) (alphanum), then ":" and a non-empty NSS.
_URN_NAME = re.compile(r"([A-Za-z0-9][A-Za-z0-9-]{0,30}[A-Za-z0-9]):(.+)", re.ASCII | re.DOTALL)
_SPLIT = re.compile(r"([^:/?#]+):(?://([^/?#]*))?([^?#]*)(?:\?([^#]*))?(?:#(.*))?", re.DOTALL)
_TRIPLET = re.compile(r"%([0-9A-Fa-f]{2})")
_UNRESERVED_CHAR = re.compile(r"[A-Za-z0-9\-._~]", re.ASCII)


def _percent(text: str, keep_encoded: bool = False) -> str:
    """Percent-encoding hex upper-cased (§6.2.2.1), and unreserved characters decoded unless ``keep_encoded``."""
    def one(match: "re.Match[str]") -> str:
        char = chr(int(match.group(1), 16))
        return char if not keep_encoded and _UNRESERVED_CHAR.fullmatch(char) else "%" + match.group(1).upper()
    return _TRIPLET.sub(one, text)


def _strip_leading_dots(path: str) -> str:
    """A rootless path loses its leading "./" and "../" segments while what is left stays rootless (DEC-0076)."""
    start = 0
    while path.startswith("./", start) or path.startswith("../", start):
        start += 2 if path.startswith("./", start) else 3
    rest = path[start:]
    return path if rest == "" or rest.startswith("/") else rest


def _remove_dot_segments(path: str) -> str:
    """RFC 3986 §5.2.4 remove_dot_segments over a path whose "." and ".." are already decoded."""
    absolute = path.startswith("/")
    segments = (path[1:] if absolute else path).split("/")
    output = []
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment in (".", ".."):
            if segment == ".." and output:
                output.pop()
            if last:  # a dot segment that ends the path leaves it ending in "/"
                output.append("")
            continue
        output.append(segment)
    return ("/" if absolute else "") + "/".join(output)


def _authority_parts(authority: str) -> Optional[Tuple[Optional[str], str, Optional[str]]]:
    at = authority.rfind("@")
    userinfo = None if at == -1 else authority[:at]
    host_port = authority if at == -1 else authority[at + 1:]
    bracket = host_port.find("]") if host_port.startswith("[") else -1
    colon = host_port.find(":", 0 if bracket == -1 else bracket)
    host = host_port if colon == -1 else host_port[:colon]
    port = None if colon == -1 else host_port[colon + 1:]
    if userinfo is not None and not _USERINFO.fullmatch(userinfo):
        return None
    if port is not None and not _PORT.fullmatch(port):
        return None
    if not (_IP_LITERAL.fullmatch(host) if host.startswith("[") else _REG_NAME.fullmatch(host)):
        return None
    return userinfo, host, port


def _parse(text: str) -> Optional[Tuple[str, Optional[str], str, Optional[str], Optional[str]]]:
    """RFC 3986 Appendix B's split, then each component checked against its §3 production; None when one fails."""
    match = _SPLIT.fullmatch(text)
    if not match:
        return None
    scheme, authority, path, query, fragment = match.groups()
    path = path or ""
    if not _SCHEME.fullmatch(scheme) or not _PATH.fullmatch(path):
        return None
    if query is not None and not _QUERY.fullmatch(query):
        return None
    if fragment is not None and not _QUERY.fullmatch(fragment):
        return None
    if authority is not None and _authority_parts(authority) is None:
        return None
    if authority is None and path == "":
        return None
    return scheme, authority, path, query, fragment


def _urn_form(authority: Optional[str], path: str, query: Optional[str]) -> str:
    name = _URN_NAME.fullmatch(path)
    path = "%s:%s" % (name.group(1).lower(), _percent(name.group(2), True)) if name else _percent(path, True)
    # A "?" not followed by "+" or "=" is no URN component (RFC 8141 §2): it is kept, never dropped unread.
    kept = "?" + _percent(query, True) if query is not None and not re.match(r"[+=]", query) else ""
    auth = "//" + _percent(authority, True) if authority is not None else ""
    return "urn:%s%s%s" % (auth, path, kept)


def _generic_form(scheme: str, authority: Optional[str], path: str, query: Optional[str], fragment: Optional[str]) -> str:
    auth = ""
    if authority is not None:
        userinfo, host, port = _authority_parts(authority)  # type: ignore[misc]
        # The host is case-insensitive (§3.2.2); its remaining percent triplets keep upper-case hex.
        lowered = re.sub(r"%[0-9a-f]{2}", lambda m: m.group(0).upper(), _percent(host).lower())
        auth = "//%s%s%s" % ("" if userinfo is None else _percent(userinfo) + "@", lowered, "" if port is None else ":" + port)
    decoded = _percent(path)
    hierarchical = authority is not None or decoded.startswith("/")
    out = _remove_dot_segments(decoded) if hierarchical else _strip_leading_dots(decoded)
    if authority is None and out.startswith("//"):  # it would read as an authority: keep the decoded path
        out = decoded
    q = "" if query is None else "?" + _percent(query)
    f = "" if fragment is None else "#" + _percent(fragment)
    return "%s:%s%s%s%s" % (scheme.lower(), auth, out, q, f)


def normal_identifier(value: Any) -> Optional[str]:
    """The normal form of an identifier: a URI's syntax-normalized form (RFC 3986 §6.2.2; RFC 8141 §3.1 for `urn:`),
    any other string as it is, None for a value that is not a string. The contract's `normalIdentifier`."""
    if not isinstance(value, str):
        return None
    parts = _parse(value)
    if parts is None:
        return value
    scheme, authority, path, query, fragment = parts
    return _urn_form(authority, path, query) if scheme.lower() == "urn" else _generic_form(scheme, authority, path, query, fragment)


def _double(value: Any) -> float:
    try:
        return float(value)
    except OverflowError:
        return float("inf") if value > 0 else float("-inf")


def _strict_equal(a: Any, b: Any) -> bool:
    """JavaScript's === on parsed JSON: numbers by value, booleans only with booleans, objects by identity."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return _double(a) == _double(b)  # as JavaScript holds them: 2**53 + 1 is 2**53
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        return a is b
    return type(a) is type(b) and a == b


def same_identifier(a: Any, b: Any) -> bool:
    """Two identifiers are the same when their normal forms are equal (DEC-0076). A value that is not a string is no
    identifier and is compared as it is (JavaScript's ===). The contract's `sameIdentifier`."""
    if not isinstance(a, str) or not isinstance(b, str):
        return _strict_equal(a, b)
    return normal_identifier(a) == normal_identifier(b)
