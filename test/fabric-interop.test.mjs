import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import * as i from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-interop.mjs';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';

const PARENT = '00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01';
const TRACE = '4bf92f3577b34da6a3ce929d0e0e4736';
const temp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-interop-'));
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
  assert.equal((fs.statSync(path.join(dir, `${handle.job.id}.json`)).mode & 0o777), 0o600);
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
