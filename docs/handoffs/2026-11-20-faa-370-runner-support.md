# Handoff: runner support matrix, protocol revision, DeepSeek Harness host (FAA-370), 2026-11-20 to 21

**State: paused by the owner, 2026-11-21 00:30** («все сессии ждут стратегический план», fabric-workspace session
2d03ce15, brief `ceo/inbox/2026-11-21-strategic-plan-fable-brief.md`). The revision and the matrix are recorded as input
for the strategist; nothing is merged, tagged or published. New tasks come through the board.

## Entry point for the strategist

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

- Branch `agent/runner-support-matrix` (PR #357, **draft, do not merge before the plan**): the record above plus code
  held by the pause: `install-host-hooks --host deepseek-harness` (`hosts/deepseek-harness/fabric.mjs`,
  `host_hooks.py` `dsh_layer_edit`, tests `test/test_dsh_host.py` 9 and `test/host-hooks-deepseek-harness.test.mjs` 5),
  the Step 2 runner list, the 0.101.0 version strings and CHANGELOG entry, backlog rows FAA-370 to FAA-373.
- Checks run: `test/validate.py` OK on the final tree; both new test files green, the Node one seen failing with the
  host removed; `claude plugin validate --strict` passed for the plugin and the marketplace. The full `npm test` was still
  running under a load average of about 130 when the pause came; its result is not claimed.
- Machine (made before the pause, reversible): `fabric-mcp` registered for Pi (`~/.pi/agent/mcp.json`) and OpenClaw
  (`~/.openclaw/openclaw.json`); `@deepseek-ai/dsh@0.2.2-rc.5` installed globally; link `/opt/homebrew/bin/dsh-tui -> dsh`
  (FAA-372 removes it once Fabric names `dsh`).
- Board: Fabric request `9985ef20` (thread `efff223b`), contract request `b5162cd8` (thread `c8f5e7eb`, with the logging
  addendum `fe61e08e`), agents base contribution `ae4b8765` (thread `74631a2c`), answer `b5a7e7cb` to `41d6e251`.

## Next, after the plan

1. If the plan keeps it: run the full `npm test` on the branch, mark PR #357 ready, merge, tag `v0.101.0` (the release
   also publishes the unreleased 0.100.0 and 0.100.1), then ask the launcher (passioncode) to pin it so local installs
   update.
2. When Fabric answers `9985ef20` items 1 to 3: run the matrix again (`runner-support.md` → "Run it again").
3. FAA-371 (milestones) and FAA-373 (logging) once the contract's decisions land.
