#!/usr/bin/env python3
"""The contract's one credential detector (Fabric Agent Contract DEC-0044, `src/secret-shape.ts` at the pin): a name
that can only carry a credential, a value shaped like one, a launch argument that carries one, and a URL that does
(LC-21). A port held to the contract's own answers by test/fixtures/contract/profile-vectors.json. Standard library
only. The dashboard kit's fabric-button.js carries its own copy of the name and value checks (FL-4).

It reads as the contract's ECMAScript does (FAA-136): ECMAScript's whitespace (Python's `\\s` also takes U+0085 and
U+001C to U+001F, and not U+FEFF), `.` stopping at every line terminator, ASCII case folding, an ASCII word boundary."""

from __future__ import annotations

import re
from typing import Dict, List
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
SECRET_VALUE = re.compile(r"(^bearer[%s]%s+|sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abposr]-[A-Za-z0-9-]{10,}"
                          r"|AKIA[0-9A-Z]{16}|glpat-[A-Za-z0-9_-]{20,})" % (JS_SPACE, _NOT_LINE_END), re.IGNORECASE | re.ASCII)
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
    return bool(JWT_SHAPE.search(value) or SECRET_VALUE.search(value) or _long_secret(value))


def _path_like(piece: str) -> bool:
    return bool(_PATH_LIKE.match(piece)) or (
        bool(re.search(r"[\\/]", piece))
        and (bool(re.search(r"\.[A-Za-z0-9]{1,8}\Z", piece)) or any(re.fullmatch(r"[a-z][a-z0-9_-]{2,}", s) for s in re.split(r"[\\/]", piece))))


def secret_argument(value: str) -> bool:
    """The same for a launch argument or a server's command and URL: a long run is looked for between path separators,
    so a folder path holding a session id is not taken for a key."""
    if JWT_SHAPE.search(value) or SECRET_VALUE.search(value) or _BEARER_INSIDE.search(value):
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
    pairs = urllib.parse.parse_qsl(text, keep_blank_values=True)
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


def secret_url(value: str) -> bool:
    """Whether a URL an MCP entry or a launch names carries a credential (LC-21): anything secret_argument finds, a
    password in its user information, or a query or fragment parameter whose name can only carry a credential and has
    a value, or whose value is shaped like one. A string that is not an absolute URL is checked as an argument only."""
    if secret_argument(value):
        return True
    # What WHATWG URL parsing does first: trim C0 controls and space from the ends (never other Unicode spaces, which it
    # refuses), then remove every tab, CR and LF.
    value = re.sub(r"[\t\n\r]", "", value.strip(_C0_OR_SPACE))
    if not _SCHEME.match(value):
        return False  # not an absolute URL (WHATWG URL parsing refuses it)
    scheme, _, rest = value.partition(":")
    if scheme.lower() in _SPECIAL:
        # A special scheme's authority starts after every slash or backslash that follows `scheme:` (WHATWG's special
        # authority ignore slashes state), and a backslash before the query or fragment reads as a slash: `https:u:p@h`
        # and `https:\\u:p@h` both carry the password p (0.56.0 unit r6).
        cut = min([at for at in (rest.find("?"), rest.find("#")) if at >= 0] or [len(rest)])
        value = scheme + "://" + (rest[:cut].replace("\\", "/") + rest[cut:]).lstrip("/")
    try:
        parts = urllib.parse.urlsplit(value)
    except ValueError:
        return False
    if not parts.scheme:
        return False
    if parts.password:
        return True
    for part in (parts.query, parts.fragment):
        for name, raws in raw_values(part).items():
            if any((raw != "" and credential_name(name)) or secret_value(raw) for raw in raws):
                return True
    return False
