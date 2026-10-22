// The estate ceremonies' headless join (contract DEC-0084), the Node kit; the twin of fabric_ceremonies.py, answer for
// answer (test/fixtures/contract/ceremony-vectors.json). Node built-ins only.
// verifyEnrollToken (the hub's and the node's verifier of an enroll-token/1), enrollJoinInput (what the joining machine
// signs with its #sig key) and enrollTokenRules (FAC-SEM-113). A token gives the machine no trust: only a passkey-signed
// revision that lists it does. Read it from stdin or a 0600 file, never argv, a URL or a log. Every function answers and
// never throws on malformed input. Normative source: the contract's src/enroll-token.ts and src/signing-challenges.ts.
// #region ceremonies-kit-node, docs: plugins/fabric-agent-adapter/skills/building-fabric-services/references/estate-record.md#the-estate-ceremonies

import crypto from 'node:crypto';
import { jcs } from './fabric-delegation.mjs';
import { CLOCK_SKEW_SECONDS, deviceKeyFingerprint, deviceKeyRef, estateTime, isSigningRpId, isValidP256Key, originWithin, validDeviceKey, verifyAssertion } from './fabric-estate.mjs';

export const ENROLL_TOKEN_SCHEMA = 'enroll-token/1';
export const ENROLL_TOKEN_TYPE = 'enroll-token/1';
export const ENROLL_JOIN_TYPE = 'enroll-join/1';
export const ENROLL_PURPOSE = 'agent-host';
export const MAX_ENROLL_TOKEN_SECONDS = 900;
export const ENROLL_TOKEN_FIELDS = Object.freeze(['scope', 'genesis', 'purpose', 'ceiling', 'notBefore', 'expiresAt', 'nonce', 'uses']);
const SHA256 = /^sha256:[a-f0-9]{64}$/;
const ESTATE_SCOPE = /^estate:[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}$/;
const NONCE32 = /^[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$/;
const ASSERTION_MEMBERS = 'alg,authenticatorData,clientDataJSON,credentialId,format,sig';

import { isObject, isString, objects as list, show, jsonEqual } from './fabric-jsvalue.mjs'; // the core's (FAA-65)
import { clockMs as clockOf } from './fabric-time.mjs'; // the core's (FAA-65)
const matches = (pattern, value) => isString(value) && pattern.test(value);
const REGISTER = new Map([
  [ENROLL_TOKEN_TYPE, { fields: ENROLL_TOKEN_FIELDS, check: (f) => matches(ESTATE_SCOPE, f.scope) && matches(SHA256, f.genesis) && f.purpose === ENROLL_PURPOSE
    && (f.ceiling === null || matches(SHA256, f.ceiling)) && Number.isFinite(estateTime(f.notBefore)) && Number.isFinite(estateTime(f.expiresAt)) && matches(NONCE32, f.nonce) && f.uses === 1 }],
  [ENROLL_JOIN_TYPE, { fields: ['digest', 'nonce'], check: (f) => matches(SHA256, f.digest) && matches(NONCE32, f.nonce) }],
]);

/** The bytes of a registered statement (DEC-0063), for enroll-token/1 and enroll-join/1; undefined otherwise. */
export function signingStatement(type, fields) {
  const spec = REGISTER.get(type);
  if (!spec || !isObject(fields)) return undefined;
  const names = Object.keys(fields);
  if (names.length !== spec.fields.length || !spec.fields.every((name) => Object.hasOwn(fields, name)) || !spec.check(fields)) return undefined;
  try { return Buffer.from(jcs({ ...fields, type }), 'utf8'); } catch { return undefined; }
}

function statementFields(token) {
  if (!isObject(token) || token.schema !== ENROLL_TOKEN_SCHEMA || !isObject(token.statement) || token.statement.type !== ENROLL_TOKEN_TYPE) return undefined;
  // The token holds exactly the schema's members: nothing unsigned rides beside the statement (DEC-0084).
  if (Object.keys(token).sort().join() !== 'schema,signature,statement') return undefined;
  const { type: _type, ...fields } = token.statement;
  return signingStatement(ENROLL_TOKEN_TYPE, fields) ? fields : undefined;
}

/**
 * The reference verifier of an enroll-token/1 under trust {record, genesis, at}; `at` is a Date or epoch seconds, as
 * verifyEstateRecord and the Python twin take it. The first failure answers.
 */
export function verifyEnrollToken(token, trust) {
  const at = isObject(trust) ? clockOf(trust.at) : Number.NaN;
  if (!Number.isFinite(at)) return { ok: false, problem: 'no-clock' };
  const fields = statementFields(token);
  const record = trust.record;
  if (!fields || !isObject(record) || !isString(record.estate)) return { ok: false, problem: 'malformed' };
  const { signature } = token;
  if (!isObject(signature) || Object.keys(signature).sort().join() !== ASSERTION_MEMBERS || signature.format !== 'webauthn-assertion' || !isString(signature.credentialId)) return { ok: false, problem: 'malformed' };
  if (fields.scope !== `estate:${record.estate}` || fields.genesis !== trust.genesis) return { ok: false, problem: 'wrong-estate' };
  const authorities = list(record.authorities);
  if (authorities.length === 0) return { ok: false, problem: 'no-trusted-authority' };
  if (list(record.revocations).some((entry) => entry.kind === 'authority' && entry.ref === signature.credentialId)) return { ok: false, problem: 'revoked-authority' };
  const found = authorities.filter((entry) => entry.credentialId === signature.credentialId);
  if (found.length > 1) return { ok: false, problem: 'duplicate-authority' };
  const authority = found[0];
  if (!authority) return { ok: false, problem: 'unknown-authority' };
  const rpId = show(authority.rpId);
  if (!isSigningRpId(rpId)) return { ok: false, problem: 'wrong-rp' };
  const credential = {
    credentialId: signature.credentialId, alg: show(authority.alg), publicKey: isObject(authority.publicKey) ? authority.publicKey : {}, rpId,
    origins: Array.isArray(authority.origins) ? authority.origins.filter((origin) => isString(origin) && originWithin(origin, rpId)) : [],
  };
  const challenge = crypto.createHash('sha256').update(signingStatement(ENROLL_TOKEN_TYPE, fields)).digest();
  const assertion = verifyAssertion(signature, credential, challenge);
  if (!assertion.ok) return { ok: false, problem: assertion.problem };
  const notBefore = estateTime(fields.notBefore);
  const expiresAt = estateTime(fields.expiresAt);
  if (expiresAt <= notBefore || expiresAt - notBefore > MAX_ENROLL_TOKEN_SECONDS * 1000) return { ok: false, problem: 'too-long-lived' };
  if (at < notBefore - CLOCK_SKEW_SECONDS * 1000) return { ok: false, problem: 'not-yet-valid' };
  if (at > expiresAt) return { ok: false, problem: 'expired' };
  return { ok: true, nonce: fields.nonce, expiresAt: fields.expiresAt, signedBy: credential.credentialId };
}

/** The enroll-join/1 statement the joining machine signs with its #sig key; undefined without a register statement. */
export function enrollJoinInput(token) {
  const fields = statementFields(token);
  const statement = fields && signingStatement(ENROLL_TOKEN_TYPE, fields);
  if (!fields || !statement) return undefined;
  return signingStatement(ENROLL_JOIN_TYPE, { digest: `sha256:${crypto.createHash('sha256').update(statement).digest('hex')}`, nonce: fields.nonce })?.toString('utf8');
}

function tokenFindings(value) {
  const findings = [];
  const flag = (instancePath, message) => findings.push({ code: 'FAC-SEM-113', instancePath, message });
  const statement = isObject(value.statement) ? value.statement : undefined;
  if (!statement) {
    flag('/statement', 'an enroll token carries its signed statement');
    return findings;
  }
  if (statement.type !== ENROLL_TOKEN_TYPE) flag('/statement/type', "the statement's type is enroll-token/1, the register's (DEC-0063)");
  const extra = Object.keys(statement).filter((name) => name !== 'type' && !ENROLL_TOKEN_FIELDS.includes(name));
  const missing = ENROLL_TOKEN_FIELDS.filter((name) => !Object.hasOwn(statement, name));
  if (extra.length > 0 || missing.length > 0) flag('/statement', `the statement has exactly the register's fields: ${ENROLL_TOKEN_FIELDS.join(', ')}`);
  if (statement.purpose !== ENROLL_PURPOSE) flag('/statement/purpose', "an enroll token's purpose is agent-host");
  if (statement.uses !== 1) flag('/statement/uses', 'an enroll token is used once: uses is 1, and the hub binds its nonce on the first use');
  const notBefore = estateTime(statement.notBefore);
  const expiresAt = estateTime(statement.expiresAt);
  const { type: _type, ...rest } = statement;
  const named = extra.length === 0 && missing.length === 0 && statement.purpose === ENROLL_PURPOSE && statement.uses === 1 && Number.isFinite(notBefore) && Number.isFinite(expiresAt);
  if (named && !signingStatement(ENROLL_TOKEN_TYPE, rest)) flag('/statement', 'scope is estate:<id>, genesis a sha256: digest, nonce 32 bytes in base64url, and ceiling null or a digest');
  if (!Number.isFinite(notBefore) || !Number.isFinite(expiresAt)) {
    flag(Number.isFinite(notBefore) ? '/statement/expiresAt' : '/statement/notBefore', 'notBefore and expiresAt are RFC 3339 date-times with an offset, on days that exist');
  } else if (expiresAt <= notBefore || expiresAt - notBefore > MAX_ENROLL_TOKEN_SECONDS * 1000) {
    flag('/statement/expiresAt', 'an enroll token is valid after notBefore and for at most 15 minutes (900 s)');
  }
  return findings;
}

/** FAC-SEM-113 (kind enroll-token); undefined for another kind. */
export function enrollTokenRules(kind, value) {
  if (kind === 'enroll-token') return tokenFindings(isObject(value) ? value : {});
  return undefined;
}
// --- the hub's single use of a token (DEC-0084) ------------------------------------------------------------------------

const PROOF = /^[A-Za-z0-9_-]{85}[AQgw]$/;
const P256_HALF_N = 0x7fffffff800000007fffffffffffffffde737d56d38bcf4279dce5617e3192a8n;

function es256Raw(octets, message, raw) {
  if (octets.length !== 65 || octets[0] !== 4 || !isValidP256Key(octets) || raw.length !== 64) return false;
  if (BigInt(`0x${raw.subarray(32).toString('hex')}`) > P256_HALF_N) return false;
  const jwk = { kty: 'EC', crv: 'P-256', x: octets.subarray(1, 33).toString('base64url'), y: octets.subarray(33).toString('base64url') };
  try { return crypto.verify('sha256', Buffer.from(message, 'utf8'), { key: jwk, format: 'jwk', dsaEncoding: 'ieee-p1363' }, raw); } catch { return false; }
}

function proves(key, message, proof) {
  if (!isString(proof) || !PROOF.test(proof)) return false;
  const octets = Buffer.from(key.publicKey, 'base64');
  const signature = Buffer.from(proof, 'base64url');
  if (key.alg === 'es256') return es256Raw(octets, message, signature);
  try {
    const publicKey = crypto.createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: octets.toString('base64url') }, format: 'jwk' });
    return crypto.verify(null, Buffer.from(message, 'utf8'), publicKey, signature);
  } catch { return false; }
}

/** The hub's single use of a verified token; `ledger` is a Map from nonce to {state: redeemed, fingerprint} or {state: revoked}. */
export function redeemEnrollToken(token, machineKey, proof, ledger) {
  const input = enrollJoinInput(token);
  if (input === undefined || !(ledger instanceof Map)) return { ok: false, problem: 'malformed' };
  const { nonce } = statementFields(token);
  if (machineOfKeys([machineKey]) === undefined) return { ok: false, problem: 'bad-key' };
  if (!proves(machineKey, input, proof)) return { ok: false, problem: 'bad-proof' };
  const fingerprint = deviceKeyFingerprint(machineKey);
  const entry = ledger.get(nonce);
  if (isObject(entry) && entry.state === 'revoked') return { ok: false, problem: 'revoked' };
  if (entry !== undefined) return { ok: false, problem: 'reused', log: { nonce, presented: fingerprint, boundTo: isObject(entry) ? show(entry.fingerprint) : show(entry) } };
  return { ok: true, record: { nonce, state: 'redeemed', fingerprint } };
}

// --- the nearby pairing (DEC-0084) ---------------------------------------------------------------------------------------

export const PAIRING_SCHEMA = 'pairing-message/1';
export const COMMIT_TYPE = 'fabric-enroll-commit/1';
export const CODE_TYPE = 'fabric-enroll-code/1';
export const FINGERPRINT_TYPE = 'estate-fingerprint/1';
export const CODE_DIGITS = 6;
export const FINGERPRINT_GROUPS = 5;
export const FINGERPRINT_GROUP_DIGITS = 5;
export const RENDEZVOUS_SECONDS = 600;
const MACHINE_ID = /^[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}$/;
const KEY_MEMBERS = 'alg,kid,publicKey,use';
const ALGORITHMS = new Map([['sig', ['es256', 'ed25519']], ['kem', ['ecdh-p256']]]);
const sha = (text) => crypto.createHash('sha256').update(Buffer.from(text, 'utf8')).digest();
const uint40 = (digest, offset) => digest.readUIntBE(offset, 5);
const own = (value, key) => (isObject(value) && Object.hasOwn(value, key) ? value[key] : undefined);
const isRole = (value) => value === 'new' || value === 'trusted';

/** The machine a key list belongs to, or undefined (one sig key, at most one kem key, one machine id, valid keys). */
export function machineOfKeys(keys) {
  if (!Array.isArray(keys) || keys.length < 1 || keys.length > 2) return undefined;
  const ids = new Set(); const uses = new Set(); const octets = new Set();
  for (const key of keys) {
    if (!isObject(key) || Object.keys(key).sort().join() !== KEY_MEMBERS) return undefined;
    const { use, kid } = key;
    if (!isString(use) || !isString(kid) || !isString(key.alg) || !ALGORITHMS.get(use)?.includes(key.alg)) return undefined;
    const id = kid.endsWith(`#${use}`) ? kid.slice(0, -(use.length + 1)) : '';
    if (!MACHINE_ID.test(id) || uses.has(use) || deviceKeyFingerprint(key) === undefined || !validDeviceKey(key) || octets.has(key.publicKey)) return undefined;
    ids.add(id); uses.add(use); octets.add(key.publicKey);
  }
  const [id] = [...ids];
  return ids.size === 1 && uses.has('sig') ? id : undefined;
}

function sideProblem(side) {
  if (!isObject(side)) return 'malformed';
  const role = own(side, 'role');
  if (!isRole(role)) return 'bad-role';
  if (!matches(NONCE32, own(side, 'nonce'))) return 'bad-nonce';
  if (machineOfKeys(own(side, 'keys')) === undefined) return 'bad-keys';
  const genesis = own(side, 'genesis');
  if (role === 'trusted' ? !matches(SHA256, genesis) : Object.hasOwn(side, 'genesis')) return 'bad-genesis';
  return undefined;
}
const covered = (side) => (side.role === 'trusted' ? { keys: side.keys, nonce: side.nonce, genesis: side.genesis } : { keys: side.keys, nonce: side.nonce });

/** A side's commitment over {type, role, keys, nonce, genesis?}. */
export function pairingCommit(side) {
  const problem = sideProblem(side);
  if (problem) return { ok: false, problem };
  return { ok: true, commit: `sha256:${sha(jcs({ type: COMMIT_TYPE, role: side.role, ...covered(side) })).toString('hex')}` };
}

function message(value, step) {
  if (!isObject(value) || own(value, 'schema') !== PAIRING_SCHEMA || own(value, 'step') !== step) return undefined;
  const members = Object.keys(value).sort().join();
  if (step === 'commit') return members === 'commit,role,schema,step' && matches(SHA256, value.commit) ? value : undefined;
  return members === 'keys,nonce,role,schema,step' || members === 'genesis,keys,nonce,role,schema,step' ? value : undefined;
}

/** Check the other side's reveal against its commitment; answers the revealing machine's id. */
export function checkReveal(commit, reveal, expected) {
  const c = message(commit, 'commit');
  const r = message(reveal, 'reveal');
  if (!c || !r) return { ok: false, problem: 'malformed' };
  if (r.role !== c.role || (expected !== undefined && expected !== null && r.role !== expected)) return { ok: false, problem: 'role-mismatch' };
  const { schema: _schema, step: _step, ...side } = r;
  const made = pairingCommit(side);
  if (!made.ok) return made;
  if (made.commit !== c.commit) return { ok: false, problem: 'commit-mismatch' };
  return { ok: true, machine: machineOfKeys(r.keys) };
}

/** The six-digit code both screens show. */
export function comparisonCode(newReveal, trustedReveal) {
  const a = message(newReveal, 'reveal');
  const b = message(trustedReveal, 'reveal');
  if (!a || !b) return { ok: false, problem: 'malformed' };
  if (a.role !== 'new' || b.role !== 'trusted') return { ok: false, problem: isRole(a.role) && isRole(b.role) ? 'role-mismatch' : 'bad-role' };
  const problem = sideProblem(a) ?? sideProblem(b);
  if (problem) return { ok: false, problem };
  if (machineOfKeys(a.keys) === machineOfKeys(b.keys)) return { ok: false, problem: 'same-machine' };
  const value = uint40(sha(jcs({ type: CODE_TYPE, new: covered(a), trusted: covered(b) })), 0) % 10 ** CODE_DIGITS;
  return { ok: true, code: String(value).padStart(CODE_DIGITS, '0') };
}

/** The estate's fingerprint from revision 1's digest. */
export function estateFingerprint(digest) {
  if (!matches(SHA256, digest)) return { ok: false, problem: 'malformed' };
  const f = sha(jcs({ type: FINGERPRINT_TYPE, digest }));
  return { ok: true, fingerprint: Array.from({ length: FINGERPRINT_GROUPS }, (_, i) => String(uint40(f, 5 * i) % 10 ** FINGERPRINT_GROUP_DIGITS).padStart(FINGERPRINT_GROUP_DIGITS, '0')).join(' ') };
}

/** The comparison code only after each reveal opened its own commitment. */
export function checkedComparisonCode(newCommit, newReveal, trustedCommit, trustedReveal) {
  const a = checkReveal(newCommit, newReveal, 'new');
  if (!a.ok) return a;
  const b = checkReveal(trustedCommit, trustedReveal, 'trusted');
  if (!b.ok) return b;
  return comparisonCode(newReveal, trustedReveal);
}

/** A one-time rendezvous after its messages at `at` (a Date): open, complete, or burned with its reason and index. */
export function rendezvousVerdict(openedAt, messages, at) {
  const opened = estateTime(openedAt);
  const now = at instanceof Date ? at.getTime() : Number.NaN;
  if (!Number.isFinite(opened) || !Number.isFinite(now) || !Array.isArray(messages)) return { state: 'burned', reason: 'malformed', index: -1 };
  if (now > opened + RENDEZVOUS_SECONDS * 1000 || now < opened - CLOCK_SKEW_SECONDS * 1000) return { state: 'burned', reason: 'expired', index: -1 };
  const commits = new Map();
  const revealed = new Set();
  for (const [index, item] of messages.entries()) {
    const burn = (reason) => ({ state: 'burned', reason, index });
    if (isObject(item) && own(item, 'schema') === PAIRING_SCHEMA && own(item, 'step') === 'abort' && Object.keys(item).sort().join() === 'role,schema,step' && isRole(item.role)) return burn('aborted');
    if (revealed.size === 2) return burn('closed');
    const commit = message(item, 'commit');
    const reveal = message(item, 'reveal');
    const role = (commit ?? reveal)?.role;
    if (!isRole(role)) return burn('malformed');
    if (commit) {
      if (commits.has(role)) return burn('repeated');
      commits.set(role, commit);
      continue;
    }
    if (revealed.has(role)) return burn('repeated');
    if (commits.size < 2) return burn('out-of-order');
    const checked = checkReveal(commits.get(role), reveal, role);
    if (!checked.ok) return burn(checked.problem === 'commit-mismatch' ? 'commit-mismatch' : 'malformed');
    revealed.add(role);
  }
  return revealed.size === 2 ? { state: 'complete' } : { state: 'open' };
}

const machineOf = (record, id) => (Array.isArray(record.machines) ? record.machines.find((machine) => isObject(machine) && machine.id === id) : undefined);
const machineRevoked = (record, id) => Array.isArray(record.revocations) && record.revocations.some((entry) => isObject(entry) && entry.kind === 'machine' && entry.ref === id);
const sameKeys = (a, b) => a.length === b.length && a.every((key) => b.some((other) => jsonEqual(key, other)));

/** What the new machine checks before it pins and applies a revision that adds it. */
export function joinListed(record, newReveal, trustedReveal, genesis) {
  const a = message(newReveal, 'reveal');
  const b = message(trustedReveal, 'reveal');
  if (!isObject(record) || !a || !b || a.role !== 'new' || b.role !== 'trusted' || sideProblem(a) || sideProblem(b)) return { ok: false, problem: 'malformed' };
  if (b.genesis !== genesis) return { ok: false, problem: 'other-estate' };
  const newId = machineOfKeys(a.keys);
  const trustedId = machineOfKeys(b.keys);
  const machine = machineOf(record, newId);
  if (!machine || machineRevoked(record, newId)) return { ok: false, problem: 'not-listed' };
  if (!Array.isArray(machine.deviceKeys) || !sameKeys(machine.deviceKeys, a.keys)) return { ok: false, problem: 'other-keys' };
  const trusted = machineOf(record, trustedId);
  const sig = b.keys.find((key) => key.use === 'sig');
  if (!trusted || machineRevoked(record, trustedId) || !Array.isArray(trusted.deviceKeys) || !trusted.deviceKeys.some((key) => jsonEqual(key, sig))) return { ok: false, problem: 'trusted-not-listed' };
  return { ok: true };
}

/** What a node does with a verified revision when its own keys are in question. */
export function ownKeysDecision(record, machineId, held) {
  if (!isObject(record) || !isString(machineId) || !Array.isArray(held)) return { action: 'malformed' };
  const machine = machineOf(record, machineId);
  if (!machine || machineRevoked(record, machineId)) return { action: 'stop', reason: 'removed' };
  const listed = Array.isArray(machine.deviceKeys) ? machine.deviceKeys : [];
  if (listed.length === 0 || !listed.every((key) => held.some((mine) => jsonEqual(key, mine)))) return { action: 'stop', reason: 'keys-replaced' };
  const retire = held.filter((key) => !listed.some((other) => jsonEqual(key, other))).map(deviceKeyRef).filter(isString);
  return { action: 'apply', retire };
}
// #endregion ceremonies-kit-node
