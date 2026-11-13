// FAA-324: fabric-tailnet-identity.mjs on the vectors fabric_tailnet_identity.py answers too.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, renameSync, mkdtempSync, mkdirSync, rmSync, chmodSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import http from 'node:http';
import * as ti from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-tailnet-identity.mjs';
import { loopbackServer } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-descriptor.mjs';

const FIXTURE = JSON.parse(readFileSync(new URL('./fixtures/tailnet-identity/vectors.json', import.meta.url), 'utf8'));
const SCHEMA = JSON.parse(readFileSync(new URL(
  '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/tailnet-groups.schema.json', import.meta.url), 'utf8'));
const L = 'Tailscale-User-Login';
const clone = (v) => JSON.parse(JSON.stringify(v));

const groupsFor = (v) => (v.groupsProblem ? new ti.GroupsError(v.groupsProblem, 'test') : ti.loadGroups(FIXTURE.groups));

test('the groups file normalizes', () => {
  assert.deepEqual(ti.loadGroups(FIXTURE.groups), { schema: 'tailnet-groups/1', ...FIXTURE.normalized });
});

test('the base\'s door-groups/1 file is read for one service', () => {
  const dg = FIXTURE.doorGroups;
  assert.deepEqual(ti.loadGroups(dg.doc, { service: dg.service }), { schema: 'door-groups/1', ...dg.normalized });
  const groups = ti.loadGroups(dg.doc, { service: dg.service });
  for (const v of dg.vectors) {
    const got = ti.decide({ groups, bound: '127.0.0.1', peer: '127.0.0.1', headers: [[L, v.login]], door: v.door,
      capability: v.capability });
    assert.equal(got.code, v.code, v.name);
  }
  for (const c of FIXTURE.badDoorGroups) {
    assert.throws(() => ti.loadGroups(c.doc, { service: c.service ?? undefined }),
      (err) => err instanceof ti.GroupsError && err.code === 'groups-invalid' && err.where === c.where, c.name);
  }
});

test('the service reads the base\'s file through TailnetIdentity', () => {
  const dg = FIXTURE.doorGroups;
  const dir = mkdtempSync(join(tmpdir(), 'door-groups-'));
  try {
    const path = join(dir, 'door-groups.json');
    writeFileSync(path, JSON.stringify(dg.doc));
    const ask = (identity) => identity.decide({ bound: '127.0.0.1', peer: '127.0.0.1', headers: [[L, 'dee@example.org']],
      door: 'mcp', capability: 'cve.scan' }).code;
    assert.equal(ask(new ti.TailnetIdentity(path, { service: dg.service, log: () => {} })), 'ok');
    assert.equal(ask(new ti.TailnetIdentity(path, { log: () => {} })), 'groups-invalid');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('every vector', () => {
  for (const v of FIXTURE.vectors) {
    const got = ti.decide({ groups: groupsFor(v), bound: v.bound, peer: v.peer, headers: v.headers, door: v.door,
      capability: v.capability });
    const e = v.expect;
    assert.equal(got.code, e.code, v.name);
    assert.equal(got.status, e.status, v.name);
    assert.equal(got.allowed, e.code === 'ok', v.name);
    assert.equal(got.login, e.login, v.name);
    assert.equal(got.name, e.name, v.name);
    assert.deepEqual(got.groups, e.groups, v.name);
    assert.equal(got.reason, FIXTURE.reasons[e.code], v.name);
    assert.deepEqual([got.door, got.capability], [v.door, v.capability], v.name);
  }
});

test('every refusal code is exercised and has its sentence', () => {
  const codes = new Set(FIXTURE.vectors.map((v) => v.expect.code).filter((c) => c !== 'ok'));
  assert.deepEqual([...codes].sort(), Object.keys(ti.REFUSALS).sort());
  assert.deepEqual(ti.REASONS, FIXTURE.reasons);
  assert.ok(Object.values(ti.REFUSALS).every((s) => s === 403));
});

test('bad groups files are invalid and name the field; good ones load', () => {
  for (const c of FIXTURE.badGroups) {
    assert.throws(() => ti.loadGroups(c.doc),
      (e) => e instanceof ti.GroupsError && e.code === 'groups-invalid' && e.where === c.where, c.name);
  }
  for (const c of FIXTURE.goodGroups) ti.loadGroups(c.doc);
});

test('the door and capability are the service\'s own arguments', () => {
  const groups = ti.loadGroups(FIXTURE.groups);
  assert.throws(() => ti.decide({ groups, bound: '127.0.0.1', peer: '127.0.0.1', headers: [], door: 'a2a',
    capability: 'x' }), TypeError);
  for (const capability of ['', '*', 'Scan Now', null]) {
    assert.throws(() => ti.decide({ groups, bound: '127.0.0.1', peer: '127.0.0.1', headers: [], door: 'mcp',
      capability }), TypeError);
  }
});

test('headers as an object with arrays, a web Headers, and nothing but login and name in an answer', () => {
  const groups = ti.loadGroups(FIXTURE.groups);
  const ask = (headers) => ti.decide({ groups, bound: '127.0.0.1', peer: '127.0.0.1', headers, door: 'dashboard',
    capability: 'vitals' });
  assert.equal(ask({ 'tailscale-user-login': 'ana@example.com' }).code, 'ok');
  assert.equal(ask({ [L]: ['ana@example.com', 'bo@example.com'] }).code, 'login-ambiguous');
  assert.equal(ask(new Headers({ [L]: 'ana@example.com' })).code, 'ok');
  const got = ask([[L, 'ana@example.com'], ['Authorization', 'Bearer example-secret'],
    ['Tailscale-User-Profile-Pic', 'https://example.com/p.png']]);
  assert.ok(!JSON.stringify(got).includes('example-secret'));
  assert.ok(!JSON.stringify(got).includes('p.png'));
});

function reloadFixture() {
  const dir = mkdtempSync(join(tmpdir(), 'faa324-'));
  const path = join(dir, 'groups.json');
  const lines = [];
  const now = { t: 0 };
  const identity = (opts = {}) => new ti.TailnetIdentity(path, { log: (l) => lines.push(l), clock: () => now.t, ...opts });
  const write = (doc) => {
    writeFileSync(`${path}.tmp`, typeof doc === 'string' ? doc : JSON.stringify(doc));
    renameSync(`${path}.tmp`, path);
  };
  const ask = (id, login = 'ana@example.com') => id.decide({ bound: '127.0.0.1', peer: '127.0.0.1',
    headers: [[L, login]], door: 'dashboard', capability: 'vitals' }).code;
  return { dir, path, lines, now, identity, write, ask, done: () => rmSync(dir, { recursive: true, force: true }) };
}

test('a missing file closes every door and logs once', () => {
  const f = reloadFixture();
  try {
    const id = f.identity();
    assert.equal(f.ask(id), 'groups-unreadable');
    assert.equal(f.ask(id), 'groups-unreadable');
    assert.equal(f.lines.length, 1);
    assert.match(f.lines[0], /groups-unreadable/);
  } finally { f.done(); }
});

test('the file is read again on change without a restart', () => {
  const f = reloadFixture();
  try {
    const id = f.identity();
    f.write(FIXTURE.groups);
    assert.equal(f.ask(id), 'ok');
    const changed = clone(FIXTURE.groups);
    changed.groups.ops = ['bo@example.com'];
    f.write(changed);
    assert.equal(f.ask(id), 'unknown-login');
    assert.equal(f.ask(id, 'bo@example.com'), 'ok');
    assert.equal(f.lines.filter((l) => l.includes('loaded')).length, 2);
  } finally { f.done(); }
});

test('an in-place rewrite is seen', () => {
  const f = reloadFixture();
  try {
    const id = f.identity();
    writeFileSync(f.path, JSON.stringify(FIXTURE.groups));
    assert.equal(f.ask(id), 'ok');
    const changed = clone(FIXTURE.groups);
    changed.groups.ops = ['bo@example.com', 'zed@example.com'];
    writeFileSync(f.path, JSON.stringify(changed));
    assert.equal(f.ask(id), 'unknown-login');
  } finally { f.done(); }
});

test('an invalid file closes every door and its content is never logged', () => {
  const f = reloadFixture();
  try {
    const id = f.identity();
    f.write(FIXTURE.groups);
    assert.equal(f.ask(id), 'ok');
    f.write('{"schema": "tailnet-groups/1", "groups": {"ops": ["secret-login@example.com"]}, ');
    for (let i = 0; i < 3; i += 1) assert.equal(f.ask(id), 'groups-invalid');
    assert.equal(f.lines.filter((l) => l.includes('groups-invalid')).length, 1);
    assert.ok(!f.lines.join('\n').includes('secret-login'));
    f.write({ schema: 'tailnet-groups/1', groups: { ops: ['ana'] }, rules: [] });
    assert.equal(f.ask(id), 'groups-invalid');
    assert.match(f.lines.at(-1), /groups\.ops/);
    f.write(FIXTURE.groups);
    assert.equal(f.ask(id), 'ok');
  } finally { f.done(); }
});

test('bad encoding and an oversized file are invalid; a folder is unreadable', () => {
  const f = reloadFixture();
  try {
    const id = f.identity();
    writeFileSync(f.path, Buffer.from('{"schema": "tailnet-groups/1", "about": "\xff", "groups": {}, "rules": []}', 'latin1'));
    assert.equal(f.ask(id), 'groups-invalid');
    const text = JSON.stringify(FIXTURE.groups);
    f.write(text + ' '.repeat(ti.MAX_GROUPS_BYTES + 1 - text.length));
    assert.equal(f.ask(id), 'groups-invalid');
    assert.match(f.lines.at(-1), /size/);
    rmSync(f.path);
    mkdirSync(f.path);
    assert.equal(f.ask(id), 'groups-unreadable');
  } finally { f.done(); }
});

test('a file this account cannot read is unreadable', {
  skip: process.platform === 'win32' || process.getuid?.() === 0 ? 'file modes do not stop root, and Windows has no chmod 000' : false,
}, () => {
  const f = reloadFixture();
  try {
    f.write(FIXTURE.groups);
    chmodSync(f.path, 0);
    assert.equal(f.ask(f.identity()), 'groups-unreadable');
    chmodSync(f.path, 0o600);
  } finally { f.done(); }
});

test('a recheck interval reads at most that often', () => {
  const f = reloadFixture();
  try {
    const id = f.identity({ recheckSeconds: 5 });
    f.write(FIXTURE.groups);
    assert.equal(f.ask(id), 'ok');
    const changed = clone(FIXTURE.groups);
    changed.groups.ops = [];
    f.write(changed);
    f.now.t = 4000;
    assert.equal(f.ask(id), 'ok');
    f.now.t = 5000;
    assert.equal(f.ask(id), 'unknown-login');
    assert.throws(() => f.identity({ recheckSeconds: -1 }), TypeError);
  } finally { f.done(); }
});

async function serve(server) {
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  return server.address().port;
}

function get(port, headers) {
  return new Promise((resolve, reject) => {
    const req = http.get({ host: '127.0.0.1', port, path: '/', headers, agent: false }, (res) => {
      let body = '';
      res.on('data', (c) => { body += c; });
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: body ? JSON.parse(body) : {} }));
    });
    req.on('error', reject);
  });
}

function handlerFor(identity, bound) {
  return (req, res) => {
    const decision = identity.decideRequest(req, { door: 'dashboard', capability: 'vitals', bound: bound?.() });
    if (!decision.allowed) return ti.sendRefusal(res, decision);
    res.writeHead(200, { 'content-type': 'application/json' });
    return res.end(JSON.stringify({ login: decision.login }));
  };
}

test('the request helpers on a real loopback server, plain and behind the kit\'s loopback gate', async () => {
  const f = reloadFixture();
  const servers = [];
  try {
    f.write(FIXTURE.groups);
    const identity = new ti.TailnetIdentity(f.path, { log: () => {} });
    const plain = http.createServer(handlerFor(identity));
    servers.push(plain);
    let gate;
    const httpServer = http.createServer(handlerFor(identity, () => gate.address().address));
    gate = loopbackServer(httpServer, { peerCheck: 'off' });
    servers.push(gate);
    const unnamed = loopbackServer(http.createServer(handlerFor(identity)), { peerCheck: 'off' });
    servers.push(unnamed);
    const unnamedPort = await serve(unnamed);
    assert.equal((await get(unnamedPort, { [L]: 'ana@example.com' })).body.error.code, 'bind-not-loopback',
      'behind the gate the bound address must be named, or the door stays shut');
    for (const server of [plain, gate]) {
      const port = await serve(server);
      assert.deepEqual(await get(port, { [L]: 'Ana@example.com' }).then((r) => [r.status, r.body]),
        [200, { login: 'ana@example.com' }]);
      const refused = await get(port, {});
      assert.equal(refused.status, 403);
      assert.deepEqual(refused.body, { error: { code: 'no-login', message: FIXTURE.reasons['no-login'] } });
      assert.equal(refused.headers['cache-control'], 'no-store');
      assert.match(refused.headers['content-type'], /^application\/json/);
      const twice = await get(port, { [L]: ['ana@example.com', 'bo@example.com'] });
      assert.equal(twice.body.error.code, 'login-ambiguous');
    }
  } finally {
    await Promise.all(servers.map((s) => new Promise((r) => s.close(() => r()))));
    f.done();
  }
});

test('a service bound beyond loopback is refused whatever the peer', () => {
  const f = reloadFixture();
  try {
    f.write(FIXTURE.groups);
    const req = { headers: { 'tailscale-user-login': 'ana@example.com' },
      socket: { remoteAddress: '127.0.0.1', server: { address: () => ({ address: '0.0.0.0', port: 8080 }) } } };
    assert.equal(new ti.TailnetIdentity(f.path, { log: () => {} }).decideRequest(req, { door: 'dashboard',
      capability: 'vitals' }).code, 'bind-not-loopback');
    const unknown = { headers: {}, socket: { remoteAddress: '127.0.0.1' } };
    assert.equal(new ti.TailnetIdentity(f.path, { log: () => {} }).decideRequest(unknown, { door: 'dashboard',
      capability: 'vitals' }).code, 'bind-not-loopback');
    assert.throws(() => ti.refusalBody({ allowed: true, code: 'ok' }), TypeError);
  } finally { f.done(); }
});

test('the shipped JSON Schema says what loadGroups enforces', () => {
  const props = SCHEMA.properties;
  assert.equal(props.schema.const, ti.GROUPS_SCHEMA);
  const rule = props.rules.items.properties;
  assert.deepEqual(rule.door.enum, [...ti.DOORS]);
  assert.equal(props.groups.propertyNames.pattern, ti.NAME_PATTERN);
  assert.equal(props.groups.additionalProperties.items.pattern, ti.LOGIN_PATTERN);
  assert.equal(rule.capabilities.oneOf.find((a) => a.type === 'array').items.pattern, ti.NAME_PATTERN);
});
