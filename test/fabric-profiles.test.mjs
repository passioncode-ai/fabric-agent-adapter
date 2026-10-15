// Runner and model profiles (DEC-0046, FAA-19) and the credential detector (DEC-0044) in the Node kit, against vectors
// whose expected answers come from the contract's own functions at the pin (make_profile_vectors.mjs).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as s from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-secrets.mjs';
import * as p from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-profiles.mjs';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const V = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/profile-vectors.json'), 'utf8'));
const decode = (hex) => Buffer.from(hex, 'hex').toString('utf8');
const plain = (v) => JSON.parse(JSON.stringify(v));

test('the credential detector answers as the contract does', () => {
  const fns = { credentialName: s.credentialName, nameWords: s.nameWords, secretValue: s.secretValue, secretArgument: s.secretArgument, secretUrl: s.secretUrl };
  for (const [name, cases] of Object.entries(V.secrets)) for (const c of cases) assert.deepEqual(fns[name](decode(c.inputHex)), c.expected, `${name}(${decode(c.inputHex).slice(0, 30)})`);
});

test('every resolution and every rule case answers as the contract does', () => {
  for (const c of V.resolutions) assert.deepEqual(plain(p.resolveModelProfile(c.input)), c.expected, c.name);
  for (const c of V.rules) assert.deepEqual(p.profileProblems(c.kind, JSON.parse(decode(c.valueHex))), c.expected, c.name);
  assert.equal(p.profileProblems('something-else', {}), undefined);
});

test('runnerCheck runs only the catalogued binary and argv, bounded, and reads the version and sign-in', { skip: process.platform === 'win32' }, () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'runner-'));
  const tool = (body) => { const f = path.join(dir, 'example-code'); fs.writeFileSync(f, `#!/bin/sh\n${body}\n`); fs.chmodSync(f, 0o755); };
  const entry = (extra = {}) => ({ kind: 'example-code', binaries: ['example-code'], version: { argv: ['--version'], pattern: '^example (\\d+\\.\\d+\\.\\d+)', timeoutMs: 2000 }, ...extra });
  assert.equal(p.runnerCheck(entry(), { searchPath: dir }).installed, false);
  assert.equal(p.runnerCheck(entry(), { searchPath: dir }).probe, 'not-installed');
  tool('if [ "$1" = "--version" ]; then echo "example 2.0.1"; exit 0; fi; if [ "$1" = "auth" ]; then exit 4; fi');
  const got = p.runnerCheck(entry({ auth: ['auth', 'status'] }), { searchPath: dir });
  assert.deepEqual([got.installed, got.version, got.signedIn, got.probe], [true, '2.0.1', false, 'not-connected']);
  assert.equal(p.runnerCheck(entry(), { searchPath: dir }).probe, null, 'no auth probe: answering is enough');
  tool('sleep 5');
  const slow = p.runnerCheck(entry({ version: { argv: ['--version'], pattern: '(x)', timeoutMs: 300 } }), { searchPath: dir });
  assert.ok(slow.problems.some((m) => m.includes('did not answer')), slow.problems.join('; '));
  assert.equal(slow.probe, 'not-responding');
  tool('if [ "$1" = "--version" ]; then echo "example 2.0.1"; exit 0; fi; sleep 5');
  assert.equal(p.runnerCheck(entry({ auth: ['auth', 'status'], version: { argv: ['--version'], pattern: '^example (\\d+\\.\\d+\\.\\d+)', timeoutMs: 300 } }), { searchPath: dir }).probe, 'not-responding', 'an auth probe that does not answer in its bound');
  for (const bad of [entry({ binaries: ['/bin/sh'] }), entry({ version: { argv: '--version', pattern: '(x)' } }), entry({ version: { argv: [], pattern: '(x)', timeoutMs: 9000 } }), entry({ auth: 'x' })]) {
    assert.throws(() => p.runnerCheck(bad, { searchPath: dir }), p.ProfileError);
  }
});

test('configuration, its tiles, the well-known document and the usage route', () => {
  const conf = p.configuration(['runner', 'model'], { from: 'binding', profile: 'default', models: ['deepseek/deepseek-v4-pro'] },
    { id: 'claude-sub', runnerKind: 'claude-code', route: 'subscription' });
  assert.deepEqual(p.configurationSummary(conf), [{ label: 'Runner', value: 'claude-code · subscription' }, { label: 'Model', value: 'default · deepseek/deepseek-v4-pro' }]);
  assert.throws(() => p.configuration(['model'], { refused: 'no-profile' }), p.ProfileError);
  assert.throws(() => p.configuration(['model'], { from: 'agent', profile: 'Bad Id', models: [] }), p.ProfileError);
  const base = { id: 'example-agent', instance: 'default', name: 'E', version: '1.0.0', build: { commit: 'abc1234' }, startedAt: k.nowIso(), status: 'ready', surfaces: { events: { path: '/e' } } };
  assert.deepEqual(k.buildWellKnown({ ...base, configuration: conf }).configuration, conf);
  assert.throws(() => k.buildWellKnown({ ...base, configuration: { slots: ['model'], resolved: { extra: 1 } } }), /configuration/);
  const a = k.makeUsageReceipt('openrouter', 'deepseek/deepseek-v4-pro', { inputTokens: 1, outputTokens: 1, costUsd: 0.01, route: 'key' });
  const b = k.makeUsageReceipt('openrouter', 'deepseek/deepseek-v4-pro', { inputTokens: 1, outputTokens: 1, costUsd: 0.0 });
  assert.equal(a.route, 'key');
  assert.equal('route' in b, false);
  assert.throws(() => k.makeUsageReceipt('openrouter', 'm', { inputTokens: 1, outputTokens: 1, route: 'borrowed' }), /route/);
  const rows = k.usageReport([a, b], { id: 'example-agent' }).days[0].byModel;
  assert.deepEqual(rows.map((r) => r.route ?? null), [null, 'key']);
  assert.deepEqual(p.modelUsable('example/none', { models: [] }), ['model example/none is not in the model catalogue']);
});

test('the resolver and the doctor admit as the contract does (DEC-0083 model-admission vectors)', () => {
  assert.ok(V.admission.length >= 8);
  for (const c of V.admission) {
    const catalogue = { models: c.classes === null ? [] : [{ id: 'example/model', classes: c.classes }] };
    const policy = { meta: { id: 'p', revision: 1 }, modelClasses: c.modelClasses };
    const resolved = p.resolveModelProfile({ catalogue, profiles: [{ id: 'x', models: ['example/model'] }], choices: { estate: 'x' }, policy });
    assert.equal('models' in resolved, c.admitted, `resolver: ${c.name}`);
    assert.equal(p.modelUsable('example/model', catalogue, policy).length === 0, c.admitted, `doctor: ${c.name}`);
  }
});

test('the doctor never throws on hostile input', () => {
  const catalogue = { models: [{ id: { toString: 1 }, classes: ['cheap'] }, { id: ['x'], classes: ['cheap'] }, { id: 'example/m', classes: ['strong'] }] };
  assert.deepEqual(p.modelUsable('example/m', catalogue), []);
  assert.deepEqual(p.modelUsable({ toString: 1 }, catalogue), ['model {"toString":1} is not in the model catalogue']);
  assert.deepEqual(p.modelUsable(null, catalogue), ['model null is not in the model catalogue']);
  assert.deepEqual(p.modelUsable({ toString: 1, a: '\ud800' }, catalogue), ['model {"toString":1,"a":"\\ud800"} is not in the model catalogue']);
  for (const [meta, shown] of [[{ id: { toString: 1 } }, '{"toString":1}'], [{ id: null }, 'null'], [{}, 'undefined'], [{ id: 7 }, '7'], [{ id: { toString: 1, a: '\udc00' } }, '{"toString":1,"a":"\\udc00"}']]) {
    assert.deepEqual(p.modelUsable('example/m', catalogue, { meta, modelClasses: ['cheap'] }), [`model example/m has class strong, which policy ${shown} does not allow`]);
  }
});

test('open-vendor is descriptive in the doctor too (DEC-0083)', () => {
  const catalogue = { models: [{ id: 'example/open', classes: ['cheap', 'open-vendor'] }, { id: 'example/bare', classes: ['open-vendor'] }] };
  const policy = { meta: { id: 'p', revision: 1 }, modelClasses: ['cheap'] };
  const bare = ['model example/bare has no class but open-vendor, which admits nothing, so policy p does not allow it'];
  assert.deepEqual(p.modelUsable('example/open', catalogue, policy), []);
  assert.deepEqual(p.modelUsable('example/bare', catalogue, policy), bare);
  assert.deepEqual(p.modelUsable('example/bare', catalogue, { ...policy, modelClasses: ['open-vendor'] }), bare);
  assert.deepEqual(p.modelUsable('example/bare', catalogue), []);
  for (const model of ['example/open', 'example/bare']) {
    const resolution = p.resolveModelProfile({ catalogue, profiles: [{ id: 'x', models: [model] }], choices: { estate: 'x' }, policy });
    assert.equal('models' in resolution, p.modelUsable(model, catalogue, policy).length === 0, model);
  }
});

test('every route case answers as the contract does (FAC-SEM-028…034)', () => {
  const { cases } = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/route-vectors.json'), 'utf8'));
  assert.ok(cases.length >= 40);
  for (const c of cases) assert.deepEqual(p.routeProblems(c.kind, c.valueText === undefined ? c.value : JSON.parse(c.valueText)), c.expected, c.name);
  assert.equal(p.routeProblems('something-else', {}), undefined);
  for (const kind of ['constructor', '__proto__', 'toString', 'hasOwnProperty']) {
    assert.equal(p.routeProblems(kind, {}), undefined, kind);
    assert.equal(p.profileProblems(kind, {}), undefined, kind);
  }
  for (const result of ['not-installed', 'not-responding', 'not-connected']) assert.ok(p.PROBE_RESULTS.includes(result));
});
