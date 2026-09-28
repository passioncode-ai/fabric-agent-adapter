// Reference kit for the fabric-service/0.1 local service extension — Node.js 20+, no dependencies.
// The Node twin of fabric_service.py: same rules, same file formats, interoperable locks.
// Normative source: fabric-agent-contract docs/specification/service.md (DEC-0015).

import crypto from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';

export const PROTOCOL = 'fabric-service/0.1';
export const EXTENSION_KEY = 'https://fabric.passioncode.ai/agent-contract/extensions/service/0.1';
export const EXIT_ALREADY_RUNNING = 75;
export const LEVELS = ['info', 'notice', 'warning', 'error'];
export const STATUSES = ['starting', 'ready', 'degraded', 'stopping'];
export const EVENTS_DEFAULT_LIMIT = 50;
export const EVENTS_MAX_LIMIT = 200;
export const SESSION_COOKIE = 'fabric_session';

const ID = /^[a-z][a-z0-9-]{1,62}$/;
const INSTANCE = /^[a-z][a-z0-9-]{0,31}$/;
const KIND = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){0,5}$/;
const ORIGIN = /^http:\/\/127\.0\.0\.1:([0-9]{3,5})$/;
const CODE = /^[A-Za-z0-9_-]{16,256}$/;
const O_EXLOCK = 0x20; // BSD/macOS: open(2) takes flock(LOCK_EX); absent from fs.constants

export class ServiceError extends Error {}
export class AlreadyRunning extends ServiceError {
  constructor(holderPid, lockPath) {
    super(`Another copy is already running (${holderPid ? `process ${holderPid}` : 'another process'} holds ${lockPath}).`);
    this.holderPid = holderPid;
    this.lockPath = lockPath;
  }
}

export const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');

export function expand(p) {
  const out = p.startsWith('~/') ? path.join(os.homedir(), p.slice(2)) : p;
  if (!path.isAbsolute(out)) throw new ServiceError(`Path ${p} must be absolute or start with ~/.`);
  return out;
}

export function servicesDir() {
  if (process.env.FABRIC_SERVICES_DIR) return expand(process.env.FABRIC_SERVICES_DIR);
  const home = os.homedir();
  if (process.platform === 'darwin') return path.join(home, 'Library/Application Support/ai.passioncode.fabric/services');
  return path.join(process.env.XDG_DATA_HOME || path.join(home, '.local/share'), 'passioncode-fabric/services');
}

export function serviceDirs(id) {
  if (!ID.test(id)) throw new ServiceError(`Service id ${id} must match ${ID}.`);
  const home = os.homedir();
  if (process.platform === 'darwin') {
    return {
      data: path.join(home, 'Library/Application Support', id),
      logs: path.join(home, 'Library/Logs', id),
      cache: path.join(home, 'Library/Caches', id),
    };
  }
  return {
    data: path.join(process.env.XDG_DATA_HOME || path.join(home, '.local/share'), id),
    logs: path.join(process.env.XDG_STATE_HOME || path.join(home, '.local/state'), id, 'logs'),
    cache: path.join(process.env.XDG_CACHE_HOME || path.join(home, '.cache'), id),
  };
}

export function ensurePrivateDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
  fs.chmodSync(dir, 0o700);
  return dir;
}

export function atomicWrite(file, data, mode = 0o600) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = path.join(path.dirname(file), `.${path.basename(file)}.${process.pid}.${crypto.randomBytes(4).toString('hex')}`);
  const fd = fs.openSync(tmp, 'wx', mode);
  try {
    fs.writeSync(fd, data);
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  try {
    fs.chmodSync(tmp, mode);
    fs.renameSync(tmp, file);
  } catch (error) {
    fs.rmSync(tmp, { force: true });
    throw error;
  }
}

// --- one copy: taken BEFORE any side effect --------------------------------------

export class InstanceLock {
  constructor(dataDir) {
    this.path = path.join(dataDir, 'service.lock');
    this.fd = null;
    this.server = null;
  }

  async acquire() {
    ensurePrivateDir(path.dirname(this.path));
    if (process.platform === 'darwin') {
      const flags = fs.constants.O_RDWR | fs.constants.O_CREAT | O_EXLOCK | fs.constants.O_NONBLOCK;
      try {
        this.fd = fs.openSync(this.path, flags, 0o600);
      } catch (error) {
        if (error.code === 'EAGAIN' || error.code === 'EWOULDBLOCK') throw new AlreadyRunning(readPid(this.path), this.path);
        throw error;
      }
      fs.ftruncateSync(this.fd, 0);
      fs.writeSync(this.fd, String(process.pid));
      fs.fsyncSync(this.fd);
      return this;
    }
    // Linux: an abstract unix socket is exclusive, has no file, and dies with the process.
    const name = `\0fabric-service-${crypto.createHash('sha256').update(path.resolve(this.path)).digest('hex').slice(0, 32)}`;
    this.server = net.createServer();
    await new Promise((resolve, reject) => {
      this.server.once('error', (error) => reject(error.code === 'EADDRINUSE' ? new AlreadyRunning(readPid(this.path), this.path) : error));
      this.server.listen(name, resolve);
    });
    this.server.unref();
    atomicWrite(this.path, String(process.pid));
    return this;
  }

  release() {
    if (this.fd !== null) fs.closeSync(this.fd);
    if (this.server) this.server.close();
    this.fd = null;
    this.server = null;
  }
}

function readPid(file) {
  try {
    const text = fs.readFileSync(file, 'utf8').trim();
    return /^\d+$/.test(text) ? Number(text) : null;
  } catch {
    return null;
  }
}

export async function holdSingleInstance(dataDir) {
  try {
    return await new InstanceLock(dataDir).acquire();
  } catch (error) {
    if (!(error instanceof AlreadyRunning)) throw error;
    process.stderr.write(`${error.message}\n`);
    process.exit(EXIT_ALREADY_RUNNING);
  }
}

// --- token and network guard ------------------------------------------------------

export function ensureToken(file) {
  if (fs.existsSync(file)) return readToken(file);
  ensurePrivateDir(path.dirname(file));
  const token = crypto.randomBytes(32).toString('base64url');
  atomicWrite(file, token, 0o600);
  return token;
}

export function readToken(file) {
  const info = fs.lstatSync(file);
  if (info.isSymbolicLink()) throw new ServiceError(`Token file ${file} is a symlink; refusing it.`);
  if (typeof process.getuid === 'function' && info.uid !== process.getuid()) throw new ServiceError(`Token file ${file} belongs to another user.`);
  if (info.mode & 0o077) throw new ServiceError(`Token file ${file} is readable by others; set mode 0600.`);
  const token = fs.readFileSync(file, 'utf8').trim();
  if (token.length < 16) throw new ServiceError(`Token file ${file} holds no usable token.`);
  return token;
}

export function tokenMatches(presented, token, scheme = 'Bearer') {
  if (!presented) return false;
  let value = presented;
  if (scheme === 'Bearer') {
    if (!presented.startsWith('Bearer ')) return false;
    value = presented.slice(7);
  }
  const a = Buffer.from(value.trim());
  const b = Buffer.from(token);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

export function checkRequest(port, host, origin, secFetchSite) {
  const hosts = new Set([`127.0.0.1:${port}`, `localhost:${port}`, `[::1]:${port}`]);
  if (!hosts.has(host)) return `Host ${host} is not this service.`;
  if (origin !== undefined && origin !== null && ![...hosts].some((h) => origin === `http://${h}`)) return `Origin ${origin} is not this service.`;
  if (secFetchSite === 'cross-site') return 'Cross-site requests are refused.';
  return null;
}

// --- descriptor (installer only) -----------------------------------------------------

export const descriptorPath = (id, instance = 'default', dir = servicesDir()) => path.join(dir, `${id}.${instance}.json`);

export function readDescriptors(dir = servicesDir()) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter((n) => n.endsWith('.json')).sort().flatMap((n) => {
    try {
      return [[path.join(dir, n), JSON.parse(fs.readFileSync(path.join(dir, n), 'utf8'))]];
    } catch {
      return [];
    }
  });
}

export function validateDescriptor(d) {
  const problems = [];
  for (const key of ['protocol', 'id', 'instance', 'name', 'origin', 'auth', 'lifecycle', 'paths', 'installedAt', 'installedBy']) {
    if (!(key in d)) problems.push(`missing ${key}`);
  }
  if (problems.length) return problems;
  if (d.protocol !== PROTOCOL) problems.push(`protocol must be ${PROTOCOL}`);
  if (!ID.test(d.id)) problems.push(`id must match ${ID}`);
  if (!INSTANCE.test(d.instance)) problems.push(`instance must match ${INSTANCE}`);
  if (!ORIGIN.test(d.origin)) problems.push('origin must be http://127.0.0.1:<port>');
  if (!d.auth?.tokenFile) problems.push('auth.tokenFile is required');
  if ((d.auth?.header ?? 'Authorization') !== 'Authorization' && (d.auth?.scheme ?? 'Bearer') !== 'none') {
    problems.push('a custom auth header carries the raw token: scheme must be none');
  }
  if (!['launchd', 'none'].includes(d.lifecycle?.manager)) problems.push('lifecycle.manager must be launchd or none');
  if (d.lifecycle?.manager === 'launchd' && !(d.lifecycle.label && String(d.lifecycle.plist ?? '').endsWith('.plist'))) {
    problems.push('a launchd service declares label and plist');
  }
  for (const [name, argv] of Object.entries(d.commands ?? {})) {
    if (!['doctor', 'update'].includes(name)) problems.push(`unknown command ${name}`);
    else if (!Array.isArray(argv) || !argv.length || !argv.every((a) => typeof a === 'string')) problems.push(`command ${name} must be an argument array`);
    else if (!/^(~\/|\/)/.test(argv[0])) problems.push(`command ${name} must start with an absolute or ~/ executable`);
  }
  return problems;
}

export function portOf(origin) {
  const m = ORIGIN.exec(origin);
  if (!m) throw new ServiceError(`Origin ${origin} is not http://127.0.0.1:<port>.`);
  return Number(m[1]);
}

export function writeDescriptor(d, dir = servicesDir()) {
  const problems = validateDescriptor(d);
  if (problems.length) throw new ServiceError(`Descriptor is invalid: ${problems.join('; ')}.`);
  const me = `${d.id}.${d.instance}`;
  const port = portOf(d.origin);
  for (const [file, other] of readDescriptors(dir)) {
    const key = `${other.id}.${other.instance ?? 'default'}`;
    if (key === me) continue;
    let otherPort = null;
    try { otherPort = portOf(String(other.origin ?? '')); } catch { continue; }
    if (otherPort === port) throw new ServiceError(`Port ${port} is already claimed by ${key} (${file}).`);
  }
  ensurePrivateDir(dir);
  const target = descriptorPath(d.id, d.instance, dir);
  atomicWrite(target, `${JSON.stringify(d, null, 2)}\n`, 0o600);
  return target;
}

export function removeDescriptor(id, instance = 'default', dir = servicesDir()) {
  try { fs.unlinkSync(descriptorPath(id, instance, dir)); return true; } catch (e) { if (e.code === 'ENOENT') return false; throw e; }
}

// --- well-known and events ------------------------------------------------------------

export function buildWellKnown({ id, instance, name, version, build, startedAt, status, degraded = [], surfaces, summary, updateAvailable = null, pid = process.pid }) {
  if (!STATUSES.includes(status)) throw new ServiceError(`status must be one of ${STATUSES.join(', ')}.`);
  if (!surfaces?.events) throw new ServiceError('surfaces.events is required.');
  if (!(build?.commit || build?.digest)) throw new ServiceError('build needs a commit or a digest.');
  const doc = {
    protocol: PROTOCOL,
    service: { id, instance, name, version, build },
    process: { pid, startedAt },
    status: status === 'ready' && degraded.length ? 'degraded' : status,
    degraded: [...degraded],
    surfaces,
    update: { available: updateAvailable },
  };
  if (summary?.length) doc.summary = summary.slice(0, 6);
  return doc;
}

export function makeEvent(id, at, kind, level, text, { subject, link, notify } = {}) {
  if (!LEVELS.includes(level)) throw new ServiceError(`level must be one of ${LEVELS.join(', ')}.`);
  if (!KIND.test(kind)) throw new ServiceError(`kind ${kind} must be dotted lowercase.`);
  const sentence = String(text).split(/\s+/).filter(Boolean).join(' ');
  if (!sentence) throw new ServiceError('An event needs a sentence.');
  if (link !== undefined && (!link.startsWith('/') || link.startsWith('//'))) throw new ServiceError('link must be a path on this service.');
  const event = { id: String(id), at, kind, level, text: sentence.slice(0, 500) };
  if (subject) event.subject = subject;
  if (link) event.link = link;
  if (notify) event.notify = true;
  return event;
}

export function parseLimit(raw) {
  if (raw === undefined || raw === null || raw === '') return EVENTS_DEFAULT_LIMIT;
  const n = Number(raw);
  if (!Number.isInteger(n)) throw new ServiceError('limit must be an integer.');
  return Math.max(1, Math.min(EVENTS_MAX_LIMIT, n));
}

// fetch(after, limit) returns events with ids greater than `after`, ascending
// (or the newest `limit`, ascending, when after is null) — a view over the log you already keep.
export async function eventsPage(fetch, after, limit) {
  const events = (await fetch(after ?? null, limit)).slice(0, limit);
  return { events, cursor: events.length ? events.at(-1).id : (after ?? null) };
}

// --- operator login -------------------------------------------------------------------

export class LoginCodes {
  constructor(stateDir, ttlSeconds = 120) {
    this.dir = ensurePrivateDir(stateDir);
    this.ttl = Math.min(ttlSeconds, 120);
    this.keyPath = path.join(this.dir, 'session.key');
    this.codesPath = path.join(this.dir, 'login-codes.json');
  }

  key() {
    if (!fs.existsSync(this.keyPath)) atomicWrite(this.keyPath, crypto.randomBytes(32), 0o600);
    return fs.readFileSync(this.keyPath);
  }

  load() {
    try { return JSON.parse(fs.readFileSync(this.codesPath, 'utf8')); } catch { return {}; }
  }

  save(codes) {
    const horizon = Date.now() / 1000 - 3600;
    const kept = Object.fromEntries(Object.entries(codes).filter(([, v]) => (v.expires ?? 0) > horizon));
    atomicWrite(this.codesPath, JSON.stringify(kept), 0o600);
  }

  issue() {
    const code = crypto.randomBytes(24).toString('base64url');
    const expires = Date.now() / 1000 + this.ttl;
    const codes = this.load();
    codes[crypto.createHash('sha256').update(code).digest('hex')] = { expires, used: false };
    this.save(codes);
    return { url: `/fabric/v1/login?code=${code}`, expiresAt: new Date(expires * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z') };
  }

  // The code is recorded as used BEFORE it is honoured, and burned even when expired.
  redeem(code) {
    if (!code || !CODE.test(code)) return null;
    const digest = crypto.createHash('sha256').update(code).digest('hex');
    const codes = this.load();
    const entry = codes[digest];
    if (!entry || entry.used) return null;
    entry.used = true;
    this.save(codes);
    if (entry.expires < Date.now() / 1000) return null;
    const session = crypto.randomBytes(18).toString('base64url');
    return `${session}.${crypto.createHmac('sha256', this.key()).update(session).digest('hex')}`;
  }

  sessionValid(value) {
    if (!value || !value.includes('.')) return false;
    const i = value.lastIndexOf('.');
    const expected = crypto.createHmac('sha256', this.key()).update(value.slice(0, i)).digest('hex');
    const mac = value.slice(i + 1);
    return mac.length === expected.length && crypto.timingSafeEqual(Buffer.from(mac), Buffer.from(expected));
  }

  revokeAll() {
    atomicWrite(this.keyPath, crypto.randomBytes(32), 0o600);
  }
}

export const sessionCookieHeader = (value, maxAge = 30 * 86400) => `${SESSION_COOKIE}=${value}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${maxAge}`;

export function cookieValue(header, name = SESSION_COOKIE) {
  for (const part of String(header ?? '').split(';')) {
    const [k, ...rest] = part.trim().split('=');
    if (k === name) return rest.join('=');
  }
  return null;
}
