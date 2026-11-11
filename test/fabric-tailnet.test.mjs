// FAA-297: fabric-tailnet.mjs on the vectors fabric_tailnet.py answers too.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as ft from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-tailnet.mjs';

const FIXTURE = JSON.parse(readFileSync(new URL('./fixtures/tailnet/vectors.json', import.meta.url), 'utf8'));

test('every vector', () => {
  const perimeter = ft.loadPerimeter(FIXTURE.perimeter);
  const keys = ft.loadKeys(FIXTURE.keys);
  for (const v of FIXTURE.vectors) {
    const got = ft.authorize({ listener: v.listener, peer: v.peer, headers: v.headers, perimeter, surface: v.surface,
      target: v.target, keys });
    assert.equal(got.status, v.expect.status, v.name);
    assert.equal(got.code, v.expect.code, v.name);
    assert.equal(got.login, v.expect.login, v.name);
    assert.deepEqual(got.groups, v.expect.groups, v.name);
    assert.equal(got.key, v.expect.key, v.name);
    assert.equal(got.allowed, v.expect.status === 200, v.name);
  }
});

test('every refusal code is exercised', () => {
  const codes = new Set(FIXTURE.vectors.map((v) => v.expect.code).filter((c) => c !== 'ok'));
  assert.deepEqual([...codes].sort(), Object.keys(ft.REFUSALS).sort());
});

test('bad perimeters and keys', () => {
  for (const c of FIXTURE.badPerimeters) {
    assert.throws(() => ft.loadPerimeter(c.doc), (e) => e instanceof ft.PerimeterError && e.code === c.code, c.name);
  }
  for (const c of FIXTURE.badKeys) {
    assert.throws(() => ft.loadKeys(c.keys), (e) => e instanceof ft.PerimeterError && e.code === c.code, c.name);
  }
});

test('hashKey, headers as an object or a Headers, and no key in an answer', () => {
  assert.equal(ft.hashKey(FIXTURE.hashKey.in), FIXTURE.hashKey.out);
  assert.throws(() => ft.hashKey(''));
  const perimeter = ft.loadPerimeter(FIXTURE.perimeter);
  const plain = ft.authorize({ listener: 'serve', peer: '127.0.0.1', headers: { 'Tailscale-User-Login': 'cy@example.com' },
    perimeter, surface: 'dashboard', target: 'vitals' });
  assert.equal(plain.code, 'ok');
  const web = ft.authorize({ listener: 'serve', peer: '127.0.0.1',
    headers: new Headers({ 'tailscale-user-login': 'ana@example.com', authorization: 'Bearer example-key-ana' }),
    perimeter, surface: 'mcp', target: 'cve.scan', keys: ft.loadKeys(FIXTURE.keys) });
  assert.equal(web.code, 'ok');
  assert.ok(!JSON.stringify(web).includes('example-key-ana'));
  assert.throws(() => ft.authorize({ listener: 'fabric', peer: '127.0.0.1', headers: {}, perimeter, surface: 'dashboard',
    target: 'vitals' }), TypeError);
});
