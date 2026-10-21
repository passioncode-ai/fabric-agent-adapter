#!/usr/bin/env python3
"""``fabric-package/1`` (contract DEC-0050, DEC-0051, DEC-0071, DEC-0074; FAA-27a): pack an agent or a skill set as one
folder with ``fabric.package.json``, sign it, and verify it. The twin of ``fabric-package.mjs``.

    python3 fabric_package.py pack   <folder> [--apply]
    python3 fabric_package.py sign   <folder> --key <private key file> [--kid <kid>] [--role publisher|organization] [--apply]
    python3 fabric_package.py verify <folder> --trust <trust.json> [--countersigned]

``pack`` reads the author's ``fabric.package.json`` (the descriptive fields), lists every other file of the folder with
its SHA-256, derives ``agentRef``, computes the digest and checks the result against the contract's schema, its rules
(FAC-SEM-064…066, FAC-SEM-102) and the folder check. ``sign`` adds an Ed25519 signature over the digest (``EdDSA``,
the one algorithm DEC-0051 admits) from a key file the caller names; it never makes or keeps a key. ``verify`` is the
contract's ``verifyPackage`` (PK-1…PK-10) plus the folder check. Without ``--apply`` nothing is written. Standard
library only; the answer is JSON on stdout, exit 0 when it holds, 1 when it does not, 2 on a usage error.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_delegation as fd  # noqa: E402
from fabric_secrets import secret_argument, secret_value  # noqa: E402

PACKAGE_FILE = "fabric.package.json"
PLUGIN_MANIFEST = ".claude-plugin/plugin.json"
SIGNATURE_STATEMENT = "fabric-package-signature/1"
# DEC-0051: ES256 joins when Fabric records its decision D2; until then a verifier refuses it as unknown-algorithm.
PACKAGE_ALGORITHMS = ("EdDSA",)
SCHEMA_PATH = Path(__file__).resolve().parent / "fabric-package.schema.json"
# What pack refuses to list: version-control and cache litter, and files that are credentials by their name.
JUNK = re.compile(r"^(\.git|__pycache__|\.DS_Store|.*\.pyc)$")
SECRET_FILE = re.compile(r"^(\.env(\..+)?|.*\.(pem|key|p12|pfx|jks|keystore)|id_(rsa|dsa|ecdsa|ed25519)|\.(npmrc|netrc|pypirc))$")
SECRET_FILE_OK = re.compile(r"^\.env\.(example|sample|template)$")
_B64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_PKCS8_ED25519 = bytes.fromhex("302e020100300506032b657004220420")


class PackageError(Exception):
    """A refusal a person can act on; the message names what to change."""


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
    Raises TypeError for a value with no RFC 8785 form."""
    covered = {k: v for k, v in pkg.items() if k not in ("digest", "signatures")}
    return sha256_of(_jsv.jcs(covered))


def package_signing_input(digest: str, role: str) -> bytes:
    """The bytes a package signature covers (DEC-0051); the role is inside, so no signature stands for another role."""
    return _jsv.jcs({"type": SIGNATURE_STATEMENT, "role": role, "digest": digest}).encode("utf-8")


# --- Ed25519 signing (RFC 8032 §5.1.6) ------------------------------------------------------------------

def _secret_scalar(seed: bytes) -> Tuple[int, bytes]:
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def ed25519_public_key(seed: bytes) -> bytes:
    """The 32-byte public key of a 32-byte Ed25519 seed."""
    if len(seed) != 32:
        raise PackageError("An Ed25519 private key is 32 bytes.")
    a, _ = _secret_scalar(seed)
    return _crypto._ed_encode_point(_crypto._ed_mul(a, _crypto._ED_G))


def ed25519_sign(seed: bytes, message: bytes) -> bytes:
    """A deterministic Ed25519 signature; the same seed and message give the bytes Node's crypto.sign gives."""
    a, prefix = _secret_scalar(seed)
    public = _crypto._ed_encode_point(_crypto._ed_mul(a, _crypto._ED_G))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % _crypto._ED_L
    big_r = _crypto._ed_encode_point(_crypto._ed_mul(r, _crypto._ED_G))
    k = int.from_bytes(hashlib.sha512(big_r + public + message).digest(), "little") % _crypto._ED_L
    return big_r + ((r + k * a) % _crypto._ED_L).to_bytes(32, "little")


from fabric_crypto import b64url as _b64url  # noqa: E402 - the core's (FAA-65)


def public_jwk(seed: bytes, kid: str) -> Dict[str, str]:
    """The public JWK an installing machine pins for this key (the package names a publisher, never a key)."""
    return {"kty": "OKP", "crv": "Ed25519", "x": _b64url(ed25519_public_key(seed)), "kid": kid, "alg": "EdDSA", "use": "sig"}


def read_signing_key(path: Any, kid: Optional[str] = None) -> Tuple[bytes, str]:
    """``(seed, kid)`` from a private key file: a JWK (``kty`` OKP, ``crv`` Ed25519, ``d``; ``kid`` and ``alg``
    EdDSA if named) or a PKCS#8 PEM (``openssl genpkey -algorithm ed25519``, then ``--kid``). The file must be readable
    by its owner only; its bytes are never echoed."""
    path = Path(path)
    try:
        stat = path.stat()
        raw = path.read_bytes()
    except OSError as exc:
        raise PackageError("Cannot read the key file %s: %s." % (path, exc.strerror)) from None
    if os.name == "posix" and stat.st_mode & 0o077:
        raise PackageError("The key file %s is readable by others (mode %o); chmod 600 it first." % (path, stat.st_mode & 0o777))
    text = raw.decode("utf-8", "replace").strip()
    if text.startswith("{"):
        try:
            jwk = json.loads(text)
        except ValueError:
            raise PackageError("The key file is neither a JWK nor a PEM private key.") from None
        if not isinstance(jwk, dict) or jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519" or not isinstance(jwk.get("d"), str):
            raise PackageError("The key file must be an Ed25519 private JWK (kty OKP, crv Ed25519, with d).")
        if jwk.get("alg", "EdDSA") != "EdDSA":
            raise PackageError("The key names alg %r; a package signature is EdDSA (DEC-0051)." % jwk.get("alg"))
        seed = _crypto.b64url_decode(jwk["d"]) if _B64URL.match(jwk["d"]) else b""
        if len(seed) != 32:
            raise PackageError("The key's d is not a 32-byte Ed25519 private key.")
        if isinstance(jwk.get("x"), str) and jwk["x"] != _b64url(ed25519_public_key(seed)):
            raise PackageError("The key's x is not the public key of its d.")
        named = jwk.get("kid")
        if kid is not None and named is not None and kid != named:
            raise PackageError("--kid %s disagrees with the key's own kid %s." % (kid, named))
        kid = kid if kid is not None else named
    elif "-----BEGIN " + "PRIVATE KEY-----" in text:  # split, so a secret scanner never reads this line as a key
        body = "".join(line for line in text.splitlines() if line and not line.startswith("-----"))
        try:
            der = base64.b64decode(body, validate=True)
        except ValueError:
            raise PackageError("The PEM key is not base64.") from None
        if len(der) != 48 or not der.startswith(_PKCS8_ED25519):
            raise PackageError("The PEM key is not an Ed25519 private key (PKCS#8).")
        seed = der[16:]
    else:
        raise PackageError("The key file is neither a JWK nor a PEM private key.")
    if not isinstance(kid, str) or not re.match(r"^[A-Za-z0-9._:-]{1,128}$", kid):
        raise PackageError("Name the key with --kid (1-128 of A-Z a-z 0-9 . _ : -): the installing machine pins it by that name.")
    return seed, kid


# --- the schema (bundled from the contract at the pin) ------------------------------------------------

_SCHEMA_CACHE: Dict[str, Any] = {}


def _schema() -> Dict[str, Any]:
    if "s" not in _SCHEMA_CACHE:
        _SCHEMA_CACHE["s"] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE["s"]


from fabric_jsvalue import json_equal as _json_equal  # noqa: E402 - the core's (FAA-65)


def _type_of(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


_DATE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$")
_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]*$")


def _format_ok(fmt: str, value: Any) -> bool:
    if not isinstance(value, str):
        return True
    if fmt == "date-time":
        if not _DATE_TIME.match(value):
            return False
        try:
            datetime.strptime(value[:19].replace("t", "T"), "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return False
        offset = value[19:].lstrip(".0123456789")
        return offset in ("Z", "z") or (int(offset[1:3]) < 24 and int(offset[4:6]) < 60)
    if fmt == "uri":
        return bool(_URI.match(value))
    return True


def _pointer(token: Any) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def _validate(schema: Any, value: Any, at: str, out: List[Dict[str, str]]) -> None:
    """The JSON Schema 2020-12 keywords the package schema uses, nothing more."""
    if schema is True:
        return
    if schema is False:
        out.append({"instancePath": at, "message": "is not allowed here"})
        return
    if "$ref" in schema:
        target = _schema()
        for token in schema["$ref"].lstrip("#/").split("/"):
            target = target[token.replace("~1", "/").replace("~0", "~")]
        _validate(target, value, at, out)
    kind = _type_of(value)
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not (kind in allowed or (kind == "integer" and "number" in allowed)):
            out.append({"instancePath": at, "message": "must be %s" % " or ".join(allowed)})
            return
    if "const" in schema and not _json_equal(schema["const"], value):
        out.append({"instancePath": at, "message": "must be %s" % json.dumps(schema["const"])})
    if "enum" in schema and not any(_json_equal(item, value) for item in schema["enum"]):
        out.append({"instancePath": at, "message": "must be one of %s" % ", ".join(json.dumps(i) for i in schema["enum"])})
    if kind == "string":
        length = len(value)  # code points, as JSON Schema counts
        if length < schema.get("minLength", 0):
            out.append({"instancePath": at, "message": "is shorter than %d" % schema["minLength"]})
        if "maxLength" in schema and length > schema["maxLength"]:
            out.append({"instancePath": at, "message": "is longer than %d" % schema["maxLength"]})
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append({"instancePath": at, "message": "does not match %s" % schema["pattern"]})
        if "format" in schema and not _format_ok(schema["format"], value):
            out.append({"instancePath": at, "message": "is not a %s" % schema["format"]})
    if kind in ("integer", "number") and "minimum" in schema and value < schema["minimum"]:
        out.append({"instancePath": at, "message": "is below %s" % schema["minimum"]})
    if kind == "array":
        if len(value) < schema.get("minItems", 0):
            out.append({"instancePath": at, "message": "has fewer than %d items" % schema["minItems"]})
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append({"instancePath": at, "message": "has more than %d items" % schema["maxItems"]})
        if schema.get("uniqueItems") and any(_json_equal(value[i], value[j]) for i in range(len(value)) for j in range(i)):
            out.append({"instancePath": at, "message": "has duplicate items"})
        if "items" in schema:
            for index, item in enumerate(value):
                _validate(schema["items"], item, "%s/%d" % (at, index), out)
        if "contains" in schema:
            matches = sum(1 for item in value if not _problems(schema["contains"], item))
            if matches < schema.get("minContains", 1):
                out.append({"instancePath": at, "message": "has fewer than %d matching items" % schema.get("minContains", 1)})
            if "maxContains" in schema and matches > schema["maxContains"]:
                out.append({"instancePath": at, "message": "has more than %d matching items" % schema["maxContains"]})
    if kind == "object":
        for name in schema.get("required", []):
            if name not in value:
                out.append({"instancePath": at, "message": "must have %s" % name})
        properties = schema.get("properties", {})
        for name, member in value.items():
            if name in properties:
                _validate(properties[name], member, "%s/%s" % (at, _pointer(name)), out)
            elif "additionalProperties" in schema:
                if schema["additionalProperties"] is False:
                    out.append({"instancePath": "%s/%s" % (at, _pointer(name)), "message": "is not a member of this object"})
                else:
                    _validate(schema["additionalProperties"], member, "%s/%s" % (at, _pointer(name)), out)
            if "propertyNames" in schema:
                _validate(schema["propertyNames"], name, "%s/%s" % (at, _pointer(name)), out)
    for sub in schema.get("allOf", []):
        _validate(sub, value, at, out)
    if "not" in schema and not _problems(schema["not"], value):
        out.append({"instancePath": at, "message": "must not match"})
    if "if" in schema:
        branch = schema.get("then") if not _problems(schema["if"], value) else schema.get("else")
        if branch is not None:
            _validate(branch, value, at, out)


def _problems(schema: Any, value: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    _validate(schema, value, "", out)
    return out


def schema_problems(pkg: Any) -> List[Dict[str, str]]:
    """Where the package breaks ``fabric-package.schema.json`` (the contract's, bundled at the pin)."""
    return _problems(_schema(), pkg)


# --- the contract's rules (FAC-SEM-064…066, FAC-SEM-102) ------------------------------------------------

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


from fabric_jsvalue import MISSING as _UNDEFINED  # noqa: E402 - the core's absent value (FAA-65)


def _same_member(obj: Dict[str, Any], name: str, other: Any) -> bool:
    """JavaScript's ``obj[name] === other`` for JSON values: an absent member equals only an absent one."""
    mine = obj.get(name, _UNDEFINED)
    if mine is _UNDEFINED or other is _UNDEFINED:
        return mine is other
    if isinstance(mine, (dict, list)) or isinstance(other, (dict, list)):
        return mine is other
    return _json_equal(mine, other)


from fabric_jsvalue import js_string as _js_string  # noqa: E402 - the core's (FAA-65)
import fabric_jsvalue as _jsv  # noqa: E402 - the core (FAA-65)
import fabric_crypto as _crypto  # noqa: E402 - the core (FAA-65)


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


def package_findings(pkg: Dict[str, Any]) -> List[Dict[str, str]]:
    """FAC-SEM-064 (whole), 065 (no secret), 066 (agentRef derived) and 102 (one role, one server), in that order."""
    return _whole(pkg) + _no_secret(pkg) + _agent_ref(pkg) + _mcp_roles(pkg)


# --- the folder check and the verifier ------------------------------------------------------------------

def _parsed(data: Optional[bytes]) -> Optional[Dict[str, Any]]:
    if data is None:
        return None
    try:
        value = json.loads(data.decode("utf-8", "replace"))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def check_package_folder(pkg: Dict[str, Any], files: Dict[str, bytes]) -> List[Dict[str, str]]:
    """DEC-0050's folder check: every listed file present with its SHA-256, nothing unlisted but
    ``fabric.package.json``, the plugin manifest naming the package's id and version, and the provider manifest
    carrying the package's cost presets or none. ``files`` maps each forward-slash path to its bytes."""
    problems: List[Dict[str, str]] = []
    listed: Dict[str, Any] = {}
    for entry in _objects(pkg.get("files")):
        listed[_js_string(entry.get("path", _UNDEFINED))] = entry.get("sha256", _UNDEFINED)
    for path, digest in listed.items():
        data = files.get(path)
        if data is None:
            problems.append({"problem": "file-missing", "path": path})
        elif digest is _UNDEFINED or sha256_of(data) != digest:
            problems.append({"problem": "file-digest", "path": path})
    for path in files:
        if path != PACKAGE_FILE and path not in listed:
            problems.append({"problem": "file-unlisted", "path": path})
    if PLUGIN_MANIFEST in files:
        plugin = _parsed(files.get(PLUGIN_MANIFEST))
        if not plugin or not _same_member(plugin, "name", pkg.get("id", _UNDEFINED)) or not _same_member(plugin, "version", pkg.get("version", _UNDEFINED)):
            problems.append({"problem": "plugin-manifest", "path": PLUGIN_MANIFEST})
    provider = pkg.get("provider")
    if isinstance(provider, str) and provider in files:
        manifest = _parsed(files.get(provider))
        if not manifest or ("costPresets" in manifest and not ("costPresets" in pkg and _json_equal(manifest["costPresets"], pkg["costPresets"]))):
            problems.append({"problem": "provider-manifest", "path": provider})
    return problems


def _key_for(keys: Any, kid: str, alg: str) -> Dict[str, Any]:
    matches = [k for k in (keys if isinstance(keys, list) else []) if isinstance(k, dict) and k.get("kid") == kid]
    if len(matches) > 1:
        return {"problem": "duplicate-kid"}
    if not matches:
        return {"problem": "unknown-key"}
    jwk = matches[0]
    if jwk.get("alg", _UNDEFINED) != alg:
        return {"problem": "key-algorithm-mismatch"}
    x = jwk.get("x")
    if (jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519" or not isinstance(x, str) or not _B64URL.match(x)
            or "d" in jwk or ("use" in jwk and jwk["use"] != "sig")):
        return {"problem": "unusable-key"}
    raw = _crypto.b64url_decode(x)
    if len(raw) != 32:
        return {"problem": "unusable-key"}
    if _crypto.is_small_order_key(raw):  # DEC-0045: refused before any verification
        return {"problem": "small-order-key"}
    return {"key": raw}


def verify_package(pkg: Any, trust: Dict[str, Any], countersigned: bool = False) -> Dict[str, Any]:
    """The contract's verifyPackage (DEC-0051), in PK-1…PK-10's order."""
    if not isinstance(pkg, dict) or not isinstance(pkg.get("digest"), str):
        return {"ok": False, "problem": "malformed"}
    try:
        digest = package_digest(pkg)
    except TypeError:
        return {"ok": False, "problem": "malformed"}
    if digest != pkg["digest"]:
        return {"ok": False, "problem": "digest-mismatch"}
    signatures = pkg.get("signatures", _UNDEFINED)
    if signatures is _UNDEFINED or (isinstance(signatures, list) and not signatures):
        return {"ok": False, "problem": "unsigned"}
    if not isinstance(signatures, list):
        return {"ok": False, "problem": "malformed"}
    if sum(1 for e in signatures if isinstance(e, dict) and e.get("role") == "publisher") != 1:
        return {"ok": False, "problem": "no-publisher-signature"}
    signers: List[Dict[str, str]] = []
    unverified: List[Dict[str, str]] = []
    trust = trust if isinstance(trust, dict) else {}
    for index, entry in enumerate(signatures):
        if (not isinstance(entry, dict) or entry.get("role") not in ("publisher", "organization") or not isinstance(entry.get("alg"), str)
                or not isinstance(entry.get("kid"), str) or not isinstance(entry.get("sig"), str) or not _B64URL.match(entry["sig"])):
            return {"ok": False, "problem": "malformed", "signature": index}
        if entry["alg"] not in PACKAGE_ALGORITHMS:
            return {"ok": False, "problem": "unknown-algorithm", "signature": index}
        found = _key_for(trust.get(entry["role"]) or [], entry["kid"], entry["alg"])
        if found.get("problem") == "unknown-key" and entry["role"] == "organization" and countersigned is not True:
            unverified.append({"role": entry["role"], "kid": entry["kid"]})
            continue
        if "problem" in found:
            return {"ok": False, "problem": found["problem"], "signature": index}
        signature = _crypto.b64url_decode(entry["sig"])
        if len(signature) != 64 or not _crypto.ed25519_verify(found["key"], package_signing_input(digest, entry["role"]), signature):
            return {"ok": False, "problem": "bad-signature", "signature": index}
        signers.append({"role": entry["role"], "kid": entry["kid"]})
    if countersigned is True and not any(s["role"] == "organization" for s in signers):
        return {"ok": False, "problem": "no-countersignature"}
    verdict: Dict[str, Any] = {"ok": True, "digest": digest, "signers": signers}
    if unverified:
        verdict["unverified"] = unverified
    return verdict


def consumer_placement(pkg: Any, configured: Any) -> List[Dict[str, str]]:
    """What a placement lacks for ``requires.mcp`` (DEC-0071): ``configured`` maps each registered role to its tools."""
    if not isinstance(pkg, dict):
        return []
    roles = [r for r in _mcp(pkg) if isinstance(r.get("role"), str)]
    if not isinstance(configured, dict):
        return [{"problem": "missing-role", "role": r["role"]} for r in roles]
    problems: List[Dict[str, str]] = []
    for requirement in roles:
        if requirement["role"] not in configured:
            problems.append({"problem": "missing-role", "role": requirement["role"]})
            continue
        tools = configured[requirement["role"]] if isinstance(configured[requirement["role"]], list) else []
        for tool in requirement.get("tools") if isinstance(requirement.get("tools"), list) else []:
            if isinstance(tool, str) and tool not in tools:
                problems.append({"problem": "missing-tool", "role": requirement["role"], "tool": tool})
    return problems


# --- the folder on disk -----------------------------------------------------------------------------------

def _litter(name: str) -> Optional[str]:
    if JUNK.match(name):
        return "litter"
    if SECRET_FILE.match(name) and not SECRET_FILE_OK.match(name):
        return "a credential file"
    return None


def read_folder(folder: Any) -> Dict[str, bytes]:
    """Every regular file under ``folder`` by its forward-slash path. Refuses a symlink, a special file, version-control
    or cache litter, and a file that is a credential by its name — each named, so the person can remove it or pack a
    clean copy."""
    root = Path(folder)
    if not root.is_dir():
        raise PackageError("%s is not a folder." % root)
    files: Dict[str, bytes] = {}
    refused: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        rel_dir = here.relative_to(root).as_posix()
        for name in sorted(dirnames):
            rel = name if rel_dir == "." else "%s/%s" % (rel_dir, name)
            why = "a symlink" if (here / name).is_symlink() else _litter(name)
            if why:
                refused.append("%s (%s)" % (rel, why))
                dirnames.remove(name)
        for name in filenames:
            rel = name if rel_dir == "." else "%s/%s" % (rel_dir, name)
            full = here / name
            why = "a symlink" if full.is_symlink() else (None if full.is_file() else "not a regular file") or _litter(name)
            if why:
                refused.append("%s (%s)" % (rel, why))
                continue
            files[rel] = full.read_bytes()
    if refused:
        raise PackageError("Not packed: remove these or pack a clean copy: " + "; ".join(sorted(refused)))
    return files


def _load_json(data: bytes, what: str) -> Dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=fd._no_duplicates)
    except fd._Duplicate as exc:
        raise PackageError("%s names %s twice in one object." % (what, json.dumps(exc.args[0], ensure_ascii=False))) from None
    except (ValueError, UnicodeDecodeError) as exc:
        raise PackageError("%s is not JSON: %s" % (what, exc)) from None
    if not isinstance(value, dict):
        raise PackageError("%s is not a JSON object." % what)
    return value


def dumps(value: Any, indent: str = "") -> str:
    """``JSON.stringify(value, null, 2)``, so both kits write the same bytes."""
    inner = indent + "  "
    if isinstance(value, dict):
        if not value:
            return "{}"
        return "{\n" + ",\n".join(inner + _jsv.json_string_literal(k) + ": " + dumps(v, inner) for k, v in value.items()) + "\n" + indent + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        return "[\n" + ",\n".join(inner + dumps(v, inner) for v in value) + "\n" + indent + "]"
    return _jsv.jcs(value)


def compose(draft: Dict[str, Any], files: Dict[str, bytes]) -> Tuple[Dict[str, Any], List[str]]:
    """The packed document: the author's fields in their order, ``agentRef`` derived after ``publisher`` for an
    agent, then ``files[]`` (every file but this one, by path) and ``digest``. Old signatures are dropped."""
    notes: List[str] = []
    pkg: Dict[str, Any] = {}
    agent = draft.get("kind") == "agent" and isinstance(draft.get("publisher"), str) and isinstance(draft.get("id"), str)
    if agent:
        derived = agent_ref_of(draft["publisher"], draft["id"])
        if "agentRef" in draft and draft["agentRef"] != derived:
            raise PackageError("agentRef is derived, never chosen: it is %s for this publisher and id (FAC-SEM-066). "
                               "Remove agentRef or fix publisher/id." % derived)
    for key, value in draft.items():
        if key in ("files", "digest", "signatures") or (agent and key == "agentRef"):
            continue
        pkg[key] = value
        if agent and key == "publisher":
            pkg["agentRef"] = agent_ref_of(draft["publisher"], draft["id"])
    if isinstance(draft.get("signatures"), list) and draft["signatures"]:
        notes.append("dropped %d signature(s): a repacked package is signed again" % len(draft["signatures"]))
    pkg["files"] = [{"path": p, "sha256": sha256_of(files[p])} for p in sorted((p for p in files if p != PACKAGE_FILE),
                                                                                  key=lambda p: p.encode("utf-16-be", "surrogatepass"))]
    pkg["digest"] = package_digest(pkg)
    return pkg, notes


def _all_problems(pkg: Dict[str, Any], files: Dict[str, bytes]) -> List[Dict[str, str]]:
    problems = [dict(p, rule="schema") for p in schema_problems(pkg)]
    problems += [dict(p, rule=p["code"]) for p in package_findings(pkg)]
    problems += [{"rule": "folder", "problem": p["problem"], "instancePath": p["path"], "message": p["problem"]} for p in check_package_folder(pkg, files)]
    return problems


def pack(folder: Any, apply: bool = False) -> Dict[str, Any]:
    """Pack ``folder`` (see the module's doc). The answer names the digest, ``agentRef`` and every problem; with
    ``apply`` and no problem, ``fabric.package.json`` is rewritten."""
    root = Path(folder)
    files = read_folder(root)
    if PACKAGE_FILE not in files:
        raise PackageError("Write %s in the folder first: schema, kind, id, version, publisher, licence and, for an agent, "
                           "resultSignal and evals with its receipt. pack fills in agentRef, files[] and digest." % PACKAGE_FILE)
    draft = _load_json(files[PACKAGE_FILE], PACKAGE_FILE)
    pkg, notes = compose(draft, files)
    problems = _all_problems(pkg, files)
    suite = pkg.get("evals", {}).get("suite") if isinstance(pkg.get("evals"), dict) else None
    if isinstance(suite, str) and suite in files and any(p.get("instancePath") == "/evals/receipt/suite" for p in problems):
        notes.append("the suite packed is %s: run it again and write that receipt" % sha256_of(files[suite]))
    answer = {"ok": not problems, "applied": False, "digest": pkg["digest"], "files": len(pkg["files"]), "problems": problems, "notes": notes}
    if pkg.get("kind") == "agent" and "agentRef" in pkg:
        answer["agentRef"] = pkg["agentRef"]
    if apply and not problems:
        fd_write(root / PACKAGE_FILE, dumps(pkg) + "\n")
        answer["applied"] = True
    answer["package"] = pkg
    return answer


def fd_write(path: Path, text: str) -> None:
    """Write through a temporary file in the same folder and rename it over, so a reader never sees half a file."""
    temp = path.with_name(".%s.tmp-%d" % (path.name, os.getpid()))
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def _packed(root: Path) -> Tuple[Dict[str, Any], Dict[str, bytes]]:
    files = read_folder(root)
    if PACKAGE_FILE not in files:
        raise PackageError("%s has no %s: pack it first." % (root, PACKAGE_FILE))
    return _load_json(files[PACKAGE_FILE], PACKAGE_FILE), files


def sign(folder: Any, key_path: Any, role: str = "publisher", kid: Optional[str] = None, apply: bool = False) -> Dict[str, Any]:
    """Add ``role``'s Ed25519 signature over the packed digest. Only a package that is whole and matches its folder is
    signed. The signature of the same role and kid is replaced; a publisher signature is always one."""
    if role not in ("publisher", "organization"):
        raise PackageError("role is publisher or organization.")
    root = Path(folder)
    pkg, files = _packed(root)
    problems = _all_problems(pkg, files)
    if problems:
        return {"ok": False, "applied": False, "problems": problems, "notes": ["pack the folder again before it is signed"]}
    seed, kid = read_signing_key(key_path, kid)
    entry = {"role": role, "alg": "EdDSA", "kid": kid, "sig": _b64url(ed25519_sign(seed, package_signing_input(pkg["digest"], role)))}
    kept = [s for s in pkg.get("signatures", []) if isinstance(s, dict)
            and not (s.get("role") == role and (role == "publisher" or s.get("kid") == kid))]
    signed = dict(pkg)
    signed["signatures"] = ([entry] + kept) if role == "publisher" else (kept + [entry])
    jwk = public_jwk(seed, kid)
    check = verify_package(signed, {role: [jwk]} if role == "publisher" else {"organization": [jwk], "publisher": []})
    if role == "publisher" and not check.get("ok"):
        raise PackageError("The signature does not verify under its own key (%s); nothing was written." % check.get("problem"))
    answer = {"ok": True, "applied": False, "digest": pkg["digest"], "signature": entry, "publicKey": jwk, "problems": [], "notes": []}
    if apply:
        fd_write(root / PACKAGE_FILE, dumps(signed) + "\n")
        answer["applied"] = True
    return answer


def verify(folder: Any, trust: Dict[str, Any], countersigned: bool = False) -> Dict[str, Any]:
    """The folder check, the contract's rules, then verifyPackage against the pinned ``trust``."""
    pkg, files = _packed(Path(folder))
    problems = _all_problems(pkg, files)
    verdict = verify_package(pkg, trust, countersigned)
    return {"ok": bool(verdict.get("ok")) and not problems, "verdict": verdict, "problems": problems}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="fabric_package.py", description="Pack, sign and verify a fabric-package/1 folder.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_pack = sub.add_parser("pack", help="list the files, derive agentRef, compute the digest and check the package")
    p_pack.add_argument("folder")
    mode = p_pack.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="show the package and write nothing (the default)")
    mode.add_argument("--apply", action="store_true", help="write fabric.package.json when nothing is wrong")
    p_sign = sub.add_parser("sign", help="add an Ed25519 signature over the packed digest")
    p_sign.add_argument("folder")
    p_sign.add_argument("--key", required=True, help="a private Ed25519 JWK or PKCS#8 PEM, readable by its owner only")
    p_sign.add_argument("--kid", help="the key's name, when the key file does not carry one")
    p_sign.add_argument("--role", choices=("publisher", "organization"), default="publisher")
    mode = p_sign.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="show the signature and write nothing (the default)")
    mode.add_argument("--apply", action="store_true", help="write the signature into fabric.package.json")
    p_verify = sub.add_parser("verify", help="check the folder and the signatures against pinned keys")
    p_verify.add_argument("folder")
    p_verify.add_argument("--trust", required=True, help='JSON: {"publisher": [jwk...], "organization": [jwk...]}')
    p_verify.add_argument("--countersigned", action="store_true", help="require an organization countersignature")
    args = parser.parse_args(argv)
    try:
        if args.command == "pack":
            answer = pack(args.folder, apply=args.apply)
            answer.pop("package", None) if args.apply else None
        elif args.command == "sign":
            answer = sign(args.folder, args.key, role=args.role, kid=args.kid, apply=args.apply)
        else:
            trust = _load_json(Path(args.trust).read_bytes(), args.trust)
            answer = verify(args.folder, trust, countersigned=args.countersigned)
    except (PackageError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, separators=(",", ":")))
        return 1
    print(dumps(answer))
    return 0 if answer.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
