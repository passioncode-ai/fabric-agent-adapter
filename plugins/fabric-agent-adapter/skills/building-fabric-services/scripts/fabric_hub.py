"""The Fabric hub's door, as a service agent reaches it (fabric-hub/0.1; Fabric ADR-0115 §1, ADR-0149 §4; FAA-12b).

A service that answers a Project's requests on the board (`fabric-project-comms/0.1`) needs three things from Fabric's
hub, and this module does exactly those, standard library only:

1. **Find the hub, every time.** `locate_hub()` re-reads `hub.json` beside Fabric's registry (macOS
   `~/Library/Application Support/ai.passioncode.fabric`, Windows `%LOCALAPPDATA%\\passioncode-fabric`, Linux
   `$XDG_DATA_HOME/passioncode-fabric`) the way Fabric's own `locateHub` does: a small regular file, never a link or a
   FIFO; protocol `fabric-hub/0.1`; the origin exactly `http://127.0.0.1:<port>`; MCP at `/mcp`; a door token file
   inside the registry root; and a `pid` that is alive. The port does not prove who holds it: while Fabric is down any
   program can listen there, so a binding credential is sent only after this check passes, re-done before each send.
2. **Ask once, keep the credential in a file.** `request_board_access()` asks the operator through the door for the
   `board.respond` grant (callee `fabric`, resources `board:<project>/<capability>`); `poll_access()` writes the binding
   credential, shown once, to a 0600 file and returns the status without it. Tokens live in files and headers only:
   never in argv, a URL, a log line or an exception text.
3. **Join the board.** `join_board()` calls `fabric.board.join {projectId}` with the binding credential and returns a
   `BoardGrant`: a one-session bearer (spent by one MCP initialize; `fabric_board.BoardSession` opens it), the session
   id and the capabilities the operator granted. Without a grant the answer is a `HubError` whose `data["ask"]` holds
   the exact `fabric.access.request` arguments to ask with.

When Fabric is down every call raises `HubError` with `retryable=True`; `Backoff` gives the bounded, jittered wait a
loop sleeps before trying again (2 s doubling to 5 minutes), so nothing spins.

fabric-hub/0.1 publishes no hub key, so the door is trusted by the pid check alone. If a later `hub.json` names
`hubKey {kid, x}` and the caller passes an estate record (DEC-0055), `locate_hub(estate=…)` checks it with
`fabric_estate.hub_key_certified` and refuses with DEC-0060's own detail (`kid-not-certified`, `estate-outside-window`,
`estate-rolled-back`, `estate-forked`, `estate-unreadable`, `no-clock`)."""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import random
import re
import stat
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_service as _fs  # noqa: E402 - beside this file: token files, atomic writes

HUB_PROTOCOL = "fabric-hub/0.1"
MCP_PROTOCOL_VERSION = "2025-06-18"
READ_CAP = 64 * 1024
LOOPBACK_ORIGIN = re.compile(r"http://127\.0\.0\.1:([0-9]{4,5})")
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
CAPABILITY = re.compile(r"[a-z][a-z0-9._-]{1,127}")


class HubError(Exception):
    """A typed refusal or fault: `code` (`not-running`, `not-a-hub`, `hub-unavailable`, `credential`, `protocol`,
    `hub-key-refused`, or the hub tool's own code such as `not_authorized`), a one-sentence `message`, `retryable`, and
    `data` (never a secret). `str()` is the sentence."""

    def __init__(self, code: str, message: str, retryable: bool = False, data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code, self.message, self.retryable, self.data = code, message, retryable, data or {}

    def __repr__(self) -> str:
        return "HubError(%r, %r)" % (self.code, self.message)


# --- where Fabric is --------------------------------------------------------------------------------------------

def fabric_root(platform: str = sys.platform, env: Optional[Dict[str, str]] = None) -> Path:
    """Fabric's registry root, where `hub.json` lives (Fabric `agentRegistry.ts#registryDirs`)."""
    env = os.environ if env is None else env
    home = Path(env.get("HOME") or env.get("USERPROFILE") or str(Path.home()))
    if platform == "darwin":
        return home / "Library/Application Support/ai.passioncode.fabric"
    if platform == "win32":
        return Path(env.get("LOCALAPPDATA") or str(home / "AppData" / "Local")) / "passioncode-fabric"
    return Path(env.get("XDG_DATA_HOME") or str(home / ".local/share")) / "passioncode-fabric"


def pid_alive(pid: int) -> bool:
    """Whether a process with this id runs as this user (Fabric `hub.ts#pidAlive`); never signals it."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
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
        return False  # another user's process under a reused id: not this user's Fabric
    except OSError:
        return False
    return True


def _read_small(path: Path) -> Optional[str]:
    """A small regular file's text without following a link or blocking on a FIFO; None when it is not one."""
    info = os.lstat(str(path))
    if not stat.S_ISREG(info.st_mode) or info.st_size > READ_CAP:
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(str(path), flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        data = os.read(fd, READ_CAP + 1)
    finally:
        os.close(fd)
    if len(data) > READ_CAP:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def locate_hub(root: Optional[Path] = None, alive: Callable[[int], bool] = pid_alive, estate: Optional[Dict[str, Any]] = None,
               now: Optional[float] = None) -> Dict[str, Any]:
    """`hub.json` read the way an agent must, every call. Answers `{origin, mcpUrl, doorTokenFile, pid, startedAt,
    features}` or raises `HubError` (`not-running`, retryable; `not-a-hub`). Reads no token. `estate` is
    `{"record": <estate record>, "applied": {"revision", "digest"?} | None}`: with it, a `hubKey` the document names is
    checked by `hub_key_certified` (DEC-0060); fabric-hub/0.1 names none, and then nothing is checked."""
    root = Path(root) if root is not None else fabric_root()
    hub_file = root / "hub.json"
    not_hub = lambda reason: HubError("not-a-hub", "Fabric's hub.json %s." % reason)  # noqa: E731
    try:
        text = _read_small(hub_file)
    except FileNotFoundError:
        raise HubError("not-running", "Fabric is not running: there is no hub.json.", True) from None
    except OSError as exc:
        raise HubError("not-a-hub", "Fabric's hub.json could not be read (%s)." % (exc.strerror or "error"), True) from None
    if text is None:
        raise not_hub("is not a small regular file")
    try:
        doc = json.loads(text)
    except ValueError:
        raise not_hub("is not JSON") from None
    if not isinstance(doc, dict) or doc.get("protocol") != HUB_PROTOCOL:
        raise not_hub("does not speak %s" % HUB_PROTOCOL)
    origin = doc.get("origin") if isinstance(doc.get("origin"), str) else ""
    match = LOOPBACK_ORIGIN.fullmatch(origin)
    if not match or not 1024 <= int(match.group(1)) <= 65535:
        raise not_hub("names an origin that is not the loopback literal")
    if doc.get("mcp") != "/mcp":
        raise not_hub("names another MCP path")
    pid = doc.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise not_hub("names no process")
    token_file = doc.get("doorTokenFile") if isinstance(doc.get("doorTokenFile"), str) else ""
    if not os.path.isabs(token_file) or os.path.realpath(os.path.dirname(token_file)) != os.path.realpath(str(root)):
        raise not_hub("names a door token outside the registry root")
    if not alive(pid):
        raise HubError("not-running", "Fabric is not running: hub.json names process %d, which is not running." % pid, True)
    features = doc.get("features")
    features = [f for f in features if isinstance(f, str)] if isinstance(features, list) else []
    if estate is not None and isinstance(doc.get("hubKey"), dict):
        import fabric_estate  # beside this file
        key = doc["hubKey"]
        # A missing or null applied is "none known", as fabric-hub.mjs reads it (`estate.applied ?? undefined`); only a
        # present one is checked, and hub_key_certified refuses an explicit null of its own (decision D3).
        applied = estate.get("applied")
        verdict = fabric_estate.hub_key_certified(estate.get("record"), key.get("kid"), key.get("x"),
                                                  time.time() if now is None else now,
                                                  fabric_estate._MISSING if applied is None else applied)
        if not verdict.get("certified"):
            raise HubError("hub-key-refused", "The estate record does not certify the hub's key (%s)." % verdict.get("detail"),
                           data={"fault": verdict.get("fault"), "detail": verdict.get("detail")})
    return {"origin": origin, "mcpUrl": origin + "/mcp", "doorTokenFile": token_file, "pid": pid,
            "startedAt": doc.get("startedAt"), "features": features}


def read_door_token(location: Dict[str, Any]) -> str:
    """The door token hub.json names: a 0600 file of this user, never a link (`fabric_service.read_token`), 43
    base64url characters. Raises `HubError` naming the file, never the contents."""
    path = Path(location["doorTokenFile"])
    try:
        token = _fs.read_token(path)
    except FileNotFoundError:
        raise HubError("not-running", "Fabric is starting or stopping: its door token is not there.", True) from None
    except (OSError, _fs.ServiceError) as exc:
        raise HubError("not-a-hub", "The door token file is not one Fabric writes (%s)." % exc) from None
    if not TOKEN.fullmatch(token):
        raise HubError("not-a-hub", "The door token is not one Fabric writes.")
    return token


def read_credential(path: Path) -> str:
    """A binding credential from its 0600 file (`fabric_service.read_token`): 43 base64url characters."""
    try:
        token = _fs.read_token(Path(path))
    except FileNotFoundError:
        raise HubError("credential", "No binding credential at %s: ask for the grant first (request_board_access)." % path) from None
    except (OSError, _fs.ServiceError) as exc:
        raise HubError("credential", str(exc)) from None
    if not TOKEN.fullmatch(token):
        raise HubError("credential", "The file %s does not hold a Fabric binding credential." % path)
    return token


# --- MCP over HTTP, loopback only ---------------------------------------------------------------------------------

def post_mcp(origin: str, body: Dict[str, Any], bearer: str, session: Optional[str] = None, timeout: float = 15.0,
             method: str = "POST", protocol_version: Optional[str] = None) -> Tuple[int, Dict[str, str], Any]:
    """One MCP request to `<origin>/mcp` with a bearer in the header. Only `http://127.0.0.1:<port>` is accepted; no
    proxy is consulted. Answers (status, lower-cased headers, parsed JSON or None); an SSE answer is read to its first
    `data:` line. A refused connection is `HubError("hub-unavailable", retryable=True)`."""
    match = LOOPBACK_ORIGIN.fullmatch(origin)
    if not match:
        raise HubError("not-a-hub", "Only the hub's loopback origin is used.")
    headers = {"Authorization": "Bearer " + bearer, "Content-Type": "application/json",
               "Accept": "application/json, text/event-stream", "Host": "127.0.0.1:%s" % match.group(1)}
    if session:
        headers["mcp-session-id"] = session
    if protocol_version:
        headers["mcp-protocol-version"] = protocol_version
    conn = http.client.HTTPConnection("127.0.0.1", int(match.group(1)), timeout=timeout)
    try:
        conn.request(method, "/mcp", body=None if method == "DELETE" else json.dumps(body).encode(), headers=headers)
        resp = conn.getresponse()
        raw = resp.read(4 * 1024 * 1024)
        got = {k.lower(): v for k, v in resp.getheaders()}
    except (OSError, http.client.HTTPException) as exc:
        raise HubError("hub-unavailable", "Fabric's hub did not answer (%s)." % exc.__class__.__name__, True) from None
    finally:
        conn.close()
    text = raw.decode("utf-8", "replace")
    if "text/event-stream" in got.get("content-type", ""):
        text = next((line[5:].strip() for line in text.splitlines() if line.startswith("data:")), "")
    try:
        parsed = json.loads(text) if text.strip() else None
    except ValueError:
        parsed = None
    return resp.status, got, parsed


def tool_answer(status: int, parsed: Any, tool: str) -> Dict[str, Any]:
    """A `tools/call` answer as a dict: `structuredContent`, else the first text content parsed as JSON. HTTP 401 is
    `credential`, 429/5xx `hub-unavailable` (retryable), a JSON-RPC error or an unreadable answer `protocol`."""
    if status == 401:
        raise HubError("credential", "The hub refused the credential for %s." % tool)
    if status == 429 or status >= 500:
        raise HubError("hub-unavailable", "Fabric's hub could not take %s just now (HTTP %d)." % (tool, status), True)
    if status != 200 or not isinstance(parsed, dict):
        raise HubError("protocol", "Fabric's hub answered %s with HTTP %d and no MCP answer." % (tool, status), True)
    if "error" in parsed:
        message = parsed["error"].get("message") if isinstance(parsed["error"], dict) else None
        raise HubError("protocol", "Fabric refused %s: %s" % (tool, str(message or "an MCP error")[:200]))
    result = parsed.get("result")
    if not isinstance(result, dict):
        raise HubError("protocol", "Fabric's answer to %s has no result." % tool)
    value = result.get("structuredContent")
    if not isinstance(value, dict):
        content = result.get("content")
        text = content[0].get("text") if isinstance(content, list) and content and isinstance(content[0], dict) else None
        try:
            value = json.loads(text) if isinstance(text, str) else None
        except ValueError:
            value = None
    if not isinstance(value, dict):
        raise HubError("protocol", "Fabric's answer to %s is not a JSON object." % tool)
    return value


# --- the client ----------------------------------------------------------------------------------------------------

class BoardGrant:
    """What `fabric.board.join` handed out. The bearer is kept off `repr` and every log; `BoardSession` spends it."""

    __slots__ = ("_bearer", "session_id", "project_id", "capabilities", "origin", "pid")

    def __init__(self, bearer: str, session_id: str, project_id: str, capabilities: Sequence[str], origin: str, pid: int):
        self._bearer = bearer
        self.session_id, self.project_id, self.capabilities = session_id, project_id, list(capabilities)
        self.origin, self.pid = origin, pid

    def bearer(self) -> str:
        return self._bearer

    def __repr__(self) -> str:
        return "BoardGrant(session_id=%r, project_id=%r, capabilities=%r)" % (self.session_id, self.project_id, self.capabilities)


def board_resource(project_id: str, capability: str) -> str:
    """The grant's resource, `board:<project>/<capability>` (ADR-0149 §2)."""
    return "board:%s/%s" % (project_id, capability)


def _project(project_id: str) -> str:
    """A Project id as Fabric's board compares it: a uuid lower-cased (Fabric `boardService.ts`, migration 81); the
    contract's ids are opaque and compared as written (DEC-0077), so nothing else is touched."""
    if not isinstance(project_id, str) or not UUID.fullmatch(project_id):
        raise HubError("protocol", "fabric.board.join takes a Project id that is a uuid.")
    return project_id.lower()


class HubClient:
    """The door client. `root` defaults to Fabric's registry root for this platform; `alive` and `post` are seams for
    tests. Every call re-reads `hub.json` first."""

    def __init__(self, root: Optional[Path] = None, *, alive: Callable[[int], bool] = pid_alive, timeout: float = 15.0,
                 estate: Optional[Dict[str, Any]] = None, post: Callable[..., Tuple[int, Dict[str, str], Any]] = post_mcp):
        self.root = Path(root) if root is not None else fabric_root()
        self.alive, self.timeout, self.estate, self.post = alive, timeout, estate, post
        self._rpc = 0

    def locate(self) -> Dict[str, Any]:
        return locate_hub(self.root, self.alive, self.estate)

    def _call(self, bearer_of: Callable[[Dict[str, Any]], str], tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        location = self.locate()  # the pid check, right before the credential leaves this process
        bearer = bearer_of(location)
        self._rpc += 1
        status, _, parsed = self.post(location["origin"], {"jsonrpc": "2.0", "id": self._rpc, "method": "tools/call",
                                                           "params": {"name": tool, "arguments": args}}, bearer, timeout=self.timeout)
        value = tool_answer(status, parsed, tool)
        error = value.get("error")
        if isinstance(error, dict) and isinstance(error.get("code"), str):
            code = error["code"]
            raise HubError(code, str(error.get("message") or "refused")[:300], code == "hub-unavailable",
                           error.get("data") if isinstance(error.get("data"), dict) else None)
        return value

    def call_door(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        return self._call(read_door_token, tool, args)

    def call_binding(self, tool: str, args: Dict[str, Any], credential_file: Path) -> Dict[str, Any]:
        return self._call(lambda _location: read_credential(credential_file), tool, args)

    # -- the grant -----------------------------------------------------------------------------------------------
    def request_board_access(self, agent_id: str, project_id: str, capabilities: Sequence[str], reason: str) -> Dict[str, Any]:
        """Ask the operator, once, to let `agent_id` answer `capabilities` for `project_id` (`fabric.access.request`,
        callee `fabric`, capability `board.respond`). Answers `{requestId, status, expiresAt, pollSecret?, note}`; keep the
        pollSecret in memory or a 0600 file — it is the only way to read the answer through the door."""
        project = _project(project_id)
        caps = list(capabilities)
        if not caps or any(not isinstance(c, str) or not CAPABILITY.fullmatch(c) for c in caps):
            raise HubError("protocol", "Name at least one capability, each [a-z][a-z0-9._-]{1,127}.")
        return self.call_door("fabric.access.request", {"agentId": agent_id, "callee": "fabric", "capabilities": ["board.respond"],
                                                        "resources": [board_resource(project, c) for c in caps], "reason": reason})

    def poll_access(self, request_id: str, poll_secret: str, credential_file: Path) -> Dict[str, Any]:
        """Read the request through the door. On Allow the first read carries the credential, once: it is written to
        `credential_file` (0600, atomic, fsync) and removed from the answer, which says `credentialSaved: true`."""
        answer = self.call_door("fabric.access.status", {"requestId": request_id, "pollSecret": poll_secret})
        credential = answer.pop("credential", None)
        if isinstance(credential, str):
            if not TOKEN.fullmatch(credential):
                raise HubError("protocol", "Fabric handed out a credential this kit does not recognise; nothing was saved.")
            _fs.ensure_private_dir(Path(credential_file).parent)
            _fs.atomic_write(Path(credential_file), credential.encode(), 0o600)
            answer["credentialSaved"] = True
        return answer

    def join_board(self, project_id: str, credential_file: Path) -> BoardGrant:
        """`fabric.board.join {projectId}`: a board session for one Project. Refusal `not_authorized` carries
        `data["ask"]`, the `fabric.access.request` arguments to ask with (capabilities to be filled by the caller)."""
        project = _project(project_id)
        try:
            answer = self.call_binding("fabric.board.join", {"projectId": project}, credential_file)
        except HubError as exc:
            if exc.code in ("not_authorized", "not-authorized"):
                raise HubError("not_authorized", "The operator has not let this agent answer requests for that Project: ask "
                               "with fabric.access.request (callee fabric, capability board.respond, resource "
                               "board:<project>/<capability>).", data={"ask": {"callee": "fabric", "capabilities": ["board.respond"],
                                                                                  "resources": [board_resource(project, "<capability>")]}}) from None
            raise
        session = answer.get("session")
        if not isinstance(session, dict) or not isinstance(session.get("bearer"), str) or not isinstance(session.get("sessionId"), str):
            raise HubError("protocol", "fabric.board.join answered no board session.")
        if session.get("projectId") != project:
            raise HubError("protocol", "fabric.board.join answered a session for another Project.")
        caps = session.get("capabilities")
        caps = [c for c in caps if isinstance(c, str)] if isinstance(caps, list) else []
        location = self.locate()
        return BoardGrant(session["bearer"], session["sessionId"], project, caps, location["origin"], location["pid"])


class Backoff:
    """Bounded exponential backoff with jitter: `first` seconds doubling to `cap`, each wait ±`jitter` of itself and
    never under `floor`. `next()` is the wait to sleep; `reset()` after a success."""

    def __init__(self, first: float = 2.0, cap: float = 300.0, jitter: float = 0.2, floor: float = 1.0,
                 rand: Callable[[], float] = random.random):
        self.first, self.cap, self.jitter, self.floor, self.rand = first, cap, jitter, floor, rand
        self.attempt = 0

    def next(self) -> float:
        base = min(self.cap, self.first * (2 ** min(self.attempt, 32)))
        self.attempt += 1
        wait = base * (1 + self.jitter * (2 * self.rand() - 1))
        return max(self.floor, min(self.cap, wait))

    def reset(self) -> None:
        self.attempt = 0
