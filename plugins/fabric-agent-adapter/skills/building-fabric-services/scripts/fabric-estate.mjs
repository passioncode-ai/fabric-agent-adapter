// `estate-record/1` (Fabric Agent Contract DEC-0055): verify an estate revision and check its rules, the twin of
// fabric_estate.py. The contract's src/estate-record-rules.ts, src/webauthn.ts and src/p256.ts at the pin, held to the
// contract's own vectors (test/fixtures/contract/estate-vectors.json):
//
// - verifyEstateRecord(record, { at, parent } | { at, authorities }): the verdict a machine applies a revision on, after
//   it has checked the revision against estate-record.schema.json (the verifier does not check the schema);
// - estateRecordRules(kind, value): FAC-SEM-072…076, with FAC-SEM-134 on each machine's profile (DEC-0106) and
//   FAC-SEM-147 on the organizations a record pins (DEC-0127, DEC-0128);
// - machineProfile(record, machineId): a machine's profile (DEC-0106): `full`, `member`, `view`, or undefined;
// - deltaAnchorOf(record): the revocation delta's head a revision vouches for (DEC-0107), or undefined; a revision
//   never moves it back (FAC-SEM-137, in the revision rules and the verdict);
// - hubKeyCertified(record, kid, x, at, applied, {context}): DL-14: a delegation verifier that reads the estate record
//   trusts a token's `kid` only while a current revision certifies it for a machine, and in an organization's context
//   only under that context's hub key while the record pins it (DL-14a, DEC-0128; fabric-delegation.mjs calls it).
//
// The record's own rules live in fabric-estate-rules.mjs since 0.52.0 (decision D8); every public name there is
// re-exported here.
//
// Node's own crypto: ES256 through createPublicKey (JWK) and verify (DER), EdDSA through Ed25519.

import crypto from 'node:crypto';
import { isObject, isString, objects as list } from './fabric-jsvalue.mjs'; // the core's (FAA-65)
import { sha256, isValidP256Key } from './fabric-crypto.mjs'; // the core's (FAA-65)
import { parseRfc3339Ms as estateTime, clockMs as clockOf } from './fabric-time.mjs'; // the core's (FAA-65)
import {
  MAX_VALIDITY_SECONDS, ASSERTION_ALGORITHMS, PERSONAL_CONTEXT, B64URL, contextOf, credentialKey, estateRecordDigest,
  estateChallenge, isSigningRpId, originWithin, revocationKey, scopeAdmits, recordFindings, droppedFindings, anchorFindings,
} from './fabric-estate-rules.mjs';
// The record's rules (D8), re-exported so callers keep importing them from this module.
export {
  ESTATE_RECORD_SCHEMA, ESTATE_CHALLENGE_TYPE, MAX_VALIDITY_SECONDS, ASSERTION_ALGORITHMS, PERSONAL_CONTEXT, ORG_CONTEXT_PREFIX,
  parseContext, credentialKey, estateRecordDigest, estateChallengeInput, estateChallenge, isSigningRpId, originWithin,
  KEY_REFERENCE, deviceKeyFingerprint, deviceKeyRef, validDeviceKey, grantContextFindings, placementGrantFindings,
  MACHINE_PROFILES, machineProfile, deltaAnchorOf, estateRecordRules,
} from './fabric-estate-rules.mjs';
export { isValidP256Key, estateTime };

/** How far ahead of the verifier's clock a signed `issuedAt` may be before it is `not-yet-valid` (DEC-0066). */
export const CLOCK_SKEW_SECONDS = 60;
export const FLAGS = Object.freeze({ UP: 0x01, UV: 0x04, BE: 0x08, BS: 0x10, AT: 0x40, ED: 0x80 });
const bytes = (text) => Buffer.from(text, 'base64url');

// ---- WebAuthn Level 3 §7.2, offline ----

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
  // With a parent, what the revision drops it revokes (FAC-SEM-114, DEC-0084): a removed machine, a replaced key.
  const dropped = isObject(trust.parent) ? [...droppedFindings(trust.parent, record), ...anchorFindings(trust.parent, record)] : [];
  const codes = [...new Set([...recordFindings(record), ...dropped].map((finding) => finding.code))];
  if (codes.length > 0) return { ok: false, problem: 'rule-violation', codes };
  return { ok: true, digest, revision: record.revision, signedBy: credential.credentialId, signCount: assertion.signCount };
}

/**
 * What a package verifier trusts for a package placed on a machine in a context (DEC-0082; `personal` when not given);
 * undefined when the record places no such agent there in that context.
 */
export function placementTrust(record, machineId, agentRef, context = PERSONAL_CONTEXT) {
  if (!isObject(record)) return undefined; // a record that is no object places nothing, as in the Python twin
  const machine = list(record.machines).find((entry) => entry.id === machineId);
  const placement = list(machine?.packages).find((entry) => entry.agentRef === agentRef && contextOf(entry) === context);
  if (!placement) return undefined;
  // DEC-0090: a partner's key is trusted only in the contexts its scope names.
  if (!scopeAdmits(record, placement.publisherKid, context)) return { publisher: [] };
  return { publisher: list(record.publisherKeys).filter((key) => key.kid === placement.publisherKid) };
}


const MAX_WINDOW_MS = MAX_VALIDITY_SECONDS * 1000;
const isRevision = (value) => Number.isSafeInteger(value) && value >= 1;
const refused = (fault, detail) => ({ certified: false, fault, detail });
/** An organization's context id (DEC-0082). */
const ORG_CONTEXT = /^org:[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;

/**
 * DL-14 (DEC-0055, DEC-0060): whether `record` certifies the delegation key `kid` with the published key's `x` at `at`
 * (a Date or epoch seconds), for a verifier whose machine applied `applied` (`{revision, digest?}`). `extraRevocations`
 * are the revocation delta's entries applied since the revision (DEC-0054). `context` is the context the token is in
 * (DEC-0128): absent or `personal` reads each machine's personal `hubKey`; an organization's `org:<orgId>` reads only that
 * context's hub keys (`machines[].contextHubKeys`) and only while the record pins the organization, so a context key never
 * verifies a personal token and the personal key never an organization's; any other context certifies nothing, so a
 * misconfigured callee fails closed. The contract's `hubKeyCertified`, in its order; never throws. Answers `{certified: true, machine, revision}` or `{certified: false, fault, detail}`: fault
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
  const context = options?.context;
  const inOrg = isString(context) && ORG_CONTEXT.test(context);
  // A context that is neither personal nor an organization's names no key: a misconfigured callee fails closed.
  if (context !== undefined && context !== 'personal' && !inOrg) return refused('token', 'kid-not-certified');
  // DEC-0128: an organization's token verifies only under that context's key, and only while the record pins it.
  if (inOrg && !(Array.isArray(record.organizations) ? record.organizations : []).some((pin) => isObject(pin) && pin.org === context)) return refused('token', 'kid-not-certified');
  const keyOf = (machine) => {
    if (!inOrg) return isObject(machine.hubKey) ? machine.hubKey : undefined;
    const entries = Array.isArray(machine.contextHubKeys) ? machine.contextHubKeys : [];
    const entry = entries.find((item) => isObject(item) && item.context === context && isObject(item.key) && item.key.kid === kid);
    return isObject(entry) ? entry.key : undefined;
  };
  const holders = record.machines.filter((machine) => isObject(machine) && keyOf(machine)?.kid === kid);
  // Two machines under one kid break FAC-SEM-073; such a revision certifies neither.
  if (holders.length !== 1) return refused('token', 'kid-not-certified');
  const [machine] = holders;
  // A missing x never equals a missing x: the published key must be the certified one.
  if (!isString(x) || keyOf(machine).x !== x) return refused('token', 'kid-not-certified');
  if (revokes('machine', machine.id)) return refused('token', 'kid-not-certified');
  return { certified: true, machine: String(machine.id), revision: record.revision };
}
