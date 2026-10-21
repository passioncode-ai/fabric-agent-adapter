"""working-with-fabric, part of fabric_session.py (FAA-65): the detached worker that delivers a spool through
fabric-mcp --rejoin-only over stdio, with a deadline. Standard library only."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from fabric_session_env import (  # noqa: E402 - the kit (FAA-65)
    BOARD_STATUS_TOOL,
    GIT_TIMEOUT_S,
    HOOK_FEATURE,
    SESSION_ID,
    VERSION,
    WORKER_DEADLINE_S,
    _remove_tree,
    _write_private,
    claude_registration,
    fabric_root,
    locate_hub,
    lock_held,
    log,
    read_small,
)


RUNNER = "claude-code"


OBSERVE_TOOL = "fabric_session_observe"


RELEASE_TOOL = "fabric_work_release"


WAITING_TOOL = "fabric_whoami"


def git_facts(cwd: Path) -> Dict[str, Optional[int]]:
    """HEAD, files that differ from it (untracked included) and lines added/removed. No path, no text."""
    facts: Dict[str, Any] = {"head": None, "filesChanged": None, "linesAdded": None, "linesRemoved": None}

    def git(*args: str) -> Optional[str]:
        try:
            done = subprocess.run(["git", "--no-optional-locks", "-C", str(cwd)] + list(args),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  timeout=GIT_TIMEOUT_S, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.decode("utf-8", "replace") if done.returncode == 0 else None

    head = (git("rev-parse", "--verify", "-q", "HEAD") or "").strip()
    facts["head"] = head if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head) else None
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


class McpStdio:
    """A minimal MCP client over stdio (newline-delimited JSON-RPC) with a hard deadline."""

    def __init__(self, argv: List[str], cwd: str, env: Dict[str, str], deadline: float):
        import threading  # only the worker needs it; the hooks' path stays light
        self.deadline = deadline
        self.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)
        self.messages: List[Dict[str, Any]] = []
        self.cond = threading.Condition()
        self.next_id = 0
        self.tools_changed = False
        threading.Thread(target=self._read, daemon=True).start()

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

    def _send(self, message: Dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

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
                            raise RuntimeError("json-rpc error %s" % (message["error"] or {}).get("code"))
                        return message.get("result") or {}
                left = self.deadline - time.monotonic()
                if left <= 0 or self.proc.poll() is not None:
                    raise TimeoutError("no answer to %s" % method)
                self.cond.wait(min(left, 0.25))

    def wait_tools_changed(self, seconds: float) -> None:
        with self.cond:
            if not self.tools_changed:
                self.cond.wait(max(0.0, min(seconds, self.deadline - time.monotonic())))
            self.tools_changed = False

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()  # fabric-mcp ends on stdin's end
            self.proc.wait(timeout=1.5)
        except Exception:  # noqa: BLE001
            self.proc.kill()
            try:
                self.proc.wait(timeout=1.0)
            except Exception:  # noqa: BLE001
                pass
        if self.proc.stdout:
            self.proc.stdout.close()


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


def _try_lock(lock: Path, directory: Path) -> bool:
    for _ in range(2):
        try:
            fd = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            if lock_held(directory):
                return False
            try:
                lock.unlink()
            except OSError:
                return False
        except OSError:
            return False
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


def deliver(directory: Path, env: Optional[Dict[str, str]] = None, deadline_s: float = WORKER_DEADLINE_S) -> List[str]:
    """Drain one session's spool through fabric-mcp --rejoin-only. Returns the log lines it wrote."""
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
    try:
        entries = sorted(directory.glob("*-*.json"))
        if not entries:
            return said
        first = json.loads(read_small(entries[0]) or "{}")
        cwd = Path(first.get("cwd") or os.getcwd())
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
                entry = json.loads(read_small(path) or "{}")
                event = entry.get("event")
                key = "%s:%s" % (session_id, path.name.split("-", 1)[0])
                if event == "end":
                    ended = True
                    if RELEASE_TOOL in names:
                        result = client.request("tools/call", {"name": RELEASE_TOOL, "arguments": {
                            "claims": "session", "outcome": "let-go",
                            "reason": "the Claude Code session ended (%s)" % entry.get("reason", "other"),
                            "idempotencyKey": key + ":release"}})
                        note("session=%s event=end tool=%s answer=%s" % (session_id[:8], RELEASE_TOOL, _answer_said(result)))
                    else:
                        note("session=%s event=end outcome=degraded reason=%r" % (session_id[:8], "no %s" % RELEASE_TOOL))
                if event in ("turn", "end"):
                    if OBSERVE_TOOL in names:
                        arguments = dict(git_facts(cwd), event=event, runtime=RUNNER, runtimeSessionId=session_id,
                                         observedAt=entry.get("observedAt"), idempotencyKey=key)
                        if event == "end":
                            arguments["reason"] = entry.get("reason", "other")
                        result = client.request("tools/call", {"name": OBSERVE_TOOL, "arguments": arguments})
                        note("session=%s event=%s tool=%s answer=%s" % (session_id[:8], event, OBSERVE_TOOL, _answer_said(result)))
                    elif not (directory / "observe.degraded").exists():
                        note("session=%s event=%s outcome=degraded reason=%r" % (session_id[:8], event, "no %s" % OBSERVE_TOOL))
                        (directory / "observe.degraded").touch()
                path.unlink()
            entries = sorted(directory.glob("*-*.json"))  # turns spooled while this worker ran
        if not ended and BOARD_STATUS_TOOL in names:
            # The board's unread count for the prompt hook (FAA-12a). A count, never a message.
            unread, said_board = board_unread(client.request("tools/call", {"name": BOARD_STATUS_TOOL, "arguments": {}}))
            _write_private(directory / "board.json", json.dumps({
                "unread": unread, "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
            note("session=%s event=board tool=%s %s" % (session_id[:8], BOARD_STATUS_TOOL, said_board))
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


def _wait_for_session_tools(client: McpStdio, deadline: float) -> List[str]:
    """fabric-mcp lists only fabric_whoami until it holds a session; then it says its tools changed."""
    while True:
        tools = client.request("tools/list", {}).get("tools") or []
        names = [t.get("name") for t in tools if isinstance(t, dict) and isinstance(t.get("name"), str)]
        if [n for n in names if n != WAITING_TOOL]:
            return names
        if time.monotonic() >= deadline:
            raise TimeoutError("fabric-mcp did not join the session (not enrolled, or Fabric did not answer)")
        client.wait_tools_changed(0.5)
