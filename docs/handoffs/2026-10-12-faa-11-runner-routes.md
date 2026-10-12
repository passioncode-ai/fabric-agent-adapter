# Handoff — FAA-11: runner routes in both kits (0.20.0)

**Objective.** Adopt DEC-0026 and DEC-0029 at the pin:
- the probe reports a runner's state with the contract's closed probe results;
- the kits check a route, a route bundle and a route event with FAC-SEM-028…034.

The pin part was done by FAA-14.

**Done.**

- `runner_check` / `runnerCheck` answer with `probe`:
  - `not-installed`;
  - `not-responding`;
  - `not-connected`;
  - none, when the runner can serve.

  They follow the walk's order, and the doctor still lists every problem.
- `route_problems` / `routeProblems` and `PROBE_RESULTS` live in `fabric_profiles.py` and `fabric-profiles.mjs`.
- Docs: *Runner routes* in `references/profiles.md`, a pointer in `SKILL.md`, the eval scenario
  `runner-routes-and-probe-results` written first, and a trigger.

**Checks run.**

- `test/fixtures/contract/route-vectors.json` holds 43 cases.
  - `make_route_vectors.mjs` generated them from the contract's `src/route-rules.ts` at the pin, staged with its
    `.js` imports rewritten to `.ts`.
  - Run with Node ≥ 24: `--contract-src <dir> --positive <dir with runner-route*.json and binding-runner-route.json>`.
  - Both kits match code, path and message.
- Mutation testing: 23 planted defects, all caught. One more mutant survived at first; the vector "a fractional index
  beside the kind at its floor" was added for it, and it is now caught.
- `npm test` passes on macOS (401 Python, 105 Node), as do `test/validate.py` and both strict plugin validations.
- Validate run [38203497306](https://github.com/passioncode-ai/fabric-agent-adapter/actions/runs/38203497306) is green
  on Linux, Windows and the plugin job.

**Decisions.**

- The kits do not walk routes. Fabric (the host) walks them. A service gets the walk's vocabulary (`probe`,
  `PROBE_RESULTS`) and the checks for what it pins or records.
- A version probe whose answer does not match the catalogue's pattern counts as `not-responding`. The catalogue's
  own probe is the only judge.

**Open.** No unblocked rows remain in this repository's backlog:
- FAA-26…29 wait for the contract §12 objects and Fabric (D2, D2b, D3);
- FAA-10 waits for `surfaces.a2a`;
- FAA-12 waits for COM-03;
- FAA-04/05 are deferred.

**Next task.**
1. Re-pin the passioncode launcher to v0.20.0 and update the local install.
2. Then watch the contract for the §12 objects (`fabric-package/1` has landed as P3-01; Fabric's D2 decides ES256)
   and repin when FAA-26 or FAA-29 can start.
