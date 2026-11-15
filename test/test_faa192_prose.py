"""FAA-192 (19), (20), (25), (26), (30), 0.90.3: the prose and scenarios of 0.59.0's licence, data and uptime rules hold
the clauses the fourth to sixth readings found held by no test, and the scenarios ask what their requests describe.

The scenario evals are judged by a model, so hosted CI cannot run them; these tests hold the words they grade."""

import json
import unittest

from test_action_and_dashboard_prose import ROOT, body, flat

CREATING, ADAPTING, BUILDING = "creating-fabric-agents", "adapting-projects-to-fabric", "building-fabric-services"


def scenario(skill: str, sid: str) -> str:
    scenarios = json.loads((ROOT / "test/evals" / skill / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
    return " ".join(json.dumps(s, ensure_ascii=False) for s in scenarios if s["id"] == sid)


class ClausesHeldByATest(unittest.TestCase):
    """(20): the four clauses the r4 fix added, and the building scenario's 'a new agent'."""

    def test_the_client_case_reaches_the_operator_channel_references_and_step_2(self):
        for skill in (CREATING, ADAPTING):
            self.assertIn("a new private agent built for a client", flat(skill + "/references/operator-channel-and-repository.md"))
        self.assertIn("a private agent built for a client, is not a PassionCode.ai repository", body(CREATING))
        self.assertIn("in an agent built for a client too", body(BUILDING))

    def test_the_licence_file_is_named_by_its_own_path(self):
        for skill in (CREATING, ADAPTING):
            self.assertIn("file by its own path (`LICENSE`, `LICENSE.md`)", flat(skill + "/references/source-and-instance.md"))

    def test_the_laptop_closed_scope_is_the_calls_fabric_admits(self):
        self.assertIn("for the calls Fabric admits, a hub that can admit them", flat(CREATING + "/references/where-agents-run.md"))

    def test_the_building_scenario_is_a_new_agent(self):
        self.assertIn("a new agent", scenario(BUILDING, "new-service-names-data-and-uptime"))


class ScenariosAskWhatTheyDescribe(unittest.TestCase):
    def test_the_two_context_cloud_agent_asks_uptime_and_data(self):  # (19)
        text = scenario(CREATING, "agent-for-a-personal-and-an-organization-cloud")
        self.assertIn("records category A", text)
        self.assertIn("replaces the Heroku default", text)
        self.assertIn("records kind U", text)

    def test_an_uptime_a_agent_keeps_its_data_in_a_durable_store(self):  # (26)
        text = scenario(CREATING, "portable-from-day-zero")
        self.assertIn("a durable store", text)
        self.assertIn("never a folder beside the checkout", text)

    def test_the_licence_holder_comes_from_the_grill_record(self):  # (25)
        self.assertIn("taken from creating-fabric-agents' grill record", scenario(BUILDING, "new-service-names-data-and-uptime"))

    def test_the_card_lists_the_newest_grill_rows(self):  # (30)
        card = (ROOT / "SKILL-CARD.md").read_text(encoding="utf-8")
        for words in ("agent first", "text for people", "answers people", "uptime A or B", "kind U or O", "who holds the copyright"):
            self.assertIn(words, card)


if __name__ == "__main__":
    unittest.main()
