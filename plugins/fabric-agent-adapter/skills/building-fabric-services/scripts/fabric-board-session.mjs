// The board responder (DEC-0078, FAA-12b): the work context a handler sees and the responder loop. The session, the
// checkpoint and the request live in fabric-board-link.mjs and are re-exported here.
// Part of the Node board connector (FAA-65, layer L4); the twin of fabric_board_session.py. Node 20+, no dependency.
import crypto from 'node:crypto';
import { Backoff, HubError, normalProject } from './fabric-hub.mjs';
import { acceptedRevisions, feedDataProblems, negotiateRevision } from './fabric-service.mjs';
import { BoardError, CAPABILITY, LEASE_SECONDS, REQUEST_STATES, SUMMARY_MAX, Stopped, isInt, isObj, outcomeProblems, receiptProblems } from './fabric-board-shapes.mjs';
import { BoardRequest, BoardSession, Checkpoint } from './fabric-board-link.mjs';
import { HOLD_RETRY_MAX_SECONDS, LEASE_MARGIN_SECONDS, SESSION_CODES, SlotKeeper } from './fabric-board-slots.mjs';

export { BoardRequest, BoardSession, Checkpoint }; // re-exported: callers import them from here since 0.40.0
export { HOLD_RETRY_MAX_SECONDS, LEASE_MARGIN_SECONDS, SESSION_CODES }; // since 0.56.0 defined in fabric-board-slots.mjs

export const RENEW_SECONDS = 20;

export const POLL_SECONDS = 15;

export const POLL_JITTER_SECONDS = 5;

export const DRAIN_SECONDS = 10;
/** An idle responder's leave waits this long for the DELETE, so an idle stop ends within LC-01's 5 s (FAA-173). */
export const IDLE_LEAVE_SECONDS = 3;

export const EVENT_SCHEMA = 'urn:fabric:schema:board-responder-event:1';

export const STOP_CODES = Object.freeze(new Set(['fenced', 'lease_expired', 'authority_changed']));

const TERMINAL = new Set(['completed', 'failed_known', 'cancelled', 'expired']);
// No longer this responder's to work on: back in the queue, claimed again, or answered by the target Project's
// participant reply (DEC-0098, DEC-0102; not terminal, the requester may still cancel it, and nobody claims it).
const NOT_OURS = new Set(['queued', 'claimed', 'answered']);

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

const clean = (text, max = SUMMARY_MAX) => String(text).split(/\s+/).filter(Boolean).join(' ').slice(0, max);

/**
 * One service's responder for one Project and its capabilities, one request at a time. handler(request, ctx) answers
 * the outcome (may be async); admit(request) is the input gate; observe(entry) reads the world after a restart;
 * emit(kind, level, text, extra) receives events. run({signal}) ticks until aborted; step() is one tick.
 */
export class Responder extends SlotKeeper {
  constructor({ hub, projectId, capabilities, credentialFile, checkpointFile, handler, admit, observe, emit, service = 'service',
    now = () => performance.now() / 1000, rand = Math.random, sessionFactory } = {}) {
    super();
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
    /** One fenced call at a time, and the entry edits beside them (FAA-77, finding 36). */
    this.fenceQueue = Promise.resolve();
    this.toResume = []; // transferred requests waiting until nothing runs (finding 39)
    this.suspect = new Set(); // capabilities a fenced call was refused on: com.status says whether they moved (FAA-155)
    this.confirmed = {}; // this session's: the generation it held, or com.status showed unmoved
  }

  /** Runs fn after every fenced call queued before it (finding 36): an await inside a call never lets another in. */
  locked(fn) {
    const run = this.fenceQueue.then(fn, fn);
    this.fenceQueue = run.catch(() => {});
    return run;
  }

  /** The generations this session confirmed (held, or compared with com.status and found unmoved), paused and retrying slots included: only their records a clean leave may forget (0.56.0 seam r2, r3). */
  heldNow() {
    // a fenced call (maybe moved) or a move withholds it
    return Object.fromEntries(Object.entries(this.confirmed).filter(([c]) => !this.suspect.has(c) && this.slots[c]?.state !== 'moved'));
  }

  // -- events --
  emit(kind, level, text, { notify = false, episode, saidAs, ...value } = {}) {
    if (episode !== undefined) { // `saidAs` keeps one episode per key, such as one per capability
      const key = saidAs ?? kind;
      if (this.said[key] === episode) return;
      this.said[key] = episode;
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
    this.slots = {}; // the previous session's slots are not this one's: a refusal now reconnects (FAA-163)
    this.confirmed = {}; // nor its confirmations: a slot may have moved between the two sessions
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
      receipt = this.receipt('com.enroll', await this.ask(capability, 'com.enroll', args));
    } catch (e) {
      if (e.code === 'held') {
        this.pause(capability);
        return;
      }
      if (e.code === 'fenced') {
        if (await this.gone(capability)) return;
        this.slots[capability] = { state: 'contested', renewedAt: this.now() };
        this.emit('board.slot.contested', 'warn', `Another responder holds the ${capability} slot on this Project; this service waits for it to lapse and never takes it over by itself.`, { notify: true, episode: capability, saidAs: `board.slot.contested:${capability}`, capability });
        return;
      }
      throw e;
    }
    this.slots[capability] = { state: 'held', generation: receipt.slot.generation, renewedAt: this.now() };
    this.heldAt(capability, receipt.slot.generation);
    delete this.said[`board.slot.contested:${capability}`];
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
      if (state === null || TERMINAL.has(state) || NOT_OURS.has(state)) this.checkpoint.drop(entry.request);
      else if (state === 'accepted') (transfer[entry.capability] ??= []).push(entry);
      else reconcile.push(entry);
    }
    const responders = (status.responders ?? []).filter(isObj);
    const generations = Object.fromEntries(responders.map((r) => [r.capability, r.generation ?? 0]));
    const onHold = new Set(responders.filter((r) => r.held === true).map((r) => r.capability)); // DEC-0079
    let failure = null;
    for (const capability of capabilities) {
      const was = this.checkpoint.slots[capability]?.generation;
      if (failure) { // the board session failed: the rest wait for the next tick (FAA-163)
        this.retryLater(capability, transfer[capability] ?? [], failure);
        this.suspect.add(capability); // its move check comes before its retry enrolls (0.56.0 seam r2)
        continue;
      }
      try {
        await this.settle(capability, () => this.recoverOne(capability, status, transfer[capability], was, generations, onHold), transfer[capability] ?? []);
      } catch (e) {
        if (!(e instanceof BoardError)) throw e; // as the Python twin: only the board's refusals are left to retry
        failure = e;
      }
    }
    for (const entry of reconcile) {
      if (this.slots[entry.capability]?.state === 'held') await this.reconcile(entry);
      else if (entry.step !== 'unknown') {
        entry.step = 'unknown'; // the slot is not this session's yet: a later tick reconciles it (finding 38)
        this.checkpoint.put(entry);
      }
    }
    if (failure) throw failure;
  }

  async recoverOne(capability, status, held, was, generations, onHold) {
    if (await this.gone(capability, status)) return; // moved away: never replaced at recovery (FAA-155)
    if (onHold.has(capability)) {
      for (const entry of held ?? []) {
        entry.step = 'lapsed'; // taken back by a transfer once the hold is lifted
        this.checkpoint.put(entry);
      }
      this.pause(capability);
    } else if (held?.length) { // at the generation a replay just recorded, else com.status's
      const mine = this.checkpoint.slots[capability]?.generation;
      await this.replace(capability, held, isInt(mine, 1) && mine !== was ? mine : generations[capability] ?? 0);
    } else await this.enroll(capability);
  }

  async replace(capability, entries, generation) {
    const args = { idempotency: this.idem(this.key('replace')), capability, expectedGeneration: isInt(generation, 0) ? generation : 0 };
    if (entries.length) args.transfer = { requests: entries.map((e) => e.request).slice(0, 64), checkpoint: { summary: 'Resumed by the same service after a restart; no effect had begun.' } };
    let receipt;
    try {
      receipt = this.receipt('com.responder_replace', await this.ask(capability, 'com.responder_replace', args));
    } catch (e) {
      // An earlier lost ask showed the slot moved: said once as board.slot.moved, no outage.
      if (e.code === 'fenced' && this.slots[capability]?.state === 'moved') return;
      if (e.code !== 'held') throw e;
      for (const entry of entries) {
        entry.step = 'lapsed'; // nothing moved: taken back by a transfer once the hold is lifted
        this.checkpoint.put(entry);
      }
      this.pause(capability);
      return;
    }
    this.slots[capability] = { state: 'held', generation: receipt.slot.generation, renewedAt: this.now() };
    this.heldAt(capability, receipt.slot.generation);
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
      if (entry.step === 'replying' && !entry.replied && entry.keys?.reply && !entry.probe) {
        // Finding 35: whether the old reply was stored is asked under the old fence, but only from the resume queue, after
        // the new attempt is recorded: a second lost answer then leaves the request queued, never stranded.
        entry.probe = { generation: entry.generation, attempt: entry.attempt, digest: entry.digest, revision: entry.revision, key: entry.keys.reply };
      }
      Object.assign(entry, { generation: item.attempt.generation, attempt: item.attempt.id, digest: item.attempt.digest, revision: item.revision,
        step: ['accepting', 'held', 'lapsed'].includes(entry.step) ? 'accepted' : entry.step });
      // Finding 35: a fenced key's digest named the old attempt; under the new one it is idempotency_conflict.
      entry.keys = entry.keys?.reconcile ? { reconcile: entry.keys.reconcile } : {};
      this.checkpoint.put(entry);
      if (!this.toResume.includes(entry.request)) this.toResume.push(entry.request);
    }
    await this.resumeNext();
  }

  /**
   * A reply whose answer was lost under the old attempt (finding 35): a stored key answers before the fence is checked
   * (project-comms.md, Idempotency), so the old call again, under the old fence kept in `probe`, says whether it was
   * stored; a refusal says it was not. A lost answer, or a board that cannot be read now, throws and leaves `probe` for
   * the next try: neither says whether the reply was stored.
   */
  async repliedBefore(entry) {
    const { key, generation, attempt, digest, revision } = entry.probe;
    let replied = true;
    try {
      this.receipt('com.reply', await this.call('com.reply', { ...this.replyExtra(entry), fence: this.fence({ ...entry, generation, attempt, digest, revision }, key) }));
    } catch (e) {
      if (['unreachable', 'session-ended', 'authority_changed', 'not_authorized', 'not_available', 'capacity_exceeded'].includes(e.code) || !(e instanceof BoardError)) throw e;
      replied = false;
    }
    if (replied) entry.replied = true;
    delete entry.probe;
    this.checkpoint.put(entry);
  }

  /**
   * Resume a transferred request while nothing runs; each idle tick takes the next (finding 39). A lost answer, of its
   * probe (finding 35) or of the `com.complete` that sends a known outcome (FAA-86), puts the request back first in
   * line, and the next tick sends the same keys again from the checkpoint. It leaves the queue before it resumes, so a
   * handler that settles inside the resume (and reaches `replace`, which resumes the queue again) never runs it twice.
   */
  async resumeNext() {
    while (!this.current && this.toResume.length && !this.stopping) {
      const stored = this.checkpoint.entries[this.toResume[0]];
      if (!stored || this.slots[stored.capability]?.state !== 'held') {
        this.toResume.shift();
        continue;
      }
      const entry = JSON.parse(JSON.stringify(stored));
      if (entry.probe) await this.repliedBefore(entry);
      this.toResume.shift();
      try {
        await this.resume(entry);
      } catch (error) {
        // Back first only while it can still be resumed: once its effect began it waits for reconcile.
        const held = this.checkpoint.entries[entry.request];
        if (held && !held.effect && held.step !== 'unknown' && !this.toResume.includes(entry.request)) this.toResume.unshift(entry.request);
        throw error;
      }
    }
  }

  /** An observed outcome: the one already known, else what observe(entry) reads; null when nothing was observed. */
  async observed(entry) {
    let outcome = isObj(entry.outcome) && entry.outcome.observed === true ? entry.outcome : null;
    if (!outcome && this.observe) {
      try {
        outcome = await this.observe({ ...entry });
      } catch {
        outcome = null; // an observation that failed is no observation
      }
    }
    return isObj(outcome) && outcome.observed === true && !outcomeProblems({ ...outcome, observed: true }, true).length ? outcome : null;
  }

  async reconcile(entry) {
    const state = await this.readState(entry);
    if (state !== 'outcome_unknown') {
      if (state !== null && (TERMINAL.has(state) || NOT_OURS.has(state))) this.checkpoint.drop(entry.request);
      else if (state === 'in_progress' && entry.step !== 'unknown') {
        entry.step = 'unknown'; // no next holder took the slot yet: a later tick tries again (finding 38)
        this.checkpoint.put(entry);
      }
      return;
    }
    const outcome = await this.observed(entry);
    if (!outcome) {
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
      if (this.state === 'down') { // a lost call was sent again and answered: the session held throughout
        this.state = 'ready';
        delete this.said['board.down'];
      }
      return this.interval();
    } catch (e) {
      if (!(e instanceof BoardError) && !(e instanceof HubError)) throw e;
      return this.fault(e);
    }
  }

  /** Seconds this session's leases still run, by its own clock: the running attempt's, else the oldest held slot's. */
  leaseLeft() {
    const renewed = this.current ? [this.current.renewedAt ?? 0]
      : Object.values(this.slots).filter((s) => s.state === 'held' && s.renewedAt !== -Infinity).map((s) => s.renewedAt ?? 0); // a lapsed slot holds no lease (FAA-163)
    return renewed.length && this.session ? Math.min(...renewed) + LEASE_SECONDS - this.now() : 0;
  }

  async fault(e) {
    const code = e.code ?? 'unreachable';
    const connecting = this.state === 'connecting' && !Object.values(this.slots).some((s) => s?.state === 'held');
    let wait = this.backoff.next();
    const left = this.leaseLeft() - LEASE_MARGIN_SECONDS;
    const keep = code === 'unreachable' && left > 0; // finding 38: the lease holds, so the session and the work stay
    if (keep) wait = Math.max(1, Math.min(wait, left)); // and the call goes again before the lease lapses
    this.waitUntil = this.now() + wait;
    if (['not_authorized', 'authority_changed', 'credential'].includes(code)) {
      this.state = 'not-authorized';
      await this.dropSession();
      this.emit('board.access.needed', 'warn', 'This service may not answer requests for this Project: the operator has to allow it in Fabric (Agents & access). Nothing is claimed until then.', { notify: true, episode: 'access', reason: code });
    } else if (code === 'held') {
      this.state = 'paused';
      this.emit('board.held', 'info', 'The operator holds new work on this Project; the responder waits and asks again with a growing pause.', { episode: 'held', reason: code });
    } else if (['no-epoch', 'schema-unsupported', 'checkpoint', 'receipt-shape', 'idempotency_conflict'].includes(code)) {
      // idempotency_conflict is a key sent with other content, a defect and not an outage (finding 35)
      this.state = 'down';
      await this.dropSession();
      this.emit('board.blocked', 'error', `The responder stopped answering requests: ${e.message}`, { notify: true, episode: code, reason: code });
    } else {
      this.state = 'down';
      // A refusal in recovery that left no slot held reconnects (seam 6); one that left some held serves them (seam 7).
      if ((connecting || ['session-ended', 'unreachable', 'not-running', 'not-a-hub', 'hub-unavailable', 'protocol'].includes(code)) && !keep) await this.dropSession();
      this.emit('board.down', 'warn', 'Fabric\'s board cannot be reached; the responder tries again with a growing pause.', { episode: 'down', reason: code });
    }
    return wait;
  }

  async dropSession() {
    const work = this.current;
    this.current = null;
    this.toResume = []; // the next session transfers them again
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
    // The DELETE released the slots: a standby taking one is no move (FAA-163).
    if (session && await session.close()) this.checkpoint.leave(this.project, this.heldNow());
  }

  async tick() {
    const work = this.current;
    if (work) {
      if (work.done) await this.finish(work);
      else await this.renew(work);
    }
    const heldByWork = work && this.current ? work.entry.capability : null;
    for (const capability of [...this.suspect]) { // kept until com.status answered, so it is asked before any enroll
      await this.gone(capability);
      this.suspect.delete(capability);
    }
    for (const [capability, slot] of Object.entries(this.slots)) {
      if (slot.state === 'moved') continue; // never enrolled again on its own, even when the new holder's lease lapses (FAA-155)
      if (slot.state === 'paused') {
        // still held: a longer pause; lifted: the slot is ours again
        if (capability !== heldByWork && this.now() >= (slot.retryAt ?? 0) && !(await this.gone(capability))) await this.enroll(capability); // a move is read first
        continue;
      }
      if (slot.state === 'retry') { // its enroll was refused: asked again alone (FAA-163)
        if (this.now() >= (slot.retryAt ?? 0)) await this.settle(capability, async () => (await this.gone(capability)) || this.enroll(capability));
        continue;
      }
      if (capability !== heldByWork && this.now() - (slot.renewedAt ?? 0) >= RENEW_SECONDS - 0.5) await this.enroll(capability);
    }
    if (!this.current && !this.stopping) {
      await this.continueLapsed();
      await this.resumeNext();
    }
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
          this.slots[capability].renewedAt = -Infinity; // lapsed: this enroll may move the generation, so it is recorded
          await this.enroll(capability);
          continue;
        }
        if (e.code === 'idempotency_window_expired' || e.code === 'capacity_exceeded') {
          delete this.claimKeys[capability];
          await this.status();
          continue;
        }
        if (e.code === 'fenced') {
          if (!(await this.gone(capability))) this.slots[capability] = { state: 'contested', renewedAt: this.now() };
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
      receipt = await this.fenced('com.accept', entry, entry.keys.accept);
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

  /**
   * A fenced call, one at a time (finding 36): fence built, sent and receipt applied under the lock. A revision_conflict
   * on com.renew or com.progress (they store nothing) reads the revision and sends once more. On a stop code the attempt
   * is lost: the work stops, and it answers null (authority_changed throws after, so the responder stops claiming).
   */
  async fenced(op, entry, key, extra = {}, apply = null) {
    let again = op === 'com.renew' || op === 'com.progress';
    for (;;) {
      try {
        return await this.locked(async () => {
          const receipt = this.receipt(op, await this.call(op, { ...extra, fence: this.fence(entry, key) }));
          apply?.(receipt);
          return receipt;
        });
      } catch (e) {
        if (e.code === 'revision_conflict' && again) {
          again = false;
          await this.locked(() => this.readState(entry));
          continue;
        }
        if (STOP_CODES.has(e.code) || ['revision_conflict', 'invalid_transition', 'digest_conflict'].includes(e.code)) {
          if (e.code === 'fenced') this.suspect.add(entry.capability); // the next tick asks com.status whether the slot moved
          this.lose(entry, e.code);
          if (e.code === 'authority_changed') throw e;
          return null;
        }
        throw e;
      }
    }
  }

  lose(entry, code) {
    if (this.current && this.current.entry === entry) this.current.ctx.stopped = true;
    if (entry.effect) {
      entry.step = 'unknown';
      this.checkpoint.put(entry);
      this.emit('board.reconcile.needed', 'warn', 'The attempt was lost after its effect began; the outcome stays unknown until this service observes what happened.', { notify: true, episode: entry.request, request: entry.request, capability: entry.capability, reason: code });
    } else if (!['claimed', 'accepting'].includes(entry.step) && (code === 'lease_expired' || (code === 'fenced' && entry.capability in this.checkpoint.slots))) {
      // Accepted work whose lease lapsed, or fenced off a slot this responder held (moved, FAA-155): the board holds it
      // (C4). It continues only by a checkpoint transfer to this responder while it holds the slot.
      entry.step = 'lapsed';
      this.checkpoint.put(entry);
      this.emit('board.attempt.lost', 'warn', code === 'lease_expired' ? 'This service\'s lease on an accepted request lapsed; it stopped working on it and takes it back by a transfer.'
        : 'The board fenced an accepted request away from this service; it stopped working on it, and nothing had been done outside it.', { request: entry.request, capability: entry.capability, reason: code });
    } else {
      this.checkpoint.drop(entry.request);
      this.emit('board.attempt.lost', 'warn', `The board took a request back from this service (${code}); it stopped working on it, and nothing had been done outside the service.`, { request: entry.request, capability: entry.capability, reason: code });
    }
  }

  async renew(work) {
    if (this.now() - (work.renewedAt ?? 0) < RENEW_SECONDS - 0.5) return;
    if (!(await this.fenced('com.renew', work.entry, this.key('renew')))) {
      this.current = null;
      return;
    }
    work.renewedAt = this.now();
    (this.slots[work.entry.capability] ??= {}).renewedAt = this.now();
  }

  async progress(entry, note) {
    const extra = note !== undefined && note !== null ? { note: { text: clean(note) || 'Working.' } } : {};
    if (!(await this.fenced('com.progress', entry, this.key('progress'), extra))) throw new Stopped();
  }

  async effectBegin(entry, summary, ctx) {
    entry.keys.effect_begin ??= this.key('effect');
    entry.step = 'effect-beginning';
    entry.effect = true; // from here a lost attempt is an unknown outcome, never "nothing happened"
    this.checkpoint.put(entry);
    const extra = summary ? { summary: clean(summary) } : {};
    const begun = (receipt) => {
      entry.revision = receipt.request.revision;
      entry.step = 'in-progress';
      this.checkpoint.put(entry);
    };
    let receipt = null;
    let lost = 0;
    let delay = this.holdDelay;
    for (;;) { // a lost answer: the same key again tells whether it was stored
      try {
        receipt = await this.fenced('com.effect_begin', entry, entry.keys.effect_begin, extra, begun);
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
  }

  async finish(work) {
    const { entry } = work;
    if (work.ctx.stopped && !(entry.request in this.checkpoint.entries)) {
      this.current = null;
      return;
    }
    let { outcome } = work;
    if (work.failure) {
      if (entry.effect) {
        await this.settleLive(entry, 'handler-failed');
        return;
      }
      if (work.failure instanceof Stopped) {
        this.current = null;
        return;
      }
      outcome = { state: 'failed_known', observed: true, summary: `The service could not do this (${work.failure?.name ?? 'Error'}).` };
    }
    const problems = outcomeProblems(outcome, !!entry.effect);
    if (problems.length) {
      this.emit('board.outcome.invalid', 'warn', `The handler's outcome was not sent: ${problems[0]}.`, { request: entry.request, capability: entry.capability });
      if (entry.effect) await this.settleLive(entry, problems.some((p) => p.includes('observation_required')) ? 'observation_required' : 'outcome');
      else {
        entry.outcome = { state: 'failed_known', observed: true, summary: 'The service answered in a form it cannot send.' };
        await this.complete(entry);
      }
      return;
    }
    entry.outcome = { ...outcome, observed: outcome.observed ?? !entry.effect };
    await this.complete(entry);
  }

  /**
   * Finding 37: the handler threw after beginEffect, or answered unobserved, while the attempt is live. Only an observed
   * result settles a started effect (project-comms.md, Request lifecycle), so observe(entry) is completed under the live
   * fence. With nothing observed, com.responder_replace on this responder's own slot is the contract's lost-result
   * operation ("an in_progress one becomes outcome_unknown ... when the next holder takes the slot", Slots end with the
   * session); com.reconcile settles it once something is observed.
   */
  async settleLive(entry, code) {
    const lost = !!this.current?.ctx.stopped; // the attempt is not live: nothing to settle
    const state = lost ? null : await this.readState(entry);
    if (state === 'accepted') { // effect_begin was never stored, so nothing began: a known failure
      entry.effect = false;
      entry.outcome = { state: 'failed_known', observed: true, summary: `The service could not do this (${code}).` };
      await this.complete(entry);
      return;
    }
    const outcome = state === 'in_progress' ? await this.observed(entry) : null;
    if (outcome) {
      entry.outcome = { ...Object.fromEntries(['state', 'summary', 'evidence'].filter((k) => k in outcome).map((k) => [k, outcome[k]])), observed: true };
      await this.complete(entry);
      return;
    }
    this.current = null;
    this.lose(entry, code);
    const slot = this.slots[entry.capability] ?? {};
    if (state === 'in_progress' && slot.state === 'held') await this.replace(entry.capability, [], slot.generation ?? 0);
  }

  replyExtra(entry) {
    const { reply } = entry.outcome;
    return { body: { text: reply.text, ...(reply.format ? { format: reply.format } : {}) }, ...(reply.artifacts?.length ? { artifacts: reply.artifacts } : {}) };
  }

  async complete(entry) {
    const { outcome } = entry;
    if (outcome.reply && !entry.replied) {
      entry.keys.reply ??= this.key('reply');
      entry.step = 'replying';
      this.checkpoint.put(entry);
      if (!(await this.fenced('com.reply', entry, entry.keys.reply, this.replyExtra(entry)))) {
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
    const receipt = await this.fenced('com.complete', entry, entry.keys.complete, { outcome: sent });
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
      const session = this.session;
      this.session = null;
      // Only a DELETE Fabric answered released the slots (FAA-163): no record of them can read as a move. An idle stop
      // waits for it 3 s (FAA-173).
      if (await session.close(work ? null : IDLE_LEAVE_SECONDS * 1000)) this.checkpoint.leave(this.project, this.heldNow());
    }
    this.state = 'stopped';
  }
}
