# Agents that answer people: what they carry from the first release

**Load this when the agent you are building answers people**: private chats, mail, store reviews, group chats, any
channel where a person asks and the agent writes back. Every item below is a part of the agent, built and tested in its
first release, not a later improvement. Each comes from the sources below: what the quality standard requires (A1,
A5), and what an audit of five production agents found working or failing (P1 to P8). The practices are field
evidence: one estate, five agents, no control; their numbers are that estate's, never a forecast.

Sources (public): the support quality standard,
[`support-quality.md`](https://github.com/ssheleg/agent-stack/blob/28a0303c42038778e2650fc51096e589f4035239/plugins/agent-stack/skills/agent-evals/references/support-quality.md) (A1 the record, A5
`support.quality_daily`), and the practices from an audit of five such agents,
[`support-practices.md`](https://github.com/ssheleg/agent-stack/blob/f882358e3fb9627f6edb20db3981818912a9844c/plugins/agent-stack/skills/agent-evals/references/support-practices.md) (P1 to P8),
both in the `agent-evals` skill of [ssheleg/agent-stack](https://github.com/ssheleg/agent-stack); the practices arrive
with [PR #70](https://github.com/ssheleg/agent-stack/pull/70), linked here at its commit until it merges. The standard says how such an agent
is measured; the practices say what worked and what failed. This page lists what the agent carries and the check that
proves each part. Read both sources before you design the reply pipeline. The kit's support-agent recipe
(building-fabric-services, `recipes/support-agent/`) is one draft-and-check step of such an agent, not the agent: a failed
check of its draft is where this page's repair, research and hold begin, and its abstentions open a gap.

## Contents

- [The record and the daily report](#the-record-and-the-daily-report)
- [Model lanes](#model-lanes)
- [Checks before a reply is sent](#checks-before-a-reply-is-sent)
- [When the check refuses](#when-the-check-refuses)
- [Hand-offs and promises](#hand-offs-and-promises)
- [Knowledge and gaps](#knowledge-and-gaps)
- [Reading the events feed](#reading-the-events-feed)
- [Checklist](#checklist)

## The record and the daily report

- **Every inbound message is a turn with a trace id** (A1): the id is on the turn row, on each model call of that turn,
  on its log line and on any copy a person reads. The turn stores its outcome (answered, general guidance, not covered,
  handed off, small talk, limit, error), the hand-off reason and category, the latency, the knowledge revision the
  answer used, and whether the channel accepted the reply. Conversation text stays inside the agent, redacted, for at
  most 30 days. Check: a test that a turn without a trace id, or with an outcome outside the list, is refused.
- **The agent publishes one `support.quality_daily` per closed UTC day and channel** on its events feed
  (`/fabric/v1/events`; building-fabric-services, `references/events-and-notifications.md`): counts and codes only, the
  judge model and rubric version, and `notMeasured` naming every family not computed that day. A metric not measured is
  null and named, never 0. The day goes in the event's `data` (`{schema, value}`, as `fabric_events.py` writes it), at
  level `info` and without a notification. Until the contract carries the schema (A7), the producer names and pins its
  own: `data.schema` is the absolute URI of the payload schema the agent publishes, and `data.value` stays within
  DEC-0070's bounds (at most 32 members, each a scalar, a list of scalars or a flat object; per-lane counts as objects
  such as `laneFailures` and `laneRecovered`; building-fabric-services, `references/protocol.md`). Check: the producer's
  day passes `make_event`; and a test runs every `notMeasured` name the producer can emit through the published name
  pattern, iterating the producer's own list.

## Model lanes

- **A table of lanes** (P4): classifier, writer, fallback writer, checker, research, judge. The checker is another
  vendor than the writer; the judge is another vendor than both, at temperature 0, on an open-vendor model where it
  reads what people wrote. Declare them as classes in the profile, where each lane's fallback is another vendor than its
  primary ([models and providers](models-and-providers.md)); per turn the router picks the checker against the model
  that actually drafted, a fallback writer included ([resilience and
  autonomy](resilience-and-autonomy.md#model-answers-are-untrusted-until-accepted), item 3). Check: the config loader
  refuses a fallback that shares its own lane's primary vendor, a checker route (primary or fallback) that shares the
  vendor of the writer or the fallback writer, and a judge route (primary or fallback) that shares the vendor of either
  writer or of either checker route (the vendor is the prefix before `/`).
- **Count what the fallback recovered** (P4), not only what the first attempt lost: a day's report says how many calls
  failed and how many of those the fallback answered. Check: a test that a recovered call counts once as a failure of
  the primary and once as a recovery, and is never counted as an error of the turn.
- **A writer model or reasoning budget changes only after an offline replay** (P4) of last week's judged sample, judged
  blind, on the current model and the candidates. Check: the config loader refuses a change of the writer lane's model
  or reasoning budget that names no replay report.

## Checks before a reply is sent

- **Deterministic false-state gates come first** (P2): the reply may not say that money arrived, that something is live,
  enabled or fixed, or that a person did something, unless the system backs it. Check: planted drafts with each false
  claim are refused before any model checker runs.
- **The checker sees the material, and sees it before the instructions** (P2): the knowledge items and account state the
  writer used come first in its context, the operator's instructions after. A checker that receives the material cut
  short after long instructions refuses correct answers as invented. Check: a planted correct answer whose material is
  longer than the instructions passes the checker.
- **Numbers and account state come from tools**, never from the model (P1): prices from a calculator, the person's
  account state and order from the system, injected per turn. Check: a planted draft with a price or an account state
  that no tool result of the turn carries is refused.
- **Before sending, re-read the conversation's live tail** (P1): if a person or the agent already answered, skip the
  turn. Check: a reply that lands in the conversation while the draft is checked makes the agent send nothing.

## When the check refuses

- **Repair, then research, then hold** (P2): one repair with the checker's reason; then one research turn on a stronger
  model that sees both refused drafts and approved past answers, under a hard time cap; only then an honest holding
  line. A refusal for a money reason is never researched. Check: a planted refusal walks all three steps in order.
- **A hold comes back by itself** (P2): when a person or the knowledge base answers the held question, the conversation
  is run again and the person gets the answer without asking twice. Check: closing the gap behind a held turn produces
  one reply in that conversation, and only one.

## Hand-offs and promises

- **A hand-off is never an answer** (P3): it is not counted as answered, and hand-off and fallback templates stay out of
  the judge's sample. Check: the daily report counts a hand-off under hand-offs, and the judge's sample builder leaves
  templated replies out.
- **Hand-offs are counted by cause** (P3): `policy`, `inability` and `infrastructure` apart, so the largest number names
  what to fix. Check: a checker outage produces `infrastructure` hand-offs, never `inability`.
- **A commitments ledger** (P3): every "I will pass this on and come back" is a row with an owner and a due date; the
  week's report counts promises made and closed. Check: a reply that promises to come back without a ledger row is
  refused.

## Knowledge and gaps

- **The knowledge client keeps no threshold of its own** (P1, P8): the knowledge service decides whether an item may be
  given as an answer and returns an `answer` flag per item; the client reads the flag and nothing else. Small closed
  rule sets (prices, payment terms, refunds, sign-in) go into the prompt whole, dated and ordered by owner. Check: a
  test that changing the client's configuration cannot make an item with `answer: false` an answer.
- **Every abstention becomes a gap in a queue** (P7), restated without personal data and grouped by meaning. When a gap
  closes, the client asks again and rewrites the held answer only once the new answer is confident. Check: a closed gap
  whose new answer comes back with `answer: false` leaves the hold in place.

## Reading the events feed

- **A reader that starts accepting a new event kind re-reads its feed once** (P6), from before its cursor: a reader that
  only moves forward has already passed the first events of that kind. Check: a test adds a kind to the reader and sees
  the earlier events of that kind delivered once.

## Checklist

- [ ] Turn record with a trace id and an outcome from the fixed list (A1)
- [ ] `support.quality_daily` per closed UTC day and channel; `notMeasured` names tested against the pattern (A5)
- [ ] Lane table: fallback, checker and judge of other vendors; fallback recoveries counted
- [ ] A writer model or reasoning budget changed only after an offline replay
- [ ] False-state gates before the model checker; the checker sees the material before the instructions
- [ ] Numbers and account state from tools; the live tail re-read before sending
- [ ] Repair, research, hold; a hold that comes back by itself
- [ ] Hand-offs by cause, never counted or judged as answers
- [ ] A commitments ledger: promises made and closed per week
- [ ] A knowledge client that reads the service's `answer` flag and keeps no threshold
- [ ] A gap queue that asks again after a gap closes
- [ ] A reader that adds an event kind re-reads its feed once
