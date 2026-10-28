"""The board responder's slot records (FAA-155, FAA-163): the generation it holds each slot at, a move to another
session and its take-back, and a capability whose enroll was refused, retried on its own. Part of the board connector
(FAA-65, layer L4); `Responder` (fabric_board_session) is a `SlotKeeper`."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
from fabric_board_shapes import BoardError, LEASE_SECONDS, _is_int  # noqa: E402 - the kit (FAA-65)

#: A lost call is sent again this long before the lease it keeps would lapse (FAA-77, finding 38).
LEASE_MARGIN_SECONDS = 10.0

#: How long a held slot waits before it asks again: doubling from the poll interval, never past this.
HOLD_RETRY_MAX_SECONDS = 900.0

#: Refusals that are about the board session, not one capability: they end recovery and go to the responder's fault.
SESSION_CODES = frozenset(["unreachable", "session-ended", "not_authorized", "authority_changed", "credential", "no-epoch",
                           "schema-unsupported", "checkpoint", "receipt-shape", "idempotency_conflict", "not-running",
                           "not-a-hub", "hub-unavailable", "protocol", "not_available"])

_whole = lambda v: int(v) if isinstance(v, float) and v.is_integer() else v  # noqa: E731 - 2.0 is 2, as Node reads it


class SlotKeeper:
    """The slot methods of `Responder`, which owns every attribute they read (`checkpoint`, `slots`, `project`, `_lock`)."""

    # -- a slot moved to another session (FAA-155, DEC-0140 PR-2) ------------------------------------------------
    def _held_at(self, capability: str, generation: int) -> None:
        """The generation this responder holds the slot at, kept beside its checkpoint so a restart knows it."""
        self._note(capability, {"project": self.project, "generation": generation})
        self._confirmed[capability] = generation
        self._said.pop("board.slot.refused:" + capability, None)  # held again: a later refusal is said again
        self._said.pop("board.slot.contested:" + capability, None)  # and a later contest, by enroll or replace

    def _note(self, capability: str, record: Optional[Dict[str, Any]]) -> None:
        """The slot record, best effort: one that cannot be written now is written at the next receipt."""
        try:
            self.checkpoint.slot(capability, record)
        except BoardError:
            pass

    def _ask(self, capability: str, op: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """An enroll or replace that can move the generation is recorded with its key first (a lost answer is no move)."""
        held = self.checkpoint.slots.get(capability) or {}
        if held.get("project") != self.project:
            return self._call(op, args)  # no record: nothing a lost answer could be mistaken for
        slot = self.slots.get(capability) or {}
        if op == "com.enroll" and slot.get("state") == "held" and slot.get("generation") == held.get("generation") \
                and self.now() - slot.get("renewed_at", 0.0) < LEASE_SECONDS - LEASE_MARGIN_SECONDS and "asking" not in held:
            return self._call(op, args)  # a live holder's renew cannot change its generation: nothing to record
        if isinstance(held.get("asking"), dict):
            if self._gone(capability):  # an earlier lost ask is settled first; it may show the slot moved
                raise BoardError("fenced", "The %s slot moved to another session." % capability, op=op)
            held = self.checkpoint.slots.get(capability) or {}
        try:
            self.checkpoint.slot(capability, dict(held, asking={"op": op, "args": args}))
            return self._call(op, args)
        except BoardError as exc:
            if exc.code == "checkpoint":
                return self._call(op, args)
            if exc.code not in ("unreachable", "session-ended"):
                self._note(capability, held)
            raise

    def _replay(self, capability: str, held: Dict[str, Any], before: Any) -> Dict[str, Any]:
        """Asks a lost enroll or replace again under its key. `repeated: true`: the generation is ours. Else it ran only now: past
        a move (`before` beyond the record) the move is read. A refusal drops the record; a lost answer keeps it."""
        asking = held.get("asking")
        rest = {k: v for k, v in held.items() if k != "asking"}
        if isinstance(asking, dict) and asking.get("op") in ("com.enroll", "com.responder_replace"):
            try:
                answer = self._receipt(asking["op"], self._call(asking["op"], asking.get("args")))
                generation, moved = _whole(answer["slot"]["generation"]), _is_int(before, 1) and before > rest.get("generation", before)
                if _is_int(generation, 1) and (answer.get("repeated") is True or not moved):
                    rest = {"project": self.project, "generation": generation}
            except BoardError as exc:
                if exc.code in ("unreachable", "session-ended"):
                    raise
                if exc.code == "idempotency_window_expired":
                    rest = {}  # a retired epoch refuses even a repeat: unknown, so no record (a first start, never a move)
            except (KeyError, TypeError):
                pass
        self._note(capability, rest or None)
        return rest

    def _gone(self, capability: str, status: Optional[Dict[str, Any]] = None) -> bool:
        """True when `com.status` shows the slot's generation past the record (the slot is left `moved`); else False."""
        held = self.checkpoint.slots.get(capability) or {}
        if held.get("project") != self.project or (not _is_int(held.get("generation"), 1) and "asking" not in held):
            return False
        status = self._status() if status is None else status
        now = _whole(next((r.get("generation") for r in status.get("responders") or [] if isinstance(r, dict) and r.get("capability") == capability), None))
        held = self._replay(capability, held, now) if "asking" in held else held  # its own lost ask first
        if "moved" in held and _is_int(held.get("moved"), 1) and not (_is_int(now, 1) and now > held.get("generation", now)):
            now = held["moved"]  # a recorded move stays until take_back, whatever com.status says of the slot now
        if not _is_int(now, 1) or not _is_int(held.get("generation"), 1) or now <= held["generation"]:
            if _is_int(now, 1) and _is_int(held.get("generation"), 1) and "moved" not in held:
                self._confirmed[capability] = held["generation"]  # com.status shows it unmoved (0.56.0 seam r3)
            return False
        with self._lock:
            record = self.checkpoint.slots.get(capability) or {}
            if record.get("project") != self.project or record.get("generation") != held.get("generation"):
                return False  # take_back (an action thread) forgot the record meanwhile: no move to keep (FAA-158)
            work = self.current
            if work is not None and work.entry["capability"] == capability:
                work.ctx.stopped.set()
                self.current = None
            for entry in [dict(e) for e in self.checkpoint.entries.values() if e.get("capability") == capability]:
                if entry.get("step") == "claimed":
                    self.checkpoint.drop(entry["request"])  # the move returned the claim to the queue
                elif entry.get("step") not in ("unknown", "lapsed"):
                    # Begun: outcome_unknown, which the slot's holder reconciles. Accepted: held on the board, continued only
                    # by a transfer if the slot is this service's again; never a com.responder_replace on its own.
                    entry["step"] = "unknown" if entry.get("effect") else "lapsed"
                    self.checkpoint.put(entry)
            self._to_resume = [r for r in self._to_resume if (self.checkpoint.entries.get(r) or {}).get("capability") != capability]
            self.slots[capability] = {"state": "moved", "generation": now, "renewed_at": self.now()}
            self._confirmed.pop(capability, None)
            if "moved" not in held:
                self._note(capability, dict(held, moved=now))  # said again at the next start if it cannot be written
        if "moved" not in held:  # once, even across restarts
            self._emit("board.slot.moved", "warning", "The %s slot on this Project moved to another session. This service stopped answering it there and left its "
                       "accepted work `accepted` (work begun is the new holder's to settle). Its take-back action brings the "
                       "slot back once the other session lets it go, or at a later restart or reconnect while accepted work "
                       "waits; a restart alone does not. Without it, ask its maintainer." % capability,
                       notify=True, episode=capability, capability=capability, generation=now, held=held["generation"])
        return True

    def take_back(self, capability: str) -> None:
        """The operator's act, never the kit's: forget the move; the next tick enrolls once the slot is free (FAA-155)."""
        if capability not in self.capabilities:
            raise BoardError("invalid_arguments", "This responder does not answer %s." % capability)
        with self._lock:
            self.checkpoint.slot(capability, None)
            if (self.slots.get(capability) or {}).get("state") == "moved":
                self.slots[capability] = {"state": "contested", "renewed_at": 0.0}
            self._said.pop("board.slot.moved", None)

    # -- one capability's refusal (FAA-163) ------------------------------------------------------------------------
    def _retry_later(self, capability: str, entries: List[Dict[str, Any]], exc: BoardError) -> None:
        """An enroll or replace of one capability was refused: its accepted work waits `lapsed` (a transfer takes it
        back once the slot is held) and the capability asks again after a doubling pause; the others go on. A refusal
        of the board session (SESSION_CODES) is not this capability's: it is left to retry and nothing is said, since
        the responder's fault says the board is down."""
        if (self.slots.get(capability) or {}).get("state") == "held":
            return  # the replace landed: what failed came after it
        for entry in entries:
            if entry.get("step") not in ("unknown", "lapsed"):
                entry["step"] = "lapsed"
                self.checkpoint.put(entry)
        slot = self.slots.get(capability) or {}
        tries = slot.get("tries", 0) + 1 if slot.get("state") == "retry" else 1
        wait = min(HOLD_RETRY_MAX_SECONDS, self.hold_delay * 2 ** (tries - 1))
        self.slots[capability] = {"state": "retry", "tries": tries, "retry_at": self.now() + wait, "renewed_at": self.now()}
        if exc.code not in SESSION_CODES:  # once per episode (said_as), also after a silent session refusal
            self._emit("board.slot.refused", "warning", "Fabric refused to give this service the %s slot (%s); it asks again "
                       "later. Its other capabilities go on." % (capability, exc.code), episode=capability,
                       said_as="board.slot.refused:" + capability,
                       capability=capability, reason=exc.code)

    def _settle(self, capability: str, act, entries: Optional[List[Dict[str, Any]]] = None) -> None:
        """Runs one capability's enroll or replace (FAA-163). A refusal of the board session is raised after the
        capability is left to retry; any other leaves it to retry and the next capability goes on."""
        try:
            act()
        except BoardError as exc:
            self._retry_later(capability, entries or [], exc)
            if exc.code in SESSION_CODES:
                raise
