# FAA-135 (board part): the board responder reads the operator's mandate

Status: implemented 2026-11-03 (both kits; tests `test/test_fabric_board_mandate.py`, `test/fabric-board-mandate.test.mjs`). Release: 0.61.0, stacked on 0.60.0. The job step shipped in 0.52.0; the `identify_agent`
hook is the second part of this row and gets its own spec.

## What the contract says (pin 3830a33)

- `docs/specification/project-comms.md` (lines 133 to 144 at the pin): a request one of the operator's own projects
  sends for a task MAY carry `mandate/1` as a JSON code block in its body. The target places the sender as T1 only when
  the board verified it (`provenance: trusted`) and the sending Project is the operator's own (a Project of his
  personal board, never a member's Project on an organization's board, T2). The block carries no `source` (a Project
  declares no `protocols`, OA-7).
- `docs/DECISIONS.md` DEC-0125 MD-3: the callee takes the mandate only from T0 or T1 and only when the chain ends in
  itself; with an authenticated caller agent id, only when that id is the agent before it; without one the chain's
  end alone binds it. `mandateCovers` is the reference; the kit's twin is `fabric_mandate.mandate_covers`.

## Decision

The kit cannot tell a personal board from an organization's: `com.status` names neither (read 2026-11-03:
`{"board": {"state": "ready"}, ...}`). So reading is opt-in and fail-closed:

- `Responder(..., agent_id=, mandate_from=)`. `mandate_from` is a collection of sender Project ids the service's
  operator declares as his own, or the string `"personal-board"` when the service is installed on his personal board.
  Default `None`: no mandate is read (today's behaviour). Both kits.
- A request is read for a mandate only when its sender's principal has `provenance: trusted` and its Project is
  within `mandate_from`, and `agent_id` is set. Exactly one fenced `json` block whose value has `kind: "mandate/1"`;
  two such blocks, or one that does not parse, read as no mandate and are named in the event log by code, never by
  content.
- The handler gets `ctx.mandate` (the mandate block with any `source` dropped, OA-7, or `None`) and `ctx.mandate_covers(call)`, which calls
  `mandate_covers` with `tier: "T1"`, `self: agent_id`, no `callerAgent` (the board names a Project's principal, not an
  authenticated agent id the chain can bind), and the service's clock. A covered call answers `recordAs`
  (`via: mandate`), which the handler records as its reason; the kit puts the operator's words in no event, log or
  checkpoint.
- Nothing else changes: `admit` still runs first, and a body stays data. A mandate never widens what `admit` refuses.

## Checks (to write before the code)

- A trusted request from a declared Project with one valid block: `ctx.mandate` is the block, `mandate_covers` answers
  `ok` for a covered capability and `outside-mandate: capability` for another.
- The same request untrusted, from an undeclared Project, with `mandate_from=None`, or without `agent_id`: no mandate.
- Two blocks, a block that is not JSON, a `mandate/1` whose chain does not end in `agent_id`: no mandate or
  `mandate-not-for-this-call`, never a crash.
- The operator's words never reach the event log or the checkpoint.
- Node twins for each.
