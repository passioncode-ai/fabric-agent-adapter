// The call queue and the load report of DEC-0104 (contract src/agent-network.ts, FAC-SEM-131 to FAC-SEM-133), as the
// contract's reference answers them: a node that hosts a job-backed agent queues its jobs per (agentRef, context) with
// these and reports its load as service-load/1 under extensions/load/0.1. Part of the Node service kit (FAA-289, layer
// L3); the twin of fabric_load.py. Node 20+, no dependency. Nothing here throws on what it reads, except
// loadExtension, which refuses a declaration a reader would treat as not declared.
//
// - jobCallerKey(accepted, credential): the opaque key of a job's caller (an accepted delegation's principal, its
//   outermost actor and a partner organization ending the chain; else the credential the node knows the caller by).
// - nextQueuedJob(queue, running, limits): the job the node starts next, or undefined (fairness between callers).
// - admitJob(queue, running, job, limits, retryAfterSeconds): {admit: true}, or the queue-full refusal with its data.
// - queueStatusMessage(position, length), readQueuePosition(statusMessage): `queued <position> of <length>`.
// - jobQueueRules(value): FAC-SEM-131 over {queue, running, limits, started}.
// - loadReportRules(report): FAC-SEM-132 on a service-load/1 report; loadReportProblems(report): its schema.
// - loadView(wellKnown), loadExtensionRules(wellKnown): the declaration as a reader reads it, and FAC-SEM-133.
// - loadExtension({ path, windowSeconds, limits }): the `extensions` entry a service declares.
//
// The kit has no JSON Schema validator: the two shapes are written here from the schemas as the contract's validator
// reads them (lengths in code points, date-time as ajv-formats' full mode). Times in the queue are UTC instants
// (interop-common#/$defs/utcInstant); times in the report are RFC 3339 read strictly (the contract's strictTime). The
// wording of a schema problem is the kit's, not ajv's.
import { ServiceError } from './fabric-base.mjs';
import { dateTime } from './fabric-connections.mjs'; // ajv-formats' date-time, as the contract's validator reads it
import { isObject, isString, objects, show } from './fabric-jsvalue.mjs';
import { parseRfc3339Ms } from './fabric-time.mjs'; // the contract's strictTime

/**
 * @typedef {{ id: string, caller: string, at: string }} QueuedJob A job waiting at the hosting node: its id, its
 *   caller's key (jobCallerKey) and when it arrived (a UTC instant).
 * @typedef {{ id: string, caller?: string }} RunningJob A job running: its id and caller.
 * @typedef {{ concurrency: number, perCaller: number, queueMax: number }} QueueLimits The queue's limits per
 *   (agentRef, context), as the load extension declares them.
 * @typedef {{ admit: true } | { admit: false, error: { code: 'queue-full', message: string,
 *   data: { retryable: true, retryAfterSeconds: number } } }} Admission
 * @typedef {{ code: string, instancePath: string, message: string }} Finding
 * @typedef {{ declared: boolean, valid: boolean, load: { path: string, windowSeconds: number, limits: QueueLimits } | null,
 *   errors: string[] }} LoadView
 */

export const LOAD_EXTENSION_KEY = 'https://fabric.passioncode.ai/agent-contract/extensions/load/0.1';
export const LOAD_REPORT_TYPE = 'service-load/1';
// The refusal code, the same as fabric-interop-rules.mjs's QUEUE_FULL (a test holds them equal); not imported because
// the facade fabric-service.mjs, which re-exports this module, comes before the interop rules in the kit's order.
const QUEUE_FULL = 'queue-full';
export const QUEUE_FULL_MESSAGE = "the agent's queue for this context is full: start again later";
/** The longest queue a status message names (`queued <position> of <length>`, six digits). */
export const QUEUE_LENGTH_MAX = 999999;
export const DEFAULT_RETRY_AFTER_SECONDS = 60;

const UTC_INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:[0-5]\d(?:\.\d{1,3})?Z$/;
const QUEUED = /^queued ([1-9]\d{0,5}) of ([1-9]\d{0,5})$/;
const ORIGIN_PATH = /^\/(?!\/)[^\s]*$/u;
const CONTEXT = /^(?:personal|org:[A-Za-z0-9][A-Za-z0-9_-]{0,127})$/;
const KEY_PATH = `/extensions/${LOAD_EXTENSION_KEY.replace(/~/g, '~0').replace(/\//g, '~1')}`;
const LIMITS = [['concurrency', 1, 1024], ['perCaller', 1, 1024], ['queueMax', 0, 100000]];
const ROW_COUNTS = ['queued', 'running', 'completed', 'failed'];

/** An own member, or undefined. */
const member = (value, key) => (isObject(value) && Object.hasOwn(value, key) ? value[key] : undefined);
/** A UTC instant (`T`, `Z`, at most three fraction digits, a day that exists) in milliseconds, else NaN. */
const utcMs = (value) => (isString(value) && UTC_INSTANT.test(value) ? parseRfc3339Ms(value) : Number.NaN);
const strictMs = (value) => (isString(value) ? parseRfc3339Ms(value) : Number.NaN);
const codePoints = (value) => [...value].length;

// --- The call queue (fabric-interop, DEC-0104) ---

/**
 * The key of a job's caller at a node that queues (DEC-0104), as the contract's jobCallerKey: for a call whose
 * delegation the node accepted (verifyDelegation's answer), its `principal` and `caller` and the partner organization
 * when the chain ends in one (DEC-0090); for a call with no token, the credential the node knows the caller by (a
 * gate's pass with `principal: null` is that case too). A refused verdict has no key, and neither has an unreadable
 * call: undefined. The key is opaque; only equality matters.
 * @param {unknown} accepted
 * @param {unknown} credential
 * @returns {string | undefined}
 */
export function jobCallerKey(accepted, credential) {
  if (isObject(accepted) && !(member(accepted, 'ok') === true && member(accepted, 'principal') === null)) {
    const principal = member(accepted, 'principal');
    const caller = member(accepted, 'caller');
    if (member(accepted, 'ok') !== true || !isString(principal) || principal === '' || !isString(caller) || caller === '') return undefined;
    const given = member(accepted, 'chain');
    const chain = Array.isArray(given) ? given : [];
    const last = chain[chain.length - 1];
    const partner = chain.length > 1 && isString(last) && last.startsWith('org:') ? [last] : [];
    return JSON.stringify(['delegated', principal, caller, ...partner]);
  }
  return isString(credential) && credential !== '' ? JSON.stringify(['credential', credential]) : undefined;
}

const limitsOk = (limits) => isObject(limits)
  && [member(limits, 'concurrency'), member(limits, 'perCaller')].every((n) => Number.isSafeInteger(n) && n >= 1)
  && Number.isSafeInteger(member(limits, 'queueMax')) && limits.queueMax >= 0;
const waitingJob = (job) => isObject(job) && isString(member(job, 'id')) && isString(member(job, 'caller')) && Number.isFinite(utcMs(member(job, 'at')));

/**
 * The job the hosting node starts next for one (agentRef, context), or undefined (DEC-0104). Nothing starts while
 * `concurrency` jobs run (every running job holds a slot, its caller readable or not). Of the waiting jobs whose caller
 * runs fewer than `perCaller`, the one whose caller runs the fewest wins; between those callers, the one whose oldest
 * waiting job arrived first; within a caller, its oldest. Arrival ties break by id (UTF-16 order).
 * @param {unknown} queue
 * @param {unknown} running
 * @param {unknown} limits
 * @returns {string | undefined}
 */
export function nextQueuedJob(queue, running, limits) {
  if (!limitsOk(limits)) return undefined;
  if ((Array.isArray(running) ? running.length : 0) >= limits.concurrency) return undefined;
  const runningOf = new Map();
  for (const job of objects(running)) if (isString(member(job, 'caller'))) runningOf.set(job.caller, (runningOf.get(job.caller) ?? 0) + 1);
  const waiting = objects(queue)
    .filter((job) => waitingJob(job) && (runningOf.get(job.caller) ?? 0) < limits.perCaller)
    .sort((a, b) => utcMs(a.at) - utcMs(b.at) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  let best;
  for (const job of waiting) if (best === undefined || (runningOf.get(job.caller) ?? 0) < (runningOf.get(best.caller) ?? 0)) best = job;
  return best?.id;
}

/**
 * Whether a start is admitted (DEC-0104): it is when the job would start at once (nextQueuedJob over the queue with it
 * added answers its id), or when fewer than `queueMax` jobs wait; otherwise {admit: false, error} with the queue-full
 * refusal and its `retryAfterSeconds` (1 to 3600, else 60). Unreadable limits or job refuse.
 * @param {unknown} queue
 * @param {unknown} running
 * @param {unknown} job
 * @param {unknown} limits
 * @param {unknown} retryAfterSeconds
 * @returns {Admission}
 */
export function admitJob(queue, running, job, limits, retryAfterSeconds) {
  const waiting = objects(queue);
  if (limitsOk(limits) && waitingJob(job) && (nextQueuedJob([...waiting, job], running, limits) === job.id || waiting.length < limits.queueMax)) return { admit: true };
  const after = Number.isSafeInteger(retryAfterSeconds) && retryAfterSeconds >= 1 && retryAfterSeconds <= 3600 ? retryAfterSeconds : DEFAULT_RETRY_AFTER_SECONDS;
  return { admit: false, error: { code: QUEUE_FULL, message: QUEUE_FULL_MESSAGE, data: { retryable: true, retryAfterSeconds: after } } };
}

/**
 * The `statusMessage` of a waiting job (DEC-0104): `queued <position> of <length>`, 1 is next, 1 <= position <= length
 * <= 999999; undefined for anything else.
 * @param {unknown} position
 * @param {unknown} length
 * @returns {string | undefined}
 */
export const queueStatusMessage = (position, length) => (Number.isSafeInteger(position) && Number.isSafeInteger(length)
  && position >= 1 && position <= length && length <= QUEUE_LENGTH_MAX ? `queued ${position} of ${length}` : undefined);

/**
 * A waiting job's place, read from its `statusMessage`, or undefined when it is not the queue's grammar.
 * @param {unknown} statusMessage
 * @returns {{ position: number, length: number } | undefined}
 */
export function readQueuePosition(statusMessage) {
  const match = isString(statusMessage) ? QUEUED.exec(statusMessage) : null;
  if (!match) return undefined;
  const position = Number(match[1]);
  const length = Number(match[2]);
  return position >= 1 && position <= length ? { position, length } : undefined;
}

const finding = (code, instancePath, message) => ({ code, instancePath, message });

/**
 * FAC-SEM-131 on {queue, running, limits, started} (`started`: the id the node started, or null): it is nextQueuedJob's.
 * @param {unknown} value
 * @returns {Finding[]}
 */
export function jobQueueRules(value) {
  const want = nextQueuedJob(member(value, 'queue'), member(value, 'running'), member(value, 'limits')) ?? null;
  if ((member(value, 'started') ?? null) === want) return [];
  return [finding('FAC-SEM-131', '/started', want === null ? 'nothing may start now' : `the job to start is ${show(want)}`)];
}

// --- The load report (DEC-0104) ---

/**
 * FAC-SEM-132 on a service-load/1 report: windows in order one `windowSeconds` apart, none after `generatedAt`, one
 * row per context, p50 at most p95, a run time only where a job ended.
 * @param {unknown} report
 * @returns {Finding[]}
 */
export function loadReportRules(report) {
  const findings = [];
  const flag = (instancePath, message) => findings.push(finding('FAC-SEM-132', instancePath, message));
  const seconds = member(report, 'windowSeconds');
  const step = Number.isSafeInteger(seconds) ? seconds * 1000 : Number.NaN;
  const generated = strictMs(member(report, 'generatedAt'));
  let previous;
  objects(member(report, 'windows')).forEach((window, index) => {
    const start = strictMs(member(window, 'start'));
    if (start > generated) flag(`/windows/${index}/start`, 'a window starts after the report was generated');
    if (previous !== undefined && start - previous !== step) flag(`/windows/${index}/start`, 'windows are not in order one windowSeconds apart');
    previous = start;
    const seen = new Set();
    objects(member(window, 'byContext')).forEach((row, at) => {
      const path = `/windows/${index}/byContext/${at}`;
      const context = member(row, 'context');
      if (isString(context) && seen.has(context)) flag(`${path}/context`, `context ${show(context)} appears twice in one window`);
      if (isString(context)) seen.add(context);
      for (const name of ['waitMs', 'runMs']) {
        const pct = member(row, name);
        if (isObject(pct) && typeof member(pct, 'p50') === 'number' && typeof member(pct, 'p95') === 'number' && pct.p50 > pct.p95) flag(`${path}/${name}`, 'p50 is above p95');
      }
      if (isObject(member(row, 'runMs')) && member(row, 'completed') === 0 && member(row, 'failed') === 0) flag(`${path}/runMs`, 'a run time with no job ended in the window');
    });
  });
  return findings;
}

/** JSON Schema's integer with its bounds, as ajv reads it: a number with no fraction, never a boolean. */
function integer(value, low, high, at, errors) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value % 1 !== 0) errors.push(`${at} type`);
  else if (value < low) errors.push(`${at} minimum`);
  else if (high !== undefined && value > high) errors.push(`${at} maximum`);
}

function members(value, allowed, required, at, errors) {
  for (const key of Object.keys(value)) if (!allowed.includes(key)) errors.push(`${at}/${key} additionalProperties`);
  for (const key of required) if (!Object.hasOwn(value, key)) errors.push(`${at || '/'} required ${key}`);
}

function timestamp(value, at, errors) {
  if (!isString(value)) errors.push(`${at} type`);
  else if (!dateTime(value)) errors.push(`${at} format`);
}

function percentiles(value, at, errors) {
  if (!isObject(value)) {
    errors.push(`${at} type`);
    return;
  }
  members(value, ['p50', 'p95'], ['p50', 'p95'], at, errors);
  for (const name of ['p50', 'p95']) if (Object.hasOwn(value, name)) integer(value[name], 0, undefined, `${at}/${name}`, errors);
}

function rowProblems(row, at, errors) {
  if (!isObject(row)) {
    errors.push(`${at} type`);
    return;
  }
  members(row, ['context', ...ROW_COUNTS, 'waitMs', 'runMs'], ['context', ...ROW_COUNTS], at, errors);
  if (Object.hasOwn(row, 'context') && !(isString(row.context) && CONTEXT.test(row.context))) errors.push(`${at}/context ${isString(row.context) ? 'pattern' : 'type'}`);
  for (const name of ROW_COUNTS) if (Object.hasOwn(row, name)) integer(row[name], 0, undefined, `${at}/${name}`, errors);
  for (const name of ['waitMs', 'runMs']) if (Object.hasOwn(row, name)) percentiles(row[name], `${at}/${name}`, errors);
}

/**
 * service-load.schema.json: what makes `report` not a service-load/1 report, each as `<path> <keyword>`; empty for a
 * valid one. Counts and durations only: a member the schema does not name (a caller, a job id) is refused.
 * @param {unknown} report
 * @returns {string[]}
 */
export function loadReportProblems(report) {
  if (!isObject(report)) return ['/ type'];
  const errors = [];
  const names = ['type', 'generatedAt', 'windowSeconds', 'windows'];
  members(report, names, names, '', errors);
  if (Object.hasOwn(report, 'type') && report.type !== LOAD_REPORT_TYPE) errors.push('/type const');
  if (Object.hasOwn(report, 'generatedAt')) timestamp(report.generatedAt, '/generatedAt', errors);
  if (Object.hasOwn(report, 'windowSeconds')) integer(report.windowSeconds, 60, 86400, '/windowSeconds', errors);
  if (Object.hasOwn(report, 'windows') && !Array.isArray(report.windows)) errors.push('/windows type');
  else if (Object.hasOwn(report, 'windows')) {
    if (report.windows.length > 168) errors.push('/windows maxItems');
    report.windows.forEach((window, index) => {
      const at = `/windows/${index}`;
      if (!isObject(window)) {
        errors.push(`${at} type`);
        return;
      }
      members(window, ['start', 'byContext'], ['start', 'byContext'], at, errors);
      if (Object.hasOwn(window, 'start')) timestamp(window.start, `${at}/start`, errors);
      if (Object.hasOwn(window, 'byContext') && !Array.isArray(window.byContext)) errors.push(`${at}/byContext type`);
      else if (Object.hasOwn(window, 'byContext')) {
        if (window.byContext.length > 64) errors.push(`${at}/byContext maxItems`);
        window.byContext.forEach((row, rowIndex) => rowProblems(row, `${at}/byContext/${rowIndex}`, errors));
      }
    });
  }
  return errors;
}

/** service-load-extension.schema.json, each problem as `<path> <keyword>`; empty for a valid declaration. */
function declarationProblems(value) {
  if (!isObject(value)) return ['/ type'];
  const errors = [];
  members(value, ['path', 'windowSeconds', 'limits'], ['path', 'windowSeconds', 'limits'], '', errors);
  if (Object.hasOwn(value, 'path')) {
    if (!isString(value.path)) errors.push('/path type');
    else {
      if (codePoints(value.path) > 256) errors.push('/path maxLength'); // the originPath's own 2048 is wider
      if (!ORIGIN_PATH.test(value.path)) errors.push('/path pattern');
    }
  }
  if (Object.hasOwn(value, 'windowSeconds')) integer(value.windowSeconds, 60, 86400, '/windowSeconds', errors);
  if (Object.hasOwn(value, 'limits')) {
    const { limits } = value;
    if (!isObject(limits)) errors.push('/limits type');
    else {
      const names = LIMITS.map(([name]) => name);
      members(limits, names, names, '/limits', errors);
      for (const [name, low, high] of LIMITS) if (Object.hasOwn(limits, name)) integer(limits[name], low, high, `/limits/${name}`, errors);
    }
  }
  return errors;
}

/**
 * The load declaration as a reader reads it (DEC-0104): `declared` when the extension key is present, `valid` when its
 * value is the schema's, `load` the declaration when valid (else null) and `errors` its problems. A reader treats an
 * invalid value as not declared and reports it (FAC-SEM-133).
 * @param {unknown} wellKnown
 * @returns {LoadView}
 */
export function loadView(wellKnown) {
  const extensions = member(wellKnown, 'extensions');
  if (!isObject(extensions) || !Object.hasOwn(extensions, LOAD_EXTENSION_KEY)) return { declared: false, valid: false, load: null, errors: [] };
  const value = extensions[LOAD_EXTENSION_KEY];
  const errors = declarationProblems(value);
  return { declared: true, valid: errors.length === 0, load: errors.length === 0 ? value : null, errors };
}

/**
 * FAC-SEM-133 on a well-known document: a value under the load extension key is valid against
 * service-load-extension.schema.json; one finding at the key otherwise.
 * @param {unknown} wellKnown
 * @returns {Finding[]}
 */
export function loadExtensionRules(wellKnown) {
  const view = loadView(wellKnown);
  if (!view.declared || view.valid) return [];
  return [finding('FAC-SEM-133', KEY_PATH, `the load declaration is invalid (${view.errors.join('; ')}); a reader treats it as not declared and reports it (DEC-0104)`)];
}

/**
 * The `extensions` entry a service declares (DEC-0104): where it serves its service-load/1 report (an origin path,
 * served under the descriptor token like the usage report), the report's window and the queue's limits per
 * (agentRef, context). Throws ServiceError on a declaration a reader would treat as not declared.
 * @param {{ path: string, windowSeconds: number, limits: QueueLimits }} declaration
 * @returns {Record<string, { path: string, windowSeconds: number, limits: QueueLimits }>}
 */
export function loadExtension({ path, windowSeconds, limits } = {}) {
  const value = { path, windowSeconds, limits: isObject(limits) ? { ...limits } : limits };
  const problems = declarationProblems(value);
  if (problems.length) throw new ServiceError(`Load declaration: ${problems.join('; ')}.`);
  return { [LOAD_EXTENSION_KEY]: value };
}
