// fabric-interop/0.1, the rule layer: the extension's names and limits, its errors, the trace context (C3.4), a usage
// object's reading (C3.2) and the job limits and uncertain effects (DEC-0087). Every function answers by a rule and
// touches no file; fabric-interop.mjs builds the tools, the envelope and the job store on it and re-exports every public
// name here. Part of the Node service kit (FAA-92, split from fabric-interop.mjs; layer L3); the twin of
// fabric_interop_rules.py. Node 20+, no dependency.
import crypto from 'node:crypto';
import { ServiceError } from './fabric-base.mjs';
import { jcs, refusalFromAction, refusalToolResult } from './fabric-delegation.mjs';
import { actionDecision, decisionShape, jobCapability } from './fabric-actions.mjs'; // DEC-0121
import { EFFECT_CLASSES, OPERATOR_SOURCE_PROTOCOL, mandateCovers, mandateProblem, withoutSource } from './fabric-mandate.mjs'; // DEC-0125, DEC-0126
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

/**
 * A request's `_meta` from this kit as a caller: its trace, the interop revisions it reads (DEC-0087), for a relayed
 * action the operator's decision (DEC-0121 AP-2; build one with operatorDecision), and the operator's mandate for the
 * task the call serves (DEC-0125 MD-3; state it with operatorMandate and hand it on to the callee with handOn before you
 * send it). Both travel here only, never in a tool's arguments; a decision decision.schema.json refuses or a mandate
 * FAC-SEM-144 refuses throws InteropError.
 *
 * DEC-0126 OA-7: `targetProtocols` is the callee's well-known `protocols`. A decision's or a mandate's `source` is sent
 * only when that list names operator-source/1; otherwise (no list, another list, a board Project, a session, Fabric's
 * agent.call, whose directory lists no `protocols`) it is left out of `_meta` and stays in the caller's own record, the
 * decision and the mandate given here, which this never changes.
 */
export function requestMeta(traceparent, { decision, mandate, targetProtocols } = {}) {
  const meta = { protocols: [...PROTOCOLS_READ] };
  const readsSource = Array.isArray(targetProtocols) && targetProtocols.includes(OPERATOR_SOURCE_PROTOCOL);
  if (parseTraceparent(traceparent)) meta.traceparent = traceparent;
  if (decision !== undefined && decision !== null) {
    if (!decisionShape(decision)) throw new InteropError('The decision is not one decision.schema.json reads; it is not sent.');
    meta.decision = structuredClone(readsSource ? decision : withoutSource(decision));
  }
  if (mandate !== undefined && mandate !== null) {
    const problem = mandateProblem(mandate);
    if (problem) throw new InteropError(`The mandate is not one FAC-SEM-144 reads (${problem}); it is not sent.`);
    meta.mandate = structuredClone(readsSource ? mandate : withoutSource(mandate));
  }
  return meta;
}

const UNREADABLE_JOB_CAPABILITY = "The operator's mandate cannot be read for this step (mandate-capability-missing): answer it, or call fabric.job.get with a decision in _meta.decision.";

/**
 * A job's own approval step under the mandate its start call carried (interop C3.3, DEC-0125 MD-3, MD-4; conformance:
 * "a job's approval step included"): the step is the call {capability: the job's, action: the input request's `key`,
 * effect, spendUsd?, project?} that mandateCovers reads, with `self` the service's agent id and `callerAgent` only an
 * agent id it authenticated for the start call. Answers {covered: true, record} (the step goes on as the operator's
 * decision, no input request; `record` is mandateCovers' recordAs, `source` included when the mandate carries one);
 * {covered: false, message, detail} (the step waits input_required, `message` its statusMessage naming the part not
 * covered, or saying the mandate expired or cannot be read; never the operator's words or `source`); or {covered: false,
 * message: null} with no mandate or a T2 caller's (MD-5), with `fault` when the service's own clock does not read.
 */
export function jobStep({ mandate, tier, now, self, capability, key, effect, callerAgent, spendUsd, project } = {}) {
  if (mandate === undefined || mandate === null) return { covered: false, message: null };
  if (!EFFECT_CLASSES.includes(effect)) throw new InteropError(`A job's approval step names its effect class (one of ${EFFECT_CLASSES.join(', ')}; DEC-0125).`);
  const call = { capability, action: key, effect };
  if (typeof spendUsd === 'number') call.spendUsd = spendUsd;
  if (typeof project === 'string') call.project = project;
  const covers = { mandate, tier, now, self, call };
  if (typeof callerAgent === 'string' && callerAgent.length > 0) covers.callerAgent = callerAgent;
  const answer = mandateCovers(covers);
  // A T2 caller's mandate changes nothing (MD-5), first; then MJ-1: read alike at the start and at the answer (actionGate).
  if ('ignored' in answer || 'fault' in answer) return { covered: false, message: null, ...('fault' in answer ? { fault: answer.fault } : {}) };
  if (!jobCapability(capability)) return { covered: false, detail: 'mandate-capability-missing', fault: 'mandate-capability-missing', message: UNREADABLE_JOB_CAPABILITY };
  if (answer.ok === true) return { covered: true, record: answer.recordAs };
  const { detail } = answer.data;
  const said = detail === 'mandate-expired' ? "The operator's mandate for this task expired before this step"
    : detail.startsWith('outside-mandate') ? `The operator's mandate does not cover this step (${detail})`
      : `The operator's mandate cannot be read for this step (${detail})`;
  return { covered: false, detail, message: `${said}: answer it, or call fabric.job.get with a mandate that covers it in _meta.mandate.` };
}

/**
 * One call of a declared action, before its handler runs (DEC-0121 AP-2, AP-4), for a Node service's own MCP server:
 * actionDecision over the call's `_meta.decision` (an own member of `meta` only, never arguments, decision D11), the
 * service's authenticated `caller` (actionCaller), `target`, `elicited` (the service's own record of an accepted
 * elicitation), `approval` (verifyApproval's accepted outcome), `actionDigest`, `humanStepUrl` and `now` (RFC 3339).
 * Answers {ok: true, record, decision}, `decision` being the one taken as the operator's (null otherwise), or {ok: false,
 * refusal} in the DL-19 form (refusalToolResult sends it); a service's own fault is the refusal unknown-state with
 * `fault` beside it for the service's log.
 *
 * DEC-0125: a service that names its own agent id (`self`) reads the call's `_meta.mandate` when it carries no
 * decision, given `effect` (the action's effect class, required: without it the call is the service's fault
 * effect-missing), `callerAgent` (only an agent id the service authenticated: a delegation's caller, its own per-agent
 * credential; never a name the call carries), `spendUsd` (its own estimate) and `project`. A covered call answers
 * {ok: true, record: {by: 'operator', via: 'mandate', task, chain, caller}, decision: null, mandate}; without `self` the
 * mandate is not read and the call is answered as before it existed.
 *
 * mandateCapability: a job's kept step's capability the mandate is read under (DEC-0141 MJ-1; the service's own input,
 * never a caller's); unusable, the refusal is operator-decision-required.
 */
export function actionGate({ action, tier, caller, meta, target, elicited = false, approval, actionDigest, humanStepUrl, now, self, effect, callerAgent, spendUsd, project, mandateCapability } = {}) {
  const inputs = { action, tier, caller, elicited: elicited === true, now };
  if (isObject(meta) && Object.hasOwn(meta, 'decision')) inputs.decision = meta.decision;
  for (const [name, value] of [['target', target], ['approval', approval], ['actionDigest', actionDigest], ['humanStepUrl', humanStepUrl]]) {
    if (value !== undefined && value !== null) inputs[name] = value;
  }
  if (self !== undefined && self !== null && isObject(meta) && Object.hasOwn(meta, 'mandate')) {
    Object.assign(inputs, { mandate: meta.mandate, self });
    for (const [name, value] of [['effect', effect], ['callerAgent', callerAgent], ['spendUsd', spendUsd], ['project', project], ['mandateCapability', mandateCapability]]) {
      if (value !== undefined && value !== null) inputs[name] = value;
    }
  }
  const answer = actionDecision(inputs);
  if (answer.ok === true) {
    const record = answer.recordAs;
    const taken = isObject(record) && record.via === 'relayed-instruction';
    const out = { ok: true, record, decision: taken ? inputs.decision : null };
    if (isObject(record) && record.via === 'mandate') out.mandate = inputs.mandate;
    return out;
  }
  // MJ-1 (DEC-0141): a job's step the service cannot read under a mandate is answered as one the mandate does not
  // cover; nothing is applied, so the job stays input_required.
  const said = answer.fault === 'mandate-capability-missing' ? { ok: false, code: 'operator-decision-required', data: { detail: 'mandate-capability-missing' } } : answer;
  const out = { ok: false, refusal: refusalFromAction(said) };
  if ('fault' in answer) out.fault = answer.fault;
  return out;
}

/** The tools/call result a service's own MCP server answers for an actionDecision answer: null when the action takes
 * the call, else DL-19's refusal as structuredContent with isError true (DEC-0121). */
export function actionRefusalToolResult(answer, traceparent) {
  const refusal = refusalFromAction(answer);
  return refusal === undefined ? null : refusalToolResult(refusal, traceparent);
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
