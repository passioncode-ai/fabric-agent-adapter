# Usage report: what the agent spent (DEC-0021)

Fabric Agent Contract DEC-0021, `docs/specification/service.md` → *Usage report*, schema
`schemas/service-usage.schema.json`. Optional. A service that calls paid models or tools should
offer it, so Fabric Dashboards (Spend, MCP `spend`) and Fabric can show each agent's spend beside
its health without knowing any provider.

## Contents

- What to record
- What to answer
- By project (DEC-0065)
- OpenRouter attribution (DEC-0065)
- Verify

## What to record

One **receipt per model call**, built from the numbers the provider returned:

```python
receipt = fs.make_usage_receipt("anthropic", "claude-sonnet-5-5",
                                input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                                cache_read_tokens=u.cache_read_input_tokens or 0,
                                cost_usd=charged, cost_basis="provider")   # or "price-list"
ledger.record(receipt)                     # fs.JsonlUsageLedger(data / "usage.jsonl")
```

```js
ledger.record(k.makeUsageReceipt('openrouter', model, { inputTokens, outputTokens, costUsd: usage.cost ?? null }));
```

- **OpenRouter through the kit.** `fabric_openrouter.Client` records these receipts itself, one per answered call,
  and checks a spend ceiling before every attempt ([connectors](connectors.md)).
- **The provider's own numbers.** Take tokens from the response's usage block, not from a local
  estimate. The cost is `provider` when the provider reported the charge (OpenRouter `usage.cost`,
  a billing API) and `price-list` when you computed it from a published price list.
- **Unknown is `None`/`null`, never `0`.** A local model, or a provider that reports no price,
  records `cost_usd=None`. The report counts it in `unpricedCalls`, and a host shows a lower bound
  («≥ $x») or «unknown». A call that is really free (a template, a cached answer) records
  `cost_usd=0.0` with `price-list`.
- **Unknown tokens are named too** (DEC-0091). When the provider gave no token count (a stream cut off, a local
  model without a counter), pass `tokens_measured=False` / `tokensMeasured: false` with the tokens you have (often 0).
  The receipt carries `tokensMeasured: false`, and the report counts the call in `unmeasuredCalls` on its day and model
  row, never more than `calls`; a host then shows the token totals as a lower bound. A job whose usage you send as
  `null` or `partial` ([interop](interop.md)) is such a call.
- **No content.** A receipt carries no prompt, output, caller or user id. The kits accept only the
  fields above.
- If the service already keeps a ledger (a jobs table with token counts), build the receipts from
  it and pass them to `usage_report(...)`. That avoids a second store.

## What to answer

Declare the surface in the well-known document and serve the report behind the service token:

```python
surfaces={..., "usage": {"path": fs.USAGE_PATH}}          # "/fabric/v1/usage"
# GET /fabric/v1/usage, token required:
return send(200, ledger.report(service_id=ID, instance=INSTANCE, budget={"period": "month", "limitUsd": 100}))
```

`usage_report` / `usageReport` give the last 31 UTC days, oldest first, per provider and model,
with day totals that are the sums of the model rows (`FAC-SEM-025`). Days without calls are
left out.

**Budget.** Pass `budget` only if the service **enforces** that limit itself. The report states
it, and the host only shows it.

**Every limit (DEC-0027).** Pass `budgets` to list every spending limit the service applies,
enforced or not, so the spend view shows all of them; the operator asked for that on 2026-10-07:

```python
ledger.report(service_id=ID, budget={"period": "month", "limitUsd": 100}, budgets=[
    {"id": "machine.monthly", "scope": "machine", "kind": "monthly", "period": "month", "limitUsd": 100, "enforced": True},
    {"id": "project.demo.daily", "scope": "project", "subject": "demo", "kind": "daily", "windowSeconds": 86400,
     "limitUsd": 5, "spentUsd": 0.31, "enforced": True},
    {"id": "job.cap", "scope": "job", "kind": "per_job", "limitUsd": 2, "enforced": True},
])
```

- A machine limit with a `period` and no `spentUsd` is counted by the kit from the receipts, the
  way `budget` is, so `budget` and its twin in `budgets` never disagree. Both count money only (DEC-0110):
  a `subscription` route's `costUsd` is an estimate at list price, never spent money, so a window
  spent only on a subscription spends `0`, and money is `null` only while no call off a subscription
  is priced. `usage_spend(rows)` / `usageSpend(rows)` is the contract's `usageSpend` over
  `days[].byModel[]` rows: money and the subscription's estimate apart. A per-order limit
  (`per_job`, `approval`) gets `spentUsd: null`. Every other limit states its own spend.
- `scope` is `machine`, `project`, `pool` or `job`; a `project` or `pool` limit names its
  `subject`. A limit has at most one window (`period`, `windowSeconds` or `since`), and it agrees
  with the kind (`daily`: the day or 86400 s; `monthly`: the month or 28–31 days; `velocity`: a
  rolling window). `tripped: true` (work stopped by it now) needs `enforced: true`. An unknown
  kind is shown generically, never refused.
- The kits refuse a report that breaks these (`usage_limit_problems` / `usageLimitProblems`,
  `FAC-SEM-031`). A breach is not refused: the report shows it, and the host shows it first.

Call `ledger.prune()` at start (or daily) to keep the file at the reported window (LC-12).

`JsonlUsageLedger` appends 0600 JSON lines. A line torn by a killed writer is skipped, and the
next receipt never glues onto it.

## By project (DEC-0065)

Pass `project_id` / `projectId` (the URI of the project the service ran the call for) and, optionally, `task_run_id` /
`taskRunId` (the service's own run id) to `make_usage_receipt` / `makeUsageReceipt`. The report then carries `byProject`:
each project once, by the normal form of its id (DEC-0076, so `URN:PROJECT:a` and `urn:project:a` are one row), with
its calls, unpriced calls, cost and `taskRuns`. A call for no project is in no row. It is the service's own run
attribution and names no caller, session or person. `usage_findings` / `usageFindings` port FAC-SEM-025 whole:
- the arithmetic;
- the window: every day exists, is not after `generatedAt`'s UTC date, and is at most 30 days before it;
- the projects: each project and task run once, and their calls, priced calls and known costs within the days' (CT-40).

A row's `route` may be `platform-metered`: the hosting platform's own metered models under the deployment's account.

## OpenRouter attribution (DEC-0065)

A product credits its own OpenRouter traffic with `attribution_headers(setting, request)` / `attributionHeaders`. The
setting is `{product, title, categories?}`: a lower-case slug (the app is `https://passioncode.ai/<product>/`), a printable
title, and at most two of OpenRouter's recognized categories (FAC-SEM-098, `attribution_setting_findings`). Attribution
is off by default: without a setting nothing is sent. The answer adds `HTTP-Referer`, `X-OpenRouter-Title` and
`X-OpenRouter-Categories` only when all of these hold:
- the request goes to `https://openrouter.ai` (read as a browser reads a URL);
- the product itself originated the traffic;
- the request carries no attribution header of the user's own.

Otherwise it answers why not. It never reads, moves or returns a key.

## Verify

`check_service.py <id>` reads a declared report: `usage.requires-token` (401 without the token)
and `usage.report` (identity, USD, dates forward, null for all-unpriced rows, sums, each row's route, the window and
`byProject`). The
`sample_service.py` serves one. Fabric Dashboards → **Spend** shows it within a minute of opening
the page.
