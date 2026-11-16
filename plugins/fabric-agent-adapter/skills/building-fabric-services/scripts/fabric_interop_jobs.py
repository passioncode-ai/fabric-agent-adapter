# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
"""fabric-interop/0.1, the job store (C3.2): durable jobs, one private JSON file each, their idempotency keys
(DEC-0087, FAA-77) and every transition a job makes. fabric_interop re-exports `JobStore`; the Node kit writes the same
file format. Part of the service kit (split from fabric_interop; layer L3). Standard library only, Python 3.9+."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import secrets
from typing import Any, Dict, Optional

import sys as _sys  # noqa: E402
if str(Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(Path(__file__).resolve().parent))

import fabric_service as _fs  # noqa: E402
from fabric_base import store_lock  # noqa: E402 - one lock per store path (R3)
from fabric_mandate import EFFECT_CLASSES  # noqa: E402 - DEC-0125
from fabric_page_links import input_request_link_findings  # noqa: E402 - DEC-0123
from fabric_interop_rules import (  # noqa: E402 - the rule layer (FAA-92)
    ENVELOPE_REQUIRED,
    OUTCOME_UNKNOWN,
    QUEUE_FULL,
    QUOTA_EXHAUSTED,
    TERMINAL,
    _JOB_ID,
    _KEY,
    InteropError,
    UnknownJob,
    intent_digest,
    kept_step,
    parse_traceparent,
    pause_message,
    quota_data_ok,
    repeated_key_decision,
    utc_time,
)

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

    def _transition(self, job_id: str, status: str, private: Optional[Dict[str, Any]] = None, **fields: Any) -> Dict[str, Any]:
        with self._lock:
            record = self._load(job_id)
            if private is not None and "steps" in private:  # in the same file write as the transition
                # Each question replaces the kept steps: a step outlives neither its question nor its answer.
                record["private"]["steps"] = dict(private["steps"])
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

    def request_input(self, job_id: str, input_requests: Dict[str, Dict[str, Any]], message: Optional[str] = None,
                      steps: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
        """input_required with MCP elicitation requests, keyed; build them with choice_request / form_request / url_request.
        `steps` (DEC-0125) maps a request key to the approval step it asks for, {effect, spendUsd?, project?}, kept in the
        job's private part so an answer's `_meta.mandate` is read for that step (CallContext.approval_step writes it).
        A step is kept as the gate reads it (kept_step), so a job's start and its answer agree."""
        if not isinstance(input_requests, dict) or not input_requests:  # a JSON object of requests, first (readings 38, 39)
            raise InteropError("input_required needs a JSON object of at least one input request.")
        if steps is not None and not isinstance(steps, dict):  # a JSON object or none, in both kits (FAA-196 (26))
            raise InteropError("steps maps an input request's key to its approval step: a JSON object, or none.")
        kept: Dict[str, Dict[str, Any]] = {}
        for key, step in (steps or {}).items():  # the value checked is the value kept (seam reading 34)
            kept[key] = kept_step(step) if key in input_requests and isinstance(step, dict) else {}
            if not (type(kept[key].get("effect")) is str and kept[key]["effect"] in EFFECT_CLASSES):
                raise InteropError("Step %r: an input request's key with its effect class (DEC-0125)." % (key,))
        for key, request in input_requests.items():  # each a keyed object, as Node refuses one (product reading 39)
            if not isinstance(key, str) or not _KEY.match(key) or not isinstance(request, dict) or request.get("method") != "elicitation/create":
                raise InteropError("Input request %r must be a keyed elicitation/create request." % (key,))
        for finding in input_request_link_findings({"inputRequests": input_requests}):  # FAC-SEM-143 (D12)
            raise InteropError("%s: %s" % (finding["instancePath"], finding["message"]))
        return self._transition(job_id, "input_required", {"steps": kept},
                                inputRequests=input_requests, statusMessage=message)

    def answer(self, job_id: str, input_responses: Dict[str, Any]) -> Dict[str, Any]:
        """Apply inputResponses (a JSON object, a dict) to an input_required job; unknown keys are ignored (MCP Tasks rule).

        Returns the responses that matched; when any did, the job is working again."""
        with self._lock:
            job = self.get(job_id)
            if job["status"] != "input_required":
                return {}
            matched = {key: value for key, value in (input_responses if isinstance(input_responses, dict) else {}).items()
                       if isinstance(job.get("inputRequests"), dict) and key in job["inputRequests"] and isinstance(value, dict)
                       and value.get("action") in ("accept", "decline", "cancel")}
            if matched:  # the answered question's kept steps go in the same write: none outlives its answer
                self._transition(job_id, "working", {"steps": {}})
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
        if code == QUEUE_FULL:  # DEC-0104: a refusal at a job's start, never a job's end (the schema refuses one)
            raise InteropError("queue-full refuses a start and never ends a job (DEC-0104)")
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
