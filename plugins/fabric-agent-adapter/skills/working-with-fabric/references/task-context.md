# The context of a task, settled before the first act on it

The operator's rule, relayed on the board by the contract's owner (message `bfc0e14e`, 2026-11-12, FAA-299).
The Fabric Agent Contract drafts it as CT-292, rules TC-1 to TC-6:
`docs/evidence/plans/2026-11-12-ct292-task-context.md`, at `753c5093` or later on its main branch. This page follows
that draft until its DEC lands (the contract's slice of 2026-11-21); then the DEC is the rule and this page cites it.

A context is `personal` or `org:<orgId>` (contract DEC-0082). It matters only when you can reach resources of more than
one: an account, a key, a grant, a board, another agent, a data store or a repository of an organization.

## Settle it before the first act (TC-1, TC-2)

Before your first act on such a resource, the task has exactly one context. Read each source that can name it; each
one that names a context is a claim:

1. the operator's words for this task that name an organization, its product or its flow;
2. the board request the task serves: the requesting Project's organization;
3. the folder's Project by folder attribution (DEC-0089) and that Project's organizations; a Project with no
   organization claims `personal`;
4. the grant the act runs under, when it states `context` (DEC-0082);
5. the place, when it belongs to one organization (its space, its machine, its cloud).

**The context is settled when at least one source claims and every claim names the same context.** A Project listed
for two organizations claims both and settles nothing. Reading your own working folder needs no context.

## Unsettled: ask once (TC-3, TC-4)

When no source claims and you can reach more than one context, or two claims differ, **ask the operator once, naming
each candidate context, the flow or product in it, and what the task would do there**, each candidate an option.
**Never guess, never pick the "safest" candidate, and never split the task across contexts**: work that needs two
contexts is two tasks. The question is a step that waits: every part whose context is settled goes on meanwhile.

This is the one exception to the operator's rule that his word is done the first time without asking (FAA-207, CT-220):
an agent that reaches one context, or whose context is settled, asks nothing.

With a person in the session, ask in the chat. With nobody there (a dispatched run, a headless place), ask through
`fabric_question_ask` with the candidates as `options` and `about: "task.context"`, send `fabric_heartbeat` with
`waitingOn: {kind: "question", id}`, and name the open step in your report. A board request you cannot place is
answered with a `com.reply` naming the step, never worked in a guessed context.

## Record the answer (TC-5)

Record the answer as `{context, by: "operator", at, source}` in the handoff (and the task note), so the next agent and
the next session read a settled context and do not ask again. It holds for that task, or for the Project when the
operator says so; it changes no registry record.

## Keep the contexts apart (TC-6)

The question, its options and its answer go only to the operator's own session or question surface: **never into
either organization's board thread** and never to another organization's agent, since naming one membership to the
other links them. The credentials, data and grants of one context are never used for a task settled in another.

## The checklist

- [ ] Reached more than one context? If not, nothing to settle.
- [ ] Each source read; the context settled, or one question asked with every candidate and its effect.
- [ ] No guess, no "safest" pick, no split; settled parts went on.
- [ ] The answer recorded in the handoff as `{context, by, at, source}`; nothing about it on any board thread.
