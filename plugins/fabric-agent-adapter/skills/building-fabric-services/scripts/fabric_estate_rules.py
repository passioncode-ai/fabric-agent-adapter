#!/usr/bin/env python3
"""`estate-record/1` (Fabric Agent Contract DEC-0055): the record's own rules, without a verifier.

The contract's `src/estate-record-rules.ts` at the pin, ported answer for answer and held to the contract's own vectors
(`test/fixtures/contract/estate-vectors.json`). Split from ``fabric_estate`` (0.52.0, decision D8) so each module stays
under the kit's line ceiling; ``fabric_estate`` re-exports every name here, so ``import fabric_estate`` keeps working.

- ``estate_record_rules(kind, value)``: FAC-SEM-072…076 for `estate-record`, `estate-record-revision` and
  `estate-placement`, with FAC-SEM-092, 110, 111, 114, 122, 134, 137 and FAC-SEM-147 (DEC-0127, DEC-0128: the
  organizations a record pins, their context issuers and the context hub keys of its machines);
- ``estate_record_digest``, ``estate_challenge_input``, ``estate_challenge``: what a passkey signs;
- ``parse_context``: the personal context or an organization's `org:<orgId>` (DEC-0082);
- ``credential_key``: whether a passkey's public key is usable (FAC-SEM-073 reads it; the assertion verifier uses it);
- ``machine_profile``, ``delta_anchor_of``, ``device_key_ref``, ``grant_context_findings``,
  ``placement_grant_findings``.

Standard library only.
"""
from __future__ import annotations

import base64
import hashlib
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fabric_crypto import is_small_order_key  # noqa: E402 - beside this file (FAA-65)
from fabric_jsvalue import jcs  # noqa: E402 - beside this file (FAA-65)
import fabric_secrets as _secrets  # noqa: E402 - beside this file: the contract's credential detector
from fabric_crypto import (  # noqa: E402 - the core (FAA-65)
    b64url as _b64url,
    b64url_bytes as _b64url_bytes,
    is_valid_p256_key,
    node_base64 as _node_base64,
    sha256 as _sha256,
)
from fabric_jsvalue import (  # noqa: E402 - the core (FAA-65)
    MISSING as _MISSING,
    get as _get,
    indexed_objects as _indexed,
    js_string as _js_string,
    js_to_number as _js_to_number,
    key_of as _key_of,
    objects as _list,
    safe_integer as _safe_integer,
    same as _same,
    set_has as _set_has,  # every membership the contract keeps in a Set or tests with includes (FAA-113)
    show as _show,
)
from fabric_time import parse_rfc3339_ms as estate_time  # noqa: E402 - the core (FAA-65)

ESTATE_RECORD_SCHEMA = "estate-record/1"
ESTATE_CHALLENGE_TYPE = "estate-revision/1"
MAX_VALIDITY_SECONDS = 30 * 24 * 60 * 60
ASSERTION_ALGORITHMS = ("ES256", "EdDSA")
_B64URL = re.compile(r"[A-Za-z0-9_-]+")
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



# --- a passkey's public key (src/webauthn.ts) ---------------------------------------------------------------------

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


def _scope_admits(record: Any, kid: Any, context: Any) -> bool:
    """DEC-0090: a key no `publisherScopes[]` entry names is trusted in any context; a partner's key, only in a context
    one of its scopes lists."""
    scopes = [s for s in _list(_get(record, "publisherScopes")) if _same(_get(s, "kid"), kid)]
    return not scopes or any(isinstance(_get(s, "contexts"), list) and _set_has(s["contexts"], context) for s in scopes)


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
    """FAC-SEM-073: every key is usable (DEC-0053) and named once. A context hub key (DEC-0128) is unique among every hub
    key of the record, of full order, once per context on its machine, in a pinned context, and held only by a machine
    that holds the personal hub key."""
    pinned = [_get(pin, "org") for pin in _list(_get(value, "organizations"))]
    ids: List[Any] = []
    hub_kids: List[Any] = []
    hub_keys: List[Any] = []
    for machine, m in _indexed(_get(value, "machines")):
        at = "/machines/%d" % m
        if _set_has(ids, _get(machine, "id")):
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
            if _set_has(seen, _get(key, "publicKey")):
                flag("%s/deviceKeys/%d/publicKey" % (at, k), "one key is never used for the other role")
            seen.append(_get(key, "publicKey"))
        hub = _get(machine, "hubKey")
        if isinstance(hub, dict):
            if _set_has(hub_kids, _get(hub, "kid")):
                flag("%s/hubKey/kid" % at, "hub key %s is certified for two machines: one kid per machine" % _show(_get(hub, "kid")))
            hub_kids.append(_get(hub, "kid"))
            if _set_has(hub_keys, _get(hub, "x")):
                flag("%s/hubKey/x" % at, "one hub public key is certified for two machines under two kids: one key per machine")
            hub_keys.append(_get(hub, "x"))
            x = _get(hub, "x")
            raw = _node_base64("" if x is _MISSING or x is None else _js_string(x))
            if is_small_order_key(raw):
                flag("%s/hubKey/x" % at, "a hub key of small order verifies forged tokens and is never certified (DEC-0045)")
        # DEC-0128: a context's hub key is as unique as the personal one, across every hub key of the record, and belongs
        # to a pinned organization, so a token in that context verifies only under its own context's key.
        contexts: List[Any] = []
        # A context's key lives with the personal hub key, so a hub move carries every context's key with it (DL-15).
        if _list(_get(machine, "contextHubKeys")) and not isinstance(_get(machine, "hubKey"), dict):
            flag("%s/contextHubKeys" % at, "a context's hub key is held only by the machine that holds the personal hub key (DEC-0128)")
        for entry, c in _indexed(_get(machine, "contextHubKeys")):
            key_at = "%s/contextHubKeys/%d" % (at, c)
            context = _get(entry, "context")
            if _set_has(contexts, context):
                flag("%s/context" % key_at, "context %s has two hub keys on one machine" % _show(context))
            contexts.append(context)
            if not _set_has(pinned, context):
                flag("%s/context" % key_at, "context %s is not an organization the record pins (DEC-0127)" % _show(context))
            key = _get(entry, "key")
            if not isinstance(key, dict):  # a key that is not an object is the schema's to refuse; nothing here reads it
                continue
            if _set_has(hub_kids, _get(key, "kid")):
                flag("%s/key/kid" % key_at, "hub key %s is certified twice: one kid per hub key, personal or per context" % _show(_get(key, "kid")))
            hub_kids.append(_get(key, "kid"))
            if _set_has(hub_keys, _get(key, "x")):
                flag("%s/key/x" % key_at, "one public key is certified as two hub keys: a context key is its own key")
            hub_keys.append(_get(key, "x"))
            x = _get(key, "x")
            if is_small_order_key(_node_base64("" if x is _MISSING or x is None else _show(x))):
                flag("%s/key/x" % key_at, "a hub key of small order verifies forged tokens and is never certified (DEC-0045)")
    credentials: List[Any] = []
    for authority, index in _indexed(_get(value, "authorities")):
        if _set_has(credentials, _get(authority, "credentialId")):
            flag("/authorities/%d/credentialId" % index, "a passkey is listed once")
        credentials.append(_get(authority, "credentialId"))
        if "problem" in credential_key(_get(authority, "publicKey"), _show(_get(authority, "alg"))):
            flag("/authorities/%d/publicKey" % index, "a passkey's public key is a valid P-256 point for ES256 or an Ed25519 key of full order for EdDSA")


def _placements(value: Dict[str, Any], flag) -> None:
    kids: List[Any] = []
    for key, index in _indexed(_get(value, "publisherKeys")):
        if _set_has(kids, _get(key, "kid")):
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
            if not _set_has(kids, _get(placement, "publisherKid")):
                flag("%s/publisherKid" % at, "publisher key %s is not in publisherKeys, so the machine pins no key to verify the package under" % _show(_get(placement, "publisherKid")))


def _partner_scopes(value: Dict[str, Any], flag) -> None:
    """FAC-SEM-122 on one record (DEC-0090): a partner's publisher key is scoped once, to a key the record pins, and a
    placement under it is in one of the organization contexts its scope names, never ``personal`` or another."""
    pinned = [_get(k, "kid") for k in _list(_get(value, "publisherKeys"))]
    scoped: List[Any] = []
    for scope, index in _indexed(_get(value, "publisherScopes")):
        if _set_has(scoped, _get(scope, "kid")):
            flag("/publisherScopes/%d/kid" % index, "publisher key %s is scoped twice" % _show(_get(scope, "kid")))
        scoped.append(_get(scope, "kid"))
        if not _set_has(pinned, _get(scope, "kid")):
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
            if not _set_has(machine_ids, _get(secret, "from")):
                flag("%s/from" % at, "the slot is filled from a machine of this estate")
            elif not _same(_context_of(secret), PERSONAL_CONTEXT) and not _same(_get(secret, "from"), _get(machine, "id")):
                # An envelope names no context (DEC-0082): an organization's instance fills its slot on its own machine.
                flag("%s/from" % at, "an organization's instance fills its slot from its own machine's vault, never by a secret envelope from another machine")
            key = _key_of(_get(secret, "agentRef"), _get(secret, "slot"), _context_of(secret))
            if key in slots:
                flag("%s/slot" % at, "slot %s is placed twice for one agent in one context on one machine" % _show(_get(secret, "slot")))
            slots.append(key)


#: DEC-0106: what a machine of the estate may be. Absent is `full`, and a writer omits `full`.
MACHINE_PROFILES = ("full", "member", "view")


def _is_profile(value: Any) -> bool:
    return isinstance(value, str) and value in MACHINE_PROFILES


def machine_profile(record: Any, machine_id: Any) -> Optional[str]:
    """A machine's profile in a record (DEC-0106): ``full`` when the machine is listed once with no ``profile``, its value
    when that is one of the three, None otherwise (not listed, listed twice, an unreadable record or id, an unknown
    value). The contract's ``machineProfile``; never raises."""
    if not isinstance(record, dict) or not isinstance(machine_id, str):
        return None
    found = [m for m in _list(_get(record, "machines")) if _same(_get(m, "id"), machine_id)]
    if len(found) != 1:
        return None
    profile = _get(found[0], "profile")
    if profile is _MISSING:
        return "full"
    return profile if _is_profile(profile) else None


def _machine_profiles(value: Dict[str, Any], flag) -> None:
    """FAC-SEM-134 (DEC-0106): a profile, when present, is `full`, `member` or `view`; only a `full` machine carries a
    `hubKey` or a context's hub key (DEC-0128); a `view` machine has no placement and no secret placement, and no secret placement names it as `from`."""
    views: List[Any] = []
    for machine, m in _indexed(_get(value, "machines")):
        profile = _get(machine, "profile")
        if profile is _MISSING:
            continue
        if not _is_profile(profile):
            flag("/machines/%d/profile" % m, "profile %s is none of full, member, view" % _show(profile))
            continue
        if profile != "full" and _get(machine, "hubKey") is not _MISSING:
            flag("/machines/%d/hubKey" % m, "a %s machine is never the hub's: only a full machine carries a hub key" % profile)
        if profile != "full" and _list(_get(machine, "contextHubKeys")):
            flag("/machines/%d/contextHubKeys" % m, "a %s machine is never the hub's: only a full machine carries a context's hub key (DEC-0128)" % profile)
        if profile == "view":
            views.append(_get(machine, "id"))
            if _list(_get(machine, "packages")):
                flag("/machines/%d/packages" % m, "a view machine runs no agent: it has no placement")
            if _list(_get(machine, "secrets")):
                flag("/machines/%d/secrets" % m, "a view machine holds none of the estate's secrets")
    for machine, m in _indexed(_get(value, "machines")):
        for secret, s in _indexed(_get(machine, "secrets")):
            if _set_has(views, _get(secret, "from")):
                flag("/machines/%d/secrets/%d/from" % (m, s), "machine %s is a view machine: it is the source of no secret" % _show(_get(secret, "from")))


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
        if _set_has(grant_ids, _grant_key(ident)):
            flag("/shareGrants/%d/meta/id" % index, "grant %s is listed twice" % _show(ident))
        grant_ids.append(_grant_key(ident))
    machines = _list(_get(value, "machines"))
    listed = {
        "authority": [_get(e, "credentialId") for e in _list(_get(value, "authorities"))],
        "machine": [_get(m, "id") for m in machines],
        # A kid, and each listed key's own reference (DEC-0084): revoking either while listing it is refused.
        "device-key": [ref for m in machines for k in _list(_get(m, "deviceKeys"))
                       for ref in ([_get(k, "kid")] if _get(k, "kid") is not _MISSING else []) + ([device_key_ref(k)] if device_key_ref(k) is not None else [])],
        # A context's hub key (DEC-0128) is listed as the personal one is; an entry whose key is no object lists undefined.
        "hub-key": [_get(m["hubKey"], "kid") for m in machines if isinstance(_get(m, "hubKey"), dict)]
                   + [_get(_get(e, "key"), "kid") if isinstance(_get(e, "key"), dict) else _MISSING
                      for m in machines for e in _list(_get(m, "contextHubKeys"))],
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
        if _set_has(listed.get(kind, []), ref):
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


def placement_grant_findings(record: Any, placement: Any) -> List[Dict[str, str]]:
    """FAC-SEM-111 for one placement of ``record``, as findings (``instancePath`` relative to the placement). Answers,
    never raises: a record or placement that is no object reads as an empty one (FAA-125)."""
    record, placement = (v if isinstance(v, dict) else {} for v in (record, placement))
    return [{"code": "FAC-SEM-111", "instancePath": at, "message": m} for at, m in _placement_grant_problems(record, placement)]


def _placement_grants(value: Dict[str, Any], flag) -> None:
    for machine, m in _indexed(_get(value, "machines")):
        for placement, p in _indexed(_get(machine, "packages")):
            for suffix, message in _placement_grant_problems(value, placement):
                flag("/machines/%d/packages/%d%s" % (m, p, suffix), message)


_ANCHOR_HASH = re.compile(r"[a-f0-9]{64}")


def delta_anchor_of(record: Any) -> Optional[Dict[str, Any]]:
    """The anchor a record vouches for (DEC-0107), or None when it names none or its shape is not the schema's. The
    contract's ``deltaAnchorOf``."""
    if not isinstance(record, dict) or not isinstance(_get(record, "deltaAnchor"), dict):
        return None
    sequence, sha = _get(record["deltaAnchor"], "sequence"), _get(record["deltaAnchor"], "sha256")
    if _safe_integer(sequence) and sequence >= 1 and isinstance(sha, str) and _ANCHOR_HASH.fullmatch(sha):
        return {"sequence": sequence, "sha256": sha}
    return None


def _anchor_findings(parent: Dict[str, Any], nxt: Dict[str, Any]) -> List[Dict[str, str]]:
    """FAC-SEM-137 across two revisions (DEC-0107): the delta anchor never moves back. A revision whose parent anchors
    the delta anchors it too, at the parent's sequence or later, with the parent's hash at the same sequence."""
    findings: List[Dict[str, str]] = []
    flag = _finding(findings, "FAC-SEM-137")
    before = delta_anchor_of(parent)
    if before is None:
        return findings
    after = delta_anchor_of(nxt)
    if after is None:
        flag("/next/deltaAnchor", "the parent anchors the delta at %s: a revision keeps an anchor once one is set" % _js_string(before["sequence"]))
    elif after["sequence"] < before["sequence"]:
        flag("/next/deltaAnchor/sequence", "the anchor moves back from %s to %s" % (_js_string(before["sequence"]), _js_string(after["sequence"])))
    elif after["sequence"] == before["sequence"] and after["sha256"] != before["sha256"]:
        flag("/next/deltaAnchor/sha256", "another hash at sequence %s: two delta histories" % _js_string(after["sequence"]))
    return findings


def _context_keys(machine: Any) -> List[Tuple[Dict[str, Any], int, Any]]:
    """A machine's context hub keys that are objects, with their indexes, each with the context it is certified for."""
    return [(entry["key"], c, _get(entry, "context")) for entry, c in _indexed(_get(machine, "contextHubKeys"))
            if isinstance(_get(entry, "key"), dict)]


def _dropped_findings(parent: Dict[str, Any], nxt: Dict[str, Any]) -> List[Dict[str, str]]:
    """FAC-SEM-114 across two revisions (DEC-0084): what a revision drops, it revokes in the same revision. A removed
    machine as ``machine <id>`` and its hub key as ``hub-key <kid>``; a replaced or dropped device key of a kept machine
    as ``device-key`` by its reference or its kid; a hub key no longer certified as it was as ``hub-key <old kid>``; a
    context's hub key dropped, replaced or moved to another context the same way (DEC-0128)."""
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
            for key, c, _context in _context_keys(machine):
                if not revoked("hub-key", _get(key, "kid")):
                    flag("%s/contextHubKeys/%d/key/kid" % (at, c), "the context hub key %s of a removed machine is revoked in the same revision (DEC-0128)" % _show(_get(key, "kid")))
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
        # DEC-0128: a context's hub key dropped (its context unpinned, OM-5, or the key replaced) is revoked the same way.
        # A key is kept only in its own context: one moved to another organization is a key that organization must not inherit.
        kept_context = {"%s %s %s" % (_show(context), _show(_get(key, "kid")), _show(_get(key, "x"))) for key, _c, context in _context_keys(kept)}
        for key, c, context in _context_keys(machine):
            if ("%s %s %s" % (_show(context), _show(_get(key, "kid")), _show(_get(key, "x"))) not in kept_context
                    and not revoked("hub-key", _get(key, "kid"))):
                flag("%s/contextHubKeys/%d/key/kid" % (at, c), "the context hub key %s is no longer certified as it was: the same revision revokes hub-key %s (DEC-0128)"
                     % (_show(_get(key, "kid")), _show(_get(key, "kid"))))
    return findings


_CONTEXT_ISSUER_PREFIX = re.compile(r"\Aurn:fabric:context:")
#: A base64url Ed25519 key of 32 bytes: 42 characters and a last one that leaves no bits over.
_ED25519_X = re.compile(r"[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]\Z")


def _js_length(text: str) -> int:
    """A string's ``length`` in JavaScript: its UTF-16 code units."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _organization_pins(value: Dict[str, Any], flag) -> None:
    """FAC-SEM-147: the organizations the person admitted (DEC-0127 OM-2), each once by its context, and no root of small
    order (DEC-0045), since the root's key sets are what every attestation of that organization verifies under; each
    context issuer once and never containing the estate id (DEC-0128). Lower case is Python's ``str.lower``, which
    agrees with JavaScript's ``toLowerCase`` on every identifier the schema admits."""
    seen: List[str] = []
    issuers: List[Any] = []
    estate = _get(value, "estate")
    for pin, index in _indexed(_get(value, "organizations")):
        at = "/organizations/%d" % index
        org = _show(_get(pin, "org"))
        if org in seen:
            flag("%s/org" % at, "organization %s is pinned twice" % org)
        seen.append(org)
        iss = _get(pin, "iss")
        # DEC-0128: a context's issuer is its own and names no estate, so two organizations' tokens share nothing.
        if isinstance(iss, str):
            if _set_has(issuers, iss):
                flag("%s/iss" % at, "context issuer %s is used by two organizations" % _show(iss))
            issuers.append(iss)
        # Only the opaque part is the pin's own: the fixed prefix would match a short estate id by chance.
        opaque = _CONTEXT_ISSUER_PREFIX.sub("", iss, count=1).lower() if isinstance(iss, str) else ""
        # An estate id shorter than eight characters appears inside any random id by chance; the issuer's duty covers it.
        if isinstance(estate, str) and _js_length(estate) >= 8 and estate.lower() in opaque:
            flag("%s/iss" % at, "a context issuer never contains the estate id (DEC-0128)")
        root = _get(pin, "root")
        x = _get(root, "x") if isinstance(root, dict) else _MISSING
        if isinstance(x, str) and _ED25519_X.match(x) and is_small_order_key(_node_base64(x)):
            flag("%s/root/x" % at, "a root of small order lets anyone forge the organization's key sets (DEC-0045)")


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
    _machine_profiles(value, _finding(findings, "FAC-SEM-134"))
    _organization_pins(value, _finding(findings, "FAC-SEM-147"))
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
        if _same(_get(secret, "agentRef"), _get(pkg, "agentRef")) and _same(_context_of(secret), context) and not _set_has(declared, _get(secret, "slot")):
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
        return _revision_chain(value) + _dropped_findings(parent, nxt) + _anchor_findings(parent, nxt)
    if kind == "estate-placement":
        return _installation(value)
    return None
