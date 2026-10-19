# FAA-52: new agents carry the no-em-dash rule for text people read

Brief and spec in one page (small change: two skill documents, one validator rule, one eval scenario).

## Source ledger

| Source | What it gave |
|---|---|
| [docs/backlog.md](../../backlog.md) FAA-52 | the task: grill, resilience checklist, eval scenario |
| Operator rule of 2026-10-18 (operator's global instructions, "No em dash in text for people") | the rule: no U+2014 and no substitute (`--`, a spaced hyphen used as a dash) in text a person reads; exceptions are exact quotations, code, commands, paths, historical records; an agent that writes text for people carries the rule in its prompt plus a check that fails on U+2014 in new output |
| `plugins/fabric-agent-adapter/skills/creating-fabric-agents/SKILL.md` Step 0 | the intake grill table the new row joins |
| `.../references/resilience-and-autonomy.md` "Checklist" | the release checklist the new item joins |
| `test/validate.py` `BUILDER_SKILLS` phrase checks, `test/test_validate.py` mutation tests | the existing way a required sentence in a skill is enforced |
| `test/evals/creating-fabric-agents/scenarios.json` | 13 scenarios; format `{id, request, expected[]}` |
| fabric-workspace `knowledge/` | no page carries the rule (`git grep -i "em dash\|U+2014" origin/main -- knowledge`: empty) |
| docs/evidence/retro.md | none found |

## Decisions

- The rule is stated as the agent's default for text people read, attributed to the operator, with no private path or
  configuration (the repository is public).
- The mechanical check fails on U+2014 only. A spaced hyphen used as a dash cannot be told from a range or a minus by a
  pattern, so the prompt carries it and a reviewer judges it; the check is not widened into false positives.
- This repository's own skill prose keeps its existing dashes: the rule binds what a generated agent writes for people,
  and rewriting every skill document is a separate change, not this row.

## REQ table

| REQ | Requirement | Verified by |
|---|---|---|
| R1 | Step 0 grill asks whether the agent writes text a person reads; if yes, the rule goes into its prompt and a check that fails on U+2014 into its tests | `test/validate.py` phrase rule; `test_validate.py` mutation test seen failing first |
| R2 | The resilience reference states the rule with its exceptions and a portable check, and its checklist asks for it | same validator rule (reference side); mutation test |
| R3 | An eval scenario covers an agent that writes text for people | `scenarios.json` parses, `validate.py` exit 0, scenario id present |
| R4 | CHANGELOG Unreleased entry; FAA-52 closed in the backlog with a receipt | release 0.35.3 notes; backlog row |
