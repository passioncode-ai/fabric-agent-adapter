# Handoff: runner support matrix, DeepSeek Harness host, protocol revision (FAA-370), 2026-11-20

- Objective: the owner's brief of 2026-11-20 (CEO window session 53895bdc), package 2 and the protocol part of package 1,
  plus the logging addendum of 22:35 (item 1 of `ceo/inbox/2026-11-20-logging-passioncode-analytics-brain-levels-brief.md`).
- Done (0.101.0): `install-host-hooks --host deepseek-harness` (`hosts/deepseek-harness/fabric.mjs`, `host_hooks.py`
  `dsh_layer_edit`); the matrix `working-with-fabric/references/runner-support.json` (`runner-support/1`) and
  `runner-support.md`; Step 2 of the skill names Fabric 0.3.26's 28 runners; report
  [docs/reports/2026-11-20-runner-support/](../reports/2026-11-20-runner-support/README.md) with the protocol revision
  (§a to §c load and milestones, §d logging) and raw real runs.
- Checks run: `npm test` (validate, Python suite, Node suite); `claude plugin validate --strict` on the plugin and the
  marketplace; `test_dsh_host.py` 9 tests and `host-hooks-deepseek-harness.test.mjs` 5 tests, the Node one seen failing
  with the host removed from `context.mjs`; real runs of 8 runners (raw files).
- Machine state changed: `fabric-mcp` registered for Pi (`~/.pi/agent/mcp.json`) and OpenClaw (`~/.openclaw/openclaw.json`);
  `@deepseek-ai/dsh@0.2.2-rc.5` installed globally; interim link `/opt/homebrew/bin/dsh-tui -> dsh` (FAA-372 removes it).
- Board: Fabric request `9985ef20` (thread `efff223b`: stable tool list, short whoami, `dsh`, worktree project, milestones,
  the matrix screen); contract request `b5162cd8` (thread `c8f5e7eb`: `work-milestone/1`, catalogue, compact surface,
  `protocol-log/1`); agents base contribution `ae4b8765` (thread `74631a2c`); answer to `41d6e251` (contract package).
- Open: FAA-371 (adapter on milestones, waits on the contract and Fabric), FAA-372 (the `dsh-tui` link, waits on
  Fabric), FAA-373 (logging, the adapter's half, waits on the contract's fields).
- Next task: when Fabric answers `9985ef20` items 1 to 3, run the matrix again with the prompt in
  `runner-support.md` → "Run it again" and update `runner-support.json`; then FAA-371 once the contract's DEC lands.
