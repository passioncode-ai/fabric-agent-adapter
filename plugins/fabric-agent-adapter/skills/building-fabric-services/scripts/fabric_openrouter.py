"""OpenRouter chat completions for a service: its own key, a spend ceiling checked before every attempt, a usage
receipt for every answered call, and a fallback model of another vendor.

    client = fabric_openrouter.Client(ceiling_usd=2.0, ledger=JsonlUsageLedger(state / "usage.jsonl"),
                                      prices=fabric_openrouter.prices_from_catalog(catalog))
    answer = client.chat([{"role": "user", "content": "..."}], model="deepseek/deepseek-v4.1-flash",
                         fallback="qwen/qwen3.8-flash", max_tokens=800)
    answer["content"], answer["receipt"]["costUsd"]

Rules (FAA-65 REQ-07; the model guide is creating-fabric-agents references/models-and-providers.md):

- **The key** is read from the environment variable `key_env` names (`OPENROUTER_API_KEY` by default) when a call is
  made; it is sent only in the `Authorization` header to `base_url`, never logged and never in an error.
- **The ceiling.** Before every attempt, retries and the fallback included, the client adds what the window has
  spent (the ledger's receipts in the UTC day or month, plus calls in flight) to this attempt's worst case: the
  prompt counted as one token per two UTF-8 bytes, `max_tokens` of output, at the model's price. Over the ceiling, the
  attempt is not sent (`OpenRouterError` kind `ceiling`). A model without a price is not sent (`unpriced`): its spend
  could not be bounded. A receipt without a cost counts as `unmeasured_call_usd`, by default this attempt's own worst
  case.
- **Receipts.** Every answer with status 200 records one receipt (`provider: openrouter`, `route: key`): the served
  model, the provider's token counts, `costUsd` from `usage.cost`, or from the price list when only tokens came
  (`costBasis: price-list`), or `null` with `tokensMeasured: false` when the answer carried no usage. A refused
  request (4xx, 5xx) records nothing: it was not billed.
- **What is an answer.** `finish_reason` `stop` or `tool_calls` with content or tool calls. `error` is retried on
  the same model; `length` (the budget ran out, reasoning included), `content_filter` and an empty answer go to the
  fallback. Never returned as success.
- **Retries.** 408, 429, 5xx and connection errors are retried on the same model (`retries` times, `Retry-After`
  honoured) within one deadline for the whole call; then the fallback is tried the same way. 401, 402 and 403 stop at
  once: a key, credit or permission problem is the same on every model.
- **The fallback** is required and of another vendor (the part before `/` differs).
- **Attribution** is off unless an attribution setting is given (FAC-SEM-098, `fabric_usage.attribution_headers`).

The transport is fabric_http's, injected in tests. Standard library only. Part of the service kit (FAA-65, layer L4).
"""
from __future__ import annotations

import json
import math
import os
import random as _random
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

import fabric_http
import fabric_time
import fabric_usage

BASE_URL = "https://openrouter.ai/api/v1"
ANSWERED = ("stop", "tool_calls")
_STOP_AT_ONCE = {401: "auth", 402: "payment", 403: "auth"}
_RESERVED_PARAMS = ("model", "messages", "max_tokens", "stream", "usage")


class OpenRouterError(Exception):
    """No answer the caller can use. `kind`: config, unpriced, ceiling, auth, payment, failed. `attempts` lists every
    attempt as `{model, status, outcome}`; nothing in it holds the key or the prompt."""

    def __init__(self, message: str, *, kind: str, attempts: Optional[List[Dict[str, Any]]] = None):
        super().__init__(message)
        self.kind = kind
        self.attempts = list(attempts or [])


def vendor(model: str) -> str:
    return str(model).split("/", 1)[0] if "/" in str(model) else ""


def _price(value: Any) -> Optional[float]:
    """A catalog price (a decimal string or a number, USD per token) as a float; None when not a finite number >= 0."""
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def prices_from_catalog(catalog: Any) -> Dict[str, Dict[str, float]]:
    """`{model: {prompt, completion, request}}` in USD per token (per request) from `GET /api/v1/models`
    (`{"data": [{"id", "pricing": {"prompt", "completion", "request"}}]}`). A model whose prompt or completion price
    is missing or unreadable is left out, so the client refuses it rather than guessing."""
    out: Dict[str, Dict[str, float]] = {}
    rows = catalog.get("data") if isinstance(catalog, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        pricing = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
        prompt, completion = _price(pricing.get("prompt")), _price(pricing.get("completion"))
        if prompt is None or completion is None:
            continue
        out[row["id"]] = {"prompt": prompt, "completion": completion, "request": _price(pricing.get("request")) or 0.0}
    return out


def prompt_tokens_bound(messages: Any) -> int:
    """An upper bound on a prompt's tokens: one token per two UTF-8 bytes of the messages as compact JSON (as `JSON.stringify` writes it). Real tokenizers
    average three to four bytes a token on prose; the bound is meant to be loose."""
    return math.ceil(len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) / 2)


def _count(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _check_attribution(project_id: Optional[str], task_run_id: Optional[str]) -> None:
    """Refuse, before a call is sent, a project or task run its receipt would refuse after the call was billed."""
    try:
        fabric_usage.make_usage_receipt("openrouter", "check", input_tokens=0, output_tokens=0,
                                        project_id=project_id, task_run_id=task_run_id)
    except fabric_usage.ServiceError as err:
        raise OpenRouterError(str(err), kind="config")


class Client:
    def __init__(self, *, ceiling_usd: float, ledger: Any, prices: Mapping[str, Mapping[str, float]],
                 key_env: str = "OPENROUTER_API_KEY", window: str = "day", base_url: str = BASE_URL,
                 attribution: Optional[Mapping[str, Any]] = None, project_id: Optional[str] = None,
                 unmeasured_call_usd: Optional[float] = None, deadline_s: float = 120.0, retries: int = 1,
                 environ: Optional[Mapping[str, str]] = None, transport: Optional[fabric_http.Transport] = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], float] = time.time, rand: Callable[[], float] = _random.random):
        if isinstance(ceiling_usd, bool) or not isinstance(ceiling_usd, (int, float)) or not ceiling_usd >= 0 \
                or not math.isfinite(ceiling_usd):
            raise OpenRouterError("ceiling_usd is a finite number of dollars, 0 or more", kind="config")
        if window not in ("day", "month"):
            raise OpenRouterError("window is day or month (UTC)", kind="config")
        if not (hasattr(ledger, "record") and hasattr(ledger, "receipts")):
            raise OpenRouterError("ledger has record(receipt) and receipts(), as fabric_usage.JsonlUsageLedger",
                                  kind="config")
        if not (isinstance(retries, int) and 0 <= retries <= 5) or isinstance(retries, bool):
            raise OpenRouterError("retries is an integer from 0 to 5", kind="config")
        fabric_http.check_url(base_url)
        _check_attribution(project_id, None)
        self.ceiling_usd = float(ceiling_usd)
        self.ledger = ledger
        self.prices = {str(k): dict(v) for k, v in prices.items()}
        self.key_env = key_env
        self.window = window
        self.base_url = base_url.rstrip("/")
        self.attribution = attribution
        self.project_id = project_id
        self.unmeasured_call_usd = unmeasured_call_usd
        self.deadline_s = deadline_s
        self.retries = retries
        self._environ = os.environ if environ is None else environ
        self._transport = transport
        self._sleep, self._clock, self._now, self._rand = sleep, clock, now, rand
        self._lock = threading.Lock()
        self._in_flight = 0.0

    # -- money ---------------------------------------------------------------------------------------------------
    def worst_case_usd(self, model: str, messages: Any, max_tokens: int) -> Optional[float]:
        """What one attempt may cost at most, or None when the model has no price."""
        price = self.prices.get(model)
        if not price or _price(price.get("prompt")) is None or _price(price.get("completion")) is None:
            return None
        return (prompt_tokens_bound(messages) * float(price["prompt"]) + max_tokens * float(price["completion"])
                + float(_price(price.get("request")) or 0.0))

    def _in_window(self, at: Any, today: str) -> bool:
        ms = fabric_time.parse_rfc3339_ms(at)
        if math.isnan(ms):
            return False
        day = fabric_time.utc_day(ms)
        return day == today if self.window == "day" else day[:7] == today[:7]

    def spent_usd(self, *, unmeasured_usd: float = 0.0) -> float:
        """What the ledger records for the current window; a receipt without a cost counts as `unmeasured_usd`."""
        today = fabric_time.utc_day(fabric_time.now_ms(self._now))
        total = 0.0
        for receipt in self.ledger.receipts():
            if not isinstance(receipt, dict) or not self._in_window(receipt.get("at"), today):
                continue
            cost = receipt.get("costUsd")
            measured = isinstance(cost, (int, float)) and _price(cost) is not None
            total += float(cost) if measured else unmeasured_usd
        return total

    def _reserve(self, model: str, messages: Any, max_tokens: int) -> float:
        worst = self.worst_case_usd(model, messages, max_tokens)
        if worst is None:
            raise OpenRouterError("%s has no price: its spend cannot be bounded, so it is not called" % model,
                                  kind="unpriced")
        unmeasured = worst if self.unmeasured_call_usd is None else float(self.unmeasured_call_usd)
        with self._lock:
            spent = self.spent_usd(unmeasured_usd=unmeasured) + self._in_flight
            if spent + worst > self.ceiling_usd:
                raise OpenRouterError("the %s ceiling of $%.4f would be passed: spent $%.4f, this attempt up to $%.4f"
                                      % (self.window, self.ceiling_usd, spent, worst), kind="ceiling")
            self._in_flight += worst
        return worst

    def _release(self, amount: float) -> None:
        with self._lock:
            self._in_flight = max(0.0, self._in_flight - amount)

    # -- receipts ------------------------------------------------------------------------------------------------
    def _receipt(self, asked: str, body: Mapping[str, Any], task_run_id: Optional[str]) -> Dict[str, Any]:
        served = body.get("model") if isinstance(body.get("model"), str) and body.get("model").strip() else asked
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else None
        at = fabric_time.format_rfc3339(fabric_time.now_ms(self._now))
        common = dict(at=at, route="key", project_id=self.project_id, task_run_id=task_run_id)
        prompt = _count(usage.get("prompt_tokens")) if usage else None
        completion = _count(usage.get("completion_tokens")) if usage else None
        if prompt is None or completion is None:
            return fabric_usage.make_usage_receipt("openrouter", served[:128], input_tokens=0, output_tokens=0,
                                                   tokens_measured=False, **common)
        details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
        cached = _count(details.get("cached_tokens")) or 0
        written = _count(details.get("cache_write_tokens")) or 0
        # prompt_tokens counts cache reads and writes; a receipt keeps them apart, as Anthropic's usage block does
        cost = _price(usage.get("cost")) if isinstance(usage.get("cost"), (int, float)) else None
        basis = "provider"
        if cost is None:
            price = self.prices.get(served) or self.prices.get(asked)
            if price:
                cost = prompt * float(price["prompt"]) + completion * float(price["completion"])
                basis = "price-list"
        return fabric_usage.make_usage_receipt(
            "openrouter", served[:128], input_tokens=max(0, prompt - cached - written), output_tokens=completion,
            cache_read_tokens=cached, cache_write_tokens=written, cost_usd=cost,
            cost_basis=basis if cost is not None else None, **common)

    # -- the call ------------------------------------------------------------------------------------------------
    def _key(self) -> str:
        key = self._environ.get(self.key_env, "")
        if not key or any(c in key for c in "\r\n\0 "):
            raise OpenRouterError("no usable key in the environment variable %s" % self.key_env, kind="config")
        return key

    def _headers(self, key: str) -> Dict[str, str]:
        headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
        if self.attribution is not None:
            headers.update(fabric_usage.attribution_headers(
                self.attribution, {"url": self.base_url, "originated": True, "headers": {}})["headers"])
        return headers

    def chat(self, messages: List[Mapping[str, Any]], *, model: str, fallback: str, max_tokens: int,
             task_run_id: Optional[str] = None, **params: Any) -> Dict[str, Any]:
        """One chat completion: `{content, message, model, finish_reason, receipt, attempts}`; `OpenRouterError`
        when no attempt gave an answer. `params` go into the request body as they are (temperature, reasoning,
        response_format, tools...)."""
        if not isinstance(messages, list) or not messages:
            raise OpenRouterError("messages is a non-empty list", kind="config")
        if not vendor(model) or not vendor(fallback) or vendor(model) == vendor(fallback):
            raise OpenRouterError("the fallback is a model of another vendor than %s" % model, kind="config")
        if not (isinstance(max_tokens, int) and not isinstance(max_tokens, bool) and 1 <= max_tokens <= 200_000):
            raise OpenRouterError("max_tokens is an integer from 1 to 200000", kind="config")
        _check_attribution(self.project_id, task_run_id)  # before anything is sent: a billed call keeps its receipt
        clash = [k for k in params if k in _RESERVED_PARAMS]
        if clash:
            raise OpenRouterError("the client sets %s itself" % ", ".join(sorted(clash)), kind="config")
        headers = self._headers(self._key())
        url = self.base_url + "/chat/completions"
        end = self._clock() + self.deadline_s
        attempts: List[Dict[str, Any]] = []
        for current in (model, fallback):
            body = {"model": current, "messages": messages, "max_tokens": max_tokens, "usage": {"include": True},
                    **params}
            for tried in range(self.retries + 1):
                left = end - self._clock()
                if left <= 0:
                    raise OpenRouterError("the deadline passed after %d attempts" % len(attempts), kind="failed",
                                          attempts=attempts)
                try:
                    held = self._reserve(current, messages, max_tokens)
                except OpenRouterError as refused:
                    refused.attempts = list(attempts)
                    raise
                wait: Optional[float] = None
                try:
                    outcome, status, wait, answer = self._attempt(url, headers, body, left, current, task_run_id)
                finally:
                    self._release(held)
                attempts.append({"model": current, "status": status, "outcome": outcome})
                if answer is not None:
                    answer["attempts"] = attempts
                    return answer
                if outcome in _STOP_AT_ONCE.values():
                    raise OpenRouterError("OpenRouter refused the key or the request (%s)" % status, kind=outcome,
                                          attempts=attempts)
                if outcome not in ("retry", "error") or tried == self.retries:
                    break  # next model
                if wait is None:
                    wait = fabric_http.backoff_s(tried, base_s=0.5, max_s=8.0, rand=self._rand())
                if self._clock() + wait >= end:
                    break
                self._sleep(wait)
        raise OpenRouterError("no answer from %s or %s" % (model, fallback), kind="failed", attempts=attempts)

    def _attempt(self, url: str, headers: Dict[str, str], body: Dict[str, Any], left: float, asked: str,
                 task_run_id: Optional[str]):
        """One request: (outcome, status, wait_s, answer or None). Outcomes: answered, retry, error, length,
        filtered, empty, refused, bad-answer, auth, payment."""
        try:
            response = fabric_http.request("POST", url, headers=headers, body=body, deadline_s=left, retries=0,
                                           transport=self._transport, clock=self._clock)
        except fabric_http.HttpError as err:
            return ("retry" if err.kind in ("connection", "timeout") else "refused"), None, None, None
        status = response.status
        if status in _STOP_AT_ONCE:
            return _STOP_AT_ONCE[status], status, None, None
        if status != 200:
            if status in fabric_http.RETRY_STATUSES:
                return "retry", status, fabric_http.retry_after_s(response.headers.get("retry-after")), None
            return "refused", status, None, None
        try:
            parsed = response.json()
        except ValueError:
            return "bad-answer", status, None, None
        if not isinstance(parsed, dict):
            return "bad-answer", status, None, None
        receipt = self._receipt(asked, parsed, task_run_id)
        self.ledger.record(receipt)
        choices = parsed.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        finish = choice.get("finish_reason")
        content = message.get("content") if isinstance(message.get("content"), str) else ""
        tools = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
        if finish == "error" or isinstance(parsed.get("error"), dict):
            return "error", status, None, None
        if finish == "length":
            return "length", status, None, None
        if finish == "content_filter":
            return "filtered", status, None, None
        if finish not in ANSWERED or not (content.strip() or tools):
            return "empty", status, None, None
        return "answered", status, None, {"content": content, "message": message, "model": receipt["model"],
                                          "finish_reason": finish, "receipt": receipt}


def totals(receipts: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Calls, priced spend and unpriced calls over receipts (what a dashboard line shows); `spentUsd` is None when
    every call is unpriced."""
    calls = priced = 0
    spent = 0.0
    for r in receipts:
        calls += 1
        if isinstance(r.get("costUsd"), (int, float)) and _price(r.get("costUsd")) is not None:
            priced += 1
            spent += float(r["costUsd"])
    return {"calls": calls, "spentUsd": spent if priced else None, "unpricedCalls": calls - priced}
