# Changelog

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
  size and the kit's reaction to it (seen once on the brand board at 360 px: a false ED-5).
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
