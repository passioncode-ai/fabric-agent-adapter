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
import { PageLinkError, dashboardsLink, inputRequestLinkFindings, pageLinkFindings, parseDashboardsLink } from './fabric-page-links.mjs';
import { EFFECT_CLASSES } from './fabric-mandate.mjs'; // DEC-0125

export {
  PROTOCOL,
  EXTENSION_KEY,
  MCP_REVISION,
  TERMINAL,
  CONTRACT_VERSION,
  JOB_HANDLE_SCHEMA,
  InteropError,
  UnknownJob,
  parseTraceparent,
  childTraceparent,
  traceIds,
  QUOTA_EXHAUSTED,
  QUEUE_FULL,
  OUTCOME_UNKNOWN,
  LIMIT_REACHED,
  INTEROP_NULL_USAGE,
  PROTOCOLS_READ,
  utcTime,
  quotaDataOk,
  readJobPause,
  jobCallerAction,
  intentIdempotencyKey,
  readsNullUsage,
  requestMeta,
  jobStep,
  actionGate,
  mandateSpend,
  UNREADABLE_PROJECT,
  actionRefusalToolResult,
  usageFindings,
  usageToward,
  jobLimitRules,
  pauseMessage,
  repeatedKeyDecision,
} from './fabric-interop-rules.mjs';
import { PROTOCOL, EXTENSION_KEY, MCP_REVISION, TERMINAL, CONTRACT_VERSION, JOB_HANDLE_SCHEMA, InteropError, UnknownJob, parseTraceparent, childTraceparent, traceIds, QUOTA_EXHAUSTED, QUEUE_FULL, OUTCOME_UNKNOWN, LIMIT_REACHED, INTEROP_NULL_USAGE, PROTOCOLS_READ, utcTime, quotaDataOk, readJobPause, jobCallerAction, intentIdempotencyKey, readsNullUsage, requestMeta, usageFindings, usageToward, jobLimitRules, pauseMessage, repeatedKeyDecision, OUTCOMES, ENVELOPE_REQUIRED, JOB_ID, KEY, SECRET_WORDS } from './fabric-interop-rules.mjs'; // the rule layer (FAA-92)

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

/**
 * URL mode: the person opens `url` out of band; for credentials and payments. A page of this service goes as its
 * open_link (`pageAnswer`, DEC-0123 PL-4); a raw loopback address and a `fabric-dashboards:` link outside the grammar
 * are refused here, when the request is built (FAC-SEM-143).
 */
export function urlRequest(message, url) {
  const needs = "A URL-mode request needs an https URL or Fabric Dashboards' open_link (DEC-0123 PL-4).";
  if (typeof url !== 'string') throw new InteropError(needs);
  const [finding] = pageLinkFindings(url, '/params/url', 'the URL-mode request');
  if (finding) throw new InteropError(finding.message);
  if (!url.startsWith('https://') && !parseDashboardsLink(url).ok) throw new InteropError(needs);
  return { method: 'elicitation/create', params: { mode: 'url', message, url } };
}

/**
 * A tool answer that hands a person one of this service's pages (DEC-0123 PL-4): `{open_link}`, the page's Fabric
 * Dashboards link, and `http_url`, its raw address, only as a diagnostic beside it (never judged as the action).
 */
export function pageAnswer(service, instance, { path, httpUrl } = {}) {
  let answer;
  try {
    answer = { open_link: dashboardsLink(service, instance, path) };
  } catch (error) {
    if (!(error instanceof PageLinkError)) throw error;
    throw new InteropError(`No open_link for ${service}.${instance}: ${error.message} (DEC-0123 PL-1).`);
  }
  if (httpUrl !== undefined && httpUrl !== null) answer.http_url = httpUrl;
  return answer;
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
  requestInput(jobId, inputRequests, statusMessage, { steps } = {}) {
    for (const [key, step] of Object.entries(steps ?? {})) {
      if (!Object.hasOwn(inputRequests ?? {}, key) || !EFFECT_CLASSES.includes(step?.effect)) throw new InteropError(`Step ${key}: an input request's key with its effect class (DEC-0125).`);
    }
    const entries = Object.entries(inputRequests ?? {});
    if (!entries.length) throw new InteropError('input_required needs at least one input request.');
    for (const [key, request] of entries) if (!KEY.test(key) || request?.method !== 'elicitation/create') throw new InteropError(`Input request ${key} must be a keyed elicitation/create request.`);
    const [finding] = inputRequestLinkFindings({ inputRequests }); // FAC-SEM-143 (D12)
    if (finding) throw new InteropError(`${finding.instancePath}: ${finding.message}`);
    return this.transition(jobId, 'input_required', { inputRequests, statusMessage }, { steps: { ...(steps ?? {}) } });
  }

  answer(jobId, inputResponses) {
    const job = this.get(jobId);
    if (job.status !== 'input_required') return {};
    const matched = Object.fromEntries(Object.entries(inputResponses ?? {}).filter(([key, value]) =>
      key in (job.inputRequests ?? {}) && ['accept', 'decline', 'cancel'].includes(value?.action)));
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
