#!/usr/bin/env python3
"""Share grants into an organization and their registrations (contract DEC-0086), the Python kit; the Node twin is
fabric-share.mjs. Standard library only.

What a kit checks before it writes or reads them:

- FAC-SEM-117: a grant whose context is an organization's (``org:<orgId>``) is named ``urn:fabric:share:`` and 32
  lower-case hex digits, carries its window with at most three fraction digits, runs one agentRef among the placements
  naming it, and keeps that agentRef against the earlier revision given as ``parent`` (a move revokes the grant and
  mints a new id).
- FAC-SEM-118: a ``share-registration/1`` document's instants are readable and an active window ends after it starts.
- FAC-SEM-045, the clause DEC-0086 adds: a ``grant.usage`` event carries its grant's own context, ``org:`` and the client
  certificate's ``org.id`` as written. The other FAC-SEM-045 clauses (epochs, users) are the receiving server's and not
  ported here.

Deriving, deciding and joining registrations (``deriveShareRegistrations``, ``decideShareRegistration``,
``joinGrantUsage``, ``gateGrantUsage``) belong to the sharer's node and the organization server, not to this kit.
``share-registration.schema.json`` beside this file is the contract's schema with its outside definitions brought in.
Every function answers and never raises on malformed input. Normative source: the contract's
src/share-registration.ts and docs/specification/share-registration.md.
"""
# #region share-kit, docs: plugins/fabric-agent-adapter/skills/building-fabric-services/references/estate-record.md#share-grants-into-an-organization

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_estate as _estate  # noqa: E402 - beside this file: FAC-SEM-110, times, show
import fabric_identifiers as _ids  # noqa: E402 - beside this file: identifier equality (DEC-0076)

SHARE_REGISTRATION_TYPE = "share-registration/1"
SHARE_REGISTRATION_RECEIPT_TYPE = "share-registration-receipt/1"
#: ``common#/$defs/shareGrantId`` and ``#/$defs/orgContextId``: compared as written, the end of the text is the end.
SHARE_GRANT_ID = re.compile(r"urn:fabric:share:(?!0{32}\Z)[0-9a-f]{32}\Z")
ORG_CONTEXT = re.compile(r"org:[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
#: ``share-registration#/$defs/instant``: an offset, seconds 00 to 59, at most three fraction digits.
_INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-5][0-9](?:\.[0-9]{1,3})?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})\Z")
_SUB_MILLISECOND = re.compile(r":[0-9]{2}\.[0-9]{4,}")


def _finding(code: str, at: str, message: str) -> Dict[str, str]:
    return {"code": code, "instancePath": at, "message": message}


def _objects(value: Any) -> List[Any]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


from fabric_jsvalue import indexed_objects as _indexed  # noqa: E402 - the core's (FAA-65)
import fabric_time as _ftime  # noqa: E402 - the core (FAA-65)
import fabric_jsvalue as _jsv  # noqa: E402 - the core (FAA-65)


def is_share_grant_id(value: Any) -> bool:
    """A share grant's id: urn:fabric:share: and 32 lower-case hex digits, not all zeros, as written."""
    return isinstance(value, str) and SHARE_GRANT_ID.match(value) is not None


def is_org_context(value: Any) -> bool:
    """An organization's context id, org:<orgId>, as written."""
    return isinstance(value, str) and ORG_CONTEXT.match(value) is not None


def _is_org(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("org:")


def share_grant_id_findings(grant: Any, at: str) -> List[Dict[str, str]]:
    """FAC-SEM-117 on one grant: an organization's share grant has a share grant id and a millisecond window."""
    if not isinstance(grant, dict) or not _is_org(grant.get("context")):
        return []
    findings = []
    meta = grant.get("meta")
    if not is_share_grant_id(meta.get("id") if isinstance(meta, dict) else None):
        findings.append(_finding("FAC-SEM-117", "%s/meta/id" % at, "a share grant into an organization is named urn:fabric:share: and 32 lower-case hex digits from a CSPRNG, never a name, an address or an estate id"))
    for name in ("startsAt", "expiresAt"):
        if isinstance(grant.get(name), str) and _SUB_MILLISECOND.search(grant[name]):
            findings.append(_finding("FAC-SEM-117", "%s/%s" % (at, name), "a share grant into an organization carries its window with at most three fraction digits"))
    return findings


def grant_findings(grant: Any, at: str = "") -> List[Dict[str, str]]:
    """Kind ``grant`` as the contract's contextRules answers it: FAC-SEM-110 (DEC-0082), then FAC-SEM-117 (DEC-0086)."""
    return _estate.grant_context_findings(grant, at) + share_grant_id_findings(grant, at)


def _agents_under(record: Dict[str, Any], context: Any, grant_id: Any) -> set:
    """The agentRefs the placements of ``record`` in ``context`` run under the grant ``grant_id`` (by normal form)."""
    placements = [placement for machine in _objects(record.get("machines")) for placement in _objects(machine.get("packages"))]
    return {_jsv.show(placement.get("agentRef", _jsv.MISSING)) for placement in placements
            if _jsv.same(placement.get("context", _jsv.MISSING), context)
            and isinstance(grant_id, str) and _ids.same_identifier(placement.get("grant"), grant_id)}


def org_share_grants_findings(value: Any) -> List[Dict[str, str]]:
    """FAC-SEM-117 on a record ``{record, parent?}``: each organization share grant's id and window, one agentRef among the
    placements naming it, and against ``parent`` (the latest earlier revision that placed it) the same agentRef."""
    value = value if isinstance(value, dict) else {}
    record = value.get("record") if isinstance(value.get("record"), dict) else {}
    parent = value.get("parent") if isinstance(value.get("parent"), dict) else None
    findings: List[Dict[str, str]] = []
    for grant, index in _indexed(record.get("shareGrants")):
        at = "/record/shareGrants/%d" % index
        findings.extend(share_grant_id_findings(grant, at))
        if not _is_org(grant.get("context")):
            continue
        meta = grant.get("meta")
        grant_id = meta.get("id") if isinstance(meta, dict) else None
        refs = _agents_under(record, grant["context"], grant_id)
        if len(refs) > 1:
            findings.append(_finding("FAC-SEM-117", at, "the placements naming this grant run %d agents: a share grant into an organization runs one agentRef" % len(refs)))
        if parent is None:
            continue
        before = next((old for old in _objects(parent.get("shareGrants"))
                       if _jsv.same(old.get("context", _jsv.MISSING), grant["context"]) and isinstance(old.get("meta"), dict)
                       and isinstance(grant_id, str) and _ids.same_identifier(old["meta"].get("id"), grant_id)), None)
        earlier = _agents_under(parent, before.get("context"), grant_id) if before is not None else set()
        if earlier and any(ref not in earlier for ref in refs):
            findings.append(_finding("FAC-SEM-117", at, "this grant ran another agent in the earlier revision given as parent: a share grant into an organization keeps its agentRef; move the share by revoking it and minting a new id"))
    return findings


def _time(value: Any) -> float:
    """An instant as milliseconds, or NaN: the schema's pattern and a day that exists."""
    return _ftime.parse_rfc3339_ms(value) if isinstance(value, str) and _INSTANT.match(value) else float("nan")


def registration_findings(value: Any) -> List[Dict[str, str]]:
    """FAC-SEM-118 on one ``share-registration/1`` document: its instants are readable, an active window ends after it starts."""
    if not isinstance(value, dict) or value.get("type") != SHARE_REGISTRATION_TYPE:
        return []
    names = ("startsAt", "expiresAt") if value.get("state") == "active" else ("withdrawnAt",)
    unreadable = [name for name in names if _time(value.get(name)) != _time(value.get(name))]
    findings = [_finding("FAC-SEM-118", "/%s" % name, "an instant is an RFC 3339 date-time with an offset, on a day that exists, with at most three fraction digits") for name in unreadable]
    if value.get("state") == "active" and not unreadable and _time(value["startsAt"]) >= _time(value["expiresAt"]):
        findings.append(_finding("FAC-SEM-118", "/expiresAt", "an active registration's window ends after it starts"))
    return findings


def grant_usage_context_findings(value: Any) -> List[Dict[str, str]]:
    """FAC-SEM-045's DEC-0086 clause on ``{binding, batch}``: every ``grant.usage`` event's ``data.context`` is ``org:`` and
    the certificate's ``org.id`` as written; another organization's usage is refused as attribution."""
    value = value if isinstance(value, dict) else {}
    binding = value.get("binding") if isinstance(value.get("binding"), dict) else {}
    org = binding["org"].get("id") if isinstance(binding.get("org"), dict) else None
    batch = value.get("batch") if isinstance(value.get("batch"), dict) else {}
    findings = []
    for position, event in enumerate(_objects(batch.get("events"))):  # the index among the objects, as the contract counts it
        if event.get("kind") != "grant.usage":
            continue
        context = event["data"].get("context", _jsv.MISSING) if isinstance(event.get("data"), dict) else _jsv.MISSING
        if not isinstance(org, str) or not isinstance(context, str) or context != "org:" + org:
            findings.append(_finding("FAC-SEM-045", "/batch/events/%d/data/context" % position, "a grant's usage carries its grant's own context, org: and the client certificate's org.id; another organization's is refused as attribution"))
    return findings


def instance_share_grant(record: Any, machine_id: Any, agent_ref: Any, context: Any, at_ms: float) -> Dict[str, Any]:
    """Whether an organization's instance may run on ``machine_id`` now (FAA-125, N-11): the placement of ``agent_ref``
    in ``context`` (as written; absent is personal) among that machine's packages, FAC-SEM-111 on it, and the grant's
    window at ``at_ms`` (``startsAt`` <= at < ``expiresAt``; an unreadable instant or clock is outside it). Answers
    ``{"ok": True, "grant": {"id", "startsAt"?, "expiresAt"?}}`` (``{"ok": True}`` for a personal placement) or ``{"ok": False, "code", "detail"}`` with code
    ``placement-missing``, ``grant-refused`` or ``grant-window``; never raises. It reads the revision it is given, as
    FAC-SEM-111 does: the caller verified it (``verify_estate_record``); a revocation delta is the hub's and the meter's."""
    record = record if isinstance(record, dict) else {}
    machine = next((m for m in _objects(record.get("machines")) if _jsv.same(m.get("id", _jsv.MISSING), machine_id)), {})
    placement = next((p for p in _objects(machine.get("packages"))
                      if _jsv.same(p.get("agentRef", _jsv.MISSING), agent_ref)
                      and _jsv.same(p.get("context", _estate.PERSONAL_CONTEXT), context)), None)
    if placement is None:
        return {"ok": False, "code": "placement-missing", "detail": "this machine places no such agent in that context (FAC-SEM-074)"}
    findings = _estate.placement_grant_findings(record, placement)
    if findings:
        return {"ok": False, "code": "grant-refused", "detail": "; ".join(f["message"] for f in findings)}
    if not isinstance(placement.get("grant"), str):
        return {"ok": True}  # a personal placement, which names no grant
    ident = _ids.normal_identifier(placement["grant"])
    grant = next((g for g in _objects(record.get("shareGrants")) if _jsv.same(g.get("context", _jsv.MISSING), context)
                  and isinstance(g.get("meta"), dict) and isinstance(g["meta"].get("id"), str)
                  and _ids.normal_identifier(g["meta"]["id"]) == ident), None)
    if grant is None:  # defensive: FAC-SEM-111 has already matched one, so this answers rather than raises
        return {"ok": False, "code": "grant-refused", "detail": "the record has no share grant for this placement"}
    answer = {"id": grant["meta"]["id"]}
    for name in ("startsAt", "expiresAt"):
        if name in grant:
            answer[name] = grant[name]
    starts, expires = (_ftime.parse_rfc3339_ms(answer[n]) if n in answer else None for n in ("startsAt", "expiresAt"))
    if (starts is not None and not starts <= at_ms) or (expires is not None and not at_ms < expires):
        return {"ok": False, "code": "grant-window", "detail": "now is outside the share grant's window, or an instant cannot be read"}
    return {"ok": True, "grant": answer}


def share_rules(kind: str, value: Any) -> Optional[List[Dict[str, str]]]:
    """Kinds ``grant`` (FAC-SEM-110, 117), ``org-share-grants`` (117 with parent), ``share-registration`` (118) and
    ``device-attribution`` (045's grant.usage clause only); None for another kind."""
    if kind == "grant":
        return grant_findings(value, "")
    if kind == "org-share-grants":
        return org_share_grants_findings(value)
    if kind == "share-registration":
        return registration_findings(value)
    if kind == "device-attribution":
        return grant_usage_context_findings(value)
    return None
# #endregion share-kit
