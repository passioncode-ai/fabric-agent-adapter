# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
"""The serving side and a bounded client of A2A 1.0 (FAA-10, DEC-0122): an Agent Card built from the service's
capabilities (`agent_card`, every skill an A2A `AgentSkill`, checked by `fabric_a2a.agent_card_findings` before it is
served), the JSON-RPC binding (`A2ABinding`: `SendMessage`, `SendStreamingMessage`, `GetTask`, `CancelTask`) mapped
onto the interop job store (`fabric_interop.JobStore`: a task is a job, a choice stop is `TASK_STATE_INPUT_REQUIRED`,
the result envelope an artifact), and `A2AClient` (`discover`, `call`, `get`, `cancel`) that reaches a peer only on an
origin the operator allowed, with its credential read from the environment `use_secret.py run` fills, never from a
file. The interface never takes the descriptor's token (DEC-0122 item 3): the card names its own scheme and the
service's `authorize` decides the caller. Part of the service kit (layer L4). Standard library only."""
from __future__ import annotations

import json
import os
import re
import secrets
import time
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))

from fabric_a2a import A2A_PROTOCOL_VERSION, A2A_SURFACE_PATH, agent_card_findings  # noqa: E402
from fabric_base import ServiceError  # noqa: E402
from fabric_interop import JobStore  # noqa: E402
from fabric_interop_rules import InteropError, UnknownJob  # noqa: E402
from fabric_http import request as http_request  # noqa: E402

#: The JSON-RPC binding's name in a card's `supportedInterfaces` (A2A 1.0).
JSONRPC_BINDING = "JSONRPC"
#: The JSON-RPC codes A2A 1.0 section 5.4 maps its errors to, and JSON-RPC 2.0's own.
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
TASK_NOT_FOUND, TASK_NOT_CANCELABLE, UNSUPPORTED_OPERATION, CONTENT_TYPE_NOT_SUPPORTED, VERSION_NOT_SUPPORTED = \
    -32001, -32002, -32004, -32005, -32009
#: The interop job status each A2A task state reads from.
TASK_STATES = {"working": "TASK_STATE_WORKING", "input_required": "TASK_STATE_INPUT_REQUIRED",
               "completed": "TASK_STATE_COMPLETED", "failed": "TASK_STATE_FAILED", "cancelled": "TASK_STATE_CANCELED"}
TERMINAL_STATES = ("TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED")
MAX_BODY = 1024 * 1024
_SKILL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class A2AError(ServiceError):
    """A refused A2A call or card; the message never carries a credential."""


def skill_from_capability(capability: Mapping[str, Any]) -> Dict[str, Any]:
    """An A2A `AgentSkill` from one capability ({name, description?, tags?, examples?, inputModes?, outputModes?}):
    its id is the capability's name, the id the contract's A2A peer profile names in `skillIds`."""
    name = capability.get("name") if isinstance(capability, Mapping) else None
    if not isinstance(name, str) or not _SKILL_ID.match(name):
        raise A2AError("a skill's id is the capability's name: letters, digits, '.', '_' or '-', at most 64")
    skill: Dict[str, Any] = {"id": name, "name": capability.get("title") or name,
                             "description": capability.get("description") or name,
                             "tags": list(capability.get("tags") or [name.split(".")[0]])}
    for key in ("examples", "inputModes", "outputModes"):
        if capability.get(key):
            skill[key] = list(capability[key])
    return skill


def agent_card(*, name: str, description: str, version: str, url: str, capabilities: Sequence[Mapping[str, Any]],
               security_schemes: Optional[Dict[str, Any]] = None, streaming: bool = False,
               extensions: Optional[List[Dict[str, Any]]] = None, remote: bool = False,
               descriptor_header: str = "Authorization") -> Dict[str, Any]:
    """The public Agent Card a service serves at `surfaces.a2a.path` (A2A 1.0): one JSON-RPC interface at `url` on the
    service's origin, one skill per capability. Raises A2AError when `agent_card_findings` finds anything, so a card
    that names a process member, a secret, the descriptor's token header or a required Fabric extension is never
    served. `security_schemes` names the interface's own scheme (never the descriptor's token)."""
    match = re.match(r"\A(https?://[^/?#]+)", url or "")
    card: Dict[str, Any] = {
        "name": name, "description": description, "version": version,
        "supportedInterfaces": [{"url": url, "protocolBinding": JSONRPC_BINDING, "protocolVersion": A2A_PROTOCOL_VERSION}],
        "capabilities": {"streaming": bool(streaming), "pushNotifications": False},
        "defaultInputModes": ["text/plain", "application/json"], "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [skill_from_capability(c) for c in capabilities],
    }
    if extensions:
        card["capabilities"]["extensions"] = [dict(e, required=False) for e in extensions]
    if security_schemes:
        card["securitySchemes"] = security_schemes
    findings = agent_card_findings(card, origin=match.group(1) if match else None, remote=remote,
                                   descriptor_header=descriptor_header)
    if findings:
        raise A2AError("the card is not served: %s" % "; ".join(f["message"] for f in findings))
    return card


def text_of(message: Any) -> str:
    """The text parts of an A2A message, joined by a line feed."""
    parts = message.get("parts") if isinstance(message, dict) else None
    return "\n".join(p["text"] for p in parts or [] if isinstance(p, dict) and isinstance(p.get("text"), str))


def data_of(message: Any) -> List[Any]:
    """The data parts of an A2A message."""
    parts = message.get("parts") if isinstance(message, dict) else None
    return [p["data"] for p in parts or [] if isinstance(p, dict) and "data" in p]


def agent_message(text: str, *, task_id: Optional[str] = None, context_id: Optional[str] = None,
                  data: Any = None) -> Dict[str, Any]:
    """An agent's A2A message: a text part, and a data part when `data` is given."""
    parts: List[Dict[str, Any]] = [{"text": text}]
    if data is not None:
        parts.append({"data": data})
    message: Dict[str, Any] = {"role": "ROLE_AGENT", "parts": parts, "messageId": "msg-" + secrets.token_hex(8)}
    if task_id:
        message["taskId"] = task_id
    if context_id:
        message["contextId"] = context_id
    return message


class TaskStart:
    """What a message handler gets: the message, its caller and `start(skill)`, which makes the job that is the task
    and returns its id; the service then runs the work and moves the job (working, request_input, complete, fail)."""

    def __init__(self, binding: "A2ABinding", message: Dict[str, Any], caller: Optional[str], context_id: str):
        self.binding, self.message, self.caller, self.context_id = binding, message, caller, context_id
        self.task_id: Optional[str] = None

    def start(self, skill: str) -> str:
        if skill not in self.binding.skills:
            raise A2AError("no skill %s on this card" % skill)
        handle = self.binding.jobs.create("a2a." + skill, {"a2a": {"message": self.message, "contextId": self.context_id,
                                                                   "caller": self.caller}})
        self.task_id = handle["job"]["id"]
        return self.task_id


Handler = Callable[[TaskStart], Optional[Dict[str, Any]]]


class A2ABinding:
    """The JSON-RPC binding over the interop job store. `handler(start)` answers a new message: it returns an agent
    message (`agent_message`) for a reply with no task, or calls `start.start(skill)` and returns None. `authorize`
    turns the request's headers into a caller (or None to refuse with HTTP 401); a task is read, answered or cancelled
    only by the caller that started it, any other gets TaskNotFound. `handle(body, headers)` returns (status, body)."""

    def __init__(self, jobs: JobStore, handler: Handler, *, skills: Sequence[str],
                 authorize: Callable[[Mapping[str, str]], Optional[str]], clock: Callable[[], float] = time.time):
        self.jobs, self.handler, self.skills, self.authorize, self.clock = jobs, handler, set(skills), authorize, clock

    def task(self, job_id: str, caller: Optional[str]) -> Dict[str, Any]:
        """The A2A Task a job reads as; UnknownJob when it is not an A2A job of this caller."""
        a2a = (self.jobs.private(job_id).get("input") or {}).get("a2a")
        if not isinstance(a2a, dict) or a2a.get("caller") != caller:
            raise UnknownJob(job_id)
        return task_of(self.jobs.get(job_id), a2a.get("contextId"))

    def handle(self, body: Any, headers: Mapping[str, str]) -> Tuple[int, Optional[Dict[str, Any]]]:
        lowered = {str(k).lower(): v for k, v in (headers or {}).items()}
        caller = self.authorize(lowered)
        if caller is None:
            return 401, None
        if isinstance(body, (bytes, bytearray)):
            if len(body) > MAX_BODY:
                return 413, None
            try:
                body = json.loads(bytes(body).decode("utf-8"))
            except ValueError:
                return 200, _error(None, PARSE_ERROR, "the body is not JSON")
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
            return 200, _error(body.get("id") if isinstance(body, dict) else None, INVALID_REQUEST, "not a JSON-RPC 2.0 request")
        rid = body.get("id")
        version = lowered.get("a2a-version")
        if version is not None and version.strip() != A2A_PROTOCOL_VERSION:
            return 200, _error(rid, VERSION_NOT_SUPPORTED, "this agent speaks A2A %s" % A2A_PROTOCOL_VERSION)
        params = body.get("params")
        if not isinstance(params, dict):
            return 200, _error(rid, INVALID_PARAMS, "params is an object")
        method = body["method"]
        try:
            if method in ("SendMessage", "SendStreamingMessage"):
                if method == "SendStreamingMessage":
                    return 200, _error(rid, UNSUPPORTED_OPERATION, "streaming is served by stream() as text/event-stream")
                return 200, _result(rid, self.send(params, caller))
            if method == "GetTask":
                return 200, _result(rid, self.task(str(params.get("id")), caller))
            if method == "CancelTask":
                return 200, _result(rid, self.cancel(str(params.get("id")), caller))
        except UnknownJob:
            return 200, _error(rid, TASK_NOT_FOUND, "no such task")
        except _NotCancelable:
            return 200, _error(rid, TASK_NOT_CANCELABLE, "the task has ended")
        except _BadParams as exc:
            return 200, _error(rid, INVALID_PARAMS, str(exc))
        except (A2AError, InteropError) as exc:
            return 200, _error(rid, INTERNAL_ERROR, "the agent could not take the message: %s" % exc)
        return 200, _error(rid, METHOD_NOT_FOUND, "no method %s here" % method[:64])

    def send(self, params: Dict[str, Any], caller: Optional[str]) -> Dict[str, Any]:
        message = params.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("parts"), list) or not message["parts"]:
            raise _BadParams("params.message is a message with parts")
        task_id = message.get("taskId")
        if isinstance(task_id, str) and task_id:
            return {"task": self._continue(task_id, message, caller)}
        context_id = message.get("contextId") if isinstance(message.get("contextId"), str) else "ctx-" + secrets.token_hex(8)
        start = TaskStart(self, message, caller, context_id)
        reply = self.handler(start)
        if start.task_id is not None:
            return {"task": self.task(start.task_id, caller)}
        if not isinstance(reply, dict):
            raise A2AError("the handler neither replied nor started a task")
        return {"message": dict(reply, contextId=context_id)}

    def _continue(self, task_id: str, message: Dict[str, Any], caller: Optional[str]) -> Dict[str, Any]:
        """A message to an input-required task answers its question: a data part {inputResponses} as fabric.job.get
        takes it, or plain text for a question with one field."""
        task = self.task(task_id, caller)
        if task["status"]["state"] != "TASK_STATE_INPUT_REQUIRED":
            raise _BadParams("the task waits for no answer")
        job = self.jobs.get(task_id)
        responses = next((d["inputResponses"] for d in data_of(message) if isinstance(d, dict) and isinstance(d.get("inputResponses"), dict)), None)
        if responses is None:
            responses = _text_answer(job.get("inputRequests") or {}, text_of(message))
        if not responses or not self.jobs.answer(task_id, responses):
            raise _BadParams("the answer names none of the task's questions")
        return self.task(task_id, caller)

    def cancel(self, task_id: str, caller: Optional[str]) -> Dict[str, Any]:
        task = self.task(task_id, caller)
        if task["status"]["state"] in TERMINAL_STATES:
            raise _NotCancelable()
        self.jobs.cancel(task_id)
        return self.task(task_id, caller)

    def stream(self, params: Dict[str, Any], caller: Optional[str], *, rid: Any = None, poll_s: float = 1.0,
               deadline_s: float = 300.0, sleep: Callable[[float], None] = time.sleep) -> Iterator[str]:
        """`SendStreamingMessage` as server-sent events: the task first, then a status update each time its state
        changes, ending at a terminal or input-required state or the deadline. Each event is one `data:` line holding
        a JSON-RPC response whose result is a StreamResponse."""
        first = self.send(params, caller)
        yield _event(rid, first)
        if "task" not in first:
            return
        task, end = first["task"], self.clock() + deadline_s
        while task["status"]["state"] not in TERMINAL_STATES + ("TASK_STATE_INPUT_REQUIRED",) and self.clock() < end:
            sleep(poll_s)
            now = self.task(task["id"], caller)
            if now["status"]["state"] != task["status"]["state"] or now.get("artifacts") != task.get("artifacts"):
                final = now["status"]["state"] in TERMINAL_STATES + ("TASK_STATE_INPUT_REQUIRED",)
                yield _event(rid, {"statusUpdate": {"taskId": now["id"], "contextId": now["contextId"],
                                                    "status": now["status"], "final": final}})
            task = now


class _NotCancelable(Exception):
    pass


class _BadParams(Exception):
    pass


def _text_answer(requests: Dict[str, Any], text: str) -> Optional[Dict[str, Any]]:
    if len(requests) != 1 or not text:
        return None
    key, request = next(iter(requests.items()))
    props = (((request.get("params") or {}).get("requestedSchema") or {}).get("properties") or {}) if isinstance(request, dict) else {}
    if len(props) != 1:
        return None
    return {key: {"action": "accept", "content": {next(iter(props)): text}}}


def task_of(job: Dict[str, Any], context_id: Optional[str]) -> Dict[str, Any]:
    """The A2A Task an interop job reads as: its state, a status message, the result envelope as an artifact."""
    state = TASK_STATES.get(job.get("status"), "TASK_STATE_UNSPECIFIED")
    status: Dict[str, Any] = {"state": state, "timestamp": job.get("updatedAt") or ""}
    text = job.get("statusMessage")
    if job.get("status") == "input_required":
        questions = [(r.get("params") or {}).get("message") for r in (job.get("inputRequests") or {}).values() if isinstance(r, dict)]
        status["message"] = agent_message(text or "; ".join(q for q in questions if isinstance(q, str)) or "an answer is needed",
                                          task_id=job["id"], context_id=context_id,
                                          data={"inputRequests": job.get("inputRequests")})
    elif job.get("status") == "failed":
        error = job.get("error") or {}
        status["message"] = agent_message(str(error.get("message") or "the task failed"), task_id=job["id"],
                                          context_id=context_id, data={"code": error.get("code")})
    elif text:
        status["message"] = agent_message(text, task_id=job["id"], context_id=context_id)
    task: Dict[str, Any] = {"id": job["id"], "contextId": context_id, "status": status}
    if job.get("status") == "completed":
        task["artifacts"] = [{"artifactId": "result", "name": "result", "parts": [{"data": job.get("result")}]}]
    return task


def _result(rid: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _event(rid: Any, result: Any) -> str:
    return "data: %s\n\n" % json.dumps(_result(rid, result), separators=(",", ":"), ensure_ascii=False)


def origin_of(url: str) -> str:
    """`scheme://host[:port]` of a URL, lower-cased, with a default port dropped; A2AError for anything else."""
    match = re.match(r"\A(https?)://([^/?#]+)", url or "", re.IGNORECASE)
    if not match or "@" in match.group(2):
        raise A2AError("a peer's address is an http(s) origin with no userinfo")
    scheme, host = match.group(1).lower(), match.group(2).lower()
    if (scheme, host.rsplit(":", 1)[-1]) in (("https", "443"), ("http", "80")) and ":" in host and not host.endswith("]"):
        host = host.rsplit(":", 1)[0]
    return "%s://%s" % (scheme, host)


class A2AClient:
    """A bounded A2A 1.0 client: every call has a deadline and a size cap (fabric_http), reaches only an origin in
    `allow_origins` (the operator's list), and sends a credential only when `credential_env` names an environment
    variable that holds one (`use_secret.py run --vault-only <project> <NAME> -- <command>` fills it; never a file
    beside the agent). It never follows a redirect and never retries a SendMessage."""

    def __init__(self, allow_origins: Sequence[str], *, credential_env: Optional[str] = None,
                 header: str = "Authorization", scheme: Optional[str] = "Bearer", deadline_s: float = 30.0,
                 max_bytes: int = MAX_BODY, transport: Any = None, insecure: bool = False):
        self.allowed = {origin_of(o) for o in allow_origins}
        if not self.allowed:
            raise A2AError("a client needs the operator's list of peer origins")
        self.credential_env, self.header, self.scheme = credential_env, header, scheme
        self.deadline_s, self.max_bytes, self.transport, self.insecure = deadline_s, max_bytes, transport, insecure
        self._ids = 0

    def _check(self, url: str) -> None:
        if origin_of(url) not in self.allowed:
            raise A2AError("%s is not on the operator's list of A2A peers" % origin_of(url))

    def _headers(self) -> Dict[str, str]:
        headers = {"A2A-Version": A2A_PROTOCOL_VERSION, "Accept": "application/json"}
        if self.credential_env:
            value = os.environ.get(self.credential_env)
            if not value:
                raise A2AError("%s is empty: run the caller under use_secret.py run, which places the key" % self.credential_env)
            headers[self.header] = "%s %s" % (self.scheme, value) if self.scheme else value
        return headers

    def _get(self, url: str) -> Any:
        self._check(url)
        kwargs = {"transport": self.transport} if self.transport else {}
        response = http_request("GET", url, headers={"Accept": "application/json"}, deadline_s=self.deadline_s,
                                 max_bytes=self.max_bytes, insecure=self.insecure, **kwargs)
        if response.status != 200:
            raise A2AError("the peer answered HTTP %d for its card" % response.status)
        try:
            return response.json()
        except ValueError:
            raise A2AError("the peer's card is not JSON") from None

    def discover(self, origin: str) -> Dict[str, Any]:
        """The peer's public card and the JSON-RPC interface to call: {card, url}."""
        card = self._get(origin_of(origin) + A2A_SURFACE_PATH)
        if not isinstance(card, dict):
            raise A2AError("the peer's card is not a JSON object")
        for interface in card.get("supportedInterfaces") or []:
            if (isinstance(interface, dict) and interface.get("protocolBinding") == JSONRPC_BINDING
                    and interface.get("protocolVersion") == A2A_PROTOCOL_VERSION and isinstance(interface.get("url"), str)):
                self._check(interface["url"])
                return {"card": card, "url": interface["url"]}
        raise A2AError("the peer's card names no A2A %s JSON-RPC interface" % A2A_PROTOCOL_VERSION)

    def _rpc(self, url: str, method: str, params: Dict[str, Any]) -> Any:
        self._check(url)
        self._ids += 1
        kwargs = {"transport": self.transport} if self.transport else {}
        response = http_request("POST", url, headers=self._headers(), body={"jsonrpc": "2.0", "id": self._ids,
                                 "method": method, "params": params}, deadline_s=self.deadline_s, retries=0,
                                 max_bytes=self.max_bytes, insecure=self.insecure, **kwargs)
        if response.status != 200:
            raise A2AError("the peer answered HTTP %d to %s" % (response.status, method))
        try:
            answer = response.json()
        except ValueError:
            answer = None
        if not isinstance(answer, dict):
            raise A2AError("the peer's answer to %s is not a JSON-RPC response" % method)
        if "error" in answer:
            error = answer["error"] if isinstance(answer["error"], dict) else {}
            raise A2AError("the peer refused %s: %s %s" % (method, error.get("code"), str(error.get("message"))[:200]))
        return answer.get("result")

    def call(self, url: str, text: str, *, data: Any = None, task_id: Optional[str] = None,
             context_id: Optional[str] = None) -> Any:
        """SendMessage: a user message with `text` (and a data part), new or continuing `task_id`; the result as sent
        ({task} or {message})."""
        parts: List[Dict[str, Any]] = [{"text": text}]
        if data is not None:
            parts.append({"data": data})
        message: Dict[str, Any] = {"role": "ROLE_USER", "parts": parts, "messageId": "msg-" + secrets.token_hex(8)}
        if task_id:
            message["taskId"] = task_id
        if context_id:
            message["contextId"] = context_id
        return self._rpc(url, "SendMessage", {"message": message})

    def get(self, url: str, task_id: str) -> Any:
        return self._rpc(url, "GetTask", {"id": task_id})

    def cancel(self, url: str, task_id: str) -> Any:
        return self._rpc(url, "CancelTask", {"id": task_id})
