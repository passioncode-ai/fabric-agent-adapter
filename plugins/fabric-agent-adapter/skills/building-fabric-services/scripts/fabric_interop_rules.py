"""fabric-interop/0.1, the rule layer: the extension's names and limits, its errors, the trace context (C3.4), a
usage object's reading (C3.2) and the job limits and uncertain effects (DEC-0087). Every function answers by a rule
and touches no file; fabric_interop builds the tools, the envelope, the job store and the MCP server on it and
re-exports every name here. Part of the service kit (FAA-92, split from fabric_interop; layer L3). Standard library
only, Python 3.9+."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from typing import Any, Callable, Dict, List, Optional

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))

from fabric_base import ServiceError  # noqa: E402
from fabric_actions import action_decision, decision_shape  # noqa: E402 - DEC-0121

PROTOCOL = "fabric-interop/0.1"
EXTENSION_KEY = "https://fabric.passioncode.ai/agent-contract/extensions/interop/0.1"
MCP_REVISION = "2026-07-28"
# Revisions a client may name in `initialize`. MCP 2026-07-28 needs no handshake, but clients
# built on earlier revisions (Claude Code 2.1.285 among them) still open with one, and a server
# that refuses it is marked failed before tools/list is ever called.
HANDSHAKE_REVISIONS = ("2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28")
CONTRACT_VERSION = "0.1.0"
JOB_STATES = ("working", "input_required", "completed", "failed", "cancelled")
OUTCOMES = ("succeeded", "partial", "failed", "cancelled", "blocked")
ENVELOPE_REQUIRED = ["id", "contractVersion", "outcome", "done", "proof", "scope", "notVerified", "artifacts",
                     "createdAt", "producer", "output", "usage"]
# The job handle inline, as a job tool's outputSchema carries it (contract interop-job-handle.schema.json).
JOB_HANDLE_SCHEMA: Dict[str, Any] = {
    "type": "object", "required": ["job"], "additionalProperties": False,
    "properties": {"job": {"type": "object", "required": ["id", "status"], "additionalProperties": False,
                           "properties": {"id": {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[A-Za-z0-9._:-]+$"},
                                          "status": {"const": "working"}}}},
}
TERMINAL = ("completed", "failed", "cancelled")

_TRACEPARENT = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})\Z")
_JOB_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}\Z")
_KEY = re.compile(r"^[A-Za-z0-9_.-]{1,64}\Z")
_SECRET_WORDS = re.compile(r"pass(word|phrase)|secret|api[\s_-]?key|access[\s_-]?key|private[\s_-]?key|"
                           r"(access|auth|bearer|refresh|session)[\s_-]?token|^token\Z|credential", re.IGNORECASE)


class InteropError(ServiceError):
    """A rule of fabric-interop/0.1 was violated; the message is one readable sentence."""


class UnknownJob(InteropError):
    def __init__(self, job_id: str):
        self.job_id = job_id
        super().__init__("unknown-job: no job %s here." % job_id)


# --- C3.4 trace context --------------------------------------------------------

def parse_traceparent(value: Any) -> Optional[Dict[str, str]]:
    """W3C Trace Context Level 1, lowercase hex; version ff and all-zero ids are invalid."""
    match = _TRACEPARENT.match(value) if isinstance(value, str) else None
    if not match:
        return None
    version, trace_id, span_id, flags = match.groups()
    if version == "ff" or set(trace_id) == {"0"} or set(span_id) == {"0"}:
        return None
    return {"version": version, "trace_id": trace_id, "span_id": span_id, "flags": flags}


def _span_id() -> str:
    while True:
        value = secrets.token_hex(8)
        if set(value) != {"0"}:
            return value


def child_traceparent(parent: Optional[str]) -> str:
    """A new span under `parent`; a missing or broken parent starts a new trace (W3C: restart)."""
    parsed = parse_traceparent(parent)
    trace_id = parsed["trace_id"] if parsed else secrets.token_hex(16)
    flags = parsed["flags"] if parsed else "01"
    return "00-%s-%s-%s" % (trace_id, _span_id(), flags)


def trace_ids(traceparent: Optional[str]) -> Dict[str, str]:
    """The `traceId`/`spanId` pair an event about this span carries (C3.4 c), or {}."""
    parsed = parse_traceparent(traceparent)
    return {"trace_id": parsed["trace_id"], "span_id": parsed["span_id"]} if parsed else {}


def _usage(usage: Any, nulls: bool = False) -> Dict[str, Any]:
    """A usage object as fabric-interop/0.1 reads it, or with `nulls` as 0.2 does: a number nobody measured is null and
    `partial` a boolean (DEC-0087)."""
    if not isinstance(usage, dict):
        raise InteropError("usage must be an object.")
    for key in ("inputTokens", "outputTokens", "wallMs"):
        if key not in usage:
            raise InteropError("usage.%s is required." % key)
    for key, value in usage.items():
        if nulls and key == "partial":
            if not isinstance(value, bool):
                raise InteropError("usage.partial must be a boolean.")
            continue
        if key not in USAGE_NUMBERS:
            raise InteropError("usage.%s is not a usage field." % key)
        if nulls and value is None:
            continue
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not numeric or value < 0 or (key != "costUsd" and not isinstance(value, int)):
            raise InteropError("usage.%s must be a non-negative %s." % (key, "number" if key == "costUsd" else "integer"))
    if nulls and usage_findings(usage, ""):
        raise InteropError("usage.partial is false while a number is null: an unknown number makes the usage partial (FAC-SEM-119).")
    return dict(usage)


# --- C3.2 limits and uncertain effects (DEC-0087) ------------------------------------------
# #region job-limits-kit, docs: plugins/fabric-agent-adapter/skills/building-fabric-services/references/interop.md#limits-and-uncertain-effects
# The contract's src/job-limits.ts, answer for answer (test/fixtures/contract/job-limit-vectors.json). Every function
# here answers and never raises on malformed input.

QUOTA_EXHAUSTED = "quota-exhausted"
#: DEC-0104: a refusal at a job's start; a job it ended is malformed, so a caller answers it `invalid`.
QUEUE_FULL = "queue-full"
OUTCOME_UNKNOWN = "outcome-unknown"
LIMIT_REACHED = "limit-reached"
INTEROP_NULL_USAGE = "fabric-interop/0.2"
#: The revisions this kit reads, named in a request's `_meta.protocols` (DEC-0067, DEC-0087).
PROTOCOLS_READ = ("fabric-interop/0.1", INTEROP_NULL_USAGE)
USAGE_NUMBERS = ("inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens", "costUsd", "wallMs")
_UTC_INSTANT = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-5][0-9])(?:\.([0-9]{1,3}))?Z\Z")
_PAUSE = re.compile(r"^quota-exhausted(?: until ([^ \t\n\r]+?))?(?:: ([ \t\n\r]*[^ \t\n\r][\s\S]*))?\Z")
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9-]{1,63}\Z")
_MAX_STATUS_MESSAGE = 500
_MAX_ERROR_MESSAGE = 2000
_ABSENT = object()


def _code_points(value: str) -> int:
    """JSON Schema's length: code points. A Python str holds code points, a lone surrogate counting once as in JavaScript."""
    return len(value)


def _own(value: Any, key: str) -> Any:
    return value.get(key, _ABSENT) if isinstance(value, dict) else _ABSENT


from fabric_time import days_from_civil as _days_from_civil  # noqa: E402 - the core's (FAA-65)


def utc_time(value: Any) -> Optional[int]:
    """A UTC instant (`interop-common#/$defs/utcInstant`) as milliseconds since the epoch, or None: the pattern and a
    day that exists, as the contract's strictTime reads it."""
    match = _UTC_INSTANT.match(value) if isinstance(value, str) else None
    if not match:
        return None
    year, month, day, hour, minute, second = (int(part) for part in match.groups()[:6])
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if not 1 <= month <= 12 or not 1 <= day <= days[month - 1] or hour > 23 or minute > 59:
        return None
    millis = int((match.group(7) or "").ljust(3, "0"))
    return ((_days_from_civil(year, month, day) * 24 + hour) * 60 + minute) * 60000 + second * 1000 + millis


def quota_data_ok(data: Any) -> bool:
    """Whether `data` is quota-exhausted's: closed, `retryable` a boolean, `resetsAt` a UTC instant, only with retryable true."""
    retryable = _own(data, "retryable")
    if not isinstance(data, dict) or not isinstance(retryable, bool):
        return False
    if any(name not in ("retryable", "resetsAt") for name in data):
        return False
    if "resetsAt" not in data:
        return True
    return retryable and utc_time(data["resetsAt"]) is not None


def _job_of(answer: Any) -> Optional[Dict[str, Any]]:
    job = _own(answer, "job")
    job_id = _own(job, "id")
    if not isinstance(job, dict) or not isinstance(job_id, str) or not job_id or _own(job, "status") not in JOB_STATES:
        return None
    return job


def read_job_pause(answer: Any) -> Dict[str, Any]:
    """Whether a fabric.job.get answer ({job}) is a job a limit paused: working, its statusMessage `quota-exhausted` or
    `quota-exhausted until <UTC instant>`, either optionally followed by `: <text>`. One that starts quota-exhausted and
    breaks the grammar is malformed."""
    job = _job_of(answer)
    message = _own(job, "statusMessage")
    if job is None or job.get("status") != "working" or not isinstance(message, str) or not message.startswith(QUOTA_EXHAUSTED):
        return {"paused": False}
    match = _PAUSE.match(message)
    if not match or _code_points(message) > _MAX_STATUS_MESSAGE:
        return {"paused": False, "malformed": True}
    until = match.group(1)
    if until is None:
        return {"paused": True}
    return {"paused": True, "resetsAt": until} if utc_time(until) is not None else {"paused": False, "malformed": True}


def job_caller_action(answer: Any, now: Any = _ABSENT) -> Dict[str, Any]:
    """What a caller does with one fabric.job.get or fabric.job.cancel answer at `now`, a UTC instant: poll, wait, answer,
    done, cancelled, resend (under the same key), person, reconcile, failed or invalid. Never "submit anew"."""
    at = utc_time(now)
    job = _job_of(answer)
    if at is None or job is None:
        return {"action": "invalid"}
    status = job["status"]
    if status == "working":
        pause = read_job_pause(answer)
        if "malformed" in pause:
            return {"action": "invalid"}
        if not pause["paused"]:
            return {"action": "poll"}
        if "resetsAt" not in pause:
            return {"action": "wait"}
        return {"action": "wait", "notBefore": pause["resetsAt"]} if utc_time(pause["resetsAt"]) > at else {"action": "poll"}
    if status in ("input_required", "completed", "cancelled"):
        return {"action": {"input_required": "answer", "completed": "done", "cancelled": "cancelled"}[status]}
    error = _own(job, "error")
    code = _own(error, "code")
    message = _own(error, "message")
    code_ok = (isinstance(code, str) and bool(_ERROR_CODE.match(code))) or _is_integer(code)
    shape_ok = isinstance(error, dict) and all(name in ("code", "message", "data") for name in error)
    if not shape_ok or not code_ok or not isinstance(message, str) or not message or _code_points(message) > _MAX_ERROR_MESSAGE:
        return {"action": "invalid"}
    if code == QUEUE_FULL:
        return {"action": "invalid"}
    if code == OUTCOME_UNKNOWN:
        return {"action": "reconcile"}
    if code == LIMIT_REACHED:
        return {"action": "person"}
    if code != QUOTA_EXHAUSTED:
        return {"action": "failed"}
    data = _own(error, "data")
    if not quota_data_ok(data):
        return {"action": "invalid"}
    if not data["retryable"]:
        return {"action": "person"}
    if "resetsAt" in data and utc_time(data["resetsAt"]) > at:
        return {"action": "resend", "notBefore": data["resetsAt"]}
    return {"action": "resend"}


def _is_integer(value: Any) -> bool:
    """JavaScript's Number.isInteger for a JSON value."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and value == value and value not in (float("inf"), float("-inf")) and value == int(value)


def intent_idempotency_key(intent: Any) -> Optional[str]:
    """The idempotency key of an intent {agentId, capability, input, request?}: a UUID of version 8 from the first 16
    bytes of the SHA-256 of its RFC 8785 form. The same intent gives the same key on every resend and machine; None
    for another shape or an input with no RFC 8785 form."""
    import fabric_delegation as _fd  # noqa: E402 - beside this file: RFC 8785
    names = ("agentId", "capability", "input", "request")
    if not isinstance(intent, dict) or any(name not in names for name in intent):
        return None
    agent_id, capability, given = intent.get("agentId"), intent.get("capability"), intent.get("input")
    if not isinstance(agent_id, str) or not agent_id or not isinstance(capability, str) or not capability or not isinstance(given, dict):
        return None
    form = {"agentId": agent_id, "capability": capability, "input": given}
    if "request" in intent:
        request = intent["request"]
        if not isinstance(request, str) or not request or _code_points(request) > 256:
            return None
        form["request"] = request
    try:
        canonical = _fd.jcs(form)
    except (TypeError, ValueError, RecursionError):
        return None
    raw = bytearray(hashlib.sha256(canonical.encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x80
    raw[8] = (raw[8] & 0x3F) | 0x80
    hexed = raw.hex()
    return "%s-%s-%s-%s-%s" % (hexed[:8], hexed[8:12], hexed[12:16], hexed[16:20], hexed[20:])


def reads_null_usage(request_meta: Any) -> bool:
    """Whether a provider may write null and partial in usage toward this caller: its _meta.protocols names fabric-interop/0.2."""
    protocols = _own(request_meta, "protocols")
    return isinstance(protocols, list) and INTEROP_NULL_USAGE in protocols


def request_meta(traceparent: Optional[str] = None, decision: Any = None) -> Dict[str, Any]:
    """A request's `_meta` from this kit as a caller: its trace, the interop revisions it reads (DEC-0087) and, for a
    relayed action, the operator's decision (DEC-0121 AP-2; build one with fabric_actions.operator_decision). A
    decision travels here only, never in a tool's arguments; one decision.schema.json refuses raises InteropError."""
    meta: Dict[str, Any] = {"protocols": list(PROTOCOLS_READ)}
    if parse_traceparent(traceparent):
        meta["traceparent"] = traceparent
    if decision is not None:
        if not decision_shape(decision):
            raise InteropError("The decision is not one decision.schema.json reads; it is not sent.")
        meta["decision"] = dict(decision)
    return meta


def action_gate(action: Any, *, tier: Any, caller: Any, meta: Any = None, target: Optional[str] = None,
                elicited: bool = False, approval: Any = None, action_digest: Optional[str] = None,
                human_step_url: Optional[str] = None, now: Any = None) -> Dict[str, Any]:
    """One call of a declared action, before its handler runs (DEC-0121 AP-2, AP-4): fabric_actions.action_decision over
    the call's `_meta.decision` (read from `meta` only, never from arguments, decision D11), the service's authenticated
    `caller` (fabric_actions.action_caller), `target` (the object the call acts on), `elicited` (the service's own
    record of an accepted elicitation), `approval` (verify_approval's accepted outcome), `action_digest`,
    `human_step_url` and `now` (RFC 3339). Answers {ok: True, record, decision}, `decision` being the one taken as the
    operator's (None otherwise), or {ok: False, refusal} in the DL-19 form (fabric_delegation.refusal_tool_result
    sends it); a service's own fault is the refusal unknown-state with `fault` beside it for the service's log."""
    import fabric_delegation as _fd  # noqa: E402 - beside this file: DL-19
    inputs: Dict[str, Any] = {"action": action, "tier": tier, "caller": caller, "elicited": elicited is True, "now": now}
    if isinstance(meta, dict) and "decision" in meta:
        inputs["decision"] = meta["decision"]
    for name, value in (("target", target), ("approval", approval), ("actionDigest", action_digest), ("humanStepUrl", human_step_url)):
        if value is not None:
            inputs[name] = value
    answer = action_decision(inputs)
    if answer.get("ok") is True:
        record = answer["recordAs"]
        taken = isinstance(record, dict) and record.get("via") == "relayed-instruction"
        return {"ok": True, "record": record, "decision": inputs["decision"] if taken else None}
    out: Dict[str, Any] = {"ok": False, "refusal": _fd.refusal_from_action(answer)}
    if "fault" in answer:
        out["fault"] = answer["fault"]
    return out


def action_refusal_tool_result(answer: Any, traceparent: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The tools/call result a service's own MCP server answers for an action_decision answer: None when the action
    takes the call, else DL-19's refusal as structuredContent with isError true (DEC-0121)."""
    import fabric_delegation as _fd  # noqa: E402 - beside this file: DL-19
    refusal = _fd.refusal_from_action(answer)
    return None if refusal is None else _fd.refusal_tool_result(refusal, traceparent=traceparent)


def usage_findings(usage: Any, at: str) -> List[Dict[str, str]]:
    """FAC-SEM-119 on a usage: partial false asserts every number known, so it stands beside no null."""
    if not isinstance(usage, dict) or usage.get("partial", _ABSENT) is not False:
        return []
    unknown = [name for name in USAGE_NUMBERS if name in usage and usage[name] is None]
    if not unknown:
        return []
    return [{"code": "FAC-SEM-119", "instancePath": "%s/partial" % at,
             "message": "partial is false while %s is null: an unknown number makes the usage partial" % ", ".join(unknown)}]


def usage_toward(usage: Any, request_meta: Any = None) -> Dict[str, Any]:
    """The usage a provider writes toward a caller (the gate): toward a reader of fabric-interop/0.2, null for a number
    nobody measured and partial true beside it; toward any other, the measured lower bound (null as 0, no partial)."""
    if reads_null_usage(request_meta):
        checked = _usage(usage, nulls=True)
        if any(checked.get(name, 0) is None for name in USAGE_NUMBERS) and "partial" not in checked:
            checked["partial"] = True
        return checked
    if not isinstance(usage, dict):
        raise InteropError("usage must be an object.")
    lower = {key: (0 if value is None else value) for key, value in usage.items() if key != "partial"}
    return _usage(lower)


def _job_findings(value: Any) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    if "malformed" in read_job_pause(value):
        findings.append({"code": "FAC-SEM-119", "instancePath": "/job/statusMessage",
                         "message": "a working job's message that starts quota-exhausted reads `quota-exhausted`, `quota-exhausted until <UTC instant>`, then optionally `: <text>`, at most 500 characters"})
    error = _own(_own(value, "job"), "error")
    data = _own(error, "data")
    resets_at = _own(data, "resetsAt")
    if _own(error, "code") == QUOTA_EXHAUSTED and isinstance(resets_at, str) and utc_time(resets_at) is None:
        findings.append({"code": "FAC-SEM-119", "instancePath": "/job/error/data/resetsAt", "message": "resetsAt is a UTC instant on a day that exists"})
    result = _own(_own(value, "job"), "result")
    findings.extend(usage_findings(_own(result, "usage"), "/job/result/usage"))
    return findings


def job_limit_rules(kind: str, value: Any) -> Optional[List[Dict[str, str]]]:
    """FAC-SEM-119 (kinds interop-job, usage and result) and FAC-SEM-120 (kind job-caller, {answer, now, action}: the
    act equals job_caller_action's). None for another kind."""
    if kind == "interop-job":
        return _job_findings(value)
    if kind == "usage":
        return usage_findings(value, "")
    if kind == "result":
        return usage_findings(_own(value, "usage"), "/usage")
    if kind == "job-caller":
        expected = job_caller_action(_own(value, "answer"), _own(value, "now"))
        if json.dumps(_own(value, "action"), sort_keys=True, default=str) == json.dumps(expected, sort_keys=True):
            return []
        return [{"code": "FAC-SEM-120", "instancePath": "/action", "message": "the caller answers %s as jobCallerAction does" % json.dumps(expected, separators=(",", ":"))}]
    return None


def pause_message(resets_at: Optional[str] = None, text: Optional[str] = None) -> str:
    """A paused job's statusMessage in the pause grammar; raises InteropError for one a reader would call malformed."""
    message = QUOTA_EXHAUSTED + ("" if resets_at is None else " until %s" % resets_at) + ("" if text is None else ": %s" % text)
    if "malformed" in read_job_pause({"job": {"id": "x", "status": "working", "statusMessage": message}}):
        raise InteropError("A pause reads quota-exhausted [until <UTC instant, Z, at most 3 fraction digits>][: <text>], at most 500 characters.")
    return message


def intent_digest(capability: str, arguments: Any) -> str:
    """What a key is kept beside (FAA-77): the SHA-256 of the RFC 8785 form of [capability, input], so a key admits
    only the intent it was first sent with. An input with no RFC 8785 form is refused."""
    import fabric_delegation as _fd  # noqa: E402 - beside this file: RFC 8785
    try:
        return "sha256:" + hashlib.sha256(_fd.jcs([capability, arguments]).encode("utf-8")).hexdigest()
    except (TypeError, ValueError, RecursionError):
        raise InteropError("A job's input with an idempotency key needs a JSON form (RFC 8785).") from None


def repeated_key_decision(job: Any, now: Any, limit_holds: Optional[bool] = None, approval_granted: bool = False) -> str:
    """The provider's answer to a repeated key: "run" (the same intent runs again, once) or "same" (answer with that job).
    A quota-exhausted job runs again once the limit no longer holds: `limit_holds` False when the provider knows it, else
    retryable with its reset passed at `now`; a limit-reached job once its approval is granted; anything else, and
    outcome-unknown above all, never."""
    if not isinstance(job, dict) or job.get("status") != "failed":
        return "same"
    error = _own(job, "error")
    code = _own(error, "code")
    if code == LIMIT_REACHED:
        return "run" if approval_granted is True else "same"
    if code != QUOTA_EXHAUSTED:
        return "same"
    if limit_holds is not None:
        return "run" if limit_holds is False else "same"
    data = _own(error, "data")
    at = utc_time(now)
    if not quota_data_ok(data) or not data["retryable"] or at is None:
        return "same"
    return "run" if "resetsAt" not in data or utc_time(data["resetsAt"]) <= at else "same"
# #endregion job-limits-kit
