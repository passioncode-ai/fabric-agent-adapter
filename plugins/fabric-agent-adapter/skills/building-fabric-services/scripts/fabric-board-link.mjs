// The board link (DEC-0078, FAA-12b): the board session over the hub, the fsynced checkpoint and a claimed request as data.
// Part of the Node board connector (FAA-65, layer L4), below the responder in fabric-board-session.mjs, which re-exports
// these names; the twin of fabric_board_link.py. Node 18+, no dependency.
import fs from 'node:fs';
import path from 'node:path';
import { HubError, MCP_PROTOCOL_VERSION, postMcp, toolAnswer } from './fabric-hub.mjs';
import { atomicWrite, ensurePrivateDir } from './fabric-service.mjs';
import { BoardError, RESPOND_TOOLS, isObj, refusalProblems } from './fabric-board-shapes.mjs';
import { UNREADABLE_PROJECT, mandateSpend } from './fabric-interop-rules.mjs'; // FAA-139
import { isAgentId, mandateCovers } from './fabric-mandate.mjs';
import { formatRfc3339 } from './fabric-time.mjs';

/** MCP over HTTP with a board session's one-session bearer; calls are serialised; close() sends the session's DELETE. */
export class BoardSession {
  constructor(grant, { timeout = 15000, post = postMcp } = {}) {
    Object.assign(this, { grant, timeout: timeout > 0 ? timeout : 15000, post }); // not above 0 is the default
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

  async #send(body, method = 'POST', timeout = null) {
    try {
      return await this.post(this.grant.origin, body, this.grant.bearer(), { session: this.mcpSession, timeout: timeout > 0 ? timeout : this.timeout, method, protocolVersion: this.mcpSession ? this.protocolVersion : undefined });
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

  /** Sends the DELETE (waiting `timeout` ms at most); true when Fabric answered it with a 2xx, so the slots are free now (FAA-163). A 404 (already gone) is false: a move made before it ended is read at the next com.status, so the slot records stay. */
  close(timeout = null) {
    return this.#serial(async () => {
      if (!this.mcpSession) return false;
      let status = 0;
      try {
        const answer = await this.#send({}, 'DELETE', timeout);
        status = Number.isInteger(answer?.status) ? answer.status : 0; // an answer it cannot read is no release, as in Python
      } catch {
        // best effort: the lease lapses in 60 s anyway
      }
      this.mcpSession = null;
      return status >= 200 && status < 300;
    });
  }
}

/** The responder's journal (0600 JSON, the same file fabric_board.py writes), fsynced before the step it announces. */
export class Checkpoint {
  constructor(file) {
    this.file = file;
    this.slots = {}; // the responder's own record of each slot it held: {project, generation, moved?} (FAA-155)
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
    // a record that is not an object is ignored, as a file without one is
    this.slots = isObj(doc.slots) ? Object.fromEntries(Object.entries(doc.slots).filter(([, v]) => isObj(v))) : {};
    return doc.requests;
  }
  #write(entries, slots = this.slots) {
    try {
      ensurePrivateDir(path.dirname(this.file));
      const sort = (o) => Object.fromEntries(Object.keys(o).sort().map((k) => [k, o[k]]));
      const doc = Object.keys(slots).length ? { requests: sort(entries), slots: sort(slots), version: 1 } : { requests: sort(entries), version: 1 };
      atomicWrite(this.file, `${JSON.stringify(doc, null, 1)}\n`, 0o600);
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
  /** Writes the record of a slot this responder held (null forgets it); nothing is written when it is unchanged. */
  slot(capability, record) {
    const { [capability]: _old, ...slots } = this.slots;
    if (record !== null) slots[capability] = JSON.parse(JSON.stringify(record));
    if (JSON.stringify(sortDeep(slots)) === JSON.stringify(sortDeep(this.slots))) return;
    this.#write(this.entries, slots);
    this.slots = slots;
  }
  /**
   * At a clean leave (the session's DELETE released the slots): forget the record of each slot this session confirmed
   * (`held`, required: capability to the generation it held, or com.status showed unmoved) at that generation or below, for `project`, with no request left and not moved away, so a later generation is another session taking a free slot, and
   * a kit rolled back to before 0.53.0 leaves nothing that reads as a move. A record that cannot be written stays.
   */
  leave(project, held) {
    const busy = new Set(Object.values(this.entries).map((e) => e.capability));
    for (const [capability, record] of Object.entries(this.slots)) {
      if (!isObj(record) || record.project !== project || 'moved' in record || busy.has(capability)) continue;
      // Only a slot this session confirmed, at or below that generation: an unconfirmed record may be a move (0.56.0 seam r2, r3).
      const confirmed = Object.hasOwn(held, capability) ? held[capability] : null;
      if (!Number.isInteger(record.generation) || record.generation < 1 || !Number.isInteger(confirmed) || record.generation > confirmed) continue;
      try {
        this.slot(capability, null);
      } catch {
        // stays for the next start
      }
    }
  }
}

const sortDeep = (v) => (isObj(v) ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sortDeep(v[k])])) : v);

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
  [Symbol.for('nodejs.util.inspect.custom')]() {
    return this.toJSON(); // console.log(request) prints no body either
  }
}

// -- the operator's mandate in a board request (FAA-135; contract project-comms.md, DEC-0125 MD-3) ---------------------

/** `mandateFrom` naming every trusted sender of the board the service is installed on: the operator's personal board. */
export const PERSONAL_BOARD = 'personal-board';
const OPENER = /^```json[ \t]*$/;
const CLOSER = /^```[ \t]*$/;

/**
 * The bodies of the ```json blocks, each fence on its own line: one pass over the lines, linear in the body. Lines end
 * at "\\n" alone, one "\\r" before it dropped, as in the Python twin (never U+2028 or a lone "\\r"); an unclosed
 * opener ends the scan.
 */
function jsonBlocks(body) {
  const lines = body.split('\n').map((line) => (line.endsWith('\r') ? line.slice(0, -1) : line));
  const blocks = [];
  for (let i = 0; i < lines.length; i += 1) {
    if (!OPENER.test(lines[i])) continue;
    let j = i + 1;
    while (j < lines.length && !CLOSER.test(lines[j])) j += 1;
    if (j === lines.length) break;
    blocks.push(lines.slice(i + 1, j).join('\n'));
    i = j;
  }
  return blocks;
}
const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
/** A Project id as Fabric's board compares it: a uuid lower-cased, any other id as written (normalProject). */
const fold = (project) => (UUID.test(project) ? project.toLowerCase() : project);

/**
 * The mandate a request carries, read only when the service opted in (`agentId` and `mandateFrom` set), the board
 * verified the sender (`provenance: trusted`) and its Project is one `mandateFrom` names (or `PERSONAL_BOARD`): a T1
 * caller by project-comms. Answers `{ mandate, unread }`: `mandate` null when none is read, `unread` `mandate-blocks`
 * (more than one) or `mandate-unreadable` (a block naming `mandate/1` that is not JSON). A `source` in the block is
 * dropped: a board block carries none (OA-7).
 */
export function readMandate(request, mandateFrom, agentId) {
  const none = { mandate: null, unread: null };
  if (agentId == null || mandateFrom == null || typeof request.body !== 'string') return none;
  const sender = isObj(request.sender) ? request.sender : {};
  const principal = isObj(sender.principal) ? sender.principal : {};
  if (principal.provenance !== 'trusted') return none;
  if (typeof sender.project !== 'string' || !sender.project) return none; // comms-message requires it; the caller
  if (mandateFrom !== PERSONAL_BOARD && !mandateFrom.has(fold(sender.project))) return none;
  const found = [];
  for (const block of jsonBlocks(request.body)) {
    let value;
    try {
      value = JSON.parse(block);
    } catch {
      if (block.includes('mandate/1')) return { mandate: null, unread: 'mandate-unreadable' };
      continue;
    }
    if (isObj(value) && value.kind === 'mandate/1') {
      delete value.source; // a Project declares no protocols: a board block carries no source (OA-7)
      found.push(value);
    }
  }
  if (found.length > 1) return { mandate: null, unread: 'mandate-blocks' };
  return found.length ? { mandate: found[0], unread: null } : none;
}

/**
 * `mandateCovers` for a call under a board request's mandate, its sender placed as T1 and no caller agent id (the
 * chain's end alone binds it, MD-3). A covered answer's `recordAs` names `caller`, the sender Project the board
 * verified (MD-3 records the caller). `wall` answers milliseconds. Null when no mandate travelled. `spendUsd` and
 * `project` are read failing closed, as the kit's other mandate readers read them (FAA-139): a spend that is not a
 * finite number is none (a ceiling refuses it), a non-string `project` unreadable, a null `project` none.
 */
export function covers(mandate, call, agentId, wall, caller = null) {
  if (mandate == null || agentId == null) return null;
  if (call !== null && typeof call === 'object' && !Array.isArray(call)) {
    const { spendUsd, project, ...rest } = call;
    call = rest;
    const spend = mandateSpend(spendUsd);
    if (spend !== undefined) call.spendUsd = spend;
    if (project !== undefined && project !== null) call.project = typeof project === 'string' ? project : UNREADABLE_PROJECT;
  }
  const clock = wall();
  let now = '';
  try {
    if (typeof clock === 'number' && Number.isFinite(clock)) now = formatRfc3339(clock);
  } catch { // finite but outside the dates a clock can name
    now = '';
  }
  const answer = mandateCovers({ mandate, tier: 'T1', now, self: agentId, call });
  return answer.recordAs ? { ok: true, recordAs: { ...answer.recordAs, caller } } : answer;
}

/** The responder's opt-in, checked: answers `mandateFrom` as the responder keeps it (a Set or the string). */
export function mandateOptions(agentId, mandateFrom) {
  if (agentId != null && !isAgentId(agentId)) throw new BoardError('invalid_arguments', 'agentId must be the service\'s registry agent id.');
  if (mandateFrom == null || mandateFrom === PERSONAL_BOARD) return mandateFrom ?? null;
  const projects = typeof mandateFrom === 'string' || mandateFrom instanceof String || typeof mandateFrom?.[Symbol.iterator] !== 'function' ? null : [...mandateFrom];
  if (projects === null || !projects.every((p) => typeof p === 'string' && p)) {
    throw new BoardError('invalid_arguments', `mandateFrom is '${PERSONAL_BOARD}' or a collection of Project ids.`);
  }
  return new Set(projects.map(fold));
}

