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

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { Backoff, HubError, MCP_PROTOCOL_VERSION, normalProject, postMcp, toolAnswer } from './fabric-hub.mjs';
import { sameIdentifier } from './fabric-identifiers.mjs';
import { acceptedRevisions, atomicWrite, ensurePrivateDir, feedDataProblems, negotiateRevision } from './fabric-service.mjs';

export const COMMS_PROTOCOL = 'fabric-project-comms/0.1';
export const LEASE_SECONDS = 60;
export const RENEW_SECONDS = 20;
export const POLL_SECONDS = 15;
export const POLL_JITTER_SECONDS = 5;
export const DRAIN_SECONDS = 10;
export const SUMMARY_MAX = 2000;
export const EVIDENCE_MAX = 8;
export const EVENT_SCHEMA = 'urn:fabric:schema:board-responder-event:1';
export const RESPOND_TOOLS = Object.freeze(new Set(['com.status', 'com.list', 'com.get', 'com.reply', 'com.enroll', 'com.claim', 'com.renew',
  'com.accept', 'com.progress', 'com.effect_begin', 'com.complete', 'com.reconcile', 'com.responder_replace']));
export const REFUSAL_CODES = Object.freeze(new Set(['invalid_arguments', 'body_too_large', 'not_authorized', 'authority_changed',
  'unsupported_capability', 'unsupported_operation', 'not_available', 'idempotency_conflict', 'idempotency_window_expired',
  'capacity_exceeded', 'digest_conflict', 'revision_conflict', 'fenced', 'lease_expired', 'invalid_transition', 'reconcile_required',
  'observation_required', 'cursor_reset_required', 'immutable_participants', 'held']));
export const STOP_CODES = Object.freeze(new Set(['fenced', 'lease_expired', 'authority_changed']));
const REQUEST_STATES = ['queued', 'claimed', 'accepted', 'in_progress', 'completed', 'failed_known', 'cancelled', 'expired', 'outcome_unknown'];
const EFFECT_STATES = ['not_started', 'started', 'succeeded_observed', 'failed_observed', 'unknown'];
const TERMINAL = new Set(['completed', 'failed_known', 'cancelled', 'expired']);
/**
 * DEC-0079: what an operator's hold may refuse, by the scopes that refuse it. A tool not named here is never refused
 * `held`: it settles, reports on or keeps alive started work, cancels or reads. The contract's HOLD_SCOPES.
 */
export const HOLD_SCOPES = Object.freeze({ 'com.submit': ['thread'], 'com.reply': ['thread'], 'com.enroll': ['project', 'slot'],
  'com.responder_replace': ['project', 'slot'], 'com.claim': ['thread', 'project', 'slot'], 'com.accept': ['thread', 'project', 'slot'],
  'com.effect_begin': ['thread', 'project', 'slot'] });
/** How long a held slot waits before it asks again: doubling from the poll interval, never past this. */
export const HOLD_RETRY_MAX_SECONDS = 900;
const OPAQUE = /^[A-Za-z0-9_-]{8,128}$/;
const PROJECT = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$/;
const CAPABILITY = /^[a-z][a-z0-9._-]{1,127}$/;
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

// --- the contract's digest -----------------------------------------------------------------------------------------

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

// --- closed shapes ------------------------------------------------------------------------------------------------

const isObj = (v) => !!v && typeof v === 'object' && !Array.isArray(v);
const isInt = (v, min) => Number.isSafeInteger(v) && v >= min;
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

// --- evidence -----------------------------------------------------------------------------------------------------

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

// --- the board session ----------------------------------------------------------------------------------------------

/** MCP over HTTP with a board session's one-session bearer; calls are serialised; close() sends the session's DELETE. */
export class BoardSession {
  constructor(grant, { timeout = 15000, post = postMcp } = {}) {
    Object.assign(this, { grant, timeout, post });
    this.mcpSession = null;
    this.protocolVersion = MCP_PROTOCOL_VERSION;
    this.rpc = 0;
    this.queue = Promise.resolve();
  }

  #serial(fn) {
    const run = this.queue.then(fn, fn);
    this.queue = run.catch(() => {});
    return run;
  }

  async #send(body, method = 'POST') {
    try {
      return await this.post(this.grant.origin, body, this.grant.bearer(), { session: this.mcpSession, timeout: this.timeout, method, protocolVersion: this.mcpSession ? this.protocolVersion : undefined });
    } catch (e) {
      if (e instanceof HubError) throw new BoardError('unreachable', 'Fabric\'s hub did not answer; a write may have been stored, so send it again with the same idempotency key.', true);
      throw e;
    }
  }

  open() {
    return this.#serial(async () => {
      this.rpc += 1;
      const answer = await this.#send({ jsonrpc: '2.0', id: this.rpc, method: 'initialize', params: { protocolVersion: MCP_PROTOCOL_VERSION, capabilities: {}, clientInfo: { name: 'fabric-agent-adapter-board', version: '1' } } });
      if (answer.status === 401) throw new BoardError('session-ended', 'Fabric refused the board session\'s bearer; join again.', true);
      const sid = answer.headers['mcp-session-id'];
      if (answer.status !== 200 || !isObj(answer.body) || !isObj(answer.body.result) || !sid) throw new BoardError('unreachable', `Fabric did not open the board session (HTTP ${answer.status}).`, true);
      this.mcpSession = String(sid);
      if (typeof answer.body.result.protocolVersion === 'string') this.protocolVersion = answer.body.result.protocolVersion;
      await this.#send({ jsonrpc: '2.0', method: 'notifications/initialized' });
    });
  }

  call(tool, args) {
    if (!RESPOND_TOOLS.has(tool)) return Promise.reject(new BoardError('not-in-scope', `${tool} is not served to a board session; use a Project session for it.`, false, tool));
    return this.#serial(async () => {
      if (!this.mcpSession) throw new BoardError('session-ended', 'The board session is not open.', true, tool);
      this.rpc += 1;
      const answer = await this.#send({ jsonrpc: '2.0', id: this.rpc, method: 'tools/call', params: { name: tool, arguments: args } });
      if (answer.status === 401) throw new BoardError('session-ended', 'Fabric ended the board session (it left, was revoked or expired); join again.', true, tool);
      let value;
      try {
        value = toolAnswer(answer, tool);
      } catch (e) {
        throw new BoardError(e.retryable ? 'unreachable' : 'receipt-shape', e.message, e.retryable, tool);
      }
      if ('error' in value) {
        if (refusalProblems(value).length) throw new BoardError('receipt-shape', `Fabric refused ${tool} in a form the contract does not name.`, false, tool);
        throw new BoardError(value.error.code, value.error.message, value.error.retryable, tool);
      }
      return value;
    });
  }

  close() {
    return this.#serial(async () => {
      if (!this.mcpSession) return;
      try {
        await this.#send({}, 'DELETE');
      } catch {
        // best effort: the lease lapses in 60 s anyway
      }
      this.mcpSession = null;
    });
  }
}

// --- the checkpoint ------------------------------------------------------------------------------------------------

/** The responder's journal (0600 JSON, the same file fabric_board.py writes), fsynced before the step it announces. */
export class Checkpoint {
  constructor(file) {
    this.file = file;
    this.entries = this.#load();
  }
  #load() {
    let text;
    try {
      text = fs.readFileSync(this.file, 'utf8');
    } catch (e) {
      if (e.code === 'ENOENT') return {};
      throw new BoardError('checkpoint', `The board checkpoint ${this.file} cannot be read (${e.code}); fix or move it before answering requests.`);
    }
    let doc;
    try {
      doc = JSON.parse(text);
    } catch {
      doc = null;
    }
    if (!isObj(doc) || doc.version !== 1 || !isObj(doc.requests)) throw new BoardError('checkpoint', `The board checkpoint ${this.file} is not one this kit writes.`);
    return doc.requests;
  }
  #write(entries) {
    try {
      ensurePrivateDir(path.dirname(this.file));
      const sorted = Object.fromEntries(Object.keys(entries).sort().map((k) => [k, entries[k]]));
      atomicWrite(this.file, `${JSON.stringify({ requests: sorted, version: 1 }, null, 1)}\n`, 0o600);
    } catch (e) {
      throw new BoardError('checkpoint', `The board checkpoint could not be written (${e.code ?? e.message}); nothing was sent.`);
    }
  }
  put(entry) {
    const entries = { ...this.entries, [entry.request]: JSON.parse(JSON.stringify(entry)) };
    this.#write(entries);
    this.entries = entries;
  }
  drop(requestId) {
    if (!(requestId in this.entries)) return;
    const { [requestId]: _gone, ...entries } = this.entries;
    this.#write(entries);
    this.entries = entries;
  }
}

// --- the request a handler sees ------------------------------------------------------------------------------------

/** A claimed request as data: never an instruction. */
export class BoardRequest {
  constructor(message, capability) {
    const req = isObj(message.request) ? message.request : {};
    const body = isObj(message.body) ? message.body : {};
    this.requestId = req.id;
    this.messageId = message.id;
    this.capability = capability;
    this.body = typeof body.text === 'string' ? body.text : null;
    this.bodyFormat = body.format ?? 'text/plain';
    this.artifacts = Array.isArray(message.artifacts) ? [...message.artifacts] : [];
    this.sender = isObj(message.sender) ? message.sender : {};
    this.deadline = req.deadline;
    this.thread = message.thread;
  }
  toJSON() {
    return { requestId: this.requestId, capability: this.capability }; // never the body
  }
}

/** What a handler may do while it works: progress(note), beginEffect(summary) before it spends or acts, and `stopped`. */
export class WorkContext {
  #responder;
  #entry;
  constructor(responder, entry) {
    this.#responder = responder;
    this.#entry = entry;
    this.stopped = false;
  }
  async progress(note) {
    if (this.stopped) throw new Stopped();
    await this.#responder.progress(this.#entry, note, this);
  }
  async beginEffect(summary) {
    if (this.stopped) throw new Stopped();
    await this.#responder.effectBegin(this.#entry, summary, this);
  }
}

// --- the responder --------------------------------------------------------------------------------------------------

const clean = (text, max = SUMMARY_MAX) => String(text).split(/\s+/).filter(Boolean).join(' ').slice(0, max);

/**
 * One service's responder for one Project and its capabilities, one request at a time. handler(request, ctx) answers
 * the outcome (may be async); admit(request) is the input gate; observe(entry) reads the world after a restart;
 * emit(kind, level, text, extra) receives events. run({signal}) ticks until aborted; step() is one tick.
 */
export class Responder {
  constructor({ hub, projectId, capabilities, credentialFile, checkpointFile, handler, admit, observe, emit, service = 'service',
    now = () => performance.now() / 1000, rand = Math.random, sessionFactory } = {}) {
    if (typeof admit !== 'function' || typeof handler !== 'function') throw new BoardError('invalid_arguments', 'A responder needs the service\'s own input gate (admit) and a handler.');
    const caps = [...(capabilities ?? [])];
    if (!caps.length || caps.some((c) => typeof c !== 'string' || !CAPABILITY.test(c)) || new Set(caps).size !== caps.length) throw new BoardError('invalid_arguments', 'Name each capability once, [a-z][a-z0-9._-]{1,127}.');
    Object.assign(this, { hub, capabilities: caps, credentialFile, handler, admit, observe, emitTo: emit, now, rand });
    this.project = normalProject(projectId);
    this.service = String(service).replace(/[^A-Za-z0-9._-]/g, '-').slice(0, 40) || 'service';
    this.checkpoint = new Checkpoint(checkpointFile);
    this.sessionFactory = sessionFactory ?? ((grant) => new BoardSession(grant));
    this.backoff = new Backoff({ rand });
    this.session = null;
    this.epoch = null;
    this.slots = {};
    this.current = null;
    this.state = 'idle';
    this.waitUntil = 0;
    this.stopping = false;
    this.claimKeys = {};
    this.said = {};
    this.rr = 0;
    this.reconcileAt = 0;
    /** The first pause under an operator's hold (DEC-0079); it doubles to HOLD_RETRY_MAX_SECONDS. */
    this.holdDelay = POLL_SECONDS;
    this.onHold = new Set();
  }

  // -- events --
  emit(kind, level, text, { notify = false, episode, ...value } = {}) {
    if (episode !== undefined) {
      if (this.said[kind] === episode) return;
      this.said[kind] = episode;
    }
    let data = { schema: EVENT_SCHEMA, value: Object.fromEntries(Object.entries(value).filter(([, v]) => v !== undefined && v !== null)) };
    if (feedDataProblems(data).length) data = undefined; // FAC-SEM-101: drop the data, keep the sentence
    if (!this.emitTo) return;
    try {
      this.emitTo(kind, level, text, { notify, ...(data ? { data } : {}) });
    } catch {
      // an event that cannot be written never stops the responder
    }
  }

  // -- keys and fences --
  key(op) {
    return `${this.service}.${op}.${crypto.randomBytes(8).toString('hex')}`;
  }
  idem(key) {
    if (this.epoch === null) throw new BoardError('no-epoch', 'Fabric told this board session no idempotency epoch.', false, 'com.status');
    return { epoch: this.epoch, key };
  }
  fence(entry, key) {
    return { request: entry.request, generation: entry.generation, attempt: entry.attempt, digest: entry.digest, expectedRevision: entry.revision, idempotency: this.idem(key) };
  }
  receipt(op, answer) {
    const problems = receiptProblems(answer, op);
    if (problems.length) throw new BoardError('receipt-shape', `Fabric answered ${op} with a receipt the contract does not name (${problems[0]}).`, false, op);
    return answer;
  }
  call(op, args) {
    if (!this.session) return Promise.reject(new BoardError('session-ended', 'No board session.', true, op));
    return this.session.call(op, args);
  }

  // -- connecting --
  async status() {
    const status = await this.call('com.status', {});
    const verdict = negotiateRevision(status.protocol, acceptedRevisions('fabric-project-comms'));
    if (verdict.error) throw new BoardError('schema-unsupported', `Fabric's board speaks ${status.protocol}, which this kit does not read.`, false, 'com.status', verdict.error.data);
    if (status.board?.state === 'unavailable') throw new BoardError('not_available', 'Fabric\'s board cannot be read right now.', true, 'com.status');
    const epoch = status.idempotency?.epoch;
    // Fail closed: a guessed epoch would store keys under a namespace the board never named.
    if (!isInt(epoch, 1)) throw new BoardError('no-epoch', 'Fabric told this board session no idempotency epoch (Fabric before its board-session fix); the responder waits rather than guess one.', false, 'com.status');
    this.epoch = epoch;
    return status;
  }

  async connect() {
    this.state = 'connecting';
    const grant = await this.hub.joinBoard(this.project, this.credentialFile);
    const missing = this.capabilities.filter((c) => !grant.capabilities.includes(c));
    const session = this.sessionFactory(grant);
    await session.open();
    this.session = session;
    const status = await this.status();
    if (missing.length) {
      this.emit('board.access.needed', 'warn', `The operator has not let this service answer ${missing.join(', ')} on this Project; ask in Fabric (Agents & access).`, { notify: true, episode: missing.join(','), capabilities: missing });
    }
    this.slots = {};
    await this.recover(status, this.capabilities.filter((c) => grant.capabilities.includes(c)));
    this.state = 'ready';
    for (const kind of ['board.down', 'board.blocked', ...(missing.length ? [] : ['board.access.needed'])]) delete this.said[kind];
  }

  async enroll(capability) {
    const args = { idempotency: this.idem(this.key('enroll')), capability };
    let receipt;
    try {
      receipt = this.receipt('com.enroll', await this.call('com.enroll', args));
    } catch (e) {
      if (e.code === 'held') {
        this.pause(capability);
        return;
      }
      if (e.code === 'fenced') {
        this.slots[capability] = { state: 'contested', renewedAt: this.now() };
        this.emit('board.slot.contested', 'warn', `Another responder holds the ${capability} slot on this Project; this service waits for it to lapse and never takes it over by itself.`, { notify: true, episode: capability, capability });
        return;
      }
      throw e;
    }
    this.slots[capability] = { state: 'held', generation: receipt.slot.generation, renewedAt: this.now() };
    delete this.said['board.slot.contested'];
    this.lifted(capability);
  }

  /**
   * The operator holds this slot or its Project (DEC-0079): ask again later, the pause doubling each time, and never act
   * around the hold. Accepted work in progress continues; only new work waits.
   */
  pause(capability) {
    const slot = this.slots[capability] ?? {};
    const pauses = slot.state === 'paused' ? (slot.pauses ?? 0) + 1 : 1;
    const wait = Math.min(HOLD_RETRY_MAX_SECONDS, this.holdDelay * 2 ** (pauses - 1));
    this.slots[capability] = { state: 'paused', pauses, retryAt: this.now() + wait, renewedAt: this.now() };
    if (!this.onHold.has(capability)) { // once per hold, per capability
      this.onHold.add(capability);
      this.emit('board.slot.held', 'info', `The operator holds new work for ${capability} on this Project; the service waits and asks again later. Work already accepted continues.`, { capability });
    }
  }

  lifted(capability) {
    if (!this.onHold.delete(capability)) return;
    this.emit('board.slot.released', 'info', `The operator's hold on ${capability} was lifted; the service takes new work again.`, { capability });
  }

  // -- restart: reconcile and transfer --
  async readState(entry) {
    const message = await this.call('com.get', { message: entry.message });
    const req = isObj(message) ? message.request : null;
    if (!isObj(req) || req.id !== entry.request || !REQUEST_STATES.includes(req.state)) return null;
    entry.revision = req.revision ?? entry.revision;
    return req.state;
  }

  async recover(status, capabilities) {
    const transfer = {};
    const reconcile = [];
    for (const entry of Object.values(this.checkpoint.entries)) {
      if (!capabilities.includes(entry.capability)) continue;
      let state;
      try {
        state = await this.readState(entry);
      } catch (e) {
        if (e.code === 'not_authorized') {
          this.checkpoint.drop(entry.request);
          continue;
        }
        throw e;
      }
      if (state === null || TERMINAL.has(state) || state === 'queued' || state === 'claimed') this.checkpoint.drop(entry.request);
      else if (state === 'accepted') (transfer[entry.capability] ??= []).push(entry);
      else reconcile.push(entry);
    }
    const responders = (status.responders ?? []).filter(isObj);
    const generations = Object.fromEntries(responders.map((r) => [r.capability, r.generation ?? 0]));
    const onHold = new Set(responders.filter((r) => r.held === true).map((r) => r.capability)); // DEC-0079
    for (const capability of capabilities) {
      if (onHold.has(capability)) {
        for (const entry of transfer[capability] ?? []) {
          entry.step = 'lapsed'; // taken back by a transfer once the hold is lifted
          this.checkpoint.put(entry);
        }
        this.pause(capability);
      } else if (transfer[capability]?.length) await this.replace(capability, transfer[capability], generations[capability] ?? 0);
      else await this.enroll(capability);
    }
    for (const entry of reconcile) if (this.slots[entry.capability]?.state === 'held') await this.reconcile(entry);
  }

  async replace(capability, entries, generation) {
    const args = { idempotency: this.idem(this.key('replace')), capability, expectedGeneration: isInt(generation, 0) ? generation : 0,
      transfer: { requests: entries.map((e) => e.request).slice(0, 64), checkpoint: { summary: 'Resumed by the same service after a restart; no effect had begun.' } } };
    let receipt;
    try {
      receipt = this.receipt('com.responder_replace', await this.call('com.responder_replace', args));
    } catch (e) {
      if (e.code !== 'held') throw e;
      for (const entry of entries) {
        entry.step = 'lapsed'; // nothing moved: taken back by a transfer once the hold is lifted
        this.checkpoint.put(entry);
      }
      this.pause(capability);
      return;
    }
    this.slots[capability] = { state: 'held', generation: receipt.slot.generation, renewedAt: this.now() };
    this.lifted(capability);
    const moved = new Map((receipt.transferred ?? []).map((item) => [item.request, item]));
    for (const entry of entries) {
      const item = moved.get(entry.request);
      if (!item) {
        // A board pinned before DEC-0078 hands back no attempt. Never claim it back: it stays held.
        entry.step = 'held';
        this.checkpoint.put(entry);
        this.emit('board.request.held', 'warn', 'An accepted request could not be resumed: this Fabric does not hand back a transferred attempt (DEC-0078). It stays held; nothing was done.', { notify: true, episode: entry.request, request: entry.request, capability });
        continue;
      }
      Object.assign(entry, { generation: item.attempt.generation, attempt: item.attempt.id, digest: item.attempt.digest, revision: item.revision,
        step: ['accepting', 'held', 'lapsed'].includes(entry.step) ? 'accepted' : entry.step });
      this.checkpoint.put(entry);
      if (!this.current) await this.resume(entry);
    }
  }

  async reconcile(entry) {
    const state = await this.readState(entry);
    if (state !== 'outcome_unknown') {
      if (state !== null && (TERMINAL.has(state) || state === 'queued' || state === 'claimed')) this.checkpoint.drop(entry.request);
      return;
    }
    let outcome = isObj(entry.outcome) && entry.outcome.observed === true ? entry.outcome : null;
    if (!outcome && this.observe) {
      try {
        outcome = await this.observe({ ...entry });
      } catch {
        outcome = null;
      }
    }
    if (!isObj(outcome) || outcome.observed !== true || outcomeProblems({ ...outcome, observed: true }, true).length) {
      entry.step = 'unknown';
      this.checkpoint.put(entry);
      this.emit('board.reconcile.needed', 'warn', 'A request\'s outcome is unknown: the work may have happened. It stays unknown until this service observes what happened.', { notify: true, episode: entry.request, request: entry.request, capability: entry.capability });
      return;
    }
    const sent = Object.fromEntries(['state', 'summary', 'evidence'].filter((k) => k in outcome).map((k) => [k, outcome[k]]));
    sent.observed = true;
    entry.keys ??= {};
    entry.keys.reconcile ??= this.key('reconcile');
    entry.step = 'reconciling';
    this.checkpoint.put(entry);
    this.receipt('com.reconcile', await this.call('com.reconcile', { idempotency: this.idem(entry.keys.reconcile), request: entry.request, digest: entry.digest, outcome: sent }));
    this.checkpoint.drop(entry.request);
    this.emit('board.request.reconciled', 'info', 'A request whose outcome was unknown was settled from what this service observed.', { request: entry.request, capability: entry.capability, state: sent.state });
  }

  // -- one tick --
  interval() {
    return Math.max(1, POLL_SECONDS + POLL_JITTER_SECONDS * (2 * this.rand() - 1));
  }

  /** One tick; answers the seconds to wait before the next. */
  async step() {
    if (this.stopping) return DRAIN_SECONDS;
    const now = this.now();
    if (now < this.waitUntil) return this.waitUntil - now;
    try {
      if (!this.session) await this.connect();
      await this.tick();
      this.backoff.reset();
      return this.interval();
    } catch (e) {
      if (!(e instanceof BoardError) && !(e instanceof HubError)) throw e;
      return this.fault(e);
    }
  }

  async fault(e) {
    const code = e.code ?? 'unreachable';
    const wait = this.backoff.next();
    this.waitUntil = this.now() + wait;
    if (['not_authorized', 'authority_changed', 'credential'].includes(code)) {
      this.state = 'not-authorized';
      await this.dropSession();
      this.emit('board.access.needed', 'warn', 'This service may not answer requests for this Project: the operator has to allow it in Fabric (Agents & access). Nothing is claimed until then.', { notify: true, episode: 'access', reason: code });
    } else if (code === 'held') {
      this.state = 'paused';
      this.emit('board.held', 'info', 'The operator holds new work on this Project; the responder waits and asks again with a growing pause.', { episode: 'held', reason: code });
    } else if (['no-epoch', 'schema-unsupported', 'checkpoint', 'receipt-shape'].includes(code)) {
      this.state = 'down';
      await this.dropSession();
      this.emit('board.blocked', 'error', `The responder stopped answering requests: ${e.message}`, { notify: true, episode: code, reason: code });
    } else {
      this.state = 'down';
      if (['session-ended', 'unreachable', 'not-running', 'not-a-hub', 'hub-unavailable', 'protocol'].includes(code)) await this.dropSession();
      this.emit('board.down', 'warn', 'Fabric\'s board cannot be reached; the responder tries again with a growing pause.', { episode: 'down', reason: code });
    }
    return wait;
  }

  async dropSession() {
    const work = this.current;
    this.current = null;
    if (work) {
      const { entry } = work;
      if (work.done && !work.failure && !outcomeProblems(work.outcome, !!entry.effect).length) {
        entry.outcome = { ...work.outcome, observed: work.outcome.observed ?? !entry.effect };
        try {
          this.checkpoint.put(entry);
        } catch {
          // the next start reruns it
        }
      } else work.ctx.stopped = true;
    }
    const session = this.session;
    this.session = null;
    if (session) await session.close();
  }

  async tick() {
    const work = this.current;
    if (work) {
      if (work.done) await this.finish(work);
      else await this.renew(work);
    }
    const heldByWork = work && this.current ? work.entry.capability : null;
    for (const [capability, slot] of Object.entries(this.slots)) {
      if (slot.state === 'paused') {
        // still held: a longer pause; lifted: the slot is ours again
        if (capability !== heldByWork && this.now() >= (slot.retryAt ?? 0)) await this.enroll(capability);
        continue;
      }
      if (capability !== heldByWork && this.now() - (slot.renewedAt ?? 0) >= RENEW_SECONDS - 0.5) await this.enroll(capability);
    }
    if (!this.current && !this.stopping) await this.continueLapsed();
    if (!this.current && !this.stopping) {
      await this.reconcilePending();
      await this.claimNext();
    }
  }

  async continueLapsed() {
    const lapsed = {};
    for (const entry of Object.values(this.checkpoint.entries)) {
      if (entry.step === 'lapsed' && this.slots[entry.capability]?.state === 'held') (lapsed[entry.capability] ??= []).push(JSON.parse(JSON.stringify(entry)));
    }
    for (const [capability, entries] of Object.entries(lapsed)) {
      const live = [];
      for (const e of entries) {
        if (await this.readState(e) === 'accepted') live.push(e);
        else this.checkpoint.drop(e.request);
      }
      if (live.length) await this.replace(capability, live, this.slots[capability].generation ?? 0);
    }
  }

  async reconcilePending() {
    if (this.now() < this.reconcileAt) return;
    this.reconcileAt = this.now() + 300;
    for (const entry of Object.values(this.checkpoint.entries)) {
      if (entry.step === 'unknown' && this.slots[entry.capability]?.state === 'held') await this.reconcile(entry);
    }
  }

  async claimNext() {
    const held = this.capabilities.filter((c) => this.slots[c]?.state === 'held');
    for (let i = 0; i < held.length; i += 1) {
      const capability = held[(this.rr + i) % held.length];
      this.claimKeys[capability] ??= this.key('claim');
      let answer;
      try {
        answer = this.receipt('com.claim', await this.call('com.claim', { idempotency: this.idem(this.claimKeys[capability]), capability }));
      } catch (e) {
        if (e.code === 'lease_expired') {
          await this.enroll(capability);
          continue;
        }
        if (e.code === 'idempotency_window_expired' || e.code === 'capacity_exceeded') {
          delete this.claimKeys[capability];
          await this.status();
          continue;
        }
        if (e.code === 'fenced') {
          this.slots[capability] = { state: 'contested', renewedAt: this.now() };
          continue;
        }
        if (e.code === 'held') {
          this.pause(capability);
          continue;
        }
        throw e;
      }
      if (!('request' in answer)) continue; // nothing claimable; the same key polls again
      delete this.claimKeys[capability];
      this.rr += 1;
      await this.start(capability, answer);
      return;
    }
  }

  // -- a claimed request --
  async start(capability, receipt) {
    if (!receipt.attempt || !receipt.message) throw new BoardError('receipt-shape', 'com.claim answered a request without its attempt or message.', false, 'com.claim');
    const { attempt } = receipt;
    const entry = { request: receipt.request.id, message: receipt.message, capability, generation: attempt.generation, attempt: attempt.id, digest: attempt.digest,
      revision: receipt.request.revision, step: 'claimed', keys: {}, effect: false };
    this.checkpoint.put(entry);
    const message = await this.call('com.get', { message: entry.message });
    const req = isObj(message) ? message.request : null;
    if (message.digest !== entry.digest) {
      this.checkpoint.drop(entry.request);
      this.emit('board.request.skipped', 'warn', 'A claimed request was not accepted: the message read back carries another digest than the claim. Nothing was done; the claim lapses.', { request: entry.request, capability, reason: 'digest-mismatch' });
      return;
    }
    if (!isObj(req) || req.id !== entry.request || req.capability !== capability || req.target !== this.project) {
      this.checkpoint.drop(entry.request);
      this.emit('board.request.skipped', 'warn', 'A claimed request was not accepted: it is not addressed to this Project and capability. Nothing was done; the claim lapses.', { request: entry.request, capability, reason: 'not-addressed' });
      return;
    }
    const request = new BoardRequest(message, capability);
    let reason;
    if (message.redacted === true || typeof request.body !== 'string') reason = 'The request\'s body was redacted, so there is nothing to act on.';
    else {
      try {
        reason = (await this.admit(request)) ?? null;
      } catch {
        reason = 'The service\'s input gate could not read this request.';
      }
    }
    if (!(await this.accept(entry))) return;
    if (reason !== null && reason !== undefined) {
      entry.outcome = { state: 'failed_known', observed: true, summary: clean(`Refused by this service's input gate: ${reason}`) };
      await this.complete(entry);
      this.emit('board.request.refused', 'info', 'A request was refused by the service\'s input gate and completed as failed.', { request: entry.request, capability });
      return;
    }
    await this.runWork(entry, request);
  }

  async accept(entry) {
    entry.keys.accept ??= this.key('accept');
    entry.step = 'accepting';
    this.checkpoint.put(entry);
    let receipt;
    try {
      receipt = await this.fenced('com.accept', entry, { fence: this.fence(entry, entry.keys.accept) });
    } catch (e) {
      if (e.code !== 'held') throw e;
      // A hold came between the claim and the accept (DEC-0079): nothing was done, the claim lapses and the request waits.
      this.checkpoint.drop(entry.request);
      this.emit('board.request.waiting', 'info', 'A claimed request was not accepted: the operator holds it. Nothing was done; it waits on the board.', { request: entry.request, capability: entry.capability });
      this.pause(entry.capability);
      return false;
    }
    if (!receipt) return false; // the claim was lost before it was accepted; nothing was done
    entry.revision = receipt.request.revision;
    entry.step = 'accepted';
    this.checkpoint.put(entry);
    return true;
  }

  async runWork(entry, request) {
    const ctx = new WorkContext(this, entry);
    const work = { entry, request, ctx, done: false, outcome: null, failure: null, renewedAt: this.now() };
    this.current = work;
    work.promise = Promise.resolve().then(() => this.handler(request, ctx)).then((outcome) => { work.outcome = outcome; }, (e) => { work.failure = e; }).finally(() => { work.done = true; });
    // A handler that answers at once is finished in this tick; a longer one is renewed by the next ticks.
    await Promise.race([work.promise, new Promise((resolve) => setImmediate(resolve))]);
    if (work.done && this.current === work) await this.finish(work);
  }

  async resume(entry) {
    if (isObj(entry.outcome)) {
      await this.complete(entry);
      return;
    }
    const message = await this.call('com.get', { message: entry.message });
    await this.runWork(entry, new BoardRequest(message, entry.capability));
  }

  async fenced(op, entry, args) {
    try {
      return this.receipt(op, await this.call(op, args));
    } catch (e) {
      if (STOP_CODES.has(e.code) || ['revision_conflict', 'invalid_transition', 'digest_conflict'].includes(e.code)) {
        this.lose(entry, e.code);
        if (e.code === 'authority_changed') throw e;
        return null;
      }
      throw e;
    }
  }

  lose(entry, code) {
    if (this.current && this.current.entry === entry) this.current.ctx.stopped = true;
    if (entry.effect) {
      entry.step = 'unknown';
      this.checkpoint.put(entry);
      this.emit('board.reconcile.needed', 'warn', 'The attempt was lost after its effect began; the outcome stays unknown until this service observes what happened.', { notify: true, episode: entry.request, request: entry.request, capability: entry.capability, reason: code });
    } else if (code === 'lease_expired' && !['claimed', 'accepting'].includes(entry.step)) {
      entry.step = 'lapsed';
      this.checkpoint.put(entry);
      this.emit('board.attempt.lost', 'warn', 'This service\'s lease on an accepted request lapsed; it stopped working on it and takes it back by a transfer.', { request: entry.request, capability: entry.capability, reason: code });
    } else {
      this.checkpoint.drop(entry.request);
      this.emit('board.attempt.lost', 'warn', `The board took a request back from this service (${code}); it stopped working on it, and nothing had been done outside the service.`, { request: entry.request, capability: entry.capability, reason: code });
    }
  }

  async renew(work) {
    if (this.now() - (work.renewedAt ?? 0) < RENEW_SECONDS - 0.5) return;
    const receipt = await this.fenced('com.renew', work.entry, { fence: this.fence(work.entry, this.key('renew')) });
    if (!receipt) {
      this.current = null;
      return;
    }
    work.renewedAt = this.now();
    (this.slots[work.entry.capability] ??= {}).renewedAt = this.now();
  }

  async progress(entry, note) {
    const args = { fence: this.fence(entry, this.key('progress')) };
    if (note !== undefined && note !== null) args.note = { text: clean(note) || 'Working.' };
    if (!(await this.fenced('com.progress', entry, args))) throw new Stopped();
  }

  async effectBegin(entry, summary, ctx) {
    entry.keys.effect_begin ??= this.key('effect');
    entry.step = 'effect-beginning';
    entry.effect = true; // from here a lost attempt is an unknown outcome, never "nothing happened"
    this.checkpoint.put(entry);
    const args = { fence: this.fence(entry, entry.keys.effect_begin), ...(summary ? { summary: clean(summary) } : {}) };
    let receipt = null;
    let lost = 0;
    let delay = this.holdDelay;
    for (;;) { // a lost answer: the same key again tells whether it was stored
      try {
        receipt = await this.fenced('com.effect_begin', entry, args);
        break;
      } catch (e) {
        if (e.code === 'held') {
          // The operator holds this work (DEC-0079): the effect has not begun. Wait, keep the lease (the tick renews it;
          // com.renew is never held), and ask again with the same key.
          entry.effect = false;
          entry.step = 'effect-held';
          this.checkpoint.put(entry);
          this.emit('board.request.waiting', 'info', 'The operator holds this request before its effect: the service waits and does nothing outside it until the hold is lifted.', { episode: entry.request, request: entry.request, capability: entry.capability });
          const until = Date.now() + delay * 1000;
          while (Date.now() < until) {
            if (ctx?.stopped) throw new Stopped();
            await new Promise((resolve) => setTimeout(resolve, Math.min(250, Math.max(1, until - Date.now()))));
          }
          if (ctx?.stopped) throw new Stopped();
          delay = Math.min(HOLD_RETRY_MAX_SECONDS, delay * 2);
          entry.effect = true;
          entry.step = 'effect-beginning';
          this.checkpoint.put(entry);
          continue;
        }
        if (e.code !== 'unreachable' || lost === 2) throw new Stopped();
        lost += 1;
        await new Promise((resolve) => setTimeout(resolve, lost * 1000));
      }
    }
    if (!receipt) throw new Stopped();
    entry.revision = receipt.request.revision;
    entry.step = 'in-progress';
    this.checkpoint.put(entry);
  }

  async finish(work) {
    const { entry } = work;
    if (work.ctx.stopped && !(entry.request in this.checkpoint.entries)) {
      this.current = null;
      return;
    }
    let { outcome } = work;
    if (work.failure) {
      if (entry.effect || work.failure instanceof Stopped) {
        this.current = null;
        if (entry.effect) this.lose(entry, 'handler-failed');
        return;
      }
      outcome = { state: 'failed_known', observed: true, summary: `The service could not do this (${work.failure?.name ?? 'Error'}).` };
    }
    const problems = outcomeProblems(outcome, !!entry.effect);
    if (problems.length) {
      this.current = null;
      if (entry.effect) this.lose(entry, problems.some((p) => p.includes('observation_required')) ? 'observation_required' : 'outcome');
      else {
        entry.outcome = { state: 'failed_known', observed: true, summary: 'The service answered in a form it cannot send.' };
        await this.complete(entry);
      }
      this.emit('board.outcome.invalid', 'warn', `The handler's outcome was not sent: ${problems[0]}.`, { request: entry.request, capability: entry.capability });
      return;
    }
    entry.outcome = { ...outcome, observed: outcome.observed ?? !entry.effect };
    await this.complete(entry);
  }

  async complete(entry) {
    const { outcome } = entry;
    const { reply } = outcome;
    if (reply && !entry.replied) {
      entry.keys.reply ??= this.key('reply');
      entry.step = 'replying';
      this.checkpoint.put(entry);
      const args = { fence: this.fence(entry, entry.keys.reply), body: { text: reply.text, ...(reply.format ? { format: reply.format } : {}) }, ...(reply.artifacts?.length ? { artifacts: reply.artifacts } : {}) };
      if (!(await this.fenced('com.reply', entry, args))) {
        this.current = null;
        return;
      }
      entry.replied = true;
      this.checkpoint.put(entry);
    }
    entry.keys.complete ??= this.key('complete');
    entry.step = 'completing';
    this.checkpoint.put(entry);
    const sent = Object.fromEntries(['state', 'observed', 'summary', 'evidence'].filter((k) => k in outcome).map((k) => [k, outcome[k]]));
    const receipt = await this.fenced('com.complete', entry, { fence: this.fence(entry, entry.keys.complete), outcome: sent });
    this.current = null;
    if (!receipt) return;
    this.checkpoint.drop(entry.request);
    this.emit('board.request.completed', 'info', `A request was answered: ${sent.state === 'completed' ? 'completed' : 'failed, as known'}.`, { request: entry.request, capability: entry.capability, state: sent.state });
  }

  // -- running --
  /** Tick until `signal` aborts, then shutdown(). */
  async run({ signal, drain = DRAIN_SECONDS } = {}) {
    while (!signal?.aborted) {
      const wait = await this.step();
      await new Promise((resolve) => {
        const timer = setTimeout(resolve, wait * 1000);
        signal?.addEventListener('abort', () => { clearTimeout(timer); resolve(); }, { once: true });
      });
    }
    await this.shutdown(drain);
  }

  /** Stop claiming, give running work up to `drain` seconds, then leave the session (its DELETE releases the slots). */
  async shutdown(drain = DRAIN_SECONDS) {
    this.stopping = true;
    const work = this.current;
    if (work && !work.done) {
      await Promise.race([work.promise, new Promise((resolve) => setTimeout(resolve, drain * 1000).unref?.())]);
      if (!work.done) work.ctx.stopped = true;
    }
    if (work && work.done && this.session) {
      try {
        await this.finish(work);
      } catch {
        // the checkpoint keeps it
      }
    }
    if (this.session) {
      await this.session.close();
      this.session = null;
    }
    this.state = 'stopped';
  }
}

// --- a fixture conversation (check_service.py, rule board.responder) -------------------------------------------------

const FIXTURE_PROJECT = '3f2a6b1c-0d4e-4f5a-8b6c-7d8e9f0a1b2c';
const FIXTURE_DIGEST = `sha256:${'a'.repeat(64)}`;

function fixtureAnswers(variant) {
  const lease = '2026-10-13T10:02:00Z';
  const status = { protocol: COMMS_PROTOCOL, board: { state: 'ready' }, project: FIXTURE_PROJECT, responders: [], transport: { telegram: 'off' }, unread: 0, idempotency: { epoch: 3 } };
  if (variant === 'no-epoch') delete status.idempotency;
  const request = { id: 'req_A1b2C3d4E5', state: 'claimed', effect: 'not_started', revision: 2 };
  return {
    'com.status': status,
    'com.enroll': { ok: true, repeated: false, slot: { project: FIXTURE_PROJECT, capability: 'fixture.render', generation: 2, leaseExpiresAt: lease } },
    'com.claim': { ok: true, repeated: false, message: 'msg_K9j8H7g6F5', request, attempt: { id: 'att_Zx9Cv8Bn7M', generation: 2, digest: FIXTURE_DIGEST, leaseExpiresAt: lease } },
    'com.get': { id: 'msg_K9j8H7g6F5', thread: 'thr_8Hc2kQ9xA1', kind: 'request', at: '2026-10-13T10:00:00Z', digest: FIXTURE_DIGEST,
      sender: { project: 'proj-requester', principal: { kind: 'agent', id: 's-1', provenance: 'trusted' } }, body: { text: 'Render the fixture.' },
      request: { id: 'req_A1b2C3d4E5', target: FIXTURE_PROJECT, capability: 'fixture.render', state: 'claimed', effect: 'not_started', revision: 2 } },
    'com.accept': variant === 'fenced' ? { error: { code: 'fenced', message: 'A newer responder holds this slot; this call was not committed.', retryable: false } }
      : { ok: true, repeated: false, request: { ...request, state: 'accepted', revision: 3 } },
    'com.complete': { ok: true, repeated: false, request: { ...request, state: 'completed', revision: 4 } },
  };
}

/** One scripted conversation per path through this kit, with no Fabric; answers the problems found (empty: it passes). */
export async function selfCheck() {
  const os = await import('node:os');
  const problems = [];
  for (const variant of ['whole', 'fenced', 'no-epoch']) {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'fabric-board-fixture-'));
    try {
      const root = path.join(tmp, 'fabric');
      fs.mkdirSync(root, { mode: 0o700 });
      const door = path.join(root, 'hub-door-token');
      fs.writeFileSync(door, 'd'.repeat(43), { mode: 0o600 });
      fs.writeFileSync(path.join(root, 'hub.json'), JSON.stringify({ protocol: 'fabric-hub/0.1', origin: 'http://127.0.0.1:47070', mcp: '/mcp', doorTokenFile: door, pid: process.pid, startedAt: '2026-10-13T10:00:00Z' }));
      const cred = path.join(tmp, 'credential');
      fs.writeFileSync(cred, 'c'.repeat(43), { mode: 0o600 });
      const answers = fixtureAnswers(variant);
      const calls = [];
      const handled = [];
      const post = async (origin, body, bearer, { method = 'POST' } = {}) => {
        if (method === 'DELETE') return { status: 200, headers: {}, body: null };
        if (body.method === 'initialize') return { status: 200, headers: { 'mcp-session-id': 'fixture-session' }, body: { jsonrpc: '2.0', id: body.id, result: { protocolVersion: MCP_PROTOCOL_VERSION } } };
        if (body.method !== 'tools/call') return { status: 202, headers: {}, body: null };
        const tool = body.params.name;
        calls.push([tool, body.params.arguments]);
        if (tool === 'fabric.board.join') return { status: 200, headers: {}, body: { jsonrpc: '2.0', id: body.id, result: { structuredContent: { session: { bearer: 'b'.repeat(43), sessionId: 's-fixture', projectId: FIXTURE_PROJECT, capabilities: ['fixture.render'] } } } } };
        const value = answers[tool] ?? { error: { code: 'unsupported_capability', message: 'not in the fixture', retryable: false } };
        return { status: 200, headers: {}, body: { jsonrpc: '2.0', id: body.id, result: { content: [{ type: 'text', text: JSON.stringify(value) }] } } };
      };
      const { HubClient } = await import('./fabric-hub.mjs');
      const responder = new Responder({ hub: new HubClient(root, { post }), projectId: FIXTURE_PROJECT, capabilities: ['fixture.render'], credentialFile: cred,
        checkpointFile: path.join(tmp, 'checkpoint.json'), handler: (request) => { handled.push(request.body); return { state: 'completed', summary: 'Rendered.' }; },
        admit: () => null, now: () => 0, rand: () => 0.5, sessionFactory: (grant) => new BoardSession(grant, { post }) });
      await responder.step();
      const tools = calls.map(([t]) => t);
      if (tools.some((t) => !RESPOND_TOOLS.has(t) && t !== 'fabric.board.join')) problems.push(`${variant}: a tool outside the respond scope was sent`);
      if (variant === 'whole') {
        if (tools.join(',') !== 'fabric.board.join,com.status,com.enroll,com.claim,com.get,com.accept,com.complete') problems.push(`whole: the calls were ${tools.join(', ')}`);
        const accept = calls.find(([t]) => t === 'com.accept')?.[1]?.fence ?? {};
        if (accept.digest !== FIXTURE_DIGEST || accept.generation !== 2 || accept.attempt !== 'att_Zx9Cv8Bn7M') problems.push('whole: com.accept did not carry the claim\'s exact fence');
        if (handled.join('|') !== 'Render the fixture.') problems.push('whole: the handler did not see the request once');
        if (Object.keys(responder.checkpoint.entries).length) problems.push('whole: the checkpoint kept a settled request');
      } else if (variant === 'fenced') {
        if (handled.length || tools.includes('com.complete')) problems.push('fenced: the kit kept acting after com.accept answered fenced');
      } else if (tools.includes('com.enroll') || responder.state !== 'down') problems.push('no-epoch: the kit did not fail closed without an idempotency epoch');
    } finally {
      fs.rmSync(tmp, { recursive: true, force: true });
    }
  }
  return problems;
}
