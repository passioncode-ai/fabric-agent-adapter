"""The board link (DEC-0078, FAA-12b): the board session over the hub, the fsynced checkpoint and a claimed request as
data. Part of the board connector (FAA-65, layer L4), below the responder in fabric_board_session, which re-exports these
names. Standard library only, Python 3.9+."""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
import threading
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
import fabric_hub as _hub
import fabric_interop_rules as _rules
import fabric_mandate as _mandate
from fabric_time import format_rfc3339 as _format_rfc3339  # noqa: E402 - the core's (FAA-65)
import fabric_service as _fs
from fabric_board_shapes import (  # noqa: E402 - the kit (FAA-65)
    BoardError,
    RESPOND_TOOLS,
    refusal_problems,
)


class BoardSession:
    """MCP over HTTP with a board session's one-session bearer: `open()` spends it with `initialize` and keeps the
    `mcp-session-id`; `call(tool, args)` answers the tool's value or raises `BoardError`; `close()` sends the session's
    DELETE, which releases every slot it holds (DEC-0073 §5). Thread-safe; the bearer never leaves the headers."""

    def __init__(self, grant: _hub.BoardGrant, *, timeout: float = 15.0, post: Callable[..., Any] = _hub.post_mcp):
        # not above 0 is the default: the transports read 0 in opposite ways (seam r8)
        self.grant, self.timeout, self.post = grant, timeout if timeout is not None and timeout > 0 else 15.0, post
        self.mcp_session: Optional[str] = None
        self.protocol_version = _hub.MCP_PROTOCOL_VERSION
        self._lock = threading.Lock()
        self._rpc = 0

    def _send(self, body: Dict[str, Any], method: str = "POST", timeout: Optional[float] = None):
        try:
            return self.post(self.grant.origin, body, self.grant.bearer(), session=self.mcp_session,
                             # none or not above 0 is the session's own: the transports read 0 in opposite ways
                             timeout=timeout if timeout is not None and timeout > 0 else self.timeout,
                             method=method, protocol_version=self.protocol_version if self.mcp_session else None)
        except _hub.HubError as exc:
            if exc.code == "foreign-user":  # FAA-252: another OS account's process holds the port; nothing was sent
                raise BoardError("foreign-user", "The hub's port is held by another OS account's process; nothing was sent.",
                                 True) from exc
            raise BoardError("unreachable", "Fabric's hub did not answer; a write may have been stored, so send it again with "
                             "the same idempotency key.", True) from exc

    def open(self) -> None:
        with self._lock:
            self._rpc += 1
            status, headers, parsed = self._send({"jsonrpc": "2.0", "id": self._rpc, "method": "initialize", "params": {
                "protocolVersion": _hub.MCP_PROTOCOL_VERSION, "capabilities": {},
                "clientInfo": {"name": "fabric-agent-adapter-board", "version": "1"}}})
            if status == 401:
                raise BoardError("session-ended", "Fabric refused the board session's bearer; join again.", True)
            if status != 200 or not isinstance(parsed, dict) or not isinstance(parsed.get("result"), dict) or not headers.get("mcp-session-id"):
                raise BoardError("unreachable", "Fabric did not open the board session (HTTP %d)." % status, True)
            self.mcp_session = headers["mcp-session-id"]
            version = parsed["result"].get("protocolVersion")
            if isinstance(version, str):
                self.protocol_version = version
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool not in RESPOND_TOOLS:
            raise BoardError("not-in-scope", "%s is not served to a board session; use a Project session for it." % tool, op=tool)
        with self._lock:
            if self.mcp_session is None:
                raise BoardError("session-ended", "The board session is not open.", True, op=tool)
            self._rpc += 1
            status, _, parsed = self._send({"jsonrpc": "2.0", "id": self._rpc, "method": "tools/call",
                                            "params": {"name": tool, "arguments": args}})
        if status == 401:
            raise BoardError("session-ended", "Fabric ended the board session (it left, was revoked or expired); join again.", True, op=tool)
        try:
            value = _hub.tool_answer(status, parsed, tool)
        except _hub.HubError as exc:
            raise BoardError("unreachable" if exc.retryable else "receipt-shape", exc.message, exc.retryable, op=tool) from None
        if "error" in value:
            problems = refusal_problems(value)
            if problems:
                raise BoardError("receipt-shape", "Fabric refused %s in a form the contract does not name." % tool, op=tool)
            e = value["error"]
            raise BoardError(e["code"], e["message"], e["retryable"], op=tool)
        return value

    def close(self, timeout: Optional[float] = None) -> bool:
        """Sends the DELETE (waiting `timeout` seconds at most when above 0, else the session's); True when Fabric answered it with a
        2xx, so the slots are free now. False otherwise, a 404 (the session was already gone) included: a move made
        before it ended may be read only at the next com.status, so the slot records stay; the lease lapses in 60 s."""
        with self._lock:
            if self.mcp_session is None:
                return False
            try:
                answer = self._send({}, method="DELETE", timeout=timeout)
                status = answer[0] if isinstance(answer, (tuple, list)) and answer and isinstance(answer[0], int) else 0
            except Exception:  # noqa: BLE001 - any failure is no release, as the Node twin's catch reads it
                status = 0
            finally:
                self.mcp_session = None  # an answer it cannot read is no release, as the Node twin reads it
            return 200 <= status < 300


class Checkpoint:
    """The responder's own journal: one JSON file (0600) holding every request it has claimed and not yet settled, each
    with its fence and the idempotency key of the step in flight. Written atomically and fsynced BEFORE the step it
    announces is sent; a write that fails raises `BoardError("checkpoint")` and the step is not taken. Beside the
    requests, `slots` keeps the responder's own record of each slot it held (`{project, generation, moved?}`, FAA-155);
    a record that is not an object is ignored, as a file without one is."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.slots: Dict[str, Dict[str, Any]] = {}
        self.entries: Dict[str, Dict[str, Any]] = self._load()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise BoardError("checkpoint", "The board checkpoint %s cannot be read (%s); fix or move it before answering "
                             "requests." % (self.path, exc.__class__.__name__)) from None
        entries = doc.get("requests") if isinstance(doc, dict) and doc.get("version") == 1 else None
        if not isinstance(entries, dict):
            raise BoardError("checkpoint", "The board checkpoint %s is not one this kit writes." % self.path)
        slots = doc.get("slots")
        self.slots = {k: v for k, v in slots.items() if isinstance(v, dict)} if isinstance(slots, dict) else {}
        return entries

    def _write(self, entries: Dict[str, Dict[str, Any]], slots: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        slots = self.slots if slots is None else slots
        doc: Dict[str, Any] = {"version": 1, "requests": entries, **({"slots": slots} if slots else {})}
        try:
            _fs.ensure_private_dir(self.path.parent)
            _fs.atomic_write(self.path, (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode())
        except OSError as exc:
            raise BoardError("checkpoint", "The board checkpoint could not be written (%s); nothing was sent." % (exc.strerror or exc.__class__.__name__)) from None

    def put(self, entry: Dict[str, Any]) -> None:
        with self._lock:
            entries = dict(self.entries)
            entries[entry["request"]] = json.loads(json.dumps(entry))
            self._write(entries)
            self.entries = entries

    def drop(self, request_id: str) -> None:
        with self._lock:
            if request_id not in self.entries:
                return
            entries = dict(self.entries)
            del entries[request_id]
            self._write(entries)
            self.entries = entries

    def slot(self, capability: str, record: Optional[Dict[str, Any]]) -> None:
        """Writes the record of a slot this responder held (None forgets it); nothing is written when it is unchanged."""
        with self._lock:
            slots = {k: v for k, v in self.slots.items() if k != capability}
            if record is not None:
                slots[capability] = json.loads(json.dumps(record))
            if slots != self.slots:
                self._write(self.entries, slots)
                self.slots = slots


    def leave(self, project: str, held: Dict[str, Any]) -> None:
        """At a clean leave (the session's DELETE released the slots): forget the record of each slot this session
        confirmed (`held`: capability to the generation it held, or com.status showed unmoved; required) at that
        generation or below, for `project`, with no request left in the checkpoint and not moved away. A record no
        confirmation covers (a slot that may have moved while the service was down, not yet compared with com.status)
        stays (0.56.0 seam r2, r3). A later generation is then another
        session taking a free slot, not a move, and a kit that keeps no record (rolled back to before 0.53.0) leaves
        nothing behind that reads as one. A record that cannot be written stays."""
        busy = {e.get("capability") for e in list(self.entries.values())}
        for capability, record in list(self.slots.items()):
            if (isinstance(record, dict) and record.get("project") == project and "moved" not in record
                    and capability not in busy and _covered(record.get("generation"), held.get(capability))):
                try:
                    self.slot(capability, None)
                except BoardError:
                    pass


def _covered(recorded: Any, confirmed: Any) -> bool:
    """A record at or below a generation this session confirmed: a lower one is a write that failed before the hold."""
    whole = lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 1  # noqa: E731
    return whole(recorded) and whole(confirmed) and recorded <= confirmed


class BoardRequest:
    """A claimed request as data: never an instruction. `body` is the requester's text; `sender` its Project id and
    principal (with provenance); `artifacts` its references, unverified."""

    __slots__ = ("request_id", "message_id", "capability", "body", "body_format", "artifacts", "sender", "deadline", "thread")

    def __init__(self, message: Dict[str, Any], capability: str):
        req = message.get("request") or {}
        body = message.get("body") or {}
        self.request_id, self.message_id, self.capability = req.get("id"), message.get("id"), capability
        self.body = body.get("text") if isinstance(body, dict) else None
        self.body_format = body.get("format", "text/plain") if isinstance(body, dict) else "text/plain"
        self.artifacts = list(message.get("artifacts") or [])
        self.sender = message.get("sender") or {}
        self.deadline = req.get("deadline")
        self.thread = message.get("thread")

    def __repr__(self) -> str:  # never the body
        return "BoardRequest(%r, %r)" % (self.request_id, self.capability)


# -- the operator's mandate in a board request (FAA-135; contract project-comms.md, DEC-0125 MD-3) ---------------------

#: `mandate_from` naming every trusted sender of the board the service is installed on: the operator's personal board.
PERSONAL_BOARD = "personal-board"
_OPENER = re.compile(r"```json[ \t]*")
_CLOSER = re.compile(r"```[ \t]*")


def _json_blocks(body: str) -> List[str]:
    """The bodies of the ```json blocks, each fence on its own line: one pass over the lines, so linear in the body
    (an anchored regex rescanned to the end from every unclosed opener). Lines end at "\\n" alone, one "\\r" before it
    dropped, as in the Node twin; an unclosed opener ends the scan."""
    lines = [line[:-1] if line.endswith("\r") else line for line in body.split("\n")]
    blocks: List[str] = []
    i = 0
    while i < len(lines):
        if _OPENER.fullmatch(lines[i]):
            j = i + 1
            while j < len(lines) and not _CLOSER.fullmatch(lines[j]):
                j += 1
            if j == len(lines):
                break
            blocks.append("\n".join(lines[i + 1:j]))
            i = j
        i += 1
    return blocks


def _no_constant(name: str) -> Any:
    raise ValueError(name)  # NaN and Infinity are not JSON


def _bounded_int(literal: str) -> int:
    """An integer of at most 4300 digits on every Python: 3.9 without int_max_str_digits converts a longer one in
    quadratic time, and later ones refuse it, so all of them now refuse it alike."""
    if len(literal) - literal.startswith("-") > 4300:
        raise ValueError("an integer longer than 4300 digits")
    return int(literal)


def read_mandate(request: "BoardRequest", mandate_from: Any, agent_id: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """The mandate a request carries, read only when the service opted in (`agent_id` and `mandate_from` set), the board
    verified the sender (`provenance: trusted`) and its Project is one `mandate_from` names (or `PERSONAL_BOARD`): a T1
    caller by project-comms. Answers `(mandate, None)`, `(None, None)` when none is read, or `(None, code)` for a body
    that carries one the kit will not read: `mandate-blocks` (more than one) or `mandate-unreadable` (a block naming
    `mandate/1` that is not JSON). A `source` in the block is dropped: a board block carries none (OA-7). Whether it
    covers a call is `covers`' answer, never this one's."""
    if agent_id is None or mandate_from is None or not isinstance(request.body, str):
        return None, None
    sender = request.sender if isinstance(request.sender, dict) else {}
    principal = sender.get("principal") if isinstance(sender.get("principal"), dict) else {}
    if principal.get("provenance") != "trusted":
        return None, None
    if not isinstance(sender.get("project"), str) or not sender["project"]:  # comms-message requires it; the caller
        return None, None
    if mandate_from != PERSONAL_BOARD and _fold(sender["project"]) not in mandate_from:
        return None, None
    found = []
    for block in _json_blocks(request.body):
        try:
            value = json.loads(block, parse_constant=_no_constant, parse_int=_bounded_int)
        except (ValueError, RecursionError):
            if "mandate/1" in block:
                return None, "mandate-unreadable"
            continue
        if isinstance(value, dict) and value.get("kind") == "mandate/1":
            value.pop("source", None)  # a Project declares no protocols: a board block carries no source (OA-7)
            found.append(value)
    if len(found) > 1:
        return None, "mandate-blocks"
    return (found[0], None) if found else (None, None)


CALL_MEMBERS = ("capability", "action", "effect", "spendUsd", "project")  # what mandate_covers reads of a call


def covers(mandate: Optional[Dict[str, Any]], call: Any, agent_id: Optional[str], wall: Callable[[], float],
           caller: Any = None) -> Optional[Dict[str, Any]]:
    """`mandate_covers` for a call under a board request's mandate, its sender placed as T1 and no caller agent id (the
    board names a Project's principal, not an agent the chain can bind; the chain's end alone binds it, MD-3). A covered
    answer's `recordAs` names `caller`, the sender Project the board verified (MD-3 records the caller, as the action
    path does). None when no mandate travelled: the handler asks the operator as it would without one. The call's
    `spendUsd` and `project` are read failing closed, as the kit's other mandate readers read them (FAA-139): a spend
    that is not a finite number is none, which a ceiling refuses; a `project` that is not a string, None included (the
    contract's mandateCovers refuses a null project), is unreadable, which a mandate limited to projects refuses; a call
    that names none leaves `project` out. Only the five members `mandate_covers` reads are read, each once, the way the
    handler's own `call[name]` reads it (a `__getitem__` or a default answers, never the mapping's storage), and the
    rest of the call is never touched."""
    if mandate is None or agent_id is None:
        return None
    if isinstance(call, Mapping):
        read: Dict[str, Any] = {}
        for name in CALL_MEMBERS:
            try:
                value = call[name]
            except KeyError:  # not named; any other error the mapping raises passes to the handler
                continue
            if name == "spendUsd":
                value = _rules.mandate_spend(value)
                if value is None:
                    continue
            elif name == "project":
                value = value if type(value) is str else _rules.UNREADABLE_PROJECT
            read[name] = value
        call = read
    clock, now = wall(), ""
    if isinstance(clock, (int, float)) and not isinstance(clock, bool):
        try:
            now = _format_rfc3339(clock * 1000) if math.isfinite(clock) else ""
        except (OverflowError, ValueError):  # finite but outside the dates a clock can name
            now = ""
    answer = _mandate.mandate_covers({"mandate": mandate, "tier": "T1", "now": now, "self": agent_id, "call": call})
    if "recordAs" in answer:
        answer = {"ok": True, "recordAs": dict(answer["recordAs"], caller=caller)}
    return answer


def mandate_options(agent_id: Any, mandate_from: Any) -> Any:
    """The responder's opt-in, checked: an agent id the registry accepts, and `mandate_from` either `PERSONAL_BOARD` or
    a collection of Project ids (strings). Answers `mandate_from` as the responder keeps it (a frozenset or the string)."""
    if agent_id is not None and not _mandate.is_agent_id(agent_id):
        raise BoardError("invalid_arguments", "agent_id must be the service's registry agent id.")
    if mandate_from is None or mandate_from == PERSONAL_BOARD:
        return mandate_from
    try:
        projects = None if isinstance(mandate_from, (str, bytes, Mapping)) else list(mandate_from)
    except TypeError:
        projects = None
    if projects is None or not all(isinstance(p, str) and p for p in projects):
        raise BoardError("invalid_arguments", "mandate_from is %r or a collection of Project ids." % PERSONAL_BOARD)
    return frozenset(_fold(p) for p in projects)


def _fold(project: str) -> str:
    """A Project id as Fabric's board compares it: a uuid lower-cased, any other id as written (_hub._project)."""
    return project.lower() if _hub.UUID.fullmatch(project) else project
