#!/usr/bin/env node
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
import { fileURLToPath, pathToFileURL } from 'node:url';
import { isSmallOrderKey, jcs } from './fabric-delegation.mjs';
import { secretArgument, secretValue } from './fabric-secrets.mjs';

export const PACKAGE_FILE = 'fabric.package.json';
export const PLUGIN_MANIFEST = '.claude-plugin/plugin.json';
export const SIGNATURE_STATEMENT = 'fabric-package-signature/1';
/** DEC-0051: ES256 joins when Fabric records its decision D2; until then a verifier refuses it as unknown-algorithm. */
export const PACKAGE_ALGORITHMS = Object.freeze(['EdDSA']);
const SCHEMA_FILE = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fabric-package.schema.json');
// What pack refuses to list: version-control and cache litter, and files that are credentials by their name.
const JUNK = /^(\.git|__pycache__|\.DS_Store|.*\.pyc)$/;
const SECRET_FILE = /^(\.env(\..+)?|.*\.(pem|key|p12|pfx|jks|keystore)|id_(rsa|dsa|ecdsa|ed25519)|\.(npmrc|netrc|pypirc))$/;
const SECRET_FILE_OK = /^\.env\.(example|sample|template)$/;
const B64URL = /^[A-Za-z0-9_-]+$/;
const PKCS8_ED25519 = Buffer.from('302e020100300506032b657004220420', 'hex');
import { isObject, objects, jsonEqual } from './fabric-jsvalue.mjs'; // the core's (FAA-65)
import { isString } from './fabric-jsvalue.mjs'; // the core's (FAA-65)

/** A refusal a person can act on; the message names what to change. */
export class PackageError extends Error {}

// --- digest, statement, identity -----------------------------------------------------------------------------------

/** urn:fabric:agent:<publisher>:<id> — one agent across its versions, derived and never chosen (FAC-SEM-066). */
export const agentRefOf = (publisher, id) => `urn:fabric:agent:${publisher}:${id}`;

/** sha256: and the hex SHA-256 of some bytes (a string is taken as UTF-8). */
export const sha256Of = (data) => `sha256:${crypto.createHash('sha256').update(data).digest('hex')}`;

/** SHA-256 over the UTF-8 RFC 8785 form of the package without digest and signatures (DEC-0050). */
export function packageDigest(pkg) {
  const { digest: _d, signatures: _s, ...covered } = pkg;
  return sha256Of(Buffer.from(jcs(covered), 'utf8'));
}

/** The bytes a package signature covers (DEC-0051); the role is inside, so no signature stands for another role. */
export const packageSigningInput = (digest, role) => Buffer.from(jcs({ type: SIGNATURE_STATEMENT, role, digest }), 'utf8');

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

// --- the schema (bundled from the contract at the pin) ---------------------------------------------------------------

let schemaCache;
const schema = () => (schemaCache ??= JSON.parse(fs.readFileSync(SCHEMA_FILE, 'utf8')));


const typeOf = (v) => (v === null ? 'null' : Array.isArray(v) ? 'array' : typeof v === 'number' ? (Number.isInteger(v) ? 'integer' : 'number') : typeof v);
const DATE_TIME = /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?([Zz]|[+-](\d{2}):(\d{2}))$/;

function formatOk(format, value) {
  if (!isString(value)) return true;
  if (format === 'date-time') {
    const m = DATE_TIME.exec(value);
    if (!m) return false;
    const [y, mo, d, h, mi, s] = m.slice(1, 7).map(Number);
    const days = new Date(Date.UTC(y, mo, 0)).getUTCDate();
    if (mo < 1 || mo > 12 || d < 1 || d > days || h > 23 || mi > 59 || s > 59) return false;
    return m[8] === 'Z' || m[8] === 'z' || (Number(m[9]) < 24 && Number(m[10]) < 60);
  }
  if (format === 'uri') return /^[A-Za-z][A-Za-z0-9+.-]*:\S*$/.test(value);
  return true;
}

const pointer = (token) => String(token).replace(/~/g, '~0').replace(/\//g, '~1');
const codePoints = (s) => [...s].length; // JSON Schema counts code points, not UTF-16 units

function validate(node, value, at, out) {
  if (node === true) return;
  if (node === false) { out.push({ instancePath: at, message: 'is not allowed here' }); return; }
  if (node.$ref) {
    const target = node.$ref.replace(/^#\//, '').split('/').reduce((n, t) => n[t.replace(/~1/g, '/').replace(/~0/g, '~')], schema());
    validate(target, value, at, out);
  }
  const kind = typeOf(value);
  if (node.type !== undefined) {
    const allowed = Array.isArray(node.type) ? node.type : [node.type];
    if (!(allowed.includes(kind) || (kind === 'integer' && allowed.includes('number')))) { out.push({ instancePath: at, message: `must be ${allowed.join(' or ')}` }); return; }
  }
  if ('const' in node && !jsonEqual(node.const, value)) out.push({ instancePath: at, message: `must be ${JSON.stringify(node.const)}` });
  if (node.enum && !node.enum.some((item) => jsonEqual(item, value))) out.push({ instancePath: at, message: `must be one of ${node.enum.map((i) => JSON.stringify(i)).join(', ')}` });
  if (kind === 'string') {
    const length = codePoints(value);
    if (length < (node.minLength ?? 0)) out.push({ instancePath: at, message: `is shorter than ${node.minLength}` });
    if (node.maxLength !== undefined && length > node.maxLength) out.push({ instancePath: at, message: `is longer than ${node.maxLength}` });
    if (node.pattern !== undefined && !new RegExp(node.pattern, 'u').test(value)) out.push({ instancePath: at, message: `does not match ${node.pattern}` });
    if (node.format !== undefined && !formatOk(node.format, value)) out.push({ instancePath: at, message: `is not a ${node.format}` });
  }
  if ((kind === 'integer' || kind === 'number') && node.minimum !== undefined && value < node.minimum) out.push({ instancePath: at, message: `is below ${node.minimum}` });
  if (kind === 'array') {
    if (value.length < (node.minItems ?? 0)) out.push({ instancePath: at, message: `has fewer than ${node.minItems} items` });
    if (node.maxItems !== undefined && value.length > node.maxItems) out.push({ instancePath: at, message: `has more than ${node.maxItems} items` });
    if (node.uniqueItems && value.some((item, i) => value.slice(0, i).some((other) => jsonEqual(item, other)))) out.push({ instancePath: at, message: 'has duplicate items' });
    if (node.items !== undefined) value.forEach((item, i) => validate(node.items, item, `${at}/${i}`, out));
    if (node.contains !== undefined) {
      const matches = value.filter((item) => problemsOf(node.contains, item).length === 0).length;
      if (matches < (node.minContains ?? 1)) out.push({ instancePath: at, message: `has fewer than ${node.minContains ?? 1} matching items` });
      if (node.maxContains !== undefined && matches > node.maxContains) out.push({ instancePath: at, message: `has more than ${node.maxContains} matching items` });
    }
  }
  if (kind === 'object') {
    for (const name of node.required ?? []) if (!Object.hasOwn(value, name)) out.push({ instancePath: at, message: `must have ${name}` });
    const properties = node.properties ?? {};
    for (const [name, member] of Object.entries(value)) {
      const where = `${at}/${pointer(name)}`;
      if (Object.hasOwn(properties, name)) validate(properties[name], member, where, out);
      else if (node.additionalProperties === false) out.push({ instancePath: where, message: 'is not a member of this object' });
      else if (node.additionalProperties !== undefined) validate(node.additionalProperties, member, where, out);
      if (node.propertyNames !== undefined) validate(node.propertyNames, name, where, out);
    }
  }
  for (const sub of node.allOf ?? []) validate(sub, value, at, out);
  if (node.not !== undefined && problemsOf(node.not, value).length === 0) out.push({ instancePath: at, message: 'must not match' });
  if (node.if !== undefined) {
    const branch = problemsOf(node.if, value).length === 0 ? node.then : node.else;
    if (branch !== undefined) validate(branch, value, at, out);
  }
}

function problemsOf(node, value) {
  const out = [];
  validate(node, value, '', out);
  return out;
}

/** Where the package breaks fabric-package.schema.json (the contract's, bundled at the pin). */
export const schemaProblems = (pkg) => problemsOf(schema(), pkg);

// --- the contract's rules (FAC-SEM-064…066, FAC-SEM-102), ported line for line from src/package-rules.ts --------------

const mcpRequirements = (value) => (isObject(value.requires) && Array.isArray(value.requires.mcp) ? value.requires.mcp.filter(isObject) : []);

function whole(value) {
  const findings = [];
  const flag = (instancePath, message) => findings.push({ code: 'FAC-SEM-064', instancePath, message });
  try {
    const digest = packageDigest(value);
    if (digest !== value.digest) flag('/digest', `the digest is ${digest}: the package changed after it was packed, or was packed over another form than RFC 8785`);
  } catch {
    flag('/digest', 'the package has no RFC 8785 form, so it has no digest');
  }
  const sha = new Map();
  objects(value.files).forEach((entry, index) => {
    const p = String(entry.path);
    if (sha.has(p)) flag(`/files/${index}/path`, `${p} is listed twice`);
    if (p === PACKAGE_FILE) flag(`/files/${index}/path`, `${PACKAGE_FILE} carries the digest and is never listed in files[]`);
    sha.set(p, entry.sha256);
  });
  const named = (at, p, what) => { if (isString(p) && !sha.has(p)) flag(at, `${what} ${p} is not listed in files[], so the digest does not cover it`); };
  named('/provider', value.provider, 'the provider manifest');
  if (isObject(value.service) && Array.isArray(value.service.entry)) named('/service/entry/0', value.service.entry[0], "the service's entry");
  if (isObject(value.evals)) {
    named('/evals/suite', value.evals.suite, 'the evals suite');
    const receipt = isObject(value.evals.receipt) ? value.evals.receipt : undefined;
    if (receipt && isString(value.evals.suite) && sha.has(value.evals.suite) && receipt.suite !== sha.get(value.evals.suite)) flag('/evals/receipt/suite', 'the receipt was written for another suite than the one packed');
  }
  objects(value.dependencies).forEach((dependency, index) => {
    if (!isString(dependency.path)) return;
    named(`/dependencies/${index}/path`, dependency.path, 'the vendored dependency');
    if (sha.has(dependency.path) && sha.get(dependency.path) !== dependency.sha256) flag(`/dependencies/${index}/sha256`, `the vendored ${String(dependency.name)} is not the file packed at ${dependency.path}`);
  });
  const paths = new Set();
  objects(value.state).forEach((entry, index) => {
    if (paths.has(entry.path)) flag(`/state/${index}/path`, `state ${String(entry.path)} is declared twice`);
    paths.add(entry.path);
  });
  if (value.kind === 'skill-set' && !sha.has(PLUGIN_MANIFEST)) flag('/files', `a skill set is one Claude Code plugin folder and lists ${PLUGIN_MANIFEST}`);
  if (value.kind === 'agent' && value.provider === undefined && mcpRequirements(value).length > 0 && !sha.has(PLUGIN_MANIFEST)) flag('/files', `a consumer agent is one Claude Code plugin folder and lists ${PLUGIN_MANIFEST}`);
  return findings;
}

function noSecret(value) {
  const findings = [];
  const flag = (instancePath, message) => findings.push({ code: 'FAC-SEM-065', instancePath, message });
  const names = new Set();
  objects(value.secrets).forEach((slot, index) => {
    if (names.has(slot.name)) flag(`/secrets/${index}/name`, `secret slot ${String(slot.name)} is declared twice`);
    names.add(slot.name);
    for (const field of ['name', 'purpose']) if (isString(slot[field]) && secretValue(slot[field])) flag(`/secrets/${index}/${field}`, 'a secret slot is named, never filled: this looks like a credential');
  });
  if (isObject(value.requires) && Array.isArray(value.requires.mcp)) {
    value.requires.mcp.forEach((requirement, index) => {
      if (!isObject(requirement)) return;
      const texts = [['role', requirement.role], ['contract', requirement.contract], ...(Array.isArray(requirement.tools) ? requirement.tools.map((tool, t) => [`tools/${t}`, tool]) : [])];
      for (const [field, text] of texts) if (isString(text) && secretValue(text)) flag(`/requires/mcp/${index}/${field}`, 'a required MCP server is named by role and tools, never by a credential');
    });
  }
  if (isObject(value.service) && Array.isArray(value.service.entry)) {
    value.service.entry.forEach((arg, index) => { if (isString(arg) && secretArgument(arg)) flag(`/service/entry/${index}`, 'a launch argument never carries a credential: the secret reaches the service from its slot'); });
  }
  return findings;
}

function agentRefRule(value) {
  if (value.kind !== 'agent' || !isString(value.publisher) || !isString(value.id)) return [];
  const expected = agentRefOf(value.publisher, value.id);
  return value.agentRef === expected ? [] : [{ code: 'FAC-SEM-066', instancePath: '/agentRef', message: `the agent is ${expected}: agentRef is derived from publisher and id` }];
}

function mcpRoles(value) {
  const seen = new Set();
  const declared = new Set(objects(value.secrets).map((slot) => slot.name).filter(isString));
  const feeds = new Map();
  const findings = [];
  mcpRequirements(value).forEach((requirement, index) => {
    if (!isString(requirement.role)) return;
    if (seen.has(requirement.role)) findings.push({ code: 'FAC-SEM-102', instancePath: `/requires/mcp/${index}/role`, message: `role ${requirement.role} is required twice: one role, one server` });
    seen.add(requirement.role);
    (Array.isArray(requirement.secrets) ? requirement.secrets : []).forEach((slot, s) => {
      if (!isString(slot)) return;
      const at = `/requires/mcp/${index}/secrets/${s}`;
      if (!declared.has(slot)) findings.push({ code: 'FAC-SEM-102', instancePath: at, message: `slot ${slot} is not declared in secrets[]` });
      const other = feeds.get(slot);
      if (other !== undefined && other !== requirement.role) findings.push({ code: 'FAC-SEM-102', instancePath: at, message: `slot ${slot} already feeds role ${other}: one slot, one role` });
      feeds.set(slot, other ?? requirement.role);
    });
  });
  return findings;
}

/** FAC-SEM-064 (whole), 065 (no secret), 066 (agentRef derived) and 102 (one role, one server), in that order. */
export const packageFindings = (pkg) => [...whole(pkg), ...noSecret(pkg), ...agentRefRule(pkg), ...mcpRoles(pkg)];

// --- the folder check and the verifier -------------------------------------------------------------------------------

const parsed = (bytes) => {
  if (bytes === undefined) return undefined;
  try {
    const value = JSON.parse(Buffer.from(bytes).toString('utf8'));
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

/**
 * Every regular file under `folder` by its forward-slash path. Refuses a symlink, a special file, version-control or
 * cache litter, and a file that is a credential by its name — each named, so the person can remove it or pack a clean
 * copy.
 */
export function readFolder(folder) {
  let stat;
  try { stat = fs.statSync(folder); } catch { stat = null; }
  if (!stat?.isDirectory()) throw new PackageError(`${folder} is not a folder.`);
  const files = new Map();
  const refused = [];
  const walk = (dir, rel) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => utf16Order(a.name, b.name))) {
      const where = rel ? `${rel}/${entry.name}` : entry.name;
      const why = entry.isSymbolicLink() ? 'a symlink' : litter(entry.name) ?? (entry.isDirectory() || entry.isFile() ? null : 'not a regular file');
      if (why) { refused.push(`${where} (${why})`); continue; }
      if (entry.isDirectory()) walk(path.join(dir, entry.name), where);
      else files.set(where, fs.readFileSync(path.join(dir, entry.name)));
    }
  };
  walk(folder, '');
  if (refused.length) throw new PackageError(`Not packed: remove these or pack a clean copy: ${refused.sort().join('; ')}`);
  return files;
}

/** JSON.parse that refuses a member named twice in one object, as the Python kit's reader does. */
function parseStrict(text, what) {
  let value;
  try { value = JSON.parse(text); } catch (error) { throw new PackageError(`${what} is not JSON: ${error.message}`); }
  const stack = [];
  let i = 0;
  const skipString = () => { i += 1; let s = ''; while (text[i] !== '"') { if (text[i] === '\\') { s += text.slice(i, i + 2); i += 2; } else { s += text[i]; i += 1; } } i += 1; return JSON.parse(`"${s}"`); };
  while (i < text.length) {
    const c = text[i];
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
  for (const [key, value] of Object.entries(draft)) {
    if (key === 'files' || key === 'digest' || key === 'signatures' || (agent && key === 'agentRef')) continue;
    pkg[key] = value;
    if (agent && key === 'publisher') pkg.agentRef = agentRefOf(draft.publisher, draft.id);
  }
  if (Array.isArray(draft.signatures) && draft.signatures.length) notes.push(`dropped ${draft.signatures.length} signature(s): a repacked package is signed again`);
  pkg.files = [...files.keys()].filter((p) => p !== PACKAGE_FILE).sort(utf16Order).map((p) => ({ path: p, sha256: sha256Of(files.get(p)) }));
  pkg.digest = packageDigest(pkg);
  return { pkg, notes };
}

function allProblems(pkg, files) {
  return [
    ...schemaProblems(pkg).map((p) => ({ ...p, rule: 'schema' })),
    ...packageFindings(pkg).map((p) => ({ ...p, rule: p.code })),
    ...checkPackageFolder(pkg, files).map((p) => ({ rule: 'folder', problem: p.problem, instancePath: p.path, message: p.problem })),
  ];
}

/** Write through a temporary file in the same folder and rename it over, so a reader never sees half a file. */
function writeAtomic(file, text) {
  const temp = path.join(path.dirname(file), `.${path.basename(file)}.tmp-${process.pid}`);
  fs.writeFileSync(temp, text);
  fs.renameSync(temp, file);
}

/** Pack `folder`; with `apply` and no problem, fabric.package.json is rewritten. */
export function pack(folder, { apply = false } = {}) {
  const files = readFolder(folder);
  if (!files.has(PACKAGE_FILE)) {
    throw new PackageError(`Write ${PACKAGE_FILE} in the folder first: schema, kind, id, version, publisher, licence and, for an agent, resultSignal and evals with its receipt. pack fills in agentRef, files[] and digest.`);
  }
  const draft = parseStrict(files.get(PACKAGE_FILE).toString('utf8'), PACKAGE_FILE);
  const { pkg, notes } = compose(draft, files);
  const problems = allProblems(pkg, files);
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
  return { pkg: parseStrict(files.get(PACKAGE_FILE).toString('utf8'), PACKAGE_FILE), files };
}

/**
 * Add `role`'s Ed25519 signature over the packed digest. Only a package that is whole and matches its folder is signed.
 * The signature of the same role and kid is replaced; a publisher signature is always one.
 */
export function sign(folder, keyFile, { role = 'publisher', kid, apply = false } = {}) {
  if (role !== 'publisher' && role !== 'organization') throw new PackageError('role is publisher or organization.');
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
      try { trustText = fs.readFileSync(flags.trust, 'utf8'); } catch (error) { throw new PackageError(`Cannot read ${flags.trust}: ${error.code ?? error.message}.`); }
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

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) process.exitCode = main(process.argv.slice(2));
