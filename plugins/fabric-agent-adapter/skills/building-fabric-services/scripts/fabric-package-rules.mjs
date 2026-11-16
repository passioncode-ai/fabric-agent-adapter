// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
// fabric-package/1, the rule layer (contract DEC-0050, DEC-0051): the package's digest and signing statement, the
// contract's rules over a package document (FAC-SEM-064…066, FAC-SEM-102) and the path rule (FAA-78, decision D5). Every
// function answers by a rule and touches no file; fabric-package.mjs packs, signs and verifies on it and re-exports every
// public name here. Part of the Node service kit (split from fabric-package.mjs; layer L2); the twin of
// fabric_package_rules.py. Node 18+, no dependency.
import crypto from 'node:crypto';
import { jcs } from './fabric-delegation.mjs';
import { secretArgument, secretValue } from './fabric-secrets.mjs';
import { isObject, objects, isString } from './fabric-jsvalue.mjs'; // the core's (FAA-65)

export const PACKAGE_FILE = 'fabric.package.json';
export const PLUGIN_MANIFEST = '.claude-plugin/plugin.json';
export const SIGNATURE_STATEMENT = 'fabric-package-signature/1';

// --- digest, statement, identity -----------------------------------------------------------------------------------

/** urn:fabric:agent:<publisher>:<id>: one agent across its versions, derived and never chosen (FAC-SEM-066). */
export const agentRefOf = (publisher, id) => `urn:fabric:agent:${publisher}:${id}`;

/** sha256: and the hex SHA-256 of some bytes (a string is taken as UTF-8). */
export const sha256Of = (data) => `sha256:${crypto.createHash('sha256').update(data).digest('hex')}`;

/** SHA-256 over the UTF-8 RFC 8785 form of the package without digest and signatures (DEC-0050). */
export function packageDigest(pkg) {
  const { digest: _d, signatures: _s, ...covered } = pkg;
  let text;
  try {
    text = jcs(covered);
  } catch (error) {
    // Nested past the stack: no form this kit can write, as Python's RecursionError is none.
    if (error instanceof RangeError) throw new TypeError('the package nests too deeply to have an RFC 8785 form');
    throw error;
  }
  return sha256Of(Buffer.from(text, 'utf8'));
}

/** The bytes a package signature covers (DEC-0051); the role is inside, so no signature stands for another role. */
export const packageSigningInput = (digest, role) => Buffer.from(jcs({ type: SIGNATURE_STATEMENT, role, digest }), 'utf8');

// --- the contract's rules (FAC-SEM-064…066, FAC-SEM-102), ported line for line from src/package-rules.ts --------------

export const mcpRequirements = (value) => (isObject(value.requires) && Array.isArray(value.requires.mcp) ? value.requires.mcp.filter(isObject) : []);

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

// --- the path rule (FAA-78, finding 40; decision D5) -------------------------------------------------------------------

/** C0 and C1 controls, DEL, and the two Unicode line terminators JavaScript's `.` stops at. */
const control = (code) => code < 0x20 || (code >= 0x7f && code <= 0x9f) || code === 0x2028 || code === 0x2029;

/**
 * Why `p` is no packaged path, or null. The schema's pattern says the same in one expression, but JavaScript's `.`
 * stops at U+2028 and U+2029, so here and in the contract's own ajv its look-aheads never see a `..`, a backslash or a
 * `//` after one (`a\u2028/../../etc/passwd` passes there). This rule reads the path character by character in both
 * kits, and refuses C1 controls, DEL and the line terminators besides. A non-string is the schema's to refuse.
 */
export function pathProblem(p) {
  if (!isString(p)) return null;
  const chars = [...p];
  if (chars.length < 1 || chars.length > 256) return 'a path is 1 to 256 characters';
  if (chars.some((ch) => control(ch.codePointAt(0)))) return 'a path carries no control character and no line or paragraph separator';
  if (p[0] === '/' || p[0] === '~') return 'a path is relative to the package folder: it never starts with / or ~';
  if (p.includes('\\') || p.includes(':')) return 'a path is written with forward slashes and no colon';
  if (p.includes('//') || p.endsWith('/')) return 'a path names a file: no empty segment and no trailing slash';
  if (p.split('/').some((segment) => segment === '.' || segment === '..')) return 'a path never steps through . or ..';
  return null;
}

/** Every member the schema types as a path, by its JSON pointer. */
function pathFields(pkg) {
  const fields = [['/provider', pkg.provider]];
  if (isObject(pkg.evals)) fields.push(['/evals/suite', pkg.evals.suite]);
  for (const name of ['state', 'dependencies', 'files']) {
    (Array.isArray(pkg[name]) ? pkg[name] : []).forEach((entry, index) => { if (isObject(entry)) fields.push([`/${name}/${index}/path`, entry.path]); });
  }
  return fields.filter(([, value]) => value !== undefined);
}

/** The path rule over every path the package names: `{instancePath, message}` per path refused. */
export function pathProblems(pkg) {
  if (!isObject(pkg)) return [];
  const out = [];
  for (const [instancePath, value] of pathFields(pkg)) {
    const message = pathProblem(value);
    if (message !== null) out.push({ instancePath, message });
  }
  return out;
}

/** FAC-SEM-064 (whole), 065 (no secret), 066 (agentRef derived) and 102 (one role, one server), in that order. */
export const packageFindings = (pkg) => [...whole(pkg), ...noSecret(pkg), ...agentRefRule(pkg), ...mcpRoles(pkg)];
