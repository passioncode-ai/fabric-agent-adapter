# FAA-58: what the estate learned about building agents, in `creating-fabric-agents` (0.37.0)

Objective (the operator, 2026-10-19): everyone who installs the adapter builds agents the right way: how to use
OpenRouter, how an agent runs in the cloud and connects to a personal cloud or an organization's, correct agents,
learning loops, orchestrators, model choice, several kinds of input and output, best practices.

## Done

- Four references in `plugins/fabric-agent-adapter/skills/creating-fabric-agents/references/`:
  `where-agents-run.md`, `models-and-providers.md`, `orchestration-and-learning.md`, `practices.md`.
- `SKILL.md`: grill rows *Where does it run, for whom?*, *Which models?*, *Who pays?*, *How does it learn?* (they
  replace *Which tenancy?*); the knowledge intake links the four references; the description names the cloud and
  OpenRouter triggers (951 characters, strict YAML).
- `test/validate.py` rule with `KnowledgePackTests` (4 tests, seen failing before the rule); eval scenario
  `agent-for-a-personal-and-an-organization-cloud`; three trigger queries; `SKILL-CARD.md` inputs.

## Sources and decisions

- The knowledge base (`fabric-workspace/knowledge/`) is private (wiki.passioncode.ai answers 401) and the adapter is
  public, so the skill carries a public distillate: each rule and its check, without receipts, product or client names,
  prices or private paths; members are pointed to `knowledge/agent-practices.md`.
- Facts about clouds and contexts come from the public contract at the pin (`contexts.md`, `estate-record.md`,
  `share-registration.md`, `entitlement.md`, `ceremonies.md`) and from the standing decisions SD-1 to SD-3 without
  their prices.
- The model table is dated 2026-10 and tells the reader to re-read the OpenRouter catalog; it carries no measured
  client data.

## Checks run

- `python3 test/validate.py`: OK at 0.37.0.
- `python3 -m unittest discover -s test`: 703 tests, OK (22 skipped).
- `node --test 'test/*.test.mjs'`: 242 tests, 234 pass, 0 fail, 8 skipped.
- `claude plugin validate ./plugins/fabric-agent-adapter --strict` and `claude plugin validate . --strict`: passed.
- No U+2014 in any added line.

## Next task

Release 0.37.0 (PR, CI on the exact head, tag, npm, launcher, local install). Then FAA-57 (0.36.1's pairing and redeem
content, now 0.37.1), the contract rows CT-18/28/42/51/52, and the adapter's own practices added to the knowledge base
page under its lease.
