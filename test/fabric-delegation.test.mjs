// The Node kit's delegation verifier (DEC-0039) against the shared vectors, whose expected answers come from the
// contract's own verifier at the pin (test/fixtures/delegation/make_vectors.mjs).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as d from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-delegation.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const V = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/delegation/vectors.json'), 'utf8'));
const answer = (r) => (r.ok
  ? Object.fromEntries(['ok', 'principal', 'caller', 'chain', 'kid', 'approver', 'method'].filter((k) => k in r).map((k) => [k, r[k]]))
  : { ok: false, code: r.code, detail: r.detail, ...(r.data ? { data: r.data } : {}) });

test('every delegation case answers as the contract does', () => {
  assert.ok(V.delegation.length >= 60);
  for (const c of V.delegation) {
    // Every expected answer is the contract's own; the contract no longer throws on any case (CT-31).
    assert.equal(c.contractThrew, undefined, c.name);
    assert.deepEqual(answer(d.verifyDelegation(c.token, c.options)), c.expected, c.name);
  }
});

test('every approval case answers as the contract does', () => {
  for (const c of V.approvals) {
    const store = d.createMemoryJtiStore();
    c.steps.forEach((step, i) => {
      const options = { ...step.options, jtiStore: step.options.jtiStore === 'none' ? undefined : store };
      assert.deepEqual(answer(d.verifyApproval(step.approval ?? undefined, options)), step.expected, `${c.name} #${i}`);
    });
  }
});

test('headers, canonical JSON and digests', () => {
  for (const c of V.headers) assert.deepEqual(d.readDelegationToken(c.headers) ?? null, c.expected, JSON.stringify(c.headers));
  assert.equal(d.readDelegationToken({ authorization: [`Bearer ${V.headers[0].headers['fabric-delegation']}`] }).via, 'authorization');
  for (const c of V.jcs) assert.equal(d.jcs(JSON.parse(c.input)), c.expected);
  for (const c of V.digests) assert.equal(d.actionDigest(JSON.parse(c.input)), c.expected);
  for (const bad of [NaN, Infinity, '\ud800', new Date(0), new Map(), undefined, () => 1]) assert.throws(() => d.jcs(bad), TypeError);
});

test("the contract's canonical vectors (DEC-0043)", () => {
  const doc = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/canonical.json'), 'utf8')).rfc8785;
  const double = (hex) => Buffer.from(hex, 'hex').readDoubleBE(0);
  for (const v of doc.vectors) {
    const value = 'inputJson' in v ? JSON.parse(v.inputJson) : v.input;
    assert.equal(d.jcs(value), v.expected, v.name);
    if (v.utf8Hex) assert.equal(Buffer.from(d.jcs(value), 'utf8').toString('hex'), v.utf8Hex);
  }
  for (const v of doc.numbers) assert.equal(d.jcs(double(v.ieee754)), v.expected, v.note ?? v.ieee754);
  for (const v of doc.refuses) assert.throws(() => d.jcs('inputJson' in v ? JSON.parse(v.inputJson) : double(v.ieee754)), TypeError, v.name);
});

test('jti stores: memory prunes, the file store survives a restart, the store is required', () => {
  const mem = d.createMemoryJtiStore();
  assert.equal(mem.consume('a', 100, 50), true);
  assert.equal(mem.consume('a', 100, 60), false);
  assert.equal(mem.consume('a', 300, 100 + d.LEEWAY_SECONDS + 1), true);
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'jti-')), 'jti.json');
  assert.equal(new d.FileJtiStore(file).consume('a', 1000, 10), true);
  assert.equal(new d.FileJtiStore(file).consume('a', 1000, 20), false);
  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
  const step = V.approvals[0].steps[0];
  assert.equal(d.verifyApproval(step.approval, { ...step.options, jtiStore: undefined }).code, 'unknown-state');
  assert.equal(d.verifyApproval(step.approval, { ...step.options, jtiStore: d.UNSAFE_NO_JTI_STORE }).ok, true);
});

test('JwksCache follows DL-15: ten minutes, an unknown kid re-read at most once a minute, unreadable after that', async () => {
  const now = [1000];
  const calls = [];
  let reply = V.jwks;
  const cache = new d.JwksCache('https://hub.example/.well-known/jwks.json', { fetch: async () => { calls.push(now[0]); if (reply instanceof Error) throw reply; return reply; }, clock: () => now[0] });
  assert.deepEqual(await cache.get('estate-new'), V.jwks);
  await cache.get('estate-next'); assert.equal(calls.length, 2, 'an unknown kid re-reads');
  now[0] += 30; await cache.get('estate-next'); assert.equal(calls.length, 2, 'not twice a minute');
  now[0] += 31; await cache.get('estate-next'); assert.equal(calls.length, 3);
  now[0] += 599; await cache.get('estate-new'); assert.equal(calls.length, 3);
  now[0] += 2; reply = new Error('down'); assert.equal(await cache.get('estate-new'), null, 'older than ten minutes and unreadable');
  const before = calls.length; await cache.get('estate-new'); assert.equal(calls.length, before, 'a failed read waits before the next try');
  now[0] += d.JWKS_RETRY_SECONDS; await cache.get('estate-new'); assert.equal(calls.length, before + 1);
  for (const bad of ['http://hub.example/jwks.json', 'ftp://x/j', 'https://u:p@hub.example/j', '']) assert.throws(() => new d.JwksCache(bad), /key set/);
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'jwks-')), 'jwks.json');
  fs.writeFileSync(file, JSON.stringify(V.jwks));
  assert.deepEqual(await new d.JwksCache(file).get('estate-new'), V.jwks);
});

test('the gate refuses in the DL-19 shape and never echoes the token', async () => {
  const c = V.delegation[0];
  const gate = d.delegationGate({ audience: c.options.audience, jwks: V.jwks, effects: { 'writer.write': 'draft', 'writer.publish': 'publish' }, issuer: 'urn:fabric:estate:example', clock: () => c.options.now });
  const ok = await gate('writer.write', { Authorization: `Bearer ${c.token}` });
  assert.equal(ok.ok, true); assert.equal(ok.caller, 'example-media');
  assert.deepEqual([(await gate('writer.write', {})).detail, (await gate('writer.other', { Authorization: `Bearer ${c.token}` })).detail], ['no-token', 'no-declared-effect']);
  assert.equal((await gate('writer.publish', { 'Fabric-Delegation': c.token })).code, 'scope-not-granted');
  const refusal = await gate('writer.write', {});
  const result = d.refusalToolResult(refusal);
  assert.equal(result.isError, true);
  assert.deepEqual(result.structuredContent.error.data, { detail: 'no-token' });
  assert.ok(result.structuredContent.error.message);
  const http = d.refusalHttp(refusal);
  assert.equal(http.status, 401);
  assert.equal(http.headers['WWW-Authenticate'], 'Bearer error="invalid_token"');
  for (const code of V.constants.refusalCodes) assert.ok([401, 403, 503].includes(d.refusalHttp({ ok: false, code, detail: 'x' }).status));
  assert.ok(!JSON.stringify(result).includes(c.token));
  // DL-26: a T0 or T1 caller is never required to present a token; a present one is verified at every tier.
  for (const tier of ['T0', 'T1']) {
    const passed = await gate('writer.write', {}, tier);
    assert.deepEqual([passed.ok, passed.tier, passed.principal], [true, tier, null]);
    assert.equal((await gate('writer.write', { 'Fabric-Delegation': 'junk' }, tier)).code, 'unauthenticated');
    assert.equal((await gate('writer.write', { Authorization: `Bearer ${c.token}` }, tier)).caller, 'example-media');
  }
  assert.equal((await gate('writer.write', {}, 'T9')).code, 'unauthenticated');
  assert.throws(() => d.delegationGate({ audience: 'a', jwks: V.jwks, effects: {}, issuer: '' }), /issuer/);
  assert.deepEqual(d.refusalFromDenial({ decision: 'denied', level: 'L1', code: 'limit-reached', reason: 'the day window is spent', checkedAt: 't', window: 'day' }),
    { error: { code: 'limit-reached', message: 'the meter denied the spend: the day window is spent', data: { window: 'day', level: 'L1' } } });
});

test('review findings: unreadable jti file, __proto__ as an id, a null header value', () => {
  const step = V.approvals[0].steps[0];
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'jti-')), 'jti.json');
  const store = new d.FileJtiStore(file);
  assert.equal(d.verifyApproval(step.approval, { ...step.options, jtiStore: store }).ok, true);
  fs.writeFileSync(file, '{');
  assert.equal(d.verifyApproval(step.approval, { ...step.options, jtiStore: store }).code, 'unknown-state');
  const proto = new d.FileJtiStore(path.join(path.dirname(file), 'p.json'));
  assert.equal(proto.consume('__proto__', 1000, 10), true);
  assert.equal(proto.consume('__proto__', 1000, 20), false);
  assert.equal(d.readDelegationToken({ 'Fabric-Delegation': null, Authorization: `Bearer ${V.delegation[0].token}` }).via, 'authorization');
});

test('small-order keys are refused by the kit itself, whatever the Node version (Node 22 accepts the forgery)', () => {
  const small = V.ed25519.filter((c) => c.kind === 'small-order key, forged');
  assert.equal(small.length, 8);
  for (const c of small) assert.equal(d.isSmallOrderKey(Buffer.from(c.pub, 'hex')), true, c.pub);
  // Non-canonical encodings of the same points (y + p, the sign bit set) are refused too.
  const pPlus = (n) => { const b = Buffer.alloc(32, 0xff); b[0] = 0xed + n; b[31] = 0x7f; return b; };
  for (const b of [pPlus(0), pPlus(1), Buffer.from('0000000000000000000000000000000000000000000000000000000000000080', 'hex')]) assert.equal(d.isSmallOrderKey(b), true, b.toString('hex'));
  for (const c of V.ed25519.filter((x) => x.kind === 'valid')) assert.equal(d.isSmallOrderKey(Buffer.from(c.pub, 'hex')), false);
});
