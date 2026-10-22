# 2026-10-22: the audit closed as 0.41.0

**Objective.** The operator asked to fix what the 2026-10-22 audit found, understand the causes, fix them as a system,
merge into `main`, clean up leftovers, update the documents and report what was done, what is next and what waits.

**Done.**
- All 53 findings of [the audit](../reports/2026-10-22-adapter-audit/README.md) (rows FAA-68 to FAA-81) fixed, each
  with a test, and six root-cause classes each given a guard ([brief](../evidence/specs/2026-10-22-audit-fixes-brief.md),
  CHANGELOG 0.41.0). Built by eight builders on disjoint files, then a second wave from the certification.
- Three blind certification readings (unit, seam, product) reported 27 findings on the integrated candidate (6 seam, 12 product, 9 unit, some overlapping); the blocking ones and the cheap ones fixed,
  a second round passed with three non-blocking risks, now rows FAA-82 to FAA-84.
- PR [#153](https://github.com/passioncode-ai/fabric-agent-adapter/pull/153) merged into `main` as `5876df8`; tag
  `v0.41.0`; the first release run (39716366275) failed to publish with E401 under the npm 11.21.1 pin this release had
  introduced; PR [#154](https://github.com/passioncode-ai/fabric-agent-adapter/pull/154) pins npm 12.2.0 (the npm that
  published 0.40.0) and run [39717133216](https://github.com/passioncode-ai/fabric-agent-adapter/actions/runs/39717133216)
  published `@passioncode-ai/fabric-agent-adapter@0.41.0` with provenance (`gitHead` `5876df8`, tarball equal to the tag).
- The PassionCode launcher pins the adapter: release 0.2.20 (PR passioncode-ai/passioncode#131, PC-57) moves it to
  `v0.41.0`.
- Clean-up: 32 remote branches deleted (the 18 stale ones named in the brief's run state, the audit and builder
  branches, all merged or byte-equal on `main`); twelve builder worktrees and their local branches removed; only
  `main` remains on the remote besides agent-sync's lease refs.

**Checks actually run.** Local on the merged head's tree: Python 965 tests OK with `FABRIC_CONTRACT_NEW`/`OLD` set to
installed checkouts of the pin and the legacy revision; `/usr/bin/python3` 3.9.6, 965 OK; Node 302 tests, 0 fail;
`python3 test/validate.py` and both `claude plugin validate --strict` exit 0. Hosted
[run 39714793032](https://github.com/passioncode-ai/fabric-agent-adapter/actions/runs/39714793032): python, floors,
macos, windows, contract and claude-plugin all success.

**Decisions.** D1 to D9 in the brief, all resolved from the sources. Two more taken during integration: a 0.40.0 job key
answers with its job (never a conflict) and runs again only for the intent its job stored; the new CHANGELOG heading
uses `## 0.41.0 (2026-10-22)` so it carries no spaced hyphen, older headings unchanged.

**Open.** FAA-82 to FAA-92 (backlog), FAA-87 needs the operator's npmjs.com sign-in. The earlier open rows (FAA-10,
FAA-26 to FAA-29, FAA-44, FAA-60, FAA-62 to FAA-67) are untouched.

**Exact next task.** FAA-82 (make the kit history guard run in CI), then FAA-83 (a stale end entry during a resumed
session), both small and in files this release already touched.
