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
import { hubKeyCertified } from './fabric-estate.mjs';

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
/** After a failed read, wait this long before trying again. */
export const JWKS_RETRY_SECONDS = 10;

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
/** DL-2's grammar, as the contract's verifier types the claims (DEC-0045). */
export const AGENT_ID = /^[a-z][a-z0-9-]{1,62}(\.[a-z][a-z0-9-]{0,31})?$/;
export const OPAQUE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const URI = /^[A-Za-z][A-Za-z0-9+.-]*:\S+$/;
const JTI = /^[A-Za-z0-9._~-]{16,128}$/;
const SCOPE = /^[a-z][a-z0-9._-]{1,127}( [a-z][a-z0-9._-]{1,127})*$/;
const SPEND_WINDOWS = ['total', 'task', 'project', 'day', 'week', 'month'];
const isUri = (value) => typeof value === 'string' && URI.test(value);
const isAmount = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0;
import { jcs, isObject } from './fabric-jsvalue.mjs'; // the core's (FAA-65)
export { jcs };
/** A string with at least one character (the token's claims refuse an empty one). */
const isNonEmptyString = (value) => typeof value === 'string' && value.length > 0;
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
  if (!isNonEmptyString(header.kid)) return 'no-kid';
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
  if (jwk.kty !== 'OKP' || jwk.crv !== 'Ed25519' || !isNonEmptyString(jwk.x) || jwk.d !== undefined) return { problem: 'unusable-key' };
  const raw = Buffer.from(jwk.x, 'base64url');
  // D4: exactly the 43 characters that write 32 bytes (Buffer reads padding, `+` and stray characters leniently).
  if (raw.length !== 32 || raw.toString('base64url') !== jwk.x) return { problem: 'unusable-key' };
  if (isSmallOrderKey(raw)) return { problem: 'small-order-key' }; // before any verification (DEC-0045, CT-29)
  try {
    return { key: crypto.createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: jwk.x }, format: 'jwk' }), raw, x: jwk.x };
  } catch {
    return { problem: 'unusable-key' };
  }
}

import { isSmallOrderKey } from './fabric-crypto.mjs'; // the core's (FAA-65)
export { isSmallOrderKey };

const hasKeys = (jwks) => isObject(jwks) && Array.isArray(jwks.keys) && jwks.keys.length > 0;

/** Parse, check the header, find the key, verify the signature. A fault of the published keys is the issuer's. */
function authentic(token, jwks, typ) {
  const compact = parseCompact(token);
  if ('problem' in compact) return { problem: compact.problem };
  const header = headerProblem(compact.header, typ);
  if (header) return { problem: header };
  const kid = compact.header.kid;
  const found = keyFor(jwks, kid);
  // Only an unknown kid is the token's fault; a published key that cannot be used is the issuer's (DL-13 row 3).
  if ('problem' in found) return found.problem === 'unknown-key' ? { problem: found.problem } : { problem: found.problem, issuer: true };
  if (compact.signature.length !== 64 || isSmallOrderKey(found.raw) || !crypto.verify(null, compact.signingInput, found.key, compact.signature)) return { problem: 'bad-signature' };
  return { compact, kid, x: found.x };
}

const ORG_CONTEXT = /^org:[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;
/** DEC-0090: a partner actor is exactly {partner: org:<id>}, never with a sub, a session or an act. */
export const isPartnerActor = (node) => isObject(node) && typeof node.partner === 'string' && ORG_CONTEXT.test(node.partner) && Object.keys(node).length === 1;

/** Depth of an actor chain; Infinity for a chain that is not one (a missing or non-string sub at any level). A partner
 * actor ends the chain and counts, never begins it (DEC-0090). */
export function chainDepth(act) {
  let depth = 0;
  let node = act;
  while (node !== undefined) {
    if (depth > 0 && isPartnerActor(node)) return depth + 1; // a partner actor ends the chain, never begins it
    if (!isObject(node) || !isNonEmptyString(node.sub)) return Number.POSITIVE_INFINITY;
    depth += 1;
    if (depth > 64) return depth;
    node = node.act;
  }
  return depth;
}

function chainOf(act) {
  const chain = [];
  // The contract's chainOf at bfa9a67: a node names its partner only when it is a partner actor (the partner member alone).
  for (let node = act; node; node = 'act' in node ? node.act : undefined) chain.push(isPartnerActor(node) ? node.partner : node.sub);
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

/** The chain's depth when every actor is DL-2's (agent id `sub`, optional session id), else undefined. No `act`, no chain. */
function actorChainDepth(act) {
  if (act === undefined) return undefined;
  let depth = 0;
  for (let node = act; node !== undefined; node = node.act) {
    if (depth > 0 && isPartnerActor(node)) return depth + 1; // DEC-0090: innermost only, it ends the chain
    if (!isObject(node) || typeof node.sub !== 'string' || !AGENT_ID.test(node.sub)) return undefined;
    if (node.session !== undefined && !(typeof node.session === 'string' && OPAQUE_ID.test(node.session))) return undefined;
    depth += 1;
  }
  return depth;
}

function spendShaped(spend) {
  if (!isObject(spend)) return false;
  if (spend.mode === 'unlimited') return true;
  if (spend.mode !== 'limited' || !Array.isArray(spend.remaining) || spend.remaining.length === 0 || spend.remaining.length > 6) return false;
  if (!spend.remaining.every((entry) => isObject(entry) && SPEND_WINDOWS.includes(entry.window) && isAmount(entry.remainingUsd))) return false;
  return spend.perCallMaxUsd === undefined || isAmount(spend.perCallMaxUsd);
}

/** DL-13 row 5 as DEC-0045 types it: {claims, depth} or {problem}. A claim the profile does not know is ignored. */
function delegationShape(payload) {
  const { iss, sub, act, aud, scope, effect, grant, spend, project, task, iat, exp, nbf, jti } = payload;
  const depth = actorChainDepth(act);
  if (depth === undefined) return { problem: 'malformed-chain' };
  const typed = isUri(iss) && isUri(sub) && typeof aud === 'string' && AGENT_ID.test(aud)
    && typeof scope === 'string' && scope.length <= 4096 && SCOPE.test(scope)
    && Array.isArray(effect) && effect.length > 0 && new Set(effect).size === effect.length && effect.every((e) => EFFECT_CLASSES.includes(e))
    && Array.isArray(grant) && grant.length === 1 && typeof grant[0] === 'string' && grant[0].length >= 1 && grant[0].length <= 256
    && (spend === undefined || spendShaped(spend)) && (project === undefined || isUri(project))
    && (task === undefined || (typeof task === 'string' && OPAQUE_ID.test(task)))
    && isTime(iat) && isTime(exp) && (nbf === undefined || isTime(nbf)) && typeof jti === 'string' && JTI.test(jti);
  return typed ? { claims: payload, depth } : { problem: 'malformed-claims' };
}

function approvalShape(payload) {
  const { iss, actionDigest: digest, aud, approver, method, iat, exp, jti } = payload;
  if (!isNonEmptyString(iss) || !isNonEmptyString(digest) || !isNonEmptyString(aud) || !isNonEmptyString(approver) || !isNonEmptyString(jti) || !isTime(iat) || !isTime(exp)) return undefined;
  if (method !== 'prompt' && method !== 'operator-channel') return undefined; // DEC-0045: `device` is removed
  return payload;
}

/** ECMAScript's time range in seconds (±8.64e15 ms): a NumericDate outside it is no instant a Date can hold. */
const MAX_CLOCK_SECONDS = 8.64e12;
/** A clock the time rows can compare (DEC-0060): a finite number of seconds within a Date's range. NaN or a string would pass every row. */
const readableClock = (now) => typeof now === 'number' && Number.isFinite(now) && Math.abs(now) <= MAX_CLOCK_SECONDS;

/**
 * DL-14 row 4a (DEC-0055, DEC-0060), right after the signature: when the callee reads the estate record, the token's
 * `kid` and the published key must be certified by that revision. `estate` is a revision the caller verified
 * (fabric-estate.mjs verifyEstateRecord) and its machine applied, or a function returning it; only an absent `estate`
 * skips the rule (null is an unreadable source). `estateApplied` is the highest revision the machine applied,
 * `estateRevocations` the revocation delta's entries since (an array or a function). A source that throws is
 * unreadable, never a pass. `[kind, detail]` or null.
 */
function estateProblem({ estate, estateApplied, estateRevocations }, kid, x, now) {
  if (estate === undefined) return null;
  let record;
  let extra;
  try {
    record = typeof estate === 'function' ? estate() : estate;
    extra = typeof estateRevocations === 'function' ? estateRevocations() : estateRevocations;
  } catch {
    return ['issuer', 'estate-unreadable'];
  }
  const verdict = hubKeyCertified(record, kid, x, now, estateApplied, extra === undefined ? undefined : { extraRevocations: extra });
  // The clock was refused before row 1, so a verdict here is the token's or the trust source's.
  return verdict.certified ? null : [verdict.fault === 'token' ? 'token' : 'issuer', verdict.detail];
}

/**
 * DL-13, in its fixed order: nothing about a token is believed before its signature is. `now` is seconds since
 * the epoch; a clock that is not one is refused `unknown-state` `no-clock` before row 1. Answers {ok: true, claims,
 * principal, caller, chain, kid} or {ok: false, code, detail}.
 */
export function verifyDelegation(token, { audience, jwks, now, capability, effect, issuer, readOnly, estate, estateApplied, estateRevocations } = {}) {
  // Before row 1: every time row compares against the clock, and a comparison with NaN is always false.
  if (!readableClock(now)) return refuse('unknown-state', 'no-clock');
  if (!isNonEmptyString(issuer)) return refuse('issuer-unavailable', 'no-trusted-issuer');
  if (!hasKeys(jwks)) return refuse('issuer-unavailable', 'no-published-keys');
  const checked = authentic(token, jwks, DELEGATION_TYP);
  if ('problem' in checked) return refuse(checked.issuer ? 'issuer-unavailable' : 'unauthenticated', checked.problem);
  const uncertified = estateProblem({ estate, estateApplied, estateRevocations }, checked.kid, checked.x, now);
  if (uncertified) return refuse(uncertified[0] === 'issuer' ? 'issuer-unavailable' : 'unauthenticated', uncertified[1]);
  const shaped = delegationShape(checked.compact.payload);
  if ('problem' in shaped) return refuse('unauthenticated', shaped.problem);
  const { claims, depth } = shaped;
  if (claims.iss !== issuer) return refuse('unauthenticated', 'wrong-issuer');
  if (claims.exp <= claims.iat || claims.exp - claims.iat > MAX_DELEGATION_LIFETIME_SECONDS) return refuse('unauthenticated', 'lifetime-above-profile');
  if (claims.iat > now + LEEWAY_SECONDS) return refuse('unauthenticated', 'issued-in-future');
  const { nbf } = checked.compact.payload;
  if (nbf !== undefined && nbf > now + LEEWAY_SECONDS) return refuse('unauthenticated', 'not-yet-valid');
  if (now > claims.exp + LEEWAY_SECONDS) return refuse('token-expired', 'expired');
  if (claims.aud !== audience) return refuse('wrong-audience', 'audience-mismatch');
  if (depth > MAX_CHAIN_DEPTH) return refuse('chain-too-deep', `depth-${depth}`);
  if (!claims.scope.split(' ').includes(capability)) return refuse('scope-not-granted', 'capability-not-in-scope');
  if (readOnly && effect !== 'none') return refuse('effect-above-ceiling', 'read-only-door');
  if (!effectWithin(effect, claims.effect)) return refuse('effect-above-ceiling', `effect-${effect}`);
  return { ok: true, claims, principal: claims.sub, caller: claims.act.sub, chain: chainOf(claims.act), kid: checked.kid };
}

/** DL-18: approval-required carries the digest; any fault is approval-invalid; the jti is consumed last. */
export function verifyApproval(approval, { audience, jwks, now, actionDigest: expected, issuer, jtiStore, estate, estateApplied, estateRevocations } = {}) {
  if (approval === undefined || approval === null || approval === '') return refuse('approval-required', 'no-approval', { actionDigest: expected });
  if (!isObject(jtiStore) || typeof jtiStore.consume !== 'function') return refuse('unknown-state', 'no-jti-store');
  if (!readableClock(now)) return refuse('unknown-state', 'no-clock');
  if (!isNonEmptyString(issuer)) return refuse('issuer-unavailable', 'no-trusted-issuer');
  if (!hasKeys(jwks)) return refuse('issuer-unavailable', 'no-published-keys');
  const checked = authentic(approval, jwks, APPROVAL_TYP);
  if ('problem' in checked) return refuse(checked.issuer ? 'issuer-unavailable' : 'approval-invalid', checked.problem);
  const uncertified = estateProblem({ estate, estateApplied, estateRevocations }, checked.kid, checked.x, now);
  if (uncertified) return refuse(uncertified[0] === 'issuer' ? 'issuer-unavailable' : 'approval-invalid', uncertified[1]);
  const claims = approvalShape(checked.compact.payload);
  if (!claims) return refuse('approval-invalid', 'malformed-claims');
  if (claims.iss !== issuer) return refuse('approval-invalid', 'wrong-issuer');
  if (claims.exp <= claims.iat || claims.exp - claims.iat > MAX_APPROVAL_LIFETIME_SECONDS) return refuse('approval-invalid', 'lifetime-above-profile');
  if (claims.iat > now + LEEWAY_SECONDS) return refuse('approval-invalid', 'issued-in-future');
  if (now > claims.exp + LEEWAY_SECONDS) return refuse('approval-invalid', 'expired');
  if (claims.aud !== audience) return refuse('approval-invalid', 'audience-mismatch');
  if (claims.actionDigest !== expected) return refuse('approval-invalid', 'digest-mismatch', { actionDigest: expected });
  let fresh;
  try { fresh = jtiStore.consume(claims.jti, claims.exp, now); } catch { return refuse('unknown-state', 'jti-store-failed'); }
  if (!fresh) return refuse('approval-reused', 'jti-consumed');
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

/** A jti store that cannot tell whether an id was consumed; the verifier answers unknown-state. */
export class JtiStoreError extends Error {}

/**
 * Consumed approval ids in a 0600 JSON file, so a second use is refused across a restart (DL-18). A file that
 * cannot be read throws JtiStoreError: forgetting every consumed id would let each approval be replayed.
 */
export class FileJtiStore {
  constructor(file) { this.file = file; }

  consume(jti, expiresAt, now) {
    let read = {};
    try {
      read = JSON.parse(fs.readFileSync(this.file, 'utf8'));
    } catch (error) {
      if (error?.code !== 'ENOENT') throw new JtiStoreError(`the consumed-approval file cannot be read: ${error?.code ?? error?.name}`);
    }
    if (!isObject(read)) throw new JtiStoreError('the consumed-approval file is not a JSON object');
    const seen = new Map(Object.entries(read).filter(([, until]) => typeof until === 'number' && until + LEEWAY_SECONDS >= now));
    if (seen.has(jti)) return false;
    seen.set(jti, expiresAt);
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const temp = path.join(path.dirname(this.file), `.${path.basename(this.file)}.${crypto.randomBytes(4).toString('hex')}.tmp`);
    const fd = fs.openSync(temp, 'wx', 0o600);
    try { fs.writeSync(fd, JSON.stringify(Object.fromEntries(seen))); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
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
  if (entry === null || entry === undefined) return undefined;
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


/** The digest an approval binds: sha256: and the hex SHA-256 of the action's RFC 8785 form. */
export const actionDigest = (action) => `sha256:${crypto.createHash('sha256').update(jcs(action), 'utf8').digest('hex')}`;

const loopback = (host) => host === 'localhost' || (net.isIP(host.replace(/^\[|\]$/g, '')) !== 0 && (/^127\./.test(host) || host.replace(/^\[|\]$/g, '') === '::1'));

async function defaultFetch(source) {
  if (/^https?:\/\//.test(source)) {
    const response = await fetch(source, { headers: { Accept: 'application/json' }, redirect: 'error', signal: AbortSignal.timeout(5000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    if (Number(response.headers.get('content-length') ?? 0) > 65536) throw new Error('the key set is too large');
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
    Object.assign(this, { source, fetcher, clock, keys: null, readAt: -Infinity, triedAt: -Infinity, rereadAt: -Infinity, pending: null });
  }

  async read(now) {
    this.triedAt = now;
    try {
      const value = await this.fetcher(this.source);
      if (hasKeys(value)) { this.keys = value; this.readAt = now; }
    } catch { /* the age check below decides */ }
  }

  async get(kid) {
    const now = this.clock();
    const fresh = now - this.readAt < JWKS_MAX_AGE_SECONDS;
    const known = this.keys !== null && (kid === undefined || kid === null || this.keys.keys.some((k) => isObject(k) && k.kid === kid));
    if (!fresh) { if (now - this.triedAt >= JWKS_RETRY_SECONDS) await (this.pending ??= this.read(now).finally(() => { this.pending = null; })); }
    else if (!known && now - this.rereadAt >= JWKS_REREAD_SECONDS) { this.rereadAt = now; await (this.pending ??= this.read(now).finally(() => { this.pending = null; })); }
    return this.clock() - this.readAt < JWKS_MAX_AGE_SECONDS ? this.keys : null;
  }
}

const kidOf = (token) => { const parsed = parseCompact(token); return 'problem' in parsed || typeof parsed.header.kid !== 'string' ? null : parsed.header.kid; };

/**
 * A check for one tools/call: `await gate(tool, headers)` answers the accepted delegation or a DL-19 refusal.
 * `effects` maps each tool to its declared effect class; a tool with none is refused rather than guessed.
 */
export const TIERS = Object.freeze(['T0', 'T1', 'T2']);

/**
 * `await gate(tool, headers, tier = 'T2')`. DL-25, DL-26: T0 is a loopback caller under the owner's account that the
 * service's own local floor authenticated, T1 an enrolled machine of the same owner, T2 everything else (and any call
 * relayed from off the machine). A T0 or T1 caller is never required to present a token: with none, the call passes
 * with no delegation. A present token is verified at every tier. `issuer` (auth.delegation.issuer) is required.
 */
export function delegationGate({ audience, jwks, effects, issuer, readOnly = false, clock = () => Date.now() / 1000, estate, estateApplied, estateRevocations }) {
  if (!isNonEmptyString(issuer)) throw new Error('the gate needs the issuer it trusts (auth.delegation.issuer)');
  return async (tool, headers, tier = 'T2') => {
    const effect = effects?.[tool];
    if (!EFFECT_CLASSES.includes(effect)) return refuse('unknown-state', 'no-declared-effect');
    const carried = readDelegationToken(headers);
    if (!carried) {
      if (tier === 'T0' || tier === 'T1') return { ok: true, tier, principal: null, caller: null, chain: [], claims: null, kid: null };
      return refuse('unauthenticated', 'no-token');
    }
    const keys = jwks instanceof JwksCache ? await jwks.get(kidOf(carried.token)) : jwks;
    const verdict = verifyDelegation(carried.token, { audience, jwks: keys, now: clock(), capability: tool, effect, readOnly, issuer, estate, estateApplied, estateRevocations });
    if (verdict.ok) verdict.tier = TIERS.includes(tier) ? tier : 'T2';
    return verdict;
  };
}

/** DL-21 step 6 (DEC-0045): the refusal a callee answers after the meter denied a grant check, the meter's code unchanged. */
export function refusalFromDenial(denial) {
  const data = {
    ...(denial.window === undefined ? {} : { window: denial.window }),
    ...(denial.level === null || denial.level === undefined ? {} : { level: denial.level }),
    ...(denial.approvalRequest === undefined ? {} : { approvalRequest: denial.approvalRequest }),
  };
  const message = `the meter denied the spend: ${denial.reason ?? ''}`.slice(0, 500);
  return { error: { code: denial.code, message, ...(Object.keys(data).length > 0 ? { data } : {}) } };
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
