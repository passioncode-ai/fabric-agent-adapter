// The project board's wire (fabric-project-comms/0.1, DEC-0022, DEC-0073, DEC-0077): constants, refusal codes, the request digest, the closed shapes the kit reads back, evidence.
// Part of the Node board connector (FAA-65, layer L4); the twin of fabric_board_shapes.py. Node 20+, no dependency.
import crypto from 'node:crypto';
import fs from 'node:fs';
import { sameIdentifier } from './fabric-identifiers.mjs';

// A service agent answers a Project's requests on Fabric's project board (fabric-project-comms/0.1; contract DEC-0022,
// DEC-0073, DEC-0077, DEC-0078; Fabric ADR-0149; FAA-12b, FAA-40). The twin of fabric_board.py — the same steps, the
// same checkpoint file, the same answers; Node built-ins only. fabric-hub.mjs finds the hub.
//
//   enroll (capability) → claim → read the message → accept (the exact digest) → [effectBegin] → [progress] →
//   [reply] → complete ({state, observed, summary?, evidence ≤ 8 sha256 artifacts})
//
// Responder runs that loop inside the service process: one tick every 15 s ± 5 s, claiming when idle and renewing the
// 60 s lease (at about 20 s) while work runs. Before it advances a step it writes and fsyncs a checkpoint; a restart
// reconciles work whose outcome is unknown (com.reconcile) and takes accepted work back by com.responder_replace with a
// transfer (DEC-0078's receipt member transferred; a Fabric that does not answer it leaves the work held — never claimed
// back). It stops acting on fenced, lease_expired and authority_changed.
//
// THE REQUEST BODY IS DATA. admit(request) is the service's own input gate, required: null admits, a sentence refuses
// (the request is accepted and completed failed_known with it). Whatever the handler does with an admitted body — and
// the checks it needs before a model, a tool or a spend sees it — is the service's own responsibility.
//
// A board session is served the respond scope only (RESPOND_TOOLS). com.submit, com.cancel, com.read_ack and
// com.directory are never sent through one; findProject checks a directory page a Project session read (FAC-SEM-107).
export const COMMS_PROTOCOL = 'fabric-project-comms/0.1';

export const LEASE_SECONDS = 60;

export const SUMMARY_MAX = 2000;

export const EVIDENCE_MAX = 8;

export const RESPOND_TOOLS = Object.freeze(new Set(['com.status', 'com.list', 'com.get', 'com.reply', 'com.enroll', 'com.claim', 'com.renew',
  'com.accept', 'com.progress', 'com.effect_begin', 'com.complete', 'com.reconcile', 'com.responder_replace']));

export const REFUSAL_CODES = Object.freeze(new Set(['invalid_arguments', 'body_too_large', 'not_authorized', 'authority_changed',
  'unsupported_capability', 'unsupported_operation', 'not_available', 'idempotency_conflict', 'idempotency_window_expired',
  'capacity_exceeded', 'digest_conflict', 'revision_conflict', 'fenced', 'lease_expired', 'invalid_transition', 'reconcile_required',
  'observation_required', 'cursor_reset_required', 'immutable_participants', 'held']));

export const REQUEST_STATES = ['queued', 'claimed', 'accepted', 'in_progress', 'completed', 'failed_known', 'cancelled', 'expired', 'outcome_unknown'];

const EFFECT_STATES = ['not_started', 'started', 'succeeded_observed', 'failed_observed', 'unknown'];

/**
 * DEC-0079: what an operator's hold may refuse, by the scopes that refuse it. A tool not named here is never refused
 * `held`: it settles, reports on or keeps alive started work, cancels or reads. The contract's HOLD_SCOPES.
 */
export const HOLD_SCOPES = Object.freeze({ 'com.submit': ['thread'], 'com.reply': ['thread'], 'com.enroll': ['project', 'slot'],
  'com.responder_replace': ['project', 'slot'], 'com.claim': ['thread', 'project', 'slot'], 'com.accept': ['thread', 'project', 'slot'],
  'com.effect_begin': ['thread', 'project', 'slot'] });

const OPAQUE = /^[A-Za-z0-9_-]{8,128}$/;

const PROJECT = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$/;

export const CAPABILITY = /^[a-z][a-z0-9._-]{1,127}$/;

const SHA256 = /^sha256:[a-f0-9]{64}$/;

const TIMESTAMP = /^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$/;

const URI = /^[A-Za-z][A-Za-z0-9+.-]*:\S+$/;

/** A board refusal (a contract refusal code) or a kit fault — see fabric_board.py's BoardError for the kit's codes. */
export class BoardError extends Error {
  constructor(code, message, retryable = false, op = undefined, data = {}) {
    super(message);
    this.name = 'BoardError';
    Object.assign(this, { code, retryable, op, data });
  }
}

/** Thrown inside a handler (from ctx.progress / ctx.beginEffect) when the attempt is no longer this responder's. */
export class Stopped extends Error {
  constructor() {
    super('the attempt is no longer this responder\'s');
    this.name = 'Stopped';
  }
}

const LONE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;

/** RFC 8785 as the board takes it: keys by UTF-16 code unit, integers only (|n| ≤ 2^53−1), no lone surrogate. */
export function commsCanonical(value) {
  if (value === null || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) throw new RangeError('canonical JSON admits integers within ±(2^53−1) only');
    return String(value === 0 ? 0 : value);
  }
  if (typeof value === 'string') {
    if (LONE.test(value)) throw new RangeError('canonical JSON refuses a lone surrogate');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(commsCanonical).join(',')}]`;
  if (typeof value === 'object') {
    const keys = Object.keys(value);
    for (const k of keys) commsCanonical(k);
    return `{${keys.sort().map((k) => {
      if (value[k] === undefined) throw new RangeError('canonical JSON has no undefined');
      return `${commsCanonical(k)}:${commsCanonical(value[k])}`;
    }).join(',')}}`;
  }
  throw new RangeError(`canonical JSON has no ${typeof value}`);
}

/** sha256:<hex> over `fabric-project-comms/0.1 NUL <operation> NUL <canonical JSON>` (the contract's commsDigest). */
export function commsDigest(operation, value) {
  if (typeof operation !== 'string' || operation === '' || operation.includes('\u0000')) throw new RangeError('an operation is a non-empty name without NUL');
  return `sha256:${crypto.createHash('sha256').update(`${COMMS_PROTOCOL}\u0000${operation}\u0000${commsCanonical(value)}`, 'utf8').digest('hex')}`;
}

export const isObj = (v) => !!v && typeof v === 'object' && !Array.isArray(v);

export const isInt = (v, min) => Number.isSafeInteger(v) && v >= min;

const str = (v, re) => typeof v === 'string' && re.test(v);

function closed(value, at, required, allowed, problems) {
  if (!isObj(value)) {
    problems.push(`${at} is an object`);
    return false;
  }
  for (const k of required) if (!(k in value)) problems.push(`${at}/${k} is required`);
  for (const k of Object.keys(value)) if (!allowed.includes(k)) problems.push(`${at}/${k} is not a member the contract names`);
  return true;
}

function attemptProblems(a, at, problems) {
  const keys = ['id', 'generation', 'digest', 'leaseExpiresAt'];
  if (!closed(a, at, keys, keys, problems)) return;
  if (!str(a.id, OPAQUE)) problems.push(`${at}/id is a board id`);
  if (!isInt(a.generation, 1)) problems.push(`${at}/generation is an integer ≥ 1`);
  if (!str(a.digest, SHA256)) problems.push(`${at}/digest is sha256:<hex>`);
  if (!str(a.leaseExpiresAt, TIMESTAMP)) problems.push(`${at}/leaseExpiresAt is a timestamp`);
}

/** comms-receipt at the pin, closed at every level; transferred answers com.responder_replace only, each request once. */
export function receiptProblems(value, op) {
  const problems = [];
  const allowed = ['ok', 'repeated', 'message', 'thread', 'at', 'request', 'slot', 'attempt', 'transferred'];
  if (!closed(value, '', ['ok', 'repeated'], allowed, problems)) return problems;
  if (value.ok !== true) problems.push('/ok is true');
  if (typeof value.repeated !== 'boolean') problems.push('/repeated is a boolean');
  for (const k of ['message', 'thread']) if (k in value && !str(value[k], OPAQUE)) problems.push(`/${k} is a board id`);
  if ('at' in value && !str(value.at, TIMESTAMP)) problems.push('/at is a timestamp');
  if ('request' in value) {
    const r = value.request;
    const keys = ['id', 'state', 'effect', 'revision'];
    if (closed(r, '/request', keys, [...keys, 'settledBy'], problems)) {
      if (!str(r.id, OPAQUE)) problems.push('/request/id is a board id');
      if (!REQUEST_STATES.includes(r.state)) problems.push('/request/state is a request state');
      if (!EFFECT_STATES.includes(r.effect)) problems.push('/request/effect is an effect state');
      if (!isInt(r.revision, 1)) problems.push('/request/revision is an integer ≥ 1');
      if ('settledBy' in r) {
        // DEC-0081: present only when the estate owner settled it; absent, the responder did.
        if (r.settledBy !== 'owner') problems.push('/request/settledBy is owner');
        if (!['completed', 'failed_known'].includes(r.state)) problems.push('/request/settledBy names a settled request (completed or failed_known)');
      }
    }
  }
  if ('slot' in value) {
    const s = value.slot;
    const keys = ['project', 'capability', 'generation', 'leaseExpiresAt'];
    if (closed(s, '/slot', keys, keys, problems)) {
      if (!str(s.project, PROJECT)) problems.push('/slot/project is a Project id');
      if (!str(s.capability, CAPABILITY)) problems.push('/slot/capability is a capability name');
      if (!isInt(s.generation, 1)) problems.push('/slot/generation is an integer ≥ 1');
      if (!str(s.leaseExpiresAt, TIMESTAMP)) problems.push('/slot/leaseExpiresAt is a timestamp');
    }
  }
  if ('attempt' in value) attemptProblems(value.attempt, '/attempt', problems);
  if ('transferred' in value) {
    const t = value.transferred;
    if (op !== undefined && op !== 'com.responder_replace') problems.push('/transferred answers com.responder_replace only (DEC-0078)');
    if (!Array.isArray(t) || t.length < 1 || t.length > 64) problems.push('/transferred is 1 to 64 items');
    else {
      const seen = new Set();
      t.forEach((item, i) => {
        const at = `/transferred/${i}`;
        const keys = ['request', 'revision', 'attempt'];
        if (!closed(item, at, keys, keys, problems)) return;
        if (!str(item.request, OPAQUE)) problems.push(`${at}/request is a board id`);
        else if (seen.has(item.request)) problems.push(`${at}/request names a request already listed (each request once, DEC-0078)`);
        seen.add(item.request);
        if (!isInt(item.revision, 1)) problems.push(`${at}/revision is an integer ≥ 1`);
        attemptProblems(item.attempt, `${at}/attempt`, problems);
      });
    }
  }
  return problems;
}

/** comms-refusal: {error: {code, message, retryable}}, closed, a known code, one sentence ≤ 300. */
export function refusalProblems(value) {
  const problems = [];
  if (closed(value, '', ['error'], ['error'], problems)) {
    const e = value.error;
    const keys = ['code', 'message', 'retryable'];
    if (closed(e, '/error', keys, keys, problems)) {
      if (!REFUSAL_CODES.has(e.code)) problems.push('/error/code is a refusal code the contract names');
      if (typeof e.message !== 'string' || e.message.length < 1 || e.message.length > 300) problems.push('/error/message is 1 to 300 characters');
      if (typeof e.retryable !== 'boolean') problems.push('/error/retryable is a boolean');
      else if (e.code === 'held' && e.retryable !== true) problems.push('/error/retryable is true for held: the operator lifts a hold (DEC-0079)');
    }
  }
  return problems;
}

/** FAC-SEM-107 (DEC-0077), the contract's commsDirectory: compared exactly as written; never throws. */
export function directoryFindings(page) {
  const findings = [];
  const projects = isObj(page) && Array.isArray(page.projects) ? page.projects : [];
  const seen = new Set();
  projects.forEach((project, p) => {
    if (!isObj(project)) return;
    if (typeof project.id === 'string') {
      if (seen.has(project.id)) findings.push({ code: 'FAC-SEM-107', instancePath: `/projects/${p}/id`, message: `a directory page lists each Project once: ${project.id} is listed again` });
      seen.add(project.id);
    }
    const names = new Set();
    (Array.isArray(project.capabilities) ? project.capabilities : []).forEach((entry, c) => {
      if (!isObj(entry) || typeof entry.capability !== 'string') return;
      if (names.has(entry.capability)) findings.push({ code: 'FAC-SEM-107', instancePath: `/projects/${p}/capabilities/${c}/capability`, message: `a Project lists each capability once: ${entry.capability} is listed again` });
      names.add(entry.capability);
    });
  });
  return findings;
}

/** comms-directory, closed at every level, then FAC-SEM-107. */
export function directoryProblems(page) {
  const problems = [];
  const top = ['protocol', 'snapshot', 'projects', 'cursor'];
  if (!closed(page, '', top, top, problems)) return problems;
  if (page.protocol !== COMMS_PROTOCOL) problems.push(`/protocol is ${COMMS_PROTOCOL}`);
  if (closed(page.snapshot, '/snapshot', ['readAt'], ['readAt', 'stale'], problems)) {
    if (!str(page.snapshot.readAt, TIMESTAMP)) problems.push('/snapshot/readAt is a timestamp');
    if ('stale' in page.snapshot && typeof page.snapshot.stale !== 'boolean') problems.push('/snapshot/stale is a boolean');
  }
  if (page.cursor !== null && !str(page.cursor, OPAQUE)) problems.push('/cursor is a board id or null');
  if (!Array.isArray(page.projects) || page.projects.length > 100) return [...problems, '/projects is at most 100 Projects'];
  page.projects.forEach((project, p) => {
    const at = `/projects/${p}`;
    if (!closed(project, at, ['id', 'name', 'capabilities'], ['id', 'name', 'capabilities'], problems)) return;
    if (!str(project.id, PROJECT)) problems.push(`${at}/id is a Project id`);
    if (typeof project.name !== 'string' || project.name.length < 1 || project.name.length > 120) problems.push(`${at}/name is 1 to 120 characters`);
    if (!Array.isArray(project.capabilities) || project.capabilities.length > 64) {
      problems.push(`${at}/capabilities is at most 64 entries`);
      return;
    }
    project.capabilities.forEach((entry, c) => {
      const cat = `${at}/capabilities/${c}`;
      if (!closed(entry, cat, ['capability', 'responder'], ['capability', 'responder', 'held'], problems)) return;
      if (!str(entry.capability, CAPABILITY)) problems.push(`${cat}/capability is a capability name`);
      if (!['active', 'stale', 'absent'].includes(entry.responder)) problems.push(`${cat}/responder is active, stale or absent`);
      if ('held' in entry && typeof entry.held !== 'boolean') problems.push(`${cat}/held is a boolean (DEC-0079)`);
    });
  });
  return [...problems, ...directoryFindings(page).map((f) => `${f.instancePath} ${f.message}`)];
}

/**
 * DEC-0079, the contract's holdRefuses: true when a board refuses `tool` on `target` with `held` under `holds`. `target`
 * is what the board resolved ({thread, project, capability, fenced, repeat}); `holds` is {threads, projects, slots:
 * [{project, capability}]}. Ids compare as written; an inherited or mistyped member counts as absent; never throws.
 */
export function holdRefuses(tool, target, holds) {
  const own = (value, key) => (isObj(value) && Object.hasOwn(value, key) ? value[key] : undefined);
  const scopes = typeof tool === 'string' && Object.hasOwn(HOLD_SCOPES, tool) ? HOLD_SCOPES[tool] : undefined;
  if (!scopes || !isObj(target)) return false;
  if (own(target, 'repeat') === true) return false;
  if (tool === 'com.reply' && own(target, 'fenced') === true) return false;
  const text = (v) => (typeof v === 'string' ? v : undefined);
  const strings = (v) => new Set(Array.isArray(v) ? v.filter((item) => typeof item === 'string') : []);
  const thread = text(own(target, 'thread'));
  const project = text(own(target, 'project'));
  const capability = text(own(target, 'capability'));
  if (scopes.includes('thread') && thread !== undefined && strings(own(holds, 'threads')).has(thread)) return true;
  if (scopes.includes('project') && project !== undefined && strings(own(holds, 'projects')).has(project)) return true;
  const slots = own(holds, 'slots');
  if (scopes.includes('slot') && project !== undefined && capability !== undefined && Array.isArray(slots)) {
    return slots.some((slot) => own(slot, 'project') === project && own(slot, 'capability') === capability);
  }
  return false;
}

/** Look a Project up in one com.directory page a Project session read; the page is checked first (FAC-SEM-107). */
export function findProject(page, projectId, capability) {
  const problems = directoryProblems(page);
  if (problems.length) throw new BoardError('directory-invalid', `The directory page cannot be read: ${problems.slice(0, 3).join('; ')}.`);
  const entry = page.projects.find((p) => p.id === projectId);
  if (!entry) return null;
  return capability === undefined || entry.capabilities.some((c) => c.capability === capability) ? entry : null;
}

/** One artifact reference {id, contentHash, label?}; the hash computed here from `content` or the file at `file`. */
export function artifactRef(uri, { content, file, label } = {}) {
  if ((content === undefined) === (file === undefined)) throw new BoardError('evidence', 'Give the artifact\'s bytes or its path, one of them.');
  const hash = crypto.createHash('sha256').update(content !== undefined ? content : fs.readFileSync(file)).digest('hex');
  const ref = { id: uri, contentHash: `sha256:${hash}`, ...(label !== undefined ? { label } : {}) };
  const problems = evidenceProblems([ref]);
  if (problems.length) throw new BoardError('evidence', problems.join('; '));
  return ref;
}

/** At most 8 references, closed, and no artifact twice: two ids with one normal form (DEC-0076) name one artifact. */
export function evidenceProblems(evidence) {
  if (!Array.isArray(evidence) || evidence.length > EVIDENCE_MAX) return [`evidence is a list of at most ${EVIDENCE_MAX} artifact references`];
  const problems = [];
  evidence.forEach((ref, i) => {
    const at = `evidence/${i}`;
    if (!closed(ref, at, ['id', 'contentHash'], ['id', 'contentHash', 'label'], problems)) return;
    if (!str(ref.id, URI)) problems.push(`${at}/id is a URI`);
    if (!str(ref.contentHash, SHA256)) problems.push(`${at}/contentHash is sha256:<hex>`);
    if ('label' in ref && (typeof ref.label !== 'string' || ref.label.length > 120)) problems.push(`${at}/label is at most 120 characters`);
    for (let j = 0; j < i; j += 1) if (isObj(evidence[j]) && sameIdentifier(evidence[j].id, ref.id)) problems.push(`${at}/id names the artifact evidence/${j} already names`);
  });
  return problems;
}

/** comms-complete's outcome plus the kit's optional reply {text, format?, artifacts?}. */
export function outcomeProblems(outcome, effectBegan) {
  const problems = [];
  if (!closed(outcome, 'outcome', ['state'], ['state', 'observed', 'summary', 'evidence', 'reply'], problems)) return problems;
  if (!['completed', 'failed_known'].includes(outcome.state)) problems.push('outcome/state is completed or failed_known');
  const observed = 'observed' in outcome ? outcome.observed : !effectBegan;
  if (typeof observed !== 'boolean') problems.push('outcome/observed is a boolean');
  else if (effectBegan && observed !== true) problems.push('observation_required: after an effect began only an observed result settles the request');
  if ('summary' in outcome && (typeof outcome.summary !== 'string' || outcome.summary.length < 1 || outcome.summary.length > SUMMARY_MAX)) problems.push(`outcome/summary is 1 to ${SUMMARY_MAX} characters`);
  if ('evidence' in outcome) problems.push(...evidenceProblems(outcome.evidence));
  if ('reply' in outcome && closed(outcome.reply, 'outcome/reply', ['text'], ['text', 'format', 'artifacts'], problems)) {
    const { text } = outcome.reply;
    if (typeof text !== 'string' || !text || Buffer.byteLength(text, 'utf8') > 65536) problems.push('outcome/reply/text is 1 to 65,536 UTF-8 bytes');
    if ('format' in outcome.reply && !['text/plain', 'text/markdown'].includes(outcome.reply.format)) problems.push('outcome/reply/format is text/plain or text/markdown');
    if ('artifacts' in outcome.reply) problems.push(...evidenceProblems(outcome.reply.artifacts).map((p) => p.replace('evidence', 'outcome/reply/artifacts')));
  }
  return problems;
}
