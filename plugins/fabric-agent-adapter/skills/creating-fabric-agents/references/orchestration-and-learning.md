# Orchestration and learning: how the agent works, and how it gets better

An agent is a loop: it takes work, plans, calls tools or other agents, stops for a person where it must, finishes or
fails honestly, and learns from what happened. This page is the design of that loop. The agent's internal loop (tool
calls, routing, memory, sub-agents) is designed in depth with `agent-orchestrator`, and its evals with `agent-evals`
(agent-stack); this page is what a Fabric agent must get right whichever way it is built.

Normative rules: the Fabric Agent Contract's `interop.md` (jobs, *Limits and uncertain effects*, DEC-0087),
`pipeline.md` (`pipeline/0.1`), `memory-and-learning.md` (proposals, retrospectives, the loop guard) and
`delegation.md` (grants and spend when one agent calls another).

## Contents

- [Workflow first, autonomy where it pays](#workflow-first-autonomy-where-it-pays)
- [The work graph](#the-work-graph)
- [Calling other agents](#calling-other-agents)
- [Stops for a person](#stops-for-a-person)
- [Learning loops](#learning-loops)
- [The loop guard](#the-loop-guard)
- [The checklist](#the-checklist)

## Workflow first, autonomy where it pays

If every step can be named, build a deterministic workflow behind the capability; let a model decide only where the
input really varies (the intake grill's *Workflow or agent?*). An orchestrator is the part that owns the plan: it cuts
work into steps, routes each to the cheapest lane that can do it (models-and-providers.md), runs independent steps in
parallel, and is the only part that decides to retry, wait, ask a person or give up.

## The work graph

- **Every step is a durable job** with a stable id that survives a restart (`fabric-interop/0.1` jobs; the kit's
  `JobStore`). A step's state lives on disk, not in a process's memory.
- **Every step has an idempotency key derived from its intent**, never a clock or a random value
  (`intent_idempotency_key({agentId, capability, input})`): a resend after a restart is the same request.
- **Effects run once.** A step that pays, sends or publishes records its intent before the call and its observed
  result after; when the answer was lost it ends `outcome-unknown` and is reconciled by observing, never re-run under
  a new key.
- **Limits are pauses, not failures.** A provider quota that will reset keeps the job `working` with
  `quota-exhausted until <instant>`; one that needs a person ends `quota-exhausted` with `retryable: false`
  (`jobs.pause`, `jobs.quota_exhausted`).
- **The caller acts on each answer as `job_caller_action` says**: poll, wait until, answer a question, resend under the
  same key, ask a person, reconcile. It never "submits anew".
- **Count what is unknown.** A step whose cost, tokens or outcome nobody measured reports `null` and names it.

## Calling other agents

- Call another agent's capability through Fabric, never its keys or its database. Its spend is metered under the grant
  you hold; a child call can only narrow scope, effects, data, deadline and depth, never widen them.
- Hold a finite budget for the whole parent operation and allocate children within it; a child whose financial outcome
  is unknown keeps its share reserved.
- A child that is unavailable answers with an explicit denial; never fall back to a privileged account to get it done.
- Record parent and child ids, so one operation can be followed end to end; refuse cycles.

## Stops for a person

- **Show who decides each stop.** The person's queue holds only the person's stops; an agent's own decisions are
  recorded, not queued for approval.
- **An approval holds the work, it does not refuse it.** Work above an approval line waits with its estimate and an
  approval request, and resumes the moment it is granted.
- **An agent never approves its own spend**, its own proposal, or its own acceptance checker.
- **A promise of a person is a handoff.** If a reply says "a person will get back to you", the agent opens the handoff
  that makes it true.
- **Tell the person once per change.** A message to an operator goes out for a failure that lasts, for money, or for a
  decision only they can make; one case once, the same case never repeated.

## Learning loops

An agent gets better only through loops that are recorded and checked, never by rewriting itself in place:

1. **Record every decision with its reason**: the option chosen, the ones passed over, and why. This is what a review,
   a retrospective and the next model read.
2. **Keep one trace id per turn** with its model calls, tools, cost and outcome, stored where it outlives the
   platform's own logs.
3. **Turn every failure into a check before it is fixed**: a planted fixture with the exact defect, watched failing,
   then the fix. A known defect not yet fixed is an expected-failure test that names its backlog row.
4. **Replay the real history** through the current agent before calling a change right; evals hold the questions you
   thought of, the history holds the ones users asked.
5. **Propose, never self-approve.** A learning (goal, failed attempt, verified correction, cause, evidence, scope,
   proposed change) is a proposal to the project's memory; a person or an independent check promotes it. It never
   changes the running revision or its own checker (`memory-and-learning.md`).
6. **Share what generalises.** A practice that held in two projects becomes a lesson other agents find (practices.md);
   a practice in one project stays in its own knowledge pack.

Memory is cited, bounded and scoped: a retrieval names the revisions it used, absence of a result is not proof of
absence, and project memory never crosses into another context.

## The loop guard

Count entries per stage and hypothesis. A third entry into the same stage with the same hypothesis stops the step as
`loop-guarded`; it resumes only with a changed hypothesis, dependency, plan or a person's decision. Switching the
model, the runtime or the account does not reset a logic loop.

## The checklist

- Each step: a durable job, a key derived from its intent, its effect recorded before and observed after.
- Limits paused or stopped with `quota-exhausted`; lost answers `outcome-unknown`; callers act as `job_caller_action`.
- Child calls through Fabric, within the parent's budget and narrower grant.
- The person's queue holds only their stops; no self-approval.
- Decisions with reasons, one trace per turn, failures turned into fixtures, history replayed, learnings proposed.
- A loop guard on every stage.
