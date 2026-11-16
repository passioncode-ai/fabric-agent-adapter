// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
// fabric-interop/0.1, the job store (C3.2): durable jobs, one private JSON file each, their idempotency keys (DEC-0087,
// FAA-77) and every transition a job makes, in the file format fabric_interop_jobs.py writes. fabric-interop.mjs
// re-exports JobStore and intentDigest. Part of the Node service kit (split from fabric-interop.mjs; layer L3); the twin
// of fabric_interop_jobs.py. Node 20+, no dependency.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { atomicWrite, ensurePrivateDir, nowIso } from './fabric-service.mjs';
import { jcs } from './fabric-delegation.mjs';
import { inputRequestLinkFindings } from './fabric-page-links.mjs';
import { EFFECT_CLASSES } from './fabric-mandate.mjs'; // DEC-0125
import { TERMINAL, InteropError, UnknownJob, parseTraceparent, QUOTA_EXHAUSTED, QUEUE_FULL, OUTCOME_UNKNOWN, utcTime, quotaDataOk, pauseMessage, repeatedKeyDecision, keptStep, ENVELOPE_REQUIRED, JOB_ID, KEY } from './fabric-interop-rules.mjs'; // the rule layer (FAA-92)
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
    // A 0.40.0 key runs only the intent its job stored (an input with no JSON form is refused, as the Python kit refuses it).
    if (decision === 'run') {
      const stored = this.load(id).private ?? {};
      if (intentDigest(stored.capability ?? null, stored.input ?? null) !== intent) decision = 'same';
    }
    return { decision, job };
  }

  get(jobId) { return { ...this.load(jobId).job }; }
  traceparent(jobId) { return this.load(jobId).private.traceparent ?? null; }

  transition(jobId, status, fields = {}, privatePart) {
    const record = this.load(jobId);
    // One write; each question replaces the kept steps, so a step outlives neither its question nor its answer.
    if (privatePart && Object.hasOwn(privatePart, 'steps')) record.private.steps = { ...privatePart.steps };
    if (TERMINAL.includes(record.job.status)) throw new InteropError(`Job ${jobId} is already ${record.job.status}; a terminal job does not change.`);
    for (const key of ['inputRequests', 'result', 'error', 'statusMessage']) delete record.job[key];
    record.job.status = status;
    for (const [key, value] of Object.entries(fields)) if (value !== undefined && value !== null) record.job[key] = value;
    return this.save(record);
  }

  working(jobId, statusMessage) { return this.transition(jobId, 'working', { statusMessage }); }

  // `steps` (DEC-0125) maps a request key to the approval step it asks for, {effect, spendUsd?, project?}, kept in the
  // job's private part (the format fabric_interop.py writes) so a service reads an answer's _meta.mandate for that step.
  // A step is kept as the gate reads it (keptStep), so a job's start and its answer agree.
  requestInput(jobId, inputRequests, statusMessage, { steps } = {}) {
    // a plain object (its prototype Object's or none), as Python's dict: a Date, a boxed String or a class instance is
    // not stored as what was checked (FAA-196 (29))
    const plainObject = (value) => value !== null && typeof value === 'object' && [Object.prototype, null].includes(Object.getPrototypeOf(value));
    const entries = Object.entries(inputRequests ?? {});
    if (!entries.length || !plainObject(inputRequests)) throw new InteropError('input_required needs a JSON object of at least one input request.'); // a JSON object of requests, first (unit 38, 40)
    if (steps !== null && steps !== undefined && (typeof steps !== 'object' || Array.isArray(steps))) { // FAA-196 (26)
      throw new InteropError('steps maps an input request\'s key to its approval step: a JSON object, or none.');
    }
    const kept = Object.create(null); // the value checked is the value kept (seam 34); a key __proto__ stays a key (35)
    for (const [key, step] of Object.entries(steps ?? {})) {
      kept[key] = Object.hasOwn(inputRequests, key) && step !== null && step !== undefined ? keptStep(step) : {};
      if (!EFFECT_CLASSES.includes(kept[key].effect)) throw new InteropError(`Step ${key}: an input request's key with its effect class (DEC-0125).`);
    }
    for (const [key, request] of entries) if (!KEY.test(key) || !plainObject(request) || !Object.hasOwn(request, 'method') || request.method !== 'elicitation/create') throw new InteropError(`Input request ${key} must be a keyed elicitation/create request.`);
    const [finding] = inputRequestLinkFindings({ inputRequests }); // FAC-SEM-143 (D12)
    if (finding) throw new InteropError(`${finding.instancePath}: ${finding.message}`);
    return this.transition(jobId, 'input_required', { inputRequests, statusMessage }, { steps: kept });
  }

  answer(jobId, inputResponses) {
    const job = this.get(jobId);
    if (job.status !== 'input_required') return {};
    const plain = (value) => value !== null && typeof value === 'object' && !Array.isArray(value); // as Python's dict (seam r37)
    const asked = plain(job.inputRequests) ? job.inputRequests : {};
    const matched = Object.fromEntries(Object.entries(plain(inputResponses) ? inputResponses : {}).filter(([key, value]) =>
      Object.hasOwn(asked, key) && ['accept', 'decline', 'cancel'].includes(value?.action))); // an asked key, never an inherited name (seam 36)
    // The answered question's kept steps go in the same write: none outlives its answer.
    if (Object.keys(matched).length) this.transition(jobId, 'working', {}, { steps: {} });
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

  fail(jobId, code, message, data) {
    // DEC-0104: a refusal at a job's start, never a job's end (the schema refuses one).
    if (code === QUEUE_FULL) throw new InteropError('queue-full refuses a start and never ends a job (DEC-0104)');
    return this.transition(jobId, 'failed', { error: data === undefined || data === null ? { code, message } : { code, message, data } });
  }

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
