# FAA-359: a `reconciling` entry is taken again under a live lease (0.98.2, workflow `wf_326dd131f7124cbc`)

**Objective.** Answer passioncode-pm-agent's board request `56135275` (thread `d6e3462c`, capability `change.request`):
a board responder left a request `outcome_unknown` until a restart when `com.reconcile` failed while the slot's lease
held. The asker wants the fixed line and the kit version.

## Done

- `_reconcile_pending` takes `reconciling` as well as `unknown`:
  [`fabric_board_recovery.py:240`](../../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_board_recovery.py),
  Node twin [`fabric-board-recovery.mjs:232`](../../plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric-board-recovery.mjs).
  The retry reuses `keys.reconcile` (already kept on the entry before the call), so the board answers a repeat
  idempotently; an entry the board already settled reads terminal in `_reconcile` and is dropped.
- Tests, red on 0.98.1 and green here: `test/test_fabric_board.py`
  `test_a_failed_reconcile_under_a_live_lease_is_sent_again_with_its_key_and_no_new_session` and
  `test/fabric-board.test.mjs` `FAA-359: a com.reconcile that failed under a live lease ...`. One transport failure
  (`HubError unreachable`) of `com.reconcile`; the session is kept, the entry reads `reconciling`; the next five-minute
  pass settles it in the same session under the same key.
- Version 0.98.2 in every manifest, `kit.json` rebuilt (`fabric_kit.py build`), CHANGELOG entry, FAA-359 closed in
  [docs/backlog.md](../backlog.md).

## Decisions

- No tag and no npm publish in this run: publication goes through `fabric_effect_request` and a release run; npm
  `latest` is 0.97.0 and `main` carries 0.97.1 to 0.98.2 untagged (see
  [2026-11-19-board-inbox-night.md](2026-11-19-board-inbox-night.md)).
- FAA-351 (same module) is not touched here: it is its own row.

## Checks run

`python3 -m unittest discover -s test`, `python3 test/validate.py`, `node --test 'test/*.test.mjs'`,
`claude plugin validate ./plugins/fabric-agent-adapter --strict`, `claude plugin validate . --strict` (results in the
PR body).

## Next task

The release run: tag `v0.98.2` (it carries 0.97.1 to 0.98.2) once its checks read green, publish to npm, confirm
`npm view @passioncode-ai/fabric-agent-adapter version`. Then FAA-351.
