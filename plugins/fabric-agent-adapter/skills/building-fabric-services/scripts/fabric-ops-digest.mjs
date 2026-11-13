// A service's operations digests (contract DEC-0153, docs/specification/ops-digest.md at the pin): every record of its
// operations log counted by operation and outcome in the hour it happened, one ops.digest.hourly@1 line for each hour
// the service observed itself running in (an empty one included), and one ops.digest.daily@1 line for each closed UTC
// day that has hourly lines. Counts only: no log line, no path, no identifier (OD-7). foldHour and foldDay are the
// contract's reference folds (src/ops-digest.ts, its vectors in test/fixtures/ops-digest/); opsDigestRules is
// FAC-SEM-166 and FAC-SEM-167; OpsDigest keeps the files (OD-1, OD-5, OD-6); opsDigestExtension writes the
// descriptor's OD-9 declaration. Part of the Node service kit (FAA-206 part 2, layer L3); the twin of
// fabric_ops_digest.py. Node 20+, no dependency.
import fs from 'node:fs';
import path from 'node:path';
import { ServiceError } from './fabric-base.mjs';
import { indexed, isObject } from './fabric-jsvalue.mjs';
import { atomicWrite, ensurePrivateDir } from './fabric-paths.mjs';
import { secretValue } from './fabric-secrets.mjs';
import { DAY_MS } from './fabric-time.mjs';

export const OPS_DIGEST_HOURLY = 'ops.digest.hourly@1';
export const OPS_DIGEST_DAILY = 'ops.digest.daily@1';
/** The descriptor's extension key (OD-9), protocol fabric-ops-digest/0.1. */
export const OPS_DIGEST_EXTENSION = 'https://fabric.passioncode.ai/agent-contract/extensions/ops-digest/0.1';
export const RISE_MIN_FAILED = 10;
export const RISE_FACTOR = 2;
/** An operation's name (OD-2), the contract's OP_NAME, and its length cap OP_NAME_MAX. */
export const OP_NAME = /^[a-z][A-Za-z0-9_]*(?:[.:/-][A-Za-z0-9_]+)*$/;
export const OP_NAME_MAX = 64;
export const OPS_MAX = 4096;
/** The overflow name the kit counts the rest under once a day holds 4095 named operations (OD-3). */
export const OVERFLOW_OP = 'ops.overflow';
export const OUTCOMES = Object.freeze(['ok', 'failed', 'unknown']);
const HOUR_MS = 3_600_000;
const WHOLE_HOUR = /^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):00:00(?:\.000)?Z$/;
const DAY = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/;
const SLASH = String.raw`(?:[\/\\]|%(?:25)?2[fF])`;
/** The contract's hasHomePath (src/activity-rules.ts at the pin). */
export const HOME_PATH = Object.freeze([
  new RegExp(String.raw`(?:^|[^A-Za-z0-9]|%(?:25)?2[fF])(?:[Uu]sers|home)${SLASH}[A-Za-z0-9_]`),
  /(?:^|[^A-Za-z0-9])-(?:[Uu]sers|home)-[A-Za-z0-9]/,
  /(?:^|[\s"'=\/\\])~(?:[A-Za-z_][A-Za-z0-9_.-]*)?(?:[\/\\]|$)/,
]);
const PRINTABLE = /^[\x20-\x7e]+$/;
const SOURCE = /^[a-z][a-z0-9-]{0,31}$/;
const FILE = /^(hourly|daily)-([0-9]{4})-([0-9]{2})\.jsonl$/;

/** An input no digest holds; its message names a credential-shaped or home-folder value only by its place. */
export class OpsDigestError extends ServiceError {}

export const hasHomePath = (value) => typeof value === 'string' && HOME_PATH.some((p) => p.test(value));
export const isRise = (failed, previous) => failed >= RISE_MIN_FAILED && failed >= RISE_FACTOR * Math.max(1, previous);

/** The instant of a whole UTC hour in the schema's form, or null (a 25th hour, a 30 February). */
export function wholeHour(value) {
  const match = typeof value === 'string' ? WHOLE_HOUR.exec(value) : null;
  if (!match) return null;
  const [year, month, day, hour] = match.slice(1).map(Number);
  const at = new Date(0);
  at.setUTCFullYear(year, month - 1, day);
  at.setUTCHours(hour);
  return at.getUTCFullYear() === year && at.getUTCMonth() === month - 1 && at.getUTCDate() === day && at.getUTCHours() === hour ? at.getTime() : null;
}
export const realDay = (value) => typeof value === 'string' && DAY.test(value) && wholeHour(`${value}T00:00:00Z`) !== null;
export const isoHour = (at) => new Date(at).toISOString();
export const dayOf = (at) => isoHour(at).slice(0, 10);

const count = (n) => (typeof n === 'number' && Number.isSafeInteger(n) && n >= 0 ? n : null);
const hidden = (value) => secretValue(value) || hasHomePath(value);
const shown = (value, instead) => (hidden(value) || !PRINTABLE.test(value) ? instead : value);
const opShown = (op) => (op.length <= OP_NAME_MAX && OP_NAME.test(op) ? shown(op, 'this operation') : 'this operation');
const byName = (a, b) => (a.op < b.op ? -1 : 1);

/** What OD-2 refuses in an operation's name (its grammar, OP_NAME_MAX included, or FAC-SEM-167); null when lawful. */
export function nameRefusal(op) {
  if (typeof op !== 'string' || op.length > OP_NAME_MAX || !OP_NAME.test(op)) return "fails OD-2's name grammar";
  return hidden(op) ? 'is refused by FAC-SEM-167' : null;
}
function allObjects(list, where) {
  if (!Array.isArray(list)) throw new OpsDigestError(`${where} is not an array`);
  for (let i = 0; i < list.length; i += 1) if (!isObject(list[i])) throw new OpsDigestError(`the item at ${i} of ${where} is not an object`);
}
function once(ops, where) {
  const names = new Set();
  ops.forEach((c, i) => {
    if (typeof c.op !== 'string') throw new OpsDigestError(`the operation at ${i} of ${where} has no string name`);
    if (names.has(c.op)) throw new OpsDigestError(`${shown(c.op, `the operation at ${i}`)} is named twice in ${where}`);
    names.add(c.op);
  });
}
const sum = (ops) => ops.reduce((t, c) => ({ ok: t.ok + c.ok, failed: t.failed + c.failed, unknown: t.unknown + c.unknown }), { ok: 0, failed: 0, unknown: 0 });
function safe(digest) {
  const counts = [digest.total, ...digest.ops].flatMap((c) => [c.ok, c.failed, c.unknown])
    .concat(digest.risen.flatMap((r) => ('previous' in r ? [r.failed, r.previous] : [r.failed])));
  if (!counts.every((n) => count(n) !== null)) throw new OpsDigestError('a sum is beyond 2^53 - 1');
  return digest;
}

/** The digest of the hour starting at from (the contract's foldHour); throws OpsDigestError where it throws. */
export function foldHour(counts, from, previous) {
  const start = wholeHour(from);
  if (start === null) throw new OpsDigestError(`${typeof from === 'string' ? shown(from, 'from') : 'from'} is not a whole UTC hour`);
  allObjects(counts, 'counts');
  if (wholeHour(isoHour(start + HOUR_MS)) === null) throw new OpsDigestError(`the hour after ${shown(from, 'from')} is not a whole UTC hour the schema writes`);
  const merged = new Map();
  counts.forEach((c, i) => {
    const refused = nameRefusal(c.op);
    if (refused !== null) throw new OpsDigestError(`the operation at ${i} ${refused}: no hourly digest (OD-3)`);
    if (![c.ok, c.failed, c.unknown].every((n) => count(n) !== null)) throw new OpsDigestError(`a count of ${shown(c.op, `the operation at ${i}`)} is not an integer from 0 to 2^53 - 1`);
    const m = merged.get(c.op) ?? { op: c.op, ok: 0, failed: 0, unknown: 0 };
    m.ok += c.ok; m.failed += c.failed; m.unknown += c.unknown;
    merged.set(c.op, m);
  });
  if (merged.size > OPS_MAX) throw new OpsDigestError(`the hour counts ${merged.size} operations, more than ${OPS_MAX}: no hourly digest (OD-3)`);
  const ops = [...merged.values()].sort(byName);
  const absent = previous === null || previous === undefined;
  if (!absent && !(isObject(previous) && typeof previous.to === 'string')) throw new OpsDigestError('the previous hour is neither absent nor a digest with a string to');
  const adjoining = !absent && wholeHour(previous.to) === start ? previous.ops : [];
  allObjects(adjoining, "the previous hour's ops");
  once(adjoining, "the previous hour's ops");
  const before = new Map(adjoining.map((c) => [c.op, c.failed]));
  for (const c of ops) if (before.has(c.op) && count(before.get(c.op)) === null) throw new OpsDigestError(`the previous hour's failures of ${shown(c.op, 'an operation')} are not an integer from 0 to 2^53 - 1`);
  const risen = ops.filter((c) => isRise(c.failed, before.get(c.op) ?? 0)).map((c) => ({ op: c.op, failed: c.failed, previous: before.get(c.op) ?? 0 }));
  return safe({ schema: OPS_DIGEST_HOURLY, from: isoHour(start), to: isoHour(start + HOUR_MS), ops, total: sum(ops), risen });
}

/** The day's hourly digests folded into one (the contract's foldDay), or null for a day with no hour of its own. */
export function foldDay(day, hourly) {
  if (!realDay(day)) throw new OpsDigestError(`${typeof day === 'string' ? shown(day, 'day') : 'day'} is not a real UTC day`);
  allObjects(hourly, 'hourly');
  const seen = new Set();
  const mine = hourly.filter((h) => {
    const at = wholeHour(h.from);
    if (at === null || dayOf(at) !== day || seen.has(at)) return false;
    seen.add(at);
    return true;
  });
  if (mine.length === 0) return null;
  const merged = new Map();
  const rose = new Map();
  for (const h of mine) {
    for (const where of ['ops', 'risen']) {
      allObjects(h[where], `${h.from}'s ${where}`);
      h[where].forEach((c, i) => {
        const refused = nameRefusal(c.op);
        if (refused !== null) throw new OpsDigestError(`the operation at ${i} of ${h.from}'s ${where} ${refused}: no daily digest (OD-3)`);
      });
    }
    for (const c of h.ops) {
      if (![c.ok, c.failed, c.unknown].every((n) => count(n) !== null)) throw new OpsDigestError(`a count of ${shown(c.op, 'an operation')} in ${h.from} is not an integer from 0 to 2^53 - 1`);
      const m = merged.get(c.op) ?? { op: c.op, ok: 0, failed: 0, unknown: 0 };
      m.ok += c.ok; m.failed += c.failed; m.unknown += c.unknown;
      merged.set(c.op, m);
    }
    once(h.risen, `the risen of ${h.from}`);
    for (const r of h.risen) {
      if (count(r.failed) === null) throw new OpsDigestError(`the rise of ${shown(r.op, 'an operation')} in ${h.from} is not an integer from 0 to 2^53 - 1`);
      if (!h.ops.some((c) => c.op === r.op)) throw new OpsDigestError(`${shown(r.op, 'an operation')} rose in ${h.from} but that hour's ops does not count it`);
      const x = rose.get(r.op) ?? { hours: 0, failed: 0 };
      x.hours += 1; x.failed += r.failed;
      rose.set(r.op, x);
    }
  }
  if (merged.size > OPS_MAX) throw new OpsDigestError(`the day folds ${merged.size} operations, more than ${OPS_MAX}: no daily digest (OD-3)`);
  const ops = [...merged.values()].sort(byName);
  const risen = [...rose.entries()].map(([op, x]) => ({ op, ...x })).sort((a, b) => b.failed - a.failed || byName(a, b));
  return safe({ schema: OPS_DIGEST_DAILY, day, hours: mine.length, ops, total: sum(ops), risen });
}

/** FAC-SEM-166 and FAC-SEM-167 on one digest of either kind; undefined for any other kind. */
export function opsDigestRules(kind, value) {
  if (!(kind === 'ops-digest-hourly' || kind === 'ops-digest-daily')) return undefined;
  const findings = [];
  const window = (instancePath, message) => findings.push({ code: 'FAC-SEM-166', instancePath, message });
  const named = (instancePath, op) => {
    if (secretValue(op)) findings.push({ code: 'FAC-SEM-167', instancePath, message: "an operation's name is shaped like a credential; it names an operation, never a value" });
    else if (hasHomePath(op)) findings.push({ code: 'FAC-SEM-167', instancePath, message: "an operation's name holds a home folder; it names an operation, never a path" });
  };
  if (kind === 'ops-digest-hourly') {
    const from = wholeHour(value.from);
    const to = wholeHour(value.to);
    if (from === null) window('/from', 'from is a whole UTC hour of a real day');
    if (to === null) window('/to', 'to is a whole UTC hour of a real day');
    if (from !== null && to !== null && to - from !== HOUR_MS) window('/to', 'to is exactly one hour after from');
  } else if (!realDay(value.day)) {
    window('/day', 'day is a real UTC day, YYYY-MM-DD');
  }
  const byOp = new Map();
  const totals = { ok: 0, failed: 0, unknown: 0 };
  for (const [entry, index] of indexed(value.ops)) {
    const op = entry.op;
    if (typeof op === 'string') {
      if (byOp.has(op)) window(`/ops/${index}/op`, `${opShown(op)} is counted once`);
      else byOp.set(op, entry);
      named(`/ops/${index}/op`, op);
    }
    for (const k of OUTCOMES) {
      const n = count(entry[k]);
      totals[k] = n === null || totals[k] === null ? null : totals[k] + n;
    }
  }
  const total = isObject(value.total) ? value.total : null;
  if (total !== null && Array.isArray(value.ops)) {
    for (const k of OUTCOMES) {
      const want = totals[k];
      if (want === null || count(total[k]) === null) continue;
      if (!Number.isSafeInteger(want)) window(`/total/${k}`, `the sum of ops' ${k} is beyond 2^53 - 1, so no total.${k} can be it`);
      else if (total[k] !== want) window(`/total/${k}`, `total.${k} is the sum of ops' ${k}, ${want}`);
    }
  }
  const rose = new Set();
  const hours = count(value.hours);
  for (const [entry, index] of indexed(value.risen)) {
    const op = entry.op;
    if (typeof op !== 'string') continue;
    const at = `/risen/${index}`;
    named(`${at}/op`, op);
    if (rose.has(op)) window(`${at}/op`, `${opShown(op)} is named once among the rises`);
    rose.add(op);
    const counted = byOp.get(op);
    if (counted === undefined) { window(`${at}/op`, `${opShown(op)} rose, so ops counts it`); continue; }
    const failed = count(entry.failed);
    const countedFailed = count(counted.failed);
    if (kind === 'ops-digest-hourly') {
      const previous = count(entry.previous);
      if (failed !== null && countedFailed !== null && failed !== countedFailed) window(`${at}/failed`, `a rise names the hour's failures of ${opShown(op)}, ${countedFailed}`);
      if (failed !== null && previous !== null && !isRise(failed, previous)) window(at, `${failed} failures against ${previous} is no rise: at least ${RISE_MIN_FAILED} and ${RISE_FACTOR} times the hour before (none counts as one)`);
    } else {
      const risenHours = count(entry.hours);
      if (risenHours !== null && hours !== null && risenHours > hours) window(`${at}/hours`, `${opShown(op)} rose in ${risenHours} hours; the day folds ${hours}`);
      if (failed !== null && risenHours !== null && failed < RISE_MIN_FAILED * risenHours) window(`${at}/failed`, `${risenHours} hours of rises hold at least ${RISE_MIN_FAILED * risenHours} failures`);
      if (failed !== null && countedFailed !== null && failed > countedFailed) window(`${at}/failed`, `the rises' failures are at most the day's failures of ${opShown(op)}, ${countedFailed}`);
    }
  }
  return findings;
}

const sameKeys = (o, keys) => Object.keys(o).sort().join(',') === [...keys].sort().join(',');
function shapeOk(line, daily) {
  if (!isObject(line) || !sameKeys(line, daily ? ['schema', 'day', 'hours', 'ops', 'total', 'risen'] : ['schema', 'from', 'to', 'ops', 'total', 'risen'])) return false;
  if (line.schema !== (daily ? OPS_DIGEST_DAILY : OPS_DIGEST_HOURLY)) return false;
  if (!Array.isArray(line.ops) || !Array.isArray(line.risen) || !isObject(line.total)) return false;
  if (line.ops.length > OPS_MAX || line.risen.length > OPS_MAX) return false;
  for (const c of line.ops) {
    if (!(isObject(c) && sameKeys(c, ['failed', 'ok', 'op', 'unknown']) && nameRefusal(c.op) === null && OUTCOMES.every((k) => count(c[k]) !== null))) return false;
  }
  const want = daily ? ['failed', 'hours', 'op'] : ['failed', 'op', 'previous'];
  for (const r of line.risen) {
    if (!(isObject(r) && sameKeys(r, want) && nameRefusal(r.op) === null && want.filter((k) => k !== 'op').every((k) => count(r[k]) !== null))) return false;
  }
  return sameKeys(line.total, ['failed', 'ok', 'unknown']) && OUTCOMES.every((k) => count(line.total[k]) !== null);
}

/** The digests of kind (hourly or daily) in folder as a reader reads them (OD-6); the first line of an hour or day kept. */
export function readDigests(folder, kind) {
  const daily = kind === 'daily';
  const out = [];
  const seen = new Set();
  let names = [];
  try { names = fs.readdirSync(folder).filter((n) => n.startsWith(`${kind}-`) && FILE.test(n)).sort(); } catch { return out; }
  for (const name of names) {
    let text;
    try { text = fs.readFileSync(path.join(folder, name)).toString('utf8'); } catch { continue; }
    for (const raw of text.split('\n')) {
      let line;
      try { line = JSON.parse(raw); } catch { continue; }
      if (!shapeOk(line, daily) || opsDigestRules(daily ? 'ops-digest-daily' : 'ops-digest-hourly', line).length) continue;
      const key = daily ? line.day : wholeHour(line.from);
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(line);
    }
  }
  return out;
}

const lineOf = (digest) => `${JSON.stringify(digest)}\n`;
function append(file, data) {
  const fd = fs.openSync(file, 'a', 0o600);
  try { fs.writeSync(fd, data); } finally { fs.closeSync(fd); }
}

/** The files of one service's operations digests in folder; see fabric_ops_digest.OpsDigest. */
export class OpsDigest {
  constructor(folder, { overflow = OVERFLOW_OP, clock } = {}) {
    if (nameRefusal(overflow) !== null) throw new OpsDigestError(`the overflow name ${nameRefusal(overflow)}`);
    this.folder = folder;
    this.overflow = overflow;
    this.clock = clock ?? (() => Date.now());
    this.hour = null;
    this.counts = new Map();
    this.names = new Set();
    this.namesDay = null;
    this.started = false;
  }

  get kept() { return path.join(this.folder, 'kept-hour.json'); }
  now(at) { return Math.trunc(at ?? this.clock()); }

  start(at) {
    ensurePrivateDir(this.folder);
    const now = this.now(at);
    const written = { hours: 0, days: 0 };
    const kept = this.readKept();
    if (kept !== null) {
      if (kept.start + HOUR_MS <= now) { written.hours += this.writeHour(kept.start, kept.counts); this.dropKept(); }
      else { this.hour = kept.start; this.counts = kept.counts; }
    }
    if (this.hour === null) { this.hour = now - (now % HOUR_MS); this.counts = new Map(); }
    this.rebuildNames(now);
    written.days += this.foldClosedDays(now);
    this.started = true;
    return written;
  }

  record(op, outcome, at) {
    const refused = nameRefusal(op);
    if (refused !== null) throw new OpsDigestError(`the operation's name ${refused} (OD-2): name the operation, never a value of it`);
    const now = this.advance(this.now(at));
    let name = op;
    if (!this.names.has(name) && name !== this.overflow) {
      if (this.names.size >= OPS_MAX - 1) name = this.overflow;
      else this.names.add(name);
    }
    this.namesDay = dayOf(now);
    const row = this.counts.get(name) ?? [0, 0, 0];
    row[outcome === 'ok' ? 0 : outcome === 'failed' ? 1 : 2] += 1;
    this.counts.set(name, row);
  }

  tick(at) { this.advance(this.now(at)); }

  flush(at) {
    const now = this.now(at);
    const written = { hours: 0, days: 0 };
    if (this.hour !== null && this.hour + HOUR_MS <= now) {
      written.hours += this.writeHour(this.hour, this.counts);
      this.hour = null; this.counts = new Map();
      this.dropKept();
    }
    written.days += this.foldClosedDays(now);
    this.keep();
    return written;
  }

  stop(at) { return this.flush(at); }

  advance(now) {
    if (!this.started) throw new OpsDigestError('call start() before recording (OD-1: the kept hour is written first)');
    const hour = now - (now % HOUR_MS);
    if (this.hour !== null && hour < this.hour) return this.hour;
    if (this.hour !== null && hour > this.hour) {
      this.writeHour(this.hour, this.counts);
      this.counts = new Map();
      this.foldClosedDays(now);
    }
    if (dayOf(hour) !== this.namesDay) { this.names = new Set(); this.namesDay = dayOf(hour); }
    this.hour = hour;
    return now;
  }

  previous(start) {
    const before = start - HOUR_MS;
    const lines = readDigests(this.folder, 'hourly');
    for (let i = lines.length - 1; i >= 0; i -= 1) if (wholeHour(lines[i].from) === before) return lines[i];
    return null;
  }

  writeHour(start, counts) {
    ensurePrivateDir(this.folder);
    const from = isoHour(start);
    if (readDigests(this.folder, 'hourly').some((line) => wholeHour(line.from) === start)) return 0;
    const rows = [...counts.entries()].map(([op, c]) => ({ op, ok: c[0], failed: c[1], unknown: c[2] }));
    const digest = foldHour(rows, from, this.previous(start));
    append(path.join(this.folder, `hourly-${from.slice(0, 7)}.jsonl`), lineOf(digest));
    return 1;
  }

  foldClosedDays(now) {
    const hourly = readDigests(this.folder, 'hourly');
    const done = new Set(readDigests(this.folder, 'daily').map((line) => line.day));
    const today = dayOf(now);
    let folded = 0;
    for (const day of [...new Set(hourly.map((line) => line.from.slice(0, 10)))].sort()) {
      if (day >= today || done.has(day)) continue;
      const digest = foldDay(day, hourly);
      if (digest !== null) { append(path.join(this.folder, `daily-${day.slice(0, 7)}.jsonl`), lineOf(digest)); folded += 1; }
    }
    return folded;
  }

  rebuildNames(now) {
    const today = dayOf(now);
    const names = new Set();
    for (const line of readDigests(this.folder, 'hourly')) if (line.from.slice(0, 10) === today) for (const c of line.ops) names.add(c.op);
    if (this.hour !== null && dayOf(this.hour) === today) for (const op of this.counts.keys()) names.add(op);
    names.delete(this.overflow);
    this.names = names; this.namesDay = today;
  }

  keep() {
    if (this.hour === null) return;
    ensurePrivateDir(this.folder);
    const ops = [...this.counts.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)).map(([op, c]) => [op, ...c]);
    atomicWrite(this.kept, `${JSON.stringify({ from: isoHour(this.hour), ops })}\n`);
  }

  readKept() {
    try {
      const body = JSON.parse(fs.readFileSync(this.kept, 'utf8'));
      const start = wholeHour(body.from);
      if (start === null) return null;
      const counts = new Map();
      for (const row of body.ops ?? []) {
        if (Array.isArray(row) && row.length === 4 && nameRefusal(row[0]) === null && row.slice(1).every((n) => count(n) !== null)) counts.set(row[0], row.slice(1));
      }
      return { start, counts };
    } catch { return null; }
  }

  dropKept() { try { fs.unlinkSync(this.kept); } catch { /* already gone */ } }
}

/** A log's own outcome word as OD-3 maps it; any word the service's published mapping does not place is unknown. */
export function outcomeOf(word, mapping = {}) {
  if (word === 'ok' || word === 'failed') return word;
  const mapped = typeof word === 'string' && Object.hasOwn(mapping ?? {}, word) ? mapping[word] : undefined;
  return OUTCOMES.includes(mapped) ? mapped : 'unknown';
}

// String.prototype.isWellFormed is Node 20; the kit's floor is Node 18 (package.json engines).
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;
function dirProblem(d) {
  if (typeof d !== 'string' || !d || d.length > 256) return 'dir is 1 to 256 characters';
  if (d.startsWith('/') || d.startsWith('~') || d.endsWith('/') || d.includes('//') || d.includes('\\') || d.includes(':')) return 'dir is relative to the data folder: forward slashes, no leading / or ~, no drive or :, no trailing /';
  if ([...d].some((ch) => ch.charCodeAt(0) < 0x20 || ch.charCodeAt(0) === 0x7f) || LONE_SURROGATE.test(d)) return 'dir holds no control character and no lone surrogate';
  if (d.split('/').some((seg) => seg === '.' || seg === '..' || !seg.replace(/[. ]+$/, ''))) return 'dir has no ., .. or empty segment';
  if (hasHomePath(d) || hasHomePath(d.replaceAll('./', '/'))) return 'dir holds a home folder';
  if (secretValue(d)) return 'dir is shaped like a credential (a run of 40 letters, digits and / mixing cases and a digit counts; a space or a dot inside a segment breaks it)';
  return null;
}

/** The descriptor's extensions member that says where a collector reads the daily digests (OD-9). */
export function opsDigestExtension(folders = [{ dir: 'digests', source: 'app' }]) {
  const items = [...folders].map((f) => ({ ...f }));
  if (items.length < 1 || items.length > 8) throw new OpsDigestError('the ops-digest declaration holds 1 to 8 folders');
  const dirs = new Set();
  const sources = new Set();
  items.forEach((item, i) => {
    if (!sameKeys(item, ['dir', 'source'])) throw new OpsDigestError(`folder ${i} is {dir, source} and nothing else`);
    const problem = dirProblem(item.dir);
    if (problem) throw new OpsDigestError(`folder ${i}: ${problem} (FAC-SEM-168)`);
    if (typeof item.source !== 'string' || !SOURCE.test(item.source) || secretValue(item.source)) throw new OpsDigestError(`folder ${i}: source is a label matching ^[a-z][a-z0-9-]{0,31}$`);
    const key = item.dir.toLowerCase().split('/').map((seg) => seg.replace(/[. ]+$/, '')).join('/');
    if (dirs.has(key) || sources.has(item.source)) throw new OpsDigestError(`folder ${i}: each dir and each source is named once (FAC-SEM-168)`);
    dirs.add(key); sources.add(item.source);
  });
  return { [OPS_DIGEST_EXTENSION]: items };
}
