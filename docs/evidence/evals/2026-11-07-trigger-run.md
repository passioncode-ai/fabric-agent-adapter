# Trigger eval of creating-fabric-agents, 2026-11-07

FAA-262 (0.75.0) added one trigger query for the communication agent template: «Сделай агента, который отвечает
пользователям в чате поддержки и обрабатывает лидов, по шаблону Fabric.» (shouldTrigger true). This records the run
that measured it.

## What ran

```bash
FABRIC_REAL_CLIENT=1 python3 test/evals/run_evals.py --skill creating-fabric-agents \
  --json docs/evidence/evals/2026-11-07-trigger-run/creating-fabric-agents.json
```

- Run on 2026-11-07 at 13:32 Europe/Warsaw on the tree of `0b26fb13` (branch `rel-0.75.0`); exit 0.
- Client: Claude Code 2.1.299, `claude -p --model haiku` (the runner's default), set up as in the
  [2026-10-24 run](2026-10-24-trigger-run.md).
- The four SKILL.md front matter blocks and `test/evals/creating-fabric-agents/triggers.json` are byte for byte the
  same at `0b26fb13` and at the release commit, so the result holds for 0.75.0.
- Cost reported by the client: $0.0130.

## Result

| Skill | Passed | Positives | Negatives | Errors | Threshold 85% |
|---|---|---|---|---|---|
| creating-fabric-agents | 28/31 (90.3%) | 16/17 | 12/14 | 0 | PASS |

The new query routed to `creating-fabric-agents`. The three misses are older queries:

- «Build a multi-agent orchestrator for our product.» (negative) chose `creating-fabric-agents`.
- «Make an agent that posts to LinkedIn every day.» (negative) chose `creating-fabric-agents`.
- «Create a new Fabric agent with a dashboard whose AGENTS.md says pages open only in Fabric Dashboards.» (positive)
  chose `building-fabric-services`.

Every case with its answer is in [creating-fabric-agents.json](2026-11-07-trigger-run/creating-fabric-agents.json).
