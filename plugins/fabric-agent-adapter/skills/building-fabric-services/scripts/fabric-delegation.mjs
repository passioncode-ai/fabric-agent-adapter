// The callee's side of fabric-delegation/0.1 (Fabric Agent Contract DEC-0039, Fabric ADR-0144): check a
// delegation token or an approval offline against the estate's published keys, and answer `ok` or one refusal
// code. A port of the contract's `src/delegation.ts` at the pinned revision; the shared vectors in
// `test/fixtures/delegation/vectors.json` hold it to that verifier's exact answers. Node's own crypto verifies
// Ed25519; no dependencies.
//
//   import { JwksCache, delegationGate, refusalToolResult } from './fabric-delegation.mjs';
//   const gate = delegationGate({ audience: 'example-agent', jwks: new JwksCache(wk.auth.delegation.jwks),
//     effects: { 'example.write': 'draft' }, issuer: wk.auth.delegation.issuer });
//   const verdict = await gate(toolName, req.headers);   // before the tool runs
//   if (!verdict.ok) return refusalToolResult(verdict);

import crypto from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';

export const REFUSAL_CODES = Object.freeze([
  'unauthenticated', 'token-expired', 'wrong-audience', 'scope-not-granted', 'effect-above-ceiling', 'no-grant',
  'grant-expired', 'grant-revoked', 'limit-reached', 'approval-required', 'approval-invalid', 'approval-reused',
  'principal-unproven', 'credential-source-refused', 'chain-too-deep', 'issuer-unavailable', 'unknown-state',
]);
export const EFFECT_CLASSES = Object.freeze(['none', 'draft', 'publish', 'send', 'reply', 'charge', 'delete', 'merge', 'deploy', 'change-policy']);
export const DELEGATION_HEADER = 'Fabric-Delegation';
export const DELEGATION_TYP = 'fabric-delegation+jwt';
export const APPROVAL_TYP = 'fabric-approval+jwt';
export const MAX_DELEGATION_LIFETIME_SECONDS = 600;
export const MAX_APPROVAL_LIFETIME_SECONDS = 86_400;
export const MAX_CHAIN_DEPTH = 4;
export const LEEWAY_SECONDS = 60;
/** DL-15: cache the key set at most 10 minutes; re-read it at most once a minute for an unknown kid. */
export const JWKS_MAX_AGE_SECONDS = 600;
export const JWKS_REREAD_SECONDS = 60;

const REFUSAL_STATUS = { unauthenticated: 401, 'token-expired': 401, 'principal-unproven': 401, 'issuer-unavailable': 503, 'unknown-state': 503 };
export const REFUSAL_MESSAGES = Object.freeze({
  unauthenticated: 'No delegation token, or one not signed by a published key or not of this profile.',
  'token-expired': 'The delegation token has expired; mint a new one.',
  'wrong-audience': 'The delegation token is for another callee.',
  'scope-not-granted': "The called capability is not in the token's scope.",
  'effect-above-ceiling': "The capability's effect is above the token's ceiling.",
  'no-grant': 'No live grant covers this call.',
  'grant-expired': 'The grant has expired.',
  'grant-revoked': 'The grant was revoked.',
  'limit-reached': 'A spend window is exhausted.',
  'approval-required': 'This action needs an approval; ask the hub for one with the action digest.',
  'approval-invalid': 'The approval is not valid for this action, callee or time.',
  'approval-reused': 'The approval was already used.',
  'principal-unproven': "The caller's proof is missing or stale.",
  'credential-source-refused': 'The grant names a credential source that is not allowed.',
  'chain-too-deep': 'The actor chain is deeper than four.',
  'issuer-unavailable': "The estate's published keys cannot be read.",
  'unknown-state': 'The state cannot be established, so the call is refused.',
});

const refuse = (code, detail, data) => (data ? { ok: false, code, detail, data } : { ok: false, code, detail });
const B64URL = /^[A-Za-z0-9_-]+$/;
const isObject = (value) => typeof value === 'object' && value !== null && !Array.isArray(value);
const isString = (value) => typeof value === 'string' && value.length > 0;
const isTime = (value) => typeof value === 'number' && Number.isInteger(value) && value >= 0;

/** Whether a JSON text repeats a member name in one object: refused, never resolved (RFC 7515 §5.2, RFC 8725 §3.2). */
export function hasDuplicateMembers(text) {
  const stack = [];
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') {
      let j = i + 1;
      while (j < text.length && text[j] !== '"') j += text[j] === '\\' ? 2 : 1;
      const top = stack[stack.length - 1];
      if (top?.keys && top.expectKey) {
        const key = JSON.parse(text.slice(i, j + 1));
        if (top.keys.has(key)) return true;
        top.keys.add(key);
        top.expectKey = false;
      }
      i = j;
    } else if (c === '{') stack.push({ keys: new Set(), expectKey: true });
    else if (c === '[') stack.push({ expectKey: false });
    else if (c === '}' || c === ']') stack.pop();
    else if (c === ',') { const top = stack[stack.length - 1]; if (top?.keys) top.expectKey = true; }
  }
  return false;
}

function decodeSegment(segment) {
  if (!B64URL.test(segment)) return { problem: 'malformed' };
  try {
    const text = Buffer.from(segment, 'base64url').toString('utf8');
    const value = JSON.parse(text);
    if (!isObject(value)) return { problem: 'malformed' };
    return hasDuplicateMembers(text) ? { problem: 'duplicate-member' } : { value };
  } catch {
    return { problem: 'malformed' };
  }
}

function parseCompact(token) {
  if (typeof token !== 'string' || token.length > 8192) return { problem: 'malformed' };
  const parts = token.split('.');
  if (parts.length !== 3) return { problem: 'malformed' };
  const [h, p, s] = parts;
  const header = decodeSegment(h);
  const payload = decodeSegment(p);
  if (!B64URL.test(s)) return { problem: 'malformed' };
  for (const part of [header, payload]) if ('problem' in part) return { problem: part.problem };
  return { header: header.value, payload: payload.value, signingInput: Buffer.from(`${h}.${p}`, 'ascii'), signature: Buffer.from(s, 'base64url') };
}

function headerProblem(header, typ) {
  if (header.alg !== 'EdDSA') return 'alg-not-eddsa';
  if (header.typ !== typ) return 'wrong-typ';
  if (!isString(header.kid)) return 'no-kid';
  for (const member of ['crit', 'jku', 'jwk', 'x5u', 'x5c']) if (header[member] !== undefined) return `header-${member}`;
  return undefined;
}

function keyFor(jwks, kid) {
  const matches = jwks.keys.filter((candidate) => isObject(candidate) && candidate.kid === kid);
  if (matches.length > 1) return { problem: 'duplicate-kid' };
  const jwk = matches[0];
  if (!jwk) return { problem: 'unknown-key' };
  // A key published for another use or algorithm is never a candidate (RFC 7517 §4.2, §4.4).
  if ((jwk.use !== undefined && jwk.use !== 'sig') || (jwk.alg !== undefined && jwk.alg !== 'EdDSA')) return { problem: 'key-not-for-signing' };
  if (jwk.kty !== 'OKP' || jwk.crv !== 'Ed25519' || !isString(jwk.x) || jwk.d !== undefined) return { problem: 'unusable-key' };
  try {
    return { key: crypto.createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: jwk.x }, format: 'jwk' }) };
  } catch {
    return { problem: 'unusable-key' };
  }
}

const hasKeys = (jwks) => isObject(jwks) && Array.isArray(jwks.keys) && jwks.keys.length > 0;

/** Parse, check the header, find the key, verify the signature. A fault of the published keys is the issuer's. */
function authentic(token, jwks, typ) {
  const compact = parseCompact(token);
  if ('problem' in compact) return { problem: compact.problem };
  const header = headerProblem(compact.header, typ);
  if (header) return { problem: header };
  const kid = compact.header.kid;
  const found = keyFor(jwks, kid);
  if ('problem' in found) return found.problem === 'unusable-key' || found.problem === 'duplicate-kid' ? { problem: found.problem, issuer: true } : { problem: found.problem };
  if (compact.signature.length !== 64 || !crypto.verify(null, compact.signingInput, found.key, compact.signature)) return { problem: 'bad-signature' };
  return { compact, kid };
}

/** Depth of an actor chain; Infinity for a chain that is not one (a missing or non-string sub at any level). */
export function chainDepth(act) {
  let depth = 0;
  let node = act;
  while (node !== undefined) {
    if (!isObject(node) || !isString(node.sub)) return Number.POSITIVE_INFINITY;
    depth += 1;
    if (depth > 64) return depth;
    node = node.act;
  }
  return depth;
}

function chainOf(act) {
  const chain = [];
  for (let node = act; node; node = node.act) chain.push(node.sub);
  return chain;
}

/** `none` is below every class and `draft` below every external one; external classes are not ordered. */
export function effectClosure(ceiling) {
  const admitted = new Set(ceiling);
  if (ceiling.length > 0) admitted.add('none');
  if (ceiling.some((effect) => effect !== 'none')) admitted.add('draft');
  return admitted;
}

export const effectWithin = (effect, ceiling) => effectClosure(ceiling).has(effect);

function delegationShape(payload) {
  const { iss, sub, act, aud, scope, effect, grant, iat, exp, jti } = payload;
  if (!isString(iss) || !isString(sub) || !isString(aud) || !isString(scope) || !isString(jti) || !isTime(iat) || !isTime(exp)) return undefined;
  if (!Array.isArray(effect) || effect.length === 0 || !effect.every((e) => EFFECT_CLASSES.includes(e))) return undefined;
  if (!Array.isArray(grant) || grant.length === 0 || !grant.every(isString)) return undefined;
  if (!isObject(act)) return undefined;
  return payload;
}

function approvalShape(payload) {
  const { iss, actionDigest: digest, aud, approver, method, iat, exp, jti } = payload;
  if (!isString(iss) || !isString(digest) || !isString(aud) || !isString(approver) || !isString(jti) || !isTime(iat) || !isTime(exp)) return undefined;
  if (method !== 'prompt' && method !== 'operator-channel' && method !== 'device') return undefined;
  return payload;
}

/**
 * DL-13, in its fixed order: nothing about a token is believed before its signature is. `now` is seconds since
 * the epoch. Answers {ok: true, claims, principal, caller, chain, kid} or {ok: false, code, detail}.
 */
export function verifyDelegation(token, { audience, jwks, now, capability, effect, issuer, readOnly } = {}) {
  if (!hasKeys(jwks)) return refuse('issuer-unavailable', 'no-published-keys');
  const checked = authentic(token, jwks, DELEGATION_TYP);
  if ('problem' in checked) return refuse(checked.issuer ? 'issuer-unavailable' : 'unauthenticated', checked.problem);
  const claims = delegationShape(checked.compact.payload);
  if (!claims) return refuse('unauthenticated', 'malformed-claims');
  if (issuer !== undefined && claims.iss !== issuer) return refuse('unauthenticated', 'wrong-issuer');
  if (claims.exp <= claims.iat || claims.exp - claims.iat > MAX_DELEGATION_LIFETIME_SECONDS) return refuse('unauthenticated', 'lifetime-above-profile');
  if (claims.iat > now + LEEWAY_SECONDS) return refuse('unauthenticated', 'issued-in-future');
  const { nbf } = checked.compact.payload;
  if (nbf !== undefined && (!isTime(nbf) || nbf > now + LEEWAY_SECONDS)) return refuse('unauthenticated', 'not-yet-valid');
  if (now > claims.exp + LEEWAY_SECONDS) return refuse('token-expired', 'expired');
  if (claims.aud !== audience) return refuse('wrong-audience', 'audience-mismatch');
  const depth = chainDepth(claims.act);
  if (!Number.isFinite(depth)) return refuse('unauthenticated', 'malformed-chain');
  if (depth > MAX_CHAIN_DEPTH) return refuse('chain-too-deep', `depth-${depth}`);
  if (!claims.scope.split(' ').includes(capability)) return refuse('scope-not-granted', 'capability-not-in-scope');
  if (readOnly && effect !== 'none') return refuse('effect-above-ceiling', 'read-only-door');
  if (!effectWithin(effect, claims.effect)) return refuse('effect-above-ceiling', `effect-${effect}`);
  return { ok: true, claims, principal: claims.sub, caller: claims.act.sub, chain: chainOf(claims.act), kid: checked.kid };
}

/** DL-18: approval-required carries the digest; any fault is approval-invalid; the jti is consumed last. */
export function verifyApproval(approval, { audience, jwks, now, actionDigest: expected, issuer, jtiStore } = {}) {
  if (approval === undefined || approval === null || approval === '') return refuse('approval-required', 'no-approval', { actionDigest: expected });
  if (!isObject(jtiStore) || typeof jtiStore.consume !== 'function') return refuse('unknown-state', 'no-jti-store');
  if (!hasKeys(jwks)) return refuse('issuer-unavailable', 'no-published-keys');
  const checked = authentic(approval, jwks, APPROVAL_TYP);
  if ('problem' in checked) return refuse(checked.issuer ? 'issuer-unavailable' : 'approval-invalid', checked.problem);
  const claims = approvalShape(checked.compact.payload);
  if (!claims) return refuse('approval-invalid', 'malformed-claims');
  if (issuer !== undefined && claims.iss !== issuer) return refuse('approval-invalid', 'wrong-issuer');
  if (claims.exp <= claims.iat || claims.exp - claims.iat > MAX_APPROVAL_LIFETIME_SECONDS) return refuse('approval-invalid', 'lifetime-above-profile');
  if (claims.iat > now + LEEWAY_SECONDS) return refuse('approval-invalid', 'issued-in-future');
  if (now > claims.exp + LEEWAY_SECONDS) return refuse('approval-invalid', 'expired');
  if (claims.aud !== audience) return refuse('approval-invalid', 'audience-mismatch');
  if (claims.actionDigest !== expected) return refuse('approval-invalid', 'digest-mismatch', { actionDigest: expected });
  if (!jtiStore.consume(claims.jti, claims.exp, now)) return refuse('approval-reused', 'jti-consumed');
  return { ok: true, claims, approver: claims.approver, method: claims.method, kid: checked.kid };
}

/** Consumed approval ids in memory: for tests and a single process that never restarts mid-approval. */
export function createMemoryJtiStore() {
  const seen = new Map();
  return {
    consume(jti, expiresAt, now) {
      for (const [id, until] of seen) if (until + LEEWAY_SECONDS < now) seen.delete(id);
      if (seen.has(jti)) return false;
      seen.set(jti, expiresAt);
      return true;
    },
  };
}

/** Consumed approval ids in a 0600 JSON file, so a second use is refused across a restart (DL-18). */
export class FileJtiStore {
  constructor(file) { this.file = file; }

  consume(jti, expiresAt, now) {
    let seen = {};
    try { const read = JSON.parse(fs.readFileSync(this.file, 'utf8')); if (isObject(read)) seen = read; } catch { seen = {}; }
    seen = Object.fromEntries(Object.entries(seen).filter(([, until]) => typeof until === 'number' && until + LEEWAY_SECONDS >= now));
    if (Object.hasOwn(seen, jti)) return false;
    seen[jti] = expiresAt;
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const temp = path.join(path.dirname(this.file), `.${path.basename(this.file)}.${crypto.randomBytes(4).toString('hex')}.tmp`);
    const fd = fs.openSync(temp, 'wx', 0o600);
    try { fs.writeSync(fd, JSON.stringify(seen)); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    fs.renameSync(temp, this.file);
    return true;
  }
}

/** Every approval may be replayed until it expires. Only on purpose, by name. */
export const UNSAFE_NO_JTI_STORE = Object.freeze({ consume: () => true });

function header(headers, name) {
  if (!headers) return undefined;
  if (typeof headers.get === 'function' && !(headers instanceof Map)) { const v = headers.get(name); return v === null ? undefined : v; }
  const entry = Object.entries(headers).find(([key]) => key.toLowerCase() === name.toLowerCase())?.[1];
  return Array.isArray(entry) ? (entry[0] ?? '') : entry;
}

/** DL-9, DL-10: Fabric-Delegation first (present but empty is still the token), then a delegation-typ Bearer JWT. */
export function readDelegationToken(headers) {
  const forwarded = header(headers, DELEGATION_HEADER);
  if (forwarded !== undefined) return { token: String(forwarded).trim(), via: 'fabric-delegation' };
  const bearer = /^Bearer\s+(\S+)$/i.exec(header(headers, 'Authorization') ?? '')?.[1];
  const parsed = bearer ? parseCompact(bearer) : undefined;
  if (bearer && parsed && !('problem' in parsed) && parsed.header.typ === DELEGATION_TYP) return { token: bearer, via: 'authorization' };
  return undefined;
}

/** RFC 8785: members sorted by UTF-16 code units, numbers in ECMAScript form; refuses what has no canonical form. */
export function jcs(value) {
  if (value === null || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new TypeError('a non-finite number has no canonical form');
    return JSON.stringify(value);
  }
  if (typeof value === 'string') {
    if (/\p{Surrogate}/u.test(value)) throw new TypeError('a lone surrogate has no canonical form');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${Array.from(value, (item) => jcs(item)).join(',')}]`;
  if (isObject(value)) {
    const prototype = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null) throw new TypeError('only plain JSON objects have a canonical form');
    const keys = Object.keys(value).sort();
    return `{${keys.map((key) => `${jcs(key)}:${jcs(value[key])}`).join(',')}}`;
  }
  throw new TypeError(`${typeof value} has no canonical form`);
}

/** The digest an approval binds: sha256: and the hex SHA-256 of the action's RFC 8785 form. */
export const actionDigest = (action) => `sha256:${crypto.createHash('sha256').update(jcs(action), 'utf8').digest('hex')}`;

const loopback = (host) => host === 'localhost' || (net.isIP(host.replace(/^\[|\]$/g, '')) !== 0 && (/^127\./.test(host) || host.replace(/^\[|\]$/g, '') === '::1'));

async function defaultFetch(source) {
  if (/^https?:\/\//.test(source)) {
    const response = await fetch(source, { headers: { Accept: 'application/json' }, redirect: 'error', signal: AbortSignal.timeout(5000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const text = await response.text();
    if (text.length > 65536) throw new Error('the key set is too large');
    return JSON.parse(text);
  }
  return JSON.parse(fs.readFileSync(source.replace(/^~(?=\/)/, process.env.HOME ?? '~'), 'utf8'));
}

/**
 * The estate's key set from `auth.delegation.jwks` (https, http on loopback, or a file), cached as DL-15 says.
 * `await get(kid)` answers null when no set younger than 10 minutes can be had (issuer-unavailable).
 */
export class JwksCache {
  constructor(source, { fetch: fetcher = defaultFetch, clock = () => Date.now() / 1000 } = {}) {
    if (typeof source !== 'string' || !source) throw new Error('the key set needs a source');
    if (/^https?:\/\//.test(source)) {
      const url = new URL(source);
      if (url.username || url.password) throw new Error('a key set URL carries no credentials');
      if (url.protocol === 'http:' && !loopback(url.hostname)) throw new Error('a key set is read over https, or over http on loopback only');
    } else if (source.includes('://')) {
      throw new Error('a key set is an https URL, a loopback http URL or a file path');
    }
    Object.assign(this, { source, fetcher, clock, keys: null, readAt: -Infinity, rereadAt: -Infinity, pending: null });
  }

  async read(now) {
    try {
      const value = await this.fetcher(this.source);
      if (hasKeys(value)) { this.keys = value; this.readAt = now; }
    } catch { /* the age check below decides */ }
  }

  async get(kid) {
    const now = this.clock();
    const fresh = now - this.readAt < JWKS_MAX_AGE_SECONDS;
    const known = this.keys !== null && (kid === undefined || kid === null || this.keys.keys.some((k) => isObject(k) && k.kid === kid));
    if (!fresh) await (this.pending ??= this.read(now).finally(() => { this.pending = null; }));
    else if (!known && now - this.rereadAt >= JWKS_REREAD_SECONDS) { this.rereadAt = now; await (this.pending ??= this.read(now).finally(() => { this.pending = null; })); }
    return this.clock() - this.readAt < JWKS_MAX_AGE_SECONDS ? this.keys : null;
  }
}

const kidOf = (token) => { const parsed = parseCompact(token); return 'problem' in parsed || typeof parsed.header.kid !== 'string' ? null : parsed.header.kid; };

/**
 * A check for one tools/call: `await gate(tool, headers)` answers the accepted delegation or a DL-19 refusal.
 * `effects` maps each tool to its declared effect class; a tool with none is refused rather than guessed.
 */
export function delegationGate({ audience, jwks, effects, issuer, readOnly = false, clock = () => Date.now() / 1000 }) {
  return async (tool, headers) => {
    const effect = effects?.[tool];
    if (!EFFECT_CLASSES.includes(effect)) return refuse('unknown-state', 'no-declared-effect');
    const carried = readDelegationToken(headers);
    if (!carried) return refuse('unauthenticated', 'no-token');
    const keys = jwks instanceof JwksCache ? await jwks.get(kidOf(carried.token)) : jwks;
    return verifyDelegation(carried.token, { audience, jwks: keys, now: clock(), capability: tool, effect, readOnly, ...(issuer === undefined ? {} : { issuer }) });
  };
}

/** The DL-19 body: {error: {code, message, data: {detail, ...}}}; never a token or a key. */
export const refusalError = (refusal) => ({ error: { code: refusal.code, message: REFUSAL_MESSAGES[refusal.code] ?? 'Refused.', data: { detail: refusal.detail, ...(refusal.data ?? {}) } } });

/** An MCP tools/call result: the refusal as structuredContent with isError true (DL-19). */
export function refusalToolResult(refusal, traceparent) {
  const structured = refusalError(refusal);
  return { resultType: 'complete', content: [{ type: 'text', text: JSON.stringify(structured) }], structuredContent: structured, isError: true, ...(traceparent ? { _meta: { traceparent } } : {}) };
}

/** An HTTP route's answer: {status, headers, body}; a 401 names the bearer scheme (RFC 6750 §3). */
export function refusalHttp(refusal) {
  const status = REFUSAL_STATUS[refusal.code] ?? 403;
  const headers = { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...(status === 401 ? { 'WWW-Authenticate': 'Bearer error="invalid_token"' } : {}) };
  return { status, headers, body: JSON.stringify(refusalError(refusal)) };
}
