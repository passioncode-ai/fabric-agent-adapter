"""FAA-338 (contract DEC-0157, UD-1 to UD-6, at the pin since 0.96.0): creating-fabric-agents and building-fabric-services
tell a builder whose agent sends anonymous usage and error data what it owes. The scenario evals
(`an-agent-that-sends-usage-data`, `a-service-that-sends-usage-data`) are judged by a model, so hosted CI cannot run them;
these tests hold the words they grade."""

import json
import unittest

from test_action_and_dashboard_prose import ROOT, body, flat

CREATING, BUILDING = "creating-fabric-agents", "building-fabric-services"
REFERENCE = "/references/usage-data.md"


def scenario(skill: str, sid: str) -> str:
    scenarios = json.loads((ROOT / "test/evals" / skill / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
    found = [json.dumps(s, ensure_ascii=False) for s in scenarios if s["id"] == sid]
    assert found, sid
    return " ".join(found)


class TheReference(unittest.TestCase):
    def test_ud1_nothing_before_the_notice_and_never_a_question(self):
        text = flat(CREATING + REFERENCE)
        for words in ("Send nothing before the notice was shown once where the person reads it",
                      "the agent's first answer in the person's chat", "A line only an agent's tool reads is not that place",
                      "never a question", "no answer means on"):
            self.assertIn(words, text)

    def test_ud2_its_own_switch_read_before_the_first_send(self):
        text = flat(CREATING + REFERENCE)
        for words in ("governs that product alone", "Read it before the first send", "An earlier decline stays off",
                      "drops what waits to be sent", "A product's switch never writes the shared file",
                      "A device policy may lock the switch off, never on"):
            self.assertIn(words, text)

    def test_ud3_anonymous_ids(self):
        text = flat(CREATING + REFERENCE)
        for words in ("a random UUID for analytics only", "kept only in memory", "after an idle hour",
                      "joins either id with an account"):
            self.assertIn(words, text)

    def test_ud4_the_agents_door_and_the_operators_word(self):
        text = flat(CREATING + REFERENCE)
        for words in ("`change-policy`", "`gate: relayed`", "a gate of `none` is nonconformant", "`humanStep: consent`",
                      "Never a mandate, another approver's approval or a standing rule",
                      "never declines a person who asks to turn their switch off"):
            self.assertIn(words, text)

    def test_ud5_and_ud6(self):
        text = flat(CREATING + REFERENCE)
        for words in ("how long it is kept", "the version that turned it on", "can be erased",
                      "Activity telemetry (DEC-0030)", "`GET /fabric/v1/usage`", "OpenRouter attribution (DEC-0065)"):
            self.assertIn(words, text)

    def test_the_two_copies_are_one_text(self):
        self.assertEqual(flat(CREATING + REFERENCE), flat(BUILDING + REFERENCE))


class TheSkills(unittest.TestCase):
    def test_the_grill_asks_and_points_at_the_reference(self):
        text = body(CREATING)
        self.assertIn("**Does it send usage data?**", text)
        self.assertIn("[the usage data reference](references/usage-data.md)", text)
        self.assertIn("`gate: relayed`", text)

    def test_building_says_it_beside_the_usage_report(self):
        text = body(BUILDING)
        self.assertIn("**Anonymous usage and error data** (DEC-0157): notice first, own switch", text)
        self.assertIn("The usage report and a local digest are not usage data", text)
        self.assertIn("(references/usage-data.md)", text)


class TheScenarios(unittest.TestCase):
    def test_each_scenario_asks_what_the_reference_holds(self):
        for skill, sid in ((CREATING, "an-agent-that-sends-usage-data"), (BUILDING, "a-service-that-sends-usage-data")):
            text = scenario(skill, sid)
            for words in ("UD-1", "UD-2", "UD-3", "UD-4", "change-policy", "gate relayed"):
                self.assertIn(words, text, (skill, words))


if __name__ == "__main__":
    unittest.main()
