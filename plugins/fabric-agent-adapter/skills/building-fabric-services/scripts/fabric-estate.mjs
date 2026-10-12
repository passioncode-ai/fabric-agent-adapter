// `estate-record/1` (Fabric Agent Contract DEC-0055): verify an estate revision and check its rules — the twin of
// fabric_estate.py. The contract's src/estate-record-rules.ts, src/webauthn.ts and src/p256.ts at the pin, held to the
// contract's own vectors (test/fixtures/contract/estate-vectors.json):
//
// - verifyEstateRecord(record, { at, parent } | { at, authorities }) — the verdict a machine applies a revision on, after
//   it has checked the revision against estate-record.schema.json (the verifier does not check the schema);
// - estateRecordRules(kind, value) — FAC-SEM-072…076;
// - hubKeyCertified(record, kid, x, at) — DL-14: a delegation verifier that reads the estate record trusts a token's
//   `kid` only while a current revision certifies it for a machine (fabric-delegation.mjs calls it).
//
// Node's own crypto: ES256 through createPublicKey (JWK) and verify (DER), EdDSA through Ed25519.

import crypto from 'node:crypto';
import { jcs } from './fabric-delegation.mjs';
import { secretValue } from './fabric-secrets.mjs';

export const ESTATE_RECORD_SCHEMA = 'estate-record/1';
export const ESTATE_CHALLENGE_TYPE = 'estate-revision/1';
export const MAX_VALIDITY_SECONDS = 30 * 24 * 60 * 60;
/** How far ahead of the verifier's clock a signed `issuedAt` may be before it is `not-yet-valid` (DEC-0066). */
export const CLOCK_SKEW_SECONDS = 60;
export const ASSERTION_ALGORITHMS = Object.freeze(['ES256', 'EdDSA']);
export const FLAGS = Object.freeze({ UP: 0x01, UV: 0x04, BE: 0x08, BS: 0x10, AT: 0x40, ED: 0x80 });

const isObject = (value) => typeof value === 'object' && value !== null && !Array.isArray(value);
const isString = (value) => typeof value === 'string';
const list = (value) => (Array.isArray(value) ? value.filter(isObject) : []);
const sha256 = (bytes) => crypto.createHash('sha256').update(bytes).digest();
const B64URL = /^[A-Za-z0-9_-]+$/;
const bytes = (text) => Buffer.from(text, 'base64url');
const canonical = (text) => Buffer.from(text, 'base64url').toString('base64url') === text;

const SMALL_ORDER = new Set([
  '0000000000000000000000000000000000000000000000000000000000000000', '0100000000000000000000000000000000000000000000000000000000000000',
  '26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05', 'c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a',
  'ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f', 'edffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f',
  'eeffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f',
]);
/** The contract's isSmallOrderKey: a key that is not 32 bytes counts as one too. */
function smallOrder(raw) {
  if (raw.length !== 32) return true;
  const cleared = Buffer.from(raw);
  cleared[31] &= 0x7f;
  return SMALL_ORDER.has(cleared.toString('hex'));
}

// ---- P-256 (DEC-0053; SEC 1 v2 §3.2.2) ----

const P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffffn;
const B = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604bn;
const toBig = (part) => BigInt(`0x${Buffer.from(part).toString('hex')}`);

/** Whether `raw` is a valid uncompressed P-256 public key: 0x04 ‖ X ‖ Y, both below p, on the curve. */
export function isValidP256Key(raw) {
  if (raw.length !== 65 || raw[0] !== 0x04) return false;
  const x = toBig(raw.subarray(1, 33));
  const y = toBig(raw.subarray(33, 65));
  if (x >= P || y >= P) return false;
  const left = (y * y) % P;
  const right = (((x * x) % P) * x - 3n * x + B) % P;
  return left === ((right % P) + P) % P;
}

// ---- WebAuthn Level 3 §7.2, offline ----

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

/**
 * Verify a passkey assertion under a credential the caller pinned (`credentialId`, `alg`, `publicKey`, `rpId`,
 * `origins`) for the expected challenge bytes: `{ok: true, flags, signCount}` or `{ok: false, problem}`.
 */
export function verifyAssertion(assertion, credential, challenge) {
  if (!isObject(assertion)) return { ok: false, problem: 'malformed' };
  const { credentialId, alg, authenticatorData, clientDataJSON, sig } = assertion;
  for (const field of [credentialId, alg, authenticatorData, clientDataJSON, sig]) if (!isString(field)) return { ok: false, problem: 'malformed' };
  if (![credentialId, authenticatorData, clientDataJSON, sig].every((field) => B64URL.test(field))) return { ok: false, problem: 'malformed' };
  if (credentialId !== credential.credentialId) return { ok: false, problem: 'malformed' };
  if (!ASSERTION_ALGORITHMS.includes(alg)) return { ok: false, problem: 'unknown-algorithm' };
  if (alg !== credential.alg) return { ok: false, problem: 'key-algorithm-mismatch' };
  const found = credentialKey(credential.publicKey, alg);
  if ('problem' in found) return { ok: false, problem: found.problem };

  const cData = bytes(clientDataJSON);
  let client;
  try {
    client = JSON.parse(new TextDecoder('utf-8', { fatal: true, ignoreBOM: false }).decode(cData));
  } catch {
    return { ok: false, problem: 'malformed' };
  }
  if (!isObject(client)) return { ok: false, problem: 'malformed' };
  if (client.type !== 'webauthn.get') return { ok: false, problem: 'wrong-type' };
  if (client.challenge !== Buffer.from(challenge).toString('base64url')) return { ok: false, problem: 'wrong-challenge' };
  if (!isString(client.origin) || !credential.origins.includes(client.origin)) return { ok: false, problem: 'wrong-origin' };
  if (client.crossOrigin === true || client.topOrigin !== undefined) return { ok: false, problem: 'cross-origin' };

  const authData = bytes(authenticatorData);
  if (authData.length < 37) return { ok: false, problem: 'malformed' };
  if (!authData.subarray(0, 32).equals(sha256(Buffer.from(credential.rpId, 'utf8')))) return { ok: false, problem: 'wrong-rp' };
  const flags = authData[32];
  if ((flags & FLAGS.AT) !== 0 || ((flags & FLAGS.BS) !== 0 && (flags & FLAGS.BE) === 0)) return { ok: false, problem: 'bad-flags' };
  if ((flags & FLAGS.UP) === 0) return { ok: false, problem: 'no-user-presence' };
  if ((flags & FLAGS.UV) === 0) return { ok: false, problem: 'no-user-verification' };

  const signed = Buffer.concat([authData, sha256(cData)]);
  const signature = bytes(sig);
  let good;
  try {
    good = alg === 'ES256'
      ? crypto.verify('sha256', signed, { key: found.key, dsaEncoding: 'der' }, signature)
      : signature.length === 64 && crypto.verify(null, signed, found.key, signature);
  } catch {
    good = false;
  }
  if (!good) return { ok: false, problem: 'bad-signature' };
  return { ok: true, flags, signCount: authData.readUInt32BE(33) };
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

const RFC3339 = /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$/;
/** An RFC 3339 date-time as milliseconds, or NaN: `T`, an offset and a day that exists; a space and `:60` refused (ER-10). */
export function estateTime(value) {
  const match = isString(value) ? RFC3339.exec(value) : null;
  if (!match) return Number.NaN;
  const [year, month, day, hour, minute, second] = match.slice(1, 7).map(Number);
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  if (date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day || hour > 23 || minute > 59 || second > 59) return Number.NaN;
  return Date.parse(value);
}
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
function signingCredential(credential, path, flag) {
  const value = isObject(credential) ? credential : {};
  if (!isSigningRpId(value.rpId)) {
    flag(`${path}/rpId`, 'a passkey signs only under a dedicated signing RP, sign.<domain>, never under the RP ID it signs in with');
    return;
  }
  (Array.isArray(value.origins) ? value.origins : []).forEach((origin, index) => {
    if (!originWithin(origin, value.rpId)) flag(`${path}/origins/${index}`, `a signing ceremony runs only on ${value.rpId} or a host under it, over https without a port`);
  });
}

const revocationKey = (entry) => `${String(entry.kind)} ${String(entry.ref)}`;
const clockOf = (at) => (at instanceof Date ? at.getTime() : (typeof at === 'number' && Number.isFinite(at) ? at * 1000 : Number.NaN));

/**
 * The reference verifier, in the order of estate-record.md's ER table. `at` is the clock (a Date, or epoch seconds); pass
 * the verified `parent`, or for revision 1 the `authorities` the machine pinned at enrollment.
 */
export function verifyEstateRecord(record, trust) {
  const at = isObject(trust) ? clockOf(trust.at) : Number.NaN;
  if (!Number.isFinite(at)) return { ok: false, problem: 'no-clock' };
  if (!isObject(record) || !isString(record.digest) || !Number.isSafeInteger(record.revision) || !isObject(record.signature)) return { ok: false, problem: 'malformed' };
  const signature = record.signature;
  if (signature.format !== 'webauthn-assertion' || !isString(signature.credentialId)) return { ok: false, problem: 'malformed' };
  let digest;
  try {
    digest = estateRecordDigest(record);
  } catch {
    return { ok: false, problem: 'malformed' };
  }
  if (digest !== record.digest) return { ok: false, problem: 'digest-mismatch' };

  let trusted;
  let revoked = new Set();
  if (trust.parent !== undefined) {
    const parent = trust.parent;
    if (!isObject(parent)) return { ok: false, problem: 'broken-chain' };
    let parentDigest;
    try {
      parentDigest = estateRecordDigest(parent);
    } catch {
      return { ok: false, problem: 'broken-chain' };
    }
    if (parent.estate !== record.estate || record.revision !== Number(parent.revision) + 1 || record.parent !== parentDigest) return { ok: false, problem: 'broken-chain' };
    if (estateTime(record.issuedAt) < estateTime(parent.issuedAt)) return { ok: false, problem: 'broken-chain' };
    const kept = new Set(list(record.revocations).map(revocationKey));
    if (list(parent.revocations).some((entry) => !kept.has(revocationKey(entry)))) return { ok: false, problem: 'broken-chain' };
    // A passkey the parent revokes signs nothing after it; a revision may still revoke its own signer (rotation).
    revoked = new Set(list(parent.revocations).filter((entry) => entry.kind === 'authority').map((entry) => entry.ref));
    trusted = list(parent.authorities);
  } else {
    if (record.revision !== 1 || record.parent !== undefined) return { ok: false, problem: 'broken-chain' };
    trusted = Array.isArray(trust.authorities) ? trust.authorities : [];
  }
  if (trusted.length === 0) return { ok: false, problem: 'no-trusted-authority' };
  const matches = trusted.filter((entry) => isObject(entry) && entry.credentialId === signature.credentialId);
  if (matches.length > 1) return { ok: false, problem: 'duplicate-authority' };
  const authority = matches[0];
  if (!authority) return { ok: false, problem: 'unknown-authority' };
  if (revoked.has(authority.credentialId)) return { ok: false, problem: 'revoked-authority' };
  const credential = {
    credentialId: String(authority.credentialId), alg: String(authority.alg), publicKey: isObject(authority.publicKey) ? authority.publicKey : {},
    rpId: String(authority.rpId), origins: Array.isArray(authority.origins) ? authority.origins.filter(isString) : [],
  };
  // DEC-0063: the estate passkey is a signing credential. An RP ID that is not sign.<domain> is wrong-rp before the
  // assertion is read; an origin outside the RP ID is not pinned, so a ceremony that ran there is wrong-origin.
  if (!isSigningRpId(authority.rpId)) return { ok: false, problem: 'wrong-rp' };
  credential.origins = credential.origins.filter((origin) => originWithin(origin, credential.rpId));
  const assertion = verifyAssertion(signature, credential, estateChallenge(digest));
  if (!assertion.ok) return { ok: false, problem: assertion.problem };

  const issuedAt = estateTime(record.issuedAt);
  const validUntil = estateTime(record.validUntil);
  if (!Number.isFinite(issuedAt) || !Number.isFinite(validUntil) || validUntil <= issuedAt || validUntil - issuedAt > MAX_VALIDITY_SECONDS * 1000) return { ok: false, problem: 'too-long-lived' };
  // A revision issued a moment ahead of this clock is admitted within the skew every relay time allows (DEC-0066).
  if (at < issuedAt - CLOCK_SKEW_SECONDS * 1000) return { ok: false, problem: 'not-yet-valid' };
  if (at > validUntil) return { ok: false, problem: 'expired' };
  const codes = [...new Set(recordFindings(record).map((finding) => finding.code))];
  if (codes.length > 0) return { ok: false, problem: 'rule-violation', codes };
  return { ok: true, digest, revision: record.revision, signedBy: credential.credentialId, signCount: assertion.signCount };
}

/** What a package verifier trusts for a package placed on a machine; undefined when the record places no such agent there. */
export function placementTrust(record, machineId, agentRef) {
  const machine = list(record.machines).find((entry) => entry.id === machineId);
  const placement = list(machine?.packages).find((entry) => entry.agentRef === agentRef);
  if (!placement) return undefined;
  return { publisher: list(record.publisherKeys).filter((key) => key.kid === placement.publisherKid) };
}

const MAX_WINDOW_MS = MAX_VALIDITY_SECONDS * 1000;
const isRevision = (value) => Number.isSafeInteger(value) && value >= 1;
const refused = (fault, detail) => ({ certified: false, fault, detail });

/**
 * DL-14 (DEC-0055, DEC-0060): whether `record` certifies the delegation key `kid` with the published key's `x` at `at`
 * (a Date or epoch seconds), for a verifier whose machine applied `applied` (`{revision, digest?}`). `extraRevocations`
 * are the revocation delta's entries applied since the revision (DEC-0054). The contract's `hubKeyCertified`, in its
 * order; never throws. Answers `{certified: true, machine, revision}` or `{certified: false, fault, detail}`: fault
 * `token` (`kid-not-certified`), `estate` (`estate-unreadable`, `estate-outside-window`, `estate-rolled-back`,
 * `estate-forked`) or `clock` (`no-clock`).
 */
export function hubKeyCertified(record, kid, x, at, applied, options) {
  const now = clockOf(at);
  if (Number.isNaN(now)) return refused('clock', 'no-clock');
  if (!isObject(record) || !isRevision(record.revision) || !isString(record.digest) || !Array.isArray(record.machines)) return refused('estate', 'estate-unreadable');
  if (record.revocations !== undefined && !Array.isArray(record.revocations)) return refused('estate', 'estate-unreadable');
  const extra = options?.extraRevocations;
  if (extra !== undefined && !Array.isArray(extra)) return refused('estate', 'estate-unreadable');
  const issuedAt = estateTime(record.issuedAt);
  const validUntil = estateTime(record.validUntil);
  // A window that is not a time, not positive or longer than 30 days is no window: NaN fails every comparison below.
  if (Number.isNaN(issuedAt) || Number.isNaN(validUntil) || validUntil <= issuedAt || validUntil - issuedAt > MAX_WINDOW_MS) return refused('estate', 'estate-unreadable');
  if (applied !== undefined) {
    if (!isObject(applied) || !isRevision(applied.revision) || (applied.digest !== undefined && !isString(applied.digest))) return refused('estate', 'estate-unreadable');
    // An older revision may still be inside its window and list a key the applied one revokes (a rollback).
    if (record.revision < applied.revision) return refused('estate', 'estate-rolled-back');
    if (record.revision === applied.revision && applied.digest !== undefined && record.digest !== applied.digest) return refused('estate', 'estate-forked');
  }
  // The window verifyEstateRecord admits the revision in: from 60 s before issuedAt to validUntil (DEC-0066).
  if (now < issuedAt - CLOCK_SKEW_SECONDS * 1000 || now > validUntil) return refused('estate', 'estate-outside-window');

  const revocations = [...(record.revocations ?? []), ...(extra ?? [])];
  // A ref is compared exactly, never as a string conversion.
  const revokes = (kind, ref) => revocations.some((entry) => isObject(entry) && entry.kind === kind && entry.ref === ref);
  if (!isString(kid) || revokes('hub-key', kid)) return refused('token', 'kid-not-certified');
  const holders = record.machines.filter((machine) => isObject(machine) && isObject(machine.hubKey) && machine.hubKey.kid === kid);
  // Two machines under one kid break FAC-SEM-073; such a revision certifies neither.
  if (holders.length !== 1) return refused('token', 'kid-not-certified');
  const [machine] = holders;
  // A missing x never equals a missing x: the published key must be the certified one.
  if (!isString(x) || machine.hubKey.x !== x) return refused('token', 'kid-not-certified');
  if (revokes('machine', machine.id)) return refused('token', 'kid-not-certified');
  return { certified: true, machine: String(machine.id), revision: record.revision };
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
  if (next.revision !== Number(parent.revision) + 1) flag('/next/revision', `the revision after ${String(parent.revision)} is ${Number(parent.revision) + 1}: a revision never skips or repeats one`);
  let parentDigest;
  try {
    parentDigest = estateRecordDigest(parent);
  } catch {
    parentDigest = undefined;
  }
  if (next.parent !== parentDigest) flag('/next/parent', 'parent names the digest of the revision before it');
  if (estateTime(next.issuedAt) < estateTime(parent.issuedAt)) flag('/next/issuedAt', 'a revision is never issued before its parent');
  const kept = new Set(list(next.revocations).map(revocationKey));
  list(parent.revocations).forEach((entry, index) => {
    if (!kept.has(revocationKey(entry))) flag(`/parent/revocations/${index}`, `the ${String(entry.kind)} revocation of ${String(entry.ref)} is dropped: a revision keeps every revocation before it`);
  });
  return findings;
}

const validDeviceKey = (key) => {
  const raw = Buffer.from(String(key.publicKey ?? ''), 'base64');
  return key.alg === 'ed25519' ? raw.length === 32 && !smallOrder(raw) : isValidP256Key(raw);
};

function keys(value, flag) {
  const ids = new Set();
  const hubKids = new Set();
  const hubKeys = new Set();
  list(value.machines).forEach((machine, m) => {
    const at = `/machines/${m}`;
    if (ids.has(machine.id)) flag(`${at}/id`, `machine ${String(machine.id)} is listed twice`);
    ids.add(machine.id);
    const deviceKeys = list(machine.deviceKeys);
    if (deviceKeys.filter((key) => key.use === 'sig').length !== 1) flag(`${at}/deviceKeys`, 'a machine has exactly one signing device key, <id>#sig');
    if (deviceKeys.filter((key) => key.use === 'kem').length > 1) flag(`${at}/deviceKeys`, 'a machine has at most one key-agreement device key, <id>#kem');
    const seen = new Set();
    deviceKeys.forEach((key, k) => {
      if (key.kid !== `${String(machine.id)}#${String(key.use)}`) flag(`${at}/deviceKeys/${k}/kid`, 'a device key is listed as <machine id>#sig or <machine id>#kem, by its role');
      if (!validDeviceKey(key)) flag(`${at}/deviceKeys/${k}/publicKey`, 'an Ed25519 key is never of small order (DEC-0045) and a P-256 key is a valid point (SEC 1 §3.2.2)');
      if (seen.has(key.publicKey)) flag(`${at}/deviceKeys/${k}/publicKey`, 'one key is never used for the other role');
      seen.add(key.publicKey);
    });
    if (isObject(machine.hubKey)) {
      const hub = machine.hubKey;
      if (hubKids.has(hub.kid)) flag(`${at}/hubKey/kid`, `hub key ${String(hub.kid)} is certified for two machines: one kid per machine`);
      hubKids.add(hub.kid);
      if (hubKeys.has(hub.x)) flag(`${at}/hubKey/x`, 'one hub public key is certified for two machines under two kids: one key per machine');
      hubKeys.add(hub.x);
      if (smallOrder(Buffer.from(String(hub.x ?? ''), 'base64url'))) flag(`${at}/hubKey/x`, 'a hub key of small order verifies forged tokens and is never certified (DEC-0045)');
    }
  });
  const credentials = new Set();
  list(value.authorities).forEach((authority, index) => {
    if (credentials.has(authority.credentialId)) flag(`/authorities/${index}/credentialId`, 'a passkey is listed once');
    credentials.add(authority.credentialId);
    if ('problem' in credentialKey(authority.publicKey, String(authority.alg))) flag(`/authorities/${index}/publicKey`, "a passkey's public key is a valid P-256 point for ES256 or an Ed25519 key of full order for EdDSA");
  });
}

function placements(value, flag) {
  const kids = new Set();
  list(value.publisherKeys).forEach((key, index) => {
    if (kids.has(key.kid)) flag(`/publisherKeys/${index}/kid`, `publisher key ${String(key.kid)} is pinned twice`);
    kids.add(key.kid);
  });
  list(value.machines).forEach((machine, m) => {
    const agents = new Set();
    list(machine.packages).forEach((placement, p) => {
      const at = `/machines/${m}/packages/${p}`;
      if (agents.has(placement.agentRef)) flag(`${at}/agentRef`, `${String(placement.agentRef)} is placed twice on one machine`);
      agents.add(placement.agentRef);
      if (!kids.has(placement.publisherKid)) flag(`${at}/publisherKid`, `publisher key ${String(placement.publisherKid)} is not in publisherKeys, so the machine pins no key to verify the package under`);
    });
  });
}

function secretReferences(value, flag) {
  const machineIds = new Set(list(value.machines).map((machine) => machine.id));
  list(value.machines).forEach((machine, m) => {
    const placed = new Set(list(machine.packages).map((placement) => placement.agentRef));
    const slots = new Set();
    list(machine.secrets).forEach((secret, s) => {
      const at = `/machines/${m}/secrets/${s}`;
      for (const field of ['slot', 'from', 'agentRef']) {
        const text = secret[field];
        if (isString(text) && secretValue(text)) flag(`${at}/${field}`, 'a secret placement names a slot, never a value: this looks like a credential');
      }
      if (!placed.has(secret.agentRef)) flag(`${at}/agentRef`, 'a secret goes only where a placed package declares it (v4 Path 2): this agent is not placed on this machine');
      if (!machineIds.has(secret.from)) flag(`${at}/from`, 'the slot is filled from a machine of this estate');
      const key = `${String(secret.agentRef)} ${String(secret.slot)}`;
      if (slots.has(key)) flag(`${at}/slot`, `slot ${String(secret.slot)} is placed twice for one agent on one machine`);
      slots.add(key);
    });
  });
}

function grantsAndRevocations(value, flag) {
  const grantIds = new Set();
  list(value.shareGrants).forEach((grant, index) => {
    if (grant.principalKind !== 'external') flag(`/shareGrants/${index}/principalKind`, 'a share grant is to a principal outside the estate: principalKind external');
    const id = isObject(grant.meta) ? grant.meta.id : undefined;
    if (grantIds.has(id)) flag(`/shareGrants/${index}/meta/id`, `grant ${String(id)} is listed twice`);
    grantIds.add(id);
  });
  const machines = list(value.machines);
  // A Map, so a kind such as `constructor` or `__proto__` reads nothing from Object.prototype.
  const listed = new Map(Object.entries({
    authority: new Set(list(value.authorities).map((entry) => entry.credentialId)),
    machine: new Set(machines.map((machine) => machine.id)),
    'device-key': new Set(machines.flatMap((machine) => list(machine.deviceKeys).map((key) => key.kid))),
    'hub-key': new Set(machines.flatMap((machine) => (isObject(machine.hubKey) ? [machine.hubKey.kid] : []))),
    'publisher-key': new Set(list(value.publisherKeys).map((key) => key.kid)),
    package: new Set(machines.flatMap((machine) => list(machine.packages).map((placement) => placement.digest))),
    grant: grantIds,
  }));
  const seen = new Set();
  list(value.revocations).forEach((revocation, index) => {
    const key = `${String(revocation.kind)} ${String(revocation.ref)}`;
    if (seen.has(key)) flag(`/revocations/${index}`, `the ${String(revocation.kind)} ${String(revocation.ref)} is revoked twice`);
    seen.add(key);
    if (listed.get(String(revocation.kind))?.has(revocation.ref)) flag(`/revocations/${index}/ref`, `the record still lists the ${String(revocation.kind)} it revokes: revocation outranks addition`);
  });
}

function recordFindings(value) {
  const findings = [];
  revisionWhole(value, flagger(findings, 'FAC-SEM-072'));
  keys(value, flagger(findings, 'FAC-SEM-073'));
  placements(value, flagger(findings, 'FAC-SEM-074'));
  secretReferences(value, flagger(findings, 'FAC-SEM-075'));
  grantsAndRevocations(value, flagger(findings, 'FAC-SEM-076'));
  // FAC-SEM-092 (DEC-0063) on each passkey the record lists.
  list(value.authorities).forEach((authority, index) => signingCredential(authority, `/authorities/${index}`, flagger(findings, 'FAC-SEM-092')));
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
  const machineIndex = list(record.machines).findIndex((entry) => entry.id === value.machine);
  const machine = list(record.machines)[machineIndex];
  let digest;
  try {
    digest = packageDigest(pkg);
  } catch {
    digest = undefined;
  }
  const flag074 = flagger(findings, 'FAC-SEM-074');
  if (!machine) {
    flag074('/machine', `machine ${String(value.machine)} is not in the estate record`);
    return findings;
  }
  if (digest === undefined || digest !== pkg.digest) flag074('/package/digest', 'the package is not the one its digest names: it changed after it was packed');
  const placement = list(machine.packages).find((entry) => entry.agentRef === pkg.agentRef);
  if (!placement) flag074('/package/agentRef', `the record places no ${String(pkg.agentRef)} on machine ${String(value.machine)}`);
  else if (placement.digest !== digest) flag074('/package', `the record places ${String(placement.digest)} of this agent on this machine, not this package`);
  const declared = new Set(list(pkg.secrets).map((slot) => slot.name));
  const flag075 = flagger(findings, 'FAC-SEM-075');
  list(machine.secrets).forEach((secret, index) => {
    if (secret.agentRef === pkg.agentRef && !declared.has(secret.slot)) flag075(`/record/machines/${machineIndex}/secrets/${index}/slot`, `the package declares no slot ${String(secret.slot)}: a secret goes only where a placed package declares it`);
  });
  return findings;
}

/** FAC-SEM-072…076 for an `estate-record`, an `estate-record-revision` `{parent, next}` or an `estate-placement`. */
export function estateRecordRules(kind, value) {
  const doc = isObject(value) ? value : {};
  if (kind === 'estate-record') return recordFindings(doc);
  if (kind === 'estate-record-revision') return revisionChain(doc);
  if (kind === 'estate-placement') return installation(doc);
  return undefined;
}
