#!/usr/bin/env python3
"""Reference kit for the fabric-interop/0.1 extension: how agents are called.

Standard library only, Python 3.9+. It sits beside fabric_service.py and uses it for
atomic, private writes. Every function implements one rule of the extension and names
it, so a service that calls these functions inherits the rule:

- C3.1 a capability is served as the MCP tool of its own name, annotations from its effect;
- C3.2 long work is a job: a stable id, fabric.job.get / fabric.job.cancel, a result envelope;
- C3.3 a question for a person is an elicitation (form mode, never a secret; URL mode for those);
- C3.4 every answer is a child span of the caller's traceparent, and so is every event.

Normative source: fabric-agent-contract docs/specification/interop.md (DEC-0016, rulings DEC-0017).
"""

# #region interop-kit — docs: plugins/fabric-agent-adapter/skills/building-fabric-services/references/interop.md#the-kit

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import secrets
import sys
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_service as _fs  # noqa: E402
from fabric_base import store_lock  # noqa: E402 - one lock per store path (R3)

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


class InteropError(_fs.ServiceError):
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


# --- C3.1 capabilities as tools --------------------------------------------------

def expected_annotations(effect: str, idempotency: str) -> Dict[str, bool]:
    """effect none -> readOnlyHint; delete|merge|deploy|change-policy -> destructiveHint; idempotency required -> idempotentHint."""
    hints: Dict[str, bool] = {}
    if effect == "none":
        hints["readOnlyHint"] = True
    if effect in ("delete", "merge", "deploy", "change-policy"):
        hints["destructiveHint"] = True
    if idempotency == "required":
        hints["idempotentHint"] = True
    return hints


def job_tool_output_schema(output_schema: Dict[str, Any]) -> Dict[str, Any]:
    """DEC-0017: a job-backed tool's outputSchema is oneOf[result envelope, job handle], self-contained,
    so structuredContent always conforms; the manifest's capability keeps the pure output schema."""
    return {"type": "object",
            "oneOf": [{"type": "object", "required": list(ENVELOPE_REQUIRED), "properties": {"output": output_schema}},
                      JOB_HANDLE_SCHEMA]}


def require_object_root(name: str, output_schema: Any) -> None:
    """DEC-0018 (FAC-SEM-023): an outputSchema is rooted at type object. MCP requires it, and a client
    may reject the WHOLE tools/list when one tool's outputSchema is, say, a bare oneOf."""
    if not isinstance(output_schema, dict) or output_schema.get("type") != "object":
        raise InteropError("Tool %s: an outputSchema must have root type \"object\"." % name)


def is_job_capability(capability: Dict[str, Any]) -> bool:
    block = (capability.get("extensions") or {}).get(EXTENSION_KEY) or {}
    return capability.get("job") is True or block.get("job") is True


def tool_for_capability(capability: Dict[str, Any], input_schema: Dict[str, Any], output_schema: Dict[str, Any],
                        title: Optional[str] = None) -> Dict[str, Any]:
    """The MCP tool for one manifest capability: its name, its input schema as it is, derived annotations,
    and its output schema — wrapped in the job union when the capability is a job (DEC-0017)."""
    require_object_root(capability["name"], output_schema)
    tool: Dict[str, Any] = {
        "name": capability["name"],
        "inputSchema": input_schema,
        "outputSchema": job_tool_output_schema(output_schema) if is_job_capability(capability) else output_schema,
        "annotations": expected_annotations(capability.get("effect", ""), capability.get("idempotency", "")),
    }
    if capability.get("description"):
        tool["description"] = capability["description"]
    if title:
        tool["title"] = title
    return tool


def tool_result(structured: Any, *, is_error: bool = False, traceparent: Optional[str] = None) -> Dict[str, Any]:
    """A tools/call result: structuredContent plus its JSON as text, for clients that read only text."""
    result: Dict[str, Any] = {
        "resultType": "complete",
        "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)}],
        "structuredContent": structured,
        "isError": is_error,
    }
    if traceparent:
        result["_meta"] = {"traceparent": traceparent}
    return result


def unknown_job_result(job_id: str, traceparent: Optional[str] = None) -> Dict[str, Any]:
    """C3.2: fabric.job.get for an unknown id answers isError with unknown-job, never a fresh job."""
    return tool_result({"error": {"code": "unknown-job", "message": "No job %s here." % job_id}},
                       is_error=True, traceparent=traceparent)


# --- C3.2 the result envelope ------------------------------------------------------

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


def result_envelope(*, outcome: str, done: List[Dict[str, Any]], proof: List[Dict[str, Any]], scope: Dict[str, Any],
                    not_verified: List[Dict[str, Any]], output: Any, usage: Dict[str, Any], producer: Dict[str, Any],
                    artifacts: Optional[List[Dict[str, Any]]] = None, traceparent: Optional[str] = None,
                    result_id: Optional[str] = None, created_at: Optional[str] = None,
                    request_meta: Any = None) -> Dict[str, Any]:
    """The full result envelope (contract result.schema.json, DEC-0011, DEC-0017): the same shape a
    synchronous call returns, with output, usage and, when the work was traced, its trace. `usage` may hold null for
    a number nobody measured; it is written as `usage_toward` the caller whose request `_meta` is `request_meta`."""
    if outcome not in OUTCOMES:
        raise InteropError("outcome must be one of %s." % ", ".join(OUTCOMES))
    for label, value in (("done", done), ("proof", proof), ("notVerified", not_verified), ("artifacts", artifacts or [])):
        if not isinstance(value, list):
            raise InteropError("%s must be a list, even when empty." % label)
    if outcome == "succeeded" and not_verified:
        raise InteropError("A succeeded result cannot keep unverified claims (FAC-SEM-001); report partial.")
    if not isinstance(scope, dict) or not isinstance(producer, dict):
        raise InteropError("scope and producer must be objects.")
    envelope: Dict[str, Any] = {
        "id": result_id or "urn:fabric:result:" + secrets.token_hex(12), "contractVersion": CONTRACT_VERSION,
        "outcome": outcome, "done": list(done), "proof": list(proof), "scope": dict(scope),
        "notVerified": list(not_verified), "artifacts": list(artifacts or []), "createdAt": created_at or _fs.now_iso(),
        "producer": dict(producer), "output": output, "usage": usage_toward(usage, request_meta),
    }
    if parse_traceparent(traceparent):
        envelope["trace"] = {"traceparent": traceparent}
    return envelope


# --- C3.2 limits and uncertain effects (DEC-0087) ------------------------------------------
# #region job-limits-kit, docs: plugins/fabric-agent-adapter/skills/building-fabric-services/references/interop.md#limits-and-uncertain-effects
# The contract's src/job-limits.ts, answer for answer (test/fixtures/contract/job-limit-vectors.json). Every function
# here answers and never raises on malformed input.

QUOTA_EXHAUSTED = "quota-exhausted"
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


def request_meta(traceparent: Optional[str] = None) -> Dict[str, Any]:
    """A request's `_meta` from this kit as a caller: its trace, and the interop revisions it reads (DEC-0087)."""
    meta: Dict[str, Any] = {"protocols": list(PROTOCOLS_READ)}
    if parse_traceparent(traceparent):
        meta["traceparent"] = traceparent
    return meta


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


# --- C3.3 awaiting a choice ------------------------------------------------------------

def form_request(message: str, properties: Dict[str, Dict[str, Any]], required: Optional[List[str]] = None) -> Dict[str, Any]:
    """An elicitation in form mode: a flat object of primitive fields, and never a secret (FAC-SEM-018)."""
    for field, schema in properties.items():
        words = " ".join(str(schema.get(key, "")) for key in ("title", "description", "format"))
        if _SECRET_WORDS.search(field) or _SECRET_WORDS.search(words):
            raise InteropError("Form mode cannot ask for %s: a secret goes through url_request." % field)
        if schema.get("type") not in ("string", "number", "integer", "boolean", "array"):
            raise InteropError("Form field %s must be a primitive (string, number, integer, boolean or an enum array)." % field)
    requested: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        requested["required"] = list(required)
    return {"method": "elicitation/create", "params": {"mode": "form", "message": message, "requestedSchema": requested}}


def choice_request(message: str, field: str, options: List[Any], title: Optional[str] = None) -> Dict[str, Any]:
    """A titled single-select: oneOf [{const, title}] — what Fabric turns into an interaction point."""
    schema: Dict[str, Any] = {"type": "string", "oneOf": [{"const": value, "title": label} for value, label in options]}
    if title:
        schema["title"] = title
    return form_request(message, {field: schema}, [field])


def url_request(message: str, url: str) -> Dict[str, Any]:
    """URL mode: the person opens `url` out of band; for credentials and payments. Put nothing sensitive in the URL."""
    if not url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        raise InteropError("A URL-mode request needs an https URL (or this machine's loopback).")
    return {"method": "elicitation/create", "params": {"mode": "url", "message": message, "url": url}}


# --- C3.2 jobs ---------------------------------------------------------------------

_SURROGATE = re.compile("[\ud800-\udfff]")


class JobStore:
    """Durable jobs, one private JSON file each under `directory`, written atomically and under the directory's lock.
    A job id survives a restart. The file holds the public `job` object exactly as fabric.job.get returns it, and a
    `private` part (the capability, its input, the trace) that is never returned; the Node kit uses the same format."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self._lock = store_lock(self.dir)

    def _path(self, job_id: str) -> Path:
        if not _JOB_ID.match(job_id or ""):
            raise UnknownJob(str(job_id))
        return self.dir / ("%s.json" % job_id)

    def _load(self, job_id: str) -> Dict[str, Any]:
        try:
            return json.loads(self._path(job_id).read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise UnknownJob(job_id) from None
        except ValueError:
            raise InteropError("Job %s is unreadable on disk." % job_id) from None

    def _save(self, record: Dict[str, Any]) -> Dict[str, Any]:
        record["job"]["updatedAt"] = _fs.now_iso()
        _fs.ensure_private_dir(self.dir)
        _fs.atomic_write(self._path(record["job"]["id"]), (json.dumps(record, ensure_ascii=False) + "\n").encode(), 0o600)
        return dict(record["job"])

    def create(self, capability: str, arguments: Any, traceparent: Optional[str] = None,
               poll_interval_ms: Optional[int] = None, delegation: Optional[Dict[str, Any]] = None, *,
               caller: Optional[str] = None, idempotency_key: Optional[str] = None, now: Optional[str] = None,
               limit_holds: Optional[bool] = None, approval_granted: bool = False) -> Dict[str, Any]:
        """Start a job; returns the handle a job-capable tool puts in structuredContent.

        With `idempotency_key` the key is kept per `caller` (the authenticated caller, DEC-0087) beside the digest of the
        intent (the capability and its input): a key that names a job of another intent raises `idempotency-conflict`;
        one that names a job of this intent starts nothing and raises InteropError, unless `repeat` would answer "run"
        (a limit no longer holds, an approval granted); then the key names the new job. A 0.40.0 key file: see `repeat`."""
        with self._lock:
            intent = None
            if idempotency_key is not None:
                intent = intent_digest(capability, arguments)
                decision = self.repeat(caller, idempotency_key, now if now is not None else _fs.now_iso(), limit_holds=limit_holds,
                                       approval_granted=approval_granted, capability=capability, arguments=arguments)
                if decision["decision"] == "conflict":
                    raise InteropError("idempotency-conflict: key %s names a job of another intent; send the same capability and input, or a new key." % idempotency_key)
                if decision["decision"] == "same":
                    raise InteropError("Key %s already names job %s; answer with that job (JobStore.repeat)." % (idempotency_key, decision["job"]["id"]))
            job_id = "job_" + secrets.token_hex(12)
            job: Dict[str, Any] = {"id": job_id, "status": "working"}
            if poll_interval_ms:
                job["pollIntervalMs"] = int(poll_interval_ms)
            private: Dict[str, Any] = {"capability": capability, "input": arguments,
                                       "traceparent": traceparent if parse_traceparent(traceparent) else None}
            if delegation:  # DEC-0039: who started it; only they read, cancel or answer it
                private["delegation"] = {"principal": delegation.get("principal"), "caller": delegation.get("caller")}
            self._save({"job": job, "private": private})
            if idempotency_key is not None:
                _fs.atomic_write(self._key_path(caller, idempotency_key), (json.dumps({"job": job_id, "intent": intent}) + "\n").encode(), 0o600)
            return {"job": {"id": job_id, "status": "working"}}

    def _key_path(self, caller: Optional[str], key: str) -> Path:
        if not isinstance(key, str) or not key:
            raise InteropError("An idempotency key is a non-empty string.")
        if _SURROGATE.search(key) or (isinstance(caller, str) and _SURROGATE.search(caller)):
            raise InteropError("An idempotency key and its caller are Unicode text; a lone surrogate is refused.")
        name = hashlib.sha256(json.dumps([caller, key], separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()  # as JSON.stringify writes it
        directory = self.dir / "keys"
        _fs.ensure_private_dir(directory)
        return directory / ("%s.json" % name)

    def _key_record(self, caller: Optional[str], key: str) -> Optional[Dict[str, Any]]:
        try:
            record = json.loads(self._key_path(caller, key).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except ValueError:
            record = None
        if not isinstance(record, dict):
            raise InteropError("Key %s is unreadable on disk." % key)
        return record

    def repeat(self, caller: Optional[str], key: str, now: Any, limit_holds: Optional[bool] = None,
               approval_granted: bool = False, *, capability: Optional[str] = None, arguments: Any = None) -> Dict[str, Any]:
        """The answer to a key this caller sent before (DEC-0087): {"decision": "new"|"same"|"run"|"conflict", "job"}. "same": answer with
        that job, never run it again (outcome-unknown above all); "run": the intent runs again, once; "conflict": given `capability` and
        its input `arguments`, the key was kept beside another intent (FAA-77). A 0.40.0 key file ({"job": id}) never answers "conflict"."""
        record = self._key_record(caller, key)
        if record is None:
            return {"decision": "new", "job": None}
        try:
            job = self.get(record["job"])
        except UnknownJob:
            return {"decision": "new", "job": None}
        except (KeyError, TypeError):
            raise InteropError("Key %s is unreadable on disk." % key) from None
        decision = repeated_key_decision(job, now, limit_holds, approval_granted)
        if capability is not None:
            intent = intent_digest(capability, arguments)
            if "intent" in record:
                decision = "conflict" if record["intent"] != intent else decision
            elif decision == "run":  # a 0.40.0 key runs only the intent its job stored (an input with no JSON form is refused)
                decision = "run" if intent_digest(*map(self.private(record["job"]).get, ("capability", "input"))) == intent else "same"
        return {"decision": decision, "job": job}

    def get(self, job_id: str) -> Dict[str, Any]:
        return dict(self._load(job_id)["job"])

    def private(self, job_id: str) -> Dict[str, Any]:
        return dict(self._load(job_id)["private"])

    def traceparent(self, job_id: str) -> Optional[str]:
        return self._load(job_id)["private"].get("traceparent")

    def _transition(self, job_id: str, status: str, **fields: Any) -> Dict[str, Any]:
        with self._lock:
            record = self._load(job_id)
            job = record["job"]
            if job["status"] in TERMINAL:
                raise InteropError("Job %s is already %s; a terminal job does not change." % (job_id, job["status"]))
            for key in ("inputRequests", "result", "error", "statusMessage"):
                job.pop(key, None)
            job["status"] = status
            job.update({key: value for key, value in fields.items() if value is not None})
            return self._save(record)

    def working(self, job_id: str, message: Optional[str] = None) -> Dict[str, Any]:
        return self._transition(job_id, "working", statusMessage=message)

    def request_input(self, job_id: str, input_requests: Dict[str, Dict[str, Any]], message: Optional[str] = None) -> Dict[str, Any]:
        """input_required with MCP elicitation requests, keyed; build them with choice_request / form_request / url_request."""
        if not input_requests:
            raise InteropError("input_required needs at least one input request.")
        for key, request in input_requests.items():
            if not _KEY.match(key) or request.get("method") != "elicitation/create":
                raise InteropError("Input request %r must be a keyed elicitation/create request." % key)
        return self._transition(job_id, "input_required", inputRequests=input_requests, statusMessage=message)

    def answer(self, job_id: str, input_responses: Dict[str, Any]) -> Dict[str, Any]:
        """Apply inputResponses to an input_required job; unknown keys are ignored (MCP Tasks rule).

        Returns the responses that matched; when any did, the job is working again."""
        with self._lock:
            job = self.get(job_id)
            if job["status"] != "input_required":
                return {}
            matched = {key: value for key, value in (input_responses or {}).items()
                       if key in job.get("inputRequests", {}) and isinstance(value, dict)
                       and value.get("action") in ("accept", "decline", "cancel")}
            if matched:
                self.working(job_id)
            return matched

    def complete(self, job_id: str, envelope: Dict[str, Any]) -> Dict[str, Any]:
        """The envelope carries the job's trace, authoritative for the stored result (DEC-0017); one that names
        another span is refused, so fabric.job.get's _meta and the envelope always agree (FAC-SEM-022)."""
        if not isinstance(envelope, dict) or not set(ENVELOPE_REQUIRED) <= set(envelope):
            raise InteropError("A completed job carries the full result envelope; build it with result_envelope.")
        stored = self.traceparent(job_id)
        given = (envelope.get("trace") or {}).get("traceparent")
        ids = lambda value: ((parse_traceparent(value) or {}).get("trace_id"), (parse_traceparent(value) or {}).get("span_id"))
        if stored and given and ids(given) != ids(stored):
            raise InteropError("Job %s ran in span %s; its result names another trace." % (job_id, stored))
        if stored and not given:
            envelope = dict(envelope, trace={"traceparent": stored})
        return self._transition(job_id, "completed", result=envelope)

    def fail(self, job_id: str, code: Any, message: str, data: Any = None) -> Dict[str, Any]:
        error: Dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return self._transition(job_id, "failed", error=error)

    def pause(self, job_id: str, resets_at: Optional[str] = None, text: Optional[str] = None) -> Dict[str, Any]:
        """A job a limit paused and its provider will resume (DEC-0087): working, its statusMessage in the pause grammar,
        and pollIntervalMs reaching the reset within its cap of one hour."""
        message = pause_message(resets_at, text)
        wait = utc_time(resets_at) - utc_time(_fs.now_iso()) if resets_at is not None else 0
        # One write, after the terminal check: a terminal job does not change, pollIntervalMs included (finding 11).
        return self._transition(job_id, "working", statusMessage=message,
                                pollIntervalMs=int(min(wait, 3600000)) if wait > 0 else None)

    def quota_exhausted(self, job_id: str, message: str, retryable: bool, resets_at: Optional[str] = None) -> Dict[str, Any]:
        """A job a limit stopped and its provider will not resume: failed, quota-exhausted, data {retryable, resetsAt?}."""
        data: Dict[str, Any] = {"retryable": retryable}
        if resets_at is not None:
            data["resetsAt"] = resets_at
        if not quota_data_ok(data):
            raise InteropError("quota-exhausted data is {retryable: boolean, resetsAt?: UTC instant}, resetsAt only with retryable true.")
        return self.fail(job_id, QUOTA_EXHAUSTED, message, data)

    def outcome_unknown(self, job_id: str, message: str, data: Any = None) -> Dict[str, Any]:
        """A job whose effect may have happened and that its provider cannot observe: failed, outcome-unknown. Its key is
        never run again; only an observed result settles it."""
        return self.fail(job_id, OUTCOME_UNKNOWN, message, data)

    def cancel(self, job_id: str) -> Dict[str, Any]:
        return self._transition(job_id, "cancelled")


# --- a minimal MCP tool server (streamable HTTP, JSON responses) ------------------------

class CallContext:
    """What a tool handler gets: the child span it runs in, and a way to start a job."""

    def __init__(self, server: "McpToolServer", tool: str, arguments: Any, traceparent: str,
                 delegation: Optional[Dict[str, Any]] = None):
        self.server = server
        self.tool = tool
        self.arguments = arguments
        self.traceparent = traceparent
        # DEC-0039: the accepted delegation (principal, caller, chain, claims) when the server has a gate.
        self.delegation = delegation

    def start_job(self, poll_interval_ms: Optional[int] = None) -> Dict[str, Any]:
        if self.server.jobs is None:
            raise InteropError("This server has no job store.")
        handle = self.server.jobs.create(self.tool, self.arguments, self.traceparent, poll_interval_ms, self.delegation)
        self.server.job_started(handle["job"]["id"], self)
        return handle


Handler = Callable[[Any, CallContext], Any]
OnInput = Callable[[str, Dict[str, Any], CallContext], None]

JOB_REQUEST_SCHEMA = {"type": "object", "required": ["id"], "additionalProperties": False, "properties": {
    "id": {"type": "string", "minLength": 1, "maxLength": 128},
    "inputResponses": {"type": "object"}}}


NAMED_METHODS = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}
HEADER_MISMATCH = -32020  # the code the official 2026-07-28 server SDK answers a header/body mismatch with


_SENTINEL = ("=?base64?", "?=")


def encode_header_value(value: str) -> str:
    """A body value as an HTTP header value, by MCP 2026-07-28 Streamable HTTP "Value Encoding": as
    it is when it is printable ASCII without leading or trailing whitespace, otherwise — and for a
    plain value that itself looks like the sentinel — `=?base64?<base64 of its UTF-8>?=`."""
    plain = (all(0x20 <= ord(c) <= 0x7E for c in value) and value == value.strip(" ")
             and not (value.startswith(_SENTINEL[0]) and value.endswith(_SENTINEL[1])))
    if plain:
        return value
    return _SENTINEL[0] + base64.b64encode(value.encode("utf-8")).decode("ascii") + _SENTINEL[1]


def decode_header_value(value: str) -> Optional[str]:
    """The body value a header carries, decoding the Base64 sentinel; None for a header value with
    invalid characters or a sentinel that is not valid Base64 of UTF-8 (a server rejects both)."""
    if value.startswith(_SENTINEL[0]) and value.endswith(_SENTINEL[1]) and len(value) >= len(_SENTINEL[0]) + len(_SENTINEL[1]):
        try:
            return base64.b64decode(value[len(_SENTINEL[0]):-len(_SENTINEL[1])], validate=True).decode("utf-8")
        except ValueError:  # binascii.Error and UnicodeDecodeError are both ValueErrors
            return None
    if any(not (0x20 <= ord(c) <= 0x7E or c == "\t") for c in value):
        return None
    return value


def mcp_header_problem(message: Any, headers: Any) -> Optional[str]:
    """MCP 2026-07-28 Streamable HTTP mirrors the body in `Mcp-Method` (every request and
    notification) and `Mcp-Name` (`params.name` or `params.uri` of tools/call, prompts/get,
    resources/read). A server MUST reject a mismatch; a request that declares 2026-07-28 must
    carry them. Earlier revisions may omit them, but what they send must still agree.
    `headers` is any case-insensitive mapping with `.get` (http.server's message, a dict)."""
    if not isinstance(message, dict) or headers is None:
        return None
    def header(name: str) -> Optional[str]:
        value = headers.get(name) if hasattr(headers, "get") else None
        if value is None and isinstance(headers, dict):
            value = next((v for k, v in headers.items() if k.lower() == name.lower()), None)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        return None if value is None else str(value)
    declared = header("MCP-Protocol-Version") == MCP_REVISION
    method = message.get("method")
    sent = header("Mcp-Method")
    if sent is None and declared:
        return "the body names method %s but the required Mcp-Method header is absent" % method
    if sent is not None and sent != method:
        return "Mcp-Method %s disagrees with the body's method %s" % (sent, method)
    field = NAMED_METHODS.get(str(method))
    if field:
        params = message.get("params")
        value = params.get(field) if isinstance(params, dict) else None
        named = header("Mcp-Name")
        if named is None and declared:
            return "the body carries params.%s but the required Mcp-Name header is absent" % field
        if named is not None:
            decoded = decode_header_value(named)
            if decoded is None:
                return "Mcp-Name is malformed: invalid characters or a broken =?base64?…?= value"
            if decoded != str(value):
                return "Mcp-Name disagrees with the body's params.%s" % field
    return None


def mcp_request_headers(method: str, params: Dict[str, Any]) -> Dict[str, str]:
    """The standard headers a 2026-07-28 client sends with one request."""
    out = {"MCP-Protocol-Version": MCP_REVISION, "Mcp-Method": method}
    field = NAMED_METHODS.get(method)
    if field and params.get(field) is not None:
        out["Mcp-Name"] = encode_header_value(str(params[field]))
    return out


class McpToolServer:
    """tools/list and tools/call for an MCP 2026-07-28 server, with fabric.job.get/cancel built in.

    `handle(message)` takes one JSON-RPC message and returns the response (None for a
    notification). Every result carries `_meta.traceparent`, a child span of the
    caller's. It is deliberately small: a service with a full MCP SDK should use that
    and keep only the helpers above.
    """

    def __init__(self, name: str, version: str, jobs: Optional[JobStore] = None,
                 on_job_started: Optional[Callable[[str, CallContext], None]] = None,
                 on_input: Optional[OnInput] = None,
                 authorize: Optional[Callable[[str, Any], Dict[str, Any]]] = None):
        # authorize(tool, headers, tier=) runs before every handler (fabric_delegation.delegation_gate, DEC-0039):
        # a refusal is answered in the DL-19 shape and the handler never runs. The built-in job tools are
        # gated by the job's own capability, and answered only for the principal and caller that started it.
        self._authorize = authorize
        self.info = {"name": name, "version": version}
        self.jobs = jobs
        self.tools: List[Dict[str, Any]] = []
        self.handlers: Dict[str, Handler] = {}
        self._on_job_started = on_job_started
        self._on_input = on_input

    def add_tool(self, tool: Dict[str, Any], handler: Handler) -> None:
        if tool["name"] in self.handlers:
            raise InteropError("Tool %s is served twice." % tool["name"])
        if "outputSchema" in tool:
            require_object_root(tool["name"], tool["outputSchema"])
        self.tools.append(tool)
        self.handlers[tool["name"]] = handler

    def job_started(self, job_id: str, ctx: CallContext) -> None:
        if self._on_job_started:
            self._on_job_started(job_id, ctx)

    def _job_tools(self) -> List[Dict[str, Any]]:
        if self.jobs is None:
            return []
        return [
            {"name": "fabric.job.get", "description": "The state of a job this agent started; answer an input request with inputResponses.",
             "inputSchema": JOB_REQUEST_SCHEMA, "annotations": {"idempotentHint": True}},
            {"name": "fabric.job.cancel", "description": "Ask this agent to stop a job it started.",
             "inputSchema": {"type": "object", "required": ["id"], "additionalProperties": False, "properties": {"id": JOB_REQUEST_SCHEMA["properties"]["id"]}},
             "annotations": {"idempotentHint": True}},
        ]

    @staticmethod
    def _error(rid: Any, code: int, message: str) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}

    def handle(self, message: Any, headers: Any = None, tier: str = "T2") -> Optional[Dict[str, Any]]:
        """One JSON-RPC message. Pass the HTTP request headers so the 2026-07-28 standard headers
        are checked (`mcp_header_problem`); a mismatch answers HEADER_MISMATCH even for a
        notification, so the transport can return HTTP 400. `tier` is the caller's origin for the
        authorize gate (DL-25: T0 local and authenticated by the service's floor, T1 an enrolled
        machine of the owner, T2 anything else); a gate never requires a token from T0 or T1."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return self._error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid request.")
        problem = mcp_header_problem(message, headers)
        if problem:
            return self._error(message.get("id"), HEADER_MISMATCH, "Bad Request: the request headers and body disagree: " + problem)
        if "id" not in message:
            return None  # a notification gets no response
        rid = message["id"]
        params = {} if message.get("params") is None else message["params"]
        meta = params.get("_meta") if isinstance(params, dict) else None
        meta = {} if meta is None else meta
        if not isinstance(params, dict) or not isinstance(meta, dict):  # finding 17: answered, never a crash
            return self._error(rid, -32602, "params and params._meta are JSON objects.")
        span = child_traceparent(meta.get("traceparent"))
        method = message["method"]
        if method == "initialize":
            asked = params.get("protocolVersion")
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": asked if asked in HANDSHAKE_REVISIONS else MCP_REVISION,
                "capabilities": {"tools": {"listChanged": False}}, "serverInfo": self.info}}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": rid, "result": {}}
        if method == "server/discover":
            return {"jsonrpc": "2.0", "id": rid, "result": {"resultType": "complete", "capabilities": {"tools": {}},
                                                             "serverInfo": self.info, "_meta": {"traceparent": span}}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": rid, "result": {"resultType": "complete", "tools": self.tools + self._job_tools(),
                                                             "_meta": {"traceparent": span}}}
        if method != "tools/call":
            return self._error(rid, -32601, "Method %s is not served here." % method)
        name = params.get("name")
        arguments = {} if params.get("arguments") is None else params["arguments"]
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return self._error(rid, -32602, "A tool call names its tool as a string and passes its arguments as a JSON object.")
        if name in ("fabric.job.get", "fabric.job.cancel") and self.jobs is not None:
            verdict = None
            if self._authorize is not None:
                job_id = str(arguments.get("id", ""))
                try:
                    private = self.jobs.private(job_id)
                except UnknownJob:
                    return {"jsonrpc": "2.0", "id": rid, "result": unknown_job_result(job_id, traceparent=span)}
                verdict = self._authorize(private["capability"], headers, tier=tier)
                owner = private.get("delegation")
                if verdict.get("ok") and owner and (owner.get("principal"), owner.get("caller")) != (verdict.get("principal"), verdict.get("caller")):
                    verdict = {"ok": False, "code": "scope-not-granted", "detail": "job-of-another-caller"}
                if not verdict.get("ok"):
                    import fabric_delegation as _fd  # noqa: E402 - only a gated server needs it
                    return {"jsonrpc": "2.0", "id": rid, "result": _fd.refusal_tool_result(verdict, traceparent=span)}
            return {"jsonrpc": "2.0", "id": rid, "result": self._job_call(name, arguments, span, verdict)}
        handler = self.handlers.get(name)
        if handler is None:
            return self._error(rid, -32602, "Unknown tool: %s." % name)
        delegation = None
        if self._authorize is not None:
            verdict = self._authorize(name, headers, tier=tier)
            if not verdict.get("ok"):
                import fabric_delegation as _fd  # noqa: E402 - only a gated server needs it
                return {"jsonrpc": "2.0", "id": rid, "result": _fd.refusal_tool_result(verdict, traceparent=span)}
            delegation = verdict
        try:
            structured = handler(arguments, CallContext(self, name, arguments, span, delegation))
        except InteropError as exc:
            return {"jsonrpc": "2.0", "id": rid, "result": tool_result({"error": {"code": "tool-error", "message": str(exc)}}, is_error=True, traceparent=span)}
        return {"jsonrpc": "2.0", "id": rid, "result": tool_result(structured, traceparent=span)}

    def _job_call(self, name: str, arguments: Dict[str, Any], span: str,
                  delegation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        job_id = str(arguments.get("id", ""))
        try:
            job_span = self.jobs.traceparent(job_id) or span
            state = self.jobs.get(job_id)
            job_span = ((state.get("result") or {}).get("trace") or {}).get("traceparent") or job_span
            if name == "fabric.job.cancel":
                state = self.jobs.get(job_id)
                if state["status"] not in TERMINAL:
                    try:
                        state = self.jobs.cancel(job_id)
                    except InteropError:  # it ended meanwhile: answer as it ended
                        state = self.jobs.get(job_id)
                return tool_result({"job": state}, traceparent=job_span)
            responses = arguments.get("inputResponses")
            if responses:
                matched = self.jobs.answer(job_id, responses)
                if matched and self._on_input:
                    private = self.jobs.private(job_id)
                    self._on_input(job_id, matched, CallContext(self, private["capability"], private["input"], job_span, delegation))
            return tool_result({"job": self.jobs.get(job_id)}, traceparent=job_span)
        except UnknownJob:
            return unknown_job_result(job_id, traceparent=span)


__all__ = [name for name in dir() if not name.startswith("_")]
# #endregion interop-kit
