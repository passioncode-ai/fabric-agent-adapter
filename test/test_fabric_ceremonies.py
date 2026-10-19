"""The estate ceremonies' headless join (contract DEC-0084; FAA-54) in the Python kit: enroll-token/1 verification, the
enroll-join/1 input and FAC-SEM-113, held to the contract's cases as test/fixtures/contract/ceremony-vectors.json
vendors them."""

import importlib
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
sys.path.insert(0, str(SCRIPTS))
fc = importlib.import_module("fabric_ceremonies")
fe = importlib.import_module("fabric_estate")

V = json.loads((Path(__file__).resolve().parent / "fixtures/contract/ceremony-vectors.json").read_text())


def clock(text):
    """The case's clock as epoch seconds, or None where JavaScript's new Date(text) is invalid."""
    millis = fe.estate_time(text)
    return millis / 1000.0 if millis == millis else None


class CeremonyTests(unittest.TestCase):
    def test_every_verify_case(self):
        for c in V["verify"]:
            with self.subTest(c["name"]):
                answer = fc.verify_enroll_token(c["token"], record=c.get("record", V["record"]), genesis=V["genesis"], at=clock(c["at"]))
                self.assertEqual(answer, c["answer"])

    def test_every_join_input(self):
        for c in V["verify"]:
            with self.subTest(c["name"]):
                self.assertEqual(fc.enroll_join_input(c["token"]), c["joinInput"])

    def test_every_rule_case(self):
        for c in V["rules"]:
            with self.subTest(c["name"]):
                self.assertEqual(fc.enroll_token_rules(c["kind"], c["value"]), c["expected"])
        self.assertIsNone(fc.enroll_token_rules("estate-record", {}))

    def test_hostile_input_never_raises(self):
        for value in (None, 0, "x", [], {}, {"schema": "enroll-token/1", "statement": [], "signature": {}}):
            self.assertEqual(fc.verify_enroll_token(value, record=V["record"], genesis=V["genesis"], at=0)["ok"], False)
            self.assertIsNone(fc.enroll_join_input(value))
            fc.enroll_token_rules("enroll-token", value)


if __name__ == "__main__":
    unittest.main()
