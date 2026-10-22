// fabric-connections.mjs: fabric-connections/0.1 (DEC-0096, FAC-SEM-127), the twin of test_fabric_connections.py.
// Every case of the contract's fixtures/vectors/connections.json (vendored, re-answered by the contract's
// connectionsView) is read here as the contract reads it.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import { CONNECTIONS_EXTENSION_KEY as KEY, connectionsExtension, connectionsRules, connectionsView, dateTime } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-connections.mjs';
import { ServiceError } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-base.mjs';
import { buildWellKnown } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-descriptor.mjs';

const V = JSON.parse(fs.readFileSync(new URL('./fixtures/contract/connections-vectors.json', import.meta.url), 'utf8'));
const INPUTS = JSON.parse(fs.readFileSync(new URL('./fixtures/kit-connections-inputs.json', import.meta.url), 'utf8'));
const EXTRA = JSON.parse(fs.readFileSync(new URL('./fixtures/contract/connections-extra-vectors.json', import.meta.url), 'utf8'));

test('every case answers as the contract does', () => {
  assert.equal(V.cases.length, 127);
  for (const c of V.cases) {
    const view = connectionsView(c.input);
    assert.deepEqual(Object.fromEntries(Object.keys(c.expected).map((k) => [k, view[k]])), c.expected, c.name);
    assert.equal(view.errors.length > 0, view.reported, c.name);
    const findings = connectionsRules(c.input);
    assert.equal(findings.length > 0, c.expected.reported, c.name);
    assert.ok(findings.every((f) => f.code === 'FAC-SEM-127'), c.name);
  }
});

test('the reader never throws', () => {
  for (const value of [null, [], 'x', 1, { extensions: null }, { extensions: { [KEY]: null } }, { extensions: { [KEY]: { connections: [null, 1] } } }]) connectionsView(value);
});

test('date-time as the contract validator reads it', () => {
  for (const [value, ok] of [['2026-10-22T10:00:00Z', true], ['2026-10-22t10:00:00z', true], ['2026-10-22 10:00:00Z', true],
    ['2026-10-22T10:00:00.5+02:00', true], ['2026-10-22T10:00:00+0200', true], ['2026-10-22T10:00:00+02', true],
    ['2026-10-22T10:00:00', false], ['2026-10-22', false], ['2026-02-29T00:00:00Z', false], ['2024-02-29T00:00:00Z', true],
    ['2026-10-22T23:59:60Z', true], ['2026-10-22T22:59:60Z', false], ['2026-10-22T24:00:00Z', false],
    ['2026-10-22T10:00:00+24:00', false], ['2026-10-22T10:00:00Z\n', false], ['２０２６-10-22T10:00:00Z', false]]) assert.equal(dateTime(value), ok, value);
});

const DECLARED = [{ id: 'router', kind: 'model', target: 'openai/gpt-5.1', purpose: 'answers' },
  { id: 'notify', kind: 'service', target: 'communicator.default', capability: 'communicator.notify' },
  { id: 'crm', kind: 'connector', target: 'hubspot' }];

test('state from checks, then degraded, then unknown; a declared state is kept', () => {
  const ext = connectionsExtension(DECLARED, { degraded: [{ source: 'crm', reason: 'token expired' }], states: { router: 'ok' } });
  assert.deepEqual(Object.fromEntries(ext[KEY].connections.map((c) => [c.id, c.state])), { router: 'ok', notify: 'unknown', crm: 'degraded' });
  assert.equal(connectionsExtension([{ ...DECLARED[0], state: 'down' }], { states: { router: 'ok' } })[KEY].connections[0].state, 'down');
});

test('a declaration a host would hide is refused', () => {
  for (const bad of [[DECLARED[0], { ...DECLARED[0] }], [{ id: 'x', kind: 'connector', target: 'api', purpose: 'key sk-AbCdEf0123456789xyzQ' }],
    [{ id: 'x', kind: 'model', target: 'a/b', capability: 'c.d' }], [{ id: 'X', kind: 'store', target: 'db' }]]) {
    assert.throws(() => connectionsExtension(bad), ServiceError);
  }
});

test('the well-known document carries it, a host reads it, an invalid one is refused', () => {
  const base = { id: 'example-agent', instance: 'default', name: 'Example', version: '1.0.0', build: { commit: '0'.repeat(40) }, startedAt: '2026-10-22T00:00:00Z', surfaces: { events: '/fabric/v1/events' } };
  const degraded = [{ source: 'crm', reason: 'token expired' }];
  const doc = buildWellKnown({ ...base, status: 'degraded', degraded, extensions: connectionsExtension(DECLARED, { degraded }) });
  const view = connectionsView(doc);
  assert.equal(view.declared, true);
  assert.deepEqual(view.connections.map((c) => c.failing), [false, false, true]);
  assert.throws(() => buildWellKnown({ ...base, status: 'ready', extensions: { [KEY]: { connections: [{ id: 'a', kind: 'nope', target: 't', state: 'ok' }] } } }), ServiceError);
});

test('every kit input answers as the contract does', () => {
  assert.equal(EXTRA.cases.length, INPUTS.inputs.length);
  EXTRA.cases.forEach((c, index) => {
    const view = connectionsView(c.input);
    assert.deepEqual(Object.fromEntries(Object.keys(c.expected).map((k) => [k, view[k]])), c.expected, String(index));
  });
});

test('odd input is refused with ServiceError only; null options read as empty', () => {
  for (const [declared, options] of [[['x'], {}], [[null], {}], [[['id', 'a']], {}], [null, {}], ['ab', {}],
    [[DECLARED[2]], { degraded: 'x' }], [[DECLARED[2]], { states: ['router'] }], [[DECLARED[0]], { states: { router: '' } }]]) {
    assert.throws(() => connectionsExtension(declared, options), ServiceError);
  }
  assert.equal(connectionsExtension([DECLARED[2]], { degraded: null, states: null })[KEY].connections[0].state, 'unknown');
  assert.equal(connectionsExtension([DECLARED[2]], null)[KEY].connections[0].state, 'unknown');
});

test('a secret-shaped member name never reaches the message', () => {
  const secret = 'sk-AbCdEf0123456789xyzQ';
  const findings = connectionsRules({ extensions: { [KEY]: { connections: [{ ...DECLARED[2], state: 'ok', [secret]: 1 }], [secret]: 2 } } });
  assert.ok(findings.length);
  assert.ok(!JSON.stringify(findings).includes(secret));
  assert.throws(() => connectionsExtension([{ ...DECLARED[2], [secret]: 1 }]), (err) => err instanceof ServiceError && !err.message.includes(secret));
});
