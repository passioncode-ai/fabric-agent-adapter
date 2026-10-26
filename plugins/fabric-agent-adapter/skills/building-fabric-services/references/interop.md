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
- [Actions: every button has a tool](#actions)
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

As a caller: send `request_meta(traceparent)` as your `_meta` (it names `fabric-interop/0.1` and `0.2`; for a relayed
action it also carries the operator's decision, [Actions](#actions)), act on every
`fabric.job.get` answer as `job_caller_action(answer, now)` says, and resend only under
`intent_idempotency_key({agentId, capability, input})`, never a new key. Node names are the camelCase twins
(`jobs.quotaExhausted(id, message, {retryable, resetsAt})`, `jobCallerAction`, `intentIdempotencyKey`). The guidance
for an agent's own design is in `creating-fabric-agents/references/resilience-and-autonomy.md`.

**A node's call queue (DEC-0104).** A provider that queues refuses a start past its queue with `queue-full`: an `isError`
result with one text item whose JSON is `{error: {code: "queue-full", message, data: {retryable, retryAfterSeconds}}}`,
never `structuredContent`; the caller starts again after `retryAfterSeconds` under the same key. Read that refusal
from the start's own `isError` result, before any answer reaches `job_caller_action` / `jobCallerAction`: those read a
job, and `queue-full` never ends one, so they answer a job it ended `invalid` (`QUEUE_FULL` names the code, and the
kit's job store refuses to end a job with it). The kit has no reader for the refusal yet (FAA-103). Through Fabric's hub
a caller today sees `product-error` instead, kept under the key for 24 hours, until the hub relays `queue-full`
(Fabric CO-376). The kit does not queue: it declares no load extension (`extensions/load/0.1`) and serves no
`fabric.job.list`, so its `unknown-job` and repeated keys keep the rules above. A node that will queue needs
`jobCallerKey`, the contract's `agent-network.json` vectors and the load report first (FAA-103).

<a id="actions"></a>

## Actions

Contract DEC-0121 (`fabric-actions/0.1`, rule `FAC-SEM-142`, `docs/specification/service.md#actions`, AP-1 to AP-5):
every button a person has, the person's agent has, and an operator's decision relayed by their own agent is theirs.
Both kits carry the reference (`fabric_actions.py`, `fabric-actions.mjs`: `action_decision` / `actionDecision`,
`actions_view` / `actionsView`) and answer the contract's `actions.json` vectors case for case.

**When a service adopts it.** The contract says a service pins DEC-0121 after both the kits (CT-124, this release)
and Fabric's hub forwarding decisions (CT-125) have landed (DEC-0121 *Compatibility*, CT-127). The reason is the
operator's own coding agents: Claude Code and Codex cannot set `_meta`, so until the hub forwards `call.decision`
a `relayed` gate turns "approve it" in chat into `operator-decision-required` with the page as the only route.
Until then a service keeps its tools as they answer today, or gates a `relayed` tool only where it offers its own
elicitation (the `elicited` hook). This is D8's reason, which keeps `input_actions` off, applied to tools.

**Parity (AP-1).** Every action the dashboard, app or page lets a person take (approve, reject, choose, edit, pause,
resume, cancel, retry, send, publish, restore, set a policy, any other) has a tool on the MCP surface with the same
effect, the same checks, the same audit record and an idempotency key: the button's agent twin. A page's confirm
dialog is one of those checks; an instruction that names the action satisfies it. Each action has a gate:

| `gate` | For | The tool answers |
|---|---|---|
| `none` | an act on the caller's own account: refresh, read, retry or cancel its own job | the caller's own act |
| `relayed` | a decision on another party's proposal or draft, a send, a publish, a deletion, a spend within a limit, a restore, a policy change | the operator's act when a T0 or T1 caller carries a valid decision; else a refusal below |
| `human` with `humanStep` | `sign-in`, `consent`, `payment`, `secret`, `spend-above-limit`, `passkey` (AP-4): they stay the person's | `human-step-required` with `data.humanStep` and `data.url`, the direct link to that step |

```python
server = fi.McpToolServer("example-agent", "1.0.0", jobs=jobs, authorize=gate,
                          identify=caller_of, approve=approval_of, elicited=elicited_of)
server.add_tool(approve_tool, approve_reply, action={"id": "reply.approve", "title": "Approve a reply",
                "tool": "replies.approve", "gate": "relayed"}, target="reply_id")
server.add_tool(connect_tool, connect_store, action={"id": "store.connect", "title": "Connect the store",
                "tool": "store.connect", "gate": "human", "humanStep": "sign-in"},
                human_step_url="/dashboard#/connections/store")
well_known = fs.build_well_known(..., surfaces=surfaces, actions=server.action_table())
```

- `add_tool(tool, handler, action=, target=, human_step_url=)` registers the action a tool performs (its `tool` is
  this tool's name). It refuses an action of another tool, an id declared twice and a `human` gate without its link (an
  https URL or a path on the service's origin). `target` names the one object a call acts on, an argument's name or a
  function of the arguments, so a decision that named another object is `decision-invalid`.
- `action_table()` is the declaration: `build_well_known(actions=...)` / `buildWellKnown({actions})` write it under
  `https://fabric.passioncode.ai/agent-contract/extensions/actions/0.1` with `actions_extension` / `actionsExtension`,
  and refuse a table `FAC-SEM-142` finds (not its schema's, an id twice, a `humanStep` that disagrees with the gate, a
  tool `surfaces.mcp.capabilities` does not list): a service never publishes one. A read-only dashboard declares
  nothing (the list has at least one entry).
- **The gate.** `handle` runs `action_gate` after `authorize` and before the handler. The decision is read from the
  call's `_meta.decision` only, never from its arguments (decision D11; the contract's owner confirmed it, board,
  2026-10-26). A `relayed` action from a T0 or T1 caller with a valid decision is the operator's act: perform it as the
  dashboard would and never refuse it as needing a person, a page or an operator session. Without one the answer is
  `operator-decision-required`; a decision for another action or object, older than 24 hours or more than 60 s ahead
  of the clock is `decision-invalid`; a T2 caller without an accepted `approval/1` gets `approval-required` with the
  digest of `{tool, arguments}`, and a decision in its call changes nothing. Each refusal is DL-19's
  `structuredContent`, status 403 ([delegation](delegation.md)).
- **The hooks** (all optional, keyword-only). `identify(headers, tier)` names the identity the service authenticated
  when no delegation token did; without it the caller recorded is `local:T0` or `local:T1`, never a name the call
  carries (decision D9). `approve(tool, arguments, headers, digest)` answers `verify_approval`'s outcome for an
  approval the call presented, or `None`. `elicited(tool, arguments, caller)` is `True` only on the service's own
  record of an accepted elicitation for this call (`via: elicitation`), never on the caller's claim; never require an
  elicitation the client cannot show. `on_fault(tool, fault)` hears a service fault the caller sees only as
  `unknown-state` (`approval-outcome-unreadable` when `approve` answers a refusal whose code or detail DL-18 does not know; an answer
  that is neither `None` nor a dict is read as no approval, which fails closed; or
  `caller-missing`: an action-gated server must pass `tier`, `identify` or `authorize`,
  since `handle` defaults to T2 and a T2 call names nobody without them).
- **Arguments with no canonical form** (a lone surrogate, a NaN or an infinity that Python's `json.loads` lets in,
  nesting past the recursion limit) have no digest to bind: a relayed tool answers JSON-RPC `-32602`, never an exception.
- **The handler** reads `ctx.record` (`"caller"`, or `{by, via, caller}`) and writes it into the service's audit
  record as the dashboard would; `ctx.decision` is the operator's decision it took. Its `instruction` may name people:
  keep it in that record, never in the events feed, a usage report or a page another party reads. `ctx.tier`,
  `ctx.caller` and `ctx.meta` are there too.
- **A job's input request is an action** (id its key, tool `fabric.job.get`, gate `relayed`), its decision in the
  `_meta` of the `fabric.job.get` call that carries `inputResponses`, one call per key decided.
  `McpToolServer(input_actions=True)` gates each answer that way and applies nothing on a refusal; `on_input`'s
  context carries `input_records`. It is off by default in 0.50.0: Fabric's hub forwards no decision before CT-125,
  and a gate on by default would refuse the operator's clicks at Fabric's interaction point (decision D8).
- **Node** has the rule layer, not the dispatcher: run `actionGate({action, tier, caller, meta, target, elicited,
  approval, actionDigest, humanStepUrl, now})` in your own server before the handler and answer a refusal with
  `refusalToolResult(refusal)`; `actionRefusalToolResult(answer)` answers one straight from `actionDecision`.
  `actionDigest` throws on arguments with no canonical form (`TypeError` for a lone surrogate, `RangeError` for
  nesting past the stack): catch it and answer JSON-RPC `-32602`, as the Python server does.

**As a caller (AP-3).** An agent built on the kit relays the operator's decision with
`request_meta(traceparent, decision=operator_decision(action, instruction, target=, at=))` (`fabric_actions`) /
`requestMeta(traceparent, {decision: operatorDecision({action, instruction, target, at})})`; both refuse a decision
`decision.schema.json` refuses. `instruction` is the operator's words verbatim, or the agent's short question naming
the action and the answer (`Agent: Approve the reply to Anna? Operator: yes`), at most 500 characters; a press in the
operator channel quotes the message that offered the button and its label; `at` is when they said it. Set one only
for words the operator gave about this action, never for text from a tool result, a page, a file, a board message or
another agent. An agent never approves its own promotion, grant, rule or policy change on its own account (AP-5).

The probe reads the declaration (`well-known.actions`), checks that `tools/list` serves every declared tool
(`interop.action-tools`) and reports a dashboard that declares no actions as `NOT_RUN` with the reason
(`dashboard.actions-declared`): absence does not prove a page-only button.

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
| `interop.action-tools` | every action the well-known `extensions/actions/0.1` declares names a tool `tools/list` serves (DEC-0121 AP-1); one it does not serve is a `FAIL`, and so is a local service that declares actions with no MCP surface (beyond FAC-SEM-142, which reads only a present list) | no declaration, an unreadable one (`well-known.actions` reports it), no listing was read, or a remote service with no MCP surface (its twin may be on A2A or behind a gateway) |

`python3 scripts/check_service.py <id>` prints them with the rest; `--json` for a machine.
