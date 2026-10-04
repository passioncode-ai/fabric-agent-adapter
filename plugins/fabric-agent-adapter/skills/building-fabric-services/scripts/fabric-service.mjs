// Reference kit for the fabric-service/0.1 local service extension — Node.js 20+, no dependencies.
// The Node twin of fabric_service.py: same rules, same file formats, interoperable locks.
// Normative source: fabric-agent-contract docs/specification/service.md (DEC-0015; the remote
// placement — an online agent or dashboard at an https origin — DEC-0019; the usage report DEC-0021).

import crypto from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';

export const PROTOCOL = 'fabric-service/0.1';
export const EXTENSION_KEY = 'https://fabric.passioncode.ai/agent-contract/extensions/service/0.1';
export const EXIT_ALREADY_RUNNING = 75;
// Lifecycle contract (fabric-workspace knowledge/lifecycle.md), the same values as fabric_service.py.
// A launchd-supervised copy that finds the lock held backs off in-process before its exit 75 (LC-03).
export const SUPERVISOR_ENV = 'FABRIC_SERVICE_SUPERVISOR';
export const LOCK_WAIT_SUPERVISED_SECONDS = 300;
export const LOCK_BACKOFF_FIRST_SECONDS = 0.5;
export const LOCK_BACKOFF_MAX_SECONDS = 30;
// LC-01: SIGTERM reaches exit in at most 10 s with work in flight — drain 8 s, hard exit 2 s later.
export const DRAIN_SECONDS = 8;
export const DRAIN_GRACE_SECONDS = 2;
export const EXIT_HARD_STOP = 70;
// LC-12: logs rotate by size, 5 x 5 MB by default.
export const LOG_MAX_BYTES = 5 * 1024 * 1024;
export const LOG_BACKUPS = 5;
export const LEVELS = ['info', 'notice', 'warning', 'error'];
export const STATUSES = ['starting', 'ready', 'degraded', 'stopping'];
export const EVENTS_DEFAULT_LIMIT = 50;
export const EVENTS_MAX_LIMIT = 200;
export const SESSION_COOKIE = 'fabric_session';
// DEC-0019: a remote placement's cookie is host-bound and HTTPS-only.
export const REMOTE_SESSION_COOKIE = '__Host-fabric_session';
export const PLACEMENTS = ['local', 'remote'];

const ID = /^[a-z][a-z0-9-]{1,62}$/;
const INSTANCE = /^[a-z][a-z0-9-]{0,31}$/;
const KIND = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){0,5}$/;
const ORIGIN = /^http:\/\/127\.0\.0\.1:([0-9]{3,5})$/;
const REMOTE_ORIGIN = /^https:\/\/((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63})(?::([0-9]{1,5}))?$/;
const RESERVED_HOST = /(^|\.)(localhost|local|internal|home\.arpa|lan|localdomain)$/;
const CODE = /^[A-Za-z0-9_-]{16,256}$/;
const TRACE_ID = /^(?!0{32}$)[0-9a-f]{32}$/;
const SPAN_ID = /^(?!0{16}$)[0-9a-f]{16}$/;
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

/** True when launchd started this process from a plist that says so (FABRIC_SERVICE_SUPERVISOR=launchd). */
export const supervisedByLaunchd = () => process.env[SUPERVISOR_ENV] === 'launchd';

const sleepSeconds = (s) => new Promise((resolve) => setTimeout(resolve, s * 1000));

/**
 * Take the lock or exit 75 with one sentence naming the holder. Started by hand, a held lock exits
 * 75 at once. Under launchd (KeepAlive) an immediate exit is a respawn every ThrottleInterval,
 * forever; so a supervised copy first backs off in-process (0.5 s doubling to 30 s,
 * LOCK_WAIT_SUPERVISED_SECONDS in all), takes over if the holder leaves, and exits 75 only when
 * the wait runs out. `waitSeconds` overrides the choice (0 = never wait).
 */
export async function holdSingleInstance(dataDir, {
  waitSeconds, sleep = sleepSeconds, clock = () => performance.now() / 1000, exit = (code) => process.exit(code),
} = {}) {
  const wait = waitSeconds ?? (supervisedByLaunchd() ? LOCK_WAIT_SUPERVISED_SECONDS : 0);
  const deadline = clock() + Math.max(0, wait);
  let delay = LOCK_BACKOFF_FIRST_SECONDS;
  let announced = false;
  for (;;) {
    try {
      return await new InstanceLock(dataDir).acquire();
    } catch (error) {
      if (!(error instanceof AlreadyRunning)) throw error;
      const remaining = deadline - clock();
      if (remaining <= 0) {
        process.stderr.write(`${error.message}\n`);
        return exit(EXIT_ALREADY_RUNNING);
      }
      if (!announced) {
        process.stderr.write(`${error.message} Waiting up to ${Math.round(remaining)} s for it to exit.\n`);
        announced = true;
      }
      await sleep(Math.min(delay, remaining));
      delay = Math.min(delay * 2, LOCK_BACKOFF_MAX_SECONDS);
    }
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
  const remote = placementOf(d) === 'remote';
  if (d.placement !== undefined && !PLACEMENTS.includes(d.placement)) problems.push('placement must be local or remote');
  const required = ['protocol', 'id', 'instance', 'name', 'origin', 'auth', 'lifecycle', 'installedAt', 'installedBy'];
  for (const key of remote ? required : [...required, 'paths']) {
    if (!(key in d)) problems.push(`missing ${key}`);
  }
  if (problems.length) return problems;
  if (d.protocol !== PROTOCOL) problems.push(`protocol must be ${PROTOCOL}`);
  if (!ID.test(d.id)) problems.push(`id must match ${ID}`);
  if (!INSTANCE.test(d.instance)) problems.push(`instance must match ${INSTANCE}`);
  if (remote) problems.push(...remoteOriginProblems(d.origin));
  else if (!ORIGIN.test(d.origin)) problems.push('origin must be http://127.0.0.1:<port>');
  if (!d.auth?.tokenFile) problems.push('auth.tokenFile is required');
  if ((d.auth?.header ?? 'Authorization') !== 'Authorization' && (d.auth?.scheme ?? 'Bearer') !== 'none') {
    problems.push('a custom auth header carries the raw token: scheme must be none');
  }
  if (!['launchd', 'none'].includes(d.lifecycle?.manager)) problems.push('lifecycle.manager must be launchd or none');
  if (d.lifecycle?.manager === 'launchd' && !(d.lifecycle.label && String(d.lifecycle.plist ?? '').endsWith('.plist'))) {
    problems.push('a launchd service declares label and plist');
  }
  if (remote) {
    if (d.lifecycle?.manager !== 'none') problems.push('a remote service is supervised by its platform: lifecycle.manager must be none');
    for (const field of ['label', 'plist']) if (d.lifecycle?.[field] !== undefined) problems.push(`a remote service has no launchd ${field}`);
    if (d.commands?.update !== undefined) problems.push('a remote service declares no update command');
  }
  for (const [name, argv] of Object.entries(d.commands ?? {})) {
    if (!['doctor', 'update'].includes(name)) problems.push(`unknown command ${name}`);
    else if (!Array.isArray(argv) || !argv.length || !argv.every((a) => typeof a === 'string')) problems.push(`command ${name} must be an argument array`);
    else if (!/^(~\/|\/)/.test(argv[0])) problems.push(`command ${name} must start with an absolute or ~/ executable`);
  }
  return problems;
}

/** DEC-0019: `local` unless the descriptor says `remote`. */
export function placementOf(d) {
  return d?.placement === 'remote' ? 'remote' : 'local';
}

/** Problems with a remote origin: https, a public DNS name, an optional port, nothing else. */
export function remoteOriginProblems(origin) {
  const m = REMOTE_ORIGIN.exec(String(origin ?? ''));
  if (!m) return ['a remote origin must be https://<dns-name>[:<port>] with no path, query or IP literal'];
  if (RESERVED_HOST.test(m[1])) return [`a remote service cannot live on the reserved name ${m[1]}`];
  if (m[2] !== undefined && (Number(m[2]) < 1 || Number(m[2]) > 65535)) return ['the origin port is out of range'];
  return [];
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
  // DEC-0019: only a local placement claims a port on this computer.
  const port = placementOf(d) === 'remote' ? null : portOf(d.origin);
  for (const [file, other] of readDescriptors(dir)) {
    const key = `${other.id}.${other.instance ?? 'default'}`;
    if (key === me) continue;
    if (port === null) continue; // a remote origin's port is another computer's
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

// An event about traced work carries traceId and spanId together (fabric-interop/0.1 C3.4 c);
// traceIds(traceparent) in fabric-interop.mjs gives both.
export function makeEvent(id, at, kind, level, text, { subject, link, notify, traceId, spanId } = {}) {
  if (!LEVELS.includes(level)) throw new ServiceError(`level must be one of ${LEVELS.join(', ')}.`);
  if (!KIND.test(kind)) throw new ServiceError(`kind ${kind} must be dotted lowercase.`);
  const sentence = String(text).split(/\s+/).filter(Boolean).join(' ');
  if (!sentence) throw new ServiceError('An event needs a sentence.');
  if (link !== undefined && (!link.startsWith('/') || link.startsWith('//'))) throw new ServiceError('link must be a path on this service.');
  if ((traceId === undefined) !== (spanId === undefined)) throw new ServiceError('An event carries traceId and spanId together, or neither.');
  if (traceId !== undefined && !(TRACE_ID.test(traceId) && SPAN_ID.test(spanId))) throw new ServiceError('traceId is 32 and spanId 16 lowercase hex characters, not all zeros.');
  const event = { id: String(id), at, kind, level, text: sentence.slice(0, 500) };
  if (subject) event.subject = subject;
  if (link) event.link = link;
  if (notify) event.notify = true;
  if (traceId !== undefined) Object.assign(event, { traceId, spanId });
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

// --- usage report (DEC-0021) -------------------------------------------------------------

export const USAGE_PATH = '/fabric/v1/usage';
export const USAGE_DAYS = 31;
export const COST_BASES = ['provider', 'price-list', 'unknown'];
const PROVIDER = /^[a-z][a-z0-9._-]{0,63}$/;
const COUNTS = ['inputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens'];

/**
 * One model call, from the provider's own usage numbers. No prompt, output or caller.
 * `costUsd` null means it cannot be priced: the report counts it as unpriced, never as $0.
 */
export function makeUsageReceipt(provider, model, { inputTokens, outputTokens, cacheReadTokens = 0, cacheWriteTokens = 0, costUsd = null, costBasis, at } = {}) {
  if (!PROVIDER.test(provider ?? '')) throw new ServiceError('provider must be a lowercase name such as anthropic or openrouter.');
  model = String(model ?? '').trim();
  if (!model || model.length > 128) throw new ServiceError('model must be 1 to 128 characters.');
  const counts = { inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens };
  for (const [name, value] of Object.entries(counts)) if (!Number.isInteger(value) || value < 0) throw new ServiceError(`${name} must be a non-negative integer.`);
  if (costUsd !== null && (typeof costUsd !== 'number' || !Number.isFinite(costUsd) || costUsd < 0)) throw new ServiceError('costUsd must be a non-negative number or null.');
  const basis = costBasis ?? (costUsd === null ? 'unknown' : 'provider');
  if (!COST_BASES.includes(basis) || (costUsd === null) !== (basis === 'unknown')) throw new ServiceError('costBasis is provider or price-list with a cost, unknown without one.');
  return { at: at ?? nowIso(), provider, model, ...counts, costUsd, costBasis: basis };
}

const utcDate = (ms) => new Date(ms).toISOString().slice(0, 10);
const emptyRow = (extra = {}) => ({ ...extra, calls: 0, unpricedCalls: 0, inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0, cost: 0 });
function closeRow(row) {
  const { cost, ...rest } = row;
  return { ...rest, costUsd: rest.calls && rest.unpricedCalls === rest.calls ? null : Math.round(cost * 1e6) / 1e6 };
}

/**
 * The service-usage.schema.json answer: the last 31 UTC days, oldest first, per provider and
 * model; days without calls are omitted. A row whose calls are all unpriced costs null; totals
 * are the sums of the model rows (FAC-SEM-025).
 */
export function usageReport(receipts, { id, instance = 'default', now = Date.now(), budget } = {}) {
  const first = utcDate(now - (USAGE_DAYS - 1) * 86_400_000), last = utcDate(now);
  const days = new Map();
  for (const r of receipts) {
    const date = String(r.at ?? '').slice(0, 10);
    if (date < first || date > last) continue;
    const rows = days.get(date) ?? new Map();
    days.set(date, rows);
    const k = `${r.provider}\u0000${r.model}`;
    const row = rows.get(k) ?? emptyRow({ provider: r.provider, model: r.model, bases: new Set() });
    rows.set(k, row);
    row.calls += 1;
    for (const c of COUNTS) row[c] += Number(r[c] ?? 0);
    if (r.costUsd === null || r.costUsd === undefined) row.unpricedCalls += 1; else row.cost += r.costUsd;
    row.bases.add(r.costBasis ?? 'unknown');
  }
  const outDays = [...days.keys()].sort().map((date) => {
    const models = [...days.get(date).values()]
      .map(({ bases, ...row }) => closeRow({ ...row, costBasis: bases.size === 1 ? [...bases][0] : 'mixed' }))
      .sort((a, b) => (a.provider + a.model < b.provider + b.model ? -1 : 1));
    const day = emptyRow({ date });
    for (const m of models) {
      for (const c of ['calls', 'unpricedCalls', ...COUNTS]) day[c] += m[c];
      day.cost += m.costUsd ?? 0;
    }
    return { ...closeRow(day), byModel: models };
  });
  const report = { protocol: PROTOCOL, service: { id, instance }, generatedAt: new Date(now).toISOString().replace(/\.\d{3}Z$/, 'Z'), currency: 'USD', days: outDays };
  if (budget !== undefined) {
    if (!['day', 'month'].includes(budget?.period) || typeof budget.limitUsd !== 'number' || !(budget.limitUsd > 0)) throw new ServiceError('budget is {period: day|month, limitUsd > 0}.');
    const prefix = budget.period === 'day' ? last : last.slice(0, 7);
    const window = outDays.filter((d) => d.date.startsWith(prefix));
    const unknown = window.length > 0 && window.every((d) => d.costUsd === null);
    report.budget = { period: budget.period, limitUsd: budget.limitUsd, spentUsd: unknown ? null : Math.round(window.reduce((n, d) => n + (d.costUsd ?? 0), 0) * 1e6) / 1e6 };
  }
  return report;
}

/** Usage receipts for services that keep none yet: append-only JSON lines, 0600, pruned to the window (LC-12).
 *  One writer process (the service holds its instance lock); every method is synchronous, so calls never interleave. */
export class JsonlUsageLedger {
  constructor(file) { this.file = file; }

  record(receipt) {
    ensurePrivateDir(path.dirname(this.file));
    const fd = fs.openSync(this.file, 'a+', 0o600);
    try {
      const { size } = fs.fstatSync(fd);
      const last = Buffer.alloc(1);
      // A killed writer left a torn line: never glue a receipt to it.
      const lead = size && fs.readSync(fd, last, 0, 1, size - 1) === 1 && last[0] !== 0x0a ? '\n' : '';
      fs.writeSync(fd, lead + JSON.stringify(receipt) + '\n');
    } finally {
      fs.closeSync(fd);
    }
  }

  receipts() {
    if (!fs.existsSync(this.file)) return [];
    const out = [];
    for (const line of fs.readFileSync(this.file, 'utf8').split('\n')) {
      if (!line) continue;
      try { out.push(JSON.parse(line)); } catch { /* a torn last line from a killed writer is skipped */ }
    }
    return out;
  }

  prune(now = Date.now()) {
    const first = utcDate(now - (USAGE_DAYS - 1) * 86_400_000);
    const all = this.receipts();
    const kept = all.filter((r) => String(r.at ?? '').slice(0, 10) >= first);
    if (kept.length !== all.length) atomicWrite(this.file, kept.map((r) => JSON.stringify(r) + '\n').join(''));
    return all.length - kept.length;
  }

  report(options) { return usageReport(this.receipts(), options); }
}

// --- logs (LC-12) ------------------------------------------------------------------------

/**
 * One structured log: JSON lines rotated by size (5 x 5 MB by default), files 0600 in a 0700
 * directory. `service.jsonl` -> `.1` ... `.<backups>`; the oldest falls off. Never pass a token,
 * a cookie, a login code or a request body that may carry one.
 */
export class RotatingLog {
  constructor(file, { maxBytes = LOG_MAX_BYTES, backups = LOG_BACKUPS } = {}) {
    if (maxBytes < 256 || backups < 1) throw new ServiceError('A rotating log needs maxBytes >= 256 and at least one backup.');
    this.file = file;
    this.maxBytes = maxBytes;
    this.backups = backups;
  }

  line(record) {
    let data = Buffer.from(`${JSON.stringify(record)}\n`);
    if (data.length <= this.maxBytes) return data;
    const cut = { ...record, truncated: true };
    let message = String(record.message ?? '');
    while (message) {
      message = message.slice(0, Math.floor(message.length / 2));
      cut.message = message;
      data = Buffer.from(`${JSON.stringify(cut)}\n`);
      if (data.length <= this.maxBytes) return data;
    }
    return Buffer.from(`${JSON.stringify({ at: record.at, level: record.level, message: '', truncated: true })}\n`);
  }

  write(level, message, fields = {}) {
    const data = this.line({ at: nowIso(), level: String(level), message: String(message), ...fields });
    ensurePrivateDir(path.dirname(this.file));
    let size = 0;
    try { size = fs.statSync(this.file).size; } catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (size && size + data.length > this.maxBytes) this.rotate();
    const fd = fs.openSync(this.file, 'a', 0o600);
    try { fs.writeSync(fd, data); } finally { fs.closeSync(fd); }
  }

  rotate() {
    for (let i = this.backups - 1; i > 0; i -= 1) {
      if (fs.existsSync(`${this.file}.${i}`)) fs.renameSync(`${this.file}.${i}`, `${this.file}.${i + 1}`);
    }
    fs.renameSync(this.file, `${this.file}.1`);
  }
}

/**
 * Call once at start: a launchd stdout file over `maxBytes` is copied to `<file>.1` and truncated
 * in place (launchd holds it open for append, so a rename would leave it writing to the old name).
 */
export function capStdoutLog(file, maxBytes = LOG_MAX_BYTES) {
  let size;
  try { size = fs.statSync(file).size; } catch (error) { if (error.code === 'ENOENT') return false; throw error; }
  if (size <= maxBytes) return false;
  fs.copyFileSync(file, `${file}.1`);
  fs.chmodSync(`${file}.1`, 0o600);
  fs.truncateSync(file, 0);
  return true;
}

// --- shutdown (LC-01) ----------------------------------------------------------------------

export class Stopping extends ServiceError {}

/**
 * SIGTERM/SIGINT: stop taking new work, drain in-flight work until `deadline` seconds, then hand
 * over with `onStop(drained)`. A hand-over that never settles is cut by a hard exit
 * (EXIT_HARD_STOP) `grace` seconds later.
 *
 *   const drain = new Drain().install((drained) => server.close(() => process.exit(0)),
 *     { onStopping: () => log.append('service.stopping', 'info', 'Stopping.') });
 *   await drain.work(async () => { ... });   // rejects with Stopping once a stop has begun
 */
export class Drain {
  constructor({ deadline = DRAIN_SECONDS, grace = DRAIN_GRACE_SECONDS } = {}) {
    this.deadline = deadline;
    this.grace = grace;
    this.inflight = 0;
    this.stopping = false;
    this.waiters = new Set();
  }

  async work(fn) {
    if (this.stopping) throw new Stopping('The service is stopping and takes no new work.');
    this.inflight += 1;
    try {
      return await fn();
    } finally {
      this.inflight -= 1;
      if (this.inflight === 0) for (const wake of this.waiters) wake();
    }
  }

  /** Refuse new work from now on; false when a stop had already begun. */
  requestStop() {
    if (this.stopping) return false;
    this.stopping = true;
    return true;
  }

  /** Resolves true when in-flight work finished inside `timeoutSeconds`, false otherwise. */
  wait(timeoutSeconds) {
    if (this.inflight === 0) return Promise.resolve(true);
    return new Promise((resolve) => {
      const wake = () => { clearTimeout(timer); this.waiters.delete(wake); resolve(true); };
      const timer = setTimeout(() => { this.waiters.delete(wake); resolve(false); }, timeoutSeconds * 1000);
      this.waiters.add(wake);
    });
  }

  install(onStop, { onStopping, signals = ['SIGTERM', 'SIGINT'] } = {}) {
    const handler = () => {
      if (!this.requestStop()) return; // a second signal changes nothing: the hard exit holds the deadline
      setTimeout(() => process.exit(EXIT_HARD_STOP), (this.deadline + this.grace) * 1000).unref();
      (async () => {
        try { await onStopping?.(); } catch (error) { process.stderr.write(`${error?.stack ?? error}\n`); }
        await onStop(await this.wait(this.deadline));
      })();
    };
    for (const signal of signals) process.on(signal, handler);
    return this;
  }
}

// --- releases (LC-11, LC-15) -----------------------------------------------------------------

/**
 * Keep the release the job runs and the one before it; remove older release directories, newest
 * first by modification time. `current` (a release or a symlink to one) is never removed, even
 * after a rollback. Symlinks and files are left alone. Returns the removed paths.
 */
export function pruneReleases(releasesDir, { keep = 2, current } = {}) {
  if (keep < 2) throw new ServiceError('keep at least the current release and the one before it (keep >= 2).');
  if (!fs.existsSync(releasesDir)) return [];
  const releases = fs.readdirSync(releasesDir, { withFileTypes: true })
    .filter((e) => e.isDirectory() && !e.isSymbolicLink())
    .map((e) => path.join(releasesDir, e.name))
    .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
  const keepers = [];
  if (current) {
    const resolved = fs.realpathSync(current);
    keepers.push(...releases.filter((p) => fs.realpathSync(p) === resolved));
  }
  for (const release of releases) {
    if (keepers.length >= keep) break;
    if (!keepers.includes(release)) keepers.push(release);
  }
  const removed = releases.filter((p) => !keepers.includes(p));
  for (const release of removed) fs.rmSync(release, { recursive: true, force: true });
  return removed;
}

// --- operator login -------------------------------------------------------------------

export class LoginCodes {
  // `stateDir` — a local service keeps codes and the session key in files. An online service
  // (DEC-0019) usually has no durable disk: pass `stateDir = null` with `{ store, key }` — `store`
  // like `new MemoryCodeStore()` (a restart forgets every code, so none can be replayed) and
  // `key` a Buffer from a platform secret, so sessions survive a deploy.
  constructor(stateDir, ttlSeconds = 120, { store = null, key = null } = {}) {
    this.ttl = Math.min(ttlSeconds, 120);
    this.store = store;
    this.fixedKey = key;
    if (stateDir) {
      this.dir = ensurePrivateDir(stateDir);
      this.keyPath = path.join(this.dir, 'session.key');
      this.codesPath = path.join(this.dir, 'login-codes.json');
    } else if (!store || !key) {
      throw new ServiceError('LoginCodes without a state directory needs { store, key }.');
    }
    if (key && Buffer.from(key).length < 32) throw new ServiceError('the session key must be at least 32 bytes.');
  }

  key() {
    if (this.fixedKey) return Buffer.from(this.fixedKey);
    if (!fs.existsSync(this.keyPath)) atomicWrite(this.keyPath, crypto.randomBytes(32), 0o600);
    return fs.readFileSync(this.keyPath);
  }

  load() {
    if (this.store) return this.store.load();
    try { return JSON.parse(fs.readFileSync(this.codesPath, 'utf8')); } catch { return {}; }
  }

  save(codes) {
    const horizon = Date.now() / 1000 - 3600;
    const kept = Object.fromEntries(Object.entries(codes).filter(([, v]) => (v.expires ?? 0) > horizon));
    if (this.store) { this.store.save(kept); return; }
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
    if (this.fixedKey) throw new ServiceError('a platform-held session key is rotated on the platform, not here.');
    atomicWrite(this.keyPath, crypto.randomBytes(32), 0o600);
  }
}

/** DEC-0019: a code store held in memory — for an online service with no durable disk. */
export class MemoryCodeStore {
  constructor() { this.codes = {}; }
  load() { return JSON.parse(JSON.stringify(this.codes)); }
  save(codes) { this.codes = JSON.parse(JSON.stringify(codes)); }
}

export const sessionCookieHeader = (value, maxAge = 30 * 86400) => `${SESSION_COOKIE}=${value}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${maxAge}`;
/** DEC-0019: the remote cookie — `__Host-` name, Secure, no Domain, Path=/. */
export const remoteSessionCookieHeader = (value, maxAge = 30 * 86400) => `${REMOTE_SESSION_COOKIE}=${value}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=${maxAge}`;

/**
 * DEC-0019: the request guard of an online service. `origin` is the service's own origin
 * (`https://agent.example.com`). `forwardedProto` is the platform-set scheme where TLS ends
 * before the process (`x-forwarded-proto`); pass `undefined` when the process terminates TLS.
 * Returns the refusal sentence, or null.
 */
export function checkRemoteRequest(origin, host, requestOrigin, secFetchSite, forwardedProto) {
  const own = new URL(origin);
  if (String(host ?? '').toLowerCase() !== own.host) return `Host ${host} is not this service.`;
  if (forwardedProto !== undefined && forwardedProto !== null && String(forwardedProto).split(',')[0].trim() !== 'https') return 'This service answers over https only.';
  if (requestOrigin !== undefined && requestOrigin !== null && requestOrigin !== own.origin) return `Origin ${requestOrigin} is not this service.`;
  if (secFetchSite === 'cross-site') return 'Cross-site requests are refused.';
  return null;
}

/**
 * DEC-0019: may this request read the well-known document? A local service answers anyone (the
 * loopback guard already ran); a remote one only the bearer of the service token. A `false`
 * answer is a `401` with an EMPTY body — nothing about the service is disclosed.
 */
export function wellKnownAllowed(placement, authorization, token, scheme = 'Bearer') {
  return placement !== 'remote' || tokenMatches(authorization, token, scheme);
}

/** The token directory a host-side installer uses for remote services on this computer. */
export function remoteTokenFile(id, instance = 'default', dir = servicesDir()) {
  return path.join(path.dirname(dir), 'tokens', `${id}.${instance}.token`);
}

/**
 * DEC-0019, installer side: register an online service on THIS computer. Writes the token file
 * (0600, never printed) and the descriptor; the same token must be set on the hosting platform as
 * a secret. Returns the descriptor path. `token` is read from the caller — a file or stdin —
 * never from an argument vector.
 */
export function registerRemote({ id, instance = 'default', name, summary, origin, token, doctor, dir = servicesDir(), installedBy = 'fabric-service register-remote' }) {
  if (!token || String(token).trim().length < 16) throw new ServiceError('the service token must be at least 16 characters.');
  const tokenFile = remoteTokenFile(id, instance, dir);
  const d = {
    protocol: PROTOCOL, id, instance, name, ...(summary ? { summary } : {}), placement: 'remote', origin,
    auth: { tokenFile }, lifecycle: { manager: 'none' }, ...(doctor ? { commands: { doctor } } : {}),
    installedAt: nowIso(), installedBy,
  };
  const problems = validateDescriptor(d);
  if (problems.length) throw new ServiceError(`Descriptor is invalid: ${problems.join('; ')}.`);
  ensurePrivateDir(path.dirname(tokenFile));
  atomicWrite(tokenFile, String(token).trim(), 0o600);
  return writeDescriptor(d, dir);
}

export function cookieValue(header, name = SESSION_COOKIE) {
  for (const part of String(header ?? '').split(';')) {
    const [k, ...rest] = part.trim().split('=');
    if (k === name) return rest.join('=');
  }
  return null;
}
