"""Protocol revisions (DEC-0067) and an event's machine-readable data (DEC-0070, the feed-data protocols): parse,
accept, negotiate and check them. Part of the service kit (FAA-65, layer L3)."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple
import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))


#: Each contract protocol's published revisions, oldest first (the contract's `PROTOCOL_REVISIONS`, DEC-0067); a test
#: holds it equal to the contract's register at the pin.
PROTOCOL_REVISIONS: Dict[str, Tuple[str, ...]] = {
    "access-log": ("1",), "approval": ("1",), "activity-summary": ("1",), "agent-directory": ("1",), "call-record": ("1",), "coding-agents": ("1",), "credential-decision": ("1",), "credential-request": ("1",), "credential-revocation": ("1",), "enroll-token": ("1",), "entitlement": ("1",),
    "entitlement-key-set": ("1",), "estate-record": ("1",), "execution-packet": ("1",),
    "fabric-actions": ("0.1",), "fabric-activity": ("0.1",), "fabric-agent-call": ("1",), "fabric-connections": ("0.1",), "fabric-credential-envelope": ("1",), "fabric-load": ("0.1",), "fabric-dashboard": ("0.1",), "fabric-delegation": ("0.1",), "fabric-device": ("0.1",),
    "fabric-interop": ("0.1", "0.2"), "fabric-local-channel": ("0.1",), "fabric-local-runner": ("0.1",), "fabric-machine-report": ("1",),
    "fabric-operator-channel": ("0.1",), "fabric-package": ("1",), "fabric-project-comms": ("0.1",), "fabric-proposal": ("1",),
    "fabric-provider": ("0.1",), "fabric-relay": ("0.1",), "fabric-secret-envelope": ("1",), "fabric-service": ("0.1",),
    "fabric-settings-backup": ("1",), "heartbeat": ("1",), "learning-note": ("1",), "machine-report": ("1",), "mandate": ("1",), "memory": ("0.1",), "node-summary": ("1",),
    "operator-source": ("1",), "org-authority": ("1",), "org-authority-draft": ("1",), "org-key-set": ("1",), "org-key-set-draft": ("1",),
    "org-membership": ("1",), "org-root-registration": ("1",), "pairing-message": ("1",),
    "pipeline": ("0.1",), "repair-request": ("1",), "repair-result": ("1",), "revocation-delta": ("1",), "session-handoff": ("1",), "service-load": ("1",), "share-registration": ("1",),
    "share-registration-receipt": ("1",), "support-quality-daily": ("1",), "window-lease": ("1",),
}


MAX_PROTOCOLS = 64


_REVISION = re.compile(r"([a-z][a-z0-9.-]{0,63})/([0-9]{1,4}(?:\.[0-9]{1,4}){0,2})", re.ASCII)


def parse_revision(value: Any) -> Optional[Tuple[str, str]]:
    """`<name>/<revision>` split, or None."""
    match = _REVISION.fullmatch(value) if isinstance(value, str) else None
    return (match.group(1), match.group(2)) if match else None


def accepted_revisions(name: str, newest: Optional[str] = None) -> List[str]:
    """The revisions a receiver implementing ``name`` up to ``newest`` accepts: N and, when the register has one, N−1."""
    known = PROTOCOL_REVISIONS.get(name, ())
    if not known:
        return []
    top = len(known) - 1 if newest is None else (known.index(newest) if newest in known else -1)
    if top < 0:
        return []
    return ["%s/%s" % (name, r) for r in reversed(known[max(0, top - 1):top + 1])]


def negotiate_revision(received: Any, accepted: Sequence[Any]) -> Dict[str, Any]:
    """A receiver's answer to a document naming ``received`` (DEC-0067, the contract's `negotiateRevision`):
    ``{"ok": True}``; the `schema-unsupported` refusal naming what was received (at most 80 characters) and the accepted
    revisions of that protocol (all of them when it names none the receiver reads); or ``{"fault":
    "no-accepted-revisions"}``, the receiver's own, when it accepts no well-formed revision. Revisions compare exactly."""
    usable: List[str] = []
    for entry in accepted if isinstance(accepted, (list, tuple)) else []:
        if parse_revision(entry) and entry not in usable:
            usable.append(entry)
    usable = usable[:MAX_PROTOCOLS]
    if not usable:
        return {"fault": "no-accepted-revisions"}
    if isinstance(received, str) and received in usable:
        return {"ok": True}
    parsed = parse_revision(received)
    same = [e for e in usable if parsed and parse_revision(e)[0] == parsed[0]]
    return {"error": {"code": "schema-unsupported", "message": "this receiver does not read that protocol revision",
                      "data": {"protocol": received[:80] if isinstance(received, str) else "", "accepted": same or usable}}}


def protocols_findings(protocols: Any, prefix: str = "/protocols") -> List[Dict[str, str]]:
    """FAC-SEM-099 (DEC-0067): 1 to 64 entries, each `<name>/<revision>` once; at most two revisions of one protocol (an
    unpublished one refused and not counted), and two of a contract protocol are N and N−1, consecutive in the register."""
    flag = lambda at, message: {"code": "FAC-SEM-099", "instancePath": at, "message": message}  # noqa: E731
    if not isinstance(protocols, list):
        return [flag(prefix, "protocols is a list of protocol revisions")]
    if not 1 <= len(protocols) <= MAX_PROTOCOLS:
        return [flag(prefix, "protocols lists 1 to %d revisions" % MAX_PROTOCOLS)]
    findings: List[Dict[str, str]] = []
    by_name: Dict[str, List[int]] = {}
    seen: List[str] = []
    for i, entry in enumerate(protocols):
        at = "%s/%d" % (prefix, i)
        parsed = parse_revision(entry)
        if not parsed:
            findings.append(flag(at, "a protocol revision is <name>/<revision>, such as fabric-service/0.1"))
            continue
        if entry in seen:
            findings.append(flag(at, "each protocol revision once"))
            continue
        seen.append(entry)
        known = PROTOCOL_REVISIONS.get(parsed[0])
        if known and parsed[1] not in known:
            findings.append(flag(at, "%s has no published revision %s" % parsed))
            continue
        indices = by_name.setdefault(parsed[0], [])
        indices.append(known.index(parsed[1]) if known else -1)
        if len(indices) > 2:
            findings.append(flag(at, "at most 2 revisions of one protocol: N and N−1"))
        elif known and len(indices) == 2 and abs(indices[0] - indices[1]) != 1:
            findings.append(flag(at, "two revisions of one protocol are N and N−1, consecutive in the register"))
    return findings


_SCHEMA_URI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:[^\s]+", re.ASCII)


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float)) or (isinstance(value, str) and len(value) <= 500)


def _too_deep(key: str, member: Any) -> str:
    """The first place under a member that breaks the bound, for the refusal (FAA-122): `cited[0]` nests an object."""
    if isinstance(member, (list, dict)) and len(member) > 32:
        return ": it has %d entries" % len(member)
    for inner, leaf in (enumerate(member) if isinstance(member, list) else member.items() if isinstance(member, dict) else ()):
        if not _scalar(leaf):
            place = "%s[%d]" % (key, inner) if isinstance(member, list) else "%s.%s" % (key, inner)
            what = "a string over 500 characters" if isinstance(leaf, str) else "a list" if isinstance(leaf, list) else \
                "an object" if isinstance(leaf, dict) else "not a scalar"
            return ": data.value.%s is %s; nest two levels at most (flatten it into lists or members of their own)" % (place, what)
    return ""


def feed_data_problems(data: Any) -> List[str]:
    """DEC-0070's `data {schema, value}` as the schema bounds it, then FAC-SEM-101: no string in `value`, at either
    level, under a credential's name or of a credential's shape (named by its place, never its value)."""
    import fabric_secrets  # noqa: E402 - beside this file; the contract's detector
    if not isinstance(data, dict) or set(data) != {"schema", "value"}:
        return ["data is {schema, value}"]
    problems: List[str] = []
    if not (isinstance(data["schema"], str) and _SCHEMA_URI.fullmatch(data["schema"])):
        problems.append("data.schema is the absolute URI of a payload schema the service publishes")
    value = data["value"]
    if not isinstance(value, dict) or len(value) > 32:
        return problems + ["data.value is an object of at most 32 members"]
    for key, member in value.items():
        if _scalar(member):
            continue
        if isinstance(member, list) and len(member) <= 32 and all(_scalar(m) for m in member):
            continue
        if isinstance(member, dict) and len(member) <= 32 and all(_scalar(m) for m in member.values()):
            continue
        problems.append("data.value.%s is a scalar (a string of at most 500 characters), a list of at most 32 scalars or an object of at most 32 scalar members%s"
                        % (key, _too_deep(key, member)))
    if problems:
        return problems
    for finding in feed_data_findings({"events": [{"data": data}]}):
        problems.append("FAC-SEM-101: %s %s" % (finding["instancePath"].replace("/events/0", ""), finding["message"]))
    return problems


def _pointer_token(name: str) -> str:
    return str(name).replace("~", "~0").replace("/", "~1")


def feed_data_findings(page: Any) -> List[Dict[str, str]]:
    """FAC-SEM-101 over an events page (the contract's `feedDataFindings`): a list's items and an object's members sit
    under the outer name too; a number is a count, never a credential."""
    import fabric_secrets  # noqa: E402
    findings: List[Dict[str, str]] = []

    def check(named: bool, member: Any, at: str) -> None:
        if not isinstance(member, str):
            return
        if named:
            findings.append({"code": "FAC-SEM-101", "instancePath": at, "message": "an event's data puts no string under a credential's name"})
        elif fabric_secrets.secret_value(member) or fabric_secrets.secret_url(member):
            findings.append({"code": "FAC-SEM-101", "instancePath": at, "message": "an event's data carries no value shaped like a credential"})

    events = page.get("events") if isinstance(page, dict) else None
    for i, event in enumerate(events if isinstance(events, list) else []):
        data = event.get("data") if isinstance(event, dict) else None
        value = data.get("value") if isinstance(data, dict) else None
        if not isinstance(value, dict):
            continue
        for key, member in value.items():
            at = "/events/%d/data/value/%s" % (i, _pointer_token(key))
            named = fabric_secrets.credential_name(key)
            check(named, member, at)
            if isinstance(member, list):
                for j, item in enumerate(member):
                    check(named, item, "%s/%d" % (at, j))
            elif isinstance(member, dict):
                for inner, leaf in member.items():
                    check(named or fabric_secrets.credential_name(inner), leaf, "%s/%s" % (at, _pointer_token(inner)))
    return findings
