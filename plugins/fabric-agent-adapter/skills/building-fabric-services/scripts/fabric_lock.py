"""One copy of a service, locked before any side effect (LC-01, DEC-0057): the instance lock, the supervisor marker
in both its forms, and the wait budget under a supervisor. Part of the service kit (FAA-65, layer L3)."""
from __future__ import annotations

import errno
import hashlib
import ntpath
import os
import posixpath
import re
import socket
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from fabric_base import (
    SUPERVISOR_ENV,
    ServiceError,
    WINDOWS,
    _O_BINARY,
)
from fabric_platform import (
    _close_handle,
    _create_first_pipe,
    _pipe_exists,
)
from fabric_paths import (
    ensure_private_dir,
)


EXIT_ALREADY_RUNNING = 75


LOCK_WAIT_SUPERVISED_SECONDS = 300.0


LOCK_BACKOFF_FIRST_SECONDS = 0.5


LOCK_BACKOFF_MAX_SECONDS = 30.0


class AlreadyRunning(ServiceError):
    def __init__(self, holder_pid: Optional[int], lock_path: Path):
        self.holder_pid = holder_pid
        self.lock_path = lock_path
        # FAC-SEM-078: a copy that cannot learn the holder's pid says the holder is unknown.
        who = "process %d" % holder_pid if holder_pid else "an unknown process"
        super().__init__("Another copy is already running (%s holds %s)." % (who, lock_path))


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
