# Closing the backlog in waves (2026-11-12)

The operator's request of 2026-11-12, in this repository's session: «давай разбираем все задачи, аудит
проводим и волнами все закрываем до самого конца полностью». Run as `/task-pipeline waves`. Fabric task
`395ed51a`. The coordinator's relay of 2026-11-11 (board thread `478d8876`, message `20028c69`) asked the
same for this repository: wave 0 the 0.78.0 release, wave 1 the help to the agents database's review.

## Survey

Every open row of `docs/backlog.md` on `origin/main` (`8d5bf23d`) and the rows that were only on
`origin/rel-0.78.0` (FAA-279 to FAA-289): 134 rows. Five read-only auditors checked each against the code,
the tests, the CHANGELOG, git history and the owning repositories of each condition. The result, one item
per row with its class, wave and receipt, is
[2026-11-12-backlog-waves-inventory.json](2026-11-12-backlog-waves-inventory.json).

| Class | Rows |
|---|---|
| doable now, in this repository | 67 |
| partial-done (a named part remains) | 30 |
| blocked-external (an owner and a condition) | 27 |
| done but still open in the register | 7 |
| obsolete | 2 |
| needs-operator | 1 |

Findings that change several rows:

- Two lines both called 0.78.0 (`rel-0.78.0` with FAA-278, and `main` with FAA-290, FAA-291, FAA-297).
  Merged as PR #276 (`8d5bf23d`) and tagged `v0.78.0`.
- The contract pin `18f8d487` is `v0.1.0+2026-11-07.1`; `.2` (DEC-0149), `.3` (CT-254), `.4`, `.5` and
  `v0.1.0+2026-11-08.1` exist. The repin (FAA-258) unblocks FAA-261 and FAA-270.
- Six contract decisions the blocked rows wait on (DEC-0156 to DEC-0161) sit on contract branches with no
  PR (contract CT-287). That, not the operator's lifted pause, holds FAA-204, FAA-225, FAA-230, FAA-288 and
  parts of FAA-202 and FAA-228.
- Fabric released up to v0.3.19; CO-479 is in v0.3.16, CO-506 in v0.3.17. CO-563 (a headless dispatched
  session saw only `fabric_whoami`, FAA-296) is on Fabric's `main` `780022af`, unreleased.

## Waves

Each wave names its exit before it starts: `python3 test/validate.py`, `python3 -m unittest discover -s test`
and `node --test 'test/*.test.mjs'` exit 0 on the integrated commit; both `claude plugin validate --strict`
pass; every closed row carries its receipt in `docs/backlog.md`; the CHANGELOG names the change.

| Wave | Seam | Rows | Exit beyond the common one |
|---|---|---|---|
| 0 | one 0.78.0 | FAA-278, FAA-263, FAA-228 (and FAA-290, FAA-291, FAA-297 already on `main`) | tag `v0.78.0`, release run green, npm `0.78.0` |
| 1 | register and texts | the register: FAA-133, 198, 199, 219, 224, 167 closed; FAA-67, 145 cancelled; FAA-188 into FAA-261; FAA-261, 270, 87 restated. working-with-fabric texts: FAA-154, 215, 216, 220, 221, 222, 236, 246, 248, 274, 295, 296. creating and adapting texts: the board request `2718ece8` (a neutral line on a private template catalogue), FAA-129, 180, 281, 282, 283. kit small fixes: FAA-127, 208, 209, 214, 223, 242, 244, 245, 252, 254, 255, 257, 259, and the dashboard kit's ResizeObserver loop (board finding `f09b651f`) | the board request answered with the release that carries the line |
| 2 | kit correctness, medium | FAA-98, 130, 137, 143, 149, 150, 152, 161, 184, 186, 189, 201, 210, 212, 217, 218, 225 (port part), 230 (recipe part), 232, 233, 234, 235, 239, 240, 250, 253, 272, 273, 277, 279, 293, 294 (item 4) | each twin change has a test in both twins |
| 3 | repin and agent creation | FAA-258 (repin to the newest contract tag), then FAA-261, 270, 265, 289, 292, 227, 268, 280, 284, 238, 135, 251, 256, 260, 286, 287, 298 | `fabric-contract.lock.json` at the new tag; the vendored vectors regenerated |
| 4 | recipes and follow-up rows | FAA-10, 66, 116, 126, 153, 182, 187, 190, 192, 194, 196, 200, 206, 243, 264 | each follow-up row triaged item by item against `main` first |

Blocked, re-checked at every wave boundary (owner and condition in the inventory): FAA-26, 27, 28, 29, 44,
63, 64 (its second question), 103, 106, 124, 144, 146, 147, 148, 179, 181, 183, 185, 202, 204, 249, 269,
271, 285, 288. Needs the operator: FAA-87 (one npm one-time password in the browser; the rest is an
agent's).

## Decisions

| Id | Decision | Why |
|---|---|---|
| W-1 | FAA-67 is cancelled, not built | the operator's rule of 2026-11-04 routes every Telegram send through the organization's gateway service; a kit connector is a second client |
| W-2 | The architect line names no private catalogue | the asking base's own rule; this repository and its npm package are public |
| W-3 | A wave integrates to `main` without a tag; a release follows a wave that ships behaviour | `references/waves.md` of task-pipeline; releases without outside users are the agent's under the operator's delegation |
| W-4 | Builders of one wave work on disjoint files; the register, the CHANGELOG and the versions are the coordinator's | two writers on one register are the conflict the lease exists for |
