// SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
// The board responder's restart recovery (DEC-0078, findings 35, 38 and 39): what a restart finds in its checkpoint is
// read back from the board, then transferred by com.responder_replace, resumed, or reconciled from what the service
// observed. Part of the Node board connector (FAA-65, layer L4); the twin of fabric_board_recovery.py. Responder
// (fabric-board-session.mjs) extends Recovery.
import { BoardError, isInt, isObj, outcomeProblems } from './fabric-board-shapes.mjs';
import { SlotKeeper } from './fabric-board-slots.mjs';

export const TERMINAL = new Set(['completed', 'failed_known', 'cancelled', 'expired']);
// No longer this responder's to work on: back in the queue, claimed again, or answered by the target Project's
// participant reply (DEC-0098, DEC-0102; not terminal, the requester may still cancel it, and nobody claims it).
export const NOT_OURS = new Set(['queued', 'claimed', 'answered']);

/** The restart methods of Responder, which owns every field they read (checkpoint, slots, observe, toResume). */
export class Recovery extends SlotKeeper {
  async recover(status, capabilities) {
    const transfer = Object.create(null);
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
    const generations = Object.assign(Object.create(null), Object.fromEntries(responders.map((r) => [r.capability, r.generation ?? 0])));
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
        this.emit('board.request.held', 'warning', 'An accepted request could not be resumed: this Fabric does not hand back a transferred attempt (DEC-0078). It stays held; nothing was done.', { notify: true, episode: entry.request, request: entry.request, capability });
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
      // foreign-user: nothing was sent now, so whether the old reply was stored is unknown (0.79.0 seam reading)
      if (['unreachable', 'foreign-user', 'session-ended', 'authority_changed', 'not_authorized', 'not_available', 'capacity_exceeded'].includes(e.code) || !(e instanceof BoardError)) throw e;
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
      this.emit('board.reconcile.needed', 'warning', 'A request\'s outcome is unknown: the work may have happened. It stays unknown until this service observes what happened.', { notify: true, episode: entry.request, request: entry.request, capability: entry.capability });
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

  async continueLapsed() {
    const lapsed = Object.create(null);
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
}
