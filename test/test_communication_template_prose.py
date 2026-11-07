"""The Fabric communication agent template (FAA-262, 0.75.0): the scenario that grades a build from it, and each phrase
of the template that scenario's expected lines rely on. A rewording of the template that drops one fails here."""
import json
import unittest

from test_action_and_dashboard_prose import ROOT, flat

TEMPLATE = "creating-fabric-agents/references/communication-agent-template.md"
SCENARIO = "a-channel-agent-starts-from-the-communication-template"
# Each expected line of the scenario, and the template phrases it rests on (whitespace normalised).
RESTS_ON = {
    0: ["Fill in the brief (section 0 of the prompt)", "a question for the owner before the build"],
    1: ["Batch a person's burst into one turn", "Claim the ticket atomically with an idempotency key before any model call"],
    2: ["Triage (the planning model, thinking low, no knowledge in the prompt) of the whole batch",
        "Any ask, even a vague one"],
    3: ["Analyse, plan and draft in ONE call", "injection {suspected, what}", "evidence (the knowledge ids it used)",
        "a separate cheap drafter after the plan scored lower at the same cost, so there is none"],
    4: ["Final pass (the planning model, thinking low) only when an action returned information the reply must use"],
    5: ["then a checker of another vendor than the drafter"],
    6: ["every other channel hands a lead to its queue", "a sales agent of its own owns the CRM and the lead",
        "Prices, discounts and terms only from the knowledge or the CRM"],
    7: ["default USD 100 a month for a new agent", "the code stops a little under the key's limit"],
}


def scenario():
    data = json.loads((ROOT / "test/evals/creating-fabric-agents/scenarios.json").read_text(encoding="utf-8"))
    return next(s for s in data["scenarios"] if s["id"] == SCENARIO)


class TheTemplateCarriesWhatItsScenarioGrades(unittest.TestCase):
    def test_every_expected_line_has_its_phrases(self):
        expected = scenario()["expected"]
        self.assertEqual(len(expected), len(RESTS_ON))
        body = flat(TEMPLATE)
        for i, phrases in RESTS_ON.items():
            for phrase in phrases:
                with self.subTest(line=i, phrase=phrase):
                    self.assertIn(" ".join(phrase.split()), body)

    def test_every_event_kind_it_names_is_one_the_kit_writes(self):
        import importlib
        import sys
        sys.path.insert(0, str(ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"))
        events = importlib.import_module("fabric_events")
        for kind in ("support.quality_daily", "answer.cited", "support.handed_off", "support.diagnosed",
                     "knowledge.learned", "knowledge.retracted", "support.tickets_daily"):
            with self.subTest(kind=kind):
                self.assertIn(kind, flat(TEMPLATE))
                events.make_event("1", "2026-11-07T00:00:00Z", kind, "info", "x")
        self.assertNotIn("handedOff", flat(TEMPLATE))


if __name__ == "__main__":
    unittest.main()
