# Being called: `fabric-interop/0.1`

Normative source: the Fabric Agent Contract's `docs/specification/interop.md` (DEC-0016)
at the commit this plugin pins. This page says how the kit implements it; where the two
differ, the contract is right.

A service that other agents — and Fabric — call does five things. Each has one helper in
`scripts/fabric_interop.py` (Python) and `scripts/fabric-interop.mjs` (Node).

| Rule | What the service does | Helper |
|---|---|---|
| C3.1 capability = tool | serves each `mcp` capability of its manifest as the MCP tool of the same name, with the manifest's two schemas unchanged and annotations from the effect | `tool_for_capability` / `toolForCapability`, `expected_annotations` |
| C3.2 long work = job | a capability whose work can outlive one request declares `"job": true` in its interop block, returns `{"job": {"id", "status": "working"}}`, and serves `fabric.job.get` and `fabric.job.cancel` | `JobStore`, `McpToolServer` (Python), `unknown_job_result` |
| C3.2 result | a completed job carries the result envelope: `done`, `proof`, `scope`, `notVerified`, `output`, `usage` | `result_envelope` / `resultEnvelope` |
| C3.3 a person decides | the job goes `input_required` with an elicitation: a titled single-select in form mode, and URL mode for anything secret | `choice_request`, `form_request`, `url_request` |
| C3.4 trace | every call runs as a child span of the caller's `_meta.traceparent`; outgoing calls carry the same trace; events about the work carry `traceId` and `spanId` | `child_traceparent`, `trace_ids`, `make_event(..., trace_id=, span_id=)` |

The interop block sits in the manifest under the capability's `extensions`:

```json
"extensions": { "https://fabric.passioncode.ai/agent-contract/extensions/interop/0.1": { "job": true } }
```

That key has one spelling (the contract's `src/extensions.ts`); copy it, never retype it.

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
- `jobs.complete(job_id, fi.result_envelope(...))`, `jobs.fail(job_id, code, message)`,
  `jobs.cancel(job_id)`. A terminal job never changes again.
- Every result carries `_meta.traceparent`. For a job it is the span of the call that
  started it, so the result is traced (the contract's FAC-SEM-019 records an untraced
  result as an incomplete span).
- Log events about the work with `**fi.trace_ids(ctx.traceparent)` so the pair lands on
  the event.

`McpToolServer` answers `server/discover`, `tools/list` and `tools/call` with JSON
responses — enough for Fabric and for the probe. A service already on an MCP SDK keeps
the SDK and uses only the helpers. The Node kit has the helpers and the same job file
format, without the dispatcher. `scripts/sample_service.py` is the worked example:
`sample.echo` answers at once, `sample.draft` is a job that stops for a title choice.

Two readings the contract leaves open, and what the kit does meanwhile:

- a job tool serves the capability's `outputSchema` although its `structuredContent` is
  the handle (contract OQ-0006);
- events that belong to no traced work carry no trace pair (contract OQ-0007).

## What the probe checks

`check_service.py` adds these rules; they read, and never call a capability.

| Rule | PASS when | NOT_RUN when |
|---|---|---|
| `interop.manifest-link` | the manifest `fabricManifest` names carries the service key with this `<id>.<instance>` (G-07) | the descriptor names no manifest |
| `interop.well-known-capabilities` | every name in `surfaces.mcp.capabilities` is a manifest capability | the surface lists none |
| `interop.tools-match` | every `mcp` capability is served as its tool, schemas equal to the files beside the manifest (matched by `$id`), annotations derived | no manifest, no MCP surface, or a schema is not beside the manifest |
| `interop.job-tools` | a `job: true` capability comes with `fabric.job.get` and `fabric.job.cancel` | no capability is a job |
| `interop.unknown-job` | `fabric.job.get` for a made-up id answers `isError` with `unknown-job` | `fabric.job.get` is not served |
| `interop.trace-propagation` | the answer's `_meta.traceparent` has the probe's trace id and a new span | the answer carries no traceparent |
| `interop.events-trace` | every event with a trace carries both `traceId` and `spanId`, well formed | no events page was read |

`python3 scripts/check_service.py <id>` prints them with the rest; `--json` for a machine.
