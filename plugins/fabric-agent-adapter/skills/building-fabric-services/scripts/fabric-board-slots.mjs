// The board responder's slot records (FAA-155, FAA-163): the generation it holds each slot at, a move to another
// session and its take-back, and a capability whose enroll was refused, retried on its own. Part of the board
// connector (FAA-65, layer L4); Responder (fabric-board-session.mjs) extends SlotKeeper.
import { BoardError, LEASE_SECONDS, isInt, isObj } from './fabric-board-shapes.mjs';

// The answer may have been stored: send it again with the same key (BoardError).
export const LOST = ['unreachable', 'session-ended'];

/** A lost call is sent again this long before the lease it keeps would lapse (FAA-77, finding 38). */
export const LEASE_MARGIN_SECONDS = 10;

/** How long a held slot waits before it asks again: doubling from the poll interval, never past this. */
export const HOLD_RETRY_MAX_SECONDS = 900;

/** Refusals that are about the board session, not one capability: they end recovery and go to the responder's fault. */
export const SESSION_CODES = Object.freeze(new Set(['unreachable', 'session-ended', 'not_authorized', 'authority_changed', 'credential', 'no-epoch',
  'schema-unsupported', 'checkpoint', 'receipt-shape', 'idempotency_conflict', 'not-running', 'not-a-hub', 'hub-unavailable', 'protocol', 'not_available']));

/** The slot methods of Responder, which owns every field they read (checkpoint, slots, project, locked). */
export class SlotKeeper {
  // -- a slot moved to another session (FAA-155, DEC-0140 PR-2) --
  /** The generation this responder holds the slot at, kept beside its checkpoint; a failed write is retried at the next receipt. */
  heldAt(capability, generation) {
    this.note(capability, { project: this.project, generation });
    this.confirmed[capability] = generation;
    delete this.said[`board.slot.refused:${capability}`]; // held again: a later refusal is said again
    delete this.said[`board.slot.contested:${capability}`]; // and a later contest, by enroll or replace
  }

  /** The slot record, best effort: one that cannot be written now is written at the next receipt. */
  note(capability, record) {
    try {
      this.checkpoint.slot(capability, record);
    } catch {
      // the request steps fail closed on their own
    }
  }

  /**
   * An enroll or replace is recorded with its key before it is sent, so a lost answer is never read as a move; a refusal
   * drops the record, a receipt replaces it (heldAt), a record that cannot be written is skipped.
   */
  async ask(capability, op, args) {
    let held = this.checkpoint.slots[capability] ?? {};
    if (held.project !== this.project) return this.call(op, args); // no record: nothing a lost answer could be mistaken for
    const slot = this.slots[capability] ?? {};
    if (op === 'com.enroll' && slot.state === 'held' && slot.generation === held.generation
      && this.now() - (slot.renewedAt ?? 0) < LEASE_SECONDS - LEASE_MARGIN_SECONDS && !('asking' in held)) {
      return this.call(op, args); // a live holder's renew cannot change its generation: nothing to record
    }
    if (isObj(held.asking)) {
      // An earlier lost ask is settled first; it may show the slot moved.
      if (await this.gone(capability)) throw new BoardError('fenced', `The ${capability} slot moved to another session.`, false, op);
      held = this.checkpoint.slots[capability] ?? {};
    }
    try {
      this.checkpoint.slot(capability, { ...held, asking: { op, args } });
    } catch {
      return this.call(op, args);
    }
    try {
      return await this.call(op, args);
    } catch (e) {
      if (!LOST.includes(e.code)) this.note(capability, held);
      throw e;
    }
  }

  /**
   * Asks a lost enroll or replace again under its key. `repeated: true`: it landed, the generation is ours. Else it ran
   * only now: if the slot had moved past the record (`before`), the record stays and the move is read (the slot just
   * taken lapses unused). A refusal or an odd receipt drops the record; a lost answer keeps it.
   */
  async replay(capability, held, before) {
    const { asking, ...rest } = held;
    let record = rest;
    if (isObj(asking) && ['com.enroll', 'com.responder_replace'].includes(asking.op)) {
      try {
        const answer = this.receipt(asking.op, await this.call(asking.op, asking.args));
        const generation = answer.slot?.generation;
        const moved = isInt(before, 1) && isInt(rest.generation, 1) && before > rest.generation;
        if (isInt(generation, 1) && (answer.repeated === true || !moved)) record = { project: this.project, generation };
      } catch (e) {
        if (LOST.includes(e.code)) throw e;
        if (e.code === 'idempotency_window_expired') record = {}; // a retired epoch: unknown, so a first start, no move
      }
    }
    this.note(capability, Object.keys(record).length ? record : null);
    return record;
  }

  /**
   * True when com.status shows the slot's generation past the one recorded held: the operator or another session moved
   * it. The slot is left `moved`. No record, another Project's, an odd value or no later generation: false.
   */
  async gone(capability, status = null) {
    let held = this.checkpoint.slots[capability] ?? {};
    if (held.project !== this.project || (!isInt(held.generation, 1) && !('asking' in held))) return false;
    let now = ((status ?? await this.status()).responders ?? []).find((r) => isObj(r) && r.capability === capability)?.generation;
    if ('asking' in held) held = await this.replay(capability, held, now); // its own lost ask first
    if (isInt(held.moved, 1) /* a recorded move stays until takeBack */ && !(isInt(now, 1) && now > (held.generation ?? now))) now = held.moved;
    if (!isInt(now, 1) || !isInt(held.generation, 1) || now <= held.generation) {
      if (isInt(now, 1) && isInt(held.generation, 1) && !('moved' in held)) this.confirmed[capability] = held.generation; // com.status shows it unmoved (0.56.0 seam r3)
      return false;
    }
    // On the fence queue (FAA-158): a fenced call in flight lands first, and a takeBack meanwhile wins.
    return this.locked(() => this.moved(capability, held, now));
  }

  /** The slot moved past `held` to `now`: stop its work, keep its accepted requests held, say it once. */
  moved(capability, held, now) {
    const record = this.checkpoint.slots[capability] ?? {};
    if (record.project !== this.project || record.generation !== held.generation) return false; // a takeBack forgot it
    if (this.current?.entry.capability === capability) {
      this.current.ctx.stopped = true;
      this.current = null;
    }
    for (const entry of Object.values(this.checkpoint.entries).filter((e) => e.capability === capability).map((e) => ({ ...e }))) {
      if (entry.step === 'claimed') this.checkpoint.drop(entry.request); // the move returned the claim to the queue
      else if (!['unknown', 'lapsed'].includes(entry.step)) {
        // Begun: outcome_unknown, which the slot's holder reconciles. Accepted: held on the board, continued only by a
        // transfer if the slot is this service's again; never a com.responder_replace on its own.
        entry.step = entry.effect ? 'unknown' : 'lapsed';
        this.checkpoint.put(entry);
      }
    }
    this.toResume = this.toResume.filter((r) => this.checkpoint.entries[r]?.capability !== capability);
    this.slots[capability] = { state: 'moved', generation: now, renewedAt: this.now() };
    delete this.confirmed[capability];
    if (!('moved' in held)) { // once, even across restarts
      this.emit('board.slot.moved', 'warning', `The ${capability} slot on this Project was moved to another session. This service stopped answering it there, left its accepted work \`accepted\` and unanswered (work already begun is the new holder's to settle) and does not take the slot back by itself. Its take-back action brings it back once the other session lets it go, or at once at a restart or reconnect while it holds accepted work for the slot; without one, ask its maintainer.`, { notify: true, episode: capability, capability, generation: now, held: held.generation });
      this.note(capability, { ...held, moved: now }); // said again at the next start if it cannot be written
    }
    return true;
  }

  /**
   * The operator's act, never the kit's: forget that a capability's slot moved away. In the same board session the next
   * tick enrolls once the slot is free; a reconnect with held work takes it back at once by a transfer (FAA-155).
   */
  takeBack(capability) {
    if (!this.capabilities.includes(capability)) throw new BoardError('invalid_arguments', `This responder does not answer ${capability}.`);
    this.checkpoint.slot(capability, null);
    if (this.slots[capability]?.state === 'moved') this.slots[capability] = { state: 'contested', renewedAt: 0 };
    delete this.said['board.slot.moved'];
  }

  // -- one capability's refusal (FAA-163) --
  /**
   * An enroll or replace of one capability was refused: its accepted work waits `lapsed` (a transfer takes it back once
   * the slot is held) and the capability asks again after a doubling pause; the others go on.
   */
  retryLater(capability, entries, e) {
    if (this.slots[capability]?.state === 'held') return; // the replace landed: what failed came after it
    for (const entry of entries) {
      if (!['unknown', 'lapsed'].includes(entry.step)) {
        entry.step = 'lapsed';
        this.checkpoint.put(entry);
      }
    }
    const slot = this.slots[capability] ?? {};
    const tries = slot.state === 'retry' ? (slot.tries ?? 0) + 1 : 1;
    const wait = Math.min(HOLD_RETRY_MAX_SECONDS, this.holdDelay * 2 ** (tries - 1));
    this.slots[capability] = { state: 'retry', tries, retryAt: this.now() + wait, renewedAt: this.now() };
    if (!SESSION_CODES.has(e.code)) { // once per episode (saidAs), also after a silent session refusal // a refusal of the board session is the fault's to say
      this.emit('board.slot.refused', 'warning', `Fabric refused to give this service the ${capability} slot (${e.code}); it asks again later. Its other capabilities go on.`, { episode: capability, saidAs: `board.slot.refused:${capability}`, capability, reason: e.code });
    }
  }

  /** Runs one capability's enroll or replace (FAA-163): a refusal of the board session is raised after the capability is left to retry. */
  async settle(capability, act, entries = []) {
    try {
      await act();
    } catch (e) {
      if (!(e instanceof BoardError)) throw e;
      this.retryLater(capability, entries, e);
      if (SESSION_CODES.has(e.code)) throw e;
    }
  }
}
