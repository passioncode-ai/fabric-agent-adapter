# 2026-10-22: the contract repin (0.43.0) and `fabric-connections/0.1` (0.44.0)

**Objective.** The operator's «дальше до конца» after 0.42.1: take the next rows to the end. FAA-95 (the repin the
contract asked for on board threads `d0d274d0` and `cd8496a2`), then FAA-62 (what an agent uses, asked by Fabric
Dashboards on `131648c0`), and the small rows that fit beside them (FAA-90, FAA-96, FAA-97).

**Done.**
- **0.43.0, FAA-95** ([brief](../evidence/specs/2026-10-22-faa-95-repin-bfa9a67-brief.md)): pin `bfa9a67` (the
  contract review and DEC-0097), `c55f2d5` supported; vectors regenerated from the contract's functions; the delegation
  chain's partner rule; `fabric-connections` in both registers; the vendored schemas and the backup's secret-name
  regexes follow DEC-0097 with contract-gated guards. PR [#159](https://github.com/passioncode-ai/fabric-agent-adapter/pull/159)
  (`64cc2f1`), tag `v0.43.0`, [release run 39815536901](https://github.com/passioncode-ai/fabric-agent-adapter/actions/runs/39815536901),
  npm 0.43.0. Launcher 0.2.22 ([passioncode#134](https://github.com/passioncode-ai/passioncode/pull/134)) pins it.
- **0.44.0, FAA-62, FAA-90, FAA-96, FAA-97** ([brief](../evidence/specs/2026-10-22-faa-62-connections-0.44.0-brief.md)):
  a new kit module in both twins, `fabric_connections` / `fabric-connections.mjs`, with the declaration, the reference
  reading, `build_well_known`'s refusal and the probe's `well-known.connections`; a layout check that measured nothing
  exits 3; the session worker waits to its deadline for an exit status; OpenClaw `--remove` drops our dead load path.
  PR [#160](https://github.com/passioncode-ai/fabric-agent-adapter/pull/160) (`5ad5c2c`), tag `v0.44.0` (receipt in
  the backlog rows).
- Board: `d0d274d0` and `cd8496a2` answered; 0.43.0 announced on `67c3a5e0`.
- fabric-workspace: the launcher row in `knowledge/products.md` corrected (PR #367).

**Checks actually run.** 0.43.0: Python 975 OK on 3.11 and 3.9.6 with both contract checkouts installed, Node 295
pass, `validate.py` and both `claude plugin validate --strict` exit 0, hosted validate 39799390019 green on six jobs.
0.44.0: Python 992 OK on 3.11 and 3.9.6, Node 304 pass, the connections suite on Node 18, 22 and 26, hosted validate
39824929148 green on six jobs.

**Certification.** 0.43.0: one blind unit reading, pass, two non-blocking findings fixed in the PR. 0.44.0: three blind
unit readings, each failing on the Python reader's parity with the contract's reference; every finding fixed with a test
seen failing first. The review loop's cap is three rounds; the closing evidence is round three's harness re-run on the
fixed code (0 open-side differences for Python, 0 differences for Node, about 98,000 inputs) and 1,073 reference-answered
inputs pinned in both suites.

**Decisions.** D1 to D4 in each brief; in 0.44.0 also D5 (where Python cannot tell whether WHATWG refuses a URL it
reads the credentials anyway: a doubt hides a declaration, never publishes one) and D6 (the extra vectors keep only
inputs whose answer is the same on Node 18 to 26, since the reference parses URLs with the runtime's own `new URL`).

**Open.** FAA-87 needs the operator's npmjs.com sign-in. FAA-85 waits on moving the kit's private writer below
`fabric_delegation`. FAA-98 (UTS46 for the Python reader's closed side). The earlier open rows are unchanged.

**Exact next task.** FAA-92: split `fabric_interop.py` and `fabric_package.py` (both at the 1000-line ceiling) by
responsibility, both twins, before their next change; then FAA-85 (it needs the same kind of layering move).
