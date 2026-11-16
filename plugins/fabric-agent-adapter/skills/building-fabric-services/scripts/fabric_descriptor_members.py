# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
"""A service descriptor's members (fabric-service/0.1; DEC-0061, DEC-0069, FAA-120): `installedBy`, `runner`, `peer`
and `source`, read as the schema shapes them, the `source.repository` rule and a git origin's identity (DEC-0089 item
2), and the host's peer check. Every function answers by a rule and touches no file; fabric_descriptor re-exports every
name here. Part of the service kit (split from fabric_descriptor; layer L3); the twin of `fabric-descriptor-members.mjs`."""
# Example URLs write their scheme in angle brackets: read `<https>` as `https` (FAA-212).
from __future__ import annotations

import ipaddress
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
from fabric_jsvalue import _JS_SPACE  # noqa: E402 - L0: JavaScript's \s, as the contract's normalizeOrigin reads it


_RESERVED_HOST = re.compile(r"(^|\.)(localhost|local|internal|home\.arpa|lan|localdomain)\Z")


_HIERARCHICAL = re.compile(r"\A[A-Za-z][A-Za-z0-9+.-]*://")


def source_repository_problem(repository: Any) -> Optional[str]:
    """Why a value is no `source.repository` the kit takes, or None: validate_descriptor's reading (FAA-198)."""
    import fabric_secrets  # noqa: E402 - beside this file; the contract's detector (DEC-0044)
    if not (isinstance(repository, str) and _SOURCE_URI.match(_IP_LITERAL.sub(r"\1h", repository, count=1))):
        return "source.repository is a URI (RFC 3986), such as https://github.com/owner/name"
    if _URI_PASSWORD.match(repository):  # before the host: user information is a credential, said as one
        return "source.repository carries no password: it names the repository, never a credential"
    if "@" in repository and not _HIERARCHICAL.match(repository):  # 0.62.0 readings 7: never an scp form's user
        # before the authority, whose two-slash rule would name `<https>:u@h/r` less usefully (0.86.0)
        return "source.repository with a user is a URL with an authority (https://user@host/path), never an scp form"
    if not _authority_ok(repository):
        return "source.repository names a host, and a port of digits up to 65535 when it has one"
    if fabric_secrets.repository_credential(repository):  # its name is no key (0.62.0 seam reading 6)
        return ("FAC-SEM-086: /source/repository holds a value shaped like a credential; it names a repository: write "
                "the repository's name in lower case if it is one")
    return None


_ORIGIN_SCHEMES, _S = ("http", "https", "ssh", "git", "git+ssh", "git+https"), re.escape(_JS_SPACE)  # normalizeOrigin's
_ORIGIN_SCP = re.compile(r"(?:[^@/%s]+@)?([^:/%s]+):([^%s]+)" % (_S, _S, _S))


def origin_identity(raw: Any) -> Optional[str]:
    """A remote's repository identity `host/path`, or None: the contract's normalizeOrigin (DEC-0089 item 2), held to
    its origin vectors (test/fixtures/contract/origin-vectors.json)."""
    if not isinstance(raw, str) or len(raw) > 4096:
        return None
    value = raw.strip(_JS_SPACE)
    scheme = re.match(r"[A-Za-z][A-Za-z0-9+.-]*(?=://)", value)
    if scheme:
        if scheme.group(0).lower() not in _ORIGIN_SCHEMES:
            return None
        host, slash, path = re.split(r"[?#]", value[scheme.end() + 3:], maxsplit=1)[0].partition("/")
        if not slash:
            return None
    else:
        scp = None if value.startswith(("/", ".")) or re.match(r"[A-Za-z]:[\\/]", value) else _ORIGIN_SCP.fullmatch(value)
        if not scp:
            return None
        host, path = scp.group(1), re.split(r"[?#]", scp.group(2), maxsplit=1)[0]
    lower = lambda text: re.sub("[A-Z]", lambda letter: letter.group(0).lower(), text)  # noqa: E731 - A to Z alone
    host = lower(re.sub(r":[0-9]*\Z", "", host[host.rfind("@") + 1:], count=1))
    path = lower(path.strip("/"))
    segments = (path[:-4] if path.endswith(".git") else path).split("/")
    if (not re.fullmatch(r"[a-z0-9.-]+", host) or "." not in host or len(segments) < 2
            or any(not segment or re.search("[%s]" % _S, segment) for segment in segments)):
        return None
    return "%s/%s" % (host, "/".join(segments))


def repository_from_origin(origin: Any) -> Optional[str]:
    """An installer's git origin (scp form included) as the `https://host/owner/name` source.repository takes, or None
    (no identity, or one the kit's rules refuse: no URI, a key's shape); no credential of it travels (FAA-200 (45))."""
    identity = origin_identity(origin)
    repository = None if identity is None else "https://" + identity
    return None if repository is None or source_repository_problem(repository) else repository


def _shown_member(name: Any) -> str:
    """A member name as a problem prints it: `<redacted>` when it is shaped like a credential, since a hand-edited
    descriptor may carry a key as a member name (FAA-200 (39)). The Node twin is shownMember."""
    import fabric_secrets  # noqa: E402 - beside this file; the contract's detector (DEC-0044)
    return "<redacted>" if fabric_secrets.secret_argument(str(name)) else str(name)


def _secret_launch_argument(value: str) -> bool:
    """A command argument that carries a credential, a URL inside it read as a URL (FAC-SEM-057, FAA-200 (28))."""
    import fabric_secrets  # noqa: E402 - beside this file
    return fabric_secrets.secret_launch_argument(value)


#: The organization edition's data classes, least sensitive first (DEC-0061, DEC-0053).
PEER_DATA_CLASSES = ("public", "internal", "confidential", "restricted")


#: The kind of a runner's sign-in, never a credential's value (DEC-0061).
CREDENTIAL_KINDS = ("subscription", "key", "platform-metered", "none")


#: A subscription runs only in its vendor's runner (DEC-0046): runner kind → login.
SUBSCRIPTION_RUNNERS = {"claude-code": "claude", "kimi-code": "kimi", "codex": "chatgpt"}


_PEER_ENDPOINT = re.compile(r"^https://(?P<host>([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63})(:([1-9][0-9]{0,3}|[1-5][0-9]{4}|6[0-4][0-9]{3}|65[0-4][0-9]{2}|655[0-2][0-9]|6553[0-5]))?(/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*)?\Z", re.ASCII)


# FAA-120: source.repository is the schema's common `uri`: RFC 3986 characters only (unreserved, reserved and %HH),
# the same in both twins; an authority, when there is one, names a host and a port of digits up to 65535, as Fabric's
# `new URL` reads it. A user:password@ in it is a credential, never the name of a repository.
_SOURCE_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:(?:[A-Za-z0-9._~:/?#@!$&'()*+,;=-]|%[0-9A-Fa-f]{2})+\Z")
# Brackets belong to an IP-literal host only (RFC 3986 3.2.2); the literal is set aside before the character check.
_IP_LITERAL = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*://(?:[^/?#@\[\]]*@)?)\[[0-9A-Fa-f:.vV]+\]")
# A special scheme's authority starts after any run of slashes, none included, as `new URL` reads it, so
# <https>:github.com:99999/o/r is read for its port too (FAA-200 (56)); any other scheme has one only after `//`.
# A special scheme's repository is written with exactly two slashes: `new URL` also reads <https>:github.com/o/r and
# <https>:////github.com/o/r, which no repository-match rule (the kit's three, Fabric's repoKey) joins to a checkout.
_URI_AUTHORITY = re.compile(r"^(?:(?P<special>[Hh][Tt][Tt][Pp][Ss]?|[Ww][Ss][Ss]?|[Ff][Tt][Pp]):(?P<slashes>/*)|[A-Za-z][A-Za-z0-9+.-]*://)"
                            r"(?:[^/?#@]*@)?(?P<host>\[[^\]]*\]|[^/?#:]*)(?::(?P<port>[^/?#]*))?")
# A special scheme (http, https, ws, wss, ftp) reads a user:password@ after any run of slashes, none included, as
# `new URL` does: <https>:bot:pw@host carries the password too (0.56.0 seam r7).
# The user part stops at its first colon: the same verdict (a colon, then an @, in the user information) read in linear
# time, where a user part that may hold colons backtracked quadratically on a run of them (FAA-200 (44)).
_URI_PASSWORD = re.compile(r"^(?:(?:[Hh][Tt][Tt][Pp][Ss]?|[Ww][Ss][Ss]?|[Ff][Tt][Pp]):[/\\]*[^/\\?#:]*:[^/\\?#]*@"
                           # any other scheme: a backslash belongs to the user information (seam r8)
                           r"|(?![Hh][Tt][Tt][Pp][Ss]?:|[Ww][Ss][Ss]?:|[Ff][Tt][Pp]:)[A-Za-z][A-Za-z0-9+.-]*://[^/?#:]*:[^/?#]*@)")


_RESIDENCY = re.compile(r"^(A[B-Z]|[B-PR-WY][A-Z]|Q[A-L]|Z[A-Y])\Z", re.ASCII)


_RUNNER_KIND_NAME = re.compile(r"^[a-z][a-z0-9-]{1,62}\Z", re.ASCII)


def _pointer(name: str) -> str:
    """A JSON Pointer token (RFC 6901 §4)."""
    return str(name).replace("~", "~0").replace("/", "~1")


def _text(value: Any, low: int = 1, high: int = 200) -> bool:
    return isinstance(value, str) and low <= len(value) <= high


def _authority_ok(uri: str) -> bool:
    m = _URI_AUTHORITY.match(uri)
    if not m:
        return True
    port, host = m.group("port"), m.group("host")
    if not host or not (port is None or port == "" or (port.isdigit() and len(port) <= 5 and int(port) <= 65535)):
        return False
    return not m.group("special") or (m.group("slashes") == "//" and _special_host_ok(host))


def _ipv4_number(part: str) -> Optional[int]:
    """The WHATWG URL standard's IPv4 number parser: decimal, 0x hexadecimal or 0-led octal; None on failure."""
    radix = 10
    if part[:2] in ("0x", "0X"):
        part, radix = part[2:], 16
    elif len(part) > 1 and part[0] == "0":
        part, radix = part[1:], 8
    if part == "":
        return 0
    digits = {10: "0123456789", 16: "0123456789abcdefABCDEF", 8: "01234567"}[radix]
    return int(part, radix) if all(c in digits for c in part) else None


def _special_host_ok(host: str) -> bool:
    """FAA-200 (37): a special scheme's host as `new URL` would accept it, so Fabric's registry never drops the
    descriptor as manifest-invalid. A host is written as it is, never percent-encoded (no repository host needs it,
    and both twins refuse every `%` rather than mirror the decoding); a bracketed host is an IPv6 address; a host
    whose last label is a number is a whole IPv4 address (each part up to 255, the last filling what is left)."""
    if "%" in host:
        return False
    if host.startswith("["):
        try:
            ipaddress.IPv6Address(host[1:-1])
        except ValueError:
            return False
        return host.endswith("]")
    parts = host.split(".")
    if len(parts) > 1 and parts[-1] == "":
        parts = parts[:-1]
    last = parts[-1]
    if not ((last != "" and last.isdigit() and last.isascii()) or (last != "" and _ipv4_number(last) is not None)):
        return True  # a domain: its code points are the source rule's, none of them one `new URL` forbids
    numbers = [_ipv4_number(p) if p else None for p in parts]
    if len(parts) > 4 or None in numbers:
        return False
    return all(n <= 255 for n in numbers[:-1]) and numbers[-1] < 256 ** (5 - len(numbers))


def descriptor_member_problems(descriptor: Dict[str, Any]) -> List[str]:
    """DEC-0061 and DEC-0069 on a descriptor's `installedBy`, `runner` and `peer`, and `source` (FAA-120), as the schema shapes them, with
    FAC-SEM-085 (a peer on a reserved name) and FAC-SEM-086 (a credential-shaped value in `runner` or `installedBy`,
    named by its place, never its value)."""
    import fabric_secrets  # noqa: E402 - beside this file; the contract's detector (DEC-0044)
    problems: List[str] = []
    life = descriptor.get("lifecycle") if isinstance(descriptor.get("lifecycle"), dict) else {}
    by = descriptor.get("installedBy")
    places: List[Tuple[str, Any]] = []
    if isinstance(by, str):
        if not _text(by):
            problems.append("installedBy is the installer and its version, 1 to 200 characters")
        places.append(("/installedBy", by))
    elif isinstance(by, dict):
        problems += ["installedBy has no member %s" % _shown_member(k) for k in by if k not in ("by", "role", "tool")]
        if by.get("by") not in ("person", "node", "organization"):
            problems.append("installedBy.by is person, node or organization")
        if by.get("by") == "person" and by.get("role") not in ("operator", "administrator"):
            problems.append("installedBy.role is operator or administrator for a person")
        if by.get("by") != "person" and "role" in by:
            problems.append("installedBy.role belongs to a person only")
        if not _text(by.get("tool")):
            problems.append("installedBy.tool is the installer and its version, 1 to 200 characters")
        places += [("/installedBy/%s" % _pointer(_shown_member(k)), v) for k, v in by.items()]
    else:
        problems.append("installedBy is the installer's name or {by, role?, tool}")
    if life.get("manager") == "person" and not (isinstance(by, dict) and by.get("by") == "person"):
        problems.append("an app's descriptor names who installed it as a person: installedBy {by: person, role, tool} (DEC-0069)")
    runner = descriptor.get("runner")
    if "runner" in descriptor:
        if not isinstance(runner, dict):
            problems.append("runner is {kind?, credentialKind}")
            runner = {}
        problems += ["runner has no member %s" % _shown_member(k) for k in runner if k not in ("kind", "credentialKind")]
        if runner.get("credentialKind") not in CREDENTIAL_KINDS:
            problems.append("runner.credentialKind is subscription, key, platform-metered or none")
        if "kind" in runner and not (isinstance(runner["kind"], str) and _RUNNER_KIND_NAME.match(runner["kind"])):
            problems.append("runner.kind is a runner kind's name")
        # a kind that is no string is no runner's (a list would raise as a key: 0.62.0 unit reading 17)
        if runner.get("credentialKind") == "subscription" and not (isinstance(runner.get("kind"), str)
                                                                    and runner["kind"] in SUBSCRIPTION_RUNNERS):
            problems.append("a subscription runs only in its vendor's runner: runner.kind claude-code, kimi-code or codex")
        places += [("/runner/%s" % _pointer(_shown_member(k)), v) for k, v in runner.items()]
    if "source" in descriptor:
        source = descriptor.get("source")
        if not isinstance(source, dict):
            problems.append("source is {repository?}")
            source = {}
        problems += ["source has no member %s" % _shown_member(k) for k in source if k != "repository"]
        problem = source_repository_problem(source["repository"]) if "repository" in source else None
        if problem:
            problems.append(problem)
    if "peer" in descriptor:
        peer = descriptor.get("peer")
        if not isinstance(peer, dict):
            problems.append("peer is {endpoint, custody, residency, maxDataClass}")
            peer = {}
        problems += ["peer has no member %s" % _shown_member(k) for k in peer if k not in ("endpoint", "custody", "residency", "maxDataClass")]
        endpoint = peer.get("endpoint")
        match = _PEER_ENDPOINT.match(endpoint) if isinstance(endpoint, str) and len(endpoint) <= 2048 else None
        if not match:
            problems.append("peer.endpoint is https://<dns-name>[:<port>][/<path>], no query, fragment, userinfo or IP literal")
        elif _RESERVED_HOST.search(match.group("host")):
            problems.append("FAC-SEM-085: a service offered to others cannot be reached at the reserved name %s" % match.group("host"))
        if peer.get("custody") not in ("organization-managed", "personal", "processor-hosted"):  # processor-hosted: DEC-0099
            problems.append("peer.custody is organization-managed, personal or processor-hosted")
        residency = peer.get("residency")
        if (not isinstance(residency, list) or not 1 <= len(residency) <= 32 or len(set(map(json.dumps, residency))) != len(residency)
                or not all(isinstance(r, str) and _RESIDENCY.match(r) for r in residency)):
            problems.append("peer.residency is 1 to 32 distinct ISO 3166-1 alpha-2 codes in upper case, EU admitted, no user-assigned code")
        if peer.get("maxDataClass") not in PEER_DATA_CLASSES:
            problems.append("peer.maxDataClass is public, internal, confidential or restricted")
        if "runner" not in descriptor:
            problems.append("a service offered to others declares runner (DEC-0061)")
        elif isinstance(runner, dict) and runner.get("credentialKind") == "subscription":
            problems.append("a service offered to others never runs on a subscription (DEC-0061)")
    for place, value in places:
        if isinstance(value, str) and fabric_secrets.secret_argument(value):
            # places are /installedBy and /runner alone: /source/repository has its own check above (FAA-200 (57))
            problems.append("FAC-SEM-086: %s holds a value shaped like a credential; it names a kind, a role or an "
                            "installer" % place)
    return problems


def peer_refusal(descriptor: Any, data_class: Any) -> Optional[str]:
    """The host's check before it routes a request from anyone but the service's operator (DEC-0061, FAC-SEM-088):
    `not-offered` (no `peer`), `peer-invalid` (its maximum is not one of the four classes), `data-class-unknown` (the
    request's class is not one of them, exactly as written) or `above-max-data-class`; None when it may. The contract's
    `peerRefusal`."""
    if not isinstance(descriptor, dict) or not isinstance(descriptor.get("peer"), dict):
        return "not-offered"
    ceiling = descriptor["peer"].get("maxDataClass")
    if not isinstance(ceiling, str) or ceiling not in PEER_DATA_CLASSES:
        return "peer-invalid"
    if not isinstance(data_class, str) or data_class not in PEER_DATA_CLASSES:
        return "data-class-unknown"
    return "above-max-data-class" if PEER_DATA_CLASSES.index(data_class) > PEER_DATA_CLASSES.index(ceiling) else None
