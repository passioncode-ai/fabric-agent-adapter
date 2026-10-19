#!/usr/bin/env node
// Writes share-vectors.json and the kits' self-contained share-registration.schema.json: share registrations and the
// grant's context on grant.usage (DEC-0086). The cases are the contract's own: fixtures/vectors/share-registration.json
// (group grantId), every fixtures/semantic/share-*.json (FAC-SEM-117 on a grant and on a record with its parent,
// FAC-SEM-118 on a registration document) and the device-attribution-*.json fixtures (FAC-SEM-045's grant.usage clause),
// each answered again here by the contract's functions at the pin, plus hostile variants. Never written by hand. The
// kits' fabric_share.py and fabric-share.mjs are held to it.
//
//   node test/fixtures/contract/make_share_vectors.mjs --contract <a clean checkout of the contract at the pin>
//     --contract-src <dir with its src/*.ts staged, .js imports rewritten to .ts> [--out test/fixtures/contract]
//     [--schema-out plugins/fabric-agent-adapter/skills/building-fabric-services/scripts]
//
// Needs Node 24 or later (type stripping).

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const out = args.out ?? here;
const schemaOut = args['schema-out'] ?? path.join(here, '../../../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts');
const src = (file) => import(pathToFileURL(path.join(args['contract-src'], file)).href);
const share = await src('share-registration.ts');
const contextRules = await src('context-rules.ts');
const deviceRules = await src('device-rules.ts');
const read = (file) => JSON.parse(fs.readFileSync(path.join(args.contract, file), 'utf8'));
const clone = (v) => JSON.parse(JSON.stringify(v));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// grantId: isShareGrantId over the contract's cases.
const vectors = read('fixtures/vectors/share-registration.json');
const grantId = vectors.grantId.map((c) => {
  if (share.isShareGrantId(c.value) !== c.ok) throw new Error(`the contract's grantId case "${c.name}" no longer answers as written`);
  return { name: c.name, value: c.value, ok: c.ok };
});
const orgContext = ['org:org-7f3a', 'org:A_b-9', 'org:', 'org:-x', 'org:x\n', 'ORG:x', 'personal', `org:${'a'.repeat(128)}`, `org:${'a'.repeat(129)}`, 7, null]
  .map((value) => ({ value, ok: share.isOrgContext(value) }));

// The rules: kind grant (FAC-SEM-110 and 117, as contextRules answers), org-share-grants (117 with parent) and
// share-registration (118's document clauses), each fixture as written and varied.
const findingsOf = (kind, value) => (kind === 'grant' ? contextRules.contextRules('grant', value) : share.shareRegistrationRules(kind, value));
const dir = path.join(args.contract, 'fixtures/semantic');
const rules = [];
const add = (name, kind, value) => rules.push({ name, kind, value, expected: findingsOf(kind, value) });
for (const file of fs.readdirSync(dir).filter((f) => f.startsWith('share-') && f.endsWith('.json')).sort()) {
  const fixture = JSON.parse(fs.readFileSync(path.join(dir, file), 'utf8'));
  if (!['grant', 'org-share-grants', 'share-registration'].includes(fixture.kind)) continue;
  const expected = findingsOf(fixture.kind, fixture.input);
  if (!same([...new Set(expected.map((f) => f.code))].sort(), [...fixture.expect].sort())) throw new Error(`${file}: the contract's rules disagree with its expect`);
  add(file, fixture.kind, fixture.input);
}
const fixtureInput = (file) => JSON.parse(fs.readFileSync(path.join(dir, file), 'utf8')).input;
const grantOk = JSON.parse(fs.readFileSync(path.join(dir, 'share-org-grants-ok.json'), 'utf8')).input;
const parentOk = JSON.parse(fs.readFileSync(path.join(dir, 'share-org-grants-parent-ok.json'), 'utf8')).input;
const registrationOk = JSON.parse(fs.readFileSync(path.join(dir, 'share-registration-ok.json'), 'utf8')).input;
const withdrawnOk = JSON.parse(fs.readFileSync(path.join(dir, 'share-registration-withdrawn-ok.json'), 'utf8')).input;
const grant0 = grantOk.record.shareGrants.find((g) => typeof g.context === 'string' && g.context.startsWith('org:'));
const hostile = { toString: 'data' };
for (const [name, value] of [
  ['a personal grant with any id', { ...clone(grant0), context: 'personal', meta: { id: 'urn:example:grant:1' } }],
  ['an org grant with an upper-case id', { ...clone(grant0), meta: { id: grant0.meta.id.toUpperCase().replace('URN:FABRIC:SHARE:', 'urn:fabric:share:') } }],
  ['an org grant with a trailing newline', { ...clone(grant0), meta: { id: `${grant0.meta.id}\n` } }],
  ['an org grant with no meta', { ...clone(grant0), meta: undefined }],
  ['an org grant whose meta is a list', { ...clone(grant0), meta: [grant0.meta.id] }],
  ['an org grant whose window has six fraction digits', { ...clone(grant0), startsAt: '2026-10-14T09:00:00.123456Z', expiresAt: '2026-11-14T09:00:00.1Z' }],
  ['a context that is not a string', { ...clone(grant0), context: ['org:x'] }],
  ['a context with its own toString', { ...clone(grant0), context: hostile }],
  ['not an object', 'grant'],
]) add(`hostile grant: ${name}`, 'grant', JSON.parse(JSON.stringify(value ?? null)));
const twoAgents = clone(grantOk);
for (const [name, value] of [
  ['no record', {}],
  ['shareGrants not a list', { record: { ...clone(grantOk.record), shareGrants: { 0: grant0 } } }],
  ['a non-object before the grants', { record: { ...clone(grantOk.record), shareGrants: [7, ...clone(grantOk.record.shareGrants)] } }],
  ['the grant named under another spelling by a placement', (() => { const v = clone(twoAgents); for (const m of v.record.machines ?? []) for (const p of m.packages ?? []) if (typeof p.grant === 'string') p.grant = p.grant.replace('urn:', 'URN:'); return v; })()],
  ['the parent is not an object', { ...clone(parentOk), parent: 'revision 6' }],
  ['the parent lists the grant in another context', (() => { const v = clone(parentOk); for (const g of v.parent?.shareGrants ?? []) g.context = 'org:other'; return v; })()],
  ['two placements name the grant under two spellings', (() => { const v = fixtureInput('share-org-grants-two-agents.json'); const id = v.record.shareGrants[1].meta.id; const naming = (v.record.machines ?? []).flatMap((m) => m.packages ?? []).filter((p) => p.grant === id); naming[naming.length - 1].grant = id.replace('urn:fabric:share:', 'URN:fabric:share:'); return v; })()],
  ['the parent ran the grant in another context', (() => { const v = fixtureInput('share-org-grants-repointed.json'); const id = v.record.shareGrants[1].meta.id; for (const g of v.parent.shareGrants ?? []) if (g.meta?.id === id) g.context = 'org:other'; for (const m of v.parent.machines ?? []) for (const p of m.packages ?? []) if (p.grant === id) p.context = 'org:other'; return v; })()],
]) add(`hostile record: ${name}`, 'org-share-grants', value);
for (const [name, value] of [
  ['the window has an offset', { ...clone(registrationOk), startsAt: '2026-10-14T11:00:00+02:00' }],
  ['a lower-case t and z', { ...clone(registrationOk), startsAt: '2026-10-14t09:00:00z' }],
  ['four fraction digits', { ...clone(registrationOk), expiresAt: '2026-11-14T09:00:00.1234Z' }],
  ['a leap second', { ...clone(registrationOk), expiresAt: '2026-12-31T23:59:60Z' }],
  ['an empty window', { ...clone(registrationOk), expiresAt: registrationOk.startsAt }],
  ['withdrawn on a day that does not exist', { ...clone(withdrawnOk), withdrawnAt: '2026-02-29T10:00:00Z' }],
  ['withdrawn with no time', (() => { const v = clone(withdrawnOk); delete v.withdrawnAt; return v; })()],
  ['another type', { ...clone(registrationOk), type: 'share-registration/2', expiresAt: 'never' }],
]) add(`hostile registration: ${name}`, 'share-registration', value);

// FAC-SEM-045, the grant.usage clause DEC-0086 adds: the contract's device-attribution findings at .../data/context.
const clause = (value) => deviceRules.deviceRules('device-attribution', value).filter((f) => /\/data\/context$/.test(f.instancePath));
const attribution = [];
for (const file of fs.readdirSync(dir).filter((f) => f.startsWith('device-attribution-') && f.endsWith('.json')).sort()) {
  const input = JSON.parse(fs.readFileSync(path.join(dir, file), 'utf8')).input;
  attribution.push({ name: file, value: input, expected: clause(input) });
}
const usageOk = JSON.parse(fs.readFileSync(path.join(dir, 'device-attribution-grant-usage-ok.json'), 'utf8')).input;
for (const [name, edit] of [
  ['no org on the binding', (v) => { delete v.binding.org; }],
  ['an org id that is a number', (v) => { v.binding.org.id = 7; }],
  ['a usage with no data', (v) => { for (const e of v.batch.events) if (e.kind === 'grant.usage') delete e.data; }],
  ['a usage whose context is personal', (v) => { for (const e of v.batch.events) if (e.kind === 'grant.usage') e.data.context = 'personal'; }],
  ['a usage whose context is the org id without org:', (v) => { for (const e of v.batch.events) if (e.kind === 'grant.usage') e.data.context = v.binding.org.id; }],
  ['events not a list', (v) => { v.batch.events = { 0: v.batch.events[0] }; }],
  ['a non-object before the usage', (v) => { v.batch.events.unshift(7, null); v.binding.org.id = 'org-other'; }],
  ['no batch', (v) => { delete v.batch; }],
]) { const value = clone(usageOk); edit(value); attribution.push({ name: `hostile: ${name}`, value, expected: clause(value) }); }

// The kits' copy of share-registration.schema.json: the contract's file, its three outside definitions brought in.
const schema = read('schemas/share-registration.schema.json');
const common = read('schemas/common.schema.json');
const pkg = read('schemas/fabric-package.schema.json');
const bring = { 'common.schema.json#/$defs/orgContextId': ['orgContextId', common.$defs.orgContextId], 'common.schema.json#/$defs/sha256': ['sha256', common.$defs.sha256],
  'common.schema.json#/$defs/shareGrantId': ['shareGrantId', common.$defs.shareGrantId], 'fabric-package.schema.json#/$defs/agentRef': ['agentRef', pkg.$defs.agentRef] };
const walk = (node) => {
  if (Array.isArray(node)) return node.map(walk);
  if (node === null || typeof node !== 'object') return node;
  return Object.fromEntries(Object.entries(node).map(([k, v]) => [k, k === '$ref' && bring[v] ? `#/$defs/${bring[v][0]}` : walk(v)]));
};
const vendored = walk(schema);
for (const [name, def] of Object.values(bring)) {
  if (name in vendored.$defs) throw new Error(`share-registration.schema.json already defines ${name}`);
  vendored.$defs[name] = def;
}
const leftover = JSON.stringify(vendored).match(/"\$ref":"[^#][^"]*"/g);
if (leftover) throw new Error(`a reference outside the copy is left: ${leftover.join(', ')}`);

fs.writeFileSync(path.join(schemaOut, 'share-registration.schema.json'), `${JSON.stringify(vendored, null, 2)}\n`);
fs.writeFileSync(path.join(out, 'share-vectors.json'), `${JSON.stringify({ source: 'fixtures/vectors/share-registration.json (grantId), fixtures/semantic/share-*.json and device-attribution-*.json', grantId, orgContext, rules, attribution }, null, 2)}\n`);
console.log(`share-vectors.json: ${grantId.length} grantId, ${orgContext.length} orgContext, ${rules.length} rule cases, ${attribution.length} attribution cases`);
