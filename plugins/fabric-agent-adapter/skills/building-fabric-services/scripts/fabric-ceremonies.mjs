// The estate ceremonies' headless join (contract DEC-0084), the Node kit; the twin of fabric_ceremonies.py, answer for
// answer (test/fixtures/contract/ceremony-vectors.json). Node built-ins only.
// verifyEnrollToken (the hub's and the node's verifier of an enroll-token/1), enrollJoinInput (what the joining machine
// signs with its #sig key) and enrollTokenRules (FAC-SEM-113). A token gives the machine no trust: only a passkey-signed
// revision that lists it does. Read it from stdin or a 0600 file, never argv, a URL or a log. Every function answers and
// never throws on malformed input. Normative source: the contract's src/enroll-token.ts and src/signing-challenges.ts.
// #region ceremonies-kit-node, docs: plugins/fabric-agent-adapter/skills/building-fabric-services/references/estate-record.md#the-estate-ceremonies

import crypto from 'node:crypto';
import { jcs } from './fabric-delegation.mjs';
import { CLOCK_SKEW_SECONDS, estateTime, isSigningRpId, originWithin, verifyAssertion } from './fabric-estate.mjs';

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

const isObject = (value) => typeof value === 'object' && value !== null && !Array.isArray(value);
const isString = (value) => typeof value === 'string';
const matches = (pattern, value) => isString(value) && pattern.test(value);
const list = (value) => (Array.isArray(value) ? value.filter(isObject) : []);
const show = (value) => {
  if (typeof value === 'string') return value;
  try { return String(value); } catch { return JSON.stringify(value) ?? typeof value; }
};
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

/** The reference verifier of an enroll-token/1 under trust {record, genesis, at: Date}; the first failure answers. */
export function verifyEnrollToken(token, trust) {
  const at = isObject(trust) && trust.at instanceof Date ? trust.at.getTime() : Number.NaN;
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
// #endregion ceremonies-kit-node
