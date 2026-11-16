#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
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
import errno
import hashlib
import json
import os
import re
import stat as _stat
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_delegation as fd  # noqa: E402
from fabric_secrets import secret_argument, secret_value  # noqa: E402

from fabric_package_rules import (  # noqa: E402,F401 - the rule layer: digest, FAC-SEM-064…066/102, the path rule
    PACKAGE_FILE,
    PLUGIN_MANIFEST,
    SIGNATURE_STATEMENT,
    agent_ref_of,
    sha256_of,
    package_digest,
    package_signing_input,
    _objects,
    _mcp,
    _whole,
    _same_member,
    _no_secret,
    _same_or_absent,
    _agent_ref,
    _mcp_roles,
    _control,
    path_problem,
    _path_fields,
    path_problems,
    package_findings,
)
# DEC-0051: ES256 joins when Fabric records its decision D2; until then a verifier refuses it as unknown-algorithm.
PACKAGE_ALGORITHMS = ("EdDSA",)
from fabric_jsvalue import json_equal as _json_equal  # noqa: E402 - the core's (FAA-65)
from fabric_package_schema import (  # noqa: E402,F401 - the schema reading (FAA-92)
    _JS_DOT,
    JS_WHITESPACE,
    SCHEMA_PATH,
    _SCHEMA_CACHE,
    _schema,
    _type_of,
    _DATE_TIME,
    _URI,
    _MONTH_DAYS,
    _leap,
    _format_ok,
    _PATTERNS,
    _js_pattern,
    _pointer,
    _validate,
    _problems,
    schema_problems,
)
# What pack refuses to list: version-control and cache litter, and files that are credentials by their name, the kit's
# own token files (`service.token`, fabric_auth; `board.credential`, fabric_hub) among them (FAA-190 (15)). Matched
# whole (fullmatch) and with JavaScript's `.`, so a name ending in a newline is judged as fabric-package.mjs judges it.
JUNK = re.compile(r"\.git|__pycache__|\.DS_Store|%s*\.pyc" % _JS_DOT)
SECRET_FILE = re.compile(r"\.env(\.%s+)?|%s*\.(pem|key|p12|pfx|jks|keystore|token|credential)|id_(rsa|dsa|ecdsa|ed25519)|\.(npmrc|netrc|pypirc)"
                         % (_JS_DOT, _JS_DOT))
SECRET_FILE_OK = re.compile(r"\.env\.(example|sample|template)")
#: A file holding a private JWK, whatever its name (FAA-190 (15)): a `d` member of 32 bytes or more in base64url, in
#: JSON, escaped JSON or Python, as the source check's JWK_PRIVATE reads one. A public JWK (no `d`) is no refusal.
PRIVATE_JWK = re.compile(rb"\\?[\"']d\\?[\"'][ \t]*:[ \t]*\\?[\"'][A-Za-z0-9_-]{43}")
_B64URL = re.compile(r"[A-Za-z0-9_-]+")
_PKCS8_ED25519 = bytes.fromhex("302e020100300506032b657004220420")
#: How deep a document read from disk may nest. Python's recursion limit and Node's stack give out at different depths,
#: so both readers refuse past this one, well below either (FAA-78, finding 43); no package document comes near it.
MAX_NESTING = 256


class PackageError(Exception):
    """A refusal a person can act on; the message names what to change."""


from fabric_jsvalue import MISSING as _UNDEFINED  # noqa: E402 - the core's absent value (FAA-65)
from fabric_jsvalue import js_string as _js_string  # noqa: E402 - the core's (FAA-65)
import fabric_jsvalue as _jsv  # noqa: E402 - the core (FAA-65)
import fabric_crypto as _crypto  # noqa: E402 - the core (FAA-65)


# --- Ed25519 signing: the core's (fabric_crypto, RFC 8032 §5.1.6), which never branches on the secret (finding 45) ---

def ed25519_public_key(seed: bytes) -> bytes:
    """The 32-byte public key of a 32-byte Ed25519 seed."""
    if len(seed) != 32:
        raise PackageError("An Ed25519 private key is 32 bytes.")
    return _crypto.ed25519_seed_public_key(seed)


from fabric_crypto import ed25519_sign  # noqa: E402,F401 - the core's: the bytes Node's crypto.sign gives
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
    text = raw.decode("utf-8", "replace").strip(JS_WHITESPACE)  # as JavaScript's trim: a leading BOM goes too
    if text.startswith("{"):
        try:  # past MAX_NESTING no key: Node's JSON.parse reads deeper than Python's stack (FAA-194 (32))
            if _nesting(text) > MAX_NESTING:
                raise ValueError("nested too deeply")
            jwk = json.loads(text, parse_constant=fd._no_constant)  # NaN and Infinity are no JSON, as JSON.parse says
        except (ValueError, RecursionError):
            raise PackageError("The key file is neither a JWK nor a PEM private key.") from None
        if not isinstance(jwk, dict) or jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519" or not isinstance(jwk.get("d"), str):
            raise PackageError("The key file must be an Ed25519 private JWK (kty OKP, crv Ed25519, with d).")
        if jwk.get("alg", "EdDSA") != "EdDSA":
            raise PackageError("The key names alg %r; a package signature is EdDSA (DEC-0051)." % jwk.get("alg"))
        seed = _crypto.b64url_decode(jwk["d"]) if _B64URL.fullmatch(jwk["d"]) else b""
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
    if not isinstance(kid, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", kid):
        raise PackageError("Name the key with --kid (1-128 of A-Z a-z 0-9 . _ : -): the installing machine pins it by that name.")
    return seed, kid


# --- the folder check and the verifier ------------------------------------------------------------------

def _json_int(text: str) -> Any:
    """An integer literal as JSON.parse reads it: one longer than a Python with `int_max_str_digits` reads is a float,
    as a JavaScript number is (FAA-194 (36))."""
    return int(text) if len(text) <= 4000 else float(text)


def _parsed(data: Optional[bytes]) -> Optional[Dict[str, Any]]:
    """A plugin or provider manifest as the contract's checkPackageFolder reads it: decoded with replacement characters
    (`Buffer.toString`, FAA-194 (29)); NaN or Infinity, or nesting past MAX_NESTING (the limit both kits share, FAA-194
    (27)), is no manifest."""
    if data is None:
        return None
    text = data.decode("utf-8", "replace")
    if _nesting(text) > MAX_NESTING:
        return None
    try:
        value = json.loads(text, parse_constant=fd._no_constant, parse_int=_json_int)
    except (ValueError, RecursionError):
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
        if plugin is None or not _same_member(plugin, "name", pkg.get("id", _UNDEFINED)) or not _same_member(plugin, "version", pkg.get("version", _UNDEFINED)):
            problems.append({"problem": "plugin-manifest", "path": PLUGIN_MANIFEST})
    provider = pkg.get("provider")
    if isinstance(provider, str) and provider in files:
        manifest = _parsed(files.get(provider))
        if manifest is None or ("costPresets" in manifest and not ("costPresets" in pkg and _json_equal(manifest["costPresets"], pkg["costPresets"]))):
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
    if (jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519" or not isinstance(x, str) or not _B64URL.fullmatch(x)
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
                or not isinstance(entry.get("kid"), str) or not isinstance(entry.get("sig"), str) or not _B64URL.fullmatch(entry["sig"])):
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
    if JUNK.fullmatch(name):
        return "litter"
    if SECRET_FILE.fullmatch(name) and not SECRET_FILE_OK.fullmatch(name):
        return "a credential file"
    return None


#: Opening a packaged file: never through a link, never waiting on a pipe (FAA-78, finding 42). Folders are opened
#: without following a link too, and what is in one is opened relative to it, so a folder swapped for a link mid-walk is
#: never followed either; where the platform has no such calls (Windows), the walk goes by path.
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_RDONLY | _NOFOLLOW | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
_DIR_FLAGS = os.O_RDONLY | _NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
_LINK_ERRNOS = (errno.ELOOP, errno.EMLINK)  # open() on a link it may not follow: ELOOP (Linux, macOS), EMLINK (FreeBSD)
_BY_FOLDER = bool(_NOFOLLOW) and hasattr(os, "O_DIRECTORY") and os.open in os.supports_dir_fd and os.scandir in getattr(os, "supports_fd", set())


def _unreadable(rel: str, exc: OSError) -> PackageError:
    """``Cannot read <path>: EACCES.``: the error's symbolic name, as Node's error.code names it."""
    return PackageError("Cannot read %s: %s." % (rel or ".", errno.errorcode.get(exc.errno or -1) or exc.strerror or exc))


def _read_file(name: str, dir_fd: Optional[int]) -> Tuple[Optional[bytes], Optional[str]]:
    """``(bytes, None)`` for a regular file, ``(None, why)`` for a link or anything else. Raises OSError."""
    try:
        handle = os.open(name, _FILE_FLAGS, dir_fd=dir_fd)
    except OSError as exc:
        if _NOFOLLOW and exc.errno in _LINK_ERRNOS:
            return None, "a symlink"
        raise
    try:
        if not _stat.S_ISREG(os.fstat(handle).st_mode):
            return None, "not a regular file"
        chunks = []
        while True:
            chunk = os.read(handle, 1 << 20)
            if not chunk:
                return b"".join(chunks), None
            chunks.append(chunk)
    finally:
        os.close(handle)


def _walk(here: Any, rel: str, files: Dict[str, bytes], refused: List[str]) -> None:
    """One folder: ``here`` is its descriptor when the walk goes by folder, else its path."""
    by_fd = isinstance(here, int)
    try:
        with os.scandir(here) as listing:
            entries = sorted(listing, key=lambda e: e.name)
    except OSError as exc:
        raise _unreadable(rel, exc) from None
    for entry in entries:
        where = "%s/%s" % (rel, entry.name) if rel else entry.name
        try:
            why = "a symlink" if entry.is_symlink() else _litter(entry.name)
            folder = entry.is_dir(follow_symlinks=False)
            if why is None and not folder and not entry.is_file(follow_symlinks=False):
                why = "not a regular file"
            if why is None and folder:
                inner = os.open(entry.name, _DIR_FLAGS, dir_fd=here) if by_fd else entry.path
                try:
                    _walk(inner, where, files, refused)
                finally:
                    if by_fd:
                        os.close(inner)
                continue
            if why is None:
                data, why = _read_file(entry.name if by_fd else entry.path, here if by_fd else None)
                if why is None and PRIVATE_JWK.search(data):  # type: ignore[arg-type]
                    why = "a private key (a JWK's d)"
                if why is None:
                    files[where] = data  # type: ignore[assignment]
                    continue
        except OSError as exc:
            if not (_NOFOLLOW and exc.errno in _LINK_ERRNOS):
                raise _unreadable(where, exc) from None
            why = "a symlink"
        refused.append("%s (%s)" % (where, why))


def read_folder(folder: Any) -> Dict[str, bytes]:
    """Every regular file under ``folder`` by its forward-slash path. Refuses a symlink, a special file, version-control
    or cache litter, a file that is a credential by its name and a file holding a private JWK, each named, so the person can remove it or pack a
    clean copy. A file or folder it cannot read is a refusal naming it (``Cannot read <path>: EACCES.``), never
    skipped (FAA-78, finding 41); a file is opened without following a link and read only when it is a regular file
    (finding 42)."""
    root = Path(folder)
    if not root.is_dir():
        raise PackageError("%s is not a folder." % root)
    files: Dict[str, bytes] = {}
    refused: List[str] = []
    try:
        top = os.open(str(root), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)) if _BY_FOLDER else str(root)
    except OSError as exc:
        raise _unreadable(str(root), exc) from None
    try:
        _walk(top, "", files, refused)
    finally:
        if _BY_FOLDER:
            os.close(top)  # type: ignore[arg-type]
    if refused:
        raise PackageError("Not packed: pack a clean copy (what Git would commit, references/package.md); delete only litter and credential files in place: " + "; ".join(sorted(refused)))
    return files


def _nesting(text: str) -> int:
    """How deep the arrays and objects of a JSON text nest, read without recursion (strings skipped)."""
    depth = deepest = 0
    i, end = 0, len(text)
    while i < end:
        ch = text[i]
        if ch == '"':
            i += 1
            while i < end and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif ch in "[{":
            depth += 1
            deepest = max(deepest, depth)
        elif ch in "]}":
            depth -= 1
        i += 1
    return deepest


def _load_json(data: bytes, what: str) -> Dict[str, Any]:
    """A JSON object from strict UTF-8 bytes: no member named twice, nesting at most MAX_NESTING deep. Every refusal
    is a PackageError, never a traceback (a RecursionError included)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PackageError("%s is not JSON: %s" % (what, exc)) from None
    if _nesting(text) > MAX_NESTING:
        raise PackageError("%s nests deeper than %d levels." % (what, MAX_NESTING))
    try:
        value = json.loads(text, object_pairs_hook=fd._no_duplicates, parse_constant=fd._no_constant)
    except fd._Duplicate as exc:
        raise PackageError("%s names %s twice in one object." % (what, json.dumps(exc.args[0], ensure_ascii=False))) from None
    except (ValueError, RecursionError) as exc:
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
    try:
        pkg["digest"] = package_digest(pkg)
    except TypeError as exc:
        raise PackageError("%s has no RFC 8785 form, so it has no digest: %s" % (PACKAGE_FILE, exc)) from None
    return pkg, notes


#: The agent's source manifest (contract DEC-0149, ``fabric-source/1``): when the folder carries one, ``pack`` writes
#: ``secrets[]`` from its secret slots and ``state[]`` from its store slots' paths, and FAC-SEM-160 holds them equal.
SOURCE_FILE = "fabric.source.json"


def _source_manifest(files: Dict[str, bytes]) -> Optional[Dict[str, Any]]:
    """The folder's source manifest, or None when it has none; a refusal when it is no ``fabric-source/1`` object."""
    if SOURCE_FILE not in files:
        return None
    source = _load_json(files[SOURCE_FILE], SOURCE_FILE)
    if source.get("format") != "fabric-source/1":
        raise PackageError("%s is not a fabric-source/1 manifest (its format member)." % SOURCE_FILE)
    return source


def source_members(source: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """``secrets[]`` from the secret slots (name, purpose, optional) and ``state[]`` from the store slots (path, purpose)."""
    secrets: List[Dict[str, Any]] = []
    state: List[Dict[str, Any]] = []
    for slot in _objects(source.get("slots")):
        if slot.get("kind") == "secret" and isinstance(slot.get("name"), str):
            secrets.append(dict({"name": slot["name"], "purpose": slot.get("purpose")}, **({"optional": True} if slot.get("optional") is True else {})))
        elif slot.get("kind") == "store" and isinstance(slot.get("path"), str):
            state.append({"path": slot["path"], "purpose": slot.get("purpose")})
    return secrets, state


def source_package_findings(source: Any, pkg: Any) -> List[Dict[str, str]]:
    """FAC-SEM-160 (contract ``sourcePackageFindings``): the package's secrets[] are the source's secret slots, by name
    and optional; its state[] paths are the store slots' paths when state[] holds any entry."""
    if not isinstance(source, dict) or not isinstance(pkg, dict):
        return []
    out: List[Dict[str, str]] = []

    def flag(at: str, message: str) -> None:
        out.append({"code": "FAC-SEM-160", "instancePath": at, "message": message})
    slots = _objects(source.get("slots"))
    secrets = {s["name"]: s.get("optional") is True for s in slots if s.get("kind") == "secret" and isinstance(s.get("name"), str)}
    stores = list(dict.fromkeys(s["path"] for s in slots if s.get("kind") == "store" and isinstance(s.get("path"), str)))
    packaged = [(e, i) for i, e in enumerate(pkg.get("secrets") if isinstance(pkg.get("secrets"), list) else []) if isinstance(e, dict)]
    names = {e.get("name") for e, _ in packaged}
    for name in secrets:
        if name not in names:
            flag("/package/secrets", "the source's secret slot %s is not in the package's secrets[]" % name)
    for entry, index in packaged:
        name = entry.get("name")
        if not isinstance(name, str) or name not in secrets:
            flag("/package/secrets/%d/name" % index, "secrets[%d] is no secret slot of the source" % index)
        elif secrets[name] != (entry.get("optional") is True):
            flag("/package/secrets/%d/optional" % index, "secrets[%d] is %soptional in the source" % (index, "" if secrets[name] else "not "))
    state = pkg.get("state")
    if not isinstance(state, list) or not state:
        return out
    paths = {e.get("path") for e in _objects(state)}
    for path in stores:
        if path not in paths:
            flag("/package/state", "a store slot's path of the source is not in the package's state[]")
    for index, entry in ((i, e) for i, e in enumerate(state) if isinstance(e, dict)):
        if not isinstance(entry.get("path"), str) or entry["path"] not in stores:
            flag("/package/state/%d/path" % index, "state[%d] is no store slot of the source" % index)
    return out


def _all_problems(pkg: Dict[str, Any], files: Dict[str, bytes]) -> List[Dict[str, str]]:
    problems = [dict(p, rule="schema") for p in schema_problems(pkg)]
    if SOURCE_FILE in files:
        try:
            problems += [dict(p, rule=p["code"]) for p in source_package_findings(_source_manifest(files), pkg)]
        except PackageError as exc:
            problems.append({"rule": "source", "instancePath": "/files", "message": str(exc)})
    problems += [dict(p, rule="path") for p in path_problems(pkg)]
    problems += [dict(p, rule=p["code"]) for p in package_findings(pkg)]
    problems += [{"rule": "folder", "problem": p["problem"], "instancePath": p["path"], "message": FOLDER_MESSAGES.get(p["problem"], p["problem"])}
                 for p in check_package_folder(pkg, files)]
    return problems


#: What a folder problem means, where its code alone does not say what to change (FAA-193).
FOLDER_MESSAGES = {
    "provider-manifest": "provider-manifest: the provider manifest must be a JSON object, and when it carries costPresets "
                         "fabric.package.json must carry the same costPresets (copy them; pack does not)",
}


def _secrets_lacking(draft: Dict[str, Any], secrets: List[Dict[str, Any]]) -> List[str]:
    """The names a hand-written secrets[] declares that the source manifest has no secret slot for, in their order."""
    have = {s["name"] for s in secrets}
    declared = draft.get("secrets") if isinstance(draft.get("secrets"), list) else []
    lacking: List[str] = []
    for entry in declared:
        name = entry.get("name") if isinstance(entry, dict) else None
        if isinstance(name, str) and name not in have and name not in lacking:
            lacking.append(name)
    return lacking


def _lacking_message(lacking: List[str]) -> str:
    return ("%s declares no secret slot for %s, which %s's secrets[] names: pack writes secrets[] from the manifest's "
            "slots and never drops a declared secret. Add each as a slot of kind secret to %s (or take it out of "
            "secrets[]), then pack again" % (SOURCE_FILE, ", ".join(lacking), PACKAGE_FILE, SOURCE_FILE))


def pack(folder: Any, apply: bool = False) -> Dict[str, Any]:
    """Pack ``folder`` (see the module's doc). The answer names the digest, ``agentRef`` and every problem; with
    ``apply`` and no problem, ``fabric.package.json`` is rewritten."""
    root = Path(folder)
    files = read_folder(root)
    if PACKAGE_FILE not in files:
        raise PackageError("Write %s in the folder first: schema, kind, id, version, publisher, licence and, for an agent, "
                           "resultSignal and evals with its receipt. pack fills in agentRef, files[] and digest." % PACKAGE_FILE)
    draft = _load_json(files[PACKAGE_FILE], PACKAGE_FILE)
    source = _source_manifest(files)
    written: List[str] = []
    refused: List[Dict[str, str]] = []
    if source is not None:  # DEC-0149: secrets[] and state[] come from the source manifest's slots
        secrets, state = source_members(source)
        lacking = _secrets_lacking(draft, secrets)
        if lacking:  # a declared secret is never dropped: the manifest gains its slot first
            refused.append({"rule": "source", "instancePath": "/secrets", "message": _lacking_message(lacking)})
        elif secrets or "secrets" in draft:
            draft["secrets"] = secrets
            written.append("secrets[]")
        if state and draft.get("state") != []:  # an empty state[] is a copy packed without state, kept
            draft["state"] = state
            written.append("state[]")
    pkg, notes = compose(draft, files)
    if written:
        notes.append("%s written from %s" % (" and ".join(written), SOURCE_FILE))
    problems = refused + _all_problems(pkg, files)
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
    """Write through a temporary file and rename it over; bytes, as the Node kit writes them (text mode: \r\n on Windows)."""
    temp = path.with_name(".%s.tmp-%d" % (path.name, os.getpid()))
    temp.write_bytes(text.encode("utf-8"))
    os.replace(temp, path)


def _packed(root: Path) -> Tuple[Dict[str, Any], Dict[str, bytes]]:
    files = read_folder(root)
    if PACKAGE_FILE not in files:
        raise PackageError("%s has no %s: pack it first." % (root, PACKAGE_FILE))
    return _load_json(files[PACKAGE_FILE], PACKAGE_FILE), files


def _key_outside(root: Path, key_path: Any) -> None:
    """Refuse a key file inside the folder being signed (FAA-190 (15)): it would ship in the package. Judged by where
    the key resolves to and by the folder's identity (device and inode), so a link to the key, a path through a linked
    folder and a case-folding file system do not hide it. A folder or key that cannot be read is judged later."""
    try:
        home = os.stat(str(root))
    except OSError:
        return
    # a file system with no inode numbers (0, as FAT on Windows) is judged by the resolved path alone
    where = os.path.normcase(os.path.realpath(os.path.abspath(str(root))))
    place = os.path.realpath(os.path.abspath(str(key_path)))
    while True:
        parent = os.path.dirname(place)
        if parent == place:
            return
        place = parent
        try:
            here = os.stat(place)
        except OSError:
            continue
        if (home.st_ino and (here.st_dev, here.st_ino) == (home.st_dev, home.st_ino)) or os.path.normcase(place) == where:
            raise PackageError("The key file %s is inside the folder being signed; keep it outside the package." % key_path)


def sign(folder: Any, key_path: Any, role: str = "publisher", kid: Optional[str] = None, apply: bool = False) -> Dict[str, Any]:
    """Add ``role``'s Ed25519 signature over the packed digest. Only a package that is whole and matches its folder is
    signed. The signature of the same role and kid is replaced; a publisher signature is always one."""
    if role not in ("publisher", "organization"):
        raise PackageError("role is publisher or organization.")
    root = Path(folder)
    _key_outside(root, key_path)
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


def _emit(text: str) -> None:
    """One answer line, UTF-8 and \\n as the Node kit writes it, whatever the locale (a Windows pipe is cp1252; FAA-72)."""
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:  # a stream a caller put in place takes text
        sys.stdout.write(text + "\n")
        return
    sys.stdout.flush()
    buffer.write((text + "\n").encode("utf-8"))
    buffer.flush()


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
        _emit(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, separators=(",", ":")))
        return 1
    _emit(dumps(answer))
    return 0 if answer.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
