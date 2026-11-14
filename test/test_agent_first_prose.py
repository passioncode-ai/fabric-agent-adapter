"""FAA-332 (0.88.0): every agent is built for agents first, so no function a person can see or change is out of an
agent's reach. The operator's rule of 2026-11-14 (this repository's session; passed to the contract on the board).

The scenario evals in test/evals/<skill>/scenarios.json are judged by a model, so hosted CI cannot run them. These
tests hold the prose those scenarios grade to the words that carry the rule: each check names the scenario it serves.
Contract DEC-0121 AP-1 makes write parity normative for a service's actions; read parity and the design order are the
operator's rule (AS-1 to AS-6 of the shared reference references/agent-surface.md)."""

import unittest

from test_action_and_dashboard_prose import body, flat, scenario_ids, section, text

REFERENCE = "references/agent-surface.md"


class EvalsComeFirst(unittest.TestCase):
    def test_the_scenarios_exist(self):
        wanted = {
            "creating-fabric-agents": {"every-function-is-an-agent-capability-first"},
            "adapting-projects-to-fabric": {"a-page-only-function-gets-its-capability"},
            "building-fabric-services": {"every-view-has-a-read-tool"},
        }
        for skill, ids in wanted.items():
            self.assertEqual(ids - scenario_ids(skill), set(), skill)


class TheReferenceCarriesTheRule(unittest.TestCase):
    def test_the_six_rules(self):  # every-function-is-an-agent-capability-first, a-page-only-function-gets-its-capability
        for skill in ("creating-fabric-agents", "adapting-projects-to-fabric"):
            words = " ".join(text("%s/%s" % (skill, REFERENCE)).split())
            for needle in ("AS-1", "AS-2", "AS-3", "AS-4", "AS-5", "AS-6", "no function a person can reach and an agent cannot",
                           "not to view, not to edit", "the same data with the same filters and paging",
                           "same effect, the same checks, the same audit record and an idempotency key", "DEC-0121 AP-1",
                           "human-step-required", "built before the release, never filed for later", "dashboard.agent-surface"):
                self.assertIn(needle, words, (skill, needle))
            self.assertNotIn("—", words)


class EachSkillAppliesIt(unittest.TestCase):
    def test_creating_asks_it_in_the_grill_and_builds_it_in_step_4(self):  # every-function-is-an-agent-capability-first
        grill = " ".join(section("creating-fabric-agents", "Step 0: the intake grill").split())
        self.assertIn("**Agent first?**", grill)
        self.assertIn("](%s)" % REFERENCE, grill)
        step = " ".join(section("creating-fabric-agents", "Step 4: implement against the observables").split())
        for needle in ("capability first", "a view over", "AS-6"):
            self.assertIn(needle, step, needle)

    def test_adapting_inventories_the_persons_functions(self):  # a-page-only-function-gets-its-capability
        skill = " ".join(body("adapting-projects-to-fabric").split())
        for needle in ("### 4d. Give an agent every function a person has", "every function a person reaches",
                       "](%s)" % REFERENCE, "before you call the adaptation done"):
            self.assertIn(needle, skill, needle)

    def test_services_read_every_view(self):  # every-view-has-a-read-tool
        skill = " ".join(body("building-fabric-services").split())
        self.assertIn("**and every view a read tool**", skill)
        dashboard = flat("building-fabric-services/references/dashboard.md")
        self.assertIn("Every view has a read tool", dashboard)
        interop = flat("building-fabric-services/references/interop.md")
        for needle in ("**Read parity.**", "dashboard.agent-surface"):
            self.assertIn(needle, interop, needle)


if __name__ == "__main__":
    unittest.main()
