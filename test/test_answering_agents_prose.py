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

# Unit round 3: the part titles, their checks, the checklist and the graded lines are pinned whole, so removing any
# clause of one fails here; a deliberate change edits these in the same commit.
PARTS = (
    ('Every inbound message is a turn with a trace id',
     'Check: a test that a turn without a trace id, or with an outcome outside the list, is refused.'),
    ('The agent publishes one `support.quality_daily` per closed UTC day and channel',
     "Check: the producer's day passes `make_event`; and a test runs every `notMeasured` name the producer can emit"
     " through the published name pattern, iterating the producer's own list."),
    ('A table of lanes',
     "Check: the config loader refuses a fallback that shares its own lane's primary vendor, a profile where some "
     'writer route has no checker route of another vendor, and a judge with no route outside the vendors of the '
     'writers and the checkers (the vendor is the prefix before `/`).'),
    ('Count what the fallback recovered',
     'Check: a test that a recovered call counts once as a failure of the primary and once as a recovery, and is '
     'never counted as an error of the turn.'),
    ('A writer model or reasoning budget changes only after an offline replay',
     "Check: the config loader refuses a change of the writer lane's model or reasoning budget that names no replay"
     ' report.'),
    ('Deterministic false-state gates come first',
     'Check: planted drafts with each false claim are refused before any model checker runs.'),
    ('The checker sees the material, and sees it before the instructions',
     'Check: a planted correct answer whose material is longer than the instructions passes the checker.'),
    ('Numbers and account state come from tools',
     'Check: a planted draft with a price or an account state that no tool result of the turn carries is refused.'),
    ("Before sending, re-read the conversation's live tail",
     'Check: a reply that lands in the conversation while the draft is checked makes the agent send nothing.'),
    ('Repair, then research, then hold',
     'Check: a planted refusal walks all three steps in order.'),
    ('A hold comes back by itself',
     'Check: closing the gap behind a held turn produces one reply in that conversation, and only one.'),
    ('A hand-off is never an answer',
     "Check: the daily report counts a hand-off under hand-offs, and the judge's sample builder leaves templated "
     'replies out.'),
    ('Hand-offs are counted by cause',
     'Check: a checker outage produces `infrastructure` hand-offs, never `inability`.'),
    ('A commitments ledger',
     'Check: a reply that promises to come back without a ledger row is refused.'),
    ('The knowledge client keeps no threshold of its own',
     "Check: a test that changing the client's configuration cannot make an item with `answer: false` an answer."),
    ('Every abstention and every inability, a hold included, becomes a gap in a queue',
     'Check: a closed gap whose new answer comes back with `answer: false` leaves the hold in place.'),
    ('A reader that starts accepting a new event kind re-reads its feed once',
     'Check: a test adds a kind to the reader and sees the earlier events of that kind delivered once.'),
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
    "reads the knowledge service's answer flag with no threshold of its own, queues every abstention and every hold"
    ' as a gap and asks again after it closes, and re-reads its feed once when it starts reading a new event kind',
)


def scenario():
    path = ROOT / "test/evals/creating-fabric-agents/scenarios.json"
    return next(s for s in json.loads(path.read_text(encoding="utf-8"))["scenarios"] if s["id"] == SCENARIO)


class AnAgentThatAnswersPeople(unittest.TestCase):
    def test_the_scenario_exists_and_grades_every_part(self):
        self.assertIn(SCENARIO, scenario_ids("creating-fabric-agents"))
        self.assertEqual(tuple(scenario()["expected"]), EXPECTED)

    def test_step_0_asks_and_step_1_links(self):  # an-agent-that-answers-people (expected 1)
        step_0 = section("creating-fabric-agents", "Step 0: the intake grill")
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
                      "re-reads its feed once", "on its events feed", "every inability, a hold included",
                      "one repair with the checker's reason", "one research turn", "an honest holding line"):
            self.assertIn(words, parts_body, words)
        body = text(REFERENCE).split("## Checklist")[0]
        parts = re.split(r"^- \*\*", body, flags=re.MULTILINE)[1:]
        found = [(" ".join(p.split("\n## ")[0].split()).split("**")[0],
                  "Check:" + " ".join(p.split("\n## ")[0].split()).split("Check:", 1)[-1]) for p in parts]
        self.assertEqual(len(found), 17)
        self.assertEqual(tuple(found), PARTS, "every part, its title and its whole check")
        # Product round 2: the checklist, the Step 0 row and the CHANGELOG name the parts a builder could otherwise
        # skip.
        tail = text(REFERENCE).split("## Checklist")[1].splitlines()
        lines = tuple(line[6:] for line in tail if line.startswith("- [ ]"))
        self.assertEqual(lines, CHECKLIST)
        checklist = " ".join(lines)
        step_0 = section("creating-fabric-agents", "Step 0: the intake grill")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split("## 0.55.0")[1].split("## 0.54.0")[0]
        changelog = " ".join(changelog.split())
        for words in ("offline replay", "from tools", "live tail"):
            for where, said in (("checklist", checklist), ("Step 0", step_0), ("CHANGELOG", changelog)):
                self.assertIn(words, said, (where, words))
        for words in ("material before the instructions", "routes `policy` before it", "at most 30 days"):
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
        for words in ("the draft-and-check step of an agent that answers people, not that agent",
                      "agents-that-answer-people.md", "`infrastructure`", "`inability`", "`policy`",
                      "`unsupported:number` where the reply states a price, is a money reason", "model checker",
                      "at most 30",
                      "only a hold counts as `inability`", "at the first refusal", "`on_handoff=`",
                      "per-item `answer` flag", "under a new message id",
                      "same-vendor fallback", "`model:payment`", "redacts before `on_handoff`"):
            self.assertIn(words, recipe, words)
        self.assertIn("recipes/support-agent/", flat(REFERENCE))
        self.assertIn("agents-that-answer-people.md", flat("building-fabric-services/SKILL.md"))
        self.assertNotIn("](../../", text(REFERENCE), "the reference names a sibling skill's page in prose")


if __name__ == "__main__":
    unittest.main()
