"""fabric_actions.py: fabric-actions/0.1 (DEC-0121, FAC-SEM-142). The reader and the gate answer every case of the
contract's fixtures/vectors/actions.json, its action-call and service-well-known-actions semantic fixtures and its
decision and service-actions-extension fixtures (vendored as test/fixtures/contract/actions-vectors.json, each answer
re-computed by the contract's functions), and the kit's own inputs answered by the same functions
(actions-extra-vectors.json); the Node twin runs the same files in fabric-actions.test.mjs."""
import json
import math
import unittest
from pathlib import Path

from test_fabric_service import load

fa = load("fabric_actions")
ServiceError = fa.ServiceError  # the class the kit raises (a second load would make another one)

HERE = Path(__file__).resolve().parent
V = json.loads((HERE / "fixtures/contract/actions-vectors.json").read_text(encoding="utf-8"))
EXTRA = json.loads((HERE / "fixtures/contract/actions-extra-vectors.json").read_text(encoding="utf-8"))
INPUTS = json.loads((HERE / "fixtures/kit-actions-inputs.json").read_text(encoding="utf-8"))
KEY = fa.ACTIONS_EXTENSION_KEY
NOW = "2026-10-24T09:30:00Z"
RELAYED = {"id": "approve-reply", "title": "Approve the reply", "tool": "reviews.approve", "gate": "relayed"}
NONE = {"id": "retry-job", "title": "Retry", "tool": "jobs.retry", "gate": "none"}
HUMAN = {"id": "connect-store", "title": "Do it yourself", "tool": "accounts.connect", "gate": "human", "humanStep": "consent"}
DECISION = {"by": "operator", "via": "relayed-instruction", "action": "approve-reply",
            "instruction": "approve the reply to the review from Anna", "at": NOW}


def js(value):
    """JSON text with sorted keys: equal only when JavaScript's isDeepStrictEqual would be (true is not 1)."""
    return json.dumps(value, sort_keys=True)


def paths(findings):
    return [f["instancePath"] for f in findings]


def view_of(view):
    return {k: view[k] for k in ("declared", "valid", "actions") if k in view}


class Vectors(unittest.TestCase):
    def test_every_case_answers_as_the_contract_does(self):
        self.assertEqual(len(V["cases"]), 65)
        for case in V["cases"]:
            with self.subTest(case["name"]):
                self.assertEqual(js(fa.action_decision(case["input"])), js(case["expected"]))

    def test_every_declaration_is_found_where_the_contract_finds_it(self):
        self.assertEqual(len(V["declarations"]), 11)
        for case in V["declarations"]:
            with self.subTest(case["name"]):
                findings = fa.actions_extension_rules(case["input"])
                self.assertEqual(paths(findings), case["findings"])
                self.assertTrue(all(f["code"] == "FAC-SEM-142" and f["message"] for f in findings))

    def test_the_action_call_fixtures(self):
        self.assertEqual(len(V["actionCalls"]), 10)
        for case in V["actionCalls"]:
            with self.subTest(case["name"]):
                self.assertEqual(js(fa.action_decision(case["inputs"])), js(case["expected"]))
                value = dict(case["inputs"], answer=case["answer"])
                self.assertEqual(paths(fa.action_rules("action-call", value)), case["findings"])
                self.assertEqual(paths(fa.action_call_rules(value)), case["findings"])
        self.assertIsNone(fa.action_rules("service-well-known", {}))

    def test_the_well_known_fixtures(self):
        self.assertEqual(len(V["wellKnowns"]), 7)
        for case in V["wellKnowns"]:
            with self.subTest(case["name"]):
                self.assertEqual(js(view_of(fa.actions_view(case["document"]))), js(case["view"]))
                self.assertEqual(paths(fa.actions_extension_rules(case["document"])), case["findings"])

    def test_the_decision_and_extension_fixtures(self):
        self.assertEqual(len(V["fixtures"]), 14)
        for case in V["fixtures"]:
            with self.subTest(case["name"]):
                if case["schema"] == "decision.schema.json":
                    self.assertEqual(fa.decision_shape(case["document"]), case["valid"])
                elif case["schema"] == "service-actions-extension.schema.json":
                    view = fa.actions_view({"extensions": {KEY: case["document"]}})
                    self.assertTrue(view["declared"])
                    self.assertEqual(view["valid"], case["valid"])
                    self.assertEqual(bool(view.get("errors")), not case["valid"])
                else:
                    self.assertTrue(fa.actions_view(case["document"])["valid"])
                    self.assertEqual(fa.actions_extension_rules(case["document"]), [])

    def test_every_kit_input_answers_as_the_contract_does(self):
        self.assertEqual(len(EXTRA["decisions"]), len(INPUTS["decisions"]))
        self.assertEqual(len(EXTRA["documents"]), len(INPUTS["wellKnowns"]))
        self.assertEqual(len(EXTRA["shapes"]), len(INPUTS["decisionShapes"]))
        for case in EXTRA["decisions"]:
            with self.subTest(case["name"]):
                self.assertEqual(js(fa.action_decision(case["input"])), js(case["expected"]))
        for case in EXTRA["documents"]:
            with self.subTest(case["name"]):
                self.assertEqual(js(view_of(fa.actions_view(case["document"]))), js(case["view"]))
                self.assertEqual(paths(fa.actions_extension_rules(case["document"])), case["findings"])
        for case in EXTRA["shapes"]:
            with self.subTest(case["name"]):
                self.assertEqual(fa.decision_shape(case["document"]), case["valid"])


class Hostile(unittest.TestCase):
    def call(self, **extra):
        value = {"action": RELAYED, "tier": "T0", "caller": "agent:claude-code", "now": NOW, "decision": DECISION}
        value.update(extra)
        return fa.action_decision(value)

    def test_inputs_that_are_not_objects_are_the_services_fault(self):
        for value in (None, [], "x", 7, math.nan, True, {"action": None}):
            with self.subTest(value=repr(value)):
                self.assertEqual(fa.action_decision(value), {"fault": "action-invalid"})

    def test_nan_and_infinity(self):
        self.assertEqual(self.call(now=math.nan), {"fault": "now-unreadable"})
        self.assertEqual(self.call(decision=dict(DECISION, at=math.nan)), {"ok": False, "code": "decision-invalid"})
        self.assertEqual(self.call(decision=dict(DECISION, at=math.inf)), {"ok": False, "code": "decision-invalid"})
        self.assertEqual(self.call(tier=math.nan), {"fault": "digest-missing"})
        self.assertEqual(self.call(action=dict(RELAYED, title=math.nan)), {"fault": "action-invalid"})
        self.assertFalse(fa.decision_shape(dict(DECISION, instruction=math.nan)))

    def test_true_is_not_one(self):
        self.assertEqual(self.call(elicited=1, decision=None)["code"], "decision-invalid")
        self.assertEqual(self.call(elicited=True, decision=None)["recordAs"]["via"], "elicitation")
        self.assertEqual(self.call(tier="T2", approval={"ok": 1, "approver": "a"}, actionDigest="sha256:" + "0" * 64)["code"],
                         "approval-required")

    def test_huge_strings_answer_quickly(self):
        big = "a" * 5_000_000
        self.assertEqual(self.call(action=dict(RELAYED, id=big)), {"fault": "action-invalid"})
        self.assertEqual(self.call(action=dict(RELAYED, title=big)), {"fault": "action-invalid"})
        self.assertEqual(self.call(decision=dict(DECISION, instruction=big))["code"], "decision-invalid")
        self.assertEqual(self.call(decision=dict(DECISION, at=big))["code"], "decision-invalid")
        self.assertEqual(self.call(now=big), {"fault": "now-unreadable"})
        self.assertEqual(self.call(tier="T2", actionDigest="sha256:" + "a" * 5_000_000), {"fault": "digest-missing"})

    def test_patterns_match_the_whole_string(self):
        for member, value in (("id", "approve-reply\n"), ("tool", "reviews.approve\n"), ("id", "\napprove"),
                              ("tool", "reviews.approve\r"), ("gate", "relayed\n")):
            with self.subTest(member=member, value=value):
                self.assertEqual(self.call(action=dict(RELAYED, **{member: value})), {"fault": "action-invalid"})
        self.assertEqual(self.call(decision=dict(DECISION, action="approve-reply\n"))["code"], "decision-invalid")
        self.assertEqual(self.call(tier="T2", actionDigest="sha256:" + "a" * 64 + "\n"), {"fault": "digest-missing"})

    def test_lengths_count_code_points(self):
        self.assertTrue(fa.decision_shape(dict(DECISION, instruction="\U0001F600" * 500)))
        self.assertFalse(fa.decision_shape(dict(DECISION, instruction="\U0001F600" * 501)))
        self.assertEqual(self.call(action=dict(RELAYED, title="\U0001F600" * 80))["ok"], True)
        self.assertEqual(self.call(action=dict(RELAYED, title="\U0001F600" * 81)), {"fault": "action-invalid"})

    def test_prototype_member_names_are_ordinary_members(self):
        self.assertEqual(self.call(action=dict(RELAYED, __proto__={})), {"fault": "action-invalid"})
        self.assertEqual(self.call(decision=dict(DECISION, constructor="x"))["code"], "decision-invalid")
        self.assertEqual(fa.actions_view({"extensions": {"__proto__": {KEY: {"actions": [RELAYED]}}}}), {"declared": False})

    def test_at_is_read_strictly(self):
        """D5: the kit reads `at` as the contract's strictTime does. The schema's date-time (ajv-formats) admits a space
        for T and a leap second; the shape check here does not, and actionDecision answers decision-invalid for both
        either way (it reads `at` with strictTime after the schema), so the answers stay the reference's."""
        for at in ("2026-10-24 09:30:00Z", "2016-12-31T23:59:60Z"):
            with self.subTest(at=at):
                self.assertFalse(fa.decision_shape(dict(DECISION, at=at)))
                self.assertEqual(self.call(decision=dict(DECISION, at=at)), {"ok": False, "code": "decision-invalid"})

    def test_an_absent_decision_is_not_a_null_one(self):
        value = {"action": RELAYED, "tier": "T0", "caller": "agent:claude-code", "now": NOW}
        self.assertEqual(fa.action_decision(value), {"ok": False, "code": "operator-decision-required"})
        self.assertEqual(fa.action_decision(dict(value, decision=None)), {"ok": False, "code": "decision-invalid"})

    def test_the_readers_never_raise(self):
        junk = (None, [], "x", 7, math.nan, {"extensions": None}, {"extensions": {KEY: None}},
                {"extensions": {KEY: {"actions": [None, 1, "x", [], {"id": math.nan}]}}},
                {"surfaces": {"mcp": {"capabilities": [math.nan, None]}}, "extensions": {KEY: {"actions": [RELAYED]}}})
        for value in junk:
            with self.subTest(value=repr(value)[:60]):
                fa.actions_view(value)
                fa.actions_extension_rules(value)
                fa.action_call_rules(value if isinstance(value, dict) else {})
        for value in (None, [], "x", math.nan, {}, {"by": "operator"}):
            self.assertFalse(fa.decision_shape(value))

    def test_the_answer_is_a_fresh_object(self):
        answer = self.call()
        answer["recordAs"]["by"] = "someone"
        self.assertEqual(self.call()["recordAs"]["by"], "operator")


class Extension(unittest.TestCase):
    def test_a_valid_table_round_trips_through_the_reader(self):
        table = [NONE, RELAYED, HUMAN]
        entry = fa.actions_extension(table, capabilities=["jobs.retry", "reviews.approve", "accounts.connect"])
        self.assertEqual(list(entry), [KEY])
        self.assertEqual(entry[KEY], {"actions": table})
        view = fa.actions_view({"extensions": entry})
        self.assertEqual(view, {"declared": True, "valid": True, "actions": table})
        document = {"surfaces": {"mcp": {"capabilities": ["jobs.retry", "reviews.approve", "accounts.connect"]}}, "extensions": entry}
        self.assertEqual(fa.actions_extension_rules(document), [])
        self.assertEqual(fa.actions_extension(table), entry)  # no capability list: tools are not compared

    def test_the_builder_copies_its_input(self):
        table = [dict(RELAYED)]
        entry = fa.actions_extension(table)
        entry[KEY]["actions"][0]["title"] = "changed"
        self.assertEqual(table[0]["title"], "Approve the reply")

    def test_a_declaration_a_reader_would_report_is_refused(self):
        bad = {
            "a tool the MCP surface does not list": ([RELAYED], ["jobs.retry"]),
            "an empty table": ([], None),
            "an id declared twice": ([RELAYED, dict(NONE, id="approve-reply")], None),
            "a human action without its step": ([dict(HUMAN, humanStep=None)], None),
            "a human action that names no step": ([{k: v for k, v in HUMAN.items() if k != "humanStep"}], None),
            "a step on a relayed action": ([dict(RELAYED, humanStep="consent")], None),
            "an unknown gate": ([dict(RELAYED, gate="page")], None),
            "an action that is not an object": (["approve-reply"], None),
            "129 actions": ([dict(RELAYED, id="a%d" % i) for i in range(129)], None),
        }
        for name, (table, capabilities) in bad.items():
            with self.subTest(name), self.assertRaises(ServiceError):
                fa.actions_extension(table, capabilities=capabilities)
        for table in (None, "x", {"actions": []}, RELAYED):
            with self.subTest(table=repr(table)[:40]), self.assertRaises(ServiceError):
                fa.actions_extension(table)
        with self.assertRaises(ServiceError):
            fa.actions_extension([RELAYED], capabilities="reviews.approve")


if __name__ == "__main__":
    unittest.main()
