# FAA-59: a quieter session start, release 0.38.0 (2026-10-20)

Objective: the operator's audit of 2026-10-20 found the plugin's SessionStart hooks talking in every repository:
the machine's Fabric-service line (which the host's global instructions already carry), a Fabric-down notice in
repositories that never use Fabric (while the `fabric` MCP server says to call `fabric_whoami` first), on every
compact and resume, and a dashboard-kit notice that said "tell the operator" against the operator's standing rule
that agents act and report.

## Done

- `working-with-fabric/scripts/fabric_session.py`: `services_line`, `SERVICES_NOTE` and `LOCAL_ORIGIN` removed.
  `DOWN_NOTICE` is one 217-character line: skip `fabric_whoami` and the board, start Fabric through the lifecycle
  broker only if the task needs it, never launch it. It prints only when `project_uses_fabric(cwd)` names a sign:
  `registration` (`fabric` at local or project scope; user scope is every folder's), a marker file
  (`fabric-agent.json`, `fabric-contract.lock.json`, `fabric.package.json`) from the folder up to its checkout's root,
  or `service` (a descriptor's `source.repository` equals the checkout's `remote.origin.url`; one `git config` call,
  only on the down path). `source: compact|resume` is silent for every host.
- `building-fabric-services/scripts/dashboard_kit.py` `notice_line`: silent unless the repository owns a service;
  names only those services, marked `(this repository)`; ends "You may upgrade it yourself: ...".
- `hooks/hooks.json`: both SessionStart groups use matcher `startup|clear`.
- Docs in the same change: `references/session-hooks.md`, working-with-fabric `SKILL.md` (Step 1 and the hooks
  paragraph), `references/dashboard-kit.md` "Upgrading an existing dashboard", building-fabric-services `SKILL.md`,
  `README.md`, `AGENTS.md` (lifecycle section and table), `SKILL-CARD.md`, `CHANGELOG.md` 0.38.0. Scenario evals:
  `down-notice-skips-whoami` (new), `dashboard-kit-upgrade-notice` (the agent upgrades and reports).

## Decisions

- "Uses Fabric" is a local, cheap test: no Fabric call, no project registry read. Fabric keeps no per-repository
  project marker on disk (checked: its folder holds `enrollments`, `services`, `tokens`; Fabric's source writes no
  `.fabric/` file into a repository), so a board identity cannot be read locally; the three signs above are what a
  Fabric project carries.
- The dashboard matcher follows the session hook (`startup|clear`): a resumed transcript already holds the line.
- A service is "owned" by every checkout of its repository (same origin), so a second checkout of the same remote
  still hears the notice; that is the repository the upgrade would land in.

## Measured (operator's Mac, 26 descriptors, `fabric` at user scope)

| Case | Before (0.37.1) | After (0.38.0) |
|---|---|---|
| Fabric running, any start incl. compact/resume | 1,243 chars | 893 at startup or `/clear`; 0 on compact/resume |
| Fabric down, repository without Fabric (`sshlg-skills`) | 678 | 0 |
| Fabric down, Fabric repository (`asset-foundry`) | 678 | 217 |
| Dashboard notice (`asset-foundry`) | 480 at startup and resume | 401 (installed path) at startup and `/clear` |

## Checks run

- Red first: the new tests failed against 0.37.1 code (11 failures, 5 errors in `test_dashboard_kit` and
  `test_fabric_session`), then passed.
- `python3 -m unittest discover -s test`: 716 tests, OK (22 skipped).
- `node --test 'test/*.test.mjs'`: 244 tests, 236 pass, 0 fail, 8 skipped.
- `python3 test/validate.py`: OK at 0.38.0.
- `claude plugin validate ./plugins/fabric-agent-adapter --strict` and `claude plugin validate . --strict`: passed.
- No U+2014 in any added line (`git diff -U0 origin/main | grep '^+'` piped to the em dash check: 0).

## Open

- FAA-60: with Fabric running the 893-character preamble still reaches every folder under a user-scope registration.

## Release receipts

[PR #141](https://github.com/passioncode-ai/fabric-agent-adapter/pull/141) merged as `15dfe52`, CI on the exact head
`3d8624f` ([validate](https://github.com/passioncode-ai/fabric-agent-adapter/actions/runs/39368510283)); the merge
also carries PR #140 (docs only), and `python3 test/validate.py` plus the two hook suites passed on `15dfe52` before
the tag. Tag `v0.38.0`, [release run](https://github.com/passioncode-ai/fabric-agent-adapter/actions/runs/39368744156)
success, npm `@passioncode-ai/fabric-agent-adapter@0.38.0`. Launcher passioncode 0.2.15
([PR #121](https://github.com/passioncode-ai/passioncode/pull/121), merge `a28fa5b`,
[release run](https://github.com/passioncode-ai/passioncode/actions/runs/39370021607), npm 0.2.15).
`npx --yes @passioncode-ai/passioncode@latest update` installed `fabric-agent-adapter@passioncode` 0.38.0; the cache
is byte-identical to `git archive v0.38.0 plugins/fabric-agent-adapter` (91 files, `diff -r -q` empty), both matchers
read `startup|clear`, and the installed hooks print 893 / 0 (startup / compact) in `sshlg-skills`. Sessions load the
new hooks at their next start.

## Next task

FAA-60: decide whether the running-Fabric preamble follows `project_uses_fabric`.
