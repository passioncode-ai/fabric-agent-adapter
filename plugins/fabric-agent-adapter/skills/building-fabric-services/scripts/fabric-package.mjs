#!/usr/bin/env node
// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
// fabric-package/1 (contract DEC-0050, DEC-0051, DEC-0071, DEC-0074; FAA-27a): pack an agent or a skill set as one folder
// with fabric.package.json, sign it, and verify it. The twin of fabric_package.py; both write the same bytes.
//
//   node fabric-package.mjs pack   <folder> [--apply]
//   node fabric-package.mjs sign   <folder> --key <private key file> [--kid <kid>] [--role publisher|organization] [--apply]
//   node fabric-package.mjs verify <folder> --trust <trust.json> [--countersigned]
//
// pack reads the author's fabric.package.json, lists every other file with its SHA-256, derives agentRef, computes the
// digest and checks the result against the contract's schema, FAC-SEM-064…066/102 and the folder check. sign adds an
// Ed25519 signature (EdDSA, the one algorithm DEC-0051 admits) from a key file the caller names; it never makes or keeps
// a key. verify is the contract's verifyPackage (PK-1…PK-10) plus the folder check. Without --apply nothing is written.
// No dependencies; the answer is JSON on stdout, exit 0 when it holds, 1 when it does not, 2 on a usage error.

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { isSmallOrderKey } from './fabric-delegation.mjs';

export { PACKAGE_FILE, PLUGIN_MANIFEST, SIGNATURE_STATEMENT, agentRefOf, sha256Of, packageDigest, packageSigningInput, pathProblem, pathProblems, packageFindings } from './fabric-package-rules.mjs'; // the rule layer
import { PACKAGE_FILE, PLUGIN_MANIFEST, agentRefOf, sha256Of, packageDigest, packageSigningInput, packageFindings, pathProblems, mcpRequirements } from './fabric-package-rules.mjs';
/** DEC-0051: ES256 joins when Fabric records its decision D2; until then a verifier refuses it as unknown-algorithm. */
export const PACKAGE_ALGORITHMS = Object.freeze(['EdDSA']);
// What pack refuses to list: version-control and cache litter, and files that are credentials by their name, the kit's
// own token files (service.token, fabric-auth; board.credential, fabric-hub) among them (FAA-190 (15)).
const JUNK = /^(\.git|__pycache__|\.DS_Store|.*\.pyc)$/;
const SECRET_FILE = /^(\.env(\..+)?|.*\.(pem|key|p12|pfx|jks|keystore|token|credential)|id_(rsa|dsa|ecdsa|ed25519)|\.(npmrc|netrc|pypirc))$/;
const SECRET_FILE_OK = /^\.env\.(example|sample|template)$/;
// A file holding a private JWK, whatever its name (FAA-190 (15)): a `d` member of 32 bytes or more in base64url, in JSON,
// escaped JSON or Python, read over the file's bytes (latin1, one character a byte) as the Python twin's PRIVATE_JWK.
const PRIVATE_JWK = /\\?["']d\\?["'][ \t]*:[ \t]*\\?["'][A-Za-z0-9_-]{43}/;
const B64URL = /^[A-Za-z0-9_-]+$/;
const PKCS8_ED25519 = Buffer.from('302e020100300506032b657004220420', 'hex');
/**
 * How deep a document read from disk may nest. Python's recursion limit and Node's stack give out at different depths,
 * so both readers refuse past this one, well below either (FAA-78, finding 43); no package document comes near it.
 */
export const MAX_NESTING = 256;
/** Strict UTF-8: invalid bytes are a refusal, never replaced, so the bytes read are the bytes signed (finding 43). */
const strictUtf8 = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });
import { isObject, objects, jsonEqual } from './fabric-jsvalue.mjs'; // the core's (FAA-65)
import { isString } from './fabric-jsvalue.mjs'; // the core's (FAA-65)

/** A refusal a person can act on; the message names what to change. */
export class PackageError extends Error {}

// --- keys ---------------------------------------------------------------------------------------------------------

const privateKeyOf = (seed) => crypto.createPrivateKey({ key: Buffer.concat([PKCS8_ED25519, seed]), format: 'der', type: 'pkcs8' });

/** The 32-byte public key of a 32-byte Ed25519 seed. */
export function ed25519PublicKey(seed) {
  if (seed.length !== 32) throw new PackageError('An Ed25519 private key is 32 bytes.');
  return Buffer.from(crypto.createPublicKey(privateKeyOf(seed)).export({ format: 'jwk' }).x, 'base64url');
}

/** A deterministic Ed25519 signature; the same seed and message give the bytes the Python signer gives. */
export const ed25519Sign = (seed, message) => crypto.sign(null, message, privateKeyOf(seed));

/** The public JWK an installing machine pins for this key (the package names a publisher, never a key). */
export const publicJwk = (seed, kid) => ({ kty: 'OKP', crv: 'Ed25519', x: ed25519PublicKey(seed).toString('base64url'), kid, alg: 'EdDSA', use: 'sig' });

/**
 * { seed, kid } from a private key file: a JWK (kty OKP, crv Ed25519, d; kid and alg EdDSA if named) or a PKCS#8 PEM
 * (openssl genpkey -algorithm ed25519, then --kid). The file must be readable by its owner only; its bytes are never
 * echoed.
 */
export function readSigningKey(file, kid) {
  let stat;
  let raw;
  try {
    stat = fs.statSync(file);
    raw = fs.readFileSync(file);
  } catch (error) {
    throw new PackageError(`Cannot read the key file ${file}: ${error.code ?? error.message}.`);
  }
  if (process.platform !== 'win32' && (stat.mode & 0o077)) throw new PackageError(`The key file ${file} is readable by others (mode ${(stat.mode & 0o777).toString(8)}); chmod 600 it first.`);
  const text = raw.toString('utf8').trim();
  let seed;
  if (text.startsWith('{')) {
    let jwk;
    // past MAX_NESTING no key: JSON.parse reads deeper than Python's stack, and both kits answer alike (FAA-194 (32))
    if (nestingOf(text) > MAX_NESTING) throw new PackageError('The key file is neither a JWK nor a PEM private key.');
    try { jwk = JSON.parse(text); } catch { throw new PackageError('The key file is neither a JWK nor a PEM private key.'); }
    if (!isObject(jwk) || jwk.kty !== 'OKP' || jwk.crv !== 'Ed25519' || !isString(jwk.d)) throw new PackageError('The key file must be an Ed25519 private JWK (kty OKP, crv Ed25519, with d).');
    if ((jwk.alg ?? 'EdDSA') !== 'EdDSA') throw new PackageError(`The key names alg ${JSON.stringify(jwk.alg)}; a package signature is EdDSA (DEC-0051).`);
    seed = B64URL.test(jwk.d) ? Buffer.from(jwk.d, 'base64url') : Buffer.alloc(0);
    if (seed.length !== 32) throw new PackageError("The key's d is not a 32-byte Ed25519 private key.");
    if (isString(jwk.x) && jwk.x !== ed25519PublicKey(seed).toString('base64url')) throw new PackageError("The key's x is not the public key of its d.");
    if (kid !== undefined && jwk.kid !== undefined && kid !== jwk.kid) throw new PackageError(`--kid ${kid} disagrees with the key's own kid ${jwk.kid}.`);
    kid = kid ?? jwk.kid;
  } else if (text.includes(`-----BEGIN ${'PRIVATE KEY'}-----`)) {
    const body = text.split(/\r?\n/).filter((line) => line && !line.startsWith('-----')).join('');
    if (!/^[A-Za-z0-9+/]*={0,2}$/.test(body)) throw new PackageError('The PEM key is not base64.');
    const der = Buffer.from(body, 'base64');
    if (der.length !== 48 || !der.subarray(0, 16).equals(PKCS8_ED25519)) throw new PackageError('The PEM key is not an Ed25519 private key (PKCS#8).');
    seed = der.subarray(16);
  } else {
    throw new PackageError('The key file is neither a JWK nor a PEM private key.');
  }
  if (!isString(kid) || !/^[A-Za-z0-9._:-]{1,128}$/.test(kid)) throw new PackageError('Name the key with --kid (1-128 of A-Z a-z 0-9 . _ : -): the installing machine pins it by that name.');
  return { seed, kid };
}

export { schemaProblems } from './fabric-package-schema.mjs'; // the schema reading (FAA-92)
import { pointer, schema, schemaProblems } from './fabric-package-schema.mjs';


// --- the folder check and the verifier -------------------------------------------------------------------------------

const replacingUtf8 = new TextDecoder('utf-8', { ignoreBOM: true });
// How deep the arrays and objects of a JSON text nest, strings skipped (the Python kit's _nesting).
const nestingOf = (text) => {
  let depth = 0;
  let deepest = 0;
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (c === '"') { i += 1; while (i < text.length && text[i] !== '"') i += text[i] === '\\' ? 2 : 1; } else if (c === '{' || c === '[') { depth += 1; deepest = Math.max(deepest, depth); } else if (c === '}' || c === ']') depth -= 1;
  }
  return deepest;
};
// A plugin or provider manifest as the contract's checkPackageFolder reads it: decoded with replacement characters
// (FAA-194 (29)); nesting past MAX_NESTING, the limit both kits share, is no manifest (FAA-194 (27)).
const parsed = (bytes) => {
  if (bytes === undefined) return undefined;
  const text = replacingUtf8.decode(bytes);
  if (nestingOf(text) > MAX_NESTING) return undefined;
  try {
    const value = JSON.parse(text);
    return isObject(value) ? value : undefined;
  } catch {
    return undefined;
  }
};

/**
 * DEC-0050's folder check: every listed file present with its SHA-256, nothing unlisted but fabric.package.json, the
 * plugin manifest naming the package's id and version, and the provider manifest carrying the package's cost presets or
 * none. `files` maps each forward-slash path to its bytes.
 */
export function checkPackageFolder(pkg, files) {
  const problems = [];
  const listed = new Map(objects(pkg.files).map((entry) => [String(entry.path), entry.sha256]));
  for (const [p, sha256] of listed) {
    const bytes = files.get(p);
    if (bytes === undefined) problems.push({ problem: 'file-missing', path: p });
    else if (sha256Of(bytes) !== sha256) problems.push({ problem: 'file-digest', path: p });
  }
  for (const p of files.keys()) if (p !== PACKAGE_FILE && !listed.has(p)) problems.push({ problem: 'file-unlisted', path: p });
  if (files.has(PLUGIN_MANIFEST)) {
    const plugin = parsed(files.get(PLUGIN_MANIFEST));
    if (!plugin || plugin.name !== pkg.id || plugin.version !== pkg.version) problems.push({ problem: 'plugin-manifest', path: PLUGIN_MANIFEST });
  }
  if (isString(pkg.provider)) {
    const provider = parsed(files.get(pkg.provider));
    if (files.has(pkg.provider) && (!provider || (provider.costPresets !== undefined && !jsonEqual(provider.costPresets, pkg.costPresets)))) problems.push({ problem: 'provider-manifest', path: pkg.provider });
  }
  return problems;
}

function keyFor(keys, kid, alg) {
  const matches = keys.filter((candidate) => isObject(candidate) && candidate.kid === kid);
  if (matches.length > 1) return { problem: 'duplicate-kid' };
  const jwk = matches[0];
  if (!jwk) return { problem: 'unknown-key' };
  if (jwk.alg !== alg) return { problem: 'key-algorithm-mismatch' };
  if (jwk.kty !== 'OKP' || jwk.crv !== 'Ed25519' || !isString(jwk.x) || !B64URL.test(jwk.x) || jwk.d !== undefined || (jwk.use !== undefined && jwk.use !== 'sig')) return { problem: 'unusable-key' };
  const raw = Buffer.from(jwk.x, 'base64url');
  if (raw.length !== 32) return { problem: 'unusable-key' };
  if (isSmallOrderKey(raw)) return { problem: 'small-order-key' }; // DEC-0045: refused before any verification
  return { key: crypto.createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: jwk.x }, format: 'jwk' }) };
}

/** The contract's verifyPackage (DEC-0051), in PK-1…PK-10's order. */
export function verifyPackage(pkg, trust, options = {}) {
  if (!isObject(pkg) || !isString(pkg.digest)) return { ok: false, problem: 'malformed' };
  let digest;
  try { digest = packageDigest(pkg); } catch { return { ok: false, problem: 'malformed' }; }
  if (digest !== pkg.digest) return { ok: false, problem: 'digest-mismatch' };
  if (pkg.signatures === undefined || (Array.isArray(pkg.signatures) && pkg.signatures.length === 0)) return { ok: false, problem: 'unsigned' };
  if (!Array.isArray(pkg.signatures)) return { ok: false, problem: 'malformed' };
  if (pkg.signatures.filter((e) => isObject(e) && e.role === 'publisher').length !== 1) return { ok: false, problem: 'no-publisher-signature' };
  const signers = [];
  const unverified = [];
  const pinned = isObject(trust) ? trust : {};
  for (const [index, entry] of pkg.signatures.entries()) {
    if (!isObject(entry) || (entry.role !== 'publisher' && entry.role !== 'organization') || !isString(entry.alg) || !isString(entry.kid) || !isString(entry.sig) || !B64URL.test(entry.sig)) return { ok: false, problem: 'malformed', signature: index };
    if (!PACKAGE_ALGORITHMS.includes(entry.alg)) return { ok: false, problem: 'unknown-algorithm', signature: index };
    const set = (entry.role === 'publisher' ? pinned.publisher : pinned.organization) ?? [];
    const found = keyFor(Array.isArray(set) ? set : [], entry.kid, entry.alg);
    if (found.problem === 'unknown-key' && entry.role === 'organization' && options.countersigned !== true) { unverified.push({ role: entry.role, kid: entry.kid }); continue; }
    if (found.problem) return { ok: false, problem: found.problem, signature: index };
    const signature = Buffer.from(entry.sig, 'base64url');
    if (signature.length !== 64 || !crypto.verify(null, packageSigningInput(digest, entry.role), found.key, signature)) return { ok: false, problem: 'bad-signature', signature: index };
    signers.push({ role: entry.role, kid: entry.kid });
  }
  if (options.countersigned === true && !signers.some((s) => s.role === 'organization')) return { ok: false, problem: 'no-countersignature' };
  return unverified.length ? { ok: true, digest, signers, unverified } : { ok: true, digest, signers };
}

/** What a placement lacks for requires.mcp (DEC-0071): `configured` maps each registered role to its tools. */
export function consumerPlacement(pkg, configured) {
  if (!isObject(pkg)) return [];
  const roles = mcpRequirements(pkg).filter((r) => isString(r.role));
  if (!(configured instanceof Map)) return roles.map((r) => ({ problem: 'missing-role', role: r.role }));
  const problems = [];
  for (const requirement of roles) {
    const registered = configured.get(requirement.role);
    if (registered === undefined) { problems.push({ problem: 'missing-role', role: requirement.role }); continue; }
    const tools = Array.isArray(registered) ? registered : [];
    for (const tool of Array.isArray(requirement.tools) ? requirement.tools : []) if (isString(tool) && !tools.includes(tool)) problems.push({ problem: 'missing-tool', role: requirement.role, tool });
  }
  return problems;
}

// --- the folder on disk ----------------------------------------------------------------------------------------------

const litter = (name) => (JUNK.test(name) ? 'litter' : SECRET_FILE.test(name) && !SECRET_FILE_OK.test(name) ? 'a credential file' : null);
const utf16Order = (a, b) => (a < b ? -1 : a > b ? 1 : 0); // JavaScript compares strings by UTF-16 code units

/** Opening a packaged file: never through a link (where the platform can say so), never waiting on a pipe (finding 42). */
const FILE_FLAGS = fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0);
/** What open() answers for a link it was told not to follow: ELOOP on Linux and macOS, EMLINK on FreeBSD. */
const LINK_CODES = new Set(['ELOOP', 'EMLINK']);

const unreadable = (where, error) => new PackageError(`Cannot read ${where || '.'}: ${error.code ?? error.message}.`);

/** The file's bytes, or the reason it is not read: a link, or not a regular file. Throws the system's error. */
function readRegular(file) {
  let fd;
  try {
    fd = fs.openSync(file, FILE_FLAGS);
  } catch (error) {
    if (fs.constants.O_NOFOLLOW !== undefined && LINK_CODES.has(error.code)) return { why: 'a symlink' };
    throw error;
  }
  try {
    if (!fs.fstatSync(fd).isFile()) return { why: 'not a regular file' };
    return { bytes: fs.readFileSync(fd) };
  } finally {
    fs.closeSync(fd);
  }
}

/**
 * Every regular file under `folder` by its forward-slash path. Refuses a symlink, a special file, version-control or
 * cache litter, and a file that is a credential by its name, each named, so the person can remove it or pack a clean
 * copy. A file or folder it cannot read is a refusal naming it (`Cannot read <path>: EACCES.`), never a crash (FAA-78,
 * finding 41); a file is opened without following a link and read only when it is a regular file (finding 42). Node
 * has no openat, so a folder swapped for a link mid-walk is checked by lstat before it is listed, after each file it
 * reads and after it is listed (FAA-91); a swap made and undone between two of those checks is not seen. The Python
 * twin holds each folder open instead.
 */
export function readFolder(folder) {
  let stat;
  try { stat = fs.statSync(folder); } catch { stat = null; }
  if (!stat?.isDirectory()) throw new PackageError(`${folder} is not a folder.`);
  const files = new Map();
  const refused = [];
  const moved = (dir, before) => {
    let now;
    try { now = fs.lstatSync(dir); } catch { return true; }
    return !now.isDirectory() || now.ino !== before.ino || now.dev !== before.dev;
  };
  const walk = (dir, rel) => {
    let entries;
    let before;
    try {
      before = rel ? fs.lstatSync(dir) : null;
      entries = fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => utf16Order(a.name, b.name));
    } catch (error) {
      throw unreadable(rel, error);
    }
    if (before && !before.isDirectory()) { refused.push(`${rel} (a symlink)`); return; }
    for (const entry of entries) {
      const where = rel ? `${rel}/${entry.name}` : entry.name;
      let why = entry.isSymbolicLink() ? 'a symlink' : litter(entry.name) ?? (entry.isDirectory() || entry.isFile() ? null : 'not a regular file');
      if (!why && entry.isDirectory()) { walk(path.join(dir, entry.name), where); continue; }
      if (!why) {
        let read;
        try { read = readRegular(path.join(dir, entry.name)); } catch (error) { throw unreadable(where, error); }
        if (before && moved(dir, before)) { refused.push(`${rel} (a symlink)`); return; } // read through a swapped folder
        if (read.why === undefined && PRIVATE_JWK.test(read.bytes.toString('latin1'))) read.why = "a private key (a JWK's d)";
        if (read.why === undefined) { files.set(where, read.bytes); continue; }
        why = read.why;
      }
      refused.push(`${where} (${why})`);
    }
    if (before) {
      try { fs.lstatSync(dir); } catch (error) { throw unreadable(rel, error); }
      if (moved(dir, before)) refused.push(`${rel} (a symlink)`);
    }
  };
  walk(folder, '');
  if (refused.length) throw new PackageError(`Not packed: pack a clean copy (what Git would commit, references/package.md); delete only litter and credential files in place: ${refused.sort().join('; ')}`);
  return files;
}

/**
 * A JSON object from strict UTF-8 bytes (a string is taken as decoded already): no member named twice, nesting at most
 * MAX_NESTING deep, as the Python kit's reader. Every refusal is a PackageError.
 */
function parseStrict(input, what) {
  let text = input;
  if (typeof input !== 'string') {
    try { text = strictUtf8.decode(input); } catch (error) { throw new PackageError(`${what} is not JSON: ${error.message}`); }
  }
  let value;
  try { value = JSON.parse(text); } catch (error) { throw new PackageError(`${what} is not JSON: ${error.message}`); }
  const stack = [];
  let i = 0;
  const skipString = () => { i += 1; let s = ''; while (text[i] !== '"') { if (text[i] === '\\') { s += text.slice(i, i + 2); i += 2; } else { s += text[i]; i += 1; } } i += 1; return JSON.parse(`"${s}"`); };
  while (i < text.length) {
    const c = text[i];
    if ((c === '{' || c === '[') && stack.length >= MAX_NESTING) throw new PackageError(`${what} nests deeper than ${MAX_NESTING} levels.`);
    if (c === '{') { stack.push({ keys: new Set(), expectKey: true }); i += 1; } else if (c === '[') { stack.push(null); i += 1; } else if (c === '}' || c === ']') { stack.pop(); i += 1; } else if (c === ',') { const top = stack.at(-1); if (top) top.expectKey = true; i += 1; } else if (c === '"') {
      const top = stack.at(-1);
      const s = skipString();
      if (top && top.expectKey) {
        if (top.keys.has(s)) throw new PackageError(`${what} names ${JSON.stringify(s)} twice in one object.`);
        top.keys.add(s);
        top.expectKey = false;
      }
    } else i += 1;
  }
  if (!isObject(value)) throw new PackageError(`${what} is not a JSON object.`);
  return value;
}

/** JSON.stringify(value, null, 2), the bytes both kits write. */
export const dumps = (value) => JSON.stringify(value, null, 2);

/**
 * The packed document: the author's fields in their order, agentRef derived after publisher for an agent, then files[]
 * (every file but this one, by path) and digest. Old signatures are dropped.
 */
export function compose(draft, files) {
  const notes = [];
  const agent = draft.kind === 'agent' && isString(draft.publisher) && isString(draft.id);
  if (agent && Object.hasOwn(draft, 'agentRef') && draft.agentRef !== agentRefOf(draft.publisher, draft.id)) {
    throw new PackageError(`agentRef is derived, never chosen: it is ${agentRefOf(draft.publisher, draft.id)} for this publisher and id (FAC-SEM-066). Remove agentRef or fix publisher/id.`);
  }
  const pkg = {};
  // A member is defined, never assigned: `pkg.__proto__ = v` would set the prototype and drop the member, where the
  // Python twin keeps it for the schema to refuse (finding 43).
  const put = (key, value) => Object.defineProperty(pkg, key, { value, enumerable: true, writable: true, configurable: true });
  for (const [key, value] of Object.entries(draft)) {
    if (key === 'files' || key === 'digest' || key === 'signatures' || (agent && key === 'agentRef')) continue;
    put(key, value);
    if (agent && key === 'publisher') put('agentRef', agentRefOf(draft.publisher, draft.id));
  }
  if (Array.isArray(draft.signatures) && draft.signatures.length) notes.push(`dropped ${draft.signatures.length} signature(s): a repacked package is signed again`);
  pkg.files = [...files.keys()].filter((p) => p !== PACKAGE_FILE).sort(utf16Order).map((p) => ({ path: p, sha256: sha256Of(files.get(p)) }));
  try {
    pkg.digest = packageDigest(pkg);
  } catch (error) {
    throw new PackageError(`fabric.package.json has no RFC 8785 form, so it has no digest: ${error.message}`);
  }
  return { pkg, notes };
}

/** What a folder problem means, where its code alone does not say what to change (FAA-193). */
const FOLDER_MESSAGES = {
  'provider-manifest': 'provider-manifest: the provider manifest must be a JSON object, and when it carries costPresets fabric.package.json must carry the same costPresets (copy them; pack does not)',
};

/**
 * The agent's source manifest (contract DEC-0149, `fabric-source/1`): when the folder carries one, `pack` writes
 * `secrets[]` from its secret slots and `state[]` from its store slots' paths, and FAC-SEM-160 holds them equal.
 */
export const SOURCE_FILE = 'fabric.source.json';

function sourceManifest(files) {
  if (!files.has(SOURCE_FILE)) return undefined;
  const source = parseStrict(files.get(SOURCE_FILE), SOURCE_FILE);
  if (source.format !== 'fabric-source/1') throw new PackageError(`${SOURCE_FILE} is not a fabric-source/1 manifest (its format member).`);
  return source;
}

/** `secrets[]` from the secret slots (name, purpose, optional) and `state[]` from the store slots (path, purpose). */
export function sourceMembers(source) {
  const secrets = [];
  const state = [];
  for (const slot of objects(source.slots)) {
    if (slot.kind === 'secret' && isString(slot.name)) secrets.push({ name: slot.name, purpose: slot.purpose, ...(slot.optional === true ? { optional: true } : {}) });
    else if (slot.kind === 'store' && isString(slot.path)) state.push({ path: slot.path, purpose: slot.purpose });
  }
  return { secrets, state };
}

/**
 * FAC-SEM-160 (contract `sourcePackageFindings`): the package's secrets[] are the source's secret slots, by name and
 * optional; its state[] paths are the store slots' paths when state[] holds any entry.
 */
export function sourcePackageFindings(source, pkg) {
  if (!isObject(source) || !isObject(pkg)) return [];
  const out = [];
  const flag = (instancePath, message) => out.push({ code: 'FAC-SEM-160', instancePath, message });
  const slots = objects(source.slots);
  const secrets = new Map(slots.filter((s) => s.kind === 'secret' && isString(s.name)).map((s) => [s.name, s.optional === true]));
  const stores = new Set(slots.filter((s) => s.kind === 'store' && isString(s.path)).map((s) => s.path));
  const packaged = (Array.isArray(pkg.secrets) ? pkg.secrets : []).flatMap((e, i) => (isObject(e) ? [[e, i]] : []));
  const names = new Set(packaged.map(([e]) => e.name));
  for (const name of secrets.keys()) if (!names.has(name)) flag('/package/secrets', `the source's secret slot ${name} is not in the package's secrets[]`);
  for (const [entry, index] of packaged) {
    if (!isString(entry.name) || !secrets.has(entry.name)) flag(`/package/secrets/${index}/name`, `secrets[${index}] is no secret slot of the source`);
    else if (secrets.get(entry.name) !== (entry.optional === true)) flag(`/package/secrets/${index}/optional`, `secrets[${index}] is ${secrets.get(entry.name) ? '' : 'not '}optional in the source`);
  }
  if (!Array.isArray(pkg.state) || pkg.state.length === 0) return out;
  const paths = new Set(objects(pkg.state).map((e) => e.path));
  for (const p of stores) if (!paths.has(p)) flag('/package/state', "a store slot's path of the source is not in the package's state[]");
  pkg.state.forEach((entry, index) => {
    if (isObject(entry) && (!isString(entry.path) || !stores.has(entry.path))) flag(`/package/state/${index}/path`, `state[${index}] is no store slot of the source`);
  });
  return out;
}

function sourceProblems(pkg, files) {
  if (!files.has(SOURCE_FILE)) return [];
  try {
    return sourcePackageFindings(sourceManifest(files), pkg).map((p) => ({ ...p, rule: p.code }));
  } catch (error) {
    if (!(error instanceof PackageError)) throw error;
    return [{ rule: 'source', instancePath: '/files', message: error.message }];
  }
}

function allProblems(pkg, files) {
  return [
    ...schemaProblems(pkg).map((p) => ({ ...p, rule: 'schema' })),
    ...sourceProblems(pkg, files),
    ...pathProblems(pkg).map((p) => ({ ...p, rule: 'path' })),
    ...packageFindings(pkg).map((p) => ({ ...p, rule: p.code })),
    ...checkPackageFolder(pkg, files).map((p) => ({ rule: 'folder', problem: p.problem, instancePath: p.path, message: FOLDER_MESSAGES[p.problem] ?? p.problem })),
  ];
}

/** Write through a temporary file in the same folder and rename it over, so a reader never sees half a file. */
function writeAtomic(file, text) {
  const temp = path.join(path.dirname(file), `.${path.basename(file)}.tmp-${process.pid}`);
  fs.writeFileSync(temp, text);
  fs.renameSync(temp, file);
}

/** The names a hand-written secrets[] declares that the source manifest has no secret slot for, in their order. */
function secretsLacking(draft, secrets) {
  const have = new Set(secrets.map((s) => s.name));
  const lacking = [];
  for (const entry of Array.isArray(draft.secrets) ? draft.secrets : []) {
    const name = isObject(entry) ? entry.name : undefined;
    if (isString(name) && !have.has(name) && !lacking.includes(name)) lacking.push(name);
  }
  return lacking;
}

function lackingMessage(lacking) {
  return `${SOURCE_FILE} declares no secret slot for ${lacking.join(', ')}, which ${PACKAGE_FILE}'s secrets[] names: pack writes secrets[] from the manifest's slots and never drops a declared secret. Add each as a slot of kind secret to ${SOURCE_FILE} (or take it out of secrets[]), then pack again`;
}

/** Pack `folder`; with `apply` and no problem, fabric.package.json is rewritten. */
export function pack(folder, { apply = false } = {}) {
  const files = readFolder(folder);
  if (!files.has(PACKAGE_FILE)) {
    throw new PackageError(`Write ${PACKAGE_FILE} in the folder first: schema, kind, id, version, publisher, licence and, for an agent, resultSignal and evals with its receipt. pack fills in agentRef, files[] and digest.`);
  }
  const draft = parseStrict(files.get(PACKAGE_FILE), PACKAGE_FILE);
  const source = sourceManifest(files);
  const written = [];
  const refused = [];
  if (source !== undefined) {
    // DEC-0149: secrets[] and state[] come from the source manifest's slots; an empty state[] is a copy without state.
    const members = sourceMembers(source);
    const lacking = secretsLacking(draft, members.secrets);
    if (lacking.length > 0) {
      // a declared secret is never dropped: the manifest gains its slot first
      refused.push({ rule: 'source', instancePath: '/secrets', message: lackingMessage(lacking) });
    } else if (members.secrets.length > 0 || Object.hasOwn(draft, 'secrets')) {
      Object.defineProperty(draft, 'secrets', { value: members.secrets, enumerable: true, writable: true, configurable: true });
      written.push('secrets[]');
    }
    if (members.state.length > 0 && !(Array.isArray(draft.state) && draft.state.length === 0)) {
      Object.defineProperty(draft, 'state', { value: members.state, enumerable: true, writable: true, configurable: true });
      written.push('state[]');
    }
  }
  const { pkg, notes } = compose(draft, files);
  if (written.length > 0) notes.push(`${written.join(' and ')} written from ${SOURCE_FILE}`);
  const problems = [...refused, ...allProblems(pkg, files)];
  const suite = isObject(pkg.evals) ? pkg.evals.suite : undefined;
  if (isString(suite) && files.has(suite) && problems.some((p) => p.instancePath === '/evals/receipt/suite')) notes.push(`the suite packed is ${sha256Of(files.get(suite))}: run it again and write that receipt`);
  const answer = { ok: problems.length === 0, applied: false, digest: pkg.digest, files: pkg.files.length, problems, notes };
  if (pkg.kind === 'agent' && Object.hasOwn(pkg, 'agentRef')) answer.agentRef = pkg.agentRef;
  if (apply && problems.length === 0) {
    writeAtomic(path.join(folder, PACKAGE_FILE), `${dumps(pkg)}\n`);
    answer.applied = true;
  }
  answer.package = pkg;
  return answer;
}

function packed(folder) {
  const files = readFolder(folder);
  if (!files.has(PACKAGE_FILE)) throw new PackageError(`${folder} has no ${PACKAGE_FILE}: pack it first.`);
  return { pkg: parseStrict(files.get(PACKAGE_FILE), PACKAGE_FILE), files };
}

/**
 * Refuse a key file inside the folder being signed (FAA-190 (15)): it would ship in the package. Judged by where the key
 * resolves to and by the folder's identity (device and inode), so a link to the key, a path through a linked folder and
 * a case-folding file system do not hide it. A folder or key that cannot be read is judged later. The Python twin's
 * _key_outside.
 */
function keyOutside(folder, keyFile) {
  let home;
  try { home = fs.statSync(folder, { bigint: true }); } catch { return; }
  // a file system with no inode numbers (0, as FAT on Windows) is judged by the resolved path alone
  const fold = (p) => (process.platform === 'win32' ? p.toLowerCase() : p);
  const resolved = (p) => { try { return fs.realpathSync(path.resolve(String(p))); } catch { return path.resolve(String(p)); } };
  const where = fold(resolved(folder));
  let place = resolved(keyFile);
  for (;;) {
    const parent = path.dirname(place);
    if (parent === place) return;
    place = parent;
    let here;
    try { here = fs.statSync(place, { bigint: true }); } catch { continue; }
    if ((home.ino !== 0n && here.dev === home.dev && here.ino === home.ino) || fold(place) === where) throw new PackageError(`The key file ${keyFile} is inside the folder being signed; keep it outside the package.`);
  }
}

/**
 * Add `role`'s Ed25519 signature over the packed digest. Only a package that is whole and matches its folder is signed.
 * The signature of the same role and kid is replaced; a publisher signature is always one.
 */
export function sign(folder, keyFile, { role = 'publisher', kid, apply = false } = {}) {
  if (role !== 'publisher' && role !== 'organization') throw new PackageError('role is publisher or organization.');
  keyOutside(folder, keyFile);
  const { pkg, files } = packed(folder);
  const problems = allProblems(pkg, files);
  if (problems.length) return { ok: false, applied: false, problems, notes: ['pack the folder again before it is signed'] };
  const key = readSigningKey(keyFile, kid);
  const entry = { role, alg: 'EdDSA', kid: key.kid, sig: ed25519Sign(key.seed, packageSigningInput(pkg.digest, role)).toString('base64url') };
  const kept = (Array.isArray(pkg.signatures) ? pkg.signatures : []).filter((s) => isObject(s) && !(s.role === role && (role === 'publisher' || s.kid === key.kid)));
  const signed = { ...pkg, signatures: role === 'publisher' ? [entry, ...kept] : [...kept, entry] };
  const jwk = publicJwk(key.seed, key.kid);
  if (role === 'publisher') {
    const check = verifyPackage(signed, { publisher: [jwk] });
    if (!check.ok) throw new PackageError(`The signature does not verify under its own key (${check.problem}); nothing was written.`);
  }
  const answer = { ok: true, applied: false, digest: pkg.digest, signature: entry, publicKey: jwk, problems: [], notes: [] };
  if (apply) {
    writeAtomic(path.join(folder, PACKAGE_FILE), `${dumps(signed)}\n`);
    answer.applied = true;
  }
  return answer;
}

/** The folder check, the contract's rules, then verifyPackage against the pinned `trust`. */
export function verify(folder, trust, { countersigned = false } = {}) {
  const { pkg, files } = packed(folder);
  const problems = allProblems(pkg, files);
  const verdict = verifyPackage(pkg, trust, { countersigned });
  return { ok: Boolean(verdict.ok) && problems.length === 0, verdict, problems };
}

const USAGE = `usage: fabric-package.mjs pack <folder> [--apply]
       fabric-package.mjs sign <folder> --key <file> [--kid <kid>] [--role publisher|organization] [--apply]
       fabric-package.mjs verify <folder> --trust <trust.json> [--countersigned]`;

/** The command line; returns the exit code. `print` receives each line of output. */
export function main(argv, print = (line) => process.stdout.write(`${line}\n`)) {
  const [command, folder, ...rest] = argv;
  const flags = {};
  for (let i = 0; i < rest.length; i += 1) {
    const name = rest[i];
    if (['--apply', '--dry-run', '--countersigned'].includes(name)) flags[name.slice(2)] = true;
    else if (['--key', '--kid', '--role', '--trust'].includes(name) && rest[i + 1] !== undefined) { flags[name.slice(2)] = rest[i + 1]; i += 1; } else { process.stderr.write(`${USAGE}\nunknown argument ${name}\n`); return 2; }
  }
  if (!['pack', 'sign', 'verify'].includes(command) || !folder || (flags.apply && flags['dry-run'])
    || (command === 'sign' && !flags.key) || (command === 'verify' && !flags.trust) || (flags.role && !['publisher', 'organization'].includes(flags.role))) {
    process.stderr.write(`${USAGE}\n`);
    return 2;
  }
  let answer;
  try {
    if (command === 'pack') {
      answer = pack(folder, { apply: Boolean(flags.apply) });
      if (flags.apply) delete answer.package;
    } else if (command === 'sign') {
      answer = sign(folder, flags.key, { role: flags.role ?? 'publisher', kid: flags.kid, apply: Boolean(flags.apply) });
    } else {
      let trustText;
      try { trustText = fs.readFileSync(flags.trust); } catch (error) { throw new PackageError(`Cannot read ${flags.trust}: ${error.code ?? error.message}.`); }
      answer = verify(folder, parseStrict(trustText, flags.trust), { countersigned: Boolean(flags.countersigned) });
    }
  } catch (error) {
    if (!(error instanceof PackageError)) throw error;
    print(JSON.stringify({ ok: false, error: error.message }));
    return 1;
  }
  print(dumps(answer));
  return answer.ok ? 0 : 1;
}

// Whether node was started on this file. Real paths, not URLs: the launcher installs the plugin under a symlinked
// folder (~/.passioncode/current), and comparing import.meta.url (resolved) with argv[1] (the link) never ran main
// (board thread b42e16b7).
function startedDirectly() {
  try {
    return Boolean(process.argv[1]) && fs.realpathSync(process.argv[1]) === fs.realpathSync(fileURLToPath(import.meta.url));
  } catch {
    return false;
  }
}

if (startedDirectly()) process.exitCode = main(process.argv.slice(2));
