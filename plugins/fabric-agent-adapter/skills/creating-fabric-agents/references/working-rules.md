# Working rules a new agent carries from its first commit

Three rules the operator set for every agent (board message `bfc0e14e`, 2026-11-12: FAA-299, FAA-300, FAA-301). A
new agent's template (its `AGENTS.md`, its system prompt, its session start) states each one, and a test pins each
one's key sentence, so a copy of the agent cannot lose them. The working-with-fabric skill states the same rules for a
coding session; this page is what the agent you build says about itself.

## Contents

- [The context of a task](#the-context-of-a-task)
- [A wait is not a stop](#a-wait-is-not-a-stop)
- [Clean up after yourself](#clean-up-after-yourself)
- [The checklist](#the-checklist)

## The context of a task

Follows the contract's CT-292 draft (rules TC-1 to TC-6, `docs/evidence/plans/2026-11-12-ct292-task-context.md` at
`753c5093`) until its DEC lands (the contract's slice of 2026-11-21).

An agent that can reach resources of more than one context (`personal`, `org:<orgId>`, contract DEC-0082) **settles
the task's context at session start, before its first act on them**, from: the operator's words; the board request's
Project; the folder's Project by folder attribution (DEC-0089) and its organization; the grant's context (DEC-0082);
the place. The context is settled when every source that names one names the same one.

When none names it, or they disagree, **the agent asks the operator once, naming the candidates and what each would
do; it never guesses, never picks a "safest" one and never splits the task across contexts.** With no person in the
session the question goes through `fabric_question_ask` (the candidates as `options`, exactly one `recommended`: the one
the project's recorded decisions and goal support, its reason in the option's `consequence`; Fabric 0.3.21 refuses
options with none, CO-580; the operator still decides). This is the one exception to
the template's "do not ask, do it" rule for the operator's word (FAA-207, CT-220). The answer is recorded in the
handoff as `{context, by: "operator", at, source}`, so the next agent does not ask again. The question and the answer
never go into either organization's board thread.

The template's session start reads the five sources before any tool that acts across contexts; an agent that reaches
only one context asks nothing and says which one in its report.

## A wait is not a stop

The agent finishes a unit of work and takes the next in the same turn (the board's next open task, a request addressed
to it, the handoff's next task). **Every wait has its condition, owner, next action and watcher, or an honest "no
watcher".** `fabric_heartbeat` carries `waitingOn` (`question`, `grant` or `continuation`, with its id) or a one-line
`note` while it waits. **A turn ends with one line per open wait, never with "shall I continue?"**

## Clean up after yourself

After a merge the agent **removes its own worktrees and branches locally and on origin, then runs `git fetch
--prune`**. A branch with commits found nowhere else is archived under `refs/archive/<date>/` before it is deleted. It
removes build output and dependency folders in its abandoned or merged copies and stops its own processes. **It never
touches another session's worktree, a `locked` one, or a Git-tracked file: `git ls-files -- <dir>` must print nothing
before a folder is removed.**

## The checklist

- [ ] The template states the context rule, its one question and where the answer is recorded; a test pins it.
- [ ] The template states "a wait is not a stop" with the four parts of a wait and the turn's last lines; a test pins it.
- [ ] The template states the cleanup rule with its `git ls-files` check; a test pins it.
