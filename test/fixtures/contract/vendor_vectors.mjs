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
const identifiers = await src('identifiers.ts');
const protocolRevisions = await src('protocol-revisions.ts');
const feedData = await src('feed-data.ts');
const semanticRules = await src('semantic-rules.ts');
const commsDigestFn = await src('comms-digest.ts');
const usageRulesModule = await src('usage-rules.ts');
const attribution = await src('openrouter-attribution.ts');

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
// DEC-0076: identifier equality, every case re-answered by normalIdentifier and sameIdentifier.
const ids = read('fixtures/vectors/identifiers.json');
for (const c of [...ids.normal, ...ids.laxPorts]) if (identifiers.normalIdentifier(c.input) !== c.expected) throw new Error(`the contract's identifier case "${c.name}" no longer answers as written`);
for (const [a, b] of ids.same) if (!identifiers.sameIdentifier(a, b)) throw new Error(`the contract's same pair ${a} ${b} no longer answers as written`);
for (const [a, b] of ids.different) if (identifiers.sameIdentifier(a, b)) throw new Error(`the contract's different pair ${a} ${b} no longer answers as written`);
write('identifier-vectors.json', { ...ids, source: 'fixtures/vectors/identifiers.json' });
// DEC-0067: negotiateRevision's cases, the register, and FAC-SEM-099 over lists answered by protocolsFindings.
const negotiation = read('fixtures/vectors/protocol-revisions.json');
for (const c of negotiation.cases) if (!same(protocolRevisions.negotiateRevision(c.received, c.accepted), c.expect)) throw new Error(`the contract's revision case "${c.name}" no longer answers as written`);
const protocolLists = [
  ['fabric-service/0.1'], ['fabric-service/0.1', 'fabric-interop/0.1'], [], 'fabric-service/0.1', ['fabric-service/0.1', 'fabric-service/0.1'],
  ['fabric-service/0.2'], ['Fabric-Service/0.1'], ['fabric-service'], ['other-protocol/3', 'other-protocol/7'], ['other-protocol/1', 'other-protocol/2', 'other-protocol/3'],
  Array.from({ length: 65 }, (_, i) => `p${i}/1`), [7], ['fabric-service/0.1.2.3'], ['other-protocol/1', 'other-protocol/1'],
].map((list) => ({ list, findings: protocolRevisions.protocolsFindings(list).map((f) => ({ code: f.code, instancePath: f.instancePath })) }));
// DEC-0070: every events-page and well-known-protocols fixture as the catalogue lists it, and FAC-SEM-101 over pages.
const pages = catalogue.filter((e) => /service-events-page|service-well-known-protocols/.test(e.path)).map((e) => ({ name: e.path.replace(/^.*\/|\.json$/g, ''), valid: e.valid, document: read(`fixtures/${e.path}`) }));
const ev = (value) => ({ events: [{ id: '1', at: '2026-10-13T08:00:00Z', kind: 'job.done', level: 'info', text: 'A note was drafted.', data: { schema: 'https://example.com/schemas/note.json', value } }], cursor: '1' });
const feedPages = [
  { notes: 3, inputTokens: 1200, title: 'a plain sentence' }, { apiKey: 'abc' }, { token: 7 }, { list: ['ok', 'sk-' + 'a'.repeat(40)] },
  { apiKeys: ['k1', 'k2'] }, { nested: { password: 'p' } }, { nested: { url: 'https://user:pa55@example.com/x' } }, { 'a/b~c': 'ghp_' + 'b'.repeat(36) }, { secrets: { one: 'plain words' } }, { apiKeys: { first: 'x' }, notes: 2 },
].map((value) => ({ page: ev(value), findings: feedData.feedDataFindings(ev(value)).map((f) => ({ code: f.code, instancePath: f.instancePath })) }));
write('feed-protocols-vectors.json', { about: "DEC-0067's negotiateRevision cases and register, FAC-SEM-099 over lists, the events-page and well-known-protocols fixtures, and FAC-SEM-101 over pages, each answered by the contract's functions.",
  source: 'fixtures/vectors/protocol-revisions.json, src/protocol-revisions.ts, src/feed-data.ts, fixtures/catalogue.json',
  register: Object.fromEntries(protocolRevisions.PROTOCOL_REVISIONS), negotiation: negotiation.cases, protocolLists, fixtures: pages, feedPages });
// DEC-0065: OpenRouter attribution, every case re-answered; FAC-SEM-025 whole over the positive usage fixtures and
// edits of the by-project one, each answered by the contract's usageRules.
const attributionVectors = read('fixtures/vectors/openrouter-attribution.json');
for (const c of attributionVectors.cases) if (!same(attribution.attributionHeaders(c.setting, c.request), c.expect)) throw new Error(`the contract's attribution case "${c.name}" no longer answers as written`);
const usagePositive = catalogue.filter((e) => /positive\/service-usage[^/]*\.json$/.test(e.path)).map((e) => [e.path.replace(/^.*\/|\.json$/g, ''), read(`fixtures/${e.path}`)]);
const byProject = read('fixtures/positive/service-usage-by-project.json');
const edited = (name, change) => { const r = JSON.parse(JSON.stringify(byProject)); change(r); return [name, r]; };
const respell = (id) => String(id).replace(/^urn:([^:]+)/i, (_, nid) => `URN:${nid.toUpperCase()}`);
const usageCases = [...usagePositive,
  edited('a project named twice under two spellings (DEC-0076)', (r) => { r.byProject.push({ ...JSON.parse(JSON.stringify(r.byProject[0])), projectId: respell(r.byProject[0].projectId), taskRuns: [] }); }),
  edited('a task run twice in its project', (r) => { const p = r.byProject.find((x) => x.taskRuns?.length); p.taskRuns.push({ ...p.taskRuns[0] }); }),
  edited('task runs hold more calls than the project', (r) => { const p = r.byProject.find((x) => x.taskRuns?.length); p.taskRuns[0].calls = p.calls + 1; }),
  edited('task runs hold more calls than the project, all unpriced', (r) => { const p = r.byProject.find((x) => x.taskRuns?.length); p.taskRuns[0].calls = p.calls + 1; p.taskRuns[0].unpricedCalls = p.calls + 1; p.taskRuns[0].costUsd = null; }),
  edited('task runs cost more than the project (CT-40)', (r) => { const p = r.byProject.find((x) => x.taskRuns?.length && typeof x.costUsd === 'number'); p.taskRuns[0].costUsd = p.costUsd + 1; }),
  edited('projects hold more calls than the days', (r) => { r.byProject[0].calls += 1000; }),
  edited('projects cost more than the days (CT-40)', (r) => { r.byProject[0].costUsd = (r.byProject[0].costUsd ?? 0) + 1000; }),
  edited('an all-unpriced project with a number for its cost', (r) => { r.byProject[0].unpricedCalls = r.byProject[0].calls; r.byProject[0].costUsd = 0; }),
  edited('a day after generatedAt', (r) => { r.days[r.days.length - 1].date = '2026-10-05'; }),
  edited('a day more than 30 days before generatedAt', (r) => { r.days[0].date = '2026-09-03'; }),
  edited('a day that does not exist', (r) => { r.days[0].date = '2026-02-30'; }),
  edited('an unreadable generatedAt', (r) => { r.generatedAt = '2026-10-04 16:00:00'; }),
  edited('days out of order', (r) => { r.days.reverse(); }),
  edited("a day's calls are not its models' sum", (r) => { r.days[0].calls += 1; }),
  edited("a day's cost is not its models' known costs", (r) => { r.days[0].costUsd += 0.5; }),
  // DEC-0091: unmeasuredCalls is bounded by calls in every row, and a day's is the sum of its models'.
  edited('a model row with more unmeasured calls than calls', (r) => { const m = r.days[0].byModel[0]; m.unmeasuredCalls = m.calls + 1; r.days[0].unmeasuredCalls = m.calls + 1; }),
  edited("a day's unmeasured calls are not its models' sum", (r) => { r.days[0].unmeasuredCalls = 1; }),
  edited('unmeasured calls written on the day and its model', (r) => { r.days[0].byModel[0].unmeasuredCalls = 1; r.days[0].unmeasuredCalls = 1; }),
  // A day with no model rows may carry nothing: a cost alone (a number or a numeric string) still names no model.
  ...[['a day with only a cost and no models', 0.5], ['a day with only a cost written as a string and no models', '0.5'], ['a day with no models and a zero cost', 0]].map(([name, cost]) =>
    edited(name, (r) => { const d = r.days[0]; for (const f of ['calls', 'unpricedCalls', 'unmeasuredCalls', 'inputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens']) d[f] = 0; d.byModel = []; d.costUsd = cost; })),
  // Every count of a day and of its first model, and its cost, set to a value the schema refuses: the rules read it as
  // the contract's toNumber does (a numeric string is a number, an object is NaN) and never throw. The field list is the
  // contract's at this pin, written here: a count the contract adds is added here at the repin that brings it.
  ...[['a day whose date is an object whose toString is not a function', (r) => { r.days[0].date = { toString: 1 }; }],
    ['two days whose dates are objects', (r) => { r.days[0].date = { a: 1 }; r.days[1].date = { a: 2 }; }],
    ['a day whose date is a number', (r) => { r.days[0].date = 20261001; }],
    ['a project id that is an object whose toString is not a function', (r) => { r.byProject[0].projectId = { toString: 1 }; }]].map(([name, change]) => edited(name, change)),
  ...['calls', 'unpricedCalls', 'unmeasuredCalls', 'inputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens', 'costUsd'].flatMap((field) =>
    [['the string "2"', '2'], ['a padded hex string', ' 0x1 '], ['a word', 'abc'], ['null', null], ['true', true], ['an empty array', []], ['a one-item array', [1]],
      ['an object', {}], ['an object whose toString is not a function', { toString: 1 }], ['a fraction', 1.5], ['a negative number', -1]].flatMap(([label, value]) => [
      edited(`the day's ${field} is ${label}`, (r) => { r.days[0][field] = value; }),
      edited(`the first model's ${field} is ${label}`, (r) => { r.days[0].byModel[0][field] = value; }),
    ])),
].map(([name, report]) => ({ name, report, findings: usageRulesModule.usageRules(report).map((f) => ({ code: f.code, instancePath: f.instancePath, message: f.message })) }));
// Numbers JavaScript and Python read differently from the same JSON text: a 400-digit integer (Infinity in JavaScript, an
// exact integer in Python), 1e400 (Infinity in both, read differently on the way) and a whole number written with a
// fraction (5 in JavaScript, 5.0 in Python). Each case is the report's text: the contract answers JSON.parse of it and a
// kit parses the same text itself.
const BIG = '1' + '0'.repeat(400);
const usageText = [
  ['a day and its model cost a 400-digit integer', (r) => { r.days[0].costUsd = '@N@'; r.days[0].byModel[0].costUsd = '@N@'; }, BIG],
  ['a project costs a 400-digit integer', (r) => { r.byProject[0].costUsd = '@N@'; }, BIG],
  ['a task run costs a 400-digit integer', (r) => { const p = r.byProject.find((x) => x.taskRuns?.length); p.taskRuns[0].costUsd = '@N@'; }, BIG],
  ['a day and its model cost 1e400', (r) => { r.days[0].costUsd = '@N@'; r.days[0].byModel[0].costUsd = '@N@'; }, '1e400'],
  ["a day's calls are a 400-digit integer", (r) => { r.days[0].calls = '@N@'; }, BIG],
  ['a project costs 2^53 + 1 and its task run 1e16', (r) => { const p = r.byProject.find((x) => x.taskRuns?.length); p.costUsd = '@N@'; p.taskRuns[0].costUsd = 1e16; }, '9007199254740993'],
  ['every call unpriced, written as 5.0, with a cost', (r) => { const m = r.days[0].byModel[0]; m.calls = 5; m.unpricedCalls = '@N@'; m.costUsd = 0.1; }, '5.0'],
  ['calls and unpriced calls written as 5.0', (r) => { const m = r.days[0].byModel[0]; m.calls = '@N@'; m.unpricedCalls = '@N@'; m.costUsd = null; r.days[0].calls = r.days[0].byModel.reduce((n, x, j) => n + (j === 0 ? 5 : x.calls), 0); r.days[0].unpricedCalls = r.days[0].byModel.reduce((n, x, j) => n + (j === 0 ? 5 : (x.unpricedCalls ?? 0)), 0); }, '5.0'],
].map(([name, change, literal]) => {
  const r = JSON.parse(JSON.stringify(byProject));
  change(r);
  const text = JSON.stringify(r).replaceAll('"@N@"', literal);
  return { name, text, findings: usageRulesModule.usageRules(JSON.parse(text)).map((f) => ({ code: f.code, instancePath: f.instancePath, message: f.message })) };
});
write('usage-attribution-vectors.json', { about: "DEC-0065: OpenRouter attribution's cases and FAC-SEM-025 over reports, answered by the contract's attributionHeaders and usageRules.",
  source: 'fixtures/vectors/openrouter-attribution.json, src/usage-rules.ts, fixtures/positive/service-usage*.json', attribution: attributionVectors.cases, usage: usageCases, usageText });
console.log(`${attributionVectors.cases.length} attribution cases, ${usageCases.length} usage reports`);
console.log(`${peer.cases.length} peer cases, ${app.action.length + app.stale.length} app-descriptor cases, ${descriptors.length} descriptor fixtures, ${semanticDescriptors.length} semantic`);

// fabric-project-comms/0.1 (DEC-0022, DEC-0073, DEC-0077; FAA-12b, FAA-40): every comms fixture as the catalogue lists it,
// the commsDigest of every valid argument fixture, and FAC-SEM-107 over directory pages answered by the contract's rule.
const commsFixtures = catalogue.filter((e) => /(^|\/)comms-[^/]*\.json$/.test(e.path)).map((e) => ({
  name: e.path.replace(/^.*\/|\.json$/g, ''), schema: e.schema, valid: e.valid, document: read(`fixtures/${e.path}`),
}));
const ARG_SCHEMAS = { 'comms-enroll.schema.json': 'com.enroll', 'comms-claim.schema.json': 'com.claim', 'comms-fenced.schema.json': 'com.accept',
  'comms-progress.schema.json': 'com.progress', 'comms-effect-begin.schema.json': 'com.effect_begin', 'comms-complete.schema.json': 'com.complete',
  'comms-reconcile.schema.json': 'com.reconcile', 'comms-responder-replace.schema.json': 'com.responder_replace' };
const commsDigests = commsFixtures.filter((f) => f.valid && ARG_SCHEMAS[f.schema]).map((f) => ({ name: f.name, operation: ARG_SCHEMAS[f.schema], args: f.document, digest: commsDigestFn.commsDigest(ARG_SCHEMAS[f.schema], f.document) }));
const dirEntry = (id, capabilities, name = id) => ({ id, name, capabilities: capabilities.map(([capability, responder]) => ({ capability, responder })) });
const dirPage = (...projects) => ({ protocol: 'fabric-project-comms/0.1', snapshot: { readAt: '2026-10-13T10:00:00Z', stale: false }, projects, cursor: null });
const directoryPages = [
  dirPage(dirEntry('proj-a', [['a.b', 'active'], ['a.c', 'absent']]), dirEntry('proj-b', [['a.b', 'stale']])),
  dirPage(),
  dirPage(dirEntry('proj-a', []), dirEntry('proj-b', []), dirEntry('proj-a', [], 'Other name')),
  dirPage(dirEntry('proj-a', []), dirEntry('proj-a', [])),
  dirPage(dirEntry('proj-a', [['a.b', 'active'], ['a.b', 'absent']])),
  dirPage(dirEntry('proj-a', [['a.b', 'active'], ['A.b', 'active']]), dirEntry('Proj-a', [])),
  dirPage(dirEntry('urn:x:A', []), dirEntry('URN:x:A', [])),
  dirPage(dirEntry('proj-a', [['a.b', 'active'], ['a.b', 'stale'], ['a.b', 'absent']]), dirEntry('proj-a', [['a.b', 'active']])),
  {}, { projects: 'x' }, { projects: [null, 3, { id: 7, capabilities: 'x' }, { capabilities: [null, { capability: 7 }] }] },
  { projects: [{ id: 'p', capabilities: [{ capability: 7 }, { capability: 7 }] }, { id: 7 }, { id: 7 }] },
].map((page) => ({ page, findings: semanticRules.evaluateSemanticRules('comms-directory', page).map((f) => ({ code: f.code, instancePath: f.instancePath, message: f.message })) }));
write('comms-vectors.json', { about: "fabric-project-comms/0.1 at the pin: every comms fixture as fixtures/catalogue.json lists it, the commsDigest of each valid responder argument fixture, and FAC-SEM-107 (DEC-0077) over directory pages, each answered by the contract's functions.",
  source: 'fixtures/catalogue.json, fixtures/*/comms-*.json, src/comms-digest.ts, src/semantic-rules.ts',
  fixtures: commsFixtures, digests: commsDigests, directoryPages });
console.log(`${commsFixtures.length} comms fixtures, ${commsDigests.length} digests, ${directoryPages.length} directory pages`);

// fabric-package/1 (DEC-0050, DEC-0051, DEC-0071, DEC-0074; FAA-27a): the contract's package vectors re-answered by its
// packageDigest, packageSigningInput, verifyPackage and checkPackageFolder; every package fixture as the catalogue lists
// it; FAC-SEM-064…066 and FAC-SEM-102 over the semantic ones; and the schema bundled with its outside references, which
// the kits validate against. The vectors' seeds are the contract's published test keys: the kits sign with them in tests.
const packageRules = await src('package-rules.ts');
const packageVectors = read('fixtures/vectors/package.json');
if (packageRules.packageDigest(packageVectors.digest.package) !== packageVectors.digest.expected) throw new Error('stale package digest vector');
if (packageRules.packageSigningInput(packageVectors.signingInput.digest, packageVectors.signingInput.role).toString('utf8') !== packageVectors.signingInput.utf8) throw new Error('stale signing input vector');
const folderFiles = new Map(Object.entries(packageVectors.folder.files).map(([p, text]) => [p, Buffer.from(text, 'utf8')]));
if (!same(packageRules.checkPackageFolder(packageVectors.digest.package, folderFiles), packageVectors.folder.expected)) throw new Error('stale folder vector');
for (const c of packageVectors.cases) {
  if (!same(packageRules.verifyPackage(c.package, c.trust, c.options ?? {}), c.expected)) throw new Error(`stale package case: ${c.name}`);
}
const packageFixtures = catalogue.filter((e) => e.schema === 'fabric-package.schema.json').map((e) => ({ name: e.path.replace(/^.*\/|\.json$/g, ''), valid: e.valid, document: read(`fixtures/${e.path}`) }));
const semanticPackages = fs.readdirSync(path.join(args.contract, 'fixtures/semantic')).filter((f) => /^package-.*\.json$/.test(f)).sort().map((f) => {
  const document = read(`fixtures/semantic/${f}`);
  return { name: f.replace(/\.json$/, ''), document, findings: semanticRules.evaluateSemanticRules('package', document).map((x) => ({ code: x.code, instancePath: x.instancePath })) };
});
for (const f of packageFixtures.filter((x) => x.valid)) {
  const findings = semanticRules.evaluateSemanticRules('package', f.document);
  if (findings.length) throw new Error(`positive package fixture ${f.name} has findings`);
}
// The schema, bundled: each outside $ref (common, service-common, manifest) inlined under $defs, so a kit needs one file.
const schemaFile = (name) => read(`schemas/${name}`);
const bundled = schemaFile('fabric-package.schema.json');
const outside = {};
const pointer = (doc, ref) => ref.split('/').slice(1).reduce((node, token) => node[token.replace(/~1/g, '/').replace(/~0/g, '~')], doc);
// A local '#…' reference inside an outside file means that file: it is qualified before it is inlined.
const inline = (node, from = null) => {
  if (Array.isArray(node)) return node.map((item) => inline(item, from));
  if (!node || typeof node !== 'object') return node;
  const outNode = {};
  for (const [key, value] of Object.entries(node)) {
    const ref = key === '$ref' && typeof value === 'string' ? (value.startsWith('#') && from ? `${from}${value}` : value) : null;
    if (ref && !ref.startsWith('#')) {
      const [file, frag] = ref.split('#');
      const name = `${file.replace(/\.schema\.json$/, '')}${frag.replace(/\//g, '.')}`;
      if (!(name in outside)) { outside[name] = null; outside[name] = inline(pointer(schemaFile(file), frag), file); }
      outNode.$ref = `#/$defs/${name}`;
    } else outNode[key] = inline(value, from);
  }
  return outNode;
};
const resolved = inline(bundled);
resolved.$defs = { ...resolved.$defs, ...outside };
const strip = (node) => (Array.isArray(node) ? node.map(strip) : node && typeof node === 'object'
  ? Object.fromEntries(Object.entries(node).filter(([k]) => !['description', 'title', '$comment'].includes(k)).map(([k, v]) => [k, k === 'properties' || k === '$defs' ? Object.fromEntries(Object.entries(v).map(([pk, pv]) => [pk, strip(pv)])) : strip(v)])) : node);
write('package-vectors.json', { about: "fabric-package/1 at the pin: the contract's vectors (each case re-answered by its verifyPackage), every package fixture as fixtures/catalogue.json lists it, and FAC-SEM-064…066/102 over the semantic package fixtures, answered by the contract's rules.",
  source: 'fixtures/vectors/package.json, fixtures/catalogue.json, fixtures/*/fabric-package-*.json, fixtures/semantic/package-*.json, src/package-rules.ts, src/semantic-rules.ts',
  vectors: packageVectors, fixtures: packageFixtures, semantic: semanticPackages });
fs.writeFileSync(path.join(here, '../../../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-package.schema.json'), `${JSON.stringify(strip(resolved), null, 2)}\n`);
console.log(`${packageVectors.cases.length} package cases, ${packageFixtures.length} package fixtures, ${semanticPackages.length} semantic, schema bundled with ${Object.keys(outside).length} outside definitions`);

// DEC-0079 (FAA-42): the operator's hold matrix, every case re-answered by the contract's holdRefuses, for the kits'
// port that decides locally which of its own calls a known hold would refuse.
const holdModule = await src('comms-hold.ts');
const holdVectors = read('fixtures/vectors/comms-hold.json');
for (const c of holdVectors.cases) {
  if (holdModule.holdRefuses(c.tool, c.target, c.holds) !== c.refused) throw new Error(`stale hold case: ${c.name}`);
}
write('comms-hold-vectors.json', { about: "DEC-0079 at the pin: the hold matrix's cases, each re-answered by the contract's holdRefuses, with the tools, the scopes per tool and the tools a hold never refuses.",
  source: 'fixtures/vectors/comms-hold.json, src/comms-hold.ts',
  tools: holdModule.COMMS_TOOLS, scopes: Object.fromEntries(holdModule.HOLD_SCOPES), neverHeld: holdModule.NEVER_HELD, cases: holdVectors.cases });
console.log(`${holdVectors.cases.length} hold cases`);
