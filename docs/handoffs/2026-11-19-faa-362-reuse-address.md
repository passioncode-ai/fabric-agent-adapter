# Handoff: FAA-362, no SO_REUSEADDR on Windows for the kit's loopback server (2026-11-19)

- **Objective.** Project Observatory's board request `fdb8b224` (thread `5179a170`): its engine vendors
  `fabric_service.py` byte for byte, and the kit's `LoopbackHTTPServer` inherited `allow_reuse_address = 1`, which on
  Windows lets a second listener bind a port a live socket holds (engine OBS-643, its PR #597).
- **Done.** `allow_reuse_address = os.name != "nt"` on `LoopbackHTTPServer`
  (`plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_descriptor.py`), `kit.json` rebuilt for
  0.98.4, versions synced, CHANGELOG 0.98.4, backlog row FAA-362. Tests in `test/test_fabric_service.py`
  (`LoopbackServerTests`): the attribute and its source line, and a second server binding a held port raises `OSError`.
  The Node twin (`loopbackServer`, `net.createServer`) needs nothing: libuv sets no `SO_REUSEADDR` on Windows.
- **Checks run.** `python3 -m unittest discover -s test`, `python3 test/validate.py`, `node --test 'test/*.test.mjs'`,
  both `claude plugin validate --strict` (results in the PR).
- **Open.** Tags since v0.97.1 are not pushed: npm `latest` is 0.97.0. A release run (tag `v0.98.4`, carrying 0.97.1 to
  0.98.4) is a publication and waits for the operator's session or an approved `fabric_effect_request`. The engine can
  take the new bytes from `main` at the merge commit meanwhile.
- **Next task.** Tag `v0.98.4` from `main`, watch `release.yml`, confirm npm `0.98.4`, then tell Project Observatory on
  thread `5179a170`.
