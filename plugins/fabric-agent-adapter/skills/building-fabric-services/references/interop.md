# Being called: `fabric-interop/0.1`

Normative source: the Fabric Agent Contract's `docs/specification/interop.md` (DEC-0016, rulings DEC-0017 and DEC-0018)
at the commit this plugin pins. This page says how the kit implements it; where the two
differ, the contract is right.

A service that other agents (and Fabric) call does five things. Each has one helper in
`scripts/fabric_interop.py` (Python) and `scripts/fabric-interop.mjs` (Node).

| Rule | What the service does | Helper |
|---|---|---|
| C3.1 capability = tool | serves each `mcp` capability of its manifest as the MCP tool of the same name, with the manifest's input schema unchanged, its output schema unchanged (or, for a job, wrapped as `oneOf[result envelope, job handle]`) and annotations from the effect | `tool_for_capability` / `toolForCapability`, `job_tool_output_schema`, `expected_annotations` |
| C3.2 long work = job | a capability whose work can outlive one request declares `"job": true` in its interop block, returns `{"job": {"id", "status": "working"}}`, and serves `fabric.job.get` and `fabric.job.cancel` | `JobStore`, `McpToolServer` (Python), `unknown_job_result` |
| C3.2 result | a completed job carries the full result envelope, the shape a synchronous call returns: `id`, `contractVersion`, `outcome`, `done`, `proof`, `scope`, `notVerified`, `artifacts`, `createdAt`, `producer`, `output`, `usage`, and its `trace` | `result_envelope` / `resultEnvelope` |
| C3.3 a person decides | the job goes `input_required` with an elicitation: a titled single-select in form mode, and URL mode for anything secret | `choice_request`, `form_request`, `url_request` |
| C3.4 trace | every call runs as a child span of the caller's `_meta.traceparent`; outgoing calls carry the same trace; the result envelope records it; events about traced work carry `traceId` and `spanId`, events about untraced work none | `child_traceparent`, `trace_ids`, `make_event(..., trace_id=, span_id=)` |

The interop block sits in the manifest under the capability's `extensions`:

```json
"extensions": { "https://fabric.passioncode.ai/agent-contract/extensions/interop/0.1": { "job": true } }
```

That key has one spelling (the contract's `src/extensions.ts`); copy it, never retype it.

## Contents

- [The kit](#the-kit)
- [Limits and uncertain effects](#limits-and-uncertain-effects)
- [What the probe checks](#what-the-probe-checks)

## The kit

```python
import fabric_interop as fi

jobs = fi.JobStore(data_dir / "jobs")               # one private JSON file per job; ids survive restarts
server = fi.McpToolServer("example-agent", "1.0.0", jobs=jobs,
                          on_job_started=start_report, on_input=resume_report)
server.add_tool(fi.tool_for_capability(capability, input_schema, output_schema), handler)
response = server.handle(json_rpc_message)          # POST /mcp body in, JSON response out (None: 202)
```

- A handler returns the value for `structuredContent`; for a job it returns
  `ctx.start_job()`, and `on_job_started(job_id, ctx)` does or schedules the work.
- `jobs.request_input(job_id, {"title_choice": fi.choice_request(...)}, "Two titles are ready.")`
  stops for a person. Fabric answers through `fabric.job.get` with `inputResponses`; the
  server calls `on_input(job_id, answers, ctx)` with the answers that matched.
- `jobs.complete(job_id, fi.result_envelope(outcome=..., producer=..., ...))`,
  `jobs.fail(job_id, code, message, data=None)`, `jobs.cancel(job_id)`; a limit or an unseen effect has its own calls
  ([Limits and uncertain effects](#limits-and-uncertain-effects)). A terminal job never changes
  again. A result with unverified claims is `partial`, never `succeeded`.
- The envelope's `trace` is authoritative for a stored result (DEC-0017): `complete` fills
  it with the span of the call that started the job and refuses one naming another span,
  and `fabric.job.get` answers with that same traceparent in `_meta` (FAC-SEM-022). The
  contract's FAC-SEM-019 records a result without a trace as an incomplete span.
- Log events about the work with `**fi.trace_ids(ctx.traceparent)` so the pair lands on
  the event.

`McpToolServer` answers `initialize` and `ping` (clients such as Claude Code 2.1.285 still
open with a handshake, and a server that refuses it is marked failed), `server/discover`,
`tools/list` and `tools/call` with JSON responses. Every tool's `outputSchema` must be
rooted at `type: object` (DEC-0018): `add_tool` refuses any other root, because a client may
drop the whole tool list over one bad schema; an SDK-level test will not show it, so check
with the real client (below). A service already on an MCP SDK keeps
the SDK and uses only the helpers. The Node kit has the helpers and the same job file
format, without the dispatcher. `scripts/sample_service.py` is the worked example:
`sample.echo` answers at once, `sample.draft` is a job that stops for a title choice.

The contract owner's rulings the kit follows: a job tool's `outputSchema` is the
self-contained `{type: object, oneOf: [result envelope, job handle]}` (`job_tool_output_schema`,
DEC-0017 amended by DEC-0018), so its `structuredContent` always conforms; an event about
untraced work carries no trace pair.

**Check with a real client**, never only an SDK: `FABRIC_REAL_CLIENT=1 python3 -m unittest
test.test_real_client` in the adapter repository, or by hand: a throwaway directory, a
temporary `--mcp-config` (mode 600, the token in a header) and `--strict-mcp-config`, so
the operator's own configuration is not touched:

```bash
claude -p "Reply with the single word OK." --strict-mcp-config --mcp-config "$TMP/mcp.json" \
  --output-format stream-json --verbose --max-turns 1
```

The first `system/init` event lists `mcp_servers` (`connected`) and the `mcp__<server>__*` tools.

## Limits and uncertain effects

Contract DEC-0087 (`FAC-SEM-119`, `FAC-SEM-120`). A limit and an effect nobody saw are not ordinary failures: a caller
that submits again pays twice. Both kits (`fabric_interop.py`, `fabric-interop.mjs`) carry the contract's functions,
answer for answer (`test/fixtures/contract/job-limit-vectors.json`).

As a provider:

- **A limit paused the job and you will resume it:** `jobs.pause(job_id, resets_at=..., text=...)` keeps it `working`
  with `statusMessage` `quota-exhausted until <UTC instant>: <text>` and sets `pollIntervalMs` to reach the reset,
  at most an hour. An instant with an offset, more than three fraction digits or a day that does not exist is refused.
- **A limit stopped it and you will not resume it:** `jobs.quota_exhausted(job_id, message, retryable, resets_at=None)`
  ends it `failed` with `quota-exhausted` and `data: {retryable, resetsAt?}`; `resetsAt` only with `retryable: True`.
- **The effect may have happened and you cannot see whether:** `jobs.outcome_unknown(job_id, message, data)`. Its key
  never runs again; only an observed result settles it.
- **Keys per caller.** `jobs.create(..., caller=<authenticated caller>, idempotency_key=<key>)` keeps the key for that
  caller only. A key that already names a job starts nothing; `jobs.repeat(caller, key, now)` answers `new`, `same`
  (answer with that job) or `run`: a `quota-exhausted` job runs again once its reset passed or you pass
  `limit_holds=False`, a `limit-reached` job once `approval_granted=True`, and an `outcome-unknown` job never.
  A key admits only the intent it was first used for: the key file keeps a digest of the capability and its input,
  and the same key with another intent is refused as `idempotency-conflict` (FAA-77). `repeat` takes the intent too
  (`capability=`, `arguments=`; Node `{capability, input}`) and then answers `conflict` for another intent. A key file
  written before 0.41.0 holds no intent: it is answered with its job, never a conflict, and its job runs again only
  for the capability and input that job stored.
- **Usage you did not measure is `null`, never 0,** but only toward a caller whose request `_meta.protocols` names
  `fabric-interop/0.2`: pass `request_meta` to `result_envelope` (`usage_toward`). Toward any other caller the kit
  writes the measured lower bound, as before. Either way, record that call's usage receipt with
  `tokens_measured=False` / `tokensMeasured: false` and the tokens you have, so your own usage report counts it in
  `unmeasuredCalls` and does not show the lower bound as complete (DEC-0091, [usage](usage.md)).

As a caller: send `request_meta(traceparent)` as your `_meta` (it names `fabric-interop/0.1` and `0.2`), act on every
`fabric.job.get` answer as `job_caller_action(answer, now)` says, and resend only under
`intent_idempotency_key({agentId, capability, input})`, never a new key. Node names are the camelCase twins
(`jobs.quotaExhausted(id, message, {retryable, resetsAt})`, `jobCallerAction`, `intentIdempotencyKey`). The guidance
for an agent's own design is in `creating-fabric-agents/references/resilience-and-autonomy.md`.

## What the probe checks

`check_service.py` adds these rules; they read, and never call a capability.

| Rule | PASS when | NOT_RUN when |
|---|---|---|
| `interop.output-schema-object` | every listed tool's `outputSchema`, when present, has root `type: object` (FAC-SEM-023) | no MCP surface |
| `interop.manifest-link` | the manifest `fabricManifest` names carries the service key with this `<id>.<instance>` (G-07) | the descriptor names no manifest |
| `interop.well-known-capabilities` | every name in `surfaces.mcp.capabilities` is a manifest capability | the surface lists none |
| `interop.tools-match` | every `mcp` capability is served as its tool, schemas equal to the files beside the manifest (matched by `$id`; a job's output wrapped in the DEC-0017 union), annotations derived | no manifest, no MCP surface, or a schema is not beside the manifest |
| `interop.job-tools` | a `job: true` capability comes with `fabric.job.get` and `fabric.job.cancel` | no capability is a job |
| `interop.unknown-job` | `fabric.job.get` for a made-up id answers `isError` with `unknown-job` | `fabric.job.get` is not served |
| `interop.trace-propagation` | the answer's `_meta.traceparent` has the probe's trace id and a new span | the answer carries no traceparent |
| `interop.events-trace` | every event with a trace carries both `traceId` and `spanId`, well formed | no events page was read |

`python3 scripts/check_service.py <id>` prints them with the rest; `--json` for a machine.
