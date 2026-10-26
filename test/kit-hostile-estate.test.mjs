// Hostile inputs the estate and ceremony twins must answer alike (FAA-78, finding 44; decision D3): the cases in
// fixtures/kit-hostile-inputs-estate.json, which test_kit_hostile_estate.py runs through the Python twins.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as fe from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-estate.mjs';
import * as fc from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-ceremonies.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (name) => JSON.parse(fs.readFileSync(path.join(here, name), 'utf8'));
const CASES = read('fixtures/kit-hostile-inputs-estate.json');
const HUB = read('fixtures/contract/hub-key-vectors.json').cases[0];
const ESTATE = read('fixtures/contract/estate-vectors.json');
const CEREMONY = read('fixtures/contract/ceremony-vectors.json');

test('hubKeyCertified: an explicit null or any other non-revision applied fails closed', () => {
  for (const c of CASES.hubKey) {
    const got = Object.hasOwn(c, 'applied') ? fe.hubKeyCertified(HUB.record, HUB.kid, HUB.x, HUB.at, c.applied) : fe.hubKeyCertified(HUB.record, HUB.kid, HUB.x, HUB.at);
    assert.deepEqual(got, c.expected, c.name);
  }
});

// DEC-0128: hostile `contextHubKeys` and `organizations` answer as the contract does (FAC-SEM-073, 076, 134, 147).
const ORGS = ESTATE.rules.find((r) => r.name === 'positive/estate-record-organizations').value;
const hubMachine = (record) => record.machines.find((m) => m.hubKey);
const findings = (value) => fe.estateRecordRules('estate-record', value).filter((f) => f.code !== 'FAC-SEM-072').map((f) => [f.code, f.instancePath]);

test('hostile context hub keys answer as the contract does', () => {
  for (const c of CASES.contextHubKeys) {
    const value = structuredClone(ORGS);
    hubMachine(value).contextHubKeys = structuredClone(c.contextHubKeys);
    assert.deepEqual(findings(value), c.expected, c.name);
  }
});

test('hostile organization pins answer as the contract does', () => {
  for (const c of CASES.organizations) {
    const value = structuredClone(ORGS);
    value.organizations = structuredClone(c.organizations);
    if (Object.hasOwn(c, 'estate')) value.estate = c.estate;
    assert.deepEqual(findings(value), c.expected, c.name);
  }
});

test('a hostile context certifies no hub key', () => {
  const key = hubMachine(ORGS).contextHubKeys[0].key;
  for (const c of CASES.hubKeyContext) assert.deepEqual(fe.hubKeyCertified(ORGS, key.kid, key.x, 1792454400, undefined, { context: c.context }), c.expected, c.name);
});

test('a device key finding names the key by its position in the list as written', () => {
  const base = ESTATE.rules.find((r) => r.name === 'estate-contexts-ok.json');
  for (const c of CASES.deviceKeys) {
    const value = structuredClone(base.value);
    const keys = value.machines[0].deviceKeys;
    keys[1].kid = c.kidFromSecond;
    value.machines[0].deviceKeys = [...c.prefix, ...keys];
    const paths = fe.estateRecordRules(base.kind, value).map((f) => f.instancePath).filter((p) => p.startsWith('/machines/0/deviceKeys/') && p.endsWith('/kid'));
    assert.deepEqual(paths, c.paths, c.name);
  }
});

test('placementTrust: a record that is no object places nothing', () => {
  for (const c of CASES.placementTrust) assert.equal(fe.placementTrust(c.record, 'm-4c1e', 'urn:fabric:agent:example:inbox-digest'), undefined, c.name);
});

test('verifyEnrollToken: epoch seconds and a Date answer alike', () => {
  for (const c of CEREMONY.verify) {
    const record = c.record ?? CEREMONY.record;
    const byDate = fc.verifyEnrollToken(c.token, { record, genesis: CEREMONY.genesis, at: new Date(c.at) });
    const bySeconds = fc.verifyEnrollToken(c.token, { record, genesis: CEREMONY.genesis, at: Date.parse(c.at) / 1000 });
    assert.deepEqual(bySeconds, byDate, c.name);
    assert.deepEqual(bySeconds, c.answer, c.name);
  }
});
