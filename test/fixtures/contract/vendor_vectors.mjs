#!/usr/bin/env node
// Vendors the contract's own vectors the kits are held to, re-answered here by the contract's functions so a stale copy
// is caught: fixtures/vectors/hub-key.json (DEC-0060, hubKeyCertified), fixtures/vectors/service-supervisor.json
// (DEC-0057, supervisorMarker and lockWaitBudgetMs) and the fixtures/semantic/service-lock-*.json records (FAC-SEM-078,
// lockOutcomeRules), fixtures/vectors/windows-token.json (DEC-0057, windowsTokenAclProblem, FAC-SEM-079), and
// DEC-0061/0069: fixtures/vectors/service-peer.json (peerRefusal), fixtures/vectors/app-descriptor.json
// (appDescriptorAction, appDescriptorStale), every service descriptor fixture and the FAC-SEM-085/086 semantic ones.
// Never written by hand.
//
//   node test/fixtures/contract/vendor_vectors.mjs --contract <a clean checkout of the contract at the pin>
//     --contract-src <dir with its src/*.ts staged, .js imports rewritten to .ts> [--out test/fixtures/contract]
//
// Needs Node 24 or later (type stripping). The hub keys' private seeds are dropped: the kits verify and never sign.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const out = args.out ?? here;
const src = (file) => import(pathToFileURL(path.join(args['contract-src'], file)).href);
const read = (file) => JSON.parse(fs.readFileSync(path.join(args.contract, file), 'utf8'));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const write = (name, value) => fs.writeFileSync(path.join(out, name), `${JSON.stringify(value, null, 2)}\n`);

const hubKeyRules = await src('hub-key-rules.ts');
const supervisor = await src('service-supervisor.ts');
const windowsToken = await src('windows-token.ts');
const appDescriptor = await src('app-descriptor.ts');
const descriptorRules = await src('descriptor-rules.ts');

// hub-key.json: every case re-answered by hubKeyCertified; seeds dropped.
const hub = read('fixtures/vectors/hub-key.json');
for (const c of hub.cases) {
  const extra = c.extraRevocations === undefined ? undefined : { extraRevocations: c.extraRevocations };
  const answer = hubKeyRules.hubKeyCertified(c.record, c.kid, c.x, c.at, c.applied, extra);
  if (!same(answer, c.expected)) throw new Error(`the contract's hub-key case "${c.name}" no longer answers as written`);
}
const hubKeys = Object.fromEntries(Object.entries(hub.hubKeys).map(([kid, key]) => [kid, Object.fromEntries(Object.entries(key).filter(([name]) => name !== 'seed'))]));
const revisions = Object.fromEntries(Object.entries(hub.revisions).map(([n, r]) => [n, typeof r === 'string' ? read(r) : r]));
write('hub-key-vectors.json', { ...hub, hubKeys, revisions, source: 'fixtures/vectors/hub-key.json' });

// service-supervisor.json: every case re-answered by supervisorMarker and lockWaitBudgetMs.
const sup = read('fixtures/vectors/service-supervisor.json');
for (const c of sup.cases) {
  const marker = supervisor.supervisorMarker({ env: c.env, argv: c.argv });
  const kindAndManager = marker.kind === 'supervised' ? { kind: marker.kind, manager: marker.manager } : { kind: marker.kind };
  if (!same(kindAndManager, c.marker) || supervisor.lockWaitBudgetMs(marker) !== c.waitBudgetMs) throw new Error(`the contract's supervisor case "${c.name}" no longer answers as written`);
}

// FAC-SEM-078: each recorded start with the findings lockOutcomeRules gives it.
const semantic = path.join(args.contract, 'fixtures/semantic');
const records = fs.readdirSync(semantic).filter((f) => /^service-lock-.*\.json$/.test(f)).sort().map((file) => {
  const fixture = JSON.parse(fs.readFileSync(path.join(semantic, file), 'utf8'));
  const { description, ...record } = fixture;
  return { name: file.replace(/\.json$/, ''), description, record, codes: supervisor.lockOutcomeRules(record).map((f) => f.instancePath) };
});
write('supervisor-vectors.json', { ...sup, lockRecords: records, source: 'fixtures/vectors/service-supervisor.json, fixtures/semantic/service-lock-*.json' });
// windows-token.json: every case re-answered by windowsTokenAclProblem.
const win = read('fixtures/vectors/windows-token.json');
for (const c of win.cases) {
  const answer = windowsToken.windowsTokenAclProblem(c.file, win.currentUserSid);
  const want = c.problem === null ? null : { problem: c.problem, ...(c.at === undefined ? {} : { at: c.at }), ...(c.sid === undefined ? {} : { sid: c.sid }) };
  const got = answer === null ? null : { problem: answer.problem, ...(c.at === undefined ? {} : { at: answer.at }), ...(c.sid === undefined ? {} : { sid: answer.sid }) };
  if (!same(got, want)) throw new Error(`the contract's windows-token case "${c.name}" no longer answers as written`);
}
write('windows-token-vectors.json', { ...win, source: 'fixtures/vectors/windows-token.json' });
console.log(`${win.cases.length} windows-token cases`);

// DEC-0057's seven killing fixtures for the descriptor (fixtures/negative, listed invalid in fixtures/catalogue.json).
const catalogue = read('fixtures/catalogue.json');
const DEC57 = ['bad-task', 'bad-unit', 'systemd-with-plist', 'task-scheduler-with-label', 'task-without-task-scheduler', 'unc-forward-slash', 'windows-service-manager'];
const negatives = DEC57.map((name) => {
  const file = `negative/service-descriptor-${name}.json`;
  const entry = catalogue.find((e) => e.path === file);
  if (!entry || entry.valid !== false) throw new Error(`${file} is not an invalid fixture in the catalogue`);
  return { name, descriptor: read(`fixtures/${file}`) };
});
write('descriptor-negatives.json', { about: "DEC-0057's killing fixtures for the service descriptor, which the kits' validate_descriptor/validateDescriptor refuse.", source: 'fixtures/negative/service-descriptor-*.json', negatives });

// DEC-0061: peerRefusal over every case; DEC-0069: appDescriptorAction and appDescriptorStale.
const peer = read('fixtures/vectors/service-peer.json');
for (const c of peer.cases) if (descriptorRules.peerRefusal(c.descriptor, c.dataClass) !== c.refusal) throw new Error(`the contract's peer case "${c.name}" no longer answers as written`);
write('service-peer-vectors.json', { ...peer, source: 'fixtures/vectors/service-peer.json' });
const app = read('fixtures/vectors/app-descriptor.json');
for (const c of app.action) if (appDescriptor.appDescriptorAction(c.existing, c.tool, c.appPath) !== c.expect) throw new Error(`the contract's action case "${c.name}" no longer answers as written`);
for (const c of app.stale) if (appDescriptor.appDescriptorStale(c.descriptor, c.appPresent) !== c.expect) throw new Error(`the contract's stale case "${c.name}" no longer answers as written`);
write('app-descriptor-vectors.json', { ...app, source: 'fixtures/vectors/app-descriptor.json' });

// Every service descriptor fixture, valid or not as the catalogue says, and the FAC-SEM-085/086 semantic fixtures with
// the findings descriptorPeerRules gives them.
const descriptors = catalogue.filter((e) => /(^|\/)service-descriptor-[^/]*\.json$/.test(e.path)).map((e) => ({
  name: e.path.replace(/^.*\/|\.json$/g, ''), valid: e.valid, descriptor: read(`fixtures/${e.path}`),
}));
const semanticDir = path.join(args.contract, 'fixtures/semantic');
const semanticDescriptors = fs.readdirSync(semanticDir).filter((f) => /^service-(descriptor|peer-endpoint)-.*\.json$/.test(f)).sort().map((file) => {
  const fixture = JSON.parse(fs.readFileSync(path.join(semanticDir, file), 'utf8'));
  return { name: file.replace(/\.json$/, ''), document: fixture.document, findings: descriptorRules.descriptorPeerRules(fixture.document).map((f) => ({ code: f.code, instancePath: f.instancePath })) };
});
write('descriptor-fixtures.json', { about: 'Every service-descriptor fixture of the contract at the pin, valid or not as fixtures/catalogue.json says, and the FAC-SEM-085/086 semantic fixtures with the findings descriptorPeerRules gives them.', source: 'fixtures/catalogue.json, fixtures/semantic/service-*', descriptors, semantic: semanticDescriptors });
console.log(`${peer.cases.length} peer cases, ${app.action.length + app.stale.length} app-descriptor cases, ${descriptors.length} descriptor fixtures, ${semanticDescriptors.length} semantic`);
