"""FAA-333 (0.89.0): what working-with-fabric must say about a level holder's word (contract DEC-0162, LV-2 to LV-7,
`v0.1.0+2026-11-14.2`), pinned to the scenario eval that asks for it. The scenarios are judged by a model, so hosted CI
cannot run them; these tests hold the prose they grade to the words that carry the rule."""
import unittest

from test_action_and_dashboard_prose import body, flat, scenario_ids

REFERENCE = "references/authority-levels.md"


class EvalsComeFirst(unittest.TestCase):
    def test_the_scenario_exists(self):
        self.assertIn("a-level-holders-word-in-an-organization", scenario_ids("working-with-fabric"))


class WorkingWithFabricCarriesTheLevels(unittest.TestCase):
    def test_the_skill_points_at_the_reference(self):  # a-level-holders-word-in-an-organization
        skill = " ".join(body("working-with-fabric").split())
        self.assertIn("a level holder's word counts as his within their level (DEC-0162", skill)
        self.assertIn("](%s)" % REFERENCE, skill)

    def test_the_reference_says_what_a_level_decides(self):  # a-level-holders-word-in-an-organization
        words = flat("working-with-fabric/%s" % REFERENCE)
        for needle in ("LV-2", "LV-3", "LV-5", "LV-6", "LV-7", "`by: level`", "`via: level-command`", "`mem`",
                       "org-membership/2", "level-insufficient: owner", "level-insufficient: admin",
                       "one request to a holder of that level", "never in the operator's form",
                       "a human step, spend above a limit, a personal context"):
            self.assertIn(needle, words, needle)
        self.assertNotIn("—", words)


if __name__ == "__main__":
    unittest.main()
