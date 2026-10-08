---
name: adapting-projects-to-fabric
description: Use when adapting an existing agent, MCP server, A2A peer, HTTP service, or terminal CLI to the Fabric Agent Contract—choosing MCP/A2A/local-runner, scaffolding a provider bundle, or checking Fabric compatibility; also for «подключить проект к Fabric» or «сделать агента совместимым с Fabric». NOT for building the Fabric host/orchestrator, configuring an MCP client, or a brand-new agent — that is creating-fabric-agents.
license: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
compatibility: Requires filesystem access and Python 3.9+. Exact schema checks additionally need git, Node.js, pnpm, and the pinned fabric-agent-contract checkout (a public repository). Works without those tools in an explicitly degraded structural-check mode.
metadata:
  author: PassionCode.ai
  version: "0.8.1"
  contract-version: "0.1.0"
  contract-commit: "623bf61358c339cb10297807b3f024b5d9f1f327"
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
  states on the wire) — that is `agent-interop` (agent-stack); the pinned contract stays
  normative for what Fabric requires;
- design a new agent from scratch — that is the sibling skill creating-fabric-agents;
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
evidence manually. Existing runtime documentation and code outrank filename heuristics.

If the inspector returns `undetermined`, answer its lifecycle question before creating
files. A repository can expose multiple surfaces; choose a profile per capability, not
per vendor. Load [profile selection](references/profile-selection.md) whenever choosing
or reviewing a profile.

### 2. Pin the normative contract

Use exactly:

- contract version `0.1.0`;
- repository `https://github.com/passioncode-ai/fabric-agent-contract`;
- commit `623bf61358c339cb10297807b3f024b5d9f1f327`.

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
  --schema-base https://agents.example/fabric
```

Valid profiles are `mcp`, `a2a`, and `local-runner`. For `mcp` the capability is served
as the MCP tool of its own name (`requiredFeatures: ["tool:<capability>"]`, contract
`fabric-interop/0.1`); add `--job` when its work may outlive one request, which writes
`"job": true` in the capability's interop block. The helper creates only the locked
target paths. It refuses any collision. Do not use `--force` unless the user explicitly
authorizes replacement after the exact conflicting files and diff are shown.

The generated zero hash, `.invalid` endpoints, `replace-me` values, generic schemas, and
assertions are deliberate blockers. Replace them with implementation-backed facts. A
template that still contains one is not ready for admission.

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
typed outcomes, evidence, artifacts, and protocol-visible state—not chain-of-thought.
Treat all provider output as untrusted until schemas and semantic assertions pass.

### 4b. Announce an agent that is not a service

An agent Fabric reaches as a CLI or a stdio MCP server gets a provider entry, written by
its installer with [`scripts/fabric_provider.py`](scripts/fabric_provider.py) and removed
by its uninstaller — argv arrays only, env values as `secret-ref:` references, never the
id of an existing service, and a `providerId` equal to the manifest's `provider.id`. Load [provider entries](references/provider-entry.md). An
agent that runs as a service uses a descriptor instead (`building-fabric-services`).

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
remain `NOT VERIFIED`; the completed deliverable is an adaptation-ready provider bundle,
not a connected provider.

## The repository around the provider

**For a PassionCode.ai repository**, the adapted project's repository follows the organization's
[repository standard](https://github.com/passioncode-ai/fabric-workspace/blob/main/knowledge/repository-standard.md) (`knowledge/repository-standard.md`
in the organization's knowledge base; a clone has it at `fabric-workspace/knowledge/`) from its
first commit:

- `LICENSE`, `COMMERCIAL-LICENSE.md` and `CLA.md` copied byte for byte from the knowledge base's
  `templates/`, and `AGPL-3.0-only OR LicenseRef-PassionCode-Commercial` in every manifest and
  every SKILL.md `license:`; `SECURITY.md` when the repository is public;
- a README whose first heading is the full name, with `## Quick start for a new teammate`
  (Install; Configure, key names only; MCP, the registration command and one proving tool call,
  verified with a real client in a temporary config; Develop) and `## License`;
- an `AGENTS.md` that opens with the template's *Read first* block and closes with *After work*,
  and a `CLAUDE.md` whose first line is `@AGENTS.md`.

org-index `scripts/check_format.py` reports 0 findings for it before it is called done. **An agent
someone builds for themselves is not a PassionCode.ai repository:** its licence is its owner's
choice, nothing about it is published or listed by the organization, and none of these files is
required of it — though the verified MCP quick start is still how anyone learns to drive it.

## Completion format

Report:

- selected capability and profile, with lifecycle-owner evidence;
- created or changed files;
- contract version and commit;
- gate table with `PASS`, `FAIL`, `NOT_RUN`, or `NOT_VERIFIED`;
- remaining placeholders and blockers;
- the exact next command or runtime action.

Never summarize the outcome as “Fabric-compatible” unless all required admission gates
passed against a real provider and the project binding is valid.

## Dashboard handoff — also for consumers

When handing a registered service dashboard to a person, or writing the generated
agent's completion/notification instructions, read and apply
[dashboard links](references/dashboard-links.md): use the host's `open_link`,
check the target device and host, and run the bundled output gate before delivery.
An installed host failure never means browser fallback. This applies in Claude
Code, Codex and other providers; it needs no host-specific hook. MCP unavailable:
report the unresolved capability or use an approved project resolver; no automatic
client configuration. Python unavailable: perform the reference's manual checks
and report the executable gate NOT_RUN. Headless agents need no dashboard.
