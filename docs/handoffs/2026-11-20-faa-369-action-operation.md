# FAA-369: a button behind execute names its operation (contract DEC-0184) (2026-11-20)

- Objective: board request `23c37a58` (thread `28d76702`) from fabric-agent-contract, after the sound-engine Hub's
  `e13bb350`: take contract DEC-0184 (`47df6447`) into the kit and the probe.
- Done (0.100.1): AO-1, `FAC-SEM-142` in `fabric_actions.py` / `fabric-actions.mjs` (`actions_extension_rules`) finds
  an action `tool` equal to a declared `surfaces.mcp.compact.search` or `.execute`, with the contract's text from
  `src/actions.ts`. AO-2, `check_service_rules.action_tools_verdict(..., compact=)` passes an action on a compact
  surface only when its tool is an operation search answered; `check_service.compact_listing_rule` keeps the doors and
  the operations (`None` when search was not read: a door still fails, an operation is `NOT_RUN`). Prose:
  `building-fabric-services/references/interop.md` (Actions, the probe's table; SKILL.md sits at its word cap and
  already points there); scenario eval
  `a-button-behind-two-doors`; FAA-369 in `docs/backlog.md`.
- Decisions: no repin. DEC-0184 changes no schema and records that such a declaration already failed `FAC-SEM-142` at
  the pinned contract (`aeecb12a`, CM-2 keeps the doors out of `capabilities`); only the finding's cause is new, and no
  contract tag contains `47df6447` yet. The contract's vectors stay generated at the pin; the new cases are the adapter's
  own tests, built from the contract's two fixtures of `47df6447`.
- Checks run: `python3 -m unittest discover -s test`, `python3 test/validate.py`, `npm test`, both
  `claude plugin validate --strict` (results in the PR).
- Open: the sound-engine Hub moves its `action_table` to `tool: "hub.pipeline_audit"` (its own repository). The next
  repin brings the contract's vectors for DEC-0184.
- Next task: the next board request addressed to fabric-agent-adapter, or FAA-367.
