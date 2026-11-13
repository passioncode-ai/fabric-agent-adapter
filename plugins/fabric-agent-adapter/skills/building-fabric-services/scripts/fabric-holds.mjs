// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
// Work a service holds by its own limits, said to its caller and its operator (FAA-298): a held job's statusMessage in
// the contract's pause grammar (`quota-exhausted[ until <until>]: waiting <reason> since <since>[: <message>]`; the
// pinned interop-job schema is closed, so `waiting {reason, since, until, message}` rides statusMessage, never a field
// of the job), one push per hold, and the operator's scoped lift. The twin of fabric_holds.py, held to the same
// vectors (test/fixtures/holds/waiting-vectors.json). A record written since 0.83.0 carries `squash: 'ecmascript'`; one
// without it is matched under both squashes, as 0.81.0's Python twin squashed names with str.split() (FAA-320,
// test/fixtures/holds/legacy-squash-vectors.json). Part of the Node service kit (layer L3, after fabric-interop).
// Node 20+, no dependency.
import crypto from 'node:crypto';
import fs from 'node:fs';
import { ServiceError, nowIso } from './fabric-base.mjs';
import { atomicWrite } from './fabric-paths.mjs';
import { decisionShape } from './fabric-actions.mjs';
import { QUOTA_EXHAUSTED, codePoints, pauseMessage, readJobPause, utcTime } from './fabric-interop-rules.mjs';
import { secretValue } from './fabric-secrets.mjs';

/** The limits a hold names: a daily quota, a per-caller share, a concurrency cap, a money cap. */
export const HOLD_REASONS = Object.freeze(['daily-quota', 'caller-share', 'concurrency', 'money']);
/** How the push names each reason to a person. */
export const REASON_WORDS = Object.freeze({
  'daily-quota': 'the daily quota', 'caller-share': 'its per-caller share',
  concurrency: 'the concurrency cap', money: 'the money cap',
});
/** The push's kind: a decision for the operator (level notice, notify true). */
export const HOLD_EVENT_KIND = 'limit.held';
/** The record of a lift applied (level info, no notify). */
export const LIFT_EVENT_KIND = 'limit.lifted';
/** The decision action a lift carries (DEC-0121 AP-2 shape). */
export const LIFT_ACTION = 'limit.lift';
const MAX_STATUS_MESSAGE = 500;
const WAITING = /^waiting (daily-quota|caller-share|concurrency|money) since ([0-9][0-9TZ:.-]*?)(?:: ([\s\S]+))?$/;
const SIZES = ['jobs', 'usd', 'limit'];

const instant = (value, name) => {
  if (!Number.isFinite(utcTime(value))) throw new ServiceError(`${name} is a UTC instant (Z, at most 3 fraction digits).`);
  return value;
};
const reasonOk = (reason, what) => {
  if (!HOLD_REASONS.includes(reason)) throw new ServiceError(`A ${what}'s reason is one of ${HOLD_REASONS.join(', ')}.`);
};
// One run of ECMAScript's whitespace, written out as fabric_secrets.JS_SPACE is, the class both twins squash with
// (FAA-316): Python's str.split() also takes U+001C to U+001F and U+0085 and not U+FEFF.
const SPACES = /[\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+/g;
const squash = (text) => String(text).replace(SPACES, ' ').replace(/^ | $/g, '');
/** What a record written since 0.83.0 carries: its names were squashed with ECMAScript's whitespace (FAA-320). */
export const SQUASH = 'ecmascript';
// Python's str.isspace() class, the one 0.81.0's Python twin squashed a name with (`" ".join(text.split())`).
const PY_SPACES = /[\t\n\v\f\r\u001c-\u001f \u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/g;
const legacySquash = (text) => String(text).replace(PY_SPACES, ' ').replace(/^ | $/g, '');
// The stored forms `caller` matches in `record`: the ECMAScript squash, and for a record with no `squash` mark (written
// before 0.83.0) also the squash 0.81.0's Python twin wrote (FAA-320). null matches only null.
const names = (caller, record) => {
  if (typeof caller !== 'string') return [caller];
  return record.squash === SQUASH ? [squash(caller)] : [squash(caller), legacySquash(caller)];
};

/** A held job's statusMessage; the message is shortened, never refused, to fit 500 characters. */
export function waitingMessage(reason, since, until = null, message = null) {
  reasonOk(reason, 'hold');
  instant(since, 'since');
  if (until !== null && until !== undefined) instant(until, 'until');
  else until = null;
  let text = `waiting ${reason} since ${since}`;
  const head = QUOTA_EXHAUSTED.length + (until === null ? 0 : ' until '.length + until.length) + ': '.length;
  if (message !== null && message !== undefined) {
    const squashed = squash(message);
    const room = MAX_STATUS_MESSAGE - head - codePoints(text) - ': '.length;
    if (squashed && room > 0) {
      text += ': ' + (codePoints(squashed) <= room ? squashed : [...squashed].slice(0, room - 3).join('').replace(/ $/, '') + '...');
    }
  }
  return pauseMessage(until === null ? { text } : { resetsAt: until, text });
}

/** `{reason, since, until?, message?}` of a fabric.job.get answer whose job a limit holds, else null. */
export function readWaiting(answer) {
  const pause = readJobPause(answer);
  if (!pause.paused) return null;
  let rest = answer.job.statusMessage.slice(QUOTA_EXHAUSTED.length);
  if ('resetsAt' in pause) rest = rest.slice(' until '.length + pause.resetsAt.length);
  if (!rest.startsWith(': ')) return null;
  const match = WAITING.exec(rest.slice(2));
  if (!match || !Number.isFinite(utcTime(match[2]))) return null;
  const waiting = { reason: match[1], since: match[2] };
  if ('resetsAt' in pause) waiting.until = pause.resetsAt;
  if (match[3] !== undefined) waiting.message = match[3];
  return waiting;
}

/** Put one job of a fabric-interop JobStore on hold (JobStore.pause with the waiting text). */
export function holdJob(jobs, jobId, reason, since, until = null, message = null) {
  let text = waitingMessage(reason, since, until, message).slice(QUOTA_EXHAUSTED.length);
  if (until !== null && until !== undefined) text = text.slice(' until '.length + until.length);
  return jobs.pause(jobId, until === null || until === undefined ? { text: text.slice(2) } : { resetsAt: until, text: text.slice(2) });
}

/** The push's one sentence: who, what, why, when it frees by itself, and the question. */
export function holdSentence(caller, work, reason, until) {
  const frees = until !== null && until !== undefined ? `it frees by itself at ${until}`
    : (['concurrency', 'caller-share'].includes(reason) ? 'it frees by itself when a running job ends' : 'it does not free by itself');
  return `${work} for ${caller} is held by ${REASON_WORDS[reason]}; ${frees}. Raise the limit for it?`;
}

function text(value, name, high = 200) {
  if (typeof value !== 'string' || !squash(value) || value.length > high) throw new ServiceError(`${name} is a text of 1 to ${high} characters.`);
  if (secretValue(value)) throw new ServiceError(`${name} looks like a credential; a hold names callers and work, never a secret.`);
  return squash(value);
}

const newId = () => crypto.randomUUID().replaceAll('-', '');

/**
 * The holds a service's limits put on work and the operator's lifts, in one file (0600, written atomically).
 * `events`, when given, is a function `({kind, level, text, subject, notify}) => event` that writes the push and the
 * lift record to the service's event log; without it they are returned for the service to write.
 */
export class HoldBook {
  constructor(file, { events = null, clock = nowIso } = {}) {
    this.file = file;
    this.events = events;
    this.clock = clock;
  }

  load() {
    if (!fs.existsSync(this.file)) return { holds: [], lifts: [] };
    let data;
    try {
      data = JSON.parse(fs.readFileSync(this.file, 'utf8'));
    } catch {
      throw new ServiceError('The hold book is not JSON; it is kept as it is.');
    }
    if (data === null || typeof data !== 'object' || !Array.isArray(data.holds) || !Array.isArray(data.lifts)) {
      throw new ServiceError('The hold book is not {holds, lifts}; it is kept as it is.');
    }
    return data;
  }

  save(data) { atomicWrite(this.file, JSON.stringify(data, null, 1) + '\n', 0o600); }

  now(now) { return instant(now ?? this.clock(), 'now'); }

  emit(kind, level, sentence, subject, notify) {
    const event = { kind, level, text: sentence, subject };
    if (notify) event.notify = true;
    return this.events ? this.events(event) : event;
  }

  static expire(data, at) {
    for (const hold of data.holds) {
      if (hold.closed === null && hold.until !== null && utcTime(hold.until) <= at) {
        hold.closed = 'expired';
        hold.closedAt = hold.until;
      }
    }
  }

  static live(lift, at) {
    if (lift.from !== null && lift.from !== undefined && utcTime(lift.from) > at) return false;
    if (lift.until !== null && lift.until !== undefined && utcTime(lift.until) <= at) return false;
    return (lift.left ?? 1) > 0;
  }

  /** Hold `work` for `caller` by `reason`: {hold, statusMessage, push}; push only when this call opened the hold. */
  hold({ caller, work, reason, until = null, message = null, jobId = null, now = null }) {
    const rawCaller = caller;
    caller = text(caller, 'caller');
    work = text(work, 'work');
    reasonOk(reason, 'hold');
    const at = this.now(now);
    if (until !== null && utcTime(instant(until, 'until')) <= utcTime(at)) {
      throw new ServiceError(`until ${until} has passed: the limit no longer holds the work.`);
    }
    const data = this.load();
    HoldBook.expire(data, utcTime(at));
    let hold = data.holds.find((h) => h.closed === null && h.reason === reason && names(rawCaller, h).includes(h.caller));
    const opened = hold === undefined;
    if (opened) {
      hold = { id: newId(), reason, caller, work, since: at, until, jobs: [], closed: null, squash: SQUASH };
      data.holds.push(hold);
    }
    if (jobId !== null && !hold.jobs.includes(String(jobId))) hold.jobs.push(String(jobId));
    this.save(data);
    const statusMessage = waitingMessage(reason, hold.since, hold.until, message);
    const push = opened ? this.emit(HOLD_EVENT_KIND, 'notice', holdSentence(caller, work, reason, until),
      { type: 'limit', id: `${reason}:${caller}`.slice(0, 200), label: REASON_WORDS[reason] }, true) : null;
    return { hold: { ...hold }, statusMessage, push };
  }

  /** Close the open hold of (reason, caller): the limit freed the work. The next hold pushes again. */
  release({ reason, caller, now = null }) {
    const at = this.now(now);
    const data = this.load();
    const hold = data.holds.find((h) => h.closed === null && h.reason === reason && names(caller, h).includes(h.caller));
    if (!hold) return null;
    hold.closed = 'released';
    hold.closedAt = at;
    this.save(data);
    return { ...hold };
  }

  openHolds(now = null) {
    const data = this.load();
    HoldBook.expire(data, utcTime(this.now(now)));
    return data.holds.filter((h) => h.closed === null).map((h) => ({ ...h }));
  }

  /** Record the operator's answer as a scoped lift: exactly one of jobs, usd or limit (limit needs until). */
  lift({ reason, decision, caller = null, jobId = null, jobs = null, usd = null, limit = null, until = null, now = null }) {
    reasonOk(reason, 'lift');
    if (!decisionShape(decision) || decision.action !== LIFT_ACTION) {
      throw new ServiceError("A lift carries the operator's decision (decision.schema.json, action limit.lift, their "
        + "words verbatim): operatorDecision({ action: 'limit.lift', instruction: words }).");
    }
    const sizes = { jobs, usd, limit };
    const given = SIZES.filter((name) => sizes[name] !== null && sizes[name] !== undefined);
    if (given.length !== 1) throw new ServiceError('A lift is one of jobs, usd or limit.');
    const kind = given[0];
    const size = sizes[kind];
    if (typeof size !== 'number' || !Number.isFinite(size) || size <= 0 || (kind !== 'usd' && !Number.isInteger(size))) {
      throw new ServiceError(`A lift's ${kind} is a positive ${kind === 'usd' ? 'number' : 'integer'}.`);
    }
    const at = this.now(now);
    if (until !== null && utcTime(instant(until, 'until')) <= utcTime(at)) throw new ServiceError("A lift's window ends after now.");
    if (kind === 'limit' && until === null) {
      throw new ServiceError('A raised limit needs its window\'s end (until): it falls back when the window ends.');
    }
    const record = { id: newId(), reason, caller: caller === null ? null : text(caller, 'caller'),
      job: jobId === null ? null : String(jobId), from: at, until, [kind]: size, decision: { ...decision }, at, squash: SQUASH };
    if (kind !== 'limit') record.left = size;
    const data = this.load();
    HoldBook.expire(data, utcTime(at));
    for (const hold of data.holds) {
      if (hold.closed === null && hold.reason === reason && (caller === null || names(caller, hold).includes(hold.caller))
        && (jobId === null || hold.jobs.includes(String(jobId)))) {
        hold.closed = 'lifted';
        hold.closedAt = at;
        hold.lift = record.id;
      }
    }
    data.lifts.push(record);
    this.save(data);
    const scope = record.caller ? `for ${record.caller}` : 'for every caller';
    const amount = { jobs: `${size} more job(s)`, usd: `USD ${size} more`, limit: `the limit at ${size}` }[kind];
    this.emit(LIFT_EVENT_KIND, 'info', `The operator lifted ${REASON_WORDS[reason]} ${scope}: ${amount}${until ? ` until ${until}` : ''}.`,
      { type: 'limit', id: `${reason}:${record.caller ?? '*'}`, label: REASON_WORDS[reason] }, false);
    return { ...record };
  }

  static matching(data, reason, caller, jobId, at, kind) {
    return data.lifts.filter((l) => l.reason === reason && kind in l && HoldBook.live(l, at)
      && (l.caller === null || names(caller, l).includes(l.caller)) && (l.job === null || l.job === jobId));
  }

  /** Whether a lift lets work past the limit: {admitted: true, lift, left} spends one job or `costUsd`, else {admitted: false}. */
  admit({ reason, caller, jobId = null, costUsd = null, now = null }) {
    const at = utcTime(this.now(now));
    const data = this.load();
    const kind = costUsd !== null ? 'usd' : 'jobs';
    const found = HoldBook.matching(data, reason, caller, jobId === null ? null : String(jobId), at, kind)
      .sort((a, b) => ((a.job === null) - (b.job === null)) || ((a.caller === null) - (b.caller === null)));
    for (const lift of found) {
      const need = kind === 'usd' ? costUsd : 1;
      if (lift.left >= need) {
        lift.left = kind === 'usd' ? Math.round((lift.left - need) * 1e6) / 1e6 : lift.left - 1;
        this.save(data);
        return { admitted: true, lift: lift.id, left: lift.left };
      }
    }
    return { admitted: false };
  }

  /** The limit in force: `base`, or the highest live raised limit for (reason, caller). */
  limit({ reason, base, caller = null, now = null }) {
    const at = utcTime(this.now(now));
    return Math.max(base, ...HoldBook.matching(this.load(), reason, caller, null, at, 'limit').map((l) => l.limit));
  }

  /** Every lift with `live`: whether it still applies now. */
  lifts(now = null) {
    const at = utcTime(this.now(now));
    return this.load().lifts.map((l) => ({ ...l, live: HoldBook.live(l, at) }));
  }
}
