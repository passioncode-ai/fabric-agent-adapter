# Connectors: outbound HTTP and OpenRouter

Two kit modules a service uses to reach the outside: `fabric_http` for any HTTP API, `fabric_openrouter` for models.
Both have Node twins (`fabric-http.mjs`, `fabric-openrouter.mjs`) that run the same cases
(`test/fixtures/kit-http-cases.json`, `test/fixtures/kit-openrouter-cases.json`). Install them with
`fabric_kit.py install <dir> --module fabric_openrouter` ([kit modules](kit-modules.md)). The project board has its
own connector ([board](board.md)). Standard library only; tests inject the transport and never open the network.

## Contents

- [fabric_http](#fabric_http)
- [fabric_openrouter](#fabric_openrouter)
- [Writing a connector for another API](#writing-a-connector-for-another-api)

## fabric_http

```python
import fabric_http
answer = fabric_http.request("GET", "https://api.example/v1/items", headers={"Authorization": "Bearer " + token},
                             deadline_s=20, retries=2)
answer.status, answer.headers["content-type"], answer.json()
```

```js
import { request } from './fabric-http.mjs';
const answer = await request('GET', 'https://api.example/v1/items', { headers, deadlineS: 20, retries: 2 });
```

| Rule | Default | Why |
|---|---|---|
| One deadline covers every attempt and every wait | `deadline_s` 30 | a caller's own deadline is one number, not one per retry |
| Retried: 408, 425, 429, 500, 502, 503, 504 and connection errors | `retries` 2 (0 to 10) | transient failures |
| Only when repeating is safe: `GET`, `HEAD`, `OPTIONS`, `PUT`, `DELETE`, or an `Idempotency-Key` header; any other request only on 429 | | a second `POST` after a timeout may do the work twice |
| Wait before retry n: `min(max_backoff_s, backoff_base_s * 2**n) * (0.5 + random())` | 0.5 s base, 8 s cap | jitter spreads retries of many clients |
| `Retry-After` (seconds, or an IMF-fixdate) replaces the wait; over `max_retry_after_s` the answer stands | 30 s | the server knows when it recovers |
| A wait that would pass the deadline is not taken: the last answer or error stands | | |
| The body is read to one byte past `max_bytes`; over it is an error | 8 MiB | a runaway answer never fills memory |
| Redirects are answered, never followed | | a redirect must not carry the `Authorization` header to another host |
| Plain `http://` is refused unless the host is loopback or `insecure=True`; credentials in a URL are refused | | a token never crosses a network in clear, nor sits in a URL |
| Header names must be tokens; a value with a line break or NUL is refused | | header injection |

Every answer comes back as a `Response`, whatever its status; `HttpError` means no usable answer came, with `kind`
`connection`, `timeout`, `too-large` or `refused`, the status when there was one, and the URL redacted to scheme,
host, port and path (`redact_url`). An error never carries a request header or body.

## fabric_openrouter

```python
import fabric_openrouter, fabric_usage
client = fabric_openrouter.Client(ceiling_usd=2.0, window="day",
                                  ledger=fabric_usage.JsonlUsageLedger(state / "usage.jsonl"),
                                  prices=fabric_openrouter.prices_from_catalog(catalog))
answer = client.chat(messages, model="deepseek/deepseek-v4.1-flash", fallback="qwen/qwen3.8-flash", max_tokens=800)
answer["content"], answer["receipt"]["costUsd"], answer["attempts"]
```

```js
const client = new Client({ ceilingUsd: 2, ledger: new JsonlUsageLedger(file), prices: pricesFromCatalog(catalog) });
const answer = await client.chat(messages, { model, fallback, maxTokens: 800 });
```

| Rule | What happens |
|---|---|
| The key | read from the environment variable `key_env` names (`OPENROUTER_API_KEY`) at each call; sent only in `Authorization`; missing is `OpenRouterError` kind `config` before anything is sent |
| The ceiling, before every attempt | the window's spend (ledger receipts in the UTC `day` or `month`) plus calls in flight plus this attempt's worst case must stay within `ceiling_usd`; otherwise kind `ceiling`, nothing sent. Retries and the fallback are checked the same way |
| The worst case | the prompt at one token per two UTF-8 bytes of the messages as compact JSON (`prompt_tokens_bound`), `max_tokens` of output, at the model's price, plus a per-request price |
| A model without a price | never called (kind `unpriced`): its spend could not be bounded. Prices come from `GET https://openrouter.ai/api/v1/models` through `prices_from_catalog` |
| A receipt without a cost in the window | counted at `unmeasured_call_usd`, by default this attempt's worst case |
| Receipts | every status-200 answer records one: the served model, the provider's tokens (cache reads and writes kept apart), `costUsd` from `usage.cost`, else from the price list (`costBasis: price-list`), else `null` with `tokensMeasured: false`; `route: key`, the client's `project_id` and the call's `task_run_id`. A refused request records nothing |
| What is an answer | `finish_reason` `stop` or `tool_calls` with content or tool calls; `error` is retried on the same model; `length` (the budget ran out, reasoning included), `content_filter` and empty content go to the fallback |
| Retries | 408, 429, 5xx and connection errors on the same model, `retries` times (default 1), `Retry-After` honoured, within one deadline (`deadline_s` 120) for the whole call |
| Stop at once | 401, 402 and 403 (kinds `auth`, `payment`): a key, credit or permission problem is the same on every model |
| The fallback | required, of another vendor (the part before `/` differs) |
| Attribution | off unless an `attribution` setting is given (FAC-SEM-098, `fabric_usage.attribution_headers`) |
| Request body | `model`, `messages`, `max_tokens`, `usage: {include: true}` and your params (temperature, reasoning, response_format, tools); `stream`, `model`, `messages`, `max_tokens` and `usage` as params are refused |

`OpenRouterError.attempts` lists every attempt as `{model, status, outcome}` (`answered`, `retry`, `error`,
`length`, `filtered`, `empty`, `refused`, `bad-answer`, `auth`, `payment`); nothing in it holds the key or the
prompt. `totals(receipts)` gives calls, priced spend and unpriced calls for a dashboard line. Choosing the models
themselves: creating-fabric-agents, `references/models-and-providers.md`.

## Writing a connector for another API

Build it on `fabric_http.request`: one module per API, the key read from a named environment variable at call time,
the deadline and retries passed through, the provider's own answer mapped into your types, and a receipt through
`fabric_usage.make_usage_receipt` for every billed call. Put it in your service, not in the kit, unless several
services need it; a kit module also needs its Node twin and shared cases ([adding a module](kit-modules.md#adding-or-changing-a-module)).
