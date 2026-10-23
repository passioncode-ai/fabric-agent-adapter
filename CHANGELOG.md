# Changelog

## 0.45.1 (2026-10-23)

### Changed

- **`working-with-fabric` teaches *When nobody answers*** (FAA-99, the operator's rule of 2026-10-22, board thread
  `c97280b0`): after a `com.submit`, check whether the owner is live; if nobody is and the change is small, make it in
  the owner's repository by its AGENTS.md and reply *adapted by* with the merge commit; otherwise the request stays
  queued. Live means an `active` responder in `com.directory`, a live claim or an agent-sync lease; a `held`
  capability is the operator's stop. Small means all three of the operator's tests, one such change per repository at a
  time, and the *adapted by* reply names what the owner should look at.
- **The target Project's reply answers a request** (DEC-0102): the skill no longer tells an agent to reply "it stays queued",
  which under the contract ends the queue; it replies only when the reply is the answer, else leaves the request for a
  responder. A request waits until its deadline (seven days by default) and then reads `expired`; the owner's side
  reviews an *adapted by* change and answers the request; holds are described as the contract defines them.
- **It reads the board as DEC-0098 and DEC-0102 serve it:** `com.list` `unread` and `since` with each message's `read`,
  `com.read_ack` of one message, a list or a thread with `upTo` and the bulk counts, `noResponder` on a request's
  receipt, `answered` (the target replied; not a completion), and the typed `reaction` the contract defines for a reply
  to an announcement (not served by Fabric 0.3.10, so the reply's first word stays the type).
- `com.reply`, `com.cancel`, responder enrollment and the project directory are described as served by installed
  Fabric releases (Fabric 0.3.10 lists them), with the fallback for an older Fabric; "Not yet available" is gone.
- Seven scenario evals (six new, one rewritten for `com.reply`) and four trigger queries come first, as AGENTS.md asks.

## 0.45.0 (2026-10-22)

### Changed

- **Pinned to contract `e742016`** (FAA-100; `bfa9a67` stays supported): DEC-0098 to DEC-0103. Every vendored vector
  is regenerated from the contract's own functions at the pin.
- **The board kit reads the board as Fabric 0.3.9 serves it** (DEC-0098, DEC-0102), both twins: a request may be
  `answered` (the target Project's participant message answered it; a responder's fenced reply never does), a bulk
  `com.read_ack` receipt carries `marked`, `alreadyRead` and `more`, and a request's `com.submit` receipt may carry
  `noResponder` (nobody can answer that capability now; the request is stored). Each is refused outside the call that
  answers it. A responder that restarts and finds a request `answered` drops it from its checkpoint: the request is
  no longer its own (found by the blind reading; it stayed there for good).
- **`peer.custody` admits `processor-hosted`** (DEC-0099): an organization's cloud a processor runs under a processing
  agreement. Both descriptor checks and `references/protocol.md`.
- **The protocol register gains `node-summary/1`, `repair-request/1` and `repair-result/1`** (DEC-0101), both twins.
- The kit's `share-registration.schema.json` carries the refusal code `purpose-not-collected` (DEC-0100).

## 0.44.2 (2026-10-22)

### Fixed

- **The consumed-approval file is written with the kit's private writer** (FAA-85). `FileJtiStore` in both twins
  opened its file with a plain 0600 mode and set no Windows ACL, so on Windows its privacy rested on its folder alone,
  and a write that failed left its temporary file behind. It now writes through `fabric_paths.atomic_write` /
  `atomicWrite`: a protected owner-only ACL before the bytes on Windows (DEC-0032), 0600 elsewhere, fsynced and renamed
  into place, nothing left on failure. The file holds consumed approval ids, not a secret.
- **The kit's private writer removes its temporary file whatever fails, and reports the error that caused it**
  (FAA-85, found by the blind readings). Node `atomicWrite` cleaned up only when chmod or the rename failed; a failure
  while setting the Windows ACL, writing or syncing left `.<name>.<pid>.<hex>` beside the real file. Python
  `atomic_write` set the Windows ACL before it wrapped the file's handle, so when that step failed the handle stayed
  open, Windows could not delete the file, and the delete's error replaced the ACL's. Both now close the file on every
  path, remove it, and raise the original error even when the removal fails.

### Changed

- `fabric_base`, `fabric_platform` and `fabric_paths` (and their Node twins) move from layer L3 to L1 in `kit.json`, so
  the L2 modules may use them: their code and names are unchanged. `fabric_delegation` now imports `fabric_paths`, so
  a service that copies `fabric_delegation` by hand copies `fabric_base`, `fabric_platform` and `fabric_paths` too
  (`fabric_kit.py install` and `status` name them).

## 0.44.1 (2026-10-22)

### Changed

- **Two kit modules split by responsibility** (FAA-92). `fabric_interop` and `fabric_package` stood at the 1000-line
  ceiling `test_fabric_kit` enforces. The rules of `fabric-interop/0.1` that need no running service (constants,
  `InteropError`, `UnknownJob`, trace context, the job limits of DEC-0087) moved to `fabric_interop_rules` /
  `fabric-interop-rules.mjs` (L3), and the reading of `fabric-package.schema.json` to `fabric_package_schema` /
  `fabric-package-schema.mjs` (L2), which now carries that schema as its data. `fabric_interop` and `fabric_package`
  re-export every name they had, in both languages, so no caller changes; a service that copies the kit by hand
  copies the two new files too (`fabric_kit.py install` and `status` name them). No behaviour changed.

### Fixed

- A board test (`test_a_revision_conflict_on_renew_reads_again_and_keeps_the_attempt`) read the call order before its
  handler's thread had started its effect, and failed under load. It now waits for the effect to start.

## 0.44.0 (2026-10-22)

### Added

- **What an agent uses, `fabric-connections/0.1`** (FAA-62, contract DEC-0096, FAC-SEM-127; asked by Fabric Dashboards
  on board thread `131648c0`). A new kit module in both twins, `fabric_connections` / `fabric-connections.mjs`:
  `connections_extension(declared, degraded, states)` / `connectionsExtension(declared, {degraded, states})` builds
  the `extensions` entry, each connection's `state` from the service's own checks, else `degraded` when `degraded[]`
  names it, else `unknown`, and refuses a declaration a host would hide (the schema, an id twice, a credential).
  `connections_view` / `connectionsView` read a peer's list as the contract's reference does; both answer all 127
  cases of the contract's `fixtures/vectors/connections.json`, vendored by `make_connections_vectors.mjs`.
  `build_well_known` / `buildWellKnown` refuse an invalid declaration passed in by hand, `check_service.py` reports
  `well-known.connections`, and the `fabric_service` facades re-export the four names. The Python twin reads
  credentials with the reference's ECMAScript semantics (ASCII case folding and word boundary, ECMAScript's whitespace,
  a URL WHATWG refuses read as text only, its query and fragment read as WHATWG serializes them, a name's leading
  `?` dropped as `URLSearchParams` drops it, an unpaired surrogate read as U+FFFD); 1,073 more inputs, answered by the
  contract's reader into `connections-extra-vectors.json`, hold both twins to it. Inputs whose answer changes with the
  Node release (the reference parses URLs with the runtime's own `new URL`) are left out of that set. Where Python cannot tell whether WHATWG refuses a URL (a
  non-ASCII host), it reads the URL's credentials anyway, so a doubt hides a declaration rather than publish one
  (FAA-98 ports UTS46 to close that gap).

### Changed

- **`check_dashboard_layout.mjs` exits 3 when no rule was measured** (FAA-96): every rule `NOT_RUN` (no Playwright, a
  browser that does not start, a service it cannot open) or no rule at all. It exited 0, and 2 for an empty report
  since 0.42.1. 0 still needs at least one rule measured and none failing.

### Fixed

- **The session worker waits for an exit status to its deadline after a closed pipe** (FAA-97): a `fabric-mcp` that
  closed its stdin and exited 3 more than a second later was logged as `outcome=unknown` and its spool kept.
- **OpenClaw `--remove` drops our load path when its folder is gone** (FAA-90): the ownership check read a manifest
  that no longer existed, so the dead path stayed.

## 0.43.0 (2026-10-22)

### Changed

- **Pinned to contract `bfa9a67`** (FAA-95; the contract review, PR #137 and #138, DEC-0096 and DEC-0097). `c55f2d5`
  (0.39.0 to 0.42.1) joins the supported revisions. Every vendored vector was regenerated from the contract's own
  functions at the pin: new negative package fixtures, a `comms-complete` case and `fabric-connections` in the register.
- **A delegation chain names a partner only for a partner actor** (contract `src/delegation.ts` at `bfa9a67`): an actor
  that carries `partner` beside `sub` is named by its `sub` in the verified `chain`, in both kits.
- **`fabric-connections/0.1` is in both protocol registers** (DEC-0096), so a `protocols` list naming it is read as
  the contract reads it. The kits do not emit the extension yet (FAA-62).
- **The provider schema's MCP branches are read as `if`/`then`/`else`** (the contract review): the schema parity test
  takes the URL pattern from `else` (a `oneOf` before); the pattern itself is unchanged. No kit code walked that `oneOf`.

### Fixed

- **The kit's copy of `fabric-package.schema.json` carries DEC-0097's path pattern.** ECMAScript's `.` stops at U+2028
  and U+2029, so the old pattern accepted `skills<U+2028>/../../etc/passwd`; any character is now `[\s\S]`. Both kits'
  own package checks already refused these paths (0.41.0). `share-registration.schema.json` is regenerated at the pin.
- **The settings backup's secret-name patterns follow DEC-0097** in both kits (`[\s\S]+_` for `.+_`); no input reached
  the difference, since table and column names refuse a line break first. A contract-gated test holds each twin's
  regex to the pinned schema's pattern.
- **A guard holds the kit's vendored schemas to the pin:** `test_the_kit_schemas_carry_the_patterns_of_the_pinned_contract`
  fails when a pattern in either copy is not a pattern of that schema's `$ref` closure at the pinned contract.

## 0.42.1 (2026-10-22)

The first published release of the 0.42 line: everything in 0.42.0 below, plus one test fix.

### Fixed

- **`test/entry-points.test.mjs` on Windows.** The test that a layout report with no rule exits 2 imported the script
  by its path; Windows reads `D:\...` in an import as a URL with the scheme `d:`. It imports a file URL now. The tag
  `v0.42.0` stays as it was: its release run ([39771949538](https://github.com/passioncode-ai/fabric-agent-adapter/actions/runs/39771949538))
  stopped at this test on the Windows job, so 0.42.0 was never published to npm or as a GitHub release.

## 0.42.0 (2026-10-22, tagged, not published)

The open asks of the Fabric project board, closed ([brief](docs/evidence/specs/2026-10-22-board-asks-0.42.0-brief.md)).

### Changed

- **Session hooks follow Fabric 0.3.9** (board thread `02bf19c5`, FAA-93; Fabric's tracking audit TR-1, TR-2, TR-11).
  The session-wide release carries `observedAt`, the time the end hook fired, where the release tool's input schema
  names it, so Fabric refuses an end from before the session enrolled (`stale-end`). A `SessionEnd` with reason
  `clear` releases nothing and observes no end: `/clear` keeps the agent process and its fabric-mcp; turns already
  spooled still go out. An end followed by a later turn of the same session id is dropped with a log line instead of
  being delivered to a resumed process (`claude --resume` keeps the id), which closes FAA-83. When
  `fabric-mcp --rejoin-only` exits 3 (no session holds the id), the worker drops the spool, marks the folder and logs
  it once; for 15 minutes the hooks spool nothing for that id, then one rejoin tries again.

### Fixed

- **Kit scripts started through a symlinked folder ran nothing** (board thread `b42e16b7`, FAA-94).
  `check_dashboard_layout.mjs` and `fabric-package.mjs` compared `import.meta.url` (resolved) with `process.argv[1]`
  (the link), so under the launcher's `~/.passioncode/current` a layout check printed nothing and exited 0. Both
  compare real paths now, and a layout report with no rule in it exits 2.
- **The kit history guard runs in hosted CI** (FAA-82). The `python` job checks out the full history with tags and sets
  `FABRIC_REQUIRE_RELEASE_TAGS=1`, under which `test_a_released_version_keeps_its_digests` fails instead of skipping
  when no release tag is present.

## 0.41.0 (2026-10-22)

The 2026-10-22 audit, closed (FAA-68 to FAA-81; [report](docs/reports/2026-10-22-adapter-audit/README.md),
[brief](docs/evidence/specs/2026-10-22-audit-fixes-brief.md)). Its 53 findings fell into six classes; each class got
its fixes and a guard that fails the next instance. Each fix has a test; the builders' reports and the commit
messages name the ones seen failing before the fix. Three blind readings (unit, seam, product) certified the result
and their findings are fixed here too.

### Fixed

- **Session hooks and the delivery worker** (FAA-68). One JSON-RPC error or unreadable spool entry no longer blocks
  a session's spool for good: the entry is logged by its code and dropped, and the end, the claim release and the end
  observation still go out. `fabric-mcp` runs in its own process group and the whole group is ended at the deadline,
  so a wrapper (`npx`, a shell script, `fabric-mcp.cmd`) cannot hold the worker for a minute. A process walk that
  cannot read the processes spools nothing and releases nothing; a launched session is remembered. Turn facts are
  measured when the turn ends (counts only). watch-mail keeps its delay between 10 s and 15 min after the jitter and
  honours the once-a-minute rejoin mark. Stale spool folders are pruned even while the hooks are inert; a stale
  worker lock is taken by an atomic rename, and its identity includes the write time and size (Linux reuses a freed
  inode number at once). An end whose release got no answer stays for the next worker. On Windows a bare `fabric-mcp`
  resolves to `fabric-mcp.cmd`.
- **Host installers and the dashboard notice** (FAA-69). The SessionStart notice asks whether the repository owns a
  service before it reads the tree, all within one 3.5 s budget. The Kimi installer repairs or removes a stale script
  path; Kimi and Codex require the script to exist; Hermes `--remove` works without the source folder; the OpenCode
  and OpenClaw bridges run the helper once per workspace, not per request, and never keep a failed run.
- **The service kit's Python twin** (FAA-70). `launchd_plist` refuses what the Node twin refuses: a secret-shaped
  argument or environment value, a bad label, an empty argv, an `ExitTimeOut` under the drain. `JobStore` and the
  event log hold a lock per store path (one idempotency key made two jobs; a cancelled job became completed; 41 of
  160 events were kept). `pause` checks for a terminal job first (both twins). The JWKS fetch has one 5 s deadline,
  runs outside the cache lock and turns a garbage answer into `issuer-unavailable`. Whole-value patterns end in
  `\Z`, so a trailing newline no longer validates. An origin written with its default port is accepted as Node
  accepts it. A socket timeout is a timeout on Python 3.9. Non-object MCP params answer -32602. systemd
  `Environment=` no longer doubles `$`. The sample service answers 400 to a bad `Content-Length` or body.
- **The board responder** (FAA-77). A lost reply answer no longer leaves a request `accepted` for good: a transfer
  re-derives the per-attempt keys after re-sending the old reply under its old key, and `idempotency_conflict` is its
  own `board.blocked` event. One fenced call per entry at a time, and a `revision_conflict` on renew re-reads the
  revision. An effect lost while the session holds the slot is observed and completed, or its slot is replaced so the
  board records `outcome_unknown`. One lost answer keeps the session while the lease holds. Every transferred request
  resumes, and a transfer survives a second lost answer (the request completes with one reply). The session's link
  (MCP session, checkpoint, request) is its own module, `fabric_board_link` / `fabric-board-link.mjs`.
- **Interop job keys** (FAA-70, FAA-77). A key admits only the intent it was first used for: another capability or
  input is `idempotency-conflict` in `create` and `conflict` in `repeat`, which now takes the intent. A key file
  written before 0.41.0 is answered with its job, and runs again only for the intent its job stored.
- **Package, delegation and estate twins** (FAA-78). Both kits refuse a package path holding a control character,
  U+2028 or U+2029, whatever the schema's pattern lets through (the contract owner was told). An unreadable folder
  entry is refused instead of skipped (Python) or crashing (Node). Files are opened without following links. Node
  reads JSON as strict UTF-8 and keeps a top-level `__proto__`; both cap nesting at 256 levels; dates take ASCII
  digits. An explicit `null` estate, applied mark or revocation list fails closed in both kits. JWKS `x` must be
  canonical base64url in both. Python Ed25519 signing is a Montgomery ladder that does not branch on the key. The
  hub's loopback origin takes ASCII digits only. On Windows, `fabric.package.json` is written with `\n` like the Node
  kit's, and the command line answers in UTF-8 whatever the console's code page.
- **The adapting skill's scripts** (FAA-71). `fabric_provider.py write` refuses what the pinned provider schema
  refuses (ports under 100, a non-URI repository, an argument over 1024 characters), refuses `--env` with `--url`
  and a writer option after `--stdio`. `check` names every template value still present and keeps
  `readyForAdmission` false; `check --contract` calls the checkout's own `tsx`, never `pnpm exec`; a client
  `.mcp.json` is not an MCP surface; a non-UTF-8 manifest is a typed receipt. `scaffold --dry-run` prints the writes
  and a diff of each collision.
- **Dashboard probes and the link gate** (FAA-79). The layout probe never prints a login code (it starts the browser
  before asking for one); ED-3 checks vertical clipping; ED-4 says NOT_RUN past its element cap. The handoff-link
  gate normalises the path and refuses `code`, `api_key` and the other credential names. The "Get Fabric" menu link is
  reachable by keyboard; the dashboard kit is 1.1.2.
- **Installers** (FAA-80). `install.sh` leaves an existing copy alone without `--force` and never copies
  `__pycache__`; both installers build a new copy beside the old and rename it, report each failure and exit 1.
- **The support-agent recipe** (FAA-81). A reply carrying a link (bare host names included), address, phone number,
  amount or number its cited entries do not contain goes to a person; links and addresses are compared by equality,
  never as substrings; the customer's message reaches the model as fenced data. A promise written in words is not
  caught, and the README says so. Decisions are an
  append-only log; `prune --keep-days N` deletes old rows; the README says the outbox keeps customer text.

### Changed

- **CI follows the organization's rule** (FAA-72). `validate.yml` runs nightly on `main` and on dispatch, with job
  timeouts and a concurrency group; a `contract` job installs the contract at the pin and at the legacy revision and
  runs the tests that used to skip (one of them had rotted); a `floors` job runs Python 3.9 and Node 18; a `macos` job
  runs both suites; Windows runs the session tests and the whole Node suite (16 tests that assumed POSIX now check
  the Windows ACL or say why they skip). `engines.node` is `>=18` (the npm CLI); the Node service kit needs 20, and on
  Linux its instance lock needs 22: Node 18 and early 20 collapse every abstract socket name into one, and later 20
  pads it so no Python copy or probe sees it, so the kit refuses to start there with a sentence naming Node 22.
- **The release path** (FAA-73). The tarball smoke test runs before the GitHub release is created; every action is
  pinned to a commit SHA; npm and the Claude Code CLI are pinned; release titles carry no em dash; the dead
  private-repository branch is gone. Moving npm publishing to trusted publishing (and removing `NPM_TOKEN`) waits on
  the operator's npmjs.com sign-in.
- **Skills and documents** (FAA-74, FAA-75). SECURITY.md and SKILL-CARD say what the probe and the kit really reach
  and write; the `vault.py moved` command is correct; the secret tools have a path and a fallback; each skill's
  NOT-for list names its siblings; shared blocks live in one reference; the building skill's description is 799
  characters. `test/evals/run_evals.py` runs the trigger evals against a real client when asked; its first run scored
  25/25 on `adapting-projects-to-fabric`.

### Guards (each fails on a planted defect)

- `validate.py` refuses a `$`-anchored whole-value pattern in every skill's scripts (R1; it found a real one in
  `adapt_project`'s cost preset id), an em dash under
  `.github/` (R6), and a workflow that floats an action, uses `@latest`, lacks a timeout, drops the nightly or gated
  jobs, gains a push or PR trigger, or creates the release before the smoke test (R5).
- Shared hostile-input fixtures run by both twins: `kit-hostile-inputs-core.json`, `kit-hostile-inputs-package.json`,
  `kit-hostile-inputs-estate.json` (R1).
- Fault-injection tests for the spool, the worker, the responder and the package walk (R2); concurrency tests for every
  store a threaded server reaches (R3).
- `test_a_released_version_keeps_its_digests`: a release's `kit.json` history entry stays what the release shipped (a
  build before the version moved on had rewritten 0.40.0's, which would have read genuine 0.40.0 copies as modified).
  It runs in a clone that has the release tags (a full local clone); the shallow hosted checkout skips it (FAA-82).
- Two timing tests no longer fail on a loaded host: the runner probe's positive cases take the most a probe may take,
  and the interop probe test lets the machine-timing verdict be the one that fails.

### Upgrading

- **A service built on the copied kit:** `fabric_kit.py status <dir>` names the modules to update; `fabric_kit.py install
  <dir>` brings the closure, `fabric_board_link` included. Passing `estate=None` (or `estate_applied=None`,
  `estate_revocations=None`) on purpose now refuses every token as `estate-unreadable`: leave the option out instead.
- **A Linux service on the Node kit:** run it on Node 22 or later; on 18 or 20 it stops at start with a sentence saying so.
- **A scaffolded bundle:** new scaffolds write a `urn:fabric:adapter:template` block into `fabric-agent.json` and take
  `--data-class`, `--created-by`, `--identity-method` and `--probe-assertion`. Rerun `check`: an older bundle that still
  holds the template's author, schemas or assertions now reads `readyForAdmission: false` until they are replaced.
- **A dashboard on kit 1.1.1:** the SessionStart notice now points at 1.1.2; `dashboard_kit.py install` updates it.
- **The support recipe:** its state moves to `decisions.jsonl` (an old `decisions.json` is still read); handoff rows gain
  `question` and `at`, and new reasons `unsupported:url|email|phone|amount|number`. Run `prune --keep-days N` once, then
  delete `decisions.json`.
- **Links you hand out:** the gate now refuses a query or fragment name such as `code`, `key`, `auth` or `api_key`, and
  a path with a dot segment or an encoded separator.
- **Installing:** a copy already in the hub is kept unless `--force` (both installers); the npm installer reports each
  skill `up to date`, `differs` or installed, and never copies Python bytecode.
- **Open human step:** moving npm publishing to trusted publishing and deleting `NPM_TOKEN` needs the operator's
  npmjs.com sign-in.


## 0.40.0 - 2026-10-21

The kits as production modules (FAA-65). Every name a kit module made public at 0.39.1 is still there; a service that
copies the kit now installs it with `fabric_kit.py install` (one file is no longer enough, see below).

### Added

- **A shared core, once per language** (layer L0 and L1): `fabric_jsvalue` / `fabric-jsvalue.mjs` (JavaScript's view
  of JSON values: `show`, `js_to_number`, `same`, `json_equal`, `jcs` and the rest), `fabric_time` / `fabric-time.mjs`
  (strict RFC 3339, UTC days, formatting, day windows, an injectable clock: the public dates API, on shared cases) and
  `fabric_crypto` / `fabric-crypto.mjs` (Ed25519 and P-256 checks, small-order keys, base64url, sha256). They used to
  live, twice, inside the estate and delegation readers; every reader now imports them.
- **The kit is a manifest-listed set, installable as one.** `kit.json` lists every module in dependency order, with the
  kit modules it imports, its sha256 and the sha256 of every release since 0.8.0. `fabric_kit.py install <dir>`
  copies a module's closure (data files included); `status <dir>` says `current`, `older` (with its release) or
  `modified`, and names a module a copy imports but lacks. SKILL.md said the kit was "one self-contained file"; it was
  not, and a one-file copy of `fabric_service.py` failed in `usage_findings`.
- **Connectors** (layer L4, both languages, shared cases): `fabric_http` (one deadline across attempts, bounded
  retries with jittered backoff only when repeating is safe, `Retry-After` up to a cap, a response size cap, redirects
  answered and never followed, plain http refused off loopback, redacted URLs in errors) and `fabric_openrouter` (the
  agent's own key from a named environment variable, a spend ceiling checked before every attempt at the worst case
  with calls in flight reserved, one usage receipt per answered call, empty, `length`, `error` and filtered answers
  never returned as success, a fallback of another vendor required, 401/402/403 stop at once, attribution off by
  default). References: `kit-modules.md`, `connectors.md`.
- **A support-agent recipe** (`building-fabric-services/recipes/support-agent/`): answers a question from a knowledge
  file through `fabric_openrouter`, accepts a reply only when code proves it (citations exist and were given, no em
  dash or substitute, the question's script, a length limit), otherwise hands it to a person with the failed checks
  named; idempotent per message id. `test/validate.py` lets a recipe import the kit modules `kit.json` lists.
- **Layering held by tests**: a module imports only modules listed before it (a planted cycle is caught), none is over
  1000 lines across every skill's scripts, the core is defined once, every module is in the module map, and the
  0.39.1 public API of both facades is a snapshot test.

### Changed

- `fabric_service` / `fabric-service.mjs` and `fabric_board` / `fabric-board.mjs` are facades over modules split by
  responsibility (base, platform, paths, protocols, lock, usage, backups, descriptor, auth, events, logs, supervisors;
  board shapes, session, fixture). The probe's rules moved to `check_service_rules.py`. In working-with-fabric,
  `fabric_session.py` is a facade over `fabric_session_{env,mcp,mail,hosts,cli}.py`; the hooks, the worker and
  `install-host-hooks` still run the facade.
- No import cycle is left: `fabric_estate` no longer imports `fabric_delegation`, in both languages.
- A Node service that imported a module-private helper of `fabric-service.mjs` or `fabric-board.mjs` (not exported at
  0.39.1, so outside the snapshot) imports it from the module that holds it now.
- The probe runs the board responder's self-check in a clean Python (`-E -s`, its own working directory), so it reads
  the kit it names and not a copy already imported.

### Fixed

- **Found by the release review (three blind readings) and fixed before release:** the OpenRouter ceiling counted
  only the messages, so a large `tools` list could pass it (the worst case now bounds the messages and every param;
  `models`, `route`, `plugins` and `web_search_options` are refused); an attempt that may have been billed without an
  answer to read (a timeout, a 200 over the size cap or not JSON) left no receipt (it now records one with no tokens
  and no cost, counted at the worst case); the Python transport could overrun its deadline on a slowly trickled body
  (it reads in chunks against one deadline); the twins differed on a lone surrogate, NaN in a body, a transport bug and
  `http://127.1` (both now behave the same, on shared cases); `fabric_service.py` could not be loaded by its path from
  another folder (every kit module now puts its own folder on `sys.path`, tested from `/`); `fabric_kit.py status`
  judged an older copy by the current release's imports and named only direct ones (it now reads each copy's own
  imports and follows the closure); an unknown `--module` is a usage error (exit 2); the facade keeps `_number`,
  `_DAY_MS` and `_utc_date_ms`; `install-host-hooks` requires the session helper's new modules; the recipe hands off a
  message holding bytes a terminal could not decode instead of exiting, and its dash check also catches U+2012 and
  U+2015.
- **Found by the second review round and fixed:** a connection cut after a call may have been billed left no receipt
  (every connection error now records an unmeasured one); `max_completion_tokens` and `n` could raise the output past
  the bound (refused); an unmeasured call was counted at the current call's worst case (now at its own, while the
  client runs); Node read a blank or hex price as a number (both twins now read a plain decimal or a number only);
  Python's deadline started after the headers (it now covers them); `fabric_kit.py status` raised on a copy it could
  not parse (it reports it `modified`) and now names a missing module's data files; `fabric_http` writes a JSON body
  byte for byte as `JSON.stringify` (numbers and key order too, through the core's `json_stringify`); loopback edge
  forms agree in both twins; the recipe's dash check covers U+2E3A, U+2E3B, U+FE58 and no-break spaces, and no longer
  flags `1 - 2`.
- **Found by the third review round and fixed:** an answer with no usage was counted at the next call's worst case
  (now at its own); image, audio and file parts could be sent past the bound (only text content is sent); Python
  raised outside `OpenRouterError` and kept no receipt on a 400-digit count or cost or JSON nested too deep (both read
  as unmeasured now); Python's deadline could be held by trickled headers (a watchdog shuts the socket at the
  deadline); `Response.json()` reads a byte order mark and refuses `NaN` as `JSON.parse` does; a `Retry-After` year
  before 1000 is no date in either twin.
- **A usage receipt's project id is checked the same way in both kits.** `fabric_service.py` defined its URI pattern
  twice and the second won: Python accepted `project_id="urn:"` where Node refused it. Now one pattern per module, and
  both kits refuse it (a test in each).

## 0.39.1 - 2026-10-21

Fixes from two rounds of blind review of 0.39.0 (FAA-64).

### Fixed

- **The probe no longer crashes on a usage report it is checking.** `check_service.py` compared `unpricedCalls` and
  `unmeasuredCalls` raw, so `null` or a string raised `TypeError`, and a 400-digit cost raised `OverflowError`; either
  stopped the whole probe before its other rules ran. Its FAC-SEM-025 arithmetic is now the kit's `usage_findings`, one
  implementation held to the contract's vectors.
- **The Python and Node kits answer FAC-SEM-025 as the contract does, message for message.** Both read each count as
  the contract's `toNumber(x ?? 0)`, each date and project id with `show`, a cost as JavaScript holds the number (an
  integer beyond a double is Infinity, which is never close to a sum), and a whole number written `5.0` as a count.
  Python compared raw values and read `5.0` as 0; Node threw on an object such as `{"toString": 1}` in a count, a date
  or a project id. The vectors now carry each finding's message and both kits compare it: 183 new report cases (208)
  set every count and the cost of a day and of its first model to eleven values the schema refuses, plus three days
  with no model rows and four dates and ids that are objects or numbers; eight new cases are the report's JSON text,
  which each kit parses itself (a 400-digit integer, `1e400`, `2^53 + 1`, `5.0`). The field list is the contract's at this pin,
  written in the generator.
- **Messages a person reads carry no em dash**: the probe, the dashboard-kit notice, the board's retry hint and the
  package refusal (Python and Node alike), the installer and the `npx` CLI, the sample service's page, the session
  hooks' unread and status lines (`2 unread on the project board: com.list`) and the dashboard kit's Fabric button
  (`Fabric is not installed. Get it at passioncode.ai/fabric`; kit **1.1.1**, so a service's kit copy is offered the
  upgrade). The live documentation, evals and the kit's demo page were rewritten the same way.

### Added

- Tests for the producer side of DEC-0091 in both kits: receipts with `tokens_measured=False` through
  `usage_report`, the day and model `unmeasuredCalls`, none on `byProject`, the probe clean, and the refusal of a
  non-boolean flag.
- Evals: the spend scenario expects unknown tokens in `unmeasuredCalls`; a new scenario covers a partner's package
  and calls (DEC-0090).
- `interop.md` and `usage.md` say a job whose usage is sent as `null` or `partial` is recorded with
  `tokens_measured=False`; `estate-record.md` says a service updates its copied kit before a revision carries
  `publisherScopes` (an older copy trusts a partner's key in every context); FAC-SEM-122 in its header and DEC-0091 in
  protocol.md's FAC-SEM-025 row.
- `test/validate.py` fails on U+2014 in the live documentation, the evals, the installer, the CLI and the kit's demo,
  and when README states which version a checkout is or which release is the latest (it said 0.21.0 until now); both
  checks have tests. The compiled-revision tests name the two contract revisions they need when they skip.

### Raised with the contract (not changed here)

- `chainOf` names a `{sub, partner}` node by its `org:` id, and job ownership and idempotency keys do not include the
  partner. The kits follow `c55f2d5` until the contract decides (board thread `6e66a023`, FAA-64).

## 0.39.0 - 2026-10-20

### Changed

- **Pinned to contract `c55f2d5`** (FAA-61; DEC-0089 to DEC-0095). `0704218` (0.36.0 to 0.38.0) joins the supported
  revisions. Every new vector is answered by the contract's own functions at the pin.

### Added

- **Unmeasured tokens are named** (DEC-0091, contract CT-62). `make_usage_receipt(..., tokens_measured=False)` /
  `makeUsageReceipt(..., { tokensMeasured: false })` writes `tokensMeasured: false`; the report counts such calls in
  `unmeasuredCalls` on the day and the model row, and FAC-SEM-025 in both kits and `check_service.py` refuses a row
  with more unmeasured calls than calls or a day whose count is not its models' sum. Four new usage vectors (25; this
  line said three until 0.39.1).
- **A partner in the delegation chain** (DEC-0090, contract CT-58). Both verifiers take `{partner: "org:<id>"}` as the
  innermost actor under at least one agent: it counts toward the depth limit and ends the chain, and the checked chain
  lists it by its `org:` id. Outermost, with an `act` beneath, `personal` or an `ORG:` prefix is `malformed-chain`.
  `is_partner_actor` / `isPartnerActor` are exported. Eight new delegation vectors (90) and thirteen `chainDepths`
  vectors held by both kits.
- **A partner's publisher key, per organization context** (DEC-0090, FAC-SEM-122). The estate kits read
  `publisherScopes[]`: `placement_trust` / `placementTrust` answer no key for a placement outside its key's scope, and
  `estate-record` and `estate-placement` flag a key scoped twice, a scope over a key `publisherKeys` does not pin, and a
  placement in a context its key's scope does not name. Seven new rule cases (137) and 45 placementTrust cases (64).
- **Protocol register at the pin**: `coding-agents/1` and `support-quality-daily/1` (DEC-0093, DEC-0095).

### Not here

- Minting a partner's token and its grant (FAC-SEM-124) are the issuer's; the kits verify, never mint.
- `partnerUsage` and FAC-SEM-123 (a partner's access-log reads) are the organization server's.
- DEC-0089 (folder attribution, FAC-SEM-121) and DEC-0092 (`fabric.project.resolve`) are Fabric's; DEC-0094 (a device
  key in a file, FAC-SEM-125) is the device's and its server's. No kit reads them.

## 0.38.0 - 2026-10-20

### Changed

- **Quieter session start** (FAA-59, the operator's audit of 2026-10-20). Measured on the operator's Mac (26 service
  descriptors, `fabric` registered at user scope): with Fabric running the SessionStart context fell from 1,243
  characters at every start, compact and resume to 893 at startup and `/clear` only; with Fabric down, from 678 in
  every repository to nothing in one that does not use Fabric and one 217-character line in one that does.
  - `fabric_session.py hook session-start` no longer adds the machine's Fabric-service count: the host's own
    instructions say how to read Fabric services. `services_line` and `SERVICES_NOTE` are gone.
  - Fabric down: one line, `skip fabric_whoami and the project board for now`, start Fabric through the lifecycle
    broker only if the task needs it, and only in a project that uses Fabric (`project_uses_fabric`): `fabric`
    registered at local or project scope, a `fabric-agent.json`, `fabric-contract.lock.json` or `fabric.package.json`
    from the folder up to its checkout's root, or a service descriptor whose `source.repository` is the checkout's
    origin. Before, every repository was told to start Fabric while the `fabric` MCP server said to call
    `fabric_whoami` first.
  - Both SessionStart hooks run on `startup|clear`, never on compact or resume; the session-start script also ignores
    `source: compact|resume` for every host.
  - `dashboard_kit.py notice` speaks only in a repository that owns a service (a descriptor names it as
    `source.repository`), names only that repository's services, and offers the upgrade as one the agent may make
    itself; it no longer says "tell the operator". `references/dashboard-kit.md` and its scenario eval say the same.

## 0.37.1 - 2026-10-20

### Added

- **The rest of contract DEC-0084 in both kits** (FAA-57), in `fabric_ceremonies.py` / `fabric-ceremonies.mjs`: the
  nearby pairing (`pairing_commit`, `check_reveal`, `comparison_code`, `checked_comparison_code`, `estate_fingerprint`,
  `rendezvous_verdict`, `join_listed`, `own_keys_decision`, `machine_of_keys`) held to the contract's `pairing.json`
  (116 cases in eight groups), and the hub's single use of a token (`redeem_enroll_token`, with the `enroll-join/1`
  proof as ES256 r and s low S or Ed25519) held to `enroll-token.json` group `redeem` and a high-S variant. 26 planted
  defects across both kits, all caught. `fabric-estate.mjs` exports `validDeviceKey`.

### Changed

- **`building-fabric-services` → remote placement:** which `installedBy` form an agent installer writes (the string
  form, or `{by: "person", role: "operator", tool}` when a person asked it), and that a TypeScript app must name its
  `.well-known` route folder in `tsconfig` `include`, which skips dot folders. Both reported by an agent that built a
  remote service in a Next.js app.

## 0.37.0 - 2026-10-19

### Added

- **`creating-fabric-agents` carries what the estate learned about building agents** (FAA-58, the operator's request
  of 2026-10-19): four new references every new agent starts from.
  - `where-agents-run.md`: this machine, a personal cloud, an organization, Enterprise; contexts (`personal`,
    `org:<id>`) with one instance per context and no secret, spend or journal crossing; connecting a machine (nearby
    code, headless enroll token); sharing an agent into an organization; running while the laptop is closed; selling
    an agent (a paid agent in its developer's organization, a partner's setup).
  - `models-and-providers.md`: lanes with a fallback of another vendor and an open-vendor model where users' content is
    read; a dated starting choice from the OpenRouter catalog; several kinds of input and output; budgets that survive
    reasoning; one OpenRouter key per agent and context with its ceiling, read from the environment; measuring a choice.
  - `orchestration-and-learning.md`: workflow first; the work graph of durable jobs with intent keys, effects observed,
    limits as pauses (DEC-0087); calling other agents within a narrower grant and budget; stops for a person; learning
    loops (decisions with reasons, one trace per turn, failures as planted fixtures first, history replayed, learnings
    proposed and never self-approved); the loop guard.
  - `practices.md`: the rules production agents taught us, each with its check: judges and evals, numbers, money,
    people in the loop, reliability, shipping.
- The intake grill asks **Where does it run, for whom?**, **Which models?**, **Who pays?** and **How does it learn?**;
  the knowledge intake links the four references. `test/validate.py` holds the rows, the links and each reference's
  checklist (`KnowledgePackTests`); eval scenario `agent-for-a-personal-and-an-organization-cloud`; three trigger
  queries.

## 0.36.0 - 2026-10-19

Repinned to Fabric Agent Contract `07042181bfae2a481aa0da1a5651f24c76669c48` (DEC-0084 to DEC-0088); `d8146cf` stays
supported, so bundles issued under it stay valid. DEC-0085 and DEC-0088 (entitlements) are the platform's and the
organization server's, not the kits'.

### Added

- **Jobs under limits and uncertain effects, in both interop kits** (FAA-56, contract DEC-0087, FAC-SEM-119/120): a job a
  limit paused stays `working` with `quota-exhausted until <instant>` (`jobs.pause`); a job a limit stopped ends
  `quota-exhausted` with `data: {retryable, resetsAt?}` (`jobs.quota_exhausted`); an effect nobody saw ends
  `outcome-unknown` (`jobs.outcome_unknown`). Idempotency keys are kept per authenticated caller and a repeated key is
  answered by its job (`jobs.repeat`): a limited job runs again once the limit no longer holds, an `outcome-unknown` one
  never. Usage nobody measured is `null` only toward a caller that names `fabric-interop/0.2` (`usage_toward`). As a
  caller: `request_meta`, `job_caller_action`, `intent_idempotency_key`. Held to the contract's `job-limits.json`.
- **Share grants into an organization** (contract DEC-0086): new `fabric_share.py` / `fabric-share.mjs` with FAC-SEM-117
  (a share grant id, a millisecond window, one agentRef kept against the parent revision), FAC-SEM-118 (a
  `share-registration/1` document) and FAC-SEM-045's `grant.usage` context clause; `share-registration.schema.json`
  vendored self-contained.
- **The estate ceremonies** (contract DEC-0084): in both estate kits FAC-SEM-114 (what a revision drops it revokes in the
  same revision), FAC-SEM-073 (a device key in canonical base64), FAC-SEM-076 (a key reference
  `<kid>@sha256:<hex>`), `device_key_fingerprint`, `device_key_ref`, and `verify_estate_record(..., parent=)` runs
  FAC-SEM-114. New `fabric_ceremonies.py` / `fabric-ceremonies.mjs`: `verify_enroll_token`, `enroll_join_input`,
  FAC-SEM-113. Pairing and the hub's single use of a token follow in FAA-57.
- **A partner's setup for a company** (FAA-55, the partner channel's PA-07): documented and tested as an org skill set
  whose `requires.packages` names the agents, every package signed with the partner's key. No new format.

### Changed

- **FAC-SEM-034** in both profile kits compares the probes before it builds a list and names at most 64 candidates, so a
  huge index allocates nothing (the contract's fix of this repository's report).
- **The protocol register** in both service kits matches the contract's: `enroll-token`, `entitlement`,
  `entitlement-key-set`, `pairing-message`, `share-registration`, `share-registration-receipt`, and `fabric-interop/0.2`.

## 0.35.4 - 2026-10-19

### Changed

- **The session hooks rejoin a session at most once a minute** (FAA-53). Every `fabric-mcp --rejoin-only` spends the
  agent's Fabric request budget, which every session on the machine shares; with about forty Claude Code sessions,
  agents waited minutes on "Fabric is rate limited". The worker marks a successful rejoin in the session's folder; a
  turn within 60 s of it is spooled and delivered by the next worker, and the end of a session always starts one.
  Fabric fixed its side in CO-334 (per-session charging, jitter after `Retry-After`) and advised this skip.
- **`creating-fabric-agents` → resilience reference follows contract DEC-0087** (FAA-56, guidance part): the codes
  are `quota-exhausted` and `outcome-unknown`; a job a limit only paused stays `working` with the pause grammar in its
  `statusMessage`; a job its provider will not resume ends `failed` with `data: {retryable, resetsAt?}`; a caller acts
  as `jobCallerAction` does. The kits' rules and vectors come with the repin (FAA-54).

## 0.35.3 - 2026-10-19

### Added

- **`creating-fabric-agents`, resilience and autonomy, third pass**: a rerun calls read-only tools until its open
  outcomes are reconciled; idempotency keys cover content as well as the run; every tool's input schema is pinned to
  the domain schema by a test.
- **`creating-fabric-agents`, text for people** (FAA-52): the intake grill asks whether the agent writes text a person
  reads; if it does, its prompt forbids the em dash (U+2014) and any substitute for it, and a test fails on U+2014 in
  its output from the first commit. The resilience reference gains *Text for people* (the rule, its exact exceptions,
  a portable check, `accept` rewriting or refusing a model's slip) and a checklist line; a new eval scenario covers it.
  `test/validate.py` fails a tree where the grill, the reference or the scenario loses it.

### Fixed

- **The resilience reference numbered two rules 9** under *Secrets and confinement*; the second is 10.

## 0.35.2 - 2026-10-18

### Added

- **`creating-fabric-agents` → resilience and autonomy, second pass**: retries moved at most once and only before the
  first byte, a persisted `Retry-After`; deciding for a waiting peer and releasing a lease with its commit; live-only,
  exactly-once hand-overs; protocols ported from shared vectors; bytecode cleared before mutation runs; blocking work
  off request workers and interruptible socket waits; bounded recursive parsing, content-addressed revocation, no
  refresh of a person's own credentials. From the same retrospective's later answers (2026-10-17/18).

## 0.35.1 - 2026-10-17

### Added

- **`creating-fabric-agents` → `references/resilience-and-autonomy.md`**: the rules that kept about twenty production
  agents working through limits, model errors and restarts, from their retrospectives of 2026-10-17 — limits as
  pauses and resume-first workers, an acceptance parser per model call, cross-vendor fallbacks and checkers, spend as
  a persisted ledger with idempotency keys, decisions recorded instead of asked, tests watched failing, run ownership,
  owner-tagged resources and secrets kept out of every child's environment. The skill reads it before the first
  stage that calls a model or spends money and reports its checklist.

### Fixed

- **The Hermes native adapter dropped a helper's answer** (FAA-51): a helper that exits without reading its input broke
  the pipe while the payload was written, and the broken pipe discarded the helper's output. It no longer does.
- **`test/validate.py` validated other checkouts as this tree** (FAA-50): its walks entered `.worktrees/` (git
  worktrees of this repository, git-ignored), so the main checkout failed the pin check — 442 errors — whenever a
  worktree of another branch sat beside it. Every walk now skips `.git` and `.worktrees`.
- **The tests left directories behind** (FAA-50): the Node tests made their temporary directories with `mkdtempSync`
  and removed none, and five Python tests used `mkdtemp` without a cleanup, so every run left about 40 directories in
  the system's temp folder. The Node tests take theirs from `test/temp-dir.mjs`, removed when the process exits; the
  Python tests register `addCleanup`. A full run now leaves none.
- **The session hooks' spool grew without bound** (FAA-50): a session folder was removed only when its worker delivered
  the session's end, so a failed delivery or a session that ended without SessionEnd left its folder forever. The next
  spooling hook now removes folders untouched for 7 days, never its own.
- **`install-host-hooks --host codex --remove`** names the SessionStart hook groups after ours that it moves: Codex
  keys a hook's trust by its position, and asks the person to approve those again in `/hooks` (FAA-49).

## 0.35.0 - 2026-10-16

### Fixed

- Codex SessionStart emits explicit JSON. Its preamble began with `[fabric-agent-adapter]`, which Codex treats as JSON-looking output and rejected with `hook returned invalid session start JSON output`.
- The Codex hook installer updates a stale owned command while preserving its matcher, timeout and unrelated hooks; ambiguous duplicate entries are refused.

### Added

- Native bounded context adapters for Hermes prompt sections, OpenCode system transforms, OpenClaw `before_prompt_build`, and Pi `before_agent_start`; no model calls or lifecycle enrollment from these hooks.
- Dry-run native installers with source preflight, config hash fences, managed-file checks and preservation of unrelated settings and explicit OpenClaw denials. Hermes opt-in uses its own CLI.
- Optional native loader probes, negative permission and timeout tests, and a sourced capability survey of all 30 Switchboard hosts plus Tabby. Native context loading is separate from live Fabric admission.

## 0.34.1 - 2026-10-15

A review of 0.33.0 and 0.34.0 found the profile and route rules disagreeing with the contract on JSON they never met in
its vectors. The kits now answer as the contract's TypeScript does on any input. The contract pin is unchanged
(`d8146cf`).

### Fixed

- **FAC-SEM-059 (`runner-profile`) compared loosely.** Python read a missing member and `null` as the same and `1`
  and `true` as equal: an unknown login with `runnerKind: null`, or an allow-list `true` against a profile `1`, passed.
  Node threw on a login or runner kind whose own `toString` member is data. Both now compare with `===`, show such a
  value as its JSON, and read only the vendor table's own members.
- **FAC-SEM-060 compared a recorded resolution loosely.** Python's `!=` called `1` and `true` equal; Node's
  `JSON.stringify` comparison called `NaN` and `null` equal. Both now use the contract's `jsonEqual`, where NaN equals
  nothing.
- **A refusal (`model-classes-empty`) named its policy wrongly on hostile input.** Node threw on an id or revision
  whose own `toString` is data; Python wrote `[object Object]`, read `null` as `undefined`, and did not read a revision
  as `Number()` does (`"0x10"`, `[5]`, `null`). Both now use the contract's `show` and `toNumber`; a revision that is
  not a number is written as null.
- **Route rules (FAC-SEM-028…034) threw or misread hostile JSON.** Node used `String()` where the contract uses `show`;
  Python wrote `[object Object]`, and compared a probe's runner kind and a drive with `!=` (`1` equal to `true`).
- **The doctor's `model_usable` raised on a catalogue row whose id is an object** (Python), and threw on a policy id
  whose own `toString` is data (Node).
- **Python wrote and compared JSON values unlike JavaScript** (found by an independent review of this fix):
  - a lone surrogate (`"\ud800"`, valid JSON) raised `TypeError` wherever a message wrote a value, because
    `_json_stringify` used the RFC 8785 writer that refuses one; it now escapes it as `JSON.stringify` does;
  - members whose keys are array indexes came out in the order written, where JavaScript writes them first and
    ascending, so two equal hostile runner kinds were not a FAC-SEM-028 duplicate;
  - integers past 2**53 compared exactly, where JavaScript compares doubles (`9007199254740993` is
    `9007199254740992`), and integers past the double range raised `OverflowError` where JavaScript reads Infinity;
  - a probe index was written as an exact integer instead of JavaScript's number (`1e+21`).
  These helpers are shared with the estate and identifier kits, whose vectors stay green.
- **Node looked a rule kind up on inherited members**: `routeProblems("__proto__", …)` threw and `"constructor"`
  answered the value; both now answer `undefined`, as the contract does.
- **The task board broke the workspace's publication**: rows FAA-28 and FAA-27a split into six cells (an escaped
  `\|`, and a fragment a 0.31.0 edit left behind). Both are fixed, and `test/validate.py` now refuses any board row that
  does not split into the header's columns.

### Evidence

- 38 new profile cases and 21 new route cases (`make_profile_vectors.mjs`, `make_route_vectors.mjs`), each answered by
  the contract's own rules; cases JavaScript cannot carry as an object (big integers, key order) keep their JSON text.
  Against 0.34.0's kits the first 44 of them fail 27 Python subtests and two Node tests.
- The reviewer's side-by-side comparison of the contract, the Node kit and the Python kit on 17 hostile inputs: 17 of
  17 identical after the fix (Python 1 of 17 before).
- Unit tests for the doctor and the rule dispatch on hostile input, in both kits; `BoardRowTests` for the board check.
- Planted defects in the new code, all caught; two were redundant code, now removed.

## 0.34.0 - 2026-10-15

The adapter is pinned at contract `d8146cf`. The profile kits now read what a lane reads (DEC-0083; FAA-45, contract
CT-52): a model profile that reads what members, clients or the public send keeps an open-vendor model on its route,
so the lane never runs on closed vendors alone, which refuse the content it exists to handle.

### Changed

- **Repin** from `82e1636` to `d8146cf`. Every vendored vector is byte-identical except `profile-vectors.json`.
  `82e1636` stays a supported revision.
- **`open-vendor` is descriptive** in `resolve_model_profile` / `resolveModelProfile` and in the doctor's `model_usable` /
  `modelUsable`: a project's `modelClasses` never admit or exclude a model by it, and a model whose only class is
  `open-vendor` is admitted on nothing. Both copies of the every-class rule answer the contract's shared
  `model-admission.json` vectors.
- **FAC-SEM-058 and FAC-SEM-060 are total on hostile input**, as the contract's became in DEC-0083's fix round: an
  `instancePath` names an item by its index as written (a non-object before it no longer shifts it, and every model
  counts at its own index), a duplicate id is what JavaScript's `Set` calls one (`1` and `true`, `null` and absent, are
  two), and an id whose own `toString` member is data is shown as its JSON.

### Added

- **FAC-SEM-112** on a `profile-resolution`: a profile with `reads: ["user-content"]` has an open-vendor route — with
  `fallback: none` its first model is `open-vendor` in the catalogue, with `between-turns` at least one is — and the
  models the project's policy leaves must still give one, or the finding at `/resolved/models` names the policy.
  `closed_user_content_route` / `closedUserContentRoute` name the models that would run on a closed route.
- `creating-fabric-agents` asks in its grill which lanes read user content; `profile-selection.md` and the profiles
  reference say how such a lane is declared and routed, and that a content refusal or an empty answer is a failed turn.

### Fixed

- **`make_profile_vectors.mjs` read the contract's newer fixtures vacuously.** Since DEC-0083 a profile fixture wraps
  its document as `{description, kind, expect, input}`; the generator fed the wrapper to the rules, so every expectation
  came out empty and the Node test passed without checking anything. It now unwraps them and stops when a fixture's own
  `expect` disagrees with the contract's answer.
- `resolve_model_profile` takes `catalogue` and `profiles` as optional, as the contract's resolver does, so an absent
  catalogue resolves instead of raising.

### Evidence

- Both kits answer 72 rule cases (45 crafted: FAC-SEM-112 edges, the policy's outcome, hostile ids and indexes), 81
  resolutions and 8 admission cases.
- 51 planted defects (30 in Python, 21 in Node), all caught but two that cannot differ on JSON input: a redundant
  type check, now removed from the code, and the Node message of a duplicate object id, which parsed JSON never
  produces. A unit test covers `1` and `1.0` as one id, a case JSON written by JavaScript cannot hold.
- Eval scenarios `lanes-that-read-user-content` and `user-content-open-vendor-route`.

## 0.33.0 - 2026-10-15

The adapter is pinned at contract `82e1636`. The estate kits now read contexts (DEC-0082; FAA-41, the RM-28 pilot): one
agent placed on a machine for the person and for each organization it serves. Before this, at the old pin, a record
placing one agent in two contexts was refused as a duplicate placement (FAC-SEM-074), and an organization's instance
was checked against no share grant.

### Changed

- **Repin** from `1636fa9` to `82e1636`. Every vendored vector is byte-identical except `estate-vectors.json`.
  `1636fa9` stays a supported revision.
- **Placement and slot keys** in `fabric_estate.py` / `fabric-estate.mjs` carry the context: a placement is keyed by
  agent and context (FAC-SEM-074), a secret slot by agent, slot and context (FAC-SEM-075). A secret fills a slot of an
  agent placed in its own context. An absent `context` is `personal`; `null` is not absent.
- **`placement_trust(record, machine, agentRef, context="personal")`** / `placementTrust(…, context)` answer for the
  placement in that context. A caller that passes none gets the personal placement, as before.
- **`estate-placement`** takes `{record, machine, package, context?}` and checks the placement in that context.

### Added

- **FAC-SEM-110**: a share grant (`principalKind: external`) is never in the `personal` context. Checked on each of an
  estate record's `shareGrants[]`, and on a grant of its own with `grant_context_findings` / `grantContextFindings`.
- **FAC-SEM-111**: an organization's placement names, in `grant`, a share grant of the record whose `context` is the
  placement's, as written, and that the record does not revoke; a personal placement names none; a context that is not
  `org:<orgId>` fails closed. Checked on a record and on an installation.
- **An organization's slot is filled from its own machine**: an envelope names no context (FAC-SEM-075).
- **`parse_context` / `parseContext`**: `personal`, `org:<orgId>` (`[A-Za-z0-9][A-Za-z0-9_-]{0,127}`), or nothing,
  compared as written.

### Fixed

- **Every estate rule is total on hostile JSON**, as the contract's became in DEC-0082's fix rounds: an
  `instancePath` names an item by its index as written (a non-object before it no longer shifts it), and a value whose
  own `toString` member is data is shown as its JSON instead of throwing.
- **A flaky board test** (FAA-43): the hold test of `com.effect_begin` lifted the hold on a 50 ms timer, so a slow runner
  saw one begin instead of two. The fake board now lifts it right after the first held begin (`lift_holds_after`), in
  the Python and the Node twin.

### Evidence

- Both kits answer 115 contract rule cases (19 hostile, built by `make_estate_vectors.mjs` from the contexts fixture),
  28 grant-context cases and 19 `placementTrust` cases.
- 28 planted defects, 14 per kit, all caught.
- A new eval scenario, `estate-contexts`.
## 0.32.1 - 2026-10-14

The `building-fabric-services` lifecycle reference is now the rule its readers follow (release iteration 1, N-12;
operator decision O6). It used to link the organization's private lifecycle contract and say "the contract wins and
this page is the defect", which left a public reader with a rule they could not open.

### Changed

- **`references/lifecycle.md` is normative.** A new *The rules* section states the lifecycle itself: the supervisor
  owns the process (never kill a service; start, stop and restart only through launchd, systemd, the Task Scheduler
  or the node; state is read from the supervisor; restart no sooner than 10 s; off stays off), the descriptor, and
  readiness through the well-known document. A table states each lifecycle rule the kits serve (LC-01, -02, -03, -04,
  -05, -09, -11, -12, -14, -15, -21, -22) in one sentence, with the section and the kit function that serve it. It
  links only public sources: the Fabric Agent Contract's service specification, *Lifecycle*. The `LC-` ids remain
  for provenance.
- **`working-with-fabric` `references/project-board.md`** no longer says the private page "wins": it is the rule a
  coding agent with this plugin follows, and cites the knowledge base for provenance.
- The two kits' lifecycle comments (`fabric_service.py`, `fabric-service.mjs`) point at the reference and the
  public specification instead of the private page.

### Added

- **`test/validate.py` refuses a skill page that defers to a private source**: a paragraph that names
  `fabric-workspace` and says it "wins", "takes precedence", "prevails" or "is authoritative", or that this page "is
  the defect". The validator's self-test plants one; `test/test_validate.py` covers the cases.

## 0.32.0 - 2026-10-14

The adapter is pinned at contract `1636fa9`. The board kits now read the operator's hold (DEC-0079) and the owner's
settlement (DEC-0081) (FAA-42, contract CT-42). Before this, a Fabric serving either decision would have broken a
responder at this pin:
- a `held` refusal was read as a malformed answer, and the responder blocked;
- a receipt carrying `settledBy`, a directory page carrying `held`, and a held refusal were all refused as shapes the
  contract does not name.

### Changed

- **Repin** from `f00a768` to `1636fa9`. Every vendored vector is byte-identical except `comms-vectors.json`, which
  gains 59 comms fixtures and one digest. `f00a768` stays a supported revision.

### Added

- **`held` (DEC-0079)** in `fabric_board.py` / `fabric-board.mjs`:
  - `held` is a known refusal code and must be `retryable: true`.
  - A slot that `com.status` names `held`, or whose `com.enroll`, `com.claim` or `com.responder_replace` is refused
    `held`, pauses. It is asked again after 15 s, the wait doubling up to 15 minutes. One `board.slot.held` event per
    capability is emitted, then `board.slot.released`; no `board.down`.
  - Accepted work continues: `com.renew`, `com.progress` and `com.complete` are never held.
  - `com.effect_begin` refused `held` waits and asks again with the same key. Nothing outside the service starts until
    it is answered.
  - A hold between the claim and the accept does nothing; the request waits on the board.
  - Accepted work found at restart under a hold is kept for a transfer once the hold is lifted.
  - `hold_refuses` / `holdRefuses`: the contract's matrix, held to its 114 cases (`comms-hold-vectors.json`, vendored
    and re-answered by the contract's own function).
- **`settledBy: "owner"` (DEC-0081)** read on a receipt's request (only `completed` or `failed_known`), and **`held`**
  read on a directory page's capability and on `com.status` responders.
- **Docs:**
  - `references/board.md`: "When the operator holds work".
  - `working-with-fabric`'s `references/project-board.md`:
    - `held` means wait and retry with the same key, never route around the hold;
    - a structured finding (DEC-0080), sent only where `com.submit` takes `finding`, with an idempotency key of at
      least 128 random bits and `repeated: true` read as the standing finding;
    - `settledBy` read as the owner's attestation.

### Evidence

- Two scenario evals (`board-responder-held`, `board-held-and-finding`) were written before the prose.
- The fake board models holds from its own records.
- 13 Python hold cases (`HoldShapeTests`, `HoldTests`, two in `RestartTests`) and 5 Node ones (`test/fabric-board.test.mjs`, the cases after "DEC-0079 and DEC-0081").
- 30 planted defects (16 Python, 14 Node) were all caught, two of them only after a case was added for them.

## 0.31.1 - 2026-10-14

### Fixed

- `fabric_package.py` no longer carries a PEM private-key header as one literal string. It is still the line that
  reads a PKCS#8 key file, and it reads files exactly as before. The PassionCode launcher's vendor step scans every
  shipped file for that marker, and the literal made it refuse to vendor 0.31.0. A test now fails if any file under
  `plugins/` or `bin/` carries the marker. Planted check: an unsplit marker fails the test.

## 0.31.0 - 2026-10-14

An agent is packed, signed and verified as a `fabric-package/1` folder (FAA-27a and FAA-36, `RM-28 pilot`; contract
DEC-0050, DEC-0051, DEC-0071, DEC-0074, all at the pin `f00a768`).

### Added

- **`fabric_package.py` and `fabric-package.mjs`** (`building-fabric-services`). The two write the same bytes.
  - `pack <folder>` reads the author's `fabric.package.json` and does the rest:
    - derives `agentRef` and lists every other file with its SHA-256, in UTF-16 order;
    - computes the RFC 8785 digest;
    - checks the result against the contract's schema (bundled at the pin), FAC-SEM-064…066 and FAC-SEM-102, and the
      folder check.
    - It refuses symlinks, `.git`, caches and files that are credentials by name, and names each one.
    - It writes nothing without `--apply`, or while a problem stands.
  - `sign <folder> --key <file>` adds an Ed25519 (`EdDSA`) publisher signature or organization countersignature over
    the typed statement.
    - The key is a JWK or PKCS#8 PEM file at mode 600, which the person names. The kit never makes, keeps or prints a
      key.
    - A folder that no longer matches its package is not signed.
  - `verify <folder> --trust <file>` runs the contract's `verifyPackage` in PK-1…PK-10's order, with the small-order key
    check first, plus the folder check and the rules.
  - Also exported: `consumer_placement` / `consumerPlacement` for a consumer agent's `requires.mcp`.
- **`npx @passioncode-ai/fabric-agent-adapter pack|sign|verify`**: the same commands from the npm package.
- **`references/package.md`**: what a package is, the author's file, the three commands, a consumer agent, and what this
  version does not do. That list: ES256 (Fabric D2), hub and passkey signing, the passkey countersignature, Fabric
  recording packages by `agentRef`, and `publish`.

### Evidence

- `test/fixtures/contract/vendor_vectors.mjs` now writes `package-vectors.json`, with every case re-answered by the
  contract's own functions, and the bundled schema. The other vendored files came out byte-identical.
- The Python and Node tests each hold 17 cases:
  - every verifier case;
  - every signature reproduced from the vector seeds;
  - every fixture through the schema, and every semantic fixture through the rules;
  - pack rebuilding the vector package byte for byte;
  - both kits packing and signing one folder to the same bytes.

  `test/test_installer.py` covers the npm commands. 28 planted defects were all caught, three of them after a case was
  added for them.
- A scenario eval (`package-pack-sign`) and three trigger queries were written before the prose.

## 0.30.0 - 2026-10-13

The Node service kit installs and uninstalls a launchd job, as the Python kit does (FAA-04). The probe fails a plist
whose copy would not know launchd supervises it (FAA-05).

### Added

- **launchd in the Node kit** (`fabric-service.mjs`, FAA-04): `launchdPlist`, `launchdLoaded`, `launchdOverride`,
  `launchdInstall` and `launchdUninstall`, the twins of the Python `launchd_*` helpers.
  - `launchdPlist` writes the same bytes as Python's `plistlib`.
  - It writes `FABRIC_SERVICE_SUPERVISOR=launchd` itself and refuses a marker argument.
  - It refuses a secret-named variable (a `*_FILE` path is fine), and any variable value or argument shaped like a
    credential, a control character or an empty program.
  - `launchdInstall` follows the LC-14 order: lint, then enable only on a first install. A label the operator
    disabled stays off, with the plist rewritten. The bootout is waited out, the bootstrap retried five times, and
    the install resolves once the well-known document answers with this `id.instance`.
  - `launchdUninstall` waits for the unload, removes the plist and resets the override to `enabled`. `purge` (with
    the service id) removes data, logs and cache; a symlinked folder loses only its link.
  - Off macOS both are refused, with the name of that platform's installer. `run`, `fetchWellKnown` and `sleep` are
    injectable, so tests never reach the real launchctl.
- **Probe rule `lifecycle.supervisor-marker`** (`check_service.py`, FAA-05). It reads the plist's
  `EnvironmentVariables` and `ProgramArguments` the way the started copy reads them (`supervisor_marker`,
  DEC-0057). It fails these cases:
  - no marker;
  - a marker naming another supervisor, or naming none;
  - markers that disagree.

  Without the marker, a copy that finds the lock held exits 75 at once, and KeepAlive restarts it every
  `ThrottleInterval`. Plists written by `launchd_plist` since 0.8.0 (FAA-06) carry the marker; an older one fails
  until it is regenerated and reinstalled.

### Evidence

- `test/fabric-service-launchd.test.mjs` (20 cases) runs against a launchd stand-in with the Python fake's
  semantics. Its byte-identity case compares `launchdPlist` with `plistlib` output.
- Two Python cases in `test/test_fabric_service.py` check `marker_problem` and the rule run on a written plist.
- 16 planted defects were all caught, after replacing two equivalent mutants with real ones. Among them: enable on
  every install, a skipped unload wait, a kept override, unsorted keys, an early bootstrap give-up, an ignored
  instance, a dropped marker, a skipped lint, the legacy override format, an endless uninstall wait, and a probe
  that accepts any supervisor or none.

## 0.29.0 - 2026-10-13

`working-with-fabric` carries the limit-stop rule (fabric-workspace principle 10, item 6, operator 2026-10-13).

### Added

- **A lane stopped on a limit: restart it at once** (`working-with-fabric`, Step 5). Applies to a workflow lane,
  subagent or session that stops on *You've hit your session / usage limit · resets <time>*, on a rate-limit error,
  or after 15–20 minutes of silence with its task unfinished. The agent that started it restarts it at once and does
  not wait for the reset:
  - a workflow: `TaskStop`, then `Workflow` with `resumeFromRunId` and the same args;
  - a subagent: `SendMessage` «resume»;
  - a session: a re-prompt.

  If a restart stops again at once, the next tries come after 2, 5, 10, then every 15 minutes. A spend, credit or
  billing limit goes to the operator once and is not retried. A long command in flight is not a stall. Each restart
  goes into a `fabric_task_note`.
- The description gains the trigger "hit your limit, resets at".

### Evidence

- The scenario eval `limit-stop-restarts-at-once` and two trigger queries (English and Russian) were written before
  the prose.

## 0.28.0 - 2026-10-13

A service answers a Project's requests on Fabric's project board (`fabric-project-comms/0.1`; FAA-12b, contract
DEC-0022, DEC-0073, DEC-0078; Fabric ADR-0149), and checks a directory page before it looks a Project up (FAA-40,
DEC-0077, `FAC-SEM-107`). Repinned to contract `f00a768` (DEC-0078: a replacement's receipt carries the attempt of
each request it transferred); `a046f57` stays supported.

### Added

- **The hub door client.**
  - `fabric_hub.py` / `fabric-hub.mjs` re-read `hub.json` before every call, the way Fabric's `locateHub` does: a small
    regular file, protocol `fabric-hub/0.1`, the origin exactly `http://127.0.0.1:<port>`, a door token inside the
    registry root, and a live pid. A binding credential is sent only after that check.
  - `request_board_access` asks the operator for the `board.respond` grant. `poll_access` writes the credential, shown
    once, to a 0600 file and leaves it out of the answer. `join_board` answers a board session.
  - Typed `HubError`s: a missing grant carries the arguments to ask with. `Backoff` waits 2 s, doubling up to 5 minutes,
    with jitter, so a loop never spins.
  - A `hubKey` in a later `hub.json` is checked with `hub_key_certified` (DEC-0060) when the caller passes an estate
    record. `fabric-hub/0.1` publishes no key today.
- **The responder.** `fabric_board.Responder` / `Responder` runs inside the service, one request at a time:
  - Each tick (15 s ± 5 s) enrolls, claims, reads the message and accepts it with the claim's exact fence. The digest
    must match the claim's, and the request must name this Project and capability.
  - `com.effect_begin` is sent only when the handler calls `ctx.begin_effect()`. Renewal is about every 20 s. Progress
    notes, a fenced `com.reply`, and `com.complete` with an observed outcome and at most 8 sha256 artifacts follow.
  - A checkpoint (0600, fsync) is written before each step. If it cannot be written, nothing is sent.
  - It stops acting on `fenced`, `lease_expired` and `authority_changed`.
  - On restart it reconciles unknown outcomes from what `observe` reads. It takes accepted work back only through
    `com.responder_replace`'s `transferred` (DEC-0078). On a Fabric that does not answer `transferred`, the work stays
    held and is never claimed back.
  - A board session never sends `com.submit`, `com.cancel`, `com.read_ack` or `com.directory`.
  - With no idempotency epoch in `com.status`, it fails closed.
  - The body is data: `admit`, the service's own input gate, is required. A refusal completes the request
    `failed_known` with the gate's sentence.
- **The directory page check (FAA-40).** `directory_findings`, `directory_problems` and `find_project` / `findProject`
  apply `FAC-SEM-107`: each Project once, each capability once per Project, compared exactly as written. A page that
  fails is refused rather than read.
- **Closed shapes:** `receipt_problems` (with `transferred` for `com.responder_replace` only, each request once),
  `refusal_problems`, `evidence_problems` (one artifact never twice, DEC-0076), `outcome_problems`, and
  `comms_digest`, which matches the contract's `commsDigest` vectors.
- **`check_service.py`** gains the rule `board.responder`:
  - `NOT_RUN` when the well-known `protocols` lists no `fabric-project-comms` revision.
  - Otherwise it runs the kit's fixture conversation: `self_check()` / `selfCheck()` covers the whole conversation, a
    fenced accept and a session without an epoch. `--board-kit` names the service's own copy.
- **`sample_service.py serve --board-project <uuid>`** opts in to answering `sample.echo` on the board, with a gate
  and a reply. It is off by default.
- `references/board.md`, linked from SKILL.md. working-with-fabric's `project-board.md`:
  - The project directory is decided (DEC-0073).
  - Answering as a responder needs `board.respond`.

### Evidence

- 20 hub tests and 49 board tests in Python, and 16 Node tests, run against one fake Fabric hub
  (`test/fake_fabric_hub.py`), which models migration 87's fence order. The Python and Node kits read each other's
  checkpoint.
- The contract's 77 comms fixtures, 8 responder-argument digests and 12 `FAC-SEM-107` pages are vendored by
  `vendor_vectors.mjs` at `f00a768`.
- 22 planted defects across both kits, all caught (`docs/reports/2026-10-13-faa-12b-board-responders/raw/plants.log`).
- Red before: the new tests at `origin/main` `65c1751` fail on the missing modules.
- The live Claude→Codex board smoke is `NOT_RUN`: no disposable Fabric fits this machine. The commands are in
  `references/board.md`.

## 0.27.0 - 2026-10-13

The usage report's window and spend by project, and OpenRouter attribution for a product's own traffic (contract
DEC-0065, FAA-33). Pin unchanged at `a046f57`.

### Added

- **Spend by project.** `make_usage_receipt` / `makeUsageReceipt` take `project_id` / `projectId`, a URI kept in its
  normal form (DEC-0076), and `task_run_id` / `taskRunId`. `usage_report` / `usageReport` then write `byProject`: each
  project once, each task run once within it, with calls, unpriced calls and cost. It names no caller, session or
  person.
- **FAC-SEM-025 whole:** `usage_findings` / `usageFindings` check the arithmetic, the window (every day exists, is not
  after `generatedAt`'s UTC date and is at most 30 days before it) and the projects. The projects' calls, priced calls
  and known costs are bounded by the days' (CT-40).
- **OpenRouter attribution, off by default:** `attribution_headers` / `attributionHeaders` and
  `attribution_setting_findings` / `attributionSettingFindings` (FAC-SEM-098). The answer adds `HTTP-Referer`,
  `X-OpenRouter-Title` and `X-OpenRouter-Categories` only with a valid setting, only to `https://openrouter.ai` (read as
  a browser reads the URL), only for traffic the product originates, and never over a user's own attribution.
- **`check_service.py`** `usage.report` reads each row's route (`platform-metered` included), the window and
  `byProject`.

### Evidence

- Both kits pass the contract's 34 attribution cases.
- Both kits give the contract's `usageRules` answer on 21 reports: its six positive usage fixtures and 15 edits of the
  by-project one.
- 23 planted defects, all caught.
- The scenario eval `usage-by-project-and-attribution` was written before the prose.

## 0.26.0 - 2026-10-13

Feed events carry machine-readable `data` (contract DEC-0070, FAA-35), and a service says which protocol revisions it
accepts (DEC-0067, FAA-37). Both are in the pin `a046f57`, which does not move.

### Added

- **`data` on an event.**
  - `make_event` / `makeEvent` and `JsonlEventLog.append` take `data={schema, value}`.
  - `schema` is the absolute URI of a payload schema the service publishes.
  - `value` holds at most 32 members. Each is a scalar (a string of at most 500 characters), a list of at most 32
    scalars, or an object of at most 32 scalar members.
  - FAC-SEM-101 refuses a string under a credential's name or of a credential's shape, at either level. The refusal names
    the place, never the value.
  - `feed_data_findings` / `feedDataFindings` and `feed_data_problems` / `feedDataProblems`.
- **Protocol revisions.**
  - `PROTOCOL_REVISIONS` (the contract's register), `parse_revision`, `accepted_revisions` (N and N−1),
    `negotiate_revision` / `negotiateRevision` (`schema-unsupported`, or the receiver's own `no-accepted-revisions`) and
    `protocols_findings` / `protocolsFindings` (FAC-SEM-099).
  - `build_well_known` / `buildWellKnown` take `protocols`. List them only once your hosts are pinned at or after
    DEC-0067, because the document is closed for an older reader.
- **`check_service.py`** reads `well-known.protocols` and `events.data`.

### Evidence

Every case below is answered by the contract's own functions at `a046f57` (`vendor_vectors.mjs`):
- the 7 `negotiateRevision` cases and the register;
- FAC-SEM-099 over 14 lists;
- every events-page and well-known-protocols fixture as the catalogue lists it;
- FAC-SEM-101 over 10 pages.

N and N−1 cannot occur at this pin, because each protocol has one revision. That rule is held on a register with three
revisions. 20 planted defects were all caught. The scenario eval `feed-data-and-protocols` was written before the prose.

## 0.25.0 - 2026-10-13

Identifier equality by normal form (contract DEC-0076) in both kits, and the contract pin moves from `fe55fc6` to
contract `main` `a046f57` (FAA-39). `fe55fc6` joins the supported revisions. DEC-0077 (`com.directory` pages) is in the
pin. Its consumer is the kits' board client, which is not built yet (FAA-12b), so nothing reads it.

### Added

- **`normal_identifier` / `normalIdentifier` and `same_identifier` / `sameIdentifier`** (`fabric_identifiers.py`,
  byte-identical in both skills, and `fabric-identifiers.mjs`). They port the contract's `src/identifiers.ts` and are
  held to its `identifiers.json` (33 normal forms, 8 same, 8 different, 6 lax-port mistakes).
  - A URI follows RFC 3986 §6.2.2.
  - A `urn:` follows RFC 8141 §3.1 (the NSS's case is kept and nothing is decoded).
  - Any other string is its own normal form.

### Changed

- **Compared by normal form:**
  - FAC-SEM-030, FAC-SEM-032 and FAC-SEM-034 compare a revision reference's id and the project and capability of
    admissions, bindings and events;
  - FAC-SEM-076 compares share grants and `grant` revocations;
  - FAC-SEM-014 compares a provider entry's `providerId`.

  Two spellings of one identifier now read as one, and two identifiers stay two.
- **Written in normal form:** the scaffolded `provider.id`, `identity.subject` and capability `id`, and the `providerId`
  that `write_provider_entry` stores.

### Evidence

- The route and estate generators now add respelled-id cases (`urn` and the NID upper-cased, and the NSS's case
  changed), each answered by the contract's own functions. The contract's fixtures are in normal form, so without these
  cases the kits' byte comparisons stayed green.
- The compiled-schema revision tests pass at `2ce3922` → `a046f57`.
- 20 planted defects, all caught.
- The scenario eval `identifiers-by-normal-form` was written before the prose.

## 0.24.0 - 2026-10-13

An app's own descriptor (contract DEC-0069) and the descriptor for listings (DEC-0061) in both kits (FAA-34). The contract
pin does not move: both decisions are at `fe55fc6`.

### Added

- **`lifecycle.manager` `node` and `person`.** `node`: Project Observatory's node supervises the service as its child,
  with no supervisor file, so `label`, `plist`, `unit` and `task` are refused beside it. `person`: an app a person
  installs and starts — `lifecycle.app` is required, `origin` is optional (its live origin is in the app's own liveness
  file), and `installedBy` is `{by: "person", role, tool}`. `write_descriptor` / `writeDescriptor` claim no port for
  it, and `check_service.py` reads it as installed, never running: `descriptor.app-installed`, no port claim, and the
  well-known document `NOT_RUN`.
- **`installedBy` by role, `runner` and `peer`.**
  - `installedBy` is a string or `{by, role?, tool}`.
  - `runner` is `{kind?, credentialKind}`, a kind and never a credential.
  - `peer` is `{endpoint, custody, residency, maxDataClass}`. An offer needs `runner` and never a subscription.
  - FAC-SEM-085 refuses a peer on a reserved name. FAC-SEM-086 refuses a value shaped like a credential in `runner` or
    `installedBy`, naming its place.
- **Ports held to the contract's vectors:** `peer_refusal` / `peerRefusal` (`service-peer.json`),
  `app_descriptor_action` / `appDescriptorAction` and `app_descriptor_stale` / `appDescriptorStale`
  (`app-descriptor.json`).
- **`fabric_button_presence` / `fabricButtonPresence`** answer whether Fabric's button may show. The answer is
  `present` only while Fabric's own descriptor (`fabric.default.json`) is registered and, for an app's descriptor,
  its app is still installed. A server sets `data-fabric="absent"` otherwise.
- **Usage:** `make_usage_receipt` / `makeUsageReceipt` accept `route: "platform-metered"`. A configuration's route
  stays `subscription` or `key`.

### Changed

- `register_remote` / `registerRemote` and the sample's `register` write `installedBy` in its object form
  (`{by: "person", role: "operator", tool}`). `register_remote` / `registerRemote` also take `runner` and `peer`.

### Fixed

- `check_service.py` reported two descriptors without an origin as claiming the same port.
- `write_descriptor` / `writeDescriptor` failed on a descriptor without one.

### Evidence

- Every service-descriptor fixture of the contract at `fe55fc6` is held through both validators: 10 valid accepted;
  every invalid one refused except the six local-channel negatives (DEC-0075, not a kit surface), a set the tests pin.
- The FAC-SEM-085/086 semantic fixtures answer at the contract's places.
- 32 planted defects, all caught.
- The scenario eval `app-descriptor-and-listing` was written before the prose.

## 0.23.0 - 2026-10-13

The contract pin moves from `b291bf0` (DEC-0055) to contract `main` `fe55fc6`, and both kits follow every rule in that
range that touches what they already do (FAA-32; the contract's hand-over of 2026-10-12, its CT-18 row). `b291bf0`
joins the supported revisions. What the range adds beyond that is its own row: FAA-33…37.

### Changed

- **The supervisor marker comes as an argument too** (DEC-0057, CT-01, P4-01): `supervisor_marker` /
  `supervisorMarker` read `FABRIC_SERVICE_SUPERVISOR=<manager>` and `--fabric-supervisor <manager>` /
  `--fabric-supervisor=<manager>` (after the executable, before `--`; a bare flag consumes no `--…` token), with `node`
  among the managers. Markers that disagree — the two forms, the argument twice, a bare or empty argument beside the
  variable — exit 75 at once, before the lock, naming both. `supervised()` and `supervised_by_launchd()` take the
  marker; `hold_single_instance` / `holdSingleInstance` take `env` and `argv`. A holder whose pid cannot be read is
  named unknown (`FAC-SEM-078`).
- **Writers:** `task_xml` / `taskXml` write `--fabric-supervisor task-scheduler` in the task's `Arguments`, before any
  `--` (a task's action carries no environment, so a Task Scheduler copy now waits like one under launchd);
  `systemd_unit` / `systemdUnit` set the variable unconditionally; every writer refuses a marker in the program
  arguments. `add_supervisor_argument(parser)` lets a service's argparse accept the flag; the sample service uses it.
- **DL-HUBKEY** (DEC-0060): `hub_key_certified` / `hubKeyCertified(record, kid, x, at, applied, extra)` answer the
  contract's verdict — `{certified, machine, revision}` or `{certified: false, fault, detail}` — instead of a boolean.
  A revision outside its window, unreadable, lower than the applied one or forking it is the trust source's fault
  (`issuer-unavailable`: `estate-outside-window`, `estate-unreadable`, `estate-rolled-back`, `estate-forked`); a `kid`
  on two machines, a missing `x` and a numeric `kid` never certify; revocation refs compare exactly. The verifiers
  take `estate_applied` / `estateApplied` and `estate_revocations` / `estateRevocations`; in the Node kit only an
  absent `estate` skips the check (`null` is an unreadable source). Every verifier refuses a clock that is not a number
  of seconds `unknown-state` `no-clock` before row 1.
- **The estate record** (DEC-0063, DEC-0066): `verify_estate_record` / `verifyEstateRecord` admit `issuedAt` up to 60 s
  ahead (`CLOCK_SKEW_SECONDS`); the signing passkey must be under a `sign.<domain>` RP (`wrong-rp`) and its origins
  within it (`wrong-origin`); the record's rules add `FAC-SEM-092`.
- **The Windows token-file reader** (DEC-0057, `FAC-SEM-079`): `windows_token_acl_problem` /
  `windowsTokenAclProblem` decide over the file's flags, owner and ACEs `{type, sid, mask}`: an object or callback ACE
  is refused, an allow with an empty mask and every deny grant nothing, SIDs compare case-insensitively, anything
  unreadable is refused. The Python kit reads the ACEs from SDDL (`acl_from_sddl`), the Node kit through .NET's raw
  descriptor with the mask read unsigned. `windows_acl` / `windowsAcl` now answer ACEs; `token_acl_problem` /
  `tokenAclProblem` are replaced by `token_file_problem` / `tokenFileProblem`.
- **The descriptor** (DEC-0057 item 5): `label` and `plist` are refused beside `systemd` and `task-scheduler`; a
  `localPath` starting `//` or `/\` is a share and refused.

### Evidence

- Vendored from the contract at `fe55fc6` and re-answered by its own functions (`test/fixtures/contract/vendor_vectors.mjs`):
  `hub-key-vectors.json` (51 cases, 14 verifier answers; the hub seeds dropped), `supervisor-vectors.json` (22 marker
  cases, 11 `FAC-SEM-078` records), `windows-token-vectors.json` (30 cases), `descriptor-negatives.json` (DEC-0057's
  seven); `estate-vectors.json` regenerated (49 verify cases). Both kits answer every case as the contract does.
- The kits' own starts against a held lock — by hand, the node, a task, an unknown holder, three conflicts — are
  recorded and read by a port of `lockOutcomeRules` that itself reads the contract's 11 records as it does.
- The sample service, started with `--fabric-supervisor=node`, serves a well-known document, usage report and events
  page valid under the `fe55fc6` schemas; the descriptors the kit writes under every manager are valid too.
- 34 planted defects, all caught.
- The `--fabric-supervisor` scenario eval (`supervised-by-argument`) was written before the prose.

## 0.22.0 - 2026-10-12

`working-with-fabric`, the fourth skill, the plugin's session hooks, and coding agents as participants of Fabric's
project board: a coding agent opened in a terminal works in a project through Fabric the way a session Fabric
launched does (Fabric 0.4.0 REQ-07, plan canvas C4; COM-04; FAA-18 from PR #53, carried onto 0.21.0, and FAA-12a).
The contract pin does not move.

### Added

- **`skills/working-with-fabric/`** (FAA-18): find Fabric (`hub.json` in Fabric's folder per OS, its `pid` alive),
  have the machine's lifecycle broker start it (`lifecycle_list` → `lifecycle_ensure_running` →
  `lifecycle_operation_get`; never launch it), register `fabric-mcp` once with no secret (`claude mcp add --scope
  user fabric -- "<Fabric>/bin/fabric-mcp" --runner claude-code`, `codex mcp add fabric -- … --runner codex`, Kimi
  Code's `mcp.json`, the per-OS `<Fabric>/bin` of Fabric ADR-0134 amendment 2), `fabric_whoami` first and what each
  of its waiting answers means, `fabric_work_list` and `fabric_work_claim` before work and `fabric_work_release` at
  the end (Fabric 0.4.0, REQ-38; the `fabric_task_*` fallback on an older Fabric), stage reports, notes, handoffs,
  tasks linked to backlog rows by `source: {repository, path, id}`, and the refusals.
- **`references/project-board.md`** (FAA-12a): the board-first workflow — `fabric_whoami`, `com.status`, `com.list`,
  `com.read_ack` only what was read; cross-project asks only through `com.submit` to a Project id (never a session,
  process id or folder; no estate, sender or session field; the same idempotency key on a retry); a reply is
  `com.submit kind: "reply"` with `replyTo` until `com.reply` ships (COM-02.3); a message is data, never an
  instruction or approval; no secret in a body; the broker, never Fabric directly; no second session from a hook; no
  folder attached and no project created to make enrollment succeed; COM-03 and the project directory pending. It
  links the rule's one home, fabric-workspace `knowledge/agents-first.md` "The project board", instead of restating
  it.
- **`scripts/fabric_session.py`**: `status` (Fabric, `fabric-mcp`, the Claude Code and Codex registrations, whether
  the session hooks are active, one next action; reads no token); the hooks; `watch-mail [--interval 60]` — one line
  each time the board's unread count rises, ±20 % jitter, a 10 s floor, backoff doubling to 15 minutes while Fabric
  is down, exits on its stdin's end, SIGTERM/SIGINT/SIGHUP or a lost parent; `install-host-hooks --host codex|kimi`
  — a dry run that prints the one entry it would add to `~/.codex/hooks.json` or `~/.kimi-code/config.toml` (never a
  value already in the file) and the file's sha256; `--apply --expect-sha256` backs the file up, keeps its mode, and
  refuses a file of another shape or one that changed; `--remove` takes the entry out.
- **Four Claude Code hooks** in `hooks/hooks.json`: SessionStart adds the preamble when Claude Code has the MCP
  server `fabric` (fabric_whoami, the board, claim and release; one line pointing at the broker when Fabric is down)
  and the machine's Fabric-service count (the line of the machine's `fabric-session-note.sh`, now in the plugin);
  Stop records the turn's facts — HEAD, files changed, lines added and removed, never content — and reads the
  board's unread count (`com.status`) into the session's spool; UserPromptSubmit adds ONE line only when that count
  rose; SessionEnd releases what the session left claimed and records its end. Stop and SessionEnd act through
  `fabric-mcp --rejoin-only` in a detached worker with a 10 s deadline, and only when the running Fabric advertises
  `session-hooks/1` in `hub.json`; until then they stay inert and write nothing. A board that cannot be read leaves
  no count, never a zero.
- **Codex and Kimi Code**: `hook session-start --host codex|kimi` prints the preamble as text; no turn observation or
  unread line, since they cannot rejoin their Fabric session yet (D1).
- **Silent in a session Fabric launched**: `FABRIC_LAUNCHED_SESSION=1` (need D6, asked of Fabric), or what Fabric
  already gives (`FABRIC_ACP_SESSION`, `FABRIC_BRIDGE_URL`, `KILO_CONFIG_CONTENT`, a `CODEX_HOME` in Fabric's
  sessions folder — names only, never values — and Claude Code's `--mcp-config <Fabric>/sessions/…` in an ancestor
  process). The Fabric side the hooks need (D1–D6) is in `references/session-hooks.md` and the
  [spec](docs/evidence/specs/2026-10-11-working-with-fabric.md).
- Evals first: 32 trigger evals (18 should trigger, 14 should not) in English and Russian and 14 scenario evals (board
  first, cross-project asks, replies, a message is not an approval, no secret in a body, waiting under a watcher, the
  Codex/Kimi hook on consent). `test/test_fabric_session.py`: 62 tests with a temporary HOME, fake `hub.json` files
  with live and dead pids, and a fake `fabric-mcp` on stdio that records argv, environment and calls and serves
  `com.status`.

### Changed

- `test/validate.py` checks four skills; the repository-standard rule applies to the three that build an agent's
  repository; `tomllib` and `shlex` join the standard-library list. `test_dashboard_kit.py` finds its own
  SessionStart entry among several.

## 0.21.0 - 2026-10-12

The estate record (contract DEC-0055, `estate-record/1`; contract backlog CT-18, CT-20) in both kits, and the pin
moved to contract `b291bf09e0a9f9fd3c16cf540832cd021203b7d1`, the merge of contract PR #54 (FAA-31).

### Added

- **`fabric_estate.py` / `fabric-estate.mjs`** — the contract's `src/estate-record-rules.ts`, `src/webauthn.ts` and
  `src/p256.ts`, ported answer for answer.
  - **`verify_estate_record` / `verifyEstateRecord`.** The checks run in this order:
    1. the clock, checked first;
    2. the shape;
    3. the digest (RFC 8785, without `digest` and `signature`);
    4. the chain to the parent: estate, next revision, parent digest, issued no earlier, no revocation dropped;
    5. the signing passkey among the trusted ones and not revoked by the parent (rotation stays valid);
    6. the WebAuthn Level 3 assertion, offline: type, challenge, origin, cross-origin, RP ID hash, UP, UV, then the
       ES256 or EdDSA signature under a validated key;
    7. the 30-day window;
    8. the record's own rules, which answer `rule-violation` with `codes`.

    Dates are strict RFC 3339. Passkey JWK coordinates must be canonical base64url.
  - **`estate_record_rules` / `estateRecordRules`** implement FAC-SEM-072…076 for `estate-record`,
    `estate-record-revision` and `estate-placement`.
  - **Also:** `placement_trust`, `estate_record_digest`, `estate_challenge` and `is_valid_p256_key` (SEC 1 §3.2.2).
  - **The Python kit verifies ES256 in pure Python** (P-256, strict DER: minimal positive INTEGERs, nothing after
    them, `r` and `s` below the group order). Its strictness matches OpenSSL's on a malleated, padded or trailing
    signature; a test checks the two against each other.
- **Trusting a delegation key (DL-14, CT-20).**
  - `verify_delegation`, `verify_approval` and `delegation_gate` (and their Node twins) take `estate`: the current
    verified revision, or a function that returns it.
  - A token's `kid` is trusted only while that revision certifies it for a machine (same `kid` and key), does not
    revoke it, and is within its window. Otherwise the token is refused with `kid-not-certified`.
  - A record that cannot be read certifies nothing: `issuer-unavailable` with `estate-unreadable`.
  - Without `estate`, nothing changes.
  - `hub_key_certified` / `hubKeyCertified` answers the question on its own.
- **Tests.**
  - `test/fixtures/contract/estate-vectors.json` is generated by `make_estate_vectors.mjs` from the contract's own
    functions and fixtures at the pin:
    - 45 `verifyEstateRecord` cases, each re-answered against the contract's;
    - 51 rule cases: the 38 semantic fixtures, the positive records, and strict-date and wrong-length edges;
    - P-256 and passkey-key cases;
    - the digest and challenge.

    The private test keys of the contract's vectors are dropped: the kits only verify.
  - Mutation testing: 42 planted defects, all caught.
- **Independent review.** Nothing critical. The ES256 verifier matched OpenSSL on 3,300 signatures, and the Node
  port matched the contract's TypeScript on 470 extra inputs.
  - **One divergence that mattered, now fixed:** Python's `\d` matched a full-width digit in a date. A Python machine
    would have applied a revision the contract refuses. Dates now take ASCII digits only.
  - **`Number()` follows JavaScript.** Its whitespace, `0b`/`0o`/`0x`, and arrays are read as JavaScript reads them.
  - **A verdict, never an exception**, for three inputs: deeply nested client data, a 400-digit revision, and a lone
    surrogate in a pinned RP ID.
  - **New vectors from the contract cover these:** 24 more rule cases.
  - **The docs now require** that `estate` is a verified revision, and the highest one applied, since the rule trusts
    the record it is given.

### Changed

- **The pin is `b291bf0`.** `0cacd08` stays supported. The compiled-schema checks pass for all three profiles against
  the new pin.
- **The settings canonical form refuses a lone surrogate in any string or key** (CT-25, DEC-0052), in both kits,
  answering the contract's refusal vectors.
- Docs: `references/estate-record.md` (new), `delegation.md` (*Keys the estate record certifies*), and `SKILL.md`.
  The scenario eval `estate-record-and-certified-keys` and a trigger came first.

## 0.20.0 - 2026-10-12

Runner routes in both kits: the closed probe results and the route checks FAC-SEM-028…034. These come from contract
DEC-0026 and DEC-0029, at the pin (FAA-11).

### Added

- **The closed probe result.** `runner_check` / `runnerCheck` answer with `probe`. The values follow the walk's order:
  - `not-installed`: no catalogued binary is on PATH;
  - `not-responding`: the version probe did not answer, failed or did not match, or the `auth` probe did not answer;
  - `not-connected`: the runner answers but is signed out;
  - null: the runner can serve.

  The doctor still names every problem it found.
- **The route checks.** `route_problems(kind, value)` / `routeProblems(kind, value)` are the contract's `routeRules`,
  finding for finding: code, path and message.
  - `runner-route`: one candidate per runner kind (FAC-SEM-028), and every candidate can attach or spawn (029).
  - `route-bundle`:
    - provider revisions are admitted by id, revision and hash (030);
    - the binding agrees with the route (032);
    - kinds and drives are in the runner catalogue (033).
  - `route-event` tells the truth about its route (034):
    - candidates by position;
    - probes in order;
    - the session, hold and recovery policy.
- `PROBE_RESULTS` lists the closed vocabulary of a passed-over candidate.
- **Tests.** `test/fixtures/contract/route-vectors.json` holds 43 cases, generated by `make_route_vectors.mjs` from the
  contract's own `src/route-rules.ts` at the pin. Both kits answer every case exactly.
  - Mutation testing: 23 planted defects, all caught.
- **Docs.** `references/profiles.md` gains *Runner routes* and the probe result. `SKILL.md` points to it. The scenario
  eval `runner-routes-and-probe-results` and a trigger came first.

## 0.19.0 - 2026-10-12

Settings backups, every spending limit and the feed client's token header in both kits. These are the
service-side surfaces the pinned contract already carries: DEC-0025 and DEC-0027 (FAA-13).

### Added

- **Settings backups (`fabric-settings-backup/1`, FAC-SEM-035).** Each function exists in both kits.
  - **Location.** Snapshots live under `<root>/settings-backups/<id>/<instance>/`, outside the data directory.
    `<root>` is per system: `~/Library/Application Support/PassionCode`, `%APPDATA%\PassionCode` or
    `$XDG_CONFIG_HOME/PassionCode`.
  - **Writing.** `make_settings_backup` builds a snapshot from allow-listed tables of JSON scalars. It refuses
    secret tables, credential columns and fractions.
  - `write_settings_backup` writes atomically, 0600 in a 0700 folder.
    - It does not rewrite an unchanged snapshot.
    - It removes a temporary file an interrupted write left behind.
    - It keeps the 14 newest snapshots.
  - `backup_due` decides when the next snapshot is due.
  - **Reading.** `read_settings_backup` refuses a damaged file and names why.
  - `newest_intact_backup` skips damaged files and empty snapshots.
  - `restore_plan` adds rows and never overwrites them. It names what it drops, leaves to defaults or refuses.
  - **The checksum** uses the settings canonical form: `settings_canonical_json` and `settings_backup_digest`.
    They are checked against the contract's vectors.
  - **Parity.** Both kits write byte-identical files.
- **Every spending limit (DEC-0027, FAC-SEM-031).**
  - `usage_report` and `usageReport` take a `budgets` list.
  - A machine day or month limit is counted from the receipts, so it always agrees with `budget`.
  - A per-order limit gets `spentUsd: null`.
  - The report is refused when its limits break FAC-SEM-031.
  - `usage_limit_problems` and `usageLimitProblems` check a report.
- **The feed client (FAC-SEM-036).** `token_header` and `tokenHeader` give the one header the descriptor
  declares. `check_service.py` now sends its token through it.
- **An independent review found 20 moderate defects; all are fixed with tests.**
  - **The readers follow the schema exactly**, and the two kits accept the same files:
    - a trailing newline is refused (Python matches a whole string now);
    - a timestamp is any RFC 3339 date-time with a real calendar date, including an offset;
    - a string holds at most 1 MiB and a row at most 512 values;
    - every `extensions` key is a URI;
    - NaN is refused;
    - in Node, invalid UTF-8 and a `1.0` integer are refused the way Python refuses them.
  - **A damaged file never stops anything.** The scan skips it, the digest does not crash, a damaged newest file
    does not suppress a good snapshot, and an impossible file name makes a snapshot due.
  - **Safer writes:**
    - only a temporary file older than an hour is removed;
    - the snapshot just written is never pruned, even after the clock steps back.
  - **The restore preview** refuses a key the snapshot holds twice.
  - **Limits:**
    - a machine limit over a rolling window is counted from the receipts;
    - a limit that is not an object is refused.
  - **Both descriptor validators** check `auth.header` and `auth.scheme` the way the schema does.
- **Tests.**
  - The contract's fixtures at the pin are copied to `test/fixtures/contract/dec-0025-0027/`.
  - The Windows CI job runs both kits' new cases.
  - Mutation testing: 79 planted defects, all caught.
- **Docs.**
  - `references/settings-backups.md` is new.
  - `usage.md` covers every limit.
  - `events-and-notifications.md` covers reading a feed.
  - Updated: `SKILL.md` step 5 and the lifecycle reference's directory table.
  - The scenario eval `settings-backups-and-every-limit` and two triggers came first.

## 0.18.0 - 2026-10-12

Services on Linux and Windows in both kits (contract DEC-0032, DEC-0033; FAA-21): the supervisor files the
contract names, and the Node kit on Windows.

### Added

- **The supervisor writers, in both kits.** They write byte-identical files, and a test holds them to that.
  - **Linux — a systemd user unit.** `systemd_unit` / `systemdUnit` writes `Restart=always`, `RestartSec=10`,
    `TimeoutStopSec` above the drain, `WantedBy=default.target` and `FABRIC_SERVICE_SUPERVISOR=systemd`.
    `systemd_install` / `systemdInstall` runs `daemon-reload` and `enable --now`. `systemd_uninstall` /
    `systemdUninstall` runs `disable --now`, removes the unit, then runs `daemon-reload`.
  - **Windows — a per-user Scheduled Task.** `task_xml` / `taskXml` writes a logon trigger, least privilege,
    restart every minute on failure, no time limit and `IgnoreNew`. `task_install` / `taskInstall` runs
    `schtasks /Create` from a UTF-16 file it then removes, then `/Run`. `task_uninstall` / `taskUninstall` runs
    `/End`, then `/Delete`.
  - **No secret in a supervisor file.** The writers refuse a credential-shaped argument, environment name or
    value, and any control character.
  - **An upgrade restarts what runs; the operator's off stays off (LC-14).** A unit that `is-enabled` reports
    disabled, or a task whose settings say `Enabled false`, is rewritten and left off unless `force_enable`.
  - **Checked by the real readers:** `systemd-analyze verify` on the Linux job (a quoted `WorkingDirectory=` is
    refused there, so it is written unquoted), and `schtasks /Create` of a throwaway task on the Windows job.
- **The Node kit on Windows and Linux:**
  - `servicesDir` and `serviceDirs` use `%LOCALAPPDATA%`.
  - `expand` and `validateDescriptor` match the Python kit: all four managers, `unit` and `task` paired with
    their manager, Windows paths, never a network share.
  - The token file gets a protected ACL: written with `icacls`, read with Windows PowerShell 5.1. A refusal
    names the SID.
  - The instance lock is a named pipe on Windows (an abstract socket on Linux, as before).
- **One copy across the kits.** The Python kit holds the Node kit's lock name (`lock_name` / `lockName`)
  beside its file lock, so the two kits exclude each other on every system. `check_service.py` now reports the
  lock as held when a Node service holds it. Before this release it failed every Node service on Linux.
- **A copy under systemd backs off on a held lock** as one under launchd does (`supervised()`).
- **The Windows CI job** runs the Node kit's platform, supervisor and service tests and the Python supervisor
  tests.
- **Docs:**
  - `references/lifecycle.md`, *Linux and Windows*: the verbs per system and the Windows directories.
  - `SKILL.md` step 4.
  - `protocol.md`.

  The scenario eval `linux-and-windows-supervision` and two triggers came first.
- **The probe only looks** (`/proc/net/unix`, `WaitNamedPipeW`) and never takes the lock's name.
- **An independent review** found 2 critical and 9 moderate defects before release; each is fixed with a test, except
  that a Scheduled Task still cannot tell the service it is supervised (a task sets no environment; documented).
- **Mutation testing:** 14 planted defects in the Python writers, 23 in the Node port, 7 in the lock name
  and probe and a quoted `WorkingDirectory=` against `systemd-analyze` were all caught.

## 0.17.0 - 2026-10-12

The organisation's lifecycle rules LC-19 and LC-21 apply to what the adapter ships and checks (FAA-22, FAA-23):
no plugin starts a stdio MCP server in every session, and no credential travels in argv or a URL query.

### Added

- **`adapt_project.py check`** refuses:
  - **LC-19:** a Claude Code plugin in the project that declares a stdio MCP server, whether in its `.mcp.json` or in
    `plugin.json` `mcpServers`, because it starts in every session that enables the plugin. An HTTP entry to a
    resident service passes.
  - **LC-21:** a launch argument or a URL that carries a credential, in the manifest's connections and in the plugin
    servers' argv, URL and env.

  `scaffold` refuses a runtime argument that carries a credential.
- **`fabric_provider.py`** refuses a credential in `run.mcp.stdio.command` (LC-21, FAC-SEM-057). The key goes in
  `env` as a secret reference.
- **`test/validate.py` gate:** the adapter's own plugin declares no MCP server and no hook command carries a
  credential.
- The detector is the contract's (`fabric_secrets`, 0.16.0). The adapting skill carries an identical copy, so it
  works installed alone, and a test keeps the two copies byte-identical.
- Docs: the adapting skill's check step, `provider-entry.md`, and `surfaces-and-auth.md` (an HTTP registration
  starts nothing per session). The scenario eval `plugin-and-argv-hygiene` came first. Five planted defects were
  each caught.

## 0.16.0 - 2026-10-12

Runner and model profiles in both kits (contract DEC-0046, Fabric ADR-0147; FAA-19). The contract's credential
detector (DEC-0044) is ported too. The contract pin is unchanged (`0cacd08`).

### Added

- **`scripts/fabric_profiles.py` and `scripts/fabric-profiles.mjs`**:
  - `resolve_model_profile` / `resolveModelProfile` (FAC-SEM-060). The order is request, agent, binding or project,
    then estate default. The project's `modelClasses` narrow the result, and when nothing is left the launch is
    refused as `model-classes-empty`, with the policy named.
  - `profile_problems` / `profileProblems`, the FAC-SEM-058…060 checks of catalogues, profile sets, runner profiles
    and recorded resolutions.
  - `runner_check` / `runnerCheck`, for the doctor (runners.md C2). It runs only the catalogued bare binary on `PATH`
    with its catalogued version and `auth` argv, never through a shell, for at most 5 s.
  - `model_usable`.
  - `configuration`, the well-known `configuration`, and `configuration_summary`, which gives the Runner and Model
    tiles for the dashboard.
- **`scripts/fabric_secrets.py` and `scripts/fabric-secrets.mjs`**: the contract's one credential detector
  (`secret-shape.ts`), with `credential_name`, `secret_value`, `secret_argument` and `secret_url`. It is the base for
  FAA-23 (LC-21).
- **`build_well_known(configuration=)` / `buildWellKnown({ configuration })`** validates the configuration and carries
  it. `configuration_problems` / `configurationProblems` are added.
- **`make_usage_receipt(route=)` / `makeUsageReceipt({ route })`**: a receipt records `subscription` or `key`, and
  the report keeps the rows of one model on two routes apart.
- **Probe rule `configuration.declared`.**
- **Vectors**: `test/fixtures/contract/profile-vectors.json` holds 17 rule cases, 35 resolutions and 128
  credential-detector cases. Every expected answer comes from the contract's own `profile-rules.ts` and
  `secret-shape.ts` (`make_profile_vectors.mjs`). Credential-shaped samples are made up and stored hex-encoded.
- Tests: 11 planted defects across both kits were each caught.
- **Docs**: `references/profiles.md`, a pointer in SKILL.md, and an updated `protocol.md`. The scenario eval
  `runner-and-model-profiles` came first.

## 0.15.0 - 2026-10-12

Fabric's button in the dashboard kit (contract DEC-0040, FB-7). With it, FAA-20 is complete. The contract pin is
unchanged (`0cacd08`).

### Added

- **`assets/dashboard-kit/fabric-button.js`** (kit `fabric-dashboard-kit` 1.1.0) is one floating menu button that
  opens Fabric on the service. It is driven by `data-service`, `data-service-name`, `data-project`,
  `data-project-name` and `data-runner`, and implements FB-1 to FB-6:
  - **Menu (FB-4):** "Chat with Fabric about …", plus "Open a coding session in …" when the page knows its project.
    Arrow keys, Home, End and Escape work.
  - **Placement (FB-2):** bottom-right, or bottom-left right-to-left, 16 px plus the safe area. The page keeps the
    button's height plus 16 px free at the end of its scroll.
  - **Look (FB-3):** the mark alone below 480 px. The accessible name is always "Open Fabric". Colours are `--ink`
    on `--panel` with an `--edge` boundary, the pairs the themes are already measured on.
  - **Host button (FB-6):** the page hides its own button under the host's `fabric_button` cookie `owner=host`.
  - **Fabric absent (FB-5):** "Fabric is not installed — get it at passioncode.ai/fabric" shows when the cookie or
    the server says Fabric is absent, or when the page is still visible and focused 1.5 s after a link was followed.

  Links are built with a port of the contract's `buildFabricLink` and `parseFabricLink`, with the FL-4 credential
  detector. A value the grammar refuses means no button, never a bad link. A press only opens a view (FB-8). The
  script is CSP-clean, and the only address it names is passioncode.ai/fabric.
- `test/fixtures/contract/fabric-links.json` holds 42 parse and 9 build cases. Every expected answer comes from the
  contract's own functions at the pin, through `make_link_vectors.mjs`.
- `test/fabric-button.test.mjs` covers:
  - the grammar against those vectors;
  - the cookie and the menu items;
  - the CSP check;
  - the behaviour in WebKit through Playwright: placement, size, scroll clearance, keyboard, right-to-left, the
    host cookie, Fabric absent, and the 1.5 s test. These are skipped when Playwright is absent.

  Eight planted defects were each caught.
- The sample service's dashboard shows the button. The layout probe passes all 17 rules on it in WebKit.
- `references/dashboard-kit.md` has a "Fabric's button" section. The scenario eval `fabric-button-on-a-dashboard`
  came first.

### Changed

- The dashboard kit is 1.1.0. `dashboard_kit.py install` also copies `fabric-button.js`, and `build` digests every
  copied file. `DASHBOARD_KIT` in both service kits names `fabric-dashboard-kit@1.1.0`.

## 0.14.0 - 2026-10-12

The contract pin moves to Fabric Agent Contract `main` `0cacd08`, which includes PR #46 (DEC-0046, runner and model
profiles) and PR #47 (CT-31). Bundles issued under the DEC-0045 revision and every earlier supported one stay valid
(FAA-30).

### Changed

- **Default contract pin `2eb91c0` → `0cacd08b0e95b6abf131eae1206b60792138bc3c`.** `2eb91c0` joins
  `SUPPORTED_CONTRACT_COMMITS`. The revisions between add DEC-0046's model and runner profile schemas, a model
  catalogue, an optional `configuration` on the well-known document and an optional `route` on usage receipts.
  They also tighten `modelClasses` in a grant to the catalogue's closed vocabulary, which the kits do not write. Later
  merges change fixtures and the contract's privacy check only. The provider manifest and the MCP, A2A and
  local-runner profiles are unchanged. The compiled-schema arms at `2ce3922` and `0cacd08` agree.
- **The shared delegation vectors are regenerated with the contract's verifier at the new pin.** The one case the
  contract used to throw on, a signed token with no `act`, now carries the contract's own answer (`unauthenticated` /
  `malformed-chain`), which is the answer the kits already gave. The other 81 delegation answers are unchanged. The
  tests no longer have a `contractThrew` path; they require that the contract answers every case.
- `references/protocol.md` names DEC-0046's `configuration` and `route`. The kits do not emit them yet (FAA-19).

## 0.13.0 - 2026-10-12

The scaffolder writes what a capability does outside itself, and what a run may cost (FAA-25; target architecture v4,
Stage 0). The contract pin is unchanged (`2eb91c0`).

### Changed

- **`adapt_project.py scaffold` requires `--effect`.** It takes the capability's effect class (`none`, `draft`,
  `publish`, `send`, `reply`, `charge`, `delete`, `merge`, `deploy`, `change-policy`) and writes it to the manifest.
  Before, every capability was written as `effect: "none"`. A scaffold without an effect is refused: the class is
  never defaulted. **This breaks every script that calls the scaffolder without `--effect`.**

### Added

- **`--idempotency required|supported|none`**, written to the capability.
- **`--cost-preset ID MAX_USD LABEL`** (repeatable) and **`--default-cost-preset ID`** write the manifest's
  `costPresets` (DEC-0037): fixed options a launcher offers for a run whose cost varies. The id grammar, the
  amounts, the labels, duplicates and the default are checked.
- `adapting-projects-to-fabric` and `creating-fabric-agents` show the flags and say the effect is read from the code
  or asked of the author, and amounts are never invented. Scenario evals `effect-declared-not-defaulted` came first
  in both skills.
- A compiled-schema test shows the written effect, idempotency and presets are valid under the pin.

## 0.12.0 - 2026-10-12

The contract pin moves to Fabric Agent Contract `main` `2eb91c0` (the merge of contract PR #45: DEC-0041…DEC-0045).
Bundles issued under the DEC-0039, DEC-0036, DEC-0035, DEC-0033, DEC-0031, DEC-0024, DEC-0021, DEC-0020 and DEC-0019
revisions stay valid (FAA-24).

### Changed

- **Default contract pin `8e49fbd` → `2eb91c00e852d9c31d804310d38fad91589fcbac`.** `8e49fbd` (DEC-0039) joins
  `SUPPORTED_CONTRACT_COMMITS`. The schemas between add only:
  - `session-handoff/1` (DEC-0042);
  - `degraded[].setup` on the well-known document and `run.mcp.stdio.scope` on the manifest and the provider entry
    (DEC-0044);
  - a tighter delegation token (DEC-0045).

  The provider manifest and the MCP, A2A and local-runner profiles stay valid as written. The compiled-schema arms at
  `2ce3922` and `2eb91c0` agree.
- **The delegation verifiers follow DEC-0045** in both kits:
  - The trusted `issuer` is required. Without it the answer is `issuer-unavailable` / `no-trusted-issuer`.
  - Every published-key problem except an unknown `kid` is the issuer's, including `key-not-for-signing`. A
    small-order key is refused as `issuer-unavailable` / `small-order-key` before any verification; 0.11.1 answered
    `bad-signature`.
  - DL-2's types are checked strictly: URIs, `AGENT_ID` actors, session and task ids, the `scope` and `jti`
    grammar, exactly one grant, effects named once, the `spend` shape, and `nbf` checked with the types.
    `approval.method: device` is removed.
  - A signed token with no `act` is refused as `malformed-chain`. The contract's own verifier throws on it, and the
    contract was told.
- **Breaking for a caller of the gate:** `delegation_gate` / `delegationGate` require `issuer`, and
  `verify_delegation` / `verify_approval` take it as a required argument.

### Added

- **Trust tiers (DL-25, DL-26):** `gate(tool, headers, tier="T2")` and `McpToolServer.handle(..., tier=)`. A T0 or T1
  caller is never required to present a token; a present one is verified at every tier.
- **`refusal_from_denial` / `refusalFromDenial`:** the callee's answer after the meter denies a grant check (DL-21
  step 6).
- **The contract's canonical vectors** (DEC-0043) run against both `jcs` ports from `test/fixtures/contract/canonical.json`.
- **`fabric_provider.py` accepts `run.mcp.stdio.scope`** (`project` or `on-demand`) and refuses `session`
  (FAC-SEM-056, LC-19). The writer does not set it until Fabric reads it.
- `degraded[].setup` (DEC-0044) is documented in `references/protocol.md`. The kits pass entries through unchanged.
- Scenario evals came first: `local-caller-needs-no-token` and `stdio-provider-scope`.

## 0.11.1 - 2026-10-12

0.11.0 plus one fix. The `v0.11.0` tag was refused by the release's own validation and never published: on Node 22,
the CI version, the Node kit accepted a forged delegation token signed "under" a small-order key. Node 26's
`crypto.verify` refuses such keys, but Node 20 and 22 accept them with the same OpenSSL.

### Security

- **The Node kit refuses small-order Ed25519 keys itself** (`isSmallOrderKey`: libsodium's list, including the
  non-canonical encodings, compared with the sign bit cleared), so `verifyDelegation` and `verifyApproval` no longer
  depend on the Node version. Checked on Node 20, 22 and 26. The contract's own verifier uses `crypto.verify` the
  same way and has the same exposure on Node before 26; the contract repository was told.

## 0.11.0 - 2026-10-12 (tagged, never published; see 0.11.1)

Contract DEC-0039, second part (FAA-20): a service built with the kit checks a delegation token and an operator's
approval offline, in Python and in Node, with the same answers as the contract's own verifier at the pin
(`8e49fbd`, unchanged).

### Added

- **`scripts/fabric_delegation.py` and `scripts/fabric-delegation.mjs`**: `verify_delegation` / `verifyDelegation`
  (the eleven DL-13 checks in their order), `verify_approval` / `verifyApproval` (DL-18, the jti consumed last),
  `read_delegation_token` / `readDelegationToken` (`Fabric-Delegation` first, then a delegation-typ Bearer),
  `jcs` and `action_digest` / `actionDigest` (RFC 8785), the jti stores (`MemoryJtiStore` / `createMemoryJtiStore`,
  `FileJtiStore`, `UNSAFE_NO_JTI_STORE`), `JwksCache` (DL-15: at most 10 minutes, an unknown `kid` re-read at most
  once a minute, 10 s between failed reads, no redirects), `delegation_gate` / `delegationGate`, and the DL-19
  refusal shapes `refusal_tool_result` / `refusalToolResult` and `refusal_http` / `refusalHttp`.
- **The Python kit verifies Ed25519 itself** (standard library only): RFC 8032, cofactorless, and as strict as
  OpenSSL. `S` must be below the group order, points must be canonical, and small-order keys are refused.
- **`McpToolServer(authorize=)`**: the gate runs before every tool; `ctx.delegation` carries the principal, caller
  and chain. A job records who started it, and `fabric.job.get` / `fabric.job.cancel` answer only that principal
  and caller, with a token that still covers the job's capability.
- **Shared vectors** `test/fixtures/delegation/vectors.json` (66 delegation, 15 approval, 8 header, 5 JCS, 2 digest
  and 330 Ed25519 cases), produced by `make_vectors.mjs`. Every expected answer comes from the contract's verifier
  or from OpenSSL. Both kits' tests run over them.
- `references/delegation.md`; `surfaces-and-auth.md` and `protocol.md` no longer say the kits do not verify. Scenario
  evals `mcp-auth-delegation` (updated) and `approval-before-an-external-effect` came first.

### Security

- An independent review of the port found, before release:
  - The Python Ed25519 verifier accepted forged signatures under a small-order key.
  - A nested token with a duplicate member crashed the gate on Python 3.9–3.11.
  - An unreadable jti file allowed approvals to be replayed.
  - The key-set fetch followed redirects.
  - The job tools were ungated.

  All are fixed, and each has a test that failed first. The small-order forgery is now in the shared vectors.

## 0.10.0 - 2026-10-11

Contract DEC-0039, first part (FAA-20, issue #52): the operator's dashboard session now lives no longer than
the contract allows, and the server enforces it; the probe treats `surfaces.mcp.auth: "delegation"` like `own`.
The contract pin moves to Fabric Agent Contract `main` `8e49fbd` (the DEC-0039 merge, contract PR #30). Bundles
issued under the DEC-0036, DEC-0035, DEC-0033, DEC-0031, DEC-0024, DEC-0021, DEC-0020 and DEC-0019 revisions
stay valid.

### Security

- **Operator sessions end on the server (DEC-0039).** Until now `LoginCodes.session_valid` checked only an HMAC
  and the cookie lived 30 days, so a copied cookie stayed valid until the session key was rotated. Now a
  session ends 12 h after its last use, 7 days after the login code was redeemed however often it is used, on
  `logout`, and when the descriptor token rotates. The cookie carries a signed claim (session id, sign-in time,
  token revision); the code store keeps a record per session (last use, logout), so a cookie with no record is
  refused. Both kits, the same behaviour.

### Changed

- **Every operator signs in once more after the upgrade**: a cookie of the old format is refused. The host does
  it on the page's `401`.
- **A remote service with `MemoryCodeStore` loses its sessions on a deploy** (it already lost its login codes):
  the store now holds the session records. Pass a durable store to keep them.
- **`session_cookie_header` / `remote_session_cookie_header`** (and the Node `sessionCookieHeader` /
  `remoteSessionCookieHeader`) default to `Max-Age` 604800 (7 days), not 30 days.
- **Default contract pin `a83bec6` → `8e49fbd5fbbf230e32c1969cd24ac3c22422f0a5`.** `a83bec6` (DEC-0036) joins
  `SUPPORTED_CONTRACT_COMMITS`. The revisions between (DEC-0037 spend policy, DEC-0038 grant windows,
  DEC-0039 delegation, DEC-0040 Fabric's button) add schemas and optional properties only: the provider
  manifest gains optional cost presets, the governance grant's `effects` may be omitted by a delegation grant,
  and the well-known document gains `auth.delegation` and the `delegation` value of `surfaces.mcp.auth`.
  Every descriptor, well-known document and bundle the kits wrote before stays valid.

### Added

- **`LoginCodes(..., token=, idle_seconds=, max_seconds=, clock=)`** (`{ token, idleSeconds, maxSeconds, clock }`
  in Node): `token` is the descriptor token or a callable returning the current one; the bounds may be
  shortened, and longer values are clamped. **`logout(cookie)`** and **`expired_session_cookie_header(remote=)`**
  (`logout`, `expiredSessionCookieHeader`); `OPERATOR_SESSION_IDLE_SECONDS`, `OPERATOR_SESSION_MAX_SECONDS`.
- **`check_service.py`**: `surfaces.mcp.auth: "delegation"` is checked like `own` — the MCP surface must refuse
  the descriptor token, and the caller rules are `NOT_RUN` (DL-16); rule **`auth.delegation-declared`** (with
  `delegation`, the well-known document names `auth.delegation {issuer, jwks}`); rule
  **`login.session-lifetime`** (the cookie set at sign-in does not outlive 7 days).
- **The sample services** pass `token=` and serve `POST /logout` (a browser write: it needs `X-Fabric-Request`).
- `references/surfaces-and-auth.md`, `remote-placement.md` and `protocol.md` describe the lifetime, logout and
  DL-16. Scenario evals `operator-session-lifetime` and `mcp-auth-delegation` came first.

### Not yet

- Verifying delegation tokens and approvals in the kits (`verifyDelegation` / `verifyApproval`) and Fabric's
  button in the dashboard kit (FB-7) follow in a later release (FAA-20 stays open).

## 0.9.0 - 2026-10-11

The dashboard kit (`fabric-dashboard/0.1`, contract DEC-0036): a Fabric service's dashboard holds inside a
host pane beside the agent console from 360 CSS px up, follows the host's colour scheme and theme, and says
so in its well-known document. The contract pin moves to Fabric Agent Contract `main` `a83bec6` (the
DEC-0036 merge, contract PR #27). Bundles issued under the DEC-0035, DEC-0033, DEC-0031, DEC-0024, DEC-0021,
DEC-0020 and DEC-0019 revisions stay valid.

### Added

- **`building-fabric-services/assets/dashboard-kit/`** (FAA-17): `fabric-dashboard.css` (the workbench token
  layer plus `--edge`; root `min-width: 360px`; fluid grids; navigation that wraps, or folds into a More menu
  with the script; `.fd-scroll` boxes with edge shades, a visible scrollbar and keyboard focus; sticky chrome
  kept within min(120 px, a quarter of the height) by letting the header scroll away), `fabric-dashboard.js`
  (applies the `fabric_appearance` cookie, hides the page's own appearance controls while the host owns
  them, re-applies on cookie change and visibility, folds navigation, names scroll boxes, measures the chrome
  for anchors; CSP-clean), seven reference themes in `themes.json` (graphite, fabric, paper, forest, ocean,
  ember, contrast; light and dark; every pair WCAG 2.2 AA, measured by `test/test_dashboard_kit.py`),
  `kit.json` (version, theme ids, file digests and per-version history) and `demo.html`.
- **`scripts/dashboard_kit.py`** `status | install | build | notice`: `install` never overwrites a copy the
  service changed without `--force`; `build` regenerates the themes from `themes.json`.
- **`scripts/check_dashboard_layout.mjs`**: renders a page in WebKit (or `--browser chromium|firefox`) at the
  floor minus 40 and 360, 480, 768, 1280 px and reports ED-1…ED-5; `--service <id>` signs in with a login
  code and reads the declared `minWidth`. Without Playwright every rule is `NOT_RUN`. It measures a settled
  page: after the load it waits for the page's own requests to finish, and at each width for two frames,
  250 ms and two more frames, so a header that grows when its data arrives is not measured between its new
  size and the kit's reaction to it (seen once on an adopting service's dashboard at 360 px: a false ED-5).
- **`check_service.py` rule `dashboard.declared`** (ED-9): PASS for a valid declaration (and names a newer
  kit), FAIL for an invalid one, NOT_RUN for no dashboard or a legacy one.
- **`dashboard_extension()` / `dashboardExtension()`** in both kits, and `extensions` in `build_well_known` /
  `buildWellKnown` (a dashboard declaration in it is validated). The sample service's dashboard is built on
  the kit and declares it.
- **The plugin's first hook**: `SessionStart` runs `dashboard_kit.py notice`, which prints one line in a
  repository whose dashboard has no kit or an older one and nothing elsewhere; it writes nothing and always
  exits 0. `AGENTS.md` Lifecycle (LC-09) declares it.
- **`references/dashboard-kit.md`**: the rules, the markup, the themes, the declaration, the probes and
  "Upgrading an existing dashboard" (only with the operator's go-ahead). Scenario evals
  `dashboard-in-a-narrow-host-pane`, `dashboard-kit-upgrade-notice`, `dashboard-follows-host-appearance`
  and two trigger queries came first.

### Changed

- **Default contract pin `52da526` → `a83bec6b47776af688402c18efec507143061f68`.** `52da526` (DEC-0035) joins
  `SUPPORTED_CONTRACT_COMMITS`. The revisions between add only the `fabric-dashboard/0.1` profile and
  `service-dashboard-extension.schema.json`; the provider manifest and the MCP, A2A and local-runner
  profiles do not change, and every descriptor and well-known document the kits wrote before stays valid.
- `references/dashboard.md` point 8 sends the page to the kit; `references/protocol.md` names the
  `extensions` dashboard declaration.

## 0.8.3 - 2026-10-10

The contract pin moves to Fabric Agent Contract `main` `52da526` (DEC-0034 and DEC-0035, the operator
channel), so the operator channel proposal is normative under the pin. Bundles issued under the DEC-0033,
DEC-0031, DEC-0024, DEC-0021, DEC-0020 and DEC-0019 revisions stay valid.

### Changed

- **Default contract pin `78b2da0` → `52da526d7cc1e063d74c5b520dbc03d0ace15246`** (FAA-15). `78b2da0`
  (DEC-0033) joins `SUPPORTED_CONTRACT_COMMITS`. The revisions between add the `fabric-operator-channel/0.1`
  profile (DEC-0034, OC-1…OC-13; DEC-0035, OC-14…OC-17 for shared groups), its status schema
  `operator-channel-status.schema.json` and the optional well-known `surfaces.operatorChannel`. Nothing in the
  provider manifest or the MCP, A2A and local-runner profiles changes, and every descriptor and well-known
  document the kits write stays valid; the kits do not serve the channel yet. Checked: `npm test`; both
  compiled-schema arms against clean checkouts at `2ce3922` and `52da526`; descriptors written by the sample
  service (`none` and `launchd`) validate against the new `service-descriptor.schema.json`.
- **The operator channel proposal is no longer "newer than the pin".** `creating-fabric-agents` step 6 and
  `adapting-projects-to-fabric` step 8 cite DEC-0034 under the pin, show the recorded answer as `proposal` in
  the channel status document when the agent serves `surfaces.operatorChannel`, check that document against
  the pinned `operator-channel-status.schema.json`, and keep the channel's runtime rules `NOT_RUN` (the probe
  has no rule for them). For a channel bound in a group shared with other bots they name OC-14…OC-17: silent
  unless addressed; a bare `/command` in a group is not addressed. Scenario evals `operator-channel-proposal`
  changed first.
- **`references/protocol.md`** summarises what the pin carries: the Windows services folder, the `systemd`
  and `task-scheduler` managers, Windows paths and token files (DEC-0032, DEC-0033), and
  `surfaces.operatorChannel` (DEC-0034).

## 0.8.2 - 2026-10-10

The Python service kit runs on Windows and Linux (contract DEC-0032, DEC-0033), and the contract pin moves to the DEC-0033 merge.

### Changed

- **Default contract pin → `78b2da018d2c4bd9ac1bde1dc3b7f1a110a175f5`** (DEC-0032, DEC-0033, FAA-16); the DEC-0031
  merge joins `SUPPORTED_CONTRACT_COMMITS`. Both are additive: new managers, new optional fields, a wider path
  grammar, and SYSTEM or Administrators admitted as a Windows token file's owner.

### Added

- **`fabric_service.py` on Windows** (DEC-0032): the services folder `%LOCALAPPDATA%\passioncode-fabric\services`
  and per-service folders under `%LOCALAPPDATA%`; the instance lock through `msvcrt.locking` on one byte far
  past the pid (released by the OS with the process); token files, descriptors and every kit write carry an
  explicit protected ACL (this user, SYSTEM, Administrators); `read_token` applies service.md "Windows token
  files" — a regular file in the profile, owned by this user, SYSTEM or Administrators (DEC-0033: an elevated
  administrator's files are owned by Administrators, as `windows-latest` showed), every granting ACE on the allow-list, refusal by
  SID; descriptors accept `systemd` (`unit`) and `task-scheduler` (`task`) with the contract's pairing rules,
  Windows paths, and refuse network shares; launchd helpers refuse off macOS instead of calling `os.getuid`;
  the kit's own log and ledger appends open in binary mode. `check_service.py` checks the lock and the
  descriptor's privacy the Windows way.
- **The operator channel proposal (FAA-15).** `creating-fabric-agents` (step 6) and
  `adapting-projects-to-fabric` (step 8) propose an agent's own messenger channel to its
  operator once, when the agent has human stops or `notify: true` events. They list the
  operator's four steps (a bot from @BotFather, its token in the secret store by name, the
  agent's link command, the code typed in the chat), record the answer (`accepted`, `declined`
  or `later`), and never create a bot, store a token or enable the channel themselves. This is
  rule OC-11 of `fabric-operator-channel/0.1` (contract DEC-0034, contract PR #25). It is newer
  than the default pin, so the skills cite it by path and keep channel conformance `NOT_RUN`
  until the pin moves. New scenario evals: `operator-channel-proposal` in both skills.

### Fixed

- **Two calls that do not exist or mean something else on Windows**, found by the first Windows run: the usage
  ledger read its last byte with `os.pread` (absent on Windows, so every `record` raised) — it seeks and reads
  there now; and `check_service.py`'s "state inside a release" rule looked for `/releases/` in a path whose
  separators are backslashes — it reads the path's POSIX form.

### Added (tests)

- **A `windows` job in `validate.yml`** (dispatch, like the others) runs the platform cases on `windows-latest`.

## 0.8.1 - 2026-10-08

The contract pin moves to Fabric Agent Contract `main` `623bf61` (DEC-0025 through DEC-0031); bundles issued
under the DEC-0024, DEC-0021, DEC-0020 and DEC-0019 revisions stay valid. And a fix for `Mcp-Name` values outside
plain ASCII.

### Changed

- **Default contract pin `23f9fda4` → `623bf61358c339cb10297807b3f024b5d9f1f327`** (FAA-14). `23f9fda4` (DEC-0024)
  joins `SUPPORTED_CONTRACT_COMMITS`. The revisions between add only optional surfaces: settings backups and the
  feed token header (DEC-0025), runner routes (DEC-0026, DEC-0029), spending limits in the usage report
  (DEC-0027), activity telemetry (DEC-0030) and devices (DEC-0031). The kits emit none of them yet, which stays
  valid; adopting DEC-0025 and DEC-0027 is FAA-13, runner routes FAA-11. Checked: `npm test`; both compiled-schema
  arms against clean checkouts at `2ce3922` and `623bf61` (11/11); a kit usage report validates against the new
  `service-usage.schema.json`.

### Fixed

- **`Mcp-Name` values outside plain ASCII follow the spec's Base64 sentinel.** MCP 2026-07-28
  Streamable HTTP ("Value Encoding") requires a name or URI with non-ASCII characters, control
  characters, leading or trailing spaces, or the sentinel's own shape to travel as
  `=?base64?<UTF-8 base64>?=`, and a server to decode it before comparing it with the body. Both kits
  sent the raw value and compared the raw header, so such a call was refused by a conforming server
  and a conforming client was refused by ours. `encode_header_value` / `encodeHeaderValue` and
  `decode_header_value` / `decodeHeaderValue` now do both; a malformed sentinel or a raw non-ASCII
  header is refused as `-32020`. Tested with the spec's own five examples in both kits. This is the
  part of PR #24 that FAA-08 had not already shipped.

## 0.8.0 - 2026-10-04

Agents report what they spend (Fabric Agent Contract DEC-0021), and a service may keep its MCP
credential apart from the host's token (DEC-0024). The contract pin moves to the DEC-0024 merge;
bundles issued under the DEC-0021, DEC-0020 and DEC-0019 revisions stay valid.

### Added

- **Usage report in both kits.** `make_usage_receipt` / `makeUsageReceipt` record one model call
  from the provider's own numbers (no prompt, output or caller). `usage_report` / `usageReport`
  build the `service-usage.schema.json` answer: 31 UTC days per provider and model, day totals
  that are the sums of the rows (FAC-SEM-025), and an unknown cost as `null`, never `0`.
  `JsonlUsageLedger` keeps receipts as 0600 JSON lines pruned to the window. A line torn by a
  killed writer is skipped and never glued to the next receipt. The Python and Node twins
  produce the same report from the same receipts (`test/fixtures/usage/receipts.json`).
- `sample_service.py` declares `surfaces.usage` and serves the report behind the token.
- `check_service.py` adds `usage.requires-token` and `usage.report` when a service declares the
  surface.
- `references/usage.md`; SKILL.md Step 5 and the protocol reference name the surface; trigger
  and scenario evals `agent-reports-its-own-spend`.

### Added (DEC-0024)

- **A service may keep its MCP credential apart from the host's token.** When the well-known
  document says `surfaces.mcp.auth: "own"`, `check_service.py` no longer calls MCP with the
  descriptor's token as a caller. It checks that the surface refuses that token
  (`interop.mcp-own-auth`) and leaves the caller rules NOT_RUN with the reason. Before this, two
  services that separate the roles on purpose were reported as `interop.tools-match` FAIL
  (401/403). `references/surfaces-and-auth.md` explains when to do it. The contract pin moves to
  `23f9fda4c05f8a3852246ee98d4f2adf74ed0875`; `9091d3d` joins the supported earlier revisions.

### Fixed

- **MCP 2026-07-28 standard headers.** The probe's MCP calls now send `Mcp-Method`, and `Mcp-Name`
  for `tools/call`. Without them a server on the official 2026-07-28 SDK answers HTTP 400 (seen live
  against a local agent on 2026-10-04: `tools/list failed: HTTP 400 from /mcp`).
  `fabric_interop.McpToolServer.handle(message, headers)` checks them the way the specification
  requires: a mismatch is refused with `-32020` whatever the revision, and a request that declares
  2026-07-28 must carry them. Callers that pass no headers keep the old behaviour.
  `mcp_header_problem` / `mcp_request_headers` are in both kits (Node: `mcpHeaderProblem`,
  `mcpRequestHeaders`). The sample service answers a mismatch with HTTP 400.

### Changed

- Contract pin `df55c8c` → `9091d3d` (lock, scaffolder default, metadata). The supported earlier
  revisions are now a reviewed list of two, `test/validate.py` checks it, and
  `test_contract_revisions` runs against real checkouts of `2ce3922` and `9091d3d`.

## 0.7.0 - 2026-10-04

The service kit meets the organization's
[product lifecycle contract](https://github.com/passioncode-ai/fabric-workspace/blob/main/knowledge/lifecycle.md)
(LC-01…LC-15). Findings F7, F8, F9, F16 of the 2026-10-03 lifecycle audit.

### Fixed

- **An upgrade no longer switches back on a service the operator switched off (LC-14, F7).**
  `launchd_install` called `launchctl enable` on every run. It now reads `launchctl
  print-disabled` and enables only on a first install (no override recorded); a disabled label
  stays disabled and unloaded, its plist is still rewritten, and the answer is
  `{"disabled": true, ...}`. `force_enable=True` is the operator's explicit switch-on.
  Tests: `test_fabric_service_lifecycle.LaunchdInstallTests` (fake `launchctl`, throwaway labels).
- **A duplicate copy under `KeepAlive` no longer respawns every 10 s (LC-03, F8).** A
  launchd-supervised copy (`FABRIC_SERVICE_SUPERVISOR=launchd`, now written by `launchd_plist`)
  backs off in-process on a held lock — 0.5 s doubling to 30 s, 300 s in all — takes over if the
  holder leaves, and exits 75 only then. Started by hand it still exits 75 at once (the contract's
  one-copy rule). Python and Node. Tests: `SupervisedLockTests`, `fabric-service-lifecycle.test.mjs`.
- **Uninstall is symmetric with install (LC-14, F9).** `launchd_uninstall` waits until launchd
  reports the job gone (raises, removing nothing, at its timeout), removes the plist, resets the
  override to `enabled`, and with `purge=True` removes the service's data, logs and cache. It now
  returns a summary dict instead of `None`. Tests: `LaunchdUninstallTests`.
- **The installers leave launcher-managed hub links alone (F16).** `install.sh` and
  `npx @passioncode-ai/fabric-agent-adapter` (even with `--force`) skip a `~/.agents/skills/<name>`
  that is a symlink, naming `npx @passioncode-ai/passioncode@latest update` when it points into
  `~/.passioncode`. Tests: `test_installer.InstallerTests.test_launcher_managed_hub_links_survive_force`,
  `test_install_sh_leaves_launcher_links_alone`.

### Added

- **`Drain` (Python and Node, LC-01, F9):** SIGTERM/SIGINT stops new work (`work()` raises
  `Stopping`), drains in-flight work for 8 s, hands over, and hard-exits (`EXIT_HARD_STOP`, 70)
  2 s later if the hand-over hangs. `sample_service.py` uses it and answers `503` while stopping.
- **`RotatingLog` and `cap_stdout_log` / `capStdoutLog` (LC-12, F9):** JSON-lines log rotated by
  size, 5 × 5 MB, files 0600 in a 0700 directory; the launchd stdout file is capped at start.
- **`prune_releases` / `pruneReleases` (LC-11, LC-15):** keeps the running release and the one
  before it, removes older ones, never removes `current` after a rollback.

### Changed

- **CO-193 contract adoption (source, pending release):** new bundles use the shared
  capability-name schema and accept underscore names. Complete previously issued bundles
  remain checkable at their explicitly supported legacy revision. The checker rejects
  forged locks, revision mismatches and modified checkouts; unavailable dependencies remain
  `NOT_RUN`. This adds no COM runtime, grant or admission authority.
- Align validation triggers with the operator's 2026-09-25 CI policy: replace automatic
  push/PR runs with manual dispatch, retaining the reusable release-validation workflow.
  Existing test jobs and commands are unchanged; no new nightly schedule is asserted.

- `launchd_plist`'s default `ExitTimeOut` is 15 s (was 40): above the drain and its hard exit, so
  launchd's SIGKILL never comes first, and inside LC-01's 10 s quit bound for the service itself.
- `references/lifecycle.md` links the org contract and maps each LC rule to the kit.
- Three scenario evals: `operator-off-survives-upgrade`, `duplicate-under-keepalive`,
  `stop-drains-and-uninstall-is-symmetric`.

## 0.6.3 - 2026-10-04

### Changed

- **Agents and services get every credential from Project Observatory, by name.**
  `building-fabric-services` principle 5: a service takes its provider credentials from the vault
  through `use_secret.py serve` (Project Observatory 0.15.0), never from a copy beside the service;
  a remote service's platform copy is recorded with `vault.py moved`. `creating-fabric-agents`
  carries the same rule for agents from their first commit: no `.env` of their own, no key file
  beside their data, no value in code, configuration or a commit, and `use_secret.py run
  --vault-only` at launch.

## 0.6.2 - 2026-10-03

### Added

- **`building-fabric-services` says how a product behaves under a host lifecycle broker** — the
  always-on per-user service agents ask to start, stop and restart products
  (`references/lifecycle.md`, "Being managed by a host lifecycle broker"): quit through both the
  platform's quit and `SIGTERM`, stay in the background when opened non-activating, keep the
  designated requirement stable, expose honest readiness. Measured on the first broker that
  stops apps: a desktop app that closes its window on `SIGTERM` and keeps running, and one that
  takes focus when launched in the background — both are what this section prevents.

## 0.6.1 - 2026-10-03

### Fixed

- **`check_service.py` no longer fails every online service hosted behind a platform router.**
  `network.host-check` required the service's own `403`, but Heroku, Fly, Render and CDNs route
  by `Host`: a foreign one is answered by the router (`404`/`421`) and never reaches the process.
  For a remote placement that answer now passes, unless its body is the well-known document. The
  Origin and cross-site checks are unchanged — they reach the service and need its `403`. Found on
  the first real online service: 26 PASS and 1 false FAIL before, 0 FAIL after (`guard_verdict`,
  `test/test_fabric_service_remote.py::GuardVerdict`, 4 mutations killed).

## 0.6.0 - 2026-10-02

### Added

- **Online agents and dashboards become Fabric services** — the remote placement of
  `fabric-service/0.1` (Fabric Agent Contract DEC-0019). `building-fabric-services` gains the
  section *Online services — the remote placement* and `references/remote-placement.md`; its
  boundary no longer excludes an online agent, only a hosted product with no agent behind it.
- **Kits (Node and Python, the same rules):** `checkRemoteRequest` / `check_remote_request` (Host,
  Origin, cross-site, a forwarded scheme that is not https), `wellKnownAllowed` /
  `well_known_allowed` (the well-known document only for the token, `401` with an empty body
  otherwise), `remoteSessionCookieHeader` (`__Host-fabric_session`, `Secure`), `MemoryCodeStore`
  and `LoginCodes(null, …, { store, key })` for a service with no durable disk and a session key
  held by its platform, `registerRemote` / `register_remote` (token file 0600 + descriptor on the
  operator's computer), placement-aware `validateDescriptor` and port claims.
- **`scripts/sample-remote-service.mjs`** — a complete online service, with its own TLS or behind
  a platform router.
- **The probe checks a remote service** over TLS with the certificate verified (`--ca-file`,
  `--connect` for tests): `well-known.requires-token`, the guards, events, the single-use login and
  `login.cookie-host-bound`; launchd, lock and loopback rules are `NOT_RUN` with that reason.

### Changed

- **Contract pin** moves from `74d3852` to `2ce3922` (DEC-0019 merged).

## 0.5.7 - 2026-10-01

### Changed

- **A service is scheduled as a standard process.** `launchd_plist` writes `ProcessType Standard`
  instead of `Background`, and `references/lifecycle.md` says why: a background job, `Nice` > 0 or
  low-priority I/O lets macOS starve a service under load for tens of seconds, and every host then
  reports an outage that never happened (measured on 2026-10-01: two services built from the kit
  were reported down more than 30 times in a day while their processes ran without a restart). The
  probe gains a `lifecycle.priority` rule that fails such a plist.
- **Notifications.** `references/events-and-notifications.md` states when to set `notify: true` —
  a decision, a failure, a warning that blocks work — once per episode, with a `subject`, a sentence
  that says what the operator should do and a `link`; questions say so in their kind; a service with
  a descriptor raises no banners of its own. This matches the host rule in Fabric Dashboards
  ADR-0010.
- **Instances.** Step 4 of `building-fabric-services`: a preview or branch instance is uninstalled
  once its check is done instead of running beside `default`.

## 0.5.6 - 2026-10-01

### Changed

- All three skills carry the dashboard handoff procedure: resolve the exact service instance, prefer its native `open_link`, check host availability, and refuse browser fallback after an installed-host failure. Remote viewers require an addressed transport.
- A portable structured-output checker validates native links, confirmed-absence browser fallback and remote-open requests before handoff. It does not open links or grant authority.
- [Evidence](docs/handoffs/2026-10-01-dashboard-links.md) includes regression fixtures and supplied-context Claude Code/Codex comparisons. Automatic skill activation across all sessions is not established.

## 0.5.5 - 2026-10-01

### Changed

- **Docs.** The skills' `compatibility` line, the skill card and `adapting-projects-to-fabric` no
  longer call the Fabric Agent Contract checkout private: the contract is a public repository
  since 2026-09-30. `AGENTS.md` points at the knowledge base's `knowledge/rules.md` (Fabric
  ADR-0093) instead of the moved org-index `RULES.md`. The README's MCP quick start is
  re-verified from the npm package. No script, kit or probe changes.

## 0.5.4 - 2026-10-01

### Changed

- **Contract pin** moves from `2ea54f7` to `74d3852`: Fabric Agent Contract was re-created as a
  public repository with one clean history on 2026-09-30, so the old commit no longer exists.
  Its schemas, source and fixtures are byte-identical to `2ea54f7` (`git diff --stat` over
  `schemas src fixtures` is empty); no kit, probe or skill behaviour changes.

## 0.5.3 - 2026-09-30

Follows Fabric ADR-0092 (the organization's licence) and the PassionCode.ai repository
standard (fabric-workspace `knowledge/repository-standard.md`). No behaviour of the skills'
scripts, the kits or the probe changes; the contract pin stays at `2ea54f7`.

### Changed

- **License.** From this version the adapter is open source under the GNU AGPL-3.0, or
  available under a commercial license from PassionCode.ai (contact@passioncode.ai): SPDX
  `AGPL-3.0-only OR LicenseRef-PassionCode-Commercial` in `package.json`, the marketplace entry,
  the plugin manifest and the three skills' `license:`. `LICENSE` is the unmodified AGPL-3.0 text
  and `COMMERCIAL-LICENSE.md` is new; both, with `CLA.md`, are byte for byte the knowledge base
  templates and now ship in the npm package. Versions v0.4.3 to v0.5.2 stay under PolyForm
  Noncommercial or Internal Use, and v0.4.2 and earlier under MIT.
- **The skills send a PassionCode.ai repository to the repository standard.**
  `creating-fabric-agents` (step 2), `adapting-projects-to-fabric` and `building-fabric-services`
  (a new section each) name the licence files, the README quick start with a verified MCP call,
  `AGENTS.md` read-first and `CLAUDE.md` `@AGENTS.md`; an agent someone builds for themselves is
  outside the standard, and its licence is its owner's choice.
- **README** follows the standard: the first paragraph says what the adapter is and that it
  works without Fabric; `## Quick start for a new teammate` (Install, Configure, MCP, Develop)
  replaces "Install", "Verify one service" and "Validate this repository", and its MCP step was
  run with a real client (Claude Code 2.1.285, `--strict-mcp-config`, a temporary config).
- **AGENTS.md** opens with the knowledge base *Read first* block and closes with *After work*.

### Added

- `test/validate.py` fails a tree whose `LICENSE`, `COMMERCIAL-LICENSE.md` or `CLA.md` differs
  from the template by one byte, whose README still states the retired licence or lacks the
  licensing wording, whose package does not ship the licence files, or whose skill drops the
  repository-standard paragraph; each rule was watched failing on a planted copy
  (`test/test_validate.py` `LicenseTests`, `RepositoryStandardTests`).

## 0.5.2 - 2026-09-30

Follows Fabric Agent Contract DEC-0018. **Contract pin** moves from `9cd778e` to `2ea54f7`.

### Fixed

- **Real clients could not connect to a kit-built MCP surface.** Claude Code 2.1.285 opens
  every HTTP server with `initialize`; `McpToolServer` answered `-32601`, so the client marked
  the server `failed` before calling `tools/list`. Every test drove the dispatcher directly,
  so none saw it. It now answers `initialize` (echoing a supported protocol version) and
  `ping`, and the sample answers `GET /mcp` with 405.
- **Every tool's `outputSchema` is rooted at `type: object`** (DEC-0018, FAC-SEM-023): the job
  union is `{type: object, oneOf: [envelope, handle]}` in both kits, `tool_for_capability` /
  `toolForCapability` and `McpToolServer.add_tool` refuse any other root, and the probe gains
  `interop.output-schema-object`, which FAILs a tool whose root is not type object.

### Added

- `test/test_real_client.py`, opt-in (`FABRIC_REAL_CLIENT=1`): the sample service listed by
  the installed `claude` CLI, in a throwaway directory with `--strict-mcp-config`, stopped at
  its init event before any model call.

## 0.5.1 - 2026-09-30

Aligns the kits, the probe and the provider writer with the contract owner's rulings,
Fabric Agent Contract DEC-0017. **Contract pin** moves from `a22dea3` to `9cd778e`.

### Changed

- **A job's result is the full result envelope** (OQ-0002): `result_envelope` /
  `resultEnvelope` now build the contract's `result.schema.json` shape — `id`,
  `contractVersion`, `outcome`, `artifacts`, `createdAt`, `producer` beside the four
  collections, `output` and `usage` — and refuse `succeeded` with unverified claims
  (FAC-SEM-001). `outcome` and `producer` are new required arguments.
- **The envelope carries its trace** (OQ-0003): `trace: {traceparent}`, authoritative for
  a stored result. `JobStore.complete` fills it from the job's span and refuses an envelope
  that names another span; `fabric.job.get` answers with the envelope's traceparent in
  `_meta`, so the two always agree (FAC-SEM-022).
- **A job-backed tool serves `oneOf[result envelope, job handle]`** (OQ-0006):
  `tool_for_capability` / `toolForCapability` wrap the output schema with
  `job_tool_output_schema` / `jobToolOutputSchema` for a job capability, so
  `structuredContent` always conforms; the manifest keeps the pure schema. The probe's
  `interop.tools-match` expects the union for a job capability.
- **Provider entries name their provider by URI** (OQ-0001): `fabric_provider.py` requires
  `providerId` (`--provider-id`), refuses an entry whose manifest does not resolve or whose
  `provider.id` differs, and `validate` checks that the file is named `<id>.json`.

## 0.5.0 - 2026-09-30

### Added

- **`fabric-interop/0.1` in the kits** (Fabric Agent Contract DEC-0016).
  `building-fabric-services/scripts/fabric_interop.py` and its Node twin
  `fabric-interop.mjs`: W3C trace context (`child_traceparent`, `trace_ids`), a
  capability served as the MCP tool of its name with annotations from its effect,
  durable jobs (`JobStore`: ids survive a restart, terminal states never change,
  `unknown-job` for an unknown id), the result envelope with `usage`, and elicitations
  (a titled single-select in form mode, URL mode for secrets; form mode refuses a
  secret field). Python also ships `McpToolServer`, a minimal `tools/list` /
  `tools/call` dispatcher with `fabric.job.get` and `fabric.job.cancel` built in.
- Events carry `traceId` and `spanId` as a pair (`make_event`, `makeEvent`).
- The sample service serves MCP at `/mcp`: `sample.echo`, and `sample.draft`, a job
  that stops for a title choice and completes with a traced result. `register` writes
  its manifest and schemas and points the descriptor's `fabricManifest` at it.
- The probe `check_service.py` gains seven `interop.*` rules: manifest link (G-07),
  capability list, tools equal to the manifest (FAC-SEM-017), job tools, unknown job,
  trace propagation and event trace pairs. It calls only `tools/list` and
  `fabric.job.get` for a made-up id.
- `adapting-projects-to-fabric/scripts/fabric_provider.py`: writes, validates and
  removes `fabric-provider/0.1` entries for agents that are not services — argv only,
  env values as `secret-ref:` references, never the id of an existing service.
- `adapt_project.py scaffold --job` writes the capability's interop block; an `mcp`
  capability now requires the tool of its own name instead of `tool:replace-me`, and
  `check` refuses a malformed interop block.
- Skills teach it: `building-fabric-services` gains `references/interop.md`,
  `adapting-projects-to-fabric` gains `references/provider-entry.md` and step 4b, and
  `creating-fabric-agents` starts new agents on it. Trigger and scenario evals added
  first.

### Changed

- **Contract pin** moves from `a5a2709` to `a22dea3` (fabric-agent-contract `main`,
  AR-1: interop, provider entries, runner catalogue, pipelines). The provider profiles
  and every existing schema field are unchanged; the contract added schemas and
  optional fields only (DEC-0016). **One pin**: `fabric-contract.lock.json`, and
  `test/validate.py` fails any live file that names another contract revision (G-11).
- The README has a newcomer path that starts the sample service and probes it.

## 0.4.3 - 2026-09-29

### Changed

- **License.** The adapter is now source-available under
  `PolyForm-Noncommercial-1.0.0 OR LicenseRef-PolyForm-Internal-Use-1.0.0`, with a
  commercial license on request (contact@passioncode.ai). Versions up to and including
  v0.4.2, on GitHub and on npm, were released under MIT and remain available under it. The manifests, the three skills' `license:` and the README say the
  same; contributions come in under `CLA.md`, which the new PR template asks for.
  `test/validate.py` fails a tree that slips back to MIT.
- Author and marketplace owner are PassionCode.ai (`https://passioncode.ai/`).
- **Contract pin** moves from `20a818e` to `a5a2709` (fabric-agent-contract `main`), the
  commit `building-fabric-services` already pinned. Between the two the provider
  profiles are unchanged — only the `fabric-service/0.1` extension was added — and
  `adapt_project.py check --contract` gives the same verdicts for an MCP, an A2A and a
  local-runner bundle at both commits (declaration shape PASS). One pin for all three
  skills.
- `creating-fabric-agents` hands the agent's own loop to `agent-orchestrator`, its
  eval suite to `agent-evals` (agent-stack) and plugin packaging to `make-skill`;
  `adapting-projects-to-fabric` sends wire-level MCP/A2A questions to `agent-interop`.

### Fixed

- The installer's help names the launcher by its npm org name,
  `npx @passioncode-ai/passioncode@latest update`; the bare `passioncode` is not ours.
- A distributed eval named a personal agent as its example service; the
  `building-fabric-services` evals use `example-agent`, and its description says "a
  macOS machine" instead of naming whose.

## 0.4.2 - 2026-09-29

- Kit: `LoopbackHTTPServer`, a `ThreadingHTTPServer` whose bind asks no resolver.
  `http.server` calls `socket.getfqdn()` between `bind()` and `listen()`; on a macOS
  CI runner that held a service's port bound but silent for over 20 seconds. The
  sample service and the skill's startup order use it, and the skill names the trap.
- Kit: a garbled pid file (for example a superscript digit) now reads as "no pid"
  instead of raising `ValueError` while naming the holder of a lock.

## 0.4.1 - 2026-09-29

### Fixed

- `building-fabric-services` could not be loaded by a strict YAML reader: its
  front-matter `description` was an unquoted plain scalar holding `: `
  ("fabric-service/0.1 extension: which surface", line 3, column 493), which YAML
  rejects with "mapping values are not allowed here". Claude Code read it
  leniently, so the plugin worked, but an agent reading the skill from
  `~/.agents/skills` could drop it. The description is now a folded block
  scalar (`>-`) with the exact same text (927 characters).
- The validator could not see that class of defect: `test/validate.py` now
  parses every SKILL.md front matter strictly (standard library only) and
  rejects what a YAML reader rejects in an unquoted value — `: ` or a trailing
  `:`, ` #` (a comment that silently truncates the value), a leading indicator
  character, a duplicate key, an unclosed quote, an undeclared multi-line
  value — with the line and column. `test/test_validate.py` plants each case.
  `validate.py --frontmatter <SKILL.md ...>` checks installed copies anywhere.
- The release smoke test looked for `~/.claude/skills`, where the installer has
  not written since 0.4.0, so it would fail on the first release that ran it.
  It now checks all three skills in `~/.agents/skills`, that `~/.claude/skills`
  stays untouched, and that the installed front matter parses strictly.
- `SKILL-CARD.md` versions and the release smoke paths joined the validator's
  sync checks.

## 0.4.0 - 2026-09-28

- Add the `building-fabric-services` skill for the `fabric-service/0.1` local
  service extension (Fabric Agent Contract DEC-0015): surface choice (MCP
  streamable HTTP, CLI, A2A), token and one-time login, state and cache
  directories, one copy per machine, launchd, descriptor, well-known document,
  events feed and notifications.
- Ship reference kits in Python (`fabric_service.py`) and Node
  (`fabric-service.mjs`) whose instance locks exclude each other, a complete
  `sample_service.py`, and `check_service.py`, a live conformance probe that
  reports PASS, FAIL or NOT_RUN per rule.
- `creating-fabric-agents` now routes an agent that runs as a service through
  the new skill.
- Fix the installer shadowing its own plugin: `npx @passioncode-ai/fabric-agent-adapter`
  and `install.sh` now install into the agents hub `~/.agents/skills`; a plain
  copy into `~/.claude/skills` is refused while the plugin is installed, and
  `--prune-shadow` moves existing shadowing copies aside.

## 0.3.1 - 2026-08-27

- Fix the executable bit on `bin/fabric-agent-adapter.js` and `install.sh`: the
  packed tarball shipped them non-executable, so `npx` failed with exit 126.
  Caught by the release workflow's own packed-tarball smoke — the gate this
  release added, doing its job on its first run.

## 0.3.0 - 2026-08-27

- Ship the npm channel: the package is `@passioncode-ai/fabric-agent-adapter`,
  an installer CLI (`bin/fabric-agent-adapter.js`) plus the plugin tree, with
  `install.sh` as the POSIX fallback.
- Add toggleable release automation (`release.yml`): a `v*` tag runs validate,
  checks tag reachability and version sync, cuts the GitHub release from the
  CHANGELOG section, smoke-tests the packed tarball from a clean cwd (the
  repository is private, so the tarball — not `npx github:` — is the artifact
  under test), and publishes to npm with provenance. Armed by RELEASE_ENABLED
  and PUBLISH_NPMJS repository variables.
- Extend the validator: package.json joins the version sync, the files
  whitelist and scoped-access rules are checked, and the new files are required.

## 0.2.0 - 2026-08-27

- Add the `creating-fabric-agents` skill: the intake grill (capability, named
  consumer, workflow-or-agent, profile, effect and tenancy declarations), the
  knowledge intake whose recorded traps become planted eval fixtures, skeleton
  and scaffold reuse of the pinned contract machinery, two-clock evals, and the
  canary-binding expectation in the conformance report.
- Point the adapting skill's boundary at its new sibling for greenfield requests.
- Rework the repository validator for multiple skills with per-skill trigger and
  scenario evals.

## 0.1.0 - 2026-08-27

- Add the `adapting-projects-to-fabric` skill.
- Add evidence-based MCP, A2A, and local-runner profile selection.
- Add a standard-library project inspector, non-destructive scaffolder, and checker.
- Add contract pinning and independent conformance gate reporting.
- Add trigger/scenario evals, unit tests, repository validator, and plugin packaging.
