// `estate-record/1` (Fabric Agent Contract DEC-0055): the record's own rules, without a verifier; the twin of
// fabric_estate_rules.py. The contract's src/estate-record-rules.ts at the pin, held to the contract's own vectors
// (test/fixtures/contract/estate-vectors.json). Split from fabric-estate.mjs (0.52.0, decision D8) so each module stays
// under the kit's line ceiling; fabric-estate.mjs re-exports every public name here.
//
// - estateRecordRules(kind, value): FAC-SEM-072…076, with FAC-SEM-092, 110, 111, 114, 122, 134, 137 and FAC-SEM-147
//   (DEC-0127, DEC-0128: the organizations a record pins, their context issuers and the context hub keys of its machines);
// - estateRecordDigest, estateChallengeInput, estateChallenge: what a passkey signs;
// - parseContext: the personal context or an organization's `org:<orgId>` (DEC-0082);
// - credentialKey: whether a passkey's public key is usable (FAC-SEM-073 reads it; the assertion verifier uses it);
// - machineProfile, deltaAnchorOf, deviceKeyRef, grantContextFindings, placementGrantFindings.

import crypto from 'node:crypto';
import { jcs } from './fabric-jsvalue.mjs';
import { normalIdentifier } from './fabric-identifiers.mjs';
import { secretValue } from './fabric-secrets.mjs';
import { isObject, isString, objects as list, indexed, show, toNumber, keyOf } from './fabric-jsvalue.mjs'; // the core's (FAA-65)
import { sha256, isSmallOrderOrMalformed as smallOrder, isValidP256Key } from './fabric-crypto.mjs'; // the core's (FAA-65)
import { parseRfc3339Ms as estateTime } from './fabric-time.mjs'; // the core's (FAA-65)

export const ESTATE_RECORD_SCHEMA = 'estate-record/1';
export const ESTATE_CHALLENGE_TYPE = 'estate-revision/1';
export const MAX_VALIDITY_SECONDS = 30 * 24 * 60 * 60;
export const ASSERTION_ALGORITHMS = Object.freeze(['ES256', 'EdDSA']);

/** DEC-0082: the personal context, and an organization's context `org:<orgId>` (the contract's `context-route.ts`). */
export const PERSONAL_CONTEXT = 'personal';
export const ORG_CONTEXT_PREFIX = 'org:';
const ORG_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;
/** The context `value` names, or undefined: `personal` exactly, or `org:` and an organization id; compared as written. */
export function parseContext(value) {
  if (typeof value !== 'string') return undefined;
  if (value === PERSONAL_CONTEXT) return { kind: 'personal' };
  if (!value.startsWith(ORG_CONTEXT_PREFIX)) return undefined;
  const org = value.slice(ORG_CONTEXT_PREFIX.length);
  return ORG_ID.test(org) ? { kind: 'org', org } : undefined;
}
/** A placement's or a secret placement's context: its `context`, `personal` when absent (DEC-0082). */
export const contextOf = (entry) => (entry.context === undefined ? PERSONAL_CONTEXT : entry.context);
export const B64URL = /^[A-Za-z0-9_-]+$/;
const bytes = (text) => Buffer.from(text, 'base64url');
const canonical = (text) => Buffer.from(text, 'base64url').toString('base64url') === text;

// ---- a passkey's public key (src/webauthn.ts) ----

/** The credential's public key, validated before use: `{key}` or `{problem: "unusable-key" | "small-order-key"}`. */
export function credentialKey(publicKey, alg) {
  if (!ASSERTION_ALGORITHMS.includes(alg)) return { problem: 'unusable-key' };
  if (!isObject(publicKey) || publicKey.d !== undefined || !isString(publicKey.x) || !B64URL.test(publicKey.x) || !canonical(publicKey.x)) return { problem: 'unusable-key' };
  if (alg === 'ES256') {
    if (publicKey.kty !== 'EC' || publicKey.crv !== 'P-256' || !isString(publicKey.y) || !B64URL.test(publicKey.y) || !canonical(publicKey.y)) return { problem: 'unusable-key' };
    const x = bytes(publicKey.x);
    const y = bytes(publicKey.y);
    if (x.length !== 32 || y.length !== 32 || !isValidP256Key(Buffer.concat([Buffer.from([4]), x, y]))) return { problem: 'unusable-key' };
    return { key: crypto.createPublicKey({ key: { kty: 'EC', crv: 'P-256', x: publicKey.x, y: publicKey.y }, format: 'jwk' }) };
  }
  if (publicKey.kty !== 'OKP' || publicKey.crv !== 'Ed25519') return { problem: 'unusable-key' };
  const raw = bytes(publicKey.x);
  if (raw.length !== 32) return { problem: 'unusable-key' };
  // DEC-0045 (CT-29): a small-order key verifies forged signatures on Node 20 and 22; it is refused before any use.
  if (smallOrder(raw)) return { problem: 'small-order-key' };
  return { key: crypto.createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: publicKey.x }, format: 'jwk' }) };
}


// ---- the record ----

/** `sha256:` and the hex SHA-256 of the UTF-8 RFC 8785 form of the record without `digest` and `signature`. */
export function estateRecordDigest(record) {
  const { digest: _digest, signature: _signature, ...covered } = record;
  return `sha256:${sha256(Buffer.from(jcs(covered), 'utf8')).toString('hex')}`;
}

export const estateChallengeInput = (digest) => Buffer.from(jcs({ type: ESTATE_CHALLENGE_TYPE, digest }), 'utf8');
/** The WebAuthn challenge a signer passes to navigator.credentials.get(): SHA-256 of estateChallengeInput. */
export const estateChallenge = (digest) => sha256(estateChallengeInput(digest));

const LABEL = '[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?';
/** `sign.` and at least two more labels, lower case: a signing RP ID is never a bare `sign.<tld>` (DEC-0063). */
const SIGNING_RP = new RegExp(`^sign(?:\\.${LABEL}){2,}$`);

/**
 * Whether an RP ID is a dedicated signing RP (v4 §7, DEC-0063): first label `sign`, then the organization's or
 * PassionCode's domain, lower case. A credential under any other RP ID is a sign-in credential and never signs.
 */
export const isSigningRpId = (rpId) => isString(rpId) && rpId.length <= 253 && SIGNING_RP.test(rpId);

/** Whether a pinned origin may run a signing ceremony for `rpId`: https, no port, no path, the RP ID or a host under it. */
export function originWithin(origin, rpId) {
  const host = isString(origin) ? /^https:\/\/([a-z0-9.-]{1,253})$/.exec(origin)?.[1] : undefined;
  return host !== undefined && (host === rpId || host.endsWith(`.${rpId}`));
}

/** FAC-SEM-092 on one signing credential: a signing RP ID, and every pinned origin within it. */
export function signingCredential(credential, path, flag) {
  const value = isObject(credential) ? credential : {};
  if (!isSigningRpId(value.rpId)) {
    flag(`${path}/rpId`, 'a passkey signs only under a dedicated signing RP, sign.<domain>, never under the RP ID it signs in with');
    return;
  }
  (Array.isArray(value.origins) ? value.origins : []).forEach((origin, index) => {
    if (!originWithin(origin, value.rpId)) flag(`${path}/origins/${index}`, `a signing ceremony runs only on ${value.rpId} or a host under it, over https without a port`);
  });
}

export const revocationKey = (entry) => `${String(entry.kind)} ${String(entry.ref)}`;

/** Whether a placement in `context` under `kid` may use that key (DEC-0090): an unscoped key anywhere, a scoped one only in its contexts. */
export function scopeAdmits(record, kid, context) {
  const scopes = list(record.publisherScopes).filter((scope) => scope.kid === kid);
  return scopes.length === 0 || scopes.some((scope) => Array.isArray(scope.contexts) && scope.contexts.includes(context));
}

// ---- FAC-SEM-072…076 ----

const flagger = (findings, code) => (instancePath, message) => findings.push({ code, instancePath, message });

function revisionWhole(value, flag) {
  try {
    const digest = estateRecordDigest(value);
    if (digest !== value.digest) flag('/digest', `the digest is ${digest}: the record changed after it was drafted, or was hashed over another form than RFC 8785`);
  } catch {
    flag('/digest', 'the record has no RFC 8785 form, so it has no digest');
  }
  const issuedAt = estateTime(value.issuedAt);
  const validUntil = estateTime(value.validUntil);
  if (!Number.isFinite(issuedAt) || !Number.isFinite(validUntil)) {
    flag(Number.isFinite(issuedAt) ? '/validUntil' : '/issuedAt', 'issuedAt and validUntil are RFC 3339 date-times with an offset, on days that exist');
  } else if (validUntil <= issuedAt || validUntil - issuedAt > MAX_VALIDITY_SECONDS * 1000) {
    flag('/validUntil', 'an estate record is valid after it is issued and for at most 30 days');
  }
}

function revisionChain(value) {
  const findings = [];
  const flag = flagger(findings, 'FAC-SEM-072');
  const parent = isObject(value.parent) ? value.parent : {};
  const next = isObject(value.next) ? value.next : {};
  if (next.estate !== parent.estate) flag('/next/estate', "a revision continues its parent's estate");
  if (next.revision !== toNumber(parent.revision) + 1) flag('/next/revision', `the revision after ${show(parent.revision)} is ${toNumber(parent.revision) + 1}: a revision never skips or repeats one`);
  let parentDigest;
  try {
    parentDigest = estateRecordDigest(parent);
  } catch {
    parentDigest = undefined;
  }
  if (next.parent !== parentDigest) flag('/next/parent', 'parent names the digest of the revision before it');
  if (estateTime(next.issuedAt) < estateTime(parent.issuedAt)) flag('/next/issuedAt', 'a revision is never issued before its parent');
  const kept = new Set(list(next.revocations).map(revocationKey));
  indexed(parent.revocations).forEach(([entry, index]) => {
    if (!kept.has(revocationKey(entry))) flag(`/parent/revocations/${index}`, `the ${show(entry.kind)} revocation of ${show(entry.ref)} is dropped: a revision keeps every revocation before it`);
  });
  return findings;
}

/** Standard base64 with its padding, the one form DEC-0053 records a device key's octets in. */
const BASE64 = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;
/** DEC-0084: a key reference, a device-key kid, `@sha256:` and 64 lower-case hex digits. */
export const KEY_REFERENCE = /^[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}#(sig|kem)@sha256:[a-f0-9]{64}$/;

/** A device key's fingerprint (DEC-0084): `sha256:` and the hex SHA-256 of its canonical base64 octets, or undefined. */
export function deviceKeyFingerprint(key) {
  const text = isObject(key) ? key.publicKey : undefined;
  if (!isString(text) || text.length === 0 || !BASE64.test(text)) return undefined;
  const raw = Buffer.from(text, 'base64');
  if (raw.toString('base64') !== text) return undefined;
  return `sha256:${sha256(raw).toString('hex')}`;
}

/** The `device-key` revocation reference of one key (DEC-0084): `<kid>@<fingerprint>`, or undefined. */
export function deviceKeyRef(key) {
  const fingerprint = deviceKeyFingerprint(key);
  const kid = isObject(key) ? key.kid : undefined;
  return fingerprint !== undefined && isString(kid) ? `${kid}@${fingerprint}` : undefined;
}

export const validDeviceKey = (key) => {
  const raw = Buffer.from(show(key.publicKey ?? ''), 'base64');
  return key.alg === 'ed25519' ? raw.length === 32 && !smallOrder(raw) : isValidP256Key(raw);
};

/**
 * FAC-SEM-073: every key is usable (DEC-0053) and named once. A context hub key (DEC-0128) is unique among every hub key
 * of the record, of full order, once per context on its machine, in a pinned context, and held only by a machine that
 * holds the personal hub key.
 */
function keys(value, flag) {
  const pinned = new Set(list(value.organizations).map((pin) => pin.org));
  const ids = new Set();
  const hubKids = new Set();
  const hubKeys = new Set();
  indexed(value.machines).forEach(([machine, m]) => {
    const at = `/machines/${m}`;
    if (ids.has(machine.id)) flag(`${at}/id`, `machine ${show(machine.id)} is listed twice`);
    ids.add(machine.id);
    const deviceKeys = list(machine.deviceKeys);
    if (deviceKeys.filter((key) => key.use === 'sig').length !== 1) flag(`${at}/deviceKeys`, 'a machine has exactly one signing device key, <id>#sig');
    if (deviceKeys.filter((key) => key.use === 'kem').length > 1) flag(`${at}/deviceKeys`, 'a machine has at most one key-agreement device key, <id>#kem');
    const seen = new Set();
    // The index is the key's position in the list as written, non-objects counted, as the contract and the Python twin name it.
    indexed(machine.deviceKeys).forEach(([key, k]) => {
      if (key.kid !== `${show(machine.id)}#${show(key.use)}`) flag(`${at}/deviceKeys/${k}/kid`, 'a device key is listed as <machine id>#sig or <machine id>#kem, by its role');
      // A key with no canonical fingerprint could be read as two keys by two readers, and no key reference names it (DEC-0084).
      if (deviceKeyFingerprint(key) === undefined) flag(`${at}/deviceKeys/${k}/publicKey`, "a device key's octets are written in canonical padded base64, the one form a key reference can name (DEC-0084)");
      else if (!validDeviceKey(key)) flag(`${at}/deviceKeys/${k}/publicKey`, 'an Ed25519 key is never of small order (DEC-0045) and a P-256 key is a valid point (SEC 1 §3.2.2)');
      if (seen.has(key.publicKey)) flag(`${at}/deviceKeys/${k}/publicKey`, 'one key is never used for the other role');
      seen.add(key.publicKey);
    });
    if (isObject(machine.hubKey)) {
      const hub = machine.hubKey;
      if (hubKids.has(hub.kid)) flag(`${at}/hubKey/kid`, `hub key ${show(hub.kid)} is certified for two machines: one kid per machine`);
      hubKids.add(hub.kid);
      if (hubKeys.has(hub.x)) flag(`${at}/hubKey/x`, 'one hub public key is certified for two machines under two kids: one key per machine');
      hubKeys.add(hub.x);
      if (smallOrder(Buffer.from(show(hub.x ?? ''), 'base64url'))) flag(`${at}/hubKey/x`, 'a hub key of small order verifies forged tokens and is never certified (DEC-0045)');
    }
    // DEC-0128: a context's hub key is as unique as the personal one, across every hub key of the record, and belongs to a
    // pinned organization, so a token in that context verifies only under its own context's key.
    const contexts = new Set();
    // A context's key lives with the personal hub key, so a hub move carries every context's key with it (DL-15).
    if (list(machine.contextHubKeys).length > 0 && !isObject(machine.hubKey)) flag(`${at}/contextHubKeys`, "a context's hub key is held only by the machine that holds the personal hub key (DEC-0128)");
    indexed(machine.contextHubKeys).forEach(([entry, c]) => {
      const keyAt = `${at}/contextHubKeys/${c}`;
      if (contexts.has(entry.context)) flag(`${keyAt}/context`, `context ${show(entry.context)} has two hub keys on one machine`);
      contexts.add(entry.context);
      if (!pinned.has(entry.context)) flag(`${keyAt}/context`, `context ${show(entry.context)} is not an organization the record pins (DEC-0127)`);
      // A key that is not an object is the schema's to refuse; nothing here reads it.
      if (!isObject(entry.key)) return;
      const key = entry.key;
      if (hubKids.has(key.kid)) flag(`${keyAt}/key/kid`, `hub key ${show(key.kid)} is certified twice: one kid per hub key, personal or per context`);
      hubKids.add(key.kid);
      if (hubKeys.has(key.x)) flag(`${keyAt}/key/x`, 'one public key is certified as two hub keys: a context key is its own key');
      hubKeys.add(key.x);
      if (smallOrder(Buffer.from(show(key.x ?? ''), 'base64url'))) flag(`${keyAt}/key/x`, 'a hub key of small order verifies forged tokens and is never certified (DEC-0045)');
    });
  });
  const credentials = new Set();
  indexed(value.authorities).forEach(([authority, index]) => {
    if (credentials.has(authority.credentialId)) flag(`/authorities/${index}/credentialId`, 'a passkey is listed once');
    credentials.add(authority.credentialId);
    if ('problem' in credentialKey(authority.publicKey, show(authority.alg))) flag(`/authorities/${index}/publicKey`, "a passkey's public key is a valid P-256 point for ES256 or an Ed25519 key of full order for EdDSA");
  });
}

function placements(value, flag) {
  const kids = new Set();
  indexed(value.publisherKeys).forEach(([key, index]) => {
    if (kids.has(key.kid)) flag(`/publisherKeys/${index}/kid`, `publisher key ${show(key.kid)} is pinned twice`);
    kids.add(key.kid);
  });
  indexed(value.machines).forEach(([machine, m]) => {
    const agents = new Set();
    indexed(machine.packages).forEach(([placement, p]) => {
      const at = `/machines/${m}/packages/${p}`;
      const key = keyOf(placement.agentRef, contextOf(placement));
      if (agents.has(key)) flag(`${at}/agentRef`, `${show(placement.agentRef)} is placed twice on one machine in the context ${show(contextOf(placement))}`);
      agents.add(key);
      if (!kids.has(placement.publisherKid)) flag(`${at}/publisherKid`, `publisher key ${show(placement.publisherKid)} is not in publisherKeys, so the machine pins no key to verify the package under`);
    });
  });
}

/**
 * FAC-SEM-122 on one record (DEC-0090): a partner's publisher key is scoped once, to a key the record pins, and a
 * placement under it is in one of the organization contexts its scope names, never `personal` or another.
 */
function partnerScopes(value, flag) {
  const pinned = new Set(list(value.publisherKeys).map((key) => key.kid));
  const scoped = new Set();
  indexed(value.publisherScopes).forEach(([scope, index]) => {
    if (scoped.has(scope.kid)) flag(`/publisherScopes/${index}/kid`, `publisher key ${show(scope.kid)} is scoped twice`);
    scoped.add(scope.kid);
    if (!pinned.has(scope.kid)) flag(`/publisherScopes/${index}/kid`, `publisher key ${show(scope.kid)} is not in publisherKeys, so the scope limits no key`);
  });
  indexed(value.machines).forEach(([machine, m]) => {
    indexed(machine.packages).forEach(([placement, p]) => {
      if (!scopeAdmits(value, placement.publisherKid, contextOf(placement))) {
        flag(`/machines/${m}/packages/${p}/publisherKid`, `publisher key ${show(placement.publisherKid)} is a partner's, trusted only in the contexts its scope names, not in ${show(contextOf(placement))}`);
      }
    });
  });
}

function secretReferences(value, flag) {
  const machineIds = new Set(list(value.machines).map((machine) => machine.id));
  indexed(value.machines).forEach(([machine, m]) => {
    const placed = new Set(list(machine.packages).map((placement) => keyOf(placement.agentRef, contextOf(placement))));
    const slots = new Set();
    indexed(machine.secrets).forEach(([secret, s]) => {
      const at = `/machines/${m}/secrets/${s}`;
      // The message never repeats the value, and no message of this rule repeats a secret placement's context.
      for (const field of ['slot', 'from', 'agentRef', 'context']) {
        const text = secret[field];
        if (isString(text) && secretValue(text)) flag(`${at}/${field}`, 'a secret placement names a slot, never a value: this looks like a credential');
      }
      if (!placed.has(keyOf(secret.agentRef, contextOf(secret)))) flag(`${at}/agentRef`, "a secret goes only where a placed package declares it (v4 Path 2): this agent is not placed on this machine in the secret's context");
      if (!machineIds.has(secret.from)) flag(`${at}/from`, 'the slot is filled from a machine of this estate');
      // An envelope names no context (DEC-0082), so an organization's instance fills its slot on its own machine.
      else if (contextOf(secret) !== PERSONAL_CONTEXT && secret.from !== machine.id) flag(`${at}/from`, "an organization's instance fills its slot from its own machine's vault, never by a secret envelope from another machine");
      const key = keyOf(secret.agentRef, secret.slot, contextOf(secret));
      if (slots.has(key)) flag(`${at}/slot`, `slot ${show(secret.slot)} is placed twice for one agent in one context on one machine`);
      slots.add(key);
    });
  });
}

function grantsAndRevocations(value, flag) {
  // A grant's id is a URI, so grants and their revocations are keyed by its normal form (DEC-0076).
  const grantKey = (id) => (typeof id === 'string' ? normalIdentifier(id) : id);
  const grantIds = new Set();
  indexed(value.shareGrants).forEach(([grant, index]) => {
    if (grant.principalKind !== 'external') flag(`/shareGrants/${index}/principalKind`, 'a share grant is to a principal outside the estate: principalKind external');
    const id = isObject(grant.meta) ? grant.meta.id : undefined;
    if (grantIds.has(grantKey(id))) flag(`/shareGrants/${index}/meta/id`, `grant ${show(id)} is listed twice`);
    grantIds.add(grantKey(id));
  });
  const machines = list(value.machines);
  // A Map, so a kind such as `constructor` or `__proto__` reads nothing from Object.prototype.
  const listed = new Map(Object.entries({
    authority: new Set(list(value.authorities).map((entry) => entry.credentialId)),
    machine: new Set(machines.map((machine) => machine.id)),
    // A kid, and each listed key's own reference (DEC-0084): revoking either while listing it is refused.
    'device-key': new Set(machines.flatMap((machine) => list(machine.deviceKeys).flatMap((key) => [key.kid, deviceKeyRef(key)].filter((ref) => ref !== undefined)))),
    // A context's hub key (DEC-0128) is listed as the personal one is; an entry whose key is no object lists undefined.
    'hub-key': new Set(machines.flatMap((machine) => [
      ...(isObject(machine.hubKey) ? [machine.hubKey.kid] : []),
      ...list(machine.contextHubKeys).map((entry) => (isObject(entry.key) ? entry.key.kid : undefined)),
    ])),
    'publisher-key': new Set(list(value.publisherKeys).map((key) => key.kid)),
    package: new Set(machines.flatMap((machine) => list(machine.packages).map((placement) => placement.digest))),
    grant: grantIds,
  }));
  const seen = new Set();
  indexed(value.revocations).forEach(([revocation, index]) => {
    const ref = revocation.kind === 'grant' ? grantKey(revocation.ref) : revocation.ref;
    const key = `${show(revocation.kind)} ${show(ref)}`;
    if (seen.has(key)) flag(`/revocations/${index}`, `the ${show(revocation.kind)} ${show(revocation.ref)} is revoked twice`);
    if (revocation.kind === 'device-key' && typeof revocation.ref === 'string' && revocation.ref.includes('@') && !KEY_REFERENCE.test(revocation.ref)) {
      flag(`/revocations/${index}/ref`, 'a device-key revocation names a kid or a key reference <kid>@sha256:<64 lower-case hex digits> (DEC-0084)');
    }
    seen.add(key);
    if (listed.get(show(revocation.kind))?.has(ref)) flag(`/revocations/${index}/ref`, `the record still lists the ${show(revocation.kind)} it revokes: revocation outranks addition`);
  });
}

/**
 * FAC-SEM-110 (DEC-0082): a grant to a principal outside the estate (`principalKind: external`) is used in that
 * principal's organization, so its `context` is never `personal`; absent means not stated.
 */
export function grantContextFindings(grant, at) {
  if (!isObject(grant) || grant.principalKind !== 'external' || grant.context !== PERSONAL_CONTEXT) return [];
  return [{ code: 'FAC-SEM-110', instancePath: `${at}/context`, message: "a grant to a principal outside the estate is used in that principal's organization, never in the personal context: name the organization's org:<orgId>, or leave context out" }];
}

/**
 * FAC-SEM-111 (DEC-0082) for one placement: an instance in an organization's context names, in `grant`, a share grant
 * of the same record (by the normal form of its id, DEC-0076) whose `context` is the placement's, as written, and that
 * the record does not revoke; a personal instance names none; a malformed context fails closed.
 */
function placementGrantProblems(record, placement) {
  const context = contextOf(placement);
  if (context === PERSONAL_CONTEXT) {
    return placement.grant === undefined ? [] : [['/grant', "a personal instance runs under no share grant: only a placement in an organization's context names one"]];
  }
  if (typeof placement.grant !== 'string') return [['/grant', `an instance placed in the context ${show(context)} names the share grant it runs under, by its id`]];
  const id = normalIdentifier(placement.grant);
  const grants = list(record.shareGrants).filter((grant) => isObject(grant.meta) && typeof grant.meta.id === 'string' && normalIdentifier(grant.meta.id) === id);
  const problems = [];
  if (grants.length === 0) problems.push(['/grant', `the record has no share grant ${placement.grant}`]);
  else if (parseContext(context)?.kind !== 'org') problems.push(['/context', `${show(context)} is not an organization's context id (org:<orgId>), so no share grant matches it`]);
  else if (!grants.some((grant) => grant.context === context)) problems.push(['/grant', `the share grant ${placement.grant} is not for the context ${show(context)}: its context must be the placement's, as written`]);
  if (list(record.revocations).some((entry) => entry.kind === 'grant' && typeof entry.ref === 'string' && normalIdentifier(entry.ref) === id)) problems.push(['/grant', `the record revokes the share grant ${placement.grant}, so no instance runs under it`]);
  return problems;
}

/** FAC-SEM-111 for one placement of `record`, as findings (`instancePath` relative to the placement); never throws (FAA-125). */
export function placementGrantFindings(record, placement) {
  const object = (value) => (isObject(value) ? value : {});
  return placementGrantProblems(object(record), object(placement)).map(([instancePath, message]) => ({ code: 'FAC-SEM-111', instancePath, message }));
}

function placementGrants(value, flag) {
  indexed(value.machines).forEach(([machine, m]) => {
    indexed(machine.packages).forEach(([placement, p]) => {
      for (const [suffix, message] of placementGrantProblems(value, placement)) flag(`/machines/${m}/packages/${p}${suffix}`, message);
    });
  });
}

/** DEC-0106: what a machine of the estate may be. Absent is `full`, and a writer omits `full`. */
export const MACHINE_PROFILES = Object.freeze(['full', 'member', 'view']);
const isProfile = (value) => typeof value === 'string' && MACHINE_PROFILES.includes(value);

/**
 * A machine's profile in a record (DEC-0106): `full` when the machine is listed once with no `profile`, its value when
 * that is one of the three, undefined otherwise (not listed, listed twice, an unreadable record or id, an unknown
 * value). The contract's machineProfile; it never throws.
 */
export function machineProfile(record, machineId) {
  if (!isObject(record) || !isString(machineId)) return undefined;
  const found = list(record.machines).filter((machine) => machine.id === machineId);
  if (found.length !== 1) return undefined;
  const { profile } = found[0];
  if (profile === undefined) return 'full';
  return isProfile(profile) ? profile : undefined;
}

/**
 * FAC-SEM-134 (DEC-0106): a profile, when present, is `full`, `member` or `view`; only a `full` machine carries a
 * `hubKey`; a `view` machine has no placement and no secret placement, and no secret placement names it as `from`.
 */
function machineProfiles(value, flag) {
  const views = new Set();
  indexed(value.machines).forEach(([machine, m]) => {
    if (machine.profile === undefined) return;
    if (!isProfile(machine.profile)) {
      flag(`/machines/${m}/profile`, `profile ${show(machine.profile)} is none of full, member, view`);
      return;
    }
    if (machine.profile !== 'full' && machine.hubKey !== undefined) flag(`/machines/${m}/hubKey`, `a ${machine.profile} machine is never the hub's: only a full machine carries a hub key`);
    if (machine.profile !== 'full' && list(machine.contextHubKeys).length > 0) flag(`/machines/${m}/contextHubKeys`, `a ${machine.profile} machine is never the hub's: only a full machine carries a context's hub key (DEC-0128)`);
    if (machine.profile === 'view') {
      views.add(machine.id);
      if (list(machine.packages).length > 0) flag(`/machines/${m}/packages`, 'a view machine runs no agent: it has no placement');
      if (list(machine.secrets).length > 0) flag(`/machines/${m}/secrets`, "a view machine holds none of the estate's secrets");
    }
  });
  indexed(value.machines).forEach(([machine, m]) => {
    indexed(machine.secrets).forEach(([secret, s]) => {
      if (views.has(secret.from)) flag(`/machines/${m}/secrets/${s}/from`, `machine ${show(secret.from)} is a view machine: it is the source of no secret`);
    });
  });
}

/**
 * FAC-SEM-147: the organizations the person admitted (DEC-0127 OM-2), each once by its context, and no root of small
 * order (DEC-0045), since the root's key sets are what every attestation of that organization verifies under; each
 * context issuer once and never containing the estate id (DEC-0128).
 */
function organizationPins(value, flag) {
  const seen = new Set();
  const issuers = new Set();
  for (const [pin, index] of indexed(value.organizations)) {
    const at = `/organizations/${index}`;
    const org = show(pin.org);
    if (seen.has(org)) flag(`${at}/org`, `organization ${org} is pinned twice`);
    seen.add(org);
    // DEC-0128: a context's issuer is its own and names no estate, so two organizations' tokens share nothing.
    if (typeof pin.iss === 'string') {
      if (issuers.has(pin.iss)) flag(`${at}/iss`, `context issuer ${show(pin.iss)} is used by two organizations`);
      issuers.add(pin.iss);
    }
    // Only the opaque part is the pin's own: the fixed prefix would match a short estate id by chance.
    const opaquePart = typeof pin.iss === 'string' ? pin.iss.replace(/^urn:fabric:context:/, '').toLowerCase() : '';
    // An estate id shorter than eight characters appears inside any random id by chance; the issuer's duty covers it.
    if (typeof value.estate === 'string' && value.estate.length >= 8 && opaquePart.includes(value.estate.toLowerCase())) {
      flag(`${at}/iss`, 'a context issuer never contains the estate id (DEC-0128)');
    }
    const x = isObject(pin.root) ? pin.root.x : undefined;
    if (typeof x === 'string' && /^[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$/.test(x) && smallOrder(Buffer.from(x, 'base64url'))) {
      flag(`${at}/root/x`, "a root of small order lets anyone forge the organization's key sets (DEC-0045)");
    }
  }
}

export function recordFindings(value) {
  const findings = [];
  revisionWhole(value, flagger(findings, 'FAC-SEM-072'));
  keys(value, flagger(findings, 'FAC-SEM-073'));
  placements(value, flagger(findings, 'FAC-SEM-074'));
  partnerScopes(value, flagger(findings, 'FAC-SEM-122'));
  secretReferences(value, flagger(findings, 'FAC-SEM-075'));
  grantsAndRevocations(value, flagger(findings, 'FAC-SEM-076'));
  indexed(value.shareGrants).forEach(([grant, index]) => findings.push(...grantContextFindings(grant, `/shareGrants/${index}`)));
  placementGrants(value, flagger(findings, 'FAC-SEM-111'));
  machineProfiles(value, flagger(findings, 'FAC-SEM-134'));
  organizationPins(value, flagger(findings, 'FAC-SEM-147'));
  // FAC-SEM-092 (DEC-0063) on each passkey the record lists.
  indexed(value.authorities).forEach(([authority, index]) => signingCredential(authority, `/authorities/${index}`, flagger(findings, 'FAC-SEM-092')));
  return findings;
}

function packageDigest(pkg) {
  const { digest: _digest, signatures: _signatures, ...covered } = pkg;
  return `sha256:${sha256(Buffer.from(jcs(covered), 'utf8')).toString('hex')}`;
}

function installation(value) {
  const findings = [];
  const record = isObject(value.record) ? value.record : {};
  const pkg = isObject(value.package) ? value.package : {};
  const [machine, machineIndex] = indexed(record.machines).find(([entry]) => entry.id === value.machine) ?? [undefined, -1];
  let digest;
  try {
    digest = packageDigest(pkg);
  } catch {
    digest = undefined;
  }
  const flag074 = flagger(findings, 'FAC-SEM-074');
  if (!machine) {
    flag074('/machine', `machine ${show(value.machine)} is not in the estate record`);
    return findings;
  }
  if (digest === undefined || digest !== pkg.digest) flag074('/package/digest', 'the package is not the one its digest names: it changed after it was packed');
  const context = contextOf(value);
  const [placement, placementIndex] = indexed(machine.packages).find(([entry]) => entry.agentRef === pkg.agentRef && contextOf(entry) === context) ?? [undefined, -1];
  if (!placement) flag074('/package/agentRef', `the record places no ${show(pkg.agentRef)} on machine ${show(value.machine)} in the context ${show(context)}`);
  else if (placement.digest !== digest) flag074('/package', `the record places ${show(placement.digest)} of this agent on this machine in this context, not this package`);
  const declared = new Set(list(pkg.secrets).map((slot) => slot.name));
  const flag075 = flagger(findings, 'FAC-SEM-075');
  indexed(machine.secrets).forEach(([secret, index]) => {
    if (secret.agentRef === pkg.agentRef && contextOf(secret) === context && !declared.has(secret.slot)) flag075(`/record/machines/${machineIndex}/secrets/${index}/slot`, `the package declares no slot ${show(secret.slot)}: a secret goes only where a placed package declares it`);
  });
  if (placement && !scopeAdmits(record, placement.publisherKid, context)) {
    flagger(findings, 'FAC-SEM-122')(`/record/machines/${machineIndex}/packages/${placementIndex}/publisherKid`, `publisher key ${show(placement.publisherKid)} is a partner's, not trusted in ${show(context)}`);
  }
  if (placement) {
    const flag111 = flagger(findings, 'FAC-SEM-111');
    for (const [suffix, message] of placementGrantProblems(record, placement)) flag111(`/record/machines/${machineIndex}/packages/${placementIndex}${suffix}`, message);
  }
  return findings;
}

/** The anchor a record vouches for (DEC-0107), or undefined when it names none or its shape is not the schema's. */
export function deltaAnchorOf(record) {
  if (!isObject(record) || !isObject(record.deltaAnchor)) return undefined;
  const { sequence, sha256 } = record.deltaAnchor;
  return Number.isSafeInteger(sequence) && sequence >= 1 && isString(sha256) && /^[a-f0-9]{64}$/.test(sha256) ? { sequence, sha256 } : undefined;
}

/**
 * FAC-SEM-137 across two revisions (DEC-0107): the delta anchor never moves back. A revision whose parent anchors the
 * delta anchors it too, at the parent's sequence or later, with the parent's hash at the same sequence.
 */
export function anchorFindings(parent, next) {
  const findings = [];
  const flag = flagger(findings, 'FAC-SEM-137');
  const before = deltaAnchorOf(parent);
  if (before === undefined) return findings;
  const after = deltaAnchorOf(next);
  if (after === undefined) flag('/next/deltaAnchor', `the parent anchors the delta at ${before.sequence}: a revision keeps an anchor once one is set`);
  else if (after.sequence < before.sequence) flag('/next/deltaAnchor/sequence', `the anchor moves back from ${before.sequence} to ${after.sequence}`);
  else if (after.sequence === before.sequence && after.sha256 !== before.sha256) flag('/next/deltaAnchor/sha256', `another hash at sequence ${after.sequence}: two delta histories`);
  return findings;
}

/**
 * FAC-SEM-114 across two revisions (DEC-0084): what a revision drops, it revokes in the same revision. A removed machine
 * as `machine <id>` and its hub key as `hub-key <kid>`; a replaced or dropped device key of a kept machine as `device-key`
 * by its reference or its kid; a hub key no longer certified as it was as `hub-key <old kid>`.
 */
/** A machine's context hub keys that are objects, with their indexes, each with the context it is certified for. */
const contextKeys = (machine) => indexed(machine.contextHubKeys).filter(([entry]) => isObject(entry.key)).map(([entry, c]) => [entry.key, c, entry.context]);

export function droppedFindings(parent, next) {
  const findings = [];
  const flag = flagger(findings, 'FAC-SEM-114');
  const revoked = (kind, ...refs) => list(next.revocations).some((entry) => entry.kind === kind && refs.some((ref) => ref !== undefined && entry.ref === ref));
  const nextMachines = new Map();
  for (const machine of list(next.machines)) if (!nextMachines.has(machine.id)) nextMachines.set(machine.id, machine);
  indexed(parent.machines).forEach(([machine, m]) => {
    const at = `/parent/machines/${m}`;
    const hub = isObject(machine.hubKey) ? machine.hubKey : undefined;
    const kept = nextMachines.get(machine.id);
    if (!kept) {
      if (!revoked('machine', machine.id)) flag(`${at}/id`, `machine ${show(machine.id)} is removed without its revocation: a revision that drops a machine lists machine ${show(machine.id)} in revocations`);
      if (hub && !revoked('hub-key', hub.kid)) flag(`${at}/hubKey/kid`, `the hub key ${show(hub.kid)} of a removed machine is revoked in the same revision`);
      contextKeys(machine).forEach(([key, c]) => {
        if (!revoked('hub-key', key.kid)) flag(`${at}/contextHubKeys/${c}/key/kid`, `the context hub key ${show(key.kid)} of a removed machine is revoked in the same revision (DEC-0128)`);
      });
      return;
    }
    const listedRefs = new Set(list(kept.deviceKeys).map(deviceKeyRef).filter((ref) => ref !== undefined));
    indexed(machine.deviceKeys).forEach(([key, k]) => {
      const ref = deviceKeyRef(key);
      if (ref === undefined || listedRefs.has(ref)) return;
      if (!revoked('device-key', ref, key.kid)) flag(`${at}/deviceKeys/${k}`, `the device key ${show(key.kid)} is replaced or dropped without its revocation: the same revision lists device-key ${ref}`);
    });
    const nextHub = isObject(kept.hubKey) ? kept.hubKey : undefined;
    if (hub && !(nextHub && nextHub.kid === hub.kid && nextHub.x === hub.x) && !revoked('hub-key', hub.kid)) {
      flag(`${at}/hubKey/kid`, `the hub key ${show(hub.kid)} is no longer certified as it was: the same revision revokes hub-key ${show(hub.kid)}, and a re-certified hub key takes a new kid`);
    }
    // DEC-0128: a context's hub key dropped (its context unpinned, OM-5, or the key replaced) is revoked the same way.
    // A key is kept only in its own context: one moved to another organization is a key that organization must not inherit.
    const keptContext = new Set(contextKeys(kept).map(([key, , context]) => `${show(context)} ${show(key.kid)} ${show(key.x)}`));
    contextKeys(machine).forEach(([key, c, context]) => {
      if (!keptContext.has(`${show(context)} ${show(key.kid)} ${show(key.x)}`) && !revoked('hub-key', key.kid)) {
        flag(`${at}/contextHubKeys/${c}/key/kid`, `the context hub key ${show(key.kid)} is no longer certified as it was: the same revision revokes hub-key ${show(key.kid)} (DEC-0128)`);
      }
    });
  });
  return findings;
}

/** FAC-SEM-072…076 for an `estate-record`, an `estate-record-revision` `{parent, next}` or an `estate-placement`. */
export function estateRecordRules(kind, value) {
  const doc = isObject(value) ? value : {};
  if (kind === 'estate-record') return recordFindings(doc);
  if (kind === 'estate-record-revision') {
    const parent = isObject(doc.parent) ? doc.parent : {};
    const next = isObject(doc.next) ? doc.next : {};
    return [...revisionChain(doc), ...droppedFindings(parent, next), ...anchorFindings(parent, next)];
  }
  if (kind === 'estate-placement') return installation(doc);
  return undefined;
}
