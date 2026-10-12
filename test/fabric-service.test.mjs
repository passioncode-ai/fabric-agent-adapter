import assert from 'node:assert/strict';
import { spawnSync, spawn } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const scripts = path.join(here, '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts');
const temp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-kit-'));
const descriptor = (port, id = 'sample', instance = 'default') => ({
  protocol: k.PROTOCOL, id, instance, name: 'Sample', origin: `http://127.0.0.1:${port}`,
  auth: { tokenFile: '/tmp/x/service.token' }, lifecycle: { manager: 'none' },
  paths: { data: '/tmp/x', logs: [] }, installedAt: k.nowIso(), installedBy: 'test',
});

test('second holder of the instance lock is refused with the pid', async () => {
  const dir = temp();
  const first = await new k.InstanceLock(dir).acquire();
  await assert.rejects(new k.InstanceLock(dir).acquire(), (e) => e instanceof k.AlreadyRunning && e.holderPid === process.pid);
  first.release();
  (await new k.InstanceLock(dir).acquire()).release();
});

test('the Node lock and the Python lock exclude each other', { skip: process.platform !== 'darwin' }, async () => {
  const dir = temp();
  const lock = await new k.InstanceLock(dir).acquire();
  const py = spawnSync('python3', ['-c', `
import sys; sys.path.insert(0, ${JSON.stringify(scripts)})
import fabric_service as fs
try:
    fs.InstanceLock(${JSON.stringify(dir)}).acquire(); print("acquired")
except fs.AlreadyRunning as e:
    print("refused", e.holder_pid)`], { encoding: 'utf8' });
  assert.equal(py.stdout.trim(), `refused ${process.pid}`);
  lock.release();
});

test('a port is a claim', () => {
  const dir = temp();
  k.writeDescriptor(descriptor(47191, 'maker', 'preview'), dir);
  assert.throws(() => k.writeDescriptor(descriptor(47191, 'writer'), dir), /47191.*maker\.preview/);
  const file = k.writeDescriptor(descriptor(47195), dir);
  // On Windows the privacy is the file's ACL, not a mode (fabric-service-platforms.test.mjs checks it).
  if (process.platform !== 'win32') assert.equal(fs.statSync(file).mode & 0o777, 0o600);
});

test('invalid descriptors are refused', () => {
  const bad = { ...descriptor(47166), origin: 'http://0.0.0.0:47166', commands: { doctor: 'brandctl check' } };
  const problems = k.validateDescriptor(bad);
  assert.ok(problems.some((p) => p.includes('origin')));
  assert.ok(problems.some((p) => p.includes('argument array')));
});

test('token file must be private and tokens compare by scheme', () => {
  const file = path.join(temp(), 'service.token');
  const token = k.ensureToken(file);
  assert.equal(k.readToken(file), token);
  if (process.platform !== 'win32') { // Windows: a grant to everyone, refused by SID, in fabric-service-platforms.test.mjs
    fs.chmodSync(file, 0o644);
    assert.throws(() => k.readToken(file), /readable by others/);
  }
  assert.ok(k.tokenMatches(`Bearer ${token}`, token));
  assert.ok(!k.tokenMatches(token, token));
  assert.ok(k.tokenMatches(token, token, 'none'));
});

test('request guard', () => {
  assert.equal(k.checkRequest(47110, '127.0.0.1:47110'), null);
  assert.ok(k.checkRequest(47110, 'evil.example'));
  assert.ok(k.checkRequest(47110, '127.0.0.1:47110', 'http://evil.example'));
  assert.ok(k.checkRequest(47110, '127.0.0.1:47110', undefined, 'cross-site'));
});

test('login codes are single use across a restart and revocable', () => {
  const dir = temp();
  const codes = new k.LoginCodes(dir);
  const code = codes.issue().url.split('code=')[1];
  const session = codes.redeem(code);
  assert.ok(codes.sessionValid(session));
  assert.equal(new k.LoginCodes(dir).redeem(code), null);
  codes.revokeAll();
  assert.ok(!codes.sessionValid(session));
});

test('operator sessions follow DEC-0039: idle, absolute, logout, rotation, clamping, forgery', () => {
  const HOUR = 3600;
  const now = [1_800_000_000];
  const token = ['t'.repeat(43)];
  const dir = temp();
  const make = (extra = {}) => new k.LoginCodes(dir, 120, { token: () => token[0], clock: () => now[0], ...extra });
  const signIn = (codes) => codes.redeem(codes.issue().url.split('code=')[1]);

  let codes = make();
  let session = signIn(codes);
  now[0] += 11 * HOUR; assert.ok(codes.sessionValid(session));
  now[0] += 11 * HOUR; assert.ok(codes.sessionValid(session), 'use refreshes the 12 hours');
  now[0] += 12 * HOUR + 1; assert.ok(!codes.sessionValid(session), 'idle bound');

  const t0 = now[0];
  session = signIn(codes);
  for (let i = 0; i < 14; i += 1) { now[0] += 12 * HOUR - 60; assert.ok(codes.sessionValid(session)); }
  now[0] = t0 + 7 * 24 * HOUR; assert.ok(!codes.sessionValid(session), 'absolute bound');

  session = signIn(codes);
  assert.equal(codes.logout(session), true);
  assert.ok(!codes.sessionValid(session) && !make().sessionValid(session), 'logout ends every copy');
  assert.equal(codes.logout(session), false);
  assert.equal(codes.logout('junk'), false);

  session = signIn(codes);
  token[0] = 'u'.repeat(43);
  assert.ok(!codes.sessionValid(session), 'token rotation');
  assert.ok(codes.sessionValid(signIn(codes)));
  assert.ok(!session.includes('t'.repeat(43)));

  const bare = new k.LoginCodes(path.join(dir, 'bare'), 120, { clock: () => now[0] });
  assert.ok(bare.sessionValid(signIn(bare)), 'no token still works');
  const short = make({ idleSeconds: 60, maxSeconds: 600 });
  session = signIn(short); now[0] += 61; assert.ok(!short.sessionValid(session));
  const long = make({ idleSeconds: 1e9, maxSeconds: 1e9 });
  assert.deepEqual([long.idleSeconds, long.maxSeconds], [12 * HOUR, 7 * 24 * HOUR]);

  session = signIn(codes);
  const parts = session.split('.');
  const flipped = parts.slice(0, 4).join('.') + '.' + (parts[4][0] === '0' ? '1' : '0') + parts[4].slice(1);
  assert.ok(!codes.sessionValid(flipped), 'forged mac');
  assert.ok(!codes.sessionValid([...parts.slice(0, 2), String(Number(parts[2]) + 7 * 24 * HOUR), ...parts.slice(3)].join('.')));
  const legacy = `abc.${crypto.createHmac('sha256', codes.key()).update('abc').digest('hex')}`;
  assert.ok(!codes.sessionValid(legacy), 'old-format cookie');
  for (const bad of [null, '', 'v2', 'v2.a.b.c.d', `v2.a.x.c.${'0'.repeat(64)}`]) assert.ok(!codes.sessionValid(bad));
  fs.unlinkSync(path.join(dir, 'login-codes.json'));
  assert.ok(!codes.sessionValid(session), 'no server record');

  session = signIn(codes);
  const store = path.join(dir, 'login-codes.json');
  const before = fs.readFileSync(store, 'utf8');
  now[0] += 30; assert.ok(codes.sessionValid(session)); assert.equal(fs.readFileSync(store, 'utf8'), before, 'no write within a minute');
  now[0] += 31; assert.ok(codes.sessionValid(session)); assert.notEqual(fs.readFileSync(store, 'utf8'), before);

  now[0] += 7 * 24 * HOUR + 2 * HOUR; signIn(codes);
  assert.equal(Object.keys(JSON.parse(fs.readFileSync(store, 'utf8'))).filter((key) => key.startsWith('s:')).length, 1, 'records pruned');

  for (const bad of [`v2.x.1.y.${'\u00e9'.repeat(64)}`, `v2.\u00e9.1.-.${'0'.repeat(64)}`, `v2.x.1.\u00e9.${'0'.repeat(64)}`]) {
    assert.equal(codes.sessionValid(bad), false, 'review S2: a non-ASCII cookie is refused, never thrown');
    assert.equal(codes.logout(bad), false);
  }
  for (const bound of [{ idleSeconds: NaN }, { maxSeconds: Infinity }, { idleSeconds: '12h' }]) {
    assert.throws(() => make(bound), /finite number/, 'review S4: a bound must be a finite number');
  }
  session = signIn(codes);
  const records = JSON.parse(fs.readFileSync(store, 'utf8'));
  for (const record of Object.values(records)) if (record.signedInAt !== undefined) record.loggedOutAt = null;
  fs.writeFileSync(store, JSON.stringify(records));
  assert.ok(codes.sessionValid(session), 'review P1: loggedOutAt null is not a logout, as in Python');
  assert.ok(k.sessionCookieHeader('v').includes('Max-Age=604800'));
  assert.ok(k.remoteSessionCookieHeader('v').includes('Max-Age=604800'));
  assert.match(k.expiredSessionCookieHeader(), /^fabric_session=; .*Max-Age=0/);
  assert.match(k.expiredSessionCookieHeader(true), /^__Host-fabric_session=; .*Secure.*Max-Age=0/);
});

test('well-known and events follow the rules', async () => {
  const wk = k.buildWellKnown({ id: 'sample', instance: 'default', name: 'S', version: '0.1.0', build: { commit: 'abcdef1' },
    startedAt: k.nowIso(), status: 'ready', degraded: [{ source: 'llm', reason: 'no key' }], surfaces: { events: { path: '/fabric/v1/events' } } });
  assert.equal(wk.status, 'degraded');
  assert.throws(() => k.makeEvent(1, k.nowIso(), 'job.failed', 'critical', 'It failed.'));
  assert.throws(() => k.makeEvent(1, k.nowIso(), 'job.failed', 'error', 'It failed.', { link: 'https://evil.example' }));
  const rows = [1, 2, 3].map((n) => k.makeEvent(n, k.nowIso(), 'demo.note', 'info', `Note ${n}.`));
  const fetch = async (after, limit) => (after === null ? rows.slice(-limit) : rows.filter((r) => Number(r.id) > Number(after)).slice(0, limit));
  assert.deepEqual((await k.eventsPage(fetch, '1', 10)).events.map((e) => e.id), ['2', '3']);
  assert.deepEqual(await k.eventsPage(fetch, '3', 10), { events: [], cursor: '3' });
  assert.equal(k.parseLimit('999'), k.EVENTS_MAX_LIMIT);
});

test('holdSingleInstance exits 75 in a second process', async () => {
  const dir = temp();
  const lock = await new k.InstanceLock(dir).acquire();
  const child = spawnSync(process.execPath, ['--input-type=module', '-e',
    `import * as k from ${JSON.stringify(path.join(scripts, 'fabric-service.mjs'))}; await k.holdSingleInstance(${JSON.stringify(dir)}); console.log('ran');`],
  { encoding: 'utf8' });
  assert.equal(child.status, 75);
  assert.match(child.stderr, new RegExp(String(process.pid)));
  assert.doesNotMatch(child.stdout, /ran/);
  lock.release();
});

// DEC-0021: the Node twin builds the same usage report as fabric_service.py from the same receipts.
const usageCase = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/usage/receipts.json'), 'utf8'));

test('usage report: days, models, sums and unknown cost as null — same numbers as the Python kit', () => {
  const now = Date.parse(usageCase.now);
  const r = k.usageReport(usageCase.receipts, { id: 'example-agent', now, budget: { period: 'month', limitUsd: 100 } });
  assert.deepEqual(r.days.map((d) => d.date), usageCase.expect.days);
  const [d0, d1] = r.days;
  assert.equal(d0.calls, usageCase.expect.day0.calls);
  assert.ok(Math.abs(d0.costUsd - usageCase.expect.day0.costUsd) < 1e-6);
  assert.equal(d0.byModel[0].costBasis, 'mixed');
  assert.equal(d1.unpricedCalls, 1);
  assert.equal(d1.byModel.find((m) => m.provider === 'local').costUsd, null, 'unknown is null, never 0');
  for (const day of r.days) for (const f of ['calls', 'unpricedCalls', 'inputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens']) {
    assert.equal(day[f], day.byModel.reduce((n, m) => n + m[f], 0), f);
  }
  assert.ok(Math.abs(r.budget.spentUsd - usageCase.expect.budgetMonthSpent) < 1e-6);
  assert.throws(() => k.usageReport([], { id: 'example-agent', budget: { period: 'week', limitUsd: 1 } }), k.ServiceError);
});

test('usage receipt refuses what the report cannot carry; the ledger is private, bounded and survives a torn line', () => {
  assert.throws(() => k.makeUsageReceipt('Anthropic', 'm', { inputTokens: 1, outputTokens: 1 }), k.ServiceError);
  assert.throws(() => k.makeUsageReceipt('anthropic', 'm', { inputTokens: 1, outputTokens: 1, costUsd: 0.1, costBasis: 'unknown' }), k.ServiceError);
  assert.throws(() => k.makeUsageReceipt('anthropic', 'm', { inputTokens: 1, outputTokens: 1, costBasis: 'provider' }), k.ServiceError);
  assert.equal(k.makeUsageReceipt('anthropic', 'm', { inputTokens: 1, outputTokens: 1 }).costBasis, 'unknown');
  const dir = temp();
  const ledger = new k.JsonlUsageLedger(path.join(dir, 'usage', 'usage.jsonl'));
  for (const r of usageCase.receipts) ledger.record(r);
  if (process.platform !== 'win32') assert.equal(fs.statSync(ledger.file).mode & 0o777, 0o600);
  fs.appendFileSync(ledger.file, '{"torn":');
  ledger.record(usageCase.receipts[3]);
  assert.equal(ledger.receipts().length, 6, 'a receipt written after a torn line is not glued to it');
  assert.equal(ledger.prune(Date.parse(usageCase.now)), 1);
  assert.equal(ledger.receipts().length, 5);
  assert.ok(!fs.readFileSync(ledger.file, 'utf8').includes('torn'));
});
