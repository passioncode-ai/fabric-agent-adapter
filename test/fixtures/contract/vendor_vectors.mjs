#!/usr/bin/env node
// Vendors the contract's own vectors the kits are held to, re-answered here by the contract's functions so a stale copy
// is caught: fixtures/vectors/hub-key.json (DEC-0060, hubKeyCertified), fixtures/vectors/service-supervisor.json
// (DEC-0057, supervisorMarker and lockWaitBudgetMs) and the fixtures/semantic/service-lock-*.json records (FAC-SEM-078,
// lockOutcomeRules) and fixtures/vectors/windows-token.json (DEC-0057, windowsTokenAclProblem, FAC-SEM-079). Never
// written by hand.
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
console.log(`wrote ${hub.cases.length} hub-key cases, ${hub.verifier.length} verifier answers; ${sup.cases.length} marker cases, ${records.length} lock records`);
