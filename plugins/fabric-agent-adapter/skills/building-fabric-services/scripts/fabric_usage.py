"""What a service spends on models (DEC-0021, DEC-0065, DEC-0091): usage receipts, the bounded ledger, the usage
report and its rules (FAC-SEM-025), OpenRouter attribution (FAC-SEM-098) and every spending limit (DEC-0027).
Part of the service kit (FAA-65, layer L3)."""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
from fabric_jsvalue import is_number as _number
from fabric_time import DAY_MS as _DAY_MS, utc_date_ms as _utc_date_ms
import fabric_jsvalue as _jsv
import fabric_time as _ftime
from fabric_base import (
    PROTOCOL,
    ServiceError,
    _O_BINARY,
    now_iso,
)
from fabric_paths import (
    _read_at,
    atomic_write,
    ensure_private_dir,
)


ROUTES = ("subscription", "key")


#: A usage row's route (DEC-0046, DEC-0061): beside a configuration's two, the hosting platform's own metered models.
USAGE_ROUTES = ROUTES + ("platform-metered",)


USAGE_PATH = "/fabric/v1/usage"


USAGE_DAYS = 31


COST_BASES = ("provider", "price-list", "unknown")


_PROVIDER = re.compile(r"^[a-z][a-z0-9._-]{0,63}\Z")


def make_usage_receipt(provider: str, model: str, *, input_tokens: int, output_tokens: int,
                       cache_read_tokens: int = 0, cache_write_tokens: int = 0,
                       cost_usd: Optional[float] = None, cost_basis: Optional[str] = None,
                       at: Optional[str] = None, route: Optional[str] = None,
                       project_id: Optional[str] = None, task_run_id: Optional[str] = None,
                       tokens_measured: bool = True) -> Dict[str, Any]:
    """One model call, from the provider's own usage numbers. No prompt, output or caller.

    `tokens_measured=False` marks a call whose token counts are a lower bound or unknown (the provider returned none,
    the stream was cut): the report counts it in `unmeasuredCalls` and its token totals are a lower bound (DEC-0091).

    `project_id` (a URI, kept in its normal form, DEC-0076) and `task_run_id` (the service's own run id) attribute the
    call to the project the service ran it for (DEC-0065); they never name a caller, session or person.

    `cost_usd` is None when the call cannot be priced: the report counts it as unpriced and
    never as $0. `cost_basis` is `provider` (the provider reported the charge) or `price-list`
    (computed from a published price list); it is `unknown` when there is no cost."""
    if not _PROVIDER.match(provider or ""):
        raise ServiceError("provider must be a lowercase name such as anthropic or openrouter.")
    model = str(model or "").strip()
    if not model or len(model) > 128:
        raise ServiceError("model must be 1 to 128 characters.")
    counts = {"inputTokens": input_tokens, "outputTokens": output_tokens,
              "cacheReadTokens": cache_read_tokens, "cacheWriteTokens": cache_write_tokens}
    for name, value in counts.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ServiceError("%s must be a non-negative integer." % name)
    if cost_usd is not None and (isinstance(cost_usd, bool) or not isinstance(cost_usd, (int, float)) or cost_usd < 0 or cost_usd != cost_usd):
        raise ServiceError("cost_usd must be a non-negative number or None.")
    basis = cost_basis or ("unknown" if cost_usd is None else "provider")
    if basis not in COST_BASES or (cost_usd is None) != (basis == "unknown"):
        raise ServiceError("cost_basis is provider or price-list with a cost, unknown without one.")
    if route is not None and route not in USAGE_ROUTES:
        raise ServiceError("route is subscription, key or platform-metered (DEC-0046, DEC-0061).")
    receipt = {"at": at or now_iso(), "provider": provider, "model": model, **counts,
               "costUsd": None if cost_usd is None else float(cost_usd), "costBasis": basis}
    if tokens_measured is not True:
        if tokens_measured is not False:
            raise ServiceError("tokens_measured is True or False.")
        receipt["tokensMeasured"] = False
    if route is not None:
        receipt["route"] = route  # the operator's own login in its vendor's runner, an issued key, or the platform's metered models
    if task_run_id is not None and project_id is None:
        raise ServiceError("a task run belongs to a project: give project_id with task_run_id.")
    if project_id is not None:
        import fabric_identifiers  # noqa: E402 - beside this file
        if not (isinstance(project_id, str) and _URI.fullmatch(project_id)):
            raise ServiceError("project_id is the URI of the project the service ran the call for.")
        receipt["projectId"] = fabric_identifiers.normal_identifier(project_id)
    if task_run_id is not None:
        if not (isinstance(task_run_id, str) and _TASK_RUN_ID.fullmatch(task_run_id)):
            raise ServiceError("task_run_id is the service's own run id: ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$.")
        receipt["taskRunId"] = task_run_id
    return receipt


_URI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:\S+", re.ASCII)


_TASK_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", re.ASCII)


def _by_project(receipts: List[Dict[str, Any]], first: str, last: str) -> List[Dict[str, Any]]:
    """DEC-0065's `byProject`: the window's calls by the project the service ran them for, each project once (by its
    normal form, DEC-0076) and each task run once within it. A call for no project is in no row."""
    projects: Dict[str, Dict[str, Any]] = {}
    for r in receipts:
        if not (first <= str(r.get("at", ""))[:10] <= last) or not r.get("projectId"):
            continue
        row = projects.setdefault(r["projectId"], {"projectId": r["projectId"], "calls": 0, "unpricedCalls": 0, "_cost": 0.0, "_runs": {}})
        row["calls"] += 1
        if r.get("costUsd") is None:
            row["unpricedCalls"] += 1
        else:
            row["_cost"] += float(r["costUsd"])
        if r.get("taskRunId"):
            run = row["_runs"].setdefault(r["taskRunId"], {"taskRunId": r["taskRunId"], "calls": 0, "unpricedCalls": 0, "_cost": 0.0})
            run["calls"] += 1
            if r.get("costUsd") is None:
                run["unpricedCalls"] += 1
            else:
                run["_cost"] += float(r["costUsd"])
    out = []
    for key in sorted(projects):
        row = projects[key]
        runs = [_close_totals(run) for _, run in sorted(row.pop("_runs").items())]
        row = _close_totals(row)
        if runs:
            row["taskRuns"] = runs
        out.append(row)
    return out


def _add_totals(row: Dict[str, Any], receipt: Dict[str, Any]) -> None:
    row["calls"] += 1
    if receipt.get("tokensMeasured") is False:
        row["unmeasuredCalls"] = row.get("unmeasuredCalls", 0) + 1  # written only when above 0: absent is 0 (DEC-0091)
    for name in ("inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens"):
        row[name] += int(receipt.get(name) or 0)
    if receipt.get("costUsd") is None:
        row["unpricedCalls"] += 1
    else:
        row["_cost"] += float(receipt["costUsd"])


def _close_totals(row: Dict[str, Any]) -> Dict[str, Any]:
    cost = row.pop("_cost")
    row["costUsd"] = None if row["calls"] and row["unpricedCalls"] == row["calls"] else round(cost, 6)
    return row


_USAGE_WINDOW_DAYS = 31


def _usage_count(value: Any) -> int:
    """The contract's `count`: Number.isSafeInteger and not negative, so 5.0 (which JavaScript reads as 5) counts."""
    return int(value) if not isinstance(value, bool) and _jsv.safe_integer(value) and value >= 0 else 0


def _usage_money(value: Any) -> Optional[float]:
    """A JSON number as JavaScript holds it (an integer beyond a double is Infinity), or None for anything else."""
    return _jsv.double(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _usage_cost(value: Any) -> float:
    """The contract's `cost`: a known, finite, non-negative cost, or 0."""
    money = _usage_money(value)
    return money if money is not None and math.isfinite(money) and money >= 0 else 0.0


def _exceeds(a: float, b: float) -> bool:
    return a - b > 0.000001 + 1e-9 * max(abs(a), abs(b))


def _usd(value: float) -> str:
    rounded = round(value * 1e6) / 1e6
    return str(int(rounded)) if rounded == int(rounded) else repr(rounded)


def _usage_list(value: Any) -> List[Dict[str, Any]]:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _priced_row(row: Dict[str, Any], at: str) -> List[Dict[str, str]]:
    calls, unpriced = _usage_count(row.get("calls")), _usage_count(row.get("unpricedCalls"))
    flag = lambda path, message: [{"code": "FAC-SEM-025", "instancePath": path, "message": message}]  # noqa: E731
    if unpriced > calls:
        return flag(at + "/unpricedCalls", "more unpriced calls than calls")
    if _usage_count(row.get("unmeasuredCalls")) > calls:  # DEC-0091: unknown token counts are some of the calls
        return flag(at + "/unmeasuredCalls", "more calls with unknown tokens than calls")
    if calls > 0 and unpriced == calls and row.get("costUsd", _MISSING_COST) is not None:
        return flag(at + "/costUsd", "every call is unpriced, so the cost is unknown (null), not a number")
    if unpriced < calls and row.get("costUsd", _MISSING_COST) is None:
        return flag(at + "/costUsd", "priced calls carry a cost; null is only for a row with no priced call")
    return []


_MISSING_COST = object()


def usage_findings(report: Any) -> List[Dict[str, str]]:
    """FAC-SEM-025 over a usage report, in the contract's order (`src/usage-rules.ts`): the arithmetic of days and
    models, the window (every date exists, not after `generatedAt`'s UTC date, at most 30 days before it), and the
    project attribution (each project once by its normal form, each task run once; calls, priced calls and known costs
    bounded). Malformed input answers findings or none, never an exception."""
    import fabric_identifiers  # noqa: E402
    value = report if isinstance(report, dict) else {}
    findings: List[Dict[str, str]] = []
    flag = lambda path, message: findings.append({"code": "FAC-SEM-025", "instancePath": path, "message": message})  # noqa: E731
    days = _usage_list(value.get("days"))
    # The arithmetic.
    previous = ""
    for i, day in enumerate(days):
        at = "/days/%d" % i
        date = _jsv.show("" if day.get("date") is None else day["date"])  # the contract's show(day.date ?? "")
        if date <= previous:
            flag(at + "/date", "days must run forward without a repeat (%s after %s)" % (date, previous))
        previous = date
        findings.extend(_priced_row(day, at))
        models = _usage_list(day.get("byModel"))
        for j, m in enumerate(models):
            findings.extend(_priced_row(m, "%s/byModel/%d" % (at, j)))
        # The contract reads every count as `toNumber(x ?? 0)` and writes it with `show`: a string count is read as a
        # number, and what is no number (an object, "abc") is NaN, which equals no sum, so it is a finding.
        number = lambda row, f: _jsv.js_to_number(row.get(f))  # noqa: E731 - None and absent read as 0
        if not models:
            spent = any(number(day, f) > 0 for f in ("calls", "inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens")) \
                or number(day, "costUsd") > 0
            if spent:
                flag(at + "/byModel", "a day with calls, tokens or cost names the models they belong to")
            continue
        for field in ("calls", "unpricedCalls", "unmeasuredCalls", "inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens"):
            total = 0.0
            for m in models:
                total += number(m, field)  # in order, in doubles, as JavaScript adds
            if number(day, field) != total:
                shown = _jsv.show(0 if day.get(field) is None else day[field])
                flag("%s/%s" % (at, field), "the day's %s is not the sum of its models (%s ≠ %s)" % (field, shown, _jsv.js_string(total)))
        known = 0.0
        for m in models:
            money = _usage_money(m.get("costUsd"))
            known += money if money is not None else 0.0
        day_cost = _usage_money(day.get("costUsd"))
        # The contract's !close(day, known): Infinity or NaN is never close, so it is a finding.
        if day_cost is not None and not abs(day_cost - known) <= 0.000001 + 1e-9 * max(abs(day_cost), abs(known)):
            flag(at + "/costUsd", "the day's cost is not the sum of its models' known costs")
    # The window.
    if days:
        generated = _ftime.parse_rfc3339_ms(value.get("generatedAt"))
        if generated != generated:
            flag("/generatedAt", "generatedAt is an RFC 3339 date-time with an offset, so the window can be read")
        else:
            today = (generated // _DAY_MS) * _DAY_MS
            oldest = today - (_USAGE_WINDOW_DAYS - 1) * _DAY_MS
            for i, day in enumerate(days):
                date = _utc_date_ms(day.get("date"))
                if date != date:
                    flag("/days/%d/date" % i, "a day's date exists in its month")
                elif date > today:
                    flag("/days/%d/date" % i, "a day is not after the UTC date of generatedAt")
                elif date < oldest:
                    flag("/days/%d/date" % i, "a day is within the last %d UTC days of generatedAt" % _USAGE_WINDOW_DAYS)
    # The projects.
    if isinstance(value.get("byProject"), list):
        seen: Dict[str, str] = {}
        project_calls, project_cost = 0, 0.0
        for p, project in enumerate(value["byProject"]):
            if not isinstance(project, dict):
                continue
            at = "/byProject/%d" % p
            normal = fabric_identifiers.normal_identifier(project.get("projectId"))
            if normal is not None:
                if normal in seen:
                    flag(at + "/projectId", "each project is one row: %s names the project %s already names" % (project["projectId"], seen[normal]))
                else:
                    seen[normal] = project["projectId"]
            project_calls += _usage_count(project.get("calls"))
            project_cost += _usage_cost(project.get("costUsd"))
            findings.extend(_priced_row(project, at))
            runs: List[str] = []
            run_calls, run_cost, run_priced = 0, 0.0, 0
            for r, run in enumerate(_usage_list(project.get("taskRuns"))):
                if isinstance(run.get("taskRunId"), str):
                    if run["taskRunId"] in runs:
                        flag("%s/taskRuns/%d/taskRunId" % (at, r), "each task run is one row within its project")
                    runs.append(run["taskRunId"])
                run_calls += _usage_count(run.get("calls"))
                run_cost += _usage_cost(run.get("costUsd"))
                run_priced += max(0, _usage_count(run.get("calls")) - _usage_count(run.get("unpricedCalls")))
                findings.extend(_priced_row(run, "%s/taskRuns/%d" % (at, r)))
            project_priced = max(0, _usage_count(project.get("calls")) - _usage_count(project.get("unpricedCalls")))
            known_cost = _usage_cost(project.get("costUsd")) == _usage_money(project.get("costUsd"))  # as JavaScript holds it
            if run_calls > _usage_count(project.get("calls")):
                flag(at + "/taskRuns", "a project's task runs hold more calls than the project (%d > %d)" % (run_calls, _usage_count(project.get("calls"))))
            elif run_priced > project_priced:
                flag(at + "/taskRuns", "a project's task runs hold more priced calls than the project (%d > %d)" % (run_priced, project_priced))
            elif known_cost and _exceeds(run_cost, _usage_cost(project.get("costUsd"))):
                flag(at + "/taskRuns", "a project's task runs cost more than the project (%s > %s)" % (_usd(run_cost), _usd(_usage_cost(project.get("costUsd")))))
        day_calls = sum(_usage_count(d.get("calls")) for d in days)
        if project_calls > day_calls:
            flag("/byProject", "the projects hold more calls than the days (%d > %d)" % (project_calls, day_calls))
        day_cost_total = sum(_usage_cost(d.get("costUsd")) for d in days)
        if _exceeds(project_cost, day_cost_total):
            flag("/byProject", "the projects cost more than the days (%s > %s)" % (_usd(project_cost), _usd(day_cost_total)))
    return findings


OPENROUTER_CATEGORIES = ("cli-agent", "ide-extension", "cloud-agent", "programming-app", "native-app-builder",
                         "creative-writing", "video-gen", "image-gen", "audio-gen", "writing-assistant", "general-chat",
                         "personal-agent", "legal", "roleplay", "game")


_ATTR_PRODUCT = re.compile(r"[a-z][a-z0-9-]{0,62}", re.ASCII)


_ATTR_TITLE = re.compile(r"[\x21-\x7e](?:[\x20-\x7e]{0,98}[\x21-\x7e])?", re.ASCII)


_ATTRIBUTION_HEADERS = ("http-referer", "referer", "x-openrouter-title", "x-title", "x-openrouter-categories")


def attribution_setting_findings(value: Any) -> List[Dict[str, str]]:
    """FAC-SEM-098: a product's setting names a product slug, a printable title and at most two recognized categories."""
    if not isinstance(value, dict):
        return [{"code": "FAC-SEM-098", "instancePath": "", "message": "an attribution setting is an object"}]
    findings: List[Dict[str, str]] = []
    flag = lambda at, message: findings.append({"code": "FAC-SEM-098", "instancePath": at, "message": message})  # noqa: E731
    if not (isinstance(value.get("product"), str) and _ATTR_PRODUCT.fullmatch(value["product"])):
        flag("/product", "the product is a lower-case slug, the last segment of its product page")
    if not (isinstance(value.get("title"), str) and _ATTR_TITLE.fullmatch(value["title"])):
        flag("/title", "the title is the product's full name: printable ASCII, 1 to 100 characters, no space at either end")
    if "categories" in value:
        categories = value["categories"]
        if not isinstance(categories, list):
            flag("/categories", "categories are a list")
        else:
            if len(categories) > 2:
                flag("/categories", "at most 2 categories per request")
            seen: List[str] = []
            for i, category in enumerate(categories):
                if not (isinstance(category, str) and category in OPENROUTER_CATEGORIES):
                    flag("/categories/%d" % i, "a category is one OpenRouter recognizes; it drops others without an error")
                elif category in seen:
                    flag("/categories/%d" % i, "each category once")
                else:
                    seen.append(category)
    return findings


def _is_openrouter(url: Any) -> bool:
    """Whether a URL's WHATWG reading is https, host openrouter.ai, the default port and no credentials (`new URL`):
    leading and trailing spaces and controls trimmed, tabs and newlines removed, backslashes read as slashes, the
    slashes after the scheme optional, the host case-folded, port 443 the default."""
    if not isinstance(url, str):
        return False
    text = url.strip("".join(chr(c) for c in range(0x21))).replace("\t", "").replace("\n", "").replace("\r", "")
    if not text[:6].lower() == "https:":
        return False
    rest = text[6:].lstrip("/\\")
    end = len(rest)
    for stop in "/\\?#":
        found = rest.find(stop)
        if found != -1:
            end = min(end, found)
    authority = rest[:end]
    if "@" in authority:
        userinfo, authority = authority.rsplit("@", 1)
        if userinfo not in ("", ":"):
            return False
    host, _, port = authority.partition(":")
    if port and not (port.isdigit() and int(port) == 443):
        return False
    return host.lower() == "openrouter.ai"


def attribution_headers(setting: Any, request: Any) -> Dict[str, Any]:
    """The headers a product adds to one request (DEC-0065, the contract's `attributionHeaders`), or none with the reason:
    `no-setting` (attribution is off by default), `invalid-setting` (FAC-SEM-098), `not-openrouter` (only
    `https://openrouter.ai`), `forwarded` (only traffic the product originates), `user-set` (a request that already
    carries an attribution header keeps the user's own). Only `HTTP-Referer`, `X-OpenRouter-Title` and
    `X-OpenRouter-Categories`; it never reads, moves or returns a key."""
    req = request if isinstance(request, dict) else {}
    if setting is None:
        return {"headers": {}, "none": "no-setting"}
    if attribution_setting_findings(setting):
        return {"headers": {}, "none": "invalid-setting"}
    if not _is_openrouter(req.get("url")):
        return {"headers": {}, "none": "not-openrouter"}
    if req.get("originated") is not True:
        return {"headers": {}, "none": "forwarded"}
    present = [str(name).lower() for name in req["headers"]] if isinstance(req.get("headers"), dict) else []
    if any(name in _ATTRIBUTION_HEADERS for name in present):
        return {"headers": {}, "none": "user-set"}
    headers = {"HTTP-Referer": "https://passioncode.ai/%s/" % setting["product"], "X-OpenRouter-Title": setting["title"]}
    if setting.get("categories"):
        headers["X-OpenRouter-Categories"] = ",".join(setting["categories"])
    return {"headers": headers}


def usage_report(receipts: Iterable[Dict[str, Any]], *, service_id: str, instance: str = "default",
                 now: Optional[_dt.datetime] = None,
                 budget: Optional[Dict[str, Any]] = None,
                 budgets: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The `service-usage.schema.json` answer: the last 31 UTC days, oldest first, per provider
    and model. Days without calls are omitted. A row whose calls are all unpriced has
    `costUsd: None`; totals are the sums of the model rows (FAC-SEM-025).

    ``budgets`` (DEC-0027) lists every spending limit the service applies, enforced or not. A
    machine limit with a calendar ``period`` and no ``spentUsd`` is counted here from the receipts,
    the way ``budget`` is, so the two never disagree; a per-order limit (``per_job``, ``approval``)
    gets ``spentUsd: None``; every other limit states its own spend. A report whose limits break
    FAC-SEM-031 is refused (``usage_limit_problems``)."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    receipts = list(receipts)
    first = (now - _dt.timedelta(days=USAGE_DAYS - 1)).strftime("%Y-%m-%d")
    last = now.strftime("%Y-%m-%d")
    days: Dict[str, Dict[str, Dict[str, Any]]] = {}
    bases: Dict[Tuple[str, str, str], set] = {}
    for r in receipts:
        date = str(r.get("at", ""))[:10]
        if not (first <= date <= last):
            continue
        key = (r["provider"], r["model"], r.get("route") or "")
        row = days.setdefault(date, {}).setdefault("%s\u0000%s\u0000%s" % key, {
            "provider": r["provider"], "model": r["model"], "calls": 0, "unpricedCalls": 0,
            "inputTokens": 0, "outputTokens": 0, "cacheReadTokens": 0, "cacheWriteTokens": 0, "_cost": 0.0})
        if r.get("route"):
            row["route"] = r["route"]  # DEC-0046: rows of one model on two routes stay apart
        _add_totals(row, r)
        bases.setdefault((date,) + key, set()).add(r.get("costBasis") or "unknown")
    out_days = []
    for date in sorted(days):
        models = []
        for row in days[date].values():
            seen = bases[(date, row["provider"], row["model"], row.get("route") or "")]
            row["costBasis"] = next(iter(seen)) if len(seen) == 1 else "mixed"
            models.append(_close_totals(row))
        models.sort(key=lambda m: (m["provider"], m["model"], m.get("route") or ""))
        day = {"date": date, "calls": 0, "unpricedCalls": 0, "inputTokens": 0, "outputTokens": 0,
               "cacheReadTokens": 0, "cacheWriteTokens": 0, "_cost": 0.0}
        for m in models:
            for name in ("calls", "unpricedCalls", "inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens"):
                day[name] += m[name]
            if m.get("unmeasuredCalls"):
                day["unmeasuredCalls"] = day.get("unmeasuredCalls", 0) + m["unmeasuredCalls"]
            day["_cost"] += m["costUsd"] or 0.0
        day = _close_totals(day)
        day["byModel"] = models
        out_days.append(day)
    report: Dict[str, Any] = {"protocol": PROTOCOL, "service": {"id": service_id, "instance": instance},
                              "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "currency": "USD", "days": out_days}
    projects = _by_project(receipts, first, last)
    if projects:
        report["byProject"] = projects
    if budget is not None:
        if budget.get("period") not in ("day", "month") or not isinstance(budget.get("limitUsd"), (int, float)) or budget["limitUsd"] <= 0:
            raise ServiceError("budget is {period: day|month, limitUsd > 0}.")
        report["budget"] = {"period": budget["period"], "limitUsd": float(budget["limitUsd"]),
                            "spentUsd": _spent_in(out_days, budget["period"], last)}
    if budgets is not None:
        limits = []
        for given in budgets:
            if not isinstance(given, dict):
                raise ServiceError("each limit in budgets is an object")
            limit = dict(given)
            if "spentUsd" not in limit:
                if limit.get("kind") in PER_ORDER_KINDS:
                    limit["spentUsd"] = None
                elif limit.get("scope") == "machine" and limit.get("period") in ("day", "month"):
                    limit["spentUsd"] = _spent_in(out_days, limit["period"], last)
                elif limit.get("scope") == "machine" and _number(limit.get("windowSeconds")):
                    limit["spentUsd"] = _spent_since(receipts, now - _dt.timedelta(seconds=limit["windowSeconds"]), now)
            if isinstance(limit.get("limitUsd"), int) and not isinstance(limit.get("limitUsd"), bool):
                limit["limitUsd"] = float(limit["limitUsd"])
            limits.append(limit)
        report["budgets"] = limits
        problems = usage_limit_problems(report)
        if problems:
            raise ServiceError("the report's limits are not coherent: " + "; ".join(problems))
    return report


def usage_spend(rows: Any) -> Optional[Dict[str, Any]]:
    """What a host shows for usage rows (DEC-0110, the contract's ``usageSpend``): money spent apart from a
    subscription's estimate. ``rows`` are ``days[].byModel[]`` rows. Money is the ``costUsd`` of every row whose
    ``route`` is ``key``, ``platform-metered`` or absent; a ``subscription`` row's ``costUsd`` is an estimate at list
    price, summed apart. A window whose calls were all on a subscription spent 0; money is None only when it has calls
    off a subscription and none of them is priced, and a lower bound while some are priced and some are not. An unknown
    ``route``, or counts or a cost the schema refuses, answers None. It never raises on a JSON value."""
    if not isinstance(rows, list):
        return None
    money: List[float] = []
    estimate: List[float] = []
    calls = subscription_calls = 0
    paid = {"calls": 0, "priced": 0, "unpriced": False}
    sub = {"calls": 0, "priced": 0, "unpriced": False}
    for row in rows:
        if not isinstance(row, dict):
            return None
        route = row.get("route", _jsv.MISSING)
        if route is not _jsv.MISSING and not (isinstance(route, str) and route in USAGE_ROUTES):
            return None
        row_calls, cost = row.get("calls", _jsv.MISSING), row.get("costUsd", _jsv.MISSING)
        unpriced = row.get("unpricedCalls", 0)
        if not _whole(row_calls) or not _whole(unpriced) or unpriced > row_calls:
            return None
        if cost is not None and not _known_cost(cost):
            return None
        if row_calls > 0 and (cost is None) != (unpriced == row_calls):  # FAC-SEM-025's own pairing
            return None
        calls += int(row_calls)
        side = sub if route == "subscription" else paid
        if route == "subscription":
            subscription_calls += int(row_calls)
        side["calls"] += int(row_calls)
        side["priced"] += int(row_calls) - int(unpriced)
        if unpriced > 0:
            side["unpriced"] = True
        if _known_cost(cost):
            (estimate if route == "subscription" else money).append(_jsv.double(cost))

    def total(side: Dict[str, Any], costs: List[float]) -> Optional[float]:
        if side["calls"] > 0 and side["priced"] == 0:
            return None
        n: Any = 0
        for x in sorted(costs):  # in a fixed order, one addition at a time, as JavaScript's reduce adds
            n = n + x
        return n

    return {"calls": calls, "moneyUsd": total(paid, money), "moneyLowerBound": paid["priced"] > 0 and paid["unpriced"],
            "estimateUsd": total(sub, estimate), "estimateLowerBound": sub["priced"] > 0 and sub["unpriced"],
            "subscriptionCalls": subscription_calls}


def _whole(value: Any) -> bool:
    """Number.isSafeInteger(value) and not negative."""
    return _jsv.safe_integer(value) and value >= 0


def _known_cost(value: Any) -> bool:
    """A finite cost of at least 0, the number read as JavaScript holds it (an integer past the double range is
    Infinity, never an OverflowError)."""
    return _number(value) and math.isfinite(_jsv.double(value)) and value >= 0


def _money(spend: Optional[Dict[str, Any]]) -> Optional[float]:
    """CT-115: a limit counts money only, never a subscription's estimate (DEC-0110)."""
    if spend is None or spend["moneyUsd"] is None:
        return None
    return round(float(spend["moneyUsd"]), 6)


def _spent_since(receipts: List[Dict[str, Any]], start: _dt.datetime, end: _dt.datetime) -> Optional[float]:
    """Money spent in a rolling window, from the receipts' own times; None when no call off a subscription in it is
    priced. A subscription's calls cost no money (DEC-0110, CT-115)."""
    lo, hi = start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for r in receipts:
        if lo < str(r.get("at", "")) <= hi:
            row = {"calls": 1, "unpricedCalls": 1 if r.get("costUsd") is None else 0, "costUsd": r.get("costUsd")}
            if r.get("route"):
                row["route"] = r["route"]
            rows.append(row)
    return _money(usage_spend(rows))


def _spent_in(out_days: List[Dict[str, Any]], period: str, last: str) -> Optional[float]:
    """Money spent in the current UTC day or month, over the window's model rows; None when no call off a subscription
    in it is priced. A subscription's calls cost no money (DEC-0110, CT-115)."""
    prefix = last if period == "day" else last[:7]
    return _money(usage_spend([m for d in out_days if d["date"].startswith(prefix) for m in d["byModel"]]))


LIMIT_SCOPES = ("machine", "project", "pool", "job")


PER_ORDER_KINDS = ("per_job", "approval")


_LIMIT_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}\Z")


_LIMIT_KIND = re.compile(r"^[a-z][a-z0-9_]{0,31}\Z")


_LIMIT_FIELDS = ("id", "scope", "subject", "kind", "period", "windowSeconds", "since", "limitUsd", "spentUsd", "enforced", "tripped")


_TIMESTAMP = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]+)?([Zz]|[+-]([0-9]{2}):([0-9]{2}))")


def _is_timestamp(value: Any) -> bool:
    """A JSON Schema `date-time` (RFC 3339): a real calendar date and time, `Z` or an offset."""
    m = _TIMESTAMP.fullmatch(value) if isinstance(value, str) else None
    if not m:
        return False
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    try:
        _dt.date(year, month, day)
    except ValueError:
        return False
    offset_ok = m.group(9) is None or (int(m.group(9)) <= 23 and int(m.group(10)) <= 59)
    return hour <= 23 and minute <= 59 and second <= 60 and offset_ok


def usage_limit_problems(report: Dict[str, Any]) -> List[str]:
    """The `budgets` of a usage report against `service-usage.schema.json` `$defs/limit` and FAC-SEM-031: unique
    ids, a subject exactly for project and pool scope, one window that agrees with the kind, per-order limits with
    no window and no spend, only a relative limit with a null `limitUsd`, a tripped limit enforced, and a legacy
    `budget` that repeats one enforced machine limit. A breach (spent above the limit) is not a problem: a report
    truthfully shows one, and a host shows it first. An unknown kind is never refused."""
    problems: List[str] = []
    limits = report.get("budgets")
    if limits is None:
        return problems
    if not isinstance(limits, list) or len(limits) > 64:
        return ["budgets is a list of at most 64 limits"]
    seen = set()
    for i, limit in enumerate(limits):
        at = "/budgets/%d" % i
        if not isinstance(limit, dict):
            problems.append("%s is not an object" % at)
            continue
        for key in limit:
            if key not in _LIMIT_FIELDS:
                problems.append("%s/%s is not a limit field" % (at, key))
        for key in ("id", "scope", "kind", "limitUsd", "spentUsd", "enforced"):
            if key not in limit:
                problems.append("%s is missing %s" % (at, key))
        if "id" in limit and not (isinstance(limit["id"], str) and _LIMIT_ID.fullmatch(limit["id"])):
            problems.append("%s/id must match %s" % (at, _LIMIT_ID.pattern))
        if "scope" in limit and limit["scope"] not in LIMIT_SCOPES:
            problems.append("%s/scope must be one of %s" % (at, ", ".join(LIMIT_SCOPES)))
        if "subject" in limit and not (isinstance(limit["subject"], str) and 1 <= len(limit["subject"]) <= 128):
            problems.append("%s/subject is 1 to 128 characters" % at)
        if "kind" in limit and not (isinstance(limit["kind"], str) and _LIMIT_KIND.fullmatch(limit["kind"])):
            problems.append("%s/kind must match %s" % (at, _LIMIT_KIND.pattern))
        if "period" in limit and limit["period"] not in ("day", "month"):
            problems.append("%s/period is day or month" % at)
        if "windowSeconds" in limit and not (isinstance(limit["windowSeconds"], int) and not isinstance(limit["windowSeconds"], bool)
                                             and limit["windowSeconds"] >= 1):
            problems.append("%s/windowSeconds is a whole number of seconds, at least 1" % at)
        if "since" in limit and not _is_timestamp(limit["since"]):
            problems.append("%s/since is a UTC timestamp" % at)
        if "limitUsd" in limit and not (limit["limitUsd"] is None or (_number(limit["limitUsd"]) and limit["limitUsd"] > 0)):
            problems.append("%s/limitUsd is a dollar amount above zero, or null" % at)
        if "spentUsd" in limit and not (limit["spentUsd"] is None or (_number(limit["spentUsd"]) and limit["spentUsd"] >= 0)):
            problems.append("%s/spentUsd is a dollar amount, zero or more, or null" % at)
        for key in ("enforced", "tripped"):
            if key in limit and not isinstance(limit[key], bool):
                problems.append("%s/%s is true or false" % (at, key))

        # FAC-SEM-031
        ident = str(limit.get("id", ""))
        if ident in seen:
            problems.append("FAC-SEM-031 %s/id: limit id %s appears twice" % (at, ident))
        seen.add(ident)
        scope = limit.get("scope")
        named = scope in ("project", "pool")
        if named and "subject" not in limit:
            problems.append("FAC-SEM-031 %s/subject: a %s limit names its %s in subject" % (at, scope, scope))
        if not named and "subject" in limit:
            problems.append("FAC-SEM-031 %s/subject: a %s limit has no subject" % (at, scope))
        windows = [f for f in ("period", "windowSeconds", "since") if f in limit]
        if len(windows) > 1:
            problems.append("FAC-SEM-031 %s/%s: a limit has one window, not %s" % (at, windows[1], " and ".join(windows)))
        kind = str(limit.get("kind", ""))
        seconds = limit.get("windowSeconds") if _number(limit.get("windowSeconds")) else None
        if kind in PER_ORDER_KINDS:
            if windows:
                problems.append("FAC-SEM-031 %s/%s: %s bounds one order and has no window" % (at, windows[0], kind))
            if limit.get("spentUsd", 0) is not None:
                problems.append("FAC-SEM-031 %s/spentUsd: %s bounds one order, so nothing is spent against it (null)" % (at, kind))
        elif kind == "daily":
            if not (limit.get("period") == "day" or seconds == 86400):
                problems.append("FAC-SEM-031 %s/period: a daily limit counts the UTC day (period day) or the last 24 hours (windowSeconds 86400)" % at)
        elif kind == "monthly":
            if not (limit.get("period") == "month" or (seconds is not None and 28 * 86400 <= seconds <= 31 * 86400)):
                problems.append("FAC-SEM-031 %s/period: a monthly limit counts the UTC month (period month) or a rolling 28–31 days (windowSeconds)" % at)
        elif kind == "velocity":
            if seconds is None:
                problems.append("FAC-SEM-031 %s/windowSeconds: a velocity limit counts a rolling window (windowSeconds)" % at)
        elif kind in ("pool", "emergency"):
            if not windows:
                problems.append("FAC-SEM-031 %s/period: a %s limit names the window it counts (period, windowSeconds or since)" % (at, kind))
        known = kind in PER_ORDER_KINDS or kind in ("daily", "monthly", "pool", "emergency")
        if known and "limitUsd" in limit and limit["limitUsd"] is None:
            problems.append("FAC-SEM-031 %s/limitUsd: a %s limit is a dollar amount; only a relative limit (velocity) may leave it null" % (at, kind))
        if limit.get("tripped") is True and limit.get("enforced") is not True:
            problems.append("FAC-SEM-031 %s/tripped: a limit that is not enforced cannot have stopped work" % at)

    budget = report.get("budget")
    if isinstance(budget, dict) and limits:
        kind = "daily" if budget.get("period") == "day" else "monthly"

        def same(x: Any, y: Any) -> bool:
            if x is None or y is None:
                return x is y
            return _number(x) and _number(y) and abs(x - y) <= 0.000001

        twin = any(isinstance(l, dict) and l.get("scope") == "machine" and l.get("enforced") is True and l.get("kind") == kind
                   and l.get("period") == budget.get("period") and same(l.get("limitUsd"), budget.get("limitUsd"))
                   and same(l.get("spentUsd"), budget.get("spentUsd")) for l in limits)
        if not twin:
            problems.append("FAC-SEM-031 /budget: budget repeats one enforced machine %s limit with period %s in budgets[], so old "
                            "and new readers agree" % (kind, budget.get("period")))
    return problems


class JsonlUsageLedger:
    """Usage receipts for services that keep none yet: append-only JSON lines, mode 0600, pruned
    to the reported window so the file stays bounded (LC-12). One writer process — the service,
    which holds its instance lock; the lock here orders that process's threads."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def record(self, receipt: Dict[str, Any]) -> None:
        line = json.dumps(receipt, separators=(",", ":")) + "\n"
        with self._lock:
            ensure_private_dir(self.path.parent)
            fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT | os.O_APPEND | _O_BINARY, 0o600)
            try:
                size = os.fstat(fd).st_size
                if size and _read_at(fd, 1, size - 1) != b"\n":
                    line = "\n" + line  # a killed writer left a torn line: never glue a receipt to it
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)

    def receipts(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # a torn last line from a killed writer is skipped, not fatal
        return out

    def prune(self, now: Optional[_dt.datetime] = None) -> int:
        """Drop receipts older than the reported window; returns how many were dropped."""
        now = now or _dt.datetime.now(_dt.timezone.utc)
        first = (now - _dt.timedelta(days=USAGE_DAYS - 1)).strftime("%Y-%m-%d")
        with self._lock:
            every = self.receipts()
            kept = [r for r in every if str(r.get("at", ""))[:10] >= first]
            dropped = len(every) - len(kept)
            if dropped:
                atomic_write(self.path, "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in kept).encode("utf-8"))
            return dropped

    def report(self, *, service_id: str, instance: str = "default", now: Optional[_dt.datetime] = None,
               budget: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return usage_report(self.receipts(), service_id=service_id, instance=instance, now=now, budget=budget)
