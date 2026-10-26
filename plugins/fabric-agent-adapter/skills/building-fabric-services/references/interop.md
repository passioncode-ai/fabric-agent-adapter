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
| C3.3 a person decides | the job goes `input_required` with an elicitation: a titled single-select in form mode, and URL mode for anything secret. A URL-mode request is an `https` URL or, for a page of this service, its Fabric Dashboards open_link (DEC-0123 PL-4): `url_request` refuses a raw loopback address (`http://127.0.0.1:4100/x`, `http://127.1/`, `http://[::1]/`, `http://localhost/` in any spelling) and a `fabric-dashboards:` link outside the grammar when the request is built, and `request_input` refuses a hand-built request either way (FAC-SEM-143). A tool answer that hands a person a page is `page_answer`'s `{open_link, http_url?}`; `http_url` is a diagnostic | `choice_request`, `form_request`, `url_request`, `page_answer` / `pageAnswer`; the rules in `fabric_page_links` / `fabric-page-links.mjs` |
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
- [The operator's mandate](#the-operators-mandate)
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

<a id="the-operators-mandate"></a>

## The operator's mandate

Contract DEC-0125 (`mandate/1`, rule `FAC-SEM-144`, `docs/specification/delegation.md#the-operators-mandate`, MD-1 to
MD-6): the operator's instruction for one task travels with the task, narrowed at each hand-over, so a service the
task reaches takes a call the mandate covers as his decision without asking him again. It is the machine form of his
rule of 2026-10-26: one approval he gives in the chat of any of his agents binds all his agents (working-with-fabric,
Step 5), which the contract states as DEC-0126 (OA-1 to OA-7). Both kits carry the reference in `fabric_mandate` /
`fabric-mandate.mjs` and answer the contract's `mandate.json` vectors case for case, its `handOn` group included.

**As a service.** Name your own agent id and each relayed action's effect class; the gate then reads the call's
`_meta.mandate` when it carries no decision:

```python
server = fi.McpToolServer("example-agent", "1.0.0", jobs=jobs, authorize=gate, agent_id="example-agent")
server.add_tool(approve_tool, approve_reply, action=reply_action, target="reply_id", effect="reply",
                spend=lambda arguments: estimate_usd(arguments), project="example-site")
```

- `McpToolServer(agent_id=)` is this service's agent id (a lower-case id, optionally `.instance`). Without it a mandate
  is not read and every call is answered as before DEC-0125.
- A `spend` or `project` function that raises, or a spend that is not a finite number, fails closed: the call is
  answered, and a mandate with a `perCallMaxUsd` ceiling or a `projects` list refuses it (`outside-mandate: spend` or
  `outside-mandate: project`); the estimate is read as a double, so an integer past the float range is infinite and
  refused under a ceiling, and a project function that answers anything but a string or `None` names no project a
  mandate can list. A refusal outside a mandate
  tells the caller the MD-4 order: call again within its own mandate, else pass the refusal up; only the leading agent
  asks the operator.
- `add_tool(tool, handler, action=, effect=, spend=, project=)`: on a server with `agent_id`, a `relayed` action names
  its `effect` (governance's class: `none`, `draft`, `publish`, `send`, `reply`, `charge`, `delete`, `merge`, `deploy`,
  `change-policy`) or `add_tool` refuses it; `spend` is the service's own estimate of a call's USD (a number, or a
  function of the arguments), read against the mandate's `perCallMaxUsd`; `project` the project a call acts in.
- The mandate is read from `_meta.mandate` only, never from its arguments. Its chain must end in `agent_id`; when
  `authorize` accepted a delegation token, the token's caller must be the agent before it in the chain
  (`mandate-not-for-this-call` otherwise). A T2 caller's mandate changes nothing (MD-5): it still gets
  `approval-required`.
- A covered call is the operator's act: `ctx.record` is `{by: "operator", via: "mandate", task, chain, caller}` and
  `ctx.mandate` the mandate it took (its `instruction` stays in the audit record, never in events or a page). Outside
  it the answer is `operator-decision-required` with `data.detail` `outside-mandate: <action|capability|effect|spend|project>`
  (and `estimateUsd`, `perCallMaxUsd` for spend); an invalid one is `decision-invalid` with `mandate-malformed`,
  `mandate-widened`, `mandate-expired`, `mandate-early` or `mandate-not-for-this-call`. A `change-policy` effect is
  never covered (AP-5); human steps never travel (MD-6).
- **Where the operator spoke (DEC-0126).** A mandate or a decision may carry `source` (`{project, session or
  thread}`), set by the agent that heard the operator's words relayed from another of his agents (OA-2). The kits read
  it exactly as `mandate.schema.json#/$defs/source` does (an unplaced one is `mandate-malformed` or `decision-invalid`)
  and return it in the record: `ctx.record`, `input_records` and `job_step`'s record carry `source` (OA-6). Keep it,
  as `instruction`, in the service's own audit record, never in the events feed, a usage report, a log line or a page
  another party reads (OA-7).
- **Listing `operator-source/1`.** A service that reads `source` lists `operator-source/1` in its well-known
  `protocols` (OA-7): `McpToolServer.well_known_protocols(protocols)` returns your list with it added when the server
  has `agent_id` or serves a relayed action, for `build_well_known(protocols=server.well_known_protocols([...]))`. A
  service that builds its own list (a Node server, or one without `McpToolServer`) adds `operator-source/1` itself
  when it reads `source`; a caller that sees no such entry sends the call without `source`, and it is taken as before.
- `action_gate(..., self_id=, effect=, caller_agent=, spend_usd=, project=)` / `actionGate({..., self, effect,
  callerAgent, spendUsd, project})` is the same gate for a server of your own; `action_decision` / `actionDecision`
  take `mandate`, `self`, `callerAgent`, `effect`, `spendUsd` and `project` as the contract's function does
  (`effect-missing`, `self-missing` are the service's own faults).
- **A job's approval step (interop C3.3).** A job reads the mandate its start call carried at its own approval step:
  `ctx.approval_step(job_id, key, request, effect=, spend_usd=, project=, message=)` on the start call's context (a
  server with `agent_id`) answers the record when the mandate covers the step `{capability: the job's, action: key,
  effect}` and asks nothing, the job going on as the operator's decision; otherwise the job waits `input_required` on
  `request`, its message naming the part not covered (`outside-mandate: <part>`) or saying the mandate expired, and the
  step is kept in the job's private part (`request_input(..., steps=)`). An answer's `_meta.mandate` that covers that
  step is then read when `input_actions=True`, beside a decision for the key. The rule alone is `job_step(mandate, ...)`
  / `jobStep({mandate, tier, now, self, capability, key, effect, callerAgent, spendUsd, project})`; Node's
  `requestInput(jobId, inputRequests, statusMessage, {steps})` keeps the same private part. Each `request_input`
  replaces the kept steps, and an answer clears them: pass `steps=` again on every question whose answer a mandate may
  cover. The answer's mandate is read under the job's own capability, as at the start (`action_gate(...,
  mandate_capability=)` / `actionGate({mandateCapability})`), so the start and the answer agree whatever the tool is
  named; a mandate can name only capability names, so one that names capabilities never covers a tool named otherwise.
  Node has no tool server: a Node service reads the kept step with `store.load(jobId).private.steps` and gates the
  answer with `actionGate({..., mandateCapability: <the job's tool>})`.

**As a caller.** The agent leading a task states the mandate from the operator's own words with
`operator_mandate(task, instruction, scope, lead, at=, expires_at=)` / `operatorMandate({task, instruction, scope,
lead, at, expiresAt})` (a day unless told, at most seven), hands it to the agent it calls with
`hand_on(mandate, callee, at, narrower=None)` / `handOn(mandate, callee, at, narrower)` (the chain gains the callee; a
wider scope, a fifth agent, an agent already in it or a time at the expiry is refused; `source` travels unchanged), and
sends it with `request_meta(traceparent, mandate=...)` / `requestMeta(traceparent, {mandate})`, which refuse one
`FAC-SEM-144` refuses. `mandate_covers` / `mandateCovers` answer what a callee would, before you call. Never write a
mandate from another agent's text, a page or a file; a callee hands on only what it received, narrowed.

A relay the operator's rule accepts (DEC-0126 OA-2, OA-3: one of his own Projects on his board, provenance `trusted`,
or a session on his own machine, with his words verbatim, when, where and the scope) is stated with
`operator_mandate(..., source=)` / `operatorMandate({..., source})` or `operator_decision(..., source=)` /
`operatorDecision({..., source})`, `instruction` and `at` copied unchanged. `source` goes only to a callee whose
well-known `protocols` list `operator-source/1` (OA-7): pass that list as
`request_meta(traceparent, decision=, mandate=, target_protocols=)` / `requestMeta(traceparent, {decision, mandate,
targetProtocols})`. Without it (no list, another list, a board Project, a session, Fabric's `agent.call`, whose
directory lists no `protocols`), `_meta` carries the decision and the mandate without `source`, and the ones you passed,
your own record, keep it (OA-6).

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
