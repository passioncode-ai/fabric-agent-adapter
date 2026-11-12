# Recipe: a data agent that answers with numbers computed by code

A service answers one question about a number from a read-only source: the model picks which declared metric the
question asks for, the code reads the source and computes the number, and the answer carries where the number came
from. A model never works out a number (creating-fabric-agents' practices, *Numbers and data*). Built only on the
service kit: `fabric_http` for the source, `fabric_openrouter` for the model and its receipts, `fabric_usage` for the
ledger, `fabric_paths` for private state. Tests: `test/test_data_agent_recipe.py` (a fake model and a fake source; no
network, no key). FAA-66.

The recipe follows the agents database's `data-room` template (version 1.7.0, its `finance-metrics-room` and
`database-query` variants), read through the agent architect on 2026-11-12: one source of truth per number, the truth
envelope on every answer, missing never zero, model lane failures mapped to fixed codes (`fail-closed-door`), the
question fenced as data with a random tag (`untrusted-fence`), and a reading that refuses a boolean, NaN or infinity
(`verdicts`). An organization that needs the whole room (provenance per fact, access levels per block, publication)
builds from that template; this recipe is the smallest piece of it a kit service can own.

## What it does with one question

| Step | Rule | When it fails |
|---|---|---|
| Repeat | the answer already given for this question id is returned, with no model call | |
| Pick | the model gets the declared metrics (id and description) and answers one id or `NONE`, temperature 0, at most 20 tokens; the question goes between two marker lines with a random tag it cannot contain | `no-metric` (an answer outside the list, `NONE` included); `model:<kind>` (`ceiling`, `failed`, `auth`, `payment`, `config`, `unpriced`) |
| Read | `GET` on the source URL (https, or loopback over plain http), its key from the environment variable `source.keyEnv` names, a deadline and a size cap; rows at `rowsAt` kept for `maxAgeSeconds` | `source:<kind>` (`no-key`, `unreachable`, `auth`, `status`, `shape`) |
| Compute | `count`, `sum`, `mean`, `min` or `max` over the rows the metric's `where` (field equalities) and `window` (`{field, days}`, back from now) keep; rounded to `decimals` (2) | a sum, mean, min or max over no row is `null` with `no-rows`, never 0; a row whose field is missing or not a finite number is left out and counted (`skipped:<n>`) |
| Say | the code's sentence: the description, the value and unit, the rows and the source with its fetch time | |
| Phrase (optional) | with `"phrase": true` the model gets the computed figures as data and writes one sentence; it is kept only when every number in it is one the code computed and it holds no em dash | `phrase-refused`, or `phrase:model:<kind>`: the code's sentence is kept |
| Record | one line appended to `answers.jsonl` (0600, fsync'd) | |

The answer is the truth envelope:

```json
{"questionId": "q-1", "outcome": "answered", "metric": "orders.paid.revenue.7d", "value": 42.5, "unit": "USD",
 "rows": 2, "source": {"name": "orders", "fetchedAt": "2026-11-05T00:00:00Z", "rows": 5},
 "degraded": ["skipped:1"], "text": "Revenue of paid orders in the last 7 days: 42.5 USD, from 2 rows of orders as of 2026-11-05T00:00:00Z.",
 "receipts": [{"provider": "openrouter", "model": "deepseek/deepseek-v4.1-flash", "costUsd": 0.0001}]}
```

A hand-off has `outcome: "handoff"` and a `reason` instead of a value. The recipe never sends the answer anywhere: the
service that calls it owns its channel.

## Declare what it may answer

Metrics are a closed list in the config (`config.example.json`): an `id`, the `description` the model reads to pick it,
a `kind`, the `field` it reads (not for `count`), and optional `where`, `window`, `unit` and `decimals`. A question
the list does not cover is `no-metric`: add a metric, never let the model compute one. A total the code derives from
other numbers says so in its description.

## Keys and limits

- The model key is read from `keyEnv` (`OPENROUTER_API_KEY`) and the source key from `source.keyEnv`, both when a call
  is made; run the service under `use_secret.py run --vault-only <project> <NAME> -- <command>` so neither is ever in
  a file, an argument or a log.
- The fallback model is of another vendor; a config whose fallback shares the writer's vendor is refused at load.
- `ceilingUsd` per `window` bounds the model spend before every attempt (fabric_openrouter); each call leaves its
  receipt in `state/usage.jsonl`, which the service serves as its usage report.

## Install into a service

```sh
python3 <skill-dir>/scripts/fabric_kit.py install <service-dir> --lang py --module fabric_openrouter \
  --module fabric_usage --module fabric_paths --module fabric_http
cp <skill-dir>/recipes/data-agent/data_agent.py <service-dir>/
use_secret.py run --vault-only example-agent OPENROUTER_API_KEY -- \
  python3 <service-dir>/data_agent.py ask --config config.json --question-id q-1 --text "How many paid orders this week?"
```

As a capability, a service's handler calls `DataAgent.ask(question_id, text)` and returns the envelope as the tool's
structured result. The question id is the caller's (a request id), so a retry answers the same envelope and costs
nothing.

## What it is not

- Not a query engine: no SQL and no model writing a query. A source that needs one is the `database-query` variant of
  the template, with its read-only guard.
- Not a judge of trends: a rise, a fall or a comparison is a metric of its own, computed by code.
- Not a store: the rows live only in memory for `maxAgeSeconds`; the answers file is its only state.
