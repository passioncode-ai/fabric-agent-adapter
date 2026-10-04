# Usage report — what the agent spent (DEC-0021)

Fabric Agent Contract DEC-0021, `docs/specification/service.md` → *Usage report*, schema
`schemas/service-usage.schema.json`. Optional. A service that calls paid models or tools should
offer it, so Fabric Dashboards (Spend, MCP `spend`) and Fabric can show each agent's spend beside
its health without knowing any provider.

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

- **The provider's own numbers.** Take tokens from the response's usage block, not from a local
  estimate. The cost is `provider` when the provider reported the charge (OpenRouter `usage.cost`,
  a billing API) and `price-list` when you computed it from a published price list.
- **Unknown is `None`/`null`, never `0`.** A local model, or a provider that reports no price,
  records `cost_usd=None`. The report counts it in `unpricedCalls`, and a host shows a lower bound
  («≥ $x») or «unknown». A call that is really free (a template, a cached answer) records
  `cost_usd=0.0` with `price-list`.
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

Call `ledger.prune()` at start (or daily) to keep the file at the reported window (LC-12).

`JsonlUsageLedger` appends 0600 JSON lines. A line torn by a killed writer is skipped, and the
next receipt never glues onto it.

## Verify

`check_service.py <id>` reads a declared report: `usage.requires-token` (401 without the token)
and `usage.report` (identity, USD, dates forward, null for all-unpriced rows, sums). The
`sample_service.py` serves one. Fabric Dashboards → **Spend** shows it within a minute of opening
the page.
