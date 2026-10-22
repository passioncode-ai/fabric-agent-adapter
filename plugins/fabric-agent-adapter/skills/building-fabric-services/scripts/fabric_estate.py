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
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fabric_crypto import ed25519_verify, is_small_order_key  # noqa: E402 - beside this file (FAA-65)
from fabric_jsvalue import jcs  # noqa: E402 - beside this file (FAA-65)
import fabric_secrets as _secrets  # noqa: E402 - beside this file: the contract's credential detector
from fabric_crypto import (  # noqa: E402 - the core (FAA-65)
    _P256_B as _B,
    _P256_N as _N,
    _P256_P as _P,
    _der_signature,
    b64url as _b64url,
    b64url_bytes as _b64url_bytes,
    es256_verify,
    is_valid_p256_key,
    node_base64 as _node_base64,
    sha256 as _sha256,
)
from fabric_jsvalue import (  # noqa: E402 - the core (FAA-65)
    MISSING as _MISSING,
    contains as _contains,
    get as _get,
    get_string as _s,
    indexed_objects as _indexed,
    js_string as _js_string,
    js_to_number as _js_to_number,
    key_of as _key_of,
    objects as _list,
    safe_integer as _safe_integer,
    same as _same,
    show as _show,
)
from fabric_time import (  # noqa: E402 - the core (FAA-65)
    clock_ms as _clock,
    parse_rfc3339_ms as estate_time,
)

ESTATE_RECORD_SCHEMA = "estate-record/1"
ESTATE_CHALLENGE_TYPE = "estate-revision/1"
MAX_VALIDITY_SECONDS = 30 * 24 * 60 * 60
#: How far ahead of the verifier's clock a signed `issuedAt` may be before it is `not-yet-valid` (DEC-0066): the one
#: skew of the relay family's and the estate record's times (`CLOCK_SKEW_SECONDS` in the contract's `src/rfc3339.ts`).
CLOCK_SKEW_SECONDS = 60
ASSERTION_ALGORITHMS = ("ES256", "EdDSA")
FLAGS = {"UP": 0x01, "UV": 0x04, "BE": 0x08, "BS": 0x10, "AT": 0x40, "ED": 0x80}
_B64URL = re.compile(r"[A-Za-z0-9_-]+")
_SURROGATE = re.compile("[\ud800-\udfff]")


# --- JavaScript's view of JSON values, which the contract's answers are written in ---------------------------------


#: DEC-0082: the personal context, and an organization's context ``org:<orgId>`` (the contract's ``context-route.ts``).
PERSONAL_CONTEXT = "personal"
ORG_CONTEXT_PREFIX = "org:"
_ORG_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


def parse_context(value: Any) -> Optional[Dict[str, str]]:
    """The context ``value`` names, or None when it names none: ``personal`` exactly, or ``org:`` and an organization id
    (``[A-Za-z0-9][A-Za-z0-9_-]{0,127}``). Compared as written: ``Personal``, ``ORG:x`` or a trailing newline name no
    context. Never raises."""
    if not isinstance(value, str):
        return None
    if value == PERSONAL_CONTEXT:
        return {"kind": "personal"}
    if not value.startswith(ORG_CONTEXT_PREFIX):
        return None
    org = value[len(ORG_CONTEXT_PREFIX):]
    return {"kind": "org", "org": org} if _ORG_ID.fullmatch(org) else None


def _context_of(entry: Any) -> Any:
    """A placement's or a secret placement's context: its ``context``, ``personal`` when absent (DEC-0082)."""
    context = _get(entry, "context")
    return PERSONAL_CONTEXT if context is _MISSING else context


# --- P-256 (DEC-0053; SEC 1 v2, FIPS 186-5) ------------------------------------------------------------------------


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
    if is_small_order_key(raw):
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
            else len(signature) == 64 and ed25519_verify(key[1], signed, signature))
    if not good:
        return fail("bad-signature")
    return {"ok": True, "flags": flags, "signCount": int.from_bytes(auth_data[33:37], "big")}


# --- the record (src/estate-record-rules.ts) ---------------------------------------------------------------------

def estate_record_digest(record: Dict[str, Any]) -> str:
    """`sha256:` and the hex SHA-256 of the UTF-8 RFC 8785 form of the record without `digest` and `signature`.
    Raises TypeError for a value RFC 8785 has no form for."""
    covered = {k: v for k, v in record.items() if k not in ("digest", "signature")}
    return "sha256:" + hashlib.sha256(jcs(covered).encode("utf-8")).hexdigest()


def estate_challenge_input(digest: str) -> bytes:
    return jcs({"type": ESTATE_CHALLENGE_TYPE, "digest": digest}).encode("utf-8")


def estate_challenge(digest: str) -> bytes:
    """The WebAuthn challenge a signer passes to navigator.credentials.get(): SHA-256 of estate_challenge_input."""
    return _sha256(estate_challenge_input(digest))


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
    return "%s %s" % (_show(_get(entry, "kind")), _show(_get(entry, "ref")))


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
    # With a parent, what the revision drops it revokes (FAC-SEM-114, DEC-0084): a removed machine, a replaced key.
    dropped = _dropped_findings(parent, record) if isinstance(parent, dict) else []
    for finding in _record_findings(record) + dropped:
        if finding["code"] not in codes:
            codes.append(finding["code"])
    if codes:
        return {"ok": False, "problem": "rule-violation", "codes": codes}
    return {"ok": True, "digest": digest, "revision": record["revision"], "signedBy": credential["credentialId"], "signCount": assertion["signCount"]}


def placement_trust(record: Dict[str, Any], machine_id: str, agent_ref: str, context: str = PERSONAL_CONTEXT) -> Optional[Dict[str, Any]]:
    """What a package verifier (DEC-0051) trusts for a package placed on a machine in a context (DEC-0082; ``personal``
    when not given, so a caller written before contexts is unchanged): the publisher keys the placement names, from the
    record's `publisherKeys`. None when the record places no such agent on that machine in that context."""
    machine = next((m for m in _list(_get(record, "machines")) if _same(_get(m, "id"), machine_id)), None)
    placement = next((p for p in _list(_get(machine, "packages"))
                      if _same(_get(p, "agentRef"), agent_ref) and _same(_context_of(p), context)), None)
    if placement is None:
        return None
    if not _scope_admits(record, _get(placement, "publisherKid"), context):  # DEC-0090: a partner's key, in its contexts only
        return {"publisher": []}
    return {"publisher": [k for k in _list(_get(record, "publisherKeys")) if _same(_get(k, "kid"), _get(placement, "publisherKid"))]}


def _scope_admits(record: Any, kid: Any, context: Any) -> bool:
    """DEC-0090: a key no `publisherScopes[]` entry names is trusted in any context; a partner's key, only in a context
    one of its scopes lists."""
    scopes = [s for s in _list(_get(record, "publisherScopes")) if _same(_get(s, "kid"), kid)]
    return not scopes or any(isinstance(_get(s, "contexts"), list) and _contains(s["contexts"], context) for s in scopes)


#: v4 §7, Freshness: an estate revision's window is at most 30 days (DEC-0055 item 2).
_MAX_WINDOW_MS = MAX_VALIDITY_SECONDS * 1000


def _refused(fault: str, detail: str) -> Dict[str, Any]:
    return {"certified": False, "fault": fault, "detail": detail}


def _revision_number(value: Any) -> bool:
    return _safe_integer(value) and value >= 1


def hub_key_certified(record: Any, kid: Any, x: Any, at: Any, applied: Any = _MISSING,
                      extra_revocations: Any = _MISSING) -> Dict[str, Any]:
    """DL-14 (DEC-0055, DEC-0060): whether ``record`` certifies the delegation key ``kid`` with the published key's ``x``
    at ``at`` (an aware datetime or epoch seconds), for a verifier whose machine applied ``applied``
    (``{"revision", "digest"?}``; ``_MISSING``, the default, when none is known; an explicit None is no revision and
    fails closed as ``estate-unreadable``, as Node's null does, decision D3). ``extra_revocations`` are the revocation
    delta's entries applied since the revision (DEC-0054). The contract's ``hubKeyCertified``, in its order; never raises. Answers ``{"certified": True, "machine",
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
    if applied is not _MISSING:
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
        flag("/next/revision", "the revision after %s is %s: a revision never skips or repeats one" % (_show(_get(parent, "revision")), _js_string(expected)))
    try:
        parent_digest: Any = estate_record_digest(parent)
    except TypeError:
        parent_digest = _MISSING
    if not _same(_get(nxt, "parent"), parent_digest):
        flag("/next/parent", "parent names the digest of the revision before it")
    if _lt(estate_time(_get(nxt, "issuedAt")), estate_time(_get(parent, "issuedAt"))):
        flag("/next/issuedAt", "a revision is never issued before its parent")
    kept = {_revocation_key(e) for e in _list(_get(nxt, "revocations"))}
    for entry, index in _indexed(_get(parent, "revocations")):
        if _revocation_key(entry) not in kept:
            flag("/parent/revocations/%d" % index, "the %s revocation of %s is dropped: a revision keeps every revocation before it" % (_show(_get(entry, "kind")), _show(_get(entry, "ref"))))
    return findings


#: Standard base64 with its padding, the one form DEC-0053 records a device key's octets in.
_BASE64 = re.compile(r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?\Z")
#: DEC-0084: a key reference, a device-key kid, ``@sha256:`` and 64 lower-case hex digits.
KEY_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}#(sig|kem)@sha256:[a-f0-9]{64}\Z")


def device_key_fingerprint(key: Any) -> Optional[str]:
    """A device key's fingerprint (DEC-0084): ``sha256:`` and the hex SHA-256 of its octets, ``publicKey`` read as
    canonical padded base64; None for any other form, so two readers never disagree on which key it names."""
    text = key.get("publicKey") if isinstance(key, dict) else None
    if not isinstance(text, str) or not text or not _BASE64.match(text):
        return None
    raw = base64.b64decode(text)
    if base64.b64encode(raw).decode("ascii") != text:
        return None
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def device_key_ref(key: Any) -> Optional[str]:
    """The ``device-key`` revocation reference of one key (DEC-0084): ``<kid>@<fingerprint>``; None without a string kid
    or a fingerprint. A replacement revokes the old key by it and leaves the next key under the same kid usable."""
    fingerprint = device_key_fingerprint(key)
    kid = key.get("kid") if isinstance(key, dict) else None
    return "%s@%s" % (kid, fingerprint) if fingerprint is not None and isinstance(kid, str) else None


def _valid_device_key(key: Dict[str, Any]) -> bool:
    public = _get(key, "publicKey")
    raw = _node_base64("" if public is _MISSING or public is None else _show(public))
    if _get(key, "alg") == "ed25519":
        return len(raw) == 32 and not is_small_order_key(raw)
    return is_valid_p256_key(raw)


def _keys(value: Dict[str, Any], flag) -> None:
    ids: List[Any] = []
    hub_kids: List[Any] = []
    hub_keys: List[Any] = []
    for machine, m in _indexed(_get(value, "machines")):
        at = "/machines/%d" % m
        if _contains(ids, _get(machine, "id")):
            flag("%s/id" % at, "machine %s is listed twice" % _show(_get(machine, "id")))
        ids.append(_get(machine, "id"))
        device_keys = _list(_get(machine, "deviceKeys"))
        if len([k for k in device_keys if _get(k, "use") == "sig"]) != 1:
            flag("%s/deviceKeys" % at, "a machine has exactly one signing device key, <id>#sig")
        if len([k for k in device_keys if _get(k, "use") == "kem"]) > 1:
            flag("%s/deviceKeys" % at, "a machine has at most one key-agreement device key, <id>#kem")
        seen: List[Any] = []
        for key, k in _indexed(_get(machine, "deviceKeys")):
            if not _same(_get(key, "kid"), "%s#%s" % (_show(_get(machine, "id")), _show(_get(key, "use")))):
                flag("%s/deviceKeys/%d/kid" % (at, k), "a device key is listed as <machine id>#sig or <machine id>#kem, by its role")
            # A key with no canonical fingerprint could be read as two keys by two readers, and no key reference names it (DEC-0084).
            if device_key_fingerprint(key) is None:
                flag("%s/deviceKeys/%d/publicKey" % (at, k), "a device key's octets are written in canonical padded base64, the one form a key reference can name (DEC-0084)")
            elif not _valid_device_key(key):
                flag("%s/deviceKeys/%d/publicKey" % (at, k), "an Ed25519 key is never of small order (DEC-0045) and a P-256 key is a valid point (SEC 1 §3.2.2)")
            if _contains(seen, _get(key, "publicKey")):
                flag("%s/deviceKeys/%d/publicKey" % (at, k), "one key is never used for the other role")
            seen.append(_get(key, "publicKey"))
        hub = _get(machine, "hubKey")
        if isinstance(hub, dict):
            if _contains(hub_kids, _get(hub, "kid")):
                flag("%s/hubKey/kid" % at, "hub key %s is certified for two machines: one kid per machine" % _show(_get(hub, "kid")))
            hub_kids.append(_get(hub, "kid"))
            if _contains(hub_keys, _get(hub, "x")):
                flag("%s/hubKey/x" % at, "one hub public key is certified for two machines under two kids: one key per machine")
            hub_keys.append(_get(hub, "x"))
            x = _get(hub, "x")
            raw = _node_base64("" if x is _MISSING or x is None else _js_string(x))
            if is_small_order_key(raw):
                flag("%s/hubKey/x" % at, "a hub key of small order verifies forged tokens and is never certified (DEC-0045)")
    credentials: List[Any] = []
    for authority, index in _indexed(_get(value, "authorities")):
        if _contains(credentials, _get(authority, "credentialId")):
            flag("/authorities/%d/credentialId" % index, "a passkey is listed once")
        credentials.append(_get(authority, "credentialId"))
        if "problem" in credential_key(_get(authority, "publicKey"), _show(_get(authority, "alg"))):
            flag("/authorities/%d/publicKey" % index, "a passkey's public key is a valid P-256 point for ES256 or an Ed25519 key of full order for EdDSA")


def _placements(value: Dict[str, Any], flag) -> None:
    kids: List[Any] = []
    for key, index in _indexed(_get(value, "publisherKeys")):
        if _contains(kids, _get(key, "kid")):
            flag("/publisherKeys/%d/kid" % index, "publisher key %s is pinned twice" % _show(_get(key, "kid")))
        kids.append(_get(key, "kid"))
    for machine, m in _indexed(_get(value, "machines")):
        agents: List[str] = []
        for placement, p in _indexed(_get(machine, "packages")):
            at = "/machines/%d/packages/%d" % (m, p)
            key = _key_of(_get(placement, "agentRef"), _context_of(placement))
            if key in agents:
                flag("%s/agentRef" % at, "%s is placed twice on one machine in the context %s"
                     % (_show(_get(placement, "agentRef")), _show(_context_of(placement))))
            agents.append(key)
            if not _contains(kids, _get(placement, "publisherKid")):
                flag("%s/publisherKid" % at, "publisher key %s is not in publisherKeys, so the machine pins no key to verify the package under" % _show(_get(placement, "publisherKid")))


def _partner_scopes(value: Dict[str, Any], flag) -> None:
    """FAC-SEM-122 on one record (DEC-0090): a partner's publisher key is scoped once, to a key the record pins, and a
    placement under it is in one of the organization contexts its scope names, never ``personal`` or another."""
    pinned = [_get(k, "kid") for k in _list(_get(value, "publisherKeys"))]
    scoped: List[Any] = []
    for scope, index in _indexed(_get(value, "publisherScopes")):
        if _contains(scoped, _get(scope, "kid")):
            flag("/publisherScopes/%d/kid" % index, "publisher key %s is scoped twice" % _show(_get(scope, "kid")))
        scoped.append(_get(scope, "kid"))
        if not _contains(pinned, _get(scope, "kid")):
            flag("/publisherScopes/%d/kid" % index, "publisher key %s is not in publisherKeys, so the scope limits no key" % _show(_get(scope, "kid")))
    for machine, m in _indexed(_get(value, "machines")):
        for placement, p in _indexed(_get(machine, "packages")):
            if not _scope_admits(value, _get(placement, "publisherKid"), _context_of(placement)):
                flag("/machines/%d/packages/%d/publisherKid" % (m, p),
                     "publisher key %s is a partner's, trusted only in the contexts its scope names, not in %s"
                     % (_show(_get(placement, "publisherKid")), _show(_context_of(placement))))


def _secret_references(value: Dict[str, Any], flag) -> None:
    machine_ids = [_get(m, "id") for m in _list(_get(value, "machines"))]
    for machine, m in _indexed(_get(value, "machines")):
        placed = [_key_of(_get(p, "agentRef"), _context_of(p)) for p in _list(_get(machine, "packages"))]
        slots: List[str] = []
        for secret, s in _indexed(_get(machine, "secrets")):
            at = "/machines/%d/secrets/%d" % (m, s)
            # The message never repeats the value, and no message of this rule repeats a secret placement's context.
            for field in ("slot", "from", "agentRef", "context"):
                text = _get(secret, field)
                if isinstance(text, str) and _secrets.secret_value(text):
                    flag("%s/%s" % (at, field), "a secret placement names a slot, never a value: this looks like a credential")
            if _key_of(_get(secret, "agentRef"), _context_of(secret)) not in placed:
                flag("%s/agentRef" % at, "a secret goes only where a placed package declares it (v4 Path 2): this agent is not placed on this machine in the secret's context")
            if not _contains(machine_ids, _get(secret, "from")):
                flag("%s/from" % at, "the slot is filled from a machine of this estate")
            elif not _same(_context_of(secret), PERSONAL_CONTEXT) and not _same(_get(secret, "from"), _get(machine, "id")):
                # An envelope names no context (DEC-0082): an organization's instance fills its slot on its own machine.
                flag("%s/from" % at, "an organization's instance fills its slot from its own machine's vault, never by an envelope from another machine")
            key = _key_of(_get(secret, "agentRef"), _get(secret, "slot"), _context_of(secret))
            if key in slots:
                flag("%s/slot" % at, "slot %s is placed twice for one agent in one context on one machine" % _show(_get(secret, "slot")))
            slots.append(key)


def _grant_key(ident: Any) -> Any:
    """A grant's id is a URI, so grants and their revocations are keyed by its normal form (DEC-0076)."""
    import fabric_identifiers  # noqa: E402 - beside this file
    return fabric_identifiers.normal_identifier(ident) if isinstance(ident, str) else ident


def _grants_and_revocations(value: Dict[str, Any], flag) -> None:
    grant_ids: List[Any] = []
    for grant, index in _indexed(_get(value, "shareGrants")):
        if _get(grant, "principalKind") != "external":
            flag("/shareGrants/%d/principalKind" % index, "a share grant is to a principal outside the estate: principalKind external")
        ident = _get(_get(grant, "meta"), "id") if isinstance(_get(grant, "meta"), dict) else _MISSING
        if _contains(grant_ids, _grant_key(ident)):
            flag("/shareGrants/%d/meta/id" % index, "grant %s is listed twice" % _show(ident))
        grant_ids.append(_grant_key(ident))
    machines = _list(_get(value, "machines"))
    listed = {
        "authority": [_get(e, "credentialId") for e in _list(_get(value, "authorities"))],
        "machine": [_get(m, "id") for m in machines],
        # A kid, and each listed key's own reference (DEC-0084): revoking either while listing it is refused.
        "device-key": [ref for m in machines for k in _list(_get(m, "deviceKeys"))
                       for ref in ([_get(k, "kid")] if _get(k, "kid") is not _MISSING else []) + ([device_key_ref(k)] if device_key_ref(k) is not None else [])],
        "hub-key": [_get(m["hubKey"], "kid") for m in machines if isinstance(_get(m, "hubKey"), dict)],
        "publisher-key": [_get(k, "kid") for k in _list(_get(value, "publisherKeys"))],
        "package": [_get(p, "digest") for m in machines for p in _list(_get(m, "packages"))],
        "grant": grant_ids,
    }
    seen: List[str] = []
    for revocation, index in _indexed(_get(value, "revocations")):
        ref = _grant_key(_get(revocation, "ref")) if _get(revocation, "kind") == "grant" else _get(revocation, "ref")
        kind = _show(_get(revocation, "kind"))
        key = "%s %s" % (kind, _show(ref))
        if key in seen:
            flag("/revocations/%d" % index, "the %s %s is revoked twice" % (kind, _show(_get(revocation, "ref"))))
        raw_ref = _get(revocation, "ref")
        if _get(revocation, "kind") == "device-key" and isinstance(raw_ref, str) and "@" in raw_ref and not KEY_REFERENCE.match(raw_ref):
            flag("/revocations/%d/ref" % index, "a device-key revocation names a kid or a key reference <kid>@sha256:<64 lower-case hex digits> (DEC-0084)")
        seen.append(key)
        if _contains(listed.get(kind, []), ref):
            flag("/revocations/%d/ref" % index, "the record still lists the %s it revokes: revocation outranks addition" % kind)


def grant_context_findings(grant: Any, at: str) -> List[Dict[str, str]]:
    """FAC-SEM-110 (DEC-0082): a grant to a principal outside the estate (``principalKind: external``, a share grant) is
    used in that principal's organization, so its ``context`` is never ``personal``; absent means not stated."""
    if not isinstance(grant, dict) or _get(grant, "principalKind") != "external" or _get(grant, "context") != PERSONAL_CONTEXT:
        return []
    return [{"code": "FAC-SEM-110", "instancePath": "%s/context" % at,
             "message": "a grant to a principal outside the estate is used in that principal's organization, never in the personal context: "
                        "name the organization's org:<orgId>, or leave context out"}]


def _placement_grant_problems(record: Dict[str, Any], placement: Dict[str, Any]) -> List[Tuple[str, str]]:
    """FAC-SEM-111 (DEC-0082) for one placement: an instance in an organization's context names, in ``grant``, a share
    grant of the same record (matched by the normal form of its id, DEC-0076) whose ``context`` is the placement's, as
    written, and that the record does not revoke; a personal instance names none. Any other context needs a grant, and
    only an ``org:<orgId>`` context can match one, so a malformed context fails closed."""
    import fabric_identifiers  # noqa: E402 - beside this file
    context = _context_of(placement)
    grant = _get(placement, "grant")
    if _same(context, PERSONAL_CONTEXT):
        return [] if grant is _MISSING else [("/grant", "a personal instance runs under no share grant: only a placement in an organization's context names one")]
    if not isinstance(grant, str):
        return [("/grant", "an instance placed in the context %s names the share grant it runs under, by its id" % _show(context))]
    ident = fabric_identifiers.normal_identifier(grant)
    grants = [g for g in _list(_get(record, "shareGrants")) if isinstance(_get(g, "meta"), dict)
              and isinstance(_get(g["meta"], "id"), str) and fabric_identifiers.normal_identifier(g["meta"]["id"]) == ident]
    problems: List[Tuple[str, str]] = []
    if not grants:
        problems.append(("/grant", "the record has no share grant %s" % grant))
    elif (parse_context(context) or {}).get("kind") != "org":
        problems.append(("/context", "%s is not an organization's context id (org:<orgId>), so no share grant matches it" % _show(context)))
    elif not any(_same(_get(g, "context"), context) for g in grants):
        problems.append(("/grant", "the share grant %s is not for the context %s: its context must be the placement's, as written" % (grant, _show(context))))
    if any(_get(e, "kind") == "grant" and isinstance(_get(e, "ref"), str) and fabric_identifiers.normal_identifier(e["ref"]) == ident
           for e in _list(_get(record, "revocations"))):
        problems.append(("/grant", "the record revokes the share grant %s, so no instance runs under it" % grant))
    return problems


def _placement_grants(value: Dict[str, Any], flag) -> None:
    for machine, m in _indexed(_get(value, "machines")):
        for placement, p in _indexed(_get(machine, "packages")):
            for suffix, message in _placement_grant_problems(value, placement):
                flag("/machines/%d/packages/%d%s" % (m, p, suffix), message)


def _dropped_findings(parent: Dict[str, Any], nxt: Dict[str, Any]) -> List[Dict[str, str]]:
    """FAC-SEM-114 across two revisions (DEC-0084): what a revision drops, it revokes in the same revision. A removed
    machine as ``machine <id>`` and its hub key as ``hub-key <kid>``; a replaced or dropped device key of a kept machine
    as ``device-key`` by its reference or its kid; a hub key no longer certified as it was as ``hub-key <old kid>``."""
    findings: List[Dict[str, str]] = []
    flag = _finding(findings, "FAC-SEM-114")
    revocations = _list(_get(nxt, "revocations"))

    def revoked(kind: str, *refs: Any) -> bool:
        return any(_get(entry, "kind") == kind and any(ref is not _MISSING and _same(_get(entry, "ref"), ref) for ref in refs)
                   for entry in revocations)

    kept_machines: List[Tuple[Any, Dict[str, Any]]] = []
    for machine in _list(_get(nxt, "machines")):
        if not any(_same(ident, _get(machine, "id")) for ident, _ in kept_machines):
            kept_machines.append((_get(machine, "id"), machine))
    for machine, m in _indexed(_get(parent, "machines")):
        at = "/parent/machines/%d" % m
        hub = _get(machine, "hubKey") if isinstance(_get(machine, "hubKey"), dict) else None
        kept = next((found for ident, found in kept_machines if _same(ident, _get(machine, "id"))), None)
        if kept is None:
            if not revoked("machine", _get(machine, "id")):
                flag("%s/id" % at, "machine %s is removed without its revocation: a revision that drops a machine lists machine %s in revocations" % (_show(_get(machine, "id")), _show(_get(machine, "id"))))
            if hub is not None and not revoked("hub-key", _get(hub, "kid")):
                flag("%s/hubKey/kid" % at, "the hub key %s of a removed machine is revoked in the same revision" % _show(_get(hub, "kid")))
            continue
        listed = {ref for ref in (device_key_ref(key) for key in _list(_get(kept, "deviceKeys"))) if ref is not None}
        for key, k in _indexed(_get(machine, "deviceKeys")):
            ref = device_key_ref(key)
            if ref is None or ref in listed:
                continue
            if not revoked("device-key", ref, _get(key, "kid")):
                flag("%s/deviceKeys/%d" % (at, k), "the device key %s is replaced or dropped without its revocation: the same revision lists device-key %s" % (_show(_get(key, "kid")), ref))
        next_hub = _get(kept, "hubKey") if isinstance(_get(kept, "hubKey"), dict) else None
        same_hub = next_hub is not None and _same(_get(next_hub, "kid"), _get(hub, "kid") if hub else _MISSING) and _same(_get(next_hub, "x"), _get(hub, "x") if hub else _MISSING)
        if hub is not None and not same_hub and not revoked("hub-key", _get(hub, "kid")):
            flag("%s/hubKey/kid" % at, "the hub key %s is no longer certified as it was: the same revision revokes hub-key %s, and a re-certified hub key takes a new kid" % (_show(_get(hub, "kid")), _show(_get(hub, "kid"))))
    return findings


def _record_findings(value: Dict[str, Any]) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    _revision_whole(value, _finding(findings, "FAC-SEM-072"))
    _keys(value, _finding(findings, "FAC-SEM-073"))
    _placements(value, _finding(findings, "FAC-SEM-074"))
    _partner_scopes(value, _finding(findings, "FAC-SEM-122"))
    _secret_references(value, _finding(findings, "FAC-SEM-075"))
    _grants_and_revocations(value, _finding(findings, "FAC-SEM-076"))
    for grant, index in _indexed(_get(value, "shareGrants")):  # FAC-SEM-110 (DEC-0082)
        findings.extend(grant_context_findings(grant, "/shareGrants/%d" % index))
    _placement_grants(value, _finding(findings, "FAC-SEM-111"))
    for authority, index in _indexed(_get(value, "authorities")):  # FAC-SEM-092 (DEC-0063)
        _signing_credential(authority, "/authorities/%d" % index, _finding(findings, "FAC-SEM-092"))
    return findings


def _package_digest(pkg: Dict[str, Any]) -> str:
    covered = {k: v for k, v in pkg.items() if k not in ("digest", "signatures")}
    return "sha256:" + hashlib.sha256(jcs(covered).encode("utf-8")).hexdigest()


def _installation(value: Dict[str, Any]) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    record = value["record"] if isinstance(_get(value, "record"), dict) else {}
    pkg = value["package"] if isinstance(_get(value, "package"), dict) else {}
    machines = _list(_get(record, "machines"))
    machine_index = next((i for m, i in _indexed(_get(record, "machines")) if _same(_get(m, "id"), _get(value, "machine"))), -1)
    flag074 = _finding(findings, "FAC-SEM-074")
    if machine_index < 0:
        flag074("/machine", "machine %s is not in the estate record" % _show(_get(value, "machine")))
        return findings
    machine = record["machines"][machine_index]
    try:
        digest: Any = _package_digest(pkg)
    except TypeError:
        digest = _MISSING
    if digest is _MISSING or not _same(digest, _get(pkg, "digest")):
        flag074("/package/digest", "the package is not the one its digest names: it changed after it was packed")
    context = _context_of(value)
    placement, placement_index = next(((p, i) for p, i in _indexed(_get(machine, "packages"))
                                       if _same(_get(p, "agentRef"), _get(pkg, "agentRef")) and _same(_context_of(p), context)), (None, -1))
    if placement is None:
        flag074("/package/agentRef", "the record places no %s on machine %s in the context %s"
                % (_show(_get(pkg, "agentRef")), _show(_get(value, "machine")), _show(context)))
    elif not _same(_get(placement, "digest"), digest):
        flag074("/package", "the record places %s of this agent on this machine in this context, not this package" % _show(_get(placement, "digest")))
    declared = [_get(slot, "name") for slot in _list(_get(pkg, "secrets"))]
    flag075 = _finding(findings, "FAC-SEM-075")
    for secret, index in _indexed(_get(machine, "secrets")):
        if _same(_get(secret, "agentRef"), _get(pkg, "agentRef")) and _same(_context_of(secret), context) and not _contains(declared, _get(secret, "slot")):
            flag075("/record/machines/%d/secrets/%d/slot" % (machine_index, index),
                    "the package declares no slot %s: a secret goes only where a placed package declares it" % _show(_get(secret, "slot")))
    if placement is not None and not _scope_admits(record, _get(placement, "publisherKid"), context):
        _finding(findings, "FAC-SEM-122")("/record/machines/%d/packages/%d/publisherKid" % (machine_index, placement_index),
                                          "publisher key %s is a partner's, not trusted in %s" % (_show(_get(placement, "publisherKid")), _show(context)))
    if placement is not None:
        flag111 = _finding(findings, "FAC-SEM-111")
        for suffix, message in _placement_grant_problems(record, placement):
            flag111("/record/machines/%d/packages/%d%s" % (machine_index, placement_index, suffix), message)
    return findings


def estate_record_rules(kind: str, value: Any) -> Optional[List[Dict[str, str]]]:
    """FAC-SEM-072…076: findings for an `estate-record`, an `estate-record-revision` `{parent, next}` or an
    `estate-placement` `{record, machine, package}`; None for another kind."""
    if not isinstance(value, dict):
        value = {}
    if kind == "estate-record":
        return _record_findings(value)
    if kind == "estate-record-revision":
        parent = value["parent"] if isinstance(_get(value, "parent"), dict) else {}
        nxt = value["next"] if isinstance(_get(value, "next"), dict) else {}
        return _revision_chain(value) + _dropped_findings(parent, nxt)
    if kind == "estate-placement":
        return _installation(value)
    return None
