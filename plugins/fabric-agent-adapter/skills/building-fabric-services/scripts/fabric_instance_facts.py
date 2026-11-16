# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
"""Who an instance serves, how it keeps data apart and the space it runs in: `fabric-instance-facts/0.1`, the extension
keyed extensions/instance-facts/0.1 (DEC-0173, FAC-SEM-180). Declared by the service, never verified.

`instance_facts(descriptor, well_known)` is the contract's `instanceFacts` (IF-5): each field from the well-known document
where it declares a value no clause of IF-6 refuses, else from the descriptor; a refused value is reported and never
read. `instance_facts_rules(kind, value)` is the contract's `instanceFactsRules` for the kinds `service-descriptor`,
`service-well-known` and `service-observation` (`{descriptor, wellKnown}`). Both never raise. Held to the contract's
`fixtures/vectors/instance-facts.json` (`test/fixtures/contract/instance-facts-vectors.json`). Part of the service kit
(FAA-342, layer L3). Standard library only."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))

from fabric_jsvalue import show  # noqa: E402
from fabric_secrets import secret_argument  # noqa: E402

INSTANCE_FACTS_EXTENSION_KEY = "https://fabric.passioncode.ai/agent-contract/extensions/instance-facts/0.1"
AUDIENCES = ("operator", "organization", "public")
ENTRIES = ("host-signin", "own-signin", "none")
TENANCY_MODES = ("single", "per-organization", "shared")
SPACE_KINDS = ("user", "container", "vm", "system")
# The schema's pattern for the label (ajv reads it with the `u` flag; JavaScript's `$` is the end of input).
_ACCOUNT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")

#: (field, member, name inside the member), in the order the contract reads them.
FIELDS: Tuple[Tuple[str, str, str], ...] = (
    ("audience", "access", "audience"),
    ("entry", "access", "entry"),
    ("mode", "tenancy", "mode"),
    ("kind", "space", "kind"),
    ("account", "space", "account"),
)
_MEMBER_OF = {"audience": "access/audience", "entry": "access/entry", "mode": "tenancy/mode", "kind": "space/kind",
              "account": "space/account"}


def _is_object(value: Any) -> bool:
    return isinstance(value, dict)


def _service_key(value: Dict[str, Any]) -> str:
    """The contract's `serviceKey`: `<id>.<instance>`, an absent (or null) instance read as `default`."""
    instance = value.get("instance")
    ident = show(value["id"]) if "id" in value else "undefined"  # String(undefined), as the contract shows an absent id
    return "%s.%s" % (ident, show("default" if instance is None else instance))


def _answers_as_another(descriptor: Any, well_known: Any) -> bool:
    if not _is_object(descriptor) or not _is_object(well_known):
        return False
    service = well_known.get("service")
    return _service_key(descriptor) != _service_key(service if _is_object(service) else {})


def _member_ok(value: Any, allowed: Dict[str, Tuple[str, ...]], required: Optional[str]) -> bool:
    if not _is_object(value):
        return False
    if required is not None and required not in value:
        return False
    for key, member in value.items():
        if key not in allowed:
            return False
        if key == "account":
            if not isinstance(member, str) or not _ACCOUNT.fullmatch(member):
                return False
        elif not isinstance(member, str) or member not in allowed[key]:
            return False
    return True


def schema_ok(value: Any) -> bool:
    """`service-instance-facts-extension.schema.json` at the pin, by hand: closed objects, the enums, the label's pattern,
    a present tenancy naming its mode and a present space its kind."""
    if not _is_object(value):
        return False
    shapes = {
        "access": ({"audience": AUDIENCES, "entry": ENTRIES}, None),
        "tenancy": ({"mode": TENANCY_MODES}, "mode"),
        "space": ({"kind": SPACE_KINDS, "account": ()}, "kind"),
    }
    for key, member in value.items():
        if key not in shapes or not _member_ok(member, *shapes[key]):
            return False
    return True


def _declared_in(document: Any) -> Tuple[bool, bool, Dict[str, Any]]:
    """(present, valid, the declared fields) of a document's extension value."""
    extensions = document.get("extensions") if _is_object(document) else None
    if not _is_object(extensions) or INSTANCE_FACTS_EXTENSION_KEY not in extensions:
        return False, True, {}
    value = extensions[INSTANCE_FACTS_EXTENSION_KEY]
    if not schema_ok(value):
        return True, False, {}
    values: Dict[str, Any] = {}
    for field, member, name in FIELDS:
        holder = value.get(member)
        if _is_object(holder) and name in holder:
            values[field] = holder[name]
    return True, True, values


def _setting_of(descriptor: Any, well_known: Any) -> Dict[str, bool]:
    setting: Dict[str, bool] = {}
    if _is_object(descriptor):
        setting["peer"] = _is_object(descriptor.get("peer"))
        setting["local"] = descriptor.get("placement") != "remote"  # an absent placement is local (DEC-0019)
        runner = descriptor.get("runner")
        setting["subscription"] = _is_object(runner) and runner.get("credentialKind") == "subscription"
    surfaces = well_known.get("surfaces") if _is_object(well_known) else None
    dashboard = surfaces.get("dashboard") if _is_object(surfaces) else None
    if _is_object(dashboard) and isinstance(dashboard.get("login"), bool):
        setting["login"] = dashboard["login"]
    return setting


def _refusal(field: str, value: Any, document: str, setting: Dict[str, bool]) -> Optional[str]:
    local = setting.get("local") is True
    if field == "audience":
        if value == "operator" and setting.get("peer") is True:
            return "operator beside peer: a service offered to others serves more than its operator"
        if value == "organization" and setting.get("peer") is False and local:
            return ("organization on a local placement needs peer: a host routes others only to a service that declares "
                    "it (DEC-0061)")
        if value == "public" and local:
            return ("public is a remote placement's: a local origin is reached from outside the computer only through peer, "
                    "which no hub routes to anyone at large")
        if value == "public" and setting.get("subscription") is True:
            return ("public beside a subscription runner: a service others reach never runs on the operator's subscription "
                    "(DEC-0046, DEC-0061 item 3)")
    if field == "entry" and "login" in setting and (value == "host-signin") != setting["login"]:
        return ("the dashboard requires a host's login code (surfaces.dashboard.login)" if setting["login"]
                else "the dashboard takes no host's login code (surfaces.dashboard.login is false)")
    if field == "mode" and value == "shared" and local:
        return "shared is a remote service's: a local placement names one context and at most one grant (DEC-0082 item 4)"
    if field == "kind" and value == "system" and local:
        return "system is a remote placement's: a local service runs under a counted OS account (DEC-0154)"
    if field == "account":
        if document == "wellKnown" and local:
            return ("a local service's well-known document is read by every counted OS account on the computer; the label "
                    "stays in its descriptor (IF-4)")
        if isinstance(value, str) and secret_argument(value):
            return "the label is shaped like a credential; it names a space, never a credential"
    return None


def instance_facts(descriptor: Any, given: Any) -> Dict[str, Any]:
    """The reference reading (IF-5). Either document may be None (not read). Never raises."""
    foreign = _answers_as_another(descriptor, given)
    well_known = None if foreign else given
    setting = _setting_of(descriptor, well_known)
    sources = [("wellKnown", _declared_in(well_known)), ("descriptor", _declared_in(descriptor))]
    view: Dict[str, Any] = {"declared": False, "facts": {}, "refused": [], "foreign": foreign,
                            "invalid": [document for document, read in sources if not read[1]]}
    declares_any = any(read[2] for _, read in sources)
    for field, _, _ in FIELDS:
        decided = False
        for document, read in sources:
            if field not in read[2]:
                continue
            value = read[2][field]
            reason = _refusal(field, value, document, setting)
            if reason is not None:
                view["refused"].append({"document": document, "field": field, "reason": reason})
                continue
            if not decided:
                view["facts"][field] = value
            decided = True
    if setting.get("login") is True and declares_any:
        view["facts"]["entry"] = "host-signin"
    view["declared"] = bool(view["facts"])
    return view


def _pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _at(document: Optional[str], field: Optional[str] = None) -> str:
    return "%s/extensions/%s%s" % ("" if document is None else "/" + document, _pointer_token(INSTANCE_FACTS_EXTENSION_KEY),
                                   "" if field is None else "/" + _MEMBER_OF[field])


def instance_facts_rules(kind: str, value: Any) -> List[Dict[str, str]]:
    """FAC-SEM-180 (IF-6) as `{code, instancePath, message}`, per the contract's kinds; [] for any other kind. A finding
    never changes the service's state; the fact it names reads not declared."""
    if not _is_object(value):
        return []
    if kind == "service-descriptor":
        view, prefix = instance_facts(value, None), (lambda document: None)
    elif kind == "service-well-known":
        view, prefix = instance_facts(None, value), (lambda document: None)
    elif kind == "service-observation":
        pair = instance_facts(value.get("descriptor"), value.get("wellKnown"))
        if pair["foreign"]:
            return []
        alone = instance_facts(value.get("descriptor"), None)["refused"] + instance_facts(None, value.get("wellKnown"))["refused"]
        view = dict(pair, invalid=[], refused=[r for r in pair["refused"] if r not in alone])
        prefix = (lambda document: document)
    else:
        return []
    findings = [{"code": "FAC-SEM-180", "instancePath": _at(prefix(document)),
                 "message": "the instance facts fail their schema; a host reads none of them from this document (DEC-0173)"}
                for document in view["invalid"]]
    findings += [{"code": "FAC-SEM-180", "instancePath": _at(prefix(r["document"]), r["field"]),
                  "message": "%s; a host reads this fact as not declared (DEC-0173 IF-6)" % r["reason"]}
                 for r in view["refused"]]
    return findings
