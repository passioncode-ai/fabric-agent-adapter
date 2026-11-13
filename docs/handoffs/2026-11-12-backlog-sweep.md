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

| 0.80.0, 0.80.1 | wave 2 and wave 3's first builders (session scripts, kit and docs, the three operator rules, FAA-307, 2B's kit rows, FAA-289, the docs rows) | PRs #279 and #280, tags `v0.80.0` and `v0.80.1`; each run failed a platform test (macOS-only paths, Windows separators), nothing published |
| 0.80.2 | 0.80.0 shipped, its two cross-platform test fixes in | PR #281, merge `b8d2355a`, tag `v0.80.2`, npm `latest` 0.80.2 |
| 0.81.0 | wave 3: the repin to contract `v0.1.0+2026-11-08.1` (FAA-258, DEC-0151 `SECRET_VALUE`), the `fabric-source/1` tree and `new` (FAA-261, FAA-270, G21), `fabric_holds` and `limits.holds` (FAA-265), FAA-298, FAA-227, FAA-251, parts of FAA-260 and FAA-286, the seam reading's five fixes; new rows FAA-311 to FAA-319 | PR #282, merge `5511f98b`, tag `v0.81.0`, release run 43284542201 success, npm `latest` 0.81.0, GitHub release `v0.81.0` |
| 0.82.0 | wave 4: FAA-311 (SA-6), FAA-312, 313, 315, 318, FAA-304, 306, 309, 314, 316, 317, FAA-303, FAA-308, FAA-292's decision, and the seven findings of its blind seam reading; rows FAA-320 to FAA-323 | PR #283, merge `4a3c5659`, tag `v0.82.0`, release run 43302458275 success, npm `latest` 0.82.0 |
| 0.83.0 | wave 5 (the triage of all 64 open rows, `docs/evidence/specs/2026-11-12-wave5-triage.json`): new kit modules `fabric_socket_proof` (FAA-292, 272), `fabric_tailnet_identity` (FAA-324, board request `087f41ef`, reading the agents base's `door-groups/1`), `fabric_ops_digest` (FAA-206), `fabric_a2a_server` (FAA-10), `fabric_interop_rules` (FAA-135); FAA-320 to 323, FAA-321, FAA-250, FAA-66, FAA-260, FAA-296 and parts of 17 more; the Node 18 floor check; the seam reading's three breaks fixed; `AGENTS.md` 1a and 1b; the architect's scan | branch `agent/faa-0.83.0`, validate run 43347117033 green on `c6f0aaee`; PR, merge and tag follow |

Board: request `2718ece8` completed (0.79.1); request `bfc0e14e` accepted for 0.80.0 (FAA-299 to FAA-301); findings
`f09b651f` and `90f24e15` answered with 0.79.1; the coordinator's threads `478d8876` and `6255f2d5` answered.

Process note: wave 2's builder 2B force-pushed its own branch `agent/faa-w2b-kit`; the operator's rules forbid it.
Recorded for the operator; later builder briefs name the rule.

## Next task

1. 0.83.0: PR from `agent/faa-0.83.0`, merge, tag `v0.83.0`, watch the release run, confirm npm; answer board request
   `087f41ef` with the version and complete it (take a fresh attempt with `com.responder_replace` first: leases last
   about 60 s); reply on the North Star thread `16093ded` with item 1b's sections and the architect's verdict; remove
   the wave 5 worktrees and branches; release the agent-sync leases (`CHANGELOG.md`, `docs/backlog.md`).
2. The operator's decisions of 2026-11-13 (this session): FAA-192 (1) the public skill does not name the private cloud
   template, only where an agent reads it; FAA-192 (15) the kit files `fabric_kit.py install` copies keep an SPDX
   line each; FAA-87 the operator signs in to npm (`npm login --auth-type=web`) so `npm trust github` can register
   `release.yml`, then drop `NODE_AUTH_TOKEN` and the `NPM_TOKEN` secret.
3. The operator offers the three hosts the open items wait for: a Hermes A2A endpoint (FAA-10's live test), a Windows
   machine with Claude Code (FAA-183), a headless Mac for one root LaunchDaemon install (FAA-286 (4)); ask how to reach
   each, then run them.
4. Wave 6: FAA-325 to FAA-328 and the doable parts left in the wave 5 triage's partial rows.

## Waits

- Blocked rows and their owners are in the inventory; re-check them at each wave boundary.
- FAA-87: a person types npm's one-time password in the browser; everything after is an agent's.
- The launcher installs adapter 0.62.0 on machines it sets up until its PC-123 repins the set.
- FAA-296's fix is Fabric's CO-563, in the Fabric release after v0.3.19.

## Checks run

On each integration commit: `python3 test/validate.py`, `python3 -m unittest discover -s test`,
`node --test 'test/*.test.mjs'`, both `claude plugin validate --strict`; 0.79.1 and later also under Node 22 with
`--no-network-family-autoselection` (standing in for Node 18). Each fix's new test was seen failing without the fix.
