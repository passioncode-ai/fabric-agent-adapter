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
| A JSON body is written as `JSON.stringify` writes it: a lone surrogate escaped, NaN and Infinity refused | | both twins send the same bytes |
| Whatever the transport throws is a connection error, in both languages; a timeout is a timeout | | |
| The deadline is held across the whole response: a watchdog shuts the socket when it passes, so trickled headers or a trickled chunk cannot hold the caller | | |
| `Response.json()` reads as `JSON.parse` does: a byte order mark skipped, `NaN` and `Infinity` refused | | |

Every answer comes back as a `Response`, whatever its status; `HttpError` means no usable answer came, with `kind`
`connection`, `timeout`, `too-large` or `refused`, the status when there was one, and the URL redacted to scheme,
host, port and path (`redact_url`); a URL that is not http or https keeps only its scheme (`htps:<redacted>`), and
one that does not parse as a URL is `<unparseable url>`. The path is not redacted (Node writes it as `new URL`
normalises it, Python as given), so a key never belongs in it. Python's `check_url` refuses a host
with a backslash, space, control character (C0, DEL or C1) or `%`, a URL with a space or ASCII control character before its
first `#` (the default transport sends a URL up to there, as Node's does; a transport you pass receives the URL as given), or a character outside ASCII in its path or query (ASCII whitespace at its ends is trimmed, as urllib and `new URL` trim it; a Unicode space ending the part before the first `#` is refused, where Node keeps it percent-encoded), and a port that is not
ASCII digits, all as kind `refused` before sending; it checks a host's shape, not its name. `redact_url` on Python reads a host holding `%` as `<unparseable url>`; Node writes it decoded. An error never carries a request header or body.

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
| The worst case | the input at one token per two UTF-8 bytes of the messages and every param (tools, response_format) as compact JSON (`prompt_tokens_bound`), `max_tokens` of output, at the model's price, plus a per-request price. `models`, `route`, `plugins`, `web_search_options` and `n` are refused (they change what is billed), and so is `max_completion_tokens` (the client sets the output budget) |
| A model without a price | never called (kind `unpriced`): its spend could not be bounded. Prices come from `GET https://openrouter.ai/api/v1/models` through `prices_from_catalog`; a price is a plain decimal string or a number, and anything else (blank, hex, a list) is no price |
| A receipt without a cost in the window | an unmeasured attempt, or an answer that came with no usage, counted at the worst case of the attempt that wrote it while this client runs; one written before it started counts as `unmeasured_call_usd`, by default the current attempt's worst case |
| Receipts | every status-200 answer records one, and so does an attempt that may have been billed without an answer to read (a timeout, a cut or refused connection, a 200 over the size cap or not JSON: no tokens, `costUsd: null`, `tokensMeasured: false`; over-counting a refused connection is the safe side): the served model, the provider's tokens (cache reads and writes kept apart), `costUsd` from `usage.cost`, else from the price list (`costBasis: price-list`), else `null` with `tokensMeasured: false`; `route: key`, the client's `project_id` and the call's `task_run_id`. A request the provider answered with a 4xx or 5xx records nothing: it was not billed |
| What is an answer | `finish_reason` `stop` or `tool_calls` with content or tool calls; `error` is retried on the same model; `length` (the budget ran out, reasoning included), `content_filter` and empty content go to the fallback |
| Retries | 408, 425, 429, 500, 502, 503, 504 and connection errors on the same model, `retries` times (default 1), `Retry-After` honoured, within one deadline (`deadline_s` 120) for the whole call |
| Stop at once | 401, 402 and 403 (kinds `auth`, `payment`): a key, credit or permission problem is the same on every model |
| The fallback | required, of another vendor (the part before `/` differs) |
| Content | text only: a string, null, or parts that are all `{"type": "text"}`; an image, audio or file part is refused (`config`), because what it is billed cannot be bounded from its bytes |
| What the ceiling does not cover | the `provider` routing param can send a call to a provider priced above the catalog; two `Client` objects sharing one ledger each hold only their own calls in flight, so give an agent one client per key |
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
