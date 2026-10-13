"""A service agent answers a Project's requests on Fabric's project board (`fabric-project-comms/0.1`; contract DEC-0022,
DEC-0073, DEC-0077, DEC-0078; Fabric ADR-0149; FAA-12b, FAA-40). Standard library only; `fabric_hub.py` finds the hub.

What a responder does, in the contract's words (project-comms.md, "Request lifecycle", "Responders and fences"):

    enroll (capability) → claim → read the message → accept (the exact digest) → [effect_begin] → [progress] →
    [reply] → complete ({state, observed, summary?, evidence ≤ 8 sha256 artifacts})

`Responder` runs that loop inside the service process (no new process): one tick every 15 s ± 5 s, which claims when
idle and renews the lease (60 s of database time, renewed at about 20 s) while work runs. Before it advances a step it
writes and fsyncs a checkpoint, so a restart picks up exactly where the last answer was confirmed: `com.reconcile` for
work whose outcome is unknown, `com.responder_replace` with a transfer for accepted work (DEC-0078 hands back the new
attempts in the receipt's `transferred`; a Fabric that does not yet answer it leaves the work held — never claimed back).
It stops acting the moment the board says `fenced`, `lease_expired` or `authority_changed`.

THE REQUEST BODY IS DATA. The kit never hands a body to a model or a shell. `admit(request)` is the service's own input
gate, required: it answers None to admit or a sentence saying why not; a refusal accepts the request and completes it
`failed_known` with that sentence, so the requester learns it. What the handler does with an admitted body — and the
checks it needs before any model, tool or spend sees it — is the service's own responsibility.

A board session (`fabric.board.join`) is served the respond scope only: `com.status`, `com.list`, `com.get`,
`com.reply` (the fenced form), `com.enroll`, `com.claim`, `com.renew`, `com.accept`, `com.progress`, `com.effect_begin`,
`com.complete`, `com.reconcile`, `com.responder_replace`. This kit never sends `com.submit`, `com.cancel`,
`com.read_ack` or `com.directory` through one; a directory lookup belongs to a Project session, and `find_project`
checks such a page first (FAC-SEM-107: each Project once, each capability once per Project, compared as written)."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import random
import re
import secrets
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_hub as _hub  # noqa: E402 - beside this file
import fabric_identifiers as _ids  # noqa: E402 - beside this file (DEC-0076)
import fabric_service as _fs  # noqa: E402 - beside this file

COMMS_PROTOCOL = "fabric-project-comms/0.1"
LEASE_SECONDS = 60.0
RENEW_SECONDS = 20.0
POLL_SECONDS = 15.0
POLL_JITTER_SECONDS = 5.0
DRAIN_SECONDS = 10.0
SUMMARY_MAX = 2000
EVIDENCE_MAX = 8
EVENT_SCHEMA = "urn:fabric:schema:board-responder-event:1"

#: The tools a board session is served (Fabric's respond scope); anything else is refused here, before it is sent.
RESPOND_TOOLS = frozenset(["com.status", "com.list", "com.get", "com.reply", "com.enroll", "com.claim", "com.renew",
                           "com.accept", "com.progress", "com.effect_begin", "com.complete", "com.reconcile",
                           "com.responder_replace"])
REFUSAL_CODES = frozenset(["invalid_arguments", "body_too_large", "not_authorized", "authority_changed",
                           "unsupported_capability", "unsupported_operation", "not_available", "idempotency_conflict",
                           "idempotency_window_expired", "capacity_exceeded", "digest_conflict", "revision_conflict",
                           "fenced", "lease_expired", "invalid_transition", "reconcile_required", "observation_required",
                           "cursor_reset_required", "immutable_participants"])
#: On these the attempt is no longer ours: stop acting at once (C4).
STOP_CODES = frozenset(["fenced", "lease_expired", "authority_changed"])
REQUEST_STATES = ("queued", "claimed", "accepted", "in_progress", "completed", "failed_known", "cancelled", "expired",
                  "outcome_unknown")
EFFECT_STATES = ("not_started", "started", "succeeded_observed", "failed_observed", "unknown")
TERMINAL = frozenset(["completed", "failed_known", "cancelled", "expired"])

_OPAQUE = re.compile(r"[A-Za-z0-9_-]{8,128}")
_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}")
_CAPABILITY = re.compile(r"[a-z][a-z0-9._-]{1,127}")
_SHA256 = re.compile(r"sha256:[a-f0-9]{64}")
_KEY = re.compile(r"[A-Za-z0-9._:-]{8,128}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})")
_URI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:[^\s]+")
_SAFE = 2 ** 53 - 1


class BoardError(Exception):
    """A board refusal (`code` from the contract's refusal codes) or a kit fault: `unreachable` (the hub did not answer;
    a write may have been stored — send it again with the same key), `session-ended`, `not-in-scope`, `receipt-shape`,
    `schema-unsupported`, `no-epoch`, `checkpoint`, `digest-mismatch`, `not-addressed`, `directory-invalid`,
    `evidence`, `observation_required`. `str()` is one sentence and never carries a token or a body."""

    def __init__(self, code: str, message: str, retryable: bool = False, op: Optional[str] = None,
                 data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code, self.message, self.retryable, self.op, self.data = code, message, retryable, op, data or {}

    def __repr__(self) -> str:
        return "BoardError(%r, %r)" % (self.code, self.message)


class Stopped(Exception):
    """Raised inside a handler (from `ctx.progress` / `ctx.begin_effect`) when the attempt is no longer this
    responder's: stop at once and act no further."""


# --- the contract's digest (src/comms-digest.ts) ---------------------------------------------------------------

def comms_canonical(value: Any) -> str:
    """RFC 8785 as the board takes it: members sorted by UTF-16 code unit, integers only (|n| ≤ 2^53−1), no lone
    surrogate, no normalisation. Raises `ValueError` on anything else rather than guessing a spelling."""
    if value is None or isinstance(value, bool):
        return json.dumps(value)
    if isinstance(value, int):
        if abs(value) > _SAFE:
            raise ValueError("canonical JSON admits integers within ±(2^53−1) only")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer() or abs(value) > _SAFE:
            raise ValueError("canonical JSON admits integers within ±(2^53−1) only")
        return str(int(value))
    if isinstance(value, str):
        if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("canonical JSON refuses a lone surrogate")
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[%s]" % ",".join(comms_canonical(v) for v in value)
    if isinstance(value, dict):
        for k in value:
            if not isinstance(k, str):
                raise ValueError("canonical JSON has string keys only")
            comms_canonical(k)  # refuses a lone surrogate in a key too
        keys = sorted(value, key=lambda k: k.encode("utf-16-be"))  # big-endian UTF-16 bytes sort as code units
        return "{%s}" % ",".join("%s:%s" % (comms_canonical(k), comms_canonical(value[k])) for k in keys)
    raise ValueError("canonical JSON has no %s" % type(value).__name__)


def comms_digest(operation: str, value: Any) -> str:
    """`sha256:<hex>` over `fabric-project-comms/0.1 NUL <operation> NUL <canonical JSON>` (the contract's `commsDigest`)."""
    if not isinstance(operation, str) or operation == "" or "\0" in operation:
        raise ValueError("an operation is a non-empty name without NUL")
    data = "%s\0%s\0%s" % (COMMS_PROTOCOL, operation, comms_canonical(value))
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


# --- closed shapes: what the kit reads back ------------------------------------------------------------------

def _is_int(v: Any, minimum: int) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and minimum <= v <= _SAFE


def _closed(value: Any, at: str, required: Sequence[str], allowed: Sequence[str], problems: List[str]) -> bool:
    if not isinstance(value, dict):
        problems.append("%s is an object" % at)
        return False
    for key in required:
        if key not in value:
            problems.append("%s/%s is required" % (at, key))
    for key in value:
        if key not in allowed:
            problems.append("%s/%s is not a member the contract names" % (at, key))
    return True


def _attempt_problems(a: Any, at: str, problems: List[str]) -> None:
    keys = ("id", "generation", "digest", "leaseExpiresAt")
    if _closed(a, at, keys, keys, problems):
        if not (isinstance(a.get("id"), str) and _OPAQUE.fullmatch(a["id"])):
            problems.append("%s/id is a board id" % at)
        if not _is_int(a.get("generation"), 1):
            problems.append("%s/generation is an integer ≥ 1" % at)
        if not (isinstance(a.get("digest"), str) and _SHA256.fullmatch(a["digest"])):
            problems.append("%s/digest is sha256:<hex>" % at)
        if not (isinstance(a.get("leaseExpiresAt"), str) and _TIMESTAMP.fullmatch(a["leaseExpiresAt"])):
            problems.append("%s/leaseExpiresAt is a timestamp" % at)


def receipt_problems(value: Any, op: Optional[str] = None) -> List[str]:
    """`comms-receipt.schema.json` at the pin, closed at every level (a seq or a holder is refused, C3), plus what a
    schema cannot say: `transferred` answers only `com.responder_replace` (DEC-0078) and names each request once."""
    problems: List[str] = []
    allowed = ("ok", "repeated", "message", "thread", "at", "request", "slot", "attempt", "transferred")
    if not _closed(value, "", ("ok", "repeated"), allowed, problems):
        return problems
    if value.get("ok") is not True:
        problems.append("/ok is true")
    if not isinstance(value.get("repeated"), bool):
        problems.append("/repeated is a boolean")
    for key in ("message", "thread"):
        if key in value and not (isinstance(value[key], str) and _OPAQUE.fullmatch(value[key])):
            problems.append("/%s is a board id" % key)
    if "at" in value and not (isinstance(value["at"], str) and _TIMESTAMP.fullmatch(value["at"])):
        problems.append("/at is a timestamp")
    if "request" in value:
        r = value["request"]
        keys = ("id", "state", "effect", "revision")
        if _closed(r, "/request", keys, keys, problems):
            if not (isinstance(r.get("id"), str) and _OPAQUE.fullmatch(r["id"])):
                problems.append("/request/id is a board id")
            if r.get("state") not in REQUEST_STATES:
                problems.append("/request/state is a request state")
            if r.get("effect") not in EFFECT_STATES:
                problems.append("/request/effect is an effect state")
            if not _is_int(r.get("revision"), 1):
                problems.append("/request/revision is an integer ≥ 1")
    if "slot" in value:
        s = value["slot"]
        keys = ("project", "capability", "generation", "leaseExpiresAt")
        if _closed(s, "/slot", keys, keys, problems):
            if not (isinstance(s.get("project"), str) and _PROJECT.fullmatch(s["project"])):
                problems.append("/slot/project is a Project id")
            if not (isinstance(s.get("capability"), str) and _CAPABILITY.fullmatch(s["capability"])):
                problems.append("/slot/capability is a capability name")
            if not _is_int(s.get("generation"), 1):
                problems.append("/slot/generation is an integer ≥ 1")
            if not (isinstance(s.get("leaseExpiresAt"), str) and _TIMESTAMP.fullmatch(s["leaseExpiresAt"])):
                problems.append("/slot/leaseExpiresAt is a timestamp")
    if "attempt" in value:
        _attempt_problems(value["attempt"], "/attempt", problems)
    if "transferred" in value:
        t = value["transferred"]
        if op is not None and op != "com.responder_replace":
            problems.append("/transferred answers com.responder_replace only (DEC-0078)")
        if not isinstance(t, list) or not 1 <= len(t) <= 64:
            problems.append("/transferred is 1 to 64 items")
        else:
            seen = set()
            for i, item in enumerate(t):
                at = "/transferred/%d" % i
                keys = ("request", "revision", "attempt")
                if _closed(item, at, keys, keys, problems):
                    rid = item.get("request")
                    if not (isinstance(rid, str) and _OPAQUE.fullmatch(rid)):
                        problems.append("%s/request is a board id" % at)
                    elif rid in seen:
                        problems.append("%s/request names a request already listed (each request once, DEC-0078)" % at)
                    seen.add(rid)
                    if not _is_int(item.get("revision"), 1):
                        problems.append("%s/revision is an integer ≥ 1" % at)
                    _attempt_problems(item.get("attempt"), at + "/attempt", problems)
    return problems


def refusal_problems(value: Any) -> List[str]:
    """`comms-refusal.schema.json`: `{error: {code, message, retryable}}`, closed, a known code, one sentence ≤ 300."""
    problems: List[str] = []
    if _closed(value, "", ("error",), ("error",), problems):
        e = value["error"]
        keys = ("code", "message", "retryable")
        if _closed(e, "/error", keys, keys, problems):
            if e.get("code") not in REFUSAL_CODES:
                problems.append("/error/code is a refusal code the contract names")
            if not (isinstance(e.get("message"), str) and 1 <= len(e["message"]) <= 300):
                problems.append("/error/message is 1 to 300 characters")
            if not isinstance(e.get("retryable"), bool):
                problems.append("/error/retryable is a boolean")
    return problems


def directory_findings(page: Any) -> List[Dict[str, str]]:
    """FAC-SEM-107 (DEC-0077), the contract's `commsDirectory`: a Project listed twice, or a capability listed twice
    within a Project, compared exactly as written (Project ids are opaque and capability names are names, not URIs —
    so not by normal form). The finding names the second entry. Never raises."""
    findings: List[Dict[str, str]] = []
    projects = page.get("projects") if isinstance(page, dict) else None
    seen = set()
    for p, project in enumerate(projects if isinstance(projects, list) else []):
        if not isinstance(project, dict):
            continue
        pid = project.get("id")
        if isinstance(pid, str):
            if pid in seen:
                findings.append({"code": "FAC-SEM-107", "instancePath": "/projects/%d/id" % p,
                                 "message": "a directory page lists each Project once: %s is listed again" % pid})
            seen.add(pid)
        caps = project.get("capabilities")
        names = set()
        for c, entry in enumerate(caps if isinstance(caps, list) else []):
            if not isinstance(entry, dict) or not isinstance(entry.get("capability"), str):
                continue
            if entry["capability"] in names:
                findings.append({"code": "FAC-SEM-107", "instancePath": "/projects/%d/capabilities/%d/capability" % (p, c),
                                 "message": "a Project lists each capability once: %s is listed again" % entry["capability"]})
            names.add(entry["capability"])
    return findings


def directory_problems(page: Any) -> List[str]:
    """`comms-directory.schema.json`, closed at every level (no count, holder or generation), then FAC-SEM-107."""
    problems: List[str] = []
    if not _closed(page, "", ("protocol", "snapshot", "projects", "cursor"), ("protocol", "snapshot", "projects", "cursor"), problems):
        return problems
    if page.get("protocol") != COMMS_PROTOCOL:
        problems.append("/protocol is %s" % COMMS_PROTOCOL)
    snap = page.get("snapshot")
    if _closed(snap, "/snapshot", ("readAt",), ("readAt", "stale"), problems):
        if not (isinstance(snap.get("readAt"), str) and _TIMESTAMP.fullmatch(snap["readAt"])):
            problems.append("/snapshot/readAt is a timestamp")
        if "stale" in snap and not isinstance(snap["stale"], bool):
            problems.append("/snapshot/stale is a boolean")
    if page.get("cursor") is not None and not (isinstance(page.get("cursor"), str) and _OPAQUE.fullmatch(page["cursor"])):
        problems.append("/cursor is a board id or null")
    projects = page.get("projects")
    if not isinstance(projects, list) or len(projects) > 100:
        problems.append("/projects is at most 100 Projects")
        return problems
    for p, project in enumerate(projects):
        at = "/projects/%d" % p
        if not _closed(project, at, ("id", "name", "capabilities"), ("id", "name", "capabilities"), problems):
            continue
        if not (isinstance(project.get("id"), str) and _PROJECT.fullmatch(project["id"])):
            problems.append("%s/id is a Project id" % at)
        if not (isinstance(project.get("name"), str) and 1 <= len(project["name"]) <= 120):
            problems.append("%s/name is 1 to 120 characters" % at)
        caps = project.get("capabilities")
        if not isinstance(caps, list) or len(caps) > 64:
            problems.append("%s/capabilities is at most 64 entries" % at)
            continue
        for c, entry in enumerate(caps):
            cat = "%s/capabilities/%d" % (at, c)
            if _closed(entry, cat, ("capability", "responder"), ("capability", "responder"), problems):
                if not (isinstance(entry.get("capability"), str) and _CAPABILITY.fullmatch(entry["capability"])):
                    problems.append("%s/capability is a capability name" % cat)
                if entry.get("responder") not in ("active", "stale", "absent"):
                    problems.append("%s/responder is active, stale or absent" % cat)
    return problems + ["%s %s" % (f["instancePath"], f["message"]) for f in directory_findings(page)]


def find_project(page: Any, project_id: str, capability: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Look a Project up in one `com.directory` page (read by a Project session — a board session is not served the
    directory). The page is checked first: a page the contract would refuse, FAC-SEM-107 included, raises
    `BoardError("directory-invalid")` instead of answering from it. Ids and capability names compare exactly as
    written (DEC-0077). Answers the entry, or None when the page does not list it (or lists it without `capability`):
    an unlisted Project may still be addressable by an id the caller already holds."""
    problems = directory_problems(page)
    if problems:
        raise BoardError("directory-invalid", "The directory page cannot be read: %s." % "; ".join(problems[:3]))
    for entry in page["projects"]:
        if entry["id"] == project_id:
            if capability is None or any(c["capability"] == capability for c in entry["capabilities"]):
                return entry
            return None
    return None


# --- evidence -------------------------------------------------------------------------------------------------

def artifact_ref(uri: str, content: Optional[bytes] = None, path: Optional[Path] = None, label: Optional[str] = None) -> Dict[str, Any]:
    """One artifact reference `{id, contentHash, label?}`: `id` is a URI the requester can resolve; the hash is
    computed here from `content` or the file at `path`, never trusted from elsewhere."""
    if (content is None) == (path is None):
        raise BoardError("evidence", "Give the artifact's bytes or its path, one of them.")
    digest = hashlib.sha256()
    if content is not None:
        digest.update(content)
    else:
        with open(str(path), "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    ref: Dict[str, Any] = {"id": uri, "contentHash": "sha256:" + digest.hexdigest()}
    if label is not None:
        ref["label"] = label
    problems = evidence_problems([ref])
    if problems:
        raise BoardError("evidence", "; ".join(problems))
    return ref


def evidence_problems(evidence: Any) -> List[str]:
    """At most 8 references, each `{id: uri, contentHash: sha256:<hex>, label? ≤ 120}`, closed; and no artifact twice:
    two ids with one normal form (DEC-0076) name one artifact."""
    if not isinstance(evidence, list) or len(evidence) > EVIDENCE_MAX:
        return ["evidence is a list of at most %d artifact references" % EVIDENCE_MAX]
    problems: List[str] = []
    for i, ref in enumerate(evidence):
        at = "evidence/%d" % i
        if not _closed(ref, at, ("id", "contentHash"), ("id", "contentHash", "label"), problems):
            continue
        if not (isinstance(ref.get("id"), str) and _URI.fullmatch(ref["id"])):
            problems.append("%s/id is a URI" % at)
        if not (isinstance(ref.get("contentHash"), str) and _SHA256.fullmatch(ref["contentHash"])):
            problems.append("%s/contentHash is sha256:<hex>" % at)
        if "label" in ref and not (isinstance(ref["label"], str) and len(ref["label"]) <= 120):
            problems.append("%s/label is at most 120 characters" % at)
        for j in range(i):
            other = evidence[j]
            if isinstance(other, dict) and _ids.same_identifier(other.get("id"), ref.get("id")):
                problems.append("%s/id names the artifact evidence/%d already names" % (at, j))
    return problems


def outcome_problems(outcome: Any, effect_began: bool) -> List[str]:
    """`comms-complete`'s outcome: state `completed`|`failed_known`, `observed` a boolean (true after an effect began),
    summary ≤ 2,000 characters, evidence as `evidence_problems`; plus the kit's optional `reply {text, format?,
    artifacts?}` (≤ 65,536 UTF-8 bytes), sent with `com.reply` before the completion."""
    problems: List[str] = []
    if not _closed(outcome, "outcome", ("state",), ("state", "observed", "summary", "evidence", "reply"), problems):
        return problems
    if outcome.get("state") not in ("completed", "failed_known"):
        problems.append("outcome/state is completed or failed_known")
    observed = outcome.get("observed", not effect_began)
    if not isinstance(observed, bool):
        problems.append("outcome/observed is a boolean")
    elif effect_began and observed is not True:
        problems.append("observation_required: after an effect began only an observed result settles the request")
    if "summary" in outcome and not (isinstance(outcome["summary"], str) and 1 <= len(outcome["summary"]) <= SUMMARY_MAX):
        problems.append("outcome/summary is 1 to %d characters" % SUMMARY_MAX)
    if "evidence" in outcome:
        problems.extend(evidence_problems(outcome["evidence"]))
    if "reply" in outcome:
        reply = outcome["reply"]
        if _closed(reply, "outcome/reply", ("text",), ("text", "format", "artifacts"), problems):
            text = reply.get("text")
            if not (isinstance(text, str) and text and len(text.encode("utf-8")) <= 65536):
                problems.append("outcome/reply/text is 1 to 65,536 UTF-8 bytes")
            if "format" in reply and reply["format"] not in ("text/plain", "text/markdown"):
                problems.append("outcome/reply/format is text/plain or text/markdown")
            if "artifacts" in reply:
                problems.extend(p.replace("evidence", "outcome/reply/artifacts", 1) for p in evidence_problems(reply["artifacts"]))
    return problems


# --- the board session --------------------------------------------------------------------------------------------

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
            raise BoardError("unreachable", "Fabric's hub did not answer; a write may have been stored — send it again with "
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


# --- the checkpoint ---------------------------------------------------------------------------------------------

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


# --- the request a handler sees --------------------------------------------------------------------------------

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


# --- the responder ------------------------------------------------------------------------------------------------

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
            if exc.code == "fenced":
                self.slots[capability] = {"state": "contested", "renewed_at": self.now()}
                self._emit("board.slot.contested", "warn", "Another responder holds the %s slot on this Project; this service "
                           "waits for it to lapse and never takes it over by itself." % capability, notify=True,
                           episode=capability, capability=capability)
                return
            raise
        self.slots[capability] = {"state": "held", "generation": receipt["slot"]["generation"], "renewed_at": self.now()}
        self._said.pop("board.slot.contested", None)

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
        generations = {r.get("capability"): r.get("generation", 0) for r in status.get("responders") or [] if isinstance(r, dict)}
        for capability in capabilities:
            held = transfer.get(capability)
            if held:
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
        receipt = self._receipt("com.responder_replace", self._call("com.responder_replace", args))
        self.slots[capability] = {"state": "held", "generation": receipt["slot"]["generation"], "renewed_at": self.now()}
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
        receipt = self._fenced("com.accept", entry, {"fence": self._fence(entry, key)})
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
        for attempt in range(3):  # a lost answer: the same key again tells whether it was stored
            try:
                receipt = self._fenced("com.effect_begin", entry, args)
                break
            except BoardError as exc:
                if exc.code != "unreachable" or attempt == 2:
                    raise Stopped() from None
                time.sleep(attempt + 1)
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


# --- a fixture conversation (check_service.py, rule board.responder) ---------------------------------------------

_FIXTURE_PROJECT = "3f2a6b1c-0d4e-4f5a-8b6c-7d8e9f0a1b2c"
_FIXTURE_DIGEST = "sha256:" + "a" * 64


def _fixture_answers(variant: str) -> Dict[str, Any]:
    """Scripted board answers in the contract's receipt shapes (fixtures comms-receipt-enroll, comms-receipt-claim)."""
    lease = "2026-10-13T10:02:00Z"
    status: Dict[str, Any] = {"protocol": COMMS_PROTOCOL, "board": {"state": "ready"}, "project": _FIXTURE_PROJECT, "responders": [],
                              "transport": {"telegram": "off"}, "unread": 0, "idempotency": {"epoch": 3}}
    if variant == "no-epoch":
        del status["idempotency"]
    request = {"id": "req_A1b2C3d4E5", "state": "claimed", "effect": "not_started", "revision": 2}
    return {
        "com.status": status,
        "com.enroll": {"ok": True, "repeated": False, "slot": {"project": _FIXTURE_PROJECT, "capability": "fixture.render", "generation": 2, "leaseExpiresAt": lease}},
        "com.claim": {"ok": True, "repeated": False, "message": "msg_K9j8H7g6F5", "request": request,
                      "attempt": {"id": "att_Zx9Cv8Bn7M", "generation": 2, "digest": _FIXTURE_DIGEST, "leaseExpiresAt": lease}},
        "com.get": {"id": "msg_K9j8H7g6F5", "thread": "thr_8Hc2kQ9xA1", "kind": "request", "at": "2026-10-13T10:00:00Z", "digest": _FIXTURE_DIGEST,
                    "sender": {"project": "proj-requester", "principal": {"kind": "agent", "id": "s-1", "provenance": "trusted"}},
                    "body": {"text": "Render the fixture."},
                    "request": {"id": "req_A1b2C3d4E5", "target": _FIXTURE_PROJECT, "capability": "fixture.render", "state": "claimed", "effect": "not_started", "revision": 2}},
        "com.accept": ({"error": {"code": "fenced", "message": "A newer responder holds this slot; this call was not committed.", "retryable": False}}
                       if variant == "fenced" else {"ok": True, "repeated": False, "request": dict(request, state="accepted", revision=3)}),
        "com.complete": {"ok": True, "repeated": False, "request": dict(request, state="completed", revision=4)},
    }


def self_check() -> List[str]:
    """One scripted conversation per path through this kit, with no Fabric: the whole conversation, a `fenced` accept
    and a board session without an epoch. Answers the problems found; an empty list means this kit answers the fixture
    conversation as the contract asks. Writes only in a temporary folder it removes."""
    import os
    import tempfile
    problems: List[str] = []
    for variant in ("whole", "fenced", "no-epoch"):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fabric"
            root.mkdir(mode=0o700)
            door = root / "hub-door-token"
            door.write_text("d" * 43)
            os.chmod(door, 0o600)
            (root / "hub.json").write_text(json.dumps({"protocol": _hub.HUB_PROTOCOL, "origin": "http://127.0.0.1:47070", "mcp": "/mcp",
                                                       "doorTokenFile": str(door), "pid": os.getpid(), "startedAt": "2026-10-13T10:00:00Z"}))
            cred = Path(tmp) / "credential"
            cred.write_text("c" * 43)
            os.chmod(cred, 0o600)
            answers, calls, handled = _fixture_answers(variant), [], []

            def post(origin, body, bearer, session=None, timeout=15.0, method="POST", protocol_version=None):
                if method == "DELETE":
                    return 200, {}, None
                rpc = body.get("method")
                if rpc == "initialize":
                    return 200, {"mcp-session-id": "fixture-session"}, {"jsonrpc": "2.0", "id": body.get("id"), "result": {"protocolVersion": _hub.MCP_PROTOCOL_VERSION}}
                if rpc != "tools/call":
                    return 202, {}, None
                tool = body["params"]["name"]
                calls.append((tool, body["params"]["arguments"]))
                if tool == "fabric.board.join":
                    value = {"session": {"bearer": "b" * 43, "sessionId": "s-fixture", "projectId": _FIXTURE_PROJECT, "capabilities": ["fixture.render"]}}
                    return 200, {}, {"jsonrpc": "2.0", "id": body.get("id"), "result": {"structuredContent": value}}
                value = answers.get(tool, {"error": {"code": "unsupported_capability", "message": "not in the fixture", "retryable": False}})
                return 200, {}, {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(value)}]}}

            responder = Responder(hub=_hub.HubClient(root, post=post), project_id=_FIXTURE_PROJECT, capabilities=["fixture.render"],
                                  credential_file=cred, checkpoint_file=Path(tmp) / "checkpoint.json",
                                  handler=lambda request, ctx: handled.append(request.body) or {"state": "completed", "summary": "Rendered."},
                                  admit=lambda request: None, now=lambda: 0.0, rand=lambda: 0.5, spawn=lambda fn: fn(),
                                  session_factory=lambda grant: BoardSession(grant, post=post))
            responder.step()
            tools = [t for t, _ in calls]
            if any(t not in RESPOND_TOOLS and t != "fabric.board.join" for t in tools):
                problems.append("%s: a tool outside the respond scope was sent" % variant)
            if variant == "whole":
                if tools != ["fabric.board.join", "com.status", "com.enroll", "com.claim", "com.get", "com.accept", "com.complete"]:
                    problems.append("whole: the calls were %s" % ", ".join(tools))
                accept = dict(calls).get("com.accept", {}).get("fence", {})
                if (accept.get("digest"), accept.get("generation"), accept.get("attempt")) != (_FIXTURE_DIGEST, 2, "att_Zx9Cv8Bn7M"):
                    problems.append("whole: com.accept did not carry the claim's exact fence")
                if handled != ["Render the fixture."]:
                    problems.append("whole: the handler did not see the request once")
                if responder.checkpoint.entries:
                    problems.append("whole: the checkpoint kept a settled request")
            elif variant == "fenced":
                if handled or "com.complete" in tools:
                    problems.append("fenced: the kit kept acting after com.accept answered fenced")
            elif "com.enroll" in tools or responder.state != "down":
                problems.append("no-epoch: the kit did not fail closed without an idempotency epoch")
    return problems
