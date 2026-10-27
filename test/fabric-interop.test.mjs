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
    // to a callee that reads source (DEC-0126 OA-7), exactly as given
    if (c.valid) assert.deepEqual(i.requestMeta(PARENT, { mandate: c.document, targetProtocols: ['operator-source/1'] }).mandate, c.document, c.name);
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

test('FAA-139: actionGate reads spend and project failing closed, as the Python server does', () => {
  const gate = (meta, extra) => i.actionGate({ action: RELAYED, tier: 'T0', caller: 'local:T0', meta, target: 'reply-7', now: NOW, self: 'example-agent', effect: 'reply', ...extra });
  const tight = { mandate: leadMandate({ ...REPLY_SCOPE, perCallMaxUsd: 1 }) };
  const scoped = { mandate: leadMandate({ ...REPLY_SCOPE, projects: ['alpha'] }) };
  for (const spendUsd of [Infinity, NaN, '0.5', true, 10n ** 400n]) {
    const refusal = gate(tight, { spendUsd }).refusal;
    assert.equal(refusalError(refusal).error.data.detail, 'outside-mandate: spend', String(spendUsd).slice(0, 12));
    JSON.stringify(refusalError(refusal)); // nothing a JSON writer refuses
  }
  for (const project of [7, ['alpha'], { id: 'alpha' }]) {
    assert.equal(refusalError(gate(scoped, { spendUsd: 0.5, project }).refusal).error.data.detail, 'outside-mandate: project');
  }
  assert.equal(gate(scoped, { spendUsd: 0.5, project: 'alpha' }).ok, true);
  assert.equal(gate(tight, { spendUsd: 1 }).ok, true);
});

test('0.56.0 seam r1: jobStep reads spend and project as actionGate does, failing closed', () => {
  const call = { tier: 'T0', now: NOW, self: 'example-agent', capability: 'reviews.approve', key: 'approve-reply', effect: 'reply' };
  const tight = leadMandate({ ...REPLY_SCOPE, perCallMaxUsd: 1 });
  const scoped = leadMandate({ ...REPLY_SCOPE, projects: ['alpha'] });
  for (const spendUsd of [NaN, Infinity, '0.5', true]) {
    const step = i.jobStep({ ...call, mandate: tight, spendUsd });
    assert.deepEqual([step.covered, step.detail], [false, 'outside-mandate: spend'], String(spendUsd));
  }
  for (const project of [7, ['alpha']]) {
    const step = i.jobStep({ ...call, mandate: scoped, spendUsd: 0.5, project });
    assert.deepEqual([step.covered, step.detail], [false, 'outside-mandate: project']);
  }
  assert.equal(i.jobStep({ ...call, mandate: scoped, spendUsd: 0.5, project: 'alpha' }).covered, true);
  assert.equal(i.jobStep({ ...call, mandate: tight, spendUsd: 1 }).covered, true);
});

test('an outside-mandate answer reaches the caller with the MD-4 wording (DEC-0125 MD-4)', async () => {
  const k = await import('../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-interop.mjs');
  const outside = k.actionRefusalToolResult({ ok: false, code: 'operator-decision-required', data: { detail: 'outside-mandate: spend', estimateUsd: 25, perCallMaxUsd: 1 } });
  assert.match(outside.structuredContent.error.message, /pass this refusal/);
  const plain = k.actionRefusalToolResult({ ok: false, code: 'operator-decision-required', data: { detail: 'no-decision' } });
  assert.doesNotMatch(plain.structuredContent.error.message, /pass this refusal/);
});

// DEC-0126: where the operator said the words (`source`, OA-1 to OA-7; FAA-134), the twin of test_interop's source tests.
const SOURCE = { project: 'example-analyst', session: 'sess-0042' };
const relayedMandate = (scope = REPLY_SCOPE) => handOn(
  operatorMandate({ task: 'answer the reviews', instruction: 'answer every review from this week', scope, lead: 'example-lead', at: '2026-10-24T09:00:00Z', source: SOURCE }),
  'example-agent', '2026-10-24T09:10:00Z');

test('requestMeta sends source only to a target that lists operator-source/1 (DEC-0126 OA-7)', () => {
  const decision = { ...DECISION, source: SOURCE };
  const mandate = relayedMandate();
  for (const targetProtocols of [undefined, null, [], ['fabric-service/0.1'], 'operator-source/1', { 'operator-source/1': true }]) {
    const meta = i.requestMeta(PARENT, { decision, mandate, targetProtocols });
    assert.equal(Object.hasOwn(meta.decision, 'source') || Object.hasOwn(meta.mandate, 'source'), false, JSON.stringify(targetProtocols));
    assert.deepEqual(meta.decision, DECISION);
  }
  const meta = i.requestMeta(PARENT, { decision, mandate, targetProtocols: ['operator-source/1'] });
  assert.deepEqual([meta.decision.source, meta.mandate.source], [SOURCE, SOURCE]);
  assert.deepEqual([decision.source, mandate.source], [SOURCE, SOURCE]); // the caller's own record keeps it
  meta.mandate.source.project = 'changed';
  assert.equal(mandate.source.project, 'example-analyst');
  assert.throws(() => i.requestMeta(PARENT, { decision: { ...DECISION, source: { project: 'example-analyst' } } }), i.InteropError);
});

test('actionGate records the source of a decision and of a mandate, and its refusals never carry it (OA-6, OA-7)', () => {
  const gate = (meta, extra = {}) => i.actionGate({ action: RELAYED, tier: 'T0', caller: 'local:T0', meta, target: 'reply-7', now: NOW, self: 'example-agent', effect: 'reply', ...extra });
  const relayed = { ...DECISION, at: NOW, source: SOURCE };
  assert.deepEqual(gate({ decision: relayed }).record, { by: 'operator', via: 'relayed-instruction', caller: 'local:T0', source: SOURCE });
  assert.deepEqual(gate({ mandate: relayedMandate() }).record.source, SOURCE);
  const refusals = [gate({ decision: { ...relayed, at: '2026-10-20T09:00:00Z' } }), gate({ mandate: relayedMandate({ actions: ['other'], effects: ['reply'] }) }),
    gate({ decision: relayed }, { tier: 'T2', actionDigest: `sha256:${'a'.repeat(64)}` })];
  assert.ok(refusals.every((r) => r.ok === false));
  const text = JSON.stringify(refusals.map((r) => i.actionRefusalToolResult({ ok: false, code: r.refusal.code, data: r.refusal.data })));
  for (const word of ['example-analyst', 'sess-0042', 'answer every review from this week']) assert.equal(text.includes(word), false, word);
});

test('jobStep: a job reads the mandate its start call carried at its own approval step (C3.3, REQ-8)', () => {
  const call = { tier: 'T0', now: NOW, self: 'example-agent', capability: 'reviews.approve', key: 'approve-reply', effect: 'reply' };
  assert.deepEqual(i.jobStep({ ...call, mandate: relayedMandate() }), {
    covered: true, record: { by: 'operator', via: 'mandate', task: 'answer the reviews', chain: ['example-lead', 'example-agent'], source: SOURCE },
  });
  const outside = i.jobStep({ ...call, mandate: leadMandate({ actions: ['other-action'], effects: ['reply'] }) });
  assert.equal(outside.covered, false);
  assert.equal(outside.detail, 'outside-mandate: action');
  assert.ok(outside.message.includes('outside-mandate: action') && outside.message.includes('_meta.mandate'));
  const expired = i.jobStep({ ...call, now: '2026-10-26T09:30:00Z', mandate: leadMandate() });
  assert.equal(expired.detail, 'mandate-expired');
  assert.ok(expired.message.includes('expired'));
  assert.ok(i.jobStep({ ...call, mandate: { kind: 'mandate/1' } }).message.includes('cannot be read'));
  assert.deepEqual(i.jobStep({ ...call }), { covered: false, message: null });
  assert.deepEqual(i.jobStep({ ...call, tier: 'T2', mandate: leadMandate() }), { covered: false, message: null });
  assert.equal(i.jobStep({ ...call, now: 'never', mandate: leadMandate() }).fault, 'now-unreadable');
  assert.equal(i.jobStep({ ...call, callerAgent: 'example-lead', mandate: leadMandate() }).covered, true);
  assert.equal(i.jobStep({ ...call, callerAgent: 'example-other', mandate: leadMandate() }).detail, 'mandate-not-for-this-call');
  assert.throws(() => i.jobStep({ ...call, effect: 'Reply', mandate: leadMandate() }), i.InteropError);
});

test('requestInput keeps an approval step in the job\'s private part, the Python file format (DEC-0125)', () => {
  const dir = temp();
  const store = new i.JobStore(dir);
  const { job } = store.create('reviews.approve', {}, { traceparent: PARENT });
  const request = i.choiceRequest('Publish the reply?', 'choice', [['yes', 'Yes'], ['no', 'No']]);
  assert.throws(() => store.requestInput(job.id, { 'approve-reply': request }, 'x', { steps: { other: { effect: 'reply' } } }), i.InteropError);
  assert.throws(() => store.requestInput(job.id, { 'approve-reply': request }, 'x', { steps: { 'approve-reply': { effect: 'Reply' } } }), i.InteropError);
  assert.equal(store.get(job.id).status, 'working');
  store.requestInput(job.id, { 'approve-reply': request }, 'Publish it?', { steps: { 'approve-reply': { effect: 'reply', spendUsd: 0 } } });
  const onDisk = JSON.parse(fs.readFileSync(path.join(dir, `${job.id}.json`), 'utf8'));
  assert.deepEqual(onDisk.private.steps, { 'approve-reply': { effect: 'reply', spendUsd: 0 } });
  assert.equal(onDisk.job.status, 'input_required');
  assert.equal(JSON.stringify(onDisk.job).includes('steps'), false);
  // Each question replaces the kept steps: a later plain question under the same key keeps none (seam round 1).
  store.working(job.id);
  store.requestInput(job.id, { 'approve-reply': request }, 'Publish another?');
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(dir, `${job.id}.json`), 'utf8')).private.steps, {});
});

test('actionGate reads a kept job step under mandateCapability, not the action\'s tool (seam round 3)', () => {
  const step = { id: 'approve-reply', title: 'Answer approve-reply', tool: 'fabric.job.get', gate: 'relayed' };
  const mandate = leadMandate({ capabilities: ['reviews.approve'], actions: ['approve-reply'], effects: ['reply'] });
  const gate = (extra) => i.actionGate({ action: step, tier: 'T0', caller: 'local:T0', meta: { mandate }, now: NOW, self: 'example-agent', effect: 'reply', ...extra });
  assert.equal(gate({}).ok, false, 'under fabric.job.get the capability is not the job\'s');
  assert.equal(gate({ mandateCapability: 'reviews.approve' }).ok, true);
  // DEC-0141 MJ-1: an unusable job capability is answered as a step the mandate does not cover, the fault kept.
  for (const mandateCapability of [undefined, '', '  ', 'Reviews Approve', 'fabric.job.get']) {
    const refused = gate({ mandateCapability });
    assert.equal(refused.ok, false, String(mandateCapability));
    assert.equal(refused.fault, 'mandate-capability-missing');
    assert.equal(refused.refusal.code, 'operator-decision-required');
    assert.equal(refused.refusal.data.detail, 'mandate-capability-missing');
    const said = i.actionRefusalToolResult(k.actionDecision({ action: step, tier: 'T0', caller: 'local:T0', mandate, now: NOW, self: 'example-agent', effect: 'reply', mandateCapability }));
    assert.equal(said.structuredContent.error.code, 'operator-decision-required');
    assert.equal(said.structuredContent.error.data.detail, 'mandate-capability-missing');
  }
});

test('jobStep reads an unusable job capability as the answer does (DEC-0141 MJ-1)', () => {
  const mandate = leadMandate({ actions: ['approve-reply'], effects: ['reply'] });
  for (const capability of ['replyDraft', 'fabric.job.get', '']) {
    const step = i.jobStep({ mandate, tier: 'T0', now: NOW, self: 'example-agent', capability, key: 'approve-reply', effect: 'reply' });
    assert.equal(step.covered, false, capability);
    assert.equal(step.fault, 'mandate-capability-missing');
    assert.match(step.message, /mandate-capability-missing/);
    // MD-5 first: a T2 caller's mandate changes nothing, whatever the job's capability.
    assert.deepEqual(i.jobStep({ mandate, tier: 'T2', now: NOW, self: 'example-agent', capability, key: 'approve-reply', effect: 'reply' }), { covered: false, message: null });
  }
});

test('answer clears the answered question\'s kept steps in the same write', () => {
  const dir = temp();
  const store = new i.JobStore(dir);
  const { job } = store.create('reviews.approve', {}, { traceparent: PARENT });
  const request = i.choiceRequest('Publish the reply?', 'choice', [['yes', 'Yes'], ['no', 'No']]);
  store.requestInput(job.id, { 'approve-reply': request }, 'Publish it?', { steps: { 'approve-reply': { effect: 'reply' } } });
  store.answer(job.id, { 'approve-reply': { action: 'accept', content: { choice: 'yes' } } });
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(dir, `${job.id}.json`), 'utf8')).private.steps, {});
});
