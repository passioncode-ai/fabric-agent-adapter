// fabric-load.mjs: the call queue and the load report of DEC-0104 (FAA-289), the twin of test_fabric_load.py. Every case
// of load-vectors.json (the contract's agent-network vectors, its job-queue, service-load and service-well-known-load
// semantic fixtures, its service-load and service-load-extension catalogue fixtures and the kit's own hostile inputs,
// each answered by the contract's functions and validator at the pin) is read here as the contract reads it.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import * as fl from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-load.mjs';
import * as facade from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';
import { ServiceError } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-base.mjs';
import { QUEUE_FULL } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-interop-rules.mjs';

const read = (name) => JSON.parse(fs.readFileSync(new URL(name, import.meta.url), 'utf8'));
const V = read('./fixtures/contract/load-vectors.json');
const LOCK = read('../fabric-contract.lock.json');
const nul = (value) => (value === undefined ? null : value);
const codes = (findings) => findings.map(({ code, instancePath }) => ({ code, instancePath }));
const LIMITS = { concurrency: 4, perCaller: 2, queueMax: 50 };

test('the vectors are the pin\'s', () => {
  assert.equal(V.commit, LOCK.commit);
  assert.equal(V.extensionKey, fl.LOAD_EXTENSION_KEY);
  assert.deepEqual([V.queue.length, V.admit.length, V.caller.length, V.position.length], [29, 19, 23, 16]);
});

test('the next job', () => {
  for (const c of V.queue) assert.deepEqual(nul(fl.nextQueuedJob(c.queue, c.running, c.limits)), c.expected, c.name);
});

test('admission', () => {
  for (const c of V.admit) assert.deepEqual(fl.admitJob(c.queue, c.running, c.job, c.limits, c.retryAfterSeconds), c.expected, c.name);
});

test('the caller key', () => {
  for (const c of V.caller) assert.equal(nul(fl.jobCallerKey(c.accepted, c.credential)), c.expected, c.name);
});

test('the position and the status message', () => {
  for (const c of V.position) assert.deepEqual(nul(fl.readQueuePosition(c.statusMessage)), c.expected, c.name);
  for (const c of V.status) {
    assert.equal(nul(fl.queueStatusMessage(c.position, c.length)), c.expected, c.name);
    if (c.expected !== null) assert.deepEqual(fl.readQueuePosition(c.expected), { position: c.position, length: c.length }, c.name);
  }
});

test('the semantic fixtures', () => {
  assert.equal(V.rules.length, 12);
  for (const c of V.rules) {
    const got = c.kind === 'job-queue' ? fl.jobQueueRules(c.value) : c.kind === 'service-load' ? fl.loadReportRules(c.value) : codes(fl.loadExtensionRules(c.value));
    assert.deepEqual(got, c.findings, c.name);
  }
});

test('the declarations', () => {
  for (const c of V.declarations) {
    const wellKnown = { extensions: { [V.extensionKey]: c.value } };
    const view = fl.loadView(wellKnown);
    assert.equal(view.declared, true, c.name);
    assert.equal(view.valid, c.valid, `${c.name}: ${view.errors.join('; ')}`);
    assert.equal(view.errors.length === 0, c.valid, c.name);
    assert.deepEqual(view.load, c.valid ? c.value : null, c.name);
    assert.deepEqual(codes(fl.loadExtensionRules(wellKnown)), c.findings, c.name);
  }
  for (const c of V.documents) assert.deepEqual(codes(fl.loadExtensionRules(c.value)), c.findings, c.name);
});

test('the reports', () => {
  for (const c of V.reports) {
    const problems = fl.loadReportProblems(c.value);
    assert.equal(problems.length === 0, c.valid, `${c.name}: ${problems.join('; ')}`);
    assert.deepEqual(fl.loadReportRules(c.value), c.findings, c.name);
  }
  for (const c of [...V.declarations, ...V.reports]) if ('catalogue' in c) assert.equal(c.catalogue, c.valid, c.name);
});

test('a declaration reads back, and one a reader would hide is refused', () => {
  const entry = fl.loadExtension({ path: '/fabric/v1/load', windowSeconds: 3600, limits: LIMITS });
  assert.deepEqual(Object.keys(entry), [fl.LOAD_EXTENSION_KEY]);
  assert.deepEqual([fl.loadView({ extensions: entry }).declared, fl.loadView({ extensions: entry }).valid], [true, true]);
  assert.deepEqual(fl.loadExtensionRules({ extensions: entry }), []);
  for (const args of [
    { path: 'load', windowSeconds: 3600, limits: LIMITS }, { path: '/load', windowSeconds: 30, limits: LIMITS },
    { path: '/load', windowSeconds: 3600, limits: { ...LIMITS, concurrency: 0 } }, { path: '/load', windowSeconds: 3600, limits: { concurrency: 1 } },
    { path: '//x', windowSeconds: 3600, limits: LIMITS }, { path: '/load', windowSeconds: 3600, limits: null }, undefined,
  ]) assert.throws(() => fl.loadExtension(args), ServiceError, JSON.stringify(args));
  const limits = { ...LIMITS };
  const copied = fl.loadExtension({ path: '/load', windowSeconds: 60, limits });
  limits.concurrency = 0;
  assert.equal(copied[fl.LOAD_EXTENSION_KEY].limits.concurrency, 4);
});

test('a node queues with its declared limits', () => {
  const { limits } = fl.loadExtension({ path: '/load', windowSeconds: 60, limits: { concurrency: 1, perCaller: 1, queueMax: 1 } })[fl.LOAD_EXTENSION_KEY];
  const a = fl.jobCallerKey({ ok: true, principal: 'urn:person:a', caller: 'writer', chain: ['writer'] }, 'hub');
  const b = fl.jobCallerKey(null, 'local-session');
  const queue = [];
  const running = [];
  const first = { id: 'j1', caller: a, at: '2026-10-22T09:00:01Z' };
  assert.deepEqual(fl.admitJob(queue, running, first, limits, 30), { admit: true });
  assert.equal(fl.nextQueuedJob([first], running, limits), 'j1');
  running.push({ id: 'j1', caller: a });
  const second = { id: 'j2', caller: b, at: '2026-10-22T09:00:02Z' };
  assert.deepEqual(fl.admitJob(queue, running, second, limits, 30), { admit: true });
  queue.push(second);
  assert.equal(fl.queueStatusMessage(queue.indexOf(second) + 1, queue.length), 'queued 1 of 1');
  const refused = fl.admitJob(queue, running, { id: 'j3', caller: a, at: '2026-10-22T09:00:03Z' }, limits, 30);
  assert.deepEqual([refused.admit, refused.error.code, refused.error.data.retryAfterSeconds], [false, QUEUE_FULL, 30]);
  assert.equal(fl.nextQueuedJob(queue, running, limits), undefined);
  running.length = 0;
  assert.equal(fl.nextQueuedJob(queue, running, limits), 'j2');
});

test('nothing throws on what it reads', () => {
  for (const value of [null, undefined, 7, 'x', [], {}, [null], { windows: 'x' }, { extensions: null }, true]) {
    fl.nextQueuedJob(value, value, value);
    fl.admitJob(value, value, value, value, value);
    fl.jobCallerKey(value, value);
    fl.queueStatusMessage(value, value);
    fl.readQueuePosition(value);
    fl.jobQueueRules(value);
    fl.loadReportRules(value);
    fl.loadReportProblems(value);
    fl.loadView(value);
    fl.loadExtensionRules(value);
  }
});

test('the facade exports the module', () => {
  for (const name of ['LOAD_EXTENSION_KEY', 'LOAD_REPORT_TYPE', 'QUEUE_FULL_MESSAGE', 'QUEUE_LENGTH_MAX', 'DEFAULT_RETRY_AFTER_SECONDS', 'jobCallerKey', 'nextQueuedJob', 'admitJob',
    'queueStatusMessage', 'readQueuePosition', 'jobQueueRules', 'loadReportRules', 'loadReportProblems', 'loadView', 'loadExtensionRules', 'loadExtension']) {
    assert.equal(facade[name], fl[name], name);
  }
});
