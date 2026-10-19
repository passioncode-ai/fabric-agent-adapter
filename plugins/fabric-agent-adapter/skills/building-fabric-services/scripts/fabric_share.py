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


def _indexed(value: Any) -> List[Any]:
    """The object items of a list with their index as written, so an instancePath names the item after a non-object."""
    return [(item, index) for index, item in enumerate(value) if isinstance(item, dict)] if isinstance(value, list) else []


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
    return {_estate._show(placement.get("agentRef", _estate._MISSING)) for placement in placements
            if _estate._same(placement.get("context", _estate._MISSING), context)
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
                       if _estate._same(old.get("context", _estate._MISSING), grant["context"]) and isinstance(old.get("meta"), dict)
                       and isinstance(grant_id, str) and _ids.same_identifier(old["meta"].get("id"), grant_id)), None)
        earlier = _agents_under(parent, before.get("context"), grant_id) if before is not None else set()
        if earlier and any(ref not in earlier for ref in refs):
            findings.append(_finding("FAC-SEM-117", at, "this grant ran another agent in the earlier revision given as parent: a share grant into an organization keeps its agentRef; move the share by revoking it and minting a new id"))
    return findings


def _time(value: Any) -> float:
    """An instant as milliseconds, or NaN: the schema's pattern and a day that exists."""
    return _estate.estate_time(value) if isinstance(value, str) and _INSTANT.match(value) else float("nan")


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
        context = event["data"].get("context", _estate._MISSING) if isinstance(event.get("data"), dict) else _estate._MISSING
        if not isinstance(org, str) or not isinstance(context, str) or context != "org:" + org:
            findings.append(_finding("FAC-SEM-045", "/batch/events/%d/data/context" % position, "a grant's usage carries its grant's own context, org: and the client certificate's org.id; another organization's is refused as attribution"))
    return findings


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
