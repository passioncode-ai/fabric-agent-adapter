// fabric-interop/0.1, the rule layer: the extension's names and limits, its errors, the trace context (C3.4), a usage
// object's reading (C3.2) and the job limits and uncertain effects (DEC-0087). Every function answers by a rule and
// touches no file; fabric-interop.mjs builds the tools, the envelope and the job store on it and re-exports every public
// name here. Part of the Node service kit (FAA-92, split from fabric-interop.mjs; layer L3); the twin of
// fabric_interop_rules.py. Node 20+, no dependency.
import crypto from 'node:crypto';
import { ServiceError } from './fabric-base.mjs';
import { jcs } from './fabric-delegation.mjs';
import { isString } from './fabric-jsvalue.mjs'; // the core's (FAA-65)
import { isObject } from './fabric-jsvalue.mjs'; // the core's (FAA-65)

export const PROTOCOL = 'fabric-interop/0.1';
export const EXTENSION_KEY = 'https://fabric.passioncode.ai/agent-contract/extensions/interop/0.1';
export const MCP_REVISION = '2026-07-28';
export const TERMINAL = ['completed', 'failed', 'cancelled'];
export const CONTRACT_VERSION = '0.1.0';
export const OUTCOMES = ['succeeded', 'partial', 'failed', 'cancelled', 'blocked'];
export const ENVELOPE_REQUIRED = ['id', 'contractVersion', 'outcome', 'done', 'proof', 'scope', 'notVerified', 'artifacts', 'createdAt', 'producer', 'output', 'usage'];
// The job handle inline, as a job tool's outputSchema carries it (contract interop-job-handle.schema.json).
export const JOB_HANDLE_SCHEMA = {
  type: 'object', required: ['job'], additionalProperties: false,
  properties: { job: { type: 'object', required: ['id', 'status'], additionalProperties: false,
    properties: { id: { type: 'string', minLength: 1, maxLength: 128, pattern: '^[A-Za-z0-9._:-]+$' }, status: { const: 'working' } } } },
};

export const TRACEPARENT = /^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$/;
export const JOB_ID = /^[A-Za-z0-9._:-]{1,128}$/;
export const KEY = /^[A-Za-z0-9_.-]{1,64}$/;
export const SECRET_WORDS = /pass(word|phrase)|secret|api[\s_-]?key|access[\s_-]?key|private[\s_-]?key|(access|auth|bearer|refresh|session)[\s_-]?token|^token$|credential/i;
export const USAGE_KEYS = ['inputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens', 'costUsd', 'wallMs'];

export class InteropError extends ServiceError {}
export class UnknownJob extends InteropError {
  constructor(jobId) { super(`unknown-job: no job ${jobId} here.`); this.jobId = jobId; }
}

// --- C3.4 trace context ---------------------------------------------------------------
export function parseTraceparent(value) {
  const m = typeof value === 'string' ? TRACEPARENT.exec(value) : null;
  if (!m) return null;
  const [, version, traceId, spanId, flags] = m;
  if (version === 'ff' || /^0+$/.test(traceId) || /^0+$/.test(spanId)) return null;
  return { version, traceId, spanId, flags };
}

export const spanIdNew = () => { for (;;) { const v = crypto.randomBytes(8).toString('hex'); if (!/^0+$/.test(v)) return v; } };

export function childTraceparent(parent) {
  const p = parseTraceparent(parent);
  return `00-${p ? p.traceId : crypto.randomBytes(16).toString('hex')}-${spanIdNew()}-${p ? p.flags : '01'}`;
}

export const traceIds = (traceparent) => {
  const p = parseTraceparent(traceparent);
  return p ? { traceId: p.traceId, spanId: p.spanId } : {};
};

export function checkUsage(usage, nulls = false) {
  if (!usage || typeof usage !== 'object') throw new InteropError('usage must be an object.');
  for (const key of ['inputTokens', 'outputTokens', 'wallMs']) if (!(key in usage)) throw new InteropError(`usage.${key} is required.`);
  for (const [key, value] of Object.entries(usage)) {
    if (nulls && key === 'partial') {
      if (typeof value !== 'boolean') throw new InteropError('usage.partial must be a boolean.');
      continue;
    }
    if (!USAGE_KEYS.includes(key)) throw new InteropError(`usage.${key} is not a usage field.`);
    if (nulls && value === null) continue;
    const ok = typeof value === 'number' && value >= 0 && (key === 'costUsd' || Number.isInteger(value));
    if (!ok) throw new InteropError(`usage.${key} must be a non-negative ${key === 'costUsd' ? 'number' : 'integer'}.`);
  }
  if (nulls && usageFindings(usage, '').length) throw new InteropError('usage.partial is false while a number is null: an unknown number makes the usage partial (FAC-SEM-119).');
  return { ...usage };
}
// --- C3.2 limits and uncertain effects (DEC-0087) ------------------------------------------
// #region job-limits-kit-node, docs: plugins/fabric-agent-adapter/skills/building-fabric-services/references/interop.md#limits-and-uncertain-effects
// The contract's src/job-limits.ts, answer for answer (test/fixtures/contract/job-limit-vectors.json), the twin of
// fabric_interop.py. Every function here answers and never throws on malformed input.

export const QUOTA_EXHAUSTED = 'quota-exhausted';
/** DEC-0104: a refusal at a job's start; a job it ended is malformed, so a caller answers it `invalid`. */
export const QUEUE_FULL = 'queue-full';
export const OUTCOME_UNKNOWN = 'outcome-unknown';
export const LIMIT_REACHED = 'limit-reached';
export const INTEROP_NULL_USAGE = 'fabric-interop/0.2';
/** The revisions this kit reads, named in a request's `_meta.protocols` (DEC-0067, DEC-0087). */
export const PROTOCOLS_READ = Object.freeze(['fabric-interop/0.1', INTEROP_NULL_USAGE]);
export const JOB_STATUSES = ['working', 'input_required', 'completed', 'failed', 'cancelled'];
export const UTC_INSTANT = /^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-5][0-9])(?:\.([0-9]{1,3}))?Z$/;
export const PAUSE = /^quota-exhausted(?: until ([^ \t\n\r]+?))?(?:: ([ \t\n\r]*[^ \t\n\r][\s\S]*))?$/;
export const ERROR_CODE = /^[a-z][a-z0-9-]{1,63}$/;
export const MAX_STATUS_MESSAGE = 500;
export const MAX_ERROR_MESSAGE = 2000;
export const codePoints = (value) => [...value].length;
export const own = (value, key) => (isObject(value) && Object.hasOwn(value, key) ? value[key] : undefined);

/** A UTC instant as milliseconds, or NaN: the pattern and a day that exists, as the contract's strictTime reads it. */
export function utcTime(value) {
  const m = isString(value) ? UTC_INSTANT.exec(value) : null;
  if (!m) return Number.NaN;
  const [year, month, day, hour, minute, second] = m.slice(1, 7).map(Number);
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  if (date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day || hour > 23 || minute > 59) return Number.NaN;
  date.setUTCHours(hour, minute, second, Number((m[7] ?? '').padEnd(3, '0')));
  return date.getTime();
}

export function quotaDataOk(data) {
  const retryable = own(data, 'retryable');
  if (!isObject(data) || typeof retryable !== 'boolean') return false;
  if (Object.keys(data).some((name) => name !== 'retryable' && name !== 'resetsAt')) return false;
  if (!Object.hasOwn(data, 'resetsAt')) return true;
  return retryable && Number.isFinite(utcTime(own(data, 'resetsAt')));
}

export function jobOf(answer) {
  const job = own(answer, 'job');
  const id = own(job, 'id');
  if (!isObject(job) || !isString(id) || id.length === 0 || !JOB_STATUSES.includes(own(job, 'status'))) return undefined;
  return job;
}

export function readJobPause(answer) {
  const job = jobOf(answer);
  const message = own(job, 'statusMessage');
  if (!job || own(job, 'status') !== 'working' || !isString(message) || !message.startsWith(QUOTA_EXHAUSTED)) return { paused: false };
  const match = PAUSE.exec(message);
  if (!match || codePoints(message) > MAX_STATUS_MESSAGE) return { paused: false, malformed: true };
  const until = match[1];
  if (until === undefined) return { paused: true };
  return Number.isFinite(utcTime(until)) ? { paused: true, resetsAt: until } : { paused: false, malformed: true };
}

/** What a caller does with one fabric.job.get or fabric.job.cancel answer at `now`; never "submit anew". */
export function jobCallerAction(answer, now) {
  const at = utcTime(now);
  const job = jobOf(answer);
  if (!Number.isFinite(at) || !job) return { action: 'invalid' };
  const status = own(job, 'status');
  if (status === 'working') {
    const pause = readJobPause(answer);
    if ('malformed' in pause) return { action: 'invalid' };
    if (!pause.paused) return { action: 'poll' };
    if (pause.resetsAt === undefined) return { action: 'wait' };
    return utcTime(pause.resetsAt) > at ? { action: 'wait', notBefore: pause.resetsAt } : { action: 'poll' };
  }
  if (status === 'input_required') return { action: 'answer' };
  if (status === 'completed') return { action: 'done' };
  if (status === 'cancelled') return { action: 'cancelled' };
  const error = own(job, 'error');
  const code = own(error, 'code');
  const message = own(error, 'message');
  const codeOk = (isString(code) && ERROR_CODE.test(code)) || Number.isInteger(code);
  const shapeOk = isObject(error) && Object.keys(error).every((name) => name === 'code' || name === 'message' || name === 'data');
  if (!shapeOk || !codeOk || !isString(message) || message.length === 0 || codePoints(message) > MAX_ERROR_MESSAGE) return { action: 'invalid' };
  if (code === QUEUE_FULL) return { action: 'invalid' };
  if (code === OUTCOME_UNKNOWN) return { action: 'reconcile' };
  if (code === LIMIT_REACHED) return { action: 'person' };
  if (code !== QUOTA_EXHAUSTED) return { action: 'failed' };
  const data = own(error, 'data');
  if (!quotaDataOk(data)) return { action: 'invalid' };
  if (!data.retryable) return { action: 'person' };
  return data.resetsAt !== undefined && utcTime(data.resetsAt) > at ? { action: 'resend', notBefore: data.resetsAt } : { action: 'resend' };
}

/** The idempotency key of an intent {agentId, capability, input, request?}: a UUID of version 8 over its RFC 8785 form. */
export function intentIdempotencyKey(intent) {
  const names = ['agentId', 'capability', 'input', 'request'];
  if (!isObject(intent) || Object.keys(intent).some((name) => !names.includes(name))) return undefined;
  const [agentId, capability, input, request] = names.map((name) => own(intent, name));
  if (!isString(agentId) || agentId.length === 0 || !isString(capability) || capability.length === 0 || !isObject(input)) return undefined;
  if (Object.hasOwn(intent, 'request') && (!isString(request) || request.length === 0 || codePoints(request) > 256)) return undefined;
  let form;
  try {
    form = jcs(Object.hasOwn(intent, 'request') ? { agentId, capability, input, request } : { agentId, capability, input });
  } catch {
    return undefined;
  }
  const bytes = crypto.createHash('sha256').update(form, 'utf8').digest().subarray(0, 16);
  bytes[6] = (bytes[6] & 0x0f) | 0x80;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString('hex');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function readsNullUsage(requestMeta) {
  const protocols = own(requestMeta, 'protocols');
  return Array.isArray(protocols) && protocols.includes(INTEROP_NULL_USAGE);
}

/** A request's `_meta` from this kit as a caller: its trace, and the interop revisions it reads (DEC-0087). */
export function requestMeta(traceparent) {
  const meta = { protocols: [...PROTOCOLS_READ] };
  if (parseTraceparent(traceparent)) meta.traceparent = traceparent;
  return meta;
}

/** FAC-SEM-119 on a usage: partial false asserts every number known, so it stands beside no null. */
export function usageFindings(usage, at) {
  if (!isObject(usage) || usage.partial !== false) return [];
  const unknown = USAGE_KEYS.filter((name) => Object.hasOwn(usage, name) && usage[name] === null);
  if (unknown.length === 0) return [];
  return [{ code: 'FAC-SEM-119', instancePath: `${at}/partial`, message: `partial is false while ${unknown.join(', ')} is null: an unknown number makes the usage partial` }];
}

/** The usage a provider writes toward a caller: null and partial toward a 0.2 reader, the measured lower bound otherwise. */
export function usageToward(usage, meta) {
  if (readsNullUsage(meta)) {
    const checked = checkUsage(usage, true);
    if (USAGE_KEYS.some((name) => checked[name] === null) && !('partial' in checked)) checked.partial = true;
    return checked;
  }
  if (!isObject(usage)) throw new InteropError('usage must be an object.');
  return checkUsage(Object.fromEntries(Object.entries(usage).filter(([key]) => key !== 'partial').map(([key, value]) => [key, value === null ? 0 : value])));
}

export function jobFindings(value) {
  const findings = [];
  if ('malformed' in readJobPause(value)) {
    findings.push({ code: 'FAC-SEM-119', instancePath: '/job/statusMessage', message: "a working job's message that starts quota-exhausted reads `quota-exhausted`, `quota-exhausted until <UTC instant>`, then optionally `: <text>`, at most 500 characters" });
  }
  const error = own(own(value, 'job'), 'error');
  const data = own(error, 'data');
  if (own(error, 'code') === QUOTA_EXHAUSTED && isString(own(data, 'resetsAt')) && !Number.isFinite(utcTime(own(data, 'resetsAt')))) {
    findings.push({ code: 'FAC-SEM-119', instancePath: '/job/error/data/resetsAt', message: 'resetsAt is a UTC instant on a day that exists' });
  }
  findings.push(...usageFindings(own(own(own(value, 'job'), 'result'), 'usage'), '/job/result/usage'));
  return findings;
}

export const sameJson = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** FAC-SEM-119 (kinds interop-job, usage and result) and FAC-SEM-120 (kind job-caller); undefined for another kind. */
export function jobLimitRules(kind, value) {
  if (kind === 'interop-job') return jobFindings(value);
  if (kind === 'usage') return usageFindings(value, '');
  if (kind === 'result') return usageFindings(own(value, 'usage'), '/usage');
  if (kind === 'job-caller') {
    const expected = jobCallerAction(own(value, 'answer'), own(value, 'now'));
    return sameJson(own(value, 'action'), expected) ? [] : [{ code: 'FAC-SEM-120', instancePath: '/action', message: `the caller answers ${JSON.stringify(expected)} as jobCallerAction does` }];
  }
  return undefined;
}

/** A paused job's statusMessage in the pause grammar; throws InteropError for one a reader would call malformed. */
export function pauseMessage({ resetsAt, text } = {}) {
  const message = `${QUOTA_EXHAUSTED}${resetsAt === undefined ? '' : ` until ${resetsAt}`}${text === undefined ? '' : `: ${text}`}`;
  if ('malformed' in readJobPause({ job: { id: 'x', status: 'working', statusMessage: message } })) {
    throw new InteropError('A pause reads quota-exhausted [until <UTC instant, Z, at most 3 fraction digits>][: <text>], at most 500 characters.');
  }
  return message;
}

/** The provider's answer to a repeated key: 'run' (the intent runs again, once) or 'same' (answer with that job). */
export function repeatedKeyDecision(job, now, { limitHolds, approvalGranted = false } = {}) {
  if (!isObject(job) || job.status !== 'failed') return 'same';
  const error = own(job, 'error');
  const code = own(error, 'code');
  if (code === LIMIT_REACHED) return approvalGranted === true ? 'run' : 'same';
  if (code !== QUOTA_EXHAUSTED) return 'same';
  if (limitHolds !== undefined && limitHolds !== null) return limitHolds === false ? 'run' : 'same';
  const data = own(error, 'data');
  const at = utcTime(now);
  if (!quotaDataOk(data) || !data.retryable || !Number.isFinite(at)) return 'same';
  return data.resetsAt === undefined || utcTime(data.resetsAt) <= at ? 'run' : 'same';
}
// #endregion job-limits-kit-node
