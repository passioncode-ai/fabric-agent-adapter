#!/usr/bin/env python3
"""The estate ceremonies' headless join (contract DEC-0084), the Python kit; the Node twin is fabric-ceremonies.mjs.
Standard library only.

An ``enroll-token/1`` lets a machine with no screen join an estate: Fabric issues it under the person's signing passkey
for at most 15 minutes and one use, the machine reads it from stdin or a 0600 file (never argv, a URL or a log) and
presents it with its ``#sig`` key, and the hub binds its nonce to that key on the first use. The token gives the machine
no trust; only a passkey-signed revision that lists it does. Its ``genesis`` authenticates the estate to the machine.

- ``verify_enroll_token(token, record=, genesis=, at=)``: the reference verifier, the hub's and the node's.
- ``enroll_join_input(token)``: the ``enroll-join/1`` statement the joining machine signs with its ``#sig`` key.
- ``enroll_token_rules("enroll-token", token)``: FAC-SEM-113.

Every function answers and never raises on malformed input. Normative source: the contract's src/enroll-token.ts,
src/signing-challenges.ts and docs/specification/ceremonies.md.
"""
# #region ceremonies-kit, docs: plugins/fabric-agent-adapter/skills/building-fabric-services/references/estate-record.md#the-estate-ceremonies

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_delegation as _delegation  # noqa: E402 - beside this file: RFC 8785
import fabric_estate as _estate  # noqa: E402 - beside this file: passkey assertions, times, show

ENROLL_TOKEN_SCHEMA = "enroll-token/1"
ENROLL_TOKEN_TYPE = "enroll-token/1"
ENROLL_JOIN_TYPE = "enroll-join/1"
ENROLL_PURPOSE = "agent-host"
MAX_ENROLL_TOKEN_SECONDS = 900
#: The register's fields of enroll-token/1 beside ``type`` (DEC-0084), one list for good.
ENROLL_TOKEN_FIELDS = ("scope", "genesis", "purpose", "ceiling", "notBefore", "expiresAt", "nonce", "uses")
_SHA256 = re.compile(r"sha256:[a-f0-9]{64}\Z")
_ESTATE_SCOPE = re.compile(r"estate:[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}\Z")
#: 32 random bytes as unpadded base64url.
_NONCE32 = re.compile(r"[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]\Z")
_ASSERTION_MEMBERS = "alg,authenticatorData,clientDataJSON,credentialId,format,sig"


def _matches(pattern: Any, value: Any) -> bool:
    return isinstance(value, str) and pattern.match(value) is not None


def _is_one(value: Any) -> bool:
    """JavaScript's ``value === 1`` on parsed JSON: true is not 1."""
    return not isinstance(value, bool) and isinstance(value, (int, float)) and value == 1


def _finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


def _register_ok(kind: str, fields: Dict[str, Any]) -> bool:
    if kind == ENROLL_TOKEN_TYPE:
        return (_matches(_ESTATE_SCOPE, fields["scope"]) and _matches(_SHA256, fields["genesis"]) and fields["purpose"] == ENROLL_PURPOSE
                and (fields["ceiling"] is None or _matches(_SHA256, fields["ceiling"])) and _finite(_estate.estate_time(fields["notBefore"]))
                and _finite(_estate.estate_time(fields["expiresAt"])) and _matches(_NONCE32, fields["nonce"]) and _is_one(fields["uses"]))
    return _matches(_SHA256, fields["digest"]) and _matches(_NONCE32, fields["nonce"])


def signing_statement(kind: str, fields: Any) -> Optional[bytes]:
    """The bytes of a registered statement (DEC-0063): the UTF-8 RFC 8785 form of ``{type, ...fields}``, for the two types
    this kit uses (``enroll-token/1``, ``enroll-join/1``); None when the fields are not exactly the type's or a value is
    outside what the register admits."""
    names = {ENROLL_TOKEN_TYPE: ENROLL_TOKEN_FIELDS, ENROLL_JOIN_TYPE: ("digest", "nonce")}.get(kind)
    if names is None or not isinstance(fields, dict) or len(fields) != len(names) or any(name not in fields for name in names):
        return None
    if not _register_ok(kind, fields):
        return None
    try:
        return _delegation.jcs(dict(fields, type=kind)).encode("utf-8")
    except (TypeError, ValueError):
        return None


def _statement_fields(token: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(token, dict) or token.get("schema") != ENROLL_TOKEN_SCHEMA or not isinstance(token.get("statement"), dict):
        return None
    if token["statement"].get("type") != ENROLL_TOKEN_TYPE:
        return None
    # The token holds exactly the schema's members: nothing unsigned rides beside the statement (DEC-0084).
    if sorted(token) != ["schema", "signature", "statement"]:
        return None
    fields = {name: value for name, value in token["statement"].items() if name != "type"}
    return fields if signing_statement(ENROLL_TOKEN_TYPE, fields) is not None else None


def verify_enroll_token(token: Any, *, record: Any, genesis: Any, at: Any) -> Dict[str, Any]:
    """The reference verifier of an enroll-token/1, for the hub that admits a join and the node that pins the estate.
    ``record`` is the current estate revision the verifier applied, ``genesis`` the digest of its revision 1, ``at`` the
    clock (an aware datetime or epoch seconds). The first failure answers: no-clock, malformed, wrong-estate, the passkey
    (no-trusted-authority, revoked-authority, duplicate-authority, unknown-authority), the assertion, then the window
    (too-long-lived, not-yet-valid, expired). Success: ``{"ok": True, "nonce", "expiresAt", "signedBy"}``."""
    now = _estate._clock(at)
    if not _finite(now):
        return {"ok": False, "problem": "no-clock"}
    fields = _statement_fields(token)
    if fields is None or not isinstance(record, dict) or not isinstance(record.get("estate"), str):
        return {"ok": False, "problem": "malformed"}
    signature = token.get("signature")
    if (not isinstance(signature, dict) or ",".join(sorted(signature)) != _ASSERTION_MEMBERS
            or signature.get("format") != "webauthn-assertion" or not isinstance(signature.get("credentialId"), str)):
        return {"ok": False, "problem": "malformed"}
    if fields["scope"] != "estate:%s" % record["estate"] or not isinstance(genesis, str) or fields["genesis"] != genesis:
        return {"ok": False, "problem": "wrong-estate"}
    authorities = _estate._list(record.get("authorities"))
    if not authorities:
        return {"ok": False, "problem": "no-trusted-authority"}
    credential_id = signature["credentialId"]
    if any(entry.get("kind") == "authority" and _estate._same(entry.get("ref", _estate._MISSING), credential_id) for entry in _estate._list(record.get("revocations"))):
        return {"ok": False, "problem": "revoked-authority"}
    matches = [entry for entry in authorities if _estate._same(entry.get("credentialId", _estate._MISSING), credential_id)]
    if len(matches) > 1:
        return {"ok": False, "problem": "duplicate-authority"}
    if not matches:
        return {"ok": False, "problem": "unknown-authority"}
    authority = matches[0]
    origins = authority.get("origins")
    rp_id = _estate._show(authority.get("rpId", _estate._MISSING))
    if not _estate.is_signing_rp_id(rp_id):
        return {"ok": False, "problem": "wrong-rp"}
    credential = {"credentialId": credential_id, "alg": _estate._show(authority.get("alg", _estate._MISSING)),
                  "publicKey": authority["publicKey"] if isinstance(authority.get("publicKey"), dict) else {}, "rpId": rp_id,
                  "origins": [o for o in origins if isinstance(o, str) and _estate.origin_within(o, rp_id)] if isinstance(origins, list) else []}
    challenge = hashlib.sha256(signing_statement(ENROLL_TOKEN_TYPE, fields)).digest()
    assertion = _estate.verify_assertion(signature, credential, challenge)
    if not assertion["ok"]:
        return {"ok": False, "problem": assertion["problem"]}
    not_before = _estate.estate_time(fields["notBefore"])
    expires_at = _estate.estate_time(fields["expiresAt"])
    if expires_at <= not_before or expires_at - not_before > MAX_ENROLL_TOKEN_SECONDS * 1000:
        return {"ok": False, "problem": "too-long-lived"}
    if now < not_before - _estate.CLOCK_SKEW_SECONDS * 1000:
        return {"ok": False, "problem": "not-yet-valid"}
    if now > expires_at:
        return {"ok": False, "problem": "expired"}
    return {"ok": True, "nonce": fields["nonce"], "expiresAt": fields["expiresAt"], "signedBy": credential_id}


def enroll_join_input(token: Any) -> Optional[str]:
    """What the joining machine signs with the #sig key it presents (DEC-0084): the enroll-join/1 statement
    ``{type, digest, nonce}``, ``digest`` the SHA-256 of the token's statement bytes; None without a register statement."""
    fields = _statement_fields(token)
    statement = signing_statement(ENROLL_TOKEN_TYPE, fields) if fields is not None else None
    if statement is None:
        return None
    joined = signing_statement(ENROLL_JOIN_TYPE, {"digest": "sha256:" + hashlib.sha256(statement).hexdigest(), "nonce": fields["nonce"]})
    return joined.decode("utf-8") if joined is not None else None


def _token_findings(value: Dict[str, Any]) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []

    def flag(at: str, message: str) -> None:
        findings.append({"code": "FAC-SEM-113", "instancePath": at, "message": message})

    statement = value.get("statement") if isinstance(value.get("statement"), dict) else None
    if statement is None:
        flag("/statement", "an enroll token carries its signed statement")
        return findings
    if statement.get("type") != ENROLL_TOKEN_TYPE:
        flag("/statement/type", "the statement's type is enroll-token/1, the register's (DEC-0063)")
    extra = [name for name in statement if name != "type" and name not in ENROLL_TOKEN_FIELDS]
    missing = [name for name in ENROLL_TOKEN_FIELDS if name not in statement]
    if extra or missing:
        flag("/statement", "the statement has exactly the register's fields: %s" % ", ".join(ENROLL_TOKEN_FIELDS))
    if statement.get("purpose") != ENROLL_PURPOSE:
        flag("/statement/purpose", "an enroll token's purpose is agent-host")
    if not _is_one(statement.get("uses")):
        flag("/statement/uses", "an enroll token is used once: uses is 1, and the hub binds its nonce on the first use")
    not_before = _estate.estate_time(statement.get("notBefore"))
    expires_at = _estate.estate_time(statement.get("expiresAt"))
    rest = {name: v for name, v in statement.items() if name != "type"}
    named = not extra and not missing and statement.get("purpose") == ENROLL_PURPOSE and _is_one(statement.get("uses")) and _finite(not_before) and _finite(expires_at)
    if named and signing_statement(ENROLL_TOKEN_TYPE, rest) is None:
        flag("/statement", "scope is estate:<id>, genesis a sha256: digest, nonce 32 bytes in base64url, and ceiling null or a digest")
    if not _finite(not_before) or not _finite(expires_at):
        flag("/statement/expiresAt" if _finite(not_before) else "/statement/notBefore", "notBefore and expiresAt are RFC 3339 date-times with an offset, on days that exist")
    elif expires_at <= not_before or expires_at - not_before > MAX_ENROLL_TOKEN_SECONDS * 1000:
        flag("/statement/expiresAt", "an enroll token is valid after notBefore and for at most 15 minutes (900 s)")
    return findings


def enroll_token_rules(kind: str, value: Any) -> Optional[List[Dict[str, str]]]:
    """FAC-SEM-113 (kind ``enroll-token``); None for another kind."""
    if kind == "enroll-token":
        return _token_findings(value if isinstance(value, dict) else {})
    return None
# #endregion ceremonies-kit
