"""working-with-fabric, part of fabric_session.py (FAA-65): where Fabric and the session's files are, whether a
project uses Fabric, whether Fabric launched this session, and the log and spool the hooks write. Standard library only."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from typing import Dict


HUB_PROTOCOL = "fabric-hub/0.1"


HOOK_FEATURE = "session-hooks/1"


BOARD_STATUS_TOOL = "com.status"


WORKER_DEADLINE_S = 10.0


GIT_TIMEOUT_S = 1.5


PS_TIMEOUT_S = 0.5


LOG_CAP_BYTES = 1_000_000


SPOOL_CAP = 50


LOCK_STALE_S = 30.0


#: A session folder untouched this long belongs to a session that will not spool again: its worker failed, or the
#: session ended without SessionEnd. Nothing retries it, so the next spooling hook removes it (FAA-50).
SESSION_STALE_S = 7 * 86400


READ_CAP = 64 * 1024


CONFIG_CAP = 32 * 1024 * 1024


SESSION_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")


LOOPBACK_ORIGIN = re.compile(r"http://127\.0\.0\.1:(\d{1,5})")


VERSION = "0.48.0"


HOSTS = {"claude": "Claude Code", "codex": "Codex", "kimi": "Kimi Code",
         "hermes": "Hermes", "opencode": "OpenCode", "openclaw": "OpenClaw", "pi": "Pi"}


NATIVE_PLUGIN_HOSTS = frozenset(("hermes", "opencode", "openclaw", "pi"))


# A session Fabric launched. FABRIC_LAUNCHED_SESSION=1 is the marker Fabric is asked to set (need D6); the others are
# what Fabric already gives a launched session (fabric sessionBundle.ts): only their NAMES are looked at, never a value
# — two of them carry the session's credential.
LAUNCH_MARKER = "FABRIC_LAUNCHED_SESSION"


LAUNCH_SIGNALS = ("FABRIC_ACP_SESSION", "FABRIC_BRIDGE_URL", "KILO_CONFIG_CONTENT")


#: Files that make a folder a Fabric project: the provider manifest and the contract pin adapt_project.py writes, and
#: a fabric-package/1 folder's manifest.
FABRIC_MARKERS = ("fabric-agent.json", "fabric-contract.lock.json", "fabric.package.json")


UNREAD_LINE = "%d unread on the project board: com.list"


def _home(env: Optional[Dict[str, str]] = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("HOME") or env.get("USERPROFILE") or str(Path.home()))


def fabric_root(platform: str = sys.platform, env: Optional[Dict[str, str]] = None) -> Path:
    """Fabric's registry root, where hub.json lives (fabric `agentRegistry.ts#registryDirs`)."""
    env = os.environ if env is None else env
    home = _home(env)
    if platform == "darwin":
        return home / "Library/Application Support/ai.passioncode.fabric"
    if platform == "win32":
        return Path(env.get("LOCALAPPDATA") or str(home / "AppData" / "Local")) / "passioncode-fabric"
    return Path(env.get("XDG_DATA_HOME") or str(home / ".local/share")) / "passioncode-fabric"


def state_root(platform: str = sys.platform, env: Optional[Dict[str, str]] = None) -> Path:
    """The hooks' own folder: the log and the per-session spool. Never Fabric's folder."""
    env = os.environ if env is None else env
    home = _home(env)
    if platform == "darwin":
        return home / "Library/Caches/ai.passioncode.fabric-agent-adapter"
    if platform == "win32":
        return Path(env.get("LOCALAPPDATA") or str(home / "AppData" / "Local")) / "fabric-agent-adapter"
    return Path(env.get("XDG_CACHE_HOME") or str(home / ".cache")) / "fabric-agent-adapter"


def fabric_bin_candidates(platform: str = sys.platform, env: Optional[Dict[str, str]] = None) -> List[Path]:
    """Where `<Fabric>/bin/fabric-mcp` is on a default install (ADR-0134 amendment 2; electron-builder targets)."""
    env = os.environ if env is None else env
    home = _home(env)
    if platform == "darwin":
        return [Path("/Applications/Fabric.app/Contents/Resources/bin/fabric-mcp"),
                home / "Applications/Fabric.app/Contents/Resources/bin/fabric-mcp"]
    if platform == "win32":
        local = Path(env.get("LOCALAPPDATA") or str(home / "AppData" / "Local"))
        return [local / "Programs" / "Fabric" / "resources" / "bin" / "fabric-mcp.cmd"]
    return [Path("/opt/Fabric/resources/bin/fabric-mcp")]


def find_fabric_bin(platform: str = sys.platform, env: Optional[Dict[str, str]] = None) -> Optional[Path]:
    for candidate in fabric_bin_candidates(platform, env):
        if candidate.is_file():
            return candidate
    return None


def read_small(path: Path, cap: int = READ_CAP) -> Optional[str]:
    """A regular file's text, or None: no FIFO, device or link target is read, nothing past `cap`."""
    try:
        st = os.lstat(str(path))
    except OSError:
        return None
    import stat as _stat
    if not _stat.S_ISREG(st.st_mode) or st.st_size > cap:
        return None
    try:
        with open(str(path), "r", encoding="utf-8") as handle:
            return handle.read(cap)
    except (OSError, UnicodeDecodeError):
        return None


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # os.kill(pid, 0) on Windows sends CTRL_C_EVENT: never use it to probe.
        import ctypes
        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def locate_hub(root: Path, alive=pid_alive) -> Dict[str, Any]:
    """hub.json read the way an agent must (fabric `hub.ts#locateHub`), minus the door token: never read here."""
    hub_file = root / "hub.json"
    if not os.path.lexists(str(hub_file)):
        return {"state": "not-running", "reason": "there is no hub.json"}
    text = read_small(hub_file)
    if text is None:
        return {"state": "not-a-hub", "reason": "hub.json is not a small regular file"}
    try:
        doc = json.loads(text)
    except ValueError:
        return {"state": "not-a-hub", "reason": "hub.json is not JSON"}
    if not isinstance(doc, dict) or doc.get("protocol") != HUB_PROTOCOL:
        return {"state": "not-a-hub", "reason": "hub.json does not speak %s" % HUB_PROTOCOL}
    match = LOOPBACK_ORIGIN.fullmatch(doc.get("origin") if isinstance(doc.get("origin"), str) else "")
    if not match or not 1024 <= int(match.group(1)) <= 65535 or doc.get("mcp") != "/mcp":
        return {"state": "not-a-hub", "reason": "hub.json names another origin or MCP path"}
    pid = doc.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return {"state": "not-a-hub", "reason": "hub.json names no process"}
    if not alive(pid):
        return {"state": "not-running", "reason": "hub.json names process %d, which is not running" % pid}
    features = doc.get("features")
    features = [f for f in features if isinstance(f, str)] if isinstance(features, list) else []
    return {"state": "running", "pid": pid, "features": features}


def _ancestors(cwd: Path) -> List[Path]:
    try:
        cwd = cwd.resolve()
    except OSError:
        pass
    return [cwd] + list(cwd.parents)


def _stdio_entry(entry: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(entry, dict) or not isinstance(entry.get("command"), str):
        return None
    if entry.get("type") not in (None, "stdio"):
        return None
    args = entry.get("args") if isinstance(entry.get("args"), list) else []
    command = entry["command"]
    name = re.split(r"[\\/]", command)[-1].lower()
    return {"command": command, "args": [str(a) for a in args],
            "fabricMcp": name in ("fabric-mcp", "fabric-mcp.cmd")}


def claude_registration(cwd: Path, env: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """Claude Code's MCP server `fabric` for this folder: local, then project (.mcp.json), then user scope.
    Only command and args are returned; an entry's env is never read out."""
    home = _home(env)
    config: Dict[str, Any] = {}
    text = read_small(home / ".claude.json", CONFIG_CAP)
    if text:
        try:
            loaded = json.loads(text)
            config = loaded if isinstance(loaded, dict) else {}
        except ValueError:
            config = {}
    projects = config.get("projects") if isinstance(config.get("projects"), dict) else {}
    for folder in _ancestors(cwd):
        servers = (projects.get(str(folder)) or {}).get("mcpServers") if isinstance(projects.get(str(folder)), dict) else None
        found = _stdio_entry((servers or {}).get("fabric")) if isinstance(servers, dict) else None
        if found:
            return dict(found, scope="local")
    for folder in _ancestors(cwd):
        text = read_small(folder / ".mcp.json")
        if text:
            try:
                servers = json.loads(text).get("mcpServers")
            except (ValueError, AttributeError):
                servers = None
            found = _stdio_entry(servers.get("fabric")) if isinstance(servers, dict) else None
            if found:
                return dict(found, scope="project")
    servers = config.get("mcpServers")
    found = _stdio_entry(servers.get("fabric")) if isinstance(servers, dict) else None
    return dict(found, scope="user") if found else None


def codex_registered(env: Optional[Dict[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    codex_home = Path(env.get("CODEX_HOME") or str(_home(env) / ".codex"))
    text = read_small(codex_home / "config.toml", CONFIG_CAP) or ""
    return re.search(r'^\s*\[\s*"?mcp_servers"?\s*\.\s*"?fabric"?\s*\]\s*$', text, re.MULTILINE) is not None


def kimi_registered(env: Optional[Dict[str, str]] = None) -> bool:
    """Kimi Code keeps its MCP servers in ~/.kimi-code/mcp.json (`mcpServers`, Claude's shape)."""
    text = read_small(_home(env) / ".kimi-code" / "mcp.json", CONFIG_CAP)
    try:
        servers = json.loads(text).get("mcpServers") if text else None
    except (ValueError, AttributeError):
        return False
    return isinstance(servers, dict) and _stdio_entry(servers.get("fabric")) is not None


def host_registered(host: str, cwd: Path, env: Optional[Dict[str, str]] = None) -> bool:
    if host == "claude":
        return claude_registration(cwd, env) is not None
    if host == "codex":
        return codex_registered(env)
    if host == "kimi":
        return kimi_registered(env)
    return False


def services_dir(platform: str = sys.platform, env: Optional[Dict[str, str]] = None) -> Path:
    """Where fabric-service/0.1 descriptors live: FABRIC_SERVICES_DIR, else Fabric's folder per OS + /services."""
    env = os.environ if env is None else env
    if env.get("FABRIC_SERVICES_DIR"):
        return Path(env["FABRIC_SERVICES_DIR"])
    return fabric_root(platform, env) / "services"


def checkout_root(cwd: Path, env: Optional[Dict[str, str]] = None) -> Optional[Path]:
    """The nearest folder at or above cwd with a `.git` entry (a worktree's `.git` is a file), never past HOME; None
    outside a checkout. No subprocess."""
    home = _home(env)
    for folder in _ancestors(cwd):
        if os.path.lexists(str(folder / ".git")):
            return folder
        if folder == home:
            break
    return None


def _repository_key(url: str) -> str:
    """One spelling of a remote: scheme, user, `.git` and case dropped; `git@host:a/b` is `host/a/b`."""
    url = url.strip().lower()
    url = re.sub(r"^git@([^:]+):", r"\1/", url)
    url = re.sub(r"^[a-z+]+://", "", url)
    url = re.sub(r"^[^@/]+@", "", url)
    return re.sub(r"\.git$", "", url).rstrip("/")


def _origin(root: Path) -> str:
    try:
        done = subprocess.run(["git", "--no-optional-locks", "-C", str(root), "config", "--get", "remote.origin.url"],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=GIT_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.decode("utf-8", "replace").strip() if done.returncode == 0 else ""


def owns_a_service(root: Path, env: Optional[Dict[str, str]] = None, platform: str = sys.platform) -> bool:
    """Whether a service descriptor names this checkout's origin as its `source.repository`. Reads each descriptor's
    `source` only; never its auth block or a token file."""
    origin = _origin(root)
    if not origin:
        return False
    directory = services_dir(platform, env)
    try:
        names = sorted(p for p in os.listdir(str(directory)) if p.endswith(".json") and not p.startswith("."))
    except OSError:
        return False
    key = _repository_key(origin)
    for name in names:
        try:
            doc = json.loads(read_small(directory / name) or "null")
        except ValueError:
            continue
        source = doc.get("source") if isinstance(doc, dict) else None
        repository = source.get("repository") if isinstance(source, dict) else None
        if isinstance(repository, str) and repository and _repository_key(repository) == key:
            return True
    return False


def project_uses_fabric(cwd: Path, env: Optional[Dict[str, str]] = None,
                        registration: Optional[Dict[str, Any]] = None, platform: str = sys.platform) -> Optional[str]:
    """Which sign says the project at cwd works with Fabric, or None. Cheapest first: `registration` when Claude Code
    has `fabric` at local or project scope (bound to this folder; user scope says nothing about it); a FABRIC_MARKERS
    file from cwd up to its checkout's root (cwd alone outside a checkout); `service` when a descriptor names the
    checkout's origin."""
    if registration and registration.get("scope") in ("local", "project"):
        return "registration"
    root = checkout_root(cwd, env)
    folders = _ancestors(cwd)
    folders = folders[:folders.index(root) + 1] if root in folders else folders[:1]
    import stat as _stat
    for folder in folders:
        for name in FABRIC_MARKERS:
            try:
                if _stat.S_ISREG(os.lstat(str(folder / name)).st_mode):
                    return name
            except OSError:
                continue
    if root is not None and owns_a_service(root, env, platform):
        return "service"
    return None


def fabric_launched(env: Optional[Dict[str, str]] = None, platform: str = sys.platform) -> Optional[str]:
    """The name of the signal that says Fabric launched this session, or None. Cheap: the environment only."""
    env = os.environ if env is None else env
    marker = env.get(LAUNCH_MARKER)
    if marker and marker != "0":
        return LAUNCH_MARKER
    for name in LAUNCH_SIGNALS:
        if name in env:  # the name only: never the value
            return name
    codex_home = env.get("CODEX_HOME")
    if codex_home:
        sessions = os.path.normpath(str(fabric_root(platform, env) / "sessions")) + os.sep
        if os.path.normpath(codex_home).startswith(sessions):
            return "CODEX_HOME"
    return None


def _process(pid: int) -> Tuple[Optional[str], int]:
    """A process's command line and its parent's pid, or (None, 0). POSIX only; bounded."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/%d/cmdline" % pid, "rb") as handle:
                command = handle.read(READ_CAP).replace(b"\0", b" ").decode("utf-8", "replace")
            with open("/proc/%d/stat" % pid, "r", encoding="utf-8", errors="replace") as handle:
                parent = int(handle.read(4096).rsplit(")", 1)[1].split()[1])
            return command, parent
        if sys.platform == "win32":
            return None, 0
        done = subprocess.run(["ps", "-ww", "-o", "ppid=", "-o", "command=", "-p", str(pid)], stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=PS_TIMEOUT_S, check=False)
        parent_text, _, command = done.stdout.decode("utf-8", "replace").strip().partition(" ")
        return (command, int(parent_text)) if done.returncode == 0 and parent_text.isdigit() else (None, 0)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None, 0


def launched_by_ancestor(env: Optional[Dict[str, str]] = None, depth: int = 4,
                         process: Optional[Callable[[int], Tuple[Optional[str], int]]] = None,
                         platform: str = sys.platform) -> Optional[bool]:
    """A Claude Code Fabric launched runs with `--mcp-config <Fabric>/sessions/<id>/mcp.json` (sessionBundle.ts,
    adapter mcp-config-flag) and no environment marker yet: look for that in this hook's few ancestors. True or False
    once the walk is done; None when a process could not be read (a `ps` that failed or ran out of time), which is
    "unknown", never "not launched" (FAA-68). Windows has no walk (`_process` reads no process there): False, so
    only the environment signals count. Only the path is matched; nothing read here is kept or logged."""
    if process is None and platform == "win32":
        return False
    marker = os.path.normpath(str(fabric_root(env=env) / "sessions")) + os.sep
    process = process or _process
    pid = os.getppid()
    for _ in range(depth):
        if pid <= 1:
            return False
        command, parent = process(pid)
        if command is None:
            return None
        if "--mcp-config" in command and marker in command:
            return True
        pid = parent
    return False


#: A session rejoins at most once in this span (FAA-53): every rejoin spends Fabric's per-agent request budget, which
#: every session of the machine shares. The Stop worker and watch-mail both honour and renew the mark (FAA-68).
REJOIN_MIN_INTERVAL_S = 60.0


#: The file in a session's folder that says Fabric launched it: the ancestor walk ran once and found the launcher.
LAUNCHED_MARK = "launched"


#: The file in a session's folder that says Fabric held no session for its id: fabric-mcp --rejoin-only exited 3
#: (Fabric 0.3.9, TR-11). For NO_SESSION_HOLD_S the hooks spool nothing for that id; after it, one rejoin tries again,
#: so a Fabric that restarted and enrolled the id again is found (board thread 02bf19c5, ask 4).
NO_SESSION_MARK = "no-session"
NO_SESSION_HOLD_S = 15 * 60.0


def no_session_held(directory: Path, now: Optional[float] = None) -> bool:
    """Whether a rejoin found no Fabric session for this id within NO_SESSION_HOLD_S."""
    try:
        mark = (directory / NO_SESSION_MARK).stat().st_mtime
    except OSError:
        return False
    age = (time.time() if now is None else now) - mark
    return 0 <= age < NO_SESSION_HOLD_S


def rejoined_recently(directory: Path, now: Optional[float] = None) -> bool:
    """Whether this session's last rejoin succeeded within REJOIN_MIN_INTERVAL_S (the worker marks it)."""
    return rejoin_wait(directory, now) > 0


def rejoin_wait(directory: Path, now: Optional[float] = None) -> float:
    """Seconds until this session may rejoin again; 0 when it may now."""
    try:
        mark = (directory / "rejoined").stat().st_mtime
    except OSError:
        return 0.0
    age = (time.time() if now is None else now) - mark
    return REJOIN_MIN_INTERVAL_S - age if 0 <= age < REJOIN_MIN_INTERVAL_S else 0.0


def log(line: str, env: Optional[Dict[str, str]] = None) -> None:
    """One structured line, 0600, rotated at 1 MB. Never raises."""
    try:
        root = state_root(env=env)
        root.mkdir(parents=True, exist_ok=True)
        path = root / "hooks.log"
        if path.exists() and path.stat().st_size > LOG_CAP_BYTES:
            os.replace(str(path), str(root / "hooks.log.1"))
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), line))
    except Exception:  # noqa: BLE001 — logging never breaks a hook
        pass


def _write_private(path: Path, text: str) -> None:
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(str(tmp), str(path))


def session_dir(session_id: str, env: Optional[Dict[str, str]] = None) -> Path:
    return state_root(env=env) / "sessions" / session_id


def spool(directory: Path, entry: Dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / ("%020d-%s.json" % (time.time_ns(), entry["event"]))
    _write_private(path, json.dumps(entry, sort_keys=True))
    turns = sorted(directory.glob("*-turn.json"))
    for old in turns[:max(0, len(turns) - SPOOL_CAP)]:
        try:
            old.unlink()
        except OSError:
            pass
    return path


def prune_stale_sessions(env: Optional[Dict[str, str]] = None, now: Optional[float] = None,
                         keep: Optional[str] = None) -> int:
    """Remove session folders whose newest file is older than SESSION_STALE_S (a running worker's lock is a fresh file,
    so its folder is never stale); never the folder of the session `keep`. Returns how many were removed. Never
    raises."""
    now = time.time() if now is None else now
    removed = 0
    try:
        folders = list((state_root(env=env) / "sessions").iterdir())
    except OSError:
        return 0
    for folder in folders:
        try:
            if folder.name == keep or not SESSION_ID.fullmatch(folder.name) or not folder.is_dir():
                continue
            newest = max([folder.stat().st_mtime] + [f.stat().st_mtime for f in folder.iterdir()])
            if now - newest > SESSION_STALE_S:
                _remove_tree(folder)
                removed += 1
        except OSError:
            continue
    return removed


def lock_held(directory: Path) -> bool:
    lock = directory / "worker.lock"
    try:
        return time.time() - lock.stat().st_mtime < LOCK_STALE_S
    except OSError:
        return False


def spawn_worker(directory: Path) -> None:
    """Start `deliver` detached: the hook returns at once and the worker outlives the session if it must."""
    argv = [sys.executable, "-S", str(Path(__file__).resolve().with_name("fabric_session.py")), "deliver", str(directory)]  # the entry point, not this module
    options: Dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                               "stderr": subprocess.DEVNULL, "close_fds": True}
    if sys.platform == "win32":
        options["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    subprocess.Popen(argv, **options)  # noqa: S603 — our own script, argv holds no secret


def _remove_tree(directory: Path) -> None:
    import shutil
    shutil.rmtree(str(directory), ignore_errors=True)
