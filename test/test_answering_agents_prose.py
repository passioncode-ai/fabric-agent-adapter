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
        for line, word in zip(expected, ("agents-that-answer-people.md", "support.quality_daily", "other vendors",
                                         "false-state", "research", "commitments ledger", "answer flag")):
            self.assertIn(word, line, word)

    def test_step_0_asks_and_step_1_links(self):  # an-agent-that-answers-people (expected 1)
        self.assertIn("Does it answer people?", section("creating-fabric-agents", "Step 0: the intake grill"))
        self.assertIn("](references/agents-that-answer-people.md)", text("creating-fabric-agents/SKILL.md"))
        self.assertIn("agents-that-answer-people.md", section("creating-fabric-agents", "Step 1: the knowledge intake"))

    def test_the_reference_carries_every_part_with_its_check(self):  # an-agent-that-answers-people (expected 2 to 7)
        reference = flat(REFERENCE)
        for words in ("not a later improvement", "trace id", "small talk, limit, error", "support.quality_daily",
                      "per closed UTC day and channel", "`notMeasured`", "never 0",
                      "another vendor than the writer", "the judge is another vendor than both",
                      "another vendor than its primary", "actually drafted", "Count what the fallback recovered",
                      "false-state gates come first", "sees the material, and sees it before the instructions",
                      "Repair, then research, then hold", "A hold comes back by itself",
                      "A hand-off is never an answer", "stay out of the judge's sample",
                      "`policy`, `inability` and `infrastructure`", "A commitments ledger", "`answer` flag",
                      "keeps no threshold of its own", "becomes a gap in a queue", "the client asks again",
                      "re-reads its feed once"):
            self.assertIn(words, reference, words)
        body = text(REFERENCE).split("## Checklist")[0]
        parts = re.split(r"^- \*\*", body, flags=re.MULTILINE)[1:]
        self.assertEqual(len(parts), 17)
        self.assertEqual([p.split("**")[0] for p in parts if "Check:" not in p], [], "every part carries its check")

    def test_the_sources_are_addressed_by_commit(self):
        reference = flat(REFERENCE)
        for words in ("agent-stack/blob/28a0303c42038778e2650fc51096e589f4035239/", "support-quality.md",
                      "agent-stack/blob/f882358e3fb9627f6edb20db3981818912a9844c/", "support-practices.md"):
            self.assertIn(words, reference, words)

    def test_the_recipe_is_the_draft_and_check_step(self):  # seam round 1: the recipe and the reference agree
        recipe = flat("building-fabric-services/recipes/support-agent/README.md")
        for words in ("the draft-and-check step of an agent that answers people, not that agent",
                      "agents-that-answer-people.md", "`infrastructure`", "`inability`"):
            self.assertIn(words, recipe, words)
        self.assertIn("recipes/support-agent/", flat(REFERENCE))
        self.assertNotIn("](../../", text(REFERENCE), "the reference names a sibling skill's page in prose")


if __name__ == "__main__":
    unittest.main()
