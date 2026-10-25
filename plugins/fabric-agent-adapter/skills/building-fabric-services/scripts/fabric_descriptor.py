"""How a service is found (fabric-service/0.1): its descriptor, peers and app descriptors (DEC-0061, DEC-0069),
build identity and the well-known document, the loopback HTTP server. Part of the service kit (FAA-65, layer L3)."""
from __future__ import annotations

import hashlib
import http.server
import json
import os
import re
import socketserver
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
from fabric_base import (
    PROTOCOL,
    ServiceError,
    _ID,
    _INSTANCE,
    _LOCAL_PATH,
    _TASK,
    _UNIT,
    expand,
    now_iso,
)
from fabric_paths import (
    atomic_write,
    ensure_private_dir,
    services_dir,
)
from fabric_protocols import (
    protocols_findings,
)
from fabric_connections import CONNECTIONS_EXTENSION_KEY, connections_view  # noqa: E402 - the kit (FAA-62)
from fabric_usage import (
    ROUTES,
)


# The embedded dashboard declaration (fabric-dashboard/0.1, DEC-0036 ED-9), under the well-known
# document's `extensions`. The kit is assets/dashboard-kit; its version is the one in kit.json.
DASHBOARD_EXTENSION_KEY = "https://fabric.passioncode.ai/agent-contract/extensions/dashboard/0.1"


DASHBOARD_KIT = "fabric-dashboard-kit@1.1.4"


REFERENCE_THEMES = ("graphite", "fabric", "paper", "forest", "ocean", "ember", "contrast")


STATUSES = ("starting", "ready", "degraded", "stopping")


_ORIGIN = re.compile(r"^http://127\.0\.0\.1:([0-9]{3,5})\Z")


# DEC-0019: a remote placement — an online agent or dashboard — lives at an https DNS name.
_REMOTE_ORIGIN = re.compile(r"^https://((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63})(?::([0-9]{1,5}))?\Z")


_RESERVED_HOST = re.compile(r"(^|\.)(localhost|local|internal|home\.arpa|lan|localdomain)\Z")


PLACEMENTS = ("local", "remote")


# DEC-0032: the supervisor per system and the field that names its job.
# DEC-0061: `node` (Project Observatory's node supervises its children, no supervisor file); DEC-0069: `person` (an app
# a person installs and starts; its descriptor says it is installed, never that it runs).
MANAGERS = ("launchd", "systemd", "task-scheduler", "node", "person", "none")


#: Managers that write no launchd label or plist (DEC-0057, DEC-0061, DEC-0069).
_NOT_LAUNCHD = ("systemd", "task-scheduler", "node", "person")


_AUTH_HEADER = re.compile(r"[A-Za-z][A-Za-z0-9-]{0,63}")


class LoopbackHTTPServer(http.server.ThreadingHTTPServer):
    """ThreadingHTTPServer for a loopback service: threads are daemons, and the bind asks
    no resolver. HTTPServer.server_bind() calls socket.getfqdn() between bind() and listen();
    on a Mac with a slow resolver the port then stays bound but silent, so a host sees
    neither an answer nor a refusal."""

    daemon_threads = True

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = host, port


def descriptor_path(service_id: str, instance: str = "default", directory: Optional[Path] = None) -> Path:
    return (directory or services_dir()) / ("%s.%s.json" % (service_id, instance))


def read_descriptors(directory: Optional[Path] = None) -> List[Tuple[Path, Dict[str, Any]]]:
    root = directory or services_dir()
    found: List[Tuple[Path, Dict[str, Any]]] = []
    if not root.is_dir():
        return found
    for path in sorted(root.glob("*.json")):
        try:
            found.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return found


def validate_descriptor(descriptor: Dict[str, Any]) -> List[str]:
    """Structural checks mirroring service-descriptor.schema.json (the schema stays normative)."""
    problems: List[str] = []
    remote = placement_of(descriptor) == "remote"
    if "placement" in descriptor and descriptor["placement"] not in PLACEMENTS:
        problems.append("placement must be local or remote")
    life_in = descriptor.get("lifecycle") if isinstance(descriptor.get("lifecycle"), dict) else {}
    app = life_in.get("manager") == "person"
    # DEC-0069: an app's descriptor says it is installed, never that it runs; its live origin is in its own liveness file.
    required = ("protocol", "id", "instance", "name", "auth", "lifecycle", "installedAt", "installedBy") + (() if app else ("origin",))
    if not remote:
        required = required + ("paths",)
    for key in required:
        if key not in descriptor:
            problems.append("missing %s" % key)
    if problems:
        return problems
    if descriptor["protocol"] != PROTOCOL:
        problems.append("protocol must be %s" % PROTOCOL)
    if not _ID.match(str(descriptor["id"])):
        problems.append("id must match %s" % _ID.pattern)
    if not _INSTANCE.match(str(descriptor["instance"])):
        problems.append("instance must match %s" % _INSTANCE.pattern)
    if remote:
        problems.extend(remote_origin_problems(descriptor["origin"]))
    elif "origin" in descriptor and not _ORIGIN.match(str(descriptor["origin"])):
        problems.append("origin must be http://127.0.0.1:<port>")
    auth = descriptor.get("auth") or {}
    if "tokenFile" not in auth:
        problems.append("auth.tokenFile is required")
    elif not _LOCAL_PATH.match(str(auth["tokenFile"])):
        problems.append("auth.tokenFile must be a local path, never a network share")
    paths = descriptor.get("paths") or {}
    for value in ([paths["data"]] if "data" in paths else []) + list(paths.get("logs") or []):
        if not _LOCAL_PATH.match(str(value)):
            problems.append("paths must be local paths, never a network share: %r" % value)
    header = auth.get("header", "Authorization")
    scheme = auth.get("scheme", "Bearer")
    if not (isinstance(header, str) and _AUTH_HEADER.fullmatch(header)):
        problems.append("auth.header must match %s" % _AUTH_HEADER.pattern)
    if scheme not in ("Bearer", "none"):
        problems.append("auth.scheme is Bearer or none")
    if header != "Authorization" and scheme != "none":
        problems.append("a custom auth header carries the raw token: scheme must be none")
    life = descriptor.get("lifecycle") or {}
    manager = life.get("manager")
    if manager not in MANAGERS:
        problems.append("lifecycle.manager must be launchd, systemd, task-scheduler, node, person or none")
    # DEC-0069: `app` is the installed app of a person's descriptor, and nothing else's.
    if manager == "person" and "app" not in life:
        problems.append("a person's app declares lifecycle.app, the installed app")
    if "app" in life and manager != "person":
        problems.append("lifecycle.app belongs to manager person only")
    if "app" in life and not _LOCAL_PATH.match(str(life["app"])):
        problems.append("lifecycle.app must be a local path")
    if manager == "launchd" and not (life.get("label") and str(life.get("plist", "")).endswith(".plist")):
        problems.append("a launchd service declares label and plist")
    if "plist" in life and not _LOCAL_PATH.match(str(life["plist"])):
        problems.append("lifecycle.plist must be a local path")
    # DEC-0057, DEC-0061, DEC-0069: a descriptor names one supervisor; launchd's label and plist never sit beside another.
    for field in ("label", "plist"):
        if field in life and manager in _NOT_LAUNCHD:
            problems.append("lifecycle.%s belongs to launchd, not to %s" % (field, manager))
    # DEC-0032: `unit` goes with systemd and `task` with Task Scheduler, and with nothing else.
    for field, owner, pattern in (("unit", "systemd", _UNIT), ("task", "task-scheduler", _TASK)):
        if manager == owner and field not in life:
            problems.append("a %s service declares %s" % (owner, field))
        if field in life and manager != owner:
            problems.append("lifecycle.%s belongs to manager %s only" % (field, owner))
        if field in life and not pattern.match(str(life[field])):
            problems.append("lifecycle.%s must match %s" % (field, pattern.pattern))
    if remote:
        if manager != "none":
            problems.append("a remote service is supervised by its platform: lifecycle.manager must be none")
        for field, of in (("label", "launchd"), ("plist", "launchd"), ("unit", "systemd"), ("task", "Task Scheduler")):
            if field in life:
                problems.append("a remote service has no %s %s" % (of, field))
        if "update" in (descriptor.get("commands") or {}):
            problems.append("a remote service declares no update command")
    problems.extend(descriptor_member_problems(descriptor))
    for name, argv in (descriptor.get("commands") or {}).items():
        if name not in ("doctor", "update"):
            problems.append("unknown command %s" % name)
        elif not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            problems.append("command %s must be an argument array" % name)
        elif not _LOCAL_PATH.match(argv[0]):
            problems.append("command %s must start with an absolute or ~/ executable" % name)
    return problems


#: The organization edition's data classes, least sensitive first (DEC-0061, DEC-0053).
PEER_DATA_CLASSES = ("public", "internal", "confidential", "restricted")


#: The kind of a runner's sign-in, never a credential's value (DEC-0061).
CREDENTIAL_KINDS = ("subscription", "key", "platform-metered", "none")


#: A subscription runs only in its vendor's runner (DEC-0046): runner kind → login.
SUBSCRIPTION_RUNNERS = {"claude-code": "claude", "kimi-code": "kimi", "codex": "chatgpt"}


_PEER_ENDPOINT = re.compile(r"^https://(?P<host>([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63})(:([1-9][0-9]{0,3}|[1-5][0-9]{4}|6[0-4][0-9]{3}|65[0-4][0-9]{2}|655[0-2][0-9]|6553[0-5]))?(/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*)?\Z", re.ASCII)


# FAA-120: source.repository is the schema's common `uri` (RFC 3986: a scheme, a colon, then no space or control
# character); a user:password@ in it is a credential, never the name of a repository.
_SOURCE_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s\x00-\x1f\x7f]+\Z")
_URI_PASSWORD = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://[^/?#@]*:[^/?#@]*@")


_RESIDENCY = re.compile(r"^(A[B-Z]|[B-PR-WY][A-Z]|Q[A-L]|Z[A-Y])\Z", re.ASCII)


_RUNNER_KIND_NAME = re.compile(r"^[a-z][a-z0-9-]{1,62}\Z", re.ASCII)


def _pointer(name: str) -> str:
    """A JSON Pointer token (RFC 6901 §4)."""
    return str(name).replace("~", "~0").replace("/", "~1")


def _text(value: Any, low: int = 1, high: int = 200) -> bool:
    return isinstance(value, str) and low <= len(value) <= high


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
        problems += ["installedBy has no member %s" % k for k in by if k not in ("by", "role", "tool")]
        if by.get("by") not in ("person", "node", "organization"):
            problems.append("installedBy.by is person, node or organization")
        if by.get("by") == "person" and by.get("role") not in ("operator", "administrator"):
            problems.append("installedBy.role is operator or administrator for a person")
        if by.get("by") != "person" and "role" in by:
            problems.append("installedBy.role belongs to a person only")
        if not _text(by.get("tool")):
            problems.append("installedBy.tool is the installer and its version, 1 to 200 characters")
        places += [("/installedBy/%s" % _pointer(k), v) for k, v in by.items()]
    else:
        problems.append("installedBy is the installer's name or {by, role?, tool}")
    if life.get("manager") == "person" and not (isinstance(by, dict) and by.get("by") == "person"):
        problems.append("an app's descriptor names who installed it as a person: installedBy {by: person, role, tool} (DEC-0069)")
    runner = descriptor.get("runner")
    if "runner" in descriptor:
        if not isinstance(runner, dict):
            problems.append("runner is {kind?, credentialKind}")
            runner = {}
        problems += ["runner has no member %s" % k for k in runner if k not in ("kind", "credentialKind")]
        if runner.get("credentialKind") not in CREDENTIAL_KINDS:
            problems.append("runner.credentialKind is subscription, key, platform-metered or none")
        if "kind" in runner and not (isinstance(runner["kind"], str) and _RUNNER_KIND_NAME.match(runner["kind"])):
            problems.append("runner.kind is a runner kind's name")
        if runner.get("credentialKind") == "subscription" and runner.get("kind") not in SUBSCRIPTION_RUNNERS:
            problems.append("a subscription runs only in its vendor's runner: runner.kind claude-code, kimi-code or codex")
        places += [("/runner/%s" % _pointer(k), v) for k, v in runner.items()]
    if "source" in descriptor:
        source = descriptor.get("source")
        if not isinstance(source, dict):
            problems.append("source is {repository?}")
            source = {}
        problems += ["source has no member %s" % k for k in source if k != "repository"]
        if "repository" in source:
            repository = source["repository"]
            if not (isinstance(repository, str) and _SOURCE_URI.match(repository)):
                problems.append("source.repository is a URI (RFC 3986), such as https://github.com/owner/name")
            elif _URI_PASSWORD.match(repository):
                problems.append("source.repository carries no password: it names the repository, never a credential")
            places.append(("/source/repository", repository))
    if "peer" in descriptor:
        peer = descriptor.get("peer")
        if not isinstance(peer, dict):
            problems.append("peer is {endpoint, custody, residency, maxDataClass}")
            peer = {}
        problems += ["peer has no member %s" % k for k in peer if k not in ("endpoint", "custody", "residency", "maxDataClass")]
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
            problems.append("FAC-SEM-086: %s holds a value shaped like a credential; it names a kind, a role or an installer" % place)
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


def app_descriptor_action(existing: Any, tool: str, app_path: str) -> str:
    """What an app that writes its own descriptor does with it on a start (DEC-0069): `keep` when it runs from a
    translocated copy (macOS App Translocation); otherwise `write` when there is none, when it is not an app's descriptor,
    when its version (`installedBy.tool`) or its path (`lifecycle.app`) differs; `keep` otherwise. The contract's
    `appDescriptorAction`."""
    if "/AppTranslocation/" in app_path:
        return "keep"
    if not isinstance(existing, dict) or not isinstance(existing.get("installedBy"), dict):
        return "write"
    recorded = existing["lifecycle"].get("app", _MISSING_APP) if isinstance(existing.get("lifecycle"), dict) else _MISSING_APP
    return "keep" if existing["installedBy"].get("tool", _MISSING_APP) == tool and recorded == app_path else "write"


_MISSING_APP = object()


def app_descriptor_stale(descriptor: Any, app_present: bool) -> bool:
    """Whether a reader treats a descriptor as stale (DEC-0069): an app's descriptor whose installed app it did not find.
    A supervised service's descriptor is never stale by this test. The contract's `appDescriptorStale`."""
    life = descriptor.get("lifecycle") if isinstance(descriptor, dict) else None
    return isinstance(life, dict) and life.get("manager") == "person" and not app_present


def app_present(descriptor: Dict[str, Any]) -> bool:
    """Whether `lifecycle.app` of an app's descriptor exists on this machine (a bundle is a folder, an executable a file)."""
    life = descriptor.get("lifecycle") if isinstance(descriptor.get("lifecycle"), dict) else {}
    app = life.get("app")
    try:
        return isinstance(app, str) and expand(app).exists()
    except ServiceError:  # not a local path: nothing installed there
        return False


#: Fabric's own descriptor (Fabric ADR-0139): `services/fabric.default.json`.
FABRIC_SERVICE = ("fabric", "default")


def fabric_button_presence(directory: Optional[Path] = None) -> str:
    """`present` or `absent` for Fabric's button (DEC-0040 FB-5, DEC-0069, Fabric SCN-142): present when Fabric's own
    descriptor is registered and, for an app's descriptor, its app is still installed. A server sets
    `data-fabric="absent"` on the button's script otherwise. The button only follows a link, so the liveness file is
    not read here; a caller that sends anything reads it."""
    path = descriptor_path(*FABRIC_SERVICE, directory=directory)
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "absent"
    if not isinstance(found, dict) or validate_descriptor(found):
        return "absent"
    return "absent" if app_descriptor_stale(found, app_present(found)) else "present"


def placement_of(descriptor: Dict[str, Any]) -> str:
    """DEC-0019: ``local`` unless the descriptor says ``remote``."""
    return "remote" if (descriptor or {}).get("placement") == "remote" else "local"


def remote_origin_problems(origin: Any) -> List[str]:
    """Problems with a remote origin: https, a public DNS name, an optional port, nothing else."""
    match = _REMOTE_ORIGIN.match(str(origin or ""))
    if not match:
        return ["a remote origin must be https://<dns-name>[:<port>] with no path, query or IP literal"]
    if _RESERVED_HOST.search(match.group(1)):
        return ["a remote service cannot live on the reserved name %s" % match.group(1)]
    if match.group(2) is not None and not 1 <= int(match.group(2)) <= 65535:
        return ["the origin port is out of range"]
    return []


def port_of(origin: str) -> int:
    match = _ORIGIN.match(origin)
    if not match:
        raise ServiceError("Origin %r is not http://127.0.0.1:<port>." % origin)
    return int(match.group(1))


def write_descriptor(descriptor: Dict[str, Any], directory: Optional[Path] = None) -> Path:
    """Installer-only. Refuses a port or id.instance another descriptor claims (a port is a claim)."""
    problems = validate_descriptor(descriptor)
    if problems:
        raise ServiceError("Descriptor is invalid: %s." % "; ".join(problems))
    root = directory or services_dir()
    me = "%s.%s" % (descriptor["id"], descriptor["instance"])
    # DEC-0019: only a local placement claims a port on this computer; DEC-0069: an app's descriptor names none.
    port = None if placement_of(descriptor) == "remote" or "origin" not in descriptor else port_of(descriptor["origin"])
    for path, other in read_descriptors(root):
        key = "%s.%s" % (other.get("id"), other.get("instance", "default"))
        if key == me or port is None:  # a remote origin's port is another computer's; an app claims none
            continue
        try:
            other_port = port_of(str(other.get("origin", "")))
        except ServiceError:
            continue
        if other_port == port:
            raise ServiceError("Port %d is already claimed by %s (%s)." % (port, key, path))
    ensure_private_dir(root)
    target = descriptor_path(descriptor["id"], descriptor["instance"], root)
    atomic_write(target, (json.dumps(descriptor, indent=2, ensure_ascii=False) + "\n").encode(), 0o600)
    return target


def remove_descriptor(service_id: str, instance: str = "default", directory: Optional[Path] = None) -> bool:
    try:
        descriptor_path(service_id, instance, directory).unlink()
        return True
    except FileNotFoundError:
        return False


def build_info(repo_root: Optional[Path] = None, package_file: Optional[Path] = None) -> Dict[str, Any]:
    """Commit (env FABRIC_BUILD_COMMIT, else git) or a sha256 digest of the package file."""
    commit = os.environ.get("FABRIC_BUILD_COMMIT")
    dirty: Optional[bool] = None
    if not commit and repo_root is not None:
        try:
            commit = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "--short=12", "HEAD"],
                                    capture_output=True, text=True, timeout=5, check=True).stdout.strip()
            status = subprocess.run(["git", "-C", str(repo_root), "status", "--porcelain", "--untracked-files=no"],
                                    capture_output=True, text=True, timeout=5, check=True).stdout
            dirty = bool(status.strip())
        except (OSError, subprocess.SubprocessError):
            commit = None
    info: Dict[str, Any] = {"builtAt": now_iso()}
    if commit:
        info["commit"] = commit
        if dirty is not None:
            info["dirty"] = dirty
    elif package_file is not None and Path(package_file).is_file():
        info["digest"] = "sha256:" + hashlib.sha256(Path(package_file).read_bytes()).hexdigest()
    else:
        raise ServiceError("No build identity: set FABRIC_BUILD_COMMIT, pass repo_root or package_file.")
    return info


_THEME_ID = re.compile(r"^[a-z][a-z0-9-]{0,31}\Z")


_KIT_REF = re.compile(r"^[a-z][a-z0-9-]{0,63}@(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?\Z", re.ASCII)


def dashboard_extension_problems(value: Any) -> List[str]:
    """What makes value not a valid ED-9 declaration (service-dashboard-extension.schema.json)."""
    if not isinstance(value, dict):
        return ["the declaration is not an object"]
    out: List[str] = []
    extra = sorted(set(value) - {"minWidth", "appearance", "themes", "kit"})
    if extra:
        out.append("unknown field(s): %s" % ", ".join(extra))
    width = value.get("minWidth")
    if isinstance(width, bool) or not isinstance(width, int):
        out.append("minWidth is required and must be a whole number of CSS pixels")
    elif not 360 <= width <= 1280:
        out.append("minWidth %d is outside 360…1280" % width)
    if "appearance" in value:
        a = value["appearance"]
        if not isinstance(a, list) or len(a) > 2 or len(set(map(str, a))) != len(a) or any(x not in ("scheme", "theme") for x in a):
            out.append("appearance is a list of distinct fields from scheme, theme")
    if "themes" in value:
        t = value["themes"]
        if not isinstance(t, list) or not 1 <= len(t) <= 32 or len(set(map(str, t))) != len(t) \
                or any(not isinstance(x, str) or not _THEME_ID.match(x) for x in t):
            out.append("themes is 1…32 distinct theme ids matching ^[a-z][a-z0-9-]{0,31}$")
    if "kit" in value and not (isinstance(value["kit"], str) and _KIT_REF.match(value["kit"])):
        out.append("kit is name@semver, for example %s" % DASHBOARD_KIT)
    return out


def dashboard_extension(min_width: int = 360, appearance: Sequence[str] = ("scheme", "theme"),
                        themes: Optional[Sequence[str]] = REFERENCE_THEMES,
                        kit: Optional[str] = DASHBOARD_KIT) -> Dict[str, Any]:
    """The `extensions` entry a dashboard built from the kit declares (DEC-0036 ED-9). Declare it only
    when the page meets ED-1…ED-6 — check_dashboard_layout.mjs measures that."""
    value: Dict[str, Any] = {"minWidth": min_width}
    if appearance:
        value["appearance"] = list(appearance)
    if themes:
        value["themes"] = list(themes)
    if kit:
        value["kit"] = kit
    problems = dashboard_extension_problems(value)
    if problems:
        raise ServiceError("Dashboard declaration: %s." % "; ".join(problems))
    return {DASHBOARD_EXTENSION_KEY: value}


_PROFILE_ID = re.compile(r"^[a-z][a-z0-9-]{0,62}\Z")


_RUNNER_KIND = re.compile(r"^[a-z][a-z0-9-]{1,62}\Z")


_MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}/[a-z0-9][a-z0-9._:-]{0,127}\Z")


def configuration_problems(doc: Any) -> List[str]:
    """DEC-0046: the well-known `configuration` — {slots, resolved} as service-well-known.schema.json types it."""
    if not isinstance(doc, dict):
        return ["configuration is an object"]
    problems = ["configuration has no member %s" % k for k in doc if k not in ("slots", "resolved")]
    slots = doc.get("slots")
    if not isinstance(slots, list) or len(slots) > 2 or len(set(map(str, slots))) != len(slots) or not all(s in ("runner", "model") for s in slots):
        problems.append("slots is a list of runner and model, each once")
    resolved = doc.get("resolved")
    if not isinstance(resolved, dict):
        return problems + ["resolved is an object"]
    for k, v in resolved.items():
        ok = {"from": lambda x: x in ("request", "agent", "binding", "estate"),
              "runnerProfile": lambda x: isinstance(x, str) and bool(_PROFILE_ID.match(x)),
              "modelProfile": lambda x: isinstance(x, str) and bool(_PROFILE_ID.match(x)),
              "runnerKind": lambda x: isinstance(x, str) and bool(_RUNNER_KIND.match(x)),
              "route": lambda x: x in ROUTES,
              "models": lambda x: isinstance(x, list) and len(x) <= 16 and all(isinstance(m, str) and _MODEL_ID.match(m) for m in x)}.get(k)
        if ok is None:
            problems.append("resolved has no member %s" % k)
        elif not ok(v):
            problems.append("resolved.%s is not valid" % k)
    return problems


def build_well_known(*, service_id: str, instance: str, name: str, version: str, build: Dict[str, Any],
                     started_at: str, status: str, degraded: Sequence[Dict[str, str]],
                     surfaces: Dict[str, Any], summary: Optional[Sequence[Dict[str, Any]]] = None,
                     update_available: Optional[str] = None, pid: Optional[int] = None,
                     extensions: Optional[Dict[str, Any]] = None,
                     configuration: Optional[Dict[str, Any]] = None,
                     protocols: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """The unauthenticated identity answer. `degraded` is always present; ready means empty.
    `configuration` (DEC-0046) says what the operator can configure and what applies now; fabric_profiles builds it.
    `extensions` is kept as given (a reader ignores keys it does not know); a dashboard declaration
    in it must be valid (dashboard_extension builds one)."""
    if status not in STATUSES:
        raise ServiceError("status must be one of %s." % ", ".join(STATUSES))
    degraded = list(degraded)
    if status == "ready" and degraded:
        status = "degraded"
    if "events" not in surfaces:
        raise ServiceError("surfaces.events is required.")
    doc: Dict[str, Any] = {
        "protocol": PROTOCOL,
        "service": {"id": service_id, "instance": instance, "name": name, "version": version, "build": build},
        "process": {"pid": pid or os.getpid(), "startedAt": started_at},
        "status": status,
        "degraded": degraded,
        "surfaces": surfaces,
        "update": {"available": update_available},
    }
    if summary:
        doc["summary"] = list(summary)[:6]
    if extensions:
        if DASHBOARD_EXTENSION_KEY in extensions:
            problems = dashboard_extension_problems(extensions[DASHBOARD_EXTENSION_KEY])
            if problems:
                raise ServiceError("Dashboard declaration: %s." % "; ".join(problems))
        if CONNECTIONS_EXTENSION_KEY in extensions:
            # DEC-0096: a host hides an invalid declaration (FAC-SEM-127); a service never publishes one.
            view = connections_view({"extensions": {CONNECTIONS_EXTENSION_KEY: extensions[CONNECTIONS_EXTENSION_KEY]}})
            if view["reported"]:
                raise ServiceError("Connections declaration: %s." % "; ".join(view["errors"]))
        doc["extensions"] = dict(extensions)
    if configuration is not None:
        problems = configuration_problems(configuration)
        if problems:
            raise ServiceError("configuration: %s." % "; ".join(problems))
        doc["configuration"] = configuration
    if protocols is not None:
        # DEC-0067: the revisions this service accepts. The document is closed for a reader pinned before DEC-0067, so
        # a service lists them only once its hosts are pinned at or after it.
        problems = protocols_findings(list(protocols))
        if problems:
            raise ServiceError("protocols: %s." % "; ".join(f["message"] for f in problems))
        doc["protocols"] = list(protocols)
    return doc
