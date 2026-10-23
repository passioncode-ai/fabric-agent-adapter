# 2026-10-23: a resumed request settles on the next tick (0.48.2)

**Objective.** The exact next task of [the 0.48.1 handoff](2026-10-23-money-rounding-0.48.1.md), FAA-87 still waiting on
the operator: FAA-86, the board responder's checkpoint entry left at `completing` after a lost `com.complete` answer.
The operator's standing request: «давай доделывай все сам автономно и выбирай лучшие решения для меня и в итоге
заливай все обнови доки и новая версия».

**Done.** 0.48.2: `_resume_next` / `resumeNext` takes a transferred request off the resume queue only after it has
resumed, in both twins. A lost answer of the `com.complete` that sends a known outcome keeps it first in line, and the
next tick sends the same key again from the checkpoint, as finding 35 already did for the replied-before probe.

**Checks actually run.** The new tests (`test_a_lost_complete_answer_on_a_resumed_request_settles_on_the_next_tick`,
the Node `FAA-86` test) red on the old code (the checkpoint held the entry at `completing`), green after; the board
suites green in both twins. Full suites: Python 1017 tests OK (28 skipped by environment flags), Node 323 tests 0 fail;
`validate.py` and both `claude plugin validate --strict` exit 0. `references/board.md` says so. The hosted suite runs in
`release.yml` before the publish.

**Open.** FAA-87 (the operator's `npm login`), FAA-84, FAA-89, FAA-91, FAA-98, FAA-60, FAA-88, FAA-106 and FAA-103 on
demand.

**Exact next task.** FAA-87 once the operator has run `npm login`; otherwise FAA-84 (the support recipe's file names
that read as links).
