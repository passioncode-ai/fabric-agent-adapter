"""Dates and times the way the contract reads them, once for the whole kit (FAA-65, layer L0).

- ``parse_rfc3339_ms(text)``: strict RFC 3339 (a ``T``, an offset, a day that exists; no space, no leap second) as
  milliseconds since the epoch, or NaN. ``estate_time`` in older code is the same function.
- ``clock_ms(at)``: a verifier's clock (a timezone-aware ``datetime`` or epoch seconds) as milliseconds, or NaN.
- ``utc_date_ms(text)``: a ``YYYY-MM-DD`` that exists as midnight UTC in milliseconds, or NaN.
- ``utc_day(ms)``, ``format_rfc3339(ms)``, ``day_window(today_ms, days)``, ``now_ms(clock)``: the helpers a service
  needs to write dates and to walk the last N UTC days.

NaN, never an exception, is the answer for what cannot be read: callers compare it and get a finding.
Standard library only; imports only ``fabric_jsvalue``.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from typing import Any, Callable, List, Optional
from fabric_jsvalue import is_number


# ASCII digits only: Python's \d also matches other scripts' digits, which Date.parse never reads.
_RFC3339 = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]+)?([Zz]|([+-])([0-9]{2}):([0-9]{2}))", re.ASCII)


def days_from_civil(year: int, month: int, day: int) -> int:
    year -= month <= 2
    era = (year if year >= 0 else year - 399) // 400
    yoe = year - era * 400
    doy = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def parse_rfc3339_ms(value: Any) -> float:
    """An RFC 3339 date-time as milliseconds since the epoch, or NaN: `T`, an offset and a day that exists are required;
    a space and a leap second `:60` are refused (ER-10). Fractions count to the millisecond, as Date.parse reads them."""
    match = _RFC3339.fullmatch(value) if isinstance(value, str) else None
    if not match:
        return math.nan
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days_in = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if not (1 <= month <= 12 and 1 <= day <= days_in[month - 1]) or hour > 23 or minute > 59 or second > 59:
        return math.nan
    if match.group(9):
        oh, om = int(match.group(10)), int(match.group(11))
        if oh > 23 or om > 59:
            return math.nan
        offset = (oh * 60 + om) * (1 if match.group(9) == "+" else -1)
    else:
        offset = 0
    millis = int((match.group(7) or ".")[1:4].ljust(3, "0"))
    seconds = days_from_civil(year, month, day) * 86400 + hour * 3600 + minute * 60 + second - offset * 60
    return float(seconds * 1000 + millis)


def clock_ms(at: Any) -> float:
    """The verifier's clock as milliseconds: a timezone-aware datetime or epoch seconds; NaN for anything else."""
    if isinstance(at, _dt.datetime) and at.tzinfo is not None:
        return at.timestamp() * 1000.0
    if is_number(at):
        try:
            seconds = float(at)
        except OverflowError:
            return math.nan
        return seconds * 1000.0 if math.isfinite(seconds) else math.nan
    return math.nan


DAY_MS = 86_400_000
_UTC_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})", re.ASCII)


def utc_date_ms(value: Any) -> float:
    """A ``YYYY-MM-DD`` date that exists, as midnight UTC in milliseconds; NaN for anything else (the contract's
    ``utcDate``)."""
    match = _UTC_DATE.fullmatch(value) if isinstance(value, str) else None
    if not match:
        return math.nan
    try:
        day = _dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return math.nan
    return float((day - _dt.date(1970, 1, 1)).days * DAY_MS)


def utc_day(ms: float) -> str:
    """The UTC calendar day (``YYYY-MM-DD``) of an instant in milliseconds. Raises ValueError for NaN or Infinity."""
    if not math.isfinite(ms):
        raise ValueError("not a finite instant")
    return (_dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc) + _dt.timedelta(milliseconds=ms)).strftime("%Y-%m-%d")


def format_rfc3339(ms: float) -> str:
    """An instant as RFC 3339 in UTC with milliseconds (``2026-10-21T09:00:00.000Z``), which ``parse_rfc3339_ms``
    reads back to the same value. Raises ValueError for NaN or Infinity."""
    if not math.isfinite(ms):
        raise ValueError("not a finite instant")
    moment = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc) + _dt.timedelta(milliseconds=int(ms))
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def day_window(today_ms: float, days: int) -> List[str]:
    """The last ``days`` UTC days ending with the day of ``today_ms``, oldest first (a usage report's window is 31)."""
    if days < 1:
        return []
    start = (today_ms // DAY_MS) * DAY_MS - (days - 1) * DAY_MS
    return [utc_day(start + i * DAY_MS) for i in range(days)]


def now_ms(clock: Optional[Callable[[], float]] = None) -> float:
    """Milliseconds since the epoch: from ``clock`` (seconds, as ``time.time``) when given, so a test fixes the time."""
    import time
    return float((clock or time.time)()) * 1000.0

