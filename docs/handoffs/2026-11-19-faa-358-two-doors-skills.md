# Handoff: the skills teach the two MCP doors (FAA-358, 0.98.1)

- **Objective.** sshlg-skills' board request `ab3ecf7e` (thread `a158bc35`, 2026-11-18): every MCP server we build or
  run lists two doors, `search` and `execute`; the adapter's kit serves it and its skills teach it, linking the canon
  (agent-stack 0.33.0, `plugins/agent-stack/skills/agent-interop/references/mcp-two-doors.md`, commit `98025b3`).
- **Done.** Items 1 and 2 were already on `main` as FAA-356 (0.98.0, `serve_compact`, job tools in two of the three
  seats). Item 3 here: `building-fabric-services`, `adapting-projects-to-fabric` and `creating-fabric-agents` SKILL.md
  name the two doors and link the canon; `references/interop.md` names the canon as the rule; one scenario eval per
  skill; versions 0.98.1; CHANGELOG; backlog FAA-358.
- **Decisions.** `serve_compact` stays opt-in (FAA-356's decision: default once the estate's kit services moved,
  rollout row RO-825), so no running service's `tools/list` changes on upgrade. Old names stay callable with no sunset
  (R28), stricter for callers than the canon's one release.
- **Checks run.** `python3 test/validate.py`, `python3 -B -m unittest discover -s test`, `node --test 'test/*.test.mjs'`,
  both `claude plugin validate --strict` (results in the PR).
- **Open.** Tags v0.97.1 to v0.98.1 are not pushed (npm `latest` 0.97.0): a release run is a publication.
- **Next task.** Release (tag from `main`, watch `release.yml`, confirm npm), then FAA-356 next step 1 when RO-825 says
  the services moved.
