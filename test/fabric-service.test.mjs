import assert from 'node:assert/strict';
import { spawnSync, spawn } from 'node:child_process';
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
  k.writeDescriptor(descriptor(8791, 'asset-foundry', 'preview'), dir);
  assert.throws(() => k.writeDescriptor(descriptor(8791, 'copylot'), dir), /8791.*asset-foundry\.preview/);
  const file = k.writeDescriptor(descriptor(8795), dir);
  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
});

test('invalid descriptors are refused', () => {
  const bad = { ...descriptor(8766), origin: 'http://0.0.0.0:8766', commands: { doctor: 'brandctl check' } };
  const problems = k.validateDescriptor(bad);
  assert.ok(problems.some((p) => p.includes('origin')));
  assert.ok(problems.some((p) => p.includes('argument array')));
});

test('token file must be private and tokens compare by scheme', () => {
  const file = path.join(temp(), 'service.token');
  const token = k.ensureToken(file);
  assert.equal(k.readToken(file), token);
  fs.chmodSync(file, 0o644);
  assert.throws(() => k.readToken(file), /readable by others/);
  assert.ok(k.tokenMatches(`Bearer ${token}`, token));
  assert.ok(!k.tokenMatches(token, token));
  assert.ok(k.tokenMatches(token, token, 'none'));
});

test('request guard', () => {
  assert.equal(k.checkRequest(8710, '127.0.0.1:8710'), null);
  assert.ok(k.checkRequest(8710, 'evil.example'));
  assert.ok(k.checkRequest(8710, '127.0.0.1:8710', 'http://evil.example'));
  assert.ok(k.checkRequest(8710, '127.0.0.1:8710', undefined, 'cross-site'));
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
