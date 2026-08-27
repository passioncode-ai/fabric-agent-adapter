---
name: creating-fabric-agents
description: Use when designing and building a NEW agent or provider that must be Fabric-compatible from its first commit — «создай агента, совместимого с фабрикой Passion Code», «новый агент под Fabric», "create a fabric-compatible agent", "build a new Fabric provider", "fabric-ready agent from scratch". Runs the intake grill (capability, named consumer, workflow-or-agent, MCP/A2A/local-runner profile, effect declarations), distils source projects into a knowledge pack whose recorded failures become planted eval fixtures, scaffolds the pinned contract bundle, and sets the two-clock eval expectation with the conformance report. NOT for adapting an existing project (use adapting-projects-to-fabric), building the Fabric host or orchestrator, or generic agent design where Fabric compatibility is not part of the request.
license: MIT
compatibility: Requires filesystem access and Python 3.9+. Exact schema checks additionally need git, Node.js, pnpm, and the pinned private fabric-agent-contract checkout. Works without those tools in an explicitly degraded structural-check mode. Ships in one plugin with adapting-projects-to-fabric, whose scripts it reuses.
metadata:
  author: passioncode-ai
  version: "0.2.0"
  contract-version: "0.1.0"
  contract-commit: "20a818e648a4c09a60df0126d11626922e8b9094"
---

# Creating Fabric-compatible agents

Design a new agent so that Fabric compatibility is a property of its first commit, not a
retrofit. The sibling skill `adapting-projects-to-fabric` wraps an interface that already
exists; this one runs the stages that come *before* an interface exists — the intake
grill and the knowledge intake — then hands the scaffolding and verification to the same
pinned machinery, so both doors lead into one pipeline.

## Boundary

Use this skill to design and build a new provider. Do not use it to:

- adapt a project that already has a stable API, MCP/A2A surface, or CLI — that is
  `adapting-projects-to-fabric`, and entering there skips nothing;
- design the Fabric host, registry, scheduler, admission service, or binding runtime;
- build a generic agent with no Fabric requirement — nothing here helps a project that
  will never be a provider;
- claim admission: the deliverable is an admission-ready provider bundle, never a
  connected provider.

## Step 0 — the intake grill

No file is created until every row has an answer. An answer of "later" fails the grill.

| Question | The gate |
|---|---|
| **What capability?** | one capability, named as `domain.action` (optionally `@surface`), with input and output shapes statable now |
| **Who calls it?** | **a named consumer** — the project, schedule, or workflow that will actually invoke this capability. No consumer, no agent: a role that "would be useful" is a catalogue entry, not a build order |
| **Workflow or agent?** | if every step can be named now, build a deterministic workflow behind the capability and skip the autonomy — an agent buys flexibility with latency, cost, and a new failure class, and that price needs a reason |
| **Which profile?** | `mcp` when Fabric owns planning and retries and the capability has a schema; `a2a` when the provider owns its task lifecycle end to end; `local-runner` when it is a terminal agent Fabric drives. When unsure, the sibling skill's profile-selection reference is the decision record |
| **What effects?** | declare anything money-, deletion-, or publication-adjacent now — the host's floor and grants are designed against these declarations, and one discovered late invalidates the admission |
| **Which tenancy?** | record whether the agent assumes one operator; the assumption is cheap to write down and expensive to excavate |

## Step 1 — the knowledge intake

If the estate holds prior art — a project that did this job, an audit that names its
failures, a retro — distil it before writing code:

1. Name the sources: repositories, `docs/`, audits, retrospectives, with references.
2. Extract **patterns** (what worked, each citing its origin) and **traps** (recorded
   failures and dead ends).
3. **Convert every trap into a planted eval fixture.** The new agent is not done until
   it has been watched rejecting the exact defects its predecessors were burned by —
   knowledge transfers as a check, not as prose.
4. Record the pack in the new project as `docs/knowledge-pack.md` with its sources, so
   the provenance of every borrowed decision survives the person who borrowed it.

Skipping this step because there is no prior art is legal; skipping it because reading
is slower than generating is how the same collector truncates at the same row limit
twice.

## Step 2 — the project skeleton

Create the minimal project: repository, `README.md` naming the capability and its
consumer, and the eval **observables** — for each requirement, the pass/fail criterion
that would show it met, written now, before the implementation. The input corpus is NOT
authored now: it grows from real traces once the provider runs, and the step-1 fixtures
are its seed because a source project's recorded failures count as production.

## Step 3 — scaffold the provider bundle

Reuse the sibling skill's scaffolder against the new skeleton with the profile chosen at
step 0:

```bash
python3 <plugin-dir>/skills/adapting-projects-to-fabric/scripts/adapt_project.py \
  scaffold <project-root> --profile <mcp|a2a|local-runner> \
  --provider-id <stable-uri> --provider-name "<name>" \
  --capability-id <stable-uri> --capability-name <domain.action> \
  --schema-base <immutable-base-uri>
```

Pin exactly contract `0.1.0` at commit `20a818e648a4c09a60df0126d11626922e8b9094` and
read the pinned guide before implementing protocol details. If this skill is installed
without its sibling, the scaffolder is absent: create the bundle by hand from the pinned
contract's `docs/guides/connecting-compatible-agents.md` and mark the structural check
`NOT_RUN` — do not reconstruct normative rules from memory.

The generated placeholders are deliberate blockers; a bundle still containing one is not
ready for admission.

## Step 4 — implement against the observables

Build the capability behind the chosen surface. Keep model choice and internal reasoning
outside the contract; expose typed outcomes, evidence, and protocol-visible state. Every
provider output is untrusted until schemas and semantic assertions pass. The step-2
observables are the definition of done; an observable attached after the code exists
lets the output decide what counts as success.

## Step 5 — check, report, and set the canary expectation

Run the sibling skill's `check` (structural, then exact when the contract checkout is
available) and complete `fabric/FABRIC-CONFORMANCE.md` with dated receipts, exactly as
its workflow steps 5–7 prescribe — this skill adds no second verification path on
purpose. Then record one expectation the report must carry:

> When a Fabric host admits this provider, it enters under a **canary binding** — a
> checker on its output and a budget cap — regardless of who wrote it. Unsupervised
> operation is a later, recorded promotion citing eval results and run history.

## Completion format

Report: capability, consumer, profile with the step-0 grill answers; the knowledge pack
and which traps became fixtures; created files; contract version and commit; the gate
table with `PASS`, `FAIL`, `NOT_RUN`, or `NOT_VERIFIED`; remaining placeholders; and the
exact next command. Never summarize the outcome as "Fabric-compatible" unless every
required admission gate passed against the real provider.
