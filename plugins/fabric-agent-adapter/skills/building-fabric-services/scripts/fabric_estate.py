#!/usr/bin/env python3
"""`estate-record/1` (Fabric Agent Contract DEC-0055): verify an estate revision and check its rules.

One revision of one person's estate: the passkeys that sign it, the machines with their device keys and hub-key
certificates, the packages placed per machine, secret placements by reference, share grants and revocations. A
revision names its parent's digest and is signed by a passkey assertion (WebAuthn Level 3, offline) over a challenge
derived from its own digest. This is the contract's `src/estate-record-rules.ts`, `src/webauthn.ts` and `src/p256.ts`
at the pin, ported answer for answer and held to the contract's own vectors (`test/fixtures/contract/estate-vectors.json`):

- ``verify_estate_record(record, at=..., parent=... | authorities=...)`` — the verdict a machine applies a revision on,
  after it has checked the revision against `estate-record.schema.json` (the verifier does not check the schema);
- ``estate_record_rules(kind, value)`` — FAC-SEM-072…076 for `estate-record`, `estate-record-revision` and
  `estate-placement`;
- ``hub_key_certified(record, kid, x, at)`` — DL-14: a delegation verifier that reads the estate record trusts a token's
  `kid` only while a current revision certifies it for a machine (``fabric_delegation`` calls it).

Standard library only. ES256 is verified here in pure Python (P-256, FIPS 186-5 / SEC 1); EdDSA by the Ed25519 verifier
in ``fabric_delegation``.
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_delegation as _delegation  # noqa: E402 - beside this file: RFC 8785, Ed25519, small-order keys
import fabric_secrets as _secrets  # noqa: E402 - beside this file: the contract's credential detector

ESTATE_RECORD_SCHEMA = "estate-record/1"
ESTATE_CHALLENGE_TYPE = "estate-revision/1"
MAX_VALIDITY_SECONDS = 30 * 24 * 60 * 60
#: How far ahead of the verifier's clock a signed `issuedAt` may be before it is `not-yet-valid` (DEC-0066): the one
#: skew of the relay family's and the estate record's times (`CLOCK_SKEW_SECONDS` in the contract's `src/rfc3339.ts`).
CLOCK_SKEW_SECONDS = 60
ASSERTION_ALGORITHMS = ("ES256", "EdDSA")
FLAGS = {"UP": 0x01, "UV": 0x04, "BE": 0x08, "BS": 0x10, "AT": 0x40, "ED": 0x80}
_MISSING = object()
_B64URL = re.compile(r"[A-Za-z0-9_-]+")
_SURROGATE = re.compile("[\ud800-\udfff]")


# --- JavaScript's view of JSON values, which the contract's answers are written in ---------------------------------

def _js_string(value: Any) -> str:
    """String(value) for a JSON value."""
    if value is _MISSING:
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
        return _delegation._number(value)
    if isinstance(value, int):
        if abs(value) < 2 ** 53:
            return str(value)
        try:
            return _delegation._number(float(value))
        except OverflowError:  # a JSON number beyond a double is Infinity in JavaScript
            return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, dict):
        return "[object Object]"
    if isinstance(value, list):
        return ",".join("" if item is None else _js_string(item) for item in value)
    return str(value)


def _get(value: Any, key: str) -> Any:
    return value.get(key, _MISSING) if isinstance(value, dict) else _MISSING


def _s(value: Any, key: str) -> str:
    return _js_string(_get(value, key))


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _same(a: Any, b: Any) -> bool:
    """JavaScript's === (and a Set's SameValueZero) on parsed JSON: an object equals only itself."""
    if a is _MISSING or b is _MISSING:
        return a is b
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _number(a) and _number(b):
        return a == b
    return type(a) is type(b) and a == b


def _contains(items: List[Any], value: Any) -> bool:
    return any(_same(item, value) for item in items)


#: The characters JavaScript's StringToNumber trims: WhiteSpace and LineTerminator (ECMA-262 §12.2, §12.3).
_JS_SPACE = "\t\n\v\f\r                  　﻿"
_JS_DECIMAL = re.compile(r"[+-]?(?:(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|Infinity)", re.ASCII)
_JS_RADIX = re.compile(r"0(?:[xX](?P<x>[0-9a-fA-F]+)|[oO](?P<o>[0-7]+)|[bB](?P<b>[01]+))", re.ASCII)


def _js_to_number(value: Any) -> float:
    """Number(value) for a JSON value, as JavaScript reads it; NaN for what it cannot read as a number."""
    if value is _MISSING:
        return math.nan
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if _number(value):
        try:
            return float(value)
        except OverflowError:
            return math.inf if value > 0 else -math.inf
    if isinstance(value, list):
        return _js_to_number(_js_string(value))  # Number([2]) is Number("2"); Number([]) is 0
    if isinstance(value, str):
        text = value.strip(_JS_SPACE)
        if text == "":
            return 0.0
        if _JS_DECIMAL.fullmatch(text):
            return float(text.replace("Infinity", "inf"))
        radix = _JS_RADIX.fullmatch(text)
        if radix:
            digits, base = next((radix.group(k), b) for k, b in (("x", 16), ("o", 8), ("b", 2)) if radix.group(k))
            return float(int(digits, base))
    return math.nan


def _safe_integer(value: Any) -> bool:
    if isinstance(value, int) and not isinstance(value, bool):
        return abs(value) <= 2 ** 53 - 1  # checked before any float: a 400-digit integer would overflow
    return isinstance(value, float) and math.isfinite(value) and value.is_integer() and abs(value) <= 2 ** 53 - 1


def _list(value: Any) -> List[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _b64url_bytes(text: str) -> bytes:
    """Buffer.from(text, "base64url") for text of the base64url alphabet: a dangling sixth bit group is ignored."""
    return _delegation._b64decode(text)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _node_base64(text: str) -> bytes:
    """Buffer.from(text, "base64"): either alphabet, other characters skipped, stops at the first "=", a dangling
    sixth bit group ignored."""
    kept = []
    for ch in text:
        if ch == "=":
            break
        if ch.isascii() and (ch.isalnum() or ch in "+/-_"):
            kept.append({"-": "+", "_": "/"}.get(ch, ch))
    body = "".join(kept)
    if len(body) % 4 == 1:
        body = body[:-1]
    return base64.b64decode(body + "=" * (-len(body) % 4))


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


# --- P-256 (DEC-0053; SEC 1 v2, FIPS 186-5) ------------------------------------------------------------------------

_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = _P - 3
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5


def is_valid_p256_key(raw: bytes) -> bool:
    """SEC 1 §3.2.2 for an uncompressed point: 0x04 ‖ X ‖ Y, X and Y below p, on y² = x³ − 3x + b. The cofactor is 1."""
    if len(raw) != 65 or raw[0] != 0x04:
        return False
    x = int.from_bytes(raw[1:33], "big")
    y = int.from_bytes(raw[33:], "big")
    if x >= _P or y >= _P:
        return False
    return (y * y - (x * x * x + _A * x + _B)) % _P == 0


def _jacobian_double(p: Tuple[int, int, int]) -> Tuple[int, int, int]:
    x, y, z = p
    if y == 0 or z == 0:
        return (0, 1, 0)
    ysq = y * y % _P
    s = 4 * x * ysq % _P
    zsq = z * z % _P
    m = 3 * (x - zsq) * (x + zsq) % _P  # a = −3
    nx = (m * m - 2 * s) % _P
    ny = (m * (s - nx) - 8 * ysq * ysq) % _P
    nz = 2 * y * z % _P
    return (nx, ny, nz)


def _jacobian_add(p: Tuple[int, int, int], q: Tuple[int, int, int]) -> Tuple[int, int, int]:
    if p[2] == 0:
        return q
    if q[2] == 0:
        return p
    z1z1 = p[2] * p[2] % _P
    z2z2 = q[2] * q[2] % _P
    u1 = p[0] * z2z2 % _P
    u2 = q[0] * z1z1 % _P
    s1 = p[1] * q[2] * z2z2 % _P
    s2 = q[1] * p[2] * z1z1 % _P
    if u1 == u2:
        return _jacobian_double(p) if s1 == s2 else (0, 1, 0)
    h = (u2 - u1) % _P
    r = (s2 - s1) % _P
    hh = h * h % _P
    hhh = h * hh % _P
    v = u1 * hh % _P
    nx = (r * r - hhh - 2 * v) % _P
    ny = (r * (v - nx) - s1 * hhh) % _P
    nz = h * p[2] * q[2] % _P
    return (nx, ny, nz)


def _shamir(u1: int, u2: int, q: Tuple[int, int]) -> Optional[Tuple[int, int]]:
    """u1·G + u2·Q in affine form, or None at infinity."""
    g = (_GX, _GY, 1)
    qj = (q[0], q[1], 1)
    both = _jacobian_add(g, qj)
    out = (0, 1, 0)
    for bit in range(max(u1.bit_length(), u2.bit_length()) - 1, -1, -1):
        out = _jacobian_double(out)
        a, b = (u1 >> bit) & 1, (u2 >> bit) & 1
        if a and b:
            out = _jacobian_add(out, both)
        elif a:
            out = _jacobian_add(out, g)
        elif b:
            out = _jacobian_add(out, qj)
    if out[2] == 0:
        return None
    zinv = pow(out[2], -1, _P)
    return (out[0] * zinv * zinv % _P, out[1] * zinv * zinv * zinv % _P)


def _der_integer(data: bytes, at: int) -> Tuple[Optional[int], int]:
    if at + 2 > len(data) or data[at] != 0x02:
        return None, at
    length = data[at + 1]
    start = at + 2
    if length == 0 or length > 33 or start + length > len(data):
        return None, at
    body = data[start:start + length]
    if body[0] & 0x80:
        return None, at  # negative
    if length > 1 and body[0] == 0 and not body[1] & 0x80:
        return None, at  # not minimal
    return int.from_bytes(body, "big"), start + length


def _der_signature(signature: bytes) -> Optional[Tuple[int, int]]:
    """An ASN.1 DER Ecdsa-Sig-Value (RFC 3279 §2.2.3), strictly: one SEQUENCE of two minimal positive INTEGERs."""
    if len(signature) < 8 or signature[0] != 0x30:
        return None
    if signature[1] & 0x80:
        return None  # a P-256 signature fits a short-form length
    if signature[1] != len(signature) - 2:
        return None
    r, at = _der_integer(signature, 2)
    if r is None:
        return None
    s, at = _der_integer(signature, at)
    if s is None or at != len(signature):
        return None
    return r, s


def es256_verify(x: bytes, y: bytes, message: bytes, signature: bytes) -> bool:
    """ECDSA P-256 with SHA-256 over `message`, the signature in DER (FIPS 186-5 §6.4.2). False, never an exception."""
    if not is_valid_p256_key(b"\x04" + x + y):
        return False
    parsed = _der_signature(signature)
    if parsed is None:
        return False
    r, s = parsed
    if not (1 <= r < _N and 1 <= s < _N):
        return False
    e = int.from_bytes(_sha256(message), "big")
    w = pow(s, -1, _N)
    point = _shamir(e * w % _N, r * w % _N, (int.from_bytes(x, "big"), int.from_bytes(y, "big")))
    return point is not None and point[0] % _N == r


# --- WebAuthn Level 3 §7.2, offline (src/webauthn.ts) ----------------------------------------------------------------

def _canonical_b64url(text: str) -> bool:
    try:
        return _b64url(_b64url_bytes(text)) == text
    except ValueError:
        return False


def credential_key(public_key: Any, alg: str) -> Dict[str, Any]:
    """The credential's public key, validated before use: ``{"key": ...}`` or ``{"problem": "unusable-key" |
    "small-order-key"}``. A P-256 point valid by SEC 1 for ES256; an Ed25519 key of full order for EdDSA."""
    if alg not in ASSERTION_ALGORITHMS:
        return {"problem": "unusable-key"}
    if (not isinstance(public_key, dict) or "d" in public_key or not isinstance(public_key.get("x"), str)
            or not _B64URL.fullmatch(public_key["x"]) or not _canonical_b64url(public_key["x"])):
        return {"problem": "unusable-key"}
    if alg == "ES256":
        y = public_key.get("y")
        if (public_key.get("kty") != "EC" or public_key.get("crv") != "P-256" or not isinstance(y, str)
                or not _B64URL.fullmatch(y) or not _canonical_b64url(y)):
            return {"problem": "unusable-key"}
        xb, yb = _b64url_bytes(public_key["x"]), _b64url_bytes(y)
        if len(xb) != 32 or len(yb) != 32 or not is_valid_p256_key(b"\x04" + xb + yb):
            return {"problem": "unusable-key"}
        return {"key": ("ES256", xb, yb)}
    if public_key.get("kty") != "OKP" or public_key.get("crv") != "Ed25519":
        return {"problem": "unusable-key"}
    raw = _b64url_bytes(public_key["x"])
    if len(raw) != 32:
        return {"problem": "unusable-key"}
    if _delegation.is_small_order_key(raw):
        return {"problem": "small-order-key"}  # DEC-0045 (CT-29): refused before any use
    return {"key": ("EdDSA", raw)}


def _no_constant(name: str) -> Any:
    raise ValueError("%s is not JSON" % name)


def verify_assertion(assertion: Any, credential: Dict[str, Any], challenge: bytes) -> Dict[str, Any]:
    """Verify a passkey assertion under a credential the caller pinned (`credentialId`, `alg`, `publicKey`, `rpId`,
    `origins`), for the expected challenge bytes, in the contract's order: shape, algorithm, key, client data, authenticator
    data, signature. ``{"ok": True, "flags": ..., "signCount": ...}`` or ``{"ok": False, "problem": ...}``."""
    def fail(problem: str) -> Dict[str, Any]:
        return {"ok": False, "problem": problem}

    if not isinstance(assertion, dict):
        return fail("malformed")
    fields = [_get(assertion, k) for k in ("credentialId", "alg", "authenticatorData", "clientDataJSON", "sig")]
    if not all(isinstance(f, str) for f in fields):
        return fail("malformed")
    credential_id, alg, authenticator_data, client_data_json, sig = fields
    if not all(_B64URL.fullmatch(f) for f in (credential_id, authenticator_data, client_data_json, sig)):
        return fail("malformed")
    if credential_id != credential.get("credentialId"):
        return fail("malformed")
    if alg not in ASSERTION_ALGORITHMS:
        return fail("unknown-algorithm")
    if alg != credential.get("alg"):
        return fail("key-algorithm-mismatch")
    found = credential_key(credential.get("publicKey"), alg)
    if "problem" in found:
        return fail(found["problem"])

    c_data = _b64url_bytes(client_data_json)
    try:
        text = c_data.decode("utf-8")
        if text.startswith("﻿"):
            text = text[1:]  # §7.2: a leading byte order mark is stripped
        client = json.loads(text, parse_constant=_no_constant)
    except (ValueError, RecursionError):
        return fail("malformed")
    if not isinstance(client, dict):
        return fail("malformed")
    if _get(client, "type") != "webauthn.get":
        return fail("wrong-type")
    if not _same(_get(client, "challenge"), _b64url(challenge)):
        return fail("wrong-challenge")
    origin = _get(client, "origin")
    if not isinstance(origin, str) or origin not in [o for o in credential.get("origins") or [] if isinstance(o, str)]:
        return fail("wrong-origin")
    if _get(client, "crossOrigin") is True or "topOrigin" in client:
        return fail("cross-origin")

    auth_data = _b64url_bytes(authenticator_data)
    if len(auth_data) < 37:
        return fail("malformed")
    if auth_data[:32] != _sha256(_SURROGATE.sub("�", str(credential.get("rpId"))).encode("utf-8")):
        return fail("wrong-rp")
    flags = auth_data[32]
    if flags & FLAGS["AT"] or (flags & FLAGS["BS"] and not flags & FLAGS["BE"]):
        return fail("bad-flags")
    if not flags & FLAGS["UP"]:
        return fail("no-user-presence")
    if not flags & FLAGS["UV"]:
        return fail("no-user-verification")

    signed = auth_data + _sha256(c_data)
    signature = _b64url_bytes(sig)
    key = found["key"]
    good = (es256_verify(key[1], key[2], signed, signature) if key[0] == "ES256"
            else len(signature) == 64 and _delegation.ed25519_verify(key[1], signed, signature))
    if not good:
        return fail("bad-signature")
    return {"ok": True, "flags": flags, "signCount": int.from_bytes(auth_data[33:37], "big")}


# --- the record (src/estate-record-rules.ts) ---------------------------------------------------------------------

def estate_record_digest(record: Dict[str, Any]) -> str:
    """`sha256:` and the hex SHA-256 of the UTF-8 RFC 8785 form of the record without `digest` and `signature`.
    Raises TypeError for a value RFC 8785 has no form for."""
    covered = {k: v for k, v in record.items() if k not in ("digest", "signature")}
    return "sha256:" + hashlib.sha256(_delegation.jcs(covered).encode("utf-8")).hexdigest()


def estate_challenge_input(digest: str) -> bytes:
    return _delegation.jcs({"type": ESTATE_CHALLENGE_TYPE, "digest": digest}).encode("utf-8")


def estate_challenge(digest: str) -> bytes:
    """The WebAuthn challenge a signer passes to navigator.credentials.get(): SHA-256 of estate_challenge_input."""
    return _sha256(estate_challenge_input(digest))


# ASCII digits only: Python's \d also matches other scripts' digits, which Date.parse never reads.
_RFC3339 = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]+)?([Zz]|([+-])([0-9]{2}):([0-9]{2}))", re.ASCII)


def _days_from_civil(year: int, month: int, day: int) -> int:
    year -= month <= 2
    era = (year if year >= 0 else year - 399) // 400
    yoe = year - era * 400
    doy = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def estate_time(value: Any) -> float:
    """An RFC 3339 date-time as milliseconds since the epoch, or NaN: `T`, an offset and a day that exists are required;
    a space and a leap second `:60` are refused (ER-10). Fractions count to the millisecond, as Date.parse reads them."""
    match = _RFC3339.fullmatch(value) if isinstance(value, str) else None
    if not match:
        return math.nan
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days_in = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if not (1 <= month <= 12 and 1 <= day <= days_in[month - 1]) or hour > 23 or minute > 59 or second > 59:
        return math.nan
    if match.group(9):
        oh, om = int(match.group(10)), int(match.group(11))
        if oh > 23 or om > 59:
            return math.nan
        offset = (oh * 60 + om) * (1 if match.group(9) == "+" else -1)
    else:
        offset = 0
    millis = int((match.group(7) or ".")[1:4].ljust(3, "0"))
    seconds = _days_from_civil(year, month, day) * 86400 + hour * 3600 + minute * 60 + second - offset * 60
    return float(seconds * 1000 + millis)


def _clock(at: Any) -> float:
    """The verifier's clock as milliseconds: a timezone-aware datetime or epoch seconds; NaN for anything else."""
    if isinstance(at, _dt.datetime) and at.tzinfo is not None:
        return at.timestamp() * 1000.0
    if _number(at):
        try:
            seconds = float(at)
        except OverflowError:
            return math.nan
        return seconds * 1000.0 if math.isfinite(seconds) else math.nan
    return math.nan


_LABEL = "[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
#: `sign.` and at least two more labels, lower case: a signing RP ID is never a bare `sign.<tld>` (DEC-0063).
_SIGNING_RP = re.compile(r"sign(?:\.%s){2,}" % _LABEL, re.ASCII)
_HTTPS_HOST = re.compile(r"https://([a-z0-9.-]{1,253})", re.ASCII)


def is_signing_rp_id(rp_id: Any) -> bool:
    """Whether an RP ID is a dedicated signing RP (v4 §7, DEC-0063): first label `sign`, then the organization's or
    PassionCode's domain, lower case. A credential under any other RP ID is a sign-in credential and never signs."""
    return isinstance(rp_id, str) and len(rp_id) <= 253 and _SIGNING_RP.fullmatch(rp_id) is not None


def origin_within(origin: Any, rp_id: str) -> bool:
    """Whether a pinned origin may run a signing ceremony for ``rp_id``: `https://`, no port, no path, its host the RP
    ID or a subdomain of it, lower case. Related origins are never used for signing."""
    match = _HTTPS_HOST.fullmatch(origin) if isinstance(origin, str) else None
    return match is not None and (match.group(1) == rp_id or match.group(1).endswith("." + rp_id))


def _signing_credential(credential: Any, path: str, flag) -> None:
    """FAC-SEM-092 on one signing credential: a signing RP ID, and every pinned origin within it."""
    value = credential if isinstance(credential, dict) else {}
    if not is_signing_rp_id(_get(value, "rpId")):
        flag("%s/rpId" % path, "a passkey signs only under a dedicated signing RP, sign.<domain>, never under the RP ID it signs in with")
        return
    origins = _get(value, "origins")
    for index, origin in enumerate(origins if isinstance(origins, list) else []):
        if not origin_within(origin, value["rpId"]):
            flag("%s/origins/%d" % (path, index), "a signing ceremony runs only on %s or a host under it, over https without a port" % value["rpId"])


def _revocation_key(entry: Dict[str, Any]) -> str:
    return "%s %s" % (_s(entry, "kind"), _s(entry, "ref"))


def _lt(a: float, b: float) -> bool:
    return not (math.isnan(a) or math.isnan(b)) and a < b


def verify_estate_record(record: Any, *, at: Any, parent: Any = _MISSING, authorities: Any = None) -> Dict[str, Any]:
    """The reference verifier, in the order of estate-record.md's ER table: the clock, shape, digest, the chain to the
    parent, the signing passkey among the trusted ones, the assertion, the validity window, then the record's own rules.
    ``at`` is the verifier's clock (an aware datetime or epoch seconds). Pass the record's verified ``parent``, or for
    revision 1 the ``authorities`` the machine pinned at enrollment. Returns ``{"ok": True, "digest", "revision",
    "signedBy", "signCount"}`` or ``{"ok": False, "problem", "codes"?}``."""
    now = _clock(at)
    if not math.isfinite(now):
        return {"ok": False, "problem": "no-clock"}  # an unreadable clock would accept any window
    if (not isinstance(record, dict) or not isinstance(_get(record, "digest"), str) or not _safe_integer(_get(record, "revision"))
            or not isinstance(_get(record, "signature"), dict)):
        return {"ok": False, "problem": "malformed"}
    signature = record["signature"]
    if _get(signature, "format") != "webauthn-assertion" or not isinstance(_get(signature, "credentialId"), str):
        return {"ok": False, "problem": "malformed"}
    try:
        digest = estate_record_digest(record)
    except TypeError:
        return {"ok": False, "problem": "malformed"}
    if digest != record["digest"]:
        return {"ok": False, "problem": "digest-mismatch"}

    revoked: List[Any] = []
    if parent is not _MISSING:
        if not isinstance(parent, dict):
            return {"ok": False, "problem": "broken-chain"}
        try:
            parent_digest = estate_record_digest(parent)
        except TypeError:
            return {"ok": False, "problem": "broken-chain"}
        if (not _same(_get(parent, "estate"), _get(record, "estate"))
                or not _same(_get(record, "revision"), _js_to_number(_get(parent, "revision")) + 1)
                or not _same(_get(record, "parent"), parent_digest)):
            return {"ok": False, "problem": "broken-chain"}
        if _lt(estate_time(_get(record, "issuedAt")), estate_time(_get(parent, "issuedAt"))):
            return {"ok": False, "problem": "broken-chain"}
        kept = {_revocation_key(e) for e in _list(_get(record, "revocations"))}
        if any(_revocation_key(e) not in kept for e in _list(_get(parent, "revocations"))):
            return {"ok": False, "problem": "broken-chain"}
        # A passkey the parent revokes signs nothing after it; a revision may still revoke its own signer (rotation).
        revoked = [_get(e, "ref") for e in _list(_get(parent, "revocations")) if _get(e, "kind") == "authority"]
        trusted = _get(parent, "authorities")
        trusted = _list(trusted)
    else:
        if not _same(_get(record, "revision"), 1) or _get(record, "parent") is not _MISSING:
            return {"ok": False, "problem": "broken-chain"}
        trusted = list(authorities) if isinstance(authorities, (list, tuple)) else []
    if len(trusted) == 0:
        return {"ok": False, "problem": "no-trusted-authority"}
    matches = [e for e in trusted if isinstance(e, dict) and _same(_get(e, "credentialId"), signature["credentialId"])]
    if len(matches) > 1:
        return {"ok": False, "problem": "duplicate-authority"}
    if not matches:
        return {"ok": False, "problem": "unknown-authority"}
    authority = matches[0]
    if _contains(revoked, _get(authority, "credentialId")):
        return {"ok": False, "problem": "revoked-authority"}
    origins = _get(authority, "origins")
    credential = {"credentialId": _s(authority, "credentialId"), "alg": _s(authority, "alg"),
                  "publicKey": authority["publicKey"] if isinstance(_get(authority, "publicKey"), dict) else {},
                  "rpId": _s(authority, "rpId"), "origins": [o for o in origins if isinstance(o, str)] if isinstance(origins, list) else []}
    # DEC-0063: the estate passkey is a signing credential. An RP ID that is not sign.<domain> is wrong-rp before the
    # assertion is read; an origin outside the RP ID is not pinned, so a ceremony that ran there is wrong-origin.
    if not is_signing_rp_id(_get(authority, "rpId")):
        return {"ok": False, "problem": "wrong-rp"}
    credential["origins"] = [o for o in credential["origins"] if origin_within(o, credential["rpId"])]
    assertion = verify_assertion(signature, credential, estate_challenge(digest))
    if not assertion["ok"]:
        return {"ok": False, "problem": assertion["problem"]}

    issued_at = estate_time(_get(record, "issuedAt"))
    valid_until = estate_time(_get(record, "validUntil"))
    if (not math.isfinite(issued_at) or not math.isfinite(valid_until) or valid_until <= issued_at
            or valid_until - issued_at > MAX_VALIDITY_SECONDS * 1000):
        return {"ok": False, "problem": "too-long-lived"}
    # A revision issued a moment ahead of this clock is admitted within the skew every relay time allows (DEC-0066).
    if now < issued_at - CLOCK_SKEW_SECONDS * 1000:
        return {"ok": False, "problem": "not-yet-valid"}
    if now > valid_until:
        return {"ok": False, "problem": "expired"}
    codes: List[str] = []
    for finding in _record_findings(record):
        if finding["code"] not in codes:
            codes.append(finding["code"])
    if codes:
        return {"ok": False, "problem": "rule-violation", "codes": codes}
    return {"ok": True, "digest": digest, "revision": record["revision"], "signedBy": credential["credentialId"], "signCount": assertion["signCount"]}


def placement_trust(record: Dict[str, Any], machine_id: str, agent_ref: str) -> Optional[Dict[str, Any]]:
    """What a package verifier (DEC-0051) trusts for a package placed on a machine: the publisher keys the placement
    names, from the record's `publisherKeys`. None when the record places no such agent on that machine."""
    machine = next((m for m in _list(_get(record, "machines")) if _same(_get(m, "id"), machine_id)), None)
    placement = next((p for p in _list(_get(machine, "packages")) if _same(_get(p, "agentRef"), agent_ref)), None)
    if placement is None:
        return None
    return {"publisher": [k for k in _list(_get(record, "publisherKeys")) if _same(_get(k, "kid"), _get(placement, "publisherKid"))]}


#: v4 §7, Freshness: an estate revision's window is at most 30 days (DEC-0055 item 2).
_MAX_WINDOW_MS = MAX_VALIDITY_SECONDS * 1000


def _refused(fault: str, detail: str) -> Dict[str, Any]:
    return {"certified": False, "fault": fault, "detail": detail}


def _revision_number(value: Any) -> bool:
    return _safe_integer(value) and value >= 1


def hub_key_certified(record: Any, kid: Any, x: Any, at: Any, applied: Any = None,
                      extra_revocations: Any = _MISSING) -> Dict[str, Any]:
    """DL-14 (DEC-0055, DEC-0060): whether ``record`` certifies the delegation key ``kid`` with the published key's ``x``
    at ``at`` (an aware datetime or epoch seconds), for a verifier whose machine applied ``applied``
    (``{"revision", "digest"?}``). ``extra_revocations`` are the revocation delta's entries applied since the revision
    (DEC-0054). The contract's ``hubKeyCertified``, in its order; never raises. Answers ``{"certified": True, "machine",
    "revision"}`` or ``{"certified": False, "fault": "token"|"estate"|"clock", "detail"}`` with detail
    ``kid-not-certified`` (the token's fault), ``estate-unreadable``, ``estate-outside-window``, ``estate-rolled-back``,
    ``estate-forked`` (the trust source's) or ``no-clock``."""
    now = _clock(at)
    if math.isnan(now):
        return _refused("clock", "no-clock")
    if (not isinstance(record, dict) or not _revision_number(_get(record, "revision"))
            or not isinstance(_get(record, "digest"), str) or not isinstance(_get(record, "machines"), list)):
        return _refused("estate", "estate-unreadable")
    revocations = _get(record, "revocations")
    if revocations is not _MISSING and not isinstance(revocations, list):
        return _refused("estate", "estate-unreadable")
    if extra_revocations is not _MISSING and not isinstance(extra_revocations, list):
        return _refused("estate", "estate-unreadable")
    issued_at, valid_until = estate_time(_get(record, "issuedAt")), estate_time(_get(record, "validUntil"))
    # A window that is not a time, not positive or longer than 30 days is no window: NaN fails every comparison below.
    if math.isnan(issued_at) or math.isnan(valid_until) or valid_until <= issued_at or valid_until - issued_at > _MAX_WINDOW_MS:
        return _refused("estate", "estate-unreadable")
    if applied is not None:
        if (not isinstance(applied, dict) or not _revision_number(_get(applied, "revision"))
                or (_get(applied, "digest") is not _MISSING and not isinstance(_get(applied, "digest"), str))):
            return _refused("estate", "estate-unreadable")
        # An older revision may still be inside its window and list a key the applied one revokes (a rollback).
        if record["revision"] < applied["revision"]:
            return _refused("estate", "estate-rolled-back")
        if (record["revision"] == applied["revision"] and _get(applied, "digest") is not _MISSING
                and record["digest"] != applied["digest"]):
            return _refused("estate", "estate-forked")
    # The window verify_estate_record admits the revision in: from 60 s before issuedAt to validUntil (DEC-0066).
    if now < issued_at - CLOCK_SKEW_SECONDS * 1000 or now > valid_until:
        return _refused("estate", "estate-outside-window")

    entries = list(revocations if isinstance(revocations, list) else []) + list(extra_revocations if isinstance(extra_revocations, list) else [])

    def revokes(kind: str, ref: Any) -> bool:  # a ref is compared exactly, never as a string conversion
        return any(isinstance(e, dict) and _same(_get(e, "kind"), kind) and _same(_get(e, "ref"), ref) for e in entries)

    if not isinstance(kid, str) or revokes("hub-key", kid):
        return _refused("token", "kid-not-certified")
    holders = [m for m in record["machines"] if isinstance(m, dict) and isinstance(_get(m, "hubKey"), dict) and _same(_get(m["hubKey"], "kid"), kid)]
    if len(holders) != 1:  # two machines under one kid break FAC-SEM-073; such a revision certifies neither
        return _refused("token", "kid-not-certified")
    machine = holders[0]
    if not isinstance(x, str) or not _same(_get(machine["hubKey"], "x"), x):  # a missing x never equals a missing x
        return _refused("token", "kid-not-certified")
    if revokes("machine", _get(machine, "id")):
        return _refused("token", "kid-not-certified")
    return {"certified": True, "machine": _s(machine, "id"), "revision": record["revision"]}


# --- FAC-SEM-072…076 ------------------------------------------------------------------------------------------------

def _finding(findings: List[Dict[str, str]], code: str):
    def flag(path: str, message: str) -> None:
        findings.append({"code": code, "instancePath": path, "message": message})
    return flag


def _revision_whole(value: Dict[str, Any], flag) -> None:
    try:
        digest = estate_record_digest(value)
        if not _same(digest, _get(value, "digest")):
            flag("/digest", "the digest is %s: the record changed after it was drafted, or was hashed over another form than RFC 8785" % digest)
    except TypeError:
        flag("/digest", "the record has no RFC 8785 form, so it has no digest")
    issued_at = estate_time(_get(value, "issuedAt"))
    valid_until = estate_time(_get(value, "validUntil"))
    if not math.isfinite(issued_at) or not math.isfinite(valid_until):
        flag("/validUntil" if math.isfinite(issued_at) else "/issuedAt", "issuedAt and validUntil are RFC 3339 date-times with an offset, on days that exist")
    elif valid_until <= issued_at or valid_until - issued_at > MAX_VALIDITY_SECONDS * 1000:
        flag("/validUntil", "an estate record is valid after it is issued and for at most 30 days")


def _revision_chain(value: Dict[str, Any]) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    flag = _finding(findings, "FAC-SEM-072")
    parent = value["parent"] if isinstance(_get(value, "parent"), dict) else {}
    nxt = value["next"] if isinstance(_get(value, "next"), dict) else {}
    if not _same(_get(nxt, "estate"), _get(parent, "estate")):
        flag("/next/estate", "a revision continues its parent's estate")
    expected = _js_to_number(_get(parent, "revision")) + 1
    if not _same(_get(nxt, "revision"), expected):
        flag("/next/revision", "the revision after %s is %s: a revision never skips or repeats one" % (_s(parent, "revision"), _js_string(expected)))
    try:
        parent_digest: Any = estate_record_digest(parent)
    except TypeError:
        parent_digest = _MISSING
    if not _same(_get(nxt, "parent"), parent_digest):
        flag("/next/parent", "parent names the digest of the revision before it")
    if _lt(estate_time(_get(nxt, "issuedAt")), estate_time(_get(parent, "issuedAt"))):
        flag("/next/issuedAt", "a revision is never issued before its parent")
    kept = {_revocation_key(e) for e in _list(_get(nxt, "revocations"))}
    for index, entry in enumerate(_list(_get(parent, "revocations"))):
        if _revocation_key(entry) not in kept:
            flag("/parent/revocations/%d" % index, "the %s revocation of %s is dropped: a revision keeps every revocation before it" % (_s(entry, "kind"), _s(entry, "ref")))
    return findings


def _valid_device_key(key: Dict[str, Any]) -> bool:
    public = _get(key, "publicKey")
    raw = _node_base64("" if public is _MISSING or public is None else _js_string(public))
    if _get(key, "alg") == "ed25519":
        return len(raw) == 32 and not _delegation.is_small_order_key(raw)
    return is_valid_p256_key(raw)


def _keys(value: Dict[str, Any], flag) -> None:
    ids: List[Any] = []
    hub_kids: List[Any] = []
    hub_keys: List[Any] = []
    for m, machine in enumerate(_list(_get(value, "machines"))):
        at = "/machines/%d" % m
        if _contains(ids, _get(machine, "id")):
            flag("%s/id" % at, "machine %s is listed twice" % _s(machine, "id"))
        ids.append(_get(machine, "id"))
        device_keys = _list(_get(machine, "deviceKeys"))
        if len([k for k in device_keys if _get(k, "use") == "sig"]) != 1:
            flag("%s/deviceKeys" % at, "a machine has exactly one signing device key, <id>#sig")
        if len([k for k in device_keys if _get(k, "use") == "kem"]) > 1:
            flag("%s/deviceKeys" % at, "a machine has at most one key-agreement device key, <id>#kem")
        seen: List[Any] = []
        for k, key in enumerate(device_keys):
            if not _same(_get(key, "kid"), "%s#%s" % (_s(machine, "id"), _s(key, "use"))):
                flag("%s/deviceKeys/%d/kid" % (at, k), "a device key is listed as <machine id>#sig or <machine id>#kem, by its role")
            if not _valid_device_key(key):
                flag("%s/deviceKeys/%d/publicKey" % (at, k), "an Ed25519 key is never of small order (DEC-0045) and a P-256 key is a valid point (SEC 1 §3.2.2)")
            if _contains(seen, _get(key, "publicKey")):
                flag("%s/deviceKeys/%d/publicKey" % (at, k), "one key is never used for the other role")
            seen.append(_get(key, "publicKey"))
        hub = _get(machine, "hubKey")
        if isinstance(hub, dict):
            if _contains(hub_kids, _get(hub, "kid")):
                flag("%s/hubKey/kid" % at, "hub key %s is certified for two machines: one kid per machine" % _s(hub, "kid"))
            hub_kids.append(_get(hub, "kid"))
            if _contains(hub_keys, _get(hub, "x")):
                flag("%s/hubKey/x" % at, "one hub public key is certified for two machines under two kids: one key per machine")
            hub_keys.append(_get(hub, "x"))
            x = _get(hub, "x")
            raw = _node_base64("" if x is _MISSING or x is None else _js_string(x))
            if _delegation.is_small_order_key(raw):
                flag("%s/hubKey/x" % at, "a hub key of small order verifies forged tokens and is never certified (DEC-0045)")
    credentials: List[Any] = []
    for index, authority in enumerate(_list(_get(value, "authorities"))):
        if _contains(credentials, _get(authority, "credentialId")):
            flag("/authorities/%d/credentialId" % index, "a passkey is listed once")
        credentials.append(_get(authority, "credentialId"))
        if "problem" in credential_key(_get(authority, "publicKey"), _s(authority, "alg")):
            flag("/authorities/%d/publicKey" % index, "a passkey's public key is a valid P-256 point for ES256 or an Ed25519 key of full order for EdDSA")


def _placements(value: Dict[str, Any], flag) -> None:
    kids: List[Any] = []
    for index, key in enumerate(_list(_get(value, "publisherKeys"))):
        if _contains(kids, _get(key, "kid")):
            flag("/publisherKeys/%d/kid" % index, "publisher key %s is pinned twice" % _s(key, "kid"))
        kids.append(_get(key, "kid"))
    for m, machine in enumerate(_list(_get(value, "machines"))):
        agents: List[Any] = []
        for p, placement in enumerate(_list(_get(machine, "packages"))):
            at = "/machines/%d/packages/%d" % (m, p)
            if _contains(agents, _get(placement, "agentRef")):
                flag("%s/agentRef" % at, "%s is placed twice on one machine" % _s(placement, "agentRef"))
            agents.append(_get(placement, "agentRef"))
            if not _contains(kids, _get(placement, "publisherKid")):
                flag("%s/publisherKid" % at, "publisher key %s is not in publisherKeys, so the machine pins no key to verify the package under" % _s(placement, "publisherKid"))


def _secret_references(value: Dict[str, Any], flag) -> None:
    machine_ids = [_get(m, "id") for m in _list(_get(value, "machines"))]
    for m, machine in enumerate(_list(_get(value, "machines"))):
        placed = [_get(p, "agentRef") for p in _list(_get(machine, "packages"))]
        slots: List[str] = []
        for s, secret in enumerate(_list(_get(machine, "secrets"))):
            at = "/machines/%d/secrets/%d" % (m, s)
            for field in ("slot", "from", "agentRef"):
                text = _get(secret, field)
                if isinstance(text, str) and _secrets.secret_value(text):
                    flag("%s/%s" % (at, field), "a secret placement names a slot, never a value: this looks like a credential")
            if not _contains(placed, _get(secret, "agentRef")):
                flag("%s/agentRef" % at, "a secret goes only where a placed package declares it (v4 Path 2): this agent is not placed on this machine")
            if not _contains(machine_ids, _get(secret, "from")):
                flag("%s/from" % at, "the slot is filled from a machine of this estate")
            key = "%s %s" % (_s(secret, "agentRef"), _s(secret, "slot"))
            if key in slots:
                flag("%s/slot" % at, "slot %s is placed twice for one agent on one machine" % _s(secret, "slot"))
            slots.append(key)


def _grants_and_revocations(value: Dict[str, Any], flag) -> None:
    grant_ids: List[Any] = []
    for index, grant in enumerate(_list(_get(value, "shareGrants"))):
        if _get(grant, "principalKind") != "external":
            flag("/shareGrants/%d/principalKind" % index, "a share grant is to a principal outside the estate: principalKind external")
        ident = _get(_get(grant, "meta"), "id") if isinstance(_get(grant, "meta"), dict) else _MISSING
        if _contains(grant_ids, ident):
            flag("/shareGrants/%d/meta/id" % index, "grant %s is listed twice" % _js_string(ident))
        grant_ids.append(ident)
    machines = _list(_get(value, "machines"))
    listed = {
        "authority": [_get(e, "credentialId") for e in _list(_get(value, "authorities"))],
        "machine": [_get(m, "id") for m in machines],
        "device-key": [_get(k, "kid") for m in machines for k in _list(_get(m, "deviceKeys"))],
        "hub-key": [_get(m["hubKey"], "kid") for m in machines if isinstance(_get(m, "hubKey"), dict)],
        "publisher-key": [_get(k, "kid") for k in _list(_get(value, "publisherKeys"))],
        "package": [_get(p, "digest") for m in machines for p in _list(_get(m, "packages"))],
        "grant": grant_ids,
    }
    seen: List[str] = []
    for index, revocation in enumerate(_list(_get(value, "revocations"))):
        key = "%s %s" % (_s(revocation, "kind"), _s(revocation, "ref"))
        if key in seen:
            flag("/revocations/%d" % index, "the %s %s is revoked twice" % (_s(revocation, "kind"), _s(revocation, "ref")))
        seen.append(key)
        if _contains(listed.get(_s(revocation, "kind"), []), _get(revocation, "ref")):
            flag("/revocations/%d/ref" % index, "the record still lists the %s it revokes: revocation outranks addition" % _s(revocation, "kind"))


def _record_findings(value: Dict[str, Any]) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    _revision_whole(value, _finding(findings, "FAC-SEM-072"))
    _keys(value, _finding(findings, "FAC-SEM-073"))
    _placements(value, _finding(findings, "FAC-SEM-074"))
    _secret_references(value, _finding(findings, "FAC-SEM-075"))
    _grants_and_revocations(value, _finding(findings, "FAC-SEM-076"))
    for index, authority in enumerate(_list(_get(value, "authorities"))):  # FAC-SEM-092 (DEC-0063)
        _signing_credential(authority, "/authorities/%d" % index, _finding(findings, "FAC-SEM-092"))
    return findings


def _package_digest(pkg: Dict[str, Any]) -> str:
    covered = {k: v for k, v in pkg.items() if k not in ("digest", "signatures")}
    return "sha256:" + hashlib.sha256(_delegation.jcs(covered).encode("utf-8")).hexdigest()


def _installation(value: Dict[str, Any]) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    record = value["record"] if isinstance(_get(value, "record"), dict) else {}
    pkg = value["package"] if isinstance(_get(value, "package"), dict) else {}
    machines = _list(_get(record, "machines"))
    machine_index = next((i for i, m in enumerate(machines) if _same(_get(m, "id"), _get(value, "machine"))), -1)
    flag074 = _finding(findings, "FAC-SEM-074")
    if machine_index < 0:
        flag074("/machine", "machine %s is not in the estate record" % _s(value, "machine"))
        return findings
    machine = machines[machine_index]
    try:
        digest: Any = _package_digest(pkg)
    except TypeError:
        digest = _MISSING
    if digest is _MISSING or not _same(digest, _get(pkg, "digest")):
        flag074("/package/digest", "the package is not the one its digest names: it changed after it was packed")
    placement = next((p for p in _list(_get(machine, "packages")) if _same(_get(p, "agentRef"), _get(pkg, "agentRef"))), None)
    if placement is None:
        flag074("/package/agentRef", "the record places no %s on machine %s" % (_s(pkg, "agentRef"), _s(value, "machine")))
    elif not _same(_get(placement, "digest"), digest):
        flag074("/package", "the record places %s of this agent on this machine, not this package" % _s(placement, "digest"))
    declared = [_get(slot, "name") for slot in _list(_get(pkg, "secrets"))]
    flag075 = _finding(findings, "FAC-SEM-075")
    for index, secret in enumerate(_list(_get(machine, "secrets"))):
        if _same(_get(secret, "agentRef"), _get(pkg, "agentRef")) and not _contains(declared, _get(secret, "slot")):
            flag075("/record/machines/%d/secrets/%d/slot" % (machine_index, index),
                    "the package declares no slot %s: a secret goes only where a placed package declares it" % _s(secret, "slot"))
    return findings


def estate_record_rules(kind: str, value: Any) -> Optional[List[Dict[str, str]]]:
    """FAC-SEM-072…076: findings for an `estate-record`, an `estate-record-revision` `{parent, next}` or an
    `estate-placement` `{record, machine, package}`; None for another kind."""
    if not isinstance(value, dict):
        value = {}
    if kind == "estate-record":
        return _record_findings(value)
    if kind == "estate-record-revision":
        return _revision_chain(value)
    if kind == "estate-placement":
        return _installation(value)
    return None
