# Handoff: the knowledge layer of D-84 in the adapter (FAA-366, 0.99.1)

- **Objective.** Board request `599b59d6` (thread `01b4e997`, 2026-11-19) from the agents database, with the operator's
  words of 2026-11-19 relayed verbatim (provenance `trusted`, scope: the knowledge layer and its graphs wherever the
  adapter teaches how an agent is built): the intake asks for the knowledge layer and puts D-84's eight parts in the
  bundle; a knowledge map panel recipe; the traps found.
- **Done.** Part 4 of `references/agent-knowledge.md` (one text in four skills); the grill row "Does it keep a knowledge
  base?" in `creating-fabric-agents`; the audit paragraph in `adapting-projects-to-fabric`;
  `building-fabric-services/references/knowledge-map-panel.md`, linked from its SKILL.md (the SKILL.md sits at 4749
  words, the validator's line is 4750); `test/test_knowledge_layer_prose.py`; three scenario evals; versions 0.99.1;
  CHANGELOG; backlog FAA-366 (done) and FAA-367 (open).
- **Decisions.** The renderers are not vendored into the public package in this change: about 1.7 MB of libraries and
  a schema the contract has not pinned yet; the recipe names them and FAA-367 holds the component. The map's fields are
  the ones the base's built map carries (`edges`, `clusters` with `label` and `size`), read from its data file, not from
  the request's prose. Semantic map is the starting variant because it injects no style and runs under the kit's strict
  CSP. The base's private report is cited by name, not path (public repository).
- **Checks run.** `python3 test/validate.py`, `python3 -B -m unittest discover -s test`, `node --test 'test/*.test.mjs'`,
  both `claude plugin validate --strict` (results in the PR).
- **Open.** FAA-367; FAA-361. Tag `v0.99.1` not pushed by this run.
- **Next task.** Push tag `v0.99.1` (checks-approved release, FAA-363) from a session that releases, then FAA-361 (spec
  first).
