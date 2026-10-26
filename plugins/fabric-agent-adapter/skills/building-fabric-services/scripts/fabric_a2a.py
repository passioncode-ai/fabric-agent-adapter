"""The reading side of an A2A Agent Card (DEC-0122): the well-known document's `surfaces.a2a` member, read as the
contract's schema reads it (`a2a_surface_findings`, `a2a_view`; `a2a_surface` builds one), and what a public card must
not carry (`agent_card_findings`): no member about the running process, no secret, no `securitySchemes` entry naming
the descriptor's token header, every Fabric extension `required: false`, and interface URLs where the placement puts
them. Serving a card, the A2A binding and a client are not here (FAA-10). Part of the service kit (layer L3).
Standard library only."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))

from fabric_base import ServiceError  # noqa: E402
from fabric_jsvalue import js_keys  # noqa: E402
from fabric_secrets import secret_value  # noqa: E402

#: A2A 1.0 section 8.2: where a peer looks for the public card.
A2A_SURFACE_PATH = "/.well-known/agent-card.json"
#: The A2A version the contract pins (the A2A peer profile); `surfaces.a2a.protocolVersion` is this constant.
A2A_PROTOCOL_VERSION = "1.0"
#: The contract's extension namespace (decision D6): an extension whose uri starts here is a Fabric fact.
FABRIC_EXTENSION_PREFIX = "https://fabric.passioncode.ai/"
#: The well-known document's members about the running process, which a public card never carries (DEC-0122 item 2).
PROCESS_MEMBERS = ("build", "process", "pid", "status", "summary", "degraded")
MAX_PATH = 2048  # service-common.schema.json originPath maxLength, counted in code points as ajv counts it

# JavaScript's \s (the schema's pattern runs under ajv), not Python's: U+FEFF is one, U+001C and U+0085 are not.
_JS_SPACE = ("\t\n\x0b\x0c\r              "
             "    　﻿")
_ORIGIN_PATH = re.compile("^/(?!/)[^%s]*\\Z" % _JS_SPACE)
_HTTPS = re.compile(r"^https://", re.IGNORECASE)


def _pointer(*parts: Any) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _ascii_lower(text: str) -> str:
    return re.sub("[A-Z]", lambda m: m.group(0).lower(), text)


def _finding(path: str, keyword: str, message: str) -> Dict[str, str]:
    return {"instancePath": path, "keyword": keyword, "message": message}


def a2a_surface_findings(value: Any, base: str = "/surfaces/a2a") -> List[Dict[str, str]]:
    """`surfaces.a2a` against service-well-known.schema.json at the pin, in ajv's order: each finding's instancePath
    and keyword are the schema error's (test/fixtures/contract/a2a-vectors.json), with a sentence."""
    if not isinstance(value, dict):
        return [_finding(base, "type", "surfaces.a2a is an object {path, protocolVersion}")]
    found = [_finding(base, "required", "surfaces.a2a has no %s" % k) for k in ("path", "protocolVersion") if k not in value]
    found += [_finding(base, "additionalProperties", "surfaces.a2a has no member %s: the card names its interfaces, "
                       "bindings and security schemes (DEC-0122)" % k)
              for k in value if k not in ("path", "protocolVersion")]
    if "path" in value:
        path = value["path"]
        if not isinstance(path, str):
            found.append(_finding(base + "/path", "type", "surfaces.a2a.path is a string"))
        else:
            if len(path) > MAX_PATH:
                found.append(_finding(base + "/path", "maxLength", "surfaces.a2a.path is longer than %d characters" % MAX_PATH))
            if not _ORIGIN_PATH.match(path):
                found.append(_finding(base + "/path", "pattern", "surfaces.a2a.path is not a path on the service origin "
                                      "(one leading /, no whitespace)"))
    if "protocolVersion" in value and not (isinstance(value["protocolVersion"], str) and value["protocolVersion"] == A2A_PROTOCOL_VERSION):
        found.append(_finding(base + "/protocolVersion", "const", "surfaces.a2a.protocolVersion is %s, the A2A version the "
                              "contract pins" % A2A_PROTOCOL_VERSION))
    return found


def a2a_surface_problems(value: Any) -> List[str]:
    """The findings of a2a_surface_findings as sentences; empty when the member is valid."""
    return [f["message"] for f in a2a_surface_findings(value)]


def a2a_surface(path: str = A2A_SURFACE_PATH) -> Dict[str, str]:
    """The `surfaces.a2a` member for a service that serves its public card at `path` (DEC-0122 item 1)."""
    surface = {"path": path, "protocolVersion": A2A_PROTOCOL_VERSION}
    problems = a2a_surface_problems(surface)
    if problems:
        raise ServiceError("surfaces.a2a: %s." % "; ".join(problems))
    return surface


def a2a_view(wk: Any) -> Dict[str, Any]:
    """What a host reads of a well-known document's A2A member; never raises. `declared` is whether `surfaces.a2a`
    is present, `valid` whether it is the schema's, `path` the card's path when it is, `findings` the schema's."""
    surfaces = wk.get("surfaces") if isinstance(wk, dict) else None
    if not isinstance(surfaces, dict) or "a2a" not in surfaces:
        return {"declared": False, "valid": False, "path": None, "protocolVersion": None, "findings": []}
    findings = a2a_surface_findings(surfaces["a2a"])
    valid = not findings
    return {"declared": True, "valid": valid, "path": surfaces["a2a"]["path"] if valid else None,
            "protocolVersion": A2A_PROTOCOL_VERSION if valid else None, "findings": findings}


def _card(code: str, path: str, message: str) -> Dict[str, str]:
    return {"code": code, "instancePath": path, "message": message}


def _secrets(card: Dict[str, Any]) -> List[Dict[str, str]]:
    """Every string the card holds that is shaped like a credential, by its place; walked without recursion, in the
    order JavaScript lists keys, so both twins name the same places in the same order."""
    found: List[Dict[str, str]] = []
    stack: List[Any] = [(card, "")]
    while stack:
        node, path = stack.pop()
        if isinstance(node, str):
            if secret_value(node):
                found.append(_card("secret", path, "%s holds a value shaped like a credential: a public card carries no "
                                   "secret (DEC-0122 item 2)" % (path or "the card")))
        elif isinstance(node, dict):
            stack.extend((node[k], path + _pointer(k)) for k in reversed(js_keys(node)))
        elif isinstance(node, list):
            stack.extend((node[i], path + _pointer(i)) for i in reversed(range(len(node))))
    return found


def _descriptor_schemes(card: Dict[str, Any], header: str) -> List[Dict[str, str]]:
    """D5: a securitySchemes entry that is an API key in the descriptor's own header. With Authorization (the
    default) the card cannot show the token, so nothing is reported."""
    schemes = card.get("securitySchemes")
    if not isinstance(schemes, dict) or not header or _ascii_lower(header) == "authorization":
        return []
    found = []
    for name in js_keys(schemes):
        scheme = schemes[name]
        if not isinstance(scheme, dict):
            continue
        key = scheme.get("apiKeySecurityScheme")  # A2A 1.0: one wrapper member per kind
        if isinstance(key, dict):
            location, named = key.get("location"), key.get("name")
        elif scheme.get("type") == "apiKey":  # the OpenAPI shape of A2A before 1.0
            location, named = scheme.get("in"), scheme.get("name")
        else:
            continue
        if location == "header" and isinstance(named, str) and _ascii_lower(named) == _ascii_lower(header):
            found.append(_card("descriptor-token-scheme", _pointer("securitySchemes", name),
                               "securitySchemes.%s is an API key in %s, the descriptor's token header: an A2A interface "
                               "never takes the descriptor's token (DEC-0122 item 3)" % (name, header)))
    return found


def _fabric_extensions(card: Dict[str, Any]) -> List[Dict[str, str]]:
    """D6: an extension under the contract's namespace carries required: false (A2A 1.0 section 4.4.4)."""
    capabilities = card.get("capabilities")
    extensions = capabilities.get("extensions") if isinstance(capabilities, dict) else None
    if not isinstance(extensions, list):
        return []
    found = []
    for i, extension in enumerate(extensions):
        uri = extension.get("uri") if isinstance(extension, dict) else None
        if not isinstance(uri, str) or _ascii_lower(uri[:len(FABRIC_EXTENSION_PREFIX)]) != FABRIC_EXTENSION_PREFIX:
            continue
        if extension.get("required") is not False:
            found.append(_card("fabric-extension-required", _pointer("capabilities", "extensions", i),
                               "the Fabric extension at capabilities.extensions[%d] does not carry required: false, so a "
                               "peer that does not know it cannot call (DEC-0122 item 4)" % i))
    return found


def _interfaces(card: Dict[str, Any], origin: Optional[str], remote: bool) -> List[Dict[str, str]]:
    """Where the card's interfaces are (DEC-0122 item 2): on a local placement on the service's loopback origin as
    written, on a remote one https; every one A2A 1.0."""
    interfaces = card.get("supportedInterfaces")
    if not isinstance(interfaces, list) or not interfaces:
        return [_card("interfaces-missing", "/supportedInterfaces", "the card names no supportedInterfaces: A2A 1.0 "
                      "lists a card's interfaces there")]
    found = []
    for i, interface in enumerate(interfaces):
        place = _pointer("supportedInterfaces", i)
        url = interface.get("url") if isinstance(interface, dict) else None
        if not isinstance(url, str):
            found.append(_card("interface-shape", place, "supportedInterfaces[%d] is not an interface with a url" % i))
            continue
        if remote:
            if not _HTTPS.match(url):
                found.append(_card("interface-scheme", place + "/url", "supportedInterfaces[%d].url is not https: a "
                                   "loopback or plain-http interface is admitted on a local placement only" % i))
        elif origin and not (url == origin or url.startswith(origin + "/")):
            found.append(_card("interface-origin", place + "/url", "supportedInterfaces[%d].url is not on the service "
                               "origin %s, where a peer on this computer reaches it" % (i, origin)))
        if not (isinstance(interface.get("protocolVersion"), str) and interface["protocolVersion"] == A2A_PROTOCOL_VERSION):
            found.append(_card("interface-version", place + "/protocolVersion", "supportedInterfaces[%d] does not expose "
                               "A2A %s, the version surfaces.a2a names" % (i, A2A_PROTOCOL_VERSION)))
    return found


def agent_card_findings(card: Any, *, origin: Optional[str] = None, remote: bool = False,
                        descriptor_header: Optional[str] = "Authorization") -> List[Dict[str, str]]:
    """What a public Agent Card must not carry or say (DEC-0122 items 2 to 4; decisions D5, D6), each finding
    {code, instancePath, message} naming the place and never the value. `origin` is the service origin the card was
    read on (its interfaces' place on a local placement; omitted, the place is not judged), `remote` the placement,
    `descriptor_header` the descriptor's `auth.header` (default Authorization). It reads the card only: whether an
    interface accepts the token cannot be seen without sending it, which DEC-0122 forbids."""
    if not isinstance(card, dict):
        return [_card("card-shape", "", "the card is not a JSON object")]
    found = [_card("process-member", _pointer(k), "the card carries %s, a member about the running process: a public "
                   "card carries none (DEC-0122 item 2)" % k) for k in PROCESS_MEMBERS if k in card]
    found += _secrets(card)
    found += _descriptor_schemes(card, descriptor_header if isinstance(descriptor_header, str) else "")
    found += _fabric_extensions(card)
    found += _interfaces(card, origin, remote)
    return found
