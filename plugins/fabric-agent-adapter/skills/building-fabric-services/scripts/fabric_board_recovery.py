# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
"""The board responder's restart recovery (DEC-0078, findings 35, 38 and 39): what a restart finds in its checkpoint is
read back from the board, then transferred by `com.responder_replace`, resumed, or reconciled from what the service
observed. Part of the board connector (FAA-65, layer L4); `Responder` (fabric_board_session) is a `Recovery`."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import sys as _sys  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
if str(_Path(__file__).resolve().parent) not in _sys.path:  # the kit loads from any working directory (FAA-65)
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
from fabric_board_shapes import BoardError, _is_int, outcome_problems  # noqa: E402 - the kit (FAA-65)
from fabric_board_slots import SlotKeeper, _whole  # noqa: E402 - the slot records (FAA-155, FAA-163)

TERMINAL = frozenset(["completed", "failed_known", "cancelled", "expired"])
#: No longer this responder's to work on: back in the queue, claimed again, or answered by the target Project's
#: participant reply (DEC-0098, DEC-0102; not terminal, the requester may still cancel it, and nobody claims it).
NOT_OURS = frozenset(["queued", "claimed", "answered"])


class Recovery(SlotKeeper):
    """The restart methods of `Responder`, which owns every attribute they read (`checkpoint`, `slots`, `observe`,
    `_to_resume`) and the calls they make (`_call`, `_read_state`, `_enroll`, `_resume`)."""

    def _recover(self, status: Dict[str, Any], capabilities: List[str]) -> None:
        transfer: Dict[str, List[Dict[str, Any]]] = {}
        reconcile: List[Dict[str, Any]] = []
        for entry in list(self.checkpoint.entries.values()):
            if entry.get("capability") not in capabilities:
                continue
            try:
                state = self._read_state(entry)
            except BoardError as exc:
                if exc.code in ("not_authorized",):
                    self.checkpoint.drop(entry["request"])
                    continue
                raise
            if state is None or state in TERMINAL or state in NOT_OURS:
                self.checkpoint.drop(entry["request"])  # settled, or no longer this responder's (NOT_OURS)
            elif state == "accepted":
                transfer.setdefault(entry["capability"], []).append(entry)
            else:  # in_progress (lost result once a new generation holds the slot) or outcome_unknown
                reconcile.append(entry)
        responders = [r for r in status.get("responders") or [] if isinstance(r, dict)]
        generations = {r.get("capability"): _whole(r.get("generation", 0)) for r in responders}
        on_hold = {r.get("capability") for r in responders if r.get("held") is True}  # DEC-0079
        failure: Optional[BoardError] = None
        for capability in capabilities:
            held, was = transfer.get(capability), (self.checkpoint.slots.get(capability) or {}).get("generation")
            if failure is not None:  # the board session failed: the rest wait for the next tick (FAA-163)
                self._retry_later(capability, held or [], failure)
                self._suspect.add(capability)  # its move check comes before its retry enrolls (0.56.0 seam r2)
                continue
            try:
                self._settle(capability, lambda: self._recover_one(capability, status, held, was, generations, on_hold), held)
            except BoardError as exc:
                failure = exc
        for entry in reconcile:
            if self.slots.get(entry["capability"], {}).get("state") == "held":
                self._reconcile(entry)
            elif entry.get("step") != "unknown":
                entry["step"] = "unknown"  # the slot is not this session's yet: a later tick reconciles it (finding 38)
                self.checkpoint.put(entry)
        if failure is not None:
            raise failure

    def _recover_one(self, capability: str, status: Dict[str, Any], held: Optional[List[Dict[str, Any]]], was: Any,
                     generations: Dict[Any, Any], on_hold: set) -> None:
        if self._gone(capability, status):
            return  # moved away: never replaced at recovery (FAA-155)
        if capability in on_hold:
            for entry in held or []:
                entry["step"] = "lapsed"  # taken back by a transfer once the hold is lifted
                self.checkpoint.put(entry)
            self._pause(capability)
        elif held:  # at the generation a replay of its own lost ask just recorded, else com.status's (seam 6)
            mine = (self.checkpoint.slots.get(capability) or {}).get("generation")
            self._replace(capability, held, mine if _is_int(mine, 1) and mine != was else generations.get(capability, 0))
        else:
            self._enroll(capability)

    def _replace(self, capability: str, entries: List[Dict[str, Any]], generation: Any) -> None:
        if not _is_int(generation, 0):
            generation = 0
        args: Dict[str, Any] = {"idempotency": self._idem(self._key("replace")), "capability": capability, "expectedGeneration": generation}
        if entries:
            args["transfer"] = {"requests": [e["request"] for e in entries][:64],
                                "checkpoint": {"summary": "Resumed by the same service after a restart; no effect had begun."}}
        try:
            receipt = self._receipt("com.responder_replace", self._ask(capability, "com.responder_replace", args))
        except BoardError as exc:
            if exc.code == "fenced" and (self.slots.get(capability) or {}).get("state") == "moved":
                return  # an earlier lost ask showed the slot moved: said once as board.slot.moved, no outage
            if exc.code != "held":
                raise
            for entry in entries:
                entry["step"] = "lapsed"  # nothing moved: taken back by a transfer once the hold is lifted
                self.checkpoint.put(entry)
            self._pause(capability)
            return
        self.slots[capability] = {"state": "held", "generation": receipt["slot"]["generation"], "renewed_at": self.now()}
        self._held_at(capability, receipt["slot"]["generation"])
        self._lifted(capability)
        moved = {item["request"]: item for item in receipt.get("transferred") or []}
        for entry in entries:
            item = moved.get(entry["request"])
            if item is None:
                # A board pinned before DEC-0078 hands back no attempt. Never claim it back: it stays held, and the next
                # start (or the operator) decides.
                entry["step"] = "held"
                self.checkpoint.put(entry)
                self._emit("board.request.held", "warning", "An accepted request could not be resumed: this Fabric does not hand "
                           "back a transferred attempt (DEC-0078). It stays held; nothing was done.", notify=True,
                           episode=entry["request"], request=entry["request"], capability=capability)
                continue
            if entry.get("step") == "replying" and not entry.get("replied") and (entry.get("keys") or {}).get("reply") \
                    and not entry.get("probe"):
                # Finding 35: whether the old reply was stored is asked under the old fence, but only from the resume queue,
                # after the new attempt is recorded: a second lost answer then leaves the request queued, never stranded.
                entry["probe"] = {"generation": entry["generation"], "attempt": entry["attempt"], "digest": entry["digest"],
                                  "revision": entry["revision"], "key": entry["keys"]["reply"]}
            entry.update(generation=item["attempt"]["generation"], attempt=item["attempt"]["id"], digest=item["attempt"]["digest"],
                         revision=item["revision"], step="accepted" if entry.get("step") in ("accepting", "held", "lapsed") else entry.get("step"))
            # Finding 35: a fenced key's digest named the old attempt; under the new one it is idempotency_conflict.
            entry["keys"] = {k: v for k, v in (entry.get("keys") or {}).items() if k == "reconcile"}
            self.checkpoint.put(entry)
            if entry["request"] not in self._to_resume:
                self._to_resume.append(entry["request"])
        self._resume_next()

    def _replied_before(self, entry: Dict[str, Any]) -> None:
        """A reply whose answer was lost under the old attempt (finding 35): a stored key answers before the fence is checked
        (project-comms.md, Idempotency), so the old call again, under the old fence kept in `probe`, says whether it was
        stored; a refusal says it was not. A lost answer, or a board that cannot be read now, raises and leaves `probe` for
        the next try: neither says whether the reply was stored."""
        probe = entry["probe"]
        old = dict(entry, **{k: probe[k] for k in ("generation", "attempt", "digest", "revision")})
        try:
            self._receipt("com.reply", self._call("com.reply", dict(self._reply_extra(entry), fence=self._fence(old, probe["key"]))))
        except BoardError as exc:
            if exc.code in ("unreachable", "foreign-user", "session-ended", "authority_changed", "not_authorized", "not_available",
                            "capacity_exceeded"):  # foreign-user: nothing was sent now, so nothing is known (0.79.0 seam)
                raise
        else:
            entry["replied"] = True
        del entry["probe"]
        self.checkpoint.put(entry)

    def _resume_next(self) -> None:
        """Resume a transferred request while nothing runs; each idle tick takes the next (finding 39). A lost answer,
        of its probe (finding 35) or of the `com.complete` that sends a known outcome (FAA-86), puts the request back
        first in line, and the next tick sends the same keys again from the checkpoint. It leaves the queue before it
        resumes, so a handler that settles inside the resume (and reaches `_replace`, which resumes the queue again)
        never runs it twice."""
        while self.current is None and self._to_resume and not self.stopping:
            entry = self.checkpoint.entries.get(self._to_resume[0])
            if entry is not None and self.slots.get(entry["capability"], {}).get("state") == "held":
                entry = json.loads(json.dumps(entry))
                if entry.get("probe"):
                    self._replied_before(entry)
                self._to_resume.pop(0)
                try:
                    self._resume(entry)
                except BaseException:
                    # Back first only while it can still be resumed: once its effect began it waits for reconcile.
                    held = self.checkpoint.entries.get(entry["request"])
                    if held is not None and not held.get("effect") and held.get("step") != "unknown" \
                            and entry["request"] not in self._to_resume:
                        self._to_resume.insert(0, entry["request"])
                    raise
            else:
                self._to_resume.pop(0)

    def _observed(self, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """An observed outcome: the one already known, else what `observe(entry)` reads; None when nothing was observed."""
        outcome = entry.get("outcome") if isinstance(entry.get("outcome"), dict) and entry["outcome"].get("observed") is True else None
        if outcome is None and self.observe is not None:
            try:
                outcome = self.observe(dict(entry))
            except Exception:  # noqa: BLE001 - an observation that failed is no observation
                outcome = None
        ok = isinstance(outcome, dict) and outcome.get("observed") is True and not outcome_problems(dict(outcome, observed=True), True)
        return outcome if ok else None

    def _reconcile(self, entry: Dict[str, Any]) -> None:
        state = self._read_state(entry)
        if state != "outcome_unknown":
            if state in TERMINAL or state in NOT_OURS:
                self.checkpoint.drop(entry["request"])
            elif state == "in_progress" and entry.get("step") != "unknown":
                entry["step"] = "unknown"  # no next holder took the slot yet: a later tick tries again (finding 38)
                self.checkpoint.put(entry)
            return
        outcome = self._observed(entry)
        if outcome is None:
            entry["step"] = "unknown"
            self.checkpoint.put(entry)
            self._emit("board.reconcile.needed", "warning", "A request's outcome is unknown: the work may have happened. It stays "
                       "unknown until this service observes what happened.", notify=True, episode=entry["request"],
                       request=entry["request"], capability=entry["capability"])
            return
        clean = {k: outcome[k] for k in ("state", "summary", "evidence") if k in outcome}
        clean["observed"] = True
        args = {"idempotency": self._idem(entry.get("keys", {}).get("reconcile") or self._key("reconcile")), "request": entry["request"],
                "digest": entry["digest"], "outcome": clean}
        entry.setdefault("keys", {})["reconcile"] = args["idempotency"]["key"]
        entry["step"] = "reconciling"
        self.checkpoint.put(entry)
        self._receipt("com.reconcile", self._call("com.reconcile", args))
        self.checkpoint.drop(entry["request"])
        self._emit("board.request.reconciled", "info", "A request whose outcome was unknown was settled from what this service "
                   "observed.", request=entry["request"], capability=entry["capability"], state=clean["state"])

    def _continue_lapsed(self) -> None:
        """Accepted work whose lease lapsed goes back to this responder by `com.responder_replace` with a transfer."""
        lapsed: Dict[str, List[Dict[str, Any]]] = {}
        for entry in self.checkpoint.entries.values():
            if entry.get("step") == "lapsed" and self.slots.get(entry.get("capability"), {}).get("state") == "held":
                lapsed.setdefault(entry["capability"], []).append(json.loads(json.dumps(entry)))
        for capability, entries in lapsed.items():
            live = [e for e in entries if self._read_state(e) == "accepted"]
            for e in entries:
                if e not in live:
                    self.checkpoint.drop(e["request"])
            if live:
                self._replace(capability, live, self.slots[capability].get("generation", 0))

    def _reconcile_pending(self) -> None:
        """Work whose outcome became unknown while running is reconciled from `observe` every five minutes, or stays so.

        An entry left `reconciling` (its `com.reconcile` failed while the slot's lease held, so the session was kept) is
        taken again too: the retry sends the same `keys.reconcile`, so the board answers it idempotently, and an entry the
        board already settled reads terminal and is dropped (FAA-359)."""
        if self.now() < getattr(self, "_reconcile_at", 0.0):
            return
        self._reconcile_at = self.now() + 300.0
        for entry in list(self.checkpoint.entries.values()):
            if entry.get("step") in ("unknown", "reconciling") and \
                    self.slots.get(entry.get("capability"), {}).get("state") == "held":
                self._reconcile(entry)
