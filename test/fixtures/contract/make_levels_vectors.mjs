#!/usr/bin/env node
// Vendors the authority levels (DEC-0162) and a place's standing mandate (DEC-0166) from the contract at the pin into
// levels-vectors.json and standing-vectors.json, every answer re-computed here by the contract's own functions so a
// stale copy is caught. Never written by hand.
//
// - fixtures/vectors/levels.json: `verify` (verifyOrgMembership, the named key set and memberships resolved), and
//   `actions` and `mandates` (actionDecision, which reads a level decision through levelStanding and a level mandate
//   through mandateCovers).
// - fixtures/vectors/profile.json: `actions` (actionDecision with `standing`) and `documents` (mandateRules: FAC-SEM-144,
//   FAC-SEM-170 and FAC-SEM-173, as `<code> <instancePath>`).
//
//   <contract>/node_modules/.bin/tsx test/fixtures/contract/make_levels_vectors.mjs --contract <tree> --contract-src <tree>/src
//     [--out test/fixtures/contract]
//
// Run it under the contract's own tsx on a clean tree of the pinned commit (a `git archive`, the checkout's node_modules
// linked beside it), as vendor_vectors.mjs is.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const out = args.out ?? here;
const src = (file) => import(pathToFileURL(path.join(args['contract-src'], file)).href);
const read = (file) => JSON.parse(fs.readFileSync(path.join(args.contract, file), 'utf8'));
const same = (a, b) => JSON.stringify(sorted(a)) === JSON.stringify(sorted(b));
const sorted = (value) => (Array.isArray(value) ? value.map(sorted) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map((k) => [k, sorted(value[k])])) : value);
const pin = JSON.parse(fs.readFileSync(path.join(here, '../../../fabric-contract.lock.json'), 'utf8')).commit;

const { actionDecision } = await src('actions.ts');
const { mandateRules } = await src('mandate.ts');
const { verifyOrgMembership } = await src('org-membership.ts');

const levels = read('fixtures/vectors/levels.json');
const resolved = (v) => {
  const trust = { ...v.trust, now: new Date(v.trust.now), ...(v.trust.keySet === 'keySet' ? { keySet: levels.keySet } : {}) };
  const membership = typeof v.membership === 'string' ? levels.memberships[v.membership] : v.membership;
  return { membership, trust };
};
for (const v of levels.verify) {
  const { membership, trust } = resolved(v);
  if (!same(verifyOrgMembership(membership, trust), v.expected)) throw new Error(`levels verify "${v.name}" no longer answers as written`);
}
for (const group of ['actions', 'mandates']) {
  for (const c of levels[group]) if (!same(actionDecision(c.input), c.expected)) throw new Error(`levels ${group} "${c.name}" no longer answers as written`);
}
const profile = read('fixtures/vectors/profile.json');
for (const c of profile.actions) if (!same(actionDecision(c.input), c.expected)) throw new Error(`profile action "${c.name}" no longer answers as written`);
for (const c of profile.documents) {
  const got = mandateRules('mandate', c.mandate).map((f) => `${f.code} ${f.instancePath}`);
  if (!same(got, c.findings)) throw new Error(`profile document "${c.name}" no longer answers as written`);
}

fs.writeFileSync(path.join(out, 'levels-vectors.json'), `${JSON.stringify({
  about: "Authority levels (DEC-0162) at the pin: the contract's fixtures/vectors/levels.json, each answer re-checked here by verifyOrgMembership and actionDecision. Written by make_levels_vectors.mjs, never by hand.",
  commit: pin, source: 'fixtures/vectors/levels.json, src/levels.ts, src/org-membership.ts, src/actions.ts, src/mandate.ts',
  keySet: levels.keySet, memberships: levels.memberships, digests: levels.digests, verify: levels.verify, actions: levels.actions, mandates: levels.mandates,
}, null, 1)}\n`);
fs.writeFileSync(path.join(out, 'standing-vectors.json'), `${JSON.stringify({
  about: "A place's standing mandate (DEC-0166) at the pin: the contract's fixtures/vectors/profile.json, each answer re-checked here by actionDecision and mandateRules. Written by make_levels_vectors.mjs, never by hand.",
  commit: pin, source: 'fixtures/vectors/profile.json, src/mandate.ts, src/actions.ts',
  actions: profile.actions, documents: profile.documents,
}, null, 1)}\n`);
console.log(`levels-vectors.json: ${levels.verify.length} verify, ${levels.actions.length} actions, ${levels.mandates.length} mandates; standing-vectors.json: ${profile.actions.length} actions, ${profile.documents.length} documents, at ${pin}`);
