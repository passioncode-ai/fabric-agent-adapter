// The Node kit's delegation verifier (DEC-0039) against the shared vectors, whose expected answers come from the
// contract's own verifier at the pin (test/fixtures/delegation/make_vectors.mjs).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import * as d from '../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-delegation.mjs';
import { tempDir } from './temp-dir.mjs';

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

test('chain depth, a partner actor innermost only (DEC-0090)', () => {
  for (const c of V.chainDepths) {
    const depth = d.chainDepth(c.act ?? undefined);
    assert.equal(Number.isFinite(depth) ? depth : null, c.expected, c.name);
  }
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

test('the file jti store writes with the kit\'s private writer: a failed write leaves no temporary file (FAA-85)', () => {
  for (const step of ['writeSync', 'fsyncSync', 'renameSync']) {
    const dir = tempDir('jti-');
    const real = fs[step];
    fs[step] = () => { const e = new Error(`refused ${step}`); e.code = 'EPERM'; throw e; };
    try {
      assert.throws(() => new d.FileJtiStore(path.join(dir, 'jti.json')).consume('a', 1000, 10), /refused/, step);
    } finally {
      fs[step] = real;
    }
    assert.deepEqual(fs.readdirSync(dir), [], step);
  }
});

test('a failed cleanup does not replace the error that caused it (FAA-85)', () => {
  const dir = tempDir('jti-');
  const [write, rm] = [fs.writeSync, fs.rmSync];
  fs.writeSync = () => { throw new Error('refused write'); };
  fs.rmSync = () => { throw new Error('refused remove'); };
  try {
    assert.throws(() => new d.FileJtiStore(path.join(dir, 'jti.json')).consume('a', 1000, 10), /refused write/);
  } finally {
    [fs.writeSync, fs.rmSync] = [write, rm];
  }
});

test('jti stores: memory prunes, the file store survives a restart, the store is required', () => {
  const mem = d.createMemoryJtiStore();
  assert.equal(mem.consume('a', 100, 50), true);
  assert.equal(mem.consume('a', 100, 60), false);
  assert.equal(mem.consume('a', 300, 100 + d.LEEWAY_SECONDS + 1), true);
  const file = path.join(tempDir('jti-'), 'jti.json');
  assert.equal(new d.FileJtiStore(file).consume('a', 1000, 10), true);
  assert.equal(new d.FileJtiStore(file).consume('a', 1000, 20), false);
  // A mode is this file's whole claim (consumed ids, no secret); on Windows Node reports 0o666 whatever the ACL says.
  if (process.platform !== 'win32') assert.equal(fs.statSync(file).mode & 0o777, 0o600);
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
  const file = path.join(tempDir('jwks-'), 'jwks.json');
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
  // DL-19 (DEC-0106): profile-forbids is the callee's refusal, 403 with no challenge.
  const forbids = d.refusalHttp({ ok: false, code: 'profile-forbids', detail: 'target-view' });
  assert.equal(forbids.status, 403);
  assert.equal(forbids.headers['WWW-Authenticate'], undefined);
  assert.equal(JSON.parse(forbids.body).error.message, "The caller's or the target's machine profile does not allow this call.");
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
  const file = path.join(tempDir('jti-'), 'jti.json');
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

// D3 (FAA-78, finding 44): an omitted estate option skips DL-14; an explicit null fails closed, as in the Python twin.
const certifyingRecord = (c) => {
  const estate = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/estate-vectors.json'), 'utf8'));
  const jwks = c.options.jwks ?? V.jwks;
  const kid = c.expected.kid;
  const iso = (s) => new Date(s * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z');
  const record = structuredClone(estate.digests[0].record);
  record.issuedAt = iso(c.options.now - 3600);
  record.validUntil = iso(c.options.now + 3600);
  record.machines[0].hubKey = { ...record.machines[0].hubKey, kid, x: jwks.keys.find((k) => k.kid === kid).x };
  return record;
};

test('an omitted estate skips the rule; an explicit null estate, source, applied mark or delta is unreadable', () => {
  const c = V.delegation.find((x) => x.expected.ok);
  const record = certifyingRecord(c);
  const verify = (extra) => d.verifyDelegation(c.token, { ...c.options, jwks: c.options.jwks ?? V.jwks, ...extra });
  assert.equal(verify({}).ok, true);
  assert.equal(verify({ estate: record }).ok, true);
  assert.equal(verify({ estate: record, estateApplied: { revision: record.revision } }).ok, true);
  assert.equal(verify({ estate: record, estateRevocations: [] }).ok, true);
  for (const [name, extra] of [['estate', { estate: null }], ['source', { estate: () => null }],
    ['applied', { estate: record, estateApplied: null }], ['revocations', { estate: record, estateRevocations: null }]]) {
    const got = verify(extra);
    assert.deepEqual([got.ok, got.code, got.detail], [false, 'issuer-unavailable', 'estate-unreadable'], name);
  }
});

test('D4: a published x is exactly 43 base64url characters that re-encode to themselves', () => {
  const c = V.delegation.find((x) => x.expected.ok);
  const jwks = c.options.jwks ?? V.jwks;
  const kid = c.expected.kid;
  const x = jwks.keys.find((k) => k.kid === kid).x;
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  const noncanonical = x.slice(0, -1) + alphabet[alphabet.indexOf(x.at(-1)) ^ 1];
  for (const loose of [`${x}=`, `${x}\n`, `+${x.slice(1)}`, noncanonical, ` ${x}`]) {
    const keys = { keys: jwks.keys.map((k) => (k.kid === kid ? { ...k, x: loose } : k)) };
    const got = d.verifyDelegation(c.token, { ...c.options, jwks: keys });
    assert.deepEqual([got.ok, got.code, got.detail], [false, 'issuer-unavailable', 'unusable-key'], JSON.stringify(loose));
  }
});

test('R1: a token with a trailing newline is malformed', () => {
  const c = V.delegation[0];
  const got = d.verifyDelegation(`${c.token}\n`, c.options);
  assert.deepEqual([got.ok, got.code, got.detail], [false, 'unauthenticated', 'malformed']);
});

// DL-19 (DEC-0039, DEC-0121): the kit's one code set is the contract's, each code answers with its own sentence, and
// the refusals of an action call (fabric-actions.mjs) are DL-19 bodies. The twin of RefusalCodeSetTests.
const ACTIONS = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/actions-vectors.json'), 'utf8'));
const HUMAN_STEPS = ['sign-in', 'consent', 'payment', 'secret', 'spend-above-limit', 'passkey'];
function dl19Problems(body) {
  const error = body !== null && typeof body === 'object' && Object.keys(body).join() === 'error' ? body.error : undefined;
  if (error === null || typeof error !== 'object' || Object.keys(error).some((k) => !['code', 'message', 'data'].includes(k))) return ['shape'];
  const problems = [];
  if (!V.constants.refusalCodes.includes(error.code)) problems.push('code');
  if (!(typeof error.message === 'string' && error.message.length >= 1 && error.message.length <= 500)) problems.push('message');
  const data = error.data ?? {};
  if (!(typeof data.detail === 'string' && data.detail.length >= 1 && data.detail.length <= 80)) problems.push('detail');
  if (error.code === 'approval-required' && !String(data.actionDigest ?? '').startsWith('sha256:')) problems.push('actionDigest');
  if (error.code === 'human-step-required') {
    if (!HUMAN_STEPS.includes(data.humanStep)) problems.push('humanStep');
    if (!(typeof data.url === 'string' && data.url.length >= 1 && data.url.length <= 2048 && /^(https:\/\/|\/)/.test(data.url))) problems.push('url');
  }
  return problems;
}

test('the code set is the contract\'s, and every code has its sentence and status', () => {
  assert.deepEqual([...d.REFUSAL_CODES], V.constants.refusalCodes);
  assert.equal(d.REFUSAL_CODES.length, 21);
  const data = { actionDigest: `sha256:${'0'.repeat(64)}`, humanStep: 'consent', url: '/x' };
  for (const code of d.REFUSAL_CODES) {
    assert.ok(Object.hasOwn(d.REFUSAL_MESSAGES, code), code);
    assert.deepEqual(dl19Problems(d.refusalError({ ok: false, code, detail: 'x', data })), [], code);
  }
  for (const code of ['operator-decision-required', 'decision-invalid', 'human-step-required']) {
    const http = d.refusalHttp({ ok: false, code, detail: 'x' });
    assert.equal(http.status, 403, code);
    assert.equal(http.headers['WWW-Authenticate'], undefined, code);
  }
});

test('the decision refusal names the routes for a client that cannot set _meta (D13)', () => {
  const message = d.REFUSAL_MESSAGES['operator-decision-required'];
  assert.ok(message.length <= 500, message);
  const places = ['_meta.decision', 'agent.call', 'call.decision', 'elicitation', 'Fabric Dashboards', 'open_link'].map((r) => message.indexOf(r));
  assert.ok(!places.includes(-1), message);
  assert.deepEqual(places, [...places].sort((a, b) => a - b));
  assert.ok(!message.includes('\u2014'));
});

test('an action refusal is a DL-19 body', () => {
  const details = { 'operator-decision-required': 'no-decision', 'decision-invalid': 'invalid-decision', 'human-step-required': 'human-step', 'approval-required': 'no-approval' };
  let refused = 0;
  for (const c of ACTIONS.cases) {
    const answer = c.expected;
    const refusal = d.refusalFromAction(answer);
    if (answer.ok === true) {
      assert.equal(refusal, undefined, c.name);
      continue;
    }
    refused += 1;
    const result = d.refusalToolResult(refusal, `00-${'a'.repeat(32)}-${'b'.repeat(16)}-01`);
    assert.equal(result.isError, true, c.name);
    const body = result.structuredContent;
    assert.deepEqual(JSON.parse(result.content[0].text), body, c.name);
    assert.deepEqual(dl19Problems(body), [], c.name);
    if ('fault' in answer) {
      assert.equal(body.error.code, 'unknown-state', c.name);
      assert.deepEqual(body.error.data, { detail: 'service-fault' }, c.name);
      assert.ok(!JSON.stringify(body).includes(answer.fault), c.name);
      continue;
    }
    assert.equal(body.error.code, answer.code, c.name);
    assert.deepEqual(body.error.data, { detail: details[answer.code], ...(answer.data ?? {}) }, c.name);
    assert.equal(d.refusalHttp(refusal).status, 403, c.name);
  }
  assert.ok(refused > 30);
});

test('a human step carries its step and link; what is not an answer is an unknown state', () => {
  const refusal = d.refusalFromAction({ ok: false, code: 'human-step-required', data: { humanStep: 'payment', url: 'https://store.example/pay' } });
  assert.deepEqual(refusal, { ok: false, code: 'human-step-required', detail: 'human-step', data: { humanStep: 'payment', url: 'https://store.example/pay' } });
  assert.deepEqual(d.refusalError(refusal).error.data, { detail: 'human-step', humanStep: 'payment', url: 'https://store.example/pay' });
  for (const value of [undefined, null, [], 'x', {}, { ok: false }, { ok: false, code: 'no-such-code' }, { ok: 'true' }, { ok: false, code: 'toString' }]) {
    const r = d.refusalFromAction(value);
    assert.deepEqual([r.code, r.detail], ['unknown-state', 'service-fault'], JSON.stringify(value));
  }
  // DEC-0141 MJ-1, seam round 3 of 0.54.0: every route from actionDecision agrees with the gate.
  const step = d.refusalFromAction({ fault: 'mandate-capability-missing' });
  assert.deepEqual([step.code, step.data], ['operator-decision-required', { detail: 'mandate-capability-missing' }]);
  assert.equal(d.refusalError(step).error.data.detail, 'mandate-capability-missing');
  assert.equal(d.refusalFromAction({ fault: 'effect-missing' }).code, 'unknown-state');
});
