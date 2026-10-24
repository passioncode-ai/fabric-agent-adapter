# 2026-10-24: the probe judges a remote session cookie by its name (0.49.2)

**Objective.** The operator's ask «проверь проблемы и долги, реши, закрой баги, сделай релиз»: every open item of this
repository (backlog, GitHub issues, the project board) checked and closed or filed, then a release.

**Done.**
- FAA-115, release 0.49.2 (PR [#194](https://github.com/passioncode-ai/fabric-agent-adapter/pull/194)): a board finding
  from a remote service behind DigitalOcean's Cloudflare edge. `check_service.py` kept one `Set-Cookie` per answer, so
  the edge's `__cf_bm` failed `login.cookie-host-bound` and `login.single-use`. It now keeps every `Set-Cookie`
  (`merge_headers`) and picks the session cookie by name (`session_cookie`, `check_service_rules.py`).
  `references/remote-placement.md` says so and gained its Contents (it passed 100 lines).
- Launcher 0.2.37 pins `v0.49.2` ([passioncode #162](https://github.com/passioncode-ai/passioncode/pull/162)); the local
  install is byte-identical to the tag (155 of 155 files).
- GitHub issues #31 (FAA-12a/12b, released in 0.22.0 and 0.28.0) and #49 (the setup entry, shipped in launcher 0.2.0)
  were done and still open: closed with their receipts.
- The board: 225 unread messages read and marked; the finding answered (thread `ced8ab45`), the ask for guidance for
  agents that answer people filed as FAA-116 and answered (thread `e68f363c`).

**Decisions.** FAA-116 waits for agent-stack's `agent-evals` reference for the learning loop, the mechanism's owner, so
the kit's guidance does not diverge from it; the public backlog names no private repository.

**Checks actually run.** The new `SessionCookieBehindAnEdge` red before the change, green after. Python 1032 tests OK
(28 skipped), Node 324 tests 0 fail, `validate.py` exit 0, both `claude plugin validate --strict` pass; hosted validate
on the branch (run 40094782187) and the release run (40095147259) green. Launcher: hosted `npm test` green (run
40096638324); locally 147 of 148 at a load average near 1000, the one `setup.test.js` failure (`fetch failed` to the
local fake server) passes alone with and without the change.

**Open.** FAA-87 (the operator's npmjs.com sign-in); FAA-98 by decision; FAA-103, FAA-106 on demand; FAA-10, 26 to
29, 44, 63, 116 wait on other owners; FAA-66, FAA-67 are features.

**Exact next task.** FAA-116 once agent-stack's learning-loop reference lands; otherwise FAA-87 after `npm login`.
