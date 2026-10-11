#!/usr/bin/env node
// Writes vectors.json: the shared cases both kits' delegation verifiers must answer exactly as the contract's
// own verifier does (DEC-0039, fabric-delegation/0.1). Keys come from fixed seeds and Ed25519 signatures are
// deterministic, so the file is reproducible. The expected answer of every case is computed by running the
// contract's `src/delegation.ts` at the pinned revision — never written by hand.
//
//   node test/fixtures/delegation/make_vectors.mjs --contract-src <dir with delegation.ts, findings.ts> \
//     --claims <contract fixtures/positive dir> [--out test/fixtures/delegation/vectors.json]
//
// <dir> is a copy of the contract's src/delegation.ts and src/findings.ts at the pin, with the import of
// "./findings.js" rewritten to "./findings.ts" so Node runs it with type stripping (Node 23.6+).

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// The raw Ed25519 truth comes from crypto.verify, which accepts small-order forgeries before Node 24 (CT-29).
if (Number(process.versions.node.split('.')[0]) < 24) { console.error('run make_vectors.mjs on Node 24 or later'); process.exit(2); }
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const here = path.dirname(fileURLToPath(import.meta.url));
const out = args.out ?? path.join(here, 'vectors.json');
const contract = await import(pathToFileURL(path.join(args['contract-src'], 'delegation.ts')).href);
const load = (name) => JSON.parse(fs.readFileSync(path.join(args.claims, name), 'utf8'));

// --- fixed keys ---------------------------------------------------------------------------------------
const PKCS8_ED25519 = Buffer.from('302e020100300506032b657004220420', 'hex');
const seed = (label) => crypto.createHash('sha256').update(`fabric-agent-adapter delegation vectors: ${label}`).digest();
const keyPair = (label) => {
  const privateKey = crypto.createPrivateKey({ key: Buffer.concat([PKCS8_ED25519, seed(label)]), format: 'der', type: 'pkcs8' });
  return { privateKey, publicKey: crypto.createPublicKey(privateKey) };
};
const current = keyPair('current');
const previous = keyPair('previous');
const stranger = keyPair('stranger');
const publicJwk = (key, kid, extra = {}) => ({ ...key.export({ format: 'jwk' }), kid, use: 'sig', alg: 'EdDSA', ...extra });
const jwks = { keys: [publicJwk(current.publicKey, 'estate-new'), publicJwk(previous.publicKey, 'estate-old')] };

const b64 = (text) => Buffer.from(text).toString('base64url');
function sign(payload, { header = {}, key = current.privateKey, typ = contract.DELEGATION_TYP, rawPayload } = {}) {
  const h = b64(JSON.stringify({ alg: 'EdDSA', typ, kid: 'estate-new', ...header }));
  const p = b64(rawPayload ?? JSON.stringify(payload));
  const s = crypto.sign(null, Buffer.from(`${h}.${p}`), key).toString('base64url');
  return `${h}.${p}.${s}`;
}

// --- delegation cases (mirroring the contract's test/delegation.test.ts) ----------------------------------
const claims = load('delegation-token-claims.json');
const NOW = claims.iat + 30;
const ISSUER = 'urn:fabric:estate:example';
const call = { audience: 'example-writer', jwks, now: NOW, capability: 'writer.write', effect: 'draft', issuer: ISSUER };
const dropNulls = (o) => { for (const k of Object.keys(o)) if (o[k] === null) delete o[k]; return o; };
const token = (overrides = {}, options = {}) => sign({ ...claims, ...overrides }, options);
const nest = (n) => { let act; for (let i = n; i >= 1; i--) act = act ? { sub: `agent-${i}`, act } : { sub: `agent-${i}` }; return act; };
const leInt = (buf) => { let n = 0n; for (let i = buf.length - 1; i >= 0; i--) n = (n << 8n) | BigInt(buf[i]); return n; };
const L = (1n << 252n) + 27742317777372353535851937790883648493n;
const malleate = (jwt) => {
  const [h, p, s] = jwt.split('.');
  const sig = Buffer.from(s, 'base64url');
  let S = 0n; for (let i = 31; i >= 0; i--) S = (S << 8n) | BigInt(sig[32 + i]);
  S += L;
  const out = Buffer.from(sig);
  for (let i = 0; i < 32; i++) { out[32 + i] = Number(S & 0xffn); S >>= 8n; }
  return `${h}.${p}.${out.toString('base64url')}`;
};
const tamper = (jwt) => { const [h, , s] = jwt.split('.'); return `${h}.${b64(JSON.stringify({ ...claims, aud: 'example-writer', scope: 'writer.write writer.admin' }))}.${s}`; };

const delegation = [
  ['accepted, issuer checked', token(), { issuer: 'urn:fabric:estate:example' }],
  ['accepted, previous key still published', token({}, { key: previous.privateKey, header: { kid: 'estate-old' } }), {}],
  ['previous key rotated out', token({}, { key: previous.privateKey, header: { kid: 'estate-old' } }), { jwks: { keys: [jwks.keys[0]] } }],
  ['no key set', token(), { jwks: null }],
  ['empty key set', token(), { jwks: { keys: [] } }],
  ['published key carries a private member', token(), { jwks: { keys: [{ ...jwks.keys[0], d: 'AAAA' }] } }],
  ['kid published twice', token(), { jwks: { keys: [jwks.keys[0], { ...jwks.keys[1], kid: 'estate-new' }] } }],
  ['key published for encryption', token(), { jwks: { keys: [{ ...jwks.keys[0], use: 'enc' }] } }],
  ['key published for another alg', token(), { jwks: { keys: [{ ...jwks.keys[0], alg: 'ES256' }] } }],
  ['key of another curve', token(), { jwks: { keys: [{ ...jwks.keys[0], crv: 'X25519' }] } }],
  ['key x not a point', token(), { jwks: { keys: [{ ...jwks.keys[0], x: b64('short') }] } }],
  ['alg not EdDSA', token({}, { header: { alg: 'HS256' } }), {}],
  ['typ of an approval', token({}, { typ: contract.APPROVAL_TYP }), {}],
  ['no kid', token({}, { header: { kid: undefined } }), {}],
  ['kid not a string', token({}, { header: { kid: 7 } }), {}],
  ['header points at a key elsewhere (jku)', token({}, { header: { jku: 'https://evil.example/jwks.json' } }), {}],
  ['header carries an embedded jwk', token({}, { header: { jwk: jwks.keys[0] } }), {}],
  ['header carries crit', token({}, { header: { crit: ['exp'] } }), {}],
  ['signed by a stranger', token({}, { key: stranger.privateKey }), {}],
  ['payload changed after signing', tamper(token()), {}],
  ['signature malleated to S + L', malleate(token()), {}],
  ['signature one byte short', (() => { const [h, p, s] = token().split('.'); return `${h}.${p}.${Buffer.from(s, 'base64url').subarray(0, 63).toString('base64url')}`; })(), {}],
  ['two segments', token().split('.').slice(0, 2).join('.'), {}],
  ['four segments', `${token()}.x`, {}],
  ['segment not base64url', token().replace('.', '.+'), {}],
  ['payload not an object', sign(null, { rawPayload: '[1,2]' }), {}],
  ['payload not JSON', sign(null, { rawPayload: '{"iss":' }), {}],
  ['a claim named twice', sign(null, { rawPayload: JSON.stringify(claims).replace('"aud":"example-writer"', '"aud":"example-writer","aud":"example-writer"') }), {}],
  ['a nested member named twice', sign(null, { rawPayload: JSON.stringify(claims).replace('"sub":"example-media"', '"sub":"example-media","sub":"x"') }), {}],
  ['a duplicate-looking key inside a string', sign(null, { rawPayload: JSON.stringify({ ...claims, project: 'urn:project:"aud":"x","aud"' }) }), {}],
  ['too long', `${token()}${'A'.repeat(8192)}`, {}],
  ['claims missing jti', token({ jti: undefined }), {}],
  ['iat not an integer', token({ iat: claims.iat + 0.5 }), {}],
  ['iat negative', token({ iat: -1 }), {}],
  ['effect empty', token({ effect: [] }), {}],
  ['effect unknown class', token({ effect: ['launch'] }), {}],
  ['grant empty', token({ grant: [] }), {}],
  ['act not an object', token({ act: 'example-media' }), {}],
  ['no act claim', token({ act: undefined }), {}],
  ['wrong issuer', token(), { issuer: 'urn:fabric:estate:other' }],
  ['no trusted issuer', token(), { issuer: null }],
  ['two grants', token({ grant: [...claims.grant, 'urn:grant:project-a:other#1'] }), {}],
  ['effect named twice', token({ effect: ['draft', 'draft'] }), {}],
  ['scope with an upper-case name', token({ scope: 'Writer.write' }), { capability: 'Writer.write' }],
  ['scope with a double space', token({ scope: 'writer.write  writer.check' }), {}],
  ['sub not a URI', token({ sub: 'operator' }), {}],
  ['aud not an agent id', token({ aud: 'Example Writer' }), { audience: 'Example Writer' }],
  ['actor sub not an agent id', token({ act: { sub: 'Example Media' } }), {}],
  ['actor session not an opaque id', token({ act: { sub: 'example-media', session: 'has space' } }), {}],
  ['task claim', token({ task: 'task-42' }), {}],
  ['task not an opaque id', token({ task: 'a b' }), {}],
  ['spend limited with no window', token({ spend: { mode: 'limited', remaining: [] } }), {}],
  ['spend unlimited', token({ spend: { mode: 'unlimited' } }), {}],
  ['jti too short', token({ jti: 'short' }), {}],
  ['project not a URI', token({ project: 'project a' }), {}],
  ['lifetime above 600 s', token({ exp: claims.iat + 601 }), {}],
  ['exp equals iat', token({ exp: claims.iat }), {}],
  ['issued more than 60 s in the future', token({ iat: NOW + 61, exp: NOW + 600 }), {}],
  ['issued 60 s in the future', token({ iat: NOW + 60, exp: NOW + 600 }), {}],
  ['nbf in the future', token({ nbf: NOW + 61 }), {}],
  ['nbf not a number', token({ nbf: 'soon' }), {}],
  ['nbf within leeway', token({ nbf: NOW + 60 }), {}],
  ['expired by 61 s', token(), { now: claims.exp + 61 }],
  ['expired by 60 s holds', token(), { now: claims.exp + 60 }],
  ['another callee', token(), { audience: 'example-reader' }],
  ['chain of four', token({ act: nest(4) }), {}],
  ['chain of five', token({ act: nest(5) }), {}],
  ['chain with an actor missing sub', token({ act: { sub: 'a', act: { session: 'x' } } }), {}],
  ['capability not in scope', token(), { capability: 'writer.delete' }],
  ['capability a prefix of a scope name', token(), { capability: 'writer' }],
  ['capability a whole later name', token(), { capability: 'writer.check' }],
  ['effect none under a draft ceiling', token(), { effect: 'none' }],
  ['effect publish above a draft ceiling', token(), { effect: 'publish' }],
  ['draft under an external ceiling', token({ effect: ['delete'] }), { effect: 'draft' }],
  ['charge not under delete', token({ effect: ['delete'] }), { effect: 'charge' }],
  ['none under a none ceiling', token({ effect: ['none'] }), { effect: 'none' }],
  ['draft not under a none ceiling', token({ effect: ['none'] }), { effect: 'draft' }],
  ['read-only door refuses a draft', token(), { readOnly: true }],
  ['read-only door serves a read', token(), { readOnly: true, effect: 'none' }],
  ['an approval presented as a token', sign(load('approval-claims.json'), { typ: contract.APPROVAL_TYP }), {}],
  ['not a string', 42, {}],
  ['forged under a small-order placeholder key', (() => {
    const zero = Buffer.alloc(32);
    const h = b64(JSON.stringify({ alg: 'EdDSA', typ: contract.DELEGATION_TYP, kid: 'estate-zero' }));
    for (let i = 0; ; i++) {
      const p = b64(JSON.stringify({ ...claims, jti: `forged-${i}` }));
      const k = leInt(crypto.createHash('sha512').update(Buffer.concat([Buffer.from('5866666666666666666666666666666666666666666666666666666666666666', 'hex'), zero, Buffer.from(`${h}.${p}`)])).digest()) % L;
      if (k % 4n === 0n) return `${h}.${p}.${Buffer.concat([Buffer.from('5866666666666666666666666666666666666666666666666666666666666666', 'hex'), Buffer.from([1]), Buffer.alloc(31)]).toString('base64url')}`;
    }
  })(), { jwks: { keys: [...jwks.keys, { kty: 'OKP', crv: 'Ed25519', x: Buffer.alloc(32).toString('base64url'), kid: 'estate-zero', use: 'sig', alg: 'EdDSA' }] } }],
].map(([name, tok, overrides]) => {
  const options = dropNulls({ ...call, ...overrides });
  let result;
  // A case the contract's verifier throws on is kept, marked, with no expected answer: the kits refuse it
  // (the test names the refusal), and the contract is told. Nothing here is written by hand.
  try { result = contract.verifyDelegation(tok, options); } catch (error) { return { name, token: tok, options, expected: null, contractThrew: String(error.message).slice(0, 120) }; }
  return { name, token: tok, options, expected: result.ok ? { ok: true, principal: result.principal, caller: result.caller, chain: result.chain, kid: result.kid } : { ok: false, code: result.code, detail: result.detail } };
});

// --- approval cases --------------------------------------------------------------------------------------
const approvalClaims = load('approval-claims.json');
const action = { capability: 'publisher.push', input: { app: 'example-app', hash: `sha256:${'ab'.repeat(32)}`, store: 'app-store' } };
const aOptions = { audience: 'example-publisher', jwks, now: approvalClaims.iat + 60, actionDigest: approvalClaims.actionDigest, issuer: ISSUER };
const approval = (overrides = {}, options = {}) => sign({ ...approvalClaims, ...overrides }, { typ: contract.APPROVAL_TYP, ...options });
const approvals = [
  ['accepted once, refused the second time', [approval(), approval()], {}],
  ['replayed an hour later', [approval(), approval()], {}, [0, 3600]],
  ['missing', [null], {}],
  ['empty string', [''], {}],
  ['no jti store', [approval()], { jtiStore: 'none' }],
  ['no key set', [approval()], { jwks: null }],
  ['another action', [approval()], { actionDigest: contract.actionDigest({ ...action, input: { ...action.input, store: 'google-play' } }) }],
  ['another callee', [approval()], { audience: 'example-writer' }],
  ['expired', [approval()], { now: approvalClaims.exp + 61 }],
  ['lifetime above 24 h', [approval({ exp: approvalClaims.iat + 86401 })], {}],
  ['issued in the future', [approval()], { now: approvalClaims.iat - 61 }],
  ['signed by a stranger', [approval({}, { key: stranger.privateKey })], {}],
  ['a delegation token presented as an approval', [sign(approvalClaims)], {}],
  ['unknown method', [approval({ method: 'chat-message' })], {}],
  ['method device, removed by DEC-0045', [approval({ method: 'device' })], {}],
  ['no trusted issuer', [approval()], { issuer: null }],
  ['wrong issuer', [approval()], { issuer: 'urn:fabric:estate:other' }],
].map(([name, documents, overrides, offsets = [0, 0]]) => {
  const store = contract.createMemoryJtiStore();
  const steps = documents.map((doc, i) => {
    const options = dropNulls({ ...aOptions, jtiStore: store, ...overrides, now: (overrides.now ?? aOptions.now) + (offsets[i] ?? 0) });
    const contractOptions = { ...options, jtiStore: options.jtiStore === 'none' ? undefined : options.jtiStore };
    const result = contract.verifyApproval(doc ?? undefined, contractOptions);
    const { jtiStore, ...wire } = options;
    return { approval: doc, options: { ...wire, jtiStore: jtiStore === 'none' ? 'none' : 'shared' }, expected: result.ok ? { ok: true, approver: result.approver, method: result.method, kid: result.kid } : { ok: false, code: result.code, detail: result.detail, ...(result.data ? { data: result.data } : {}) } };
  });
  return { name, steps };
});

// --- headers, canonical JSON, digests ----------------------------------------------------------------------
const jwt = token();
const headers = [
  { 'fabric-delegation': jwt, authorization: 'Bearer product-key' },
  { 'Fabric-Delegation': '  ' },
  { Authorization: `Bearer ${jwt}` },
  { authorization: `bearer ${jwt}` },
  { Authorization: 'Bearer opaque-descriptor-token' },
  { Authorization: `Bearer ${approval()}` },
  { Authorization: `Basic ${jwt}` },
  {},
].map((h) => ({ headers: h, expected: contract.readDelegationToken(h) ?? null }));

const jcsInputs = [
  '{"numbers":[333333333.33333329,1E30,4.50,2e-3,0.000000000000000000000000001],"string":"\\u20ac$\\u000F\\u000aA\'\\u0042\\u0022\\u005c\\\\\\"\\/","literals":[null,true,false]}',
  '[1.0,-0.0,0,1e21,1e20,123456789012345680000,0.1,1e-7,5e-324,1.7976931348623157e308,-1.5,100,2.5e-5]',
  '{"\\u20ac":1,"\\ud83d\\ude00":2,"a":3,"A":4,"\\u00e9":5,"\\ufb33":6,"":7}',
  '"\\u0000\\u001f\\u007f\\u2028\\b\\f\\n\\r\\t"',
  '{"b":{"z":[{"y":1,"x":2}],"a":null},"a":true}',
];
const jcsCases = jcsInputs.map((input) => ({ input, expected: contract.jcs(JSON.parse(input)) }));
const digests = [action, { input: { store: 'app-store', hash: action.input.hash, app: 'example-app' }, capability: 'publisher.push' }]
  .map((value) => ({ input: JSON.stringify(value), expected: contract.actionDigest(value) }));

// --- raw Ed25519 (the Python kit's own implementation is checked against OpenSSL) ------------------------------
const ed25519 = [];
for (let i = 0; i < 64; i++) {
  const pair = keyPair(`raw-${i}`);
  const msg = crypto.createHash('sha512').update(`message ${i}`).digest().subarray(0, i % 64);
  const sig = crypto.sign(null, msg, pair.privateKey);
  const pub = Buffer.from(pair.publicKey.export({ format: 'jwk' }).x, 'base64url');
  const variants = [['valid', sig, msg, pub]];
  const flipped = Buffer.from(sig); flipped[i % 64] ^= 1 << (i % 8); variants.push(['bit flipped', flipped, msg, pub]);
  const other = Buffer.from(msg.length ? msg : Buffer.from('x')); other[0] ^= 1; variants.push(['message changed', sig, other, pub]);
  const [h, p] = ['a', 'b'];
  variants.push(['S + L', Buffer.from(malleate(`${h}.${p}.${sig.toString('base64url')}`).split('.')[2], 'base64url'), msg, pub]);
  const badKey = Buffer.from(pub); badKey[31] ^= 0x40; variants.push(['key changed', sig, msg, badKey]);
  for (const [kind, s, m, k] of variants) {
    let valid;
    try { valid = crypto.verify(null, m, crypto.createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: k.toString('base64url') }, format: 'jwk' }), s); } catch { valid = false; }
    ed25519.push({ kind, pub: k.toString('hex'), msg: m.toString('hex'), sig: s.toString('hex'), valid });
  }
}
// Small-order public keys: R = B, S = 1 satisfies the cofactorless equation whenever k = H(R||A||M) is a multiple
// of the key's order, so a verifier that does not refuse such keys accepts a signature nobody made. OpenSSL refuses.
const SMALL_ORDER = ['0100000000000000000000000000000000000000000000000000000000000000', 'ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f',
  '0000000000000000000000000000000000000000000000000000000000000080', '0000000000000000000000000000000000000000000000000000000000000000',
  'c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a', 'c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa',
  '26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05', '26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85'];
const BASE = Buffer.from('5866666666666666666666666666666666666666666666666666666666666666', 'hex');
const ONE = Buffer.concat([Buffer.from([1]), Buffer.alloc(31)]);
const kOf = (pub, msg) => leInt(crypto.createHash('sha512').update(Buffer.concat([BASE, pub, msg])).digest()) % L;
for (const hex of SMALL_ORDER) {
  const pub = Buffer.from(hex, 'hex');
  let msg; for (let i = 0; ; i++) { msg = Buffer.from(`forged ${i}`); if (kOf(pub, msg) % 8n === 0n) break; }
  let valid; try { valid = crypto.verify(null, msg, crypto.createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: pub.toString('base64url') }, format: 'jwk' }), Buffer.concat([BASE, ONE])); } catch { valid = false; }
  ed25519.push({ kind: 'small-order key, forged', pub: hex, msg: msg.toString('hex'), sig: Buffer.concat([BASE, ONE]).toString('hex'), valid });
}
// RFC 8032 §7.1 TEST 1 and TEST 2, checked here by OpenSSL too.
for (const [pub, msg, sig] of [
  ['d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a', '', 'e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b'],
  ['3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c', '72', '92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00'],
]) {
  const valid = crypto.verify(null, Buffer.from(msg, 'hex'), crypto.createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: Buffer.from(pub, 'hex').toString('base64url') }, format: 'jwk' }), Buffer.from(sig, 'hex'));
  ed25519.push({ kind: 'RFC 8032', pub, msg, sig, valid });
}

const doc = {
  about: 'Shared cases for the kits\' delegation verifiers (DEC-0039). Generated by make_vectors.mjs; expected answers from the contract\'s src/delegation.ts at the pin. Do not edit by hand.',
  constants: { leewaySeconds: contract.LEEWAY_SECONDS, maxChainDepth: contract.MAX_CHAIN_DEPTH, refusalCodes: [...contract.REFUSAL_CODES] },
  jwks,
  delegation,
  approvals,
  headers,
  jcs: jcsCases,
  digests,
  ed25519,
};
fs.writeFileSync(out, `${JSON.stringify(doc, null, 1)}\n`);
console.log(`wrote ${out}: ${delegation.length} delegation, ${approvals.length} approval, ${headers.length} header, ${jcsCases.length} jcs, ${ed25519.length} ed25519 cases`);
