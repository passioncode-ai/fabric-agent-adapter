"""Work a service holds by its own limits, said to its caller and its operator (FAA-298). Part of the service kit
(layer L3, after fabric_interop).

A service that holds work by a limit of its own (a daily quota, a per-caller share, a concurrency cap, a money cap)
says so three ways:

- to the caller, on the job: `waiting_message(reason, since, until, message)` is the job's `statusMessage`. The pinned
  `interop-job` schema is closed (`additionalProperties: false`), so `waiting {reason, since, until, message}` cannot
  be a field of the job; it rides the contract's pause grammar (DEC-0087) as its text:
  `quota-exhausted[ until <until>]: waiting <reason> since <since>[: <message>]`. A caller that reads only the pause
  grammar waits (and until `until`, when given); `read_waiting(answer)` gives the four parts back. `JobStore.pause`
  takes the same statusMessage through `hold_job`.
- to the operator, once per hold: `HoldBook.hold` opens a hold per (reason, caller), or joins the open one, and returns
  the push only when it opens: one `notify` event naming the caller, the work, the reason and when the hold frees by
  itself, with the question whether to raise the limit. Further jobs held by the same limit for the same caller join
  the hold silently; a hold is closed by `release`, by its `until` passing, or by a lift that covers it.
- the answer, as a scoped lift: `HoldBook.lift` records the operator's words (a DEC-0121 decision, action
  `limit.lift`) with its scope (the reason, optionally one caller and one job) and its size (a number of jobs, an
  amount of money, or a raised limit for a time window such as 100 a day for today). `admit` spends a jobs or money
  lift; `limit` gives the limit in force. A lift falls back by itself when its window ends or its amount is spent.

`HoldBook` keeps one JSON file (0600, written atomically); a ThreadingHTTPServer's handlers share it under the store
lock. It holds caller names, work labels, reasons and the operator's words, never a credential: `hold` refuses a text
the contract's detector reads as one.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
from fabric_base import ServiceError, now_iso, store_lock  # noqa: E402
from fabric_paths import atomic_write  # noqa: E402
from fabric_actions import decision_shape  # noqa: E402
from fabric_interop_rules import pause_message, read_job_pause, utc_time, QUOTA_EXHAUSTED  # noqa: E402
import fabric_secrets  # noqa: E402

#: The limits a hold names: a daily quota, a per-caller share, a concurrency cap, a money cap.
HOLD_REASONS = ("daily-quota", "caller-share", "concurrency", "money")
#: How the push names each reason to a person.
REASON_WORDS = {"daily-quota": "the daily quota", "caller-share": "its per-caller share",
                "concurrency": "the concurrency cap", "money": "the money cap"}
#: The push's kind: a decision for the operator (level notice, notify true; events-and-notifications.md).
HOLD_EVENT_KIND = "limit.held"
#: The record of a lift applied (level info, no notify).
LIFT_EVENT_KIND = "limit.lifted"
#: The decision action a lift carries (DEC-0121 AP-2 shape).
LIFT_ACTION = "limit.lift"
_MAX_STATUS_MESSAGE = 500
_WAITING = re.compile(r"^waiting (daily-quota|caller-share|concurrency|money) since ([0-9][0-9TZ:.-]*?)(?:: ([\s\S]+))?\Z")
_SIZES = ("jobs", "usd", "limit")
#: One run of ECMAScript's whitespace, the class both twins squash with (FAA-316): Python's str.split() also takes
#: U+001C to U+001F and U+0085 and not U+FEFF, so the twins wrote different statusMessages.
_SPACES = re.compile("[%s]+" % fabric_secrets.JS_SPACE)


def _squash(text: str) -> str:
    """Runs of ECMAScript whitespace as one space, none at either end (the Node twin's `squash`)."""
    return _SPACES.sub(" ", text).strip(" ")


def _instant(value: Any, name: str) -> str:
    if utc_time(value) is None:
        raise ServiceError("%s is a UTC instant (Z, at most 3 fraction digits)." % name)
    return value


def waiting_message(reason: str, since: str, until: Optional[str] = None, message: Optional[str] = None) -> str:
    """A held job's statusMessage: the pause grammar, its text `waiting <reason> since <since>[: <message>]`. The
    message is shortened, never refused, to fit the contract's 500 characters; a reason or an instant outside the
    grammar raises ServiceError."""
    if reason not in HOLD_REASONS:
        raise ServiceError("A hold's reason is one of %s." % ", ".join(HOLD_REASONS))
    _instant(since, "since")
    if until is not None:
        _instant(until, "until")
    text = "waiting %s since %s" % (reason, since)
    head = len(QUOTA_EXHAUSTED) + (0 if until is None else len(" until ") + len(until)) + len(": ")
    if message is not None:
        message = _squash(str(message))
        room = _MAX_STATUS_MESSAGE - head - len(text) - len(": ")
        if message and room > 0:
            text += ": " + (message if len(message) <= room else message[:room - 3].rstrip(" ") + "...")
    return pause_message(until, text)


def read_waiting(answer: Any) -> Optional[Dict[str, Any]]:
    """`{reason, since, until?, message?}` of a fabric.job.get answer whose job a limit holds (`waiting_message`), else
    None: a plain pause, a queue position or a finished job is not a hold."""
    pause = read_job_pause(answer)
    if not pause.get("paused"):
        return None
    status = answer["job"]["statusMessage"]
    rest = status[len(QUOTA_EXHAUSTED):]
    if "resetsAt" in pause:
        rest = rest[len(" until ") + len(pause["resetsAt"]):]
    if not rest.startswith(": "):
        return None
    match = _WAITING.match(rest[2:])
    if not match or utc_time(match.group(2)) is None:
        return None
    waiting: Dict[str, Any] = {"reason": match.group(1), "since": match.group(2)}
    if "resetsAt" in pause:
        waiting["until"] = pause["resetsAt"]
    if match.group(3) is not None:
        waiting["message"] = match.group(3)
    return waiting


def hold_job(jobs: Any, job_id: str, reason: str, since: str, until: Optional[str] = None,
             message: Optional[str] = None) -> Dict[str, Any]:
    """Put one job of a fabric_interop JobStore on hold: working, its statusMessage `waiting_message(...)`, its
    pollIntervalMs reaching `until` (JobStore.pause). Returns the job."""
    text = waiting_message(reason, since, until, message)[len(QUOTA_EXHAUSTED):]
    if until is not None:
        text = text[len(" until ") + len(until):]
    return jobs.pause(job_id, resets_at=until, text=text[2:])


def hold_sentence(caller: str, work: str, reason: str, until: Optional[str]) -> str:
    """The push's one sentence: who, what, why, when it frees by itself, and the question."""
    frees = ("it frees by itself at %s" % until) if until is not None else (
        "it frees by itself when a running job ends" if reason in ("concurrency", "caller-share")
        else "it does not free by itself")
    return "%s for %s is held by %s; %s. Raise the limit for it?" % (work, caller, REASON_WORDS[reason], frees)


def _text(value: Any, name: str, high: int = 200) -> str:
    if not isinstance(value, str) or not _squash(value) or len(value) > high:
        raise ServiceError("%s is a text of 1 to %d characters." % (name, high))
    if fabric_secrets.secret_value(value):
        raise ServiceError("%s looks like a credential; a hold names callers and work, never a secret." % name)
    return _squash(value)


class HoldBook:
    """The holds a service's limits put on work and the operator's lifts, in one file (FAA-298).

    `events`, when given, is the service's event log (an object with `append(kind, level, text, subject=..., **extra)`,
    such as fabric_events.JsonlEventLog): the push and the lift record are written there. Without it they are returned
    for the service to write."""

    def __init__(self, path: Path, events: Any = None, clock: Callable[[], str] = now_iso):
        self.path = Path(path)
        self.events = events
        self.clock = clock
        self._lock = store_lock(self.path)

    # --- the file -------------------------------------------------------------------------
    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"holds": [], "lifts": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except ValueError:
            raise ServiceError("The hold book %s is not JSON; it is kept as it is." % self.path.name) from None
        if not isinstance(data, dict) or not isinstance(data.get("holds"), list) or not isinstance(data.get("lifts"), list):
            raise ServiceError("The hold book %s is not {holds, lifts}; it is kept as it is." % self.path.name)
        return data

    def _save(self, data: Dict[str, Any]) -> None:
        atomic_write(self.path, (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode(), 0o600)

    def _now(self, now: Optional[str]) -> str:
        return _instant(now if now is not None else self.clock(), "now")

    def _emit(self, kind: str, level: str, text: str, subject: Dict[str, str], notify: bool) -> Dict[str, Any]:
        if self.events is not None:
            return self.events.append(kind, level, text, subject=subject, notify=notify)
        out: Dict[str, Any] = {"kind": kind, "level": level, "text": text, "subject": subject}
        if notify:
            out["notify"] = True
        return out

    @staticmethod
    def _expire(data: Dict[str, Any], at: int) -> None:
        for hold in data["holds"]:
            if hold.get("closed") is None and hold.get("until") is not None and utc_time(hold["until"]) <= at:
                hold["closed"], hold["closedAt"] = "expired", hold["until"]

    @staticmethod
    def _live(lift: Dict[str, Any], at: int) -> bool:
        if lift.get("from") is not None and utc_time(lift["from"]) > at:
            return False
        if lift.get("until") is not None and utc_time(lift["until"]) <= at:
            return False
        return lift.get("left", 1) > 0

    # --- holds ----------------------------------------------------------------------------
    def hold(self, *, caller: str, work: str, reason: str, until: Optional[str] = None, message: Optional[str] = None,
             job_id: Optional[str] = None, now: Optional[str] = None) -> Dict[str, Any]:
        """Hold `work` for `caller` by `reason`. Returns {hold, statusMessage, push}: `push` is the notify event when this
        call opened the hold, None when the work joined an open one (one push per hold)."""
        caller, work = _text(caller, "caller"), _text(work, "work")
        if reason not in HOLD_REASONS:
            raise ServiceError("A hold's reason is one of %s." % ", ".join(HOLD_REASONS))
        at = self._now(now)
        if until is not None and utc_time(_instant(until, "until")) <= utc_time(at):
            raise ServiceError("until %s has passed: the limit no longer holds the work." % until)
        with self._lock:
            data = self._load()
            self._expire(data, utc_time(at))
            hold = next((h for h in data["holds"] if h.get("closed") is None and h["reason"] == reason
                         and h["caller"] == caller), None)
            opened = hold is None
            if opened:
                hold = {"id": uuid.uuid4().hex, "reason": reason, "caller": caller, "work": work, "since": at,
                        "until": until, "jobs": [], "closed": None}
                data["holds"].append(hold)
            if job_id is not None and job_id not in hold["jobs"]:
                hold["jobs"].append(str(job_id))
            self._save(data)
        status = waiting_message(reason, hold["since"], hold["until"], message)
        push = None
        if opened:
            push = self._emit(HOLD_EVENT_KIND, "notice", hold_sentence(caller, work, reason, until),
                              {"type": "limit", "id": "%s:%s" % (reason, caller)[:200], "label": REASON_WORDS[reason]}, True)
        return {"hold": dict(hold), "statusMessage": status, "push": push}

    def release(self, *, reason: str, caller: str, now: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Close the open hold of (reason, caller): the limit freed the work. The next hold pushes again."""
        at = self._now(now)
        with self._lock:
            data = self._load()
            hold = next((h for h in data["holds"] if h.get("closed") is None and h["reason"] == reason
                         and h["caller"] == caller), None)
            if hold is None:
                return None
            hold["closed"], hold["closedAt"] = "released", at
            self._save(data)
            return dict(hold)

    def open_holds(self, now: Optional[str] = None) -> List[Dict[str, Any]]:
        data = self._load()
        self._expire(data, utc_time(self._now(now)))
        return [dict(h) for h in data["holds"] if h.get("closed") is None]

    # --- lifts ----------------------------------------------------------------------------
    def lift(self, *, reason: str, decision: Dict[str, Any], caller: Optional[str] = None, job_id: Optional[str] = None,
             jobs: Optional[int] = None, usd: Optional[float] = None, limit: Optional[int] = None,
             until: Optional[str] = None, now: Optional[str] = None) -> Dict[str, Any]:
        """Record the operator's answer as a scoped lift: exactly one of `jobs` (that many more jobs), `usd` (that much
        more money) or `limit` (the limit raised to that value, which needs `until`, the window's end). `decision` is
        the operator's words in decision.schema.json's shape with action `limit.lift`. The open hold it covers closes
        as lifted. Returns the lift."""
        if reason not in HOLD_REASONS:
            raise ServiceError("A lift's reason is one of %s." % ", ".join(HOLD_REASONS))
        if not decision_shape(decision) or decision.get("action") != LIFT_ACTION:
            raise ServiceError("A lift carries the operator's decision (decision.schema.json, action limit.lift, their "
                               "words verbatim): fabric_actions.operator_decision('limit.lift', words).")
        sizes = {"jobs": jobs, "usd": usd, "limit": limit}
        given = [name for name in _SIZES if sizes[name] is not None]
        if len(given) != 1:
            raise ServiceError("A lift is one of jobs, usd or limit.")
        size = sizes[given[0]]
        if isinstance(size, bool) or not isinstance(size, (int, float)) or size <= 0 or (
                given[0] != "usd" and int(size) != size):
            raise ServiceError("A lift's %s is a positive %s." % (given[0], "number" if given[0] == "usd" else "integer"))
        at = self._now(now)
        if until is not None and utc_time(_instant(until, "until")) <= utc_time(at):
            raise ServiceError("A lift's window ends after now.")
        if given[0] == "limit" and until is None:
            raise ServiceError("A raised limit needs its window's end (until): it falls back when the window ends.")
        record: Dict[str, Any] = {"id": uuid.uuid4().hex, "reason": reason, "caller": None if caller is None else _text(caller, "caller"),
                                  "job": None if job_id is None else str(job_id), "from": at, "until": until,
                                  given[0]: size, "decision": dict(decision), "at": at}
        if given[0] != "limit":
            record["left"] = size
        with self._lock:
            data = self._load()
            self._expire(data, utc_time(at))
            for hold in data["holds"]:
                if hold.get("closed") is None and hold["reason"] == reason and record["caller"] in (None, hold["caller"]) and (
                        job_id is None or str(job_id) in hold["jobs"]):
                    hold["closed"], hold["closedAt"], hold["lift"] = "lifted", at, record["id"]
            data["lifts"].append(record)
            self._save(data)
        scope = ("for %s" % record["caller"]) if record["caller"] else "for every caller"
        amount = {"jobs": "%s more job(s)", "usd": "USD %s more", "limit": "the limit at %s"}[given[0]] % size
        self._emit(LIFT_EVENT_KIND, "info", "The operator lifted %s %s: %s%s." % (
            REASON_WORDS[reason], scope, amount, (" until %s" % until) if until else ""),
            {"type": "limit", "id": "%s:%s" % (reason, record["caller"] or "*"), "label": REASON_WORDS[reason]}, False)
        return dict(record)

    def _matching(self, data: Dict[str, Any], reason: str, caller: Optional[str], job_id: Optional[str], at: int,
                  kind: str) -> List[Dict[str, Any]]:
        return [l for l in data["lifts"] if l["reason"] == reason and kind in l and self._live(l, at)
                and l.get("caller") in (None, caller) and l.get("job") in (None, job_id)]

    def admit(self, *, reason: str, caller: str, job_id: Optional[str] = None, cost_usd: Optional[float] = None,
              now: Optional[str] = None) -> Dict[str, Any]:
        """Whether a lift lets work past the limit that would hold it: {admitted: True, lift} spends one job of a jobs
        lift, or `cost_usd` of a money lift (the narrowest scope first: a job's, a caller's, every caller's), else
        {admitted: False}. A raised limit is read with `limit`, not spent here."""
        at = utc_time(self._now(now))
        with self._lock:
            data = self._load()
            kind = "usd" if cost_usd is not None else "jobs"
            for lift in sorted(self._matching(data, reason, caller, None if job_id is None else str(job_id), at, kind),
                               key=lambda l: (l.get("job") is None, l.get("caller") is None)):
                need = cost_usd if kind == "usd" else 1
                if lift["left"] >= need:
                    lift["left"] = round(lift["left"] - need, 6) if kind == "usd" else lift["left"] - 1
                    self._save(data)
                    return {"admitted": True, "lift": lift["id"], "left": lift["left"]}
            return {"admitted": False}

    def limit(self, *, reason: str, base: float, caller: Optional[str] = None, now: Optional[str] = None) -> float:
        """The limit in force: `base`, or the highest live raised limit for (reason, caller); `base` again once the
        window ends."""
        at = utc_time(self._now(now))
        raised = [l["limit"] for l in self._matching(self._load(), reason, caller, None, at, "limit")]
        return max([base] + raised)

    def lifts(self, now: Optional[str] = None) -> List[Dict[str, Any]]:
        """Every lift with `live`: whether it still applies now."""
        at = utc_time(self._now(now))
        return [dict(l, live=self._live(l, at)) for l in self._load()["lifts"]]
