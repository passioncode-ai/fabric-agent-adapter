"""Supervisors (DEC-0032, LC-14): launchd plists, systemd user units and Task Scheduler tasks, installed and
removed without touching what the operator turned off; release pruning (LC-15). Part of the service kit
(FAA-65, layer L3)."""
from __future__ import annotations

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
import urllib.request
from pathlib import Path, PurePath
from typing import Any, Callable, Dict, List, Optional, Sequence

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
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
    instead of exiting into a respawn loop.

    The same refusals as the Node twin (finding 10): a label launchd cannot name, no program, an ExitTimeOut that does
    not outlast the drain, an environment name ending TOKEN/SECRET/PASSWORD/KEY (a `*_FILE` path is fine), a value or
    an argument shaped like a credential, and a control character in any string the plist carries."""
    import fabric_secrets  # noqa: E402 - beside this file; the contract's detector (DEC-0044)
    if not _LABEL.match(str(label)):
        raise ServiceError("label must match %s" % _LABEL.pattern)
    argv = [str(a) for a in program_arguments]
    if not argv:
        raise ServiceError("A launchd job starts a program; ProgramArguments is empty.")
    if not exit_timeout > DRAIN_SECONDS:
        raise ServiceError("ExitTimeOut must outlast the %d s drain." % DRAIN_SECONDS)
    env = dict(environment or {})
    for key, value in env.items():
        if re.search(r"(TOKEN|SECRET|PASSWORD|KEY)\Z", key) and not key.endswith("_FILE"):
            raise ServiceError("Environment variable %s looks like a secret; pass a *_FILE path instead." % key)
        if fabric_secrets.secret_value(str(value)):
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


_OVERRIDE_ROW = re.compile(r'^\s*"([^"]+)"\s*=>\s*(\S+)\s*\Z')


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
                      service_id: Optional[str] = None, instance: str = "default") -> Dict[str, Any]:
    """Symmetric with ``launchd_install`` (LC-14): bootout and WAIT until the job is gone, remove
    the plist, and reset the override to ``enabled`` — launchctl has no verb that deletes an
    override, and a leftover ``disabled`` would make a later fresh install stay off. Data stays
    unless ``purge`` (then ``service_id`` names whose data, logs and cache go, and ``instance`` which
    instance's: ``instance_dirs``, so one context's purge never reaches another's, FAA-125). A job still
    loaded at ``timeout`` raises, leaving the plist and data in place."""
    if purge and not service_id:
        raise ServiceError("purge needs the service id whose data, logs and cache to remove.")
    dirs = instance_dirs(str(service_id), instance) if purge else {}
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
