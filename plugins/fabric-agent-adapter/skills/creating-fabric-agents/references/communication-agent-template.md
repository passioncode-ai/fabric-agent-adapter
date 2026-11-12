# Fabric communication agent: the template prompt

**Load this when you are about to build, or rebuild, an agent that talks with people on a channel**: a support bot, a
sales or lead desk, a community or group assistant, a mail inbox, store-review replies, partner or ads direct messages.
When the agents database names a template for this kind of agent, build from it and read this prompt beside it;
otherwise copy the prompt (the template folder's `TEMPLATE.md`) into the coding agent that will build it, fill in the brief, and let it build the agent
end to end. Either way the agent carries the first-release parts this prompt names. The prompt is the recipe; the pages it links hold the rules in full:
[agents that answer people](agents-that-answer-people.md), the channel-agent standard in
[practices](practices.md#agents-on-a-channel-people-write-to), [models and providers](models-and-providers.md),
[orchestration and learning](orchestration-and-learning.md), [resilience and autonomy](resilience-and-autonomy.md) and
the kit's draft-and-check recipe (building-fabric-services, `recipes/support-agent/`).

Where it comes from: an audit of the answering agents of one estate on 2026-11-07 (six that answer with a model: a
Telegram support bot, a community-group assistant, a mail reply service, a mail support agent, a team assistant and a
drafting inbox), their measured quality, and three blind evaluations of the inbound pipeline on 56 real questions
and 19 written batches (two judges of different vendors). The numbers in it are that estate's field evidence, measured in its own private
repositories and not reproducible from this one, never a forecast for yours.

## Contents

- [How to use it](#how-to-use-it)
- [The prompt](#the-prompt)
- [What the audit found](#what-the-audit-found-for-the-reviewer-of-a-new-agent)

## How to use it

The template is a folder in the format of an organization agent template (fabric-workspace
`knowledge/system/templates.md`, S2, readable by the organization's members; the format: [agent-templates.md](agent-templates.md)):
the prompt in `TEMPLATE.md` (role and duties in sections 1 and 4, connections and data in 5, learning in 6, the contract and
its doors in 8, checks in 9), and beside it the manifest, the connections, the access levels and data rooms (the brief's
section 0 names them per organization), the acceptance check, the assembly and the changelog. S2's operating rules A1 to
A12 apply by reference.


When the agents database named a template, build from it and use these steps for what this prompt adds to it.

1. Fill in the brief (section 0 of the prompt). Every `<...>` is a decision of the agent's owner; a field you cannot fill
   is a question for the owner before the build, not a guess.
2. Give the whole prompt (the fenced block of `TEMPLATE.md`) to the coding agent in the agent's own repository.
3. The agent is done when the acceptance in section 9 passes on the build the channel runs, not on a fixture.

## The prompt

The prompt is the template folder's [`TEMPLATE.md`](../templates/communication-agent/TEMPLATE.md), sections 0 to 9
(FAA-265 moved it there from this page, unchanged). Its folder,
[`templates/communication-agent/`](../templates/communication-agent/), carries the rest of the template in the format of
[agent-templates.md](agent-templates.md): `manifest.json`, `connections.json`, `access.json`, `data-rooms.json`,
`checks/acceptance.md` (section 9 as the checks the assembled agent passes), `assembly.md` and `CHANGELOG.md`, and
passes `scripts/template_check.py`.

Open for the agents database's owner (FAA-265): whether the database takes this folder as its template of this kind,
or merges it into a close one (a chat assistant or a support answerer), so that one source holds each kind of agent;
until the owner decides, the adapter's folder is the public one and the database's template, when one is named, is
read beside it.

## What the audit found (for the reviewer of a new agent)

- The pieces that worked in production: a burst debounce with a hard cap; a cheap code prefilter before any model;
  the policy, not the model, deciding send, draft or skip; a checker of another vendor that sees the material; code
  checks no model can argue with (sources, links, handles, language, state claims); one repair bounded by the time
  left; retrieval that abstains on the knowledge service's own flag; a two-layer injection check that holds the message
  when the check cannot run; model lanes per step in one file; a second look on every unanswered question; coming back
  when a gap closes; a person's answer becoming knowledge; a calibrated daily judge; eval tickets from real failures and
  a weekly replay; an atomic claim before any model call.
- The gaps it found: a judge that never sees the material checks tone, not accuracy; an injection guard that is only a
  prompt line; an assistant with no judge and no injection rule; a group channel where an unanswered asker hears
  nothing; general chat assistants with no grounding, guard or evaluation (one with a provider key hard-coded in a
  comment).
- The owners' own top failures over 14 days: no fact in the knowledge (the largest by far; by its second look, missing
  data two to three times as often as retrieval misses), a checker refusal after the repair, foreign links and handles stopped
  by code, silence in a group when the knowledge lacked the answer, and referrals instead of answers by mail.
- The weakest measured channel was a partner or ads direct-message desk (policy_safe 70%, helped yes 33%); the
  strongest private-chat support bot answered 74% of turns itself with helped yes 44% under a strict judge, first reply
  p90 25 s, and 0 dropped turns in a week.
