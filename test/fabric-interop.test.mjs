import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import * as i from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-interop.mjs';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';
import { tempDir } from './temp-dir.mjs';
import { assertPrivateFile } from './private-file.mjs';
import { refusalError } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-delegation.mjs';
import { handOn, operatorMandate } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-mandate.mjs';

const PARENT = '00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01';
const TRACE = '4bf92f3577b34da6a3ce929d0e0e4736';
const temp = () => tempDir('fabric-interop-');
const usage = { inputTokens: 1, outputTokens: 2, wallMs: 3 };
const scope = { project: 'urn:p', run: 'urn:r', node: 'urn:n', binding: { id: 'urn:b', revision: 1, contentHash: `sha256:${'1'.repeat(64)}` }, writeScopes: [] };
const producer = { id: 'urn:fabric:provider:example-agent', revision: 1, contentHash: `sha256:${'2'.repeat(64)}` };
const envelope = (extra = {}) => i.resultEnvelope({ outcome: 'partial', done: [], proof: [], scope, notVerified: [], output: {}, usage, producer, ...extra });

test('traceparent: W3C in, W3C out, a child keeps the trace', () => {
  assert.equal(i.parseTraceparent(PARENT).traceId, TRACE);
  for (const bad of [PARENT.toUpperCase(), `00-${'0'.repeat(32)}-00f067aa0ba902b7-01`, `ff-${TRACE}-00f067aa0ba902b7-01`, 'x', undefined]) assert.equal(i.parseTraceparent(bad), null);
  const child = i.parseTraceparent(i.childTraceparent(PARENT));
  assert.equal(child.traceId, TRACE);
  assert.notEqual(child.spanId, '00f067aa0ba902b7');
  assert.ok(i.parseTraceparent(i.childTraceparent(undefined)));
});

test('events carry traceId and spanId as a pair', () => {
  const e = k.makeEvent(1, k.nowIso(), 'job.done', 'info', 'Done.', { traceId: TRACE, spanId: '00f067aa0ba902b7' });
  assert.deepEqual([e.traceId, e.spanId], [TRACE, '00f067aa0ba902b7']);
  assert.throws(() => k.makeEvent(1, k.nowIso(), 'job.done', 'info', 'Done.', { traceId: TRACE }), k.ServiceError);
  assert.throws(() => k.makeEvent(1, k.nowIso(), 'job.done', 'info', 'Done.', { traceId: 'XYZ', spanId: '00f067aa0ba902b7' }), k.ServiceError);
});

test('a capability is served as a tool of its name with derived annotations', () => {
  const tool = i.toolForCapability({ name: 'example.echo', effect: 'none', idempotency: 'required' }, { type: 'object' }, { type: 'object' });
  assert.equal(tool.name, 'example.echo');
  assert.deepEqual(tool.annotations, { readOnlyHint: true, idempotentHint: true });
  assert.deepEqual(i.expectedAnnotations('merge', 'none'), { destructiveHint: true });
});

test('jobs: a stable handle, the Python file format, terminal states stay terminal', () => {
  const dir = temp();
  const handle = new i.JobStore(dir).create('example.draft', {}, { traceparent: PARENT });
  assert.deepEqual(Object.keys(handle.job), ['id', 'status']);
  const store = new i.JobStore(dir);
  assert.equal(store.get(handle.job.id).status, 'working');
  assertPrivateFile(path.join(dir, `${handle.job.id}.json`));
  assert.throws(() => store.get('job_nope'), i.UnknownJob);
  assert.equal(i.unknownJobResult('job_nope').structuredContent.error.code, 'unknown-job');
  assert.equal(store.complete(handle.job.id, envelope()).status, 'completed');
  assert.throws(() => store.cancel(handle.job.id), i.InteropError);
  const onDisk = JSON.parse(fs.readFileSync(path.join(dir, `${handle.job.id}.json`), 'utf8'));
  assert.deepEqual(Object.keys(onDisk).sort(), ['job', 'private']);
});

test('DEC-0017: the full envelope carries its trace; a job tool serves the union', () => {
  const env = envelope({ traceparent: PARENT });
  assert.deepEqual(Object.keys(env).sort(), ['artifacts', 'contractVersion', 'createdAt', 'done', 'id', 'notVerified', 'outcome', 'output', 'producer', 'proof', 'scope', 'trace', 'usage']);
  assert.throws(() => envelope({ outcome: 'succeeded', notVerified: [{ claim: 'x', reason: 'y' }] }), i.InteropError);
  const out = { type: 'object' };
  const u = i.jobToolOutputSchema(out);
  assert.equal(u.type, 'object');
  assert.equal(u.oneOf[0].properties.output, out);
  for (const bad of [{ type: 'array' }, { oneOf: [{ type: 'object' }] }]) {
    assert.throws(() => i.toolForCapability({ name: 'example.echo', effect: 'none', idempotency: 'none' }, {}, bad), i.InteropError);
  }
  assert.deepEqual(u.oneOf[1].properties.job.properties.status, { const: 'working' });
  assert.deepEqual(i.toolForCapability({ name: 'example.draft', effect: 'draft', idempotency: 'none', job: true }, {}, out).outputSchema, u);
  const dir = temp();
  const store = new i.JobStore(dir);
  const id = store.create('example.draft', {}, { traceparent: PARENT }).job.id;
  assert.deepEqual(store.complete(id, envelope()).result.trace, { traceparent: PARENT });
  const other = store.create('example.draft', {}, { traceparent: PARENT }).job.id;
  assert.throws(() => store.complete(other, envelope({ traceparent: i.childTraceparent(PARENT) })), i.InteropError);
});

test('form mode never asks for a secret; a choice is a titled single-select', () => {
  assert.throws(() => i.formRequest('Paste it.', { apiKey: { type: 'string' } }), i.InteropError);
  const req = i.choiceRequest('Pick.', 'title', [['a', 'A'], ['b', 'B']]);
  assert.deepEqual(req.params.requestedSchema.properties.title.oneOf, [{ const: 'a', title: 'A' }, { const: 'b', title: 'B' }]);
  assert.throws(() => envelope({ usage: { inputTokens: -1, outputTokens: 0, wallMs: 0 } }), i.InteropError);
});

test('URL mode hands over an open_link, never a raw local address (DEC-0123 PL-4, FAC-SEM-143, D12)', () => {
  const link = 'fabric-dashboards://service/example-agent.default?path=%2Fdashboard%2Fdrafts%2F7';
  assert.equal(i.urlRequest('Approve the draft.', link).params.url, link);
  assert.equal(i.urlRequest('Connect the account.', 'https://publish.example/connect').params.mode, 'url');
  for (const url of ['http://127.0.0.1:4100/x', 'http://localhost:4100/dashboard', 'http://127.1/', 'https://127.0.0.1/',
    'http://[::1]:4100/', 'http://0/', 'http://loc%61lhost/', 'fabric-dashboards://open?service=example-agent.default',
    'fabric-dashboards://service/Bad', ' fabric-dashboards://service/example-agent.default?path=x', 'http://agents.example/',
    'ftp://files.example/', '/dashboard', 7]) {
    assert.throws(() => i.urlRequest('Open it.', url), i.InteropError, String(url));
  }
  assert.throws(() => i.urlRequest('Open it.', 'http://127.0.0.1:4100/x'), /open_link.*DEC-0123|DEC-0123.*open_link/);
});

test('pageAnswer is PL-4\'s shape', () => {
  assert.deepEqual(i.pageAnswer('example-agent', 'default'), { open_link: 'fabric-dashboards://service/example-agent.default' });
  assert.deepEqual(i.pageAnswer('example-agent', 'default', { path: '/jobs/7', httpUrl: 'http://127.0.0.1:4100/jobs/7' }),
    { open_link: 'fabric-dashboards://service/example-agent.default?path=%2Fjobs%2F7', http_url: 'http://127.0.0.1:4100/jobs/7' });
  for (const [service, instance, path] of [['Example', 'default'], ['example-agent', 'default', 'jobs'], ['example-agent', 'default', '/x?token=abc']]) {
    assert.throws(() => i.pageAnswer(service, instance, { path }), i.InteropError);
  }
});

test('a URL-mode request on a raw local address is refused at requestInput; the job stays working', () => {
  const store = new i.JobStore(temp());
  const id = store.create('example.draft', {}).job.id;
  const raw = { method: 'elicitation/create', params: { mode: 'url', message: 'Approve.', url: 'http://127.0.0.1:4100/x' } };
  assert.throws(() => store.requestInput(id, { approve: raw }), (error) => error instanceof i.InteropError && error.message.includes('/inputRequests/approve/params/url'));
  assert.equal(store.get(id).status, 'working');
  const link = i.urlRequest('Approve.', 'fabric-dashboards://service/example-agent.default?path=%2Fdrafts%2F7');
  assert.equal(store.requestInput(id, { approve: link }).status, 'input_required');
});

// MCP 2026-07-28 standard headers: the Node twin agrees with fabric_interop.py.
test('mcpHeaderProblem refuses a declared request without Mcp-Method/Mcp-Name and any mismatch; matching headers pass', () => {
  const call = { jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'sample.echo', arguments: {} } };
  assert.match(i.mcpHeaderProblem(call, { 'MCP-Protocol-Version': i.MCP_REVISION }), /Mcp-Method header is absent/);
  assert.match(i.mcpHeaderProblem(call, { 'mcp-protocol-version': i.MCP_REVISION, 'mcp-method': 'tools/call' }), /Mcp-Name header is absent/);
  assert.match(i.mcpHeaderProblem(call, { 'Mcp-Method': 'tools/list' }), /disagrees/);
  assert.match(i.mcpHeaderProblem(call, new Headers({ 'Mcp-Method': 'tools/call', 'Mcp-Name': 'other' })), /Mcp-Name disagrees/);
  assert.equal(i.mcpHeaderProblem(call, i.mcpRequestHeaders('tools/call', call.params)), null);
  assert.equal(i.mcpHeaderProblem(call, {}), null, 'an earlier revision may omit them');
  assert.deepEqual(i.mcpRequestHeaders('tools/list'), { 'MCP-Protocol-Version': i.MCP_REVISION, 'Mcp-Method': 'tools/list' });
});

// MCP 2026-07-28 Streamable HTTP, "Value Encoding": the spec's own examples, as fabric_interop.py.
test('Mcp-Name values use the Base64 sentinel exactly as the spec shows, and a server compares them decoded', () => {
  for (const [value, header] of [['us-west1', 'us-west1'], ['Hello, 世界', '=?base64?SGVsbG8sIOS4lueVjA==?='], [' padded ', '=?base64?IHBhZGRlZCA=?='],
    ['line1\nline2', '=?base64?bGluZTEKbGluZTI=?='], ['=?base64?literal?=', '=?base64?PT9iYXNlNjQ/bGl0ZXJhbD89?=']]) {
    assert.equal(i.encodeHeaderValue(value), header, value);
    assert.equal(i.decodeHeaderValue(header), value, value);
  }
  const call = { jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: 'погода', arguments: {} } };
  const headers = i.mcpRequestHeaders('tools/call', call.params);
  assert.ok(headers['Mcp-Name'].startsWith('=?base64?'));
  assert.equal(i.mcpHeaderProblem(call, headers), null);
  assert.match(i.mcpHeaderProblem(call, { ...headers, 'Mcp-Name': i.encodeHeaderValue('другое') }), /disagrees/);
  assert.match(i.mcpHeaderProblem(call, { ...headers, 'Mcp-Name': '=?base64?***?=' }), /malformed/);
  assert.match(i.mcpHeaderProblem(call, { ...headers, 'Mcp-Name': 'погода' }), /malformed/);
});

// DEC-0121: the caller relays the operator's decision in _meta.decision (REQ-8); a Node service's own server gates a tool
// registered with an action with actionGate and answers its refusal with actionRefusalToolResult (REQ-7, D9, D11).
const AV = JSON.parse(fs.readFileSync(new URL('./fixtures/contract/actions-vectors.json', import.meta.url), 'utf8'));
const NOW = '2026-10-24T09:30:00Z';
const RELAYED = { id: 'approve-reply', title: 'Approve the reply', tool: 'reviews.approve', gate: 'relayed' };
const HUMAN = { id: 'connect-store', title: 'Connect the store', tool: 'accounts.connect', gate: 'human', humanStep: 'consent' };
const DECISION = { by: 'operator', via: 'relayed-instruction', action: 'approve-reply', target: 'reply-7', instruction: 'Agent: Approve the reply to Anna? Operator: yes', at: '2026-10-24T09:29:00Z' };

test('requestMeta carries the decision in _meta, copied, and never one the schema refuses', () => {
  const meta = i.requestMeta(PARENT, { decision: DECISION });
  assert.deepEqual(meta.decision, DECISION);
  assert.equal(meta.traceparent, PARENT);
  assert.equal('decision' in i.requestMeta(PARENT), false);
  meta.decision.instruction = 'changed';
  assert.equal(DECISION.instruction, 'Agent: Approve the reply to Anna? Operator: yes');
  const decisions = AV.fixtures.filter((c) => c.schema === 'decision.schema.json');
  assert.ok(decisions.some((c) => c.valid) && decisions.some((c) => !c.valid));
  for (const c of decisions) {
    if (c.valid) assert.deepEqual(i.requestMeta(PARENT, { decision: c.document }).decision, c.document, c.name);
    else assert.throws(() => i.requestMeta(PARENT, { decision: c.document }), i.InteropError, c.name);
  }
});

test('actionGate: no decision, a valid one, one in the arguments, a T2 caller, a human step', () => {
  const gate = (extra) => i.actionGate({ action: RELAYED, tier: 'T0', caller: 'local:T0', meta: {}, target: 'reply-7', now: NOW, ...extra });
  const none = gate();
  assert.equal(none.ok, false);
  assert.deepEqual(refusalError(none.refusal).error.data, { detail: 'no-decision' });
  assert.equal(none.refusal.code, 'operator-decision-required');
  const ok = gate({ meta: { decision: DECISION } });
  assert.deepEqual(ok, { ok: true, record: { by: 'operator', via: 'relayed-instruction', caller: 'local:T0' }, decision: DECISION });
  // A decision is read from _meta only: an inherited member is not one, and arguments are never read (D11).
  assert.equal(gate({ meta: Object.create({ decision: DECISION }) }).refusal.code, 'operator-decision-required');
  assert.equal(gate({ meta: { decision: null } }).refusal.code, 'decision-invalid');
  assert.equal(gate({ meta: { decision: { ...DECISION, target: 'reply-8' } } }).refusal.code, 'decision-invalid');
  const t2 = gate({ tier: 'T2', caller: 'agent:remote', meta: { decision: DECISION }, actionDigest: `sha256:${'a'.repeat(64)}` });
  assert.deepEqual([t2.refusal.code, t2.refusal.data], ['approval-required', { actionDigest: `sha256:${'a'.repeat(64)}` }]);
  const fault = gate({ tier: 'T2', caller: null, meta: { decision: DECISION } });
  assert.deepEqual([fault.refusal.code, fault.refusal.detail], ['unknown-state', 'service-fault']);
  const step = i.actionGate({ action: HUMAN, tier: 'T0', caller: 'local:T0', meta: { decision: { ...DECISION, action: 'connect-store' } }, humanStepUrl: '/connect/store', now: NOW });
  assert.deepEqual(refusalError(step.refusal).error.data, { detail: 'human-step', humanStep: 'consent', url: '/connect/store' });
  const own = i.actionGate({ action: { ...RELAYED, gate: 'none' }, tier: 'T2', caller: null, meta: { decision: DECISION }, now: NOW });
  assert.deepEqual(own, { ok: true, record: 'caller', decision: null });
  const elicited = gate({ elicited: true });
  assert.deepEqual(elicited.record, { by: 'operator', via: 'elicitation', caller: 'local:T0' });
  assert.equal(elicited.decision, null);
});

test('actionRefusalToolResult answers DL-19 structuredContent, or null for a call the action takes', () => {
  assert.equal(i.actionRefusalToolResult({ ok: true, recordAs: 'caller' }), null);
  const result = i.actionRefusalToolResult({ ok: false, code: 'operator-decision-required' }, PARENT);
  assert.equal(result.isError, true);
  assert.deepEqual(result.structuredContent.error.data, { detail: 'no-decision' });
  assert.equal(result.structuredContent.error.code, 'operator-decision-required');
  assert.equal(result._meta.traceparent, PARENT);
  assert.equal(i.actionRefusalToolResult({ fault: 'caller-missing' }).structuredContent.error.code, 'unknown-state');
});

// DEC-0125: the operator's mandate in _meta.mandate (FAA-131), the twin of test_interop's mandate tests.
const REPLY_SCOPE = { actions: ['approve-reply'], effects: ['reply'] };
const leadMandate = (scope = REPLY_SCOPE) => handOn(
  operatorMandate({ task: 'answer the reviews', instruction: 'answer every review from this week', scope, lead: 'example-lead', at: '2026-10-24T09:00:00Z' }),
  'example-agent', '2026-10-24T09:10:00Z');

test('requestMeta carries the mandate in _meta, copied, and never one FAC-SEM-144 refuses', () => {
  const mandate = leadMandate();
  const meta = i.requestMeta(PARENT, { mandate });
  assert.deepEqual(meta.mandate, mandate);
  assert.notEqual(meta.mandate, mandate);
  assert.equal('mandate' in i.requestMeta(PARENT), false);
  const both = i.requestMeta(PARENT, { decision: DECISION, mandate });
  assert.deepEqual([both.decision, both.mandate], [DECISION, mandate]);
  const vectors = JSON.parse(fs.readFileSync(new URL('./fixtures/contract/mandate-vectors.json', import.meta.url), 'utf8'));
  for (const c of vectors.fixtures) {
    if (c.valid) assert.deepEqual(i.requestMeta(PARENT, { mandate: c.document }).mandate, c.document, c.name);
    else assert.throws(() => i.requestMeta(PARENT, { mandate: c.document }), i.InteropError, c.name);
  }
  const widened = structuredClone(mandate);
  widened.chain[1].scope = { actions: ['approve-reply'], effects: ['publish'] };
  for (const bad of ['yes', [], widened]) assert.throws(() => i.requestMeta(PARENT, { mandate: bad }), i.InteropError);
});

test('actionGate reads a mandate only for a service that names its agent id, and names what it does not cover', () => {
  const gate = (extra) => i.actionGate({ action: RELAYED, tier: 'T0', caller: 'local:T0', meta: { mandate: leadMandate() }, target: 'reply-7', now: NOW, self: 'example-agent', effect: 'reply', ...extra });
  assert.deepEqual(gate(), {
    ok: true, decision: null, mandate: leadMandate(),
    record: { by: 'operator', via: 'mandate', task: 'answer the reviews', chain: ['example-lead', 'example-agent'], caller: 'local:T0' },
  });
  const unread = gate({ self: undefined });
  assert.deepEqual([unread.refusal.code, unread.refusal.detail], ['operator-decision-required', 'no-decision']);
  const fault = gate({ effect: undefined });
  assert.deepEqual([fault.refusal.code, fault.fault], ['unknown-state', 'effect-missing']);
  assert.deepEqual(refusalError(gate({ effect: 'publish' }).refusal).error.data, { detail: 'outside-mandate: effect' });
  const tight = leadMandate({ ...REPLY_SCOPE, perCallMaxUsd: 1 });
  assert.deepEqual(refusalError(gate({ meta: { mandate: tight }, spendUsd: 2 }).refusal).error.data, { detail: 'outside-mandate: spend', estimateUsd: 2, perCallMaxUsd: 1 });
  const other = refusalError(gate({ callerAgent: 'example-other' }).refusal).error;
  assert.deepEqual([other.code, other.data], ['decision-invalid', { detail: 'mandate-not-for-this-call' }]);
  assert.deepEqual(refusalError(gate({ now: '2026-10-25T09:00:00Z' }).refusal).error.data, { detail: 'mandate-expired' });
  assert.deepEqual(refusalError(gate({ meta: { mandate: 'yes' } }).refusal).error.data, { detail: 'mandate-malformed' });
  assert.equal(gate({ meta: Object.create({ mandate: leadMandate() }) }).refusal.code, 'operator-decision-required'); // own members only
  const decided = gate({ meta: { mandate: leadMandate(), decision: DECISION } });
  assert.deepEqual([decided.record.via, decided.decision, 'mandate' in decided], ['relayed-instruction', DECISION, false]);
  const t2 = gate({ tier: 'T2', caller: 'agent:remote', actionDigest: `sha256:${'a'.repeat(64)}` });
  assert.equal(t2.refusal.code, 'approval-required');
});

test('an outside-mandate answer reaches the caller with the MD-4 wording (DEC-0125 MD-4)', async () => {
  const k = await import('../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-interop.mjs');
  const outside = k.actionRefusalToolResult({ ok: false, code: 'operator-decision-required', data: { detail: 'outside-mandate: spend', estimateUsd: 25, perCallMaxUsd: 1 } });
  assert.match(outside.structuredContent.error.message, /pass this refusal/);
  const plain = k.actionRefusalToolResult({ ok: false, code: 'operator-decision-required', data: { detail: 'no-decision' } });
  assert.doesNotMatch(plain.structuredContent.error.message, /pass this refusal/);
});
