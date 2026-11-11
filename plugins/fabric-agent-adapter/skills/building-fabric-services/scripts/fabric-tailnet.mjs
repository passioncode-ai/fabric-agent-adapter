// Who is calling an agent that sits behind `tailscale serve`, and what that person may open (FAA-297). The twin of
// fabric_tailnet.py; both answer test/fixtures/tailnet/vectors.json alike. No dependencies beyond node:crypto and
// node:net.
//
// The header `Tailscale-User-Login` is believed only on the agent's own serve listener (a loopback port or a Unix
// socket that only serve reaches) and only from a loopback peer; on any other listener a request carrying it is
// refused. What a person may open comes from a `tailnet-perimeter/1` file generated from the organization's access
// registry (it names its source in `generatedFrom`); MCP also takes a personal key, stored as its SHA-256, owned by one
// login and no wider than that login's groups. Refusals are 401 or 403 with a stable `code`.

import { createHash, timingSafeEqual } from 'node:crypto';
import { isIP } from 'node:net';

export const PERIMETER_SCHEMA = 'tailnet-perimeter/1';
export const IDENTITY_HEADER = 'tailscale-user-login';
export const SERVE_HEADERS = Object.freeze(['tailscale-user-login', 'tailscale-user-name', 'tailscale-user-profile-pic']);
export const LISTENER_SERVE = 'serve';
export const SURFACES = Object.freeze(['dashboard', 'mcp']);

const LOGIN = /^[A-Za-z0-9._%+-]{1,128}@[A-Za-z0-9.-]{1,125}$/;
const NAME = /^[a-z][a-z0-9._:/-]{0,127}$/;
const KEY_HASH = /^sha256:[0-9a-f]{64}$/;
const KEY_ID = /^[A-Za-z0-9._-]{1,64}$/;

export const REFUSALS = Object.freeze({
  'serve-header-off-serve': 403,
  'peer-not-loopback': 403,
  'identity-missing': 401,
  'identity-ambiguous': 401,
  'identity-malformed': 401,
  'not-in-perimeter': 403,
  'dashboard-not-granted': 403,
  'capability-not-granted': 403,
  'key-required': 401,
  'key-unknown': 401,
  'key-not-yours': 403,
  'key-wider-than-group': 403,
});

/** A perimeter or key list that cannot be used: `code` names why, `where` the place, never a value. */
export class PerimeterError extends Error {
  constructor(code, where = '') {
    super(`${code}${where ? ` at ${where}` : ''}`);
    this.name = 'PerimeterError';
    this.code = code;
    this.where = where;
  }
}

/** The stored form of a personal key: `sha256:<hex>` of its UTF-8 bytes. */
export function hashKey(value) {
  if (typeof value !== 'string' || !value) throw new TypeError('a key is a non-empty string');
  return `sha256:${createHash('sha256').update(value, 'utf8').digest('hex')}`;
}

const sortedSet = (values) => [...new Set(values)].sort();
const isRecordValue = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const pyKeySort = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

function names(value, where) {
  if (!Array.isArray(value) || !value.every((v) => typeof v === 'string' && NAME.test(v))) {
    throw new PerimeterError('perimeter-invalid', where);
  }
  return sortedSet(value);
}

/** Check a parsed `tailnet-perimeter/1` document and answer its normalized form; throw PerimeterError otherwise. */
export function loadPerimeter(doc) {
  if (!isRecordValue(doc) || doc.schema !== PERIMETER_SCHEMA) throw new PerimeterError('perimeter-schema', 'schema');
  const source = doc.generatedFrom;
  if (!isRecordValue(source) || !['registry', 'revision', 'at'].every((k) => typeof source[k] === 'string' && source[k])) {
    throw new PerimeterError('perimeter-not-generated', 'generatedFrom');
  }
  const groups = doc.groups;
  if (!isRecordValue(groups) || Object.keys(groups).length === 0) throw new PerimeterError('perimeter-invalid', 'groups');
  const out = {};
  for (const name of Object.keys(groups).sort(pyKeySort)) {
    const group = groups[name];
    const where = NAME.test(name) ? `groups.${name}` : 'groups';
    if (!NAME.test(name) || !isRecordValue(group)) throw new PerimeterError('perimeter-invalid', where);
    const members = group.members;
    if (!Array.isArray(members) || !members.every((m) => typeof m === 'string' && LOGIN.test(m))) {
      throw new PerimeterError('perimeter-invalid', `${where}.members`);
    }
    out[name] = {
      members: sortedSet(members.map((m) => m.toLowerCase())),
      dashboards: names(group.dashboards ?? [], `${where}.dashboards`),
      capabilities: names(group.capabilities ?? [], `${where}.capabilities`),
    };
  }
  return {
    schema: PERIMETER_SCHEMA,
    generatedFrom: { registry: source.registry, revision: source.revision, at: source.at },
    groups: out,
  };
}

/** Check a list of personal keys `{id, login, sha256, capabilities}` (the hash only, never the key). */
export function loadKeys(keys) {
  if (!Array.isArray(keys)) throw new PerimeterError('keys-invalid', 'keys');
  const out = [];
  const seen = new Set();
  keys.forEach((key, i) => {
    const where = `keys[${i}]`;
    if (!isRecordValue(key) || typeof key.id !== 'string' || !KEY_ID.test(key.id)
        || typeof key.login !== 'string' || !LOGIN.test(key.login)
        || typeof key.sha256 !== 'string' || !KEY_HASH.test(key.sha256)) {
      throw new PerimeterError('keys-invalid', where);
    }
    if (seen.has(key.id) || out.some((k) => k.sha256 === key.sha256)) throw new PerimeterError('keys-duplicate', where);
    seen.add(key.id);
    out.push({ id: key.id, login: key.login.toLowerCase(), sha256: key.sha256,
      capabilities: names(key.capabilities ?? [], `${where}.capabilities`) });
  });
  return out;
}

function headerValues(headers, name) {
  // A list of pairs, a Map or a fetch Headers (anything with entries()), or a plain object such as Node's req.headers.
  const plain = headers === null || headers === undefined || Object.getPrototypeOf(headers) === Object.prototype
    || Object.getPrototypeOf(headers) === null;
  const pairs = Array.isArray(headers) ? headers
    : !plain && typeof headers.entries === 'function' ? [...headers.entries()]
      : Object.entries(headers ?? {});
  const found = [];
  for (const [key, value] of pairs) {
    if (typeof key === 'string' && key.toLowerCase() === name) found.push(...(Array.isArray(value) ? value : [value]));
  }
  return found.map((v) => (typeof v === 'string' ? v : ''));
}

function isLoopback(address) {
  if (address === 'unix') return true;
  if (typeof address !== 'string') return false;
  const ip = address.split('%', 1)[0];
  const family = isIP(ip);
  if (family === 4) return ip.split('.')[0] === '127';
  if (family !== 6) return false;
  const host = new URL(`http://[${ip}]/`).hostname; // the canonical compressed form: [::1], [::ffff:7f00:1]
  return host === '[::1]' || /^\[::ffff:7f[0-9a-f]{2}:[0-9a-f]{1,4}\]$/.test(host);
}

const refuse = (code, login = null, groups = []) => ({ allowed: false, status: REFUSALS[code], code, login, groups });

function bearer(headers) {
  const values = headerValues(headers, 'authorization');
  if (values.length !== 1) return null;
  const text = values[0].trim();
  const space = text.indexOf(' ');
  if (space < 0) return null;
  const scheme = text.slice(0, space);
  const rest = text.slice(space + 1).trim();
  return scheme.toLowerCase() === 'bearer' && rest && !rest.includes(' ') ? rest : null;
}

function sameDigest(a, b) {
  const x = Buffer.from(a, 'utf8');
  const y = Buffer.from(b, 'utf8');
  return x.length === y.length && timingSafeEqual(x, y);
}

/**
 * Decide one request. `listener` is which of the agent's listeners took it (`serve` for serve's own); `peer` the
 * connecting address (`unix` for a Unix socket); `perimeter` and `keys` as loadPerimeter and loadKeys answer;
 * `surface` `dashboard` or `mcp`; `target` the dashboard's or the capability's name. Answers
 * {allowed, status, code, login, groups}: status 200 with code `ok`, else 401 or 403 with the refusal's code.
 */
export function authorize({ listener, peer, headers, perimeter, surface, target, keys = null }) {
  if (!SURFACES.includes(surface)) throw new TypeError(`surface is one of ${SURFACES.join(', ')}`);
  if (listener !== LISTENER_SERVE) {
    if (SERVE_HEADERS.some((h) => headerValues(headers, h).length)) return refuse('serve-header-off-serve');
    throw new TypeError("authorize decides serve's listener; the Fabric listener keeps its session key");
  }
  if (!isLoopback(peer)) return refuse('peer-not-loopback');
  const logins = headerValues(headers, IDENTITY_HEADER);
  if (logins.length === 0) return refuse('identity-missing');
  if (logins.length > 1) return refuse('identity-ambiguous');
  let login = logins[0].trim();
  if (!LOGIN.test(login)) return refuse('identity-malformed');
  login = login.toLowerCase();
  const groups = Object.keys(perimeter.groups).filter((n) => perimeter.groups[n].members.includes(login)).sort(pyKeySort);
  if (groups.length === 0) return refuse('not-in-perimeter', login);
  const dashboards = new Set(groups.flatMap((n) => perimeter.groups[n].dashboards));
  const capabilities = new Set(groups.flatMap((n) => perimeter.groups[n].capabilities));
  if (surface === 'dashboard') {
    if (!dashboards.has(target)) return refuse('dashboard-not-granted', login, groups);
    return { allowed: true, status: 200, code: 'ok', login, groups };
  }
  const presented = bearer(headers);
  if (presented === null) return refuse('key-required', login, groups);
  const digest = hashKey(presented);
  const key = (keys ?? []).find((k) => sameDigest(k.sha256, digest));
  if (!key) return refuse('key-unknown', login, groups);
  if (key.login !== login) return refuse('key-not-yours', login, groups);
  if (!key.capabilities.every((c) => capabilities.has(c))) return refuse('key-wider-than-group', login, groups);
  if (!key.capabilities.includes(target)) return refuse('capability-not-granted', login, groups);
  return { allowed: true, status: 200, code: 'ok', login, groups, key: key.id };
}
