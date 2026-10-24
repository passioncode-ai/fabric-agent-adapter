"""working-with-fabric, part of fabric_session.py (FAA-65): watch-mail, one look at the board per interval while an
agent waits on it, with backoff while Fabric is down. Standard library only."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fabric_session_env import (  # noqa: E402 - the kit (FAA-65)
    BOARD_STATUS_TOOL,
    HOOK_FEATURE,
    SESSION_ID,
    UNREAD_LINE,
    VERSION,
    WORKER_DEADLINE_S,
    _write_private,
    claude_registration,
    fabric_launched,
    fabric_root,
    locate_hub,
    rejoin_wait,
    session_dir,
)
from fabric_session_mcp import (  # noqa: E402 - the kit (FAA-65)
    McpStdio,
    NoSessionError,
    _wait_for_session_tools,
    board_unread,
    deliver,
)


WATCH_MIN_INTERVAL_S = 10


WATCH_MAX_BACKOFF_S = 900


def poll_unread(session_id: str, cwd: Path, env: Optional[Dict[str, str]] = None,
                deadline_s: float = WORKER_DEADLINE_S) -> Tuple[str, Any]:
    """One look at the board through `fabric-mcp --rejoin-only`: ("ok", count), ("unavailable", why) when Fabric
    answers but the board cannot be read, ("down", why) when Fabric cannot be reached, ("wait", seconds) when the
    session rejoined within the last minute (the Stop worker's mark, or this one's): the rejoin budget is shared, so
    no fabric-mcp starts then (FAA-68). No fabric-mcp starts unless the running Fabric advertises session-hooks/1
    (the rejoin). A successful rejoin renews the mark in the session's folder when the hooks made one. Turns the hooks
    spooled while the mark held them back are delivered by this look, through the same rejoin (FAA-89)."""
    env = dict(os.environ if env is None else env)
    directory = session_dir(session_id, env)
    left = rejoin_wait(directory)
    if left > 0:
        return "wait", left
    hub = locate_hub(fabric_root(env=env))
    if hub["state"] != "running":
        return "down", "Fabric is not running (%s)" % hub["reason"]
    if HOOK_FEATURE not in hub.get("features", []):
        return "down", "this Fabric does not advertise %s, so nothing can rejoin the session" % HOOK_FEATURE
    registration = claude_registration(cwd, env)
    if not registration:
        return "down", "Claude Code has no MCP server named fabric"
    if directory.is_dir() and any(directory.glob("*-*.json")):
        return _deliver_and_count(directory, env, deadline_s)
    client: Optional[McpStdio] = None
    try:
        deadline = time.monotonic() + deadline_s
        argv = [registration["command"]] + registration["args"] + ["--rejoin-only", "--runtime-session-id", session_id]
        client = McpStdio(argv, str(cwd), dict(env, CLAUDE_CODE_SESSION_ID=session_id), deadline)
        client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "fabric-agent-adapter-watch-mail", "version": VERSION}})
        client.notify("notifications/initialized")
        names = _wait_for_session_tools(client, deadline)
        if directory.is_dir():  # the hooks made it, after their launch check; never made here
            try:
                _write_private(directory / "rejoined", "")
            except OSError:
                pass
        if BOARD_STATUS_TOOL not in names:
            return "unavailable", "this Fabric serves no %s" % BOARD_STATUS_TOOL
        unread, said = board_unread(client.request("tools/call", {"name": BOARD_STATUS_TOOL, "arguments": {}}))
        return ("ok", unread) if unread is not None else ("unavailable", "the project board cannot be read (%s)" % said)
    except NoSessionError:
        return "down", "Fabric holds no session for this id"
    except TimeoutError:
        return "down", "fabric-mcp did not join this session in time"
    except Exception as exc:  # noqa: BLE001 — a poll never raises
        return "down", "fabric-mcp failed (%s)" % type(exc).__name__
    finally:
        if client is not None:
            client.close()


def _deliver_and_count(directory: Path, env: Dict[str, str], deadline_s: float) -> Tuple[str, Any]:
    """FAA-89: the hooks' worker drains the spool through one rejoin and writes the board's unread count beside it;
    this look reads that count instead of rejoining a second time within the minute."""
    started = time.time()
    deliver(directory, env, deadline_s)
    if not directory.is_dir():  # the look delivered the session's end, and the worker removed its folder
        return "down", "the session ended: its spooled turns were delivered"
    board = directory / "board.json"
    try:
        fresh = board.stat().st_mtime >= started - 1
    except OSError:
        fresh = False
    unread = None
    if fresh:
        try:
            data = json.loads(board.read_text(encoding="utf-8"))
            unread = data.get("unread") if isinstance(data, dict) else None
        except (OSError, ValueError):
            unread = None
    if isinstance(unread, int) and not isinstance(unread, bool) and unread >= 0:
        return "ok", unread
    if fresh:
        return "unavailable", "the project board cannot be read"
    left = rejoin_wait(directory)
    if left > 0:
        return "wait", left
    return "down", "the spooled turns could not be delivered now"


def watch_mail(session_id: str, cwd: Path, env: Optional[Dict[str, str]] = None, interval: float = 60, *,
               poll: Optional[Callable[[], Tuple[str, Any]]] = None, out: Callable[[str], None] = print,
               wait: Callable[[float], bool], stop: Callable[[], bool], rng: Callable[[], float]) -> int:
    """Poll the board every `interval` seconds (±20 % jitter; the delay after jitter stays within WATCH_MIN_INTERVAL_S
    and WATCH_MAX_BACKOFF_S) and print ONE line each time the unread count rises. While Fabric is down or the board
    unreadable, say so once and back off, doubling up to WATCH_MAX_BACKOFF_S. A look the shared rejoin mark holds back
    ("wait") changes nothing and waits it out. `wait(seconds)` returns True when it was told to stop."""
    interval = max(float(WATCH_MIN_INTERVAL_S), float(interval))
    poll = poll or (lambda: poll_unread(session_id, cwd, env))
    last, trouble, backoff = 0, None, interval
    while not stop():
        kind, value = poll()
        if kind == "wait":
            delay = float(value)
        elif kind == "ok":
            if value > last:
                out(UNREAD_LINE % value)
            last, trouble, backoff = value, None, interval
            delay = interval
        else:
            backoff = min(backoff * 2, float(WATCH_MAX_BACKOFF_S))
            if trouble != kind:
                out("watch-mail: %s; trying again, backing off up to %d minutes" % (value, WATCH_MAX_BACKOFF_S // 60))
                trouble = kind
            delay = backoff
        jittered = delay if kind == "wait" else delay * (0.8 + 0.4 * rng())
        if wait(min(max(jittered, float(WATCH_MIN_INTERVAL_S)), float(WATCH_MAX_BACKOFF_S))):
            break
    return 0


def watch_mail_cli(argv: Sequence[str], env: Optional[Dict[str, str]] = None) -> int:
    import argparse
    import random
    import signal
    import stat as _stat
    import threading
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(prog="fabric_session.py watch-mail",
                                     description="Print one line each time the project board's unread count rises.")
    parser.add_argument("--interval", type=int, default=60, help="seconds between looks (at least %d)" % WATCH_MIN_INTERVAL_S)
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--session-id", default=None, help="the Claude Code session id (default: CLAUDE_CODE_SESSION_ID)")
    args = parser.parse_args(list(argv))
    session_id = args.session_id or env.get("CLAUDE_CODE_SESSION_ID") or ""
    if not SESSION_ID.fullmatch(session_id):
        sys.stderr.write("watch-mail needs the Claude Code session id: run it from Claude Code (it sets "
                         "CLAUDE_CODE_SESSION_ID) or pass --session-id. Other agents cannot rejoin their session yet.\n")
        return 2
    if fabric_launched(env):
        sys.stderr.write("watch-mail: this session was launched by Fabric; call com.status with your own tools.\n")
        return 2
    cwd = Path(args.cwd).expanduser()
    if not claude_registration(cwd, env):
        sys.stderr.write("watch-mail: Claude Code has no MCP server named fabric for %s; see working-with-fabric.\n" % cwd)
        return 2
    stopped = threading.Event()
    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: stopped.set())
    try:  # a pipe from the watcher that started us: its end is our end. /dev/null or a terminal is not.
        mode = os.fstat(sys.stdin.fileno()).st_mode if sys.stdin else 0
    except (OSError, ValueError):
        mode = 0
    if _stat.S_ISFIFO(mode) or _stat.S_ISSOCK(mode):
        def drain() -> None:
            try:
                while sys.stdin.buffer.read1(4096) if hasattr(sys.stdin.buffer, "read1") else sys.stdin.read(4096):
                    pass
            except (OSError, ValueError):
                pass
            stopped.set()
        threading.Thread(target=drain, daemon=True).start()
    parent = os.getppid()

    def wait(seconds: float) -> bool:
        until = time.monotonic() + seconds
        while not stopped.is_set():
            left = until - time.monotonic()
            if left <= 0:
                return False
            stopped.wait(min(left, 2.0))
            if os.getppid() != parent:  # orphaned: whoever started us is gone
                stopped.set()
        return True

    return watch_mail(session_id, cwd, env, args.interval, out=lambda line: print(line, flush=True),
                      wait=wait, stop=stopped.is_set, rng=random.random)
