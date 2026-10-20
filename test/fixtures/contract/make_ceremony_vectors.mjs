#!/usr/bin/env node
// Writes ceremony-vectors.json: the headless join of the estate ceremonies (DEC-0084), the contract's
// fixtures/vectors/enroll-token.json (group verify) and every fixtures/semantic/enroll-token-*.json, each answered again
// here by the contract's own functions (verifyEnrollToken, enrollJoinInput, enrollTokenRules in src/enroll-token.ts),
// plus hostile variants. Never written by hand. The kits' fabric_ceremonies.py and fabric-ceremonies.mjs are held to it.
//
//   node test/fixtures/contract/make_ceremony_vectors.mjs --contract <a clean checkout of the contract at the pin>
//     --contract-src <dir with its src/*.ts staged, .js imports rewritten to .ts> [--out test/fixtures/contract]
//
// Needs Node 24 or later (type stripping).

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const out = args.out ?? here;
const enroll = await import(pathToFileURL(path.join(args['contract-src'], 'enroll-token.ts')).href);
const pairing = await import(pathToFileURL(path.join(args['contract-src'], 'pairing.ts')).href);
const read = (file) => JSON.parse(fs.readFileSync(path.join(args.contract, file), 'utf8'));
const clone = (v) => JSON.parse(JSON.stringify(v));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const check = (group, c, actual, expected) => { if (!same(actual, expected)) throw new Error(`the contract's ${group} case "${c.name}" no longer answers as written`); };

const vectors = read('fixtures/vectors/enroll-token.json');
const record = read(vectors.record);
const verify = vectors.verify.map((c) => {
  const answer = enroll.verifyEnrollToken(c.token, { record: c.record ?? record, genesis: vectors.genesis, at: new Date(c.at) });
  if (!same(answer, c.answer)) throw new Error(`the contract's verify case "${c.name}" no longer answers as written`);
  return { ...c, joinInput: enroll.enrollJoinInput(c.token) ?? null };
});
const good = vectors.verify.find((c) => c.answer.ok === true).token;
for (const [name, edit, at] of [
  ['the clock is not a date', (t) => t, 'not a time'],
  ['a token that is a list', () => [good], '2026-10-15T09:00:00Z'],
  ['a signature member beside the statement', (t) => { t.note = 'x'; return t; }, '2026-10-15T09:00:00Z'],
  ['a statement value changed after signing', (t) => { t.statement.uses = 2; return t; }, '2026-10-15T09:00:00Z'],
  ['a credential id that is a number', (t) => { t.signature.credentialId = 7; return t; }, '2026-10-15T09:00:00Z'],
  ['uses true after signing', (t) => { t.statement.uses = true; return t; }, '2026-10-15T09:00:00Z'],
  ['one minute and one millisecond before notBefore', (t) => t, '2026-10-15T08:58:59.999Z'],
  ['one minute before notBefore', (t) => t, '2026-10-15T08:59:00Z'],
  ['at expiresAt', (t) => t, '2026-10-15T09:15:00Z'],
  ['a millisecond after expiresAt', (t) => t, '2026-10-15T09:15:00.001Z'],
]) {
  const token = edit(clone(good));
  const clock = new Date(at);
  verify.push({ name: `hostile: ${name}`, token, at, answer: enroll.verifyEnrollToken(token, { record, genesis: vectors.genesis, at: clock }), joinInput: enroll.enrollJoinInput(token) ?? null });
}
for (const [name, rpId] of [['a passkey whose RP is no signing RP', 'example.com'], ['a passkey whose RP is a number', 7]]) {
  const r = clone(record);
  for (const a of r.authorities ?? []) a.rpId = rpId;
  verify.push({ name: `hostile: ${name}`, token: good, at: '2026-10-15T09:00:00Z', record: r,
    answer: enroll.verifyEnrollToken(good, { record: r, genesis: vectors.genesis, at: new Date('2026-10-15T09:00:00Z') }), joinInput: enroll.enrollJoinInput(good) ?? null });
}
verify.push({ name: 'hostile: a record with no estate', token: good, at: '2026-10-15T09:00:00Z', record: { ...clone(record), estate: 7 },
  answer: enroll.verifyEnrollToken(good, { record: { ...clone(record), estate: 7 }, genesis: vectors.genesis, at: new Date('2026-10-15T09:00:00Z') }), joinInput: enroll.enrollJoinInput(good) ?? null });

const dir = path.join(args.contract, 'fixtures/semantic');
const rules = fs.readdirSync(dir).filter((f) => f.startsWith('enroll-token-') && f.endsWith('.json')).sort().map((file) => {
  const fixture = JSON.parse(fs.readFileSync(path.join(dir, file), 'utf8'));
  const expected = enroll.enrollTokenRules(fixture.kind, fixture.input);
  if (!same([...new Set(expected.map((f) => f.code))].sort(), [...fixture.expect].sort())) throw new Error(`${file}: the contract's rules disagree with its expect`);
  return { name: file, kind: fixture.kind, value: fixture.input, expected };
});
for (const [name, edit] of [
  ['a statement that is a list', (t) => { t.statement = [t.statement]; }],
  ['uses true', (t) => { t.statement.uses = true; }],
  ['a nonce of 31 bytes', (t) => { t.statement.nonce = t.statement.nonce.slice(0, 42); }],
  ['a scope with an upper-case prefix', (t) => { t.statement.scope = t.statement.scope.replace('estate:', 'Estate:'); }],
  ['a ceiling that is not a digest', (t) => { t.statement.ceiling = 'sha256:x'; }],
  ['exactly 900 seconds', (t) => { t.statement.expiresAt = '2026-10-15T09:15:00Z'; }],
  ['an offset window of 900 seconds', (t) => { t.statement.notBefore = '2026-10-15T11:00:00+02:00'; t.statement.expiresAt = '2026-10-15T09:15:00Z'; }],
  ['expiresAt before notBefore', (t) => { t.statement.expiresAt = '2026-10-15T08:59:00Z'; }],
  ['a leap second', (t) => { t.statement.notBefore = '2016-12-31T23:59:60Z'; }],
  ['an expiry on a day that does not exist', (t) => { t.statement.expiresAt = '2026-02-30T09:15:00Z'; }],
  ['no expiry', (t) => { delete t.statement.expiresAt; }],
]) { const value = clone(good); edit(value); rules.push({ name: `hostile: ${name}`, kind: 'enroll-token', value, expected: enroll.enrollTokenRules('enroll-token', value) }); }

// The hub's single use of a token (redeem): the ledger is a list of [nonce, entry] pairs, a Map in the contract.
const redeem = vectors.redeem.map((c) => {
  check('redeem', c, enroll.redeemEnrollToken(c.token, c.machineKey, c.proof, new Map(c.ledger)), c.answer);
  return c;
});

// A high-S twin of the first ES256 proof: the same signature with s' = n - s verifies under plain ECDSA, and the
// contract refuses it (low-S only, as relay-auth/1).
{
  const N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551n;
  const base = vectors.redeem.find((c) => c.answer.ok === true && c.machineKey.alg === 'es256');
  const raw = Buffer.from(base.proof, 'base64url');
  const high = N - BigInt(`0x${raw.subarray(32).toString('hex')}`);
  const proof = Buffer.concat([raw.subarray(0, 32), Buffer.from(high.toString(16).padStart(64, '0'), 'hex')]).toString('base64url');
  const answer = enroll.redeemEnrollToken(base.token, base.machineKey, proof, new Map());
  if (answer.ok) throw new Error('the contract accepted a high-S proof');
  redeem.push({ name: 'hostile: the same ES256 proof in its high-S form', token: base.token, machineKey: base.machineKey, proof, ledger: [], answer });
}

// The nearby pairing (fixtures/vectors/pairing.json), every group re-answered by src/pairing.ts.
const pv = read('fixtures/vectors/pairing.json');
const date = (text) => new Date(text);
const groups = {
  commits: (c) => pairing.pairingCommit(c.side),
  reveals: (c) => pairing.checkReveal(c.commit, c.reveal, c.expected ?? undefined),
  codes: (c) => pairing.comparisonCode(c.new, c.trusted),
  checkedCodes: (c) => pairing.checkedComparisonCode(c.newCommit, c.new, c.trustedCommit, c.trusted),
  fingerprints: (c) => pairing.estateFingerprint(c.digest),
  rendezvous: (c) => pairing.rendezvousVerdict(c.openedAt, c.messages, date(c.at)),
  join: (c) => pairing.joinListed(c.record, c.new, c.trusted, c.genesis),
  ownKeys: (c) => pairing.ownKeysDecision(c.record, c.machine, c.held),
};
const pairingCases = Object.fromEntries(Object.entries(groups).map(([group, run]) => [group, pv[group].map((c) => { check(group, c, run(c), c.answer); return c; })]));

fs.writeFileSync(path.join(out, 'ceremony-vectors.json'), `${JSON.stringify({ about: vectors.about, source: 'fixtures/vectors/enroll-token.json (verify) and fixtures/semantic/enroll-token-*.json', record, genesis: vectors.genesis, verify, rules, redeem, pairing: pairingCases, pairingAbout: pv.about }, null, 2)}\n`);
console.log(`ceremony-vectors.json: ${verify.length} verify, ${rules.length} rule, ${redeem.length} redeem, ${Object.entries(pairingCases).map(([g, l]) => `${l.length} ${g}`).join(', ')}`);
