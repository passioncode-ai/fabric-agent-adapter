// fabric-a2a.mjs: the reading side of DEC-0122 (decision D4 of the 0.51.0 brief), the twin of test_fabric_a2a.py.
// surfaces.a2a is read as the contract's schema reads it, on the three vendored catalogue fixtures and the kit's own
// cases (test/fixtures/kit-a2a-cases.json, shared with the Python twin); buildWellKnown writes the member and never
// publishes an invalid one; agentCardFindings reports what a public Agent Card must not carry (D5, D6).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import { A2A_PROTOCOL_VERSION, A2A_SURFACE_PATH, a2aSurface, a2aSurfaceFindings, a2aSurfaceProblems, a2aView, agentCardFindings } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-a2a.mjs';
import { ServiceError } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-base.mjs';
import { buildWellKnown } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-descriptor.mjs';

const VECTORS = JSON.parse(fs.readFileSync(new URL('./fixtures/contract/a2a-vectors.json', import.meta.url), 'utf8'));
const SAMPLE_KEY = 'sk-' + 'Ab1'.repeat(8); // a provider-key shape, built here so no file holds one
const CASES = JSON.parse(fs.readFileSync(new URL('./fixtures/kit-a2a-cases.json', import.meta.url), 'utf8').replaceAll('@SK@', SAMPLE_KEY));
const BASE = { id: 'example-agent', instance: 'default', name: 'Example', version: '1.0.0', build: { commit: '0'.repeat(40) }, startedAt: '2026-10-26T00:00:00Z', status: 'ready', degraded: [] };
const keyed = (findings) => findings.map((f) => ({ instancePath: f.instancePath, keyword: f.keyword }));

test('the three catalogue fixtures read as the contract reads them', () => {
  assert.deepEqual(VECTORS.fixtures.map((f) => f.name), ['service-well-known-a2a', 'service-well-known-a2a-old-version', 'service-well-known-a2a-url']);
  for (const fixture of VECTORS.fixtures) {
    const surface = fixture.document.surfaces.a2a;
    assert.deepEqual(keyed(a2aSurfaceFindings(surface)), fixture.errors, fixture.name);
    assert.equal(a2aSurfaceProblems(surface).length === 0, fixture.valid, fixture.name);
    const view = a2aView(fixture.document);
    assert.equal(view.declared, true, fixture.name);
    assert.equal(view.valid, fixture.valid, fixture.name);
  }
});

test("the kit's own inputs", () => {
  assert.equal(CASES.surfaces.length, 26);
  for (const c of CASES.surfaces) {
    const findings = a2aSurfaceFindings(c.value);
    assert.deepEqual(keyed(findings), c.findings, c.name);
    assert.ok(findings.every((f) => typeof f.message === 'string' && f.message), c.name);
  }
});

test('a surface is built and checked', () => {
  assert.equal(A2A_SURFACE_PATH, '/.well-known/agent-card.json');
  assert.equal(A2A_PROTOCOL_VERSION, '1.0');
  assert.deepEqual(a2aSurface(), { path: '/.well-known/agent-card.json', protocolVersion: '1.0' });
  assert.deepEqual(a2aSurface('/a2a/card'), { path: '/a2a/card', protocolVersion: '1.0' });
  for (const bad of ['a2a/card', '//x', '/a b', '/x\n', 7]) assert.throws(() => a2aSurface(bad), ServiceError, String(bad));
});

test('the view never throws and tells absence from invalidity', () => {
  for (const wk of [null, [], 'x', {}, { surfaces: null }, { surfaces: [] }, { surfaces: { events: { path: '/e' } } }]) assert.equal(a2aView(wk).declared, false);
  let view = a2aView({ surfaces: { a2a: null } });
  assert.deepEqual([view.declared, view.valid, view.path], [true, false, null]);
  view = a2aView({ surfaces: { a2a: { path: '/c', protocolVersion: '1.0' } } });
  assert.deepEqual([view.declared, view.valid, view.path, view.findings], [true, true, '/c', []]);
});

test('buildWellKnown writes the member', () => {
  const surfaces = { events: { path: '/fabric/v1/events' } };
  const doc = buildWellKnown({ ...BASE, surfaces, a2a: a2aSurface() });
  assert.deepEqual(doc.surfaces.a2a, { path: '/.well-known/agent-card.json', protocolVersion: '1.0' });
  assert.equal(Object.hasOwn(surfaces, 'a2a'), false, "the caller's surfaces are not changed");
  assert.equal(a2aView(doc).valid, true);
  assert.equal(buildWellKnown({ ...BASE, surfaces: { events: { path: '/e' }, a2a: { path: '/c', protocolVersion: '1.0' } } }).surfaces.a2a.path, '/c');
  assert.equal(Object.hasOwn(buildWellKnown({ ...BASE, surfaces: { events: { path: '/e' } } }).surfaces, 'a2a'), false);
});

test('buildWellKnown refuses an invalid member either way', () => {
  for (const fixture of VECTORS.fixtures.slice(1)) {
    const surface = fixture.document.surfaces.a2a;
    assert.throws(() => buildWellKnown({ ...BASE, surfaces: { events: { path: '/e' }, a2a: surface } }), (e) => e instanceof ServiceError && e.message.includes('surfaces.a2a'), fixture.name);
    assert.throws(() => buildWellKnown({ ...BASE, surfaces: { events: { path: '/e' } }, a2a: surface }), ServiceError, fixture.name);
  }
  assert.throws(() => buildWellKnown({ ...BASE, surfaces: { events: { path: '/e' }, a2a: a2aSurface() }, a2a: a2aSurface() }), /not both/);
});

test("the kit's own cards", () => {
  assert.equal(CASES.cards.length, 25);
  for (const c of CASES.cards) {
    const o = c.options;
    const findings = agentCardFindings(c.card, { origin: o.origin, remote: o.remote, descriptorHeader: o.descriptorHeader });
    assert.deepEqual(findings.map((f) => ({ code: f.code, instancePath: f.instancePath })), c.findings, c.name);
    for (const finding of findings) assert.ok(!finding.message.includes(SAMPLE_KEY), 'a finding names the place, never the value');
  }
});

test("without an origin the interfaces' place is not judged", () => {
  const card = { supportedInterfaces: [{ url: 'http://127.0.0.1:1/a2a', protocolBinding: 'JSONRPC', protocolVersion: '1.0' }] };
  assert.deepEqual(agentCardFindings(card), []);
  assert.deepEqual(agentCardFindings(card, { remote: true }).map((f) => f.code), ['interface-scheme']);
});

test('a deep card is walked without recursion', () => {
  const card = { supportedInterfaces: [{ url: 'http://127.0.0.1:1/', protocolBinding: 'JSONRPC', protocolVersion: '1.0' }] };
  let node = card;
  for (let i = 0; i < 5000; i += 1) { node.x = {}; node = node.x; }
  node.y = SAMPLE_KEY;
  assert.deepEqual(agentCardFindings(card).map((f) => f.code), ['secret']);
});
