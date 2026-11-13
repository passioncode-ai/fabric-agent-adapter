// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
// A person's identity at every door of a service published through `tailscale serve` (FAA-324). The twin of
// fabric_tailnet_identity.py; both answer test/fixtures/tailnet-identity/vectors.json alike. No dependencies beyond
// node:fs, node:net and node:perf_hooks.
//
// Serve sets the caller's `Tailscale-User-Login` (and `Tailscale-User-Name`, read here for display only) and removes
// any copies a client sent, also their `_` spellings; it sets none for a tagged node, for Funnel traffic (it sets
// `Tailscale-Funnel-Request: ?1` instead) or for traffic it cannot attribute, and it always sets `X-Forwarded-For`
// (https://tailscale.com/kb/1312/serve, "Identity headers", read 2026-11-12; tailscale/tailscale
// ipn/ipnlocal/serve.go, addTailscaleIdentityHeaders). The header is believed only when the service listens on a
// loopback address and the request's peer is a loopback address (it came through the local serve proxy); anything
// else is refused, since there the header comes from the network. Another process of this machine can still send it
// to the loopback port: the kit's loopbackServer refuses another OS account's peer (DEC-0154, FAA-227), and serve's
// own listener (fabric-tailnet.mjs, FAA-297) closes the rest.
//
// What a login may open comes from a `tailnet-groups/1` file the organization writes (its JSON Schema is
// tailnet-groups.schema.json beside this file). Logins are compared as ASCII names lowercased whole, after trimming
// the spaces and tabs HTTP allows; a non-ASCII (RFC 2047-encoded) login is refused as malformed. TailnetIdentity reads
// the file again when its inode, size, mtime or ctime change, and while it is unreadable or invalid every door refuses;
// the reason is logged once per change, naming the field, never the file's content. Every refusal is 403 with a code.

import { createHash } from 'node:crypto';
import { closeSync, fstatSync, openSync, readSync, statSync } from 'node:fs';
import { BlockList, isIP } from 'node:net';
import { performance } from 'node:perf_hooks';

export const GROUPS_SCHEMA = 'tailnet-groups/1';
export const DOOR_GROUPS = 'door-groups/1'; // the agents base's format (thread d23eeb7a), read for one service
export const DOORS = Object.freeze(['dashboard', 'mcp', 'service']);
export const LOGIN_HEADER = 'tailscale-user-login';
export const NAME_HEADER = 'tailscale-user-name';
export const FUNNEL_HEADER = 'tailscale-funnel-request';
/** The largest groups file read; a larger one is invalid. */
export const MAX_GROUPS_BYTES = 1048576;

/** The patterns as the JSON Schema writes them. */
export const LOGIN_PATTERN = '^[A-Za-z0-9._%+-]{1,128}@[A-Za-z0-9.-]{1,125}$';
export const NAME_PATTERN = '^[a-z][a-z0-9._:/-]{0,127}$';
const LOGIN = new RegExp(LOGIN_PATTERN);
const NAME = new RegExp(NAME_PATTERN);
const ENCODED_WORD = /^=\?utf-8\?q\?([^?]*)\?=$/i;

const LOOPBACK = new BlockList();
LOOPBACK.addSubnet('127.0.0.0', 8, 'ipv4');
LOOPBACK.addAddress('::1', 'ipv6');
const TAILNET = new BlockList();
TAILNET.addSubnet('100.64.0.0', 10, 'ipv4');
TAILNET.addSubnet('fd7a:115c:a1e0::', 48, 'ipv6');

/** code -> HTTP status: every refusal is 403. */
export const REFUSALS = Object.freeze(Object.fromEntries([
  'bind-not-loopback', 'not-loopback', 'groups-unreadable', 'groups-invalid', 'funnel-request', 'no-login',
  'tagged-node', 'login-ambiguous', 'login-malformed', 'unknown-login', 'not-allowed'].map((c) => [c, 403])));

/** code -> the sentence a person reads; the twins carry the same text. */
export const REASONS = Object.freeze({
  ok: 'Allowed by a rule of a group this login belongs to.',
  'bind-not-loopback': 'The service does not listen on a loopback address only, so a Tailscale identity header '
    + 'could come from the network and is not believed.',
  'not-loopback': 'The request did not come from the local tailscale serve proxy (its peer is not a loopback '
    + 'address), so its Tailscale identity header is not believed.',
  'groups-unreadable': 'The tailnet groups file cannot be read, so every door stays closed until it can.',
  'groups-invalid': 'The tailnet groups file is not a valid tailnet-groups/1 or door-groups/1 document, so every door stays closed '
    + 'until it is fixed.',
  'funnel-request': 'The request came through Tailscale Funnel from the public internet, which carries no tailnet '
    + 'identity.',
  'no-login': 'The request carries no Tailscale-User-Login header, so the caller is not known.',
  'tagged-node': 'The request came through tailscale serve from a tailnet node with no user (a tagged node), which '
    + 'carries no login.',
  'login-ambiguous': 'The request carries more than one Tailscale-User-Login header.',
  'login-malformed': 'The Tailscale-User-Login header is not a login name.',
  'unknown-login': 'This login is in no group of the tailnet groups file.',
  'not-allowed': 'No group of this login has a rule that opens this door for this capability.',
});

/** A groups file that cannot be used: `code` groups-invalid or groups-unreadable, `where` the field (or why it could
 * not be read), never a value from the file. */
export class GroupsError extends Error {
  constructor(code, where = '') {
    super(`${code}${where ? ` at ${where}` : ''}`);
    this.name = 'GroupsError';
    this.code = code;
    this.where = where;
  }
}

const invalid = (where) => new GroupsError('groups-invalid', where);
const isPlainObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const sortedUnique = (items) => [...new Set(items)].sort();

/** Check a parsed `tailnet-groups/1` document; answer it normalized or throw GroupsError groups-invalid. */
export function loadGroups(doc, { service } = {}) {
  if (!isPlainObject(doc)) throw invalid('document');
  if (Object.hasOwn(doc, 'format') && !Object.hasOwn(doc, 'schema')) {
    if (doc.format !== DOOR_GROUPS) throw invalid('format');
    return loadDoorGroups(doc, service);
  }
  if (doc.schema !== GROUPS_SCHEMA) throw invalid('schema');
  if (Object.keys(doc).some((k) => !['schema', 'about', 'groups', 'rules'].includes(k))) throw invalid('document');
  if ('about' in doc && (typeof doc.about !== 'string' || [...doc.about].length > 1000)) throw invalid('about');
  const { groups } = doc;
  if (!isPlainObject(groups) || !Object.keys(groups).every((n) => NAME.test(n))) throw invalid('groups');
  const out = {};
  for (const name of Object.keys(groups).sort()) {
    const members = groups[name];
    if (!Array.isArray(members) || !members.every((m) => typeof m === 'string' && LOGIN.test(m))) {
      throw invalid(`groups.${name}`);
    }
    out[name] = sortedUnique(members.map((m) => m.toLowerCase()));
  }
  const { rules } = doc;
  if (!Array.isArray(rules)) throw invalid('rules');
  const norm = rules.map((rule, i) => {
    const where = `rules[${i}]`;
    const keys = isPlainObject(rule) ? Object.keys(rule).sort() : [];
    if (keys.join(',') !== 'capabilities,door,group') throw invalid(where);
    if (typeof rule.group !== 'string' || !Object.hasOwn(out, rule.group)) throw invalid(`${where}.group`);
    if (!DOORS.includes(rule.door)) throw invalid(`${where}.door`);
    const caps = rule.capabilities;
    if (caps !== '*' && (!Array.isArray(caps) || !caps.length
        || !caps.every((c) => typeof c === 'string' && NAME.test(c)))) throw invalid(`${where}.capabilities`);
    return { group: rule.group, door: rule.door, capabilities: caps === '*' ? '*' : sortedUnique(caps) };
  });
  return { schema: GROUPS_SCHEMA, groups: out, rules: norm };
}

/** `door-groups/1` (the agents base): {format, version, generated_at?, groups: {name: {people, doors: {service:
 * [capability]}}}, retired?: {name: {at, why}}}. For `service`: `*` opens every door, `dashboard` the dashboard, `mcp`
 * every MCP tool, any other name that capability at the MCP door and at the service's own door; a group with no entry
 * for the service, and a retired group, open nothing. Without a service every door stays closed. */
function loadDoorGroups(doc, service) {
  if (typeof service !== 'string' || !service) throw invalid('service');
  if (Object.keys(doc).some((k) => !['format', 'version', 'generated_at', 'groups', 'retired'].includes(k))) {
    throw invalid('document');
  }
  if (!Number.isInteger(doc.version) || doc.version < 1) throw invalid('version');
  if (doc.generated_at != null && (typeof doc.generated_at !== 'string' || [...doc.generated_at].length > 64)) {
    throw invalid('generated_at');
  }
  const { groups } = doc;
  if (!isPlainObject(groups) || !Object.keys(groups).every((n) => NAME.test(n))) throw invalid('groups');
  const retired = Object.hasOwn(doc, 'retired') ? doc.retired : {};
  if (!isPlainObject(retired) || !Object.keys(retired).every((n) => NAME.test(n))) throw invalid('retired');
  for (const name of Object.keys(retired).sort()) {
    const entry = retired[name];
    if (Object.hasOwn(groups, name)) throw invalid(`retired.${name}`);
    if (!isPlainObject(entry) || Object.keys(entry).some((k) => k !== 'at' && k !== 'why')
        || !Object.values(entry).every((v) => v === null || (typeof v === 'string' && [...v].length <= 1000))) {
      throw invalid(`retired.${name}`);
    }
  }
  const people = {};
  const rules = [];
  for (const name of Object.keys(groups).sort()) {
    const group = groups[name];
    if (!isPlainObject(group) || Object.keys(group).sort().join(',') !== 'doors,people') throw invalid(`groups.${name}`);
    const members = group.people;
    if (!Array.isArray(members) || !members.every((m) => typeof m === 'string' && LOGIN.test(m))) {
      throw invalid(`groups.${name}.people`);
    }
    const { doors } = group;
    if (!isPlainObject(doors) || !Object.keys(doors).every((k) => k.length > 0)) throw invalid(`groups.${name}.doors`);
    for (const key of Object.keys(doors).sort()) {
      const caps = doors[key];
      if (!Array.isArray(caps) || !caps.length || !caps.every((c) => typeof c === 'string' && (c === '*' || NAME.test(c)))) {
        throw invalid(`groups.${name}.doors.${key}`);
      }
    }
    people[name] = sortedUnique(members.map((m) => m.toLowerCase()));
    const caps = new Set(Object.hasOwn(doors, service) ? doors[service] : []);
    const tools = sortedUnique([...caps].filter((c) => !['*', 'dashboard', 'mcp'].includes(c)));
    const opened = {
      dashboard: caps.has('*') || caps.has('dashboard') ? '*' : null,
      mcp: caps.has('*') || caps.has('mcp') ? '*' : (tools.length ? tools : null),
      service: caps.has('*') ? '*' : (tools.length ? tools : null),
    };
    for (const door of DOORS) if (opened[door]) rules.push({ group: name, door, capabilities: opened[door] });
  }
  return { schema: DOOR_GROUPS, groups: people, rules };
}

/** Every value of one header, case-insensitively: a web Headers, an object whose values may be arrays (Node's
 * headersDistinct), or [name, value] pairs. */
function values(headers, name) {
  const found = [];
  const pairs = headers == null ? []
    : typeof headers.entries === 'function' && !Array.isArray(headers) ? headers.entries()
      : Array.isArray(headers) ? headers : Object.entries(headers);
  for (const [key, value] of pairs) {
    if (typeof key === 'string' && key.toLowerCase() === name) found.push(...(Array.isArray(value) ? value : [value]));
  }
  return found.map((v) => (typeof v === 'string' ? v : ''));
}

function address(text) {
  if (typeof text !== 'string') return null;
  let host = text.split('%')[0];
  const mapped = /^::ffff:(\d{1,3}(?:\.\d{1,3}){3})$/i.exec(host);
  if (mapped) host = mapped[1];
  const family = isIP(host);
  if (!family) return null;
  if (family === 6) {
    const hex = /^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/i.exec(host);
    if (hex) {
      const [hi, lo] = [parseInt(hex[1], 16), parseInt(hex[2], 16)];
      return { host: `${hi >> 8}.${hi & 255}.${lo >> 8}.${lo & 255}`, type: 'ipv4' };
    }
  }
  return { host, type: family === 4 ? 'ipv4' : 'ipv6' };
}

const isLoopback = (text) => {
  const a = address(text);
  return a !== null && LOOPBACK.check(a.host, a.type);
};

function fromTailnet(vals) {
  if (vals.length !== 1) return false;
  const a = address(vals[0].replace(/^[ \t]+|[ \t]+$/g, ''));
  return a !== null && TAILNET.check(a.host, a.type);
}

const trim = (s) => s.replace(/^[ \t]+|[ \t]+$/g, '');

/** `Tailscale-User-Name` for display: ASCII as sent, or serve's RFC 2047 words decoded; null when absent, repeated,
 * over 256 characters or holding a control character. */
function displayName(vals) {
  if (vals.length !== 1) return null;
  let text = trim(vals[0]);
  if ([...text].some((c) => c.codePointAt(0) > 126)) return null;
  if (text.startsWith('=?')) {
    const bytes = [];
    for (const word of text.split(' ')) {
      const m = ENCODED_WORD.exec(word);
      if (!m) return null;
      const enc = m[1];
      for (let i = 0; i < enc.length;) {
        if (enc[i] === '=') {
          const pair = enc.slice(i + 1, i + 3);
          if (!/^[0-9a-fA-F]{2}$/.test(pair)) return null;
          bytes.push(parseInt(pair, 16));
          i += 3;
        } else {
          bytes.push(enc[i] === '_' ? 32 : enc.charCodeAt(i));
          i += 1;
        }
      }
    }
    try {
      text = new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(bytes));
    } catch {
      return null;
    }
  }
  const chars = [...text];
  if (!chars.length || chars.length > 256 || chars.some((c) => c.codePointAt(0) < 32 || c.codePointAt(0) === 127)) {
    return null;
  }
  return text;
}

function decision(code, door, capability, login = null, name = null, groups = []) {
  return { allowed: code === 'ok', status: code === 'ok' ? 200 : REFUSALS[code], code, reason: REASONS[code], login,
    name, groups: [...groups], door, capability };
}

/** Decide one request. `groups` is what loadGroups answered or the GroupsError that keeps every door closed;
 * `bound` the address the service listens on; `peer` the connection's remote address; `door` one of DOORS;
 * `capability` the name the service asks for. Answers {allowed, status, code, reason, login, name, groups, door,
 * capability}. A door or capability outside the rules' grammar is the service's mistake and throws TypeError. */
export function decide({ groups, bound, peer, headers, door, capability }) {
  if (!DOORS.includes(door)) throw new TypeError(`door is one of ${DOORS.join(', ')}`);
  if (typeof capability !== 'string' || !NAME.test(capability)) {
    throw new TypeError(`capability is a name matching ${NAME_PATTERN}`);
  }
  if (!isLoopback(bound)) return decision('bind-not-loopback', door, capability);
  if (!isLoopback(peer)) return decision('not-loopback', door, capability);
  if (groups instanceof GroupsError) {
    return decision(Object.hasOwn(REFUSALS, groups.code) ? groups.code : 'groups-invalid', door, capability);
  }
  if (values(headers, FUNNEL_HEADER).length) return decision('funnel-request', door, capability);
  const logins = values(headers, LOGIN_HEADER).map(trim).filter((v) => v);
  if (!logins.length) {
    return decision(fromTailnet(values(headers, 'x-forwarded-for')) ? 'tagged-node' : 'no-login', door, capability);
  }
  if (logins.length > 1) return decision('login-ambiguous', door, capability);
  if (!LOGIN.test(logins[0])) return decision('login-malformed', door, capability);
  const login = logins[0].toLowerCase();
  const name = displayName(values(headers, NAME_HEADER));
  const memberOf = Object.keys(groups.groups).filter((g) => groups.groups[g].includes(login)).sort();
  if (!memberOf.length) return decision('unknown-login', door, capability, login, name);
  const opened = groups.rules.some((r) => memberOf.includes(r.group) && r.door === door
    && (r.capabilities === '*' || r.capabilities.includes(capability)));
  return decision(opened ? 'ok' : 'not-allowed', door, capability, login, name, memberOf);
}

/** The JSON body of a refusal: {error: {code, message}}; never a header value or a login. */
export function refusalBody(d) {
  if (!d || d.allowed || !Object.hasOwn(REFUSALS, d.code)) throw new TypeError('refusalBody takes a refused decision');
  return { error: { code: d.code, message: REASONS[d.code] } };
}

/** Answer a refused decision on a node:http response: 403, JSON, no-store. */
export function sendRefusal(res, d) {
  const body = JSON.stringify(refusalBody(d));
  res.writeHead(REFUSALS[d.code], { 'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body), 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' });
  res.end(body);
}

function readBounded(path) {
  const fd = openSync(path, 'r');
  try {
    if (!fstatSync(fd).isFile()) {
      const err = new Error('not a file');
      err.code = 'EISDIR';
      throw err;
    }
    const buf = Buffer.alloc(MAX_GROUPS_BYTES + 1);
    let size = 0;
    for (;;) {
      const n = readSync(fd, buf, size, buf.length - size, null);
      if (n === 0) break;
      size += n;
      if (size === buf.length) break;
    }
    return buf.subarray(0, size);
  } finally {
    closeSync(fd);
  }
}

/** The groups file at `path`, read again when it changes, and the decision at a door. `recheckSeconds` 0 looks at the
 * file on every request (one stat), a positive value at most that often; `log` takes one line per change of the file's
 * state (default stderr); `clock` gives monotonic milliseconds (a test replaces it). */
// A file whose stat is unchanged but whose mtime is this close to now may have been rewritten within one timestamp tick
// (same size, coarse clock): its content is read and compared (git's racy-clean rule).
const RACY_NS = 2000000000n;

export class TailnetIdentity {
  constructor(path, { recheckSeconds = 0, log, clock = () => performance.now(), service } = {}) {
    if (typeof recheckSeconds !== 'number' || !(recheckSeconds >= 0)) {
      throw new TypeError('recheckSeconds is a number of seconds, 0 or more');
    }
    this.path = String(path);
    this.service = service; // the service's id: the entry a door-groups/1 file is read for
    this.recheckSeconds = recheckSeconds;
    this.log = log ?? ((line) => process.stderr.write(`${line}\n`));
    this.clock = clock;
    this.signature = undefined;
    this.groups = new GroupsError('groups-unreadable', 'not read');
    this.checked = null;
    this.logged = null;
  }

  stat() {
    try {
      const st = statSync(this.path, { bigint: true });
      if (!st.isFile()) return 'error:not-a-file';
      this.mtimeNs = st.mtimeNs;
      return [st.dev, st.ino, st.size, st.mtimeNs, st.ctimeNs].join(':');
    } catch (err) {
      return `error:${err?.code ?? 'unknown'}`;
    }
  }

  read() {
    let data;
    try {
      data = readBounded(this.path);
    } catch (err) {
      this.digest = null;
      return new GroupsError('groups-unreadable', err?.code ?? 'unknown');
    }
    this.digest = createHash('sha256').update(data).digest('hex');
    if (data.length > MAX_GROUPS_BYTES) return invalid('size');
    let text;
    try {
      text = new TextDecoder('utf-8', { fatal: true }).decode(data);
    } catch {
      return invalid('encoding');
    }
    if (text.charCodeAt(0) === 0xfeff) return invalid('json'); // Python's json refuses a byte-order mark too
    let doc;
    try {
      doc = JSON.parse(text);
    } catch {
      return invalid('json');
    }
    try {
      return loadGroups(doc, { service: this.service });
    } catch (err) {
      if (err instanceof GroupsError) return err;
      throw err;
    }
  }

  /** The groups in force: the normalized file, or the GroupsError that keeps every door closed. */
  current() {
    const now = this.clock();
    if (this.checked !== null && this.recheckSeconds && now - this.checked < this.recheckSeconds * 1000) {
      return this.groups;
    }
    this.checked = now;
    const signature = this.stat();
    if (signature === this.signature && !signature.startsWith('error:') && this.rewrittenInPlace()) {
      this.signature = undefined;
    }
    if (signature !== this.signature) {
      this.signature = signature;
      this.groups = signature.startsWith('error:')
        ? new GroupsError('groups-unreadable', signature.slice(6)) : this.read();
      this.report(signature);
    }
    return this.groups;
  }

  /** Whether a file whose stat did not change holds other bytes: asked only while its mtime is within RACY_NS of now,
   * since a rewrite of the same size within one timestamp tick leaves every stat field as it was (git's racy-clean
   * rule). */
  rewrittenInPlace() {
    const age = BigInt(Date.now()) * 1000000n - this.mtimeNs;
    if (age >= RACY_NS || age <= -RACY_NS) return false;
    try {
      return createHash('sha256').update(readBounded(this.path)).digest('hex') !== this.digest;
    } catch {
      return true; // read it again the usual way, which names the error
    }
  }

  report(signature) {
    const state = this.groups;
    let key;
    let line;
    if (state instanceof GroupsError) {
      key = `${signature}|${state.code}|${state.where}`;
      line = `fabric: tailnet groups file ${this.path}: ${state.code} (${state.where}); every door refuses until it is fixed`;
    } else {
      key = `${signature}|ok`;
      line = `fabric: tailnet groups file ${this.path} loaded: ${Object.keys(state.groups).length} groups, `
        + `${state.rules.length} rules`;
    }
    if (key !== this.logged) {
      this.logged = key;
      try { this.log(line); } catch { /* a log that fails never opens a door */ }
    }
  }

  /** decide() with the groups in force. */
  decide({ bound, peer, headers, door, capability }) {
    return decide({ groups: this.current(), bound, peer, headers, door, capability });
  }

  /** decide() for a node:http request: the address its server listens on, the connection's peer and the request's
   * headers, each value apart. Behind the kit's loopbackServer the request's own server never listened (the gate
   * did), so pass `bound: gate.address().address`; a bound address nobody can tell is refused (bind-not-loopback). */
  decideRequest(req, { door, capability, bound } = {}) {
    let listening = bound ?? null;
    if (bound === undefined) {
      try {
        listening = req?.socket?.server?.address?.()?.address ?? null;
      } catch {
        listening = null;
      }
    }
    return this.decide({ bound: listening, peer: req?.socket?.remoteAddress ?? null,
      headers: req?.headersDistinct ?? req?.headers ?? {}, door, capability });
  }
}
