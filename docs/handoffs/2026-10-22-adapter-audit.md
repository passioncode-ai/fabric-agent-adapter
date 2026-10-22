# 2026-10-22: whole-adapter audit

**Objective.** The operator asked to go through everything in the adapter and find its weak spots.

**Done.** A read-only audit of `main` at `f0736a6` (0.40.0, equal to npm `latest`): the project-audit collector,
four independent reviewers (kit, session hooks and installers, the adapting and creating skills, delivery), and the
auditor's own re-runs of the strongest reproductions. Result: [the report](../reports/2026-10-22-adapter-audit/README.md)
and nine proposed rows, FAA-68 to FAA-76, in [the backlog](../backlog.md). No product code changed.

**Checks actually run.**
- `npm test`: `Ran 785 tests ... OK (skipped=22)`; Node `tests 263, pass 255, fail 0`; `validate.py` OK.
- `/usr/bin/python3` (3.9.6) on `test_fabric_http.py`: `FAILED (failures=2)` (FAA-70).
- The full Python suite with `FABRIC_CONTRACT_NEW`/`OLD` set to installed checkouts of `c55f2d5` and `2ce3922`:
  `FAILED (failures=1, skipped=16)`, the failure being `test_the_contract_fixtures_agree` (FAA-72).
- Re-runs in the session scratch directory: the poisoned spool (`FAIL=1`, both workers fail, release never called),
  the `JobStore` races (`jobs created for one key: 2`), the trailing-newline divergence, and the provider writer
  accepting port 80 and a non-URI repository.

**Decisions.** Findings are grouped by owning area into nine rows rather than one row per finding, so each row is one
deliverable with one test surface. Severity is the auditor's; the rows stay `open ... proposed by the audit` until the
operator orders them.

**Second round (same day).** The operator repeated the request; `main` was unchanged, so the second round took
what the first did not reach: the crypto-bearing modules, the estate, share, ceremony and board responder modules,
the dashboard front end, the installers and the recipes. Five more rows, FAA-77 to FAA-81, and a second section in
the report. The auditor re-ran the board reproduction on the repository's fake hub (`R2 after 20 min: board
in_progress cp in-progress reconciles 0`, `R3 board: accepted cp: replying`) and re-read the package walk, the
installer and the layout probe. Board read: the one request addressed here (DEC-0087) is closed by FAA-56, the two
findings by FAA-48 and FAA-53.

**Open.** All fourteen rows. FAA-66, FAA-67 and the earlier open rows are untouched.

**Exact next task.** By severity: FAA-77 items 35-36 (the responder leaves board requests stuck), then FAA-68 item 1 then 2: make `deliver` drop a refused or unreadable spool entry with its error
code (a test with a stub answering `-32602` that proves the `end` entry and `fabric_work_release` still go out), and
kill the whole process group in `McpStdio.close` (a test with a wrapper script around a stub that ignores stdin's
end). Then FAA-70 item 10 (Python `launchd_plist` parity with Node) and FAA-72 (nightly trigger and the pinned
contract job), which together close the three high-severity gaps that can leak a secret or hide a regression.
