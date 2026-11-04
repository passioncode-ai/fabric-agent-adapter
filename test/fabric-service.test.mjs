import assert from 'node:assert/strict';
import { spawnSync, spawn } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';
import { tempDir } from './temp-dir.mjs';
import { abstractNames } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-lock.mjs';
// FAA-72: on Linux the lock needs a Node that binds an abstract socket name exactly (22 and later); Node 18 and 20
// refuse to hold it (fabric-lock.mjs), and lock-old-node-refuses.test.mjs holds that refusal.
const noLinuxLock = process.platform === 'linux' && (await abstractNames()) !== 'exact' && `Node ${process.version} cannot hold the Linux lock`;

const here = path.dirname(fileURLToPath(import.meta.url));
const scripts = path.join(here, '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts');
const temp = () => tempDir('fabric-kit-');
const descriptor = (port, id = 'sample', instance = 'default') => ({
  protocol: k.PROTOCOL, id, instance, name: 'Sample', origin: `http://127.0.0.1:${port}`,
  auth: { tokenFile: '/tmp/x/service.token' }, lifecycle: { manager: 'none' },
  paths: { data: '/tmp/x', logs: [] }, installedAt: k.nowIso(), installedBy: 'test', source: { repository: 'https://github.com/example-org/example-agent' },
});

test('second holder of the instance lock is refused with the pid', { skip: noLinuxLock }, async () => {
  const dir = temp();
  const first = await new k.InstanceLock(dir).acquire();
  await assert.rejects(new k.InstanceLock(dir).acquire(), (e) => e instanceof k.AlreadyRunning && e.holderPid === process.pid);
  first.release();
  (await new k.InstanceLock(dir).acquire()).release();
});

test('a failed pid write lets the instance lock go (a board finding of 2026-11-03)', { skip: noLinuxLock }, async () => {
  // The caller (holdSingleInstance) drops a lock whose acquire threw, so acquire itself must let the lock go.
  for (const call of ['ftruncateSync', 'writeSync', 'fsyncSync']) {
    const dir = temp();
    const original = fs[call];
    let thrown = false;
    fs[call] = (...args) => {
      if (thrown) return original(...args);
      thrown = true;
      throw Object.assign(new Error('No space left on device'), { code: 'ENOSPC' });
    };
    let lock = null;
    const attempt = new k.InstanceLock(dir);
    try {
      lock = await attempt.acquire();
    } catch (error) {
      assert.equal(error.code, 'ENOSPC', call);
      assert.equal(attempt.fd ?? null, null, `${call}: no descriptor kept`);
      assert.equal(attempt.server ?? null, null, `${call}: no name kept (Linux, Windows)`);
    } finally {
      fs[call] = original;
    }
    if (lock) lock.release(); // ftruncateSync off macOS: the pid goes through atomicWrite, which does not call it
    (await new k.InstanceLock(dir).acquire()).release();
  }
});

test('a close that fails too still lets the lock go, the first error standing (0.61.0 seam reading 7)', { skip: process.platform !== 'darwin' }, async () => {
  const dir = temp();
  const { fsyncSync, closeSync } = fs;
  let lock = null;
  fs.fsyncSync = () => { throw Object.assign(new Error('No space left on device'), { code: 'ENOSPC' }); };
  fs.closeSync = (fd) => { closeSync(fd); throw Object.assign(new Error('Input/output error'), { code: 'EIO' }); };
  try {
    lock = new k.InstanceLock(dir);
    await assert.rejects(lock.acquire(), (e) => e.code === 'ENOSPC');
  } finally {
    fs.fsyncSync = fsyncSync;
    fs.closeSync = closeSync;
  }
  assert.equal(lock.fd, null, 'no closed descriptor number is kept for a later release');
  lock.release();
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

test('a new install names its repository; a reinstall without it warns (FAA-198)', () => {
  const dir = temp();
  const { source, ...bare } = descriptor(47196);
  assert.ok(k.sourceRefusal(bare, dir));
  assert.throws(() => k.writeDescriptor(bare, dir), /sample\.default names no source\.repository/);
  assert.deepEqual(fs.readdirSync(dir), [], 'a refused install writes nothing');
  const seen = [];
  const emit = process.emitWarning;
  process.emitWarning = (message, options) => seen.push([message, options?.code]);
  try {
    k.writeDescriptor(descriptor(47196), dir);
    assert.deepEqual(seen, [], 'a descriptor that names its repository is written without a word');
    k.writeDescriptor(bare, dir);
  } finally {
    process.emitWarning = emit;
  }
  assert.equal(seen.length, 1);
  assert.match(seen[0][0], /names no source\.repository/);
  assert.equal(seen[0][1], 'FABRIC_NO_SOURCE_REPOSITORY');
  assert.equal(k.sourceRefusal(bare, dir), null, 'an installed descriptor is a rewrite');
  for (const empty of [{}, { repository: '' }, 'x', ['a'], 1, true]) assert.ok(k.sourceRefusal({ ...bare, id: 'other', source: empty }, dir), JSON.stringify(empty));
  fs.mkdirSync(path.join(dir, 'folder.default.json')); // a folder at the descriptor's path is no installed descriptor
  assert.ok(k.sourceRefusal({ ...bare, id: 'folder' }, dir));
  assert.equal(k.sourceRefusal({ ...bare, instance: null }, dir), null, 'a null instance reads as default, as in Python');
  assert.ok(k.sourceRefusal({ ...bare, id: 'other', source: null }, dir), 'a null source names nothing');
  const named = { ...descriptor(47188), source: { repository: 'https://github.com/example-org/task-pipeline-dashboard' } };
  assert.deepEqual(k.validateDescriptor(named), [], 'a repository name is no key (0.62.0 seam reading 6)');
  const keyed = { ...named, source: { repository: `https://github.com/example-org/r?token=sk-${'Fx9k'.repeat(5)}` } };
  assert.ok(k.validateDescriptor(keyed).some((p) => p.includes('FAC-SEM-086')), 'a key in the query still is');
  for (const scp of ['bot:fixture@github.com:example-org/r', 'https:fixture@github.com/example-org/r', 'x-access-token:fixture@github.com:example-org/r']) {
    assert.ok(k.validateDescriptor({ ...named, source: { repository: scp } }).some((p) => p.includes('never an scp form')), scp); // readings 7
  }
  const pathKey = { ...named, source: { repository: `https://github.com/example-org/ghp_${'Fx9k'.repeat(9)}` } };
  assert.ok(k.validateDescriptor(pathKey).some((p) => p.includes('FAC-SEM-086')), 'a path piece shaped like a key still is');
  assert.ok(k.sourceRefusal({ ...bare, instance: ['default'] }, dir), 'a list instance names no file');
  assert.ok(k.sourceRefusal({ ...bare, id: 'other', source: { repository: [] } }, dir));
  fs.symlinkSync(path.join(dir, 'missing.json'), path.join(dir, 'gone.default.json'));
  assert.ok(k.sourceRefusal({ ...bare, id: 'gone' }, dir), 'a broken link is none either');
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

test('holdSingleInstance exits 75 in a second process', { skip: noLinuxLock }, async () => {
  const dir = temp();
  const lock = await new k.InstanceLock(dir).acquire();
  const child = spawnSync(process.execPath, ['--input-type=module', '-e',
    `import * as k from ${JSON.stringify(pathToFileURL(path.join(scripts, 'fabric-service.mjs')).href)}; await k.holdSingleInstance(${JSON.stringify(dir)}); console.log('ran');`],
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

test('usageSpend answers as the contract (DEC-0110), and a limit counts money, never a subscription estimate (CT-115)', () => {
  const cases = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/usage-spend-vectors.json'), 'utf8')).cases;
  assert.ok(cases.length >= 40);
  for (const c of cases) assert.deepEqual(k.usageSpend(c.rows) ?? null, c.expected, c.name);
  const now = Date.parse('2026-10-04T12:00:00Z');
  const at = '2026-10-04T01:00:00Z';
  const sub = k.makeUsageReceipt('anthropic', 'm', { inputTokens: 1, outputTokens: 1, costUsd: 2, costBasis: 'price-list', at, route: 'subscription' });
  const key = k.makeUsageReceipt('openrouter', 'm', { inputTokens: 1, outputTokens: 1, costUsd: 0.5, costBasis: 'provider', at, route: 'key' });
  const local = k.makeUsageReceipt('local', 'llama', { inputTokens: 1, outputTokens: 1, at });
  const limits = [{ id: 'day', scope: 'machine', kind: 'spend', period: 'day', limitUsd: 5, enforced: false },
    { id: 'hour', scope: 'machine', kind: 'spend', windowSeconds: 86400, limitUsd: 5, enforced: false }];
  const spent = (receipts) => {
    const budget = k.usageReport(receipts, { id: 'example-agent', now, budget: { period: 'day', limitUsd: 5 } });
    const listed = k.usageReport(receipts, { id: 'example-agent', now, budgets: limits });
    return [[budget.budget.spentUsd, ...listed.budgets.map((b) => b.spentUsd)], budget];
  };
  const [got, r] = spent([sub, key]);
  assert.equal(r.days[0].costUsd, 2.5, "the day's costUsd still sums every route");
  assert.deepEqual(got, [0.5, 0.5, 0.5]);
  assert.deepEqual(spent([sub])[0], [0, 0, 0], 'only a subscription: no money spent');
  assert.deepEqual(spent([sub, local])[0], [null, null, null], 'an unpriced call off the subscription leaves money unknown');
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
