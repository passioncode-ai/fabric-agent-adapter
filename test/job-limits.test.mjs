// Jobs under limits and uncertain effects (contract DEC-0087, FAC-SEM-119/120; FAA-56) in the Node interop kit, the
// twin of test_job_limits.py: the contract's vectors as job-limit-vectors.json vendors them, and the provider's side on
// a real JobStore, written in the same file format the Python kit reads.
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-interop.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const V = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/job-limit-vectors.json'), 'utf8'));
const NOW = '2026-10-19T10:00:00Z';

function store(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'job-limits-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return new k.JobStore(path.join(dir, 'jobs'));
}
const start = (jobs, caller = 'caller-a', key = 'k-1') => jobs.create('media.order', { brief: 'x' }, { caller, idempotencyKey: key }).job.id;

test('queue-full never ends a job (DEC-0104): the store refuses it; QUEUE_FULL names the code', (t) => {
  assert.equal(k.QUEUE_FULL, 'queue-full');
  const jobs = store(t);
  const id = start(jobs);
  assert.throws(() => jobs.fail(id, k.QUEUE_FULL, 'the queue is full'), k.InteropError);
  assert.equal(jobs.fail(id, 'provider-error', 'stopped').status, 'failed');
});

test('every pause, caller, key, usage and reader case answers as the contract does', () => {
  for (const c of V.pause) assert.deepEqual(k.readJobPause(c.answer), c.expected, c.name);
  for (const c of V.caller) assert.deepEqual('now' in c ? k.jobCallerAction(c.answer, c.now) : k.jobCallerAction(c.answer), c.expected, c.name);
  for (const c of V.key) assert.equal(k.intentIdempotencyKey(c.intent) ?? null, c.expected, c.name);
  for (const c of V.usage) assert.deepEqual(k.usageFindings(c.usage, '').map((f) => `${f.code} ${f.instancePath}`), c.findings, c.name);
  for (const c of V.reader) assert.equal(k.readsNullUsage(c.meta), c.expected, c.name);
  for (const c of V.rules) assert.deepEqual(k.jobLimitRules(c.kind, c.value), c.findings, c.name);
});

test('hostile input never throws', () => {
  for (const value of [null, 0, 'x', [], {}, { job: null }, { job: { id: '', status: 'failed' } }, Number.NaN]) {
    k.readJobPause(value); k.jobCallerAction(value, value); k.readsNullUsage(value); k.usageFindings(value, '');
    assert.equal(k.intentIdempotencyKey(value), undefined);
  }
  assert.equal(k.intentIdempotencyKey({ agentId: 'a', capability: 'c', input: { n: Infinity } }), undefined);
  assert.equal(k.intentIdempotencyKey({ agentId: 'a', capability: 'c', input: { s: '\ud800' } }), undefined);
});

test('a paused job reads as paused and a caller waits', (t) => {
  const jobs = store(t);
  const id = start(jobs);
  const job = jobs.pause(id, { resetsAt: '2026-10-19T12:00:00Z', text: "the provider's hourly quota" });
  assert.equal(job.statusMessage, "quota-exhausted until 2026-10-19T12:00:00Z: the provider's hourly quota");
  assert.deepEqual(k.jobCallerAction({ job }, NOW), { action: 'wait', notBefore: '2026-10-19T12:00:00Z' });
  assert.equal(jobs.pause(id).statusMessage, 'quota-exhausted');
  for (const bad of ['2026-10-19T12:00:00+02:00', '2026-02-30T12:00:00Z', '2026-10-19T12:00:00.1234Z']) assert.throws(() => jobs.pause(id, { resetsAt: bad }), k.InteropError);
  assert.throws(() => jobs.pause(id, { text: ' \t' }), k.InteropError);
});

test('quota-exhausted carries its data; outcome-unknown is reconciled, never run again', (t) => {
  const jobs = store(t);
  const job = jobs.quotaExhausted(start(jobs), 'the monthly plan is used up', { retryable: true, resetsAt: '2026-11-01T00:00:00Z' });
  assert.deepEqual(job.error, { code: 'quota-exhausted', message: 'the monthly plan is used up', data: { retryable: true, resetsAt: '2026-11-01T00:00:00Z' } });
  assert.throws(() => jobs.quotaExhausted(start(jobs, 'caller-a', 'k-2'), 'x', { retryable: false, resetsAt: '2026-11-01T00:00:00Z' }), k.InteropError);
  const unknown = jobs.outcomeUnknown(start(jobs, 'caller-a', 'k-3'), 'the payment request timed out after it was sent', { mayHaveRun: true });
  assert.deepEqual(k.jobCallerAction({ job: unknown }, NOW), { action: 'reconcile' });
  assert.equal(jobs.repeat('caller-a', 'k-3', NOW).decision, 'same');
  assert.throws(() => start(jobs, 'caller-a', 'k-3'), k.InteropError);
});

test('keys are per caller, and a limited key runs again once the limit no longer holds', (t) => {
  const jobs = store(t);
  const first = start(jobs, 'caller-a');
  assert.notEqual(start(jobs, 'caller-b'), first, 'two callers never share a job');
  assert.deepEqual(jobs.repeat('caller-c', 'k-1', NOW), { decision: 'new', job: null });
  assert.throws(() => start(jobs, 'caller-a'), k.InteropError);
  jobs.quotaExhausted(first, 'hourly quota', { retryable: true, resetsAt: '2026-10-19T11:00:00Z' });
  assert.equal(jobs.repeat('caller-a', 'k-1', NOW).decision, 'same');
  assert.equal(jobs.repeat('caller-a', 'k-1', '2026-10-19T11:00:00Z').decision, 'run');
  const second = jobs.create('media.order', { brief: 'x' }, { caller: 'caller-a', idempotencyKey: 'k-1', now: '2026-10-19T11:00:00Z' }).job.id;
  assert.deepEqual(jobs.repeat('caller-a', 'k-1', '2026-10-19T11:00:01Z'), { decision: 'same', job: jobs.get(second) });
  const held = start(jobs, 'caller-a', 'k-4');
  jobs.quotaExhausted(held, 'budget', { retryable: false });
  assert.equal(jobs.repeat('caller-a', 'k-4', NOW, { limitHolds: false }).decision, 'run');
  const window = start(jobs, 'caller-a', 'k-5');
  jobs.fail(window, 'limit-reached', "the grant's spend window is used up", { approval: 'urn:example:approval:1' });
  assert.equal(jobs.repeat('caller-a', 'k-5', NOW).decision, 'same');
  assert.equal(jobs.repeat('caller-a', 'k-5', NOW, { approvalGranted: true }).decision, 'run');
});

test('the usage gate between fabric-interop/0.1 and 0.2 readers', () => {
  const measured = { inputTokens: 1200, outputTokens: null, wallMs: 5100, costUsd: null };
  const newer = k.requestMeta();
  assert.deepEqual(newer.protocols, ['fabric-interop/0.1', 'fabric-interop/0.2']);
  assert.deepEqual(k.usageToward(measured, {}), { inputTokens: 1200, outputTokens: 0, wallMs: 5100, costUsd: 0 });
  assert.deepEqual(k.usageToward(measured, newer), { ...measured, partial: true });
  assert.throws(() => k.usageToward({ ...measured, partial: false }, newer), k.InteropError);
  const envelope = { outcome: 'succeeded', done: [], proof: [], scope: {}, notVerified: [], output: {}, producer: { agent: 'example-agent' } };
  assert.equal(k.resultEnvelope({ ...envelope, usage: measured }).usage.outputTokens, 0);
  assert.equal(k.resultEnvelope({ ...envelope, usage: measured, requestMeta: newer }).usage.outputTokens, null);
});

test('both kits write the same key file and read each other\'s jobs', (t) => {
  // The key index is keyed by sha256 of JSON [caller, key], as fabric_interop.JobStore._key_path writes it.
  const jobs = store(t);
  const id = start(jobs, 'caller-a', 'k-1');
  const files = fs.readdirSync(path.join(jobs.dir, 'keys'));
  assert.equal(files.length, 1);
  assert.equal(files[0], `${crypto.createHash('sha256').update('["caller-a","k-1"]').digest('hex')}.json`, 'the name fabric_interop.py writes');
  const intent = `sha256:${crypto.createHash('sha256').update('["media.order",{"brief":"x"}]').digest('hex')}`;
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(jobs.dir, 'keys', files[0]), 'utf8')), { job: id, intent });
  assert.equal(k.intentDigest('media.order', { brief: 'x' }), intent);
});

test('FAA-77 item 39: a limited key runs again only for the intent it was first sent with', (t) => {
  const jobs = store(t);
  const first = start(jobs);
  jobs.quotaExhausted(first, 'hourly quota', { retryable: true, resetsAt: '2026-10-19T11:00:00Z' });
  const later = '2026-10-19T11:00:00Z';
  for (const [capability, input] of [['media.order', { brief: 'y' }], ['media.refund', { brief: 'x' }], ['media.order', { brief: 'x', to: 'someone-else' }]]) {
    assert.throws(() => jobs.create(capability, input, { caller: 'caller-a', idempotencyKey: 'k-1', now: later }), /^InteropError: idempotency-conflict|idempotency-conflict/, JSON.stringify(input));
  }
  assert.equal(fs.readdirSync(jobs.dir).filter((f) => f.startsWith('job_')).length, 1, 'a refused intent starts nothing');
  assert.notEqual(jobs.create('media.order', { brief: 'x' }, { caller: 'caller-a', idempotencyKey: 'k-1', now: later }).job.id, first);
  const running = start(jobs, 'caller-a', 'k-2');
  assert.throws(() => jobs.create('media.order', { brief: 'z' }, { caller: 'caller-a', idempotencyKey: 'k-2' }), (e) => e.message.startsWith('idempotency-conflict'));
  assert.equal(jobs.repeat('caller-a', 'k-2', NOW).job.id, running);
});

// Rewrite a key file as a kit before 0.41.0 wrote it: {"job": id}, no intent.
const legacy = (jobs, id, key = 'k-1') => fs.writeFileSync(path.join(jobs.dir, 'keys', `${crypto.createHash('sha256').update(JSON.stringify(['caller-a', key])).digest('hex')}.json`), `${JSON.stringify({ job: id })}\n`);
const jobFiles = (jobs) => fs.readdirSync(jobs.dir).filter((f) => f.startsWith('job_')).length;

test('FAA-77: a key file from 0.40.0 is answered with its job, never idempotency-conflict', (t) => {
  const jobs = store(t);
  const first = start(jobs);
  legacy(jobs, first);
  for (const input of [{ brief: 'x' }, { brief: 'y' }]) {
    assert.throws(() => jobs.create('media.order', input, { caller: 'caller-a', idempotencyKey: 'k-1' }), (e) => e.message.startsWith(`Key k-1 already names job ${first}; answer with that job`), JSON.stringify(input));
  }
  assert.deepEqual(jobs.repeat('caller-a', 'k-1', NOW), { decision: 'same', job: jobs.get(first) });
  assert.equal(jobs.repeat('caller-a', 'k-1', NOW, { capability: 'media.order', input: { brief: 'y' } }).decision, 'same', 'a legacy record answers as before');
  assert.equal(jobFiles(jobs), 1, 'nothing started');
});

test('FAA-77: a limited key file from 0.40.0 runs again only for its own job\'s input', (t) => {
  const jobs = store(t);
  const held = start(jobs);
  jobs.quotaExhausted(held, 'budget', { retryable: false });
  legacy(jobs, held);
  assert.throws(() => jobs.create('media.order', { brief: 'z' }, { caller: 'caller-a', idempotencyKey: 'k-1', limitHolds: false }), (e) => e.message.startsWith(`Key k-1 already names job ${held}`));
  assert.equal(jobFiles(jobs), 1);
  const second = jobs.create('media.order', { brief: 'x' }, { caller: 'caller-a', idempotencyKey: 'k-1', limitHolds: false }).job.id;
  assert.notEqual(second, held);
  assert.equal(jobs.repeat('caller-a', 'k-1', NOW, { capability: 'media.order', input: { brief: 'z' } }).decision, 'conflict', 'the new key file carries the intent');
});

test('FAA-77: repeat given the intent answers conflict for another one', (t) => {
  const jobs = store(t);
  const first = start(jobs);
  assert.deepEqual(jobs.repeat('caller-a', 'k-1', NOW, { capability: 'media.order', input: { brief: 'x' } }), { decision: 'same', job: jobs.get(first) });
  for (const [capability, input] of [['media.order', { brief: 'y' }], ['media.refund', { brief: 'x' }]]) {
    assert.deepEqual(jobs.repeat('caller-a', 'k-1', NOW, { capability, input }), { decision: 'conflict', job: jobs.get(first) });
  }
  assert.equal(jobs.repeat('caller-a', 'k-1', NOW).decision, 'same', 'without the intent: as before');
  jobs.quotaExhausted(first, 'budget', { retryable: false });
  assert.equal(jobs.repeat('caller-a', 'k-1', NOW, { limitHolds: false, capability: 'media.order', input: { brief: 'x' } }).decision, 'run');
  assert.equal(jobs.repeat('caller-a', 'k-1', NOW, { limitHolds: false, capability: 'media.order', input: { brief: 'y' } }).decision, 'conflict');
});

test('finding 9: a lone surrogate in a key or caller is refused with a sentence, as the Python kit refuses it', (t) => {
  const jobs = store(t);
  for (const [caller, key] of [['caller-a', '\ud800'], ['\udfff', 'k-1'], ['caller-a', 'a\udc00b']]) {
    assert.throws(() => jobs.create('media.order', { brief: 'x' }, { caller, idempotencyKey: key }), (e) => e instanceof k.InteropError && /lone surrogate/.test(e.message), JSON.stringify(key));
    assert.throws(() => jobs.repeat(caller, key, NOW), (e) => e instanceof k.InteropError && /lone surrogate/.test(e.message));
  }
  assert.equal(start(jobs, 'caller-a', 'k-\u{1f600}').startsWith('job_'), true, 'a well-formed pair is text');
  assert.throws(() => jobs.create('media.order', { brief: '\ud800' }, { caller: 'caller-a', idempotencyKey: 'k-9' }), /RFC 8785/);
});

test('finding 11: pause on a terminal job changes nothing', (t) => {
  const jobs = store(t);
  const id = start(jobs);
  jobs.cancel(id);
  const before = jobs.get(id);
  assert.throws(() => jobs.pause(id, { resetsAt: '2099-01-01T00:00:00Z' }), k.InteropError);
  assert.deepEqual(jobs.get(id), before);
});
