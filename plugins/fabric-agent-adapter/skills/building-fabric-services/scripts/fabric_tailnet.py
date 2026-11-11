#!/usr/bin/env python3
"""Who is calling an agent that sits behind `tailscale serve`, and what that person may open (FAA-297). Standard
library only; the Node twin is fabric-tailnet.mjs, and both answer test/fixtures/tailnet/vectors.json alike.

The agent listens on loopback and `tailscale serve` proxies the tailnet to that listener, adding the caller's
`Tailscale-User-Login`. The header proves nothing by itself: any process on the machine can send it to a loopback port.
So the agent gives serve a listener of its own (a loopback port, or a Unix socket, only serve's backend), and the
header is believed only on that listener and only from a loopback peer. On any other listener (the Fabric one, whose
callers carry the session key) a request that carries the header is refused, never half-trusted.

What a person may open comes from a perimeter file (`tailnet-perimeter/1`) generated from the organization's access
registry, never kept by hand: it names its source (`generatedFrom`), and a perimeter without one is refused. Each
group lists its members' logins, the dashboards and the capabilities they may reach. MCP takes, besides the identity,
a personal key: only its SHA-256 is stored, it belongs to one login, and its capabilities may not be wider than the
groups of that login. Every refusal is 401 or 403 with a stable `code`; no answer echoes a key or a header value
other than the login itself."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

PERIMETER_SCHEMA = "tailnet-perimeter/1"
IDENTITY_HEADER = "tailscale-user-login"
#: Headers tailscale serve sets for a person; on a listener that is not serve's they mark a forged or misrouted call.
SERVE_HEADERS = ("tailscale-user-login", "tailscale-user-name", "tailscale-user-profile-pic")
LISTENER_SERVE = "serve"
SURFACES = ("dashboard", "mcp")

_LOGIN = re.compile(r"^[A-Za-z0-9._%+-]{1,128}@[A-Za-z0-9.-]{1,125}\Z", re.ASCII)
_NAME = re.compile(r"^[a-z][a-z0-9._:/-]{0,127}\Z", re.ASCII)
_KEY_HASH = re.compile(r"^sha256:[0-9a-f]{64}\Z", re.ASCII)
_KEY_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}\Z", re.ASCII)

#: code -> HTTP status. 401: the caller has not proven who it is; 403: it has, and may not.
REFUSALS: Dict[str, int] = {
    "serve-header-off-serve": 403,
    "peer-not-loopback": 403,
    "identity-missing": 401,
    "identity-ambiguous": 401,
    "identity-malformed": 401,
    "not-in-perimeter": 403,
    "dashboard-not-granted": 403,
    "capability-not-granted": 403,
    "key-required": 401,
    "key-unknown": 401,
    "key-not-yours": 403,
    "key-wider-than-group": 403,
}

Headers = Union[Mapping[str, Any], Iterable[Tuple[str, Any]]]


class PerimeterError(ValueError):
    """A perimeter or key list that cannot be used. `code` names why; `where` names the place, never a value."""

    def __init__(self, code: str, where: str = ""):
        self.code = code
        self.where = where
        super().__init__("%s%s" % (code, " at " + where if where else ""))


def hash_key(value: str) -> str:
    """The stored form of a personal key: `sha256:<hex>` of its UTF-8 bytes."""
    if not isinstance(value, str) or not value:
        raise ValueError("a key is a non-empty string")
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _names(value: Any, where: str) -> List[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and _NAME.match(v) for v in value):
        raise PerimeterError("perimeter-invalid", where)
    return sorted(set(value))


def load_perimeter(doc: Any) -> Dict[str, Any]:
    """Check a parsed `tailnet-perimeter/1` document and answer its normalized form; raise PerimeterError otherwise."""
    if not isinstance(doc, dict) or doc.get("schema") != PERIMETER_SCHEMA:
        raise PerimeterError("perimeter-schema", "schema")
    source = doc.get("generatedFrom")
    if not isinstance(source, dict) or not all(isinstance(source.get(k), str) and source.get(k)
                                               for k in ("registry", "revision", "at")):
        raise PerimeterError("perimeter-not-generated", "generatedFrom")
    groups = doc.get("groups")
    if not isinstance(groups, dict) or not groups:
        raise PerimeterError("perimeter-invalid", "groups")
    out: Dict[str, Dict[str, List[str]]] = {}
    for name in sorted(groups):
        group = groups[name]
        where = "groups.%s" % name if _NAME.match(name) else "groups"
        if not _NAME.match(name) or not isinstance(group, dict):
            raise PerimeterError("perimeter-invalid", where)
        members = group.get("members")
        if not isinstance(members, list) or not all(isinstance(m, str) and _LOGIN.match(m) for m in members):
            raise PerimeterError("perimeter-invalid", where + ".members")
        out[name] = {"members": sorted({m.lower() for m in members}),
                     "dashboards": _names(group.get("dashboards", []), where + ".dashboards"),
                     "capabilities": _names(group.get("capabilities", []), where + ".capabilities")}
    return {"schema": PERIMETER_SCHEMA, "generatedFrom": {k: source[k] for k in ("registry", "revision", "at")},
            "groups": out}


def load_keys(keys: Any) -> List[Dict[str, Any]]:
    """Check a list of personal keys `{id, login, sha256, capabilities}` (the hash only, never the key)."""
    if not isinstance(keys, list):
        raise PerimeterError("keys-invalid", "keys")
    out, seen = [], set()
    for i, key in enumerate(keys):
        where = "keys[%d]" % i
        if (not isinstance(key, dict) or not isinstance(key.get("id"), str) or not _KEY_ID.match(key["id"])
                or not isinstance(key.get("login"), str) or not _LOGIN.match(key["login"])
                or not isinstance(key.get("sha256"), str) or not _KEY_HASH.match(key["sha256"])):
            raise PerimeterError("keys-invalid", where)
        if key["id"] in seen or key["sha256"] in {k["sha256"] for k in out}:
            raise PerimeterError("keys-duplicate", where)
        seen.add(key["id"])
        out.append({"id": key["id"], "login": key["login"].lower(), "sha256": key["sha256"],
                    "capabilities": _names(key.get("capabilities", []), where + ".capabilities")})
    return out


def _header_values(headers: Headers, name: str) -> List[str]:
    pairs = headers.items() if isinstance(headers, Mapping) else headers
    found: List[str] = []
    for key, value in pairs:
        if isinstance(key, str) and key.lower() == name:
            found.extend(value if isinstance(value, (list, tuple)) else [value])
    return [v if isinstance(v, str) else "" for v in found]


def _is_loopback(address: Optional[str]) -> bool:
    if address == "unix":  # a Unix socket only serve can reach (the agent sets its mode)
        return True
    if not isinstance(address, str):
        return False
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback


def _refuse(code: str, login: Optional[str] = None) -> Dict[str, Any]:
    return {"allowed": False, "status": REFUSALS[code], "code": code, "login": login, "groups": []}


def _bearer(headers: Headers) -> Optional[str]:
    values = _header_values(headers, "authorization")
    if len(values) != 1:
        return None
    scheme, _, rest = values[0].strip().partition(" ")
    rest = rest.strip()
    return rest if scheme.lower() == "bearer" and rest and " " not in rest else None


def authorize(*, listener: str, peer: Optional[str], headers: Headers, perimeter: Mapping[str, Any], surface: str,
              target: str, keys: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """Decide one request. `listener` is which of the agent's listeners took it (`serve` for serve's own); `peer` the
    connecting address (`unix` for a Unix socket); `perimeter` and `keys` as load_perimeter and load_keys answer;
    `surface` `dashboard` or `mcp`; `target` the dashboard's or the capability's name. Answers
    {allowed, status, code, login, groups}: status 200 with code `ok`, else 401 or 403 with the refusal's code."""
    if surface not in SURFACES:
        raise ValueError("surface is one of %s" % ", ".join(SURFACES))
    if listener != LISTENER_SERVE:
        if any(_header_values(headers, h) for h in SERVE_HEADERS):
            return _refuse("serve-header-off-serve")
        raise ValueError("authorize decides serve's listener; the Fabric listener keeps its session key")
    if not _is_loopback(peer):
        return _refuse("peer-not-loopback")
    logins = _header_values(headers, IDENTITY_HEADER)
    if not logins:
        return _refuse("identity-missing")
    if len(logins) > 1:
        return _refuse("identity-ambiguous")
    login = logins[0].strip()
    if not _LOGIN.match(login):
        return _refuse("identity-malformed")
    login = login.lower()
    groups = sorted(name for name, g in perimeter["groups"].items() if login in g["members"])
    if not groups:
        return _refuse("not-in-perimeter", login)
    reach = {"dashboard": set(), "mcp": set()}
    for name in groups:
        reach["dashboard"].update(perimeter["groups"][name]["dashboards"])
        reach["mcp"].update(perimeter["groups"][name]["capabilities"])
    if surface == "dashboard":
        if target not in reach["dashboard"]:
            return dict(_refuse("dashboard-not-granted", login), groups=groups)
        return {"allowed": True, "status": 200, "code": "ok", "login": login, "groups": groups}
    presented = _bearer(headers)
    if presented is None:
        return dict(_refuse("key-required", login), groups=groups)
    digest = hash_key(presented)
    key = next((k for k in keys or () if hmac.compare_digest(k["sha256"], digest)), None)
    if key is None:
        return dict(_refuse("key-unknown", login), groups=groups)
    if key["login"] != login:
        return dict(_refuse("key-not-yours", login), groups=groups)
    if not set(key["capabilities"]) <= reach["mcp"]:
        return dict(_refuse("key-wider-than-group", login), groups=groups)
    if target not in key["capabilities"]:
        return dict(_refuse("capability-not-granted", login), groups=groups)
    return {"allowed": True, "status": 200, "code": "ok", "login": login, "groups": groups, "key": key["id"]}
