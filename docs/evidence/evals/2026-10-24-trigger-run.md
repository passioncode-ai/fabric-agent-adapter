# Trigger evals of the other three skills, 2026-10-24

FAA-88: after [the run of 2026-10-22](2026-10-22-trigger-run.md) covered `adapting-projects-to-fabric`, the other
three skills' trigger evals had never run against a model. This records them (FAA-111, REQ-4).

## What ran

```bash
for skill in creating-fabric-agents building-fabric-services working-with-fabric; do
  FABRIC_REAL_CLIENT=1 python3 test/evals/run_evals.py --skill "$skill" --model haiku --jobs 6 \
    --json "docs/evidence/evals/2026-10-24-trigger-run/$skill.json"
done
```

- Started 2026-10-24T02:17:42Z; every run exited 0.
- Client: Claude Code 2.1.299, `claude -p --model haiku`, set up as in the 2026-10-22 run (no tools, no MCP servers,
  no setting sources, an empty temporary directory). Each case shows the four skills' front matter descriptions
  plus `none`, and one request; the model answers one name.
- Two rounds: the first on the descriptions of 0.48.3, the second after the description edits below. The JSON files
  hold the second round (every case and answer); the first round's pass rates are kept here only.
- Cost reported by the client, second round: $0.0109, $0.0187 and $0.0159 (about $0.045). The first round cost
  about the same ($0.0101, $0.0185, $0.0149).

## Result

| Skill | First round | Second round | Positives | Negatives | Errors | Threshold 85% |
|---|---|---|---|---|---|---|
| creating-fabric-agents | 24/26 | 26/26 (100.0%) | 12/12 | 14/14 | 0 | PASS |
| building-fabric-services | 38/45 (84.4%, below) | 44/45 (97.8%) | 27/27 | 17/18 | 0 | PASS |
| working-with-fabric | 38/39 | 38/39 (97.4%) | 23/23 | 15/16 | 0 | PASS |

The first round's misses were boundary negatives: requests a description pulled in that belong to a sibling or to no
skill. The edits name those boundaries in the descriptions (each stays within 1024 characters):

- `building-fabric-services`: names its dashboard link and kit, data and cache paths, callers and their
  authentication, long jobs, the spend report and limits, runner routes and model profiles, the estate record and
  delegation tokens; and says it is not for building the Dashboards app itself (window, tray).
- `creating-fabric-agents`: not for an agent, bot or A2A server that need not speak Fabric.
- `working-with-fabric`: the lifecycle broker in scope only for starting Fabric, not other apps.

## The two misses left

| Should trigger | Query | Routed to |
|---|---|---|
| no | Build the Fabric Dashboards desktop app window and tray icon. | building-fabric-services |
| no | Restart the example-agent app through the lifecycle broker. | working-with-fabric |

Both are near the boundary each description now states in words; a small model still matches on the shared nouns
(Dashboards, lifecycle broker). Both skills stay above the threshold, so the descriptions are not tightened further:
each extra word costs every session that lists the skill. A larger model would read the stated boundary; the next
run with `--model sonnet` is the check, when one is wanted.

Raw output: [creating-fabric-agents.json](2026-10-24-trigger-run/creating-fabric-agents.json),
[building-fabric-services.json](2026-10-24-trigger-run/building-fabric-services.json),
[working-with-fabric.json](2026-10-24-trigger-run/working-with-fabric.json).
