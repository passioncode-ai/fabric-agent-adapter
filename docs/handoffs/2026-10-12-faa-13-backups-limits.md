# Handoff — FAA-13: settings backups, every limit, the feed client's header (0.19.0)

**Objective.** Adopt the service-side optional surfaces the pin (`0.1.0`) already carries:
- DEC-0025: `fabric-settings-backup/1` and the feed client rule;
- DEC-0027: `budgets` in the usage report.

**Done.**

- **Both kits:**
  - Settings backups: the canonical form, the checksum, make, write, read, the newest intact backup, a restore
    plan and when a backup is due.
  - Limits: `budgets` in the usage report and its FAC-SEM-031 check.
  - The feed client: `token_header`.
- **Probe:** `check_service.py` sends its token through `token_header`.
- **New reference:** `settings-backups.md`.
- **Updated docs:**
  - `usage.md`;
  - `events-and-notifications.md`;
  - `SKILL.md` step 5;
  - the lifecycle reference's directory table.
- **Eval:** the scenario `settings-backups-and-every-limit` was written first.

**Checks run.**

- `test/test_fabric_service_backups.py` (21) and `test/fabric-service-backups.test.mjs` (12).
  - They run against the contract's positive, negative and semantic fixtures (`test/fixtures/contract/dec-0025-0027/`)
    and its canonical-form vectors.
  - A cross-kit case requires the two kits' backup files to be byte-identical.
- Mutation testing: 79 planted defects, all caught. Three further mutants survived the first pass; their tests were
  tightened (the expected message, a probe where nothing else looks) and they are now caught.
- An independent review found 20 moderate defects and nothing critical; all are fixed with tests (CHANGELOG 0.19.0).
  I found one more myself: the readers required `Z` where the contract allows any RFC 3339 offset.
- Full suites, `test/validate.py` and both strict plugin validations on macOS.
- The Windows CI job runs the new cases.

**Decisions.**

- The kits do not touch a service's database. `restore_plan` takes the current tables' columns, keys, required
  columns and existing keys, and returns what to insert and what was dropped, defaulted or refused. The service
  applies the plan.
- A machine limit with a `period` and no `spentUsd` is counted by the kit, so `budget` and its twin agree.

**Open.** Nothing from FAA-13. FAA-11 (runner routes: probe results, `route-bundle` and `route-event`,
FAC-SEM-028…034) is the next unblocked row.

**Next task.**
1. Re-pin the passioncode launcher to v0.19.0 and update the local install.
2. Then FAA-11.
