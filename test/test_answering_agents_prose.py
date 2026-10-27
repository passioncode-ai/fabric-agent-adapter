"""FAA-162 (0.55.0): what creating-fabric-agents must say about an agent that answers people, pinned to the scenario eval
`an-agent-that-answers-people` (test/evals/creating-fabric-agents/scenarios.json), which a model judges and hosted CI
cannot run. Sources: agent-stack's support quality standard (A1, A5) and its practices from an audit of five such
agents (P1 to P8), linked from the reference at their commits; board request 1ad39d4e."""

import unittest

from test_action_and_dashboard_prose import body, flat, scenario_ids

REFERENCE = "creating-fabric-agents/references/agents-that-answer-people.md"


class AnAgentThatAnswersPeople(unittest.TestCase):
    def test_the_scenario_exists(self):
        self.assertIn("an-agent-that-answers-people", scenario_ids("creating-fabric-agents"))

    def test_the_skill_sends_such_an_agent_to_the_reference(self):  # an-agent-that-answers-people (expected 1)
        self.assertIn("references/agents-that-answer-people.md", body("creating-fabric-agents"))

    def test_the_reference_carries_every_part_with_its_check(self):  # an-agent-that-answers-people (expected 2 to 7)
        reference = flat(REFERENCE)
        for words in ("trace id", "support.quality_daily", "`notMeasured`", "never 0",
                      "another vendor than the writer", "Count what the fallback recovered",
                      "false-state gates come first", "sees the material, and sees it before the instructions",
                      "Repair, then research, then hold", "A hold comes back by itself",
                      "A hand-off is never an answer", "`policy`, `inability` and `infrastructure`",
                      "A commitments ledger", "`answer` flag", "keeps no threshold of its own",
                      "becomes a gap in a queue", "re-reads its feed once"):
            self.assertIn(words, reference, words)
        self.assertEqual(reference.count("Check:"), 14)  # every part listed with its check

    def test_the_sources_are_addressed_by_commit(self):
        reference = flat(REFERENCE)
        for words in ("agent-stack/blob/28a0303c42038778e2650fc51096e589f4035239/", "support-quality.md",
                      "agent-stack/blob/f882358e3fb9627f6edb20db3981818912a9844c/", "support-practices.md"):
            self.assertIn(words, reference, words)


if __name__ == "__main__":
    unittest.main()
