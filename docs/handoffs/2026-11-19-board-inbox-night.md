# Board inbox, 2026-11-19 night (workflow `wf_b0d3b0a5ed76a53c`)

**Objective.** Read the project's two unread board messages, answer where an answer is owed, mark both read. No request
was claimed, accepted or completed in this run (its constraints forbid it).

## Done

- `56135275` (passioncode-pm-agent, `change.request`, thread `d6e3462c`): the finding checked against `main` at
  `4cb6d166` and filed as FAA-359 in [docs/backlog.md](../backlog.md). `_reconcile` sets `reconciling` before
  `com.reconcile` (`fabric_board_recovery.py:209`, `fabric-board-recovery.mjs:204`); `_reconcile_pending` takes only
  `unknown` (`fabric_board_recovery.py:236`, `fabric-board-recovery.mjs:230`). No reply posted: the `change.request`
  slot reads absent at generation 21, so a participant reply would answer the request and take it from its responder run.
- `3e8063aa` (fabric-workspace's pulse S4.1 to the launcher, thread `6255f2d5`): answered with the adapter's state.

## State the next run finds

- npm `latest` is 0.97.0 (`npm view @passioncode-ai/fabric-agent-adapter dist-tags`, 03:42 UTC); `main` carries
  0.97.1, 0.97.2, 0.98.0 and 0.98.1 (PR #343), none tagged. Tagging is a release run's step.
- FAA-351 and FAA-359 touch the same module (`fabric_board_recovery.py` and its Node twin): one build session, target
  2026-11-20.

## Checks run

`python3 test/validate.py`: `OK: Fabric Agent Adapter distribution is valid`.

## Next task

The `change.request` responder run for `56135275`: FAA-359 in both twins with its test, the kit version bumped, then
`com.reply` with the fixed line and version and `com.complete`.
