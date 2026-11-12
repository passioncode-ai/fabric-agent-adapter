"""Supervisors (DEC-0032, LC-14): launchd plists, systemd user units and Task Scheduler tasks, installed and
removed without touching what the operator turned off; release pruning (LC-15). Part of the service kit
(FAA-65, layer L3)."""
from __future__ import annotations

import http.client
import ipaddress
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePath
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
import fabric_peer_owner as _po  # noqa: E402 - the listener's owner (DEC-0154 HA-2)
from fabric_base import (
    DRAIN_SECONDS,
    SUPERVISOR_ENV,
    ServiceError,
    _TASK,
    _UNIT,
)
from fabric_paths import (
    atomic_write,
    instance_dirs,
)
from fabric_lock import (
    SUPERVISOR_ARG,
    _marker_arguments,
)


DEFAULT_EXIT_TIMEOUT = 15


_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,250}\Z")  # what launchd and the Node twin take as a label
_USER_NAME = re.compile(r"^[a-z_][a-z0-9_.-]{0,31}\Z")  # a macOS short name, as a LaunchDaemon's UserName takes it
#: The short-name rule in words, printed alike by both twins (FAA-286 item 13).
USER_NAME_RULE = "a lower-case letter or _, then up to 31 lower-case letters, digits, _, . or -"

#: Where a LaunchDaemon's plist lives: a job in launchd's system domain, started at boot with no GUI login (FAA-278).
SYSTEM_DAEMONS = Path("/Library/LaunchDaemons")


def _no_marker_argument(argv: Sequence[str]) -> None:
    """The supervisor file's writer writes the marker itself; one already in the arguments could only disagree with it."""
    if _marker_arguments(list(argv)):
        raise ServiceError("%s is written by the supervisor file's writer; leave it out of the program arguments" % SUPERVISOR_ARG)


_PATH_ANCHOR = re.compile(r"^(?:[/~.]|[A-Za-z]:[\\/])")
_PATH_WORD = re.compile(r"[a-z][a-z0-9_-]{2,}")


def _secret_env_value(value: str) -> bool:
    """An environment value: read path-aware (`secret_argument`) only when it reads as a path (it starts as one, has at
    least two separators and a lower-case word between them), so a release folder under Application Support is no key
    (FAA-266) while a base64 key whose `/` splits it stays one; any other value keeps the strict `secret_value`."""
    import fabric_secrets  # noqa: E402 - beside this file; the contract's detector (DEC-0044)
    pieces = re.split(r"[\\/]", value)
    path = bool(_PATH_ANCHOR.match(value)) and len(pieces) >= 3 and any(_PATH_WORD.fullmatch(x) for x in pieces)
    return fabric_secrets.secret_argument(value) if path else fabric_secrets.secret_value(value)


def _no_secret_in_supervisor_file(argv: Sequence[str], environment: Optional[Dict[str, str]]) -> None:
    """No supervisor file carries a secret (service.md): not in an argument, an environment name or its value."""
    import fabric_secrets  # noqa: E402 - beside this file; the contract's detector (DEC-0044)
    for arg in argv:
        if fabric_secrets.secret_argument(arg):
            raise ServiceError("an argument carries a credential; a supervisor file never does (read it from the token file or a secret reference)")
    for name, value in (environment or {}).items():
        if fabric_secrets.credential_name(name) or _secret_env_value(str(value)):
            raise ServiceError("environment %s looks like a credential; a supervisor file never carries one" % name)


def _plain(value: str, what: str) -> str:
    """A supervisor file is line- and XML-structured: no control character in anything written into it."""
    if re.search(r"[\x00-\x1f\x7f]", value):
        raise ServiceError("%s holds a control character (a line break, a tab, a NUL); a supervisor file cannot carry it" % what)
    return value


def _systemd_quote(value: str, dollar: bool = True) -> str:
    """A quoted systemd value. ExecStart= expands $VAR, so its $ is doubled; Environment= expands none, so `dollar`
    False leaves it alone (finding 17). Both expand % specifiers."""
    _plain(value, "an argument")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return '"%s"' % (escaped.replace("$", "$$") if dollar else escaped)


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
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*\Z", name):
            raise ServiceError("environment name %r is not a variable name" % name)
    lines += ["Environment=%s" % _systemd_quote("%s=%s" % (k, v), dollar=False) for k, v in sorted(env.items())]
    lines += ["Restart=always", "RestartSec=10", "TimeoutStopSec=%d" % stop_timeout, "KillMode=mixed", "",
              "[Install]", "WantedBy=default.target", ""]
    return "\n".join(lines)


def _systemd_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"


def _check(result: Any, what: str) -> None:
    if getattr(result, "returncode", 1) != 0:
        raise ServiceError("%s failed: %s" % (what, (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()[:200]))


def _poll_installed(origin: str, service_id: Optional[str], instance: str, timeout: float,
                    read: Optional[Callable[[str], Any]], sleep: Callable[[float], None], clock: Callable[[], float]) -> Any:
    """Poll the well-known answer at `origin` until this OS account's listener answers as `service_id`.`instance`, as
    launchd_install does (the pinned contract's Install row: every supervisor polls, FAA-253). Another account's listener,
    or one whose owner cannot be told, is never a successful install (DEC-0154 HA-2)."""
    if not service_id:
        raise ServiceError("polling the install at %s needs the service_id it must answer as" % origin)
    read = read or well_known_of
    deadline = clock() + max(0.0, timeout)
    while True:
        doc = read(origin)
        foreign = doc.reason if isinstance(doc, ForeignUserAnswer) else None
        if not foreign and _answers(doc, service_id, instance):
            return doc
        if clock() >= deadline:
            break
        sleep(0.5)
    if foreign:
        raise ServiceError("%s is not this service's: %s (DEC-0154 HA-2); the port is another OS account's or its owner "
                           "cannot be told." % (origin, foreign))
    raise ServiceError("%s did not answer as %s.%s within %.0f s; read its log." % (origin, service_id, instance, timeout))


def systemd_install(unit: str, text: str, *, unit_dir: Optional[Path] = None, run: Callable[..., Any] = subprocess.run,
                    system: str = sys.platform, force_enable: bool = False, origin: Optional[str] = None,
                    service_id: Optional[str] = None, instance: str = "default", timeout: float = 40.0,
                    fetch_well_known: Optional[Callable[[str], Any]] = None, sleep: Callable[[float], None] = time.sleep,
                    clock: Callable[[], float] = time.monotonic) -> Path:
    """Write the user unit, enable it so it comes back after a login, and (re)start it so the new unit is what runs.

    The operator's intent wins (LC-14): a unit already installed and disabled stays off — the file is rewritten, so
    the new version is what starts once they enable it — unless ``force_enable`` (the operator asked for it on).
    With ``origin`` (and ``service_id``), it then polls the well-known answer as ``launchd_install`` does, until this
    account's listener answers within ``timeout`` (FAA-253); ``fetch_well_known(origin)`` reads it as ``well_known_of``."""
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
    if origin is not None:
        _poll_installed(origin, service_id, instance, timeout, fetch_well_known, sleep, clock)
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
                 force_enable: bool = False, origin: Optional[str] = None, service_id: Optional[str] = None,
                 instance: str = "default", timeout: float = 40.0, fetch_well_known: Optional[Callable[[str], Any]] = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> Any:
    """Create (or replace) the task from its XML without administrator rights, then (re)start it so the new
    definition is what runs. A task already installed and disabled stays off (LC-14) unless ``force_enable``.
    With ``origin`` (and ``service_id``), it then polls the well-known answer as ``launchd_install`` does and returns it
    (FAA-253); without, it returns None as before."""
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
    if origin is not None:
        return _poll_installed(origin, service_id, instance, timeout, fetch_well_known, sleep, clock)
    return None


def task_uninstall(task: str, *, run: Callable[..., Any] = subprocess.run, system: str = sys.platform) -> None:
    """End the running task, then delete it."""
    if system != "win32":
        raise ServiceError("Task Scheduler is the supervisor on Windows only")
    run(["schtasks", "/End", "/TN", task], capture_output=True, text=True)
    _check(run(["schtasks", "/Delete", "/TN", task, "/F"], capture_output=True, text=True), "schtasks /Delete")


def launchd_plist(label: str, program_arguments: Sequence[str], *, working_directory: Path,
                  stdout_path: Path, environment: Optional[Dict[str, str]] = None,
                  exit_timeout: int = DEFAULT_EXIT_TIMEOUT, user_name: Optional[str] = None) -> bytes:
    """RunAtLoad + KeepAlive true + ThrottleInterval 10; no secret may appear in `environment`.

    ``ExitTimeOut`` (15 s) sits above the drain and its hard exit (``Drain``: 8 + 2 s), so launchd's
    SIGKILL never arrives first. ``FABRIC_SERVICE_SUPERVISOR=launchd`` tells the lock to back off
    instead of exiting into a respawn loop.

    The same refusals as the Node twin (finding 10): a label launchd cannot name, no program, an ExitTimeOut that does
    not outlast the drain, an environment name ending TOKEN/SECRET/PASSWORD/KEY (a `*_FILE` path is fine), a value or
    an argument shaped like a credential, and a control character in any string the plist carries.

    ``user_name`` writes ``UserName``, the account a LaunchDaemon (system domain, FAA-278) runs as; it must be a macOS
    short name, and it is meaningful only for a plist installed in ``/Library/LaunchDaemons``."""
    import fabric_secrets  # noqa: E402 - beside this file; the contract's detector (DEC-0044)
    if not _LABEL.match(str(label)):
        raise ServiceError("label must match %s" % _LABEL.pattern)
    argv = [str(a) for a in program_arguments]
    if not argv:
        raise ServiceError("A launchd job starts a program; ProgramArguments is empty.")
    if not exit_timeout > DRAIN_SECONDS:
        raise ServiceError("ExitTimeOut must outlast the %d s drain." % DRAIN_SECONDS)
    if user_name is not None and not _USER_NAME.match(str(user_name)):
        raise ServiceError("UserName must be a macOS short name matching %s" % _USER_NAME.pattern)
    env = dict(environment or {})
    for key, value in env.items():
        if re.search(r"(TOKEN|SECRET|PASSWORD|KEY)\Z", key) and not key.endswith("_FILE"):
            raise ServiceError("Environment variable %s looks like a secret; pass a *_FILE path instead." % key)
        if _secret_env_value(str(value)):  # path-aware only for a path: a release folder is no key (FAA-266)
            raise ServiceError("Environment %s holds a value shaped like a credential; a plist never carries one." % key)
    for arg in argv:
        if fabric_secrets.secret_argument(arg):
            raise ServiceError("An argument carries a credential; a plist never does (read it from the token file or a secret reference).")
    for value in [str(label), str(working_directory), str(stdout_path)] + argv + [str(x) for pair in env.items() for x in pair]:
        _plain(value, "a plist string")
    env.setdefault("PATH", "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin")
    _no_marker_argument(argv)
    env[SUPERVISOR_ENV] = "launchd"
    plist = {
        "Label": label,
        "ProgramArguments": argv,
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
    if user_name is not None:
        plist["UserName"] = str(user_name)
    return plistlib.dumps(plist)


def _launchctl(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=timeout)


def _domain() -> str:
    if sys.platform == "win32":
        # DEC-0032: launchd is macOS's supervisor; Windows has Task Scheduler, and no uid.
        raise ServiceError("launchd exists only on macOS; this system's supervisor is Task Scheduler.")
    return "gui/%d" % os.getuid()


def launchd_domain(plist_path: Optional[Path] = None, domain: Optional[str] = None) -> str:
    """The launchd domain a job lives in: ``system`` for a LaunchDaemon (``domain="system"``, or a plist in
    ``/Library/LaunchDaemons``), else this user's ``gui/<uid>`` (FAA-278). A LaunchDaemon starts at boot, before any
    login, so it is the form for a headless Mac that a FileVault restart (``fdesetup authrestart``) leaves with no GUI
    session; a ``gui/<uid>`` job starts only while its user is logged in."""
    if domain not in (None, "gui", "system"):
        raise ServiceError("domain must be gui or system")
    if plist_path is not None and re.match(r"^(?:system|gui)(?:/[0-9]*)?\Z", str(plist_path)):
        raise ServiceError("%s is a launchd domain, not a plist path: pass domain=%r (FAA-286)"
                           % (plist_path, "system" if str(plist_path) == "system" else "gui"))
    if domain is None and plist_path is not None:
        folder = re.sub(r"^/{2,}", "/", str(Path(os.path.abspath(str(plist_path))).parent))  # POSIX keeps a leading //
        domain = "system" if folder.lower() == str(SYSTEM_DAEMONS).lower() else "gui"  # APFS ignores case
    if domain == "system":
        if sys.platform != "darwin":
            raise ServiceError("launchd is the supervisor on macOS only; use systemd_install on Linux and task_install on "
                               "Windows.")
        return "system"
    return _domain()


def _in_daemons(plist_path: Path) -> bool:
    folder = re.sub(r"^/{2,}", "/", str(Path(os.path.abspath(str(plist_path))).parent))
    return folder.lower() == str(SYSTEM_DAEMONS).lower()


def _pair_problem(plist_path: Path, domain: Optional[str]) -> Optional[str]:
    """A domain the plist's folder contradicts (FAA-286 items 14 and 21): a system job in a LaunchAgents folder (launchd
    also loads it into gui/<uid> at login), or a gui job in /Library/LaunchDaemons (launchd loads it at boot as root).
    Another folder is allowed for a system job, as the tests' and a staging install's are."""
    if domain == "system" and Path(os.path.abspath(str(plist_path))).parent.name.lower() == "launchagents":
        return ("A LaunchDaemon's plist lives in %s: %s is in a LaunchAgents folder, which launchd also loads into "
                "gui/<uid> at login, so the job would run twice." % (SYSTEM_DAEMONS, plist_path))
    if domain == "gui" and _in_daemons(plist_path):
        return ("%s is in %s, which launchd loads at boot as a LaunchDaemon: a gui/<uid> job's plist goes in "
                "~/Library/LaunchAgents." % (plist_path, SYSTEM_DAEMONS))
    return None


def _leftover_agent(label: str, user_name: str) -> Optional[Path]:
    """A LaunchAgent of ``label`` in ``user_name``'s ~/Library/LaunchAgents, which would run a second copy at its login
    (FAA-286 item 6)."""
    try:
        import pwd
        home = Path(pwd.getpwnam(user_name).pw_dir)
    except (ImportError, KeyError, ValueError):
        return None
    try:
        agents = sorted((home / "Library" / "LaunchAgents").glob("*.plist"))
    except OSError:
        return None
    return next((p for p in agents if _plist_field(p, "Label") == label), None)


def _need_root(domain: str, label: str, plist_path: Path, install: bool) -> None:
    """A system-domain job is installed and removed by root: refuse before anything is written (FAA-278)."""
    if domain != "system" or os.geteuid() == 0:
        return
    if install:
        raise ServiceError("A LaunchDaemon (launchd's system domain) is installed by root, and this process is not "
                           "root: run launchd_install as root (the release, descriptor and token stay its UserName's, "
                           "lifecycle reference, The system domain), or as root write %s and run "
                           "`launchctl bootstrap system %s`. Status and pid read without root." % (plist_path, plist_path))
    raise ServiceError("A LaunchDaemon (launchd's system domain) is removed by root, and this process is not root: run "
                       "launchd_uninstall as root, or as root run `launchctl bootout system/%s`, remove %s and run "
                       "`launchctl enable system/%s` (so a later install is not kept off). Status and pid read without "
                       "root." % (label, plist_path, label))


def launchd_loaded(label: str, domain: Optional[str] = None) -> bool:
    """Whether launchd has the job ``label`` loaded in this user's ``gui/<uid>`` domain, or with ``domain="system"`` in
    the system domain (FAA-278); reading needs no root."""
    return _launchctl("print", "%s/%s" % (launchd_domain(domain=domain), label)).returncode == 0


_PID_ROW = re.compile(r"^\s*pid\s*=\s*([0-9]+)\s*\Z")  # ASCII digits, as Node reads them (FAA-273)


def launchd_pid(label: str, domain: Optional[str] = None) -> Optional[int]:
    """The running pid of this account's launchd job ``label`` (with ``domain="system"``, of the LaunchDaemon), or
    None (not running, or not readable). Reading needs no root."""
    try:
        result = _launchctl("print", "%s/%s" % (launchd_domain(domain=domain), label))
    except subprocess.TimeoutExpired:
        return None  # a launchctl that hangs is a pid not read, never an error out of an install's poll (FAA-273)
    if result.returncode != 0:
        return None
    for line in (result.stdout or "").splitlines():
        hit = _PID_ROW.match(line)
        if hit:
            return int(hit.group(1))
    return None


def _loopback_host(host: Optional[str]) -> bool:
    """Whether `host` (urlsplit's hostname: lower-case, no brackets) names this machine: localhost, 127/8 or ::1."""
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class ForeignUserAnswer:
    """A refused listener (DEC-0154 HA-2), as `well_known_of` answers it: never a document, whatever keys a service's JSON
    carries. `reason` starts with `foreign-user` or `table-restricted` (the Node twin's class, FAA-259)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def __repr__(self) -> str:
        return "ForeignUserAnswer(%r)" % self.reason


def _read_well_known(origin: str, timeout: float = 2.0,
                     vouch_pid: Optional[int] = None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(the well-known answer or None, why the listener was refused or None). A loopback origin is read only on a
    connection whose server end is this OS account's process (DEC-0154 HA-2): another account's, root's, or one whose
    owner cannot be told is never this service's answer, labelled `foreign-user`, or `table-restricted` when the socket
    table hides other processes. `vouch_pid`, the pid of a launchd job this
    caller started, proves the listener when the socket table hides other processes (FAA-267)."""
    parts = urllib.parse.urlsplit(origin)
    try:
        port = parts.port or (80 if parts.scheme == "http" else None)  # no port is http's 80, as in the Node twin
    except ValueError:  # a port out of range
        port = None
    if parts.scheme == "http" and port and _loopback_host(parts.hostname):
        # every loopback spelling (127.0.0.1, another 127/8 address, localhost, [::1]) goes on a checked connection,
        # never the unchecked way (FAA-257)
        conn = _po.CheckedHTTPConnection(parts.hostname, port, timeout=timeout, vouch_pid=vouch_pid)
        try:
            conn.request("GET", "/.well-known/fabric-service", headers={"Host": parts.netloc.rpartition("@")[2]})
            response = conn.getresponse()
            return (json.loads(response.read().decode()) if response.status == 200 else None), None
        except _po.ListenerRefused as exc:
            restricted = exc.owner is not None and (exc.owner.reason or "").startswith(_po.TABLE_RESTRICTED)
            return None, "%s: %s" % (_po.TABLE_RESTRICTED if restricted else "foreign-user", exc)
        except (OSError, ValueError, http.client.HTTPException):
            return None, None
        finally:
            conn.close()
    try:
        with urllib.request.urlopen(origin + "/.well-known/fabric-service", timeout=timeout) as response:
            return json.loads(response.read().decode()), None
    except (urllib.error.URLError, OSError, ValueError):
        return None, None


def _job_listens(pid: int, port: int) -> bool:
    """Whether launchd's job `pid` listens on 127.0.0.1:<port> exactly (never the wildcard), asked of the process itself
    (`lsof -p`), which a restricted socket table does not hide. Used only for a LaunchDaemon root just bootstrapped,
    whose pid launchd itself named (FAA-278)."""
    if sys.platform != "darwin" or not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        return False
    try:
        out = _po._run([_po.LSOF, "-nP", "-a", "-p", str(pid), "-i4TCP", "-sTCP:LISTEN", "-Fn"])
    except _po.TableUnreadable:
        return False
    return any(host == "127.0.0.1" and p == port for host, p in _po.parse_lsof_listeners(out))  # exact bind, as RT-3


def _account_uid(user_name: str) -> Optional[int]:
    """The uid of account ``user_name`` on this machine, or None when it has no such account. Only a short name: macOS
    getpwnam also answers an upper-case name or the full name, which launchd's UserName does not take."""
    if not isinstance(user_name, str) or not _USER_NAME.match(user_name):
        return None
    try:
        import pwd
        return pwd.getpwnam(user_name).pw_uid
    except (ImportError, KeyError, ValueError):
        return None


def _pid_uid(pid: int) -> Optional[int]:
    """The uid process ``pid`` runs as (``ps -o uid= -p``), or None when it is gone or cannot be read."""
    try:
        return _po.parse_ps_uid(_po._run([_po.PS, "-o", "uid=", "-p", str(pid)]))
    except _po.TableUnreadable:
        return None


def _positive(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


class _JobConnection(http.client.HTTPConnection):
    """A connection whose server end must be launchd's job `job_pid`, running as `job_uid`, its UserName's uid (a
    LaunchDaemon runs as its UserName, so the installer, root, reads it as another account's: the job's own pid and
    uid are the proof, FAA-278; contract DEC-0161, proposed: RT-3 extended to launchd's system domain)."""

    def __init__(self, host: str, port: int, job_pid: int, timeout: float, job_uid: Optional[int] = None) -> None:
        if not isinstance(job_pid, int) or isinstance(job_pid, bool) or job_pid <= 1:
            raise ServiceError("A LaunchDaemon's answer is read only on its job's pid, a positive number.")
        if not _positive(job_uid):
            raise ServiceError("A LaunchDaemon's answer is read only from its UserName's uid, a number.")
        super().__init__(host, port, timeout=timeout)
        self.job_pid = job_pid
        self.job_uid = job_uid

    def connect(self) -> None:
        super().connect()
        owner = _po.server_end(self.sock)
        restricted = owner.kind == _po.UNKNOWN and (owner.reason or "").startswith(_po.TABLE_RESTRICTED)
        if owner.pid == self.job_pid and not _job_listens(self.job_pid, self.port):
            self.close()
            # The job's pid, but lsof did not show it bound to exactly 127.0.0.1:<port>: a wildcard is never vouched for.
            raise _po.ListenerRefused(_po.SERVER_NOT_OWN, "the LaunchDaemon's pid %d is not shown listening on exactly "
                                      "127.0.0.1:%d by lsof (a wildcard is never vouched for); nothing was sent"
                                      % (self.job_pid, self.port))
        if owner.pid == self.job_pid or (restricted and _job_listens(self.job_pid, self.port)):
            runs_as = _pid_uid(self.job_pid)
            if runs_as == self.job_uid:
                return
            self.close()
            # Not the restricted owner: the pid was proved, only its uid is wrong, and the error says so.
            raise _po.ListenerRefused(_po.SERVER_NOT_OWN, "the LaunchDaemon's pid %d runs as uid %s, not its UserName's "
                                      "uid %d; nothing was sent" % (self.job_pid, runs_as, self.job_uid))
        self.close()
        raise _po.ListenerRefused(_po.SERVER_NOT_OWN, "the server on port %d is not the LaunchDaemon's pid %d (%s): "
                                  "another process holds the port, or the job's program starts the server as a child "
                                  "(start it with exec); nothing was sent"
                                  % (self.port, self.job_pid, owner.reason or owner.kind), owner)


def _read_job_well_known(origin: str, job_pid: int, job_uid: Optional[int] = None,
                         timeout: float = 2.0) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """As `_read_well_known`, for a LaunchDaemon: a loopback origin is read only when launchd's job `job_pid`, running as
    `job_uid`, accepted the connection; (the answer or None, why the listener was refused or None)."""
    try:
        port = urllib.parse.urlsplit(origin).port
    except ValueError:  # a port out of range
        port = None
    if not (port and 1 <= port <= 65535 and origin == "http://127.0.0.1:%d" % port):
        raise ServiceError("A LaunchDaemon's answer is read only at http://127.0.0.1:<port>, where its job's pid and uid "
                           "prove it; %s is not." % origin)
    conn = _JobConnection("127.0.0.1", port, job_pid, timeout, job_uid)
    try:
        conn.request("GET", "/.well-known/fabric-service", headers={"Host": "127.0.0.1:%d" % port})
        response = conn.getresponse()
        return (json.loads(response.read().decode()) if response.status == 200 else None), None
    except _po.ListenerRefused as exc:
        restricted = exc.owner is not None and (exc.owner.reason or "").startswith(_po.TABLE_RESTRICTED)
        return None, "%s: %s" % (_po.TABLE_RESTRICTED if restricted else "foreign-user", exc)
    except (OSError, ValueError, http.client.HTTPException):
        return None, None
    finally:
        conn.close()


def fetch_well_known(origin: str, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
    """The well-known answer at `origin`, or None: nothing answers, the answer is not JSON, or the listener is not this
    OS account's process (DEC-0154 HA-2). `well_known_of` tells the last two apart."""
    return _read_well_known(origin, timeout)[0]


def well_known_of(origin: str, timeout: float = 2.0, vouch_pid: Optional[int] = None) -> Any:
    """The well-known answer at `origin` as the Node `wellKnownOf` gives it (FAA-259): the document; None when nothing
    answers or the answer is not JSON (down); a `ForeignUserAnswer` when the listener is another OS account's process or
    its owner cannot be told. So a status reads HA-2's order: down, foreign-user, foreign, status."""
    doc, why = _read_well_known(origin, timeout, vouch_pid=vouch_pid)
    return ForeignUserAnswer(why) if why else doc


def job_well_known_of(origin: str, job_pid: int, job_uid: Optional[int] = None, timeout: float = 2.0) -> Any:
    """As `well_known_of`, for a LaunchDaemon whose job `job_pid` (running as `job_uid`) must hold the listener."""
    doc, why = _read_job_well_known(origin, job_pid, job_uid)
    return ForeignUserAnswer(why) if why else doc


_OVERRIDE_ROW = re.compile(r'^\s*"([^"]+)"\s*=>\s*(\S+)\s*\Z')


def launchd_override(label: str, domain: Optional[str] = None) -> Optional[str]:
    """The operator's launchd override for ``label``: ``"disabled"``, ``"enabled"``, None when
    none is recorded (a first install), or ``"unknown"`` when the table cannot be read.

    Reads ``launchctl print-disabled gui/<uid>`` (``system`` with ``domain="system"``); macOS 14+ prints ``=> disabled|enabled``,
    older releases ``=> true|false`` (true means disabled)."""
    result = _launchctl("print-disabled", launchd_domain(domain=domain))
    if result.returncode != 0:
        return "unknown"
    for line in result.stdout.splitlines():
        match = _OVERRIDE_ROW.match(line)
        if match and match.group(1) == label:
            return "disabled" if match.group(2) in ("disabled", "true") else "enabled"
    return None


_PATH_ROW = re.compile(r"^\s*path\s*=\s*(.+?)\s*\Z")


def _plist_field(path: Path, key: str) -> Optional[str]:
    try:
        value = plistlib.loads(Path(path).read_bytes()).get(key)
    except Exception:  # unreadable or not a plist: it claims nothing
        return None
    return value if isinstance(value, str) else None


def _same_file(a: Any, b: Any) -> bool:
    """One file, whatever the case of its path (APFS ignores case, realpath keeps it)."""
    try:
        return os.path.samefile(str(a), str(b))
    except OSError:
        return os.path.realpath(str(a)) == os.path.realpath(str(b))


def _label_holders(label: str, plist_path: Path) -> List[Path]:
    """Other plists that hold launchd label ``label`` in the system domain (FAA-278): the plist launchd loaded the job
    from, when it is not ``plist_path``, and any plist of that label beside ``plist_path``. Reading needs no root."""
    found: List[Path] = []
    result = _launchctl("print", "system/%s" % label)
    if result.returncode == 0:
        for line in (result.stdout or "").splitlines():
            hit = _PATH_ROW.match(line)
            if hit:
                found.append(Path(hit.group(1)))
                break
    try:
        siblings = sorted(Path(plist_path).parent.glob("*.plist"))
    except OSError:
        siblings = []
    found += [p for p in siblings if _plist_field(p, "Label") == label]
    return [p for p in dict.fromkeys(found) if not _same_file(p, plist_path)]


def _answers(doc: Any, service_id: str, instance: str) -> bool:
    """Whether a well-known answer names this service and instance; any other JSON is no answer."""
    service = doc.get("service") if isinstance(doc, dict) else None
    return isinstance(service, dict) and service.get("id") == service_id and service.get("instance") == instance


def _refuse_held_label(label: str, plist_path: Path) -> None:
    holders = _label_holders(label, plist_path)
    if holders:
        owner = _plist_field(holders[0], "UserName")
        raise ServiceError("Label %s is already held by %s%s: the system domain is shared by every account of this "
                           "Mac, so a label is the machine's and one plist holds it. Choose a label of your own (for "
                           "example with the account in it), or remove that LaunchDaemon as root first."
                           % (label, holders[0], " (%s's)" % owner if owner else ""))


def launchd_install(label: str, plist_path: Path, plist_bytes: bytes, *, origin: str,
                    service_id: str, instance: str = "default", timeout: float = 40.0,
                    force_enable: bool = False, domain: Optional[str] = None,
                    fetch_well_known: Optional[Callable[..., Any]] = None,
                    fetch_job_well_known: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """Write + lint the plist, bootout and WAIT for unload, bootstrap (retry EIO 5), then
    poll the well-known document until it answers with this identity.

    The operator's intent wins (LC-14): only a first install (no override recorded) enables the
    label. A label the operator disabled stays disabled and unloaded — the plist is still
    rewritten, so the new release is what starts once they turn it back on — and the answer is
    ``{"disabled": True, "label", "plist", "loaded"}`` instead of the well-known document.
    ``force_enable`` is for an operator who asked for the service to be switched on.

    A plist in ``/Library/LaunchDaemons`` (or ``domain="system"``) is a LaunchDaemon in launchd's system domain, started
    at boot with no login (FAA-278): only root installs it, refused before anything is written otherwise, and the
    answer counts only when launchd's own job accepted the connection (its ``UserName``, not the installer, owns it).
    A ``gui/<uid>`` bootstrap with no GUI session (SSH, a headless Mac after a FileVault restart) says so.

    ``fetch_well_known(origin, vouch_pid=...)`` and ``fetch_job_well_known(origin, job_pid, job_uid)`` read the answer as
    ``well_known_of`` and ``job_well_known_of`` do (the document, None, or a ``ForeignUserAnswer``); a caller may inject
    its own, as the Node ``launchdInstall`` takes ``fetchWellKnown`` (FAA-259)."""
    read_answer = fetch_well_known or (lambda origin_, vouch_pid=None: well_known_of(origin_, vouch_pid=vouch_pid))
    read_job = fetch_job_well_known or job_well_known_of
    plist_path = Path(plist_path)
    pair = _pair_problem(plist_path, domain)
    if pair:
        raise ServiceError(pair)
    dom = launchd_domain(plist_path, domain)
    which = "system" if dom == "system" else None
    _need_root(dom, label, plist_path, True)
    if dom == "system":
        try:
            port = urllib.parse.urlsplit(origin).port
        except ValueError:  # a port out of range
            port = None
        if not (port and 1 <= port <= 65535 and origin == "http://127.0.0.1:%d" % port):
            raise ServiceError("A LaunchDaemon's origin is http://127.0.0.1:<port>: only there is its answer proved by "
                               "the job's pid and uid (FAA-278); %s is not." % origin)
        try:
            named = plistlib.loads(plist_bytes).get("UserName")
        except Exception as exc:  # named as what it is, never as a missing UserName (FAA-286 item 16)
            raise ServiceError("The plist does not parse (%s): write it with launchd_plist." % type(exc).__name__)
        named = named if isinstance(named, str) else None  # a UserName that is not a string names no account
        if named:
            _refuse_held_label(label, plist_path)
        if named and plist_path.exists():
            installed_label = _plist_field(plist_path, "Label")
            if installed_label is not None and installed_label != label:
                raise ServiceError("%s holds launchd label %s, not %s: writing over it would leave that job loaded from a "
                                   "plist that no longer describes it. Uninstall it as root first, or write this one at "
                                   "%s/%s.plist." % (plist_path, installed_label, label, SYSTEM_DAEMONS, label))
            installed = _plist_field(plist_path, "UserName")
            if installed and installed != named:
                raise ServiceError("%s is %s's LaunchDaemon: the system domain is shared by every account of this Mac, so "
                                   "a label is the machine's. Choose a label of your own (for example with the account in "
                                   "it), or uninstall that one as root first." % (plist_path, installed))
        if named and not _USER_NAME.match(named):
            raise ServiceError("UserName %s is not a macOS short name (%s): launchd takes the account's short name."
                               % (named, USER_NAME_RULE))
        job_uid = _account_uid(named) if named else None
        if named and job_uid is None:
            raise ServiceError("UserName %s is no account of this Mac: launchd would not start the job. Name the account "
                               "whose Fabric and agents call the service." % named)
        if job_uid == 0:
            raise ServiceError("UserName %s is root: the job would run as root, keep its data in root's home, and every "
                               "client refuses root's listener (DEC-0154 HA-2). Name the account whose Fabric and agents "
                               "call the service." % named)
        if not named:
            raise ServiceError("A LaunchDaemon needs UserName: without it the job runs as root, keeps its data in root's "
                               "home, and every client refuses root's listener (DEC-0154 HA-2). Write the plist with "
                               "launchd_plist(..., user_name=<the account whose Fabric and agents call it>).")
        leftover = _leftover_agent(label, named)
        if leftover is not None:
            raise ServiceError("%s is a LaunchAgent of label %s: it would start a second copy at %s's login beside this "
                               "LaunchDaemon. Remove it first (launchd_uninstall as %s; lifecycle reference, The system "
                               "domain)." % (leftover, label, named, named))
    existed = plist_path.exists()
    atomic_write(plist_path, plist_bytes, 0o644)
    lint = subprocess.run(["plutil", "-lint", str(plist_path)], capture_output=True, text=True)
    if lint.returncode != 0:
        raise ServiceError("plist failed plutil -lint: %s" % lint.stdout.strip())
    target = "%s/%s" % (dom, label)
    override = launchd_override(label, which)
    if force_enable or override is None:
        _launchctl("enable", target)
    elif override == "disabled":
        return {"disabled": True, "label": label, "plist": str(plist_path), "loaded": launchd_loaded(label, which)}
    _launchctl("bootout", target)
    deadline = time.time() + 15
    while launchd_loaded(label, which) and time.time() < deadline:
        time.sleep(0.25)
    last = ""
    for _ in range(5):
        result = _launchctl("bootstrap", dom, str(plist_path))
        if result.returncode == 0:
            break
        last = (result.stderr or result.stdout).strip()
        time.sleep(1.0)
    else:
        if dom != "system" and re.search(r":\s*125:|Domain does not support|Could not find domain", last):
            raise ServiceError("launchctl bootstrap failed: %s. This user has no GUI login session (an SSH session, or a "
                               "headless Mac after a FileVault restart), so %s does not run jobs: remove the LaunchAgent "
                               "this attempt wrote (launchd_uninstall), then install it as a LaunchDaemon in the system "
                               "domain (a plist in %s with UserName, as root; FAA-278)." % (last, dom, SYSTEM_DAEMONS))
        if dom == "system":
            # a plist left in /Library/LaunchDaemons loads at the next boot (FAA-286 item 15): one this call wrote goes
            if not existed:
                try:
                    plist_path.unlink()
                except OSError:
                    pass
            raise ServiceError("launchctl bootstrap failed: %s; %s" % (last, "the plist this call wrote was removed"
                               if not plist_path.exists() else "%s stays and loads at the next boot: remove it as root"
                               % plist_path))
        raise ServiceError("launchctl bootstrap failed: %s" % last)
    deadline = time.time() + timeout
    if dom == "system":
        foreign = None
        while time.time() < deadline:
            job = launchd_pid(label, "system")
            doc = read_job(origin, job, job_uid) if job else None
            why = doc.reason if isinstance(doc, ForeignUserAnswer) else None
            foreign = why or foreign  # the last refusal stays the reason while launchd shows no pid
            if not why and _answers(doc, service_id, instance):
                return doc
            time.sleep(0.5)
        loaded = ("; the job stays loaded and its plist starts it again at boot: as root, `launchctl bootout system/%s` "
                  "and removing %s (or launchd_uninstall) take it away" % (label, plist_path))
        if foreign and foreign.startswith(_po.TABLE_RESTRICTED):
            raise ServiceError("%s could not be proved this LaunchDaemon's: %s; the job's pid did not show the listener: "
                               "start the server with exec (no wrapper child), or read the job's log%s."
                               % (origin, foreign, loaded))
        if foreign:
            raise ServiceError("%s is not this LaunchDaemon's: %s%s." % (origin, foreign, loaded))
        raise ServiceError("%s did not answer as %s.%s within %.0f s; read its log%s."
                           % (origin, service_id, instance, timeout, loaded))
    foreign = vouch = None
    while time.time() < deadline:
        doc = read_answer(origin, vouch_pid=vouch)
        foreign = doc.reason if isinstance(doc, ForeignUserAnswer) else None
        if foreign and foreign.startswith(_po.TABLE_RESTRICTED):
            vouch = launchd_pid(label)  # only a restricted table needs the job's pid (FAA-267)
        if not foreign and _answers(doc, service_id, instance):
            return doc
        time.sleep(0.5)
    if foreign:
        # DEC-0154 HA-2 and service.md's Install row: a listener of another account is never a successful install.
        if foreign.startswith(_po.TABLE_RESTRICTED):
            raise ServiceError("%s could not be proved this service's: %s (DEC-0154 HA-2); this interpreter sees no other "
                               "process's sockets and the job's pid did not show the listener: run the installer from "
                               "Apple's /usr/bin/python3, or read the job's log." % (origin, foreign))
        raise ServiceError("%s is not this service's: %s (DEC-0154 HA-2); the port is another OS account's or its owner "
                           "cannot be told." % (origin, foreign))
    raise ServiceError("%s did not answer as %s.%s within %.0f s; read its log." % (origin, service_id, instance, timeout))


def launchd_uninstall(label: str, plist_path: Path, *, timeout: float = 30.0, purge: bool = False,
                      service_id: Optional[str] = None, instance: str = "default",
                      domain: Optional[str] = None) -> Dict[str, Any]:
    """Symmetric with ``launchd_install`` (LC-14): bootout and WAIT until the job is gone, remove
    the plist, and reset the override to ``enabled`` — launchctl has no verb that deletes an
    override, and a leftover ``disabled`` would make a later fresh install stay off. Data stays
    unless ``purge`` (then ``service_id`` names whose data, logs and cache go, and ``instance`` which
    instance's: ``instance_dirs``, so one context's purge never reaches another's, FAA-125). A job still
    loaded at ``timeout`` raises, leaving the plist and data in place. A LaunchDaemon (a plist in
    ``/Library/LaunchDaemons``, or ``domain="system"``) is removed only by root, and its data belongs to its UserName,
    so ``purge`` is refused for it: remove the data as that user (FAA-278)."""
    if purge and not service_id:
        raise ServiceError("purge needs the service id whose data, logs and cache to remove.")
    dom = launchd_domain(Path(plist_path), domain)
    which = "system" if dom == "system" else None
    _need_root(dom, label, Path(plist_path), False)
    if purge and dom == "system":
        raise ServiceError("A LaunchDaemon's data belongs to its UserName, not to root: uninstall without purge, then "
                           "remove the data as that user.")
    if dom == "system":
        _refuse_held_label(label, Path(plist_path))  # a bootout would stop another plist's job (FAA-278)
    holds = _plist_field(Path(plist_path), "Label") if Path(plist_path).exists() else None
    if holds is not None and holds != label:  # FAA-286 item 9: booting out one job and unlinking another's plist
        raise ServiceError("%s holds launchd label %s, not %s: nothing was removed. Name the plist of %s, or uninstall %s "
                           "with its own label." % (plist_path, holds, label, label, holds))
    dirs = instance_dirs(str(service_id), instance) if purge else {}
    target = "%s/%s" % (dom, label)
    _launchctl("bootout", target)
    deadline = time.monotonic() + timeout
    while launchd_loaded(label, which):
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
        for directory in dirs.values():
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
