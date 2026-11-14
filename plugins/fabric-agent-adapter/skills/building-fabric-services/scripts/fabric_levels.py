# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
"""Authority levels (DEC-0162): an organization's owner, an administrator or an architect in its projects decides for
the organization's agents as the operator does, proved by a signed `org-membership/2` attestation the call's delegation
token binds by `mem`. Part of the service kit (layer L2); the twin of fabric-levels.mjs.

- ``verify_org_membership(value, trust)``: the contract's reference verifier of an `org-membership/1` or `/2`
  attestation (DEC-0127 OM-4, DEC-0162 LV-1) under the organization's key set the service applied: ``{"ok": True,
  status, role, type?, projects?, expiresAt?, refreshDue, unchanged, digest, held}`` or ``{"ok": False, "problem"}``.
  ``trust`` holds ``now`` (milliseconds since the epoch, or a datetime), ``org``, ``audience``, ``subject?``, ``keySet``
  (applied under the pinned root: this verifier reads the set's shape, never its root signature), ``held?`` and
  ``levels`` (True for a reader the issuer registered for `/2`).
- ``level_standing(inputs)``: whether a level stands for one call (LV-4, LV-5, LV-7, LV-11), as the contract's
  ``levelStanding`` answers; ``level_short_of(level, min_level, in_project)``: the detail a level gets for an action
  declared above it (DEC-0166 AU-2 reads it); ``level_contexts_well_formed(levels)``: the service's own configuration.
- ``level_rules(kind, value)``: FAC-SEM-170 on a level decision (kind ``decision``) or a level mandate (``mandate``).

Ed25519 is fabric_crypto's (no dependency). Never raises on JSON as json.loads gives it. Standard library only.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from typing import Any, Dict, List, Optional

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))

from fabric_crypto import b64url_decode, ed25519_verify, is_small_order_key, sha256  # noqa: E402
from fabric_jsvalue import jcs, show  # noqa: E402
from fabric_time import parse_rfc3339_ms  # noqa: E402

ORG_MEMBERSHIP_TYPE = "org-membership/1"
ORG_MEMBERSHIP_2_TYPE = "org-membership/2"
ORG_KEY_SET_TYPE = "org-key-set/1"
ORG_MEMBERSHIP_ALGORITHMS = ("EdDSA",)
MAX_ATTESTATION_SECONDS = 24 * 60 * 60
REFRESH_SECONDS = 15 * 60
CLOCK_SKEW_SECONDS = 60
ORG_ROLES = ("owner", "admin", "member")
#: The roles of org-membership/2, highest first: each covers the ones after it, an architect within its projects (LV-2).
LEVEL_ROLES = ("owner", "admin", "architect", "member")
MAX_PROJECTS = 64
MEMBERSHIP_STATUSES = ("active", "ended")
MAX_EXTENSIONS = 16
MAX_KEYS = 32
MAX_REVOKED = 256
MAX_ADMINISTRATORS = 16
#: The levels a service may declare an action needs (LV-7), in its authority extension's `actionLevels`.
ACTION_LEVELS = ("operator", "owner", "admin", "architect")
#: The levels a decision or a mandate may name, highest first; `member` decides nothing by its level (LV-2).
DECIDING_LEVELS = ("owner", "admin", "architect")
_RANK = {"owner": 3, "admin": 2, "architect": 1, "member": 0}

ORG_MEMBERSHIP_FIELDS = ("issuer", "org", "audience", "subject", "role", "external", "status", "revision",
                         "membershipEndsAt", "issuedAt", "notBefore", "expiresAt", "extensions", "alg", "kid")
ORG_MEMBERSHIP_2_FIELDS = ("issuer", "org", "audience", "subject", "role", "projects", "external", "status", "revision",
                           "membershipEndsAt", "issuedAt", "notBefore", "expiresAt", "extensions", "alg", "kid")
ORG_KEY_SET_FIELDS = ("issuer", "org", "revision", "issuedAt", "keys", "revoked", "administrators", "alg", "kid")
_AUTHORITY_FIELDS = ("credentialId", "alg", "publicKey", "rpId", "origins")
_ASSERTION_ALGORITHMS = ("ES256", "EdDSA")

#: `common.schema.json#/$defs/contextId` (DEC-0082): `personal` or `org:` and an id.
CALL_CONTEXT = re.compile(r"(?:personal|org:[A-Za-z0-9][A-Za-z0-9_-]{0,127})", re.ASCII)
_OPAQUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}", re.ASCII)
ORG = re.compile(r"org:[A-Za-z0-9][A-Za-z0-9_-]{0,127}", re.ASCII)
_ISSUER = re.compile(r"https://(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.ASCII)
_EXTENSION = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?/[a-z][a-z0-9._-]{0,63}", re.ASCII)
_SIG = re.compile(r"[A-Za-z0-9_-]{85}[AQgw]", re.ASCII)
_X = re.compile(r"[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]", re.ASCII)
_SHA256 = re.compile(r"sha256:[a-f0-9]{64}", re.ASCII)
_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", re.ASCII)
_B64URL = re.compile(r"[A-Za-z0-9_-]+", re.ASCII)
_ORIGIN = re.compile(r"https://[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", re.ASCII)
#: At most three fraction digits: every port compares the same instants, at millisecond precision (DEC-0085).
_MILLISECONDS = re.compile(r".*:[0-9]{2}(?:\.[0-9]{1,3})?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})", re.ASCII | re.DOTALL)


def _matches(pattern: "re.Pattern[str]", value: Any) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _positive(value: Any) -> bool:
    return type(value) is int and 1 <= value <= 2 ** 53 - 1 or (type(value) is float and value.is_integer() and 1 <= value <= 2 ** 53 - 1)


def _time(value: Any) -> float:
    """A strict RFC 3339 instant with at most three fraction digits, in milliseconds, or NaN."""
    return parse_rfc3339_ms(value) if isinstance(value, str) and _MILLISECONDS.fullmatch(value) else math.nan


def _readable(value: Any) -> bool:
    return not math.isnan(_time(value))


def _exactly(value: Dict[str, Any], names: Any) -> bool:
    return len(value) == len(names) and all(name in value for name in names)


def _issuer_ok(value: Any) -> bool:
    return isinstance(value, str) and len(value) <= 261 and _ISSUER.fullmatch(value) is not None


def _digest_of(data: bytes) -> str:
    return "sha256:" + sha256(data).hex()


def _statement(kind: str, fields: Dict[str, Any], names: Any) -> Optional[bytes]:
    """The signing register's statement (DEC-0063): the UTF-8 RFC 8785 form of ``{type, ...fields}`` when the fields are
    exactly the type's."""
    if not _exactly(fields, names):
        return None
    try:
        return jcs(dict(fields, type=kind)).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        return None


def org_membership_signing_input(attestation: Any) -> Optional[bytes]:
    """The bytes the organization's key signs: the attestation without `sig`, as the register states it."""
    if not isinstance(attestation, dict) or attestation.get("type") not in (ORG_MEMBERSHIP_TYPE, ORG_MEMBERSHIP_2_TYPE):
        return None
    fields = {name: value for name, value in attestation.items() if name not in ("type", "sig")}
    names = ORG_MEMBERSHIP_2_FIELDS if attestation["type"] == ORG_MEMBERSHIP_2_TYPE else ORG_MEMBERSHIP_FIELDS
    return _statement(attestation["type"], fields, names)


def _extensions_ok(value: Any) -> bool:
    if not isinstance(value, dict) or len(value) > MAX_EXTENSIONS:
        return False
    for name, item in value.items():
        if not (len(name) <= 320 and _EXTENSION.fullmatch(name)):
            return False
        if not ((isinstance(item, str) and len(item) <= 256) or type(item) is bool
                or (type(item) is int and abs(item) <= 2 ** 53 - 1) or (type(item) is float and item.is_integer() and abs(item) <= 2 ** 53 - 1)):
            return False
    return True


def _projects_ok(role: Any, projects: Any) -> bool:
    """`/2`'s projects (FAC-SEM-169): 1 to 64 distinct projects for an architect, none for any other role."""
    if not isinstance(projects, list) or len(projects) > MAX_PROJECTS or not all(_matches(_PROJECT, p) for p in projects):
        return False
    if len(set(projects)) != len(projects):
        return False
    return (role == "architect") == (len(projects) > 0)


def org_membership_well_formed(doc: Dict[str, Any]) -> bool:
    """Whether an attestation's members have the shapes the schema gives them, the algorithm's value aside."""
    levels = doc.get("type") == ORG_MEMBERSHIP_2_TYPE
    names = (ORG_MEMBERSHIP_2_FIELDS if levels else ORG_MEMBERSHIP_FIELDS) + ("type", "sig")
    if not _exactly(doc, names):
        return False
    role_ok = (isinstance(doc["role"], str) and doc["role"] in LEVEL_ROLES and _projects_ok(doc["role"], doc["projects"])) if levels \
        else (isinstance(doc["role"], str) and doc["role"] in ORG_ROLES)
    return (_issuer_ok(doc["issuer"]) and _matches(ORG, doc["org"]) and _matches(_OPAQUE, doc["audience"])
            and _matches(_OPAQUE, doc["subject"]) and role_ok and type(doc["external"]) is bool
            and isinstance(doc["status"], str) and doc["status"] in MEMBERSHIP_STATUSES and _positive(doc["revision"])
            and (doc["membershipEndsAt"] is None or _readable(doc["membershipEndsAt"]))
            and _readable(doc["issuedAt"]) and _readable(doc["notBefore"]) and _readable(doc["expiresAt"])
            and _extensions_ok(doc["extensions"]) and isinstance(doc["alg"], str) and _matches(_OPAQUE, doc["kid"])
            and _matches(_SIG, doc["sig"]))


def _jwk_ok(key: Any) -> bool:
    if not isinstance(key, dict):
        return False
    if key.get("kty") == "EC":
        return _exactly(key, ("kty", "crv", "x", "y")) and key["crv"] == "P-256" and _matches(_X, key["x"]) and _matches(_X, key["y"])
    return key.get("kty") == "OKP" and _exactly(key, ("kty", "crv", "x")) and key["crv"] == "Ed25519" and _matches(_X, key["x"])


def administrator_ok(value: Any) -> bool:
    """One administrator credential in `org-key-set/1`'s shape (DEC-0129)."""
    if not (isinstance(value, dict) and _exactly(value, _AUTHORITY_FIELDS)):
        return False
    origins = value["origins"]
    return (isinstance(value["credentialId"], str) and len(value["credentialId"]) <= 1366 and _B64URL.fullmatch(value["credentialId"]) is not None
            and isinstance(value["alg"], str) and value["alg"] in _ASSERTION_ALGORITHMS and _jwk_ok(value["publicKey"])
            and (value["alg"] == "ES256") == (value["publicKey"].get("kty") == "EC")
            and isinstance(value["rpId"], str) and isinstance(origins, list) and 1 <= len(origins) <= 8
            and all(isinstance(o, str) and len(o) <= 256 and _ORIGIN.fullmatch(o) for o in origins)
            and len(set(origins)) == len(origins))


def _valid_at_issue(keyset: Dict[str, Any]) -> bool:
    issued = _time(keyset["issuedAt"])
    return any(isinstance(key, dict) and _time(key.get("notBefore")) <= issued < _time(key.get("notAfter")) for key in keyset["keys"])


def org_key_set_well_formed(keyset: Any) -> bool:
    """A key set's shapes and FAC-SEM-146's structure; algorithms, small-order keys and signing RP IDs aside."""
    if not (isinstance(keyset, dict) and keyset.get("type") == ORG_KEY_SET_TYPE and _exactly(keyset, ORG_KEY_SET_FIELDS + ("type", "sig"))):
        return False
    keys, revoked, admins = keyset["keys"], keyset["revoked"], keyset["administrators"]
    if not (_issuer_ok(keyset["issuer"]) and _matches(ORG, keyset["org"]) and _positive(keyset["revision"]) and _readable(keyset["issuedAt"])
            and isinstance(keys, list) and 1 <= len(keys) <= MAX_KEYS
            and isinstance(revoked, list) and len(revoked) <= MAX_REVOKED and all(_matches(_OPAQUE, kid) for kid in revoked)
            and len(set(revoked)) == len(revoked)
            and isinstance(admins, list) and len(admins) <= MAX_ADMINISTRATORS and all(administrator_ok(a) for a in admins)
            and len({a["credentialId"] for a in admins}) == len(admins)
            and isinstance(keyset["alg"], str) and _matches(_OPAQUE, keyset["kid"]) and _matches(_SIG, keyset["sig"])):
        return False
    kids = set()
    for key in keys:
        if not (isinstance(key, dict) and _exactly(key, ("kid", "alg", "x", "notBefore", "notAfter")) and _matches(_OPAQUE, key["kid"])
                and isinstance(key["alg"], str) and _matches(_X, key["x"])):
            return False
        if key["kid"] in kids or key["kid"] == keyset["kid"] or key["kid"] in revoked:
            return False
        kids.add(key["kid"])
        if not _time(key["notBefore"]) < _time(key["notAfter"]):
            return False
    return _valid_at_issue(keyset)


def held_membership_ok(held: Any) -> bool:
    return isinstance(held, dict) and _matches(_OPAQUE, held.get("subject")) and _positive(held.get("revision")) and _matches(_SHA256, held.get("digest"))


def _trust_clauses_ok(org: Any, audience: Any, keyset: Any) -> bool:
    return (_matches(ORG, org) and _matches(_OPAQUE, audience) and org_key_set_well_formed(keyset)
            and keyset["alg"] in ORG_MEMBERSHIP_ALGORITHMS and keyset["org"] == org)


def _clock_of(now: Any) -> float:
    if isinstance(now, _dt.datetime):
        return now.timestamp() * 1000 if now.tzinfo is not None else math.nan
    if type(now) in (int, float) and math.isfinite(now):
        return float(now)
    return math.nan


def verify_org_membership(value: Any, trust: Any) -> Dict[str, Any]:
    """The contract's verifyOrgMembership (DEC-0127 OM-4, DEC-0162 LV-1), in its order; never raises."""
    if not isinstance(trust, dict):
        return {"ok": False, "problem": "context-invalid"}
    now = _clock_of(trust.get("now"))
    if math.isnan(now):
        return {"ok": False, "problem": "no-clock"}
    held = trust.get("held")
    levels = trust.get("levels")
    if not (_trust_clauses_ok(trust.get("org"), trust.get("audience"), trust.get("keySet"))
            and ("subject" not in trust or _matches(_OPAQUE, trust["subject"]))
            and (held is None or held_membership_ok(held)) and (levels is None or type(levels) is bool)):
        return {"ok": False, "problem": "context-invalid"}
    known = isinstance(value, dict) and (value.get("type") == ORG_MEMBERSHIP_TYPE or (levels is True and value.get("type") == ORG_MEMBERSHIP_2_TYPE))
    data = org_membership_signing_input(value) if known and org_membership_well_formed(value) else None
    if data is None:
        return {"ok": False, "problem": "malformed"}
    keyset = trust["keySet"]
    if value["issuer"] != keyset["issuer"]:
        return {"ok": False, "problem": "wrong-issuer"}
    if value["alg"] not in ORG_MEMBERSHIP_ALGORITHMS:
        return {"ok": False, "problem": "unknown-algorithm"}
    key = next((entry for entry in keyset["keys"] if entry["kid"] == value["kid"]), None)
    if key is None:
        return {"ok": False, "problem": "key-revoked" if value["kid"] in keyset["revoked"] else "unknown-key"}
    if key["alg"] != value["alg"]:
        return {"ok": False, "problem": "unusable-key"}
    raw = b64url_decode(key["x"])
    if is_small_order_key(raw):
        return {"ok": False, "problem": "small-order-key"}
    issued = _time(value["issuedAt"])
    if issued < _time(key["notBefore"]) or issued >= _time(key["notAfter"]):
        return {"ok": False, "problem": "key-not-valid"}
    if not ed25519_verify(raw, data, b64url_decode(value["sig"])):
        return {"ok": False, "problem": "bad-signature"}
    if value["org"] != trust["org"]:
        return {"ok": False, "problem": "wrong-org"}
    if value["audience"] != trust["audience"]:
        return {"ok": False, "problem": "wrong-audience"}
    if "subject" in trust and value["subject"] != trust["subject"]:
        return {"ok": False, "problem": "wrong-subject"}
    not_before, expires = _time(value["notBefore"]), _time(value["expiresAt"])
    if issued > not_before or not_before >= expires or expires - issued > MAX_ATTESTATION_SECONDS * 1000:
        return {"ok": False, "problem": "too-long-lived"}
    if now < not_before - CLOCK_SKEW_SECONDS * 1000:
        return {"ok": False, "problem": "not-yet-valid"}
    if now >= expires:
        return {"ok": False, "problem": "expired"}
    digest = _digest_of(data)
    unchanged = False
    if held is not None and held["subject"] == value["subject"]:
        if value["revision"] < held["revision"]:
            return {"ok": False, "problem": "stale-revision"}
        if value["revision"] == held["revision"] and digest != held["digest"]:
            return {"ok": False, "problem": "revision-conflict"}
        unchanged = value["revision"] == held["revision"]
    ends = math.inf if value["membershipEndsAt"] is None else _time(value["membershipEndsAt"])
    verdict: Dict[str, Any] = {"ok": True, "status": "ended" if value["status"] == "ended" or now >= ends else "active",
                               "role": value["role"]}
    if value["type"] == ORG_MEMBERSHIP_2_TYPE:
        verdict.update({"type": ORG_MEMBERSHIP_2_TYPE, "projects": list(value["projects"]), "expiresAt": value["expiresAt"]})
    verdict.update({"refreshDue": now >= expires - REFRESH_SECONDS * 1000, "unchanged": unchanged, "digest": digest,
                    "held": {"subject": value["subject"], "revision": value["revision"], "digest": digest}})
    return verdict


def level_context_ok(org: str, entry: Any) -> bool:
    """One entry of a service's level contexts: an opaque audience, a well-formed EdDSA key set of that organization,
    attestations held by subject."""
    if not isinstance(entry, dict) or not _trust_clauses_ok(org, entry.get("audience"), entry.get("keySet")):
        return False
    if not all(key["alg"] in ORG_MEMBERSHIP_ALGORITHMS for key in entry["keySet"]["keys"]):
        return False
    if "held" not in entry:
        return True
    held = entry["held"]
    return isinstance(held, dict) and all(held_membership_ok(h) and h["subject"] == subject for subject, h in held.items())


def level_contexts_well_formed(levels: Any) -> bool:
    """Whether a service's level contexts are its own well-formed configuration: a map keyed by `org:<orgId>`."""
    return isinstance(levels, dict) and all(level_context_ok(org, entry) for org, entry in levels.items())


def _strictest(min_level: Any) -> bool:
    """`operator`, or a declared level that is not one of ACTION_LEVELS, read as the strictest (LV-7)."""
    return min_level is not None and (min_level == "operator" or not (isinstance(min_level, str) and min_level in ACTION_LEVELS))


def level_short_of(level: Any, min_level: Any, in_project: bool) -> Optional[str]:
    """The detail a level gets for an action its service declares `min_level` (LV-7, LV-10), or None when it covers it."""
    if _strictest(min_level):
        return "level-insufficient: operator"
    rank = _RANK.get(level, 0) if isinstance(level, str) else 0
    if min_level == "owner" and rank < _RANK["owner"]:
        return "level-insufficient: owner"
    if (min_level == "admin" or not in_project) and rank < _RANK["admin"]:
        return "level-insufficient: admin"
    return None


def level_standing(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Whether a level stands for one call (DEC-0162 LV-4, LV-5, LV-7, LV-11), as the contract's levelStanding answers:
    ``{"ok": True, level, org, approver, membershipDigest, revision, projects}``, ``{"ok": False, "invalid": detail}`` or
    ``{"ok": False, "insufficient": detail}``. ``inputs``: membership, org, level, at, project?, context, contexts,
    tokenMem?, minLevel?, now (milliseconds)."""
    org, level, project = inputs.get("org"), inputs.get("level"), inputs.get("project")
    if inputs.get("context") != org:
        return {"ok": False, "invalid": "level-membership: context-invalid"}
    contexts = inputs.get("contexts")
    context = contexts.get(org) if isinstance(contexts, dict) and isinstance(org, str) and org in contexts else None
    membership = inputs.get("membership")
    subject = membership.get("subject") if isinstance(membership, dict) and isinstance(membership.get("subject"), str) else None
    held_by_subject = None
    if isinstance(context, dict) and isinstance(context.get("held"), dict) and subject is not None and subject in context["held"]:
        held_by_subject = context["held"][subject]
    trust: Dict[str, Any] = {"now": inputs.get("now"), "org": org, "audience": context.get("audience") if isinstance(context, dict) else "",
                             "keySet": context.get("keySet") if isinstance(context, dict) else {}, "levels": True}
    if held_by_subject is not None:
        trust["held"] = held_by_subject
    verdict = verify_org_membership(membership, trust)
    if not verdict["ok"]:
        if verdict["problem"] == "wrong-audience":
            return {"ok": False, "invalid": "level-audience"}
        if verdict["problem"] == "expired":
            return {"ok": False, "invalid": "level-expired"}
        return {"ok": False, "invalid": "level-membership: %s" % verdict["problem"]}
    if verdict.get("type") != ORG_MEMBERSHIP_2_TYPE:
        return {"ok": False, "invalid": "level-membership: malformed"}
    if verdict["status"] != "active":  # LV-11: an ended membership ends its level at once
        return {"ok": False, "invalid": "level-membership: ended"}
    if inputs.get("tokenMem") != verdict["digest"]:
        return {"ok": False, "invalid": "level-unbound"}
    if not parse_rfc3339_ms(inputs.get("at")) < parse_rfc3339_ms(verdict["expiresAt"]):
        return {"ok": False, "invalid": "level-expired"}
    rank = _RANK[level] if isinstance(level, str) and level in DECIDING_LEVELS else math.inf
    if rank > _RANK[verdict["role"]]:
        return {"ok": False, "invalid": "level-role"}
    projects = verdict["projects"]
    min_level = inputs.get("minLevel")
    if _strictest(min_level):
        return {"ok": False, "insufficient": "level-insufficient: operator"}
    if min_level == "owner" and rank < _RANK["owner"]:
        return {"ok": False, "insufficient": "level-insufficient: owner"}
    if (min_level == "admin" or project is None) and rank < _RANK["admin"]:
        return {"ok": False, "insufficient": "level-insufficient: admin"}
    if verdict["role"] == "architect" and project is not None and project not in projects:
        return {"ok": False, "insufficient": "level-insufficient: admin"}
    return {"ok": True, "level": level, "org": org, "approver": verdict["held"]["subject"], "membershipDigest": verdict["digest"],
            "revision": verdict["held"]["revision"], "projects": projects}


def _level_document(value: Dict[str, Any], projects: Optional[List[Any]], at: Any, flag: Any) -> None:
    membership = value.get("membership")
    if not isinstance(membership, dict) or membership.get("type") != ORG_MEMBERSHIP_2_TYPE:
        flag("/membership", "a level decision carries the holder's org-membership/2 attestation")
        return
    if membership.get("org") != value.get("org"):
        flag("/org", "the level is in %s, the attestation's organization, not %s" % (show(membership.get("org")), show(value.get("org"))))
    level = _RANK.get(value.get("level"), 4) if isinstance(value.get("level"), str) else 4
    role = _RANK.get(membership.get("role"), -1) if isinstance(membership.get("role"), str) else -1
    if level > role:
        flag("/level", "the attestation's role %s does not cover the level %s" % (show(membership.get("role")), show(value.get("level"))))
    if not parse_rfc3339_ms(at) < parse_rfc3339_ms(membership.get("expiresAt")):
        flag("/at", "the holder decides before the attestation's expiresAt")
    if value.get("level") == "architect" and membership.get("role") == "architect":
        own = membership["projects"] if isinstance(membership.get("projects"), list) else []
        if not projects:
            flag("/level", "an architect decides only in its projects: the decision names one, a mandate's scope lists them")
        else:
            for project in projects:
                if project not in own:
                    flag("/membership/projects", "the project %s is not among the architect's projects" % show(project))


def level_rules(kind: str, value: Any) -> Optional[List[Dict[str, str]]]:
    """FAC-SEM-170 on kind `decision` (a level decision) and on kind `mandate` (a level mandate); None for any other kind."""
    if kind not in ("decision", "mandate"):
        return None
    findings: List[Dict[str, str]] = []
    if not isinstance(value, dict) or value.get("by") != "level":
        return findings

    def flag(path: str, message: str) -> None:
        findings.append({"code": "FAC-SEM-170", "instancePath": path, "message": message})

    if kind == "decision":
        _level_document(value, None if "project" not in value else [value["project"]], value.get("at"), flag)
    else:
        scope = value.get("scope") if isinstance(value.get("scope"), dict) else {}
        _level_document(value, scope["projects"] if isinstance(scope.get("projects"), list) else None, value.get("at"), flag)
    return findings
