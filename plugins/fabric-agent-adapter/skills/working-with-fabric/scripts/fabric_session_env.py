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
from typing import Callable, List, Optional, Tuple


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


VERSION = "0.83.1"


HOSTS = {"claude": "Claude Code", "codex": "Codex", "kimi": "Kimi Code",
         "hermes": "Hermes", "opencode": "OpenCode", "openclaw": "OpenClaw", "pi": "Pi"}


NATIVE_PLUGIN_HOSTS = frozenset(("hermes", "opencode", "openclaw", "pi"))


# A session Fabric launched. FABRIC_LAUNCHED_SESSION=1 is the marker Fabric is asked to set (need D6); the others are
# what Fabric already gives a launched session (fabric sessionBundle.ts): only their NAMES are looked at, never a value
# — two of them carry the session's credential.
LAUNCH_MARKER = "FABRIC_LAUNCHED_SESSION"


LAUNCH_SIGNALS = ("FABRIC_ACP_SESSION", "FABRIC_BRIDGE_URL", "KILO_CONFIG_CONTENT")


#: FAA-201: the workflow id a launcher names in FABRIC_DISPATCH_WORKFLOW (Observatory's WORKFLOW_ID); the one copy the
#: session modules read. dashboard_kit.py keeps its own (it is a kit module) and a test holds the two equal.
DISPATCH_WORKFLOW = r"wf_[0-9a-f]{16}"


#: Files that make a folder a Fabric project: the provider manifest and the contract pin adapt_project.py writes, and
#: a fabric-package/1 folder's manifest.
FABRIC_MARKERS = ("fabric-agent.json", "fabric-contract.lock.json", "fabric.package.json")


#: FAA-205 (the operator's rule of 2026-11-04, relayed on the board, thread 11646774): what waits on the Project gets
#: an answer in the same turn, its state now, the result later in a second message. The line keeps its prefix, which
#: watchers match on.
UNREAD_LINE = ("%d unread on the project board: com.list; answer what waits on you in this turn: its state now (done, "
               "where, when, what blocks), the result later")

#: FAA-142 (Fabric 0.3.14, ask dfb43ffb): a turn's `fabric_session_observe` answer may carry `nudges`, each
#: {kind, says, task_id?, request_id?}, shown on a turn once (at most five) and kept for fabric_work_list. The worker keeps their `says` here and the prompt hook prints
#: them once: at most MAX_NUDGES lines, each one line of at most MAX_NUDGE_CHARS characters.
NUDGES_FILE = "nudges.json"
#: Each nudge's line names its source, so the agent sees Fabric's words, data to act on through its tools, never the
#: person's request. Fabric 0.3.14 starts every `says` with "Fabric:" (board e94ec9c0; tag v0.3.14 7e43dc03, FAA-143); a
#: line that does not gets this tag.
NUDGE_PREFIX = "Fabric reminder: "


def nudge_shown(line: str) -> str:
    return line if line.startswith("Fabric:") else NUDGE_PREFIX + line
#: The nudges of turns a `watch-mail` look delivered (FAA-89): that look prints them, the prompt hook never does.
WATCH_NUDGES_FILE = "nudges.watch.json"
MAX_NUDGES = 5
MAX_NUDGE_CHARS = 400
#: At most this many items of an answer's nudges are read (FAA-143): a broken Fabric's long list costs linear time.
MAX_NUDGE_ITEMS = 1000
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]+")


def nudge_lines(value: Any, limit: Optional[int] = MAX_NUDGES) -> List[str]:
    """The `says` of a nudges list as clean lines: one line each (controls and line breaks become a space), cut to
    MAX_NUDGE_CHARS, blanks and repeats dropped, at most `limit` (None: all) from the first MAX_NUDGE_ITEMS items.
    Anything that is not such a list gives []."""
    lines: List[str] = []
    seen = set()
    if not isinstance(value, list):
        return lines
    for item in value[:MAX_NUDGE_ITEMS]:
        says = item.get("says") if isinstance(item, dict) else None
        if not isinstance(says, str):
            continue
        line = " ".join(_CONTROL.sub(" ", says).split())[:MAX_NUDGE_CHARS].rstrip()
        if line and line not in seen:
            seen.add(line)
            lines.append(line)
        if limit is not None and len(lines) == limit:
            break
    return lines


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


#: The launcher's folder for every app it installs, when the person sets one (FAA-237).
APPLICATIONS_ENV = "PASSIONCODE_APPLICATIONS"


def launcher_folder(env: Optional[Dict[str, str]] = None) -> Optional[Path]:
    """The folder `PASSIONCODE_APPLICATIONS` names, when it starts with `/` (FAA-237). The launcher's `appsDir` takes
    any non-empty value as it is, so a relative value or a literal `~` would be a folder under the launcher's working
    folder, which no other process can find: none here, and the default order holds. A macOS path is POSIX on
    whatever host reads it."""
    value = (os.environ if env is None else env).get(APPLICATIONS_ENV) or ""
    return Path(value) if value.startswith("/") else None


def fabric_bin_candidates(platform: str = sys.platform, env: Optional[Dict[str, str]] = None) -> List[Path]:
    """Where `<Fabric>/bin/fabric-mcp` is on a default install (ADR-0134 amendment 2; electron-builder targets)."""
    env = os.environ if env is None else env
    home = _home(env)
    if platform == "darwin":
        # The launcher's one folder for every app, when the person set it (its lib/catalog.js appsDir; FAA-237): only
        # there. An empty or relative value is not a place, and the default order holds.
        chosen = launcher_folder(env)
        if chosen:
            return [chosen / "Fabric.app/Contents/Resources/bin/fabric-mcp"]
        # The user's own copy first: on a Mac with several users a copy in /Applications may be another user's
        # (FAA-229; the launcher's order from its PR #277, lib/catalog.js appPath, planned for launcher 0.2.76).
        return [home / "Applications/Fabric.app/Contents/Resources/bin/fabric-mcp",
                Path("/Applications/Fabric.app/Contents/Resources/bin/fabric-mcp")]
    if platform == "win32":
        local = Path(env.get("LOCALAPPDATA") or str(home / "AppData" / "Local"))
        return [local / "Programs" / "Fabric" / "resources" / "bin" / "fabric-mcp.cmd"]
    return [Path("/opt/Fabric/resources/bin/fabric-mcp")]


def _owner_uid(path: Path) -> Optional[int]:
    try:
        return os.stat(str(path)).st_uid
    except (OSError, ValueError):  # ValueError: a NUL in a path read from a config file
        return None


def a_file(path: Path) -> bool:
    """`path.is_file()`, False where it cannot be read: the launcher's folder is the person's choice and may sit under a
    folder this user cannot enter, where Python before 3.14 raises PermissionError (0.70.0 unit reading 4)."""
    try:
        return path.is_file()
    except (OSError, ValueError):
        return False


def _real(path: Path) -> Path:
    try:
        return Path(os.path.realpath(str(path)))
    except (OSError, ValueError):
        return path


def another_users_copy(path: Path, platform: str = sys.platform, env: Optional[Dict[str, str]] = None) -> bool:
    """On macOS, a file outside the user's home that is neither this user's nor root's: another user's copy, which this
    user must not run (FAA-229). Root's is an install every user shares, not another user's. False elsewhere, and for a
    path it cannot read. A bare command is the one PATH resolves to, and a link is judged by what it points at, so a
    link in the home to another user's copy is that copy."""
    if platform != "darwin" or not hasattr(os, "getuid"):
        return False
    environ = os.environ if env is None else env
    if not path.is_absolute():
        if len(path.parts) != 1:  # relative to a folder Claude Code starts it in, which this does not know
            return False
        import shutil  # only status reaches this; the hooks never pay for the import

        found = shutil.which(str(path), path=environ.get("PATH", os.defpath))
        if not found:
            return False
        path = Path(found)
    path = _real(path)
    if _real(_home(environ)) in path.parents:
        return False
    owner = _owner_uid(path)
    return owner is not None and owner not in (os.getuid(), 0)


def administrators_copy(path: Path, platform: str = sys.platform, env: Optional[Dict[str, str]] = None) -> bool:
    """On macOS, a file outside the user's home that root owns: an install the administrator made (a pkg or MDM). This
    user may run it, and the launcher does not update it (its doctor calls it the administrator's from its PR #277,
    planned for 0.2.76; FAA-237)."""
    if platform != "darwin" or not hasattr(os, "getuid") or os.getuid() == 0 or not path.is_absolute():
        return False
    path = _real(path)
    if _real(_home(os.environ if env is None else env)) in path.parents:
        return False
    return _owner_uid(path) == 0


def find_fabric_bin(platform: str = sys.platform, env: Optional[Dict[str, str]] = None) -> Optional[Path]:
    """The first candidate that is a file (only the launcher's folder when `PASSIONCODE_APPLICATIONS` names one). On
    macOS a copy outside the user's home is taken only when it is this user's or root's (an install every user
    shares): another user's copy is skipped (FAA-229, FAA-237)."""
    for candidate in fabric_bin_candidates(platform, env):
        if a_file(candidate) and not another_users_copy(candidate, platform, env):
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


def _windows_pid_alive(pid: int, kernel: Any = None, last_error: Any = None) -> Optional[bool]:
    """pid_alive on Windows, where os.kill(pid, 0) would send CTRL_C_EVENT: the check Node's process.kill(pid, 0) makes
    (libuv's uv_kill), asking OpenProcess for the same access (terminate, query, synchronize; never the limited query an
    elevated process of the same user grants, FAA-323). Refused with ERROR_ACCESS_DENIED (5), another account's or an
    elevated process: None, as Node answers EPERM there (FAA-304); refused otherwise, no process; opened, running
    while its exit code is STILL_ACTIVE and a zero wait times out. `kernel` and `last_error` stand in for kernel32 and
    ctypes.get_last_error in a test."""
    import ctypes
    if kernel is None:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        last_error = ctypes.get_last_error  # type: ignore[attr-defined]
    handle = kernel.OpenProcess(0x0001 | 0x0400 | 0x00100000, False, pid)  # TERMINATE | QUERY_INFORMATION | SYNCHRONIZE
    if not handle:
        return None if last_error() == 5 else False  # ERROR_ACCESS_DENIED: not verified, never called running
    try:
        code = ctypes.c_ulong()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
            return False
        return kernel.WaitForSingleObject(handle, 0) != 0  # WAIT_OBJECT_0: ended, with exit code 259
    finally:
        kernel.CloseHandle(handle)


def pid_alive(pid: int) -> Optional[bool]:
    """True: a process of this OS account runs under `pid`; False: none does. None (falsy): a process of another
    account does (EPERM; on Windows, OpenProcess refused with access denied, FAA-304), as when the id hub.json names
    was reused: not verified, never called running (FAA-254)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return None
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
    live = alive(pid)
    if live is None:  # FAA-254: another account's process under that id, so not this account's Fabric
        return {"state": "not-a-hub", "reason": "hub.json names process %d, which runs under another OS account: "
                "not verified" % pid}
    if not live:
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


#: Claude Code's own variable for its folder, and Fabric Switchboard's for the person's folder a Switchboard home is
#: built from (0.7.14 and later); a home of an earlier Switchboard lies in its data folder (FAA-218).
CLAUDE_CONFIG_ENV = "CLAUDE_CONFIG_DIR"
SWITCHBOARD_SOURCE_ENV = "SWITCHBOARD_CLAUDE_SOURCE_DIR"
SWITCHBOARD_DATA = "ai.passioncode.fabric-switchboard"


def claude_folders(env: Optional[Dict[str, str]] = None) -> Dict[str, Optional[Path]]:
    """The launcher's `claudeFolders` (passioncode lib/launcher.js, PC-129; FAA-218): `read` is where the session's
    Claude Code files are, CLAUDE_CONFIG_DIR when set, else ~/.claude; `write` is where settings, plugins and user MCP
    servers are written, None for Claude Code's default (~/.claude with ~/.claude.json). In a Switchboard home `write`
    is SWITCHBOARD_CLAUDE_SOURCE_DIR when it is absolute, ~/.claude's default for a home of an earlier Switchboard."""
    env = os.environ if env is None else env
    home = _home(env)
    value = env.get(CLAUDE_CONFIG_ENV) or ""
    config = Path(os.path.abspath(value)) if value else None
    named = env.get(SWITCHBOARD_SOURCE_ENV) or ""
    source: Optional[Path] = None
    if config is not None:
        if named and os.path.isabs(named):
            source = Path(os.path.abspath(named))
        elif SWITCHBOARD_DATA in re.split(r"[\\/]", str(config)):
            source = home / ".claude"
    write = (None if source == home / ".claude" else source) if source is not None else config
    return {"read": config or home / ".claude", "write": write}


def claude_json(env: Optional[Dict[str, str]] = None) -> Path:
    """The `.claude.json` Claude Code reads in this environment: inside CLAUDE_CONFIG_DIR when it is set (Claude Code
    2.1.299 reads and `claude mcp add` writes it there, FAA-234), else ~/.claude.json. In a Switchboard home that is the
    home's own, the servers Switchboard carried into it."""
    env = os.environ if env is None else env
    return (claude_folders(env)["read"] if env.get(CLAUDE_CONFIG_ENV) else _home(env)) / ".claude.json"


def claude_registration(cwd: Path, env: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """Claude Code's MCP server `fabric` for this folder: local, then project (.mcp.json), then user scope.
    Only command and args are returned, with the folder a local or project entry was found in; an entry's env is never
    read out."""
    config: Dict[str, Any] = {}
    text = read_small(claude_json(env), CONFIG_CAP)
    if text:
        try:
            loaded = json.loads(text)
            config = loaded if isinstance(loaded, dict) else {}
        except ValueError:
            config = {}
    projects = config.get("projects") if isinstance(config.get("projects"), dict) else {}
    # FAA-235: Claude Code keys a local entry by the git root of the folder it was added in, or that folder outside a
    # checkout, and applies it only there (Claude Code 2.1.299; docs/evidence/runs/2026-11-12-faa-235-local-scope-key.md):
    # one key, never an ancestor's. A hook's cwd moves with the session (a submodule, a worktree under .claude/), while
    # Claude Code keeps the entry of the folder the session started in, which it hands hooks as CLAUDE_PROJECT_DIR:
    # that folder's key is read too (the 0.80.0 seam reading)
    started = (env if env is not None else os.environ).get("CLAUDE_PROJECT_DIR") or ""
    keys = [cwd] + ([Path(started)] if started else [])
    for place in keys:
        folder = checkout_root(place, env) or _ancestors(place)[0]
        project = projects.get(str(folder))
        servers = project.get("mcpServers") if isinstance(project, dict) else None
        found = _stdio_entry(servers.get("fabric")) if isinstance(servers, dict) else None
        if found:
            return dict(found, scope="local", folder=str(folder))
    for folder in _ancestors(cwd):
        text = read_small(folder / ".mcp.json")
        if text:
            try:
                servers = json.loads(text).get("mcpServers")
            except (ValueError, AttributeError):
                servers = None
            found = _stdio_entry(servers.get("fabric")) if isinstance(servers, dict) else None
            if found:
                return dict(found, scope="project", folder=str(folder))
    servers = config.get("mcpServers")
    found = _stdio_entry(servers.get("fabric")) if isinstance(servers, dict) else None
    return dict(found, scope="user") if found else None


_CODEX_FABRIC = re.compile(r'^\s*\[\s*"?mcp_servers"?\s*\.\s*"?fabric"?\s*\]\s*$', re.MULTILINE)
_TOML_HEADER = re.compile(r"^\s*\[", re.MULTILINE)
#: one `command = "..."` line of a table (a basic or literal string), up to the line's end: a lookahead, not `$` (R1)
_TOML_COMMAND = re.compile(r"""^[ \t]*command[ \t]*=[ \t]*("(?:[^"\\\n]|\\.)*"|'[^'\n]*')[ \t]*(?:#[^\n]*)?(?=\r?\n|\Z)""",
                           re.MULTILINE)


def _codex_config(env: Optional[Dict[str, str]] = None) -> str:
    env = os.environ if env is None else env
    codex_home = Path(env.get("CODEX_HOME") or str(_home(env) / ".codex"))
    return read_small(codex_home / "config.toml", CONFIG_CAP) or ""


def codex_registered(env: Optional[Dict[str, str]] = None) -> bool:
    return _CODEX_FABRIC.search(_codex_config(env)) is not None


def codex_command(env: Optional[Dict[str, str]] = None) -> Optional[str]:
    """The `command` of `[mcp_servers.fabric]` in Codex's config.toml (FAA-233), a basic or literal TOML string, or
    None. Read with a pattern, not a TOML parser (Python 3.9 has none): the table runs to the next header."""
    text = _codex_config(env)
    header = _CODEX_FABRIC.search(text)
    if header is None:
        return None
    rest = text[header.end():]
    following = _TOML_HEADER.search(rest)
    found = _TOML_COMMAND.search(rest[:following.start()] if following else rest)
    if not found:
        return None
    value = found.group(1)
    if value.startswith("'"):
        return value[1:-1]
    try:
        decoded = json.loads(value)
    except ValueError:
        return None
    return decoded if isinstance(decoded, str) else None


def kimi_registration(env: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """Kimi Code keeps its MCP servers in ~/.kimi-code/mcp.json (`mcpServers`, Claude's shape): the `fabric` entry's
    command and args, or None."""
    text = read_small(_home(env) / ".kimi-code" / "mcp.json", CONFIG_CAP)
    try:
        servers = json.loads(text).get("mcpServers") if text else None
    except (ValueError, AttributeError, RecursionError):
        return None
    return _stdio_entry(servers.get("fabric")) if isinstance(servers, dict) else None


def kimi_registered(env: Optional[Dict[str, str]] = None) -> bool:
    return kimi_registration(env) is not None


def _json_file(path: Path) -> Any:
    """A small strict-JSON file's value, or None (absent, too large, not JSON: a JSONC comment included)."""
    text = read_small(path, CONFIG_CAP)
    try:
        return json.loads(text) if text else None
    except (ValueError, RecursionError):
        return None


def _member(value: Any, *names: str) -> Any:
    for name in names:
        value = value.get(name) if isinstance(value, dict) else None
    return value


def opencode_registration(cwd: Path, env: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """OpenCode's `mcp.fabric` (FAA-233): the `command` array's first word of a local entry and the file that names it,
    or None. The nearest `opencode.json` from cwd up to its checkout's root wins, then `$OPENCODE_CONFIG`, then
    `$XDG_CONFIG_HOME/opencode/opencode.json` (default `~/.config`), as OpenCode merges them; an entry that turns it
    off (`enabled: false`), a remote one, or a file that is not strict JSON (`.jsonc`) names none."""
    env = os.environ if env is None else env
    root = checkout_root(cwd, env)
    folders = _ancestors(cwd)
    files = [f / "opencode.json" for f in (folders[:folders.index(root) + 1] if root in folders else folders[:1])]
    if env.get("OPENCODE_CONFIG"):
        files.append(Path(env["OPENCODE_CONFIG"]))
    files.append(Path(env.get("XDG_CONFIG_HOME") or str(_home(env) / ".config")) / "opencode" / "opencode.json")
    for path in files:
        entry = _member(_json_file(path), "mcp", "fabric")
        if not isinstance(entry, dict):
            continue
        command = entry.get("command")
        if entry.get("enabled") is False or entry.get("type") == "remote":
            return None
        if isinstance(command, list) and command and isinstance(command[0], str) and command[0]:
            return {"command": command[0], "file": str(path)}
    return None


def pi_registration(cwd: Path, env: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """Pi's `mcpServers.fabric` (FAA-233): its `command` and the file that names it, or None. The project's
    `.pi/mcp.json` (Pi reads it in a project the person trusted) replaces the agent directory's
    (`$PI_CODING_AGENT_DIR`, default `~/.pi/agent`) `mcp.json`; a project entry without `command` overrides only
    `enabled`, so `enabled: false` there names none; a server with a `url` is remote and names none."""
    env = os.environ if env is None else env
    agent = Path(env.get("PI_CODING_AGENT_DIR") or str(_home(env) / ".pi" / "agent"))
    found: Optional[Dict[str, Any]] = None
    for path in (agent / "mcp.json", cwd / ".pi" / "mcp.json"):  # global first, then the project's replaces it
        entry = _member(_json_file(path), "mcpServers", "fabric")
        if not isinstance(entry, dict):
            continue
        if "command" in entry or "url" in entry or "type" in entry:
            command = entry.get("command")
            found = {"command": command, "file": str(path)} if isinstance(command, str) and command and "url" not in entry else None
            if found is not None and entry.get("enabled") is False:
                found = None
        elif found is not None and entry.get("enabled") is False:
            found = None
    return found


def registered_command(host: str, cwd: Path, env: Optional[Dict[str, str]] = None) -> Optional[str]:
    """The command the host runs as `fabric` (FAA-232, FAA-233): Claude Code's entry for this folder, Codex's
    config.toml, Kimi Code's mcp.json, OpenCode's opencode.json, Pi's mcp.json; None when the host registers none, or
    registers it in a file read elsewhere (Hermes' YAML, OpenClaw's)."""
    if host == "claude":
        entry = claude_registration(cwd, env)
        return entry["command"] if entry else None
    if host == "codex":
        return codex_command(env)
    if host == "kimi":
        entry = kimi_registration(env)
        return entry["command"] if entry else None
    if host in ("opencode", "pi"):
        entry = (opencode_registration if host == "opencode" else pi_registration)(cwd, env)
        return entry["command"] if entry else None
    return None


def foreign_command(command: Optional[str], platform: str = sys.platform, env: Optional[Dict[str, str]] = None,
                    lookup: bool = True) -> bool:
    """Whether a registered command runs another user's copy (FAA-229): never one relative to a folder (`./`), and a
    bare name only with `lookup` (a PATH lookup, which status makes and the session hooks do not)."""
    if not command or re.split(r"[\\/]", command)[-1].lower() not in ("fabric-mcp", "fabric-mcp.cmd"):
        return False
    if command.startswith(("./", ".\\")):  # Path() drops a leading ./, which would read as a PATH name
        return False
    path = Path(command)
    if not lookup and not path.is_absolute():
        return False
    return another_users_copy(path, platform, env)


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
        value = env["FABRIC_SERVICES_DIR"]
        if value == "~" or value[:2] in ("~/", "~\\"):  # `~` as the kit, Fabric and Fabric Dashboards expand it (FAA-189)
            home = env.get("HOME") or env.get("USERPROFILE") or str(Path.home())
            return Path(home) / value[2:] if len(value) > 2 else Path(home)
        return Path(value)
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
    """One spelling of a remote: scheme, user, `.git` and case dropped; `git@host:a/b` is `host/a/b`. The kit's rule
    (dashboard_kit and check_service_rules `same_repository`), copied because a session script imports no kit module;
    test_fabric_session.RepositoryRule holds the three equal (FAA-200 (13))."""
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
#: The file in the hooks' own folder (state_root) that says the running Fabric's fabric_session_observe takes
#: `repositories` as {host, owner, name}: a worker writes it from the tool's schema and removes it when the schema stops
#: saying so. Until it exists the Stop hook reads no transcript (FAA-140, seam and product readings 1).
REPOSITORIES_MARK = "observe-takes-repositories"
#: The file in the hooks' own folder that turns the transcript read off (FAA-160): the turn's git facts are still
#: measured. The environment variable FABRIC_SESSION_NO_REPOSITORIES=1 does the same for one environment.
NO_REPOSITORIES_MARK = "no-repositories"
NO_REPOSITORIES_ENV = "FABRIC_SESSION_NO_REPOSITORIES"
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


#: FAA-152: the turn's git branch goes to Fabric (contract DEC-0140 PR-3: shown on this machine's screens, never stored
#: or shared) unless the person turns it off with FABRIC_SESSION_NO_BRANCH set to anything but "" or "0".
NO_BRANCH_ENV = "FABRIC_SESSION_NO_BRANCH"


def branch_off(env: Optional[Dict[str, str]] = None) -> bool:
    return (os.environ if env is None else env).get(NO_BRANCH_ENV, "") not in ("", "0")


def repositories_off(env: Optional[Dict[str, str]] = None) -> bool:
    """Whether the person turned the transcript read off (FAA-160): FABRIC_SESSION_NO_REPOSITORIES set to anything but
    "" or "0", or the file NO_REPOSITORIES_MARK in the hooks' own folder."""
    value = (os.environ if env is None else env).get(NO_REPOSITORIES_ENV, "")
    return value not in ("", "0") or (state_root(env=env) / NO_REPOSITORIES_MARK).exists()


def repositories_wanted(env: Optional[Dict[str, str]] = None) -> bool:
    """Whether the Stop hook reads the transcript for the turn's other repositories (FAA-140): only once a worker
    left the mark, and not when the person turned it off (FAA-160). On Windows too (FAA-175): bash_paths reads a Git
    Bash command's /c/... and C:/... paths as this host's."""
    return not repositories_off(env) and (state_root(env=env) / REPOSITORIES_MARK).exists()


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
    so its folder is never stale), and dispatch records as old (FAA-201); never the folder of the session `keep`.
    Returns how many were removed. Never raises."""
    now = time.time() if now is None else now
    removed = 0
    try:
        folders = list((state_root(env=env) / "sessions").iterdir())
    except OSError:
        folders = []
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
    return removed + prune_dispatch_records(env, now)


def prune_dispatch_records(env: Optional[Dict[str, str]] = None, now: Optional[float] = None) -> int:
    """FAA-201: remove the dispatch records (which session holds a dispatch) older than SESSION_STALE_S, and the
    temporary file of a write a full disk cut short; nothing else. Returns how many. Never raises."""
    now = time.time() if now is None else now
    removed = 0
    try:
        folder = state_root(env=env) / "dispatch"
        records = list(folder.glob("*.json")) + list(folder.glob(".*.tmp"))  # a write a full disk cut short
    except OSError:
        records = []
    for record in records:
        try:
            if now - record.lstat().st_mtime > SESSION_STALE_S:  # the link's own age: a dangling one goes too (FAA-208)
                record.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def take_nudges(directory: Path, name: str = NUDGES_FILE) -> List[str]:
    """The nudges the worker kept in `directory`, taken once: the file is renamed away first, so a merge the worker
    makes meanwhile lands in a new file for the next take: the worker's merge takes the same way, so one of the two holds
    each line at a time. [] on any trouble."""
    path = directory / name
    taken = directory / (".%s.taken.%d" % (name, os.getpid()))
    try:
        os.replace(str(path), str(taken))
    except OSError:
        return []
    try:
        value = json.loads(read_small(taken) or "null")
    except ValueError:
        value = None
    finally:
        try:
            taken.unlink()
        except OSError:
            pass
    return nudge_lines([{"says": line} for line in value] if isinstance(value, list) else [])


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
