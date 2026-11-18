# Handoff: two MCP doors in the service kit (FAA-356, 0.98.0)

- **Objective.** The agents database's board request `a7277193` (thread `cb3781e6`, its rule R33 O15, decision D-72;
  first numbered O13 and D-66 on the thread): the kit's MCP server lists two doors, `<domain>.search` and
  `<domain>.execute`, instead of one tool per capability; a direct tool beside them only on a measured case (the
  operator's later word of 2026-11-18 on the same thread).
- **Done.** `McpToolServer.serve_compact(domain, direct=None, retired=None)`, `search` and `execute` in
  `plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_interop.py`; the job tools take two of
  the three seats with no measurement on a server with a job store, and `retired` (YYYY-MM-DD) is what `search` answers
  on each operation no longer listed (the base's settled points, thread message `6f0d1e79`); the probe's
  `interop.compact-listing` and the capability checks read through `search` (`check_service.py`,
  `compact_listing_rule`); the reference section "Two doors: search and execute" in `references/interop.md`;
  `kit.json` history 0.98.0; CHANGELOG; backlog row FAA-356.
- **Decisions.** Opt-in in 0.98.0, as the request asks ("opt-in first, then default"); a full listing of more than five
  tools is `interop.compact-listing` NOT_RUN, never FAIL, so no service's probe turns red on upgrade. No Node twin: the
  kit's MCP server class exists only in Python (`fabric-interop.mjs` has no server). The row was FAA-354 on the first
  run's branch; 0.97.2 took that id on `main` first, so the rebase renumbered it FAA-356. `retired` has no default (a
  default of "today" would move with every restart).
- **Checks run.** `python3 -B -m unittest test.test_compact_mcp` (21 OK, four a live probe of the sample service); the
  full Python and Node suites, `test/validate.py` and both strict plugin validations (results in PR #336).
- **Open.** (1) Make compact the default once the estate's kit services moved (the base's rollout row RO-825).
  (2) The base's `Door` wrapper can drop its `/mcp?surface=capabilities` listing after it takes 0.98.0.
  (3) FAA-355: the contract's CM-7 shape of `interop.tools-match` at the next repin. (4) Tag v0.97.1, v0.97.2 and
  v0.98.0 are not pushed: npm `latest` is 0.97.0 until a release run.
- **Next task.** Release 0.98.0 (tag `v0.98.0` from `main`, watch `release.yml`, confirm npm), then FAA-356 (1) when
  rollout row RO-825 says the services moved.
