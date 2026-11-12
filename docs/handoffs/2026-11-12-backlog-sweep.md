# Backlog sweep handoff (2026-11-12)

Objective: the operator's request of 2026-11-12, «давай разбираем все задачи, аудит проводим и волнами все закрываем
до самого конца полностью», run as `/task-pipeline waves` over `docs/backlog.md`. Fabric task `395ed51a`. Plan and the
inventory of all 134 open rows: [the plan](../evidence/specs/2026-11-12-backlog-waves-plan.md),
[the inventory](../evidence/specs/2026-11-12-backlog-waves-inventory.json).

## Done

| Release | What | Receipt |
|---|---|---|
| 0.78.0 | the two 0.78.0 lines joined (`rel-0.78.0` with FAA-278, `main` with FAA-290, FAA-291, FAA-297) | PR #276, merge `8d5bf23d`, tag `v0.78.0`, release run 43150500652 success, npm 0.78.0 |
| 0.79.0 | wave 1 (37 rows): the register sweep, working-with-fabric against Fabric v0.3.19, the catalogue line, kit fixes, FAA-293, dashboard kit 1.1.6 | PR #277, merge `97ca5b5e`, tag `v0.79.0`; its release run 43176165810 failed `floors` and `windows`, nothing published |
| 0.79.1 | 0.79.0 plus the fixes its run and the blind seam reading found (Node 18 `localhost`, Windows dispatch tests and the open descriptor, `foreign-user` dropping a lost call's record, the default loopback port) | PR #278, merge `3b6519bc`, tag `v0.79.1`, npm `latest` 0.79.1, GitHub release `v0.79.1`; the run reads red only for the registry poll (FAA-307) |

Board: request `2718ece8` completed (0.79.1); request `bfc0e14e` accepted for 0.80.0 (FAA-299 to FAA-301); findings
`f09b651f` and `90f24e15` answered with 0.79.1; the coordinator's threads `478d8876` and `6255f2d5` answered.

## In flight (branch `agent/faa-0.80.0`)

Wave 2 merged there: 2A (session scripts), 2C (kit and docs), 2D (the three operator rules), FAA-307. Waiting for 2B
(`agent/faa-w2b-kit`: FAA-98, 149, 150, 186, 189, 250, 253, 272, 273, 279) and wave 3's first builders
(`agent/faa-w3a-load`: FAA-289; `agent/faa-w3b-docs`: FAA-268, 280, 284, 238).

## Next task

1. Merge `agent/faa-w2b-kit`, `agent/faa-w3a-load` and `agent/faa-w3b-docs` into `agent/faa-0.80.0`; rebuild
   `kit.json`; the CHANGELOG and the register for them; the three suites and both plugin validations; one blind seam
   reading; PR, merge, tag `v0.80.0`; answer `bfc0e14e` with the version.
2. Wave 3 proper: the repin (FAA-258) to the newest contract tag, then FAA-261 and FAA-270 (G21), FAA-265, FAA-292,
   FAA-227, FAA-251, FAA-256, FAA-260, FAA-286, FAA-287, FAA-298.
3. Wave 4: the recipes and the follow-up rows (FAA-10, 66, 116, 126, 153, 182, 187, 190, 192, 194, 196, 200, 206, 243,
   264), each triaged against `main` first.

## Waits

- Blocked rows and their owners are in the inventory; re-check them at each wave boundary.
- FAA-87: a person types npm's one-time password in the browser; everything after is an agent's.
- The launcher installs adapter 0.62.0 on machines it sets up until its PC-123 repins the set.
- FAA-296's fix is Fabric's CO-563, in the Fabric release after v0.3.19.

## Checks run

On each integration commit: `python3 test/validate.py`, `python3 -m unittest discover -s test`,
`node --test 'test/*.test.mjs'`, both `claude plugin validate --strict`; 0.79.1 also under Node 22 with
`--no-network-family-autoselection` (standing in for Node 18). Each fix's new test was seen failing without the fix.
