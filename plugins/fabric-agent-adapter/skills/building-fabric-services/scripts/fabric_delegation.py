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
import urllib.error
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
# After a failed read, wait this long before trying again, so a down issuer does not cost every call a fetch.
JWKS_RETRY_SECONDS = 10
# JavaScript's String.prototype.trim set, so a header is trimmed as the contract's verifier trims it.
_JS_WHITESPACE = "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"

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
# DL-2's grammar, as the contract's verifier types the claims (DEC-0045): an agent id, an opaque session or task id,
# a URI, a jti and a scope.
AGENT_ID = re.compile(r"^[a-z][a-z0-9-]{1,62}(\.[a-z][a-z0-9-]{0,31})?$")
OPAQUE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:\S+$")
_JTI = re.compile(r"^[A-Za-z0-9._~-]{16,128}$")
_SCOPE = re.compile(r"^[a-z][a-z0-9._-]{1,127}( [a-z][a-z0-9._-]{1,127})*$")
_SPEND_WINDOWS = ("total", "task", "project", "day", "week", "month")
# The small-order points of edwards25519 and their non-canonical encodings, sign bit cleared (the contract's
# src/ed25519.ts; libsodium's has_small_order list).
SMALL_ORDER_ENCODINGS = (
    "0000000000000000000000000000000000000000000000000000000000000000", "0100000000000000000000000000000000000000000000000000000000000000",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05", "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f", "edffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
    "eeffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
)
_MISSING = object()


def is_small_order_key(raw: bytes) -> bool:
    """Whether a 32-byte Ed25519 public key is a point of small order, in any encoding (CT-29)."""
    if len(raw) != 32:
        return True
    return (raw[:31] + bytes([raw[31] & 0x7F])).hex() in SMALL_ORDER_ENCODINGS


def _full(pattern: "re.Pattern[str]", value: Any) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


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
_IDENTITY = (1).to_bytes(32, "little")


def ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """RFC 8032 §5.1.7, cofactorless: [S]B == R + [k]A, compared by R's encoding. False, never an exception."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    a = _decode_point(public_key)
    if a is None or _encode_point(_mul(8, a)) == _IDENTITY:
        return False  # a small-order key would accept R = [S]B for a quarter or more of all messages; OpenSSL refuses it
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
        except (ValueError, RecursionError):
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
    if is_small_order_key(raw):
        return {"problem": "small-order-key"}  # refused before any verification (DEC-0045, CT-29)
    return {"key": raw, "x": jwk["x"]}


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
        # Only an unknown kid is the token's fault; a published key that cannot be used is the issuer's (DL-13 row 3).
        return {"problem": found["problem"], "issuer": found["problem"] != "unknown-key"}
    if len(compact["signature"]) != 64 or not ed25519_verify(found["key"], compact["signing_input"], compact["signature"]):
        return {"problem": "bad-signature"}
    return {"compact": compact, "kid": kid, "x": found["x"]}


_ORG_CONTEXT = re.compile(r"org:[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


def is_partner_actor(node: Any) -> bool:
    """DEC-0090: a partner actor is exactly {partner: org:<id>}, never with a sub, a session or an act."""
    return isinstance(node, dict) and len(node) == 1 and isinstance(node.get("partner"), str) and _ORG_CONTEXT.match(node["partner"]) is not None


def chain_depth(act: Any) -> float:
    """Depth of an actor chain; infinity for a chain that is not one (a missing or non-string sub at any level). A
    partner actor ends the chain and counts, never begins it (DEC-0090)."""
    depth = 0
    node = act
    while node is not _MISSING:
        if depth > 0 and is_partner_actor(node):
            return depth + 1
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
        chain.append(node["partner"] if "partner" in node else node["sub"])  # the contract's chainOf, partner first
        node = node.get("act") if "act" in node else None
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


def _actor_chain_depth(act: Any) -> Optional[int]:
    """The chain's depth when every actor is DL-2's (an agent id `sub`, an optional session id), else None. A token
    with no `act` has no caller, so it is no chain either."""
    if act is _MISSING:
        return None
    depth = 0
    node = act
    while node is not _MISSING:
        if depth > 0 and is_partner_actor(node):  # DEC-0090: innermost only, it ends the chain
            return depth + 1
        if not isinstance(node, dict) or not _full(AGENT_ID, node.get("sub")):
            return None
        if "session" in node and not _full(OPAQUE_ID, node["session"]):
            return None
        depth += 1
        node = node.get("act", _MISSING)
    return depth


def _is_amount(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _spend_shaped(spend: Any) -> bool:
    if not isinstance(spend, dict):
        return False
    if spend.get("mode") == "unlimited":
        return True
    remaining = spend.get("remaining")
    if spend.get("mode") != "limited" or not isinstance(remaining, list) or not 1 <= len(remaining) <= 6:
        return False
    if not all(isinstance(e, dict) and e.get("window") in _SPEND_WINDOWS and _is_amount(e.get("remainingUsd")) for e in remaining):
        return False
    return "perCallMaxUsd" not in spend or _is_amount(spend["perCallMaxUsd"])


def _delegation_shape(payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[int]]:
    """DL-13 row 5 as DEC-0045 types it: (problem, depth). A claim the profile does not know is ignored."""
    depth = _actor_chain_depth(payload.get("act", _MISSING))
    if depth is None:
        return "malformed-chain", None
    effect, grant = payload.get("effect"), payload.get("grant")
    typed = (_full(_URI, payload.get("iss")) and _full(_URI, payload.get("sub")) and _full(AGENT_ID, payload.get("aud"))
             and isinstance(payload.get("scope"), str) and len(payload["scope"]) <= 4096 and _full(_SCOPE, payload["scope"])
             and isinstance(effect, list) and len(effect) > 0 and all(isinstance(e, str) and e in EFFECT_CLASSES for e in effect)
             and len(set(effect)) == len(effect)
             and isinstance(grant, list) and len(grant) == 1 and isinstance(grant[0], str) and 1 <= _utf16_length(grant[0]) <= 256
             and ("spend" not in payload or _spend_shaped(payload["spend"]))
             and ("project" not in payload or _full(_URI, payload["project"]))
             and ("task" not in payload or _full(OPAQUE_ID, payload["task"]))
             and _is_time(payload.get("iat")) and _is_time(payload.get("exp"))
             and ("nbf" not in payload or _is_time(payload["nbf"])) and _full(_JTI, payload.get("jti")))
    return (None, depth) if typed else ("malformed-claims", None)


def _approval_shape(payload: Dict[str, Any]) -> bool:
    if not all(_is_string(payload.get(k)) for k in ("iss", "actionDigest", "aud", "approver", "jti")):
        return False
    if not _is_time(payload.get("iat")) or not _is_time(payload.get("exp")):
        return False
    return payload.get("method") in ("prompt", "operator-channel")  # DEC-0045: `device` is removed


#: ECMAScript's time range in seconds (±8.64e15 ms): a NumericDate outside it is no instant a Date can hold.
MAX_CLOCK_SECONDS = 8.64e12


def _readable_clock(now: Any) -> bool:
    """A clock the time rows can compare: a finite number of seconds within a Date's range (DEC-0060). NaN or text
    would make every time row false and let an expired token through."""
    if not isinstance(now, (int, float)) or isinstance(now, bool):
        return False
    try:
        return math.isfinite(now) and abs(now) <= MAX_CLOCK_SECONDS
    except OverflowError:
        return False


def _estate_problem(estate: Any, kid: str, x: str, now: float, applied: Any = None,
                    revocations: Any = None) -> Optional[Tuple[str, str]]:
    """DL-14 row 4a (DEC-0055, DEC-0060), right after the signature: when the callee reads the estate record, the
    token's kid and the published key must be certified by that revision. `estate` is a revision the caller verified
    (fabric_estate.verify_estate_record) and its machine applied, or a callable returning it; None skips the rule (a
    callable returning None is an unreadable source). `applied` is the highest revision the machine applied
    (`{"revision", "digest"?}`); `revocations` the revocation delta's entries applied since (a list or a callable). A
    source that raises is unreadable, never a pass. Returns ("token" | "issuer", detail) or None."""
    if estate is None:
        return None
    try:
        record = estate() if callable(estate) else estate
        extra = revocations() if callable(revocations) else revocations
    except Exception:
        return ("issuer", "estate-unreadable")
    import fabric_estate  # beside this file; imported here, since fabric_estate imports this module
    verdict = fabric_estate.hub_key_certified(record, kid, x, now, applied,
                                              fabric_estate._MISSING if extra is None else extra)
    if verdict["certified"]:
        return None
    # The clock was refused before row 1, so a verdict here is the token's or the trust source's.
    return ("token" if verdict["fault"] == "token" else "issuer", verdict["detail"])


def verify_delegation(token: Any, *, audience: str, jwks: Any, now: float, capability: str, effect: str,
                      issuer: Optional[str], read_only: bool = False, estate: Any = None,
                      estate_applied: Any = None, estate_revocations: Any = None) -> Dict[str, Any]:
    """DL-13, in its fixed order: nothing about a token is believed before its signature is.
    `now` is seconds since the epoch. Returns {ok: True, claims, principal, caller, chain, kid} or a refusal
    {ok: False, code, detail[, data]} whose detail is a short machine word, never the token. `issuer` is required.
    With `estate` (a verified estate revision, or a callable returning the current one), the token's kid must be one
    the revision certifies for a machine (DL-14, DEC-0055, DEC-0060); `estate_applied` is the highest revision the
    machine applied and `estate_revocations` the revocation delta's entries since. A clock that is not a number of
    seconds is refused `unknown-state` `no-clock` before row 1."""
    # Before row 1: every time row compares against the clock, and a comparison with NaN is always false.
    if not _readable_clock(now):
        return _refuse("unknown-state", "no-clock")
    if not _is_string(issuer):
        return _refuse("issuer-unavailable", "no-trusted-issuer")
    if not _has_keys(jwks):
        return _refuse("issuer-unavailable", "no-published-keys")
    checked = _authentic(token, jwks, DELEGATION_TYP)
    if "problem" in checked:
        return _refuse("issuer-unavailable" if checked.get("issuer") else "unauthenticated", checked["problem"])
    uncertified = _estate_problem(estate, checked["kid"], checked["x"], now, estate_applied, estate_revocations)
    if uncertified:
        return _refuse("issuer-unavailable" if uncertified[0] == "issuer" else "unauthenticated", uncertified[1])
    claims = checked["compact"]["payload"]
    problem, depth = _delegation_shape(claims)
    if problem:
        return _refuse("unauthenticated", problem)
    if claims["iss"] != issuer:
        return _refuse("unauthenticated", "wrong-issuer")
    if claims["exp"] <= claims["iat"] or claims["exp"] - claims["iat"] > MAX_DELEGATION_LIFETIME_SECONDS:
        return _refuse("unauthenticated", "lifetime-above-profile")
    if claims["iat"] > now + LEEWAY_SECONDS:
        return _refuse("unauthenticated", "issued-in-future")
    if "nbf" in claims and claims["nbf"] > now + LEEWAY_SECONDS:
        return _refuse("unauthenticated", "not-yet-valid")
    if now > claims["exp"] + LEEWAY_SECONDS:
        return _refuse("token-expired", "expired")
    if claims["aud"] != audience:
        return _refuse("wrong-audience", "audience-mismatch")
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


class JtiStoreError(RuntimeError):
    """A jti store that cannot tell whether an id was consumed; the verifier answers unknown-state."""


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
        """True the first time; False for a used id. Raises JtiStoreError when the file cannot be read: forgetting
        every consumed id would let each approval be replayed."""
        with self._lock:
            try:
                seen = json.loads(self.path.read_text())
            except FileNotFoundError:
                seen = {}
            except (OSError, ValueError) as exc:
                raise JtiStoreError("the consumed-approval file cannot be read: %s" % exc.__class__.__name__) from None
            if not isinstance(seen, dict):
                raise JtiStoreError("the consumed-approval file is not a JSON object")
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
                    jti_store: Any, issuer: Optional[str], estate: Any = None, estate_applied: Any = None,
                    estate_revocations: Any = None) -> Dict[str, Any]:
    """DL-18: a missing approval is approval-required carrying the action digest; any fault of the document is
    approval-invalid; a second use is approval-reused. The jti is consumed last."""
    if approval is None or approval == "":
        return _refuse("approval-required", "no-approval", {"actionDigest": action_digest})
    if jti_store is None or not callable(getattr(jti_store, "consume", None)):
        return _refuse("unknown-state", "no-jti-store")
    if not _readable_clock(now):
        return _refuse("unknown-state", "no-clock")
    if not _is_string(issuer):
        return _refuse("issuer-unavailable", "no-trusted-issuer")
    if not _has_keys(jwks):
        return _refuse("issuer-unavailable", "no-published-keys")
    checked = _authentic(approval, jwks, APPROVAL_TYP)
    if "problem" in checked:
        return _refuse("issuer-unavailable" if checked.get("issuer") else "approval-invalid", checked["problem"])
    uncertified = _estate_problem(estate, checked["kid"], checked["x"], now, estate_applied, estate_revocations)
    if uncertified:
        return _refuse("issuer-unavailable" if uncertified[0] == "issuer" else "approval-invalid", uncertified[1])
    claims = checked["compact"]["payload"]
    if not _approval_shape(claims):
        return _refuse("approval-invalid", "malformed-claims")
    if claims["iss"] != issuer:
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
    try:
        fresh = jti_store.consume(claims["jti"], claims["exp"], now)
    except Exception:  # a store that cannot answer is an unknown state, never a pass (DL-19)
        return _refuse("unknown-state", "jti-store-failed")
    if not fresh:
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
        return {"token": forwarded.strip(_JS_WHITESPACE), "via": "fabric-delegation"}
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
        if abs(value) < 2 ** 53:
            return str(value)
        try:
            return _number(float(value))
        except OverflowError:
            raise TypeError("a number beyond a double has no canonical form") from None
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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect could leave https or loopback for any scheme or host: none is followed."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _fetch(source: str) -> Any:
    if source.startswith(("https://", "http://")):
        request = urllib.request.Request(source, headers={"Accept": "application/json"})
        try:
            with _OPENER.open(request, timeout=5) as response:  # https or loopback http only, no redirect
                return json.loads(response.read(65537)[:65536])
        except urllib.error.HTTPError as exc:
            exc.close()
            raise
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
                if now - self._tried_at >= JWKS_RETRY_SECONDS:
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

TIERS = ("T0", "T1", "T2")


def delegation_gate(*, audience: str, jwks: Any, effects: Mapping[str, str], issuer: str,
                    read_only: bool = False, clock: Callable[[], float] = time.time, estate: Any = None,
                    estate_applied: Any = None, estate_revocations: Any = None) -> Callable[..., Dict[str, Any]]:
    """A check for one tools/call: `gate(tool, headers, tier="T2")` answers the accepted delegation or a DL-19
    refusal. `effects` maps each tool to its declared effect class (its manifest entry); a tool with none is
    refused rather than guessed. `jwks` is a JwksCache or a key set; `issuer` (auth.delegation.issuer) is required.

    DL-25, DL-26: `tier` is the caller's origin. T0 is a loopback caller under the owner's account that the service's
    own local floor has authenticated; T1 an enrolled machine of the same owner; T2 everything else, and any call
    relayed from off the machine. A T0 or T1 caller is never required to present a token: with none, the call
    passes with no delegation ({ok: True, tier, principal: None, ...}). A present token is verified at every tier
    and refused when invalid. Unknown tiers count as T2. `estate` (a callable returning the current verified estate
    revision) makes the gate trust only kids that revision certifies (DL-14, DEC-0055, DEC-0060); `estate_applied` and
    `estate_revocations` pass the applied mark and the revocation delta's entries through."""
    if not _is_string(issuer):
        raise ValueError("the gate needs the issuer it trusts (auth.delegation.issuer)")

    def gate(tool: str, headers: Any, tier: str = "T2") -> Dict[str, Any]:
        effect = effects.get(tool)
        if effect not in EFFECT_CLASSES:
            return _refuse("unknown-state", "no-declared-effect")
        carried = read_delegation_token(headers)
        if carried is None:
            if tier in ("T0", "T1"):
                return {"ok": True, "tier": tier, "principal": None, "caller": None, "chain": [], "claims": None, "kid": None}
            return _refuse("unauthenticated", "no-token")
        keys = jwks.get(_kid_of(carried["token"])) if isinstance(jwks, JwksCache) else jwks
        verdict = verify_delegation(carried["token"], audience=audience, jwks=keys, now=clock(), capability=tool,
                                    effect=effect, issuer=issuer, read_only=read_only, estate=estate,
                                    estate_applied=estate_applied, estate_revocations=estate_revocations)
        if verdict["ok"]:
            verdict["tier"] = tier if tier in TIERS else "T2"
        return verdict

    return gate


def refusal_from_denial(denial: Dict[str, Any]) -> Dict[str, Any]:
    """DL-21 step 6 (DEC-0045): the refusal a callee answers after the meter denied a grant check. The meter's code
    goes unchanged into error.code; its window, level (when set) and approvalRequest into error.data."""
    data = {k: denial[k] for k in ("window", "approvalRequest") if denial.get(k) is not None}
    if denial.get("level") is not None:
        data["level"] = denial["level"]
    error: Dict[str, Any] = {"code": denial["code"], "message": ("the meter denied the spend: %s" % denial.get("reason", ""))[:500]}
    if data:
        error["data"] = data
    return {"error": error}


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
