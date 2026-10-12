#!/usr/bin/env python3
"""Reference kit for the fabric-service/0.1 local service extension.

Standard library only, Python 3.9+. Copy this file into a service (it is one
module on purpose) or import it by path. Every function implements one rule of
the extension; the rule it implements is named in its docstring, so a service
that calls these functions inherits the rule instead of re-deriving it.

Normative source: fabric-agent-contract docs/specification/service.md (DEC-0015).
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import errno
import hashlib
import hmac
import http.server
import json
import ntpath
import os
from pathlib import Path, PurePath
import plistlib
import posixpath
import re
import secrets
import shutil
import signal
import socket
import socketserver
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
import urllib.error
import urllib.parse
import urllib.request

PROTOCOL = "fabric-service/0.1"
EXTENSION_KEY = "https://fabric.passioncode.ai/agent-contract/extensions/service/0.1"
# The embedded dashboard declaration (fabric-dashboard/0.1, DEC-0036 ED-9), under the well-known
# document's `extensions`. The kit is assets/dashboard-kit; its version is the one in kit.json.
DASHBOARD_EXTENSION_KEY = "https://fabric.passioncode.ai/agent-contract/extensions/dashboard/0.1"
DASHBOARD_KIT = "fabric-dashboard-kit@1.1.0"
REFERENCE_THEMES = ("graphite", "fabric", "paper", "forest", "ocean", "ember", "contrast")
EXIT_ALREADY_RUNNING = 75
# Lifecycle contract (fabric-workspace knowledge/lifecycle.md). A launchd-supervised copy that finds
# the lock held backs off in-process for this long before its exit 75 (LC-03, F8): under KeepAlive
# with ThrottleInterval 10 that is a few starts an hour instead of one every 10 s.
SUPERVISOR_ENV = "FABRIC_SERVICE_SUPERVISOR"
LOCK_WAIT_SUPERVISED_SECONDS = 300.0
LOCK_BACKOFF_FIRST_SECONDS = 0.5
LOCK_BACKOFF_MAX_SECONDS = 30.0
# LC-01: SIGTERM reaches exit in at most 10 s with work in flight — drain 8 s, then hand over,
# and a hard exit 2 s later if the hand-over itself hangs. ExitTimeOut sits above both.
DRAIN_SECONDS = 8.0
DRAIN_GRACE_SECONDS = 2.0
EXIT_HARD_STOP = 70
DEFAULT_EXIT_TIMEOUT = 15
# LC-12: logs rotate by size, 5 x 5 MB by default.
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 5
LOGIN_CODE_TTL_SECONDS = 120
# DEC-0039 (service.md "The session's lifetime"): the longest a service may keep an operator session.
OPERATOR_SESSION_IDLE_SECONDS = 12 * 60 * 60
OPERATOR_SESSION_MAX_SECONDS = 7 * 24 * 60 * 60
EVENTS_DEFAULT_LIMIT = 50
EVENTS_MAX_LIMIT = 200
LEVELS = ("info", "notice", "warning", "error")
STATUSES = ("starting", "ready", "degraded", "stopping")

_ID = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_INSTANCE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_KIND = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){0,5}$")
_ORIGIN = re.compile(r"^http://127\.0\.0\.1:([0-9]{3,5})$")
# DEC-0019: a remote placement — an online agent or dashboard — lives at an https DNS name.
_REMOTE_ORIGIN = re.compile(r"^https://((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63})(?::([0-9]{1,5}))?$")
_RESERVED_HOST = re.compile(r"(^|\.)(localhost|local|internal|home\.arpa|lan|localdomain)$")
PLACEMENTS = ("local", "remote")
_CODE = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
_TRACE_ID = re.compile(r"^(?!0{32}$)[0-9a-f]{32}$")
_SPAN_ID = re.compile(r"^(?!0{16}$)[0-9a-f]{16}$")
# DEC-0032: a local path is POSIX (`/…`, `~/…`) or Windows (`C:\…`, `C:/…`, `~\…`); a network
# share (`\\server\…`, `\\?\…`) is never a local path.
# DEC-0057: `//server/…` and `/\\server…` are shares on Windows too, so a leading slash is followed by neither.
_LOCAL_PATH = re.compile(r"^(~[\\/]|/(?![\\/])|[A-Za-z]:[\\/])")
# DEC-0032: the supervisor per system and the field that names its job.
MANAGERS = ("launchd", "systemd", "task-scheduler", "none")
_AUTH_HEADER = re.compile(r"[A-Za-z][A-Za-z0-9-]{0,63}")
_UNIT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_.@-]{0,250}\.service$")
_TASK = re.compile(r"^\\[A-Za-z0-9 ._\\-]{1,254}$")
WINDOWS = os.name == "nt"
# Without O_BINARY a Windows descriptor is in text mode and every LF written becomes CRLF.
_O_BINARY = getattr(os, "O_BINARY", 0)


class ServiceError(Exception):
    """A rule of the extension was violated; the message is one readable sentence."""


class AlreadyRunning(ServiceError):
    def __init__(self, holder_pid: Optional[int], lock_path: Path):
        self.holder_pid = holder_pid
        self.lock_path = lock_path
        # FAC-SEM-078: a copy that cannot learn the holder's pid says the holder is unknown.
        who = "process %d" % holder_pid if holder_pid else "an unknown process"
        super().__init__("Another copy is already running (%s holds %s)." % (who, lock_path))


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def expand(path: str) -> Path:
    """Paths in a descriptor may start with ~/ (or ~\\ on Windows); everything else must be
    absolute, and a network share is never a local path (DEC-0032)."""
    if not _LOCAL_PATH.match(str(path)):
        raise ServiceError("Path %r must be absolute or start with ~/." % path)
    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        raise ServiceError("Path %r must be absolute or start with ~/." % path)
    return p


# --- where things live -------------------------------------------------------

def services_dir() -> Path:
    """Descriptor directory: FABRIC_SERVICES_DIR, else the per-user OS location."""
    override = os.environ.get("FABRIC_SERVICES_DIR")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library/Application Support/ai.passioncode.fabric/services"
    if sys.platform == "win32":
        # DEC-0032: LOCALAPPDATA, not APPDATA, so token files never roam with the profile.
        return _local_app_data() / "passioncode-fabric" / "services"
    base = os.environ.get("XDG_DATA_HOME") or str(home / ".local/share")
    return Path(base) / "passioncode-fabric/services"


def service_dirs(service_id: str) -> Dict[str, Path]:
    """State lives outside code: data+config, logs and cache in per-user OS directories."""
    _require_id(service_id)
    home = Path.home()
    if sys.platform == "darwin":
        return {
            "data": home / "Library/Application Support" / service_id,
            "logs": home / "Library/Logs" / service_id,
            "cache": home / "Library/Caches" / service_id,
        }
    if sys.platform == "win32":
        data = _local_app_data() / service_id
        return {"data": data, "logs": data / "Logs", "cache": data / "Cache"}
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share") / service_id
    state = Path(os.environ.get("XDG_STATE_HOME") or home / ".local/state") / service_id
    cache = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache") / service_id
    return {"data": data, "logs": state / "logs", "cache": cache}


def _read_at(fd: int, n: int, offset: int) -> bytes:
    """`os.pread` where it exists; Windows has none, so seek and read (the descriptor's appends
    still go to the end: O_APPEND moves to it before every write)."""
    if hasattr(os, "pread"):
        return os.pread(fd, n, offset)
    os.lseek(fd, offset, os.SEEK_SET)
    return os.read(fd, n)


def _local_app_data() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    return Path(value) if value else Path.home() / "AppData" / "Local"


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if WINDOWS:
        _win_protect(path, folder=True)
    else:
        os.chmod(path, 0o700)
    return path


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Temporary file in the same directory, fsync, rename: a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
    try:
        if WINDOWS:
            # The file's ACL is its privacy (DEC-0032): set explicitly and protected — before the bytes go in — so
            # it does not depend on what the folder hands down. A rename keeps it.
            _win_protect(Path(tmp), folder=False)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if not WINDOWS:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


# --- one copy ----------------------------------------------------------------

class InstanceLock:
    """Exclusive flock on <data>/service.lock, taken BEFORE any side effect.

    Binding a port is not a lock: a second copy that resumes jobs before its
    bind fails has already done damage. The lock is released by the kernel when
    the process dies, so a crash never leaves it stale.
    """

    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "service.lock"
        self._fd: Optional[int] = None
        self._name: Any = None

    #: Windows locks a byte range, not the file: one byte far past the pid the file holds, so the
    #: holder may rewrite the pid and another process may still read it (locking past the end of
    #: a file is allowed there).
    WINDOWS_LOCK_OFFSET = 1 << 30

    def acquire(self) -> "InstanceLock":
        ensure_private_dir(self.path.parent)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT | _O_BINARY, 0o600)
        try:
            if WINDOWS:
                import msvcrt

                os.lseek(fd, self.WINDOWS_LOCK_OFFSET, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                os.lseek(fd, 0, os.SEEK_SET)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES, getattr(errno, "EDEADLOCK", -1)):
                raise AlreadyRunning(_read_pid(self.path), self.path) from None
            raise
        try:
            self._name = _hold_lock_name(self.path)
        except BaseException:
            os.close(fd)
            raise
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        os.fsync(fd)
        self._fd = fd
        return self

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        if self._name is not None:
            _drop_lock_name(self._name)
            self._name = None


# The Node kit cannot flock on Linux or lock a byte range on Windows, so it holds a name instead: an
# abstract unix socket on Linux, a named pipe on Windows — exclusive, no file, gone with the process.
# This kit holds the same name beside its file lock, so the two kits exclude each other everywhere
# and the probe sees either one (`lock_name_held`).

def lock_name(lock_path: Path, platform: str = sys.platform) -> Optional[str]:
    """The name the Node kit holds for this lock file; None where it holds none (macOS: O_EXLOCK)."""
    if platform.startswith("linux"):
        digest = hashlib.sha256(posixpath.abspath(str(lock_path)).encode()).hexdigest()[:32]
        return "\0fabric-service-" + digest
    if platform == "win32":
        # Windows paths compare without case: C:\Users and c:\users are one lock.
        digest = hashlib.sha256(ntpath.normcase(ntpath.abspath(str(lock_path))).encode()).hexdigest()[:32]
        return "\\\\.\\pipe\\fabric-service-" + digest
    return None


def _hold_lock_name(lock_path: Path) -> Any:
    name = lock_name(lock_path)
    if name is None:
        return None
    if WINDOWS:
        handle = _create_first_pipe(name)
        if handle is None:
            raise AlreadyRunning(_read_pid(lock_path), lock_path)
        return handle
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(name)
    except OSError as exc:
        sock.close()
        if exc.errno == errno.EADDRINUSE:
            raise AlreadyRunning(_read_pid(lock_path), lock_path) from None
        raise
    # Held by its descriptor, like the file lock: a socket object would close when collected.
    return sock.detach()


def _drop_lock_name(held: Any) -> None:
    if WINDOWS:
        _close_handle(held)
    else:
        os.close(held)


def lock_name_held(lock_path: Path) -> Optional[bool]:
    """True when some process holds the lock's name (a running service of either kit); None where there is no name
    to hold. It only looks — /proc/net/unix on Linux, WaitNamedPipeW on Windows — and never takes the name, so a
    probe cannot make a service that is starting at that moment fail."""
    name = lock_name(lock_path)
    if name is None:
        return None
    if WINDOWS:
        return _pipe_exists(name)
    try:
        with open("/proc/net/unix", encoding="utf-8", errors="replace") as table:
            return any(line.rstrip("\n").endswith(" @" + name[1:]) for line in table)
    except OSError:
        return None


def _read_pid(path: Path) -> Optional[int]:
    try:
        text = path.read_text().strip()
        return int(text) if re.fullmatch(r"[0-9]{1,10}", text, re.ASCII) else None
    except OSError:
        return None


#: The managers a supervisor marker may name (DEC-0057): the three systems' supervisors and Project Observatory's node.
SUPERVISORS = ("launchd", "systemd", "task-scheduler", "node")
#: The argument form of the marker, for a supervisor whose start carries no environment (a Scheduled Task's action).
SUPERVISOR_ARG = "--fabric-supervisor"


def _marker_arguments(argv: Sequence[Any]) -> List[str]:
    """The marker values an argument vector carries after the executable and before ``--``. A bare
    ``--fabric-supervisor`` followed by nothing, by ``--`` or by another ``--…`` flag is a marker with an empty value
    and consumes nothing."""
    values: List[str] = []
    index = 1
    while index < len(argv):
        item = argv[index]
        if item == "--":
            break
        if item == SUPERVISOR_ARG:
            following = argv[index + 1] if index + 1 < len(argv) else None
            if isinstance(following, str) and not following.startswith("--"):
                values.append(following)
                index += 1
            else:
                values.append("")
        elif isinstance(item, str) and item.startswith(SUPERVISOR_ARG + "="):
            values.append(item[len(SUPERVISOR_ARG) + 1:])
        index += 1
    return values


def supervisor_marker(env: Optional[Dict[str, str]] = None, argv: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """How this copy was started (DEC-0057), from ``FABRIC_SERVICE_SUPERVISOR=<manager>`` and
    ``--fabric-supervisor <manager>`` / ``--fabric-supervisor=<manager>`` (``env`` and ``argv`` default to this process's):

    - ``{"kind": "supervised", "manager", "forms"}`` — every marker present names the same manager of SUPERVISORS;
    - ``{"kind": "conflict", "values", "forms"}`` — the markers disagree: the copy is unsupervised and exits 75 at once,
      before it takes the lock (an empty or bare argument beside a variable disagrees with it);
    - ``{"kind": "manual", "forms", "unreadable"?}`` — no marker (only an empty variable counts as none), or one that
      names no manager.

    A copy never infers supervision from its parent process. The contract's ``supervisorMarker``."""
    env = os.environ if env is None else env
    argv = sys.argv if argv is None else argv
    variable = env.get(SUPERVISOR_ENV) if isinstance(env, dict) or hasattr(env, "get") else None
    from_env = [variable] if isinstance(variable, str) and variable != "" else []
    from_args = _marker_arguments(list(argv) if isinstance(argv, (list, tuple)) else [])
    forms = (["environment"] if from_env else []) + (["argument"] if from_args else [])
    values: List[str] = []
    for value in from_env + from_args:
        if value not in values:
            values.append(value)
    if len(values) > 1:
        return {"kind": "conflict", "values": values, "forms": forms}
    if not values:
        return {"kind": "manual", "forms": forms}
    if values[0] in SUPERVISORS:
        return {"kind": "supervised", "manager": values[0], "forms": forms}
    return {"kind": "manual", "unreadable": values[0], "forms": forms}


def lock_wait_budget_seconds(marker: Dict[str, Any]) -> float:
    """How long a copy started so may wait for the lock: 300 s when supervised, else not at all."""
    return LOCK_WAIT_SUPERVISED_SECONDS if marker.get("kind") == "supervised" else 0.0


def marker_conflict_message(marker: Dict[str, Any]) -> str:
    """The one sentence a copy whose markers disagree exits with, naming the markers present."""
    shown = ", ".join(repr(v) for v in marker["values"])
    if marker["forms"] == ["environment", "argument"]:
        return "%s and %s disagree (%s); not starting unsupervised." % (SUPERVISOR_ENV, SUPERVISOR_ARG, shown)
    return "%s is given with different values (%s); not starting unsupervised." % (SUPERVISOR_ARG, shown)


def supervised(env: Optional[Dict[str, str]] = None, argv: Optional[Sequence[str]] = None) -> bool:
    """True when a supervisor that restarts on exit started this process and said so with the marker
    (``launchd_plist`` and ``systemd_unit`` set the variable, ``task_xml`` writes the argument, a node sets either)."""
    return supervisor_marker(env, argv)["kind"] == "supervised"


def supervised_by_launchd(env: Optional[Dict[str, str]] = None, argv: Optional[Sequence[str]] = None) -> bool:
    """True when launchd started this process from a plist written by ``launchd_plist``.

    The plist says so explicitly (``FABRIC_SERVICE_SUPERVISOR=launchd``); the parent process or
    ``XPC_SERVICE_NAME`` is not evidence — a terminal inside an app carries one too."""
    return supervisor_marker(env, argv).get("manager") == "launchd"


def add_supervisor_argument(parser: Any) -> Any:
    """Let a service's own argparse parser accept the marker in both spellings, and a bare one, and ignore it
    (DEC-0057: argparse exits 2 on an unknown flag). The kit reads the marker from ``sys.argv`` itself."""
    import argparse
    parser.add_argument(SUPERVISOR_ARG, nargs="?", const="", default=None, help=argparse.SUPPRESS)
    return parser


def hold_single_instance(data_dir: Path, wait_seconds: Optional[float] = None, *,
                         sleep: Callable[[float], None] = time.sleep,
                         clock: Callable[[], float] = time.monotonic,
                         env: Optional[Dict[str, str]] = None, argv: Optional[Sequence[str]] = None) -> InstanceLock:
    """Take the lock or exit 75 with one sentence naming the holder (DEC-0057, FAC-SEM-078).

    Markers that disagree exit 75 at once, before the lock, naming them. Started by hand (no
    marker), a held lock exits 75 at once. Under a supervisor that restarts on exit an immediate
    exit is a respawn every few seconds, forever; so a supervised copy first backs off in-process
    (0.5 s doubling to 30 s, ``LOCK_WAIT_SUPERVISED_SECONDS`` in all), takes over if the holder
    leaves, and exits 75 only when the wait runs out. Nothing has been touched while it waits.
    ``wait_seconds`` overrides the choice (0 = never wait); ``env`` and ``argv`` default to this process's."""
    marker = supervisor_marker(env, argv)
    if marker["kind"] == "conflict":
        print(marker_conflict_message(marker), file=sys.stderr)
        raise SystemExit(EXIT_ALREADY_RUNNING)
    if wait_seconds is None:
        wait_seconds = lock_wait_budget_seconds(marker)
    deadline = clock() + max(0.0, wait_seconds)
    delay = LOCK_BACKOFF_FIRST_SECONDS
    announced = False
    while True:
        try:
            return InstanceLock(data_dir).acquire()
        except AlreadyRunning as exc:
            remaining = deadline - clock()
            if remaining <= 0:
                print(str(exc), file=sys.stderr)
                raise SystemExit(EXIT_ALREADY_RUNNING)
            if not announced:
                print("%s Waiting up to %.0f s for it to exit." % (exc, remaining), file=sys.stderr, flush=True)
                announced = True
            sleep(min(delay, remaining))
            delay = min(delay * 2, LOCK_BACKOFF_MAX_SECONDS)


# --- Windows ACLs (DEC-0032) ---------------------------------------------------

#: The trustees a token file may grant anything to besides the current user: LocalSystem and the
#: Administrators group — the same trust as root reading a 0600 file on POSIX.
WINDOWS_TRUSTED = ("S-1-5-18", "S-1-5-32-544")


def token_file_problem(path: Path, file: Dict[str, Any], user: str) -> Optional[str]:
    """windows_token_acl_problem as one sentence naming the file and the refusal, or None."""
    problem = windows_token_acl_problem(file, user)
    return None if problem is None else "Token file %s refused: %s." % (path, problem["message"])


SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"
#: A string SID: revision 1, an identifier authority and up to 15 sub-authorities of 32 bits each.
_SID_TEXT = re.compile(r"S-1-[0-9]{1,15}(?:-[0-9]{1,10}){0,15}", re.IGNORECASE | re.ASCII)


def _sid(value: Any) -> Optional[str]:
    """A readable SID in upper case (SIDs compare case-insensitively on their S), or None."""
    if not isinstance(value, str) or not _SID_TEXT.fullmatch(value):
        return None
    return value.upper() if all(int(part) <= 0xFFFFFFFF for part in value.split("-")[3:]) else None


def windows_token_acl_problem(file: Any, current_user_sid: Any) -> Optional[Dict[str, Any]]:
    """service.md "Windows token files" (DEC-0032, DEC-0033, DEC-0057, FAC-SEM-079) on what a reader has read:
    ``file`` is ``{isRegularFile, isReparsePoint, realPathInProfile, ownerSid, aces: [{type, sid, mask}]}``, the mask
    the ACE's unsigned 32-bit access mask. The first refusal ``{problem, at, sid?, message}``, or None when the file may
    be read: a regular file, not a reparse point, inside the profile; owned by the user, SYSTEM or Administrators; every
    allow ACE with a non-zero mask naming one of those three; deny ACEs ignored; any other ACE type refused; anything
    unreadable refused. The contract's ``windowsTokenAclProblem``; a refusal names the SID, never the contents."""
    def refuse(problem: str, at: str, message: str, sid: Optional[str] = None) -> Dict[str, Any]:
        out = {"problem": problem, "at": at, "message": message}
        if sid is not None:
            out["sid"] = sid
        return out
    user = _sid(current_user_sid)
    if user is None:
        return refuse("unreadable", "/currentUserSid", "the current user's SID is unreadable")
    if not isinstance(file, dict):
        return refuse("unreadable", "/file", "the token file's metadata is unreadable")
    for flag in ("isRegularFile", "isReparsePoint", "realPathInProfile"):
        if not isinstance(file.get(flag), bool):
            return refuse("unreadable", "/file/" + flag, flag + " is unreadable")
    if file["isReparsePoint"]:
        return refuse("reparse-point", "/file/isReparsePoint", "the token file is a reparse point (a symlink or a junction)")
    if not file["isRegularFile"]:
        return refuse("not-regular-file", "/file/isRegularFile", "the token file is not a regular file")
    if not file["realPathInProfile"]:
        return refuse("outside-profile", "/file/realPathInProfile", "the token file's real path lies outside the user's profile")
    trusted = {user, SYSTEM_SID, ADMINISTRATORS_SID}
    owner = _sid(file.get("ownerSid"))
    if owner is None:
        return refuse("unreadable", "/file/ownerSid", "the owner SID is unreadable")
    if owner not in trusted:
        return refuse("owner", "/file/ownerSid", "the token file is owned by %s, not by the current user, SYSTEM or Administrators" % owner, owner)
    aces = file.get("aces")
    if not isinstance(aces, list):
        return refuse("unreadable", "/file/aces", "the ACL is unreadable")
    for index, ace in enumerate(aces):
        at = "/file/aces/%d" % index
        if not isinstance(ace, dict):
            return refuse("unreadable", at, "ACE %d is unreadable" % index)
        if not isinstance(ace.get("type"), str):
            return refuse("unreadable", at + "/type", "ACE %d has an unreadable type" % index)
        trustee = _sid(ace.get("sid"))
        if trustee is None:
            return refuse("unreadable", at + "/sid", "ACE %d names an unreadable SID" % index)
        mask = ace.get("mask")
        if (not isinstance(mask, (int, float)) or isinstance(mask, bool) or (isinstance(mask, float) and not mask.is_integer())
                or not 0 <= mask <= 0xFFFFFFFF):
            return refuse("unreadable", at + "/mask", "ACE %d has an unreadable access mask" % index)
        if ace["type"] == "deny":
            continue
        if ace["type"] != "allow":
            return refuse("ace-type", at + "/type", "ACE %d for %s is of a type the rule does not read" % (index, trustee), trustee)
        if mask == 0:
            continue
        if trustee not in trusted:
            return refuse("ace-sid", at + "/sid", "the token file grants access to %s; only the current user, SYSTEM and Administrators may hold any" % trustee, trustee)
    return None


#: SDDL ACE types (MS-DTYP §2.5.1.1) as the rule's ACE type: allow and deny are read, every other type is refused.
_SDDL_ACE_TYPES = {"A": "allow", "D": "deny", "OA": "allow-object", "OD": "deny-object", "XA": "allow-callback",
                   "XD": "deny-callback", "ZA": "allow-object-callback"}
#: SDDL access-right aliases (MS-DTYP §2.5.1.1, "ace_rights") and their masks.
_SDDL_RIGHTS = {"GA": 0x10000000, "GR": 0x80000000, "GW": 0x40000000, "GX": 0x20000000, "RC": 0x20000, "SD": 0x10000,
                "WD": 0x40000, "WO": 0x80000, "RP": 0x10, "WP": 0x20, "CC": 0x1, "DC": 0x2, "LC": 0x4, "SW": 0x8,
                "LO": 0x80, "DT": 0x40, "CR": 0x100, "FA": 0x1F01FF, "FR": 0x120089, "FW": 0x120116, "FX": 0x1200A0,
                "KA": 0xF003F, "KR": 0x20019, "KX": 0x20019, "KW": 0x20006}


def _sddl_ace_strings(dacl: str) -> List[str]:
    """The top-level parenthesized ACE strings of an SDDL DACL; a callback ACE's conditional expression may nest."""
    aces, depth, start = [], 0, 0
    for index, char in enumerate(dacl):
        if char == "(":
            if depth == 0:
                start = index + 1
            depth += 1
        elif char == ")" and depth:
            depth -= 1
            if depth == 0:
                aces.append(dacl[start:index])
    return aces


def _sddl_mask(rights: str) -> Optional[int]:
    """An SDDL rights field as the unsigned 32-bit mask, or None when it cannot be read."""
    if re.fullmatch(r"0[xX][0-9a-fA-F]{1,8}", rights):
        return int(rights, 16)
    if len(rights) % 2:
        return None
    mask = 0
    for i in range(0, len(rights), 2):
        if rights[i:i + 2] not in _SDDL_RIGHTS:
            return None
        mask |= _SDDL_RIGHTS[rights[i:i + 2]]
    return mask


def acl_from_sddl(sddl: str, canonical: Callable[[str], str] = lambda sid: sid) -> Tuple[str, List[Dict[str, Any]]]:
    """(owner SID, the ACEs that apply to the object itself as ``{type, sid, mask}``) from an SDDL owner-and-DACL
    string. ``canonical`` turns an SDDL alias (SY, BA, WD…) into its SID. A missing or NULL DACL grants everyone
    everything and is read as an allow ACE for Everyone (S-1-1-0); an inherit-only ACE (flag IO) applies to children
    only and is not read; an unreadable rights field gives mask None, which the rule refuses."""
    owner = sddl.split("O:", 1)[1].split("G:", 1)[0].split("D:", 1)[0] if "O:" in sddl else ""
    dacl = sddl.split("D:", 1)[1] if "D:" in sddl else ""
    owner_sid = canonical(owner) if owner else ""
    if not dacl or dacl.startswith("NO_ACCESS_CONTROL"):
        return owner_sid, [{"type": "allow", "sid": "S-1-1-0", "mask": 0x1F01FF}]
    aces = []
    for text in _sddl_ace_strings(dacl):
        fields = text.split(";", 6)
        if len(fields) < 6:  # unreadable: the rule refuses it
            aces.append({"type": None, "sid": None, "mask": None})
            continue
        kind, flags, rights, trustee = fields[0], fields[1], fields[2], fields[5]
        if "IO" in [flags[i:i + 2] for i in range(0, len(flags), 2)]:
            continue
        aces.append({"type": _SDDL_ACE_TYPES.get(kind, kind), "sid": canonical(trustee), "mask": _sddl_mask(rights)})
    return owner_sid, aces


if WINDOWS:  # pragma: no cover - exercised by the Windows CI job
    import ctypes
    from ctypes import wintypes

    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _PVOID = ctypes.c_void_p
    _SE_FILE_OBJECT, _OWNER_INFO, _DACL_INFO, _PROTECTED_DACL = 1, 0x1, 0x4, 0x80000000
    _REPARSE_POINT = 0x400
    _advapi32.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD] + [ctypes.POINTER(_PVOID)] * 5
    _advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    _advapi32.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD] + [_PVOID] * 4
    _advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    _advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        _PVOID, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.ULONG)]
    _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(_PVOID), ctypes.POINTER(wintypes.ULONG)]
    _advapi32.GetSecurityDescriptorDacl.argtypes = [_PVOID, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(_PVOID),
                                                    ctypes.POINTER(wintypes.BOOL)]
    _advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    _advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, _PVOID, wintypes.DWORD,
                                              ctypes.POINTER(wintypes.DWORD)]
    _advapi32.ConvertSidToStringSidW.argtypes = [_PVOID, ctypes.POINTER(wintypes.LPWSTR)]
    _advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(_PVOID)]
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.LocalFree.argtypes = [_PVOID]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _CANONICAL: Dict[str, str] = {}

    def _win_error(what: str, code: Optional[int] = None) -> OSError:
        code = ctypes.get_last_error() if code is None else code
        return OSError(code, "%s: %s" % (what, ctypes.FormatError(code).strip()))

    def _sid_text(sid: Any) -> str:
        text = wintypes.LPWSTR()
        if not _advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise _win_error("ConvertSidToStringSidW")
        try:
            return text.value
        finally:
            _kernel32.LocalFree(text)

    def _canonical_sid(trustee: str) -> str:
        """SDDL writes well-known accounts by alias (SY, BA, LA, OW); compare SIDs."""
        if trustee not in _CANONICAL:
            sid = _PVOID()
            if _advapi32.ConvertStringSidToSidW(trustee, ctypes.byref(sid)):
                try:
                    _CANONICAL[trustee] = _sid_text(sid)
                finally:
                    _kernel32.LocalFree(sid)
            else:
                _CANONICAL[trustee] = trustee
        return _CANONICAL[trustee]

    def windows_user_sid() -> str:
        token = wintypes.HANDLE()
        if not _advapi32.OpenProcessToken(_kernel32.GetCurrentProcess(), 0x8, ctypes.byref(token)):
            raise _win_error("OpenProcessToken")
        try:
            size = wintypes.DWORD()
            _advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            if not _advapi32.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
                raise _win_error("GetTokenInformation")
            return _sid_text(ctypes.cast(buf, ctypes.POINTER(_PVOID))[0])
        finally:
            _kernel32.CloseHandle(token)

    def _sddl(path: Path) -> str:
        sd = _PVOID()
        refs = [_PVOID() for _ in range(4)]
        code = _advapi32.GetNamedSecurityInfoW(str(path), _SE_FILE_OBJECT, _OWNER_INFO | _DACL_INFO,
                                               *[ctypes.byref(r) for r in refs], ctypes.byref(sd))
        if code:
            raise _win_error("GetNamedSecurityInfoW", code)
        try:
            text = wintypes.LPWSTR()
            if not _advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                    sd, 1, _OWNER_INFO | _DACL_INFO, ctypes.byref(text), None):
                raise _win_error("ConvertSecurityDescriptorToStringSecurityDescriptorW")
            try:
                return text.value or ""
            finally:
                _kernel32.LocalFree(text)
        finally:
            _kernel32.LocalFree(sd)

    def windows_acl(path: Path) -> Tuple[str, List[Dict[str, Any]]]:
        """(owner SID, the ACEs on the object itself as ``{type, sid, mask}``), read from its SDDL (acl_from_sddl)."""
        return acl_from_sddl(_sddl(path), _canonical_sid)

    def _win_protect(path: Path, folder: bool) -> None:
        """A protected list (inheritance off): this user, SYSTEM, Administrators, full control;
        inherited by what a folder holds."""
        inherit = "OICI" if folder else ""
        sddl = "D:P" + "".join("(A;%s;FA;;;%s)" % (inherit, who) for who in (windows_user_sid(), "SY", "BA"))
        sd = _PVOID()
        if not _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(sd), None):
            raise _win_error("ConvertStringSecurityDescriptorToSecurityDescriptorW")
        try:
            present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), _PVOID()
            if not _advapi32.GetSecurityDescriptorDacl(sd, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
                raise _win_error("GetSecurityDescriptorDacl")
            code = _advapi32.SetNamedSecurityInfoW(str(path), _SE_FILE_OBJECT, _DACL_INFO | _PROTECTED_DACL,
                                                   None, None, dacl, None)
            if code:
                raise _win_error("SetNamedSecurityInfoW", code)
        finally:
            _kernel32.LocalFree(sd)

    _kernel32.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR] + [wintypes.DWORD] * 6 + [_PVOID]
    _kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
    _INVALID_HANDLE = wintypes.HANDLE(-1).value

    def _create_first_pipe(name: str) -> Any:
        """The pipe's first instance, or None when another process holds it (ERROR_ACCESS_DENIED)."""
        # PIPE_ACCESS_INBOUND | FILE_FLAG_FIRST_PIPE_INSTANCE; PIPE_REJECT_REMOTE_CLIENTS; unlimited instances,
        # as libuv creates them: then a second first-instance attempt, ours or the Node kit's, is refused with
        # ERROR_ACCESS_DENIED (Node: EADDRINUSE), never ERROR_PIPE_BUSY.
        handle = _kernel32.CreateNamedPipeW(name, 0x1 | 0x00080000, 0x8, 255, 0, 0, 0, None)
        if handle == _INVALID_HANDLE:
            code = ctypes.get_last_error()
            if code in (5, 231):  # ERROR_ACCESS_DENIED, ERROR_PIPE_BUSY: another process holds it
                return None
            raise _win_error("CreateNamedPipeW", code)
        return handle

    def _close_handle(handle: Any) -> None:
        _kernel32.CloseHandle(handle)

    _kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    _kernel32.WaitNamedPipeW.restype = wintypes.BOOL

    def _pipe_exists(name: str) -> bool:
        """Some process holds the pipe: waiting for it does not fail with ERROR_FILE_NOT_FOUND. Nothing connects."""
        if _kernel32.WaitNamedPipeW(name, 1):
            return True
        return ctypes.get_last_error() != 2

    def _win_token_problem(path: Path, info: os.stat_result) -> Optional[str]:
        profile = os.path.normcase(os.path.realpath(os.environ.get("USERPROFILE") or str(Path.home())))
        real = os.path.normcase(os.path.realpath(str(path)))
        try:
            inside = os.path.commonpath([profile, real]) == profile
        except ValueError:  # another drive
            inside = False
        owner, aces = windows_acl(path)
        file = {"isRegularFile": stat.S_ISREG(info.st_mode), "isReparsePoint": bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT),
                "realPathInProfile": inside, "ownerSid": owner, "aces": aces}
        return token_file_problem(path, file, windows_user_sid())
else:
    def _create_first_pipe(name: str) -> Any:  # noqa: ARG001
        raise ServiceError("named pipes exist only on Windows")

    def _close_handle(handle: Any) -> None:  # noqa: ARG001
        raise ServiceError("handles exist only on Windows")

    def _pipe_exists(name: str) -> bool:  # noqa: ARG001
        raise ServiceError("named pipes exist only on Windows")

    def _win_protect(path: Path, folder: bool) -> None:  # noqa: ARG001 - POSIX uses modes
        raise ServiceError("Windows ACLs exist only on Windows")

    def _win_token_problem(path: Path, info: os.stat_result) -> Optional[str]:  # noqa: ARG001
        raise ServiceError("Windows token rules apply only on Windows")


# --- token -------------------------------------------------------------------

def ensure_token(path: Path) -> str:
    """Create the service token once (0600, owner only); never rotate silently."""
    path = Path(path)
    if path.exists():
        return read_token(path)
    ensure_private_dir(path.parent)
    token = secrets.token_urlsafe(32)
    atomic_write(path, token.encode(), 0o600)
    return token


def read_token(path: Path) -> str:
    """Refuse a symlink, a file owned by someone else, or one others can read.

    On Windows the rule is service.md "Windows token files" (DEC-0032, DEC-0033, DEC-0057):
    windows_token_acl_problem over the file's flags, owner and ACEs; a refusal names the SID,
    never the contents."""
    path = Path(path)
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise ServiceError("Token file %s is a symlink; refusing it." % path)
    if WINDOWS:
        problem = _win_token_problem(path, info)
        if problem:
            raise ServiceError(problem)
    else:
        if info.st_uid != os.getuid():
            raise ServiceError("Token file %s belongs to another user." % path)
        if info.st_mode & 0o077:
            raise ServiceError("Token file %s is readable by others; set mode 0600." % path)
    token = path.read_text().strip()
    if len(token) < 16:
        raise ServiceError("Token file %s holds no usable token." % path)
    return token


def token_matches(presented: Optional[str], token: str, scheme: str = "Bearer") -> bool:
    if not presented:
        return False
    value = presented
    if scheme == "Bearer":
        if not presented.startswith("Bearer "):
            return False
        value = presented[len("Bearer "):]
    return hmac.compare_digest(value.strip().encode(), token.encode())


# --- network guard -----------------------------------------------------------

def check_request(port: int, host: Optional[str], origin: Optional[str] = None,
                  sec_fetch_site: Optional[str] = None) -> Optional[str]:
    """Return why a request must be refused (403), or None when it may proceed."""
    allowed_hosts = {"127.0.0.1:%d" % port, "localhost:%d" % port, "[::1]:%d" % port}
    if host not in allowed_hosts:
        return "Host %r is not this service." % host
    if origin is not None and origin not in {"http://" + h for h in allowed_hosts}:
        return "Origin %r is not this service." % origin
    if sec_fetch_site == "cross-site":
        return "Cross-site requests are refused."
    return None


# --- descriptor --------------------------------------------------------------

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
    required = ("protocol", "id", "instance", "name", "origin", "auth", "lifecycle", "installedAt", "installedBy")
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
    elif not _ORIGIN.match(str(descriptor["origin"])):
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
        problems.append("lifecycle.manager must be launchd, systemd, task-scheduler or none")
    if manager == "launchd" and not (life.get("label") and str(life.get("plist", "")).endswith(".plist")):
        problems.append("a launchd service declares label and plist")
    if "plist" in life and not _LOCAL_PATH.match(str(life["plist"])):
        problems.append("lifecycle.plist must be a local path")
    # DEC-0057: a descriptor names one supervisor; launchd's label and plist never sit beside another.
    for field in ("label", "plist"):
        if field in life and manager in ("systemd", "task-scheduler"):
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
    for name, argv in (descriptor.get("commands") or {}).items():
        if name not in ("doctor", "update"):
            problems.append("unknown command %s" % name)
        elif not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            problems.append("command %s must be an argument array" % name)
        elif not _LOCAL_PATH.match(argv[0]):
            problems.append("command %s must start with an absolute or ~/ executable" % name)
    return problems


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
    # DEC-0019: only a local placement claims a port on this computer.
    port = None if placement_of(descriptor) == "remote" else port_of(descriptor["origin"])
    for path, other in read_descriptors(root):
        key = "%s.%s" % (other.get("id"), other.get("instance", "default"))
        if key == me or port is None:  # a remote origin's port is another computer's
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


# --- build identity & well-known ------------------------------------------------

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


_THEME_ID = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_KIT_REF = re.compile(r"^[a-z][a-z0-9-]{0,63}@(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")


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


_PROFILE_ID = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_RUNNER_KIND = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}/[a-z0-9][a-z0-9._:-]{0,127}$")
ROUTES = ("subscription", "key")


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
                     configuration: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        doc["extensions"] = dict(extensions)
    if configuration is not None:
        problems = configuration_problems(configuration)
        if problems:
            raise ServiceError("configuration: %s." % "; ".join(problems))
        doc["configuration"] = configuration
    return doc


# --- events ------------------------------------------------------------------

def make_event(event_id: Any, at: str, kind: str, level: str, text: str, *, subject: Optional[Dict[str, str]] = None,
               link: Optional[str] = None, notify: bool = False, trace_id: Optional[str] = None,
               span_id: Optional[str] = None) -> Dict[str, Any]:
    """One activity event: one sentence a person reads, never a machine id.

    An event about traced work carries its trace as a pair, `trace_id` and `span_id`
    (fabric-interop/0.1 C3.4 c); fabric_interop.trace_ids(traceparent) gives both."""
    if level not in LEVELS:
        raise ServiceError("level must be one of %s." % ", ".join(LEVELS))
    if not _KIND.match(kind):
        raise ServiceError("kind %r must be dotted lowercase." % kind)
    text = " ".join(str(text).split())
    if not text:
        raise ServiceError("An event needs a sentence.")
    if link is not None and (not link.startswith("/") or link.startswith("//")):
        raise ServiceError("link must be a path on this service.")
    if (trace_id is None) != (span_id is None):
        raise ServiceError("An event carries traceId and spanId together, or neither.")
    if trace_id is not None and not (_TRACE_ID.match(trace_id) and _SPAN_ID.match(str(span_id))):
        raise ServiceError("traceId is 32 and spanId 16 lowercase hex characters, not all zeros.")
    event: Dict[str, Any] = {"id": str(event_id), "at": at, "kind": kind, "level": level, "text": text[:500]}
    if subject:
        event["subject"] = subject
    if link:
        event["link"] = link
    if notify:
        event["notify"] = True
    if trace_id is not None:
        event["traceId"], event["spanId"] = trace_id, span_id
    return event


def parse_limit(raw: Optional[str]) -> int:
    try:
        value = int(raw) if raw not in (None, "") else EVENTS_DEFAULT_LIMIT
    except ValueError:
        raise ServiceError("limit must be an integer.") from None
    return max(1, min(EVENTS_MAX_LIMIT, value))


def events_page(fetch: Callable[[Optional[str], int], Iterable[Dict[str, Any]]],
                after: Optional[str], limit: int) -> Dict[str, Any]:
    """A cursor page over the log the service already keeps.

    `fetch(after, limit)` returns events with ids greater than `after` in
    ascending order (or the newest `limit`, ascending, when `after` is None).
    """
    events = list(fetch(after, limit))[:limit]
    cursor = events[-1]["id"] if events else (after or None)
    return {"events": events, "cursor": cursor}


class JsonlEventLog:
    """A minimal append-only log for services that keep none yet. Ids are integers as strings."""

    def __init__(self, path: Path, keep: int = 5000):
        self.path = Path(path)
        self.keep = keep

    def _all(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def append(self, kind: str, level: str, text: str, **extra: Any) -> Dict[str, Any]:
        rows = self._all()
        next_id = int(rows[-1]["id"]) + 1 if rows else 1
        event = make_event(next_id, now_iso(), kind, level, text, **extra)
        rows.append(event)
        rows = rows[-self.keep:]
        atomic_write(self.path, ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n").encode(), 0o600)
        return event

    def fetch(self, after: Optional[str], limit: int) -> List[Dict[str, Any]]:
        rows = self._all()
        if after is None:
            return rows[-limit:]
        try:
            floor = int(after)
        except ValueError:
            raise ServiceError("cursor %r is not from this service." % after) from None
        return [r for r in rows if int(r["id"]) > floor][:limit]


# --- usage report (DEC-0021) -------------------------------------------------------

USAGE_PATH = "/fabric/v1/usage"
USAGE_DAYS = 31
COST_BASES = ("provider", "price-list", "unknown")
_PROVIDER = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")


def make_usage_receipt(provider: str, model: str, *, input_tokens: int, output_tokens: int,
                       cache_read_tokens: int = 0, cache_write_tokens: int = 0,
                       cost_usd: Optional[float] = None, cost_basis: Optional[str] = None,
                       at: Optional[str] = None, route: Optional[str] = None) -> Dict[str, Any]:
    """One model call, from the provider's own usage numbers. No prompt, output or caller.

    `cost_usd` is None when the call cannot be priced: the report counts it as unpriced and
    never as $0. `cost_basis` is `provider` (the provider reported the charge) or `price-list`
    (computed from a published price list); it is `unknown` when there is no cost."""
    if not _PROVIDER.match(provider or ""):
        raise ServiceError("provider must be a lowercase name such as anthropic or openrouter.")
    model = str(model or "").strip()
    if not model or len(model) > 128:
        raise ServiceError("model must be 1 to 128 characters.")
    counts = {"inputTokens": input_tokens, "outputTokens": output_tokens,
              "cacheReadTokens": cache_read_tokens, "cacheWriteTokens": cache_write_tokens}
    for name, value in counts.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ServiceError("%s must be a non-negative integer." % name)
    if cost_usd is not None and (isinstance(cost_usd, bool) or not isinstance(cost_usd, (int, float)) or cost_usd < 0 or cost_usd != cost_usd):
        raise ServiceError("cost_usd must be a non-negative number or None.")
    basis = cost_basis or ("unknown" if cost_usd is None else "provider")
    if basis not in COST_BASES or (cost_usd is None) != (basis == "unknown"):
        raise ServiceError("cost_basis is provider or price-list with a cost, unknown without one.")
    if route is not None and route not in ROUTES:
        raise ServiceError("route is subscription or key (DEC-0046).")
    receipt = {"at": at or now_iso(), "provider": provider, "model": model, **counts,
               "costUsd": None if cost_usd is None else float(cost_usd), "costBasis": basis}
    if route is not None:
        receipt["route"] = route  # the operator's own login in its vendor's runner, or an issued key
    return receipt


def _add_totals(row: Dict[str, Any], receipt: Dict[str, Any]) -> None:
    row["calls"] += 1
    for name in ("inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens"):
        row[name] += int(receipt.get(name) or 0)
    if receipt.get("costUsd") is None:
        row["unpricedCalls"] += 1
    else:
        row["_cost"] += float(receipt["costUsd"])


def _close_totals(row: Dict[str, Any]) -> Dict[str, Any]:
    cost = row.pop("_cost")
    row["costUsd"] = None if row["calls"] and row["unpricedCalls"] == row["calls"] else round(cost, 6)
    return row


def usage_report(receipts: Iterable[Dict[str, Any]], *, service_id: str, instance: str = "default",
                 now: Optional[_dt.datetime] = None,
                 budget: Optional[Dict[str, Any]] = None,
                 budgets: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The `service-usage.schema.json` answer: the last 31 UTC days, oldest first, per provider
    and model. Days without calls are omitted. A row whose calls are all unpriced has
    `costUsd: None`; totals are the sums of the model rows (FAC-SEM-025).

    ``budgets`` (DEC-0027) lists every spending limit the service applies, enforced or not. A
    machine limit with a calendar ``period`` and no ``spentUsd`` is counted here from the receipts,
    the way ``budget`` is, so the two never disagree; a per-order limit (``per_job``, ``approval``)
    gets ``spentUsd: None``; every other limit states its own spend. A report whose limits break
    FAC-SEM-031 is refused (``usage_limit_problems``)."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    receipts = list(receipts)
    first = (now - _dt.timedelta(days=USAGE_DAYS - 1)).strftime("%Y-%m-%d")
    last = now.strftime("%Y-%m-%d")
    days: Dict[str, Dict[str, Dict[str, Any]]] = {}
    bases: Dict[Tuple[str, str, str], set] = {}
    for r in receipts:
        date = str(r.get("at", ""))[:10]
        if not (first <= date <= last):
            continue
        key = (r["provider"], r["model"], r.get("route") or "")
        row = days.setdefault(date, {}).setdefault("%s\u0000%s\u0000%s" % key, {
            "provider": r["provider"], "model": r["model"], "calls": 0, "unpricedCalls": 0,
            "inputTokens": 0, "outputTokens": 0, "cacheReadTokens": 0, "cacheWriteTokens": 0, "_cost": 0.0})
        if r.get("route"):
            row["route"] = r["route"]  # DEC-0046: rows of one model on two routes stay apart
        _add_totals(row, r)
        bases.setdefault((date,) + key, set()).add(r.get("costBasis") or "unknown")
    out_days = []
    for date in sorted(days):
        models = []
        for row in days[date].values():
            seen = bases[(date, row["provider"], row["model"], row.get("route") or "")]
            row["costBasis"] = next(iter(seen)) if len(seen) == 1 else "mixed"
            models.append(_close_totals(row))
        models.sort(key=lambda m: (m["provider"], m["model"], m.get("route") or ""))
        day = {"date": date, "calls": 0, "unpricedCalls": 0, "inputTokens": 0, "outputTokens": 0,
               "cacheReadTokens": 0, "cacheWriteTokens": 0, "_cost": 0.0}
        for m in models:
            for name in ("calls", "unpricedCalls", "inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens"):
                day[name] += m[name]
            day["_cost"] += m["costUsd"] or 0.0
        day = _close_totals(day)
        day["byModel"] = models
        out_days.append(day)
    report: Dict[str, Any] = {"protocol": PROTOCOL, "service": {"id": service_id, "instance": instance},
                              "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "currency": "USD", "days": out_days}
    if budget is not None:
        if budget.get("period") not in ("day", "month") or not isinstance(budget.get("limitUsd"), (int, float)) or budget["limitUsd"] <= 0:
            raise ServiceError("budget is {period: day|month, limitUsd > 0}.")
        report["budget"] = {"period": budget["period"], "limitUsd": float(budget["limitUsd"]),
                            "spentUsd": _spent_in(out_days, budget["period"], last)}
    if budgets is not None:
        limits = []
        for given in budgets:
            if not isinstance(given, dict):
                raise ServiceError("each limit in budgets is an object")
            limit = dict(given)
            if "spentUsd" not in limit:
                if limit.get("kind") in PER_ORDER_KINDS:
                    limit["spentUsd"] = None
                elif limit.get("scope") == "machine" and limit.get("period") in ("day", "month"):
                    limit["spentUsd"] = _spent_in(out_days, limit["period"], last)
                elif limit.get("scope") == "machine" and _number(limit.get("windowSeconds")):
                    limit["spentUsd"] = _spent_since(receipts, now - _dt.timedelta(seconds=limit["windowSeconds"]), now)
            if isinstance(limit.get("limitUsd"), int) and not isinstance(limit.get("limitUsd"), bool):
                limit["limitUsd"] = float(limit["limitUsd"])
            limits.append(limit)
        report["budgets"] = limits
        problems = usage_limit_problems(report)
        if problems:
            raise ServiceError("the report's limits are not coherent: " + "; ".join(problems))
    return report


def _spent_since(receipts: List[Dict[str, Any]], start: _dt.datetime, end: _dt.datetime) -> Optional[float]:
    """Spend in a rolling window, from the receipts' own times; None when every call in it is unpriced."""
    lo, hi = start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")
    inside = [r for r in receipts if lo < str(r.get("at", "")) <= hi]
    if inside and all(r.get("costUsd") is None for r in inside):
        return None
    return round(sum(r.get("costUsd") or 0.0 for r in inside), 6)


def _spent_in(out_days: List[Dict[str, Any]], period: str, last: str) -> Optional[float]:
    """Spend in the current UTC day or month; None when every call in it is unpriced."""
    prefix = last if period == "day" else last[:7]
    window = [d for d in out_days if d["date"].startswith(prefix)]
    unknown = bool(window) and all(d["costUsd"] is None for d in window)
    return None if unknown else round(sum(d["costUsd"] or 0.0 for d in window), 6)


# --- every spending limit (DEC-0027, FAC-SEM-031) ---------------------------------

LIMIT_SCOPES = ("machine", "project", "pool", "job")
PER_ORDER_KINDS = ("per_job", "approval")
_LIMIT_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}$")
_LIMIT_KIND = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_LIMIT_FIELDS = ("id", "scope", "subject", "kind", "period", "windowSeconds", "since", "limitUsd", "spentUsd", "enforced", "tripped")
_TIMESTAMP = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]+)?([Zz]|[+-]([0-9]{2}):([0-9]{2}))")


def _is_timestamp(value: Any) -> bool:
    """A JSON Schema `date-time` (RFC 3339): a real calendar date and time, `Z` or an offset."""
    m = _TIMESTAMP.fullmatch(value) if isinstance(value, str) else None
    if not m:
        return False
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    try:
        _dt.date(year, month, day)
    except ValueError:
        return False
    offset_ok = m.group(9) is None or (int(m.group(9)) <= 23 and int(m.group(10)) <= 59)
    return hour <= 23 and minute <= 59 and second <= 60 and offset_ok


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def usage_limit_problems(report: Dict[str, Any]) -> List[str]:
    """The `budgets` of a usage report against `service-usage.schema.json` `$defs/limit` and FAC-SEM-031: unique
    ids, a subject exactly for project and pool scope, one window that agrees with the kind, per-order limits with
    no window and no spend, only a relative limit with a null `limitUsd`, a tripped limit enforced, and a legacy
    `budget` that repeats one enforced machine limit. A breach (spent above the limit) is not a problem: a report
    truthfully shows one, and a host shows it first. An unknown kind is never refused."""
    problems: List[str] = []
    limits = report.get("budgets")
    if limits is None:
        return problems
    if not isinstance(limits, list) or len(limits) > 64:
        return ["budgets is a list of at most 64 limits"]
    seen = set()
    for i, limit in enumerate(limits):
        at = "/budgets/%d" % i
        if not isinstance(limit, dict):
            problems.append("%s is not an object" % at)
            continue
        for key in limit:
            if key not in _LIMIT_FIELDS:
                problems.append("%s/%s is not a limit field" % (at, key))
        for key in ("id", "scope", "kind", "limitUsd", "spentUsd", "enforced"):
            if key not in limit:
                problems.append("%s is missing %s" % (at, key))
        if "id" in limit and not (isinstance(limit["id"], str) and _LIMIT_ID.fullmatch(limit["id"])):
            problems.append("%s/id must match %s" % (at, _LIMIT_ID.pattern))
        if "scope" in limit and limit["scope"] not in LIMIT_SCOPES:
            problems.append("%s/scope must be one of %s" % (at, ", ".join(LIMIT_SCOPES)))
        if "subject" in limit and not (isinstance(limit["subject"], str) and 1 <= len(limit["subject"]) <= 128):
            problems.append("%s/subject is 1 to 128 characters" % at)
        if "kind" in limit and not (isinstance(limit["kind"], str) and _LIMIT_KIND.fullmatch(limit["kind"])):
            problems.append("%s/kind must match %s" % (at, _LIMIT_KIND.pattern))
        if "period" in limit and limit["period"] not in ("day", "month"):
            problems.append("%s/period is day or month" % at)
        if "windowSeconds" in limit and not (isinstance(limit["windowSeconds"], int) and not isinstance(limit["windowSeconds"], bool)
                                             and limit["windowSeconds"] >= 1):
            problems.append("%s/windowSeconds is a whole number of seconds, at least 1" % at)
        if "since" in limit and not _is_timestamp(limit["since"]):
            problems.append("%s/since is a UTC timestamp" % at)
        if "limitUsd" in limit and not (limit["limitUsd"] is None or (_number(limit["limitUsd"]) and limit["limitUsd"] > 0)):
            problems.append("%s/limitUsd is a dollar amount above zero, or null" % at)
        if "spentUsd" in limit and not (limit["spentUsd"] is None or (_number(limit["spentUsd"]) and limit["spentUsd"] >= 0)):
            problems.append("%s/spentUsd is a dollar amount, zero or more, or null" % at)
        for key in ("enforced", "tripped"):
            if key in limit and not isinstance(limit[key], bool):
                problems.append("%s/%s is true or false" % (at, key))

        # FAC-SEM-031
        ident = str(limit.get("id", ""))
        if ident in seen:
            problems.append("FAC-SEM-031 %s/id: limit id %s appears twice" % (at, ident))
        seen.add(ident)
        scope = limit.get("scope")
        named = scope in ("project", "pool")
        if named and "subject" not in limit:
            problems.append("FAC-SEM-031 %s/subject: a %s limit names its %s in subject" % (at, scope, scope))
        if not named and "subject" in limit:
            problems.append("FAC-SEM-031 %s/subject: a %s limit has no subject" % (at, scope))
        windows = [f for f in ("period", "windowSeconds", "since") if f in limit]
        if len(windows) > 1:
            problems.append("FAC-SEM-031 %s/%s: a limit has one window, not %s" % (at, windows[1], " and ".join(windows)))
        kind = str(limit.get("kind", ""))
        seconds = limit.get("windowSeconds") if _number(limit.get("windowSeconds")) else None
        if kind in PER_ORDER_KINDS:
            if windows:
                problems.append("FAC-SEM-031 %s/%s: %s bounds one order and has no window" % (at, windows[0], kind))
            if limit.get("spentUsd", 0) is not None:
                problems.append("FAC-SEM-031 %s/spentUsd: %s bounds one order, so nothing is spent against it (null)" % (at, kind))
        elif kind == "daily":
            if not (limit.get("period") == "day" or seconds == 86400):
                problems.append("FAC-SEM-031 %s/period: a daily limit counts the UTC day (period day) or the last 24 hours (windowSeconds 86400)" % at)
        elif kind == "monthly":
            if not (limit.get("period") == "month" or (seconds is not None and 28 * 86400 <= seconds <= 31 * 86400)):
                problems.append("FAC-SEM-031 %s/period: a monthly limit counts the UTC month (period month) or a rolling 28–31 days (windowSeconds)" % at)
        elif kind == "velocity":
            if seconds is None:
                problems.append("FAC-SEM-031 %s/windowSeconds: a velocity limit counts a rolling window (windowSeconds)" % at)
        elif kind in ("pool", "emergency"):
            if not windows:
                problems.append("FAC-SEM-031 %s/period: a %s limit names the window it counts (period, windowSeconds or since)" % (at, kind))
        known = kind in PER_ORDER_KINDS or kind in ("daily", "monthly", "pool", "emergency")
        if known and "limitUsd" in limit and limit["limitUsd"] is None:
            problems.append("FAC-SEM-031 %s/limitUsd: a %s limit is a dollar amount; only a relative limit (velocity) may leave it null" % (at, kind))
        if limit.get("tripped") is True and limit.get("enforced") is not True:
            problems.append("FAC-SEM-031 %s/tripped: a limit that is not enforced cannot have stopped work" % at)

    budget = report.get("budget")
    if isinstance(budget, dict) and limits:
        kind = "daily" if budget.get("period") == "day" else "monthly"

        def same(x: Any, y: Any) -> bool:
            if x is None or y is None:
                return x is y
            return _number(x) and _number(y) and abs(x - y) <= 0.000001

        twin = any(isinstance(l, dict) and l.get("scope") == "machine" and l.get("enforced") is True and l.get("kind") == kind
                   and l.get("period") == budget.get("period") and same(l.get("limitUsd"), budget.get("limitUsd"))
                   and same(l.get("spentUsd"), budget.get("spentUsd")) for l in limits)
        if not twin:
            problems.append("FAC-SEM-031 /budget: budget repeats one enforced machine %s limit with period %s in budgets[], so old "
                            "and new readers agree" % (kind, budget.get("period")))
    return problems


# --- the feed client (DEC-0025, FAC-SEM-036) --------------------------------------

def token_header(auth: Any, token: str) -> Tuple[str, str]:
    """The one header a client sends the service token in, as the descriptor's ``auth`` declares it: ``header``
    defaults to Authorization and ``scheme`` to Bearer; ``none`` carries the raw token. Never assume
    ``Authorization: Bearer`` (a feed client that did was refused on every poll and dropped every notify event)."""
    declared = auth if isinstance(auth, dict) else {}
    name = declared.get("header") if isinstance(declared.get("header"), str) else "Authorization"
    scheme = declared.get("scheme") if isinstance(declared.get("scheme"), str) else "Bearer"
    return name, token if scheme == "none" else "Bearer " + token


# --- settings backups (DEC-0025, FAC-SEM-035) -------------------------------------

SETTINGS_BACKUP_FORMAT = "fabric-settings-backup/1"
SETTINGS_BACKUP_KEEP = 14
SETTINGS_BACKUP_MAX_AGE_SECONDS = 24 * 60 * 60
_STALE_TEMP_SECONDS = 60 * 60
_SAFE_INTEGER = 2 ** 53 - 1
_TABLE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_SECRET_TABLE = re.compile(r"^((.+_)?(account_connections?|account_connection_drafts?|tokens?|secrets?|credentials?|passwords?|login_codes?)|(operator_)?sessions?)$")
_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_SECRET_COLUMN = re.compile(r"^(?:.+_)?(?:[Tt]oken|[Ss]ecret|[Pp]assword|[Pp]assphrase|[Aa]pi_?[Kk]ey|[Pp]rivate_[Kk]ey|[Cc]ookie|[Ll]ogin_[Cc]ode|[Oo]tp|[Cc]redential)s?$")
_REASON = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SURROGATE = re.compile("[\ud800-\udfff]")
_URI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:\S*")
_MAX_CELL_CHARS = 1048576
_MAX_ROW_VALUES = 512


def _canonical_check(value: Any, at: str = "") -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        # CT-25 (DEC-0052): Python cannot encode a lone surrogate as UTF-8, so no two languages agree on its bytes.
        if _SURROGATE.search(value):
            raise ServiceError("%s: a lone surrogate has no canonical form" % (at or "/"))
        return
    if isinstance(value, int):
        if abs(value) > _SAFE_INTEGER:
            raise ServiceError("%s: %d is outside ±(2^53 − 1) and has no canonical form; store it as a string" % (at or "/", value))
        return
    if isinstance(value, float):
        raise ServiceError("%s: a fraction has no canonical form; a settings backup stores it as its decimal string" % (at or "/"))
    if isinstance(value, list):
        for i, item in enumerate(value):
            _canonical_check(item, "%s/%d" % (at, i))
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ServiceError("%s: object keys are strings" % (at or "/"))
            _canonical_check(key, "%s (a key)" % (at or "/"))
            _canonical_check(item, "%s/%s" % (at, key))
        return
    raise ServiceError("%s: %s is not a JSON value" % (at or "/", type(value).__name__))


def settings_canonical_json(value: Any) -> str:
    """The settings canonical form (DEC-0025, DEC-0043): keys sorted by code point at every level, ", " and ": ",
    strings escaped as JSON requires and nothing else, integers in decimal — Python's
    ``json.dumps(value, sort_keys=True, ensure_ascii=False)``. Refuses a fraction, an integer outside ±(2^53 − 1)
    and anything that is not JSON."""
    _canonical_check(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def settings_backup_digest(tables: Any) -> str:
    """The ``sha256`` a settings backup carries: SHA-256 of the UTF-8 canonical JSON of ``tables``."""
    return hashlib.sha256(settings_canonical_json(tables).encode("utf-8")).hexdigest()


def settings_backup_problems(doc: Any) -> List[str]:
    """Why a reader refuses this settings backup: its shape (``settings-backup.schema.json``) and FAC-SEM-035 —
    the checksum is the digest of the tables, counts name exactly the tables and their rows, every row is as wide as
    its columns, and every value has a canonical form. Empty means intact."""
    if not isinstance(doc, dict):
        return ["a settings backup is a JSON object"]
    problems: List[str] = []
    if doc.get("format") != SETTINGS_BACKUP_FORMAT:
        problems.append("format must be %s, not %r: a reader refuses a format it does not know" % (SETTINGS_BACKUP_FORMAT, doc.get("format")))
    for key in ("format", "service", "created_at", "reason", "sha256", "counts", "tables"):
        if key not in doc:
            problems.append("missing %s" % key)
    for key in doc:
        if key not in ("format", "service", "created_at", "reason", "sha256", "counts", "tables", "extensions"):
            problems.append("%s is not a settings backup field" % key)
    if "extensions" in doc:
        if not isinstance(doc["extensions"], dict):
            problems.append("extensions is an object")
        else:
            for key in doc["extensions"]:
                if not _URI.fullmatch(key):
                    problems.append("extensions key %r is not a URI" % key)
    service = doc.get("service")
    if "service" in doc:
        if not isinstance(service, dict) or set(service) != {"id", "instance", "version", "schema"}:
            problems.append("service is {id, instance, version, schema}")
        else:
            if not _ID.fullmatch(str(service["id"])):
                problems.append("service.id must match %s" % _ID.pattern)
            if not _INSTANCE.fullmatch(str(service["instance"])):
                problems.append("service.instance must match %s" % _INSTANCE.pattern)
            if not (isinstance(service["version"], str) and len(service["version"]) <= 64):
                problems.append("service.version is a string of at most 64 characters")
            schema = service["schema"]
            if not ((isinstance(schema, int) and not isinstance(schema, bool) and schema >= 0)
                    or (isinstance(schema, str) and 1 <= len(schema) <= 64)):
                problems.append("service.schema is a whole number or a short string")
    if "created_at" in doc and not _is_timestamp(doc["created_at"]):
        problems.append("created_at is a UTC timestamp")
    if "reason" in doc and not (isinstance(doc["reason"], str) and _REASON.fullmatch(doc["reason"])):
        problems.append("reason must match %s" % _REASON.pattern)
    if "sha256" in doc and not (isinstance(doc["sha256"], str) and _SHA256.fullmatch(doc["sha256"])):
        problems.append("sha256 is 64 lowercase hex digits")
    tables = doc.get("tables") if isinstance(doc.get("tables"), dict) else {}
    counts = doc.get("counts") if isinstance(doc.get("counts"), dict) else {}
    if "tables" in doc and not isinstance(doc.get("tables"), dict):
        problems.append("tables is an object")
    if "counts" in doc and not isinstance(doc.get("counts"), dict):
        problems.append("counts is an object")
    for name in list(tables) + [n for n in counts if n not in tables]:
        if not _TABLE.fullmatch(name) or _SECRET_TABLE.fullmatch(name):
            problems.append("table %s is never backed up: it can only hold connections, tokens, secrets, credentials, "
                            "passwords, login codes or sessions (or its name is not a table name)" % name)
    for name, count in counts.items():
        if not (isinstance(count, int) and not isinstance(count, bool) and count >= 0):
            problems.append("counts.%s is a whole number" % name)
    canonical = True
    for name, table in tables.items():
        if not isinstance(table, dict) or set(table) != {"columns", "rows"}:
            problems.append("tables.%s is {columns, rows}" % name)
            continue
        columns, rows = table["columns"], table["rows"]
        if not (isinstance(columns, list) and 1 <= len(columns) <= 512 and len(set(map(str, columns))) == len(columns)):
            problems.append("tables.%s.columns is 1 to 512 distinct names" % name)
            columns = columns if isinstance(columns, list) else []
        for column in columns:
            if not (isinstance(column, str) and _COLUMN.fullmatch(column)) or _SECRET_COLUMN.fullmatch(str(column)):
                problems.append("column %s.%s is refused: its name says it holds a credential value (name the secret, "
                                "never store it: secret_name, token_slot)" % (name, column))
        if not isinstance(rows, list):
            problems.append("tables.%s.rows is a list" % name)
            continue
        width = len(columns)
        for i, row in enumerate(rows):
            at = "/tables/%s/rows/%d" % (name, i)
            if not isinstance(row, list):
                problems.append("%s is a list of values" % at)
                continue
            if len(row) != width:
                problems.append("FAC-SEM-035 %s: row has %d values for %d columns" % (at, len(row), width))
            if len(row) > _MAX_ROW_VALUES:
                problems.append("%s holds more than %d values" % (at, _MAX_ROW_VALUES))
            for j, cell in enumerate(row):
                if isinstance(cell, float) or (isinstance(cell, int) and not isinstance(cell, bool) and abs(cell) > _SAFE_INTEGER):
                    canonical = False
                    problems.append("FAC-SEM-035 %s/%d: a fraction or an unsafe integer has no canonical form; store it as a string" % (at, j))
                elif isinstance(cell, str) and _SURROGATE.search(cell):
                    canonical = False
                    problems.append("FAC-SEM-035 %s/%d: a string with a lone surrogate cannot be encoded as UTF-8" % (at, j))
                elif isinstance(cell, str) and len(cell) > _MAX_CELL_CHARS:
                    problems.append("%s/%d is longer than %d characters" % (at, j, _MAX_CELL_CHARS))
                elif not (cell is None or isinstance(cell, (bool, int, str))):
                    canonical = False
                    problems.append("%s/%d is not a JSON scalar" % (at, j))
        if counts.get(name) != len(rows):
            problems.append("FAC-SEM-035 /counts/%s: counts says %s for %d rows" % (name, counts.get(name, "nothing"), len(rows)))
    for name in counts:
        if name not in tables:
            problems.append("FAC-SEM-035 /counts/%s: counts names %s, which the backup does not carry" % (name, name))
    if canonical and isinstance(doc.get("tables"), dict):
        try:
            digest: Optional[str] = settings_backup_digest(tables)
        except (ServiceError, UnicodeError, TypeError, ValueError) as exc:  # a name no canonical form can carry
            digest = None
            problems.append("FAC-SEM-035 /tables: the tables have no canonical form (%s)" % exc)
        if digest is not None and doc.get("sha256") != digest:
            problems.append("FAC-SEM-035 /sha256: the checksum does not match the tables: the file is damaged and a reader refuses it")
    return problems


def settings_backup_root(platform: str = sys.platform) -> Path:
    """Where every service keeps its settings backups — outside its data directory (DEC-0025)."""
    if platform == "darwin":
        return Path.home() / "Library/Application Support/PassionCode"
    if platform == "win32":
        appdata = os.environ.get("APPDATA")
        return (Path(appdata) if appdata else Path.home() / "AppData" / "Roaming") / "PassionCode"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "PassionCode"


def settings_backup_dir(service_id: str, instance: str = "default", root: Optional[Path] = None) -> Path:
    _require_id(service_id)
    if not (isinstance(instance, str) and _INSTANCE.fullmatch(instance)):
        raise ServiceError("instance must match %s" % _INSTANCE.pattern)
    return (root or settings_backup_root()) / "settings-backups" / service_id / instance


def make_settings_backup(*, service_id: str, instance: str = "default", version: str, schema: Any,
                         tables: Dict[str, Dict[str, Any]], reason: str, now: Optional[_dt.datetime] = None) -> Dict[str, Any]:
    """A snapshot of the operator's decisions and bindings: the tables on the service's allow-list, each
    ``{"columns": [...], "rows": [[...], ...]}`` of JSON scalars (a fraction as its decimal string). Refuses a file a
    reader would refuse."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    doc = {"format": SETTINGS_BACKUP_FORMAT,
           "service": {"id": service_id, "instance": instance, "version": version, "schema": schema},
           "created_at": now.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "reason": reason,
           "sha256": "", "counts": {name: len(table.get("rows") or []) for name, table in tables.items()}, "tables": tables}
    try:
        doc["sha256"] = settings_backup_digest(tables)
    except ServiceError as exc:
        raise ServiceError("this snapshot has no canonical form: %s" % exc) from None
    problems = settings_backup_problems(doc)
    if problems:
        raise ServiceError("this snapshot would be refused: " + "; ".join(problems))
    return doc


def _backup_name(doc: Dict[str, Any]) -> str:
    stamp = doc["created_at"].replace("-", "").replace(":", "")
    head, _, frac = stamp.rstrip("Z").partition(".")
    return "settings-%s%sZ.json" % (head, (frac + "000000")[:6])


def settings_backups(directory: Path) -> List[Path]:
    """The snapshot files, newest first (their names sort in time order)."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted((p for p in directory.iterdir() if re.fullmatch(r"settings-[0-9]{8}T[0-9]{12}Z\.json", p.name)), reverse=True)


def _no_constant(name: str) -> Any:
    raise ValueError("%s is not JSON" % name)


def read_settings_backup(path: Path) -> Dict[str, Any]:
    """A snapshot a reader may trust, or ServiceError naming why it is refused (FAC-SEM-035)."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=_no_constant)
    except (OSError, ValueError) as exc:
        raise ServiceError("settings backup %s cannot be read: %s" % (path, exc)) from None
    problems = settings_backup_problems(doc)
    if problems:
        raise ServiceError("settings backup %s is refused: %s" % (path, "; ".join(problems)))
    return doc


def write_settings_backup(doc: Dict[str, Any], directory: Path, *, keep: int = SETTINGS_BACKUP_KEEP) -> Optional[Path]:
    """Write a snapshot made by ``make_settings_backup``: atomically, 0600 in a 0700 directory, named by its time.
    A temporary file an interrupted write left is removed first; a snapshot whose checksum equals the newest file's
    is not written again (None). After a write, all but the ``keep`` newest are removed (at least 14)."""
    problems = settings_backup_problems(doc)
    if problems:
        raise ServiceError("this snapshot would be refused: " + "; ".join(problems))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    ensure_private_dir(directory)
    stale = time.time() - _STALE_TEMP_SECONDS
    for left in directory.iterdir():
        # Only a temporary file an interrupted write left: one a concurrent writer is still filling is younger.
        try:
            if left.name.startswith(".settings-") and left.stat().st_mtime < stale:
                left.unlink()
        except OSError:
            pass
    existing = settings_backups(directory)
    if existing:
        try:
            if read_settings_backup(existing[0])["sha256"] == doc["sha256"]:
                return None
        except Exception:  # noqa: BLE001 - a damaged newest file is no reason to skip a good snapshot
            pass
    path = directory / _backup_name(doc)
    atomic_write(path, json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8") + b"\n", 0o600)
    # The newest by name, but never the one just written: a clock that stepped back must not delete it.
    for old in [p for p in settings_backups(directory) if p != path][max(keep, SETTINGS_BACKUP_KEEP) - 1:]:
        old.unlink()
    return path


def backup_due(directory: Path, now: Optional[_dt.datetime] = None) -> bool:
    """True when there is no snapshot or the newest is older than 24 hours: take one at start or on the daily tick."""
    newest = settings_backups(directory)
    if not newest:
        return True
    try:
        stamp = _dt.datetime.strptime(newest[0].name[len("settings-"):-len("Z.json")], "%Y%m%dT%H%M%S%f").replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return True  # a name no calendar has: take a fresh snapshot rather than trust it
    return ((now or _dt.datetime.now(_dt.timezone.utc)) - stamp).total_seconds() > SETTINGS_BACKUP_MAX_AGE_SECONDS


def newest_intact_backup(directory: Path) -> Tuple[Optional[Path], Optional[Dict[str, Any]], List[Tuple[Path, str]]]:
    """The source of an automatic restore: the newest snapshot that is intact and has content. Damaged ones are
    skipped and returned with the reason, for the restore report."""
    skipped: List[Tuple[Path, str]] = []
    for path in settings_backups(directory):
        try:
            doc = read_settings_backup(path)
        except Exception as exc:  # noqa: BLE001 - one damaged file never stops the scan
            skipped.append((path, str(exc)))
            continue
        if any(doc["counts"].values()):
            return path, doc, skipped
    return None, None, skipped


def restore_plan(doc: Dict[str, Any], current: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """What restoring ``doc`` would do — it adds and never overwrites (DEC-0025). ``current`` describes the database
    now, per table: ``columns`` (all of them), ``key`` (the primary key columns), ``required`` (columns without a
    default) and ``existing`` (the primary keys present, as tuples). Per table: the rows to insert (dicts over the
    columns both sides have), how many are already present, the snapshot columns dropped, the current columns left
    to their defaults, the required columns the snapshot lacks, and every row refused with its key and reason.
    ``unknownTables`` names snapshot tables the service no longer has. The service applies ``insert`` and adds any
    row its database refuses to ``refused``; a manual restore shows this plan first and applying it is the operator's act."""
    problems = settings_backup_problems(doc)
    if problems:
        raise ServiceError("a damaged snapshot is never restored: " + "; ".join(problems))
    plan: Dict[str, Any] = {"source": {"created_at": doc["created_at"], "sha256": doc["sha256"]}, "tables": {}, "unknownTables": []}
    for name, table in doc["tables"].items():
        now_table = current.get(name)
        if now_table is None:
            plan["unknownTables"].append(name)
            continue
        columns = list(now_table.get("columns") or [])
        key = list(now_table.get("key") or [])
        required = list(now_table.get("required") or [])
        existing = {tuple(k) for k in now_table.get("existing") or []}
        shared = [c for c in table["columns"] if c in columns]
        missing = [c for c in required if c not in table["columns"]]
        entry = {"insert": [], "present": 0, "droppedColumns": [c for c in table["columns"] if c not in columns],
                 "defaultedColumns": [c for c in columns if c not in table["columns"]], "missingRequired": missing, "refused": []}
        planned = set()
        for row in table["rows"]:
            values = dict(zip(table["columns"], row))
            ident = [values.get(c) for c in key]
            if any(c not in table["columns"] for c in key):
                entry["refused"].append({"key": ident, "reason": "the primary key is not in the snapshot"})
            elif tuple(ident) in planned:
                entry["refused"].append({"key": ident, "reason": "the snapshot holds this key twice"})
            elif tuple(ident) in existing:
                entry["present"] += 1
            elif missing:
                entry["refused"].append({"key": ident, "reason": "required column %s is not in the snapshot" % ", ".join(missing)})
            else:
                planned.add(tuple(ident))
                entry["insert"].append({c: values[c] for c in shared})
        plan["tables"][name] = entry
    return plan


class JsonlUsageLedger:
    """Usage receipts for services that keep none yet: append-only JSON lines, mode 0600, pruned
    to the reported window so the file stays bounded (LC-12). One writer process — the service,
    which holds its instance lock; the lock here orders that process's threads."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def record(self, receipt: Dict[str, Any]) -> None:
        line = json.dumps(receipt, separators=(",", ":")) + "\n"
        with self._lock:
            ensure_private_dir(self.path.parent)
            fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT | os.O_APPEND | _O_BINARY, 0o600)
            try:
                size = os.fstat(fd).st_size
                if size and _read_at(fd, 1, size - 1) != b"\n":
                    line = "\n" + line  # a killed writer left a torn line: never glue a receipt to it
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)

    def receipts(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # a torn last line from a killed writer is skipped, not fatal
        return out

    def prune(self, now: Optional[_dt.datetime] = None) -> int:
        """Drop receipts older than the reported window; returns how many were dropped."""
        now = now or _dt.datetime.now(_dt.timezone.utc)
        first = (now - _dt.timedelta(days=USAGE_DAYS - 1)).strftime("%Y-%m-%d")
        with self._lock:
            every = self.receipts()
            kept = [r for r in every if str(r.get("at", ""))[:10] >= first]
            dropped = len(every) - len(kept)
            if dropped:
                atomic_write(self.path, "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in kept).encode("utf-8"))
            return dropped

    def report(self, *, service_id: str, instance: str = "default", now: Optional[_dt.datetime] = None,
               budget: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return usage_report(self.receipts(), service_id=service_id, instance=instance, now=now, budget=budget)


# --- logs (LC-12) ---------------------------------------------------------------

class RotatingLog:
    """One structured log: JSON lines rotated by size (5 x 5 MB by default), files 0600 in a
    0700 directory. ``service.jsonl`` -> ``.1`` ... ``.<backups>``; the oldest falls off.

    Never pass a token, a cookie, a login code or a request body that may carry one."""

    def __init__(self, path: Path, max_bytes: int = LOG_MAX_BYTES, backups: int = LOG_BACKUPS):
        if max_bytes < 256 or backups < 1:
            raise ServiceError("A rotating log needs max_bytes >= 256 and at least one backup.")
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.backups = backups
        self._lock = threading.Lock()

    def _line(self, record: Dict[str, Any]) -> bytes:
        data = (json.dumps(record, ensure_ascii=False) + "\n").encode()
        if len(data) <= self.max_bytes:
            return data
        record = dict(record, truncated=True)
        message = str(record.get("message", ""))
        while message:
            message = message[: len(message) // 2]
            record["message"] = message
            data = (json.dumps(record, ensure_ascii=False) + "\n").encode()
            if len(data) <= self.max_bytes:
                return data
        return (json.dumps({"at": record.get("at"), "level": record.get("level"), "message": "",
                            "truncated": True}) + "\n").encode()

    def write(self, level: str, message: str, **fields: Any) -> None:
        record: Dict[str, Any] = {"at": now_iso(), "level": str(level), "message": str(message)}
        record.update(fields)
        data = self._line(record)
        with self._lock:
            ensure_private_dir(self.path.parent)
            try:
                size = self.path.stat().st_size
            except FileNotFoundError:
                size = 0
            if size and size + len(data) > self.max_bytes:
                self._rotate()
            fd = os.open(str(self.path), os.O_WRONLY | os.O_APPEND | os.O_CREAT | _O_BINARY, 0o600)
            try:
                os.write(fd, data)
            finally:
                os.close(fd)

    def _rotate(self) -> None:
        for index in range(self.backups - 1, 0, -1):
            older = Path("%s.%d" % (self.path, index))
            if older.exists():
                os.replace(older, "%s.%d" % (self.path, index + 1))
        os.replace(self.path, "%s.1" % self.path)


def cap_stdout_log(path: Path, max_bytes: int = LOG_MAX_BYTES) -> bool:
    """Call once at start: a launchd stdout file over ``max_bytes`` is copied to ``<path>.1`` and
    truncated in place. launchd holds the file open for append, so a rename would leave it
    writing to the old name; truncation keeps its descriptor valid. Returns True when capped."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return False
    if size <= max_bytes:
        return False
    backup = Path("%s.1" % path)
    shutil.copyfile(path, backup)
    os.chmod(backup, 0o600)
    with open(path, "r+b") as handle:
        handle.truncate(0)
    return True


# --- shutdown (LC-01) -------------------------------------------------------------

class Stopping(ServiceError):
    """The service is stopping and takes no new work."""


class Drain:
    """SIGTERM/SIGINT: stop taking new work, drain in-flight work until ``deadline``, then hand
    over with ``on_stop(drained)``. A hand-over that hangs is cut by a hard exit
    (``EXIT_HARD_STOP``) ``grace`` seconds later, so quit reaches exit inside the lifecycle bound.

        drain = fs.Drain()
        drain.install(lambda drained: server.shutdown(),
                      on_stopping=lambda: log.append("service.stopping", "info", "Stopping."))
        with drain.work():          # raises fs.Stopping once a stop has begun
            ...
    """

    def __init__(self, deadline: float = DRAIN_SECONDS, grace: float = DRAIN_GRACE_SECONDS):
        self.deadline = deadline
        self.grace = grace
        self._cond = threading.Condition()
        self._inflight = 0
        self._stopping = False

    @property
    def stopping(self) -> bool:
        return self._stopping

    @property
    def inflight(self) -> int:
        return self._inflight

    @contextlib.contextmanager
    def work(self):
        with self._cond:
            if self._stopping:
                raise Stopping("The service is stopping and takes no new work.")
            self._inflight += 1
        try:
            yield
        finally:
            with self._cond:
                self._inflight -= 1
                self._cond.notify_all()

    def request_stop(self) -> bool:
        """Refuse new work from now on; False when a stop had already begun."""
        with self._cond:
            if self._stopping:
                return False
            self._stopping = True
            return True

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait for in-flight work to finish; True when it did inside ``timeout``."""
        end = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while self._inflight > 0:
                left = None if end is None else end - time.monotonic()
                if left is not None and left <= 0:
                    return False
                self._cond.wait(left)
            return True

    def install(self, on_stop: Callable[[bool], None], *, on_stopping: Optional[Callable[[], None]] = None,
                signals: Sequence[int] = (signal.SIGTERM, signal.SIGINT)) -> "Drain":
        """Install the handlers (main thread only). A second signal changes nothing: the hard-exit
        timer already holds the deadline."""
        def handler(_signum: int, _frame: Any) -> None:
            if self.request_stop():
                threading.Thread(target=self._stop, args=(on_stopping, on_stop), daemon=True).start()

        for sig in signals:
            signal.signal(sig, handler)
        return self

    def _stop(self, on_stopping: Optional[Callable[[], None]], on_stop: Callable[[bool], None]) -> None:
        hard = threading.Timer(self.deadline + self.grace, os._exit, args=(EXIT_HARD_STOP,))
        hard.daemon = True
        hard.start()
        if on_stopping is not None:
            try:
                on_stopping()
            except Exception:  # a failing stop notice must not stop the drain
                traceback.print_exc()
        on_stop(self.wait(self.deadline))


# --- operator login ----------------------------------------------------------

class LoginCodes:
    """Single-use login codes (<=120 s), recorded as used BEFORE they are honoured, and operator
    sessions with the DEC-0039 lifetime: a session ends 12 h after its last use, 7 days after the code
    was redeemed, on logout, and when the descriptor token rotates. The server enforces all four: the
    cookie carries a signed claim (session id, sign-in time, token revision) and the code store keeps a
    record per session (last use, logout). Rotating the key with revoke_all() ends every session."""

    def __init__(self, state_dir: Optional[Path], ttl: int = LOGIN_CODE_TTL_SECONDS, *,
                 store: Optional["MemoryCodeStore"] = None, key: Optional[bytes] = None,
                 token: "Optional[str | Callable[[], str]]" = None,
                 idle_seconds: int = OPERATOR_SESSION_IDLE_SECONDS,
                 max_seconds: int = OPERATOR_SESSION_MAX_SECONDS,
                 clock: Callable[[], float] = time.time):
        # A local service keeps codes, sessions and the key in files. An online one (DEC-0019) usually has
        # no durable disk: pass state_dir=None with store=MemoryCodeStore() and key= bytes from a platform
        # secret. A memory store forgets codes AND sessions on a restart, so a deploy signs the operator
        # out (the host signs in again on the page's 401); pass a durable store to keep sessions.
        # token= is the descriptor token, or a callable returning the current one: a session begun under
        # one token is refused once it rotates. A service MAY shorten either bound, never lengthen one.
        self.ttl = min(ttl, LOGIN_CODE_TTL_SECONDS)
        self.idle_seconds = _session_bound(idle_seconds, OPERATOR_SESSION_IDLE_SECONDS)
        self.max_seconds = _session_bound(max_seconds, OPERATOR_SESSION_MAX_SECONDS)
        # One lock around every load-modify-save, so a concurrent refresh never saves over a logout or a
        # burned code (a threading server checks sessions on several threads; the instance lock keeps
        # other processes out of the state directory).
        self._lock = threading.RLock()
        self._store = store
        self._fixed_key = key
        self._token = token
        self._clock = clock
        if state_dir is not None:
            self.dir = ensure_private_dir(Path(state_dir))
            self._key_path = self.dir / "session.key"
            self._codes_path = self.dir / "login-codes.json"
        elif store is None or key is None:
            raise ServiceError("LoginCodes without a state directory needs store= and key=.")
        if key is not None and len(key) < 32:
            raise ServiceError("the session key must be at least 32 bytes.")

    def _key(self) -> bytes:
        if self._fixed_key is not None:
            return bytes(self._fixed_key)
        if not self._key_path.exists():
            atomic_write(self._key_path, secrets.token_bytes(32), 0o600)
        return self._key_path.read_bytes()

    def _load(self) -> Dict[str, Any]:
        if self._store is not None:
            return self._store.load()
        try:
            return json.loads(self._codes_path.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, codes: Dict[str, Any]) -> None:
        horizon = self._clock() - 3600
        codes = {k: v for k, v in codes.items() if v.get("expires", 0) > horizon}
        if self._store is not None:
            self._store.save(codes)
            return
        atomic_write(self._codes_path, json.dumps(codes).encode(), 0o600)

    def issue(self) -> Dict[str, str]:
        with self._lock:
            code = secrets.token_urlsafe(24)
            expires = self._clock() + self.ttl
            codes = self._load()
            codes[hashlib.sha256(code.encode()).hexdigest()] = {"expires": expires, "used": False}
            self._save(codes)
            at = _dt.datetime.fromtimestamp(expires, _dt.timezone.utc).replace(microsecond=0)
            return {"url": "/fabric/v1/login?code=" + code, "expiresAt": at.isoformat().replace("+00:00", "Z")}

    def redeem(self, code: Optional[str]) -> Optional[str]:
        """Return a session cookie value, or None. The code is burned even when it has expired."""
        with self._lock:
            if not code or not _CODE.match(code):
                return None
            digest = hashlib.sha256(code.encode()).hexdigest()
            codes = self._load()
            entry = codes.get(digest)
            if not entry or entry.get("used"):
                return None
            entry["used"] = True
            self._save(codes)
            now = self._clock()
            if entry.get("expires", 0) < now:
                return None
            session_id = secrets.token_urlsafe(18)
            signed_in = int(now)
            codes[self._record_key(session_id)] = {"expires": signed_in + self.max_seconds,
                                                   "signedInAt": signed_in, "lastUsedAt": now}
            self._save(codes)
            claim = "v2.%s.%d.%s" % (session_id, signed_in, self._token_revision())
            return claim + "." + self._mac(claim)

    def session_valid(self, cookie_value: Optional[str]) -> bool:
        """True while the session is live; a use within the bounds refreshes the idle bound."""
        with self._lock:
            parsed = self._parse(cookie_value)
            if parsed is None:
                return False
            session_id, signed_in = parsed
            now = self._clock()
            if now >= signed_in + self.max_seconds:
                return False
            codes = self._load()
            record = codes.get(self._record_key(session_id))
            if not record or record.get("signedInAt") != signed_in or record.get("loggedOutAt") is not None:
                return False
            last = float(record.get("lastUsedAt", 0))
            if now >= last + self.idle_seconds:
                return False
            if now - last >= min(60, max(1, self.idle_seconds // 10)):
                record["lastUsedAt"] = now
                self._save(codes)
            return True

    def logout(self, cookie_value: Optional[str]) -> bool:
        """End this session on the server: every copy of the cookie is refused from now on. Clear the
        browser's copy with expired_session_cookie_header(). False when there was no live record."""
        with self._lock:
            parsed = self._parse(cookie_value)
            if parsed is None:
                return False
            codes = self._load()
            record = codes.get(self._record_key(parsed[0]))
            if not record or record.get("signedInAt") != parsed[1] or record.get("loggedOutAt") is not None:
                return False
            record["loggedOutAt"] = self._clock()
            self._save(codes)
            return True

    def _parse(self, cookie_value: Optional[str]) -> Optional[Tuple[str, int]]:
        """The signed claim of a cookie under the current key and token, or None."""
        if not isinstance(cookie_value, str) or not cookie_value.isascii():
            return None
        parts = cookie_value.split(".")
        if len(parts) != 5 or parts[0] != "v2" or not parts[1] or not parts[2].isdigit():
            return None
        claim, mac = ".".join(parts[:4]), parts[4]
        if not hmac.compare_digest(mac, self._mac(claim)):
            return None
        if not hmac.compare_digest(parts[3], self._token_revision()):
            return None
        return parts[1], int(parts[2])

    def _mac(self, claim: str) -> str:
        return hmac.new(self._key(), claim.encode(), hashlib.sha256).hexdigest()

    def _token_revision(self) -> str:
        token = self._token() if callable(self._token) else self._token
        if not token:
            return "-"
        return hmac.new(self._key(), b"token-revision\0" + token.encode(), hashlib.sha256).hexdigest()[:16]

    @staticmethod
    def _record_key(session_id: str) -> str:
        return "s:" + hashlib.sha256(session_id.encode()).hexdigest()

    def revoke_all(self) -> None:
        if self._fixed_key is not None:
            raise ServiceError("a platform-held session key is rotated on the platform, not here.")
        atomic_write(self._key_path, secrets.token_bytes(32), 0o600)


def _session_bound(value: Any, longest: int) -> int:
    """A session bound in seconds: a finite number, never longer than the contract's (DEC-0039)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
        raise ServiceError("a session bound must be a finite number of seconds.")
    return min(int(value), longest)


class MemoryCodeStore:
    """DEC-0019: a login-code store held in memory — for an online service with no durable disk."""

    def __init__(self) -> None:
        self._codes: Dict[str, Any] = {}

    def load(self) -> Dict[str, Any]:
        return json.loads(json.dumps(self._codes))

    def save(self, codes: Dict[str, Any]) -> None:
        self._codes = json.loads(json.dumps(codes))


SESSION_COOKIE = "fabric_session"
REMOTE_SESSION_COOKIE = "__Host-fabric_session"


def session_cookie_header(value: str, max_age: int = OPERATOR_SESSION_MAX_SECONDS) -> str:
    """The cookie lives no longer than the absolute bound (DEC-0039); the server ends it sooner."""
    return "%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d" % (SESSION_COOKIE, value, max_age)


def remote_session_cookie_header(value: str, max_age: int = OPERATOR_SESSION_MAX_SECONDS) -> str:
    """DEC-0019: the remote cookie — __Host- name, Secure, no Domain, Path=/."""
    return "%s=%s; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=%d" % (REMOTE_SESSION_COOKIE, value, max_age)


def expired_session_cookie_header(remote: bool = False) -> str:
    """The header that clears the browser's session cookie, sent with a logout."""
    return (remote_session_cookie_header if remote else session_cookie_header)("", 0)


def check_remote_request(origin: str, host: Optional[str], request_origin: Optional[str] = None,
                         sec_fetch_site: Optional[str] = None, forwarded_proto: Optional[str] = None) -> Optional[str]:
    """DEC-0019: the request guard of an online service; returns the refusal sentence or None.
    ``forwarded_proto`` is the platform-set scheme where TLS ends before the process; pass None
    when the process terminates TLS itself."""
    own = urllib.parse.urlsplit(origin)
    own_host = own.netloc.lower()
    if str(host or "").lower() != own_host:
        return "Host %s is not this service." % host
    if forwarded_proto is not None and str(forwarded_proto).split(",")[0].strip() != "https":
        return "This service answers over https only."
    if request_origin is not None and request_origin != "%s://%s" % (own.scheme, own_host):
        return "Origin %s is not this service." % request_origin
    if sec_fetch_site == "cross-site":
        return "Cross-site requests are refused."
    return None


def well_known_allowed(placement: str, authorization: Optional[str], token: str, scheme: str = "Bearer") -> bool:
    """DEC-0019: a local service answers anyone (the loopback guard already ran); a remote one only
    the bearer of the service token. False is a 401 with an EMPTY body."""
    return placement != "remote" or token_matches(authorization, token, scheme)


def remote_token_file(service_id: str, instance: str = "default", directory: Optional[Path] = None) -> Path:
    return (directory or services_dir()).parent / "tokens" / ("%s.%s.token" % (service_id, instance))


def register_remote(*, service_id: str, name: str, origin: str, token: str, instance: str = "default",
                    summary: Optional[str] = None, doctor: Optional[List[str]] = None,
                    directory: Optional[Path] = None, installed_by: str = "fabric-service register-remote") -> Path:
    """DEC-0019, installer side: register an online service on THIS computer — the token file
    (0600, never printed) and the descriptor. The same token is set on the platform as a secret."""
    if not token or len(token.strip()) < 16:
        raise ServiceError("the service token must be at least 16 characters.")
    root = directory or services_dir()
    token_file = remote_token_file(service_id, instance, root)
    descriptor: Dict[str, Any] = {"protocol": PROTOCOL, "id": service_id, "instance": instance, "name": name,
                                  "placement": "remote", "origin": origin, "auth": {"tokenFile": str(token_file)},
                                  "lifecycle": {"manager": "none"}, "installedAt": now_iso(), "installedBy": installed_by}
    if summary:
        descriptor["summary"] = summary
    if doctor:
        descriptor["commands"] = {"doctor": list(doctor)}
    problems = validate_descriptor(descriptor)
    if problems:
        raise ServiceError("Descriptor is invalid: %s." % "; ".join(problems))
    ensure_private_dir(token_file.parent)
    atomic_write(token_file, token.strip().encode(), 0o600)
    return write_descriptor(descriptor, root)


def cookie_value(cookie_header: Optional[str], name: str = SESSION_COOKIE) -> Optional[str]:
    for part in (cookie_header or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return None


# --- launchd -----------------------------------------------------------------

# --- systemd and Task Scheduler (DEC-0032, service.md "Supervisor") ------------------

def _no_marker_argument(argv: Sequence[str]) -> None:
    """The supervisor file's writer writes the marker itself; one already in the arguments could only disagree with it."""
    if _marker_arguments(list(argv)):
        raise ServiceError("%s is written by the supervisor file's writer; leave it out of the program arguments" % SUPERVISOR_ARG)


def _no_secret_in_supervisor_file(argv: Sequence[str], environment: Optional[Dict[str, str]]) -> None:
    """No supervisor file carries a secret (service.md): not in an argument, an environment name or its value."""
    import fabric_secrets  # noqa: E402 - beside this file; the contract's detector (DEC-0044)
    for arg in argv:
        if fabric_secrets.secret_argument(arg):
            raise ServiceError("an argument carries a credential; a supervisor file never does (read it from the token file or a secret reference)")
    for name, value in (environment or {}).items():
        if fabric_secrets.credential_name(name) or fabric_secrets.secret_value(str(value)):
            raise ServiceError("environment %s looks like a credential; a supervisor file never carries one" % name)


def _plain(value: str, what: str) -> str:
    """A supervisor file is line- and XML-structured: no control character in anything written into it."""
    if re.search(r"[\x00-\x1f\x7f]", value):
        raise ServiceError("%s holds a control character (a line break, a tab, a NUL); a supervisor file cannot carry it" % what)
    return value


def _systemd_quote(value: str) -> str:
    _plain(value, "an argument")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    return '"%s"' % escaped


def systemd_unit(unit: str, program_arguments: Sequence[str], *, working_directory: Path,
                 environment: Optional[Dict[str, str]] = None, description: Optional[str] = None,
                 stop_timeout: int = DEFAULT_EXIT_TIMEOUT) -> str:
    """A systemd user unit (DEC-0032): Restart=always, RestartSec=10, TimeoutStopSec above the drain time,
    WantedBy=default.target. The service is told who supervises it (FABRIC_SERVICE_SUPERVISOR=systemd)."""
    if not _UNIT.match(unit):
        raise ServiceError("unit must match %s" % _UNIT.pattern)
    argv = [str(a) for a in program_arguments]
    if not argv or not argv[0].startswith("/"):
        raise ServiceError("a systemd unit starts an absolute executable")
    if stop_timeout <= DRAIN_SECONDS:
        raise ServiceError("TimeoutStopSec must outlast the %d s drain" % DRAIN_SECONDS)
    env = dict(environment or {})
    _no_secret_in_supervisor_file(argv, env)
    _no_marker_argument(argv)
    env[SUPERVISOR_ENV] = "systemd"  # the unit's writer writes the marker, whatever the caller passed
    # A unit is a Linux file: a Path built anywhere (a test on Windows, an installer's planner) names a POSIX path.
    cwd = _plain(working_directory.as_posix() if isinstance(working_directory, PurePath) else str(working_directory),
                 "the working directory")
    if not cwd.startswith("/"):
        raise ServiceError("a systemd unit's working directory is absolute")
    lines = ["[Unit]", "Description=%s" % _plain(description or unit, "the description").replace("%", "%%"), "",
             "[Service]", "Type=simple", "ExecStart=%s" % " ".join(_systemd_quote(a) for a in argv),
             # Not quoted: systemd reads WorkingDirectory= as the rest of the line, quotes included.
             "WorkingDirectory=%s" % cwd.replace("%", "%%")]
    for name in env:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            raise ServiceError("environment name %r is not a variable name" % name)
    lines += ["Environment=%s" % _systemd_quote("%s=%s" % (k, v)) for k, v in sorted(env.items())]
    lines += ["Restart=always", "RestartSec=10", "TimeoutStopSec=%d" % stop_timeout, "KillMode=mixed", "",
              "[Install]", "WantedBy=default.target", ""]
    return "\n".join(lines)


def _systemd_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"


def _check(result: Any, what: str) -> None:
    if getattr(result, "returncode", 1) != 0:
        raise ServiceError("%s failed: %s" % (what, (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()[:200]))


def systemd_install(unit: str, text: str, *, unit_dir: Optional[Path] = None, run: Callable[..., Any] = subprocess.run,
                    system: str = sys.platform, force_enable: bool = False) -> Path:
    """Write the user unit, enable it so it comes back after a login, and (re)start it so the new unit is what runs.

    The operator's intent wins (LC-14): a unit already installed and disabled stays off — the file is rewritten, so
    the new version is what starts once they enable it — unless ``force_enable`` (the operator asked for it on)."""
    if not system.startswith("linux"):
        raise ServiceError("systemd is the supervisor on Linux only")
    if not _UNIT.match(unit):
        raise ServiceError("unit must match %s" % _UNIT.pattern)
    folder = unit_dir or _systemd_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / unit
    first = not path.exists()
    state = "" if first else (getattr(run(["systemctl", "--user", "is-enabled", unit], capture_output=True, text=True),
                                      "stdout", "") or "").strip()
    atomic_write(path, text.encode("utf-8"), 0o644)
    _check(run(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True), "systemctl --user daemon-reload")
    if state == "disabled" and not force_enable:
        return path
    _check(run(["systemctl", "--user", "enable", unit], capture_output=True, text=True), "systemctl --user enable")
    _check(run(["systemctl", "--user", "restart", unit], capture_output=True, text=True), "systemctl --user restart")
    return path


def systemd_uninstall(unit: str, *, unit_dir: Optional[Path] = None, run: Callable[..., Any] = subprocess.run,
                      system: str = sys.platform) -> None:
    """Stop it and keep it off across logins (`disable --now`), then remove the unit."""
    if not system.startswith("linux"):
        raise ServiceError("systemd is the supervisor on Linux only")
    run(["systemctl", "--user", "disable", "--now", unit], capture_output=True, text=True)
    path = (unit_dir or _systemd_dir()) / unit
    if path.exists():
        path.unlink()
    _check(run(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True), "systemctl --user daemon-reload")


def _xml(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def task_xml(task: str, program_arguments: Sequence[str], *, working_directory: str, description: Optional[str] = None,
             user: Optional[str] = None) -> str:
    """A per-user Scheduled Task (DEC-0032): a logon trigger, restart on failure every minute, no execution time limit,
    run only when the user is logged on, created without administrator rights."""
    if not _TASK.match(task):
        raise ServiceError("task must match %s" % _TASK.pattern)
    argv = [str(a) for a in program_arguments]
    if not argv or not re.match(r"^[A-Za-z]:[\\/]", argv[0]):
        raise ServiceError("a task starts a drive-absolute executable (C:\\…)")
    for value, what in [(a, "an argument") for a in argv] + [(str(working_directory), "the working directory"),
                                                           (description or task, "the description")]:
        _plain(value, what)
    _no_secret_in_supervisor_file(argv, None)
    _no_marker_argument(argv)
    # A task's Exec action carries no environment, so the marker is an argument (DEC-0057), before any `--`.
    cut = argv.index("--") if "--" in argv else len(argv)
    argv = argv[:cut] + [SUPERVISOR_ARG, "task-scheduler"] + argv[cut:]
    who = user or ("%s\\%s" % (os.environ.get("USERDOMAIN", ""), os.environ["USERNAME"]) if os.environ.get("USERNAME") else "")
    if not who:
        raise ServiceError("name the user the task runs as (DOMAIN\\user); USERNAME is not set")
    _plain(who, "the user")
    body = """<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>{desc}</Description><URI>{task}</URI></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{user}</UserId></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{user}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>true</Enabled>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author"><Exec><Command>{command}</Command><Arguments>{arguments}</Arguments><WorkingDirectory>{cwd}</WorkingDirectory></Exec></Actions>
</Task>
""".format(desc=_xml(description or task), task=_xml(task), user=_xml(who), command=_xml(argv[0]),
           arguments=_xml(subprocess.list2cmdline(argv[1:])), cwd=_xml(str(working_directory)))
    return '<?xml version="1.0" encoding="UTF-16"?>\n' + body


_TASK_DISABLED = re.compile(r"<Settings>(?:(?!</Settings>).)*<Enabled>false</Enabled>", re.S)


def task_install(task: str, xml_text: str, *, run: Callable[..., Any] = subprocess.run, system: str = sys.platform,
                 force_enable: bool = False) -> None:
    """Create (or replace) the task from its XML without administrator rights, then (re)start it so the new
    definition is what runs. A task already installed and disabled stays off (LC-14) unless ``force_enable``."""
    if system != "win32":
        raise ServiceError("Task Scheduler is the supervisor on Windows only")
    query = run(["schtasks", "/Query", "/TN", task, "/XML"], capture_output=True, text=True)
    existed = getattr(query, "returncode", 1) == 0
    keep_off = existed and not force_enable and bool(_TASK_DISABLED.search(getattr(query, "stdout", "") or ""))
    fd, name = tempfile.mkstemp(suffix=".xml")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(xml_text.encode("utf-16"))
        _check(run(["schtasks", "/Create", "/TN", task, "/XML", name, "/F"], capture_output=True, text=True), "schtasks /Create")
    finally:
        os.unlink(name)
    if keep_off:
        _check(run(["schtasks", "/Change", "/TN", task, "/DISABLE"], capture_output=True, text=True), "schtasks /Change /DISABLE")
        return
    if existed:
        run(["schtasks", "/End", "/TN", task], capture_output=True, text=True)
    _check(run(["schtasks", "/Run", "/TN", task], capture_output=True, text=True), "schtasks /Run")


def task_uninstall(task: str, *, run: Callable[..., Any] = subprocess.run, system: str = sys.platform) -> None:
    """End the running task, then delete it."""
    if system != "win32":
        raise ServiceError("Task Scheduler is the supervisor on Windows only")
    run(["schtasks", "/End", "/TN", task], capture_output=True, text=True)
    _check(run(["schtasks", "/Delete", "/TN", task, "/F"], capture_output=True, text=True), "schtasks /Delete")


def launchd_plist(label: str, program_arguments: Sequence[str], *, working_directory: Path,
                  stdout_path: Path, environment: Optional[Dict[str, str]] = None,
                  exit_timeout: int = DEFAULT_EXIT_TIMEOUT) -> bytes:
    """RunAtLoad + KeepAlive true + ThrottleInterval 10; no secret may appear in `environment`.

    ``ExitTimeOut`` (15 s) sits above the drain and its hard exit (``Drain``: 8 + 2 s), so launchd's
    SIGKILL never arrives first. ``FABRIC_SERVICE_SUPERVISOR=launchd`` tells the lock to back off
    instead of exiting into a respawn loop."""
    env = dict(environment or {})
    for key in env:
        if re.search(r"(TOKEN|SECRET|PASSWORD|KEY)$", key) and not key.endswith("_FILE"):
            raise ServiceError("Environment variable %s looks like a secret; pass a *_FILE path instead." % key)
    env.setdefault("PATH", "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin")
    _no_marker_argument([str(a) for a in program_arguments])
    env[SUPERVISOR_ENV] = "launchd"
    plist = {
        "Label": label,
        "ProgramArguments": list(program_arguments),
        "WorkingDirectory": str(working_directory),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "ExitTimeOut": exit_timeout,
        # Standard, never Background: a host probes the service and agents call it while the Mac
        # is busy; Background (and Nice/LowPriorityIO) lets macOS starve it for tens of seconds
        # under load, and every host then reports an outage that never happened.
        "ProcessType": "Standard",
        "StandardOutPath": str(stdout_path),
        "StandardErrorPath": str(stdout_path),
        "EnvironmentVariables": env,
    }
    return plistlib.dumps(plist)


def _launchctl(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=timeout)


def _domain() -> str:
    if sys.platform == "win32":
        # DEC-0032: launchd is macOS's supervisor; Windows has Task Scheduler, and no uid.
        raise ServiceError("launchd exists only on macOS; this system's supervisor is Task Scheduler.")
    return "gui/%d" % os.getuid()


def launchd_loaded(label: str) -> bool:
    return _launchctl("print", "%s/%s" % (_domain(), label)).returncode == 0


def fetch_well_known(origin: str, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
    try:
        with urllib.request.urlopen(origin + "/.well-known/fabric-service", timeout=timeout) as response:
            return json.loads(response.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return None


_OVERRIDE_ROW = re.compile(r'^\s*"([^"]+)"\s*=>\s*(\S+)\s*$')


def launchd_override(label: str) -> Optional[str]:
    """The operator's launchd override for ``label``: ``"disabled"``, ``"enabled"``, None when
    none is recorded (a first install), or ``"unknown"`` when the table cannot be read.

    Reads ``launchctl print-disabled gui/<uid>``; macOS 14+ prints ``=> disabled|enabled``,
    older releases ``=> true|false`` (true means disabled)."""
    result = _launchctl("print-disabled", _domain())
    if result.returncode != 0:
        return "unknown"
    for line in result.stdout.splitlines():
        match = _OVERRIDE_ROW.match(line)
        if match and match.group(1) == label:
            return "disabled" if match.group(2) in ("disabled", "true") else "enabled"
    return None


def launchd_install(label: str, plist_path: Path, plist_bytes: bytes, *, origin: str,
                    service_id: str, instance: str = "default", timeout: float = 40.0,
                    force_enable: bool = False) -> Dict[str, Any]:
    """Write + lint the plist, bootout and WAIT for unload, bootstrap (retry EIO 5), then
    poll the well-known document until it answers with this identity.

    The operator's intent wins (LC-14): only a first install (no override recorded) enables the
    label. A label the operator disabled stays disabled and unloaded — the plist is still
    rewritten, so the new release is what starts once they turn it back on — and the answer is
    ``{"disabled": True, "label", "plist", "loaded"}`` instead of the well-known document.
    ``force_enable`` is for an operator who asked for the service to be switched on."""
    plist_path = Path(plist_path)
    atomic_write(plist_path, plist_bytes, 0o644)
    lint = subprocess.run(["plutil", "-lint", str(plist_path)], capture_output=True, text=True)
    if lint.returncode != 0:
        raise ServiceError("plist failed plutil -lint: %s" % lint.stdout.strip())
    target = "%s/%s" % (_domain(), label)
    override = launchd_override(label)
    if force_enable or override is None:
        _launchctl("enable", target)
    elif override == "disabled":
        return {"disabled": True, "label": label, "plist": str(plist_path), "loaded": launchd_loaded(label)}
    _launchctl("bootout", target)
    deadline = time.time() + 15
    while launchd_loaded(label) and time.time() < deadline:
        time.sleep(0.25)
    last = ""
    for _ in range(5):
        result = _launchctl("bootstrap", _domain(), str(plist_path))
        if result.returncode == 0:
            break
        last = (result.stderr or result.stdout).strip()
        time.sleep(1.0)
    else:
        raise ServiceError("launchctl bootstrap failed: %s" % last)
    deadline = time.time() + timeout
    while time.time() < deadline:
        doc = fetch_well_known(origin)
        if doc and doc.get("service", {}).get("id") == service_id and doc.get("service", {}).get("instance") == instance:
            return doc
        time.sleep(0.5)
    raise ServiceError("%s did not answer as %s.%s within %.0f s; read its log." % (origin, service_id, instance, timeout))


def launchd_uninstall(label: str, plist_path: Path, *, timeout: float = 30.0, purge: bool = False,
                      service_id: Optional[str] = None) -> Dict[str, Any]:
    """Symmetric with ``launchd_install`` (LC-14): bootout and WAIT until the job is gone, remove
    the plist, and reset the override to ``enabled`` — launchctl has no verb that deletes an
    override, and a leftover ``disabled`` would make a later fresh install stay off. Data stays
    unless ``purge`` (then ``service_id`` names whose data, logs and cache go). A job still
    loaded at ``timeout`` raises, leaving the plist and data in place."""
    if purge and not service_id:
        raise ServiceError("purge needs the service id whose data, logs and cache to remove.")
    target = "%s/%s" % (_domain(), label)
    _launchctl("bootout", target)
    deadline = time.monotonic() + timeout
    while launchd_loaded(label):
        if time.monotonic() >= deadline:
            raise ServiceError("launchd job %s is still loaded %.0f s after bootout; nothing was removed." % (label, timeout))
        time.sleep(0.1)
    try:
        Path(plist_path).unlink()
        plist_removed = True
    except FileNotFoundError:
        plist_removed = False
    _launchctl("enable", target)
    purged: List[str] = []
    if purge:
        for directory in service_dirs(str(service_id)).values():
            if directory.is_symlink():
                directory.unlink()
            elif directory.exists():
                shutil.rmtree(directory)
            else:
                continue
            purged.append(str(directory))
    return {"unloaded": True, "plistRemoved": plist_removed, "override": "enabled", "purged": purged}


def prune_releases(releases_dir: Path, keep: int = 2, *, current: Optional[Path] = None) -> List[Path]:
    """Keep the release the job runs and the one before it (LC-11 rollback, LC-15); remove
    older release directories, newest first by modification time. ``current`` (a release or a
    symlink to one) is never removed, even after a rollback to an older release. Symlinks and
    files in ``releases_dir`` are left alone. Returns what was removed."""
    if keep < 2:
        raise ServiceError("keep at least the current release and the one before it (keep >= 2).")
    root = Path(releases_dir)
    if not root.is_dir():
        return []
    releases = [p for p in root.iterdir() if p.is_dir() and not p.is_symlink()]
    releases.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    keepers: List[Path] = []
    if current is not None:
        resolved = Path(current).resolve()
        keepers.extend(p for p in releases if p.resolve() == resolved)
    for release in releases:
        if len(keepers) >= keep:
            break
        if release not in keepers:
            keepers.append(release)
    removed = [p for p in releases if p not in keepers]
    for release in removed:
        shutil.rmtree(release)
    return removed


# --- helpers for input validation -----------------------------------------------

def _require_id(service_id: str) -> None:
    if not (isinstance(service_id, str) and _ID.fullmatch(service_id)):
        raise ServiceError("Service id %r must match %s." % (service_id, _ID.pattern))


__all__ = [name for name in dir() if not name.startswith("_")]
