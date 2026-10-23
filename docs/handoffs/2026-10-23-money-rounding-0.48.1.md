# 2026-10-23: the twins round money alike (0.48.1)

**Objective.** The next rows after 0.48.0, the operator's request standing («давай доделывай все сам автономно и
выбирай лучшие решения для меня и в итоге заливай все обнови доки и новая версия»): FAA-108 (a test's fixed deadline
under load, test-only, PR [#180](https://github.com/passioncode-ai/fabric-agent-adapter/pull/180)) and FAA-110 (the
usage twins round money two ways).

**Done.** FAA-108: the runner-check logic cases pass a recorded run that asserts the 5000 ms bound it asks for and gives
the process room; the bound stays tested by the slow cases. FAA-110, 0.48.1: the Python kit rounds a cost as
`Math.round(x * 1e6) / 1e6` (`_round_usd`, in `costUsd`, `spentUsd` and the money shown in messages), held to 3014 cases
Node answers; `usage_spend` adds call counts as doubles (a new contract-answered vector). PR
[#181](https://github.com/passioncode-ai/fabric-agent-adapter/pull/181) (`787c352`), tag `v0.48.1`, npm 0.48.1; launcher
0.2.32 ([passioncode#152](https://github.com/passioncode-ai/passioncode/pull/152)), installed here byte-identical to the tag
(155 of 155 files).

**Checks actually run.** Red before the change (Python's old rounding): the rounding test lists values that differ,
starting at 5e-7 (0.0 against Node's 1e-6), and the 2^53 vector answers 27021597764222973 against 27021597764222972;
green after. Full suites: Python 1016 tests OK (28 skipped by environment flags), Node 322 tests 0 fail; `validate.py`
and both `claude plugin validate --strict` exit 0. The hosted suite runs in `release.yml` before the publish.

**Open.** FAA-87 (the operator's `npm login`), FAA-86, FAA-84, FAA-89, FAA-91, FAA-98, FAA-106 and FAA-103 on demand.

**Exact next task.** FAA-87 once the operator has run `npm login`; otherwise FAA-86 (the board responder's checkpoint
entry left at `completing` after a lost `com.complete` answer).
