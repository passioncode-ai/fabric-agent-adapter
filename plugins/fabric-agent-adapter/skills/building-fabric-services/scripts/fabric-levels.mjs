// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
// Authority levels (DEC-0162): an organization's owner, an administrator or an architect in its projects decides for the
// organization's agents as the operator does, proved by a signed org-membership/2 attestation the call's delegation token
// binds by `mem`. Part of the service kit (layer L2); the twin of fabric_levels.py.
//
// - verifyOrgMembership(value, trust): the contract's reference verifier of an org-membership/1 or /2 attestation
//   (DEC-0127 OM-4, DEC-0162 LV-1) under the organization's key set the service applied. `trust.now` is a Date or
//   milliseconds since the epoch; `trust.levels` true for a reader the issuer registered for /2.
// - levelStanding(input), levelShortOf(level, minLevel, inProject), levelContextsWellFormed(levels): as the contract's.
// - levelRules(kind, value): FAC-SEM-170 on a level decision (kind `decision`) or a level mandate (`mandate`).
// Node 20+, no dependency; never throws on JSON as JSON.parse gives it.

import crypto from 'node:crypto';
import { isSmallOrderKey, sha256 } from './fabric-crypto.mjs';
import { isObject, jcs, show } from './fabric-jsvalue.mjs';
import { parseRfc3339Ms } from './fabric-time.mjs';

export const ORG_MEMBERSHIP_TYPE = 'org-membership/1';
export const ORG_MEMBERSHIP_2_TYPE = 'org-membership/2';
export const ORG_KEY_SET_TYPE = 'org-key-set/1';
export const ORG_MEMBERSHIP_ALGORITHMS = Object.freeze(['EdDSA']);
export const MAX_ATTESTATION_SECONDS = 24 * 60 * 60;
export const REFRESH_SECONDS = 15 * 60;
export const CLOCK_SKEW_SECONDS = 60;
export const ORG_ROLES = Object.freeze(['owner', 'admin', 'member']);
/** The roles of org-membership/2, highest first: each covers the ones after it, an architect within its projects (LV-2). */
export const LEVEL_ROLES = Object.freeze(['owner', 'admin', 'architect', 'member']);
export const MAX_PROJECTS = 64;
export const MEMBERSHIP_STATUSES = Object.freeze(['active', 'ended']);
const MAX_EXTENSIONS = 16;
const MAX_KEYS = 32;
const MAX_REVOKED = 256;
const MAX_ADMINISTRATORS = 16;
/** The levels a service may declare an action needs (LV-7), in its authority extension's `actionLevels`. */
export const ACTION_LEVELS = Object.freeze(['operator', 'owner', 'admin', 'architect']);
/** The levels a decision or a mandate may name, highest first; `member` decides nothing by its level (LV-2). */
export const DECIDING_LEVELS = Object.freeze(['owner', 'admin', 'architect']);
const RANK = new Map([['owner', 3], ['admin', 2], ['architect', 1], ['member', 0]]);

export const ORG_MEMBERSHIP_FIELDS = Object.freeze(['issuer', 'org', 'audience', 'subject', 'role', 'external', 'status', 'revision', 'membershipEndsAt', 'issuedAt', 'notBefore', 'expiresAt', 'extensions', 'alg', 'kid']);
export const ORG_MEMBERSHIP_2_FIELDS = Object.freeze(['issuer', 'org', 'audience', 'subject', 'role', 'projects', 'external', 'status', 'revision', 'membershipEndsAt', 'issuedAt', 'notBefore', 'expiresAt', 'extensions', 'alg', 'kid']);
const ORG_KEY_SET_FIELDS = ['issuer', 'org', 'revision', 'issuedAt', 'keys', 'revoked', 'administrators', 'alg', 'kid'];
const AUTHORITY_FIELDS = ['credentialId', 'alg', 'publicKey', 'rpId', 'origins'];
const ASSERTION_ALGORITHMS = ['ES256', 'EdDSA'];

/** common.schema.json#/$defs/contextId (DEC-0082): `personal` or `org:` and an id. */
export const CALL_CONTEXT = /^(?:personal|org:[A-Za-z0-9][A-Za-z0-9_-]{0,127})$/;
const OPAQUE = /^[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}$/;
export const ORG = /^org:[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;
const ISSUER = /^https:\/\/(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const EXTENSION = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\/[a-z][a-z0-9._-]{0,63}$/;
const SIG = /^[A-Za-z0-9_-]{85}[AQgw]$/;
const X = /^[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$/;
const SHA256 = /^sha256:[a-f0-9]{64}$/;
const PROJECT = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const B64URL = /^[A-Za-z0-9_-]+$/;
const ORIGIN = /^https:\/\/[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$/;
/** At most three fraction digits: every port compares the same instants, at millisecond precision (DEC-0085). */
const MILLISECONDS = /:[0-9]{2}(?:\.[0-9]{1,3})?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})$/;

const isString = (value) => typeof value === 'string';
const matches = (pattern, value) => isString(value) && pattern.test(value);
const positive = (value) => Number.isSafeInteger(value) && value >= 1;
const time = (value) => (isString(value) && MILLISECONDS.test(value) ? parseRfc3339Ms(value) : Number.NaN);
const readable = (value) => Number.isFinite(time(value));
const exactly = (value, names) => Object.keys(value).length === names.length && names.every((name) => Object.hasOwn(value, name));
const issuerOk = (value) => isString(value) && value.length <= 261 && ISSUER.test(value);
const digestOf = (bytes) => `sha256:${sha256(bytes).toString('hex')}`;
const rawKey = (x) => Buffer.from(x, 'base64url');

function statement(type, fields, names) {
  if (!exactly(fields, names)) return undefined;
  try {
    return Buffer.from(jcs({ ...fields, type }), 'utf8');
  } catch {
    return undefined;
  }
}

/** The bytes the organization's key signs: the attestation without `sig`, as the signing register states it. */
export function orgMembershipSigningInput(attestation) {
  if (!isObject(attestation) || (attestation.type !== ORG_MEMBERSHIP_TYPE && attestation.type !== ORG_MEMBERSHIP_2_TYPE)) return undefined;
  const { type, sig: _sig, ...fields } = attestation;
  return statement(type, fields, type === ORG_MEMBERSHIP_2_TYPE ? ORG_MEMBERSHIP_2_FIELDS : ORG_MEMBERSHIP_FIELDS);
}

function extensionsOk(value) {
  if (!isObject(value)) return false;
  const entries = Object.entries(value);
  return entries.length <= MAX_EXTENSIONS && entries.every(([name, item]) =>
    name.length <= 320 && EXTENSION.test(name) && ((isString(item) && [...item].length <= 256) || typeof item === 'boolean' || Number.isSafeInteger(item)));
}

function projectsOk(role, projects) {
  if (!Array.isArray(projects) || projects.length > MAX_PROJECTS || !projects.every((project) => matches(PROJECT, project)) || new Set(projects).size !== projects.length) return false;
  return (role === 'architect') === (projects.length > 0);
}

/** Whether an attestation's members have the shapes the schema gives them, the algorithm's value aside. */
export function orgMembershipWellFormed(doc) {
  const levels = doc.type === ORG_MEMBERSHIP_2_TYPE;
  return exactly(doc, [...(levels ? ORG_MEMBERSHIP_2_FIELDS : ORG_MEMBERSHIP_FIELDS), 'type', 'sig'])
    && issuerOk(doc.issuer) && matches(ORG, doc.org) && matches(OPAQUE, doc.audience) && matches(OPAQUE, doc.subject)
    && (levels ? LEVEL_ROLES.includes(doc.role) && projectsOk(doc.role, doc.projects) : ORG_ROLES.includes(doc.role)) && typeof doc.external === 'boolean'
    && MEMBERSHIP_STATUSES.includes(doc.status) && positive(doc.revision)
    && (doc.membershipEndsAt === null || readable(doc.membershipEndsAt))
    && readable(doc.issuedAt) && readable(doc.notBefore) && readable(doc.expiresAt)
    && extensionsOk(doc.extensions) && isString(doc.alg) && matches(OPAQUE, doc.kid) && matches(SIG, doc.sig);
}

const jwkOk = (key) => isObject(key) && ((key.kty === 'EC' && exactly(key, ['kty', 'crv', 'x', 'y']) && key.crv === 'P-256' && matches(X, key.x) && matches(X, key.y))
  || (key.kty === 'OKP' && exactly(key, ['kty', 'crv', 'x']) && key.crv === 'Ed25519' && matches(X, key.x)));

/** One administrator credential in org-key-set/1's shape (DEC-0129). */
export function administratorOk(value) {
  return isObject(value) && exactly(value, AUTHORITY_FIELDS) && isString(value.credentialId) && value.credentialId.length <= 1366 && B64URL.test(value.credentialId)
    && ASSERTION_ALGORITHMS.includes(value.alg) && jwkOk(value.publicKey) && (value.alg === 'ES256') === (isObject(value.publicKey) && value.publicKey.kty === 'EC')
    && isString(value.rpId) && Array.isArray(value.origins) && value.origins.length >= 1 && value.origins.length <= 8
    && value.origins.every((origin) => isString(origin) && origin.length <= 256 && ORIGIN.test(origin)) && new Set(value.origins).size === value.origins.length;
}

function validAtIssue(set) {
  const issuedAt = time(set.issuedAt);
  return set.keys.some((key) => isObject(key) && time(key.notBefore) <= issuedAt && issuedAt < time(key.notAfter));
}

/** A key set's shapes and FAC-SEM-146's structure; algorithms, small-order keys and signing RP IDs aside. */
export function orgKeySetWellFormed(set) {
  if (!(isObject(set) && set.type === ORG_KEY_SET_TYPE && exactly(set, [...ORG_KEY_SET_FIELDS, 'type', 'sig']))) return false;
  const { keys, revoked, administrators } = set;
  if (!(issuerOk(set.issuer) && matches(ORG, set.org) && positive(set.revision) && readable(set.issuedAt)
    && Array.isArray(keys) && keys.length >= 1 && keys.length <= MAX_KEYS
    && Array.isArray(revoked) && revoked.length <= MAX_REVOKED && revoked.every((kid) => matches(OPAQUE, kid)) && new Set(revoked).size === revoked.length
    && Array.isArray(administrators) && administrators.length <= MAX_ADMINISTRATORS && administrators.every(administratorOk)
    && new Set(administrators.map((entry) => entry.credentialId)).size === administrators.length
    && isString(set.alg) && matches(OPAQUE, set.kid) && matches(SIG, set.sig))) return false;
  const kids = new Set();
  for (const key of keys) {
    if (!isObject(key) || !exactly(key, ['kid', 'alg', 'x', 'notBefore', 'notAfter']) || !matches(OPAQUE, key.kid) || !isString(key.alg) || !matches(X, key.x)) return false;
    if (kids.has(key.kid) || key.kid === set.kid || revoked.includes(key.kid)) return false;
    kids.add(key.kid);
    if (!(time(key.notBefore) < time(key.notAfter))) return false;
  }
  return validAtIssue(set);
}

export const heldMembershipOk = (held) => isObject(held) && matches(OPAQUE, held.subject) && positive(held.revision) && matches(SHA256, held.digest);

const trustClausesOk = (org, audience, keySet) =>
  matches(ORG, org) && matches(OPAQUE, audience) && orgKeySetWellFormed(keySet) && ORG_MEMBERSHIP_ALGORITHMS.includes(keySet.alg) && keySet.org === org;

function signatureVerifies(x, input, sig) {
  try {
    const key = crypto.createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x }, format: 'jwk' });
    return crypto.verify(null, input, key, Buffer.from(sig, 'base64url'));
  } catch {
    return false;
  }
}

const clockOf = (now) => (now instanceof Date ? now.getTime() : typeof now === 'number' && Number.isFinite(now) ? now : Number.NaN);

/** The contract's verifyOrgMembership (DEC-0127 OM-4, DEC-0162 LV-1), in its order; never throws. */
export function verifyOrgMembership(value, trust) {
  if (!isObject(trust)) return { ok: false, problem: 'context-invalid' };
  const now = clockOf(trust.now);
  if (!Number.isFinite(now)) return { ok: false, problem: 'no-clock' };
  if (!(trustClausesOk(trust.org, trust.audience, trust.keySet) && (trust.subject === undefined || matches(OPAQUE, trust.subject))
    && (trust.held === undefined || heldMembershipOk(trust.held)) && (trust.levels === undefined || typeof trust.levels === 'boolean'))) {
    return { ok: false, problem: 'context-invalid' };
  }
  const known = isObject(value) && (value.type === ORG_MEMBERSHIP_TYPE || (trust.levels === true && value.type === ORG_MEMBERSHIP_2_TYPE));
  const input = known && orgMembershipWellFormed(value) ? orgMembershipSigningInput(value) : undefined;
  if (!input) return { ok: false, problem: 'malformed' };
  const { keySet } = trust;
  if (value.issuer !== keySet.issuer) return { ok: false, problem: 'wrong-issuer' };
  if (!ORG_MEMBERSHIP_ALGORITHMS.includes(value.alg)) return { ok: false, problem: 'unknown-algorithm' };
  const key = keySet.keys.find((entry) => entry.kid === value.kid);
  if (!key) return { ok: false, problem: keySet.revoked.includes(value.kid) ? 'key-revoked' : 'unknown-key' };
  if (key.alg !== value.alg) return { ok: false, problem: 'unusable-key' };
  if (isSmallOrderKey(rawKey(key.x))) return { ok: false, problem: 'small-order-key' };
  const issuedAt = time(value.issuedAt);
  if (issuedAt < time(key.notBefore) || issuedAt >= time(key.notAfter)) return { ok: false, problem: 'key-not-valid' };
  if (!signatureVerifies(key.x, input, value.sig)) return { ok: false, problem: 'bad-signature' };
  if (value.org !== trust.org) return { ok: false, problem: 'wrong-org' };
  if (value.audience !== trust.audience) return { ok: false, problem: 'wrong-audience' };
  if (trust.subject !== undefined && value.subject !== trust.subject) return { ok: false, problem: 'wrong-subject' };
  const notBefore = time(value.notBefore);
  const expiresAt = time(value.expiresAt);
  if (issuedAt > notBefore || notBefore >= expiresAt || expiresAt - issuedAt > MAX_ATTESTATION_SECONDS * 1000) return { ok: false, problem: 'too-long-lived' };
  if (now < notBefore - CLOCK_SKEW_SECONDS * 1000) return { ok: false, problem: 'not-yet-valid' };
  if (now >= expiresAt) return { ok: false, problem: 'expired' };
  const digest = digestOf(input);
  const { held } = trust;
  let unchanged = false;
  if (held && held.subject === value.subject) {
    if (value.revision < held.revision) return { ok: false, problem: 'stale-revision' };
    if (value.revision === held.revision && digest !== held.digest) return { ok: false, problem: 'revision-conflict' };
    unchanged = value.revision === held.revision;
  }
  const endsAt = value.membershipEndsAt === null ? Number.POSITIVE_INFINITY : time(value.membershipEndsAt);
  return {
    ok: true,
    status: value.status === 'ended' || now >= endsAt ? 'ended' : 'active',
    role: value.role,
    ...(value.type === ORG_MEMBERSHIP_2_TYPE ? { type: ORG_MEMBERSHIP_2_TYPE, projects: [...value.projects], expiresAt: value.expiresAt } : {}),
    refreshDue: now >= expiresAt - REFRESH_SECONDS * 1000,
    unchanged,
    digest,
    held: { subject: value.subject, revision: value.revision, digest },
  };
}

/** One entry of a service's level contexts: an opaque audience, a well-formed EdDSA key set of that organization,
 * attestations held by subject. */
export function levelContextOk(org, entry) {
  if (!isObject(entry) || !trustClausesOk(org, entry.audience, entry.keySet)) return false;
  if (!entry.keySet.keys.every((key) => ORG_MEMBERSHIP_ALGORITHMS.includes(key.alg))) return false;
  return entry.held === undefined || (isObject(entry.held) && Object.entries(entry.held).every(([subject, held]) => heldMembershipOk(held) && held.subject === subject));
}

/** Whether a service's level contexts are its own well-formed configuration: a map keyed by `org:<orgId>`. */
export const levelContextsWellFormed = (levels) => isObject(levels) && Object.entries(levels).every(([org, entry]) => levelContextOk(org, entry));

const strictest = (minLevel) => minLevel === 'operator' || (minLevel !== undefined && !ACTION_LEVELS.includes(minLevel));

/** The detail a level gets for an action its service declares `minLevel` (LV-7, LV-10), or undefined when it covers it. */
export function levelShortOf(level, minLevel, inProject) {
  if (strictest(minLevel)) return 'level-insufficient: operator';
  const rank = RANK.get(level) ?? 0;
  if (minLevel === 'owner' && rank < RANK.get('owner')) return 'level-insufficient: owner';
  if ((minLevel === 'admin' || !inProject) && rank < RANK.get('admin')) return 'level-insufficient: admin';
  return undefined;
}

/**
 * Whether a level stands for one call (DEC-0162 LV-4, LV-5, LV-7, LV-11), as the contract's levelStanding answers:
 * {ok: true, level, org, approver, membershipDigest, revision, projects}, {ok: false, invalid} or {ok: false,
 * insufficient}. `now` is milliseconds since the epoch.
 */
export function levelStanding({ membership, org, level, at, project, context, contexts, tokenMem, minLevel, now }) {
  if (context !== org) return { ok: false, invalid: 'level-membership: context-invalid' };
  const entry = isObject(contexts) && Object.hasOwn(contexts, org) ? contexts[org] : undefined;
  const subject = isObject(membership) && typeof membership.subject === 'string' ? membership.subject : undefined;
  const heldBySubject = isObject(entry) && isObject(entry.held) && subject !== undefined && Object.hasOwn(entry.held, subject) ? entry.held[subject] : undefined;
  const verdict = verifyOrgMembership(membership, {
    now, org, audience: isObject(entry) ? entry.audience : '', keySet: isObject(entry) ? entry.keySet : {},
    ...(heldBySubject !== undefined ? { held: heldBySubject } : {}), levels: true,
  });
  if (!verdict.ok) {
    if (verdict.problem === 'wrong-audience') return { ok: false, invalid: 'level-audience' };
    if (verdict.problem === 'expired') return { ok: false, invalid: 'level-expired' };
    return { ok: false, invalid: `level-membership: ${verdict.problem}` };
  }
  if (verdict.type !== ORG_MEMBERSHIP_2_TYPE) return { ok: false, invalid: 'level-membership: malformed' };
  if (verdict.status !== 'active') return { ok: false, invalid: 'level-membership: ended' };
  if (tokenMem !== verdict.digest) return { ok: false, invalid: 'level-unbound' };
  if (!(parseRfc3339Ms(at) < parseRfc3339Ms(verdict.expiresAt))) return { ok: false, invalid: 'level-expired' };
  const rank = DECIDING_LEVELS.includes(level) ? RANK.get(level) : Number.POSITIVE_INFINITY;
  if (rank > RANK.get(verdict.role)) return { ok: false, invalid: 'level-role' };
  const { projects } = verdict;
  if (strictest(minLevel)) return { ok: false, insufficient: 'level-insufficient: operator' };
  if (minLevel === 'owner' && rank < RANK.get('owner')) return { ok: false, insufficient: 'level-insufficient: owner' };
  if ((minLevel === 'admin' || project === undefined) && rank < RANK.get('admin')) return { ok: false, insufficient: 'level-insufficient: admin' };
  if (verdict.role === 'architect' && project !== undefined && !projects.includes(project)) return { ok: false, insufficient: 'level-insufficient: admin' };
  return { ok: true, level, org, approver: verdict.held.subject, membershipDigest: verdict.digest, revision: verdict.held.revision, projects };
}

function levelDocument(value, projects, at, flag) {
  const { membership } = value;
  if (!isObject(membership) || membership.type !== ORG_MEMBERSHIP_2_TYPE) {
    flag('/membership', "a level decision carries the holder's org-membership/2 attestation");
    return;
  }
  if (membership.org !== value.org) flag('/org', `the level is in ${show(membership.org)}, the attestation's organization, not ${show(value.org)}`);
  const level = RANK.get(value.level) ?? 4;
  const role = RANK.get(membership.role) ?? -1;
  if (level > role) flag('/level', `the attestation's role ${show(membership.role)} does not cover the level ${show(value.level)}`);
  if (!(parseRfc3339Ms(at) < parseRfc3339Ms(membership.expiresAt))) flag('/at', "the holder decides before the attestation's expiresAt");
  if (value.level === 'architect' && membership.role === 'architect') {
    const own = Array.isArray(membership.projects) ? membership.projects : [];
    if (projects === undefined || projects.length === 0) flag('/level', 'an architect decides only in its projects: the decision names one, a mandate\'s scope lists them');
    else for (const project of projects) if (!own.includes(project)) flag('/membership/projects', `the project ${show(project)} is not among the architect's projects`);
  }
}

/** FAC-SEM-170 on kind `decision` (a level decision) and on kind `mandate` (a level mandate); undefined for any other kind. */
export function levelRules(kind, value) {
  if (kind !== 'decision' && kind !== 'mandate') return undefined;
  const findings = [];
  if (!isObject(value) || value.by !== 'level') return findings;
  const flag = (instancePath, message) => findings.push({ code: 'FAC-SEM-170', instancePath, message });
  if (kind === 'decision') levelDocument(value, value.project === undefined ? undefined : [value.project], value.at, flag);
  else {
    const scope = isObject(value.scope) ? value.scope : {};
    levelDocument(value, Array.isArray(scope.projects) ? scope.projects : undefined, value.at, flag);
  }
  return findings;
}
