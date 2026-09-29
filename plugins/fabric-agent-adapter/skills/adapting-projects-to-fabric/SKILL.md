---
name: adapting-projects-to-fabric
description: Use when adapting an existing agent, MCP server, A2A peer, HTTP service, or terminal CLI to the Fabric Agent Contract—choosing MCP/A2A/local-runner, scaffolding a provider bundle, or checking Fabric compatibility; also for «подключить проект к Fabric» or «сделать агента совместимым с Fabric». NOT for building the Fabric host/orchestrator, configuring an MCP client, or a brand-new agent — that is creating-fabric-agents.
license: MIT
compatibility: Requires filesystem access and Python 3.9+. Exact schema checks additionally need git, Node.js, pnpm, and the pinned private fabric-agent-contract checkout. Works without those tools in an explicitly degraded structural-check mode.
metadata:
  author: passioncode-ai
  version: "0.4.2"
  contract-version: "0.1.0"
  contract-commit: "20a818e648a4c09a60df0126d11626922e8b9094"
---

# Adapting projects to Fabric

Turn an existing stable interface into a proposed Fabric provider bundle, then prove
only the compatibility gates for which receipts exist. The Fabric Agent Contract is
normative; this skill is an authoring workflow pinned to one immutable revision.

## Boundary

Use this skill to adapt or assess a provider project. Do not use it to:

- design the Fabric host, registry, scheduler, admission service, or project binding runtime;
- add an MCP server to Claude Code, Codex, or an agent gateway;
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
- commit `20a818e648a4c09a60df0126d11626922e8b9094`.

Read the pinned contract's guide
`docs/guides/connecting-compatible-agents.md`, the selected profile specification, and
the referenced JSON Schemas before implementing protocol details. If the private checkout
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

Valid profiles are `mcp`, `a2a`, and `local-runner`. The helper creates only the locked
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
- Local runner maps typed input, executable identity, result location, cancellation,
  heartbeat, and partial results without relying on ambient accounts.

Keep model selection and provider-internal reasoning outside the Fabric contract. Expose
typed outcomes, evidence, artifacts, and protocol-visible state—not chain-of-thought.
Treat all provider output as untrusted until schemas and semantic assertions pass.

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
