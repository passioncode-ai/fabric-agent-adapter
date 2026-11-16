# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
"""``fabric-package/1``, the rule layer (contract DEC-0050, DEC-0051): the package's digest and signing statement, the
contract's rules over a package document (FAC-SEM-064…066, FAC-SEM-102) and the path rule (FAA-78, decision D5). Every
function answers by a rule and touches no file; fabric_package packs, signs and verifies on it and re-exports every name
here. Part of the service kit (split from fabric_package; layer L2); the twin of ``fabric-package-rules.mjs``. Standard
library only, Python 3.9+."""

import hashlib
from typing import Any, Dict, List, Optional, Tuple

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))

from fabric_secrets import secret_argument, secret_value  # noqa: E402
from fabric_jsvalue import json_equal as _json_equal  # noqa: E402 - the core's (FAA-65)
from fabric_jsvalue import MISSING as _UNDEFINED  # noqa: E402 - the core's absent value (FAA-65)
from fabric_jsvalue import js_string as _js_string  # noqa: E402 - the core's (FAA-65)
import fabric_jsvalue as _jsv  # noqa: E402 - the core (FAA-65)

PACKAGE_FILE = "fabric.package.json"
PLUGIN_MANIFEST = ".claude-plugin/plugin.json"
SIGNATURE_STATEMENT = "fabric-package-signature/1"


# --- digest, statement, identity ------------------------------------------------------------------------

def agent_ref_of(publisher: str, id_: str) -> str:
    """``urn:fabric:agent:<publisher>:<id>``: one agent across its versions, derived and never chosen (FAC-SEM-066)."""
    return "urn:fabric:agent:%s:%s" % (publisher, id_)


def sha256_of(data: Any) -> str:
    """``sha256:`` and the hex SHA-256 of some bytes (a str is taken as UTF-8)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def package_digest(pkg: Dict[str, Any]) -> str:
    """SHA-256 over the UTF-8 RFC 8785 form of the package without ``digest`` and ``signatures`` (DEC-0050).
    Raises TypeError for a value with no RFC 8785 form, a value nested past the stack included."""
    covered = {k: v for k, v in pkg.items() if k not in ("digest", "signatures")}
    try:
        return sha256_of(_jsv.jcs(covered))
    except RecursionError:  # nested past Python's stack: no form this kit can write, as Node's RangeError is none
        raise TypeError("the package nests too deeply to have an RFC 8785 form") from None


def package_signing_input(digest: str, role: str) -> bytes:
    """The bytes a package signature covers (DEC-0051); the role is inside, so no signature stands for another role."""
    return _jsv.jcs({"type": SIGNATURE_STATEMENT, "role": role, "digest": digest}).encode("utf-8")


def _objects(value: Any) -> List[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _mcp(value: Dict[str, Any]) -> List[Dict[str, Any]]:
    requires = value.get("requires")
    return _objects(requires.get("mcp")) if isinstance(requires, dict) else []


def _whole(value: Dict[str, Any]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []

    def flag(at: str, message: str) -> None:
        out.append({"code": "FAC-SEM-064", "instancePath": at, "message": message})

    try:
        digest = package_digest(value)
        if digest != value.get("digest"):
            flag("/digest", "the digest is %s: the package changed after it was packed, or was packed over another form than RFC 8785" % digest)
    except TypeError:
        flag("/digest", "the package has no RFC 8785 form, so it has no digest")
    sha: Dict[str, Any] = {}
    for index, entry in enumerate(_objects(value.get("files"))):
        path = _js_string(entry.get("path", _UNDEFINED))
        if path in sha:
            flag("/files/%d/path" % index, "%s is listed twice" % path)
        if path == PACKAGE_FILE:
            flag("/files/%d/path" % index, "%s carries the digest and is never listed in files[]" % PACKAGE_FILE)
        sha[path] = entry.get("sha256", _UNDEFINED)

    def named(at: str, path: Any, what: str) -> None:
        if isinstance(path, str) and path not in sha:
            flag(at, "%s %s is not listed in files[], so the digest does not cover it" % (what, path))

    named("/provider", value.get("provider"), "the provider manifest")
    service = value.get("service")
    if isinstance(service, dict) and isinstance(service.get("entry"), list) and service["entry"]:
        named("/service/entry/0", service["entry"][0], "the service's entry")
    evals = value.get("evals")
    if isinstance(evals, dict):
        named("/evals/suite", evals.get("suite"), "the evals suite")
        receipt = evals.get("receipt") if isinstance(evals.get("receipt"), dict) else None
        suite = evals.get("suite")
        if receipt is not None and isinstance(suite, str) and suite in sha and not _same_member(receipt, "suite", sha[suite]):
            flag("/evals/receipt/suite", "the receipt was written for another suite than the one packed")
    for index, dependency in enumerate(_objects(value.get("dependencies"))):
        path = dependency.get("path")
        if not isinstance(path, str):
            continue
        named("/dependencies/%d/path" % index, path, "the vendored dependency")
        if path in sha and not _same_member(dependency, "sha256", sha[path]):
            flag("/dependencies/%d/sha256" % index, "the vendored %s is not the file packed at %s" % (_js_string(dependency.get("name")), path))
    seen: List[Any] = []
    for index, entry in enumerate(_objects(value.get("state"))):
        if any(_same_or_absent(entry.get("path", _UNDEFINED), other) for other in seen):
            flag("/state/%d/path" % index, "state %s is declared twice" % _js_string(entry.get("path", _UNDEFINED)))
        seen.append(entry.get("path", _UNDEFINED))
    if value.get("kind") == "skill-set" and PLUGIN_MANIFEST not in sha:
        flag("/files", "a skill set is one Claude Code plugin folder and lists %s" % PLUGIN_MANIFEST)
    if value.get("kind") == "agent" and "provider" not in value and _mcp(value) and PLUGIN_MANIFEST not in sha:
        flag("/files", "a consumer agent is one Claude Code plugin folder and lists %s" % PLUGIN_MANIFEST)
    return out


def _same_member(obj: Dict[str, Any], name: str, other: Any) -> bool:
    """JavaScript's ``obj[name] === other`` for JSON values: an absent member equals only an absent one."""
    mine = obj.get(name, _UNDEFINED)
    if mine is _UNDEFINED or other is _UNDEFINED:
        return mine is other
    if isinstance(mine, (dict, list)) or isinstance(other, (dict, list)):
        return mine is other
    return _json_equal(mine, other)


def _no_secret(value: Dict[str, Any]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []

    def flag(at: str, message: str) -> None:
        out.append({"code": "FAC-SEM-065", "instancePath": at, "message": message})

    seen: List[Any] = []
    for index, slot in enumerate(_objects(value.get("secrets"))):
        name = slot.get("name", _UNDEFINED)
        if any(_same_or_absent(name, other) for other in seen):
            flag("/secrets/%d/name" % index, "secret slot %s is declared twice" % _js_string(name))
        seen.append(name)
        for field in ("name", "purpose"):  # the message never repeats the value
            text = slot.get(field)
            if isinstance(text, str) and secret_value(text):
                flag("/secrets/%d/%s" % (index, field), "a secret slot is named, never filled: this looks like a credential")
    requires = value.get("requires")
    if isinstance(requires, dict) and isinstance(requires.get("mcp"), list):
        for index, requirement in enumerate(requires["mcp"]):
            if not isinstance(requirement, dict):
                continue
            texts = [("role", requirement.get("role")), ("contract", requirement.get("contract"))]
            if isinstance(requirement.get("tools"), list):
                texts += [("tools/%d" % t, tool) for t, tool in enumerate(requirement["tools"])]
            for field, text in texts:
                if isinstance(text, str) and secret_value(text):
                    flag("/requires/mcp/%d/%s" % (index, field), "a required MCP server is named by role and tools, never by a credential")
    service = value.get("service")
    if isinstance(service, dict) and isinstance(service.get("entry"), list):
        for index, arg in enumerate(service["entry"]):
            if isinstance(arg, str) and secret_argument(arg):
                flag("/service/entry/%d" % index, "a launch argument never carries a credential: the secret reaches the service from its slot")
    return out


def _same_or_absent(a: Any, b: Any) -> bool:
    """Set membership as the contract's ``new Set`` tests it: SameValueZero for JSON values, identity for containers."""
    if a is _UNDEFINED or b is _UNDEFINED:
        return a is b
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        return a is b
    return _json_equal(a, b)


def _agent_ref(value: Dict[str, Any]) -> List[Dict[str, str]]:
    if value.get("kind") != "agent" or not isinstance(value.get("publisher"), str) or not isinstance(value.get("id"), str):
        return []
    expected = agent_ref_of(value["publisher"], value["id"])
    if value.get("agentRef") == expected and isinstance(value.get("agentRef"), str):
        return []
    return [{"code": "FAC-SEM-066", "instancePath": "/agentRef", "message": "the agent is %s: agentRef is derived from publisher and id" % expected}]


def _mcp_roles(value: Dict[str, Any]) -> List[Dict[str, str]]:
    seen = set()
    declared = {slot.get("name") for slot in _objects(value.get("secrets")) if isinstance(slot.get("name"), str)}
    feeds: Dict[str, str] = {}
    out: List[Dict[str, str]] = []
    for index, requirement in enumerate(_mcp(value)):
        role = requirement.get("role")
        if not isinstance(role, str):
            continue
        if role in seen:
            out.append({"code": "FAC-SEM-102", "instancePath": "/requires/mcp/%d/role" % index, "message": "role %s is required twice: one role, one server" % role})
        seen.add(role)
        for s, slot in enumerate(requirement.get("secrets") if isinstance(requirement.get("secrets"), list) else []):
            if not isinstance(slot, str):
                continue
            at = "/requires/mcp/%d/secrets/%d" % (index, s)
            if slot not in declared:
                out.append({"code": "FAC-SEM-102", "instancePath": at, "message": "slot %s is not declared in secrets[]" % slot})
            other = feeds.get(slot)
            if other is not None and other != role:
                out.append({"code": "FAC-SEM-102", "instancePath": at, "message": "slot %s already feeds role %s: one slot, one role" % (slot, other)})
            feeds[slot] = other if other is not None else role
    return out


# --- the path rule (FAA-78, finding 40; decision D5) ----------------------------------------------------------------

def _control(ch: str) -> bool:
    """C0 and C1 controls, DEL, and the two Unicode line terminators JavaScript's ``.`` stops at."""
    code = ord(ch)
    return code < 0x20 or 0x7F <= code <= 0x9F or code in (0x2028, 0x2029)


def path_problem(path: Any) -> Optional[str]:
    """Why ``path`` is no packaged path, or None. The schema's pattern says the same in one expression, but JavaScript's
    ``.`` stops at U+2028 and U+2029, so in Node and in the contract's own ajv its look-aheads never see a ``..``, a
    backslash or a ``//`` after one (``a\u2028/../../etc/passwd`` passes there). This rule reads the path character by
    character in both kits, and refuses C1 controls, DEL and the line terminators besides. A non-string is the
    schema's to refuse."""
    if not isinstance(path, str):
        return None
    if not 1 <= len(path) <= 256:
        return "a path is 1 to 256 characters"
    if any(_control(ch) for ch in path):
        return "a path carries no control character and no line or paragraph separator"
    if path[0] in "/~":
        return "a path is relative to the package folder: it never starts with / or ~"
    if "\\" in path or ":" in path:
        return "a path is written with forward slashes and no colon"
    if "//" in path or path.endswith("/"):
        return "a path names a file: no empty segment and no trailing slash"
    if any(segment in (".", "..") for segment in path.split("/")):
        return "a path never steps through . or .."
    return None


def _path_fields(pkg: Dict[str, Any]) -> List[Tuple[str, Any]]:
    """Every member the schema types as a path, by its JSON pointer."""
    fields: List[Tuple[str, Any]] = [("/provider", pkg.get("provider", _UNDEFINED))]
    evals = pkg.get("evals")
    if isinstance(evals, dict):
        fields.append(("/evals/suite", evals.get("suite", _UNDEFINED)))
    for name in ("state", "dependencies", "files"):
        items = pkg.get(name)
        for index, entry in enumerate(items if isinstance(items, list) else []):
            if isinstance(entry, dict):
                fields.append(("/%s/%d/path" % (name, index), entry.get("path", _UNDEFINED)))
    return [(at, value) for at, value in fields if value is not _UNDEFINED]


def path_problems(pkg: Any) -> List[Dict[str, str]]:
    """The path rule over every path the package names: ``{instancePath, message}`` per path refused."""
    if not isinstance(pkg, dict):
        return []
    out = []
    for at, value in _path_fields(pkg):
        why = path_problem(value)
        if why is not None:
            out.append({"instancePath": at, "message": why})
    return out


def package_findings(pkg: Dict[str, Any]) -> List[Dict[str, str]]:
    """FAC-SEM-064 (whole), 065 (no secret), 066 (agentRef derived) and 102 (one role, one server), in that order."""
    return _whole(pkg) + _no_secret(pkg) + _agent_ref(pkg) + _mcp_roles(pkg)
