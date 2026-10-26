"""working-with-fabric, part of fabric_session.py (FAA-65): the detached worker that delivers a spool through
fabric-mcp --rejoin-only over stdio, with a deadline. Standard library only."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from fabric_session_env import (  # noqa: E402 - the kit (FAA-65)
    BOARD_STATUS_TOOL,
    GIT_TIMEOUT_S,
    HOOK_FEATURE,
    LOCK_STALE_S,
    NO_SESSION_MARK,
    NUDGES_FILE,
    SESSION_ID,
    VERSION,
    WORKER_DEADLINE_S,
    _remove_tree,
    _write_private,
    claude_registration,
    fabric_root,
    locate_hub,
    log,
    nudge_lines,
    take_nudges,
    read_small,
)


RUNNER = "claude-code"


OBSERVE_TOOL = "fabric_session_observe"


RELEASE_TOOL = "fabric_work_release"


WAITING_TOOL = "fabric_whoami"


#: The Stop and SessionEnd hooks measure the turn's facts inside this total, so the hook stays far under its 5 s.
FACTS_BUDGET_S = 1.5


FACT_KEYS = ("head", "filesChanged", "linesAdded", "linesRemoved")


HEAD = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def git_facts(cwd: Path, budget_s: Optional[float] = None) -> Dict[str, Optional[int]]:
    """HEAD, files that differ from it (untracked included) and lines added/removed. No path, no text. With
    `budget_s`, every git call shares that total; a fact git could not give in time is None."""
    facts: Dict[str, Any] = {"head": None, "filesChanged": None, "linesAdded": None, "linesRemoved": None}
    until = None if budget_s is None else time.monotonic() + budget_s

    def git(*args: str) -> Optional[str]:
        timeout = GIT_TIMEOUT_S if until is None else min(GIT_TIMEOUT_S, until - time.monotonic())
        if timeout <= 0:
            return None
        try:
            done = subprocess.run(["git", "--no-optional-locks", "-C", str(cwd)] + list(args),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  timeout=timeout, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.decode("utf-8", "replace") if done.returncode == 0 else None

    head = (git("rev-parse", "--verify", "-q", "HEAD") or "").strip()
    facts["head"] = head if HEAD.fullmatch(head) else None
    status = git("status", "--porcelain=v1", "-z", "--untracked-files=normal")
    if status is not None:
        facts["filesChanged"] = _count_status(status)
    if facts["head"]:
        numstat = git("diff", "--numstat", "HEAD")
        if numstat is not None:
            added = removed = 0
            for line in numstat.splitlines():
                parts = line.split("\t", 2)
                if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                    added, removed = added + int(parts[0]), removed + int(parts[1])
            facts["linesAdded"], facts["linesRemoved"] = added, removed
    return facts


def _count_status(z: str) -> int:
    records, count, skip = z.split("\0"), 0, False
    for record in records:
        if skip:
            skip = False
            continue
        if len(record) < 4:
            continue
        count += 1
        skip = record[0] in "RC"  # a rename or copy carries its old path in the next record
    return count


def stored_facts(entry: Dict[str, Any]) -> Dict[str, Any]:
    """The facts a spool entry carries, as the hook measured them when its turn ended (FAA-68): a head of 40 or 64
    hex digits and non-negative counts, each else None. Nothing is measured at delivery."""
    facts = entry.get("facts") if isinstance(entry.get("facts"), dict) else {}
    head = facts.get("head")
    out: Dict[str, Any] = {"head": head if isinstance(head, str) and HEAD.fullmatch(head) else None}
    for key in FACT_KEYS[1:]:
        value = facts.get(key)
        out[key] = value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2 ** 53 else None
    return out


class JsonRpcError(RuntimeError):
    """An `error` answer to one request: that request failed, the connection did not."""

    def __init__(self, code: Any):
        self.code = code if isinstance(code, int) and not isinstance(code, bool) else None
        super().__init__("json-rpc error %s" % self.code)

    def said(self) -> str:
        return "error:%s" % ("unnamed" if self.code is None else self.code)


#: fabric-mcp --rejoin-only's exit status when no Fabric session holds the runtime id (Fabric 0.3.9, TR-11).
NO_SESSION_EXIT = 3


class NoSessionError(TimeoutError):
    """fabric-mcp --rejoin-only ended with NO_SESSION_EXIT: Fabric holds no session for this id. A TimeoutError, so a
    caller that knows only "no answer" (watch-mail) keeps treating it as one."""


class McpStdio:
    """A minimal MCP client over stdio (newline-delimited JSON-RPC) with a hard deadline."""

    def __init__(self, argv: List[str], cwd: str, env: Dict[str, str], deadline: float):
        import threading  # only the worker needs it; the hooks' path stays light
        self.deadline = deadline
        # Its own process group (FAA-68): a wrapper (npx, a shell script, fabric-mcp.cmd) keeps the server as a
        # grandchild, and only a group kill reaches it.
        options: Dict[str, Any] = {}
        if sys.platform == "win32":
            options["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP
            # CreateProcess applies no PATHEXT: a registration naming `fabric-mcp` means `fabric-mcp.cmd` on PATH.
            import shutil
            found = shutil.which(argv[0], path=env.get("PATH"))
            argv = [found or argv[0]] + list(argv[1:])
        else:
            options["start_new_session"] = True
        self.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, **options)
        self.messages: List[Dict[str, Any]] = []
        self.cond = threading.Condition()
        self.next_id = 0
        self.tools_changed = False
        self.tools: List[Dict[str, Any]] = []  # the last tools/list answer, for the tools' input schemas
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            try:
                message = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue
            with self.cond:
                if isinstance(message, dict) and message.get("method") == "notifications/tools/list_changed":
                    self.tools_changed = True
                elif isinstance(message, dict):
                    self.messages.append(message)
                self.cond.notify_all()
        with self.cond:
            self.cond.notify_all()

    def _ended(self) -> None:
        """The server is gone: raise what its exit status says."""
        if self.proc.returncode == NO_SESSION_EXIT:
            raise NoSessionError("fabric-mcp found no session for this id")
        raise TimeoutError("fabric-mcp ended")

    def _send(self, message: Dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except OSError:  # a server that closed its stdin: say why it exits, never a broken pipe
            # Its exit status may come later than the pipe's end (FAA-97): wait for it up to the deadline.
            try:
                self.proc.wait(timeout=max(0.0, self.deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise TimeoutError("fabric-mcp closed its stdin and did not exit") from None
            self._ended()

    def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    def request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self.next_id += 1
        ident = self.next_id
        self._send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        with self.cond:
            while True:
                for message in self.messages:
                    if message.get("id") == ident:
                        self.messages.remove(message)
                        if "error" in message:
                            error = message["error"]
                            raise JsonRpcError(error.get("code") if isinstance(error, dict) else None)
                        return message.get("result") or {}
                left = self.deadline - time.monotonic()
                if self.proc.poll() is not None:
                    self._ended()
                if left <= 0:
                    raise TimeoutError("no answer to %s" % method)
                self.cond.wait(min(left, 0.25))

    def wait_tools_changed(self, seconds: float) -> None:
        with self.cond:
            if not self.tools_changed:
                self.cond.wait(max(0.0, min(seconds, self.deadline - time.monotonic())))
            self.tools_changed = False

    def close(self) -> None:
        """End the server: its stdin's end first (fabric-mcp exits on it), then its whole process group, so nothing a
        wrapper started keeps the pipe open. Never blocks on stdout while the reader thread holds it (FAA-68)."""
        grace = max(0.2, min(1.5, self.deadline - time.monotonic()))
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.wait(timeout=grace)
        except Exception:  # noqa: BLE001
            pass
        self._kill_group()  # the wrapper may have exited and left its child behind: always
        try:
            self.proc.wait(timeout=1.0)
        except Exception:  # noqa: BLE001
            pass
        self.reader.join(timeout=1.0)
        if self.proc.stdout and not self.reader.is_alive():
            self.proc.stdout.close()  # a reader still blocked keeps it; the process's end closes it

    def _kill_group(self) -> None:
        if sys.platform == "win32":
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2.0, check=False)
            except (OSError, subprocess.SubprocessError):
                pass
            if self.proc.poll() is None:
                self.proc.kill()
            return
        import signal
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)  # the group the server leads (start_new_session)
        except OSError:
            pass


def _take_lock(directory: Path, wait_s: float = 0.0) -> bool:
    """One worker per session. A second one waits for the first (bounded), so an `end` entry spooled while a
    worker was finishing is still delivered."""
    lock = directory / "worker.lock"
    until = time.monotonic() + wait_s
    while True:
        if _try_lock(lock, directory):
            return True
        if time.monotonic() >= until:
            return False
        time.sleep(0.2)


def _identity(st: os.stat_result) -> Tuple[int, int, int, int]:
    return (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size)  # not ctime: the rename itself moves it


def _try_lock(lock: Path, directory: Path, _between: Optional[Callable[[], None]] = None) -> bool:
    """Create the lock; take a stale one (older than LOCK_STALE_S) by renaming it to a name of this worker's own and
    checking that the file renamed is the very one judged stale. A lock another worker made in between is put back
    (FAA-68: no check-then-act). `_between` runs after the judgement and before the rename, for the tests."""
    for _ in range(2):
        try:
            fd = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            pass
        except OSError:
            return False
        try:
            seen = os.lstat(str(lock))
        except FileNotFoundError:
            continue
        except OSError:
            return False
        if time.time() - seen.st_mtime < LOCK_STALE_S:
            return False
        if _between is not None:
            _between()
        taken = directory / (".worker.lock.%d.%s" % (os.getpid(), os.urandom(4).hex()))
        try:
            os.rename(str(lock), str(taken))
        except FileNotFoundError:
            continue  # another worker took it first; try to create ours
        except OSError:
            return False
        try:
            got = os.lstat(str(taken))
        except OSError:
            return False
        # An inode number alone is not identity: Linux hands a freed one straight to the next file, so the lock another
        # worker just made can carry the stale lock's number. Its write time and size are its own.
        if _identity(got) != _identity(seen):
            try:
                os.link(str(taken), str(lock))  # put the live lock back, unless a newer one is there already
            except OSError:
                pass
            try:
                os.unlink(str(taken))
            except OSError:
                pass
            return False
        try:
            os.unlink(str(taken))
        except OSError:
            pass
    return False


def _answer_json(result: Dict[str, Any]) -> Dict[str, Any]:
    """The JSON an answer carries: structuredContent, else its first text block parsed (the board's tools answer
    that way). {} when it carries none."""
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    content = result.get("content")
    if isinstance(content, list) and content and isinstance(content[0], dict) and isinstance(content[0].get("text"), str):
        try:
            value = json.loads(content[0]["text"])
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _answer_said(result: Dict[str, Any]) -> str:
    """What an answer was, in a log-safe word: never its text."""
    if not result.get("isError"):
        return "ok"
    error = _answer_json(result).get("error")
    code = error.get("code") if isinstance(error, dict) and isinstance(error.get("code"), str) else None
    return "refused:%s" % (code if code and re.fullmatch(r"[a-z0-9._-]{1,64}", code) else "unnamed")


def board_unread(result: Dict[str, Any]) -> Tuple[Optional[int], str]:
    """`com.status` (comms-status.schema.json) → (the unread count, a log-safe word). A board that is `unavailable`,
    or an answer without a count, is None: "cannot be read" is never reported as zero. A `degraded` board that still
    gives the reader's count is read (unread counts belong to the reader: the contract's project-comms.md)."""
    said = _answer_said(result)
    if said != "ok":
        return None, "answer=" + said
    doc = _answer_json(result)
    board = doc.get("board") if isinstance(doc.get("board"), dict) else {}
    unread = doc.get("unread")
    state = board.get("state")
    if state not in ("ready", "degraded") or not isinstance(unread, int) or isinstance(unread, bool) or unread < 0:
        return None, "board=unavailable"
    return unread, "answer=ok unread=%d%s" % (unread, " board=degraded" if state == "degraded" else "")


def _read_entry(path: Path) -> Optional[Dict[str, Any]]:
    """One spool entry, or None when it cannot be read as one: not a small regular file, not UTF-8 JSON, not an
    object, or an event other than `turn` and `end`."""
    try:
        entry = json.loads(read_small(path) or "")
    except ValueError:
        return None
    if not isinstance(entry, dict) or entry.get("event") not in ("turn", "end"):
        return None
    return entry


def _entry_cwd(entries: List[Path]) -> Path:
    """The folder the session worked in, from the first entry that names an existing one."""
    for path in entries:
        entry = _read_entry(path)
        cwd = entry.get("cwd") if entry else None
        if isinstance(cwd, str) and cwd and "\0" not in cwd and Path(cwd).is_dir():
            return Path(cwd)
    return Path(os.getcwd())


def deliver(directory: Path, env: Optional[Dict[str, str]] = None, deadline_s: float = WORKER_DEADLINE_S,
            nudges_file: str = NUDGES_FILE) -> List[str]:
    """Drain one session's spool through fabric-mcp --rejoin-only. Returns the log lines it wrote. An entry that
    cannot be read, or a call answered with a JSON-RPC error, is logged and dropped; the rest still goes out (FAA-68).
    Only an answer that never came leaves the spool for the next worker: the session's folder goes only once its end
    entry's calls (the claim release and the end observation) were answered, refused or error-coded."""
    env = dict(os.environ if env is None else env)
    said: List[str] = []

    def note(line: str) -> None:
        said.append(line)
        log(line, env)

    session_id = directory.name
    if not SESSION_ID.fullmatch(session_id) or not directory.is_dir():
        return said
    if not _take_lock(directory, wait_s=deadline_s + 2.0):
        return said
    client: Optional[McpStdio] = None
    ended = False

    def call(event: str, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        assert client is not None
        result: Dict[str, Any] = {}
        try:
            result = client.request("tools/call", {"name": tool, "arguments": arguments})
            answer = _answer_said(result)
        except JsonRpcError as exc:
            answer = exc.said()
        note("session=%s event=%s tool=%s answer=%s" % (session_id[:8], event, tool, answer))
        return result

    try:
        entries = _drop_stale_ends(sorted(directory.glob("*-*.json")), note, session_id)
        if not entries:
            return said
        cwd = _entry_cwd(entries)
        registration = claude_registration(cwd, env)
        hub = locate_hub(fabric_root(env=env))
        if not registration or hub["state"] != "running" or HOOK_FEATURE not in hub.get("features", []):
            note("session=%s outcome=dropped reason=%r" % (session_id[:8], "Fabric or its registration went away"))
            for entry in entries:
                entry.unlink()
            ended = any(e.name.endswith("-end.json") for e in entries)
            return said
        deadline = time.monotonic() + deadline_s
        child_env = dict(env, CLAUDE_CODE_SESSION_ID=session_id)
        argv = [registration["command"]] + registration["args"] + ["--rejoin-only", "--runtime-session-id", session_id]
        client = McpStdio(argv, str(cwd), child_env, deadline)
        client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "fabric-agent-adapter-hooks", "version": VERSION}})
        client.notify("notifications/initialized")
        names = _wait_for_session_tools(client, deadline)
        _write_private(directory / "rejoined", "")
        while entries:
            for path in entries:
                entry = _read_entry(path)
                if entry is None:
                    note("session=%s outcome=dropped reason=%r" % (session_id[:8], "unreadable entry"))
                    path.unlink()
                    continue
                event = entry["event"]
                key = "%s:%s" % (session_id, path.name.split("-", 1)[0])
                reason = entry.get("reason") if isinstance(entry.get("reason"), str) else "other"
                if event == "end":
                    if RELEASE_TOOL in names:
                        release = {"claims": "session", "outcome": "let-go",
                                   "reason": "the Claude Code session ended (%s)" % reason,
                                   "idempotencyKey": key + ":release"}
                        # Fabric 0.3.9 refuses an end observed before the session enrolled (`stale-end`, board thread
                        # 02bf19c5): say when it was observed, where the tool takes the field.
                        if isinstance(entry.get("observedAt"), str) and "observedAt" in _input_fields(client, RELEASE_TOOL):
                            release["observedAt"] = entry["observedAt"]
                        call(event, RELEASE_TOOL, release)
                    else:
                        note("session=%s event=end outcome=degraded reason=%r" % (session_id[:8], "no %s" % RELEASE_TOOL))
                if OBSERVE_TOOL in names:
                    arguments = dict(stored_facts(entry), event=event, runtime=RUNNER, runtimeSessionId=session_id,
                                     observedAt=entry.get("observedAt"), idempotencyKey=key)
                    if event == "end":
                        arguments["reason"] = reason
                    answered = call(event, OBSERVE_TOOL, arguments)
                    if event == "turn" and not answered.get("isError"):
                        _keep_nudges(directory, _answer_json(answered).get("nudges"), note, session_id, nudges_file)
                elif not (directory / "observe.degraded").exists():
                    note("session=%s event=%s outcome=degraded reason=%r" % (session_id[:8], event, "no %s" % OBSERVE_TOOL))
                    (directory / "observe.degraded").touch()
                path.unlink()
                if event == "end":
                    ended = True  # only now: a call that timed out above left this entry for the next worker
            entries = _drop_stale_ends(sorted(directory.glob("*-*.json")), note, session_id)  # spooled meanwhile
        if not ended and BOARD_STATUS_TOOL in names:
            # The board's unread count for the prompt hook (FAA-12a). A count, never a message.
            try:
                unread, said_board = board_unread(client.request("tools/call", {"name": BOARD_STATUS_TOOL, "arguments": {}}))
            except JsonRpcError as exc:
                unread, said_board = None, "answer=" + exc.said()
            _write_private(directory / "board.json", json.dumps({
                "unread": unread, "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
            note("session=%s event=board tool=%s %s" % (session_id[:8], BOARD_STATUS_TOOL, said_board))
    except NoSessionError:
        # Recorded once (02bf19c5, ask 4): nothing in the spool can reach a session Fabric does not hold.
        note("session=%s outcome=no-session reason=%r" % (session_id[:8], "Fabric holds no session for this id"))
        for path in directory.glob("*-*.json"):
            ended = ended or path.name.endswith("-end.json")  # the session's last hook: its folder goes now
            try:
                path.unlink()
            except OSError:
                pass
        try:
            _write_private(directory / NO_SESSION_MARK, "")
        except OSError as exc:  # the worker never raises: without the mark, the next turn tries once more
            note("session=%s outcome=no-session reason=%r" % (session_id[:8], "the mark was not written (%s)" % type(exc).__name__))
    except TimeoutError as exc:
        note("session=%s outcome=unknown reason=%r" % (session_id[:8], str(exc)))
    except Exception as exc:  # noqa: BLE001 — the worker never raises
        note("session=%s outcome=failed reason=%r" % (session_id[:8], type(exc).__name__))
    finally:
        if client is not None:
            client.close()
        try:
            (directory / "worker.lock").unlink()
        except OSError:
            pass
        if ended:
            _remove_tree(directory)
    return said


def _keep_nudges(directory: Path, value: Any, note: Callable[[str], None], session_id: str,
                 name: str = NUDGES_FILE) -> None:
    """FAA-142: add a turn's nudges to the ones the prompt hook has not printed yet (NUDGES_FILE), without repeats and
    at most MAX_NUDGES. The log names how many, never what they say. A file that cannot be written loses this turn's
    nudges: Fabric gives each once, and its nudges also ride on `fabric_work_list` (board ask e2a7bec4). The pending
    file is taken by renaming it away, as a reader takes it, so a prompt in between prints nothing twice."""
    lines = nudge_lines(value)
    if not lines:
        return
    kept = take_nudges(directory, name)
    merged = nudge_lines([{"says": line} for line in kept + lines])
    dropped = len(kept) + len([line for line in lines if line not in kept]) - len(merged)
    try:
        _write_private(directory / name, json.dumps(merged))
        note("session=%s event=turn nudges=%d dropped=%d" % (session_id[:8], len(lines), dropped))
    except OSError as exc:
        note("session=%s event=turn nudges=%d outcome=lost reason=%r" % (session_id[:8], len(merged), type(exc).__name__))


def _drop_stale_ends(entries: List[Path], note: Callable[[str], None], session_id: str) -> List[Path]:
    """The entries left once every end followed by a later turn of the same id is dropped (FAA-83; board thread
    02bf19c5, ask 3): `claude --resume` keeps the id, so such an end belongs to an earlier process of the session, and
    delivering it would release the live session's claims. An end that is the newest entry keeps its retry. Entries
    are named by `time_ns`, so the sorted order is the spooling order."""
    kept: List[Path] = []
    for index, path in enumerate(entries):
        if path.name.endswith("-end.json") and any(p.name.endswith("-turn.json") for p in entries[index + 1:]):
            note("session=%s event=end outcome=dropped reason=%r" % (session_id[:8], "a later turn of the same session"))
            try:
                path.unlink()
            except OSError:
                pass
            continue
        kept.append(path)
    return kept


def _input_fields(client: McpStdio, tool: str) -> List[str]:
    """The property names a listed tool's input schema declares; [] when it declares none."""
    for listed in client.tools:
        if listed.get("name") == tool:
            schema = listed.get("inputSchema")
            props = schema.get("properties") if isinstance(schema, dict) else None
            return [k for k in props if isinstance(k, str)] if isinstance(props, dict) else []
    return []


def _wait_for_session_tools(client: McpStdio, deadline: float) -> List[str]:
    """fabric-mcp lists only fabric_whoami until it holds a session; then it says its tools changed."""
    while True:
        tools = client.request("tools/list", {}).get("tools") or []
        client.tools = [t for t in tools if isinstance(t, dict)]
        names = [t.get("name") for t in tools if isinstance(t, dict) and isinstance(t.get("name"), str)]
        if [n for n in names if n != WAITING_TOOL]:
            return names
        if time.monotonic() >= deadline:
            raise TimeoutError("fabric-mcp did not join the session (not enrolled, or Fabric did not answer)")
        client.wait_tools_changed(0.5)
