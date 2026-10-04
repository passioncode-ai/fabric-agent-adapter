# Handoff — lifecycle contract in the service kit (0.7.0), 2026-10-03

Objective: bring `building-fabric-services` and the installers in line with the organization's
[product lifecycle contract](https://github.com/passioncode-ai/fabric-workspace/blob/main/knowledge/lifecycle.md)
(LC-01…LC-15), closing findings F7, F8, F9, F16 of the 2026-10-03 lifecycle audit
(`fabric-workspace` `docs/reports/2026-10-03-lifecycle-audit/raw/passioncode-adapter.md`).

## What changed (branch `claude/lifecycle-contract`)

| Finding | Rule | Change | Test |
|---|---|---|---|
| F7 | LC-14 | `launchd_install` reads `launchctl print-disabled`; enables only on a first install; a disabled label stays disabled, plist still rewritten; `force_enable` | `test/test_fabric_service_lifecycle.py::LaunchdInstallTests` |
| F8 | LC-03 | supervised copy (`FABRIC_SERVICE_SUPERVISOR=launchd`, written by `launchd_plist`) backs off in-process up to 300 s before exit 75; by hand still exits 75 at once | `SupervisedLockTests`; `test/fabric-service-lifecycle.test.mjs` |
| F9 | LC-14 | `launchd_uninstall` waits for unload, removes plist, resets override, optional `purge` | `LaunchdUninstallTests` |
| F9 | LC-01 | `Drain` (Python + Node): 8 s drain, 2 s grace, hard exit 70; sample service uses it | `DrainTests`, `SampleServiceStopTests`, Node `LC-01 …` tests |
| F9 | LC-12 | `RotatingLog` (5 × 5 MB, 0600/0700), `cap_stdout_log` | `RotationTests`, Node `LC-12 …` tests |
| — | LC-11/15 | `prune_releases` / `pruneReleases` (current + previous) | `PruneReleasesTests`, Node `LC-15 …` tests |
| F16 | LC-14 (one owner per artefact) | `install.sh` and the npm installer skip hub links (launcher links named) even with `--force` | `test_installer.py` (3 new tests) |

Docs: `references/lifecycle.md` (links the contract, LC map, Contents), `SKILL.md` steps 3–4,
`AGENTS.md` `## Lifecycle` (LC-09 footprint, LC-15 retention), CHANGELOG 0.7.0, three scenario evals.

## Decisions

- **Exit 75 is kept.** The pinned contract (`service.md`, "One copy") says a held lock MUST print one
  sentence and exit 75. The supervised back-off delays that exit instead of replacing it, so the pin
  is not contradicted. If the contract should say so explicitly, that is a `fabric-agent-contract`
  decision record, not a change here.
- **Supervision is explicit** (`FABRIC_SERVICE_SUPERVISOR=launchd` in the plist), not inferred from
  `XPC_SERVICE_NAME`, which terminals inside apps also carry. Existing services get it on their next
  `launchd_plist` + `launchd_install`.
- **`ExitTimeOut` default 40 → 15 s**, above `Drain`'s 10 s bound (LC-01).
- launchd install/uninstall stay Python-only (the Node kit never had them).

## Checks run

`npm test` → exit 0 (validate.py OK; 183 Python tests OK, 1 skipped; 38 Node tests pass).
`claude plugin validate ./plugins/fabric-agent-adapter --strict` → passed; `claude plugin validate . --strict` → passed.

## Next task

Coordinator: review and land the PR, then release 0.7.0 (tag `v0.7.0`) and pin it in the
PassionCode launcher. Not done here by instruction (no merge, release or publish).
