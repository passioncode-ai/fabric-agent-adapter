# Design: the kits as layered, installable modules (FAA-65)

Brief: [2026-10-21-faa-65-kit-modules-brief.md](2026-10-21-faa-65-kit-modules-brief.md). Stage 2, approved under the
operator's standing instruction "Act, then report" (`~/.claude/CLAUDE.md`), recorded here as the approval.

## The module map

Python file names are listed; each Node twin is the same name in kebab case with `.mjs`. A module imports only from a
lower layer or its own layer's earlier entries in this table (the order is the dependency order).

| Layer | Module | From (today) | Holds |
|---|---|---|---|
| L0 | `fabric_jsvalue` | `fabric_estate`, `fabric_delegation` | JavaScript value semantics: `js_string`, `js_to_number`, `show`, `double`, `safe_integer`, `json_stringify`, `jcs` (RFC 8785), `json_equal` |
| L0 | `fabric_time` | `fabric_estate.estate_time`, the service's UTC date and window helpers | strict RFC 3339, UTC days, N-day windows, a clock that can be injected |
| L0 | `fabric_identifiers`, `fabric_secrets` | unchanged | normal-form ids; secret-shaped strings |
| L1 | `fabric_crypto` | `fabric_delegation`, `fabric_estate` | base64url, Ed25519 verify with the small-order refusal, P-256 point check, sha256 digests |
| L2 | `fabric_estate`, `fabric_delegation`, `fabric_share`, `fabric_ceremonies`, `fabric_package`, `fabric_profiles` | as today, minus what moved to L0/L1 | protocol readers held to the contract's vectors |
| L2 | `fabric_usage` | `fabric_service` (usage report, FAC-SEM-025, attribution, limits) | usage receipts, the report, its rules, OpenRouter attribution, spending limits |
| L2 | `fabric_protocols` | `fabric_service` (DEC-0067, DEC-0070) | protocol revisions and feed data |
| L2 | `fabric_backups` | `fabric_service` (DEC-0025) | settings backups |
| L3 | `fabric_paths` | `fabric_service` | where things live, private dirs, atomic writes |
| L3 | `fabric_lock` | `fabric_service` | one copy: the instance lock and the supervisor marker |
| L3 | `fabric_auth` | `fabric_service` | token, network guard, operator login, cookies, remote placement, Windows ACLs |
| L3 | `fabric_descriptor` | `fabric_service` | the descriptor, peers, app descriptors, build info, the well-known document |
| L3 | `fabric_events`, `fabric_logs` | `fabric_service` | events; rotating logs, shutdown and drain, releases |
| L3 | `fabric_supervisors` | `fabric_service` | launchd, systemd, Task Scheduler |
| L3 | `fabric_interop` | as today | MCP tools, jobs, elicitations, traces |
| L3 | `fabric_service` | facade | re-exports every 0.39.1 name; no logic of its own |
| L4 | `fabric_http` | new | an HTTP client with deadlines, bounded retries, `Retry-After`, a size cap |
| L4 | `fabric_openrouter` | new | OpenRouter chat with a spend ceiling, usage receipts, a fallback model |
| L4 | `fabric_hub`, `fabric_board` | as today, the board split where it exceeds the ceiling | Fabric's hub; the project board |
| L5 | `check_service`, `sample_service`, `recipes/support-agent/` | the probe split by rule area | the probe, the sample, the recipe |

## Rules every module follows

- Standard library only; Python 3.9+, Node 20+.
- No module above 1,000 lines; no import cycle; no upward import. Three tests hold these: `test_kit_layout.py` (Python
  AST), `kit-layout.test.mjs` (Node import scan), and a size test in both.
- A facade keeps every name that was public at `v0.39.1`: the snapshot is generated from the tag into
  `test/fixtures/kit-api-0.39.1.json` and both suites assert the current facade exports a superset.
- Behaviour is unchanged: every existing test and contract vector passes after every wave.

## Distribution

`plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/kit.json` lists, per language, every module, its
sha256 and the modules it imports. `fabric_kit.py install <dir> [--lang py|node] [--module <m> ...]` copies the
closure of the named modules (default: `fabric_service` and what it needs) with a version marker; `status <dir>` says
`current`, `older` or `modified` per file, as the dashboard kit does. The SKILL.md copy step says this instead of "one
self-contained file".

## Connectors

- `fabric_http.request(method, url, *, headers, body, deadline_s, retries, transport)`: retries only an idempotent
  method or a request with an `Idempotency-Key`; backoff with jitter, `Retry-After` honoured up to a cap; the response
  size capped; errors carry the status and a redacted URL; the transport is injected in tests.
- `fabric_openrouter.Client(key_env, ceiling_usd, ledger)`: `chat(messages, model, fallback, max_tokens, ...)` checks
  the ceiling at the full output budget before every attempt, records one usage receipt per answered call (`cost` from
  `usage.cost`, `null` when absent, `tokens_measured=False` when usage is missing), treats `finish_reason: "error"` and
  empty content as failures, tries the fallback of another vendor once, and sends no attribution header unless the
  operator's setting allows it (FAC-SEM-098).

## The recipe

`recipes/support-agent/`: a service on the kit that answers one inbound question. It looks the question up in a local
knowledge file, drafts a reply through `fabric_openrouter`, and accepts it only when code proves it: every cited entry
exists, no U+2014, the reply's script matches the question's. Otherwise it hands the question to a person (an event the
operator's channel reads). It is idempotent per message id, keeps a spend ceiling, and records usage receipts.

## Waves

1. API snapshot; L0/L1 core in both languages, every reader repointed; the layout, cycle and size tests (the size
   test carries an allowlist that only shrinks); `kit.json` and `fabric_kit.py`.
2. `fabric_service` split in both languages behind the facade.
3. The remaining oversize modules split; the allowlist emptied.
4. Connectors and the public date API.
5. The support-agent recipe.
6. Docs, wiki, release.
