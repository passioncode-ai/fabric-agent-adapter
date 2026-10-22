# Brief: FAA-62 (fabric-connections/0.1) and FAA-90, FAA-96, FAA-97 as 0.44.0

**Request:** the operator's «дальше до конца» (2026-10-22): the next rows after 0.43.0. FAA-62 was unblocked when the
contract decided DEC-0096 (`63bb296`) and Fabric Dashboards adopted its reader (0.7.19, CT-70). Route: task-pipeline,
full flow recorded here.

## Source ledger

| Source | What it says |
|---|---|
| contract `bfa9a67` `docs/specification/connections.md` | the declaration, the credential rules, `connectionsView`, FAC-SEM-127; the adapter owes the emission from a declared list, `state` from its checks and `degraded[].source` |
| contract `src/connections.ts`, `fixtures/vectors/connections.json` (127 cases) | the reference reading every port runs |
| ajv-formats 3.0.1 `dist/formats.js` in the contract's install | `date-time` in full mode (zone required, `t` or a space, calendar and leap second) |
| backlog FAA-90, FAA-96, FAA-97 | findings of the 0.41.0 builders and the 0.42.0 blind reading |

## Requirements

| REQ | What | Verified by |
|---|---|---|
| REQ-1 | Both twins read a connections list as `connectionsView` does | all 127 vendored cases in `test_fabric_connections.py` and `fabric-connections.test.mjs` |
| REQ-2 | Both twins build a declaration: `state` from checks, else `degraded`, else `unknown`; a hidden one is refused | producer tests in both |
| REQ-3 | `build_well_known` refuses an invalid declaration; the probe reports `well-known.connections` | tests in both, the probe test |
| REQ-4 | A layout report that measured nothing exits 3 (FAA-96) | `test_dashboard_layout`, `entry-points.test.mjs`, red first |
| REQ-5 | The worker waits for an exit status to its deadline (FAA-97) | a late-exit server test, red first |
| REQ-6 | OpenClaw `--remove` drops our dead load path (FAA-90) | `test_native_hook_install`, red first |

## Decisions

| Id | Decision | Source |
|---|---|---|
| D1 | The schema is checked by hand in each twin, not by a JSON Schema library: the kit is standard library only; the 127 vectors hold the two readings to the reference | AGENTS.md, local rules |
| D2 | A failing connection named in `degraded[]` reads `degraded`, not `down`: the service still runs; a service that knows it is down says so in `states` | connections.md, *Reading it* |
| D3 | FAA-96: "nothing measured" is exit 3, distinct from a failure (1) and a usage error (2); an empty report moves from 2 to 3 | the kit's rule that a check that measured nothing is never a pass (board `b42e16b7`) |
| D4 | FAA-85 waits: its fix needs the private writer moved below `fabric_delegation` in the kit's layers | `test_the_order_is_a_layering` |
| D5 | Where the Python twin cannot tell whether WHATWG would refuse a URL (a non-ASCII host, which WHATWG maps through UTS46), it reads the URL's credentials anyway: a doubt then hides a declaration the reference would show, never publishes one the reference hides. The closed side (about 1,200 of 4,195 single-code-point hosts in the second reading) is row FAA-98 | the second blind reading: no open difference left in 38,882 inputs; 522 of them pinned in `test/fixtures/kit-connections-inputs.json` |
