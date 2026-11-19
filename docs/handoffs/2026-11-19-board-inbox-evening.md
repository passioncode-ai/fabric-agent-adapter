# Board inbox, 2026-11-19 evening (workflow `wf_5b8a9c2eb5fde1b5`)

**Objective.** Read the project's 34 unread board messages, do what is the project's own, answer where owed, mark all
read. No request was claimed, accepted or completed in this run (its constraints forbid it).

## Done

- `12caaa48` (Fabric, the operator's order on limits, thread `445c6a1c`): FAA-364, PR #350, merged as `b3e3e570`. The
  recipe example configs held `ceilingUsd` 1.0 a day and `references/connectors.md` showed 2 USD a day; now 95 a
  month, with `test/test_no_low_default_ceilings.py`. Answered on the thread (`8ab8771a`).
- `0468ed9b` (fabric-workspace's pulse S4.1, thread `6255f2d5`): answered (`2194204e`): `v0.98.4` is npm `latest`, the
  state of FAA-351, FAA-202, FAA-339 and the repin date.
- Read only, nothing owed: the pulse replies and messages to the launcher and Fabric (`3c16b699`, `843fcf03`,
  `f02a8934`, `91f96626`, `dab45dd1`), the other participants' answers on `445c6a1c`, `d2757412`, the PM agent's relay
  notes (`aede98bb`, `114429c4`, `9c3d86e2`, `ec6b4d99`).
- Already completed by earlier runs: `fdb8b224` (FAA-362), `52f7914b` (FAA-360), `e9562845` (FAA-363, 0.98.4).

## Left to their responder runs (`change.request` slot absent at generation 31: no participant reply)

- `23c37a58`: contract DEC-0184 (AO-1, AO-2): an action's `tool` on a compact surface names an operation, never the
  `search` or `execute` door. Deadline 2026-12-03.
- `da5a75a2`: observing-products, channel kinds `agent-session`, `work-queue`, `consumer-repo`, `board-thread` and
  `docs/observer/state.json` (Fabric CO-598). Deadline 2026-12-03.
- `599b59d6`: the agents base's D-84, the knowledge layer and graphs in the creating and adapting skills and a
  knowledge-map panel recipe. Deadline 2026-11-26.
- `3bed4856`: DEC-0183 in `fabric_usage.py` (`editable`, `minUsd`, `maxUsd`, `period: week`, `limitChanges`,
  `months`); already `accepted` by a responder run. Deadline 2026-11-26.

## Checks run

New test and both recipe suites (64 OK), `test_fabric_kit*`, `python3 test/validate.py` OK, both
`claude plugin validate --strict` passed. The full suite was not run: the MacBook had 4 GB free.

## Next task

At the next kit version: the usage examples in the module comments of `fabric_openrouter.py` and
`fabric-openrouter.mjs` (2 USD) move to 95 a month (FAA-364's open part); then the responder runs above.
