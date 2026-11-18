# Handoff: two MCP doors in the service kit (FAA-354, 0.98.0)

- **Objective.** The agents database's board request `a7277193` (thread `cb3781e6`, its rule R33 O13, decision D-66):
  the kit's MCP server lists two doors, `<domain>.search` and `<domain>.execute`, instead of one tool per capability;
  a direct tool beside them only on a measured case (the operator's later word of 2026-11-18 on the same thread).
- **Done.** `McpToolServer.serve_compact(domain, direct=None)`, `search` and `execute` in
  `plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_interop.py`; the probe's
  `interop.compact-listing` and the capability checks read through `search` (`check_service.py`,
  `compact_listing_rule`); the reference section "Two doors: search and execute" in `references/interop.md`;
  `kit.json` rebuilt at 0.98.0; CHANGELOG; backlog row FAA-354.
- **Decisions.** Opt-in in 0.98.0, as the request asks ("opt-in first, then default"); a full listing of more than five
  tools is `interop.compact-listing` NOT_RUN, never FAIL, so no service's probe turns red on upgrade. No Node twin: the
  kit's MCP server class exists only in Python (`fabric-interop.mjs` has no server).
- **Checks run.** `python3 -B -m unittest test.test_compact_mcp` (19 OK, four a live probe of the sample service); the
  full Python and Node suites, `test/validate.py` and both strict plugin validations (results in the PR).
- **Open.** (1) Make compact the default once the estate's kit services moved (the base's rollout row). (2) The base's
  `Door` wrapper can drop its `/mcp?surface=capabilities` listing after it takes 0.98.0.
- **Next task.** Reply on thread `cb3781e6` with the release, then take FAA-354 (1) when the base's rollout row says
  the services moved.
