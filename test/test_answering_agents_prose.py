"""FAA-162 (0.55.0): what creating-fabric-agents must say about an agent that answers people, pinned to the scenario eval
`an-agent-that-answers-people` (test/evals/creating-fabric-agents/scenarios.json), which a model judges and hosted CI
cannot run. Sources: agent-stack's support quality standard (A1, A5) and its practices from an audit of five such
agents (P1 to P8), linked from the reference at their commits; board request 1ad39d4e."""

import json
import re
import unittest

from test_action_and_dashboard_prose import ROOT, flat, scenario_ids, section, text

REFERENCE = "creating-fabric-agents/references/agents-that-answer-people.md"
SCENARIO = "an-agent-that-answers-people"

# Unit rounds 3 and 4: every part, the checklist, the graded lines, the Step 0 row, the recipe's paragraph and
# retention, and the CHANGELOG entry are pinned whole (whitespace normalized), so removing any clause of one fails here;
# a deliberate change edits these in the same commit.
PARTS = (
    'Every inbound message is a turn with a trace id** (A1): the id is on the turn row, on each model call of that '
    'turn, on its log line and on any copy a person reads. The turn stores its outcome (answered, general guidance,'
    ' not covered, handed off, small talk, limit, error), the hand-off reason and category, the latency, the '
    'knowledge revision the answer used, and whether the channel accepted the reply. Conversation text stays inside'
    ' the agent, redacted, for at most 30 days. Check: a test that a turn without a trace id, or with an outcome '
    'outside the list, is refused.',
    'The agent publishes one `support.quality_daily` per closed UTC day and channel** (A5) on its events feed '
    '(`/fabric/v1/events`; building-fabric-services, `references/events-and-notifications.md`): counts and codes '
    'only, the judge model and rubric version, and `notMeasured` naming every family not computed that day. A '
    "metric not measured is null and named, never 0. The day goes in the event's `data` (`{schema, value}`, as "
    '`fabric_events.py` writes it), at level `info` and without a notification. Until the contract carries the '
    'schema (A7), the producer names and pins its own: `data.schema` is the absolute URI of the payload schema the '
    "agent publishes, and `data.value` stays within DEC-0070's bounds (at most 32 members, each a scalar, a list of"
    ' scalars or a flat object; per-lane counts as objects such as `laneFailures` and `laneRecovered`; '
    "building-fabric-services, `references/protocol.md`). Check: the producer's day passes `make_event`; a planted "
    'day that writes 0 for a family not computed fails; and a test runs every `notMeasured` name the producer can '
    "emit through the published name pattern, iterating the producer's own list.",
    'A table of lanes** (P4): classifier, writer, fallback writer, checker, research, judge. The checker is another'
    ' vendor than the writer; the judge is another vendor than both, at temperature 0, on an open-vendor model '
    "where it reads what people wrote. Declare them as classes in the profile, where each lane's fallback is "
    'another vendor than its primary ([models and providers](models-and-providers.md)); per turn the router picks '
    'the checker against the model that actually drafted, a fallback writer included ([resilience and '
    'autonomy](resilience-and-autonomy.md#model-answers-are-untrusted-until-accepted), item 3). A lane that reads '
    'what people wrote has an open-vendor route (DEC-0083). Check: the config loader refuses a fallback that shares'
    " its own lane's primary vendor, a profile where some writer route has no checker route of another vendor, and "
    'a judge with no route outside the vendors of the writers and the checkers (the vendor is the prefix before '
    '`/`).',
    "Count what the fallback recovered** (P4), not only what the first attempt lost: a day's report says how many "
    'calls failed and how many of those the fallback answered. Check: a test that a recovered call counts once as a'
    ' failure of the primary and once as a recovery, and is never counted as an error of the turn.',
    "A writer model or reasoning budget changes only after an offline replay** (P4) of last week's judged sample, "
    'judged blind, on the current model and the candidates. Check: the config loader refuses a change of the writer'
    " lane's model or reasoning budget that names no replay report.",
    'Deterministic false-state gates come first** (P2): the reply may not say that money arrived, that something is'
    ' live, enabled or fixed, or that a person did something, unless the system backs it. Check: planted drafts '
    'with each false claim are refused before any model checker runs.',
    'The checker sees the material, and sees it before the instructions** (P2): the knowledge items and account '
    "state the writer used come first in its context, the operator's instructions after. A checker that receives "
    'the material cut short after long instructions refuses correct answers as invented. Check: a planted correct '
    'answer whose material is longer than the instructions passes the checker.',
    "Numbers and account state come from tools**, never from the model (P1): prices from a calculator, the person's"
    ' account state and order from the system, injected per turn. Check: a planted draft with a price or an account'
    ' state that no tool result of the turn carries is refused.',
    "Before sending, re-read the conversation's live tail** (P1): if a person or the agent already answered, skip "
    'the turn. Check: a reply that lands in the conversation while the draft is checked makes the agent send '
    'nothing.',
    "Repair, then research, then hold** (P2): one repair with the checker's reason; then one research turn on a "
    'stronger model that sees both refused drafts and approved past answers, under a hard time cap; only then an '
    'honest holding line. A refusal for a money reason is never researched. Check: a planted refusal walks all '
    'three steps in order.',
    'A hold comes back by itself** (P2): when a person or the knowledge base answers the held question, the '
    'conversation is run again and the person gets the answer without asking twice. Check: closing the gap behind a'
    ' held turn produces one reply in that conversation, and only one.',
    'A hand-off is never an answer** (P3): it is not counted as answered, and hand-off and fallback templates stay '
    "out of the judge's sample. Check: the daily report counts a hand-off under hand-offs, and the judge's sample "
    'builder leaves templated replies out.',
    'Hand-offs are counted by cause** (P3): `policy`, `inability` and `infrastructure` apart, so the largest number'
    ' names what to fix. A hold after a checker or model outage, or at the research time cap, is `infrastructure`; '
    'only a hold after a refusal on the material is `inability`. Check: a checker outage produces `infrastructure` '
    'hand-offs and holds, never `inability`.',
    'A commitments ledger** (P3): every "I will pass this on and come back" is a row with an owner and a due date; '
    "the week's report counts promises made and closed. Check: a reply that promises to come back without a ledger "
    'row is refused.',
    'The knowledge client keeps no threshold of its own** (P1, P8): the knowledge service decides whether an item '
    'may be given as an answer and returns an `answer` flag per item; the client reads the flag and nothing else. '
    'Small closed rule sets (prices, payment terms, refunds, sign-in) go into the prompt whole, dated and ordered '
    "by owner. Check: a test that changing the client's configuration cannot make an item with `answer: false` an "
    'answer.',
    'Every abstention and every inability, a hold on the material included, becomes a gap in a queue** (P7), '
    'restated without personal data and grouped by meaning. When a gap closes, the client asks again and rewrites '
    'the held answer only once the new answer is confident. Check: a closed gap whose new answer comes back with '
    '`answer: false` leaves the hold in place, and a hold after a checker outage opens no gap.',
    'A reader that starts accepting a new event kind re-reads its feed once** (P6), from before its cursor: a '
    'reader that only moves forward has already passed the first events of that kind. The re-read reaches back only'
    " as far as the producer's feed keeps (at least 7 days or 1000 events, building-fabric-services "
    "`references/events-and-notifications.md`); an older day is read from the producer's own store or not at all. "
    'Check: a test adds a kind to the reader and sees the earlier events of that kind delivered once.',
)
CHECKLIST = (
    'Turn record with a trace id and an outcome from the fixed list (A1)',
    '`support.quality_daily` per closed UTC day and channel; `notMeasured` names tested against the pattern (A5)',
    'Lane table: fallback, checker and judge of other vendors; fallback recoveries counted',
    'A writer model or reasoning budget changed only after an offline replay',
    'False-state gates before the model checker; the checker sees the material before the instructions',
    'Numbers and account state from tools; the live tail re-read before sending',
    'Repair, research, hold; a hold that comes back by itself',
    'Hand-offs by cause, never counted or judged as answers',
    'A commitments ledger: promises made and closed per week',
    "A knowledge client that reads the service's `answer` flag and keeps no threshold",
    'A gap queue that asks again after a gap closes',
    'A reader that adds an event kind re-reads its feed once',
)
EXPECTED = (
    'loads references/agents-that-answer-people.md and builds its parts into the first release, not later',
    'records every inbound message as a turn with a trace id and an outcome from the fixed list, and publishes one '
    'support.quality_daily per closed UTC day and channel on the events feed, with notMeasured named and never 0',
    'declares lanes with a fallback of another vendor than its primary, a checker of another vendor than the writer'
    ' and a judge of another vendor than both, counts what the fallback recovered, and changes the writer model or '
    'reasoning budget only after an offline replay',
    'puts deterministic false-state gates before the model checker, gives the checker the material before the '
    "instructions, takes numbers and account state from tools, and re-reads the conversation's live tail before "
    'sending',
    'on a refusal repairs once, then runs one research turn, then holds honestly, and the hold comes back by itself'
    ' when the gap closes',
    "counts hand-offs by cause (policy, inability, infrastructure), never as answers, keeps them out of the judge's"
    ' sample, and keeps a commitments ledger',
    "reads the knowledge service's answer flag with no threshold of its own, queues every abstention and every "
    'inability, a hold on the material included, as a gap (a hold after an outage opens none) and asks again after '
    'it closes, and re-reads its feed once when it starts reading a new event kind',
)
STEP_0_ROW = (
    '| **Does it answer people?** | if it answers people in a chat, by mail, in store reviews or in a group, it '
    'carries from its first release the turn record and the daily `support.quality_daily` report, the lane table '
    'with vendor exclusion and fallback recoveries counted, a writer change only after an offline replay, '
    'false-state gates and a checker that sees the material first, numbers and account state from tools, the live '
    'tail re-read before sending, repair then research then a hold that comes back, hand-offs by cause and never '
    "counted or judged as answers, a commitments ledger, a knowledge client that reads the service's `answer` flag,"
    ' a gap queue and a feed re-read on a new event kind (references/agents-that-answer-people.md) |')
RECIPE_PARAGRAPH = (
    'This recipe is the draft-and-check step of an agent that answers people, not that agent, and used alone it '
    'falls short of one. Every hand-off goes to `on_handoff`, by default the outbox a person reads, at the first '
    'refusal: the practices name that as the failing pattern (P2). An agent that repairs passes its own '
    '`on_handoff=` so a failed check reaches its repair step rather than a person; the recipe returns the failed '
    'checks by name in `reasons`, but takes no reason in and returns no refused draft yet, and it calls again under'
    ' a new message id, since the stored decision answers any repeat of the same id. `on_handoff` runs under the '
    "agent's lock, before the decision is saved, so it queues the hand-off and returns: since 0.55.0 a call to "
    '`answer` from inside it, on the same thread, is refused with `ReentryError` (a `RecipeError`), and unless '
    '`on_handoff` catches it the first call raises it too, its draft paid and nothing saved or delivered. A call it'
    ' hands to another thread and waits for waits for the lock forever, so it never waits: the repair step calls '
    '`answer` once the first call has returned. The original id stays a hand-off, which a repeat of it returns; the'
    " repair step sends the retry's reply and records the turn as answered in the agent's own turn record, which, "
    "not `decisions.jsonl` (one line per message id decided), counts turns. The retry's own hand-off reaches "
    "`on_handoff` again, so the repair step bounds its retries (one repair is the practices') and passes any "
    "further hand-off to the person's channel. A copy of `support_agent.py` made before 0.55.0 takes no "
    '`on_handoff` in `from_config` and hangs on such a call (`grep -c ReentryError support_agent.py` prints 0 for '
    'it; `fabric_kit.py status` covers the kit modules only): copy it again. The recipe also lacks three parts of '
    'such an agent: the Lookup (shared words, best three) is a relevance rule of its own, where the agent reads the'
    " knowledge service's per-item `answer` flag and puts small closed rule sets into the prompt whole; "
    '`from_config` accepts a same-vendor fallback, refused only per call as `model:config`; and the decision does '
    'not record which model answered, so fallback recoveries are not counted. The recipe hands off nothing for '
    '`policy`: the calling service routes the categories a person must handle (refunds, unbans, account recovery) '
    "before it calls the recipe, or a model's `HANDOFF` on them is counted as a false knowledge gap. Count its "
    'hand-offs by cause: a failed check is a refusal for the agent to repair, research and hold, and only a hold on'
    ' the material counts as `inability` (a hold after an outage or at the research time cap is `infrastructure`); '
    '`unsupported:amount` is a money reason, never researched, and so is `unsupported:number` while the decision '
    'returns no draft to tell a price from another number; `no-knowledge` and `model-unsure` are `inability`; every'
    ' `inability` opens a gap; `model:*` is `infrastructure`, and `model:ceiling` and `model:payment` are also the '
    "turn's `limit` outcome. The rest of the agent's parts with checks come from [agents that answer "
    'people](../../../creating-fabric-agents/references/agents-that-answer-people.md): the turn record, the daily '
    "`support.quality_daily` report, the other-vendor model checker that sees the material first (this recipe's "
    'checks are code only), the false-state gates, numbers and account state from tools, the live-tail re-read, the'
    ' commitments ledger and the gap queue.')
RECIPE_RETENTION = (
    "Every handoff row in `handoffs.jsonl` holds the customer's own message, which can carry an email address, a "
    "phone number or a card number. It stays until it is pruned. Choose a retention the product's privacy policy "
    "states, at most 30 days for an agent that answers people (the standard's A1). A1 also asks for the text "
    'redacted: the outbox keeps it as written, and `prune` takes any `--keep-days`, so such an agent passes an '
    '`on_handoff` that redacts what it stores, which replaces the outbox, and keeps 30 days or fewer. Prune on a '
    'schedule:')
CHANGELOG_ENTRY = (
    '- **creating-fabric-agents: agents that answer people** (FAA-162, board request `1ad39d4e`). A new reference, '
    '`references/agents-that-answer-people.md`, lists what an agent that answers people (a support chat, mail, '
    'store reviews, a group) carries from its first release, each part with the check that proves it: a turn record'
    ' with a trace id and a fixed outcome list, one `support.quality_daily` per closed UTC day and channel with '
    '`notMeasured` named, model lanes whose fallback, checker and judge are other vendors with fallback recoveries '
    'counted, a writer change only after an offline replay, false-state gates before the model checker, a checker '
    'that sees the material before the instructions, numbers and account state from tools, the live tail re-read '
    'before sending, repair then research then a hold that comes back by itself, hand-offs by cause and never as '
    "answers, a commitments ledger, a knowledge client that reads the service's `answer` flag, a gap queue, and a "
    "feed re-read when a reader starts on a new event kind. Its sources are agent-stack's support quality standard "
    'and the practices from an audit of five such agents, linked at their commits (the practices at agent-stack PR '
    '#70 until it merges). Step 0 of the skill gains the row "Does it answer people?" and Step 1 links the '
    'reference. New scenario eval `an-agent-that-answers-people` and its prose test '
    '(`test/test_answering_agents_prose.py`), which fails when a part or its check is removed. The support-agent '
    'recipe now says it is the draft-and-check step of such an agent, not the agent: used alone it hands the '
    'message to a person at the first refusal (the refused draft is not kept), and its Lookup is a relevance rule '
    "an agent that answers people replaces with the knowledge service's `answer` flag. It says the calling service "
    'routes `policy` before it, maps its hand-offs to causes (a failed check goes to repair and counts as '
    '`inability` only at a hold on the material, a hold after an outage or at the research time cap being '
    '`infrastructure`; `no-knowledge` and `model-unsure` are `inability` and open a gap; a money reason is never '
    'researched; `model:*` is `infrastructure`, `model:ceiling` and `model:payment` also the `limit` outcome), and '
    'tells such an agent to pass an `on_handoff` that redacts what it stores, in place of the outbox, and to keep '
    '30 days or fewer; `from_config` takes `on_handoff=`, and a call to `answer` from inside `on_handoff` is '
    'refused at once with `ReentryError` rather than hanging (copy `support_agent.py` again to get both); '
    'building-fabric-services and the README point at it. Backlog FAA-116 records what is left for the recipe.')


def scenario():
    path = ROOT / "test/evals/creating-fabric-agents/scenarios.json"
    return next(s for s in json.loads(path.read_text(encoding="utf-8"))["scenarios"] if s["id"] == SCENARIO)


class AnAgentThatAnswersPeople(unittest.TestCase):
    def test_the_scenario_exists_and_grades_every_part(self):
        self.assertIn(SCENARIO, scenario_ids("creating-fabric-agents"))
        self.assertEqual(tuple(scenario()["expected"]), EXPECTED)

    def test_step_0_asks_and_step_1_links(self):  # an-agent-that-answers-people (expected 1)
        step_0 = section("creating-fabric-agents", "Step 0: the intake grill")
        rows = [" ".join(line.split()) for line in text("creating-fabric-agents/SKILL.md").splitlines()
                if line.startswith("| **Does it answer people?**")]
        self.assertEqual(rows, [STEP_0_ROW], "the row whole, nothing added at its edges")
        self.assertIn("Does it answer people?", step_0)
        self.assertIn("(references/agents-that-answer-people.md)", step_0)
        for words in ("turn record", "support.quality_daily", "vendor exclusion", "offline replay", "false-state gates",
                      "material first", "from tools", "live tail", "repair then research then a hold that comes back",
                      "hand-offs by cause and never counted or judged as answers", "commitments ledger",
                      "`answer` flag", "gap queue", "feed re-read"):
            self.assertIn(words, step_0, words)
        self.assertIn("](references/agents-that-answer-people.md)", text("creating-fabric-agents/SKILL.md"))
        self.assertIn("agents-that-answer-people.md", section("creating-fabric-agents", "Step 1: the knowledge intake"))

    def test_the_reference_carries_every_part_with_its_check(self):  # an-agent-that-answers-people (expected 2 to 7)
        self.assertIn("built and tested in its first release, not a later improvement", flat(REFERENCE))
        # Unit round 2: a graded clause is looked for in the parts alone, so a copy in the sources line or the checklist
        # cannot stand in for a part that lost it.
        parts_body = text(REFERENCE).split("## The record and the daily report")[1].split("## Checklist")[0]
        parts_body = " ".join(parts_body.split())
        for words in ("trace id", "small talk, limit, error", "support.quality_daily",
                      "per closed UTC day and channel", "`notMeasured`", "never 0",
                      "another vendor than the writer", "the judge is another vendor than both",
                      "another vendor than its primary", "actually drafted", "Count what the fallback recovered",
                      "false-state gates come first", "sees the material, and sees it before the instructions",
                      "Repair, then research, then hold", "A hold comes back by itself",
                      "A hand-off is never an answer", "stay out of the judge's sample",
                      "`policy`, `inability` and `infrastructure`", "A commitments ledger", "`answer` flag",
                      "keeps no threshold of its own", "becomes a gap in a queue", "the client asks again",
                      "re-reads its feed once", "on its events feed", "a hold on the material included",
                      "one repair with the checker's reason", "one research turn", "an honest holding line"):
            self.assertIn(words, parts_body, words)
        body = text(REFERENCE).split("## Checklist")[0]
        parts = re.split(r"^- \*\*", body, flags=re.MULTILINE)[1:]
        found = tuple(" ".join(p.split("\n## ")[0].split()) for p in parts)
        self.assertEqual(len(found), 17)
        self.assertEqual([p.split("**")[1] for p in found if "Check:" not in p], [], "every part carries its check")
        self.assertEqual(found, PARTS, "every part whole")
        # Product round 2: the checklist, the Step 0 row and the CHANGELOG name the parts a builder could otherwise
        # skip.
        tail = text(REFERENCE).split("## Checklist")[1].splitlines()
        lines = tuple(line[6:] for line in tail if line.startswith("- [ ]"))
        self.assertEqual(lines, CHECKLIST)
        checklist = " ".join(lines)
        step_0 = section("creating-fabric-agents", "Step 0: the intake grill")
        changelog_text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split("## 0.55.0")[1].split("## 0.54.0")[0]
        changelog = " ".join(changelog_text.split())
        # Unit round 5: each pin equals its whole block, so text added at its edges fails too.
        entries = [" ".join(("- " + e).split()) for e in ("\n" + changelog_text).split("\n- ")[1:]
                   if e.startswith("**creating-fabric-agents: agents that answer people**")]
        self.assertEqual(entries, [CHANGELOG_ENTRY])
        for words in ("offline replay", "from tools", "live tail"):
            for where, said in (("checklist", checklist), ("Step 0", step_0), ("CHANGELOG", changelog)):
                self.assertIn(words, said, (where, words))
        for words in ("material before the instructions", "routes `policy` before it", "keep 30 days or fewer"):
            self.assertIn(words, changelog, words)
        reference = flat(REFERENCE)
        self.assertIn("DEC-0070", reference)
        self.assertIn("#model-answers-are-untrusted-until-accepted", reference)
        self.assertIn("reaches back only as far as the producer's feed keeps", reference)
        self.assertNotIn("the template carries", reference)

    def test_the_sources_are_addressed_by_commit(self):
        reference = flat(REFERENCE)
        for words in ("agent-stack/blob/28a0303c42038778e2650fc51096e589f4035239/", "support-quality.md",
                      "agent-stack/blob/f882358e3fb9627f6edb20db3981818912a9844c/", "support-practices.md"):
            self.assertIn(words, reference, words)

    def test_the_recipe_is_the_draft_and_check_step(self):  # seam round 1: the recipe and the reference agree
        recipe = flat("building-fabric-services/recipes/support-agent/README.md")
        readme = text("building-fabric-services/recipes/support-agent/README.md")
        paragraphs = [" ".join(p.split()) for p in readme.split("\n\n")]
        self.assertIn(RECIPE_PARAGRAPH, paragraphs, "the paragraph whole, nothing added at its edges")
        self.assertIn(RECIPE_RETENTION, paragraphs)
        for words in ("the draft-and-check step of an agent that answers people, not that agent",
                      "agents-that-answer-people.md", "`infrastructure`", "`inability`", "`policy`",
                      "and so is `unsupported:number` while the decision returns no draft", "model checker",
                      "at most 30",
                      "only a hold on the material counts as `inability`", "at the first refusal", "`on_handoff=`",
                      "per-item `answer` flag", "under a new message id",
                      "same-vendor fallback", "`model:payment`", "an `on_handoff` that redacts what it stores"):
            self.assertIn(words, recipe, words)
        self.assertIn("recipes/support-agent/", flat(REFERENCE))
        self.assertIn("agents-that-answer-people.md", flat("building-fabric-services/SKILL.md"))
        self.assertNotIn("](../../", text(REFERENCE), "the reference names a sibling skill's page in prose")


if __name__ == "__main__":
    unittest.main()
