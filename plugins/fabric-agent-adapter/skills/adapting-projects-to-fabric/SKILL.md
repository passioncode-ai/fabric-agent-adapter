---
name: adapting-projects-to-fabric
description: Use when adapting an existing agent, MCP server, A2A peer, HTTP service, or terminal CLI to the Fabric Agent Contract (choosing MCP/A2A/local-runner, scaffolding a provider bundle, or checking Fabric compatibility); also for «подключить проект к Fabric» or «сделать агента совместимым с Fabric». NOT for building the Fabric host/orchestrator, configuring an MCP client, a brand-new agent (creating-fabric-agents), running an agent as a local or online Fabric service with a dashboard (building-fabric-services), or a coding session working through Fabric, its board or claims, «подключись к Fabric» (working-with-fabric).
license: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
compatibility: Requires filesystem access and Python 3.9+. Exact schema checks additionally need git, Node.js, pnpm, and the pinned fabric-agent-contract checkout (a public repository). Works without those tools in an explicitly degraded structural-check mode.
metadata:
  author: PassionCode.ai
  version: "0.44.0"
  contract-version: "0.1.0"
  contract-commit: "bfa9a67aa3c6cb808c093e7d83cd59799f1ee7d0"
---

# Adapting projects to Fabric

Turn an existing stable interface into a proposed Fabric provider bundle, then prove
only the compatibility gates for which receipts exist. The Fabric Agent Contract is
normative; this skill is an authoring workflow pinned to one immutable revision.

## Boundary

Use this skill to adapt or assess a provider project. Do not use it to:

- design the Fabric host, registry, scheduler, admission service, or project binding runtime;
- add an MCP server to Claude Code, Codex, or an agent gateway;
- answer wire-level MCP or A2A questions (transports, sessions, auth handshakes, task
  states on the wire): that is `agent-interop` (agent-stack); the pinned contract stays
  normative for what Fabric requires;
- design a new agent from scratch: that is the sibling skill `creating-fabric-agents`;
- run the agent as a resident service with a dashboard, a descriptor and launchd: that is
  `building-fabric-services`;
- work in a project through Fabric from a coding session (registering `fabric-mcp`, the board,
  claims): that is `working-with-fabric`;
- claim admission merely because generated files or a valid manifest exist.

If the project has only a browser interface and no stable API, MCP/A2A surface, or CLI,
stop with that missing prerequisite. Browser automation is not a base Fabric profile.

## Required inputs

Establish these values from the request or target repository:

- project root;
- the one capability being adapted;
- stable provider and capability URIs;
- who owns the task lifecycle;
- the interface Fabric can actually reach;
- expected inputs, outputs, effects, data classes, and safe probe behaviour;
- a public or private immutable base URI for published schemas and fixtures.

Do not ask for all fields before inspecting. Discover safe facts first and ask only
for decisions that remain material. Never request or copy secret values into the bundle.

## Workflow

### 1. Inspect without execution

Resolve this skill's directory and run:

```bash
python3 <skill-dir>/scripts/adapt_project.py inspect <project-root> --json
```

The inspector samples repository files but does not execute the project. Verify its
evidence manually. Existing runtime documentation and code outrank filename heuristics. A
client configuration (`.mcp.json`, an `mcpServers` block) lists servers the project calls, not one
it serves: inspect reports it as `mcp-client-config` and asks instead of choosing `mcp`.

If the inspector returns `undetermined`, answer its lifecycle question before creating
files. A repository can expose multiple surfaces; choose a profile per capability, not
per vendor. Load [profile selection](references/profile-selection.md) whenever choosing
or reviewing a profile.

### 2. Pin the normative contract

Use exactly:

- contract version `0.1.0`;
- repository `https://github.com/passioncode-ai/fabric-agent-contract`;
- commit `bfa9a67aa3c6cb808c093e7d83cd59799f1ee7d0`.

This is the default for new bundles. When checking an issued legacy bundle, preserve its
explicit supported lock and use that exact clean checkout. Never silently upgrade or
downgrade it. Unknown repository/version/SHA locks and mismatched checkouts fail; missing
dependencies remain `NOT_RUN`. Capability names may contain underscores at this default
revision; declaring a COM name does not confer a grant, admission or wider authority.

Read the pinned contract's guide
`docs/guides/connecting-compatible-agents.md`, the selected profile specification, and
the referenced JSON Schemas before implementing protocol details. If the contract checkout
is unavailable, continue only through local structure and mark exact schema validation
`NOT_RUN`; do not reconstruct missing normative rules from memory.

### 3. Scaffold the provider bundle

Load [provider bundle](references/provider-bundle.md) before creating or mapping files.
Then run one explicit profile command:

```bash
python3 <skill-dir>/scripts/adapt_project.py scaffold <project-root> \
  --profile mcp \
  --provider-id https://agents.example/providers/example \
  --provider-name "Example provider" \
  --capability-id https://agents.example/capabilities/example \
  --capability-name example.run \
  --schema-base https://agents.example/fabric \
  --effect draft
```

Valid profiles are `mcp`, `a2a`, and `local-runner`. For `mcp` the capability is served
as the MCP tool of its own name (`requiredFeatures: ["tool:<capability>"]`, contract
`fabric-interop/0.1`); add `--job` when its work may outlive one request, which writes
`"job": true` in the capability's interop block. The helper creates only the locked
target paths. It refuses any collision.

`--effect` is required and never defaulted: the capability's class (`none`, `draft`, `publish`, `send`, `reply`,
`charge`, `delete`, `merge`, `deploy`, `change-policy`), read from what the code does or asked of the author. Choose
`--idempotency required|supported|none` for an external effect on purpose. When a run's cost varies, give the
launcher fixed options (DEC-0037): `--cost-preset ID MAX_USD LABEL` per option and `--default-cost-preset ID`; the
amounts come from the author or measured runs, never invented. Pass what the author knows so it is not written as a
scaffold default: `--data-class` (repeat), `--created-by URI`, `--identity-method`, `--probe-assertion` (repeat).

On a collision run `scaffold --dry-run` first: it writes nothing and prints the planned writes and a unified diff of
each existing file. Use `--force` only when the user authorizes replacing exactly those files.

Every value the scaffold invents is a sentinel that `check` names: the zero hash, `.invalid` endpoints,
`replace-me` values, `urn:fabric:adapter:author`, the generic schemas (marked `fabric-adapter-template`), the
generic fixture and assertions, and each value listed under the manifest's `urn:fabric:adapter:template`
extension (the defaulted `dataClasses`, a defaulted `tls` identity method). Replace each with an
implementation-backed fact, then remove it from that list and the block when it is empty. While one remains,
`readyForAdmission` is false.

### 4. Implement the adapter seam

Preserve the chosen ownership boundary:

- A2A maps the provider's remote task, progress, artifact, cancellation, and terminal
  states; Fabric does not take over its internal loop.
- MCP exposes bounded tools/resources/prompts while Fabric owns planning and retries.
  The served tool's name, input and output schemas equal the manifest's (FAC-SEM-017);
  long work returns a job handle and serves `fabric.job.get` / `fabric.job.cancel`; a
  question for a person is a form-mode choice, a secret goes through URL mode; every call
  runs as a child span of `_meta.traceparent`. The kit for all of it is
  `building-fabric-services`'s `scripts/fabric_interop.py`.
- Local runner maps typed input, executable identity, result location, cancellation,
  heartbeat, and partial results without relying on ambient accounts.

Keep model selection and provider-internal reasoning outside the Fabric contract. Expose
typed outcomes, evidence, artifacts, and protocol-visible state, not chain-of-thought.
Treat all provider output as untrusted until schemas and semantic assertions pass.

### 4b. Announce an agent that is not a service

An agent Fabric reaches as a stdio MCP server, or as an MCP server on a loopback URL that is not
a service, gets a provider entry, written by its installer with
[`scripts/fabric_provider.py`](scripts/fabric_provider.py) and removed by its uninstaller: argv
arrays only, env values as `secret-ref:` references, never the id of an existing service, and a
`providerId` equal to the manifest's `provider.id`. Load [provider entries](references/provider-entry.md).
A provider entry only describes an MCP server: a CLI that does not speak MCP gets no entry; it is
announced by its `local-runner` manifest (step 3). An agent that runs as a service uses a
descriptor instead (`building-fabric-services`).

### 5. Make probes safe and meaningful

For each capability, create at least one bounded fixture that:

- can run repeatedly;
- has an explicit timeout;
- cannot publish, charge, message real recipients, or mutate production;
- validates the declared output shape;
- tests a semantic property a fake or wrong implementation would fail;
- preserves a typed partial/stopped result on timeout or cancellation.

A transport success is not semantic success. Assertions such as “returns JSON” are too
weak; assert the capability's intended meaning and evidence obligations.

### 6. Run independent checks

First run local structure:

```bash
python3 <skill-dir>/scripts/adapt_project.py check <project-root> --json
```

When the exact contract checkout and dependencies are available, run:

```bash
python3 <skill-dir>/scripts/adapt_project.py check <project-root> \
  --contract /path/to/fabric-agent-contract --json
```

The local check also refuses two lifecycle faults (LC-19, LC-21): a Claude Code plugin in
the project that declares a stdio MCP server (it starts in every session that enables the
plugin; serve it over HTTP from one resident process or register it at project scope), and a
credential in a launch argument or a URL query, where every process and every log can read it.
Fix both at their cause; never weaken the check.

Load [verification](references/verification.md) before interpreting or publishing the
result. Fix every local error. Fix every placeholder warning or record why the bundle is
still a draft. Do not convert `NOT_RUN` or `NOT_VERIFIED` to `PASS` without the named
runtime receipt.

### 7. Update the conformance report

Update `fabric/FABRIC-CONFORMANCE.md` with dated receipts for:

1. declaration shape;
2. exact protocol negotiation;
3. bounded semantic probes;
4. project-binding readiness.

Include commands and exit codes, immutable endpoint or artifact identities, and explicit
unverified surfaces. If live Fabric admission/runtime does not yet exist, the last gates
remain `NOT_VERIFIED`; the completed deliverable is an adaptation-ready provider bundle,
not a connected provider.

### 8. Propose the operator channel

If the agent has a human stop (a choice, an approval, a confirmation) or emits `notify: true`
events, propose its operator channel (`fabric-operator-channel/0.1`, OC-11) to the operator once,
now, as [the operator channel and the repository standard](references/operator-channel-and-repository.md)
describes: the operator's four steps, the answer recorded and never asked again, and the bot, the
token and enabling the channel left to the operator. An agent with neither stops nor notify events
skips this step.

## The repository around the provider

**For a PassionCode.ai repository**, the adapted project's repository follows the organization's
repository standard (`knowledge/repository-standard.md`) from its first commit: the licence files,
the README quick start verified with a real client, `AGENTS.md` and `CLAUDE.md`, listed in the
shared reference above. An agent someone builds for themselves is not a PassionCode.ai repository:
its licence is its owner's choice and none of those files is required of it.

## Completion format

Report:

- selected capability and profile, with lifecycle-owner evidence;
- created or changed files;
- contract version and commit;
- gate table with `PASS`, `FAIL`, `NOT_RUN`, or `NOT_VERIFIED`;
- remaining placeholders and blockers;
- the operator channel answer (step 8), or why it was skipped;
- the exact next command or runtime action.

Never summarize the outcome as “Fabric-compatible” unless all required admission gates
passed against a real provider and the project binding is valid.

## Dashboard handoff: also for consumers

When handing a registered service dashboard to a person, or writing the generated agent's
completion or notification instructions, read and apply [dashboard links](references/dashboard-links.md)
and run its output gate before delivery, in any host. Headless agents need no dashboard.
