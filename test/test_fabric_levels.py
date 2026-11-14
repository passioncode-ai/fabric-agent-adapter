"""Authority levels (DEC-0162) and a place's standing mandate (DEC-0166) in the Python kit, held to the contract's own
vectors at the pin (test/fixtures/contract/make_levels_vectors.mjs): the membership verifier, a level decision and a
level mandate through action_decision, a standing mandate through action_decision, and the document rules (FAC-SEM-144,
FAC-SEM-170, FAC-SEM-173). The twin of fabric-levels.test.mjs."""
import copy
import json
import unittest
from pathlib import Path

from test_fabric_service import load

fl = load("fabric_levels")
fa = load("fabric_actions")
fm = load("fabric_mandate")
ft = load("fabric_time")
HERE = Path(__file__).resolve().parent
LEVELS = json.loads((HERE / "fixtures/contract/levels-vectors.json").read_text(encoding="utf-8"))
STANDING = json.loads((HERE / "fixtures/contract/standing-vectors.json").read_text(encoding="utf-8"))
PIN = json.loads((HERE.parent / "fabric-contract.lock.json").read_text(encoding="utf-8"))["commit"]


def resolved(case):
    trust = dict(case["trust"], now=ft.parse_rfc3339_ms(case["trust"]["now"]))
    if trust.get("keySet") == "keySet":
        trust["keySet"] = LEVELS["keySet"]
    membership = LEVELS["memberships"][case["membership"]] if isinstance(case["membership"], str) else case["membership"]
    return membership, trust


class LevelVectors(unittest.TestCase):
    def test_the_vectors_are_the_pins(self):
        self.assertEqual((LEVELS["commit"], STANDING["commit"]), (PIN, PIN))
        self.assertEqual((len(LEVELS["verify"]), len(LEVELS["actions"]), len(LEVELS["mandates"])), (6, 64, 23))
        self.assertEqual((len(STANDING["actions"]), len(STANDING["documents"])), (49, 11))

    def test_the_membership_verifier(self):
        for case in LEVELS["verify"]:
            with self.subTest(case["name"]):
                self.assertEqual(fl.verify_org_membership(*resolved(case)), case["expected"])

    def test_every_digest_is_the_attestations(self):
        trust = {"now": ft.parse_rfc3339_ms("2026-10-25T11:30:00Z"), "org": "org:org-a", "audience": "reviews-service-a1",
                 "keySet": LEVELS["keySet"], "levels": True}
        for name, membership in LEVELS["memberships"].items():
            with self.subTest(name):
                data = fl.org_membership_signing_input(membership)
                self.assertEqual("sha256:" + load("fabric_crypto").sha256(data).hex(), LEVELS["digests"][name])
        self.assertTrue(fl.verify_org_membership(LEVELS["memberships"]["owner"], trust)["ok"])

    def test_a_level_decision_and_a_level_mandate(self):
        for group in ("actions", "mandates"):
            for case in LEVELS[group]:
                with self.subTest(group=group, case=case["name"]):
                    self.assertEqual(fa.action_decision(case["input"]), case["expected"])

    def test_a_standing_mandate(self):
        for case in STANDING["actions"]:
            with self.subTest(case["name"]):
                self.assertEqual(fa.action_decision(case["input"]), case["expected"])

    def test_the_document_rules(self):
        for case in STANDING["documents"]:
            with self.subTest(case["name"]):
                got = ["%s %s" % (f["code"], f["instancePath"]) for f in fm.mandate_rules("mandate", case["mandate"])]
                self.assertEqual(got, case["findings"])
                self.assertTrue(all(f["message"] for f in fm.mandate_rules("mandate", case["mandate"])))


class LevelEdges(unittest.TestCase):
    def owner_case(self):
        return copy.deepcopy(next(c for c in LEVELS["actions"] if c["expected"].get("ok") is True))

    def test_a_tampered_attestation_is_a_bad_signature(self):
        case = self.owner_case()
        case["input"]["decision"]["membership"]["revision"] += 1
        answer = fa.action_decision(case["input"])
        self.assertEqual((answer["code"], answer["data"]["detail"]), ("decision-invalid", "level-membership: bad-signature"))

    def test_a_reader_without_levels_refuses_a_v2_attestation(self):
        membership, trust = resolved(next(c for c in LEVELS["verify"] if c["membership"] == "architect"))
        self.assertEqual(fl.verify_org_membership(membership, dict(trust, levels=False)), {"ok": False, "problem": "malformed"})

    def test_malformed_level_contexts_are_the_services_fault(self):
        case = self.owner_case()
        self.assertEqual(fa.action_decision(dict(case["input"], levels=[{"org": "org:org-a"}])), {"fault": "levels-invalid"})
        self.assertEqual(fa.action_decision(dict(case["input"], actionLevel="root")), {"fault": "action-level-invalid"})

    def test_never_raises_on_odd_inputs(self):
        for value in (None, 1, "x", [], {"type": "org-membership/2"}):
            self.assertFalse(fl.verify_org_membership(value, {"now": 0, "org": "org:a", "audience": "a", "keySet": {}})["ok"])
        self.assertEqual(fl.level_rules("other", {}), None)
        self.assertEqual(fl.level_short_of("member", "operator", True), "level-insufficient: operator")


if __name__ == "__main__":
    unittest.main()
