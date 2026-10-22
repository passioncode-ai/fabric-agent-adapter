"""A service's events (DEC-0029): making them, paging them and the JSONL event log. Part of the service kit
(FAA-65, layer L3)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
from fabric_base import (
    ServiceError,
    now_iso,
    store_lock,
)
from fabric_paths import (
    atomic_write,
)
from fabric_protocols import (
    feed_data_problems,
)


EVENTS_DEFAULT_LIMIT = 50


EVENTS_MAX_LIMIT = 200


LEVELS = ("info", "notice", "warning", "error")


_KIND = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){0,5}\Z")


_TRACE_ID = re.compile(r"^(?!0{32}\Z)[0-9a-f]{32}\Z")


_SPAN_ID = re.compile(r"^(?!0{16}\Z)[0-9a-f]{16}\Z")


def make_event(event_id: Any, at: str, kind: str, level: str, text: str, *, subject: Optional[Dict[str, str]] = None,
               link: Optional[str] = None, notify: bool = False, trace_id: Optional[str] = None,
               span_id: Optional[str] = None, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One activity event: one sentence a person reads, never a machine id. `data` (DEC-0070) adds machine-readable
    fields beside the sentence, `{schema, value}`, never a secret: it is refused here, so no feed carries one.

    An event about traced work carries its trace as a pair, `trace_id` and `span_id`
    (fabric-interop/0.1 C3.4 c); fabric_interop.trace_ids(traceparent) gives both."""
    if level not in LEVELS:
        raise ServiceError("level must be one of %s." % ", ".join(LEVELS))
    if not _KIND.match(kind):
        raise ServiceError("kind %r must be dotted lowercase." % kind)
    text = " ".join(str(text).split())
    if not text:
        raise ServiceError("An event needs a sentence.")
    if link is not None and (not link.startswith("/") or link.startswith("//")):
        raise ServiceError("link must be a path on this service.")
    if (trace_id is None) != (span_id is None):
        raise ServiceError("An event carries traceId and spanId together, or neither.")
    if trace_id is not None and not (_TRACE_ID.match(trace_id) and _SPAN_ID.match(str(span_id))):
        raise ServiceError("traceId is 32 and spanId 16 lowercase hex characters, not all zeros.")
    event: Dict[str, Any] = {"id": str(event_id), "at": at, "kind": kind, "level": level, "text": text[:500]}
    if subject:
        event["subject"] = subject
    if link:
        event["link"] = link
    if notify:
        event["notify"] = True
    if trace_id is not None:
        event["traceId"], event["spanId"] = trace_id, span_id
    if data is not None:
        problems = feed_data_problems(data)
        if problems:
            raise ServiceError("Event data: %s." % "; ".join(problems))
        event["data"] = {"schema": data["schema"], "value": data["value"]}
    return event


def parse_limit(raw: Optional[str]) -> int:
    try:
        value = int(raw) if raw not in (None, "") else EVENTS_DEFAULT_LIMIT
    except ValueError:
        raise ServiceError("limit must be an integer.") from None
    return max(1, min(EVENTS_MAX_LIMIT, value))


def events_page(fetch: Callable[[Optional[str], int], Iterable[Dict[str, Any]]],
                after: Optional[str], limit: int) -> Dict[str, Any]:
    """A cursor page over the log the service already keeps.

    `fetch(after, limit)` returns events with ids greater than `after` in
    ascending order (or the newest `limit`, ascending, when `after` is None).
    """
    events = list(fetch(after, limit))[:limit]
    cursor = events[-1]["id"] if events else (after or None)
    return {"events": events, "cursor": cursor}


class JsonlEventLog:
    """A minimal append-only log for services that keep none yet. Ids are integers as strings."""

    def __init__(self, path: Path, keep: int = 5000):
        self.path = Path(path)
        self.keep = keep
        self._lock = store_lock(self.path)  # R3: appends from a threaded server's handlers never lose one another

    def _all(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def append(self, kind: str, level: str, text: str, **extra: Any) -> Dict[str, Any]:
        with self._lock:
            rows = self._all()
            next_id = int(rows[-1]["id"]) + 1 if rows else 1
            event = make_event(next_id, now_iso(), kind, level, text, **extra)
            rows.append(event)
            rows = rows[-self.keep:]
            atomic_write(self.path, ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n").encode(), 0o600)
            return event

    def fetch(self, after: Optional[str], limit: int) -> List[Dict[str, Any]]:
        rows = self._all()
        if after is None:
            return rows[-limit:]
        try:
            floor = int(after)
        except ValueError:
            raise ServiceError("cursor %r is not from this service." % after) from None
        return [r for r in rows if int(r["id"]) > floor][:limit]
