# Trigger eval of working-with-fabric, 2026-11-12

FAA-130: since 0.50.0 the working-with-fabric description names relaying the operator's decision and no longer says
'from a terminal' or '(not other apps)', and the negative case 'Restart the example-agent app through the lifecycle
broker.' leaned on that boundary. The latest recorded run of this skill was [2026-10-24](2026-10-24-trigger-run.md),
before that change. This records the run after it.

## What ran

```bash
FABRIC_REAL_CLIENT=1 python3 test/evals/run_evals.py --skill working-with-fabric \
  --json docs/evidence/evals/2026-11-12-trigger-run/working-with-fabric.json
```

- Run on 2026-11-12 at 08:40 Europe/Warsaw on the tree of `b3b03737` (branch `agent/faa-w2c-misc`, two commits on
  `v0.79.0` that touch neither a SKILL.md nor a triggers file); exit 0.
- Client: Claude Code 2.1.299, `claude -p --model haiku` (the runner's default), set up as in the
  [2026-10-24 run](2026-10-24-trigger-run.md).
- The five SKILL.md front matter blocks and `test/evals/working-with-fabric/triggers.json` are those of `v0.79.0`.
- Cost reported by the client: $0.0122.

## Result

| Skill | Passed | Positives | Negatives | Errors | Threshold 85% |
|---|---|---|---|---|---|
| working-with-fabric | 38/44 (86.4%) | 24/27 | 14/17 | 0 | PASS |

The case FAA-130 names passed: 'Restart the example-agent app through the lifecycle broker.' (negative) routed to
`none`, where on 2026-10-24 it routed to `working-with-fabric`.

The six misses:

| Should trigger | Query | Routed to | On 2026-10-24 |
|---|---|---|---|
| yes | My subagent hit its usage limit and says it resets at 9pm. Should I wait for the reset? | none | passed |
| yes | Воркфлоу упёрся в лимит сессии, ждать сброса? | none | passed |
| yes | The operator already approved this in my lead agent's chat and it relayed his words with the date and scope. Do I need to ask him again? | none | a case added since |
| no | Fix the enrollment bug in Fabric's sessionEnroll.ts. | working-with-fabric | passed |
| no | Take a lease on CHANGELOG.md with agent-sync before editing it. | working-with-fabric | passed |
| no | Implement com.reply in Fabric's boardService.ts. | working-with-fabric | passed |

The pass rate fell from 97.4% (38/39) to 86.4% (38/44), just above the threshold: five cases were added since, four of
them pass, and five older cases flipped (four to a miss, the lifecycle broker one to a pass). The cause is the
description's own cut: FAA-291 (`b82e1d2f`, 0.78.0) shortened every description to about 350 characters for the
listing budget, and working-with-fabric's lost the lifecycle broker, 'hit your limit, resets at', the relay of the
operator's decision (only 'the operator's decisions' stays), and 'changing Fabric's own code' among its exclusions. The lifecycle broker case passes because
the broker is no longer named; the usage-limit and relayed-approval requests miss because their words are gone; and
the small model now takes requests about Fabric's own code, and an agent-sync lease, on the nouns Fabric and lease.
The skill stays above the threshold, so the description is not changed in this run (it is FAA-291's budget); a
further drop would fail the gate. The board row for it: name 'changing Fabric's own code' and the usage limit back in
the description within the budget, or move the cases the budget gave up, and run again (with `--model sonnet` too).

Every case with its answer is in [working-with-fabric.json](2026-11-12-trigger-run/working-with-fabric.json).
