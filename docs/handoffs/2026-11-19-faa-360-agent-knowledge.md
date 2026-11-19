# Handoff: the skills teach a project's knowledge surface (FAA-360, 0.98.3)

- **Objective.** Board request `52f7914b` (thread `7802adb1`, 2026-11-19), relayed from another Project with the
  operator's words of 2026-11-19 (provenance `trusted`, scope: every Fabric project, always): every project other
  agents call, build on or read keeps a RAG search with verified citations, a hybrid index and an MCP server with two
  doors, and agents ask each other through it.
- **Done.** `references/agent-knowledge.md`, one text in `adapting-projects-to-fabric`, `creating-fabric-agents`,
  `building-fabric-services` and `working-with-fabric`; a paragraph in each of their SKILL.md; the consumers' audit in
  `observing-products` (Phase 2); `test/test_agent_knowledge_prose.py`; one scenario eval per skill; versions 0.98.3;
  CHANGELOG; backlog FAA-360 (done) and FAA-361 (open).
- **Decisions.** The template rule (agents database request `e968b42b`) and the two doors (agent-stack canon at
  `98025b3`) are linked, not copied. The requester's own project is not named in this public repository (neutral names
  rule); its board request id is. `knowledge.search` is an operation behind `execute`, so the doors stay two.
- **Checks run.** `python3 test/validate.py`, `python3 -B -m unittest discover -s test`, `node --test 'test/*.test.mjs'`,
  both `claude plugin validate --strict` (results in the PR).
- **Open.** FAA-361, the kit's own index module. Tags since v0.97.1 are not pushed: a release run is a publication.
- **Next task.** FAA-361 (spec first: the module's layer in `kit.json`, the verifier's contract, the evaluation file's
  shape), or the release when the operator's session takes it.
