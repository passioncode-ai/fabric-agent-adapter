---
name: creating-fabric-agents
description: Use when designing and building a NEW agent or provider that must be Fabric-compatible from its first commit, «создай агента, совместимого с фабрикой Passion Code», «новый агент под Fabric», "create a fabric-compatible agent", "build a new Fabric provider", "fabric-ready agent from scratch", «агент в облаке организации», "which models and OpenRouter key for a new Fabric agent". Runs the intake grill (capability, named consumer, workflow or agent, profile, effects, where it runs, models, who pays, how it learns), turns source projects' recorded failures into planted eval fixtures, scaffolds the pinned contract bundle and sets the canary expectation. NOT for adapting an existing project (adapting-projects-to-fabric), making an agent a local or online Fabric service with a dashboard (building-fabric-services), a coding session working through Fabric or its board (working-with-fabric), the Fabric host or orchestrator, or agent design without Fabric.
license: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
compatibility: Requires filesystem access and Python 3.9+. Exact schema checks additionally need git, Node.js, pnpm, and the pinned fabric-agent-contract checkout (a public repository). Works without those tools in an explicitly degraded structural-check mode. Ships in one plugin with adapting-projects-to-fabric, whose scripts it reuses.
metadata:
  author: PassionCode.ai
  version: "0.44.1"
  contract-version: "0.1.0"
  contract-commit: "bfa9a67aa3c6cb808c093e7d83cd59799f1ee7d0"
---

# Creating Fabric-compatible agents

Design a new agent so that Fabric compatibility is a property of its first commit, not a
retrofit. The sibling skill `adapting-projects-to-fabric` wraps an interface that already
exists; this one runs the stages that come *before* an interface exists (the intake
grill and the knowledge intake), then hands the scaffolding and verification to the same
pinned machinery, so both doors lead into one pipeline.

## Boundary

Use this skill to design and build a new provider. Do not use it to:

- adapt a project that already has a stable API, MCP/A2A surface, or CLI: that is
  `adapting-projects-to-fabric`, and entering there skips nothing;
- run an agent as a local or online service with a dashboard on its own: that is
  `building-fabric-services` (step 4 hands over to it for a new agent that needs one);
- work in a project through Fabric from a coding session (the board, claims): that is
  `working-with-fabric`;
- design the Fabric host, registry, scheduler, admission service, or binding runtime;
- build a generic agent with no Fabric requirement: nothing here helps a project that
  will never be a provider;
- claim admission: the deliverable is an admission-ready provider bundle, never a
  connected provider.

## Handing off to neighbouring skills

- The agent's own loop (tool calls, routing and fallback, memory, sub-agents) is
  designed with `agent-orchestrator` (agent-stack).
- Its eval suite beyond the step-2 observables (trajectories, judges, regression
  fixtures from traces) is built with `agent-evals` (agent-stack).
- Packaging the agent as an Agent Skill or Claude Code plugin goes through `make-skill`.

When one of them is not installed, do that part by hand against its own documentation
and say in the report which skill was missing.

## Step 0: the intake grill

No file is created until every row has an answer. An answer of "later" fails the grill.

| Question | The gate |
|---|---|
| **What capability?** | one capability, named as `domain.action` (optionally `@surface`), with input and output shapes statable now |
| **Who calls it?** | **a named consumer**: the project, schedule, or workflow that will actually invoke this capability. No consumer, no agent: a role that "would be useful" is a catalogue entry, not a build order |
| **Workflow or agent?** | if every step can be named now, build a deterministic workflow behind the capability and skip the autonomy; an agent buys flexibility with latency, cost, and a new failure class, and that price needs a reason |
| **Which profile?** | `mcp` when Fabric owns planning and retries and the capability has a schema; `a2a` when the provider owns its task lifecycle end to end; `local-runner` when it is a terminal agent Fabric drives. When unsure, the sibling skill's profile-selection reference is the decision record |
| **What effects?** | declare anything money-, deletion-, or publication-adjacent now; the host's floor and grants are designed against these declarations, and one discovered late invalidates the admission |
| **Where does it run, for whom?** | this machine, the person's cloud or an organization's, and in which contexts (`personal`, `org:<id>`): one instance per context, its secrets, spend and journal never crossing into another. Record which capabilities need the person's machine and what they answer when it is off (references/where-agents-run.md) |
| **Which models?** | per lane (planning, replies, volume work, media): a primary, a fallback of another vendor, an open-vendor model where it reads what users send, the input kinds each reads, declared as classes in the profile (references/models-and-providers.md) |
| **Who pays?** | one key per agent and context with its own ceiling, from the estate's key manager, read from the environment; checked before every call; a personal key never pays for an organization |
| **How does it learn?** | decisions recorded with reasons, one trace per turn, every failure a planted fixture first, history replayed, learnings proposed and never self-approved (references/orchestration-and-learning.md) |
| **Text for people?** | if it writes anything a person reads (a reply, a message, a post, a report, a UI string), its prompt forbids the em dash (U+2014) and any substitute for it, and a test fails on U+2014 in new output, from the first commit (the resilience reference, *Text for people*) |

## Step 1: the knowledge intake

If the estate holds prior art (a project that did this job, an audit that names its
failures, a retro), distil it before writing code:

1. Name the sources: repositories, `docs/`, audits, retrospectives, with references.
2. Extract **patterns** (what worked, each citing its origin) and **traps** (recorded
   failures and dead ends).
3. **Convert every trap into a planted eval fixture.** The new agent is not done until
   it has been watched rejecting the exact defects its predecessors were burned by:
   knowledge transfers as a check, not as prose.
4. Record the pack in the new project as `docs/knowledge-pack.md` with its sources, so
   the provenance of every borrowed decision survives the person who borrowed it.

Skipping this step because there is no prior art is legal; skipping it because reading
is slower than generating is how the same collector truncates at the same row limit
twice.

Every new agent also starts from what the estate already learned, whether or not it has
prior art of its own:

- [practices.md](references/practices.md): the rules production agents taught us, each with
  the check that catches it (judges and evals, numbers, money, people in the loop,
  reliability, shipping). Organization members also read the knowledge base's
  `knowledge/agent-practices.md` and add to it what this agent learns.
- [where-agents-run.md](references/where-agents-run.md): this machine, a personal cloud, an
  organization; contexts; connecting a machine; sharing into an organization; selling.
- [models-and-providers.md](references/models-and-providers.md): lanes, a starting model
  choice, several kinds of input and output, budgets, OpenRouter keys.
- [orchestration-and-learning.md](references/orchestration-and-learning.md): the work graph,
  calling other agents, stops for a person, learning loops, the loop guard.

## Step 2: the project skeleton

Create the minimal project: repository, `README.md` naming the capability and its
consumer, and the eval **observables**: for each requirement, the pass/fail criterion
that would show it met, written now, before the implementation. The input corpus is NOT
authored now: it grows from real traces once the provider runs, and the step-1 fixtures
are its seed because a source project's recorded failures count as production.

**For a PassionCode.ai repository**, the new agent's repository follows the organization's
repository standard (`knowledge/repository-standard.md`) from its first commit: the licence files,
the README quick start verified with a real client, `AGENTS.md` and `CLAUDE.md`, as
[the operator channel and the repository standard](references/operator-channel-and-repository.md)
lists them. An agent someone builds for themselves is not a PassionCode.ai repository: its licence
is its owner's choice and none of those files is required of it.

**Every credential the agent uses is read by name, never held as a value**, from its first commit:
the README's Configure section lists key NAMES. With Project Observatory installed, the agent finds
them with `observatory_credentials` and runs under
`python3 "$(project-observatory full-path)/tools/use_secret.py" run --vault-only <project> <NAME> -- <command>`
(a long-running service: `use_secret.py serve`), with `OBSERVATORY_VAULT_ONLY=1` in its environment.
Without it, the person's OS keychain or secret manager injects the key into the agent's environment
at start. Either way: no `.env` of its own, no key file beside its data, no value in argv, code,
configuration or a commit. A workflow names the keys it needs in its checkpoint (`credentials`),
never their values.

## Step 3: scaffold the provider bundle

Reuse the sibling skill's scaffolder against the new skeleton with the profile chosen at
step 0:

```bash
python3 <plugin-dir>/skills/adapting-projects-to-fabric/scripts/adapt_project.py \
  scaffold <project-root> --profile <mcp|a2a|local-runner> \
  --provider-id <stable-uri> --provider-name "<name>" \
  --capability-id <stable-uri> --capability-name <domain.action> \
  --schema-base <immutable-base-uri> --effect <class> \
  [--idempotency required|supported|none] [--cost-preset <id> <max-usd> "<label>" ... --default-cost-preset <id>]
```

The effect class is declared, never defaulted: ask the author what the agent does outside itself when the request
does not say. Cost presets are only for a run whose cost varies; their amounts come from the author or measured runs.

Pin exactly contract `0.1.0` at commit `bfa9a67aa3c6cb808c093e7d83cd59799f1ee7d0` and
read the pinned guide before implementing protocol details. If this skill is installed
without its sibling, the scaffolder is absent: create the bundle by hand from the pinned
contract's `docs/guides/connecting-compatible-agents.md` and mark the structural check
`NOT_RUN`; do not reconstruct normative rules from memory.

This default accepts underscore capability names; a declared communications name does
not grant COM access or prove runtime admission. Existing bundles retain their explicit
supported revision and require its exact checkout; never silently migrate their lock.

The generated placeholders are deliberate blockers; a bundle still containing one is not
ready for admission.

A new agent is called the `fabric-interop/0.1` way from its first version: add `--job`
for a capability whose work may outlive one request, serve each capability as the MCP
tool of its name, and carry the caller's trace (the `building-fabric-services` interop
reference). An agent that is not a service is announced with a provider entry
(`adapting-projects-to-fabric`, `scripts/fabric_provider.py`).

## Step 4: implement against the observables

If the agent keeps running on the operator's computer (it answers other agents, runs
long jobs or shows a dashboard), build it as a service with the sibling skill
`building-fabric-services`: its instance lock, launchd plist, descriptor, well-known
document and events feed are part of this step, not a later retrofit. If that skill is
absent, apply the `fabric-service/0.1` rules from the pinned contract's
`docs/specification/service.md` by hand and mark its probe `NOT_RUN`.

Build the capability behind the chosen surface. Keep model choice and internal reasoning
outside the contract; expose typed outcomes, evidence, and protocol-visible state. One fact
about each model lane is the contract's (DEC-0083): what it reads. Ask in the grill which
lanes read what members, clients or the public send, declare it as the profile's `reads`,
and give such a lane an open-vendor route (FAC-SEM-112; the `building-fabric-services`
profiles reference). Every
provider output is untrusted until schemas and semantic assertions pass. The step-2
observables are the definition of done; an observable attached after the code exists
lets the output decide what counts as success.

## Step 5: check, report, and set the canary expectation

Run the sibling skill's `check` (structural, then exact when the contract checkout is
available) and complete `fabric/FABRIC-CONFORMANCE.md` with dated receipts, exactly as
its workflow steps 5–7 prescribe; this skill adds no second verification path on
purpose. Then record one expectation the report must carry:

> When a Fabric host admits this provider, it enters under a **canary binding** (a
> checker on its output and a budget cap), regardless of who wrote it. Unsupervised
> operation is a later, recorded promotion citing eval results and run history.

## Step 6: propose the operator channel

If the agent has a human stop (a choice, an approval, a confirmation) or emits `notify: true`
events, propose its operator channel (`fabric-operator-channel/0.1`, OC-11) to the operator once,
now, as the shared reference linked at step 2 describes: the
operator's four steps, the answer recorded and never asked again, and the bot, the token and
enabling the channel left to the operator. An agent with neither stops nor notify events skips
this step.

## Resilience and autonomy

Before the first stage that calls a model or spends money, read
[resilience and autonomy](references/resilience-and-autonomy.md) and design its answers in:
a limit pauses and resumes, every model answer passes the call site's own acceptance, fallbacks
and checkers cross vendors, spend is a persisted ledger with idempotency keys, open questions
become recorded decisions, every fix has a test seen failing, and text a person reads carries no
em dash (U+2014), held by its prompt and a test. Report its checklist with a
file and a test per line, or `NOT_RUN` where the agent has no such stage.

## Completion format

Report: capability, consumer, profile with the step-0 grill answers; the knowledge pack
and which traps became fixtures; created files; contract version and commit; the gate
table with `PASS`, `FAIL`, `NOT_RUN`, or `NOT_VERIFIED`; remaining placeholders; the
operator channel answer (step 6); and the exact next command. Never summarize the outcome as
"Fabric-compatible" unless every required admission gate passed against the real provider.

## Dashboard handoff: also for consumers

When handing a registered service dashboard to a person, or writing the generated agent's
completion or notification instructions, read and apply [dashboard links](references/dashboard-links.md)
and run its output gate before delivery, in any host. Headless agents need no dashboard.
