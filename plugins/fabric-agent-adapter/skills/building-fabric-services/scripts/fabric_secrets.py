#!/usr/bin/env python3
"""The contract's one credential detector (Fabric Agent Contract DEC-0044, `src/secret-shape.ts` at the pin): a name
that can only carry a credential, a value shaped like one, a launch argument that carries one, and a URL that does
(LC-21). A port held to the contract's own answers by test/fixtures/contract/profile-vectors.json. Standard library
only. The dashboard kit's fabric-button.js carries its own copy of the name and value checks (FL-4)."""

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
JWT_SHAPE = re.compile(r"eyJ[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]*")
SECRET_VALUE = re.compile(r"(^bearer\s.+|sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abposr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|glpat-[A-Za-z0-9_-]{20,})",
                          re.IGNORECASE | re.DOTALL)
_LONG_RUN = re.compile(r"[A-Za-z0-9+/=_-]{40,}")
_BEARER_INSIDE = re.compile(r"\bbearer\s+(?=[A-Za-z0-9._~+/-]*\d)[A-Za-z0-9._~+/-]{12,}=*", re.IGNORECASE)
_PATH_LIKE = re.compile(r"^(?:[/~.]|[A-Za-z]:[\\/]|[a-z][a-z0-9+.-]*://)", re.IGNORECASE)
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def name_words(name: str) -> List[str]:
    """A name's words: split at `.`, `_`, `-` and camelCase humps, lowercased (`APIKey` is `api key`)."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    return [w.lower() for w in re.split(r"[\s._-]+", spaced) if w]


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
        and (bool(re.search(r"\.[A-Za-z0-9]{1,8}$", piece)) or any(re.fullmatch(r"[a-z][a-z0-9_-]{2,}", s) for s in re.split(r"[\\/]", piece))))


def secret_argument(value: str) -> bool:
    """The same for a launch argument or a server's command and URL: a long run is looked for between path separators,
    so a folder path holding a session id is not taken for a key."""
    if JWT_SHAPE.search(value) or SECRET_VALUE.search(value) or _BEARER_INSIDE.search(value):
        return True
    for piece in re.split(r"[\s=]", value):
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


def secret_url(value: str) -> bool:
    """Whether a URL an MCP entry or a launch names carries a credential (LC-21): anything secret_argument finds, a
    password in its user information, or a query or fragment parameter whose name can only carry a credential and has
    a value, or whose value is shaped like one. A string that is not an absolute URL is checked as an argument only."""
    if secret_argument(value):
        return True
    if not _SCHEME.match(value.strip()):
        return False  # not an absolute URL (WHATWG URL parsing refuses it)
    try:
        parts = urllib.parse.urlsplit(value.strip())
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
