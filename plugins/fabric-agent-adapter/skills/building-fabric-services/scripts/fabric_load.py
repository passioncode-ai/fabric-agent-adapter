"""The call queue and the load report of DEC-0104 (contract `src/agent-network.ts`, FAC-SEM-131 to FAC-SEM-133), as the
contract's reference answers them: a node that hosts a job-backed agent queues its jobs per (agentRef, context) with
these and reports its load as `service-load/1` under `extensions/load/0.1`. Part of the service kit (FAA-289, layer L3);
the twin of fabric-load.mjs. Standard library only. Nothing here raises on what it reads, except `load_extension`, which
refuses a declaration a reader would treat as not declared.

- job_caller_key(accepted, credential): the opaque key of a job's caller (an accepted delegation's principal, its
  outermost actor and a partner organization ending the chain; else the credential the node knows the caller by).
- next_queued_job(queue, running, limits): the job the node starts next, or None (fairness between callers).
- admit_job(queue, running, job, limits, retry_after_seconds): {admit: True}, or the `queue-full` refusal with its data.
- queue_status_message(position, length), read_queue_position(status_message): `queued <position> of <length>`.
- job_queue_rules(value): FAC-SEM-131 over {queue, running, limits, started}.
- load_report_rules(report): FAC-SEM-132 on a `service-load/1` report; load_report_problems(report): its schema.
- load_view(well_known), load_extension_rules(well_known): the declaration as a reader reads it, and FAC-SEM-133.
- load_extension(path, window_seconds, limits): the `extensions` entry a service declares.

The kit has no JSON Schema validator: the two shapes are written here from the schemas as the contract's validator
reads them (ECMAScript's \\s in patterns, lengths in code points, `date-time` as ajv-formats' full mode). Times in the
queue are UTC instants (`interop-common#/$defs/utcInstant`); times in the report are RFC 3339 read strictly (the
contract's strictTime). The wording of a schema problem is the kit's, not ajv's."""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))

from fabric_base import ServiceError  # noqa: E402
from fabric_connections import date_time  # noqa: E402 - ajv-formats' date-time, as the contract's validator reads it
from fabric_jsvalue import (  # noqa: E402
    MISSING, _JS_SPACE, double, get, is_number, json_stringify, objects, safe_integer, same, show,
)
from fabric_time import parse_rfc3339_ms  # noqa: E402 - the contract's strictTime

LOAD_EXTENSION_KEY = "https://fabric.passioncode.ai/agent-contract/extensions/load/0.1"
LOAD_REPORT_TYPE = "service-load/1"
#: The refusal code, the same as fabric_interop_rules.QUEUE_FULL (a test holds them equal); not imported because the
#: facade fabric_service, which re-exports this module, comes before the interop rules in the kit's order.
_QUEUE_FULL = "queue-full"
QUEUE_FULL_MESSAGE = "the agent's queue for this context is full: start again later"
#: The longest queue a status message names (`queued <position> of <length>`, six digits).
QUEUE_LENGTH_MAX = 999999
DEFAULT_RETRY_AFTER_SECONDS = 60

_UTC_INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-5][0-9](?:\.[0-9]{1,3})?Z", re.ASCII)
_QUEUED = re.compile(r"queued ([1-9][0-9]{0,5}) of ([1-9][0-9]{0,5})", re.ASCII)
_ORIGIN_PATH = re.compile("/(?!/)[^%s]*" % re.escape(_JS_SPACE))
_CONTEXT = re.compile(r"(?:personal|org:[A-Za-z0-9][A-Za-z0-9_-]{0,127})", re.ASCII)
_KEY_PATH = "/extensions/" + LOAD_EXTENSION_KEY.replace("~", "~0").replace("/", "~1")
_LIMITS = (("concurrency", 1, 1024), ("perCaller", 1, 1024), ("queueMax", 0, 100000))
_ROW_COUNTS = ("queued", "running", "completed", "failed")


def _utc_ms(value: Any) -> float:
    """A UTC instant (`T`, `Z`, at most three fraction digits, a day that exists) in milliseconds, else NaN."""
    return parse_rfc3339_ms(value) if isinstance(value, str) and _UTC_INSTANT.fullmatch(value) else math.nan


def _strict_ms(value: Any) -> float:
    return parse_rfc3339_ms(value) if isinstance(value, str) else math.nan


def _utf16(value: str) -> bytes:
    """A key that orders strings as JavaScript's `<` does: by UTF-16 code units."""
    return value.encode("utf-16-be", "surrogatepass")


def _string(value: Any) -> bool:
    return isinstance(value, str)


# --- The call queue (fabric-interop, DEC-0104) ---


def job_caller_key(accepted: Any = MISSING, credential: Any = MISSING) -> Optional[str]:
    """The key of a job's caller at a node that queues (DEC-0104), as the contract's jobCallerKey: for a call whose
    delegation the node accepted (verify_delegation's answer), its `principal` and `caller` and the partner
    organization when the chain ends in one (DEC-0090); for a call with no token, the credential the node knows the
    caller by (a gate's pass with `principal: None` is that case too). A refused verdict has no key, and neither has
    an unreadable call: None. The key is opaque; only equality matters."""
    if isinstance(accepted, dict) and not (get(accepted, "ok") is True and get(accepted, "principal") is None):
        principal, caller = get(accepted, "principal"), get(accepted, "caller")
        if get(accepted, "ok") is not True or not _string(principal) or principal == "" or not _string(caller) or caller == "":
            return None
        chain = get(accepted, "chain")
        chain = chain if isinstance(chain, list) else []
        last = chain[-1] if chain else MISSING
        partner = [last] if len(chain) > 1 and _string(last) and last.startswith("org:") else []
        return json_stringify(["delegated", principal, caller] + partner)
    return json_stringify(["credential", credential]) if _string(credential) and credential != "" else None


def _limits_ok(limits: Any) -> bool:
    if not isinstance(limits, dict):
        return False
    concurrency, per_caller, queue_max = get(limits, "concurrency"), get(limits, "perCaller"), get(limits, "queueMax")
    return (all(safe_integer(n) and double(n) >= 1 for n in (concurrency, per_caller))
            and safe_integer(queue_max) and double(queue_max) >= 0)


def _waiting_job(job: Any) -> bool:
    return isinstance(job, dict) and _string(get(job, "id")) and _string(get(job, "caller")) and math.isfinite(_utc_ms(get(job, "at")))


def next_queued_job(queue: Any, running: Any, limits: Any) -> Optional[str]:
    """The job the hosting node starts next for one (agentRef, context), or None (DEC-0104). Nothing starts while
    `concurrency` jobs run (every running job holds a slot, its caller readable or not). Of the waiting jobs whose
    caller runs fewer than `perCaller`, the one whose caller runs the fewest wins; between those callers, the one whose
    oldest waiting job arrived first; within a caller, its oldest. Arrival ties break by id (UTF-16 order)."""
    if not _limits_ok(limits):
        return None
    if (len(running) if isinstance(running, list) else 0) >= double(limits["concurrency"]):
        return None
    running_of: Dict[str, int] = {}
    for job in objects(running):
        if _string(get(job, "caller")):
            running_of[job["caller"]] = running_of.get(job["caller"], 0) + 1
    waiting = [job for job in objects(queue) if _waiting_job(job) and running_of.get(job["caller"], 0) < double(limits["perCaller"])]
    waiting.sort(key=lambda job: (_utc_ms(job["at"]), _utf16(job["id"])))
    best: Optional[Dict[str, Any]] = None
    for job in waiting:
        if best is None or running_of.get(job["caller"], 0) < running_of.get(best["caller"], 0):
            best = job
    return None if best is None else best["id"]


def admit_job(queue: Any, running: Any, job: Any, limits: Any, retry_after_seconds: Any = MISSING) -> Dict[str, Any]:
    """Whether a start is admitted (DEC-0104): it is when the job would start at once (next_queued_job over the queue
    with it added answers its id), or when fewer than `queueMax` jobs wait; otherwise {admit: False, error} with the
    `queue-full` refusal and its `retryAfterSeconds` (1 to 3600, else 60). Unreadable limits or job refuse."""
    waiting = objects(queue)
    if _limits_ok(limits) and _waiting_job(job) and (
            next_queued_job(waiting + [job], running, limits) == job["id"] or len(waiting) < double(limits["queueMax"])):
        return {"admit": True}
    after = retry_after_seconds if safe_integer(retry_after_seconds) and 1 <= double(retry_after_seconds) <= 3600 else DEFAULT_RETRY_AFTER_SECONDS
    return {"admit": False, "error": {"code": _QUEUE_FULL, "message": QUEUE_FULL_MESSAGE,
                                      "data": {"retryable": True, "retryAfterSeconds": int(after)}}}


def queue_status_message(position: Any, length: Any) -> Optional[str]:
    """The `statusMessage` of a waiting job (DEC-0104): `queued <position> of <length>`, 1 is next, 1 <= position <=
    length <= 999999; None for anything else."""
    if not (safe_integer(position) and safe_integer(length)):
        return None
    if not 1 <= double(position) <= double(length) <= QUEUE_LENGTH_MAX:
        return None
    return "queued %d of %d" % (int(position), int(length))


def read_queue_position(status_message: Any) -> Optional[Dict[str, int]]:
    """A waiting job's place, read from its `statusMessage`, or None when it is not the queue's grammar."""
    match = _QUEUED.fullmatch(status_message) if _string(status_message) else None
    if not match:
        return None
    position, length = int(match.group(1)), int(match.group(2))
    return {"position": position, "length": length} if 1 <= position <= length else None


def _finding(code: str, instance_path: str, message: str) -> Dict[str, str]:
    return {"code": code, "instancePath": instance_path, "message": message}


def job_queue_rules(value: Any) -> List[Dict[str, str]]:
    """FAC-SEM-131 on {queue, running, limits, started} (`started`: the id the node started, or None): it is
    next_queued_job's."""
    want = next_queued_job(get(value, "queue"), get(value, "running"), get(value, "limits"))
    started = get(value, "started")
    if same(None if started is MISSING else started, want):
        return []
    return [_finding("FAC-SEM-131", "/started", "nothing may start now" if want is None else "the job to start is %s" % show(want))]


# --- The load report (DEC-0104) ---


def load_report_rules(report: Any) -> List[Dict[str, str]]:
    """FAC-SEM-132 on a `service-load/1` report: windows in order one `windowSeconds` apart, none after `generatedAt`,
    one row per context, p50 at most p95, a run time only where a job ended."""
    findings: List[Dict[str, str]] = []
    flag = lambda path, message: findings.append(_finding("FAC-SEM-132", path, message))  # noqa: E731
    seconds = get(report, "windowSeconds")
    step = double(seconds) * 1000 if safe_integer(seconds) else math.nan
    generated = _strict_ms(get(report, "generatedAt"))
    previous: Any = MISSING
    for index, window in enumerate(objects(get(report, "windows"))):
        start = _strict_ms(get(window, "start"))
        if start > generated:
            flag("/windows/%d/start" % index, "a window starts after the report was generated")
        if previous is not MISSING and start - previous != step:
            flag("/windows/%d/start" % index, "windows are not in order one windowSeconds apart")
        previous = start
        seen = set()
        for at, row in enumerate(objects(get(window, "byContext"))):
            path = "/windows/%d/byContext/%d" % (index, at)
            context = get(row, "context")
            if _string(context) and context in seen:
                flag(path + "/context", "context %s appears twice in one window" % show(context))
            if _string(context):
                seen.add(context)
            for name in ("waitMs", "runMs"):
                pct = get(row, name)
                p50, p95 = get(pct, "p50"), get(pct, "p95")
                if isinstance(pct, dict) and is_number(p50) and is_number(p95) and double(p50) > double(p95):
                    flag("%s/%s" % (path, name), "p50 is above p95")
            if isinstance(get(row, "runMs"), dict) and same(get(row, "completed"), 0) and same(get(row, "failed"), 0):
                flag(path + "/runMs", "a run time with no job ended in the window")
    return findings


def _integer(value: Any, low: float, high: Optional[float], at: str, errors: List[str]) -> None:
    """JSON Schema's integer with its bounds, as ajv reads it: a number with no fraction (2.0 is one), never a bool."""
    if not is_number(value) or not math.isfinite(double(value)) or double(value) != math.floor(double(value)):
        errors.append("%s type" % at)
    elif double(value) < low:
        errors.append("%s minimum" % at)
    elif high is not None and double(value) > high:
        errors.append("%s maximum" % at)


def _members(value: Dict[str, Any], allowed: tuple, required: tuple, at: str, errors: List[str]) -> None:
    errors.extend("%s/%s additionalProperties" % (at, key) for key in value if key not in allowed)
    errors.extend("%s required %s" % (at or "/", key) for key in required if key not in value)


def _timestamp(value: Any, at: str, errors: List[str]) -> None:
    if not _string(value):
        errors.append("%s type" % at)
    elif not date_time(value):
        errors.append("%s format" % at)


def _percentiles(value: Any, at: str, errors: List[str]) -> None:
    if not isinstance(value, dict):
        errors.append("%s type" % at)
        return
    _members(value, ("p50", "p95"), ("p50", "p95"), at, errors)
    for name in ("p50", "p95"):
        if name in value:
            _integer(value[name], 0, None, "%s/%s" % (at, name), errors)


def _row_problems(row: Any, at: str, errors: List[str]) -> None:
    if not isinstance(row, dict):
        errors.append("%s type" % at)
        return
    _members(row, ("context",) + _ROW_COUNTS + ("waitMs", "runMs"), ("context",) + _ROW_COUNTS, at, errors)
    if "context" in row and not (_string(row["context"]) and _CONTEXT.fullmatch(row["context"])):
        errors.append("%s/context %s" % (at, "pattern" if _string(row["context"]) else "type"))
    for name in _ROW_COUNTS:
        if name in row:
            _integer(row[name], 0, None, "%s/%s" % (at, name), errors)
    for name in ("waitMs", "runMs"):
        if name in row:
            _percentiles(row[name], "%s/%s" % (at, name), errors)


def load_report_problems(report: Any) -> List[str]:
    """service-load.schema.json: what makes `report` not a `service-load/1` report, each as `<path> <keyword>`; empty
    for a valid one. Counts and durations only: a member the schema does not name (a caller, a job id) is refused."""
    if not isinstance(report, dict):
        return ["/ type"]
    errors: List[str] = []
    _members(report, ("type", "generatedAt", "windowSeconds", "windows"), ("type", "generatedAt", "windowSeconds", "windows"), "", errors)
    if "type" in report and not same(report["type"], LOAD_REPORT_TYPE):
        errors.append("/type const")
    if "generatedAt" in report:
        _timestamp(report["generatedAt"], "/generatedAt", errors)
    if "windowSeconds" in report:
        _integer(report["windowSeconds"], 60, 86400, "/windowSeconds", errors)
    windows = report.get("windows", MISSING)
    if windows is not MISSING and not isinstance(windows, list):
        errors.append("/windows type")
    elif isinstance(windows, list):
        if len(windows) > 168:
            errors.append("/windows maxItems")
        for index, window in enumerate(windows):
            at = "/windows/%d" % index
            if not isinstance(window, dict):
                errors.append("%s type" % at)
                continue
            _members(window, ("start", "byContext"), ("start", "byContext"), at, errors)
            if "start" in window:
                _timestamp(window["start"], at + "/start", errors)
            rows = window.get("byContext", MISSING)
            if rows is not MISSING and not isinstance(rows, list):
                errors.append("%s/byContext type" % at)
            elif isinstance(rows, list):
                if len(rows) > 64:
                    errors.append("%s/byContext maxItems" % at)
                for row_index, row in enumerate(rows):
                    _row_problems(row, "%s/byContext/%d" % (at, row_index), errors)
    return errors


def _declaration_problems(value: Any) -> List[str]:
    """service-load-extension.schema.json, each problem as `<path> <keyword>`; empty for a valid declaration."""
    if not isinstance(value, dict):
        return ["/ type"]
    errors: List[str] = []
    _members(value, ("path", "windowSeconds", "limits"), ("path", "windowSeconds", "limits"), "", errors)
    path = value.get("path", MISSING)
    if path is not MISSING:
        if not _string(path):
            errors.append("/path type")
        else:
            if len(path) > 256:  # code points, as ajv counts them; the originPath's own 2048 is wider
                errors.append("/path maxLength")
            if not _ORIGIN_PATH.fullmatch(path):
                errors.append("/path pattern")
    if "windowSeconds" in value:
        _integer(value["windowSeconds"], 60, 86400, "/windowSeconds", errors)
    limits = value.get("limits", MISSING)
    if limits is not MISSING:
        if not isinstance(limits, dict):
            errors.append("/limits type")
        else:
            _members(limits, tuple(name for name, _, _ in _LIMITS), tuple(name for name, _, _ in _LIMITS), "/limits", errors)
            for name, low, high in _LIMITS:
                if name in limits:
                    _integer(limits[name], low, high, "/limits/%s" % name, errors)
    return errors


def load_view(well_known: Any) -> Dict[str, Any]:
    """The load declaration as a reader reads it (DEC-0104): `declared` when the extension key is present, `valid` when
    its value is the schema's, `load` the declaration when valid (else None) and `errors` its problems. A reader treats
    an invalid value as not declared and reports it (FAC-SEM-133)."""
    extensions = get(well_known, "extensions")
    if not isinstance(extensions, dict) or LOAD_EXTENSION_KEY not in extensions:
        return {"declared": False, "valid": False, "load": None, "errors": []}
    value = extensions[LOAD_EXTENSION_KEY]
    errors = _declaration_problems(value)
    return {"declared": True, "valid": not errors, "load": None if errors else value, "errors": errors}


def load_extension_rules(well_known: Any) -> List[Dict[str, str]]:
    """FAC-SEM-133 on a well-known document: a value under the load extension key is valid against
    service-load-extension.schema.json; one finding at the key otherwise."""
    view = load_view(well_known)
    if not view["declared"] or view["valid"]:
        return []
    return [_finding("FAC-SEM-133", _KEY_PATH, "the load declaration is invalid (%s); a reader treats it as not declared "
                                               "and reports it (DEC-0104)" % "; ".join(view["errors"]))]


def load_extension(path: Any, window_seconds: Any, limits: Any) -> Dict[str, Any]:
    """The `extensions` entry a service declares (DEC-0104): where it serves its `service-load/1` report (an origin
    path, served under the descriptor token like the usage report), the report's window and the queue's limits per
    (agentRef, context). Raises ServiceError on a declaration a reader would treat as not declared."""
    value = {"path": path, "windowSeconds": window_seconds, "limits": dict(limits) if isinstance(limits, dict) else limits}
    problems = _declaration_problems(value)
    if problems:
        raise ServiceError("Load declaration: %s." % "; ".join(problems))
    return {LOAD_EXTENSION_KEY: value}
