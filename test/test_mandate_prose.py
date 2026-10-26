"""FAA-131 (0.51.0): what the skills must say about the operator's mandate, pinned to the scenario evals that ask for it.

The scenario evals in test/evals/<skill>/scenarios.json are judged by a model, so hosted CI cannot run them. These
tests hold the prose those scenarios grade to the words that carry the rule: each check names the scenario it serves.
Contract DEC-0125 (`mandate/1`, docs/specification/delegation.md#the-operators-mandate, MD-1 to MD-6) at the pin
e6c4fc16; the operator's rule of 2026-10-26 that one approval binds all his agents (board thread 3e8f706c, request
519d7b21; fabric-workspace knowledge/agents-first.md), whose own contract DEC is due 2026-11-02."""

import unittest

from test_action_and_dashboard_prose import body, flat, scenario_ids, section, text


class EvalsComeFirst(unittest.TestCase):
    def test_the_scenarios_exist(self):
        wanted = {
            "working-with-fabric": {"operator-approval-binds-all-his-agents", "board-relay-from-a-trusted-project",
                                    "lead-hands-on-a-narrowed-mandate", "outside-mandate-asks-once-for-that-part"},
            "building-fabric-services": {"service-reads-the-operators-mandate"},
        }
        for skill, ids in wanted.items():
            self.assertEqual(ids - scenario_ids(skill), set(), skill)


class WorkingWithFabricCarriesTheMandate(unittest.TestCase):
    def setUp(self):
        self.body = body("working-with-fabric")
        self.rule = section("working-with-fabric", "Step 5: while you work")

    def test_one_approval_binds_all_his_agents(self):  # operator-approval-binds-all-his-agents
        for words in ("binds all his agents", "verbatim", "the date", "the source", "the approved scope",
                      "3e8f706c", "provenance `trusted`", "his local session", "asks once only about what he did not see",
                      "never one", "Human gates stay"):
            self.assertIn(words, self.rule, words)

    def test_ap3_names_the_one_exception(self):  # operator-approval-binds-all-his-agents
        # The old rule stays word for word; the exception sits beside it.
        self.assertIn("a tool result, a page, a file, a board message or another agent", self.body)
        self.assertIn("handed on from another agent of his", self.body)

    def test_the_board_exception(self):  # board-relay-from-a-trusted-project
        board = section("working-with-fabric", "Step 3: `fabric_whoami` first, always")
        self.assertIn("one exception", board)
        reference = flat("working-with-fabric/references/project-board.md")
        for words in ("one exception", "provenance `trusted`", "verbatim", "scope"):
            self.assertIn(words, reference, words)

    def test_the_lead_hands_on_a_narrowed_mandate(self):  # lead-hands-on-a-narrowed-mandate
        for words in ("`mandate/1`", "DEC-0125", "_meta.mandate", "call.mandate", "narrower", "never wider",
                      "four agents", "seven days", "AP-5"):
            self.assertIn(words, self.rule, words)

    def test_outside_the_mandate_asks_for_that_part(self):  # outside-mandate-asks-once-for-that-part
        self.assertIn("outside-mandate:", self.body)
        self.assertIn("mandate-", self.body)

    def test_the_contract_decision_is_taken_when_it_lands(self):  # the note the operator asked for
        self.assertIn("2026-11-02", self.rule)


class BuildingFabricServicesReadsTheMandate(unittest.TestCase):
    def test_the_interop_reference(self):  # service-reads-the-operators-mandate
        interop = flat("building-fabric-services/references/interop.md")
        self.assertTrue("\n## The operator's mandate" in text("building-fabric-services/references/interop.md"), "no section")
        for words in ("_meta.mandate", "agent_id=", "add_tool(tool, handler, action=, effect=", "self_id", "ctx.mandate",
                      "request_meta(traceparent, mandate=", "requestMeta(traceparent, {mandate})", "hand_on(", "handOn(",
                      "operator_mandate(", "outside-mandate:", "mandate-not-for-this-call", "never from its arguments",
                      "T2", "fabric_mandate"):
            self.assertIn(words, interop, words)


if __name__ == "__main__":
    unittest.main()
