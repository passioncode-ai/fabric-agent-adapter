#!/usr/bin/env python3
"""The callee's side of fabric-delegation/0.1 (Fabric Agent Contract DEC-0039, Fabric ADR-0144): check a
delegation token or an approval offline against the estate's published keys, and answer `ok` or one refusal
code. A port of the contract's `src/delegation.ts` at the pinned revision; the shared vectors in
`test/fixtures/delegation/vectors.json` hold this module to that verifier's exact answers.

Standard library only. Ed25519 (RFC 8032) is verified here in plain Python: verification uses only public data,
so it needs no constant-time arithmetic; it is cofactorless and strict as OpenSSL is (S below L, A decodes,
R compared by its encoding).

    from fabric_delegation import JwksCache, delegation_gate
    gate = delegation_gate(audience="example-agent", jwks=JwksCache(well_known["auth"]["delegation"]["jwks"]),
                           effects={"example.write": "draft"}, issuer=well_known["auth"]["delegation"]["issuer"])
    server = fabric_interop.McpToolServer("example-agent", VERSION, authorize=gate)
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
import urllib.parse
import urllib.request

REFUSAL_CODES = (
    "unauthenticated", "token-expired", "wrong-audience", "scope-not-granted", "effect-above-ceiling", "no-grant",
    "grant-expired", "grant-revoked", "limit-reached", "approval-required", "approval-invalid", "approval-reused",
    "principal-unproven", "credential-source-refused", "chain-too-deep", "issuer-unavailable", "unknown-state",
)
EFFECT_CLASSES = ("none", "draft", "publish", "send", "reply", "charge", "delete", "merge", "deploy", "change-policy")
DELEGATION_HEADER = "Fabric-Delegation"
DELEGATION_TYP = "fabric-delegation+jwt"
APPROVAL_TYP = "fabric-approval+jwt"
MAX_DELEGATION_LIFETIME_SECONDS = 600
MAX_APPROVAL_LIFETIME_SECONDS = 86_400
MAX_CHAIN_DEPTH = 4
LEEWAY_SECONDS = 60
# DL-15: a callee caches the key set at most 10 minutes and re-reads it at most once a minute for an unknown kid.
JWKS_MAX_AGE_SECONDS = 600
JWKS_REREAD_SECONDS = 60

# DL-19: the HTTP status of each refusal, and the sentence that goes in error.message.
REFUSAL_STATUS = {"unauthenticated": 401, "token-expired": 401, "principal-unproven": 401,
                  "issuer-unavailable": 503, "unknown-state": 503}
REFUSAL_MESSAGES = {
    "unauthenticated": "No delegation token, or one not signed by a published key or not of this profile.",
    "token-expired": "The delegation token has expired; mint a new one.",
    "wrong-audience": "The delegation token is for another callee.",
    "scope-not-granted": "The called capability is not in the token's scope.",
    "effect-above-ceiling": "The capability's effect is above the token's ceiling.",
    "no-grant": "No live grant covers this call.",
    "grant-expired": "The grant has expired.",
    "grant-revoked": "The grant was revoked.",
    "limit-reached": "A spend window is exhausted.",
    "approval-required": "This action needs an approval; ask the hub for one with the action digest.",
    "approval-invalid": "The approval is not valid for this action, callee or time.",
    "approval-reused": "The approval was already used.",
    "principal-unproven": "The caller's proof is missing or stale.",
    "credential-source-refused": "The grant names a credential source that is not allowed.",
    "chain-too-deep": "The actor chain is deeper than four.",
    "issuer-unavailable": "The estate's published keys cannot be read.",
    "unknown-state": "The state cannot be established, so the call is refused.",
}

_B64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_MISSING = object()


def _refuse(code: str, detail: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "code": code, "detail": detail}
    if data:
        out["data"] = data
    return out


def _is_string(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def _is_time(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 0
    return isinstance(value, float) and math.isfinite(value) and value.is_integer() and value >= 0


# --- Ed25519 (RFC 8032 §5.1) ----------------------------------------------------------------------------

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _add(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    aa = (y1 - x1) * (y2 - x2) % _P
    bb = (y1 + x1) * (y2 + x2) % _P
    cc = 2 * t1 * t2 * _D % _P
    dd = 2 * z1 * z2 % _P
    e, f, g, h = bb - aa, dd - cc, dd + cc, bb + aa
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(scalar: int, point: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    result = (0, 1, 1, 0)
    while scalar:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _decode_point(data: bytes) -> Optional[Tuple[int, int, int, int]]:
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        if sign:
            return None
        return (0, y, 1, 0)
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P:
        return None
    if x & 1 != sign:
        x = _P - x
    return (x, y, 1, x * y % _P)


def _encode_point(point: Tuple[int, int, int, int]) -> bytes:
    x, y, z, _ = point
    zi = pow(z, _P - 2, _P)
    x, y = x * zi % _P, y * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


_G = _decode_point(bytes.fromhex("5866666666666666666666666666666666666666666666666666666666666666"))


def ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """RFC 8032 §5.1.7, cofactorless: [S]B == R + [k]A, compared by R's encoding. False, never an exception."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    a = _decode_point(public_key)
    if a is None:
        return False
    k = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), "little") % _L
    neg_a = ((-a[0]) % _P, a[1], a[2], (-a[3]) % _P)
    return secrets.compare_digest(_encode_point(_add(_mul(s, _G), _mul(k, neg_a))), signature[:32])


# --- the compact document ------------------------------------------------------------------------------

def _b64decode(segment: str) -> bytes:
    """Base64url without padding, as Node reads it: a dangling sixth bit group is ignored."""
    if len(segment) % 4 == 1:
        segment = segment[:-1]
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


class _Duplicate(ValueError):
    pass


def _no_duplicates(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    seen: Dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _Duplicate(key)
        seen[key] = value
    return seen


def _no_constant(name: str) -> Any:
    raise ValueError(name)  # NaN and Infinity are not JSON


def _decode_segment(segment: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not _B64URL.match(segment):
        return None, "malformed"
    try:
        text = _b64decode(segment).decode("utf-8", "replace")
        value = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except _Duplicate:
        try:
            value = json.loads(text, parse_constant=_no_constant)
        except ValueError:
            return None, "malformed"
        return (None, "duplicate-member") if isinstance(value, dict) else (None, "malformed")
    except (ValueError, TypeError, RecursionError):
        return None, "malformed"
    if not isinstance(value, dict):
        return None, "malformed"
    return value, None


def _utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _parse_compact(token: Any) -> Dict[str, Any]:
    if not isinstance(token, str) or _utf16_length(token) > 8192:
        return {"problem": "malformed"}
    parts = token.split(".")
    if len(parts) != 3:
        return {"problem": "malformed"}
    h, p, s = parts
    header, header_problem = _decode_segment(h)
    payload, payload_problem = _decode_segment(p)
    if not _B64URL.match(s):
        return {"problem": "malformed"}
    for problem in (header_problem, payload_problem):
        if problem:
            return {"problem": problem}
    try:
        signature = _b64decode(s)
    except ValueError:
        signature = b""
    return {"header": header, "payload": payload, "signing_input": ("%s.%s" % (h, p)).encode("ascii"), "signature": signature}


def _header_problem(header: Dict[str, Any], typ: str) -> Optional[str]:
    if header.get("alg") != "EdDSA":
        return "alg-not-eddsa"
    if header.get("typ") != typ:
        return "wrong-typ"
    if not _is_string(header.get("kid")):
        return "no-kid"
    for member in ("crit", "jku", "jwk", "x5u", "x5c"):
        if member in header:
            return "header-" + member
    return None


def _key_for(jwks: Dict[str, Any], kid: str) -> Dict[str, Any]:
    matches = [k for k in jwks["keys"] if isinstance(k, dict) and k.get("kid") == kid]
    if len(matches) > 1:
        return {"problem": "duplicate-kid"}
    if not matches:
        return {"problem": "unknown-key"}
    jwk = matches[0]
    # A key published for another use or algorithm is never a candidate (RFC 7517 §4.2, §4.4).
    if ("use" in jwk and jwk["use"] != "sig") or ("alg" in jwk and jwk["alg"] != "EdDSA"):
        return {"problem": "key-not-for-signing"}
    if jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519" or not _is_string(jwk.get("x")) or "d" in jwk:
        return {"problem": "unusable-key"}
    if not _B64URL.match(jwk["x"]):
        return {"problem": "unusable-key"}
    try:
        raw = _b64decode(jwk["x"])
    except ValueError:
        return {"problem": "unusable-key"}
    if len(raw) != 32:
        return {"problem": "unusable-key"}
    return {"key": raw}


def _has_keys(jwks: Any) -> bool:
    return isinstance(jwks, dict) and isinstance(jwks.get("keys"), list) and len(jwks["keys"]) > 0


def _authentic(token: Any, jwks: Dict[str, Any], typ: str) -> Dict[str, Any]:
    """Parse, check the header, find the key, verify the signature. A fault of the published keys is the issuer's."""
    compact = _parse_compact(token)
    if "problem" in compact:
        return compact
    problem = _header_problem(compact["header"], typ)
    if problem:
        return {"problem": problem}
    kid = compact["header"]["kid"]
    found = _key_for(jwks, kid)
    if "problem" in found:
        return {"problem": found["problem"], "issuer": found["problem"] in ("unusable-key", "duplicate-kid")}
    if len(compact["signature"]) != 64 or not ed25519_verify(found["key"], compact["signing_input"], compact["signature"]):
        return {"problem": "bad-signature"}
    return {"compact": compact, "kid": kid}


def chain_depth(act: Any) -> float:
    """Depth of an actor chain; infinity for a chain that is not one (a missing or non-string sub at any level)."""
    depth = 0
    node = act
    while node is not _MISSING:
        if not isinstance(node, dict) or not _is_string(node.get("sub")):
            return math.inf
        depth += 1
        if depth > 64:
            return depth
        node = node.get("act", _MISSING)
    return depth


def _chain_of(act: Dict[str, Any]) -> List[str]:
    chain = []
    node: Any = act
    while isinstance(node, dict):
        chain.append(node["sub"])
        node = node.get("act")
    return chain


def effect_closure(ceiling: List[str]) -> set:
    """`none` is below every class and `draft` below every external one; external classes are not ordered."""
    admitted = set(ceiling)
    if ceiling:
        admitted.add("none")
    if any(effect != "none" for effect in ceiling):
        admitted.add("draft")
    return admitted


def effect_within(effect: str, ceiling: List[str]) -> bool:
    return effect in effect_closure(ceiling)


def _delegation_shape(payload: Dict[str, Any]) -> bool:
    if not all(_is_string(payload.get(k)) for k in ("iss", "sub", "aud", "scope", "jti")):
        return False
    if not _is_time(payload.get("iat")) or not _is_time(payload.get("exp")):
        return False
    effect, grant = payload.get("effect"), payload.get("grant")
    if not isinstance(effect, list) or not effect or not all(isinstance(e, str) and e in EFFECT_CLASSES for e in effect):
        return False
    if not isinstance(grant, list) or not grant or not all(_is_string(g) for g in grant):
        return False
    return isinstance(payload.get("act"), dict)


def _approval_shape(payload: Dict[str, Any]) -> bool:
    if not all(_is_string(payload.get(k)) for k in ("iss", "actionDigest", "aud", "approver", "jti")):
        return False
    if not _is_time(payload.get("iat")) or not _is_time(payload.get("exp")):
        return False
    return payload.get("method") in ("prompt", "operator-channel", "device")


def verify_delegation(token: Any, *, audience: str, jwks: Any, now: float, capability: str, effect: str,
                      issuer: Optional[str] = None, read_only: bool = False) -> Dict[str, Any]:
    """DL-13, in its fixed order: nothing about a token is believed before its signature is.
    `now` is seconds since the epoch. Returns {ok: True, claims, principal, caller, chain, kid} or a refusal
    {ok: False, code, detail[, data]} whose detail is a short machine word, never the token."""
    if not _has_keys(jwks):
        return _refuse("issuer-unavailable", "no-published-keys")
    checked = _authentic(token, jwks, DELEGATION_TYP)
    if "problem" in checked:
        return _refuse("issuer-unavailable" if checked.get("issuer") else "unauthenticated", checked["problem"])
    claims = checked["compact"]["payload"]
    if not _delegation_shape(claims):
        return _refuse("unauthenticated", "malformed-claims")
    if issuer is not None and claims["iss"] != issuer:
        return _refuse("unauthenticated", "wrong-issuer")
    if claims["exp"] <= claims["iat"] or claims["exp"] - claims["iat"] > MAX_DELEGATION_LIFETIME_SECONDS:
        return _refuse("unauthenticated", "lifetime-above-profile")
    if claims["iat"] > now + LEEWAY_SECONDS:
        return _refuse("unauthenticated", "issued-in-future")
    if "nbf" in claims and (not _is_time(claims["nbf"]) or claims["nbf"] > now + LEEWAY_SECONDS):
        return _refuse("unauthenticated", "not-yet-valid")
    if now > claims["exp"] + LEEWAY_SECONDS:
        return _refuse("token-expired", "expired")
    if claims["aud"] != audience:
        return _refuse("wrong-audience", "audience-mismatch")
    depth = chain_depth(claims["act"])
    if not math.isfinite(depth):
        return _refuse("unauthenticated", "malformed-chain")
    if depth > MAX_CHAIN_DEPTH:
        return _refuse("chain-too-deep", "depth-%d" % depth)
    if capability not in claims["scope"].split(" "):
        return _refuse("scope-not-granted", "capability-not-in-scope")
    if read_only and effect != "none":
        return _refuse("effect-above-ceiling", "read-only-door")
    if not effect_within(effect, claims["effect"]):
        return _refuse("effect-above-ceiling", "effect-%s" % effect)
    return {"ok": True, "claims": claims, "principal": claims["sub"], "caller": claims["act"]["sub"],
            "chain": _chain_of(claims["act"]), "kid": checked["kid"]}


class MemoryJtiStore:
    """Consumed approval ids in memory: for tests and a single process that never restarts mid-approval."""

    def __init__(self) -> None:
        self._seen: Dict[str, float] = {}
        self._lock = threading.Lock()

    def consume(self, jti: str, expires_at: float, now: float) -> bool:
        with self._lock:
            for key, until in list(self._seen.items()):
                if until + LEEWAY_SECONDS < now:
                    del self._seen[key]
            if jti in self._seen:
                return False
            self._seen[jti] = expires_at
            return True


class FileJtiStore:
    """Consumed approval ids in a 0600 JSON file, so a second use is refused across a restart (DL-18). One
    service instance writes it (the kit's instance lock keeps other processes out); threads are serialised."""

    _locks: Dict[str, threading.Lock] = {}
    _locks_guard = threading.Lock()

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        with FileJtiStore._locks_guard:
            self._lock = FileJtiStore._locks.setdefault(str(self.path.resolve()), threading.Lock())

    def consume(self, jti: str, expires_at: float, now: float) -> bool:
        with self._lock:
            try:
                seen = json.loads(self.path.read_text())
                if not isinstance(seen, dict):
                    seen = {}
            except (OSError, ValueError):
                seen = {}
            seen = {k: v for k, v in seen.items() if isinstance(v, (int, float)) and v + LEEWAY_SECONDS >= now}
            if jti in seen:
                return False
            seen[jti] = expires_at
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(".%s.%s.tmp" % (self.path.name, secrets.token_hex(4)))
            fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as handle:
                json.dump(seen, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(temp), str(self.path))
            return True


class _NoReplayProtection:
    def consume(self, jti: str, expires_at: float, now: float) -> bool:  # noqa: ARG002
        return True


# Every approval may be replayed until it expires. Only on purpose, by name.
UNSAFE_NO_JTI_STORE = _NoReplayProtection()


def verify_approval(approval: Optional[str], *, audience: str, jwks: Any, now: float, action_digest: str,
                    jti_store: Any, issuer: Optional[str] = None) -> Dict[str, Any]:
    """DL-18: a missing approval is approval-required carrying the action digest; any fault of the document is
    approval-invalid; a second use is approval-reused. The jti is consumed last."""
    if approval is None or approval == "":
        return _refuse("approval-required", "no-approval", {"actionDigest": action_digest})
    if jti_store is None or not callable(getattr(jti_store, "consume", None)):
        return _refuse("unknown-state", "no-jti-store")
    if not _has_keys(jwks):
        return _refuse("issuer-unavailable", "no-published-keys")
    checked = _authentic(approval, jwks, APPROVAL_TYP)
    if "problem" in checked:
        return _refuse("issuer-unavailable" if checked.get("issuer") else "approval-invalid", checked["problem"])
    claims = checked["compact"]["payload"]
    if not _approval_shape(claims):
        return _refuse("approval-invalid", "malformed-claims")
    if issuer is not None and claims["iss"] != issuer:
        return _refuse("approval-invalid", "wrong-issuer")
    if claims["exp"] <= claims["iat"] or claims["exp"] - claims["iat"] > MAX_APPROVAL_LIFETIME_SECONDS:
        return _refuse("approval-invalid", "lifetime-above-profile")
    if claims["iat"] > now + LEEWAY_SECONDS:
        return _refuse("approval-invalid", "issued-in-future")
    if now > claims["exp"] + LEEWAY_SECONDS:
        return _refuse("approval-invalid", "expired")
    if claims["aud"] != audience:
        return _refuse("approval-invalid", "audience-mismatch")
    if claims["actionDigest"] != action_digest:
        return _refuse("approval-invalid", "digest-mismatch", {"actionDigest": action_digest})
    if not jti_store.consume(claims["jti"], claims["exp"], now):
        return _refuse("approval-reused", "jti-consumed")
    return {"ok": True, "claims": claims, "approver": claims["approver"], "method": claims["method"], "kid": checked["kid"]}


def _header(headers: Any, name: str) -> Optional[str]:
    if headers is None:
        return None
    if hasattr(headers, "get_all"):  # http.server's and email's message: case-insensitive
        values = headers.get_all(name)
        return values[0] if values else None
    if isinstance(headers, Mapping):
        for key, value in headers.items():
            if isinstance(key, str) and key.lower() == name.lower():
                if isinstance(value, (list, tuple)):
                    return str(value[0]) if value else ""
                return value
    return None


def read_delegation_token(headers: Any) -> Optional[Dict[str, str]]:
    """DL-9, DL-10: the hub's Fabric-Delegation header first (present but empty is still the token, refused
    later, never a fall-through), then a delegation-typ JWT in Authorization: Bearer."""
    forwarded = _header(headers, DELEGATION_HEADER)
    if forwarded is not None:
        return {"token": forwarded.strip(), "via": "fabric-delegation"}
    match = re.fullmatch(r"Bearer\s+(\S+)", _header(headers, "Authorization") or "", re.IGNORECASE)
    if match:
        parsed = _parse_compact(match.group(1))
        if "problem" not in parsed and parsed["header"].get("typ") == DELEGATION_TYP:
            return {"token": match.group(1), "via": "authorization"}
    return None


# --- RFC 8785 canonical JSON --------------------------------------------------------------------------------

def _number(value: float) -> str:
    """ECMAScript Number::toString, which RFC 8785 §3.2.2.3 prescribes."""
    if value == 0:
        return "0"
    if value < 0:
        return "-" + _number(-value)
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


_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _string(value: str) -> str:
    out = ['"']
    for ch in value:
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            raise TypeError("a lone surrogate has no canonical form")
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
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
        return str(value) if abs(value) < 2 ** 53 else _number(float(value))
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("a non-finite number has no canonical form")
        return _number(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ",".join(jcs(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("only string member names have a canonical form")
        keys = sorted(value, key=lambda key: key.encode("utf-16-be", "surrogatepass"))
        return "{" + ",".join(_string(key) + ":" + jcs(value[key]) for key in keys) + "}"
    raise TypeError("%s has no canonical form" % type(value).__name__)


def action_digest(action: Any) -> str:
    """The digest an approval binds: sha256: and the hex SHA-256 of the action's RFC 8785 form."""
    return "sha256:" + hashlib.sha256(jcs(action).encode("utf-8")).hexdigest()


# --- the estate's keys ----------------------------------------------------------------------------------------

def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _fetch(source: str) -> Any:
    if source.startswith(("https://", "http://")):
        request = urllib.request.Request(source, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - https or loopback http only
            return json.loads(response.read(65537)[:65536])
    return json.loads(Path(source).expanduser().read_text())


class JwksCache:
    """The estate's key set from `auth.delegation.jwks` (https, http on loopback, or a file), cached as DL-15
    says: at most 10 minutes, re-read at most once a minute for a kid it does not hold. `get()` answers None
    when no set younger than 10 minutes can be had, which the verifier reports as issuer-unavailable."""

    def __init__(self, source: str, *, fetch: Optional[Callable[[str], Any]] = None, clock: Callable[[], float] = time.time):
        if not isinstance(source, str) or not source:
            raise ValueError("the key set needs a source")
        if source.startswith(("https://", "http://")):
            parts = urllib.parse.urlsplit(source)
            if parts.username or parts.password:
                raise ValueError("a key set URL carries no credentials")
            if parts.scheme == "http" and not _loopback(parts.hostname or ""):
                raise ValueError("a key set is read over https, or over http on loopback only")
        elif "://" in source:
            raise ValueError("a key set is an https URL, a loopback http URL or a file path")
        self.source = source
        self._fetch = fetch or _fetch
        self._clock = clock
        self._keys: Optional[Dict[str, Any]] = None
        self._read_at = -math.inf
        self._tried_at = -math.inf
        self._reread_at = -math.inf  # the last re-read for a kid the set did not hold
        self._lock = threading.Lock()

    def _read(self, now: float) -> None:
        self._tried_at = now
        try:
            value = self._fetch(self.source)
        except (OSError, ValueError):
            return
        if _has_keys(value):
            self._keys, self._read_at = value, now

    def get(self, kid: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            now = self._clock()
            fresh = now - self._read_at < JWKS_MAX_AGE_SECONDS
            known = self._keys is not None and (kid is None or any(isinstance(k, dict) and k.get("kid") == kid for k in self._keys["keys"]))
            if not fresh:
                self._read(now)
            elif not known and now - self._reread_at >= JWKS_REREAD_SECONDS:
                self._reread_at = now
                self._read(now)
            return self._keys if now - self._read_at < JWKS_MAX_AGE_SECONDS else None


def _kid_of(token: str) -> Optional[str]:
    parsed = _parse_compact(token)
    kid = parsed.get("header", {}).get("kid") if "problem" not in parsed else None
    return kid if isinstance(kid, str) else None


# --- the gate in front of a service's tools ------------------------------------------------------------------

def delegation_gate(*, audience: str, jwks: Any, effects: Mapping[str, str], issuer: Optional[str] = None,
                    read_only: bool = False, clock: Callable[[], float] = time.time) -> Callable[[str, Any], Dict[str, Any]]:
    """A check for one tools/call: `gate(tool, headers)` answers the accepted delegation or a DL-19 refusal.
    `effects` maps each tool to its declared effect class (its manifest entry); a tool with none is refused
    rather than guessed. `jwks` is a JwksCache or a key set."""

    def gate(tool: str, headers: Any) -> Dict[str, Any]:
        effect = effects.get(tool)
        if effect not in EFFECT_CLASSES:
            return _refuse("unknown-state", "no-declared-effect")
        carried = read_delegation_token(headers)
        if carried is None:
            return _refuse("unauthenticated", "no-token")
        keys = jwks.get(_kid_of(carried["token"])) if isinstance(jwks, JwksCache) else jwks
        return verify_delegation(carried["token"], audience=audience, jwks=keys, now=clock(), capability=tool,
                                 effect=effect, issuer=issuer, read_only=read_only)

    return gate


def refusal_error(refusal: Dict[str, Any]) -> Dict[str, Any]:
    """The DL-19 body: {error: {code, message, data: {detail, ...}}}; never a token or a key."""
    data = {"detail": refusal["detail"]}
    data.update(refusal.get("data") or {})
    return {"error": {"code": refusal["code"], "message": REFUSAL_MESSAGES.get(refusal["code"], "Refused."), "data": data}}


def refusal_tool_result(refusal: Dict[str, Any], traceparent: Optional[str] = None) -> Dict[str, Any]:
    """An MCP tools/call result: the refusal as structuredContent with isError true (DL-19)."""
    structured = refusal_error(refusal)
    result: Dict[str, Any] = {"resultType": "complete", "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)}],
                              "structuredContent": structured, "isError": True}
    if traceparent:
        result["_meta"] = {"traceparent": traceparent}
    return result


def refusal_http(refusal: Dict[str, Any]) -> Tuple[int, Dict[str, str], bytes]:
    """An HTTP route's answer: status, headers and JSON body; a 401 names the bearer scheme (RFC 6750 §3)."""
    status = REFUSAL_STATUS.get(refusal["code"], 403)
    headers = {"Content-Type": "application/json", "Cache-Control": "no-store"}
    if status == 401:
        headers["WWW-Authenticate"] = 'Bearer error="invalid_token"'
    return status, headers, json.dumps(refusal_error(refusal)).encode()
