#!/usr/bin/env python3
"""A person's identity at every door of a service published through `tailscale serve` (FAA-324). Standard library
only; the Node twin is fabric-tailnet-identity.mjs, and both answer test/fixtures/tailnet-identity/vectors.json alike.

`tailscale serve` proxies HTTPS on the node's tailnet name to the service's loopback listener and sets the caller's
`Tailscale-User-Login` (and `Tailscale-User-Name`, read here for display only). What Tailscale documents
(https://tailscale.com/kb/1312/serve, "Identity headers", read 2026-11-12) and its source shows
(tailscale/tailscale `ipn/ipnlocal/serve.go`, `addTailscaleIdentityHeaders` and `delHeaderVariants`):

- Serve removes any incoming `Tailscale-User-Login`, `Tailscale-User-Name`, `Tailscale-User-Profile-Pic`,
  `Tailscale-Funnel-Request` and `Tailscale-Headers-Info` (also their `_` spellings) before it sets its own, so a
  tailnet client cannot forge them through serve.
- It sets no identity header for a tagged node, for Funnel traffic (it sets `Tailscale-Funnel-Request: ?1` instead)
  or for traffic it cannot attribute; it always sets `X-Forwarded-For` to the source address.
- Its documentation advises the backend to listen on localhost only: a backend reachable directly lets any caller
  supply its own values.

So the header is believed only when the service listens on a loopback address and the request's peer is a loopback
address (it came through the local serve proxy). A service bound to another address, or a request from another
peer, is refused: there the header comes from the network and is forgeable. What this does not stop: another
process of this machine can send the header to the loopback port. The kit's `LoopbackHTTPServer` refuses another OS
account's peer (DEC-0154, FAA-227); a process of the service's own account is trusted as the service is. Where that
matters, give serve a listener of its own (`fabric_tailnet`, FAA-297).

No request is let through by default. A request without a login (a tagged node's, a Funnel request's, a direct
call's), with an empty, repeated or malformed one, or from a login no rule opens the door for, is refused with a
stable code and a sentence, and every refusal is HTTP 403. What a login may open comes from a groups file the
organization writes (`tailnet-groups/1`, its JSON Schema `tailnet-groups.schema.json` beside this file):

    {"schema": "tailnet-groups/1",
     "groups": {"ops": ["ana@example.com"]},
     "rules": [{"group": "ops", "door": "dashboard", "capabilities": "*"}]}

The agents base's `door-groups/1` file is read as well, for one service (`service=`, the service's id): its
groups name `people` and, per service, the doors and tools they open (`*` every door, `dashboard`, `mcp` every MCP
tool, or a tool name, opened at the MCP door and at the service's own door); a retired group opens nothing, and
without a service every door stays closed.

Logins are compared as ASCII email-style names lowercased whole (local part and domain alike), after trimming the
spaces and tabs HTTP allows around a header value; nothing else is changed (no dot or `+tag` folding, no IDN
mapping), and a login that is not plain ASCII (serve RFC 2047-encodes a non-ASCII one) is refused as malformed.
`TailnetIdentity` reads the file again when its inode, size, mtime or ctime change (and, while its mtime is under two
seconds old, when its bytes do: a same-size rewrite within one timestamp tick), without a restart, and while it
is unreadable or invalid every door refuses (`groups-unreadable`, `groups-invalid`); the reason is logged once per
change, naming the field, never the file's content."""

from __future__ import annotations

import errno
import hashlib
import ipaddress
import json
import os
import re
import stat
import sys
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple, Union

GROUPS_SCHEMA = "tailnet-groups/1"
DOOR_GROUPS = "door-groups/1"  # the agents base's format (thread d23eeb7a), read for one service
DOORS = ("dashboard", "mcp", "service")
LOGIN_HEADER = "tailscale-user-login"
NAME_HEADER = "tailscale-user-name"
FUNNEL_HEADER = "tailscale-funnel-request"
#: The largest groups file read; a larger one is invalid.
MAX_GROUPS_BYTES = 1048576
# A file whose stat is unchanged but whose mtime is this close to now may have been rewritten within one timestamp tick
# (same size, coarse clock): its content is read and compared (git's racy-clean rule).
RACY_NS = 2_000_000_000

#: The patterns as the JSON Schema writes them (ECMAScript); compiled below to end at the end of the string.
LOGIN_PATTERN = "^[A-Za-z0-9._%+-]{1,128}@[A-Za-z0-9.-]{1,125}$"
NAME_PATTERN = "^[a-z][a-z0-9._:/-]{0,127}$"
_LOGIN = re.compile(LOGIN_PATTERN[:-1] + r"\Z", re.ASCII)
_NAME = re.compile(NAME_PATTERN[:-1] + r"\Z", re.ASCII)
_TAILNET = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))
_ENCODED_WORD = re.compile(r"=\?utf-8\?q\?([^?]*)\?=\Z", re.ASCII | re.IGNORECASE)

#: code -> HTTP status: every refusal is 403.
REFUSALS: Dict[str, int] = {code: 403 for code in (
    "bind-not-loopback", "not-loopback", "groups-unreadable", "groups-invalid", "funnel-request", "no-login",
    "tagged-node", "login-ambiguous", "login-malformed", "unknown-login", "not-allowed")}

#: code -> the sentence a person reads; the twins carry the same text.
REASONS: Dict[str, str] = {
    "ok": "Allowed by a rule of a group this login belongs to.",
    "bind-not-loopback": "The service does not listen on a loopback address only, so a Tailscale identity header "
                         "could come from the network and is not believed.",
    "not-loopback": "The request did not come from the local tailscale serve proxy (its peer is not a loopback "
                    "address), so its Tailscale identity header is not believed.",
    "groups-unreadable": "The tailnet groups file cannot be read, so every door stays closed until it can.",
    "groups-invalid": "The tailnet groups file is not a valid tailnet-groups/1 or door-groups/1 document, so every door stays closed "
                      "until it is fixed.",
    "funnel-request": "The request came through Tailscale Funnel from the public internet, which carries no tailnet "
                      "identity.",
    "no-login": "The request carries no Tailscale-User-Login header, so the caller is not known.",
    "tagged-node": "The request came through tailscale serve from a tailnet node with no user (a tagged node), which "
                   "carries no login.",
    "login-ambiguous": "The request carries more than one Tailscale-User-Login header.",
    "login-malformed": "The Tailscale-User-Login header is not a login name.",
    "unknown-login": "This login is in no group of the tailnet groups file.",
    "not-allowed": "No group of this login has a rule that opens this door for this capability.",
}

Headers = Union[Mapping[str, Any], Iterable[Tuple[str, Any]], Any]


class GroupsError(ValueError):
    """A groups file that cannot be used. `code` is `groups-invalid` or `groups-unreadable`; `where` names the field
    (or the reason the file could not be read), never a value from the file."""

    def __init__(self, code: str, where: str = ""):
        self.code = code
        self.where = where
        super().__init__("%s%s" % (code, " at " + where if where else ""))


def _invalid(where: str) -> GroupsError:
    return GroupsError("groups-invalid", where)


def load_groups(doc: Any, service: Optional[str] = None) -> Dict[str, Any]:
    """Check a parsed `tailnet-groups/1` or `door-groups/1` document; answer it normalized (logins lowercased and
    sorted, each group's members once, the rules) or raise GroupsError `groups-invalid` naming the field. A
    `door-groups/1` file is read for one `service` (its id): without one every door stays closed."""
    if not isinstance(doc, dict):
        raise _invalid("document")
    if "format" in doc and "schema" not in doc:
        if doc["format"] != DOOR_GROUPS:
            raise _invalid("format")
        return _load_door_groups(doc, service)
    if doc.get("schema") != GROUPS_SCHEMA:
        raise _invalid("schema")
    if set(doc) - {"schema", "about", "groups", "rules"}:
        raise _invalid("document")
    if "about" in doc and (not isinstance(doc["about"], str) or len(doc["about"]) > 1000):
        raise _invalid("about")
    groups = doc.get("groups")
    if not isinstance(groups, dict) or not all(isinstance(n, str) and _NAME.match(n) for n in groups):
        raise _invalid("groups")
    out: Dict[str, List[str]] = {}
    for name in sorted(groups):
        members = groups[name]
        if not isinstance(members, list) or not all(isinstance(m, str) and _LOGIN.match(m) for m in members):
            raise _invalid("groups.%s" % name)
        out[name] = sorted({m.lower() for m in members})
    rules = doc.get("rules")
    if not isinstance(rules, list):
        raise _invalid("rules")
    norm: List[Dict[str, Any]] = []
    for i, rule in enumerate(rules):
        where = "rules[%d]" % i
        if not isinstance(rule, dict) or set(rule) != {"group", "door", "capabilities"}:
            raise _invalid(where)
        if not isinstance(rule["group"], str) or rule["group"] not in out:
            raise _invalid(where + ".group")
        if rule["door"] not in DOORS:
            raise _invalid(where + ".door")
        caps = rule["capabilities"]
        if caps != "*" and (not isinstance(caps, list) or not caps
                            or not all(isinstance(c, str) and _NAME.match(c) for c in caps)):
            raise _invalid(where + ".capabilities")
        norm.append({"group": rule["group"], "door": rule["door"],
                     "capabilities": "*" if caps == "*" else sorted(set(caps))})
    return {"schema": GROUPS_SCHEMA, "groups": out, "rules": norm}


def _values(headers: Headers, name: str) -> List[str]:
    """Every value of one header, case-insensitively, from a parsed message (`get_all`), a mapping whose values may
    be lists, or pairs."""
    if hasattr(headers, "get_all") and hasattr(headers, "items"):
        found: List[Any] = list(headers.get_all(name) or [])
    else:
        pairs = headers.items() if isinstance(headers, Mapping) else headers
        found = []
        for key, value in pairs:
            if isinstance(key, str) and key.lower() == name:
                found.extend(value if isinstance(value, (list, tuple)) else [value])
    return [v if isinstance(v, str) else "" for v in found]


def _address(text: Any) -> Optional[Any]:
    if not isinstance(text, str):
        return None
    try:
        ip = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _is_loopback(text: Any) -> bool:
    ip = _address(text)
    return ip is not None and ip.is_loopback


def _from_tailnet(values: List[str]) -> bool:
    """One X-Forwarded-For value that is a Tailscale address (100.64.0.0/10, fd7a:115c:a1e0::/48): serve set it."""
    if len(values) != 1:
        return False
    ip = _address(values[0].strip(" \t"))
    return ip is not None and any(ip.version == net.version and ip in net for net in _TAILNET)


def _display_name(values: List[str]) -> Optional[str]:
    """`Tailscale-User-Name` for display: ASCII as sent, or serve's RFC 2047 `=?utf-8?q?...?=` words decoded; None
    when absent, repeated, over 256 characters or holding a control character."""
    if len(values) != 1:
        return None
    text = values[0].strip(" \t")
    if any(ord(c) > 126 for c in text):
        return None
    if text.startswith("=?"):
        raw = b""
        for word in text.split(" "):
            match = _ENCODED_WORD.match(word)
            if match is None:
                return None
            encoded, i = match.group(1), 0
            while i < len(encoded):
                if encoded[i] == "=":
                    pair = encoded[i + 1:i + 3]
                    if len(pair) != 2 or not all(c in "0123456789abcdefABCDEF" for c in pair):
                        return None
                    raw += bytes([int(pair, 16)])
                    i += 3
                else:
                    raw += b" " if encoded[i] == "_" else encoded[i].encode("ascii")
                    i += 1
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not text or len(text) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in text):
        return None
    return text


def _load_door_groups(doc: Dict[str, Any], service: Optional[str]) -> Dict[str, Any]:
    """`door-groups/1` (the agents base): {format, version, generated_at?, groups: {name: {people, doors: {service:
    [capability]}}}, retired?: {name: {at, why}}}. For `service`: `*` opens every door, `dashboard` the dashboard,
    `mcp` every MCP tool, any other name that capability at the MCP door and at the service's own door; a group with
    no entry for the service, and a retired group, open nothing."""
    if not isinstance(service, str) or not service:
        raise _invalid("service")
    if set(doc) - {"format", "version", "generated_at", "groups", "retired"}:
        raise _invalid("document")
    version = doc.get("version")
    if isinstance(version, float) and version.is_integer():  # JSON's 3.0 is JavaScript's 3, as the Node twin reads it
        version = int(version)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise _invalid("version")
    if doc.get("generated_at") is not None and (not isinstance(doc["generated_at"], str) or len(doc["generated_at"]) > 64):
        raise _invalid("generated_at")
    groups = doc.get("groups")
    if not isinstance(groups, dict) or not all(isinstance(n, str) and _NAME.match(n) for n in groups):
        raise _invalid("groups")
    retired = doc.get("retired", {})
    if not isinstance(retired, dict) or not all(isinstance(n, str) and _NAME.match(n) for n in retired):
        raise _invalid("retired")
    for name in sorted(retired):
        entry = retired[name]
        if name in groups:
            raise _invalid("retired.%s" % name)
        if not isinstance(entry, dict) or set(entry) - {"at", "why"} or not all(
                v is None or (isinstance(v, str) and len(v) <= 1000) for v in entry.values()):
            raise _invalid("retired.%s" % name)
    people: Dict[str, List[str]] = {}
    rules: List[Dict[str, Any]] = []
    for name in sorted(groups):
        group = groups[name]
        if not isinstance(group, dict) or set(group) != {"people", "doors"}:
            raise _invalid("groups.%s" % name)
        members = group["people"]
        if not isinstance(members, list) or not all(isinstance(m, str) and _LOGIN.match(m) for m in members):
            raise _invalid("groups.%s.people" % name)
        doors = group["doors"]
        if not isinstance(doors, dict) or not all(isinstance(k, str) and k for k in doors):
            raise _invalid("groups.%s.doors" % name)
        for key in sorted(doors):
            caps = doors[key]
            if not isinstance(caps, list) or not caps or not all(
                    isinstance(c, str) and (c == "*" or _NAME.match(c)) for c in caps):
                raise _invalid("groups.%s.doors.%s" % (name, key))
        people[name] = sorted({m.lower() for m in members})
        caps = set(doors.get(service) or [])
        tools = sorted(caps - {"*", "dashboard", "mcp"})
        opened = {"dashboard": "*" if caps & {"*", "dashboard"} else None,
                  "mcp": "*" if caps & {"*", "mcp"} else (tools or None),
                  "service": "*" if "*" in caps else (tools or None)}
        rules.extend({"group": name, "door": door, "capabilities": opened[door]} for door in DOORS if opened[door])
    return {"schema": DOOR_GROUPS, "groups": people, "rules": rules}


def _decision(code: str, door: str, capability: str, login: Optional[str] = None, name: Optional[str] = None,
              groups: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"allowed": code == "ok", "status": 200 if code == "ok" else REFUSALS[code], "code": code,
            "reason": REASONS[code], "login": login, "name": name, "groups": list(groups or []), "door": door,
            "capability": capability}


def decide(*, groups: Union[Mapping[str, Any], GroupsError], bound: Any, peer: Any, headers: Headers, door: str,
           capability: str) -> Dict[str, Any]:
    """Decide one request. `groups` is what load_groups answered, or the GroupsError that keeps every door closed;
    `bound` the address the service listens on; `peer` the connection's remote address; `door` one of DOORS;
    `capability` the name the service asks for (a page, a tool, an action). Answers {allowed, status, code, reason,
    login, name, groups, door, capability}: 200 `ok`, else 403 with the refusal's code. Never raises for a request;
    a door or capability outside the rules' grammar is the service's mistake and raises ValueError."""
    if door not in DOORS:
        raise ValueError("door is one of %s" % ", ".join(DOORS))
    if not isinstance(capability, str) or not _NAME.match(capability):
        raise ValueError("capability is a name matching %s" % NAME_PATTERN)
    if not _is_loopback(bound):
        return _decision("bind-not-loopback", door, capability)
    if not _is_loopback(peer):
        return _decision("not-loopback", door, capability)
    if isinstance(groups, GroupsError):
        return _decision(groups.code if groups.code in REFUSALS else "groups-invalid", door, capability)
    if _values(headers, FUNNEL_HEADER):
        return _decision("funnel-request", door, capability)
    logins = [v.strip(" \t") for v in _values(headers, LOGIN_HEADER)]
    logins = [v for v in logins if v]
    if not logins:
        code = "tagged-node" if _from_tailnet(_values(headers, "x-forwarded-for")) else "no-login"
        return _decision(code, door, capability)
    if len(logins) > 1:
        return _decision("login-ambiguous", door, capability)
    if not _LOGIN.match(logins[0]):
        return _decision("login-malformed", door, capability)
    login = logins[0].lower()
    name = _display_name(_values(headers, NAME_HEADER))
    member_of = sorted(g for g, members in groups["groups"].items() if login in members)
    if not member_of:
        return _decision("unknown-login", door, capability, login, name)
    for rule in groups["rules"]:
        if rule["group"] in member_of and rule["door"] == door and (
                rule["capabilities"] == "*" or capability in rule["capabilities"]):
            return _decision("ok", door, capability, login, name, member_of)
    return _decision("not-allowed", door, capability, login, name, member_of)


def refusal_body(decision: Mapping[str, Any]) -> Dict[str, Any]:
    """The JSON body of a refusal: {"error": {"code", "message"}}; never a header value or a login."""
    if decision.get("allowed") or decision.get("code") not in REFUSALS:
        raise ValueError("refusal_body takes a refused decision")
    return {"error": {"code": decision["code"], "message": REASONS[decision["code"]]}}


def send_refusal(handler: Any, decision: Mapping[str, Any]) -> None:
    """Answer a refused decision on an http.server handler: 403, JSON, no-store."""
    body = json.dumps(refusal_body(decision)).encode("utf-8")
    handler.send_response(REFUSALS[decision["code"]])
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)


def _errno_name(exc: OSError) -> str:
    """The error's symbolic name (ENOENT, EACCES), as Node names it; never its message, which may hold the path."""
    return errno.errorcode.get(exc.errno or 0, "unknown")


def _stderr(line: str) -> None:
    sys.stderr.write(line + "\n")


class TailnetIdentity:
    """The groups file at `path`, read again when it changes, and the decision at a door. `recheck_seconds` 0 looks
    at the file on every request (one stat); a positive value at most that often. `log` takes one line per change of
    the file's state (default stderr); `clock` gives monotonic seconds (a test replaces it)."""

    def __init__(self, path: Union[str, "os.PathLike[str]"], *, recheck_seconds: float = 0.0,
                 log: Optional[Callable[[str], None]] = None, clock: Callable[[], float] = time.monotonic,
                 service: Optional[str] = None) -> None:
        if not isinstance(recheck_seconds, (int, float)) or recheck_seconds < 0:
            raise ValueError("recheck_seconds is a number of seconds, 0 or more")
        self.path = os.fspath(path)
        self.service = service  # the service's id: the entry a door-groups/1 file is read for
        self.recheck_seconds = float(recheck_seconds)
        self._log = log or _stderr
        self._clock = clock
        self._lock = threading.Lock()
        self._signature: Any = object()  # nothing read yet
        self._digest: Optional[str] = None  # sha256 of the bytes last read
        self._groups: Union[Dict[str, Any], GroupsError] = GroupsError("groups-unreadable", "not read")
        self._checked: Optional[float] = None
        self._logged: Any = None

    def _stat(self) -> Tuple[Any, ...]:
        try:
            st = os.stat(self.path)
        except OSError as exc:
            return ("error", _errno_name(exc))
        if not stat.S_ISREG(st.st_mode):
            return ("error", "not-a-file")
        return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)

    def _read(self) -> Union[Dict[str, Any], GroupsError]:
        try:
            with open(self.path, "rb") as handle:
                data = handle.read(MAX_GROUPS_BYTES + 1)
        except OSError as exc:
            self._digest = None
            return GroupsError("groups-unreadable", _errno_name(exc))
        self._digest = hashlib.sha256(data).hexdigest()
        if len(data) > MAX_GROUPS_BYTES:
            return _invalid("size")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return _invalid("encoding")

        def no_constant(_name: str) -> Any:
            raise ValueError("not JSON")

        try:
            doc = json.loads(text, parse_constant=no_constant)
        except ValueError:
            return _invalid("json")
        try:
            return load_groups(doc, self.service)
        except GroupsError as exc:
            return exc

    def current(self) -> Union[Dict[str, Any], GroupsError]:
        """The groups in force: the normalized file, or the GroupsError that keeps every door closed."""
        with self._lock:
            now = self._clock()
            if self._checked is not None and self.recheck_seconds and now - self._checked < self.recheck_seconds:
                return self._groups
            self._checked = now
            signature = self._stat()
            if signature == self._signature and signature[0] != "error" and self._rewritten_in_place(signature):
                self._signature = object()
            if signature != self._signature:
                self._signature = signature
                self._groups = (GroupsError("groups-unreadable", signature[1])
                                if signature[0] == "error" else self._read())
                self._report(signature)
            return self._groups

    def _rewritten_in_place(self, signature: Tuple[Any, ...]) -> bool:
        """Whether a file whose stat did not change holds other bytes: asked only while its mtime is within RACY_NS of
        now, since a rewrite of the same size within one timestamp tick leaves every stat field as it was."""
        if abs(time.time_ns() - signature[3]) >= RACY_NS:
            return False
        try:
            with open(self.path, "rb") as handle:
                data = handle.read(MAX_GROUPS_BYTES + 1)
        except OSError:
            return True  # read it again the usual way, which names the error
        return hashlib.sha256(data).hexdigest() != self._digest

    def _report(self, signature: Any) -> None:
        state = self._groups
        if isinstance(state, GroupsError):
            key = (signature, state.code, state.where)
            line = ("fabric: tailnet groups file %s: %s (%s); every door refuses until it is fixed"
                    % (self.path, state.code, state.where))
        else:
            key = (signature, "ok")
            line = ("fabric: tailnet groups file %s loaded: %d groups, %d rules"
                    % (self.path, len(state["groups"]), len(state["rules"])))
        if key != self._logged:
            self._logged = key
            try:
                self._log(line)
            except Exception:  # a log that fails never opens a door
                pass

    def decide(self, *, bound: Any, peer: Any, headers: Headers, door: str, capability: str) -> Dict[str, Any]:
        """decide() with the groups in force."""
        return decide(groups=self.current(), bound=bound, peer=peer, headers=headers, door=door,
                      capability=capability)

    def decide_request(self, handler: Any, *, door: str, capability: str, bound: Any = None) -> Dict[str, Any]:
        """decide() for an http.server handler: the address the server listens on (`bound` overrides it), the
        connection's peer and the request's headers. A bound address nobody can tell is refused."""
        if bound is None:
            address = getattr(getattr(handler, "server", None), "server_address", None)
            bound = address[0] if isinstance(address, tuple) and address else None
        client = getattr(handler, "client_address", None)
        peer = client[0] if isinstance(client, tuple) and client else None
        return self.decide(bound=bound, peer=peer, headers=getattr(handler, "headers", None) or [], door=door,
                           capability=capability)
