// Reference kit for the fabric-interop/0.1 extension — Node.js 20+, no dependencies.
// The Node twin of fabric_interop.py: the same rules and the same job file format, so a
// job written by one kit is read by the other. The minimal MCP dispatcher is Python-only;
// a Node service uses the official MCP SDK for the wire and these helpers for the rules.
// Normative source: fabric-agent-contract docs/specification/interop.md (DEC-0016, rulings DEC-0017).
// #region interop-kit-node — docs: plugins/fabric-agent-adapter/skills/building-fabric-services/references/interop.md#the-kit

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { ServiceError, atomicWrite, ensurePrivateDir, nowIso } from './fabric-service.mjs';
import { jcs } from './fabric-delegation.mjs';

export const PROTOCOL = 'fabric-interop/0.1';
export const EXTENSION_KEY = 'https://fabric.passioncode.ai/agent-contract/extensions/interop/0.1';
export const MCP_REVISION = '2026-07-28';
export const TERMINAL = ['completed', 'failed', 'cancelled'];
export const CONTRACT_VERSION = '0.1.0';
const OUTCOMES = ['succeeded', 'partial', 'failed', 'cancelled', 'blocked'];
const ENVELOPE_REQUIRED = ['id', 'contractVersion', 'outcome', 'done', 'proof', 'scope', 'notVerified', 'artifacts', 'createdAt', 'producer', 'output', 'usage'];
// The job handle inline, as a job tool's outputSchema carries it (contract interop-job-handle.schema.json).
export const JOB_HANDLE_SCHEMA = {
  type: 'object', required: ['job'], additionalProperties: false,
  properties: { job: { type: 'object', required: ['id', 'status'], additionalProperties: false,
    properties: { id: { type: 'string', minLength: 1, maxLength: 128, pattern: '^[A-Za-z0-9._:-]+$' }, status: { const: 'working' } } } },
};

const TRACEPARENT = /^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$/;
const JOB_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const KEY = /^[A-Za-z0-9_.-]{1,64}$/;
const SECRET_WORDS = /pass(word|phrase)|secret|api[\s_-]?key|access[\s_-]?key|private[\s_-]?key|(access|auth|bearer|refresh|session)[\s_-]?token|^token$|credential/i;
const USAGE_KEYS = ['inputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens', 'costUsd', 'wallMs'];

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

const spanIdNew = () => { for (;;) { const v = crypto.randomBytes(8).toString('hex'); if (!/^0+$/.test(v)) return v; } };

export function childTraceparent(parent) {
  const p = parseTraceparent(parent);
  return `00-${p ? p.traceId : crypto.randomBytes(16).toString('hex')}-${spanIdNew()}-${p ? p.flags : '01'}`;
}

export const traceIds = (traceparent) => {
  const p = parseTraceparent(traceparent);
  return p ? { traceId: p.traceId, spanId: p.spanId } : {};
};

// --- C3.1 capabilities as tools ----------------------------------------------------------
export function expectedAnnotations(effect, idempotency) {
  const hints = {};
  if (effect === 'none') hints.readOnlyHint = true;
  if (['delete', 'merge', 'deploy', 'change-policy'].includes(effect)) hints.destructiveHint = true;
  if (idempotency === 'required') hints.idempotentHint = true;
  return hints;
}

// DEC-0017: a job-backed tool serves oneOf[result envelope, job handle]; the manifest keeps the pure output schema.
export const jobToolOutputSchema = (outputSchema) => ({ type: 'object', oneOf: [{ type: 'object', required: [...ENVELOPE_REQUIRED], properties: { output: outputSchema } }, JOB_HANDLE_SCHEMA] });
export const isJobCapability = (capability) => capability.job === true || capability.extensions?.[EXTENSION_KEY]?.job === true;

// DEC-0018 (FAC-SEM-023): an outputSchema is rooted at type object; a client may reject the whole
// tools/list when one tool's outputSchema is, say, a bare oneOf.
export function requireObjectRoot(name, outputSchema) {
  if (!outputSchema || typeof outputSchema !== 'object' || outputSchema.type !== 'object') throw new InteropError(`Tool ${name}: an outputSchema must have root type "object".`);
}

export function toolForCapability(capability, inputSchema, outputSchema, title) {
  requireObjectRoot(capability.name, outputSchema);
  const served = isJobCapability(capability) ? jobToolOutputSchema(outputSchema) : outputSchema;
  const tool = { name: capability.name, inputSchema, outputSchema: served, annotations: expectedAnnotations(capability.effect, capability.idempotency) };
  if (capability.description) tool.description = capability.description;
  if (title) tool.title = title;
  return tool;
}

export function toolResult(structured, { isError = false, traceparent } = {}) {
  const result = { resultType: 'complete', content: [{ type: 'text', text: JSON.stringify(structured) }], structuredContent: structured, isError };
  if (traceparent) result._meta = { traceparent };
  return result;
}

export const unknownJobResult = (jobId, traceparent) =>
  toolResult({ error: { code: 'unknown-job', message: `No job ${jobId} here.` } }, { isError: true, traceparent });

// --- C3.2 the result envelope --------------------------------------------------------------
function checkUsage(usage, nulls = false) {
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

// The full result envelope (contract result.schema.json, DEC-0017): the shape a synchronous call returns.
export function resultEnvelope({ outcome, done, proof, scope, notVerified, output, usage, producer, artifacts = [], traceparent, id, createdAt, requestMeta }) {
  if (!OUTCOMES.includes(outcome)) throw new InteropError(`outcome must be one of ${OUTCOMES.join(', ')}.`);
  for (const [label, value] of [['done', done], ['proof', proof], ['notVerified', notVerified], ['artifacts', artifacts]]) {
    if (!Array.isArray(value)) throw new InteropError(`${label} must be a list, even when empty.`);
  }
  if (outcome === 'succeeded' && notVerified.length) throw new InteropError('A succeeded result cannot keep unverified claims (FAC-SEM-001); report partial.');
  if (!scope || typeof scope !== 'object' || !producer || typeof producer !== 'object') throw new InteropError('scope and producer must be objects.');
  const envelope = {
    id: id ?? `urn:fabric:result:${crypto.randomBytes(12).toString('hex')}`, contractVersion: CONTRACT_VERSION, outcome,
    done: [...done], proof: [...proof], scope: { ...scope }, notVerified: [...notVerified], artifacts: [...artifacts],
    createdAt: createdAt ?? nowIso(), producer: { ...producer }, output, usage: usageToward(usage, requestMeta),
  };
  if (parseTraceparent(traceparent)) envelope.trace = { traceparent };
  return envelope;
}

// --- C3.2 limits and uncertain effects (DEC-0087) ------------------------------------------
// #region job-limits-kit-node, docs: plugins/fabric-agent-adapter/skills/building-fabric-services/references/interop.md#limits-and-uncertain-effects
// The contract's src/job-limits.ts, answer for answer (test/fixtures/contract/job-limit-vectors.json), the twin of
// fabric_interop.py. Every function here answers and never throws on malformed input.

export const QUOTA_EXHAUSTED = 'quota-exhausted';
export const OUTCOME_UNKNOWN = 'outcome-unknown';
export const LIMIT_REACHED = 'limit-reached';
export const INTEROP_NULL_USAGE = 'fabric-interop/0.2';
/** The revisions this kit reads, named in a request's `_meta.protocols` (DEC-0067, DEC-0087). */
export const PROTOCOLS_READ = Object.freeze(['fabric-interop/0.1', INTEROP_NULL_USAGE]);
const JOB_STATUSES = ['working', 'input_required', 'completed', 'failed', 'cancelled'];
const UTC_INSTANT = /^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-5][0-9])(?:\.([0-9]{1,3}))?Z$/;
const PAUSE = /^quota-exhausted(?: until ([^ \t\n\r]+?))?(?:: ([ \t\n\r]*[^ \t\n\r][\s\S]*))?$/;
const ERROR_CODE = /^[a-z][a-z0-9-]{1,63}$/;
const MAX_STATUS_MESSAGE = 500;
const MAX_ERROR_MESSAGE = 2000;
const codePoints = (value) => [...value].length;
import { isString } from './fabric-jsvalue.mjs'; // the core's (FAA-65)
import { isObject } from './fabric-jsvalue.mjs'; // the core's (FAA-65)
const own = (value, key) => (isObject(value) && Object.hasOwn(value, key) ? value[key] : undefined);

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

function jobOf(answer) {
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

function jobFindings(value) {
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

const sameJson = (a, b) => JSON.stringify(a) === JSON.stringify(b);

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

// --- C3.3 awaiting a choice ------------------------------------------------------------------
export function formRequest(message, properties, required) {
  for (const [field, schema] of Object.entries(properties)) {
    const words = ['title', 'description', 'format'].map((k) => schema[k] ?? '').join(' ');
    if (SECRET_WORDS.test(field) || SECRET_WORDS.test(words)) throw new InteropError(`Form mode cannot ask for ${field}: a secret goes through urlRequest.`);
    if (!['string', 'number', 'integer', 'boolean', 'array'].includes(schema.type)) throw new InteropError(`Form field ${field} must be a primitive.`);
  }
  const requestedSchema = { type: 'object', properties };
  if (required?.length) requestedSchema.required = [...required];
  return { method: 'elicitation/create', params: { mode: 'form', message, requestedSchema } };
}

export function choiceRequest(message, field, options, title) {
  const schema = { type: 'string', oneOf: options.map(([value, label]) => ({ const: value, title: label })) };
  if (title) schema.title = title;
  return formRequest(message, { [field]: schema }, [field]);
}

export function urlRequest(message, url) {
  if (!/^(https:\/\/|http:\/\/127\.0\.0\.1|http:\/\/localhost)/.test(url)) throw new InteropError('A URL-mode request needs an https URL (or this machine\'s loopback).');
  return { method: 'elicitation/create', params: { mode: 'url', message, url } };
}

// --- C3.2 jobs: the same file format as fabric_interop.JobStore ------------------------------
const LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;

/** What a key is kept beside (FAA-77): sha256 of the RFC 8785 form of [capability, input]; an input with none is refused. */
export function intentDigest(capability, input) {
  let form;
  try { form = jcs([capability, input]); } catch { throw new InteropError("A job's input with an idempotency key needs a JSON form (RFC 8785)."); }
  return `sha256:${crypto.createHash('sha256').update(form, 'utf8').digest('hex')}`;
}

export class JobStore {
  constructor(dir) { this.dir = dir; }

  file(jobId) {
    if (!JOB_ID.test(jobId ?? '')) throw new UnknownJob(String(jobId));
    return path.join(this.dir, `${jobId}.json`);
  }

  load(jobId) {
    let text;
    try { text = fs.readFileSync(this.file(jobId), 'utf8'); } catch (e) { if (e.code === 'ENOENT') throw new UnknownJob(jobId); throw e; }
    try { return JSON.parse(text); } catch { throw new InteropError(`Job ${jobId} is unreadable on disk.`); }
  }

  save(record) {
    record.job.updatedAt = nowIso();
    ensurePrivateDir(this.dir);
    atomicWrite(this.file(record.job.id), `${JSON.stringify(record)}\n`, 0o600);
    return { ...record.job };
  }

  // With idempotencyKey the key is kept per caller (the authenticated caller, DEC-0087): a key that already names a job
  // starts nothing and throws, unless repeat() answers 'run'; then the key names the new job.
  // The key is kept beside the intent's digest (FAA-77): a key that names a job of another intent is idempotency-conflict.
  // A key file a kit before 0.41.0 wrote carries no intent: it is answered with its job as 0.40.0 answered it (see repeat).
  create(capability, input, { traceparent, pollIntervalMs, caller = null, idempotencyKey, now, limitHolds, approvalGranted = false } = {}) {
    let intent = null;
    if (idempotencyKey !== undefined) {
      intent = intentDigest(capability, input);
      const decision = this.repeat(caller, idempotencyKey, now ?? nowIso(), { limitHolds, approvalGranted, capability, input });
      if (decision.decision === 'conflict') throw new InteropError(`idempotency-conflict: key ${idempotencyKey} names a job of another intent; send the same capability and input, or a new key.`);
      if (decision.decision === 'same') throw new InteropError(`Key ${idempotencyKey} already names job ${decision.job.id}; answer with that job (JobStore.repeat).`);
    }
    const id = `job_${crypto.randomBytes(12).toString('hex')}`;
    const job = { id, status: 'working' };
    if (pollIntervalMs) job.pollIntervalMs = Math.trunc(pollIntervalMs);
    this.save({ job, private: { capability, input, traceparent: parseTraceparent(traceparent) ? traceparent : null } });
    if (idempotencyKey !== undefined) atomicWrite(this.keyFile(caller, idempotencyKey), `${JSON.stringify({ job: id, intent })}\n`, 0o600);
    return { job: { id, status: 'working' } };
  }

  keyFile(caller, key) {
    if (typeof key !== 'string' || key.length === 0) throw new InteropError('An idempotency key is a non-empty string.');
    if (LONE_SURROGATE.test(key) || (typeof caller === 'string' && LONE_SURROGATE.test(caller))) throw new InteropError('An idempotency key and its caller are Unicode text; a lone surrogate is refused.');
    const dir = path.join(this.dir, 'keys');
    ensurePrivateDir(dir);
    return path.join(dir, `${crypto.createHash('sha256').update(JSON.stringify([caller ?? null, key]), 'utf8').digest('hex')}.json`);
  }

  keyRecord(caller, key) {
    let record;
    try { record = JSON.parse(fs.readFileSync(this.keyFile(caller, key), 'utf8')); } catch (e) {
      if (e.code === 'ENOENT') return null;
      if (e instanceof InteropError) throw e;
    }
    if (record === null || typeof record !== 'object' || Array.isArray(record)) throw new InteropError(`Key ${key} is unreadable on disk.`);
    return record;
  }

  // The answer to a key this caller sent before: {decision: 'new'|'same'|'run'|'conflict', job}. 'same': answer with
  // that job; 'run': the intent runs again, once; 'conflict': given options.capability (and options.input), the key was
  // kept beside another intent (idempotency-conflict, FAA-77). A key file a kit before 0.41.0 wrote holds only
  // {"job": id}, no intent: it never answers 'conflict', and 'run' only for the intent its job stored; otherwise 'same'.
  repeat(caller, key, now, options = {}) {
    const record = this.keyRecord(caller, key);
    if (record === null) return { decision: 'new', job: null };
    const id = record.job;
    if (typeof id !== 'string') throw new InteropError(`Key ${key} is unreadable on disk.`);
    let job;
    try { job = this.get(id); } catch (e) { if (e instanceof UnknownJob) return { decision: 'new', job: null }; throw e; }
    let decision = repeatedKeyDecision(job, now, options);
    if (options.capability === undefined || options.capability === null) return { decision, job };
    const intent = intentDigest(options.capability, options.input ?? null);
    if (Object.hasOwn(record, 'intent')) return { decision: record.intent !== intent ? 'conflict' : decision, job };
    if (decision === 'run' && this.storedIntent(id) !== intent) decision = 'same'; // a legacy key admits no run it cannot vouch for
    return { decision, job };
  }

  // The intent a job was started with, from its private part; null when it has no RFC 8785 form.
  storedIntent(jobId) {
    const stored = this.load(jobId).private ?? {};
    try { return intentDigest(stored.capability ?? null, stored.input ?? null); } catch (e) { if (e instanceof InteropError) return null; throw e; }
  }

  get(jobId) { return { ...this.load(jobId).job }; }
  traceparent(jobId) { return this.load(jobId).private.traceparent ?? null; }

  transition(jobId, status, fields = {}) {
    const record = this.load(jobId);
    if (TERMINAL.includes(record.job.status)) throw new InteropError(`Job ${jobId} is already ${record.job.status}; a terminal job does not change.`);
    for (const key of ['inputRequests', 'result', 'error', 'statusMessage']) delete record.job[key];
    record.job.status = status;
    for (const [key, value] of Object.entries(fields)) if (value !== undefined && value !== null) record.job[key] = value;
    return this.save(record);
  }

  working(jobId, statusMessage) { return this.transition(jobId, 'working', { statusMessage }); }

  requestInput(jobId, inputRequests, statusMessage) {
    const entries = Object.entries(inputRequests ?? {});
    if (!entries.length) throw new InteropError('input_required needs at least one input request.');
    for (const [key, request] of entries) if (!KEY.test(key) || request?.method !== 'elicitation/create') throw new InteropError(`Input request ${key} must be a keyed elicitation/create request.`);
    return this.transition(jobId, 'input_required', { inputRequests, statusMessage });
  }

  answer(jobId, inputResponses) {
    const job = this.get(jobId);
    if (job.status !== 'input_required') return {};
    const matched = Object.fromEntries(Object.entries(inputResponses ?? {}).filter(([key, value]) =>
      key in (job.inputRequests ?? {}) && ['accept', 'decline', 'cancel'].includes(value?.action)));
    if (Object.keys(matched).length) this.working(jobId);
    return matched;
  }

  // The envelope carries the job's trace, authoritative for the stored result (DEC-0017, FAC-SEM-022).
  complete(jobId, envelope) {
    if (!envelope || !ENVELOPE_REQUIRED.every((k) => k in envelope)) throw new InteropError('A completed job carries the full result envelope; build it with resultEnvelope.');
    const stored = this.traceparent(jobId);
    const given = envelope.trace?.traceparent;
    const ids = (v) => { const p = parseTraceparent(v); return p ? `${p.traceId}-${p.spanId}` : null; };
    if (stored && given && ids(given) !== ids(stored)) throw new InteropError(`Job ${jobId} ran in span ${stored}; its result names another trace.`);
    const result = stored && !given ? { ...envelope, trace: { traceparent: stored } } : envelope;
    return this.transition(jobId, 'completed', { result });
  }

  fail(jobId, code, message, data) { return this.transition(jobId, 'failed', { error: data === undefined || data === null ? { code, message } : { code, message, data } }); }

  // A job a limit paused and its provider will resume: working, the pause grammar, pollIntervalMs reaching the reset.
  pause(jobId, { resetsAt, text } = {}) {
    const statusMessage = pauseMessage({ resetsAt, text });
    const wait = resetsAt === undefined ? 0 : utcTime(resetsAt) - Date.now();
    // One write, after the terminal check: a terminal job does not change, pollIntervalMs included (finding 11).
    return this.transition(jobId, 'working', { statusMessage, pollIntervalMs: wait > 0 ? Math.trunc(Math.min(wait, 3600000)) : undefined });
  }

  // A job a limit stopped and its provider will not resume: failed, quota-exhausted, data {retryable, resetsAt?}.
  quotaExhausted(jobId, message, { retryable, resetsAt } = {}) {
    const data = resetsAt === undefined ? { retryable } : { retryable, resetsAt };
    if (!quotaDataOk(data)) throw new InteropError('quota-exhausted data is {retryable: boolean, resetsAt?: UTC instant}, resetsAt only with retryable true.');
    return this.fail(jobId, QUOTA_EXHAUSTED, message, data);
  }

  // A job whose effect may have happened: failed, outcome-unknown; its key never runs again.
  outcomeUnknown(jobId, message, data) { return this.fail(jobId, OUTCOME_UNKNOWN, message, data); }
  cancel(jobId) { return this.transition(jobId, 'cancelled'); }
}
// #endregion interop-kit-node

// --- MCP 2026-07-28 standard headers ------------------------------------------------------

export const NAMED_METHODS = { 'tools/call': 'name', 'prompts/get': 'name', 'resources/read': 'uri' };
export const HEADER_MISMATCH = -32020; // the code the official 2026-07-28 server SDK answers a header/body mismatch with

const SENTINEL = ['=?base64?', '?='];

/**
 * A body value as an HTTP header value, by MCP 2026-07-28 Streamable HTTP "Value Encoding": as it
 * is when it is printable ASCII without leading or trailing whitespace, otherwise — and for a plain
 * value that itself looks like the sentinel — `=?base64?<base64 of its UTF-8>?=`.
 */
export function encodeHeaderValue(value) {
  const s = String(value);
  const plain = /^[\x20-\x7e]*$/.test(s) && s === s.replace(/^ +| +$/g, '') && !(s.startsWith(SENTINEL[0]) && s.endsWith(SENTINEL[1]));
  if (plain) return s;
  let binary = '';
  for (const byte of new TextEncoder().encode(s)) binary += String.fromCharCode(byte);
  return SENTINEL[0] + btoa(binary) + SENTINEL[1];
}

/** The body value a header carries, decoding the Base64 sentinel; null for invalid characters or a
 *  sentinel that is not valid Base64 of UTF-8 (a server rejects both). */
export function decodeHeaderValue(value) {
  const s = String(value);
  if (s.startsWith(SENTINEL[0]) && s.endsWith(SENTINEL[1]) && s.length >= SENTINEL[0].length + SENTINEL[1].length) {
    const body = s.slice(SENTINEL[0].length, -SENTINEL[1].length);
    if (body.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(body)) return null;
    try {
      const bytes = Uint8Array.from(atob(body), (c) => c.charCodeAt(0));
      return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    } catch { return null; }
  }
  return /^[\x20-\x7e\t]*$/.test(s) ? s : null;
}

/**
 * MCP 2026-07-28 Streamable HTTP mirrors the body in `Mcp-Method` (every request and
 * notification) and `Mcp-Name` (`params.name` or `params.uri` of tools/call, prompts/get,
 * resources/read). A server MUST reject a mismatch; a request that declares 2026-07-28 must carry
 * them. Returns the problem as a sentence, or null. `headers` is a plain object (any case) or a
 * Headers instance.
 */
export function mcpHeaderProblem(message, headers) {
  if (!message || typeof message !== 'object' || !headers) return null;
  const header = (name) => {
    if (typeof headers.get === 'function') return headers.get(name) ?? null;
    const key = Object.keys(headers).find((k) => k.toLowerCase() === name.toLowerCase());
    const value = key === undefined ? undefined : headers[key];
    return value === undefined ? null : String(Array.isArray(value) ? value[0] : value);
  };
  const declared = header('MCP-Protocol-Version') === MCP_REVISION;
  const { method } = message;
  const sent = header('Mcp-Method');
  if (sent === null && declared) return `the body names method ${method} but the required Mcp-Method header is absent`;
  if (sent !== null && sent !== method) return `Mcp-Method ${sent} disagrees with the body's method ${method}`;
  const field = NAMED_METHODS[method];
  if (field) {
    const named = header('Mcp-Name');
    if (named === null && declared) return `the body carries params.${field} but the required Mcp-Name header is absent`;
    if (named !== null) {
      const decoded = decodeHeaderValue(named);
      if (decoded === null) return 'Mcp-Name is malformed: invalid characters or a broken =?base64?…?= value';
      if (decoded !== String(message.params?.[field])) return `Mcp-Name disagrees with the body's params.${field}`;
    }
  }
  return null;
}

/** The standard headers a 2026-07-28 client sends with one request. */
export function mcpRequestHeaders(method, params = {}) {
  const out = { 'MCP-Protocol-Version': MCP_REVISION, 'Mcp-Method': method };
  const field = NAMED_METHODS[method];
  if (field && params[field] !== undefined && params[field] !== null) out['Mcp-Name'] = encodeHeaderValue(params[field]);
  return out;
}
