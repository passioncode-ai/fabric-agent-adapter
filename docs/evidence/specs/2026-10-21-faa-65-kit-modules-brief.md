# Task brief: the kits as production modules (FAA-65)

- **Date:** 2026-10-21
- **Task (one line):** refactor the adapter's kits into cohesive, layered, installable modules (Python and Node twins)
  without breaking services that copy them, and add the building blocks the operator named: date helpers, connectors
  (HTTP, OpenRouter, the board) and a ready support-agent recipe.
- **Operator's words:** «рефакторинг наших китов готовых, best practice, подборки, готовый support agent, работа с
  датой, коннекторы ... проверим весь модуль, разные модули разделим, рефакторим всю систему, production grade».
- **UI verdict:** no. The kits are libraries and CLIs; the dashboard kit's look is not touched.
- **Risk class:** R3 (the kit's public API is copied into other services; a break reaches them). Full flow, not the
  short path: `short path: refused · R3 · >5 files · public contract`.
- **Model:** the most capable in this environment (Opus 5.5), inherited by every stage and subagent.
- **Run mode:** `loop: armed by ~/.claude/CLAUDE.md "Act, then report"`; outward acts under the standing release and
  PR authorization in the same file (section *Releases and pull requests*).

## Knowledge sources

| Source | What it says about this task | Fresh? | Authority | Stale after this run? |
|---|---|---|---|---|
| code: `building-fabric-services/scripts/` | 20,704 lines; `fabric_service.py` 3,454 (145 defs), `fabric-service.mjs` 2,541; natural seams are its `# ---` sections (paths, lock, ACLs, token, descriptor, well-known, protocols, events, usage, attribution, limits, feed, backups, logs, shutdown, login, supervisors) | 2026-10-21 | as-built | yes |
| import graph (measured with grep, no code graph) | cycles: `fabric_estate` and `fabric_delegation` import each other; `fabric_service` imports `fabric_estate` lazily while `fabric_hub` imports `fabric_service`; JS semantics (`_js_to_number`, `_js_string`, `_show`, `jcs`) live in estate and delegation, strict RFC 3339 in estate and again in the Node service | 2026-10-21 | as-built | yes |
| `building-fabric-services/SKILL.md:147` | "Copy the kit into the service (each is one self-contained file)" | 2026-10-21 | doc | **yes: false today**, `fabric_service.py` imports `fabric_estate`, `fabric_identifiers`, `fabric_secrets`; a one-file copy fails in `usage_findings` |
| `README.md:153`, `SKILL.md:18` | floors: Python 3.9+, Node 20+ (package.json `engines.node >=16` is the installer's) | current | convention | no |
| tests (`test/*.py`, `test/*.test.mjs`) | 132 distinct `fs.` names used, 2 private; 6 `patch.object` on `fs`; vectors held to the contract in `test/fixtures/` | current | as-built | no |
| `AGENTS.md` | stdlib only, non-destructive, twins in sync, leases on guarded files, docs in the same change | current | convention | no |
| `docs/backlog.md` | FAA-60, FAA-62, FAA-63 open; no row for this refactor (FAA-65 opened by this run) | 2026-10-21 | register | yes |
| `docs/evidence/retrospectives/` | dated retros; no standing-instruction file (`retro.md`) | 2026-10-19 | history | no |
| lessons: `scripts/lessons.py query` | local index absent | n/a | none | no |
| lessons: Observatory `observatory_search` (fresh server, kinds lesson) | abstained: 6 lexical matches below the coverage floor | 2026-10-21 | none | no |
| wiki `projects/fabric-agent-adapter/` | navigation card (created 2026-10-21) | 2026-10-21 | context | yes, at stage 9 |
| code graph (`graphify-out/`) | not built | n/a | none | no |
| `docs/DOCMAP.md` | absent | n/a | none | seeded at stage 9 |

Contradictions: SKILL.md's "one self-contained file" against the import graph (the code wins; the doc is fixed by REQ-05).

## Documentation

| Question | Answer |
|---|---|
| Regime | governed by `AGENTS.md`, `test/validate.py` and agent-sync leases since 2026-10-01 |
| Decision home | `docs/backlog.md` rows and dated handoffs (the repository has no ADR directory, `AGENTS.md`) |
| Doc map | `docs/DOCMAP.md` seeded at stage 9 from `AGENTS.md`'s "Where things live" |
| Gate | `python3 test/validate.py` (exit code) |
| Shared state | leases on `CHANGELOG.md`, `docs/backlog.md`, `fabric-contract.lock.json`, `docs/backlog-sources.json` |
| Entry audit (`setup`) | declined for this run: the doc surface was reviewed blind on 2026-10-21 (FAA-64, three rounds); recorded, not re-asked |

## Scope

- **In scope:** the Python and Node kits under `building-fabric-services/scripts/`, `fabric_session.py`, the probe, the
  kit's distribution (manifest, install, status), new modules for time, JS values, crypto, HTTP, OpenRouter, a
  support-agent recipe, their docs, and the release.
- **Out of scope:** any change in behaviour the contract's vectors observe; the dashboard kit's look; the contract pin.
- **Deferred (board rows at stage 10):** a data or analytics agent recipe (FAA-66); a Telegram connector (it is
  `telegram-dev`'s route); A2A (FAA-10).

## Decisions locked (the grill, closed by the operator's standing rule "an open question is a decision")

1. **Compatibility:** `fabric_service.py` / `fabric-service.mjs` and every other current module name stay importable
   with the 0.39.1 public API (names without a leading underscore) as facades. Why: services copied the kit; the
   cheapest safe migration is none. Private names may move; the two tests that use them follow.
2. **Distribution:** the kit is a versioned set of files, not one file: `kit.json` lists every module per language with
   its sha256 and its dependencies; `fabric_kit.py install|status` copies a module's closure into a service and tells
   an older or edited copy apart (the dashboard kit's proven pattern). Why: the one-file promise is already false.
3. **Layers** (each may import only from layers below): L0 `fabric_jsvalue`, `fabric_time`, `fabric_identifiers`,
   `fabric_secrets`; L1 `fabric_crypto`; L2 protocol readers (delegation, estate, share, ceremonies, package,
   profiles, usage rules, interop); L3 the service runtime modules; L4 connectors (HTTP, OpenRouter, hub, board); L5
   recipes and samples, the probe. Enforced by a test, not by convention.
4. **Module size:** no kit module above 1,000 lines after the split, enforced by a test; the 0.39.1 facades are thin.
5. **"работа с датой"** is read as dates (a public `fabric_time` API). A data-agent recipe is deferred (FAA-66),
   because the request names a support agent and not a data agent.
6. **Connectors:** stdlib only (`urllib`, `http.client`; Node `fetch`). Tests use an injected transport; no test opens
   the network or holds a key.
7. **Recipe:** one Python support agent under `building-fabric-services/recipes/support-agent/`, built only on the kit
   and its connectors, with tests. Node recipes are not asked for.
8. **Version:** 0.40.0 (minor: new modules and connectors; the facades keep 0.39.x callers working).

## Requirements

| REQ | Requirement | Verified by |
|---|---|---|
| REQ-01 | Shared core extracted once per language: `fabric_jsvalue` (JS value semantics), `fabric_time`, `fabric_crypto`; no second implementation of their functions remains | a layout test that fails when a core function is defined outside its home; the full suite and every contract vector |
| REQ-02 | `fabric_service` split into cohesive runtime modules; the facade exports every 0.39.1 public name | a public-API snapshot test per language (names at `v0.39.1` are a subset of names now) |
| REQ-03 | No import cycles; the layer table holds | a dependency test (Python AST, Node import scan) that fails on a planted cycle and a planted upward import |
| REQ-04 | No kit module above 1,000 lines (`fabric_board`, `fabric_estate`, `check_service`, `fabric_session` included) | a size test over every kit module |
| REQ-05 | Kit distribution: `kit.json` manifest with digests and dependencies; `fabric_kit.py install|status`; docs say how to copy | a test that installs `fabric_service`'s closure into an empty folder and runs it in a fresh interpreter (Python) and process (Node) with nothing else on the path |
| REQ-06 | HTTP connector: deadlines, bounded retries with backoff on 429/5xx/connection errors honouring `Retry-After`, retries only for idempotent requests or with an idempotency key, response size cap, no secret in a log line or URL | unit tests over a fake transport, both languages |
| REQ-07 | OpenRouter connector: key read from a named environment variable, the ceiling checked before every attempt at the full output budget, a usage receipt per call (provider cost, `null` when unknown, `tokens_measured=False` when usage is missing), a fallback of another vendor, an empty answer never returned as success, attribution off by default | unit tests over a fake transport, both languages |
| REQ-08 | Date helpers: public, documented `fabric_time` (strict RFC 3339, UTC day, N-day windows, an injectable clock) | unit tests plus the contract's estate and usage date cases |
| REQ-09 | Support-agent recipe: knowledge lookup, a drafted reply through the OpenRouter connector, code-proven checks (citations exist, no U+2014, the reply's language), handoff to a person when unsure, idempotent per message, spend ceiling, usage receipts | the recipe's own tests over a fake model |
| REQ-10 | Docs in the same change: SKILL.md files, references (module map, install, connectors, recipe), README, AGENTS.md, CHANGELOG 0.40.0, DOCMAP, handoff, wiki card | `python3 test/validate.py`; a doc check that every module in `kit.json` is documented |
| REQ-11 | Behaviour unchanged at every wave: every existing test and vector passes; the compiled-revision arms pass on real checkouts | `python3 -m unittest discover -s test`, `node --test 'test/*.test.mjs'`, the arms |
| REQ-12 | Released: 0.40.0, launcher, the local install byte-identical to the tag, board announcement naming the new file layout | release run, npm, `diff -r` against `git archive` |

## Finish line

Exit checks green on the released artefact and two consecutive verification rounds with nothing blocking (R3).

## Autonomy

- Tests: `python3 -m unittest discover -s test`, `node --test 'test/*.test.mjs'`, `python3 test/validate.py`, both
  `claude plugin validate --strict`. CI: `validate.yml` is dispatched by hand on the PR head (workflow_dispatch only).
- Branch: `agent/faa-65-kit-modules`; integrate by merge commit after CI on the exact head, as the history shows.
- Release: tag `v0.40.0`, release run, npm; launcher `passioncode` pin and release; local install byte check.
- Deploy target: none beyond npm and GitHub releases.
- Board: announce on the adapter's thread `67c3a5e0`.

## Open assumptions / risks

- A service that imported a private name from the kit breaks; mitigated by keeping every module name and its public
  API, and said in the changelog.
- Splitting the Node twin moves `export` statements; a re-export facade keeps named imports working.

## Stage 1: contracts grounded on fetched docs

OpenRouter, read 2026-10-21 through context7 (`/llmstxt/openrouter_ai_llms_txt`, pages api_reference/overview,
errors-and-debugging, guides/best-practices/reasoning-tokens):
- a non-streaming response always carries `usage` (`prompt_tokens`, `completion_tokens`, optional
  `prompt_tokens_details.cached_tokens`, `cache_write_tokens`, `completion_tokens_details.reasoning_tokens`, `cost`);
- an error is `{error: {code, message, metadata}}`; a 200 may still carry `choices[].finish_reason: "error"` with
  `choices[].error`, which is a failure, not an answer;
- 429, 503 and 402 may carry `Retry-After` (seconds);
- reasoning shares `max_tokens`: a too small budget returns `finish_reason: "length"` with empty content, still billed.
Python stdlib (`urllib.request`, `http.client`, `socket.timeout`) and Node 20 `fetch` with `AbortSignal.timeout` are the
transports; both are in the floors the README states.

## Amendment 2026-10-21 (build)

The layer table above puts `fabric_profiles` and `fabric_interop` at L2; they import the service modules, so they sit
at L3 in `kit.json` and `references/kit-modules.md`, which are the source of truth for layers.
