# Handoff: runner support matrix, protocol revision, DeepSeek Harness host (FAA-370), 2026-11-20 to 21

**State, 2026-11-21 (second run): the pause no longer holds this release.** The owner's pause of 2026-11-21 00:30
(«все сессии ждут стратегический план», fabric-workspace session 2d03ce15) ended for this work with the system design
of the same day: board request `7965c76c` (thread `b1881a9b`, the owner's words relayed verbatim, CEO session
`53895bdc`) names SD-ADP-01, release 0.101.0, as work that runs now, due 2026-11-25. The branch is merged with `main`
and goes in through PR #357; the release is the tag `v0.101.0` on that merge.

## Entry point

[docs/reports/2026-11-20-runner-support/README.md](../reports/2026-11-20-runner-support/README.md): the matrix in one
line each, five findings with owners, and links to
- [protocol-revision.md](../reports/2026-11-20-runner-support/protocol-revision.md): §a load inventory, §b redundant
  load, §c the milestone-only proposal and migration, §d logging at every level (the owner's addendum of 22:35);
- the matrix data `plugins/fabric-agent-adapter/skills/working-with-fabric/references/runner-support.json`
  (`runner-support/1`) and its page `runner-support.md`;
- `raw/`: every real run (command, version, answer, exit code).

Matrix (Fabric 0.3.26, 2026-11-20): fully supported Claude Code, Codex, Hermes, Pi; with a gap Kimi Code (own terminal
sees only `fabric_whoami`), OpenClaw (`fabric_whoami` cut at 16,000 characters), DeepSeek Harness (Fabric starts the
removed `dsh-tui`; tool-list race), Kilo (board not run); 20 not checked.

## What exists where

- PR #357 (`agent/runner-support-matrix` into `main`): `install-host-hooks --host deepseek-harness`
  (`hosts/deepseek-harness/fabric.mjs`, `host_hooks.py` `dsh_layer_edit`, tests `test/test_dsh_host.py` and
  `test/host-hooks-deepseek-harness.test.mjs`), the Step 2 runner list, the matrix, the report, the 0.101.0 version
  strings and CHANGELOG entry.
- Backlog ids. `main` filed FAA-370 to FAA-376 for the system design while this branch held FAA-370 to FAA-373, so at
  the merge `main`'s ids stay and the branch's rows moved: the matrix joined FAA-370 (SD-ADP-01); the milestone half is
  **FAA-377** (was FAA-371), the `dsh-tui` link is **FAA-378** (was FAA-372, and named FAA-372 in board request
  `9985ef20`), logging is **FAA-379** (was FAA-373).
- Checks run on the merged tree: see the PR's description (the full `npm test`, `test/validate.py`, both
  `claude plugin validate --strict`).
- Machine (reversible): `fabric-mcp` registered for Pi (`~/.pi/agent/mcp.json`) and OpenClaw
  (`~/.openclaw/openclaw.json`); `@deepseek-ai/dsh@0.2.2-rc.5` installed globally; link `/opt/homebrew/bin/dsh-tui -> dsh`
  (FAA-378 removes it once Fabric names `dsh`).
- Board: Fabric request `9985ef20` (thread `efff223b`), contract request `b5162cd8` (thread `c8f5e7eb`, with the logging
  addendum `fe61e08e`), agents base contribution `ae4b8765` (thread `74631a2c`, taken as inbox item
  `ib-20261120-9b0a60e07c` for the daily review of 2026-11-21), answer `b5a7e7cb` to `41d6e251`.

## Fabric's answer to `9985ef20` (reply `38fd03ab`, 2026-11-20)

| Item | Fabric task | Promised |
|---|---|---|
| 1. One tool list from the first `tools/list`, typed `not-admitted` before admission | `b22a5192` | release by 2026-11-25 |
| 2. `fabric_whoami` shorter, `project`, `protocol`, `task`, `waiting` first | `513f1013` | same release, by 2026-11-25 |
| 3. DeepSeek Harness: `dsh` in the catalogue, then a main `acp-session` runner | `3d74c9be` | `dsh` by 2026-11-23, runner by 2026-11-25 |
| 4. A worktree under `_worktrees` bound to another project | `d3eba990` | analysis by 2026-11-25 |
| 5 to 7. Milestones, compact MCP surface, the support screen, Pi and OpenClaw | `a038892e` | spec in the thread by 2026-11-27; Pi and OpenClaw stay consoles (ADR-0134) until the matrix shows them green |

Fabric writes the version number into thread `efff223b` when items 1 to 3 ship.

## Released, 2026-11-21 (third run), and paused again

- `v0.101.0` is tagged on `d7a4339e` (the operator's «давай вперёд» in the adapter session `6a78ed83`); `release.yml`
  run 44852845209 succeeded; npm `latest` reads 0.101.0; the published tarball carries `runner-support.json`
  (`runner-support/1`, 28 runners, byte for byte `main`), `runner-support.md` and `hosts/deepseek-harness/fabric.mjs`.
  FAA-370's acceptance holds.
- Board: Fabric told in thread `efff223b` (`cbd19155`); the publication question `effect:219658` (request `d3169811`)
  marked as no longer needed in thread `4eabd112` (`241da7af`); launcher pin requested from passioncode, request
  `4644bcde` (thread `121cf170`, no responder online, deadline 2026-11-28). The operator was told through the
  communicator (eventId `faa-0.101.0-released-2026-11-21`).
- **Paused by the owner, 2026-11-21 ~03:30** (CEO window: every session stands while the reconciler on Fable 5.2,
  fabric-workspace `25879d0f`, orders the owner's instructions of the last hours). Nothing is open on this work.

## Closed, 2026-11-21 (fourth run, no person in it)

- The FAA-370 row in `docs/backlog.md` is closed with its receipt (tag, release run, npm 0.101.0, the matrix file's
  path in the tarball, read back with `npm pack` in this run).
- passioncode answered `4644bcde` (reply `7a13a480`, thread `121cf170`): launcher 0.2.82 pins `v0.101.0`, target
  2026-11-28 (its PC-237); 0.2.81 goes out first with `v0.99.0`. The local install reads 0.96.0 until then.
- The pause: this run did the record only (the row, this file, the state in the pulse thread `6255f2d5`) and started
  no feature work. SD-ADP-01 is named in the system design as work that runs during the pause, and closing its row
  is its last step.
- Fabric has not named its release in thread `efff223b` yet. The Fabric task `3118313c` stays open on a time wait
  until 2026-11-24 08:00 UTC, the morning after Fabric's date for `dsh` in its catalogue.

## Next

1. From 2026-11-24: read thread `efff223b`. When Fabric names the release with `dsh` in its catalogue (promised by
   2026-11-23; the tool list and `fabric_whoami` items by 2026-11-25): run the matrix again (`runner-support.md`,
   "Run it again"), update `runner-support.json`, and do FAA-378 (remove the interim `dsh-tui -> dsh` link and its
   note). If it has not shipped, ask for the new date in that thread and move the wait to it.
2. When the launcher's 0.2.82 is out (target 2026-11-28): update the local install through the launcher and read
   `claude plugin list` back as 0.101.0.
3. FAA-377 (milestones) and FAA-379 (logging) once the contract's DECs land (CT-364 by 2026-12-10, CT-365 by
   2026-12-12, thread `c8f5e7eb`); the contract allows starting from `protocol-revision.md` before them.
4. FAA-375 (the matrix generated from conformance runs) follows FAA-373.
