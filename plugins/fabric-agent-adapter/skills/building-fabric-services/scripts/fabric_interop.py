#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
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

import difflib
import hashlib
import json
import math
from pathlib import Path
import re
import secrets
import sys
import time
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fabric_service as _fs  # noqa: E402
from fabric_base import store_lock  # noqa: E402 - one lock per store path (R3)
from fabric_actions import action_caller, readable_action  # noqa: E402 - DEC-0121
from fabric_mandate import EFFECT_CLASSES, OPERATOR_SOURCE_PROTOCOL, is_agent_id  # noqa: E402 - DEC-0125, DEC-0126
from fabric_jsvalue import real_number as _real_number  # noqa: E402 - the core's (FAA-65)
from fabric_time import format_rfc3339  # noqa: E402 - the core's (FAA-65)
from fabric_page_links import (  # noqa: E402 - DEC-0123
    PageLinkError, dashboards_link, input_request_link_findings, page_link_findings, parse_dashboards_link)

from fabric_interop_rules import (  # noqa: E402,F401 - the rule layer (FAA-92)
    _days_from_civil,
    UNREADABLE_PROJECT,
    kept_step,
    mandate_spend,
    PROTOCOL,
    EXTENSION_KEY,
    MCP_REVISION,
    HANDSHAKE_REVISIONS,
    CONTRACT_VERSION,
    JOB_STATES,
    OUTCOMES,
    ENVELOPE_REQUIRED,
    JOB_HANDLE_SCHEMA,
    TERMINAL,
    _TRACEPARENT,
    _JOB_ID,
    _KEY,
    _SECRET_WORDS,
    InteropError,
    UnknownJob,
    parse_traceparent,
    _span_id,
    child_traceparent,
    trace_ids,
    _usage,
    QUOTA_EXHAUSTED,
    QUEUE_FULL,
    OUTCOME_UNKNOWN,
    LIMIT_REACHED,
    INTEROP_NULL_USAGE,
    PROTOCOLS_READ,
    USAGE_NUMBERS,
    _UTC_INSTANT,
    _PAUSE,
    _ERROR_CODE,
    _MAX_STATUS_MESSAGE,
    _MAX_ERROR_MESSAGE,
    _ABSENT,
    _code_points,
    _own,
    utc_time,
    quota_data_ok,
    _job_of,
    read_job_pause,
    job_caller_action,
    _is_integer,
    intent_idempotency_key,
    reads_null_usage,
    request_meta,
    job_step,
    action_gate,
    action_refusal_tool_result,
    authority_config_problem,
    authority_declaration,
    authority_gate_inputs,
    usage_findings,
    usage_toward,
    _job_findings,
    job_limit_rules,
    pause_message,
    intent_digest,
    repeated_key_decision,
    NAMED_METHODS,
    UNREADABLE_AGENT,
    identified_agent,
    HEADER_MISMATCH,
    encode_header_value,
    decode_header_value,
    mcp_header_problem,
    mcp_request_headers,
)

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
    """URL mode: the person opens `url` out of band; for credentials and payments. Put nothing sensitive in the URL.
    A page of this service goes as its open_link (`page_answer`, DEC-0123 PL-4); a raw loopback address and a
    `fabric-dashboards:` link outside the grammar are refused here, when the request is built (FAC-SEM-143)."""
    if not isinstance(url, str):
        raise InteropError("A URL-mode request needs an https URL or Fabric Dashboards' open_link (DEC-0123 PL-4).")
    findings = page_link_findings(url, "/params/url", "the URL-mode request")
    if findings:
        raise InteropError(findings[0]["message"])
    if not url.startswith("https://") and not parse_dashboards_link(url)["ok"]:
        raise InteropError("A URL-mode request needs an https URL or Fabric Dashboards' open_link (DEC-0123 PL-4).")
    return {"method": "elicitation/create", "params": {"mode": "url", "message": message, "url": url}}


def page_answer(service: str, instance: str, path: Optional[str] = None, http_url: Optional[str] = None) -> Dict[str, Any]:
    """A tool answer that hands a person one of this service's pages (DEC-0123 PL-4): `{"open_link"}`, the page's
    Fabric Dashboards link, and `http_url`, its raw address, only as a diagnostic beside it (never judged as the
    action). Raises InteropError for an id, instance or path the open_link grammar refuses."""
    try:
        answer: Dict[str, Any] = {"open_link": dashboards_link(service, instance, path)}
    except PageLinkError as refused:
        raise InteropError("No open_link for %s.%s: %s (DEC-0123 PL-1)." % (service, instance, refused)) from None
    if http_url is not None:
        answer["http_url"] = http_url
    return answer


# --- C3.2 jobs: the job store lives in fabric_interop_jobs ------------------------------

from fabric_interop_jobs import JobStore, _SURROGATE  # noqa: E402,F401 - the job store (C3.2)


# --- a minimal MCP tool server (streamable HTTP, JSON responses) ------------------------

class CallContext:
    """What a tool handler gets: the child span it runs in, and a way to start a job.

    DEC-0121: `tier` is the caller's (DL-25), `caller` the identity the service authenticated (decision D9), `meta`
    the request's `_meta`. For a tool registered with an action, `record` is action_decision's recordAs: "caller"
    (the caller's own act) or {by, via, caller}, the act to put in the service's audit record, and `decision` the
    operator's decision it took (its `instruction` stays in that record, never in events or a page another party
    reads), else None. `input_records` maps each answered input request to its record when input_actions is on.
    DEC-0125: `mandate` is the operator's mandate the call was taken under (record `via: mandate`), else None.
    DEC-0126: `record` carries `source` when the decision or the mandate does (OA-6); like `instruction` it stays in the
    service's own audit record, never an event, a usage report, a log line or a page another party reads (OA-7)."""

    def __init__(self, server: "McpToolServer", tool: str, arguments: Any, traceparent: str,
                 delegation: Optional[Dict[str, Any]] = None, *, tier: Optional[str] = None, caller: Optional[str] = None,
                 meta: Optional[Dict[str, Any]] = None, record: Any = None, decision: Optional[Dict[str, Any]] = None,
                 input_records: Optional[Dict[str, Any]] = None, mandate: Optional[Dict[str, Any]] = None,
                 caller_agent: Optional[str] = None):
        self.server = server
        self.tool = tool
        self.arguments = arguments
        self.traceparent = traceparent
        # DEC-0039: the accepted delegation (principal, caller, chain, claims) when the server has a gate.
        self.delegation = delegation
        self.tier, self.caller, self.meta = tier, caller, {} if meta is None else meta
        self.record, self.decision, self.input_records = record, decision, input_records
        self.mandate = mandate
        # FAA-135: the caller's agent id the service authenticated (the delegation's caller, else identify_agent's).
        delegated = (delegation or {}).get("caller")
        self.caller_agent = caller_agent if caller_agent is not None else (delegated if isinstance(delegated, str) and delegated else None)

    def start_job(self, poll_interval_ms: Optional[int] = None) -> Dict[str, Any]:
        if self.server.jobs is None:
            raise InteropError("This server has no job store.")
        handle = self.server.jobs.create(self.tool, self.arguments, self.traceparent, poll_interval_ms, self.delegation)
        try:
            self.server.job_started(handle["job"]["id"], self)
        except InteropError as exc:  # a refused start: the job it created ends with it, never left working (FAA-196 (28))
            self.server.jobs.fail(handle["job"]["id"], "tool-error", str(exc)[:_MAX_ERROR_MESSAGE] or "The job's start was refused.")
            raise
        return handle

    def approval_step(self, job_id: str, key: str, request: Dict[str, Any], *, effect: str, spend_usd: Any = None,
                      project: Optional[str] = None, message: Optional[str] = None) -> Any:
        """The job's own approval step `key` (interop C3.3, DEC-0125): on a server with agent_id, the mandate this call
        carried (`_meta.mandate`) is read for it (job_step). Covered: answers the record (`via: mandate`, `source` when
        the mandate carries one) and asks nothing; the job goes on as the operator's decision. Otherwise the job waits
        input_required on `request`, its message naming the part not covered (or `message`), and answers None; the step
        is kept so an answer's `_meta.mandate` that covers it is read when input_actions is on. Any fault job_step answers
        (mandate-capability-missing, MJ-1, or the server clock's now-unreadable) goes to on_fault under the job's
        capability. The step is read under that capability, the name the job was created under (FAA-179), which is the
        tool's own unless the handler created the job under another name with `server.jobs.create`."""
        if self.server.jobs is None:
            raise InteropError("This server has no job store.")
        key = str.__str__(key) if isinstance(key, str) else key  # a (str, Enum) key reads as its str (FAA-196 (30))
        step: Dict[str, Any] = {"message": None}
        stored = self.server.jobs.private(job_id).get("capability")
        capability = stored if isinstance(stored, str) else self.tool
        if self.server.agent_id is not None:
            caller = self.caller_agent
            carried = self.meta.get("mandate")
            if carried is None and "mandate" in self.meta:
                carried = {}  # a null mandate is present and unreadable, as the answer reads it; never "none" (FAA-178)
            step = job_step(carried, tier=self.tier, now=format_rfc3339(self.server._clock() * 1000),
                            self_id=self.server.agent_id, capability=capability, key=key, effect=effect, caller_agent=caller,
                            spend_usd=spend_usd, project=project)
            if step["covered"]:
                return step["record"]
            self.server._fault(capability, step)  # the start hears it as the answer does, under the same name (MJ-1)
        kept = {"effect": effect, "spendUsd": spend_usd, "project": project}  # request_input keeps it as the gate reads it
        self.server.jobs.request_input(job_id, {key: request}, step["message"] or message, steps={key: kept})
        return None


Handler = Callable[[Any, CallContext], Any]
OnInput = Callable[[str, Dict[str, Any], CallContext], None]

JOB_REQUEST_SCHEMA = {"type": "object", "required": ["id"], "additionalProperties": False, "properties": {
    "id": {"type": "string", "minLength": 1, "maxLength": 128},
    "inputResponses": {"type": "object"}}}


# --- compact MCP: two doors, search and execute (FAA-356, agents database R33 O15, D-72) ----------------------------
# The operator, 2026-11-18: an MCP server lists two doors, `<domain>.search` and `<domain>.execute`; a capability is
# listed beside them only on a measured case. Every capability stays served, declared and probed one by one.

COMPACT_META = "ai.passioncode.fabric/compact"  # the door a compact tool is: "search" or "execute"
COMPACT_RETIRED_META = "ai.passioncode.fabric/retired"  # on a call by a name off the listing: {since, replacedBy}
COMPACT_LIMIT = 5  # a listing of at most this many tools is short enough as it is
DIRECT_MAX = 3  # direct tools beside the two doors, each on a measured case
DIRECT_MIN_CALLS, DIRECT_MIN_SHARE = 20, 0.3  # the measured case: >= 20 calls and >= 30 % of the service's calls
_COMPACT_DOMAIN = re.compile(r"^[a-z][a-z0-9_-]{0,62}(\.[a-z0-9_-]{1,63}){0,3}\Z")
_RETIRED_DATE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\Z")
JOB_TOOL_NAMES = ("fabric.job.get", "fabric.job.cancel")  # seats beside the doors with no measurement (D-72)


def direct_problem(name: str, measured: Any) -> Optional[str]:
    """Why `measured` ({calls, total, window}) is not a measured case for a direct tool, or None (D-72)."""
    if not isinstance(measured, dict):
        return "%s: a direct tool needs its measurement {calls, total, window}" % name
    calls, total, window = measured.get("calls"), measured.get("total"), measured.get("window")
    if not all(type(v) is int and v >= 0 for v in (calls, total)) or not (isinstance(window, str) and window.strip()):
        return "%s: the measurement names calls and total as counts and its window" % name
    if calls > total or calls < DIRECT_MIN_CALLS or total == 0 or calls / total < DIRECT_MIN_SHARE:
        return "%s: %d of %d calls is not a measured case (at least %d calls and %d %% of the service's calls)" % (
            name, calls, total, DIRECT_MIN_CALLS, int(DIRECT_MIN_SHARE * 100))
    return None


class _NamedHeaders:
    """The request's headers with Mcp-Name naming the operation `execute` runs (case-insensitive, read only)."""

    def __init__(self, headers: Any, name: str):
        self._headers, self._name = headers, encode_header_value(name)

    def get(self, key: str, default: Any = None) -> Any:
        if str(key).lower() == "mcp-name":
            return self._name
        value = self._headers.get(key) if hasattr(self._headers, "get") else None
        if value is None and isinstance(self._headers, dict):
            value = next((v for k, v in self._headers.items() if str(k).lower() == str(key).lower()), None)
        return default if value is None else value

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __contains__(self, key: Any) -> bool:
        return self.get(key) is not None

    def items(self) -> List[Any]:
        source = list(self._headers.items()) if hasattr(self._headers, "items") else []
        return [(k, v) for k, v in source if str(k).lower() != "mcp-name"] + [("Mcp-Name", self._name)]


_UNREADABLE = object()  # what a service's spend or project function answers when it raised
_UNREADABLE_PROJECT = UNREADABLE_PROJECT  # never a member of a mandate's projects, so a scoped mandate refuses


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
                 authorize: Optional[Callable[[str, Any], Dict[str, Any]]] = None, *,
                 identify: Optional[Callable[[Any, str], Optional[str]]] = None,
                 approve: Optional[Callable[[str, Dict[str, Any], Any, str], Optional[Dict[str, Any]]]] = None,
                 elicited: Optional[Callable[[str, Dict[str, Any], Optional[str]], bool]] = None,
                 input_actions: bool = False, clock: Callable[[], float] = time.time,
                 on_fault: Optional[Callable[[str, str], None]] = None, agent_id: Optional[str] = None,
                 identify_agent: Optional[Callable[[Any, str], Optional[str]]] = None,
                 authority: Optional[Dict[str, Any]] = None):
        # authorize(tool, headers, tier=) runs before every handler (fabric_delegation.delegation_gate, DEC-0039):
        # a refusal is answered in the DL-19 shape and the handler never runs. The built-in job tools are
        # gated by the job's own capability, and answered only for the principal and caller that started it.
        # DEC-0121: a tool added with an action runs action_gate after authorize and before its handler.
        # identify(headers, tier) names the caller the service authenticated when no delegation did (D9; else
        # local:T0 / local:T1); approve(tool, arguments, headers, digest) answers verify_approval's outcome for an
        # approval the call presented, or None; elicited(tool, arguments, caller) is True only on the service's own
        # record of an accepted elicitation. input_actions=True gates each answered input request as an action (D8).
        # on_fault(tool, fault) hears a service fault the caller only sees as unknown-state (e.g. caller-missing: an
        # action-gated server needs a tier, identify or authorize that names who calls), but for mandate-capability-missing
        # (MJ-1), which the caller reads as operator-decision-required naming it in data.detail.
        # DEC-0125: agent_id is this service's own agent id; with it the server reads a call's _meta.mandate for a
        # relayed action added with its effect (the chain must end in agent_id, and in the delegation's caller before
        # it when authorize accepted a token); without it a mandate is not read, as before. FAA-135:
        # identify_agent(headers, tier) names the agent id of a per-agent credential the service authenticated, read
        # when no delegation named a caller: the chain must hold it before agent_id (identified_agent reads its answer).
        # FAA-334: authority {levels, actionLevels, standing} is the service's level contexts and profile reading; the
        # gate then decides a level holder's word and a place's standing mandate itself (authority_extension declares it).
        if agent_id is not None and not is_agent_id(agent_id):
            raise InteropError("agent_id is this service's agent id (a lower-case id, optionally .instance; DEC-0125).")
        problem = None if authority is None else authority_config_problem(authority)
        if problem is not None:
            raise InteropError("%s (DEC-0162, DEC-0166)." % problem)
        self.agent_id, self.authority = agent_id, authority
        self._authorize = authorize
        self._identify, self._approve, self._elicited, self._identify_agent = identify, approve, elicited, identify_agent
        self.input_actions, self._clock, self._on_fault = input_actions is True, clock, on_fault
        self.actions: Dict[str, Dict[str, Any]] = {}
        self.info = {"name": name, "version": version}
        self.jobs = jobs
        self.tools: List[Dict[str, Any]] = []
        self.handlers: Dict[str, Handler] = {}
        self._on_job_started = on_job_started
        self._on_input = on_input
        # DEC-0126 OA-7: a server that reads `source` (a decision's on a relayed action, a mandate's with agent_id) lists
        # operator-source/1 in its well-known protocols; well_known_protocols() hands the list to build_well_known.
        self.reads_source = agent_id is not None
        self.compact: Optional[Dict[str, Any]] = None  # FAA-356: serve_compact's {domain, direct}
        self.calls: Dict[str, int] = {}  # calls answered per tool name since the start, for search's `calls`

    def serve_compact(self, domain: str, direct: Any = None, retired: Optional[str] = None) -> None:
        """List two doors, `<domain>.search` and `<domain>.execute`, instead of one tool per capability (FAA-356,
        agents database R33 O15, decision D-72). Three seats beside the doors: the built-in job tools take theirs
        with no measurement while the server has a job store (D-72, until the contract folds them into execute);
        `direct` maps the rest, at most three in all, to their measured case {calls, total, window}: at least 20
        calls and 30 % of the service's calls. Every tool stays callable by its own name, so a client of the full
        listing keeps working; `retired` (YYYY-MM-DD), the day the full listing left tools/list, is what search
        answers as each such name's `retired` (R28). A server whose full listing holds five tools or fewer lists it
        as it is. Call it after the tools are added."""
        if not isinstance(domain, str) or not _COMPACT_DOMAIN.match(domain):
            raise InteropError("serve_compact: the domain is a lower-case name such as example-agent (FAA-356).")
        doors = {domain + ".search", domain + ".execute"}
        if doors & set(self.handlers) or doors & set(JOB_TOOL_NAMES):
            raise InteropError("serve_compact: a served tool already has the name %s." % " or ".join(sorted(doors)))
        if retired is not None and not (isinstance(retired, str) and _RETIRED_DATE.match(retired)):
            raise InteropError("serve_compact: retired is the day the full listing left tools/list, YYYY-MM-DD (R28).")
        direct = dict(direct or {})
        seats = DIRECT_MAX - len(self._job_tools())
        if len(direct) > seats:
            raise InteropError("serve_compact: at most %d direct tools beside the two doors%s (D-72)." % (
                seats, " and the two job tools" if self.jobs is not None else ""))
        for name, measured in direct.items():
            if name not in self.handlers or name in JOB_TOOL_NAMES:
                raise InteropError("serve_compact: %s is not a tool this server serves." % name)
            problem = direct_problem(name, measured)
            if problem:
                raise InteropError("serve_compact: " + problem + " (D-72).")
        self.compact = {"domain": domain, "direct": {k: dict(v) for k, v in direct.items()}, "retired": retired}

    def _full_listing(self) -> List[Dict[str, Any]]:
        return self.tools + self._job_tools()

    def listing(self) -> List[Dict[str, Any]]:
        """What tools/list answers: the full listing, or the direct tools, the job tools and the two doors when
        serve_compact was called and the full listing holds more than five tools."""
        full = self._full_listing()
        if self.compact is None or len(full) <= COMPACT_LIMIT:
            return full
        direct = [t for t in self.tools if t["name"] in self.compact["direct"]]
        return direct + self._job_tools() + self._door_tools()

    def _door_tools(self) -> List[Dict[str, Any]]:
        domain = self.compact["domain"]
        return [
            {"name": domain + ".search",
             "description": "Find what this agent can do: every operation with its purpose, input schema, gate (none, "
                            "relayed, human) and an example; query filters by words. Run one with %s.execute." % domain,
             "inputSchema": {"type": "object", "additionalProperties": False,
                             "properties": {"query": {"type": "string", "maxLength": 200,
                                                      "description": "Words every operation found must contain."}}},
             "annotations": {"readOnlyHint": True, "idempotentHint": True}, "_meta": {COMPACT_META: "search"}},
            {"name": domain + ".execute",
             "description": "Run one operation %s.search names, with its arguments; the same checks, gate and audit as "
                            "calling it by its own name." % domain,
             "inputSchema": {"type": "object", "required": ["operation"], "additionalProperties": False,
                             "properties": {"operation": {"type": "string", "minLength": 1, "maxLength": 128},
                                            "arguments": {"type": "object"},
                                            "idempotencyKey": {"type": "string", "minLength": 8, "maxLength": 128}}},
             "_meta": {COMPACT_META: "execute"}},
        ]

    def _operation(self, tool: Dict[str, Any]) -> Dict[str, Any]:
        """One operation as search answers it: the tool as the full listing serves it, its gate, an example and calls."""
        name = tool["name"]
        entry = self.actions.get(name)
        examples = (tool.get("inputSchema") or {}).get("examples")
        operation = dict(tool)
        operation.update({"gate": entry["action"]["gate"] if entry else "none",
                          "example": examples[0] if isinstance(examples, list) and examples else None,
                          "calls": self.calls.get(name, 0)})
        compact = self.compact or {}
        if name in (compact.get("direct") or {}):
            operation["direct"] = dict(compact["direct"][name])
        elif compact.get("retired") and name not in JOB_TOOL_NAMES:
            operation["retired"] = compact["retired"]  # its own name left tools/list that day and still answers (R28)
        return operation

    def _search(self, arguments: Dict[str, Any], span: str) -> Dict[str, Any]:
        query = arguments.get("query", "")
        if not isinstance(query, str) or len(query) > 200 or set(arguments) - {"query"}:
            return tool_result({"error": {"code": "invalid-arguments", "message": "search takes {query?: string}."}},
                               is_error=True, traceparent=span)
        words = query.lower().split()
        found = [self._operation(t) for t in self._full_listing()
                 if all(w in " ".join(str(t.get(k, "")) for k in ("name", "title", "description")).lower() for w in words)]
        return tool_result({"domain": self.compact["domain"], "operations": found, "total": len(self._full_listing())},
                           traceparent=span)

    def _execute(self, rid: Any, arguments: Dict[str, Any], headers: Any, tier: str,
                 meta: Dict[str, Any], span: str) -> Dict[str, Any]:
        """Re-enter tools/call with the operation's own name, so its authorize level, action gate, mandate and audit
        run as they do for a call by that name, never wider (DEC-0121 parity, D-72)."""
        def refuse(code: str, message: str, **extra: Any) -> Dict[str, Any]:
            return {"jsonrpc": "2.0", "id": rid, "result": tool_result(
                {"error": {"code": code, "message": message, **extra}}, is_error=True, traceparent=span)}
        operation, inner = arguments.get("operation"), arguments.get("arguments", {})
        key = arguments.get("idempotencyKey")
        if set(arguments) - {"operation", "arguments", "idempotencyKey"} or not isinstance(operation, str) \
                or not isinstance(inner, dict) or not (key is None or (isinstance(key, str) and 8 <= len(key) <= 128)):
            return refuse("invalid-arguments", "execute takes {operation: string, arguments?: object, idempotencyKey?: string}.")
        names = [t["name"] for t in self._full_listing()]
        if operation not in names:
            return refuse("unknown-operation", "%s is not an operation of this agent; %s.search lists them." % (
                operation, self.compact["domain"]), near=difflib.get_close_matches(operation, names, n=3, cutoff=0.5))
        if key is not None:
            schema = next(t for t in self._full_listing() if t["name"] == operation).get("inputSchema") or {}
            if "idempotencyKey" not in (schema.get("properties") or {}):
                return refuse("invalid-arguments", "%s takes no idempotencyKey; leave it out or pass the key its "
                                                   "arguments name." % operation)
            if inner.get("idempotencyKey", key) != key:
                return refuse("invalid-arguments", "idempotencyKey and arguments.idempotencyKey disagree.")
            inner = {**inner, "idempotencyKey": key}
        message = {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                   "params": {"name": operation, "arguments": inner, "_meta": meta}}
        return self.handle(message, None if headers is None else _NamedHeaders(headers, operation), tier=tier, _route="execute")

    def well_known_protocols(self, protocols: Any = ()) -> List[str]:
        """The well-known `protocols` (DEC-0067) a service on this server lists: `protocols` and, when it reads `source`
        (agent_id given, or a relayed action served), operator-source/1 (DEC-0126 OA-7), each once."""
        listed = list(protocols)
        if (self.reads_source or any(e["action"]["gate"] == "relayed" for e in self.actions.values())) \
                and OPERATOR_SOURCE_PROTOCOL not in listed:
            listed.append(OPERATOR_SOURCE_PROTOCOL)
        return listed

    def authority_extension(self) -> Optional[Dict[str, Any]]:
        """extensions/authority/0.1's value for build_well_known(extensions=), None without authority (FAA-334)."""
        return None if self.authority is None else authority_declaration(self.authority)

    def add_tool(self, tool: Dict[str, Any], handler: Handler, action: Optional[Dict[str, Any]] = None, *,
                 target: Any = None, human_step_url: Optional[str] = None, effect: Optional[str] = None,
                 spend: Any = None, project: Any = None, context: Any = None) -> None:
        """Serve a tool. `action` (DEC-0121 AP-1) is the declared action this tool performs, {id, title, tool, gate,
        humanStep?}, its `tool` this tool's name: the server runs action_gate before the handler. `target` names the
        object a call acts on: an argument's name, or a function of the arguments; `human_step_url` is the link of a
        `human` action's step (an https URL or a path on the service's origin, AP-4).

        DEC-0125, on a server with agent_id: `effect` is the action's effect class (governance's vocabulary), required
        for a relayed action, since a mandate covers a call by its effect; `spend` the service's own estimate of what a
        call spends, USD (a number, or a function of the arguments answering a number or None); `project` the project a
        call acts in (a name, or a function of the arguments). With authority (FAA-334), `context` is the call's context,
        `personal` or `org:<orgId>` (a name, or a function of the arguments), and a relayed action names its effect."""
        if tool["name"] in self.handlers:
            raise InteropError("Tool %s is served twice." % tool["name"])
        if self.compact is not None and tool["name"] in (self.compact["domain"] + ".search", self.compact["domain"] + ".execute"):
            raise InteropError("Tool %s is a door of the compact listing (FAA-356)." % tool["name"])
        if "outputSchema" in tool:
            require_object_root(tool["name"], tool["outputSchema"])
        if action is not None:
            if not readable_action(action) or action["tool"] != tool["name"]:
                raise InteropError("Tool %s: its action is not a declared action of this tool (DEC-0121)." % tool["name"])
            if action["id"] in {a["action"]["id"] for a in self.actions.values()}:
                raise InteropError("Action %s is declared twice." % action["id"])
            if action["gate"] == "human" and not (isinstance(human_step_url, str) and re.match(r"https://|/", human_step_url)):
                raise InteropError("Tool %s: a human step needs its link, an https URL or a path (DEC-0121 AP-4)." % tool["name"])
            if not (target is None or isinstance(target, str) or callable(target)):
                raise InteropError("Tool %s: target is an argument's name or a function of the arguments." % tool["name"])
            if (self.agent_id is not None or self.authority is not None) and action["gate"] == "relayed" \
                    and not (type(effect) is str and effect in EFFECT_CLASSES):
                raise InteropError("Tool %s: a relayed action on a server that reads mandates names its effect class (DEC-0125)." % tool["name"])
            if effect is not None and not (type(effect) is str and effect in EFFECT_CLASSES):
                raise InteropError("Tool %s: effect is one of %s." % (tool["name"], ", ".join(EFFECT_CLASSES)))
            if not (spend is None or callable(spend) or (isinstance(spend, (int, float)) and not isinstance(spend, bool))):
                raise InteropError("Tool %s: spend is a number of USD or a function of the arguments." % tool["name"])
            for label, value in (("project", project), ("context", context)):
                if not (value is None or isinstance(value, str) or callable(value)):
                    raise InteropError("Tool %s: %s is a name or a function of the arguments." % (tool["name"], label))
            self.actions[tool["name"]] = {"action": dict(action), "target": target, "url": human_step_url,
                                          "effect": effect, "spend": spend, "project": project, "context": context}
        self.tools.append(tool)
        self.handlers[tool["name"]] = handler

    def action_table(self) -> List[Dict[str, Any]]:
        """The declared actions in the order they were added: build_well_known(actions=) writes them (DEC-0121 AP-1)."""
        return [dict(entry["action"]) for entry in self.actions.values()]

    def _caller(self, headers: Any, tier: str, verdict: Optional[Dict[str, Any]]) -> Optional[str]:
        """D9: the delegation's caller when a gate accepted a token, else identify(headers, tier), else the local floor."""
        authenticated = (verdict or {}).get("caller")
        if not authenticated and self._identify is not None:
            authenticated = self._identify(headers, tier)
        return action_caller(tier, authenticated)

    def _caller_agent(self, headers: Any, tier: str, verdict: Optional[Dict[str, Any]]) -> Optional[str]:
        """FAA-135: the caller's agent id a mandate's chain is bound with: the delegation's caller when authorize accepted
        a token, else what identify_agent names (identified_agent; a hook that raises names UNREADABLE_AGENT), else
        None. Read only on a server with agent_id; never a name the call carries."""
        delegated = (verdict or {}).get("caller")
        if self.agent_id is None or (isinstance(delegated, str) and delegated):
            return delegated if self.agent_id is not None else None
        if self._identify_agent is None:
            return None
        try:
            return identified_agent(self._identify_agent(headers, tier))
        except Exception:  # noqa: BLE001 - the service's own hook: an id no chain holds, so a mandate is refused
            return UNREADABLE_AGENT

    def _gate_action(self, action: Dict[str, Any], name: str, arguments: Dict[str, Any], target: Any, url: Any,
                     headers: Any, tier: str, meta: Dict[str, Any], caller: Optional[str],
                     mandate: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """action_gate for one call: the approval the call presented, the digest of {tool, arguments}, the clock, and
        under DEC-0125 what a mandate is read with (`mandate`: self_id, effect, caller_agent, spend_usd, project)."""
        digest, approval = None, None
        if action["gate"] == "relayed":
            import fabric_delegation as _fd  # noqa: E402 - only an action-gated server needs it
            try:
                digest = _fd.action_digest({"tool": name, "arguments": arguments})
            except (TypeError, ValueError, RecursionError):  # no canonical form (a lone surrogate, a non-finite number,
                # nesting past the recursion limit), as intent_digest reads it: no digest to bind
                return {"ok": False, "invalid": "Invalid params: the arguments have no canonical form."}
            outcome = self._approve(name, arguments, headers, digest) if self._approve is not None else None
            if isinstance(outcome, dict) and outcome.get("ok") is True:
                approval = outcome
            elif isinstance(outcome, dict) and outcome.get("code") not in (None, "approval-required"):
                # DL-18: the presented approval's own refusal; an outcome that is not verify_approval's is the service's.
                readable = outcome.get("code") in _fd.REFUSAL_CODES and isinstance(outcome.get("detail"), str) and outcome["detail"]
                if readable:
                    return {"ok": False, "refusal": outcome}
                return {"ok": False, "refusal": {"ok": False, "code": "unknown-state", "detail": "service-fault"},
                        "fault": "approval-outcome-unreadable"}
        elicited = action["gate"] == "relayed" and self._elicited is not None and self._elicited(name, arguments, caller) is True
        return action_gate(action, tier=tier, caller=caller, meta=meta, target=target, elicited=elicited, approval=approval,
                           action_digest=digest, human_step_url=url, now=format_rfc3339(self._clock() * 1000), **(mandate or {}))

    def _mandate_inputs(self, entry: Dict[str, Any], arguments: Dict[str, Any], caller_agent: Optional[str]) -> Dict[str, Any]:
        """DEC-0125: what action_gate reads a mandate with, empty on a server without agent_id. The caller's agent id is
        _caller_agent's (the delegation's caller, else identify_agent's, FAA-135), never a name the call carries."""
        if self.agent_id is None:
            return {}
        spend, project = (self._read(entry.get(k), arguments) for k in ("spend", "project"))
        # The estimate is read as a double, as the contract does: an int past the float range is infinite, and an
        # estimate that is not a finite number reads as none, which a mandate's ceiling refuses (fail closed).
        number = _real_number(spend)  # by what it stores; a bool, a mock or not a number is none (seam reading 18)
        try:
            double = float(number) if number is not None else math.nan
        except OverflowError:
            double = math.inf
        spend = number
        finite = math.isfinite(double)  # the service's own number goes on when it is finite (25 stays 25)
        if project is _UNREADABLE or not (project is None or type(project) is str):  # an exact str, as the core compares
            project = _UNREADABLE_PROJECT  # a function that raised or named no exact str: a scoped mandate refuses
        return {"self_id": self.agent_id, "effect": entry.get("effect"),
                "caller_agent": caller_agent if isinstance(caller_agent, str) and caller_agent else None,
                # an estimate that raised or is not finite is none: a mandate with a ceiling then refuses (fail closed)
                "spend_usd": spend if finite else None,
                "project": project}  # None or an exact str, read once above: never re-decided into no project (unit r33)

    def _authority_inputs(self, entry: Dict[str, Any], arguments: Dict[str, Any], delegation: Any) -> Dict[str, Any]:
        """FAA-334: what action_gate reads levels and a profile with (authority_gate_inputs; mem and prof from the verified
        token's claims, never the call's), and on a server without agent_id the action's effect and project too."""
        if self.authority is None:
            return {}
        context = self._read(entry.get("context"), arguments)
        out = authority_gate_inputs(self.authority, entry["action"]["id"], context, (delegation or {}).get("claims"))
        if self.agent_id is None:  # _mandate_inputs reads them on a server with agent_id
            project = self._read(entry.get("project"), arguments)
            out.update(effect=entry.get("effect"), project=project if project is None or type(project) is str else _UNREADABLE_PROJECT)
        return out

    @staticmethod
    def _read(value: Any, arguments: Dict[str, Any]) -> Any:
        """A spend or project the service gave, or what its function answers; a function that raises answers _UNREADABLE."""
        try:
            return value(arguments) if callable(value) else value
        except Exception:  # noqa: BLE001 - the service's own code; the call is still answered
            return _UNREADABLE

    def _gate_inputs(self, arguments: Dict[str, Any], headers: Any, tier: str, meta: Dict[str, Any],
                     caller: Optional[str], agent: Optional[str] = None) -> Dict[str, Any]:
        """D8: each input request an answer would take is an action (id its key, tool fabric.job.get, gate relayed),
        one decision per call; the first refusal refuses the call and nothing is applied. DEC-0125: on a server with
        agent_id, a step approval_step kept is read under the call's `_meta.mandate` too (C3.3)."""
        job_id = str(arguments.get("id", ""))
        job = self.jobs.get(job_id)
        private = self.jobs.private(job_id)  # one read of the job's private part (unit reading 39)
        steps = private.get("steps") if isinstance(private.get("steps"), dict) else {}
        asked = job.get("inputRequests") if job["status"] == "input_required" and isinstance(job.get("inputRequests"), dict) else {}
        records: Dict[str, Any] = {}
        for key, value in arguments["inputResponses"].items():
            if key not in asked or not isinstance(value, dict) or value.get("action") not in ("accept", "decline", "cancel"):
                continue
            action = {"id": key, "title": "Answer %s" % key, "tool": "fabric.job.get", "gate": "relayed"}
            step, mandate = steps.get(key), {}
            if self.agent_id is not None and isinstance(step, dict):
                # A kept step's mandate is read as approval_step read it, under the job's own capability, which must
                # be a capability name (MJ-1); the action itself stays fabric.job.get, so it is a readable action.
                capability = private.get("capability")
                mandate = {"self_id": self.agent_id, "effect": step.get("effect"), "spend_usd": step.get("spendUsd"),
                           "project": step.get("project"), "caller_agent": agent if isinstance(agent, str) and agent else None,
                           "mandate_capability": capability if isinstance(capability, str) else None}
            gated = self._gate_action(action, "fabric.job.get", {"id": job_id, "inputResponses": {key: value}}, None, None,
                                      headers, tier, meta, caller, mandate)
            if not gated["ok"]:
                return dict(gated, capability=private.get("capability"))  # the one read names the fault (FAA-186)
            records[key] = gated["record"]
        return {"ok": True, "records": records}

    def _fault(self, tool: str, gated: Dict[str, Any]) -> None:
        """Hand a service fault to on_fault; the caller saw unknown-state (operator-decision-required naming it for
        mandate-capability-missing, MJ-1). A hook that raises is the service's."""
        if gated.get("fault") and self._on_fault is not None:
            try:
                self._on_fault(tool, str(gated["fault"]))
            except Exception:  # noqa: BLE001 - logging must not change the answer
                pass

    @staticmethod
    def _target(target: Any, arguments: Dict[str, Any]) -> Optional[str]:
        """The object a call acts on: the named argument, or what the service's function answers; a string or None."""
        try:
            value = target(arguments) if callable(target) else arguments.get(target) if isinstance(target, str) else None
        except Exception:  # noqa: BLE001 - a function that cannot read this call names no object
            return None
        return value if isinstance(value, str) else None

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

    def handle(self, message: Any, headers: Any = None, tier: str = "T2", *, _route: str = "name") -> Optional[Dict[str, Any]]:
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
            return {"jsonrpc": "2.0", "id": rid, "result": {"resultType": "complete", "tools": self.listing(),
                                                             "_meta": {"traceparent": span}}}
        if method != "tools/call":
            return self._error(rid, -32601, "Method %s is not served here." % method)
        name = params.get("name")
        arguments = {} if params.get("arguments") is None else params["arguments"]
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return self._error(rid, -32602, "A tool call names its tool as a string and passes its arguments as a JSON object.")
        if self.compact is not None and name == self.compact["domain"] + ".search":
            return {"jsonrpc": "2.0", "id": rid, "result": self._search(arguments, span)}
        if self.compact is not None and name == self.compact["domain"] + ".execute":
            return self._execute(rid, arguments, headers, tier, meta, span)
        if _route == "name" and self.compact is not None and self.compact.get("retired") and name in self.handlers \
                and name not in self.compact["direct"] and len(self._full_listing()) > COMPACT_LIMIT:
            # R28: a name off the listing keeps answering; its result says since when and what replaced it. In _meta,
            # never structuredContent, so a tool's outputSchema still holds (FAA-356, the base's patterns/compact-mcp).
            response = self.handle(message, headers, tier=tier, _route="retired")
            result = (response or {}).get("result")
            if isinstance(result, dict):
                result["_meta"] = dict(result.get("_meta") or {}, **{COMPACT_RETIRED_META: {
                    "since": self.compact["retired"], "replacedBy": self.compact["domain"] + ".execute"}})
            return response
        if name in self.handlers or (self.jobs is not None and name in ("fabric.job.get", "fabric.job.cancel")):
            self.calls[name] = self.calls.get(name, 0) + 1
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
            caller, agent, inputs = self._caller(headers, tier, verdict), self._caller_agent(headers, tier, verdict), None
            responses = arguments.get("inputResponses")
            if name == "fabric.job.get" and responses is not None and not isinstance(responses, dict):  # seam r37: never a crash
                return self._error(rid, -32602, "fabric.job.get takes inputResponses as a JSON object (interop C3.3).")
            if name == "fabric.job.get" and self.input_actions and isinstance(responses, dict) and responses:
                try:
                    inputs = self._gate_inputs(arguments, headers, tier, meta, caller, agent)
                except UnknownJob:
                    return {"jsonrpc": "2.0", "id": rid, "result": unknown_job_result(str(arguments.get("id", "")), traceparent=span)}
                if not inputs["ok"] and "invalid" in inputs:
                    return self._error(rid, -32602, inputs["invalid"])
                if not inputs["ok"]:
                    stored = inputs.get("capability")  # read once, by _gate_inputs (FAA-186)
                    self._fault(stored if isinstance(stored, str) else name, inputs)  # as the start heard it (FAA-179)
                    import fabric_delegation as _fd  # noqa: E402 - DL-19
                    return {"jsonrpc": "2.0", "id": rid, "result": _fd.refusal_tool_result(inputs["refusal"], traceparent=span)}
            context = {"tier": tier, "caller": caller, "meta": meta, "input_records": inputs["records"] if inputs else None,
                       "caller_agent": agent}
            return {"jsonrpc": "2.0", "id": rid, "result": self._job_call(name, arguments, span, verdict, context)}
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
        caller, gated, entry = self._caller(headers, tier, delegation), {"record": None, "decision": None}, self.actions.get(name)
        agent = self._caller_agent(headers, tier, delegation)
        if entry is not None:  # DEC-0121: after the authorize gate, before the handler
            gated = self._gate_action(entry["action"], name, arguments, self._target(entry["target"], arguments), entry["url"],
                                      headers, tier, meta, caller, {**self._mandate_inputs(entry, arguments, agent),
                                                                    **self._authority_inputs(entry, arguments, delegation)})
            if not gated["ok"] and "invalid" in gated:
                return self._error(rid, -32602, gated["invalid"])
            if not gated["ok"]:
                self._fault(name, gated)
                import fabric_delegation as _fd  # noqa: E402 - DL-19
                return {"jsonrpc": "2.0", "id": rid, "result": _fd.refusal_tool_result(gated["refusal"], traceparent=span)}
        context = CallContext(self, name, arguments, span, delegation, tier=tier, caller=caller, meta=meta,
                              record=gated["record"], decision=gated["decision"], mandate=gated.get("mandate"), caller_agent=agent)
        try:
            structured = handler(arguments, context)
        except InteropError as exc:
            return {"jsonrpc": "2.0", "id": rid, "result": tool_result({"error": {"code": "tool-error", "message": str(exc)}}, is_error=True, traceparent=span)}
        return {"jsonrpc": "2.0", "id": rid, "result": tool_result(structured, traceparent=span)}

    def _job_call(self, name: str, arguments: Dict[str, Any], span: str,
                  delegation: Optional[Dict[str, Any]] = None, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
            context = context or {}
            if responses and context.get("input_records") is not None:  # D8: only the keys the action gate took
                responses = {key: responses[key] for key in context["input_records"]}
            if responses:
                matched = self.jobs.answer(job_id, responses)
                if matched and self._on_input:
                    private = self.jobs.private(job_id)
                    try:
                        self._on_input(job_id, matched, CallContext(self, private["capability"], private["input"], job_span, delegation, **context))
                    except InteropError as exc:  # answered as the handler path answers one (FAA-196 (27))
                        return tool_result({"error": {"code": "tool-error", "message": str(exc)}}, is_error=True, traceparent=job_span)
            return tool_result({"job": self.jobs.get(job_id)}, traceparent=job_span)
        except UnknownJob:
            return unknown_job_result(job_id, traceparent=span)


__all__ = [name for name in dir() if not name.startswith("_")]
# #endregion interop-kit
