"""A service's operations digests (contract DEC-0153, `docs/specification/ops-digest.md` at the pin): every record of its
operations log counted by operation and outcome in the hour it happened, one `ops.digest.hourly@1` line for each hour
the service observed itself running in (an empty one included), and one `ops.digest.daily@1` line for each closed UTC
day that has hourly lines. Counts only: no log line, no path, no identifier (OD-7). `fold_hour` and `fold_day` are the
contract's reference folds (`src/ops-digest.ts`, its vectors in test/fixtures/ops-digest/); `ops_digest_rules` is
FAC-SEM-166 and FAC-SEM-167; `OpsDigest` keeps the files (OD-1, OD-5, OD-6): it writes an hour when it closes, keeps the
hour it stops in for the next run, never fills hours it did not observe, and folds every closed day once, catch-up
included. `ops_digest_extension` writes the descriptor's OD-9 declaration. Part of the service kit (FAA-206 part 2,
layer L3). Standard library only."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))

from fabric_base import ServiceError, _O_BINARY  # noqa: E402
from fabric_jsvalue import indexed_objects  # noqa: E402
from fabric_paths import atomic_write, ensure_private_dir  # noqa: E402
from fabric_secrets import JS_SPACE, secret_value  # noqa: E402
from fabric_time import DAY_MS, days_from_civil  # noqa: E402

OPS_DIGEST_HOURLY = "ops.digest.hourly@1"
OPS_DIGEST_DAILY = "ops.digest.daily@1"
#: The descriptor's extension key (OD-9), protocol `fabric-ops-digest/0.1`.
OPS_DIGEST_EXTENSION = "https://fabric.passioncode.ai/agent-contract/extensions/ops-digest/0.1"
#: A failure count is a rise when it is at least this many in the hour (OD-4)...
RISE_MIN_FAILED = 10
#: ...and at least this many times the hour before's (an hour before with none, or none recorded, counts as one).
RISE_FACTOR = 2
#: An operation's name (OD-2), the contract's `OP_NAME`, and its length cap `OP_NAME_MAX`.
OP_NAME = re.compile(r"[a-z][A-Za-z0-9_]*(?:[.:/-][A-Za-z0-9_]+)*\Z", re.ASCII)
OP_NAME_MAX = 64
#: At most this many operations in a digest's `ops` (OD-3): 4095 named a day plus the one overflow name.
OPS_MAX = 4096
#: The overflow name the kit counts the rest under once a day holds 4095 named operations (OD-3); a service that
#: changes it publishes its own with its outcome map.
OVERFLOW_OP = "ops.overflow"
OUTCOMES = ("ok", "failed", "unknown")
MAX_COUNT = 2 ** 53 - 1
HOUR_MS = 3600000

_WHOLE_HOUR = re.compile(r"\A([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):00:00(?:\.000)?Z\Z")
_DAY = re.compile(r"\A([0-9]{4})-([0-9]{2})-([0-9]{2})\Z")
_SLASH = r"(?:[/\\]|%(?:25)?2[fF])"
#: The contract's `hasHomePath` (src/activity-rules.ts at the pin), JavaScript's \s read as JavaScript reads it.
HOME_PATH = (
    re.compile(r"(?:\A|[^A-Za-z0-9]|%(?:25)?2[fF])(?:[Uu]sers|home)" + _SLASH + r"[A-Za-z0-9_]"),
    re.compile(r"(?:\A|[^A-Za-z0-9])-(?:[Uu]sers|home)-[A-Za-z0-9]"),
    re.compile("(?:\\A|[" + JS_SPACE + "\"'=/\\\\])~(?:[A-Za-z_][A-Za-z0-9_.-]*)?(?:[/\\\\]|\\Z)"),
)
_PRINTABLE = re.compile(r"\A[\x20-\x7e]+\Z")
_SOURCE = re.compile(r"\A[a-z][a-z0-9-]{0,31}\Z")
_FILE = re.compile(r"\A(hourly|daily)-([0-9]{4})-([0-9]{2})\.jsonl\Z")


class OpsDigestError(ServiceError):
    """An input no digest holds; its message names a credential-shaped or home-folder value only by its place."""


def has_home_path(value: str) -> bool:
    """Whether `value` holds a home folder, as the contract's `hasHomePath` reads it (FAC-SEM-167, FAC-SEM-168)."""
    return isinstance(value, str) and any(p.search(value) for p in HOME_PATH)


def is_rise(failed: int, previous: int) -> bool:
    """Whether `failed` failures in an hour are a rise against `previous` in the hour before (OD-4)."""
    return failed >= RISE_MIN_FAILED and failed >= RISE_FACTOR * max(1, previous)


def _civil_from_days(z: int) -> Tuple[int, int, int]:
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    return yoe + era * 400 + (m <= 2), m, d


def _month_days(y: int, m: int) -> int:
    if m == 2:
        return 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28
    return 30 if m in (4, 6, 9, 11) else 31


def whole_hour(value: Any) -> Optional[int]:
    """The instant (ms since the epoch) of a whole UTC hour in the schema's form, or None (a 25th hour, a 30 February)."""
    match = _WHOLE_HOUR.match(value) if isinstance(value, str) else None
    if not match:
        return None
    y, m, d, h = (int(g) for g in match.groups())
    if not (1 <= m <= 12 and 1 <= d <= _month_days(y, m) and h <= 23):
        return None
    return (days_from_civil(y, m, d) * 24 + h) * HOUR_MS


def real_day(value: Any) -> bool:
    """Whether `value` is a real `YYYY-MM-DD` day."""
    return isinstance(value, str) and bool(_DAY.match(value)) and whole_hour(value + "T00:00:00Z") is not None


def iso_hour(at: int) -> str:
    """A whole hour as `Date.prototype.toISOString` writes it (years 0 to 9999)."""
    y, m, d = _civil_from_days(at // DAY_MS)
    return "%04d-%02d-%02dT%02d:00:00.000Z" % (y, m, d, (at % DAY_MS) // HOUR_MS)


def day_of(at: int) -> str:
    """The UTC day of an instant, `YYYY-MM-DD`."""
    return iso_hour(at)[:10]


def _count(n: Any) -> Optional[int]:
    """A count as JavaScript's Number.isSafeInteger reads a JSON number: an integer from 0 to 2^53 - 1 (an integral
    float included, a boolean never), or None."""
    if isinstance(n, bool):
        return None
    if isinstance(n, float):
        if not n.is_integer():
            return None
        n = int(n)
    return n if isinstance(n, int) and 0 <= n <= MAX_COUNT else None


def _hidden(value: str) -> bool:
    return secret_value(value) or has_home_path(value)


def _shown(value: str, instead: str) -> str:
    return instead if _hidden(value) or not _PRINTABLE.match(value) else value


def _op_shown(op: str) -> str:
    return _shown(op, "this operation") if len(op) <= OP_NAME_MAX and OP_NAME.match(op) else "this operation"


def name_refusal(op: Any) -> Optional[str]:
    """What OD-2 refuses in an operation's name (its grammar, OP_NAME_MAX included, or FAC-SEM-167); None when lawful."""
    if not isinstance(op, str) or len(op) > OP_NAME_MAX or not OP_NAME.match(op):
        return "fails OD-2's name grammar"
    return "is refused by FAC-SEM-167" if _hidden(op) else None


def _objects(items: Any, where: str) -> None:
    if not isinstance(items, list):
        raise OpsDigestError("%s is not an array" % where)
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise OpsDigestError("the item at %d of %s is not an object" % (i, where))


def _once(ops: Sequence[Dict[str, Any]], where: str) -> None:
    names = set()
    for i, c in enumerate(ops):
        if not isinstance(c.get("op"), str):
            raise OpsDigestError("the operation at %d of %s has no string name" % (i, where))
        if c["op"] in names:
            raise OpsDigestError("%s is named twice in %s" % (_shown(c["op"], "the operation at %d" % i), where))
        names.add(c["op"])


def _sum(ops: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    return {k: sum(c[k] for c in ops) for k in OUTCOMES}


def _safe(digest: Dict[str, Any]) -> Dict[str, Any]:
    counts = [digest["total"][k] for k in OUTCOMES] + [c[k] for c in digest["ops"] for k in OUTCOMES]
    for r in digest["risen"]:
        counts += [r["failed"], r["previous"]] if "previous" in r else [r["failed"]]
    if any(n > MAX_COUNT for n in counts):
        raise OpsDigestError("a sum is beyond 2^53 - 1")
    return digest


def fold_hour(counts: Sequence[Dict[str, Any]], from_: str, previous: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The digest of the hour starting at `from_`: `counts` ({op, ok, failed, unknown}, an op may repeat and is
    summed) by operation, sorted by name, and each operation whose failures rose against `previous`, which counts
    only when it is the hour just before (a gap compares with none). Raises OpsDigestError where the contract's
    `foldHour` throws: no hourly digest is written then (OD-3)."""
    start = whole_hour(from_)
    if start is None:
        raise OpsDigestError("%s is not a whole UTC hour" % (_shown(from_, "from") if isinstance(from_, str) else "from"))
    _objects(counts, "counts")
    if _civil_from_days((start + HOUR_MS) // DAY_MS)[0] > 9999:
        raise OpsDigestError("the hour after %s is not a whole UTC hour the schema writes" % _shown(from_, "from"))
    merged: Dict[str, Dict[str, Any]] = {}
    for i, c in enumerate(counts):
        refused = name_refusal(c.get("op"))
        if refused is not None:
            raise OpsDigestError("the operation at %d %s: no hourly digest (OD-3)" % (i, refused))
        values = [_count(c.get(k)) for k in OUTCOMES]
        if None in values:
            raise OpsDigestError("a count of %s is not an integer from 0 to 2^53 - 1" % _shown(c["op"], "the operation at %d" % i))
        m = merged.setdefault(c["op"], {"op": c["op"], "ok": 0, "failed": 0, "unknown": 0})
        for k, n in zip(OUTCOMES, values):
            m[k] += n
    if len(merged) > OPS_MAX:
        raise OpsDigestError("the hour counts %d operations, more than %d: no hourly digest (OD-3)" % (len(merged), OPS_MAX))
    ops = [merged[k] for k in sorted(merged)]
    absent = previous is None
    if not absent and not (isinstance(previous, dict) and isinstance(previous.get("to"), str)):
        raise OpsDigestError("the previous hour is neither absent nor a digest with a string to")
    adjoining = previous["ops"] if not absent and whole_hour(previous["to"]) == start else []
    _objects(adjoining, "the previous hour's ops")
    _once(adjoining, "the previous hour's ops")
    before = {c["op"]: c.get("failed") for c in adjoining}
    for c in ops:
        if c["op"] in before and _count(before[c["op"]]) is None:
            raise OpsDigestError("the previous hour's failures of %s are not an integer from 0 to 2^53 - 1" % _shown(c["op"], "an operation"))
    risen = [{"op": c["op"], "failed": c["failed"], "previous": _count(before.get(c["op"], 0))}
             for c in ops if is_rise(c["failed"], _count(before.get(c["op"], 0)))]
    return _safe({"schema": OPS_DIGEST_HOURLY, "from": iso_hour(start), "to": iso_hour(start + HOUR_MS), "ops": ops,
                  "total": _sum(ops), "risen": risen})


def fold_day(day: str, hourly: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The day's hourly digests (those whose hour starts on `day`, the first of a repeated hour kept) folded into one,
    or None for a day with no hour of its own (OD-5). Deciding the day is closed is the caller's. Raises
    OpsDigestError where the contract's `foldDay` throws."""
    if not real_day(day):
        raise OpsDigestError("%s is not a real UTC day" % (_shown(day, "day") if isinstance(day, str) else "day"))
    _objects(hourly, "hourly")
    seen, mine = set(), []
    for h in hourly:
        at = whole_hour(h.get("from"))
        if at is None or day_of(at) != day or at in seen:
            continue
        seen.add(at)
        mine.append(h)
    if not mine:
        return None
    merged: Dict[str, Dict[str, Any]] = {}
    rose: Dict[str, Dict[str, int]] = {}
    for h in mine:
        for where in ("ops", "risen"):
            items = h.get(where)
            _objects(items, "%s's %s" % (h["from"], where))
            for i, c in enumerate(items):
                refused = name_refusal(c.get("op"))
                if refused is not None:
                    raise OpsDigestError("the operation at %d of %s's %s %s: no daily digest (OD-3)" % (i, h["from"], where, refused))
        for c in h["ops"]:
            values = [_count(c.get(k)) for k in OUTCOMES]
            if None in values:
                raise OpsDigestError("a count of %s in %s is not an integer from 0 to 2^53 - 1" % (_shown(c["op"], "an operation"), h["from"]))
            m = merged.setdefault(c["op"], {"op": c["op"], "ok": 0, "failed": 0, "unknown": 0})
            for k, n in zip(OUTCOMES, values):
                m[k] += n
        _once(h["risen"], "the risen of %s" % h["from"])
        for r in h["risen"]:
            failed = _count(r.get("failed"))
            if failed is None:
                raise OpsDigestError("the rise of %s in %s is not an integer from 0 to 2^53 - 1" % (_shown(r["op"], "an operation"), h["from"]))
            if not any(c.get("op") == r["op"] for c in h["ops"]):
                raise OpsDigestError("%s rose in %s but that hour's ops does not count it" % (_shown(r["op"], "an operation"), h["from"]))
            x = rose.setdefault(r["op"], {"hours": 0, "failed": 0})
            x["hours"] += 1
            x["failed"] += failed
    if len(merged) > OPS_MAX:
        raise OpsDigestError("the day folds %d operations, more than %d: no daily digest (OD-3)" % (len(merged), OPS_MAX))
    ops = [merged[k] for k in sorted(merged)]
    risen = sorted(({"op": op, "hours": x["hours"], "failed": x["failed"]} for op, x in rose.items()),
                   key=lambda r: (-r["failed"], r["op"]))
    return _safe({"schema": OPS_DIGEST_DAILY, "day": day, "hours": len(mine), "ops": ops, "total": _sum(ops),
                  "risen": risen})


def ops_digest_rules(kind: str, value: Dict[str, Any]) -> Optional[List[Dict[str, str]]]:
    """FAC-SEM-166 and FAC-SEM-167 on one digest of either kind ({code, instancePath, message} each, as the contract's
    `opsDigestRules` words them); None for any other kind. It assumes the schema already passed."""
    if kind not in ("ops-digest-hourly", "ops-digest-daily"):
        return None
    findings: List[Dict[str, str]] = []

    def window(path: str, message: str) -> None:
        findings.append({"code": "FAC-SEM-166", "instancePath": path, "message": message})

    def named(path: str, op: str) -> None:
        if secret_value(op):
            findings.append({"code": "FAC-SEM-167", "instancePath": path, "message": "an operation's name is shaped like a credential; it names an operation, never a value"})
        elif has_home_path(op):
            findings.append({"code": "FAC-SEM-167", "instancePath": path, "message": "an operation's name holds a home folder; it names an operation, never a path"})

    if kind == "ops-digest-hourly":
        start, end = whole_hour(value.get("from")), whole_hour(value.get("to"))
        if start is None:
            window("/from", "from is a whole UTC hour of a real day")
        if end is None:
            window("/to", "to is a whole UTC hour of a real day")
        if start is not None and end is not None and end - start != HOUR_MS:
            window("/to", "to is exactly one hour after from")
    elif not real_day(value.get("day")):
        window("/day", "day is a real UTC day, YYYY-MM-DD")

    by_op: Dict[str, Dict[str, Any]] = {}
    totals: Dict[str, Optional[int]] = {"ok": 0, "failed": 0, "unknown": 0}
    for entry, index in indexed_objects(value.get("ops")):
        op = entry.get("op")
        if isinstance(op, str):
            if op in by_op:
                window("/ops/%d/op" % index, "%s is counted once" % _op_shown(op))
            else:
                by_op[op] = entry
            named("/ops/%d/op" % index, op)
        for k in OUTCOMES:
            n = _count(entry.get(k))
            totals[k] = None if n is None or totals[k] is None else totals[k] + n
    total = value.get("total") if isinstance(value.get("total"), dict) else None
    if total is not None and isinstance(value.get("ops"), list):
        for k in OUTCOMES:
            want = totals[k]
            if want is None or _count(total.get(k)) is None:
                continue
            if want > MAX_COUNT:
                window("/total/%s" % k, "the sum of ops' %s is beyond 2^53 - 1, so no total.%s can be it" % (k, k))
            elif _count(total.get(k)) != want:
                window("/total/%s" % k, "total.%s is the sum of ops' %s, %d" % (k, k, want))

    rose = set()
    hours = _count(value.get("hours"))
    for entry, index in indexed_objects(value.get("risen")):
        op = entry.get("op")
        if not isinstance(op, str):
            continue
        at = "/risen/%d" % index
        named(at + "/op", op)
        if op in rose:
            window(at + "/op", "%s is named once among the rises" % _op_shown(op))
        rose.add(op)
        counted = by_op.get(op)
        if counted is None:
            window(at + "/op", "%s rose, so ops counts it" % _op_shown(op))
            continue
        failed, counted_failed = _count(entry.get("failed")), _count(counted.get("failed"))
        if kind == "ops-digest-hourly":
            previous = _count(entry.get("previous"))
            if failed is not None and counted_failed is not None and failed != counted_failed:
                window(at + "/failed", "a rise names the hour's failures of %s, %d" % (_op_shown(op), counted_failed))
            if failed is not None and previous is not None and not is_rise(failed, previous):
                window(at, "%d failures against %d is no rise: at least %d and %d times the hour before (none counts as one)"
                       % (failed, previous, RISE_MIN_FAILED, RISE_FACTOR))
        else:
            risen_hours = _count(entry.get("hours"))
            if risen_hours is not None and hours is not None and risen_hours > hours:
                window(at + "/hours", "%s rose in %d hours; the day folds %d" % (_op_shown(op), risen_hours, hours))
            if failed is not None and risen_hours is not None and failed < RISE_MIN_FAILED * risen_hours:
                window(at + "/failed", "%d hours of rises hold at least %d failures" % (risen_hours, RISE_MIN_FAILED * risen_hours))
            if failed is not None and counted_failed is not None and failed > counted_failed:
                window(at + "/failed", "the rises' failures are at most the day's failures of %s, %d" % (_op_shown(op), counted_failed))
    return findings


_HOURLY_KEYS = ("schema", "from", "to", "ops", "total", "risen")
_DAILY_KEYS = ("schema", "day", "hours", "ops", "total", "risen")


def _shape_ok(line: Any, daily: bool) -> bool:
    """A closed-schema check of the members the kit reads back (OD-6: a reader skips a line that fails the schema)."""
    keys = _DAILY_KEYS if daily else _HOURLY_KEYS
    if not isinstance(line, dict) or sorted(line) != sorted(keys):
        return False
    if line["schema"] != (OPS_DIGEST_DAILY if daily else OPS_DIGEST_HOURLY):
        return False
    if not isinstance(line["ops"], list) or not isinstance(line["risen"], list) or not isinstance(line["total"], dict):
        return False
    if len(line["ops"]) > OPS_MAX or len(line["risen"]) > OPS_MAX:
        return False
    for c in line["ops"]:
        if not (isinstance(c, dict) and sorted(c) == ["failed", "ok", "op", "unknown"] and name_refusal(c["op"]) is None
                and all(_count(c[k]) is not None for k in OUTCOMES)):
            return False
    want = ["failed", "hours", "op"] if daily else ["failed", "op", "previous"]
    for r in line["risen"]:
        if not (isinstance(r, dict) and sorted(r) == want and name_refusal(r["op"]) is None
                and all(_count(r[k]) is not None for k in want if k != "op")):
            return False
    return sorted(line["total"]) == ["failed", "ok", "unknown"] and all(_count(line["total"][k]) is not None for k in OUTCOMES)


def read_digests(folder: Path, kind: str) -> List[Dict[str, Any]]:
    """The digests of `kind` (`hourly` or `daily`) in `folder`, as a reader reads them (OD-6): line by line, oldest
    month first, a line that is not JSON, names another schema or fails the schema or a rule skipped, never stopping
    at one; of two lines for one hour (or one day) the first kept."""
    daily = kind == "daily"
    out, seen = [], set()
    files = sorted(p for p in Path(folder).glob("%s-*.jsonl" % kind) if _FILE.match(p.name)) if Path(folder).is_dir() else []
    for path in files:
        try:
            text = path.read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        for raw in text.split("\n"):
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if not _shape_ok(line, daily) or ops_digest_rules("ops-digest-daily" if daily else "ops-digest-hourly", line):
                continue
            key = line["day"] if daily else whole_hour(line["from"])
            if key in seen:
                continue
            seen.add(key)
            out.append(line)
    return out


def _line(digest: Dict[str, Any]) -> bytes:
    return (json.dumps(digest, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _append(path: Path, data: bytes) -> None:
    """One whole line appended in one write, the file 0600 (OD-6)."""
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT | _O_BINARY, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


class OpsDigest:
    """The files of one service's operations digests in `folder` (a folder inside its data folder, 0700): count each
    record with `record(op, outcome)`, say the service is running with `tick()` (an hour with a tick and no record is
    written empty), and call `flush()` now and then and `stop()` at the end. `start()` first: it writes every closed
    hour the last run kept, the hour it stopped in included, then folds each closed UTC day that has hourly lines and
    no daily line (catch-up, OD-5). An hour the service did not observe is never written (OD-1). `clock` returns
    milliseconds since the epoch. Thread-safe."""

    def __init__(self, folder: Path, *, overflow: str = OVERFLOW_OP, clock=None):
        if name_refusal(overflow) is not None:
            raise OpsDigestError("the overflow name %s" % name_refusal(overflow))
        self.folder = Path(folder)
        self.overflow = overflow
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._lock = threading.RLock()
        self._hour: Optional[int] = None
        self._counts: Dict[str, List[int]] = {}
        self._names: set = set()
        self._names_day: Optional[str] = None
        self._started = False

    @property
    def _kept(self) -> Path:
        return self.folder / "kept-hour.json"

    def _now(self, at: Optional[int]) -> int:
        return int(self._clock() if at is None else at)

    def start(self, at: Optional[int] = None) -> Dict[str, int]:
        """Write the closed hour the last run kept, then fold every closed day (OD-1, OD-5); the counts of {hours,
        days} written. A kept hour that is still open is resumed."""
        with self._lock:
            ensure_private_dir(self.folder)
            now, written = self._now(at), {"hours": 0, "days": 0}
            kept = self._read_kept()
            if kept is not None:
                start, counts = kept
                if start + HOUR_MS <= now:
                    written["hours"] += self._write_hour(start, counts)
                    self._drop_kept()
                else:
                    self._hour, self._counts = start, counts
            if self._hour is None:
                self._hour, self._counts = now - now % HOUR_MS, {}  # starting is observing itself run (OD-1)
            self._rebuild_names(now)
            written["days"] += self._fold_closed_days(now)
            self._started = True
            return written

    def record(self, op: str, outcome: str, at: Optional[int] = None) -> None:
        """Count one record of `op` with `outcome` (`ok`, `failed`, any other word `unknown`, OD-3) in the hour it
        happened. A name OD-2 refuses raises OpsDigestError: name the operation, never a value of it."""
        refused = name_refusal(op)
        if refused is not None:
            raise OpsDigestError("the operation's name %s (OD-2): name the operation, never a value of it" % refused)
        with self._lock:
            now = self._advance(self._now(at))
            if op not in self._names and op != self.overflow:
                if len(self._names) >= OPS_MAX - 1:
                    op = self.overflow
                else:
                    self._names.add(op)
            self._names_day = day_of(now)
            row = self._counts.setdefault(op, [0, 0, 0])
            row[OUTCOMES.index(outcome) if outcome in ("ok", "failed") else 2] += 1

    def tick(self, at: Optional[int] = None) -> None:
        """The service observed itself running now: this hour is written, empty if nothing was recorded (OD-1)."""
        with self._lock:
            self._advance(self._now(at))

    def flush(self, at: Optional[int] = None) -> Dict[str, int]:
        """Write the hour that closed, fold a day that closed, and keep the open hour's counts on disk."""
        with self._lock:
            now = self._now(at)
            written = {"hours": 0, "days": 0}
            if self._hour is not None and self._hour + HOUR_MS <= now:
                written["hours"] += self._write_hour(self._hour, self._counts)
                self._hour, self._counts = None, {}
                self._drop_kept()
            written["days"] += self._fold_closed_days(now)
            self._keep()
            return written

    def stop(self, at: Optional[int] = None) -> Dict[str, int]:
        """`flush`, keeping the open hour with its counts for the next run, which writes it when it has closed."""
        return self.flush(at)

    def _advance(self, now: int) -> int:
        if not self._started:
            raise OpsDigestError("call start() before recording (OD-1: the kept hour is written first)")
        hour = now - now % HOUR_MS
        if self._hour is not None and hour < self._hour:
            return self._hour  # a clock that went back counts in the open hour, never rewrites a closed one
        if self._hour is not None and hour > self._hour:
            self._write_hour(self._hour, self._counts)
            self._counts = {}
            self._fold_closed_days(now)
        if day_of(hour) != self._names_day:
            self._names, self._names_day = set(), day_of(hour)
        self._hour = hour
        return now

    def _previous(self, start: int) -> Optional[Dict[str, Any]]:
        before = start - HOUR_MS
        for line in reversed(read_digests(self.folder, "hourly")):
            if whole_hour(line["from"]) == before:
                return line
        return None

    def _write_hour(self, start: int, counts: Dict[str, List[int]]) -> int:
        ensure_private_dir(self.folder)
        frm = iso_hour(start)
        if any(whole_hour(line["from"]) == start for line in read_digests(self.folder, "hourly")):
            return 0  # readers keep the first line of an hour (OD-5): a second one is never written
        rows = [{"op": op, "ok": c[0], "failed": c[1], "unknown": c[2]} for op, c in counts.items()]
        digest = fold_hour(rows, frm, self._previous(start))
        _append(self.folder / ("hourly-%s.jsonl" % frm[:7]), _line(digest))
        return 1

    def _fold_closed_days(self, now: int) -> int:
        hourly = read_digests(self.folder, "hourly")
        done = {line["day"] for line in read_digests(self.folder, "daily")}
        today, folded = day_of(now), 0
        for day in sorted({line["from"][:10] for line in hourly}):
            if day >= today or day in done:
                continue
            digest = fold_day(day, hourly)
            if digest is not None:
                _append(self.folder / ("daily-%s.jsonl" % day[:7]), _line(digest))
                folded += 1
        return folded

    def _rebuild_names(self, now: int) -> None:
        """OD-1: the day's named operations from that day's hourly lines and the kept hour, so a restart never names
        more than OD-3 allows."""
        today = day_of(now)
        names = {c["op"] for line in read_digests(self.folder, "hourly") if line["from"][:10] == today for c in line["ops"]}
        if self._hour is not None and day_of(self._hour) == today:
            names |= set(self._counts)
        names.discard(self.overflow)
        self._names, self._names_day = names, today

    def _keep(self) -> None:
        if self._hour is None:
            return
        ensure_private_dir(self.folder)
        body = {"from": iso_hour(self._hour), "ops": [[op] + c for op, c in sorted(self._counts.items())]}
        atomic_write(self._kept, (json.dumps(body, separators=(",", ":")) + "\n").encode("utf-8"))

    def _read_kept(self) -> Optional[Tuple[int, Dict[str, List[int]]]]:
        try:
            body = json.loads(self._kept.read_text(encoding="utf-8"))
            start = whole_hour(body.get("from"))
            counts = {row[0]: [int(row[1]), int(row[2]), int(row[3])] for row in body.get("ops", [])
                      if isinstance(row, list) and len(row) == 4 and name_refusal(row[0]) is None
                      and all(_count(n) is not None for n in row[1:])}
        except (OSError, ValueError, AttributeError, TypeError):
            return None  # an unreadable kept hour is not written: never a partial line (OD-1)
        return (start, counts) if start is not None else None

    def _drop_kept(self) -> None:
        try:
            self._kept.unlink()
        except OSError:
            pass


def outcome_of(word: Any, mapping: Optional[Dict[str, str]] = None) -> str:
    """A log's own outcome word as OD-3 maps it: `ok` and `failed` themselves, a word of the service's published
    `mapping` to its outcome, any other `unknown` (a setup answer, a refusal, a skip, a missing slot)."""
    if word in ("ok", "failed"):
        return word
    mapped = (mapping or {}).get(word) if isinstance(word, str) else None
    return mapped if mapped in OUTCOMES else "unknown"


def _dir_problem(d: Any) -> Optional[str]:
    if not isinstance(d, str) or not d or len(d) > 256:
        return "dir is 1 to 256 characters"
    if d.startswith(("/", "~")) or d.endswith("/") or "//" in d or "\\" in d or ":" in d:
        return "dir is relative to the data folder: forward slashes, no leading / or ~, no drive or :, no trailing /"
    if any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in d) or re.search("[\ud800-\udfff]", d):
        return "dir holds no control character and no lone surrogate"
    if any(seg in (".", "..") or not seg.rstrip(". ") for seg in d.split("/")):
        return "dir has no ., .. or empty segment"
    if has_home_path(d) or has_home_path(d.replace("./", "/")):
        return "dir holds a home folder"
    if secret_value(d):
        return "dir is shaped like a credential (a run of 40 letters, digits and / mixing cases and a digit counts; "\
            "a space or a dot inside a segment breaks it)"
    return None


def ops_digest_extension(folders: Iterable[Dict[str, str]] = ({"dir": "digests", "source": "app"},)) -> Dict[str, Any]:
    """The descriptor's `extensions` member that says where a collector reads the daily digests (OD-9): 1 to 8
    {dir, source}, `dir` inside the data folder. Only a local descriptor that names `paths.data` carries it. Checks
    the grammar, home folders and credential shapes; the contract's FAC-SEM-168 (its caseless fold of `dir` among
    them) stays the authority."""
    items = [dict(f) for f in folders]
    if not 1 <= len(items) <= 8:
        raise OpsDigestError("the ops-digest declaration holds 1 to 8 folders")
    dirs, sources = set(), set()
    for i, item in enumerate(items):
        if sorted(item) != ["dir", "source"]:
            raise OpsDigestError("folder %d is {dir, source} and nothing else" % i)
        problem = _dir_problem(item["dir"])
        if problem:
            raise OpsDigestError("folder %d: %s (FAC-SEM-168)" % (i, problem))
        if not isinstance(item["source"], str) or not _SOURCE.match(item["source"]) or secret_value(item["source"]):
            raise OpsDigestError("folder %d: source is a label matching ^[a-z][a-z0-9-]{0,31}$" % i)
        key = "/".join(seg.rstrip(". ") for seg in item["dir"].lower().split("/"))
        if key in dirs or item["source"] in sources:
            raise OpsDigestError("folder %d: each dir and each source is named once (FAC-SEM-168)" % i)
        dirs.add(key)
        sources.add(item["source"])
    return {OPS_DIGEST_EXTENSION: items}
