# Trigger evals of creating-fabric-agents and building-fabric-services, 2026-11-15

FAA-192 (5): 0.59.0's readings asked for a real-client run of the trigger evals, since the Russian trigger of
creating-fabric-agents («новый агент под Fabric») might also draw building-fabric-services. The last recorded runs of
both skills were [2026-10-24](2026-10-24-trigger-run.md). This records the run on the 0.90.2 tree.

## What ran

```bash
FABRIC_REAL_CLIENT=1 python3 test/evals/run_evals.py --skill creating-fabric-agents \
  --json docs/evidence/evals/2026-11-15-trigger-run/creating-fabric-agents.json
FABRIC_REAL_CLIENT=1 python3 test/evals/run_evals.py --skill building-fabric-services \
  --json docs/evidence/evals/2026-11-15-trigger-run/building-fabric-services.json
FABRIC_REAL_CLIENT=1 python3 test/evals/run_evals.py --skill building-fabric-services --model sonnet \
  --json docs/evidence/evals/2026-11-15-trigger-run/building-fabric-services-sonnet.json
```

Run on 2026-11-15 on branch `agent/faa-192-prose-evals` from `main` at 0.90.2 (no SKILL.md front matter changed on the
branch); the client is Claude Code 2.1.299, `claude -p` with the runner's default model (haiku) unless named. Costs reported by the client:
USD 0.0092, 0.0145 and 0.3060.

## Result

| Skill | Model | Passed | Positives | Negatives | Threshold 85% |
|---|---|---|---|---|---|
| creating-fabric-agents | haiku | 30/33 (90.9 %) | 19/19 | 11/14 | PASS |
| building-fabric-services | haiku | 40/50 (80.0 %) | 22/31 | 18/19 | below |
| building-fabric-services | sonnet | 43/50 (86.0 %) | 24/31 | 19/19 | PASS |

The case FAA-192 (5) asked about passed: every positive of creating-fabric-agents, the Russian one included, routed to
it, and no positive of creating went to building-fabric-services. Its three misses are negatives that routed to it
(a generic multi-agent orchestrator, a LinkedIn posting agent, a generic A2A server).

building-fabric-services under-triggers on topics its description does not name: settings and caches that survive a
reinstall, a single running copy under launchd, the runner route checks, the signed estate record, and packing and
signing a `fabric-package/1` folder (both models miss these). On 2026-10-24 it scored haiku 38/45, sonnet 44/45 on
45 cases; the file holds 50 now. Filed as FAA-336 (its description, within the listing
budget), since the sonnet run passes and no release depends on it.

Raw answers: [creating](2026-11-15-trigger-run/creating-fabric-agents.json),
[building, haiku](2026-11-15-trigger-run/building-fabric-services.json),
[building, sonnet](2026-11-15-trigger-run/building-fabric-services-sonnet.json).
