# Trigger evals against a real client, 2026-10-22

Audit finding 33 (FAA-75): the trigger evals were counted by `test/validate.py` and never run against a model. This
records the first run of `test/evals/run_evals.py` on one skill's triggers, kept small on purpose.

## What ran

```bash
FABRIC_REAL_CLIENT=1 python3 test/evals/run_evals.py --skill adapting-projects-to-fabric --model haiku --jobs 8 \
  --json docs/evidence/evals/2026-10-22-trigger-run/adapting-projects-to-fabric.json
```

- Started 2026-10-22T01:31:44Z, finished by 01:41:53Z; exit 0.
- Client: Claude Code 2.1.299, `claude -p --model haiku`, no tools, no MCP servers, no setting sources, no saved
  session, in an empty temporary directory. Each case shows the model the four skills' front matter descriptions
  (as committed at `cf8ffb4`, after the FAA-75 boundary edits) plus `none`, and one request; it answers one name.
- Cases: the 25 queries of `test/evals/adapting-projects-to-fabric/triggers.json` (11 positive, 14 negative,
  including the three cross-skill negatives added for the sibling boundaries).
- Cost reported by the client: $0.0098 in total.

## Result

| Skill | Passed | Pass rate | Positives | Negatives | Errors | Threshold |
|---|---|---|---|---|---|---|
| adapting-projects-to-fabric | 25/25 | 100.0% | 11/11 | 14/14 | 0 | 85%, PASS |

The negatives were routed to `none` 9 times, `creating-fabric-agents` 3, `working-with-fabric` 1 and
`building-fabric-services` 1: each of the three cross-skill negatives went to the sibling it was written for.
Two generic requests ("Create a generic A2A server from scratch", "Make an agent that posts to LinkedIn every day")
were routed to `creating-fabric-agents`, which pass here but are negatives in that skill's own `triggers.json`: its
description likely attracts agent builds with no Fabric requirement, and its own run is the check. Raw output:
[adapting-projects-to-fabric.json](2026-10-22-trigger-run/adapting-projects-to-fabric.json) (every case and answer) and
[adapting-projects-to-fabric.log](2026-10-22-trigger-run/adapting-projects-to-fabric.log) (the runner's stdout).

| Should trigger | Query | Routed to |
|---|---|---|
| + | Adapt this autonomous research agent so Fabric can connect it over A2A. | adapting-projects-to-fabric |
| + | Make this MCP server compatible with the Fabric Agent Contract. | adapting-projects-to-fabric |
| + | Wrap our terminal coding agent as a Fabric local runner. | adapting-projects-to-fabric |
| + | Choose MCP or A2A for this provider and generate fabric-agent.json. | adapting-projects-to-fabric |
| + | Проверь проект и подготовь его для подключения к Fabric. | adapting-projects-to-fabric |
| + | Сделай этого агента совместимым со стандартом Fabric. | adapting-projects-to-fabric |
| + | Как подключить Pruvl к Fabric и пройти проверку совместимости? | adapting-projects-to-fabric |
| + | Создай provider bundle, fixtures и probes по Fabric Agent Contract. | adapting-projects-to-fabric |
| + | Audit this agent repository against Fabric contract 0.1.0. | adapting-projects-to-fabric |
| + | Migrate this HTTP job API into a Fabric-compatible A2A peer. | adapting-projects-to-fabric |
| - | Build a multi-agent orchestrator for our product. | none |
| - | Add this MCP server to my Claude Code config. | none |
| - | Write a better system prompt for the research agent. | none |
| - | Create a generic A2A server from scratch. | creating-fabric-agents |
| - | Review the architecture of this repository. | none |
| - | Connect an OAuth MCP server through agentgateway. | none |
| - | Make an agent that posts to LinkedIn every day. | creating-fabric-agents |
| - | Install the Fabric repository locally. | none |
| - | Design the Fabric host registry and admission runtime. | none |
| - | Проведи общий аудит проекта и найди баги. | none |
| + | Register our stdio MCP agent with Fabric; it is not a service and has no port. | adapting-projects-to-fabric |
| - | Pick a Postgres connection pool size for our API. | none |
| - | Подключись к Fabric и возьми задачу FAA-12 через fabric_work_claim. | working-with-fabric |
| - | Create a brand-new Fabric-compatible agent from scratch and run its intake grill. | creating-fabric-agents |
| - | Turn example-agent into an always-on local Fabric service with a dashboard and launchd. | building-fabric-services |

## What this does not prove

- It measures routing over descriptions in isolation, not a full Claude Code session where other installed skills
  compete and the host decides when to load a skill. A full-session run is NOT_RUN.
- One run, one model, one skill. The other three skills' triggers are NOT_RUN here (the spend was kept to one skill);
  the same command with `--skill <name>` runs them.
- Scenario evals (`scenarios.json`) need a judge of free-form behaviour; the runner reports them NOT_RUN.
