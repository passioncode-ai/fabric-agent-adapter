"""FAA-131 (0.51.0): what the skills must say about the operator's mandate, pinned to the scenario evals that ask for it.

The scenario evals in test/evals/<skill>/scenarios.json are judged by a model, so hosted CI cannot run them. These
tests hold the prose those scenarios grade to the words that carry the rule: each check names the scenario it serves.
Contract DEC-0125 (`mandate/1`, docs/specification/delegation.md#the-operators-mandate, MD-1 to MD-6) and DEC-0126
(one approval binds all the operator's agents, OA-1 to OA-7, `source` and `operator-source/1`) and DEC-0141 (MJ-1, a
job's step read under the job's capability) at the pin 00e050ba (`v0.1.0+2026-10-27.1`, 0.54.0, FAA-159); the operator's rule of 2026-10-26 (board thread 3e8f706c, request 519d7b21;
fabric-workspace knowledge/agents-first.md) that DEC-0126 answers."""

import json
import unittest

from test_action_and_dashboard_prose import ROOT, body, flat, scenario_ids, section, text


class EvalsComeFirst(unittest.TestCase):
    def test_the_scenarios_exist(self):
        wanted = {
            "working-with-fabric": {"operator-approval-binds-all-his-agents", "board-relay-from-a-trusted-project",
                                    "lead-hands-on-a-narrowed-mandate", "outside-mandate-asks-once-for-that-part",
                                    "relay-source-goes-only-where-it-is-read", "lead-covers-a-job-step-by-its-capability"},
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

    def test_the_record_and_the_stop_rule(self):  # operator-approval-binds-all-his-agents (points 6 and 7)
        for words in ("as your reason", "stop rule", "one-time code", "top-up"):
            self.assertIn(words, self.rule, words)

    def test_only_his_personal_board(self):  # board-relay-from-a-trusted-project
        self.assertIn("personal board", self.rule)
        self.assertIn("never a member's Project on an organization's board", self.body)
        board = flat("working-with-fabric/references/project-board.md")
        self.assertIn("personal board", board)

    def test_the_prose_relay_is_the_pinned_contracts(self):  # operator-approval-binds-all-his-agents
        # At 0.52.0 the pin carries DEC-0126: the relay is the contract's (OA-2, OA-3), no longer ahead of it.
        self.assertNotIn("ahead of this skill's pinned contract", self.rule)
        self.assertNotIn("ahead of the pin", self.rule)
        for words in ("DEC-0126", "OA-1", "OA-2", "OA-3", "OA-4", "OA-5", "OA-6", "OA-7", "copied unchanged",
                      "the runner's own delivery", "L0", "L1"):
            self.assertIn(words, self.rule, words)

    def test_a_job_step_is_covered_by_its_capability(self):  # lead-covers-a-job-step-by-its-capability
        flat_body = " ".join(self.body.split())
        for words in ("name the job's capability in `capabilities` without `actions`", "`mandate-capability-missing`: no mandate covers", "DEC-0141 MJ-1",
                      "its request key as the action"):
            self.assertIn(words, flat_body, words)
        interop = flat("building-fabric-services/references/interop.md")
        for words in ("`mandate-capability-missing`", "covers no step of another capability", "stays `input_required`",
                      "One fault reaches the caller by name", "It logs the `fault`"):  # service-reads-the-operators-mandate
            self.assertIn(words, interop, words)
        self.assertNotIn("`mandate-capability-missing` (`approval-outcome-unreadable`", interop)
        self.assertNotIn("the answer is read under `fabric.job.get`", interop)

    def test_source_goes_only_where_it_is_read(self):  # relay-source-goes-only-where-it-is-read
        for words in ("`source`", "`operator-source/1`", "request_meta(target_protocols=", "your own record",
                      "without `source`", "never to an events feed"):
            self.assertIn(words, self.rule, words)
        board = flat("working-with-fabric/references/project-board.md")
        self.assertNotIn("ahead of the pinned contract", board)
        for words in ("OA-2", "OA-7", "without `source`"):
            self.assertIn(words, board, words)

    def test_only_the_lead_asks(self):  # outside-mandate-asks-once-for-that-part (MD-4)
        self.assertIn("pass the refusal to the agent that called you", self.rule)

    def test_call_mandate_waits_for_the_hub(self):  # the CT-125 caveat
        self.assertIn("`call.mandate` of Fabric's `agent.call` once Fabric's hub forwards it", self.rule)

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

    def test_the_contract_decision_is_taken(self):  # the note the operator asked for
        # The contract answered request 519d7b21 with DEC-0126; 0.52.0 pins it (FAA-134), so no "next release" remains.
        self.assertIn("DEC-0126", self.rule)
        self.assertNotIn("next release", self.rule)


class BuildingFabricServicesReadsTheMandate(unittest.TestCase):
    def test_the_interop_reference(self):  # service-reads-the-operators-mandate
        interop = flat("building-fabric-services/references/interop.md")
        self.assertTrue("\n## The operator's mandate" in text("building-fabric-services/references/interop.md"), "no section")
        for words in ("_meta.mandate", "agent_id=", "add_tool(tool, handler, action=, effect=", "self_id", "ctx.mandate",
                      "request_meta(traceparent, mandate=", "requestMeta(traceparent, {mandate})", "hand_on(", "handOn(",
                      "operator_mandate(", "outside-mandate:", "mandate-not-for-this-call", "never from its arguments",
                      "T2", "fabric_mandate"):
            self.assertIn(words, interop, words)

    def test_the_interop_reference_carries_the_source(self):  # service-reads-the-operators-mandate (DEC-0126)
        interop = flat("building-fabric-services/references/interop.md")
        self.assertNotIn("ahead of the pin", interop)
        for words in ("DEC-0126", "OA-6", "OA-7", "`operator-source/1`", "well_known_protocols(", "request_meta(traceparent, decision=, mandate=, target_protocols=",
                      "targetProtocols", "operator_mandate(..., source=", "operator_decision(..., source=", "approval_step(",
                      "jobStep(", "C3.3", "builds its own list"):
            self.assertIn(words, interop, words)

    def test_the_shared_operator_channel_reference_cites_the_relay(self):  # operator-approval-binds-all-his-agents
        for skill in ("creating-fabric-agents", "adapting-projects-to-fabric"):
            shared = flat("%s/references/operator-channel-and-repository.md" % skill)
            for words in ("DEC-0126", "OA-2", "OA-7", "`operator-source/1`"):
                self.assertIn(words, shared, words)



class AComparisonOfCodesIsAHumanStep(unittest.TestCase):
    """DEC-0142 (contract CT-186) at the pin 3830a33 (`v0.1.0+2026-10-27.6`, 0.57.0, FAA-176): AP-4's steps gain
    `comparison`, a comparison of codes between two people or the choice to share without one; it stays the person's."""

    def test_the_scenarios_ask_for_it(self):  # human-step-required-hands-over-the-link, operator-approval-binds-all-his-agents
        scenarios = {s["id"]: " ".join(s["expected"]) for s in json.loads(
            (ROOT / "test/evals/working-with-fabric/scenarios.json").read_text(encoding="utf-8"))["scenarios"]}
        for sid in ("human-step-required-hands-over-the-link", "operator-approval-binds-all-his-agents"):
            self.assertIn("or the choice to share without one", scenarios[sid], sid)

    def test_working_with_fabric_names_it_a_human_gate(self):  # operator-approval-binds-all-his-agents
        rule = section("working-with-fabric", "Step 5: while you work")
        self.assertIn("a comparison of codes with another person or the choice to share without one (DEC-0142)", rule)
        refusals = section("working-with-fabric", "Refusals and lost answers")
        row = next(line for line in refusals.split("| `human-step-required`")[1:])
        self.assertIn("a human gate of OA-5 (above) stays the person's", row)

    def test_the_service_references_list_seven_steps(self):  # service-reads-the-operators-mandate
        interop = flat("building-fabric-services/references/interop.md")
        self.assertIn("`passkey`, `comparison` (a comparison of codes between two people or the choice to share without one, DEC-0142)", interop)
        self.assertIn("a reader pinned before it (a 0.56.0 or older kit, Fabric's node before CO-479) refuses the whole declaration", interop)
        delegation = flat("building-fabric-services/references/delegation.md")
        self.assertIn("`passkey`, and since DEC-0142 `comparison`: a comparison of codes between two people or the choice to share without one", delegation)
        self.assertIn("a reader pinned before DEC-0142 refuses a whole declaration that names it", delegation)


if __name__ == "__main__":
    unittest.main()
