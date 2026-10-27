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


def scenario():
    path = ROOT / "test/evals/creating-fabric-agents/scenarios.json"
    return next(s for s in json.loads(path.read_text(encoding="utf-8"))["scenarios"] if s["id"] == SCENARIO)


class AnAgentThatAnswersPeople(unittest.TestCase):
    def test_the_scenario_exists_and_grades_every_part(self):
        self.assertIn(SCENARIO, scenario_ids("creating-fabric-agents"))
        expected = scenario()["expected"]
        self.assertEqual(len(expected), 7)
        graded = (("agents-that-answer-people.md", "first release, not later"),
                  ("trace id", "outcome from the fixed list", "support.quality_daily", "closed UTC day and channel",
                   "notMeasured", "never 0"),
                  ("fallback of another vendor than its primary", "checker of another vendor than the writer",
                   "judge of another vendor than both", "fallback recovered", "offline replay"),
                  ("false-state gates before the model checker", "material before the instructions",
                   "numbers and account state from tools", "live tail"),
                  ("repairs once", "one research turn", "holds honestly", "comes back by itself"),
                  ("by cause", "never as answers", "judge's sample", "commitments ledger"),
                  ("answer flag", "no threshold of its own", "as a gap", "asks again", "re-reads its feed once"))
        for line, words in zip(expected, graded):
            for word in words:
                self.assertIn(word, line, word)

    def test_step_0_asks_and_step_1_links(self):  # an-agent-that-answers-people (expected 1)
        step_0 = section("creating-fabric-agents", "Step 0: the intake grill")
        self.assertIn("Does it answer people?", step_0)
        self.assertIn("(references/agents-that-answer-people.md)", step_0)
        self.assertIn("](references/agents-that-answer-people.md)", text("creating-fabric-agents/SKILL.md"))
        self.assertIn("agents-that-answer-people.md", section("creating-fabric-agents", "Step 1: the knowledge intake"))

    def test_the_reference_carries_every_part_with_its_check(self):  # an-agent-that-answers-people (expected 2 to 7)
        self.assertIn("not a later improvement", flat(REFERENCE))
        # Unit round 2: a graded clause is looked for in the parts alone, so a copy in the sources line or the checklist
        # cannot stand in for a part that lost it.
        parts_body = " ".join(text(REFERENCE).split("## The record and the daily report")[1].split("## Checklist")[0].split())
        for words in ("trace id", "small talk, limit, error", "support.quality_daily",
                      "per closed UTC day and channel", "`notMeasured`", "never 0",
                      "another vendor than the writer", "the judge is another vendor than both",
                      "another vendor than its primary", "actually drafted", "Count what the fallback recovered",
                      "false-state gates come first", "sees the material, and sees it before the instructions",
                      "Repair, then research, then hold", "A hold comes back by itself",
                      "A hand-off is never an answer", "stay out of the judge's sample",
                      "`policy`, `inability` and `infrastructure`", "A commitments ledger", "`answer` flag",
                      "keeps no threshold of its own", "becomes a gap in a queue", "the client asks again",
                      "re-reads its feed once"):
            self.assertIn(words, parts_body, words)
        body = text(REFERENCE).split("## Checklist")[0]
        parts = re.split(r"^- \*\*", body, flags=re.MULTILINE)[1:]
        self.assertEqual(len(parts), 17)
        self.assertEqual([p.split("**")[0] for p in parts if "Check:" not in p], [], "every part carries its check")
        # Product round 2: the checklist, the Step 0 row and the CHANGELOG name the parts a builder could otherwise skip.
        checklist = " ".join(text(REFERENCE).split("## Checklist")[1].split())
        step_0 = section("creating-fabric-agents", "Step 0: the intake grill")
        changelog = " ".join((ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split("## 0.55.0")[1].split("## 0.54.0")[0].split())
        for words in ("offline replay", "from tools", "live tail"):
            for where, said in (("checklist", checklist), ("Step 0", step_0), ("CHANGELOG", changelog)):
                self.assertIn(words, said, (where, words))
        reference = flat(REFERENCE)
        self.assertIn("DEC-0070", reference)
        self.assertIn("#model-answers-are-untrusted-until-accepted", reference)
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
                      "`unsupported:amount` is a money reason", "model checker", "at most 30"):
            self.assertIn(words, recipe, words)
        self.assertIn("recipes/support-agent/", flat(REFERENCE))
        self.assertIn("agents-that-answer-people.md", flat("building-fabric-services/SKILL.md"))
        self.assertNotIn("](../../", text(REFERENCE), "the reference names a sibling skill's page in prose")


if __name__ == "__main__":
    unittest.main()
