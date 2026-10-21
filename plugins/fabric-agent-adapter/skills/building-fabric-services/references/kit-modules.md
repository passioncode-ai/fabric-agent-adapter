# The service kit: modules, layers and installing them

Since 0.40.0 (FAA-65) the kit is a set of small modules in two languages, not two large files. `scripts/kit.json`
lists every module in dependency order, per language, with the kit modules it imports and its sha256; `history` keeps
the digests of every release since 0.8.0, so a copy in a service can be told apart. `scripts/fabric_kit.py` installs a
module with exactly what it needs and reports a copy's state. Tests: `test/test_fabric_kit.py`,
`test/test_kit_api.py`, `test/kit-api.test.mjs`.

## Contents

- [Install, status, build](#install-status-build)
- [The layers](#the-layers)
- [What 0.39 code keeps](#what-039-code-keeps)
- [Dates and times](#dates-and-times)
- [Adding or changing a module](#adding-or-changing-a-module)

## Install, status, build

```bash
K=<adapter>/plugins/fabric-agent-adapter/skills/building-fabric-services/scripts
python3 $K/fabric_kit.py install <service-dir>                      # fabric_service and its closure (Python)
python3 $K/fabric_kit.py install <service-dir> --lang node          # fabric-service.mjs and its closure
python3 $K/fabric_kit.py install <service-dir> --module fabric_openrouter --module fabric_board
python3 $K/fabric_kit.py install <service-dir> --all --dry-run      # every module, nothing written
python3 $K/fabric_kit.py status <service-dir> [--json]              # current, older (the release), modified, missing
python3 $K/fabric_kit.py build [--check]                            # maintainers: refresh kit.json from the sources
```

- `install` copies the closure of the named modules and nothing else. It refuses to overwrite a file it does not
  recognise (`modified`: someone edited the copy) unless `--force`, and says which.
- `status` names each kit file in the folder as `current`, `older` with the release it came from, or `modified`, and
  prints `missing <file>, which <file> imports` for a module the folder lacks: that copy would fail when that code
  path runs. A folder holding only the 0.40.0 `fabric_service.py` gets one such line per module it needs.
- Exit codes: 0 done or all current, 1 a problem (missing, modified, refused), 2 usage.
- `build --check` is what CI runs: `kit.json` must be what the sources say.

## The layers

A module imports only modules listed before it in `kit.json`, so the kit has no import cycle and no upward import
(`test_the_order_is_a_layering`; a planted cycle is caught). Python name first, the Node twin is the same name with
`-` for `_` and `.mjs`. No module is over 1000 lines (`test_no_module_over_the_line_ceiling`).

| Layer | Module | What it holds |
|---|---|---|
| L0 | `fabric_jsvalue` | JavaScript's view of JSON values: numbers, strings, equality, `jcs`, `show`; defined once for the kit |
| L0 | `fabric_time` | strict RFC 3339, UTC days, formatting, day windows, the clock ([dates](#dates-and-times)) |
| L0 | `fabric_identifiers` | identifier equality by normal form (DEC-0076) |
| L0 | `fabric_secrets` | the contract's one credential detector (DEC-0044) |
| L1 | `fabric_crypto` | Ed25519 and P-256 verification, base64url, sha256: what the verifiers need and nothing more |
| L2 | `fabric_estate` | `estate-record/1` revisions and their rules (DEC-0055) |
| L2 | `fabric_delegation` | the callee's side of `fabric-delegation/0.1` (DEC-0039) |
| L2 | `fabric_share` | share grants and registrations (DEC-0086) |
| L2 | `fabric_ceremonies` | the headless join token (DEC-0084) |
| L2 | `fabric_package` | `fabric-package/1`: pack, sign, verify (DEC-0050, DEC-0051) |
| L3 | `fabric_base` | the protocol name, `ServiceError`, small shared helpers |
| L3 | `fabric_platform` | Windows: named pipes, owner-only files (DEC-0032) |
| L3 | `fabric_paths` | the services directory, a service's folders, atomic and private writes |
| L3 | `fabric_protocols` | protocol revisions (DEC-0067) and feed data (DEC-0070) |
| L3 | `fabric_lock` | the instance lock and the supervisor marker (LC-01, DEC-0057) |
| L3 | `fabric_usage` | usage receipts, the ledger, the usage report, attribution, spending limits ([usage](usage.md)) |
| L3 | `fabric_backups` | settings backups (DEC-0025) |
| L3 | `fabric_descriptor` | the descriptor, peers, app descriptors, the well-known document |
| L3 | `fabric_auth` | the token, the network guard, login codes |
| L3 | `fabric_events` | events, paging, the JSONL event log (DEC-0029) |
| L3 | `fabric_logs` | rotating logs, the stop signal and the drain (LC-12) |
| L3 | `fabric_supervisors` | launchd, systemd user units, Task Scheduler (DEC-0032, LC-14) |
| L3 | `fabric_service` | the facade: every name 0.39.1 exported, re-exported from the modules above |
| L3 | `fabric_profiles` | runner and model profiles ([profiles](profiles.md)) |
| L3 | `fabric_interop` | `fabric-interop/0.1`: jobs, envelopes, MCP tools ([interop](interop.md)) |
| L4 | `fabric_hub` | the Fabric hub's door (`fabric-hub/0.1`) |
| L4 | `fabric_board_shapes` | the project board's wire: constants, refusal codes, shapes |
| L4 | `fabric_board_session` | the board responder: a session, the checkpoint, the fenced request |
| L4 | `fabric_board_fixture` | the scripted board the probe runs a responder against |
| L4 | `fabric_board` | the facade of the board connector ([board](board.md)) |
| L4 | `fabric_http` | outbound HTTP: deadline, bounded retries, `Retry-After`, size cap ([connectors](connectors.md)) |
| L4 | `fabric_openrouter` | OpenRouter chat: own key, spend ceiling, receipts, fallback ([connectors](connectors.md)) |

Beside the kit, not in `kit.json`: the probe (`check_service.py`, `check_service_rules.py`), the sample
(`sample_service.py`, `sample-remote-service.mjs`), `fabric_kit.py` itself and the dashboard tools. Recipes built on
the kit live in `../recipes/` ([the support agent](../recipes/support-agent/README.md)).

## What 0.39 code keeps

`import fabric_service as fs` and `import ... from './fabric-service.mjs'` keep working: the facades re-export every
public name 0.39.1 had, in both languages (the snapshot is `test/fixtures/kit-api/kit-api-0.39.1.json`; a missing
name fails `test_kit_api`), and the Python facade the private names too. `fabric_board` and `fabric-board.mjs` are
facades the same way. What changed for a service that copies the kit: `fabric_service.py` alone is no longer enough;
install with `fabric_kit.py install` and `status` names what is missing. A service that imported a module-private
helper (`_x`) of the Node twin should import it from its module now.

## Dates and times

`fabric_time` / `fabric-time.mjs` is the kit's one reading of dates, on the cases both twins test
(`test/fixtures/kit-time-cases.json`). Anything unreadable is NaN, never an exception, so a check compares it and
reports a finding.

| Python | Node | What |
|---|---|---|
| `parse_rfc3339_ms(text)` | `parseRfc3339Ms(text)` | strict RFC 3339: a `T`, an offset and a day that exists; no space, no leap second; milliseconds or NaN |
| `utc_date_ms(text)` | `utcDateMs(text)` | a `YYYY-MM-DD` that exists, as midnight UTC in milliseconds, or NaN |
| `utc_day(ms)` | `utcDay(ms)` | the UTC calendar day of an instant (NaN or Infinity raise) |
| `format_rfc3339(ms)` | `formatRfc3339(ms)` | `2026-10-21T09:00:00.000Z`, which parses back to the same value |
| `day_window(today_ms, days)` | `dayWindow(todayMs, days)` | the last N UTC days ending with today's, oldest first (a usage report's 31) |
| `clock_ms(at)` | `clockMs(at)` | a verifier's clock (an aware `datetime` / a `Date`, or epoch seconds) in milliseconds |
| `now_ms(clock)` | `nowMs(clock)` | now in milliseconds; `clock` returns seconds in Python (`time.time`), milliseconds in Node (`Date.now`) |
| `DAY_MS` | `DAY_MS` | 86 400 000 |

`fabric_estate.estate_time` is `parse_rfc3339_ms` under its older name.

## Adding or changing a module

1. Put it in the lowest layer whose modules it needs; import only modules listed before it.
2. Write the Node twin with the same public names in camelCase, and shared cases under `test/fixtures/` that both
   test files read.
3. Add it to `kit.json` (module, file, layer) and run `fabric_kit.py build`; add it to the table above
   (`test_every_kit_module_is_documented`).
4. A value or helper the core already has is imported, never redefined (`test_the_core_is_defined_once`).
5. Stay under 1000 lines; split by responsibility, keeping a facade when callers already import the old name.
