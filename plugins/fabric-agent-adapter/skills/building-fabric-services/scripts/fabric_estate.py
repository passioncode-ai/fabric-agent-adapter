#!/usr/bin/env python3
"""`estate-record/1` (Fabric Agent Contract DEC-0055): verify an estate revision and check its rules.

One revision of one person's estate: the passkeys that sign it, the machines with their device keys and hub-key
certificates, the packages placed per machine, secret placements by reference, share grants and revocations. A
revision names its parent's digest and is signed by a passkey assertion (WebAuthn Level 3, offline) over a challenge
derived from its own digest. This is the contract's `src/estate-record-rules.ts`, `src/webauthn.ts` and `src/p256.ts`
at the pin, ported answer for answer and held to the contract's own vectors (`test/fixtures/contract/estate-vectors.json`):

- ``verify_estate_record(record, at=..., parent=... | authorities=...)``: the verdict a machine applies a revision on,
  after it has checked the revision against `estate-record.schema.json` (the verifier does not check the schema);
- ``estate_record_rules(kind, value)``: FAC-SEM-072…076 for `estate-record`, `estate-record-revision` and
  `estate-placement`, with FAC-SEM-134 on each machine's profile (DEC-0106) and FAC-SEM-147 on the organizations a
  record pins (DEC-0127, DEC-0128);
- ``machine_profile(record, machine_id)``: a machine's profile (DEC-0106): `full`, `member`, `view`, or None;
- ``delta_anchor_of(record)``: the revocation delta's head a revision vouches for (DEC-0107), or None; a revision
  never moves it back (FAC-SEM-137, in the revision rules and the verdict);
- ``hub_key_certified(record, kid, x, at, context=...)``: DL-14: a delegation verifier that reads the estate record
  trusts a token's `kid` only while a current revision certifies it for a machine, and in an organization's context
  only under that context's hub key while the record pins it (DL-14a, DEC-0128; ``fabric_delegation`` calls it).

The record's own rules (FAC-SEM-072…076 and the rest) live in ``fabric_estate_rules`` since 0.52.0 (decision D8); every
name there is re-exported here, so callers keep ``import fabric_estate``.

Standard library only. ES256 is verified here in pure Python (P-256, FIPS 186-5 / SEC 1); EdDSA by the Ed25519 verifier
in ``fabric_delegation``.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fabric_crypto import ed25519_verify, is_small_order_key  # noqa: E402,F401 - beside this file (FAA-65)
from fabric_jsvalue import jcs  # noqa: E402,F401 - beside this file (FAA-65)
from fabric_crypto import (  # noqa: E402,F401 - the core (FAA-65); the private names stay reachable here
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
from fabric_jsvalue import (  # noqa: E402,F401 - the core (FAA-65)
    MISSING as _MISSING,
    get as _get,
    get_string as _s,
    js_to_number as _js_to_number,
    objects as _list,
    safe_integer as _safe_integer,
    same as _same,
    set_has as _set_has,
    show as _show,
)
from fabric_time import (  # noqa: E402,F401 - the core (FAA-65)
    clock_ms as _clock,
    parse_rfc3339_ms as estate_time,
)
# The record's rules (D8): every public name and the private ones callers reached through this module.
from fabric_estate_rules import (  # noqa: E402,F401 - beside this file
    ASSERTION_ALGORITHMS,
    ESTATE_CHALLENGE_TYPE,
    ESTATE_RECORD_SCHEMA,
    KEY_REFERENCE,
    MACHINE_PROFILES,
    MAX_VALIDITY_SECONDS,
    ORG_CONTEXT_PREFIX,
    PERSONAL_CONTEXT,
    _B64URL,
    _anchor_findings,
    _context_of,
    _dropped_findings,
    _lt,
    _record_findings,
    _revocation_key,
    _scope_admits,
    _valid_device_key,
    credential_key,
    delta_anchor_of,
    device_key_fingerprint,
    device_key_ref,
    estate_challenge,
    estate_challenge_input,
    estate_record_digest,
    estate_record_rules,
    grant_context_findings,
    is_signing_rp_id,
    machine_profile,
    origin_within,
    parse_context,
    placement_grant_findings,
)

#: How far ahead of the verifier's clock a signed `issuedAt` may be before it is `not-yet-valid` (DEC-0066): the one
#: skew of the relay family's and the estate record's times (`CLOCK_SKEW_SECONDS` in the contract's `src/rfc3339.ts`).
CLOCK_SKEW_SECONDS = 60
FLAGS = {"UP": 0x01, "UV": 0x04, "BE": 0x08, "BS": 0x10, "AT": 0x40, "ED": 0x80}
_SURROGATE = re.compile("[\ud800-\udfff]")


# --- WebAuthn Level 3 §7.2, offline (src/webauthn.ts) ----------------------------------------------------------------

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
    if _set_has(revoked, _get(authority, "credentialId")):
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
    dropped = _dropped_findings(parent, record) + _anchor_findings(parent, record) if isinstance(parent, dict) else []
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


#: v4 §7, Freshness: an estate revision's window is at most 30 days (DEC-0055 item 2).
_MAX_WINDOW_MS = MAX_VALIDITY_SECONDS * 1000


def _refused(fault: str, detail: str) -> Dict[str, Any]:
    return {"certified": False, "fault": fault, "detail": detail}


def _revision_number(value: Any) -> bool:
    return _safe_integer(value) and value >= 1


#: An organization's context id (DEC-0082), as the contract's hub-key rules read it.
_ORG_CONTEXT = re.compile(r"org:[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


def hub_key_certified(record: Any, kid: Any, x: Any, at: Any, applied: Any = _MISSING,
                      extra_revocations: Any = _MISSING, context: Any = _MISSING) -> Dict[str, Any]:
    """DL-14 (DEC-0055, DEC-0060): whether ``record`` certifies the delegation key ``kid`` with the published key's ``x``
    at ``at`` (an aware datetime or epoch seconds), for a verifier whose machine applied ``applied``
    (``{"revision", "digest"?}``; ``_MISSING``, the default, when none is known; an explicit None is no revision and
    fails closed as ``estate-unreadable``, as Node's null does, decision D3). ``extra_revocations`` are the revocation
    delta's entries applied since the revision (DEC-0054). ``context`` is the context the token is in (DEC-0128): omitted or
    ``personal`` reads each machine's personal ``hubKey``; an organization's ``org:<orgId>`` reads only that context's
    hub keys (``machines[].contextHubKeys``) and only while the record pins the organization, so a context key never
    verifies a personal token and the personal key never an organization's; any other context certifies nothing
    (``kid-not-certified``), so a misconfigured callee fails closed. The contract's ``hubKeyCertified``, in its order;
    never raises. Answers ``{"certified": True, "machine",
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
    in_org = isinstance(context, str) and _ORG_CONTEXT.match(context) is not None
    # A context that is neither personal nor an organization's names no key: a misconfigured callee fails closed.
    if context is not _MISSING and context != "personal" and not in_org:
        return _refused("token", "kid-not-certified")
    # DEC-0128: an organization's token verifies only under that context's key, and only while the record pins it.
    if in_org:
        pins = _get(record, "organizations")
        if not any(isinstance(pin, dict) and _same(_get(pin, "org"), context) for pin in (pins if isinstance(pins, list) else [])):
            return _refused("token", "kid-not-certified")

    def key_of(machine: Dict[str, Any]) -> Any:
        if not in_org:
            hub = _get(machine, "hubKey")
            return hub if isinstance(hub, dict) else None
        entries = _get(machine, "contextHubKeys")
        entry = next((e for e in (entries if isinstance(entries, list) else [])
                      if isinstance(e, dict) and _same(_get(e, "context"), context) and isinstance(_get(e, "key"), dict)
                      and _same(_get(e["key"], "kid"), kid)), None)
        return entry["key"] if entry is not None else None

    holders = [m for m in record["machines"] if isinstance(m, dict) and key_of(m) is not None and _same(_get(key_of(m), "kid"), kid)]
    if len(holders) != 1:  # two machines under one kid break FAC-SEM-073; such a revision certifies neither
        return _refused("token", "kid-not-certified")
    machine = holders[0]
    if not isinstance(x, str) or not _same(_get(key_of(machine), "x"), x):  # a missing x never equals a missing x
        return _refused("token", "kid-not-certified")
    if revokes("machine", _get(machine, "id")):
        return _refused("token", "kid-not-certified")
    return {"certified": True, "machine": _s(machine, "id"), "revision": record["revision"]}
