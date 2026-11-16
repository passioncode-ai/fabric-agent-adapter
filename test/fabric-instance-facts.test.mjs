// fabric-instance-facts.mjs: fabric-instance-facts/0.1 (DEC-0173, FAC-SEM-180, FAA-342), the twin of
// test_fabric_instance_facts.py. Every case of the contract's instance-facts vectors and the kit's hostile cases
// (vendored, re-answered by the contract's functions at the pin) is read here as the contract reads it, and the
// descriptor writer and the well-known builder keep the extension key and its value as given.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { INSTANCE_FACTS_EXTENSION_KEY, instanceFacts, instanceFactsRules } from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-instance-facts.mjs';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';
import { tempDir } from './temp-dir.mjs';

const read = (name) => JSON.parse(fs.readFileSync(new URL(name, import.meta.url), 'utf8'));
const V = read('./fixtures/contract/instance-facts-vectors.json');
const FIX = read('./fixtures/contract/descriptor-fixtures.json');
const KEY = 'https://fabric.passioncode.ai/agent-contract/extensions/instance-facts/0.1';
const FACTS = { access: { audience: 'operator', entry: 'own-signin' }, tenancy: { mode: 'single' }, space: { kind: 'user', account: 'agents-1' } };
const KINDS = [['service-descriptor', 'descriptor'], ['service-well-known', 'wellKnown'], ['service-observation', 'pair']];

test('the key is the contract\'s, and the facade exports the reader', () => {
  assert.equal(INSTANCE_FACTS_EXTENSION_KEY, V.key);
  assert.equal(INSTANCE_FACTS_EXTENSION_KEY, KEY);
  assert.equal(k.INSTANCE_FACTS_EXTENSION_KEY, KEY);
  assert.equal(k.instanceFacts, instanceFacts);
});

test('every case reads and finds as the contract does', () => {
  assert.equal(V.cases.filter((c) => !c.name.startsWith('hostile: ')).length, 38);
  for (const c of V.cases) {
    const read = instanceFacts(c.descriptor ?? undefined, c.wellKnown ?? undefined);
    assert.deepEqual(read, c.read, c.name);
    assert.deepEqual(Object.keys(read.facts), Object.keys(c.read.facts), `${c.name}: the facts' order`);
    for (const [kind, key] of KINDS) {
      if (c.findings[key] === null) continue;
      const value = key === 'pair' ? { descriptor: c.descriptor, wellKnown: c.wellKnown } : c[key];
      assert.deepEqual(instanceFactsRules(kind, value), c.findings[key], `${c.name} (${kind})`);
    }
  }
});

test('other kinds and shapes answer nothing', () => {
  for (const [kind, value] of [['service-directory', {}], ['service-descriptor', null], ['service-well-known', []], ['service-observation', 'x']]) {
    assert.deepEqual(instanceFactsRules(kind, value), []);
  }
  assert.deepEqual(instanceFacts(undefined, undefined), { declared: false, facts: {}, refused: [], foreign: false, invalid: [] });
});

test('the descriptor writer keeps the key and its value', () => {
  const dir = tempDir('fabric-instance-facts-');
  const services = path.join(dir, 'services');
  const desc = { ...structuredClone(FIX.descriptors.find((d) => d.name === 'service-descriptor-node').descriptor), source: { repository: 'https://github.com/example-org/example-agent' }, extensions: { [KEY]: structuredClone(FACTS) } };
  assert.deepEqual(k.validateDescriptor(desc), []);
  const written = JSON.parse(fs.readFileSync(k.writeDescriptor(desc, services, { portOwner: () => null }), 'utf8'));
  assert.deepEqual(Object.keys(written.extensions), [KEY]);
  assert.deepEqual(written.extensions[KEY], FACTS);
  assert.deepEqual(instanceFactsRules('service-descriptor', written), []);
});

test('the well-known builder keeps the key and its value, and never refuses a pair problem', () => {
  const value = { access: { audience: 'organization' }, tenancy: { mode: 'shared' } };
  const doc = k.buildWellKnown({ id: 'facts-keeper', instance: 'default', name: 'Example', version: '1.0.0', build: { commit: '0'.repeat(40) },
    startedAt: '2026-11-16T00:00:00Z', status: 'ready', degraded: [], surfaces: { events: { path: '/fabric/v1/events' } }, extensions: { [KEY]: structuredClone(value) } });
  assert.deepEqual(doc.extensions, { [KEY]: value });
  assert.deepEqual(instanceFactsRules('service-well-known', doc), []);
  const local = { protocol: 'fabric-service/0.1', id: 'facts-keeper', instance: 'default', origin: 'http://127.0.0.1:47931' };
  assert.deepEqual(instanceFactsRules('service-observation', { descriptor: local, wellKnown: doc }).map((f) => f.instancePath.split('/').slice(-2).join('/')), ['access/audience', 'tenancy/mode']);
});
