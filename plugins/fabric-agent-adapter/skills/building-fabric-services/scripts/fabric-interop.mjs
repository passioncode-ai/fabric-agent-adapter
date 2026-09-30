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
export const jobToolOutputSchema = (outputSchema) => ({ oneOf: [{ type: 'object', required: [...ENVELOPE_REQUIRED], properties: { output: outputSchema } }, JOB_HANDLE_SCHEMA] });
export const isJobCapability = (capability) => capability.job === true || capability.extensions?.[EXTENSION_KEY]?.job === true;

export function toolForCapability(capability, inputSchema, outputSchema, title) {
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
function checkUsage(usage) {
  if (!usage || typeof usage !== 'object') throw new InteropError('usage must be an object.');
  for (const key of ['inputTokens', 'outputTokens', 'wallMs']) if (!(key in usage)) throw new InteropError(`usage.${key} is required.`);
  for (const [key, value] of Object.entries(usage)) {
    if (!USAGE_KEYS.includes(key)) throw new InteropError(`usage.${key} is not a usage field.`);
    const ok = typeof value === 'number' && value >= 0 && (key === 'costUsd' || Number.isInteger(value));
    if (!ok) throw new InteropError(`usage.${key} must be a non-negative ${key === 'costUsd' ? 'number' : 'integer'}.`);
  }
  return { ...usage };
}

// The full result envelope (contract result.schema.json, DEC-0017): the shape a synchronous call returns.
export function resultEnvelope({ outcome, done, proof, scope, notVerified, output, usage, producer, artifacts = [], traceparent, id, createdAt }) {
  if (!OUTCOMES.includes(outcome)) throw new InteropError(`outcome must be one of ${OUTCOMES.join(', ')}.`);
  for (const [label, value] of [['done', done], ['proof', proof], ['notVerified', notVerified], ['artifacts', artifacts]]) {
    if (!Array.isArray(value)) throw new InteropError(`${label} must be a list, even when empty.`);
  }
  if (outcome === 'succeeded' && notVerified.length) throw new InteropError('A succeeded result cannot keep unverified claims (FAC-SEM-001); report partial.');
  if (!scope || typeof scope !== 'object' || !producer || typeof producer !== 'object') throw new InteropError('scope and producer must be objects.');
  const envelope = {
    id: id ?? `urn:fabric:result:${crypto.randomBytes(12).toString('hex')}`, contractVersion: CONTRACT_VERSION, outcome,
    done: [...done], proof: [...proof], scope: { ...scope }, notVerified: [...notVerified], artifacts: [...artifacts],
    createdAt: createdAt ?? nowIso(), producer: { ...producer }, output, usage: checkUsage(usage),
  };
  if (parseTraceparent(traceparent)) envelope.trace = { traceparent };
  return envelope;
}

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

  create(capability, input, { traceparent, pollIntervalMs } = {}) {
    const id = `job_${crypto.randomBytes(12).toString('hex')}`;
    const job = { id, status: 'working' };
    if (pollIntervalMs) job.pollIntervalMs = Math.trunc(pollIntervalMs);
    this.save({ job, private: { capability, input, traceparent: parseTraceparent(traceparent) ? traceparent : null } });
    return { job: { id, status: 'working' } };
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

  fail(jobId, code, message) { return this.transition(jobId, 'failed', { error: { code, message } }); }
  cancel(jobId) { return this.transition(jobId, 'cancelled'); }
}
// #endregion interop-kit-node
