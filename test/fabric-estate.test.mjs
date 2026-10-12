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
const plain = (value) => JSON.parse(JSON.stringify(value ?? null));

test('every verify case answers as the contract does', () => {
  assert.equal(V.verify.length, 45);
  for (const c of V.verify) {
    const trust = { ...c.trust, at: c.trust.at === undefined || c.trust.at === null ? c.trust.at : new Date(c.trust.at) };
    assert.deepEqual(plain(e.verifyEstateRecord(c.record, trust)), c.expected, c.name);
  }
});

test('every rule case answers as the contract does (FAC-SEM-072…076)', () => {
  for (const c of V.rules) assert.deepEqual(e.estateRecordRules(c.kind, c.value), c.expected, c.name);
  const codes = new Set(V.rules.flatMap((c) => (c.expected ?? []).map((f) => f.code)));
  assert.deepEqual([...codes].sort(), ['FAC-SEM-072', 'FAC-SEM-073', 'FAC-SEM-074', 'FAC-SEM-075', 'FAC-SEM-076']);
});

test('the digest, the challenge, placement trust, P-256 keys and passkey keys', () => {
  for (const c of V.digests) {
    assert.equal(e.estateRecordDigest(c.record), c.digest);
    assert.equal(e.estateChallengeInput(c.digest).toString('utf8'), c.challengeInput);
    assert.equal(e.estateChallenge(c.digest).toString('hex'), c.challenge);
  }
  for (const c of V.placementTrust) assert.deepEqual(plain(e.placementTrust(c.record, c.machine, c.agentRef)), c.expected);
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
  assert.equal(e.hubKeyCertified(certifying(), kid, x, o.now), true);
  assert.equal(verify(undefined).ok, true);
  assert.equal(verify(certifying()).ok, true);
  assert.equal(verify(() => certifying()).ok, true, 'a function gives the current revision');
});

test('an uncertified, revoked or stale kid is refused; an unreadable record certifies nothing', () => {
  const revoked = certifying();
  revoked.revocations = [...(revoked.revocations ?? []), { kind: 'hub-key', ref: kid }];
  const stale = certifying();
  stale.validUntil = stale.issuedAt;
  for (const [name, record] of [['another kid', certifying('another-kid')], ['another key', certifying(kid, 'B'.repeat(43))], ['revoked', revoked], ['stale', stale]]) {
    const verdict = verify(record);
    assert.deepEqual([verdict.ok, verdict.code, verdict.detail], [false, 'unauthenticated', 'kid-not-certified'], name);
  }
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
  assert.equal((await gate(o.capability, { 'Fabric-Delegation': tokenCase.token })).detail, 'kid-not-certified');
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
