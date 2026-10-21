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
- ``redeem_enroll_token(token, machine_key, proof, ledger)``: the hub's single use of a verified token.
- The nearby pairing: ``pairing_commit``, ``check_reveal``, ``comparison_code``, ``checked_comparison_code``,
  ``estate_fingerprint``, ``rendezvous_verdict``, ``join_listed``, ``own_keys_decision`` (``machine_of_keys``).

Every function answers and never raises on malformed input. Normative source: the contract's src/enroll-token.ts,
src/signing-challenges.ts and docs/specification/ceremonies.md.
"""
# #region ceremonies-kit, docs: plugins/fabric-agent-adapter/skills/building-fabric-services/references/estate-record.md#the-estate-ceremonies

from __future__ import annotations

import base64
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
                and (fields["ceiling"] is None or _matches(_SHA256, fields["ceiling"])) and _finite(_ftime.parse_rfc3339_ms(fields["notBefore"]))
                and _finite(_ftime.parse_rfc3339_ms(fields["expiresAt"])) and _matches(_NONCE32, fields["nonce"]) and _is_one(fields["uses"]))
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
        return _jsv.jcs(dict(fields, type=kind)).encode("utf-8")
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
    now = _ftime.clock_ms(at)
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
    authorities = _jsv.objects(record.get("authorities"))
    if not authorities:
        return {"ok": False, "problem": "no-trusted-authority"}
    credential_id = signature["credentialId"]
    if any(entry.get("kind") == "authority" and _jsv.same(entry.get("ref", _jsv.MISSING), credential_id) for entry in _jsv.objects(record.get("revocations"))):
        return {"ok": False, "problem": "revoked-authority"}
    matches = [entry for entry in authorities if _jsv.same(entry.get("credentialId", _jsv.MISSING), credential_id)]
    if len(matches) > 1:
        return {"ok": False, "problem": "duplicate-authority"}
    if not matches:
        return {"ok": False, "problem": "unknown-authority"}
    authority = matches[0]
    origins = authority.get("origins")
    rp_id = _jsv.show(authority.get("rpId", _jsv.MISSING))
    if not _estate.is_signing_rp_id(rp_id):
        return {"ok": False, "problem": "wrong-rp"}
    credential = {"credentialId": credential_id, "alg": _jsv.show(authority.get("alg", _jsv.MISSING)),
                  "publicKey": authority["publicKey"] if isinstance(authority.get("publicKey"), dict) else {}, "rpId": rp_id,
                  "origins": [o for o in origins if isinstance(o, str) and _estate.origin_within(o, rp_id)] if isinstance(origins, list) else []}
    challenge = hashlib.sha256(signing_statement(ENROLL_TOKEN_TYPE, fields)).digest()
    assertion = _estate.verify_assertion(signature, credential, challenge)
    if not assertion["ok"]:
        return {"ok": False, "problem": assertion["problem"]}
    not_before = _ftime.parse_rfc3339_ms(fields["notBefore"])
    expires_at = _ftime.parse_rfc3339_ms(fields["expiresAt"])
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
    not_before = _ftime.parse_rfc3339_ms(statement.get("notBefore"))
    expires_at = _ftime.parse_rfc3339_ms(statement.get("expiresAt"))
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
# --- the hub's single use of a token (DEC-0084) ----------------------------------------------------------------------

_PROOF = re.compile(r"[A-Za-z0-9_-]{85}[AQgw]\Z")


def _b64url(text: str) -> bytes:
    """Strict base64url decode: a length the alphabet cannot produce raises, as the ceremony's readers expect."""
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _es256_raw(octets: bytes, message: bytes, raw: bytes) -> bool:
    """ECDSA P-256 over SHA-256 with a 64-byte r || s signature, low-S only (relay-auth/1's form)."""
    if len(octets) != 65 or octets[0] != 4 or not _crypto.is_valid_p256_key(octets) or len(raw) != 64:
        return False
    r, s = int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
    n = _crypto._P256_N
    if not (1 <= r < n and 1 <= s <= n // 2):
        return False
    e = int.from_bytes(hashlib.sha256(message).digest(), "big")
    w = pow(s, -1, n)
    point = _crypto._shamir(e * w % n, r * w % n, (int.from_bytes(octets[1:33], "big"), int.from_bytes(octets[33:], "big")))
    return point is not None and point[0] % n == r


def _proves(key: Dict[str, Any], message: str, proof: Any) -> bool:
    """Whether ``proof`` is the presented key's signature over ``message``: 64 bytes in their one canonical base64url
    form, ES256 as r || s low-S, Ed25519 as itself."""
    if not isinstance(proof, str) or not _PROOF.match(proof):
        return False
    octets = base64.b64decode(key["publicKey"])
    signature = _b64url(proof)
    if key.get("alg") == "es256":
        return _es256_raw(octets, message.encode("utf-8"), signature)
    return _crypto.ed25519_verify(octets, message.encode("utf-8"), signature)


def redeem_enroll_token(token: Any, machine_key: Any, proof: Any, ledger: Any) -> Dict[str, Any]:
    """The hub's single use of a token verify_enroll_token accepted. ``machine_key`` is the joining machine's #sig key,
    ``proof`` its signature over ``enroll_join_input(token)``, ``ledger`` the hub's dict from nonce to entry
    (``{"state": "redeemed", "fingerprint"}`` or ``{"state": "revoked"}``). The first failure answers: malformed,
    bad-key, bad-proof, revoked, reused (with the log the hub records); the first use answers the record to store."""
    join = enroll_join_input(token)
    if join is None or not isinstance(ledger, dict):
        return {"ok": False, "problem": "malformed"}
    nonce = _statement_fields(token)["nonce"]
    if machine_of_keys([machine_key]) is None:
        return {"ok": False, "problem": "bad-key"}
    if not _proves(machine_key, join, proof):
        return {"ok": False, "problem": "bad-proof"}
    fingerprint = _estate.device_key_fingerprint(machine_key)
    entry = ledger.get(nonce, _jsv.MISSING)
    if isinstance(entry, dict) and entry.get("state") == "revoked":
        return {"ok": False, "problem": "revoked"}
    if entry is not _jsv.MISSING:
        bound = _jsv.show(entry.get("fingerprint", _jsv.MISSING)) if isinstance(entry, dict) else _jsv.show(entry)
        return {"ok": False, "problem": "reused", "log": {"nonce": nonce, "presented": fingerprint, "boundTo": bound}}
    return {"ok": True, "record": {"nonce": nonce, "state": "redeemed", "fingerprint": fingerprint}}


# --- the nearby pairing (DEC-0084) ------------------------------------------------------------------------------------

PAIRING_SCHEMA = "pairing-message/1"
COMMIT_TYPE = "fabric-enroll-commit/1"
CODE_TYPE = "fabric-enroll-code/1"
FINGERPRINT_TYPE = "estate-fingerprint/1"
CODE_DIGITS = 6
FINGERPRINT_GROUPS = 5
FINGERPRINT_GROUP_DIGITS = 5
RENDEZVOUS_SECONDS = 600
_MACHINE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}\Z")
_KEY_MEMBERS = ["alg", "kid", "publicKey", "use"]
_ALGORITHMS = {"sig": ("es256", "ed25519"), "kem": ("ecdh-p256",)}


from fabric_jsvalue import json_equal as _json_equal  # noqa: E402,F401 - moved (FAA-65)
import fabric_time as _ftime  # noqa: E402 - the core (FAA-65)
import fabric_jsvalue as _jsv  # noqa: E402 - the core (FAA-65)
import fabric_crypto as _crypto  # noqa: E402 - the core (FAA-65)


def _is_role(value: Any) -> bool:
    return value in ("new", "trusted") and isinstance(value, str)


def machine_of_keys(keys: Any) -> Optional[str]:
    """The machine a key list belongs to, or None: one or two keys, each exactly {kid, use, alg, publicKey}, one sig
    (es256 or ed25519) and at most one kem (ecdh-p256), each kid <id>#<use> for one machine id, each key valid and in
    canonical padded base64, no key in both roles."""
    if not isinstance(keys, list) or not 1 <= len(keys) <= 2:
        return None
    ids, uses, octets = set(), set(), set()
    for key in keys:
        if not isinstance(key, dict) or sorted(key) != _KEY_MEMBERS:
            return None
        use, kid, alg = key["use"], key["kid"], key["alg"]
        if not isinstance(use, str) or not isinstance(kid, str) or not isinstance(alg, str) or alg not in _ALGORITHMS.get(use, ()):
            return None
        machine = kid[: -(len(use) + 1)] if kid.endswith("#" + use) else ""
        if (not _MACHINE_ID.match(machine) or use in uses or _estate.device_key_fingerprint(key) is None
                or not _estate._valid_device_key(key) or key["publicKey"] in octets):
            return None
        ids.add(machine)
        uses.add(use)
        octets.add(key["publicKey"])
    return next(iter(ids)) if len(ids) == 1 and "sig" in uses else None


def _side_problem(side: Any) -> Optional[str]:
    if not isinstance(side, dict):
        return "malformed"
    role = side.get("role")
    if not _is_role(role):
        return "bad-role"
    if not _matches(_NONCE32, side.get("nonce")):
        return "bad-nonce"
    if machine_of_keys(side.get("keys")) is None:
        return "bad-keys"
    if role == "trusted":
        if not _matches(_SHA256, side.get("genesis")):
            return "bad-genesis"
    elif "genesis" in side:
        return "bad-genesis"
    return None


def _covered(side: Dict[str, Any]) -> Dict[str, Any]:
    if side["role"] == "trusted":
        return {"keys": side["keys"], "nonce": side["nonce"], "genesis": side["genesis"]}
    return {"keys": side["keys"], "nonce": side["nonce"]}


def _sha_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pairing_commit(side: Any) -> Dict[str, Any]:
    """A side's commitment: sha256 of the RFC 8785 form of {type: fabric-enroll-commit/1, role, keys, nonce, genesis?}."""
    problem = _side_problem(side)
    if problem:
        return {"ok": False, "problem": problem}
    return {"ok": True, "commit": "sha256:" + _sha_hex(_jsv.jcs(dict({"type": COMMIT_TYPE, "role": side["role"]}, **_covered(side))))}


def _message(value: Any, step: str) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict) or value.get("schema") != PAIRING_SCHEMA or value.get("step") != step:
        return None
    members = ",".join(sorted(value))
    if step == "commit":
        return value if members == "commit,role,schema,step" and _matches(_SHA256, value.get("commit")) else None
    return value if members in ("keys,nonce,role,schema,step", "genesis,keys,nonce,role,schema,step") else None


def check_reveal(commit: Any, reveal: Any, expected: Optional[str] = None) -> Dict[str, Any]:
    """Check the other side's reveal against its commitment; answers the revealing machine's id."""
    c, r = _message(commit, "commit"), _message(reveal, "reveal")
    if c is None or r is None:
        return {"ok": False, "problem": "malformed"}
    if not _jsv.same(r["role"], c["role"]) or (expected is not None and not _jsv.same(r["role"], expected)):
        return {"ok": False, "problem": "role-mismatch"}
    made = pairing_commit({k: v for k, v in r.items() if k not in ("schema", "step")})
    if not made["ok"]:
        return made
    if made["commit"] != c["commit"]:
        return {"ok": False, "problem": "commit-mismatch"}
    return {"ok": True, "machine": machine_of_keys(r["keys"])}


def comparison_code(new_reveal: Any, trusted_reveal: Any) -> Dict[str, Any]:
    """The six-digit code both screens show, over both reveals' keys, nonces and the estate's genesis."""
    a, b = _message(new_reveal, "reveal"), _message(trusted_reveal, "reveal")
    if a is None or b is None:
        return {"ok": False, "problem": "malformed"}
    if not _jsv.same(a["role"], "new") or not _jsv.same(b["role"], "trusted"):
        return {"ok": False, "problem": "role-mismatch" if _is_role(a["role"]) and _is_role(b["role"]) else "bad-role"}
    problem = _side_problem(a) or _side_problem(b)
    if problem:
        return {"ok": False, "problem": problem}
    if machine_of_keys(a["keys"]) == machine_of_keys(b["keys"]):
        return {"ok": False, "problem": "same-machine"}
    digest = hashlib.sha256(_jsv.jcs({"type": CODE_TYPE, "new": _covered(a), "trusted": _covered(b)}).encode("utf-8")).digest()
    return {"ok": True, "code": str(int.from_bytes(digest[:5], "big") % 10 ** CODE_DIGITS).zfill(CODE_DIGITS)}


def estate_fingerprint(digest: Any) -> Dict[str, Any]:
    """The estate's fingerprint from revision 1's digest: five groups of five digits a person compares."""
    if not _matches(_SHA256, digest):
        return {"ok": False, "problem": "malformed"}
    f = hashlib.sha256(_jsv.jcs({"type": FINGERPRINT_TYPE, "digest": digest}).encode("utf-8")).digest()
    groups = [str(int.from_bytes(f[5 * i:5 * i + 5], "big") % 10 ** FINGERPRINT_GROUP_DIGITS).zfill(FINGERPRINT_GROUP_DIGITS) for i in range(FINGERPRINT_GROUPS)]
    return {"ok": True, "fingerprint": " ".join(groups)}


def checked_comparison_code(new_commit: Any, new_reveal: Any, trusted_commit: Any, trusted_reveal: Any) -> Dict[str, Any]:
    """The comparison code only after each reveal opened its own commitment."""
    a = check_reveal(new_commit, new_reveal, "new")
    if not a["ok"]:
        return a
    b = check_reveal(trusted_commit, trusted_reveal, "trusted")
    if not b["ok"]:
        return b
    return comparison_code(new_reveal, trusted_reveal)


def rendezvous_verdict(opened_at: Any, messages: Any, at: Any) -> Dict[str, Any]:
    """A one-time rendezvous after the messages it carried, at ``at`` (an aware datetime or epoch seconds): open,
    complete, or burned with the reason and the index of the message that burned it."""
    opened = _ftime.parse_rfc3339_ms(opened_at)
    now = _ftime.clock_ms(at)
    if not _finite(opened) or not _finite(now) or not isinstance(messages, list):
        return {"state": "burned", "reason": "malformed", "index": -1}
    if now > opened + RENDEZVOUS_SECONDS * 1000 or now < opened - _estate.CLOCK_SKEW_SECONDS * 1000:
        return {"state": "burned", "reason": "expired", "index": -1}
    commits: Dict[str, Any] = {}
    revealed: set = set()
    for index, item in enumerate(messages):
        def burn(reason: str) -> Dict[str, Any]:
            return {"state": "burned", "reason": reason, "index": index}
        if (isinstance(item, dict) and item.get("schema") == PAIRING_SCHEMA and item.get("step") == "abort"
                and sorted(item) == ["role", "schema", "step"] and _is_role(item.get("role"))):
            return burn("aborted")
        if len(revealed) == 2:
            return burn("closed")
        commit, reveal = _message(item, "commit"), _message(item, "reveal")
        role = (commit or reveal or {}).get("role")
        if not _is_role(role):
            return burn("malformed")
        if commit is not None:
            if role in commits:
                return burn("repeated")
            commits[role] = commit
            continue
        if role in revealed:
            return burn("repeated")
        if len(commits) < 2:
            return burn("out-of-order")
        checked = check_reveal(commits.get(role), reveal, role)
        if not checked["ok"]:
            return burn("commit-mismatch" if checked["problem"] == "commit-mismatch" else "malformed")
        revealed.add(role)
    return {"state": "complete"} if len(revealed) == 2 else {"state": "open"}


def _machine_of(record: Dict[str, Any], machine_id: Any) -> Optional[Dict[str, Any]]:
    machines = record.get("machines")
    if not isinstance(machines, list):
        return None
    return next((m for m in machines if isinstance(m, dict) and _jsv.same(m.get("id", _jsv.MISSING), machine_id)), None)


def _machine_revoked(record: Dict[str, Any], machine_id: Any) -> bool:
    revocations = record.get("revocations")
    return isinstance(revocations, list) and any(isinstance(e, dict) and e.get("kind") == "machine"
                                                 and _jsv.same(e.get("ref", _jsv.MISSING), machine_id) for e in revocations)


def join_listed(record: Any, new_reveal: Any, trusted_reveal: Any, genesis: Any) -> Dict[str, Any]:
    """What the new machine checks before it pins and applies: the estate is the one the code bound, and the record
    lists it with exactly the keys it revealed and the trusted machine with its revealed #sig key, revoking neither."""
    a, b = _message(new_reveal, "reveal"), _message(trusted_reveal, "reveal")
    if (not isinstance(record, dict) or a is None or b is None or not _jsv.same(a["role"], "new")
            or not _jsv.same(b["role"], "trusted") or _side_problem(a) or _side_problem(b)):
        return {"ok": False, "problem": "malformed"}
    if not isinstance(genesis, str) or b["genesis"] != genesis:
        return {"ok": False, "problem": "other-estate"}
    new_id, trusted_id = machine_of_keys(a["keys"]), machine_of_keys(b["keys"])
    machine = _machine_of(record, new_id)
    if machine is None or _machine_revoked(record, new_id):
        return {"ok": False, "problem": "not-listed"}
    listed = machine.get("deviceKeys")
    if not isinstance(listed, list) or len(listed) != len(a["keys"]) or not all(any(_json_equal(k, o) for o in a["keys"]) for k in listed):
        return {"ok": False, "problem": "other-keys"}
    trusted = _machine_of(record, trusted_id)
    sig = next(k for k in b["keys"] if k["use"] == "sig")
    if (trusted is None or _machine_revoked(record, trusted_id) or not isinstance(trusted.get("deviceKeys"), list)
            or not any(_json_equal(k, sig) for k in trusted["deviceKeys"])):
        return {"ok": False, "problem": "trusted-not-listed"}
    return {"ok": True}


def own_keys_decision(record: Any, machine_id: Any, held: Any) -> Dict[str, Any]:
    """What a node does with a verified revision when its own keys are in question: apply (retiring the held keys the
    record no longer lists, by key reference), stop as removed, stop as keys-replaced, or malformed."""
    if not isinstance(record, dict) or not isinstance(machine_id, str) or not isinstance(held, list):
        return {"action": "malformed"}
    machine = _machine_of(record, machine_id)
    if machine is None or _machine_revoked(record, machine_id):
        return {"action": "stop", "reason": "removed"}
    listed = machine.get("deviceKeys") if isinstance(machine.get("deviceKeys"), list) else []
    if not listed or not all(any(_json_equal(k, mine) for mine in held) for k in listed):
        return {"action": "stop", "reason": "keys-replaced"}
    retire = [ref for ref in (_estate.device_key_ref(k) for k in held if not any(_json_equal(k, o) for o in listed)) if isinstance(ref, str)]
    return {"action": "apply", "retire": retire}
# #endregion ceremonies-kit
