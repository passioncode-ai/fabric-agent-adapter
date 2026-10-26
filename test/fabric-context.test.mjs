// FAA-125 (organization row N-11): one instance per context, the Node kit (fabric-context.mjs); the twin of
// test_fabric_context.py over the same cases (test/fixtures/kit-context-cases.json). Brief: docs/evidence/specs/
// 2026-10-26-faa-128-125-repin-a3a66eb-brief.md (N-11 design, D14 to D20).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { INSTANCE, ServiceError } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-base.mjs';
import * as fc from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-context.mjs';
import { descriptorPath } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-descriptor.mjs';
import { placementGrantFindings } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-estate.mjs';
import { abstractNames, EXIT_ALREADY_RUNNING, InstanceLock } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-lock.mjs';
import { instanceDirs, serviceDirs } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-paths.mjs';
import { instanceShareGrant } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-share.mjs';
import { parseRfc3339Ms } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-time.mjs';
import { tempDir } from './temp-dir.mjs';

// FAA-72: on Linux the lock needs a Node that binds an abstract socket name exactly (22 and later); Node 18 and 20
// refuse to hold it (fabric-lock.mjs), and lock-old-node-refuses.test.mjs holds that refusal.
const noLinuxLock = process.platform === 'linux' && (await abstractNames()) !== 'exact' && `Node ${process.version} cannot hold the Linux lock`;

const here = path.dirname(fileURLToPath(import.meta.url));
const CASES = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/kit-context-cases.json'), 'utf8'));
const SERVICE = CASES.service;
const RECORD = CASES.record;
const A = 'urn:agent:example-agent';
const atSeconds = (text) => parseRfc3339Ms(text) / 1000;
const NO_SUPERVISOR = { env: {}, argv: [], waitSeconds: 0, exit: (code) => code };

/** HOME, the XDG roots and the services directory in a temporary folder; restored after the test. */
function tempHome(t) {
  const root = tempDir('fabric-context-');
  const home = path.join(root, 'home');
  fs.mkdirSync(home);
  const keys = ['HOME', 'USERPROFILE', 'LOCALAPPDATA', 'XDG_DATA_HOME', 'XDG_STATE_HOME', 'XDG_CACHE_HOME', 'FABRIC_SERVICES_DIR'];
  const saved = Object.fromEntries(keys.map((key) => [key, process.env[key]]));
  t.after(() => { for (const [key, value] of Object.entries(saved)) { if (value === undefined) delete process.env[key]; else process.env[key] = value; } });
  Object.assign(process.env, { HOME: home, USERPROFILE: home, LOCALAPPDATA: path.join(home, 'AppData', 'Local'), XDG_DATA_HOME: '', XDG_STATE_HOME: '', XDG_CACHE_HOME: '', FABRIC_SERVICES_DIR: path.join(root, 'services') });
  const created = () => fs.readdirSync(root, { recursive: true }).map(String).sort();
  return { root, home, created };
}

/** Run holdContextInstance with stderr captured; an injected exit answers its code. */
async function hold(context, options = {}) {
  const write = process.stderr.write;
  let err = '';
  process.stderr.write = (chunk) => { err += chunk; return true; };
  try {
    const result = await fc.holdContextInstance(SERVICE, context, { ...NO_SUPERVISOR, ...options });
    return typeof result === 'number' ? { code: result, err } : { held: result, err };
  } finally {
    process.stderr.write = write;
  }
}

test('the constants', () => {
  assert.equal(fc.EXIT_CONTEXT_REFUSED, 78);
  assert.equal(fc.CONTEXT_MARKER, 'fabric-context.json');
});

test('every name, each a descriptor instance', () => {
  for (const [context, expected] of CASES.names) {
    const name = fc.contextInstanceName(context);
    assert.equal(name, expected, context.slice(0, 40));
    assert.match(name, INSTANCE);
  }
  assert.equal(fc.contextInstanceName('personal', { personalInstance: 'main' }), 'main');
  assert.equal(fc.contextInstanceName('org:acme', { personalInstance: 'main' }), 'org-acme');
});

test('a context that is none is refused', () => {
  for (const value of ['Personal', 'ORG:x', 'org:', 'org:-x', 'personal\n', 5, null, undefined]) {
    assert.throws(() => fc.contextInstanceName(value), (error) => error instanceof fc.ContextRefused && error instanceof ServiceError && error.code === 'context-invalid', String(value));
  }
});

test('every case answers as the Python kit does, and creates nothing', (t) => {
  const { created } = tempHome(t);
  for (const c of CASES.cases) {
    const answer = () => fc.contextInstance(SERVICE, c.context, {
      record: c.record ? RECORD : undefined, machineId: c.machine ?? undefined, agentRef: c.agentRef ?? undefined,
      at: atSeconds(c.at), personalInstance: c.personalInstance ?? 'default',
    });
    if (c.refused) {
      assert.throws(answer, (error) => error instanceof fc.ContextRefused && error.code === c.refused, c.name);
      continue;
    }
    const info = answer();
    assert.equal(info.instance, c.instance, c.name);
    assert.equal(info.kind, c.kind, c.name);
    assert.equal(info.context, c.context, c.name);
    assert.equal(info.key, `${SERVICE}.${c.instance}`, c.name);
    assert.deepEqual(info.grant, c.grant, c.name);
    assert.deepEqual(info.dirs, instanceDirs(SERVICE, c.instance), c.name);
    assert.equal(info.descriptorPath, descriptorPath(SERVICE, c.instance), c.name);
    if (c.kind === 'org') assert.equal(info.org, c.context.slice(4), c.name);
    assert.ok(!JSON.stringify(info).includes('machines'), 'the answer never carries the record');
  }
  assert.deepEqual(created(), ['home'], 'contextInstance is pure: no folder, file or lock');
});

test('the clock defaults to now; an unreadable clock is outside every window', (t) => {
  tempHome(t);
  assert.equal(fc.contextInstance(SERVICE, 'org:open-ended', { record: RECORD, machineId: 'machine-a', agentRef: A }).instance, 'org-open-ended');
  assert.throws(() => fc.contextInstance(SERVICE, 'org:acme-rehearsal', { record: RECORD, machineId: 'machine-a', agentRef: A, at: 'not a clock' }),
    (error) => error.code === 'grant-window');
});

test('the personal instance keeps the service folders; an organization gets siblings named as its descriptor', (t) => {
  const { home } = tempHome(t);
  const name = `${SERVICE}.org-acme-rehearsal`;
  const local = path.join(home, 'AppData', 'Local');
  const expected = {
    darwin: { data: path.join(home, 'Library/Application Support', name), logs: path.join(home, 'Library/Logs', name), cache: path.join(home, 'Library/Caches', name) },
    linux: { data: path.join(home, '.local/share', name), logs: path.join(home, '.local/state', name, 'logs'), cache: path.join(home, '.cache', name) },
    win32: { data: path.join(local, name), logs: path.join(local, name, 'Logs'), cache: path.join(local, name, 'Cache') },
  };
  for (const [platform, dirs] of Object.entries(expected)) {
    assert.deepEqual(instanceDirs(SERVICE, 'default', platform), serviceDirs(SERVICE, platform), platform);
    assert.deepEqual(instanceDirs(SERVICE, undefined, platform), serviceDirs(SERVICE, platform), platform);
    const got = instanceDirs(SERVICE, 'org-acme-rehearsal', platform);
    assert.deepEqual(got, dirs, platform);
    const personal = serviceDirs(SERVICE, platform);
    for (const key of Object.keys(got)) assert.ok(!got[key].startsWith(personal[key] + path.sep) && got[key] !== personal[key], 'never inside the personal tree');
  }
  for (const bad of ['Org', '', 'a'.repeat(33), '../x', 'default.x']) assert.throws(() => instanceDirs(SERVICE, bad), ServiceError, bad);
  assert.throws(() => instanceDirs('Bad Id', 'default'), ServiceError);
});

test('the personal instance holds the service lock and marks its folder', { skip: noLinuxLock }, async (t) => {
  tempHome(t);
  const { held, code } = await hold('personal');
  assert.equal(code, undefined);
  t.after(() => held.lock.release());
  const data = serviceDirs(SERVICE).data;
  assert.equal(held.lock.path, path.join(data, 'service.lock'), 'an existing install keeps its lock (D15)');
  const marker = path.join(data, 'fabric-context.json');
  assert.deepEqual(JSON.parse(fs.readFileSync(marker, 'utf8')), { service: SERVICE, instance: 'default', context: 'personal' });
  if (process.platform !== 'win32') assert.equal(fs.statSync(marker).mode & 0o777, 0o600);
  assert.equal(held.instance, 'default');
});

test('a second copy for the same context exits 75', { skip: noLinuxLock }, async (t) => {
  tempHome(t);
  const first = await hold('personal');
  t.after(() => first.held.lock.release());
  const second = await hold('personal');
  assert.equal(second.code, EXIT_ALREADY_RUNNING);
  assert.match(second.err, /already running/);
});

test('two contexts run side by side', { skip: noLinuxLock }, async (t) => {
  tempHome(t);
  const personal = await hold('personal');
  t.after(() => personal.held.lock.release());
  const org = await hold('org:acme-rehearsal', { record: RECORD, machineId: 'machine-a', agentRef: A, at: atSeconds('2026-10-26T12:00:00Z') });
  assert.equal(org.code, undefined, org.err);
  t.after(() => org.held.lock.release());
  assert.notEqual(org.held.lock.path, personal.held.lock.path);
  assert.equal(org.held.lock.path, path.join(instanceDirs(SERVICE, 'org-acme-rehearsal').data, 'service.lock'));
  assert.equal(JSON.parse(fs.readFileSync(path.join(path.dirname(org.held.lock.path), 'fabric-context.json'), 'utf8')).context, 'org:acme-rehearsal');
});

test('a refusal exits 78 with one sentence and creates nothing', async (t) => {
  const { created } = tempHome(t);
  const cases = [
    ['org:acme-rehearsal', {}, 'record-required'],
    ['org:revoked-org', { record: RECORD, machineId: 'machine-a', agentRef: A }, 'grant-refused'],
    ['org:window-org', { record: RECORD, machineId: 'machine-a', agentRef: A, at: atSeconds('2026-10-26T12:00:00Z') }, 'grant-window'],
    ['Personal', {}, 'context-invalid'],
  ];
  for (const [context, options, refused] of cases) {
    const { code, err } = await hold(context, options);
    assert.equal(code, 78, refused);
    assert.ok(err.includes(refused), err);
    assert.equal(err.trim().split('\n').length, 1, 'one sentence');
    assert.ok(!err.includes('urn:fabric:share') && !err.includes('machine-a'), 'never a record or grant value');
  }
  assert.deepEqual(created(), ['home'], 'nothing created before a refusal');
});

test('a folder never changes context; the lock is released before the exit', { skip: noLinuxLock }, async (t) => {
  tempHome(t);
  const data = serviceDirs(SERVICE).data;
  fs.mkdirSync(data, { recursive: true });
  fs.writeFileSync(path.join(data, 'fabric-context.json'), JSON.stringify({ service: SERVICE, instance: 'default', context: 'org:other' }));
  const { code, err } = await hold('personal');
  assert.equal(code, 78);
  assert.match(err, /context-mismatch/);
  (await new InstanceLock(data).acquire()).release();
  fs.writeFileSync(path.join(data, 'fabric-context.json'), 'not json');
  const unreadable = await hold('personal');
  assert.equal(unreadable.code, 78);
  assert.match(unreadable.err, /context-mismatch/);
});

test('an equal marker is kept', { skip: noLinuxLock }, async (t) => {
  tempHome(t);
  const first = await hold('personal');
  const marker = path.join(path.dirname(first.held.lock.path), 'fabric-context.json');
  const before = [fs.readFileSync(marker, 'utf8'), fs.statSync(marker).mtimeMs];
  first.held.lock.release();
  const again = await hold('personal');
  t.after(() => again.held.lock.release());
  assert.equal(again.code, undefined);
  assert.deepEqual([fs.readFileSync(marker, 'utf8'), fs.statSync(marker).mtimeMs], before);
});

test('instanceShareGrant answers and never throws; placementGrantFindings is public', () => {
  const at = parseRfc3339Ms('2026-10-26T12:00:00Z');
  for (const record of [undefined, null, [], { machines: 'x' }, { machines: [{ id: 'machine-a', packages: [null, 3] }] }]) {
    assert.equal(instanceShareGrant(record, 'machine-a', A, 'org:acme-rehearsal', at).code, 'placement-missing');
  }
  assert.deepEqual(instanceShareGrant(RECORD, 'machine-a', A, 'org:acme-rehearsal', at),
    { ok: true, grant: { id: `urn:fabric:share:${'1'.repeat(32)}`, startsAt: '2026-10-01T00:00:00Z', expiresAt: '2026-12-01T00:00:00Z' } });
  const revoked = instanceShareGrant(RECORD, 'machine-a', A, 'org:revoked-org', at);
  assert.equal(revoked.code, 'grant-refused');
  assert.match(revoked.detail, /revokes/);
  const findings = placementGrantFindings(RECORD, { agentRef: A, context: 'org:revoked-org', grant: `urn:fabric:share:${'3'.repeat(32)}` });
  assert.deepEqual(findings.map((f) => [f.code, f.instancePath]), [['FAC-SEM-111', '/grant']]);
  assert.deepEqual(placementGrantFindings(RECORD, { agentRef: A }), []);
  assert.deepEqual(placementGrantFindings(null, null), [], 'answers, never throws');
});
