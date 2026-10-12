#!/usr/bin/env node
// Writes estate-vectors.json: estate-record/1 (DEC-0055) cases whose expected answers come from the contract's own
// functions at the pin — verifyEstateRecord, estateRecordRules (FAC-SEM-072…076), estateRecordDigest, estateChallenge,
// placementTrust (src/estate-record-rules.ts), verifyAssertion and credentialKey (src/webauthn.ts) and isValidP256Key
// (src/p256.ts) — never written by hand. The kits' fabric_estate.py and fabric-estate.mjs are held to them.
//
//   node test/fixtures/contract/make_estate_vectors.mjs --contract-src <dir with the staged .ts sources>
//     --vectors <fixtures/vectors/estate-record.json> --semantic <dir of the fixtures/semantic/estate-*.json files>
//     --positive <dir with estate-record-first.json, estate-record-second.json, fabric-package-agent.json>
//     [--out test/fixtures/contract/estate-vectors.json]
//
// Needs Node 24 or later (type stripping); the staged sources import each other as .ts. The contract's vectors carry
// the private test keys that made their signatures; they are dropped here: the kits verify and never sign.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const src = (file) => import(pathToFileURL(path.join(args['contract-src'], file)).href);
const estate = await src('estate-record-rules.ts');
const webauthn = await src('webauthn.ts');
const p256 = await src('p256.ts');
const read = (file) => JSON.parse(fs.readFileSync(file, 'utf8'));
const clone = (v) => JSON.parse(JSON.stringify(v));
const contract = read(args.vectors);

// verifyEstateRecord: the contract's own cases, re-answered here so a stale copy is caught.
const verify = contract.cases.map((c) => {
  const trust = { ...c.trust, at: c.trust.at === null || c.trust.at === undefined ? c.trust.at : new Date(c.trust.at) };
  const answer = estate.verifyEstateRecord(c.record, trust);
  if (JSON.stringify(answer) !== JSON.stringify(c.expected)) throw new Error(`the contract's vector "${c.name}" no longer answers as written`);
  return { name: c.name, record: c.record, trust: c.trust, expected: answer };
});

// estateRecordRules: every estate semantic fixture, through the contract's own rules.
const rules = fs.readdirSync(args.semantic).filter((f) => f.endsWith('.json')).sort().map((file) => {
  const fixture = read(path.join(args.semantic, file));
  const expected = estate.estateRecordRules(fixture.kind, fixture.input);
  const codes = [...new Set(expected.map((f) => f.code))].sort();
  if (JSON.stringify(codes) !== JSON.stringify([...fixture.expect].sort())) throw new Error(`${file}: the rules answer ${codes}, the fixture expects ${fixture.expect}`);
  return { name: file, kind: fixture.kind, value: fixture.input, expected };
});
const first = read(path.join(args.positive, 'estate-record-first.json'));
const second = read(path.join(args.positive, 'estate-record-second.json'));
const agentPkg = read(path.join(args.positive, 'fabric-package-agent.json'));
for (const [name, kind, value] of [['positive/estate-record-first', 'estate-record', first], ['positive/estate-record-second', 'estate-record', second],
  ['positive revision first → second', 'estate-record-revision', { parent: first, next: second }],
  ['positive placement', 'estate-placement', { record: first, machine: first.machines[0].id, package: agentPkg }],
  ['a kind the rules do not know', 'estate-something', first],
  ['a hub key of the wrong length', 'estate-record', (() => { const r = clone(first); r.machines[0].hubKey.x = 'AAAA'; return r; })()],
  ['dates in lower case', 'estate-record', (() => { const r = clone(first); r.issuedAt = r.issuedAt.replace('T', 't').replace('Z', 'z'); return r; })()],
  ['dates with an offset', 'estate-record', (() => { const r = clone(first); r.issuedAt = '2026-10-12T11:00:00.5+02:00'; return r; })()],
  ['a leap second', 'estate-record', (() => { const r = clone(first); r.validUntil = r.validUntil.replace(':00Z', ':60Z'); return r; })()],
  ['a space for T', 'estate-record', (() => { const r = clone(first); r.issuedAt = r.issuedAt.replace('T', ' '); return r; })()],
  ['a day that does not exist', 'estate-record', (() => { const r = clone(first); r.issuedAt = '2026-02-30T09:00:00Z'; return r; })()],
  ['revision chain over non-objects', 'estate-record-revision', { parent: 'x', next: 7 }],
  ['placement with nothing in it', 'estate-placement', {}],
  ['a full-width digit in a date', 'estate-record', (() => { const r = clone(first); r.issuedAt = `\uff12${r.issuedAt.slice(1)}`; return r; })()],
  ...['\uff11', '\ufeff1', '0b1', '0o7', '0x1f', [1], ['2'], [], {}, '  3  ', '\u00a07', '-0x10', 'Infinity', '-Infinity', '1e2', '.5', '5.', '1e', 'infinity', null, true, '\u06611', '\u001c1']
    .map((revision) => [`Number() of a parent revision ${JSON.stringify(revision)}`, 'estate-record-revision', { parent: { ...clone(first), revision }, next: clone(second) }])]) {
  rules.push({ name, kind, value, expected: estate.estateRecordRules(kind, value) });
}

// The digest, the challenge and placementTrust.
const digests = [first, second].map((record) => ({ record, digest: estate.estateRecordDigest(record), challenge: estate.estateChallenge(estate.estateRecordDigest(record)).toString('hex'),
  challengeInput: estate.estateChallengeInput(estate.estateRecordDigest(record)).toString('utf8') }));
const placement = first.machines[0].packages?.[0];
const trusts = [
  { record: first, machine: first.machines[0].id, agentRef: placement?.agentRef, expected: estate.placementTrust(first, first.machines[0].id, placement?.agentRef) ?? null },
  { record: first, machine: first.machines[0].id, agentRef: 'agent:nobody', expected: estate.placementTrust(first, first.machines[0].id, 'agent:nobody') ?? null },
  { record: first, machine: 'm-none', agentRef: placement?.agentRef, expected: estate.placementTrust(first, 'm-none', placement?.agentRef) ?? null },
];

// isValidP256Key over the record's own P-256 device keys and their breakages.
const P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffffn;
const hex = (n) => n.toString(16).padStart(64, '0');
const p256Cases = [];
for (const machine of [...first.machines, ...second.machines]) {
  for (const key of machine.deviceKeys ?? []) {
    if (key.alg !== 'es256') continue;
    const raw = Buffer.from(key.publicKey, 'base64');
    const variants = {
      [`${key.kid} as listed`]: raw,
      [`${key.kid} with y + 1`]: Buffer.concat([raw.subarray(0, 33), Buffer.from(hex(BigInt(`0x${raw.subarray(33).toString('hex')}`) + 1n), 'hex').subarray(-32)]),
      [`${key.kid} compressed prefix`]: Buffer.concat([Buffer.from([2]), raw.subarray(1)]),
      [`${key.kid} cut short`]: raw.subarray(0, 64),
      [`${key.kid} x = p`]: Buffer.concat([Buffer.from([4]), Buffer.from(hex(P), 'hex'), raw.subarray(33)]),
    };
    for (const [name, bytes] of Object.entries(variants)) p256Cases.push({ name, raw: bytes.toString('hex'), expected: p256.isValidP256Key(bytes) });
  }
}

// credentialKey over the vectors' authorities and their breakages (the verdict, never the KeyObject).
const keyVerdict = (pk, alg) => { const r = webauthn.credentialKey(pk, alg); return 'problem' in r ? { problem: r.problem } : { ok: true }; };
const es = contract.keys.passkeyEs256.authority;
const ed = contract.keys.passkeyEdDSA.authority;
const credentialKeys = [
  ['ES256 as pinned', es.publicKey, 'ES256'], ['EdDSA as pinned', ed.publicKey, 'EdDSA'],
  ['ES256 with a private part', { ...es.publicKey, d: 'AA' }, 'ES256'], ['ES256 x not canonical', { ...es.publicKey, x: `${es.publicKey.x.slice(0, -1)}${es.publicKey.x.slice(-1) === 'k' ? 'l' : 'k'}` }, 'ES256'],
  ['ES256 on another curve', { ...es.publicKey, crv: 'P-384' }, 'ES256'], ['EdDSA key under ES256', ed.publicKey, 'ES256'],
  ['an algorithm the contract does not admit', es.publicKey, 'RS256'], ['EdDSA small order', contract.keys.smallOrder?.publicKey ?? { kty: 'OKP', crv: 'Ed25519', x: 'AQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' }, 'EdDSA'],
].map(([name, publicKey, alg]) => ({ name, publicKey, alg, expected: keyVerdict(publicKey, alg) }));

const keys = Object.fromEntries(Object.entries(contract.keys).map(([name, entry]) => {
  const { privateJwk: _private, seed: _seed, ...kept } = entry;
  return [name, kept];
}));
const out = args.out ?? path.join(here, 'estate-vectors.json');
fs.writeFileSync(out, `${JSON.stringify({
  $comment: 'Generated by make_estate_vectors.mjs from the contract pin\'s src/estate-record-rules.ts, src/webauthn.ts and src/p256.ts and its fixtures (vectors/estate-record.json, semantic/estate-*.json); do not edit by hand. The private test keys are dropped.',
  keys, digests, verify, rules, placementTrust: trusts, p256: p256Cases, credentialKeys,
}, null, 2)}\n`);
console.log(`wrote ${verify.length} verify cases, ${rules.length} rule cases (${rules.reduce((n, c) => n + (c.expected?.length ?? 0), 0)} findings), ${p256Cases.length} P-256 cases, ${credentialKeys.length} key cases to ${out}`);
