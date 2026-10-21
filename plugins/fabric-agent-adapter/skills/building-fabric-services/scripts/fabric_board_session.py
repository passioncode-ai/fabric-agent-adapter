"""The board responder (DEC-0078, FAA-12b): a board session over the hub, the fsynced checkpoint, the request a handler
sees and the responder loop (enroll, claim, accept the exact digest, effect, progress, complete; stop when fenced).
Part of the board connector (FAA-65, layer L4)."""
from __future__ import annotations

import json
import random
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
import fabric_hub as _hub
import fabric_service as _fs
from fabric_board_shapes import (  # noqa: E402 - the kit (FAA-65)
    BoardError,
    REQUEST_STATES,
    RESPOND_TOOLS,
    SUMMARY_MAX,
    Stopped,
    _CAPABILITY,
    _is_int,
    outcome_problems,
    receipt_problems,
    refusal_problems,
)


RENEW_SECONDS = 20.0


POLL_SECONDS = 15.0


POLL_JITTER_SECONDS = 5.0


DRAIN_SECONDS = 10.0


EVENT_SCHEMA = "urn:fabric:schema:board-responder-event:1"


#: On these the attempt is no longer ours: stop acting at once (C4).
STOP_CODES = frozenset(["fenced", "lease_expired", "authority_changed"])


TERMINAL = frozenset(["completed", "failed_known", "cancelled", "expired"])


#: How long a held slot waits before it asks again: doubling from the poll interval, never past this.
HOLD_RETRY_MAX_SECONDS = 900.0


class BoardSession:
    """MCP over HTTP with a board session's one-session bearer: `open()` spends it with `initialize` and keeps the
    `mcp-session-id`; `call(tool, args)` answers the tool's value or raises `BoardError`; `close()` sends the session's
    DELETE, which releases every slot it holds (DEC-0073 §5). Thread-safe; the bearer never leaves the headers."""

    def __init__(self, grant: _hub.BoardGrant, *, timeout: float = 15.0, post: Callable[..., Any] = _hub.post_mcp):
        self.grant, self.timeout, self.post = grant, timeout, post
        self.mcp_session: Optional[str] = None
        self.protocol_version = _hub.MCP_PROTOCOL_VERSION
        self._lock = threading.Lock()
        self._rpc = 0

    def _send(self, body: Dict[str, Any], method: str = "POST"):
        try:
            return self.post(self.grant.origin, body, self.grant.bearer(), session=self.mcp_session, timeout=self.timeout,
                             method=method, protocol_version=self.protocol_version if self.mcp_session else None)
        except _hub.HubError as exc:
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

    def close(self) -> None:
        with self._lock:
            if self.mcp_session is None:
                return
            try:
                self._send({}, method="DELETE")
            except BoardError:
                pass  # best effort: the lease lapses in 60 s anyway
            self.mcp_session = None


class Checkpoint:
    """The responder's own journal: one JSON file (0600) holding every request it has claimed and not yet settled, each
    with its fence and the idempotency key of the step in flight. Written atomically and fsynced BEFORE the step it
    announces is sent; a write that fails raises `BoardError("checkpoint")` and the step is not taken."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
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
        return entries

    def _write(self, entries: Dict[str, Dict[str, Any]]) -> None:
        try:
            _fs.ensure_private_dir(self.path.parent)
            _fs.atomic_write(self.path, (json.dumps({"version": 1, "requests": entries}, indent=1, sort_keys=True) + "\n").encode())
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


class WorkContext:
    """What a handler may do while it works: `progress(note)` posts a note on the request's thread (and renews the
    lease); `begin_effect(summary)` must be called — and must return — before the handler spends or acts outside
    the service; `stopped` is set when the attempt is no longer this responder's. Both raise `Stopped` then."""

    def __init__(self, responder: "Responder", entry: Dict[str, Any]):
        self._responder, self._entry = responder, entry
        self.stopped = threading.Event()

    def progress(self, note: Optional[str] = None) -> None:
        if self.stopped.is_set():
            raise Stopped()
        self._responder._progress(self._entry, note, self)

    def begin_effect(self, summary: Optional[str] = None) -> None:
        if self.stopped.is_set():
            raise Stopped()
        self._responder._effect_begin(self._entry, summary, self)


class _Work:
    def __init__(self, entry: Dict[str, Any], request: BoardRequest, ctx: WorkContext):
        self.entry, self.request, self.ctx = entry, request, ctx
        self.done = threading.Event()
        self.outcome: Optional[Dict[str, Any]] = None
        self.failure: Optional[BaseException] = None
        self.renewed_at: Optional[float] = None


Handler = Callable[[BoardRequest, WorkContext], Dict[str, Any]]


class Responder:
    """One service's responder for one Project and one or more capabilities, one request at a time.

    `handler(request, ctx)` returns the outcome `{state, observed?, summary?, evidence?, reply?}`; `admit(request)`
    is the service's input gate (None admits; a sentence refuses); `observe(entry)` reads the world after a restart and
    answers an observed outcome or None, for `com.reconcile`. `emit(kind, level, text, **extra)` receives the
    responder's events (`JsonlEventLog.append` fits). `run(stop)` loops until `stop` is set; `step()` is one tick and
    answers the seconds until the next."""

    def __init__(self, *, hub: _hub.HubClient, project_id: str, capabilities: Sequence[str], credential_file: Path,
                 checkpoint_file: Path, handler: Handler, admit: Callable[[BoardRequest], Optional[str]],
                 observe: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None,
                 emit: Optional[Callable[..., Any]] = None, service: str = "service",
                 now: Callable[[], float] = time.monotonic, rand: Callable[[], float] = random.random,
                 spawn: Optional[Callable[[Callable[[], None]], Any]] = None, session_factory: Optional[Callable[..., BoardSession]] = None):
        if admit is None or handler is None:
            raise BoardError("invalid_arguments", "A responder needs the service's own input gate (admit) and a handler.")
        caps = list(capabilities)
        if not caps or any(not isinstance(c, str) or not _CAPABILITY.fullmatch(c) for c in caps) or len(set(caps)) != len(caps):
            raise BoardError("invalid_arguments", "Name each capability once, [a-z][a-z0-9._-]{1,127}.")
        self.hub, self.project = hub, _hub._project(project_id)
        self.capabilities = caps
        self.credential_file, self.handler, self.admit, self.observe = Path(credential_file), handler, admit, observe
        self.checkpoint = Checkpoint(Path(checkpoint_file))
        self._emit_to, self.service, self.now, self.rand = emit, re.sub(r"[^A-Za-z0-9._-]", "-", service)[:40] or "service", now, rand
        self.spawn = spawn or (lambda fn: threading.Thread(target=fn, name="board-handler", daemon=True).start())
        self.session_factory = session_factory or (lambda grant: BoardSession(grant))
        self.backoff = _hub.Backoff(rand=rand)
        self.session: Optional[BoardSession] = None
        self.epoch: Optional[int] = None
        self.slots: Dict[str, Dict[str, Any]] = {}
        self.current: Optional[_Work] = None
        self.state = "idle"
        self.wait_until = 0.0
        self.stopping = False
        self.claim_keys: Dict[str, str] = {}
        self._said: Dict[str, str] = {}
        self._rr = 0
        #: The first pause under an operator's hold (DEC-0079); it doubles to HOLD_RETRY_MAX_SECONDS.
        self.hold_delay = POLL_SECONDS
        self._on_hold: set = set()

    # -- events -------------------------------------------------------------------------------------------------
    def _emit(self, kind: str, level: str, text: str, notify: bool = False, episode: Optional[str] = None, **value: Any) -> None:
        if episode is not None:
            if self._said.get(kind) == episode:
                return  # once per episode
            self._said[kind] = episode
        data = {"schema": EVENT_SCHEMA, "value": {k: v for k, v in value.items() if v is not None}}
        problems = _fs.feed_data_problems(data)
        if problems:  # FAC-SEM-101: never a credential in data; drop the data, keep the sentence
            data = None
        if self._emit_to is None:
            return
        try:
            self._emit_to(kind, level, text, notify=notify, **({"data": data} if data else {}))
        except Exception:  # noqa: BLE001 - an event that cannot be written never stops the responder
            pass

    # -- keys and fences ------------------------------------------------------------------------------------------
    def _key(self, op: str) -> str:
        return "%s.%s.%s" % (self.service, op, secrets.token_hex(8))

    def _idem(self, key: str) -> Dict[str, Any]:
        if self.epoch is None:
            raise BoardError("no-epoch", "Fabric told this board session no idempotency epoch.", op="com.status")
        return {"epoch": self.epoch, "key": key}

    def _fence(self, entry: Dict[str, Any], key: str) -> Dict[str, Any]:
        return {"request": entry["request"], "generation": entry["generation"], "attempt": entry["attempt"],
                "digest": entry["digest"], "expectedRevision": entry["revision"], "idempotency": self._idem(key)}

    def _receipt(self, op: str, answer: Dict[str, Any]) -> Dict[str, Any]:
        problems = receipt_problems(answer, op)
        if problems:
            raise BoardError("receipt-shape", "Fabric answered %s with a receipt the contract does not name (%s)." % (op, problems[0]), op=op)
        return answer

    def _call(self, op: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if self.session is None:
            raise BoardError("session-ended", "No board session.", True, op=op)
        return self.session.call(op, args)

    # -- connecting --------------------------------------------------------------------------------------------
    def _status(self) -> Dict[str, Any]:
        status = self._call("com.status", {})
        verdict = _fs.negotiate_revision(status.get("protocol"), _fs.accepted_revisions("fabric-project-comms"))
        if "error" in verdict:
            raise BoardError("schema-unsupported", "Fabric's board speaks %s, which this kit does not read." % status.get("protocol"),
                             data=verdict["error"]["data"])
        if (status.get("board") or {}).get("state") == "unavailable":
            raise BoardError("not_available", "Fabric's board cannot be read right now.", True, op="com.status")
        epoch = (status.get("idempotency") or {}).get("epoch")
        if not _is_int(epoch, 1):
            # Fail closed: a guessed epoch would store keys under a namespace the board never named.
            raise BoardError("no-epoch", "Fabric told this board session no idempotency epoch (Fabric before its board-session "
                             "fix); the responder waits rather than guess one.", op="com.status")
        self.epoch = epoch
        return status

    def _connect(self) -> None:
        self.state = "connecting"
        grant = self.hub.join_board(self.project, self.credential_file)
        missing = [c for c in self.capabilities if c not in grant.capabilities]
        session = self.session_factory(grant)
        session.open()
        self.session = session
        status = self._status()
        if missing:
            self._emit("board.access.needed", "warn", "The operator has not let this service answer %s on this Project; ask in "
                       "Fabric (Agents & access)." % ", ".join(missing), notify=True, episode=",".join(missing),
                       capabilities=missing)
        self.slots = {}
        self._recover(status, [c for c in self.capabilities if c in grant.capabilities])
        self.state = "ready"
        for kind in ("board.down", "board.blocked") + (() if missing else ("board.access.needed",)):
            self._said.pop(kind, None)

    def _enroll(self, capability: str) -> None:
        args = {"idempotency": self._idem(self._key("enroll")), "capability": capability}
        try:
            receipt = self._receipt("com.enroll", self._call("com.enroll", args))
        except BoardError as exc:
            if exc.code == "held":
                self._pause(capability)
                return
            if exc.code == "fenced":
                self.slots[capability] = {"state": "contested", "renewed_at": self.now()}
                self._emit("board.slot.contested", "warn", "Another responder holds the %s slot on this Project; this service "
                           "waits for it to lapse and never takes it over by itself." % capability, notify=True,
                           episode=capability, capability=capability)
                return
            raise
        self.slots[capability] = {"state": "held", "generation": receipt["slot"]["generation"], "renewed_at": self.now()}
        self._said.pop("board.slot.contested", None)
        self._lifted(capability)

    def _pause(self, capability: str) -> None:
        """The operator holds this slot or its Project (DEC-0079): ask again later, the pause doubling each time, and
        never act around the hold. Accepted work in progress continues; only new work waits."""
        slot = self.slots.get(capability) or {}
        pauses = slot.get("pauses", 0) + 1 if slot.get("state") == "paused" else 1
        wait = min(HOLD_RETRY_MAX_SECONDS, self.hold_delay * 2 ** (pauses - 1))
        self.slots[capability] = {"state": "paused", "pauses": pauses, "retry_at": self.now() + wait, "renewed_at": self.now()}
        if capability not in self._on_hold:  # once per hold, per capability
            self._on_hold.add(capability)
            self._emit("board.slot.held", "info", "The operator holds new work for %s on this Project; the service waits and "
                       "asks again later. Work already accepted continues." % capability, capability=capability)

    def _lifted(self, capability: str) -> None:
        if capability in self._on_hold:
            self._on_hold.discard(capability)
            self._emit("board.slot.released", "info", "The operator's hold on %s was lifted; the service takes new work "
                       "again." % capability, capability=capability)

    # -- restart: reconcile and transfer -------------------------------------------------------------------------
    def _read_state(self, entry: Dict[str, Any]) -> Optional[str]:
        message = self._call("com.get", {"message": entry["message"]})
        req = message.get("request") if isinstance(message, dict) else None
        if not isinstance(req, dict) or req.get("id") != entry["request"] or req.get("state") not in REQUEST_STATES:
            return None
        entry["revision"] = req.get("revision", entry.get("revision"))
        return req["state"]

    def _recover(self, status: Dict[str, Any], capabilities: List[str]) -> None:
        transfer: Dict[str, List[Dict[str, Any]]] = {}
        reconcile: List[Dict[str, Any]] = []
        for entry in list(self.checkpoint.entries.values()):
            if entry.get("capability") not in capabilities:
                continue
            try:
                state = self._read_state(entry)
            except BoardError as exc:
                if exc.code in ("not_authorized",):
                    self.checkpoint.drop(entry["request"])
                    continue
                raise
            if state is None or state in TERMINAL or state in ("queued", "claimed"):
                self.checkpoint.drop(entry["request"])  # settled, or back in the queue for whoever claims next
            elif state == "accepted":
                transfer.setdefault(entry["capability"], []).append(entry)
            else:  # in_progress (lost result once a new generation holds the slot) or outcome_unknown
                reconcile.append(entry)
        responders = [r for r in status.get("responders") or [] if isinstance(r, dict)]
        generations = {r.get("capability"): r.get("generation", 0) for r in responders}
        on_hold = {r.get("capability") for r in responders if r.get("held") is True}  # DEC-0079
        for capability in capabilities:
            held = transfer.get(capability)
            if capability in on_hold:
                for entry in held or []:
                    entry["step"] = "lapsed"  # taken back by a transfer once the hold is lifted
                    self.checkpoint.put(entry)
                self._pause(capability)
            elif held:
                self._replace(capability, held, generations.get(capability, 0))
            else:
                self._enroll(capability)
        for entry in reconcile:
            if self.slots.get(entry["capability"], {}).get("state") == "held":
                self._reconcile(entry)

    def _replace(self, capability: str, entries: List[Dict[str, Any]], generation: Any) -> None:
        if not _is_int(generation, 0):
            generation = 0
        args = {"idempotency": self._idem(self._key("replace")), "capability": capability, "expectedGeneration": generation,
                "transfer": {"requests": [e["request"] for e in entries][:64],
                             "checkpoint": {"summary": "Resumed by the same service after a restart; no effect had begun."}}}
        try:
            receipt = self._receipt("com.responder_replace", self._call("com.responder_replace", args))
        except BoardError as exc:
            if exc.code != "held":
                raise
            for entry in entries:
                entry["step"] = "lapsed"  # nothing moved: taken back by a transfer once the hold is lifted
                self.checkpoint.put(entry)
            self._pause(capability)
            return
        self.slots[capability] = {"state": "held", "generation": receipt["slot"]["generation"], "renewed_at": self.now()}
        self._lifted(capability)
        moved = {item["request"]: item for item in receipt.get("transferred") or []}
        for entry in entries:
            item = moved.get(entry["request"])
            if item is None:
                # A board pinned before DEC-0078 hands back no attempt. Never claim it back: it stays held, and the next
                # start (or the operator) decides.
                entry["step"] = "held"
                self.checkpoint.put(entry)
                self._emit("board.request.held", "warn", "An accepted request could not be resumed: this Fabric does not hand "
                           "back a transferred attempt (DEC-0078). It stays held; nothing was done.", notify=True,
                           episode=entry["request"], request=entry["request"], capability=capability)
                continue
            entry.update(generation=item["attempt"]["generation"], attempt=item["attempt"]["id"], digest=item["attempt"]["digest"],
                         revision=item["revision"], step="accepted" if entry.get("step") in ("accepting", "held", "lapsed") else entry.get("step"))
            self.checkpoint.put(entry)
            if self.current is None:
                self._resume(entry)

    def _reconcile(self, entry: Dict[str, Any]) -> None:
        state = self._read_state(entry)
        if state != "outcome_unknown":
            if state in TERMINAL or state in ("queued", "claimed"):
                self.checkpoint.drop(entry["request"])
            return
        outcome = entry.get("outcome") if isinstance(entry.get("outcome"), dict) and entry["outcome"].get("observed") is True else None
        if outcome is None and self.observe is not None:
            try:
                outcome = self.observe(dict(entry))
            except Exception:  # noqa: BLE001 - an observation that failed is no observation
                outcome = None
        if not outcome or outcome_problems(dict(outcome, observed=True), True) or outcome.get("observed") is not True:
            entry["step"] = "unknown"
            self.checkpoint.put(entry)
            self._emit("board.reconcile.needed", "warn", "A request's outcome is unknown: the work may have happened. It stays "
                       "unknown until this service observes what happened.", notify=True, episode=entry["request"],
                       request=entry["request"], capability=entry["capability"])
            return
        clean = {k: outcome[k] for k in ("state", "summary", "evidence") if k in outcome}
        clean["observed"] = True
        args = {"idempotency": self._idem(entry.get("keys", {}).get("reconcile") or self._key("reconcile")), "request": entry["request"],
                "digest": entry["digest"], "outcome": clean}
        entry.setdefault("keys", {})["reconcile"] = args["idempotency"]["key"]
        entry["step"] = "reconciling"
        self.checkpoint.put(entry)
        self._receipt("com.reconcile", self._call("com.reconcile", args))
        self.checkpoint.drop(entry["request"])
        self._emit("board.request.reconciled", "info", "A request whose outcome was unknown was settled from what this service "
                   "observed.", request=entry["request"], capability=entry["capability"], state=clean["state"])

    # -- one tick ------------------------------------------------------------------------------------------------
    def interval(self) -> float:
        return max(1.0, POLL_SECONDS + POLL_JITTER_SECONDS * (2 * self.rand() - 1))

    def step(self) -> float:
        """One tick. Answers the seconds to wait before the next."""
        if self.stopping:
            return DRAIN_SECONDS
        now = self.now()
        if now < self.wait_until:
            return self.wait_until - now
        try:
            if self.session is None:
                self._connect()
            self._tick()
            self.backoff.reset()
            return self.interval()
        except (BoardError, _hub.HubError) as exc:
            return self._fault(exc)

    def _fault(self, exc: Exception) -> float:
        code = getattr(exc, "code", "unreachable")
        wait = self.backoff.next()
        self.wait_until = self.now() + wait
        if code in ("not_authorized", "authority_changed", "credential"):
            self.state = "not-authorized"
            self._drop_session()
            self._emit("board.access.needed", "warn", "This service may not answer requests for this Project: the operator "
                       "has to allow it in Fabric (Agents & access). Nothing is claimed until then.", notify=True,
                       episode="access", reason=code)
        elif code == "held":
            self.state = "paused"
            self._emit("board.held", "info", "The operator holds new work on this Project; the responder waits and asks again "
                       "with a growing pause.", episode="held", reason=code)
        elif code in ("no-epoch", "schema-unsupported", "checkpoint", "receipt-shape"):
            self.state = "down"
            self._drop_session()
            self._emit("board.blocked", "error", "The responder stopped answering requests: %s" % getattr(exc, "message", str(exc)),
                       notify=True, episode=code, reason=code)
        else:
            self.state = "down"
            if code in ("session-ended", "unreachable", "not-running", "not-a-hub", "hub-unavailable", "protocol"):
                self._drop_session()
            self._emit("board.down", "warn", "Fabric's board cannot be reached; the responder tries again with a growing pause.",
                       episode="down", reason=code)
        return wait

    def _drop_session(self) -> None:
        work, self.current = self.current, None
        if work is not None:
            entry = work.entry
            if work.done.is_set() and work.failure is None and not outcome_problems(work.outcome, bool(entry.get("effect"))):
                # The answer is known: keep it, so the next session sends it instead of doing the work again.
                entry["outcome"] = dict(work.outcome, observed=work.outcome.get("observed", not entry.get("effect")))
                try:
                    self.checkpoint.put(entry)
                except BoardError:
                    pass
            else:
                work.ctx.stopped.set()  # the lease lapses; acting on would outlive the attempt
        session, self.session = self.session, None
        if session is not None:
            session.close()

    def _tick(self) -> None:
        work = self.current
        if work is not None:
            if work.done.is_set():
                self._finish(work)
            else:
                self._renew(work)
        held_by_work = work.entry["capability"] if work is not None and self.current is not None else None
        for capability, slot in list(self.slots.items()):
            if slot.get("state") == "paused":
                if capability != held_by_work and self.now() >= slot.get("retry_at", 0.0):
                    self._enroll(capability)  # still held: a longer pause; lifted: the slot is ours again
                continue
            if capability != held_by_work and self.now() - slot.get("renewed_at", 0) >= RENEW_SECONDS - 0.5:
                self._enroll(capability)  # the holder's enroll renews its lease (no event); a lapsed one re-enrolls
        if self.current is None and not self.stopping:
            self._continue_lapsed()
        if self.current is None and not self.stopping:
            self._reconcile_pending()
            self._claim_next()

    def _continue_lapsed(self) -> None:
        """Accepted work whose lease lapsed goes back to this responder by `com.responder_replace` with a transfer."""
        lapsed: Dict[str, List[Dict[str, Any]]] = {}
        for entry in self.checkpoint.entries.values():
            if entry.get("step") == "lapsed" and self.slots.get(entry.get("capability"), {}).get("state") == "held":
                lapsed.setdefault(entry["capability"], []).append(json.loads(json.dumps(entry)))
        for capability, entries in lapsed.items():
            live = [e for e in entries if self._read_state(e) == "accepted"]
            for e in entries:
                if e not in live:
                    self.checkpoint.drop(e["request"])
            if live:
                self._replace(capability, live, self.slots[capability].get("generation", 0))

    def _reconcile_pending(self) -> None:
        """Work whose outcome became unknown while running (its attempt was lost after the effect began) is tried
        again every five minutes: the slot's holder reconciles from what `observe` reads, or it stays unknown."""
        if self.now() < getattr(self, "_reconcile_at", 0.0):
            return
        self._reconcile_at = self.now() + 300.0
        for entry in list(self.checkpoint.entries.values()):
            if entry.get("step") == "unknown" and self.slots.get(entry.get("capability"), {}).get("state") == "held":
                self._reconcile(entry)

    def _claim_next(self) -> None:
        held = [c for c in self.capabilities if self.slots.get(c, {}).get("state") == "held"]
        for i in range(len(held)):
            capability = held[(self._rr + i) % len(held)]
            key = self.claim_keys.setdefault(capability, self._key("claim"))
            try:
                answer = self._receipt("com.claim", self._call("com.claim", {"idempotency": self._idem(key), "capability": capability}))
            except BoardError as exc:
                if exc.code == "lease_expired":
                    self._enroll(capability)  # the slot lapsed: enroll again (a new generation)
                    continue
                if exc.code in ("idempotency_window_expired", "capacity_exceeded"):
                    self.claim_keys.pop(capability, None)
                    self._status()
                    continue
                if exc.code == "fenced":
                    self.slots[capability] = {"state": "contested", "renewed_at": self.now()}
                    continue
                if exc.code == "held":
                    self._pause(capability)
                    continue
                raise
            if "request" not in answer:
                continue  # nothing claimable; the same key polls again
            self.claim_keys.pop(capability, None)
            self._rr += 1
            self._start(capability, answer)
            return

    # -- a claimed request -------------------------------------------------------------------------------------
    def _start(self, capability: str, receipt: Dict[str, Any]) -> None:
        if "attempt" not in receipt or "message" not in receipt:
            raise BoardError("receipt-shape", "com.claim answered a request without its attempt or message.", op="com.claim")
        attempt = receipt["attempt"]
        entry = {"request": receipt["request"]["id"], "message": receipt["message"], "capability": capability,
                 "generation": attempt["generation"], "attempt": attempt["id"], "digest": attempt["digest"],
                 "revision": receipt["request"]["revision"], "step": "claimed", "keys": {}, "effect": False}
        self.checkpoint.put(entry)
        message = self._call("com.get", {"message": entry["message"]})
        req = message.get("request") if isinstance(message, dict) else None
        if message.get("digest") != entry["digest"]:
            self.checkpoint.drop(entry["request"])
            self._emit("board.request.skipped", "warn", "A claimed request was not accepted: the message read back carries "
                       "another digest than the claim. Nothing was done; the claim lapses.", request=entry["request"],
                       capability=capability, reason="digest-mismatch")
            return
        if not isinstance(req, dict) or req.get("id") != entry["request"] or req.get("capability") != capability \
                or req.get("target") != self.project:
            self.checkpoint.drop(entry["request"])
            self._emit("board.request.skipped", "warn", "A claimed request was not accepted: it is not addressed to this "
                       "Project and capability. Nothing was done; the claim lapses.", request=entry["request"],
                       capability=capability, reason="not-addressed")
            return
        request = BoardRequest(message, capability)
        if message.get("redacted") is True or not isinstance(request.body, str):
            reason: Optional[str] = "The request's body was redacted, so there is nothing to act on."
        else:
            try:
                reason = self.admit(request)
            except Exception:  # noqa: BLE001 - a gate that fails refuses
                reason = "The service's input gate could not read this request."
        if not self._accept(entry):
            return
        if reason is not None:
            text = ("Refused by this service's input gate: %s" % " ".join(str(reason).split()))[:SUMMARY_MAX]
            entry["outcome"] = {"state": "failed_known", "observed": True, "summary": text}
            self._complete(entry)
            self._emit("board.request.refused", "info", "A request was refused by the service's input gate and completed as "
                       "failed.", request=entry["request"], capability=capability)
            return
        self._run(entry, request)

    def _accept(self, entry: Dict[str, Any]) -> bool:
        key = entry["keys"].get("accept") or self._key("accept")
        entry["keys"]["accept"], entry["step"] = key, "accepting"
        self.checkpoint.put(entry)
        try:
            receipt = self._fenced("com.accept", entry, {"fence": self._fence(entry, key)})
        except BoardError as exc:
            if exc.code != "held":
                raise
            # A hold came between the claim and the accept (DEC-0079): nothing was done, the claim lapses and the request
            # waits on the board for the hold to be lifted.
            self.checkpoint.drop(entry["request"])
            self._emit("board.request.waiting", "info", "A claimed request was not accepted: the operator holds it. Nothing "
                       "was done; it waits on the board.", request=entry["request"], capability=entry["capability"])
            self._pause(entry["capability"])
            return False
        if receipt is None:
            return False  # the claim was lost before it was accepted; nothing was done
        entry["revision"], entry["step"] = receipt["request"]["revision"], "accepted"
        self.checkpoint.put(entry)
        return True

    def _run(self, entry: Dict[str, Any], request: BoardRequest) -> None:
        ctx = WorkContext(self, entry)
        work = _Work(entry, request, ctx)
        work.renewed_at = self.now()
        self.current = work

        def body() -> None:
            try:
                work.outcome = self.handler(request, ctx)
            except BaseException as exc:  # noqa: BLE001 - recorded, decided by _finish
                work.failure = exc
            finally:
                work.done.set()
        self.spawn(body)
        if work.done.is_set():
            self._finish(work)

    def _resume(self, entry: Dict[str, Any]) -> None:
        """A transferred request continues: an outcome already known is sent; otherwise the handler runs again (no
        effect had begun, so nothing happened yet)."""
        if isinstance(entry.get("outcome"), dict):
            self._complete(entry)
            return
        message = self._call("com.get", {"message": entry["message"]})
        self._run(entry, BoardRequest(message, entry["capability"]))

    def _fenced(self, op: str, entry: Dict[str, Any], args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """A fenced call. On `fenced`, `lease_expired` or `authority_changed` the attempt is lost: the work stops, and
        answers None (`authority_changed` raises after that, so the responder stops claiming)."""
        try:
            return self._receipt(op, self._call(op, args))
        except BoardError as exc:
            if exc.code in STOP_CODES or exc.code in ("revision_conflict", "invalid_transition", "digest_conflict"):
                self._lose(entry, exc.code)
                if exc.code == "authority_changed":
                    raise
                return None
            raise

    def _lose(self, entry: Dict[str, Any], code: str) -> None:
        if self.current is not None and self.current.entry is entry:
            self.current.ctx.stopped.set()
        if entry.get("effect"):
            entry["step"] = "unknown"
            self.checkpoint.put(entry)
            self._emit("board.reconcile.needed", "warn", "The attempt was lost after its effect began; the outcome stays unknown "
                       "until this service observes what happened.", notify=True, episode=entry["request"],
                       request=entry["request"], capability=entry["capability"], reason=code)
        elif code == "lease_expired" and entry.get("step") not in ("claimed", "accepting"):
            # Our own lease lapsed on accepted work: the board holds it (C4). It continues only by a checkpoint transfer
            # to this responder, which the next tick asks for; nothing outside the service had begun.
            entry["step"] = "lapsed"
            self.checkpoint.put(entry)
            self._emit("board.attempt.lost", "warn", "This service's lease on an accepted request lapsed; it stopped working "
                       "on it and takes it back by a transfer.", request=entry["request"], capability=entry["capability"], reason=code)
        else:
            self.checkpoint.drop(entry["request"])
            self._emit("board.attempt.lost", "warn", "The board took a request back from this service (%s); it stopped working "
                       "on it, and nothing had been done outside the service." % code, request=entry["request"],
                       capability=entry["capability"], reason=code)

    def _renew(self, work: _Work) -> None:
        entry = work.entry
        if self.now() - (work.renewed_at or 0.0) < RENEW_SECONDS - 0.5:
            return
        receipt = self._fenced("com.renew", entry, {"fence": self._fence(entry, self._key("renew"))})
        if receipt is None:
            self.current = None
            return
        work.renewed_at = self.now()
        self.slots.setdefault(entry["capability"], {})["renewed_at"] = self.now()

    def _progress(self, entry: Dict[str, Any], note: Optional[str], ctx: WorkContext) -> None:
        args: Dict[str, Any] = {"fence": self._fence(entry, self._key("progress"))}
        if note is not None:
            args["note"] = {"text": " ".join(str(note).split())[:SUMMARY_MAX] or "Working."}
        if self._fenced("com.progress", entry, args) is None:
            raise Stopped()

    def _effect_begin(self, entry: Dict[str, Any], summary: Optional[str], ctx: WorkContext) -> None:
        key = entry["keys"].get("effect_begin") or self._key("effect")
        entry["keys"]["effect_begin"], entry["step"] = key, "effect-beginning"
        entry["effect"] = True  # from here a lost attempt is an unknown outcome, never "nothing happened"
        self.checkpoint.put(entry)
        args: Dict[str, Any] = {"fence": self._fence(entry, key)}
        if summary:
            args["summary"] = " ".join(str(summary).split())[:SUMMARY_MAX]
        receipt = None
        lost, delay = 0, self.hold_delay
        while True:  # a lost answer: the same key again tells whether it was stored
            try:
                receipt = self._fenced("com.effect_begin", entry, args)
                break
            except BoardError as exc:
                if exc.code == "held":
                    # The operator holds this work (DEC-0079): the effect has not begun. Wait, keep the lease (the tick
                    # renews it; com.renew is never held), and ask again with the same key.
                    entry["effect"], entry["step"] = False, "effect-held"
                    self.checkpoint.put(entry)
                    self._emit("board.request.waiting", "info", "The operator holds this request before its effect: the "
                               "service waits and does nothing outside it until the hold is lifted.", episode=entry["request"],
                               request=entry["request"], capability=entry["capability"])
                    if ctx.stopped.wait(delay):
                        raise Stopped() from None
                    delay = min(HOLD_RETRY_MAX_SECONDS, delay * 2)
                    entry["effect"], entry["step"] = True, "effect-beginning"
                    self.checkpoint.put(entry)
                    continue
                if exc.code != "unreachable" or lost == 2:
                    raise Stopped() from None
                lost += 1
                time.sleep(lost)
        if receipt is None:
            raise Stopped()
        entry["revision"], entry["step"] = receipt["request"]["revision"], "in-progress"
        self.checkpoint.put(entry)

    def _finish(self, work: _Work) -> None:
        entry = work.entry
        if work.ctx.stopped.is_set() and entry["request"] not in self.checkpoint.entries:
            self.current = None
            return
        outcome = work.outcome
        if work.failure is not None:
            if entry.get("effect") or isinstance(work.failure, Stopped):
                self.current = None
                if entry.get("effect"):
                    self._lose(entry, "handler-failed")
                return
            outcome = {"state": "failed_known", "observed": True,
                       "summary": "The service could not do this (%s)." % work.failure.__class__.__name__}
        problems = outcome_problems(outcome, bool(entry.get("effect")))
        if problems:
            self.current = None
            if entry.get("effect"):
                self._lose(entry, "observation_required" if any("observation_required" in p for p in problems) else "outcome")
            else:
                entry["outcome"] = {"state": "failed_known", "observed": True, "summary": "The service answered in a form it cannot send."}
                self._complete(entry)
            self._emit("board.outcome.invalid", "warn", "The handler's outcome was not sent: %s." % problems[0],
                       request=entry["request"], capability=entry["capability"])
            return
        entry["outcome"] = dict(outcome, observed=outcome.get("observed", not entry.get("effect")))
        self._complete(entry)

    def _complete(self, entry: Dict[str, Any]) -> None:
        outcome = entry["outcome"]
        reply = outcome.get("reply")
        if reply and not entry.get("replied"):
            key = entry["keys"].get("reply") or self._key("reply")
            entry["keys"]["reply"], entry["step"] = key, "replying"
            self.checkpoint.put(entry)
            body = {"text": reply["text"], **({"format": reply["format"]} if "format" in reply else {})}
            args: Dict[str, Any] = {"fence": self._fence(entry, key), "body": body}
            if reply.get("artifacts"):
                args["artifacts"] = reply["artifacts"]
            if self._fenced("com.reply", entry, args) is None:
                self.current = None
                return
            entry["replied"] = True
            self.checkpoint.put(entry)
        key = entry["keys"].get("complete") or self._key("complete")
        entry["keys"]["complete"], entry["step"] = key, "completing"
        self.checkpoint.put(entry)
        sent = {k: outcome[k] for k in ("state", "observed", "summary", "evidence") if k in outcome}
        receipt = self._fenced("com.complete", entry, {"fence": self._fence(entry, key), "outcome": sent})
        self.current = None
        if receipt is None:
            return
        self.checkpoint.drop(entry["request"])
        self._emit("board.request.completed", "info", "A request was answered: %s." % ("completed" if sent["state"] == "completed" else "failed, as known"),
                   request=entry["request"], capability=entry["capability"], state=sent["state"])

    # -- running ----------------------------------------------------------------------------------------------
    def run(self, stop: threading.Event, drain: float = DRAIN_SECONDS) -> None:
        """Tick until `stop` is set, then `shutdown(drain)`."""
        while not stop.is_set():
            stop.wait(self.step())
        self.shutdown(drain)

    def shutdown(self, drain: float = DRAIN_SECONDS) -> None:
        """Stop claiming, give running work up to `drain` seconds to finish and be completed, then leave the session
        (its DELETE releases the slots). What is still open stays in the checkpoint for the next start."""
        self.stopping = True
        work = self.current
        if work is not None and not work.done.wait(drain):
            work.ctx.stopped.set()
        if work is not None and work.done.is_set() and self.session is not None:
            try:
                self._finish(work)
            except (BoardError, _hub.HubError):
                pass  # the checkpoint keeps it
        if self.session is not None:
            self.session.close()
            self.session = None
        self.state = "stopped"
