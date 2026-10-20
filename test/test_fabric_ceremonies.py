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

    def test_every_redeem_case(self):
        """FAA-57: the hub's single use of a token, the ledger as a dict from nonce to entry."""
        for c in V["redeem"]:
            with self.subTest(c["name"]):
                self.assertEqual(fc.redeem_enroll_token(c["token"], c["machineKey"], c["proof"], dict(c["ledger"])), c["answer"])
        self.assertEqual(fc.redeem_enroll_token(V["verify"][0]["token"], {}, "", []), {"ok": False, "problem": "malformed"})

    def test_every_pairing_case(self):
        """FAA-57: the nearby pairing, every group of the contract's pairing.json."""
        P = V["pairing"]
        runs = {
            "commits": lambda c: fc.pairing_commit(c["side"]),
            "reveals": lambda c: fc.check_reveal(c["commit"], c["reveal"], c.get("expected")),
            "codes": lambda c: fc.comparison_code(c["new"], c["trusted"]),
            "checkedCodes": lambda c: fc.checked_comparison_code(c["newCommit"], c["new"], c["trustedCommit"], c["trusted"]),
            "fingerprints": lambda c: fc.estate_fingerprint(c["digest"]),
            "rendezvous": lambda c: fc.rendezvous_verdict(c["openedAt"], c["messages"], clock(c["at"])),
            "join": lambda c: fc.join_listed(c["record"], c["new"], c["trusted"], c["genesis"]),
            "ownKeys": lambda c: fc.own_keys_decision(c["record"], c["machine"], c["held"]),
        }
        for group, run in runs.items():
            self.assertGreater(len(P[group]), 0, group)
            for c in P[group]:
                with self.subTest(group=group, name=c["name"]):
                    self.assertEqual(run(c), c["answer"])

    def test_hostile_input_never_raises(self):
        for value in (None, 0, "x", [], {}, {"schema": "enroll-token/1", "statement": [], "signature": {}}):
            self.assertEqual(fc.verify_enroll_token(value, record=V["record"], genesis=V["genesis"], at=0)["ok"], False)
            self.assertIsNone(fc.enroll_join_input(value))
            fc.enroll_token_rules("enroll-token", value)
            for function in (fc.pairing_commit, fc.estate_fingerprint, fc.machine_of_keys):
                function(value)
            fc.check_reveal(value, value)
            fc.comparison_code(value, value)
            fc.rendezvous_verdict(value, value, value)
            fc.join_listed(value, value, value, value)
            fc.own_keys_decision(value, value, value)
            fc.redeem_enroll_token(value, value, value, {})


if __name__ == "__main__":
    unittest.main()
