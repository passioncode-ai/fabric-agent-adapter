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
| 0.83.0 | wave 5 (the triage of all 64 open rows, `docs/evidence/specs/2026-11-12-wave5-triage.json`): new kit modules `fabric_socket_proof` (FAA-292, 272), `fabric_tailnet_identity` (FAA-324, board request `087f41ef`, reading the agents base's `door-groups/1`), `fabric_ops_digest` (FAA-206), `fabric_a2a_server` (FAA-10), `fabric_interop_rules` (FAA-135); FAA-320 to 323, FAA-321, FAA-250, FAA-66, FAA-260, FAA-296 and parts of 17 more; the Node 18 floor check; the seam reading's three breaks fixed; `AGENTS.md` 1a and 1b; the architect's scan | PR #284, merge `6f18283b`, tag `v0.83.0`; its release run 43350367412 failed one Windows test (`an in-place rewrite is seen`), nothing published |
| 0.83.1 | 0.83.0 shipped; a same-size rewrite of the tailnet groups file within one timestamp tick is seen (racy-clean reread, both twins) | PR #285, merge `254dc076`, tag `v0.83.1`, release run 43355019349 success, npm `latest` 0.83.1; board request `087f41ef` completed (answer `01cf9b04`) |
| 0.84.0 | wave 6: FAA-325 to FAA-328, FAA-192 items 1 and 15 (the operator's decisions of 2026-11-13: the cloud template not named; an SPDX line in every kit module and the dashboard kit, 1.1.9); the blind seam reading's two breaks fixed (the peer owner's install closure keeps `fabric_socket_proof`; zoned and IPv4-mapped loopback never read unchecked), `PEER_OWNER_VERSION` `1.3.1+kit.8` | PR #286, merge `aabab103`, tag `v0.84.0`; its release run 43421488665 failed one Node 18 timing test (`floors`), nothing published |
| 0.84.1 | 0.84.0 shipped; the board mandate's linear-time test compares 256 KiB with 1 MiB and repeats each read until 50 ms of CPU time (Windows' 15.6 ms ticks), both twins | PR #287, merge `ba493e73`, tag `v0.84.1`, release run 43426718391 success, npm `latest` 0.84.1, GitHub release `v0.84.1` |
| 0.85.0 | wave 7, part one: FAA-196 (14), (21), (22) reachable part, (29), (30); FAA-187 (4); FAA-182 and FAA-277 done; FAA-243 and FAA-256 done (the Windows owner check measured) | PR, merge and tag `v0.85.0` on `agent/faa-0.85.0`; the release run in the next cut of this file |

Board: request `2718ece8` completed (0.79.1); request `bfc0e14e` accepted for 0.80.0 (FAA-299 to FAA-301); findings
`f09b651f` and `90f24e15` answered with 0.79.1; the coordinator's threads `478d8876` and `6255f2d5` answered.

Process note: wave 2's builder 2B force-pushed its own branch `agent/faa-w2b-kit`; the operator's rules forbid it.
Recorded for the operator; later builder briefs name the rule.

## Next task

1. Read 0.85.0's release run and npm; a red platform job means the next patch, as for 0.79.1, 0.80.2, 0.83.1 and 0.84.1.
2. Wave 7, part two, row by row: what is left is in each row's status line. The large rows: FAA-190
   (104 items, about 90 open), FAA-200 (57, about 45), FAA-194 (40, about 30), FAA-273 ((5), (8), (10), (11) the
   cache half, (15), (17), (21), (22); `fabric_peer_owner.py` sits at 1000 lines, so (11) needs room made first),
   FAA-192 ((5), (19), (20), (21), (25), (26), (28), (30)), FAA-187 ((3), (10)). Sub-agents of this account hit their
   weekly limit on 2026-11-13 and come back 2026-11-18 22:00 Europe/Warsaw: from then, one triage agent per large row
   and two or three builders, as waves 5 and 6 ran.
3. FAA-87: the operator signs in to npm in the browser (`npm login --auth-type=web`; `npm whoami` answered E401 on
   2026-11-13); then `npm trust github @passioncode-ai/fabric-agent-adapter --file release.yml --repo
   passioncode-ai/fabric-agent-adapter --allow-publish --yes`, drop `NODE_AUTH_TOKEN` from `release.yml` and delete the
   `NPM_TOKEN` secret.
4. The three hosts the operator offered (2026-11-13): a Hermes A2A endpoint (FAA-10's live test), a Windows machine
   with Claude Code (FAA-183), a headless Mac with root for one LaunchDaemon install (FAA-286 (4)); each waits for how
   to reach it.
5. FAA-116 builds the rest of an answering agent: it goes through the agent architect first (the operator's rule of
   2026-11-12), `python3 ~/DATA/fabric-agents-database/tools/audit.py consult "<the need>"`.

## Waits

- Blocked rows and their owners are in the inventory; re-check them at each wave boundary.
- FAA-87: a person types npm's one-time password in the browser; everything after is an agent's.
- The launcher installs adapter 0.62.0 on machines it sets up until its PC-123 repins the set.
- FAA-296's fix is Fabric's CO-563, in the Fabric release after v0.3.19.

## Checks run

On each integration commit: `python3 test/validate.py`, `python3 -m unittest discover -s test`,
`node --test 'test/*.test.mjs'`, both `claude plugin validate --strict`; 0.79.1 and later also under Node 22 with
`--no-network-family-autoselection` (standing in for Node 18). Each fix's new test was seen failing without the fix.
