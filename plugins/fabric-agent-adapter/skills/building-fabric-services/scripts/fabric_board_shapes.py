"""The project board's wire (fabric-project-comms/0.1, DEC-0022, DEC-0073, DEC-0077): constants, the refusal codes, the
contract's request digest, the closed shapes the kit reads back (receipts, refusals, directory pages, messages) and
evidence. Part of the board connector (FAA-65, layer L4)."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence

import fabric_identifiers as _ids


COMMS_PROTOCOL = "fabric-project-comms/0.1"


LEASE_SECONDS = 60.0


SUMMARY_MAX = 2000


EVIDENCE_MAX = 8


#: The tools a board session is served (Fabric's respond scope); anything else is refused here, before it is sent.
RESPOND_TOOLS = frozenset(["com.status", "com.list", "com.get", "com.reply", "com.enroll", "com.claim", "com.renew",
                           "com.accept", "com.progress", "com.effect_begin", "com.complete", "com.reconcile",
                           "com.responder_replace"])


REFUSAL_CODES = frozenset(["invalid_arguments", "body_too_large", "not_authorized", "authority_changed",
                           "unsupported_capability", "unsupported_operation", "not_available", "idempotency_conflict",
                           "idempotency_window_expired", "capacity_exceeded", "digest_conflict", "revision_conflict",
                           "fenced", "lease_expired", "invalid_transition", "reconcile_required", "observation_required",
                           "cursor_reset_required", "immutable_participants", "held"])


REQUEST_STATES = ("queued", "claimed", "accepted", "in_progress", "completed", "failed_known", "cancelled", "expired",
                  "outcome_unknown")


EFFECT_STATES = ("not_started", "started", "succeeded_observed", "failed_observed", "unknown")


#: DEC-0079: what an operator's hold may refuse, by the scopes that refuse it. A tool not named here is never refused
#: `held` — it settles, reports on or keeps alive started work (com.renew, com.progress, com.complete, com.reconcile),
#: cancels or reads. The contract's HOLD_SCOPES.
HOLD_SCOPES = {"com.submit": ("thread",), "com.reply": ("thread",), "com.enroll": ("project", "slot"),
               "com.responder_replace": ("project", "slot"), "com.claim": ("thread", "project", "slot"),
               "com.accept": ("thread", "project", "slot"), "com.effect_begin": ("thread", "project", "slot")}


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
        if _closed(r, "/request", keys, keys + ("settledBy",), problems):
            if not (isinstance(r.get("id"), str) and _OPAQUE.fullmatch(r["id"])):
                problems.append("/request/id is a board id")
            if r.get("state") not in REQUEST_STATES:
                problems.append("/request/state is a request state")
            if r.get("effect") not in EFFECT_STATES:
                problems.append("/request/effect is an effect state")
            if not _is_int(r.get("revision"), 1):
                problems.append("/request/revision is an integer ≥ 1")
            if "settledBy" in r:
                # DEC-0081: present only when the estate owner settled it; absent, the responder did.
                if r["settledBy"] != "owner":
                    problems.append("/request/settledBy is owner")
                if r.get("state") not in ("completed", "failed_known"):
                    problems.append("/request/settledBy names a settled request (completed or failed_known)")
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
            elif e.get("code") == "held" and e["retryable"] is not True:
                problems.append("/error/retryable is true for held: the operator lifts a hold (DEC-0079)")
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
            if _closed(entry, cat, ("capability", "responder"), ("capability", "responder", "held"), problems):
                if not (isinstance(entry.get("capability"), str) and _CAPABILITY.fullmatch(entry["capability"])):
                    problems.append("%s/capability is a capability name" % cat)
                if entry.get("responder") not in ("active", "stale", "absent"):
                    problems.append("%s/responder is active, stale or absent" % cat)
                if "held" in entry and not isinstance(entry["held"], bool):
                    problems.append("%s/held is a boolean (DEC-0079)" % cat)
    return problems + ["%s %s" % (f["instancePath"], f["message"]) for f in directory_findings(page)]


def hold_refuses(tool: Any, target: Any, holds: Any) -> bool:
    """DEC-0079, the contract's ``holdRefuses``: True when a board refuses ``tool`` on ``target`` with ``held`` under
    ``holds``. ``target`` is what the board resolved (``thread``, ``project``, ``capability``, ``fenced``, ``repeat``);
    ``holds`` is ``{threads, projects, slots: [{project, capability}]}``. Ids compare as written. Malformed input never
    raises: a member of the wrong type counts as absent, and an unknown tool is never refused ``held``."""
    scopes = HOLD_SCOPES.get(tool) if isinstance(tool, str) else None
    if not scopes or not isinstance(target, dict):
        return False
    if target.get("repeat") is True:
        return False
    if tool == "com.reply" and target.get("fenced") is True:
        return False
    holds = holds if isinstance(holds, dict) else {}

    def text(value: Any) -> Optional[str]:
        return value if isinstance(value, str) else None

    def strings(value: Any) -> set:
        return {item for item in value if isinstance(item, str)} if isinstance(value, list) else set()

    thread, project, capability = text(target.get("thread")), text(target.get("project")), text(target.get("capability"))
    if "thread" in scopes and thread is not None and thread in strings(holds.get("threads")):
        return True
    if "project" in scopes and project is not None and project in strings(holds.get("projects")):
        return True
    slots = holds.get("slots")
    if "slot" in scopes and project is not None and capability is not None and isinstance(slots, list):
        return any(isinstance(slot, dict) and slot.get("project") == project and slot.get("capability") == capability
                   for slot in slots)
    return False


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
