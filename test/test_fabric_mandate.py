"""fabric_mandate.py: the operator's mandate, mandate/1 (DEC-0125, FAC-SEM-144). The reader answers every case of the
contract's fixtures/vectors/mandate.json and its mandate.schema.json fixtures (vendored as
test/fixtures/contract/mandate-vectors.json, each answer re-computed by the contract's functions), and the kit's own
inputs answered by the same functions (mandate-extra-vectors.json, from test/fixtures/kit-mandate-inputs.json); the
Node twin runs the same files in fabric-mandate.test.mjs."""
import json
import unittest
from pathlib import Path

from test_fabric_service import load

fm = load("fabric_mandate")
fa = load("fabric_actions")
fd = load("fabric_delegation")
ServiceError = fm.ServiceError

HERE = Path(__file__).resolve().parent
V = json.loads((HERE / "fixtures/contract/mandate-vectors.json").read_text(encoding="utf-8"))
EXTRA = json.loads((HERE / "fixtures/contract/mandate-extra-vectors.json").read_text(encoding="utf-8"))
POSITIVE = next(f["document"] for f in V["fixtures"] if f["valid"])
SCOPE = {"capabilities": ["research.run"], "effects": ["charge", "draft"], "projects": ["example-site"]}
#: Documents whose `at` the contract's ajv-formats date-time admits and the kit's shape refuses, as fabric_actions'
#: decision_shape does (0.50.0 brief D5, this brief D26): both readings answer mandate-malformed (FAC-SEM-144 reads the
#: time strictly next), so only mandate_shape's answer differs.
STRICT_TIME_APART = {"at with an offset without a colon", "at with a space for T"}


def js(value):
    """JSON text with sorted keys: equal only when JavaScript's isDeepStrictEqual would be (true is not 1)."""
    return json.dumps(value, sort_keys=True)


class Vectors(unittest.TestCase):
    def test_every_contract_case(self):
        self.assertEqual(len(V["cases"]), 37)
        for case in V["cases"]:
            with self.subTest(case["name"]):
                self.assertEqual(js(fm.mandate_covers(case["input"])), js(case["expected"]))

    def test_every_catalogue_fixture(self):
        self.assertEqual(len(V["fixtures"]), 3)
        for fixture in V["fixtures"]:
            with self.subTest(fixture["name"]):
                self.assertIs(fm.mandate_shape(fixture["document"]), fixture["valid"])
                self.assertEqual(fm.mandate_problem(fixture["document"]), fixture["problem"])
                self.assertEqual(fm.mandate_rules("mandate", fixture["document"]), fixture["findings"])

    def test_the_lifetime_and_the_codes(self):
        self.assertEqual(fm.MANDATE_LIFETIME_SECONDS, V["lifetimeSeconds"])
        self.assertEqual((fm.OUTSIDE_MANDATE, fm.MANDATE_INVALID), ("operator-decision-required", "decision-invalid"))
        self.assertIsNone(fm.mandate_rules("decision", POSITIVE))


class KitInputs(unittest.TestCase):
    def test_every_cover(self):
        self.assertEqual(len(EXTRA["covers"]), 106)
        for case in EXTRA["covers"]:
            with self.subTest(case["name"]):
                self.assertEqual(js(fm.mandate_covers(case["input"])), js(case["expected"]))

    def test_every_document(self):
        self.assertEqual(STRICT_TIME_APART, {c["name"] for c in EXTRA["documents"] if fm.mandate_shape(c["mandate"]) != c["valid"]})
        for case in EXTRA["documents"]:
            with self.subTest(case["name"]):
                self.assertIs(fm.mandate_shape(case["mandate"]), case["valid"] and case["name"] not in STRICT_TIME_APART)
                self.assertEqual(fm.mandate_problem(case["mandate"]), case["problem"])
                self.assertEqual(fm.mandate_rules("mandate", case["mandate"]), case["findings"])

    def test_every_scope_pair(self):
        for case in EXTRA["scopes"]:
            with self.subTest(case["name"]):
                self.assertIs(fm.scope_within(case["child"], case["parent"]), case["within"])

    def test_the_scope_in_force(self):
        self.assertGreater(len(EXTRA["effective"]), 50)
        for case in EXTRA["effective"]:
            with self.subTest(case["name"]):
                self.assertEqual(js(fm.effective_scope(case["mandate"])), js(case["scope"]))

    def test_every_hand_over(self):
        for case in EXTRA["handOns"]:
            with self.subTest(case["name"]):
                call = lambda: fm.hand_on(case["mandate"], case["callee"], case["at"], case.get("narrower"))  # noqa: E731
                if "throws" in case:
                    with self.assertRaises(ServiceError) as caught:
                        call()
                    self.assertTrue(str(caught.exception).endswith(case["throws"]), str(caught.exception))
                else:
                    self.assertEqual(js(call()), js(case["expected"]))

    def test_every_action_decision_with_a_mandate(self):
        self.assertEqual(len(EXTRA["decisions"]), 22)
        for case in EXTRA["decisions"]:
            with self.subTest(case["name"]):
                self.assertEqual(js(fa.action_decision(case["input"])), js(case["expected"]))


class Hostile(unittest.TestCase):
    def test_never_raises_on_what_it_reads(self):
        odd = [None, [], "x", 7, {"call": None}, {"call": []}, {"call": "x"},
               {"mandate": POSITIVE, "tier": "T0", "now": "2026-10-26T12:00:00Z", "self": "example-researcher"},
               {"mandate": POSITIVE, "tier": "T0", "now": "2026-10-26T12:00:00Z", "self": "example-researcher",
                "call": {"capability": {"x": 1}, "effect": [1], "action": {}, "project": [], "spendUsd": {"a": 1}}}]
        for value in odd:
            with self.subTest(value=value):
                answer = fm.mandate_covers(value)
                self.assertIsInstance(answer, dict)
        for value in [None, [], "x", {"kind": "mandate/1", "scope": {"effects": [{}]}}, {"chain": [{"agent": []}]}]:
            with self.subTest(document=value):
                self.assertEqual(fm.mandate_problem(value), "mandate-malformed")

    def test_a_missing_call_is_a_call_that_names_nothing(self):
        # The reference reads call.capability of an absent call and throws; the kit reads it as an empty call.
        base = {"mandate": POSITIVE, "tier": "T0", "now": "2026-10-26T12:00:00Z", "self": "example-researcher"}
        self.assertEqual(fm.mandate_covers(base), {"ok": False, "code": "operator-decision-required",
                                                   "data": {"detail": "outside-mandate: capability"}})

    def test_the_input_is_never_changed(self):
        before = js(POSITIVE)
        fm.hand_on(POSITIVE, "example-writer", "2026-10-26T10:06:00Z", {"capabilities": ["research.run"], "effects": ["draft"], "projects": ["example-site"]})
        fm.effective_scope(POSITIVE)
        self.assertEqual(js(POSITIVE), before)


class Building(unittest.TestCase):
    def test_operator_mandate_states_the_operators_words(self):
        mandate = fm.operator_mandate("FAA-131", "adopt the mandate in both kits", SCOPE, "example-developer",
                                      at="2026-10-26T10:00:00Z")
        self.assertIsNone(fm.mandate_problem(mandate))
        self.assertEqual(mandate["chain"], [{"agent": "example-developer", "at": "2026-10-26T10:00:00Z"}])
        self.assertEqual(mandate["expiresAt"], "2026-10-27T10:00:00.000Z")  # a day unless told otherwise
        self.assertEqual(mandate["by"], "operator")

    def test_operator_mandate_by_the_clock(self):
        mandate = fm.operator_mandate("t", "do it", SCOPE, "example-developer", clock=lambda: 1793000000.0)
        self.assertEqual(mandate["at"], "2026-10-26T07:33:20.000Z")
        self.assertIsNone(fm.mandate_problem(mandate))

    def test_operator_mandate_refuses_what_the_schema_refuses(self):
        for kwargs in ({"instruction": ""}, {"instruction": "x" * 501}, {"lead": "Example"}, {"scope": {"effects": []}},
                       {"expires_at": "2026-11-03T10:00:01Z"}, {"at": "2026-10-26 10:00:00Z"}):
            args = {"task": "t", "instruction": "do it", "scope": SCOPE, "lead": "example-developer", "at": "2026-10-26T10:00:00Z"}
            args.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(ServiceError):
                fm.operator_mandate(args.pop("task"), args.pop("instruction"), args.pop("scope"), args.pop("lead"), **args)

    def test_a_lead_hands_on_narrowed_and_the_callee_takes_it(self):
        mandate = fm.operator_mandate("t", "run the research", SCOPE, "example-developer", at="2026-10-26T10:00:00Z")
        handed = fm.hand_on(mandate, "example-researcher", "2026-10-26T10:05:00Z",
                            {"capabilities": ["research.run"], "effects": ["charge"], "projects": ["example-site"], "perCallMaxUsd": 20})
        answer = fm.mandate_covers({"mandate": handed, "tier": "T0", "now": "2026-10-26T12:00:00Z", "self": "example-researcher",
                                    "callerAgent": "example-developer",
                                    "call": {"capability": "research.run", "effect": "charge", "spendUsd": 21}})
        self.assertEqual(answer["data"], {"detail": "outside-mandate: spend", "estimateUsd": 21, "perCallMaxUsd": 20})

    def test_effect_closure_is_defined_once(self):
        self.assertEqual(fm.effect_closure(["charge"]), {"charge", "none", "draft"})
        self.assertEqual(fm.effect_closure(["none"]), {"none"})
        self.assertEqual(fm.effect_closure([]), set())
        self.assertIs(fd.effect_closure.__module__, fm.effect_closure.__module__)


if __name__ == "__main__":
    unittest.main()
