// `estate-record/1` (contract DEC-0055) in the Node kit (FAA-31); the twin of test_fabric_estate.py. Every answer was
// given by the contract's own functions at the pin (fixtures/contract/estate-vectors.json, make_estate_vectors.mjs). The
// last cases hold the delegation verifier to DL-14: with an estate record, a kid is trusted only while a current
// revision certifies it (CT-20).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as e from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-estate.mjs';
import * as dl from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-delegation.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const V = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/estate-vectors.json'), 'utf8'));
const D = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/delegation/vectors.json'), 'utf8'));
const HUB = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/hub-key-vectors.json'), 'utf8'));
const plain = (value) => JSON.parse(JSON.stringify(value ?? null));

test('every verify case answers as the contract does', () => {
  assert.equal(V.verify.length, 49);
  for (const c of V.verify) {
    const trust = { ...c.trust, at: c.trust.at === undefined || c.trust.at === null ? c.trust.at : new Date(c.trust.at) };
    assert.deepEqual(plain(e.verifyEstateRecord(c.record, trust)), c.expected, c.name);
  }
});

test('every rule case answers as the contract does (FAC-SEM-072…076)', () => {
  for (const c of V.rules) assert.deepEqual(e.estateRecordRules(c.kind, c.value), c.expected, c.name);
  const codes = new Set(V.rules.flatMap((c) => (c.expected ?? []).map((f) => f.code)));
  assert.deepEqual([...codes].sort(), ['FAC-SEM-072', 'FAC-SEM-073', 'FAC-SEM-074', 'FAC-SEM-075', 'FAC-SEM-076', 'FAC-SEM-110', 'FAC-SEM-111', 'FAC-SEM-114', 'FAC-SEM-122', 'FAC-SEM-134', 'FAC-SEM-137']);
});

test('the digest, the challenge, placement trust, P-256 keys and passkey keys', () => {
  for (const c of V.digests) {
    assert.equal(e.estateRecordDigest(c.record), c.digest);
    assert.equal(e.estateChallengeInput(c.digest).toString('utf8'), c.challengeInput);
    assert.equal(e.estateChallenge(c.digest).toString('hex'), c.challenge);
  }
  assert.ok(V.grantContext.length >= 7);
  for (const c of V.grantContext) assert.deepEqual(plain(e.grantContextFindings(c.value, '')), c.expected, c.name);
  for (const c of V.placementTrust) assert.deepEqual(plain('context' in c ? e.placementTrust(c.record, c.machine, c.agentRef, c.context) : e.placementTrust(c.record, c.machine, c.agentRef)), c.expected);
  // DEC-0106: the contract's own profile vectors (fixtures/vectors/machine-call.json) and hostile inputs.
  assert.ok(V.machineProfile.length >= 17);
  for (const c of V.machineProfile) assert.equal(e.machineProfile(c.record, c.machineId) ?? null, c.expected, c.name);
  assert.deepEqual([...e.MACHINE_PROFILES], ['full', 'member', 'view']);
  // DEC-0107: the anchor a record vouches for; FAC-SEM-137's variants run with the rule cases.
  assert.ok(V.deltaAnchor.length >= 10);
  for (const c of V.deltaAnchor) assert.deepEqual(e.deltaAnchorOf(c.record) ?? null, c.expected, JSON.stringify(c.record));
  // The contract keeps the view machines' ids in a Set: NaN matches NaN there (FAA-107; no JSON carries NaN).
  const nanFound = e.estateRecordRules('estate-record', { machines: [{ id: NaN, profile: 'view' }, { id: 'a', secrets: [{ from: NaN }] }] }).filter((f) => f.code === 'FAC-SEM-134');
  assert.deepEqual(nanFound.map((f) => f.instancePath), ['/machines/1/secrets/0/from']);
  assert.equal(nanFound[0].message, 'machine NaN is a view machine: it is the source of no secret');
  for (const c of V.p256) assert.equal(e.isValidP256Key(Buffer.from(c.raw, 'hex')), c.expected, c.name);
  for (const c of V.credentialKeys) {
    const found = e.credentialKey(c.publicKey, c.alg);
    assert.deepEqual('problem' in found ? { problem: found.problem } : { ok: true }, c.expected, c.name);
  }
});

test('dates are strict RFC 3339, and the clock is a Date or epoch seconds', () => {
  assert.equal(e.estateTime('2026-10-12t09:00:00z'), 1791795600000);
  assert.equal(e.estateTime('2026-10-12T11:00:00.123456+02:00'), 1791795600123);
  for (const bad of ['2026-02-30T00:00:00Z', '2026-10-12 09:00:00Z', '2026-10-12T09:00:60Z', '2026-10-12T09:00:00', 1791795600, null]) assert.ok(Number.isNaN(e.estateTime(bad)), String(bad));
  const c = V.verify.find((x) => x.expected.ok);
  assert.equal(e.verifyEstateRecord(c.record, { ...c.trust, at: Date.parse(c.trust.at) / 1000 }).ok, true);
  assert.deepEqual(e.verifyEstateRecord(c.record, { ...c.trust, at: c.trust.at }), { ok: false, problem: 'no-clock' });
});

// ---- DL-14 with DEC-0055 (CT-20) ----

const iso = (seconds) => new Date(seconds * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z');
const tokenCase = D.delegation.find((c) => c.expected.ok);
const o = tokenCase.options;
const jwks = o.jwks ?? D.jwks;
const kid = tokenCase.expected.kid;
const x = jwks.keys.find((k) => k.kid === kid).x;
const certifying = (forKid = kid, forX = x, now = o.now) => {
  const record = structuredClone(V.digests[0].record);
  record.issuedAt = iso(now - 3600);
  record.validUntil = iso(now + 3600);
  record.machines[0].hubKey = { ...record.machines[0].hubKey, kid: forKid, x: forX };
  return record;
};
const verify = (estate) => dl.verifyDelegation(tokenCase.token, { audience: o.audience, jwks, now: o.now, capability: o.capability, effect: o.effect, issuer: o.issuer, readOnly: o.readOnly ?? false, estate });

test('a certified kid is trusted; no record changes nothing', () => {
  const record = certifying();
  assert.deepEqual(e.hubKeyCertified(record, kid, x, o.now), { certified: true, machine: record.machines[0].id, revision: record.revision });
  assert.equal(verify(undefined).ok, true);
  assert.equal(verify(certifying()).ok, true);
  assert.equal(verify(() => certifying()).ok, true, 'a function gives the current revision');
});

test('an uncertified, revoked or stale kid is refused; an unreadable record certifies nothing', () => {
  const revoked = certifying();
  revoked.revocations = [...(revoked.revocations ?? []), { kind: 'hub-key', ref: kid }];
  for (const [name, record] of [['another kid', certifying('another-kid')], ['another key', certifying(kid, 'B'.repeat(43))], ['revoked', revoked]]) {
    const verdict = verify(record);
    assert.deepEqual([verdict.ok, verdict.code, verdict.detail], [false, 'unauthenticated', 'kid-not-certified'], name);
  }
  // DEC-0060: a revision whose window cannot hold the clock is the trust source's fault, not the token's.
  const stale = certifying();
  stale.validUntil = stale.issuedAt;
  assert.deepEqual([verify(stale).code, verify(stale).detail], ['issuer-unavailable', 'estate-unreadable']);
  assert.deepEqual([verify(null).code, verify(null).detail], ['issuer-unavailable', 'estate-unreadable'], 'only an absent estate skips the check');
  const broken = verify(() => { throw new Error('the record store is down'); });
  assert.deepEqual([broken.ok, broken.code, broken.detail], [false, 'issuer-unavailable', 'estate-unreadable']);
});

test('approvals and the gate follow the record', async () => {
  const step = D.approvals.flatMap((c) => c.steps).find((s) => s.expected.ok);
  const so = step.options;
  const keys = so.jwks ?? D.jwks;
  const record = certifying(step.expected.kid, keys.keys.find((k) => k.kid === step.expected.kid).x, so.now);
  const approve = (estate) => dl.verifyApproval(step.approval, { audience: so.audience, jwks: keys, now: so.now, actionDigest: so.actionDigest, jtiStore: dl.createMemoryJtiStore(), issuer: so.issuer, estate });
  assert.equal(approve(record).ok, true);
  record.machines[0].hubKey.kid = 'another-kid';
  assert.deepEqual([approve(record).code, approve(record).detail], ['approval-invalid', 'kid-not-certified']);
  const gate = dl.delegationGate({ audience: o.audience, jwks, effects: { [o.capability]: o.effect }, issuer: o.issuer, clock: () => o.now, estate: () => ({}) });
  const refused = await gate(o.capability, { 'Fabric-Delegation': tokenCase.token });
  assert.deepEqual([refused.code, refused.detail], ['issuer-unavailable', 'estate-unreadable']);
  const rolled = dl.delegationGate({ audience: o.audience, jwks, effects: { [o.capability]: o.effect }, issuer: o.issuer, clock: () => o.now, estate: () => certifying(), estateApplied: { revision: certifying().revision + 1 } });
  const back = await rolled(o.capability, { 'Fabric-Delegation': tokenCase.token });
  assert.deepEqual([back.code, back.detail], ['issuer-unavailable', 'estate-rolled-back']);
});

// ---- DEC-0060: hubKeyCertified and the verifiers' row 4a, held to the contract's own answers ----

test('every hub-key case answers as the contract does', () => {
  assert.equal(HUB.cases.length, 51);
  const details = new Set();
  for (const c of HUB.cases) {
    const got = e.hubKeyCertified(c.record, c.kid, c.x, c.at, c.applied, c.extraRevocations === undefined ? undefined : { extraRevocations: c.extraRevocations });
    assert.deepEqual(got, c.expected, c.name);
    details.add(got.detail ?? 'certified');
  }
  assert.deepEqual([...details].sort(), ['certified', 'estate-forked', 'estate-outside-window', 'estate-rolled-back', 'estate-unreadable', 'kid-not-certified', 'no-clock']);
});

test('every verifier answer matches', () => {
  assert.equal(HUB.verifier.length, 14);
  for (const c of HUB.verifier) {
    const options = { audience: 'example-media', jwks: HUB.jwks, now: c.now, issuer: HUB.issuer, estateApplied: c.estateApplied };
    if (c.estate) options.estate = c.estate.throws ? () => { throw new Error('the record store is down'); } : c.estate.record;
    const got = c.document === 'approval'
      ? dl.verifyApproval(c.token, { ...options, actionDigest: HUB.actionDigest, jtiStore: dl.createMemoryJtiStore() })
      : dl.verifyDelegation(c.token, { ...options, capability: 'media.render', effect: 'draft' });
    assert.equal(got.ok, c.expected.ok, c.name);
    if (!c.expected.ok) assert.deepEqual([got.code, got.detail], [c.expected.code, c.expected.detail], c.name);
  }
});

test('a revocation ref is compared exactly, never after String() (DEC-0060 (i))', () => {
  const c = HUB.cases[0];
  const record = structuredClone(c.record);
  record.machines[0].id = 7;
  record.revocations = [{ kind: 'machine', ref: '7', revokedAt: '2026-10-21T09:00:00Z' }];
  assert.equal(e.hubKeyCertified(record, c.kid, c.x, c.at).certified, true);
  record.revocations[0].ref = 7;
  assert.equal(e.hubKeyCertified(record, c.kid, c.x, c.at).detail, 'kid-not-certified');
});

test('an unreadable clock is refused first; the delta revocations pass through', () => {
  const c = HUB.verifier[0];
  for (const now of [NaN, Infinity, '1792918830', true, 8.64e12 + 1, null, undefined]) {
    const got = dl.verifyDelegation(c.token, { audience: 'example-media', jwks: HUB.jwks, now, capability: 'media.render', effect: 'draft' });
    assert.deepEqual([got.code, got.detail], ['unknown-state', 'no-clock'], String(now));
  }
  const approval = dl.verifyApproval('x.y.z', { audience: 'example-media', jwks: HUB.jwks, now: NaN, actionDigest: HUB.actionDigest, issuer: HUB.issuer, jtiStore: dl.createMemoryJtiStore() });
  assert.deepEqual([approval.code, approval.detail], ['unknown-state', 'no-clock']);
  for (const extra of [[{ kind: 'hub-key', ref: 'hub-m-4c1e-1', revokedAt: '2026-10-21T09:00:00Z' }], () => [{ kind: 'machine', ref: 'm-4c1e', revokedAt: '2026-10-21T09:00:00Z' }]]) {
    const got = dl.verifyDelegation(c.token, { audience: 'example-media', jwks: HUB.jwks, now: c.now, capability: 'media.render', effect: 'draft', issuer: HUB.issuer, estate: c.estate.record, estateRevocations: extra });
    assert.deepEqual([got.code, got.detail], ['unauthenticated', 'kid-not-certified']);
  }
});

// ---- DEC-0063: the estate passkey is a signing credential (FAC-SEM-092) ----

test('signing RP IDs and origins; the record rules flag a sign-in credential', () => {
  for (const [rp, ok] of [['sign.example.org', true], ['sign.a.b.c', true], ['sign.org', false], ['example.org', false], ['SIGN.example.org', false],
    ['sign.example.org.', false], [null, false], [`sign.${'a'.repeat(63)}.org`, true], [`sign.${'a'.repeat(64)}.org`, false]]) assert.equal(e.isSigningRpId(rp), ok, String(rp));
  for (const [origin, ok] of [['https://sign.example.org', true], ['https://x.sign.example.org', true], ['https://sign.example.org:443', false],
    ['http://sign.example.org', false], ['https://evilsign.example.org', false], ['https://sign.example.org/', false]]) assert.equal(e.originWithin(origin, 'sign.example.org'), ok, origin);
  const record = structuredClone(V.digests[0].record);
  record.authorities[0].rpId = 'example.org';
  const flagged = (r) => e.estateRecordRules('estate-record', r).filter((f) => f.code === 'FAC-SEM-092').map((f) => f.instancePath);
  assert.deepEqual(flagged(record), ['/authorities/0/rpId']);
  record.authorities[0].rpId = 'sign.example.org';
  record.authorities[0].origins = ['https://sign.example.org', 'https://example.org'];
  assert.deepEqual(flagged(record), ['/authorities/0/origins/1']);
});

test('ES256 through OpenSSL refuses a malleated, padded or trailing signature; a coordinate is below p', async () => {
  const crypto = await import('node:crypto');
  const c = V.verify.find((x) => x.expected.ok && x.record.signature.alg === 'ES256');
  const authority = c.trust.authorities.find((a) => a.alg === 'ES256');
  const sig = c.record.signature;
  const message = Buffer.concat([Buffer.from(sig.authenticatorData, 'base64url'), crypto.createHash('sha256').update(Buffer.from(sig.clientDataJSON, 'base64url')).digest()]);
  const key = crypto.createPublicKey({ key: { kty: 'EC', crv: 'P-256', x: authority.publicKey.x, y: authority.publicKey.y }, format: 'jwk' });
  const ok = (der) => crypto.verify('sha256', message, { key, dsaEncoding: 'der' }, der);
  const N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551n;
  const der = Buffer.from(sig.sig, 'base64url');
  const big = (b) => BigInt(`0x${b.toString('hex')}`);
  const rLen = der[3];
  const r = big(der.subarray(4, 4 + rLen));
  const s = big(der.subarray(6 + rLen));
  const integer = (n, pad = false) => {
    let body = Buffer.from(n.toString(16).padStart(Math.ceil(n.toString(16).length / 2) * 2, '0'), 'hex');
    if (body[0] & 0x80) body = Buffer.concat([Buffer.from([0]), body]);
    if (pad) body = Buffer.concat([Buffer.from([0]), body]);
    return Buffer.concat([Buffer.from([2, body.length]), body]);
  };
  const seq = (inner) => Buffer.concat([Buffer.from([0x30, inner.length]), inner]);
  assert.equal(ok(der), true);
  const low = N - s;
  assert.equal(ok(seq(Buffer.concat([integer(r), integer(low)]))), true, 'low-S is the same signature');
  assert.equal(ok(seq(Buffer.concat([integer(r), integer(s + N)]))), false, 's + n');
  assert.equal(ok(seq(Buffer.concat([integer(r), integer(low, true)]))), false, 'a zero more than minimal');
  assert.equal(ok(seq(Buffer.concat([integer(r), integer(s), Buffer.from([0])]))), false, 'a byte after s inside the sequence');
  const P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffffn;
  const B = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604bn;
  const pow = (b, ex, m) => { let out = 1n; b %= m; while (ex > 0n) { if (ex & 1n) out = (out * b) % m; b = (b * b) % m; ex >>= 1n; } return out; };
  const root = pow(B, (P + 1n) / 4n, P);
  const hex32 = (n) => Buffer.from(n.toString(16).padStart(64, '0'), 'hex');
  assert.equal(e.isValidP256Key(Buffer.concat([Buffer.from([4]), hex32(P), hex32(root)])), false);
  assert.equal(e.isValidP256Key(Buffer.concat([Buffer.from([4]), hex32(0n), hex32(root)])), true);
});
