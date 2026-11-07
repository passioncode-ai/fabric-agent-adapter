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
        "Any ask, even a vague one", "a complaint about the product"],
    3: ["Analyse, plan and draft in ONE call", "injection {suspected, what}", "scope (the product or off-topic)", "evidence (the knowledge ids it used)",
        "a separate cheap drafter after the plan scored lower at the same cost, so there is none"],
    4: ["Final pass (the planning model, thinking low) only when an action returned information the reply must use"],
    5: ["then a checker of another vendor than the model that drafted this turn", "never the plan's own `evidence`",
        "whose plan has no injection verdict, or whose call failed, is held"],
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

    def test_every_event_kind_it_names_passes_the_kit_writers_kind_rule(self):
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

    def test_the_recipe_readme_skips_check_reply_by_the_templates_routes(self):
        readme = flat("building-fabric-services/recipes/support-agent/README.md")
        for phrase in ("an off-topic plan", "a plan whose only actions are ask_clarification or handoff",
                       "a triage reply", "never the draft's markers"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readme)
                self.assertIn(phrase, flat(TEMPLATE))
        self.assertNotIn("no fact to cite", readme)
        self.assertNotIn("no fact to cite", flat(TEMPLATE))

    def test_the_declaration_rules_a_builder_follows_hold_under_the_probe(self):
        """0.75.0 readings, round 10: a real answered signal drops the queue's recommendation (FAC-SEM-164), and the
        operator's in-chat decision is carried out once, never held again (CA-8, the standard's 4.10)."""
        body = flat(TEMPLATE)
        for phrase in ("replaces with a real signal and then drops its `recommendation`",
                       "carried out once within CA-8's bounds and never held again"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)

    def test_the_changelog_counts_the_adversarial_batches_the_template_lists(self):
        import re
        body = flat(TEMPLATE)
        listed = body.split("The adversarial batches, each with its expected behaviour, all passing: ", 1)[1]
        listed = listed.split(" - Clarifying questions", 1)[0]
        said = re.search(r"the acceptance with (\d+) adversarial batches",
                         " ".join((ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split()))
        self.assertEqual(int(said.group(1)), len(listed.split("; ")))


if __name__ == "__main__":
    unittest.main()
