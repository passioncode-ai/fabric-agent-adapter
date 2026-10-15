#!/usr/bin/env node
// Writes route-vectors.json: DEC-0026/DEC-0029 cases whose expected findings come from the contract's own routeRules
// at the pin (src/route-rules.ts, FAC-SEM-028…034) — never written by hand. The kits' fabric_profiles.route_problems
// and fabric-profiles.mjs routeProblems are held to them, code, path and message.
//
//   node test/fixtures/contract/make_route_vectors.mjs --contract-src <dir with route-rules.ts, findings.ts>
//     --positive <dir with runner-route.json, runner-route-event-*.json, binding-runner-route.json>
//     [--out test/fixtures/contract/route-vectors.json]
//
// Needs Node 24 or later (type stripping); the .ts imports are rewritten to .ts in the staged copy.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const { routeRules } = await import(pathToFileURL(path.join(args['contract-src'], 'route-rules.ts')).href);
const read = (file) => JSON.parse(fs.readFileSync(path.join(args.positive, file), 'utf8'));
const clone = (v) => JSON.parse(JSON.stringify(v));

const route = read('runner-route.json');
const selected = read('runner-route-event-selected.json');
const switched = read('runner-route-event-switched.json');
const exhausted = read('runner-route-event-exhausted.json');
const binding = read('binding-runner-route.json');
const ref = (r) => ({ id: r.id, revision: r.revision, contentHash: r.contentHash });
const admissions = route.candidates.map((c) => ({ state: 'admitted', capability: route.capability, provider: clone(c.provider) }));
const catalogue = [
  { kind: 'claude-code', drives: { pty: {}, sdk: {} } }, { kind: 'codex', drives: { 'codex-app-server': {}, pty: {} } },
  { kind: 'kimi-code', drives: { acp: {} } }, { kind: 'hermes', drives: { acp: {} } },
];
const agreeing = { ...clone(binding), runnerRoute: ref(route.meta) };

const cases = [];
const add = (name, kind, value) => cases.push({ name, kind, value, expected: routeRules(kind, value) });
const edit = (base, change) => { const v = clone(base); change(v); return v; };

// FAC-SEM-028, FAC-SEM-029 — the route itself.
add('route: the positive fixture', 'runner-route', route);
add('route: a runner kind twice', 'runner-route', edit(route, (r) => { r.candidates[2].runnerKind = 'codex'; }));
add('route: a candidate that can never run', 'runner-route', edit(route, (r) => { r.candidates[1].session = { attach: 'never', spawn: 'never' }; }));
add('route: no candidates at all', 'runner-route', edit(route, (r) => { r.candidates = []; }));

// FAC-SEM-030, FAC-SEM-032, FAC-SEM-033 — what a host checks when it pins a route.
const bundle = { route, admissions, binding: agreeing, catalogue };
add('bundle: admitted, bound and catalogued', 'route-bundle', bundle);
add('bundle: a candidate not admitted', 'route-bundle', edit(bundle, (b) => { b.admissions.pop(); }));
add('bundle: admitted under another hash', 'route-bundle', edit(bundle, (b) => { b.admissions[1].provider.contentHash = `sha256:${'0'.repeat(64)}`; }));
add('bundle: admitted for another capability', 'route-bundle', edit(bundle, (b) => { b.admissions[0].capability = 'urn:fabric:capability:other'; }));
add('bundle: an admission that was revoked', 'route-bundle', edit(bundle, (b) => { b.admissions[2].state = 'revoked'; }));
add('bundle: the binding is for another project and capability', 'route-bundle', edit(bundle, (b) => { b.binding.project = 'urn:project:b'; b.binding.capability = 'urn:fabric:capability:other'; }));
add('bundle: the binding uses another profile', 'route-bundle', edit(bundle, (b) => { b.binding.profileKind = 'mcp-tool'; }));
add('bundle: the binding binds a provider the route does not name', 'route-bundle', edit(bundle, (b) => { b.binding.provider = { id: 'urn:fabric:provider:other', revision: 1, contentHash: `sha256:${'1'.repeat(64)}` }; }));
add('bundle: the binding pins another route', 'route-bundle', edit(bundle, (b) => { b.binding.runnerRoute.revision = 2; }));
add('bundle: a binding without a runnerRoute', 'route-bundle', edit(bundle, (b) => { delete b.binding.runnerRoute; }));
add('bundle: a kind the catalogue does not have', 'route-bundle', edit(bundle, (b) => { b.catalogue = b.catalogue.filter((e) => e.kind !== 'hermes'); }));
add('bundle: a drive the entry does not offer', 'route-bundle', edit(bundle, (b) => { b.catalogue[1].drives = { pty: {} }; }));
add('bundle: no binding and no catalogue', 'route-bundle', { route, admissions });

// FAC-SEM-034 — an event tells the truth about its route.
add('event: selected (positive)', 'route-event', { route, event: selected });
add('event: switched (positive)', 'route-event', { route, event: switched });
add('event: exhausted (positive)', 'route-event', { route, event: exhausted });
add('event: names another route, project and capability', 'route-event', { route, event: edit(selected, (e) => { e.route.revision = 9; e.project = 'urn:project:b'; e.capability = 'urn:fabric:capability:other'; }) });
add('event: a probe at the wrong position', 'route-event', { route, event: edit(selected, (e) => { e.probes[1].runnerKind = 'hermes'; }) });
add('event: probes out of order', 'route-event', { route, event: edit(selected, (e) => { e.probes.reverse(); }) });
add('event: a probe missing above the selection', 'route-event', { route, event: edit(selected, (e) => { e.probes.splice(1, 1); }) });
add('event: no-held-session for a candidate that may spawn', 'route-event', { route, event: edit(selected, (e) => { e.probes[1].result = 'no-held-session'; }) });
add('event: spawn-failed for a candidate that never spawns', 'route-event', { route, event: edit(selected, (e) => { e.probes[0].result = 'spawn-failed'; }) });
add('event: attached where attach is never', 'route-event', { route, event: edit(selected, (e) => { e.selected.session = 'attached'; }) });
add('event: spawned where spawn is never', 'route-event', { route, event: edit(selected, (e) => {
  e.selected = { index: 0, runnerKind: 'claude-code', provider: clone(route.candidates[0].provider), session: 'spawned', executionContext: e.selected.executionContext };
  e.probes = [];
}) });
add('event: a drive the route does not run it through', 'route-event', { route, event: edit(selected, (e) => { e.selected.drive = 'pty'; }) });
add('event: the selection names another provider', 'route-event', { route, event: edit(selected, (e) => { e.selected.provider.revision = 7; }) });
add('event: an index that is not an integer', 'route-event', { route, event: edit(selected, (e) => { e.selected.index = 2.5; }) });
add('event: a fractional index beside the kind at its floor', 'route-event', { route, event: edit(selected, (e) => { e.selected = { index: 2.5, runnerKind: 'kimi-code', session: 'spawned', executionContext: e.selected.executionContext }; e.probes = e.probes.slice(0, 2); }) });
add('event: sticky, kept and walked nothing', 'route-event', { route, event: edit(selected, (e) => { e.sticky = true; e.probes = []; }) });
add('event: sticky under reprobe, without a conversation, with probes', 'route-event', {
  route: edit(route, (r) => { r.recovery = 'reprobe'; }), event: edit(selected, (e) => { e.sticky = true; delete e.conversation; }),
});
add('event: exhausted that skipped a candidate', 'route-event', { route, event: edit(exhausted, (e) => { e.probes.pop(); }) });
add('event: held without exhausted: hold', 'route-event', { route, event: edit(exhausted, (e) => { e.answer = 'held'; }) });
add('event: held under exhausted: hold', 'route-event', { route: edit(route, (r) => { r.exhausted = 'hold'; }), event: edit(exhausted, (e) => { e.answer = 'held'; }) });
add('event: a switch to the same candidate', 'route-event', { route, event: edit(switched, (e) => { e.from = { index: 2, runnerKind: 'kimi-code' }; }) });
add('event: a switch from a candidate that is not there', 'route-event', { route, event: edit(switched, (e) => { e.from = { index: 9, runnerKind: 'ghost' }; }) });
add('event: preferred-available under sticky recovery', 'route-event', { route, event: edit(switched, (e) => { e.reason = 'preferred-available'; }) });
add('event: preferred-available under reprobe, moving up', 'route-event', { route: edit(route, (r) => { r.recovery = 'reprobe'; }), event: edit(switched, (e) => { e.reason = 'preferred-available'; }) });
add('event: preferred-available under reprobe, moving down', 'route-event', {
  route: edit(route, (r) => { r.recovery = 'reprobe'; }),
  event: edit(switched, (e) => {
    e.reason = 'preferred-available';
    e.from = { index: 1, runnerKind: 'codex' };
    e.selected = { index: 3, runnerKind: 'hermes', provider: clone(route.candidates[3].provider), drive: 'acp', session: 'spawned', executionContext: e.selected.executionContext };
    e.probes = [{ index: 0, runnerKind: 'claude-code', result: 'no-held-session' }, { index: 1, runnerKind: 'codex', result: 'not-installed' }, { index: 2, runnerKind: 'kimi-code', result: 'not-connected' }];
  }),
});
add('event: not an object', 'route-event', 'not an object');

// DEC-0076: identifiers compare by normal form. Each case respells an id the fixtures write in normal form — `urn` and the
// NID upper-cased, which RFC 8141 §3.1 lower-cases — so a kit that compares bytes fails here; the last two change the NSS's
// case, which stays significant.
const respell = (id) => String(id).replace(/^urn:([^:]+)/i, (_, nid) => `URN:${nid.toUpperCase()}`);
add('bundle: an admission for the capability spelled otherwise (DEC-0076)', 'route-bundle', edit(bundle, (b) => { b.admissions.forEach((a) => { a.capability = respell(a.capability); }); }));
add('bundle: admissions naming the providers spelled otherwise (DEC-0076)', 'route-bundle', edit(bundle, (b) => { b.admissions.forEach((a) => { a.provider.id = respell(a.provider.id); }); }));
add('bundle: the binding\'s project, capability, provider and route spelled otherwise (DEC-0076)', 'route-bundle', edit(bundle, (b) => {
  b.binding.project = respell(b.binding.project); b.binding.capability = respell(b.binding.capability);
  b.binding.provider.id = respell(b.binding.provider.id); b.binding.runnerRoute.id = respell(b.binding.runnerRoute.id);
}));
add('event: the route, project and capability spelled otherwise (DEC-0076)', 'route-event', { route, event: edit(selected, (e) => {
  e.route.id = respell(e.route.id); e.project = respell(e.project); e.capability = respell(e.capability);
  if (e.selected?.provider) e.selected.provider.id = respell(e.selected.provider.id);
}) });
add('bundle: the binding\'s project in another case of its NSS is another project (DEC-0076)', 'route-bundle', edit(bundle, (b) => { b.binding.project = b.binding.project.replace(/[a-z]+$/, (s) => s.toUpperCase()); }));
add('event: the capability in another case of its NSS is another capability (DEC-0076)', 'route-event', { route, event: edit(selected, (e) => { e.capability = e.capability.replace(/[a-z-]+$/, (s) => s.toUpperCase()); }) });

// Hostile JSON (the contract's rules show a value whose own toString is data as its JSON, and compare with ===, so 1
// and true differ and null is not absent): every rule answered as the contract answers it, never by a throw.
{
  const hostile = { toString: 1 };
  add('hostile: a runner kind with its own toString, twice', 'runner-route', edit(route, (r) => { r.candidates[0].runnerKind = hostile; r.candidates[1].runnerKind = { toString: 1 }; }));
  add('hostile: runner kinds null and absent are two kinds', 'runner-route', edit(route, (r) => { r.candidates[0].runnerKind = null; delete r.candidates[1].runnerKind; }));
  add('hostile: runner kinds true and "true" show the same', 'runner-route', edit(route, (r) => { r.candidates[0].runnerKind = true; r.candidates[1].runnerKind = 'true'; }));
  add('hostile: a provider revision with its own toString', 'route-bundle', edit(bundle, (b) => { b.route.candidates[0].provider.revision = hostile; }));
  add('hostile: the route capability with its own toString', 'route-bundle', edit(bundle, (b) => { b.route.capability = hostile; }));
  add('hostile: a binding profile kind and project with their own toString', 'route-bundle', edit(bundle, (b) => { b.binding.profileKind = hostile; b.binding.project = hostile; }));
  add('hostile: a catalogue kind and a candidate drive with their own toString', 'route-bundle', edit(bundle, (b) => { b.catalogue[0].kind = hostile; b.route.candidates[0].drive = hostile; }));
  add('hostile: a revision null against one absent', 'route-bundle', edit(bundle, (b) => { b.route.candidates[0].provider.revision = null; delete b.admissions[0].provider.revision; }));
  const at = selected.selected.index;
  add('hostile: the selected runner kind true against a candidate kind 1', 'route-event', { route: edit(route, (r) => { r.candidates[at].runnerKind = 1; }), event: edit(selected, (e) => { e.selected.runnerKind = true; }) });
  add('hostile: the selected runner kind null against one absent', 'route-event', { route: edit(route, (r) => { delete r.candidates[at].runnerKind; }), event: edit(selected, (e) => { e.selected.runnerKind = null; }) });
  add('hostile: the selected drive true against the candidate drive 1', 'route-event', { route: edit(route, (r) => { r.candidates[at].drive = 1; }), event: edit(selected, (e) => { e.selected.drive = true; }) });
  add('hostile: the event project and capability with their own toString', 'route-event', { route, event: edit(selected, (e) => { e.project = hostile; e.capability = { toString: 1 }; }) });
  add('hostile: a selected runner kind and index with their own toString', 'route-event', { route, event: edit(selected, (e) => { e.selected.runnerKind = hostile; e.selected.index = { toString: 1 }; }) });
}

// JSON a JavaScript object cannot carry as written (see make_profile_vectors.mjs): the case keeps `valueText`, and the
// contract answers JSON.parse of it.
{
  const raw = (name, kind, object, literals = {}) => {
    let text = JSON.stringify(object);
    for (const [mark, literal] of Object.entries(literals)) text = text.split(JSON.stringify(`@@${mark}@@`)).join(literal);
    const value = JSON.parse(text);
    cases.push({ name: `raw: ${name}`, kind, value, valueText: text, expected: routeRules(kind, value) });
  };
  const at = selected.selected.index;
  raw('two runner kinds whose number-like key comes first only in JavaScript', 'runner-route', edit(route, (r) => { r.candidates[0].runnerKind = '@@a@@'; r.candidates[1].runnerKind = '@@b@@'; }), { a: '{"toString":1,"1":0}', b: '{"1":0,"toString":1}' });
  raw('a candidate drive with its own toString and a lone surrogate', 'route-bundle', edit(bundle, (b) => { b.route.candidates[0].drive = { toString: 1, x: '\udc00' }; }));
  raw('a binding capability 2**53+1 against the route 2**53', 'route-bundle', edit(bundle, (b) => { b.binding.capability = '@@a@@'; b.route.capability = '@@b@@'; }), { a: '9007199254740993', b: '9007199254740992' });
  raw('a selected runner kind 2**53+1 against the candidate 2**53', 'route-event', { route: edit(route, (r) => { r.candidates[at].runnerKind = '@@b@@'; }), event: edit(selected, (e) => { e.selected.runnerKind = '@@a@@'; }) }, { a: '9007199254740993', b: '9007199254740992' });
  raw('a selected drive 2**53+1 against the candidate drive 2**53', 'route-event', { route: edit(route, (r) => { r.candidates[at].drive = '@@b@@'; }), event: edit(selected, (e) => { e.selected.drive = '@@a@@'; }) }, { a: '9007199254740993', b: '9007199254740992' });
  for (const [label, literal] of [['of 401 digits', `1${'0'.repeat(400)}`], ['1e21', '1e21'], ['2**53+1', '9007199254740993']]) {
    raw(`a probe index ${label}`, 'route-event', { route, event: edit(selected, (e) => { (e.probes ??= []).unshift({ ...e.selected, index: '@@i@@' }); }) }, { i: literal });
  }
}

const out = args.out ?? path.join(here, 'route-vectors.json');
fs.writeFileSync(out, `${JSON.stringify({
  $comment: 'Generated by make_route_vectors.mjs from the contract pin\'s src/route-rules.ts (routeRules, FAC-SEM-028…034); do not edit by hand.',
  cases,
}, null, 2)}\n`);
console.log(`wrote ${cases.length} cases, ${cases.reduce((n, c) => n + (c.expected?.length ?? 0), 0)} findings, to ${out}`);
