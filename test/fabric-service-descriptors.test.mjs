// DEC-0061 and DEC-0069 in the Node service kit (FAA-34); the twin of test_fabric_service_descriptors.py. The validator is
// held to every service-descriptor fixture of the contract at the pin and the ports to its vectors (vendor_vectors.mjs).
// The local channel (DEC-0075) is not a kit surface yet: its six negatives are the only fixtures the validator does not
// refuse, and that set is pinned so a new one is noticed.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import * as k from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-service.mjs';
import { tempDir } from './temp-dir.mjs';

const read = (name) => JSON.parse(fs.readFileSync(new URL(`./fixtures/contract/${name}`, import.meta.url), 'utf8'));
const FIX = read('descriptor-fixtures.json');
const PEER = read('service-peer-vectors.json');
const APP = read('app-descriptor-vectors.json');
const LOCAL_CHANNEL = ['service-descriptor-channels-without-local', 'service-descriptor-local-channel-bad-sid', 'service-descriptor-local-channel-both',
  'service-descriptor-local-channel-home', 'service-descriptor-local-channel-multibyte', 'service-descriptor-remote-with-channel'];
const fixture = (name) => structuredClone(FIX.descriptors.find((d) => d.name === name).descriptor);
const temp = () => tempDir('fabric-descriptors-');

test('every valid descriptor is accepted; every invalid one is refused but the local channel', () => {
  const valid = FIX.descriptors.filter((d) => d.valid);
  assert.equal(valid.length, 10);
  for (const d of valid) assert.deepEqual(k.validateDescriptor(d.descriptor), [], d.name);
  const accepted = FIX.descriptors.filter((d) => !d.valid && k.validateDescriptor(d.descriptor).length === 0).map((d) => d.name).sort();
  assert.deepEqual(accepted, LOCAL_CHANNEL);
});

test('FAC-SEM-085 and FAC-SEM-086 at the contract\'s places; each refusal for its reason', () => {
  assert.equal(FIX.semantic.length, 3);
  for (const s of FIX.semantic) {
    const found = k.validateDescriptor(s.document).filter((p) => p.startsWith('FAC-SEM-'));
    assert.equal(found.length, s.findings.length, s.name);
    for (const want of s.findings) assert.ok(found.some((p) => p.startsWith(want.code) && (want.code === 'FAC-SEM-085' || p.includes(want.instancePath))), `${s.name}: ${found}`);
  }
  const reasons = {
    'service-descriptor-node-with-label': 'label belongs to launchd', 'service-descriptor-node-with-unit': 'unit belongs',
    'service-descriptor-person-with-plist': 'plist belongs to launchd', 'service-descriptor-person-without-app': 'lifecycle.app',
    'service-descriptor-app-beside-launchd': 'lifecycle.app belongs to manager person', 'service-descriptor-without-origin': 'missing origin',
    'service-descriptor-person-installed-by-string': 'as a person', 'service-descriptor-remote-under-node': 'manager must be none',
    'service-descriptor-peer-without-runner': 'declares runner', 'service-descriptor-peer-subscription': 'never runs on a subscription',
    'service-descriptor-runner-subscription-wrong-runner': "vendor's runner", 'service-descriptor-installed-by-node-with-role': 'a person only',
  };
  for (const [name, reason] of Object.entries(reasons)) assert.ok(k.validateDescriptor(fixture(name)).join(' ').includes(reason), name);
});

test('peerRefusal and residency as the contract reads them', () => {
  assert.equal(PEER.cases.length, 22);
  for (const c of PEER.cases) assert.equal(k.peerRefusal(c.descriptor, c.dataClass), c.refusal, c.name);
  const base = fixture('service-descriptor-peer');
  for (const code of PEER.residency.accepted) assert.deepEqual(k.validateDescriptor({ ...base, peer: { ...base.peer, residency: [code] } }), [], code);
  for (const code of PEER.residency.refused) assert.ok(k.validateDescriptor({ ...base, peer: { ...base.peer, residency: [code] } }).join(' ').includes('peer.residency'), code);
});

test('appDescriptorAction and appDescriptorStale', () => {
  for (const c of APP.action) assert.equal(k.appDescriptorAction(c.existing, c.tool, c.appPath), c.expect, c.name);
  for (const c of APP.stale) assert.equal(k.appDescriptorStale(c.descriptor, c.appPresent), c.expect, c.name);
});

test('Fabric\'s button: present only while Fabric\'s descriptor is registered and its app installed', () => {
  const dir = temp();
  const app = path.join(dir, 'Example App.app');
  fs.mkdirSync(app);
  const services = path.join(dir, 'services');
  assert.equal(k.fabricButtonPresence(services), 'absent', 'no services directory');
  const desc = fixture('service-descriptor-person-app');
  desc.lifecycle.app = app;
  k.writeDescriptor({ ...desc, id: 'fabric', instance: 'default' }, services);
  assert.equal(k.fabricButtonPresence(services), 'present');
  fs.rmdirSync(app);
  assert.equal(k.fabricButtonPresence(services), 'absent', "an app's descriptor whose app is gone is stale");
  fs.writeFileSync(path.join(services, 'fabric.default.json'), JSON.stringify({ ...fixture('service-descriptor-node'), id: 'fabric', instance: 'default' }));
  assert.equal(k.fabricButtonPresence(services), 'present', 'a supervised Fabric with an origin');
  fs.writeFileSync(path.join(services, 'fabric.default.json'), '{not json');
  assert.equal(k.fabricButtonPresence(services), 'absent');
  fs.writeFileSync(path.join(services, 'fabric.default.json'), JSON.stringify({ id: 'fabric' }));
  assert.equal(k.fabricButtonPresence(services), 'absent', 'an invalid descriptor is no Fabric');
});

test('two app descriptors without an origin never clash', () => {
  const dir = temp();
  const desc = fixture('service-descriptor-person-app');
  desc.lifecycle.app = dir;
  const services = path.join(dir, 'services');
  assert.ok(fs.existsSync(k.writeDescriptor(desc, services)));
  assert.ok(fs.existsSync(k.writeDescriptor({ ...desc, id: 'other-app' }, services)));
});

test('registerRemote writes who installed it and takes runner and peer; usage rows take platform-metered', () => {
  const dir = temp();
  const written = JSON.parse(fs.readFileSync(k.registerRemote({ id: 'example-inbox', name: 'Example Inbox', origin: 'https://inbox.example.com', token: 't'.repeat(32), dir }), 'utf8'));
  assert.deepEqual(written.installedBy, { by: 'person', role: 'operator', tool: 'fabric-service register-remote' });
  const offered = fixture('service-descriptor-peer-remote');
  const second = JSON.parse(fs.readFileSync(k.registerRemote({
    id: 'example-inbox', instance: 'offered', name: 'Example Inbox', origin: 'https://inbox.example.com', token: 't'.repeat(32), dir,
    runner: offered.runner, peer: offered.peer, installedBy: { by: 'person', role: 'administrator', tool: 'example-inbox register-remote 1.0.0' },
  }), 'utf8'));
  assert.deepEqual([second.runner, second.peer], [offered.runner, offered.peer]);
  assert.throws(() => k.registerRemote({ id: 'example-inbox', instance: 'bad', name: 'X', origin: 'https://inbox.example.com', token: 't'.repeat(32), dir, peer: offered.peer }), /declares runner/);
  assert.equal(k.makeUsageReceipt('example', 'example-model', { inputTokens: 1, outputTokens: 1, route: 'platform-metered' }).route, 'platform-metered');
  assert.throws(() => k.makeUsageReceipt('example', 'example-model', { inputTokens: 1, outputTokens: 1, route: 'metered' }));
  assert.ok(!k.ROUTES.includes('platform-metered'), "a configuration's route stays subscription or key");
});
