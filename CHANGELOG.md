# Changelog

## Unreleased

### Fixed

- **The probe speaks MCP 2026-07-28 Streamable HTTP headers.** `check_service.py` sent no
  `Mcp-Method` or `Mcp-Name`, so a server that validates them (as the spec requires of a server
  that reads the body, and as SDK v2 servers do) answered `400 HeaderMismatch` (`-32020`) and the
  probe failed `interop.tools-match` and `interop.unknown-job` against a healthy service. Every
  MCP POST now derives the headers from its own JSON-RPC body: `Mcp-Method` from `method` on
  requests and notifications, `Mcp-Name` from `params.name` (`tools/call`, `prompts/get`) or
  `params.uri` (`resources/read`), with the spec's `=?base64?…?=` encoding for a value that is not
  plain header-safe ASCII.
- **Legacy servers.** A 400/404/405 whose body is not a modern JSON-RPC error (`-32020`, `-32021`,
  `-32022`, `-32601`) marks an initialize-based server (2025-11-25 and earlier): the probe opens a
  session with `initialize` and `notifications/initialized`, sends `Mcp-Session-Id` and the
  negotiated `MCP-Protocol-Version`, keeps that era for the rest of the run and closes the session
  with `DELETE`. A failed handshake leaves no session behind. A modern error is reported with its
  code and message and never causes a fallback. Modern requests now carry
  `io.modelcontextprotocol/clientInfo`.
- **A pass through the fallback is visible.** The new rule `interop.mcp-revision` names the era
  that answered and the refusal that caused the fallback. It FAILs when only the legacy session
  worked but the manifest declares MCP 2026-07-28, so a dual-era service whose modern path is
  broken no longer gets PASS on every interop rule. A service whose `mcp` capabilities declare
  only a legacy revision passes. A service that declares no revision gets NOT_RUN.
- **Empty answers fail.** A 200 without a JSON-RPC object (an empty body, an event stream with no
  `data:` line, or non-object JSON) FAILs the rule that asked. Before this fix such an answer
  dropped five interop rules on `tools/list`, or crashed the probe on `tools/call`.
- `references/interop.md` ("What the probe checks") documents the headers, the fallback and the
  new rule.
- Regression: `test/test_mcp_probe_headers.py` (25 tests) runs the probe against local fixtures:
  - a strict server that refuses absent or mismatched headers
  - a legacy session server
  - a dual-era server whose modern path is broken
  - a server that refuses every version
  - servers that answer 200 with an empty body
  - a legacy server whose handshake fails

  It also pins the spec's encoding table.

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

