"""Hostile inputs the estate and ceremony twins must answer alike (FAA-78, finding 44; decision D3). The cases live in
test/fixtures/kit-hostile-inputs-estate.json; kit-hostile-estate.test.mjs runs the same cases through the Node twins."""

import copy
import datetime
import importlib
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"))
fe = importlib.import_module("fabric_estate")
fc = importlib.import_module("fabric_ceremonies")
ft = importlib.import_module("fabric_time")

CASES = json.loads((HERE / "fixtures/kit-hostile-inputs-estate.json").read_text(encoding="utf-8"))
CONTRACT = HERE / "fixtures/contract"
HUB = json.loads((CONTRACT / "hub-key-vectors.json").read_text(encoding="utf-8"))["cases"][0]
ESTATE = json.loads((CONTRACT / "estate-vectors.json").read_text(encoding="utf-8"))
CEREMONY = json.loads((CONTRACT / "ceremony-vectors.json").read_text(encoding="utf-8"))


class HubKeyAppliedTests(unittest.TestCase):
    def test_every_applied_case(self):
        for case in CASES["hubKey"]:
            with self.subTest(case["name"]):
                if "applied" in case:
                    got = fe.hub_key_certified(HUB["record"], HUB["kid"], HUB["x"], HUB["at"], case["applied"])
                else:
                    got = fe.hub_key_certified(HUB["record"], HUB["kid"], HUB["x"], HUB["at"])
                self.assertEqual(got, case["expected"])

    def test_the_absent_value_is_the_core_sentinel(self):
        """Callers that mean "not given" pass fabric_jsvalue.MISSING, the one object fabric_estate._MISSING names."""
        self.assertIs(fe._MISSING, importlib.import_module("fabric_jsvalue").MISSING)
        self.assertEqual(fe.hub_key_certified(HUB["record"], HUB["kid"], HUB["x"], HUB["at"], fe._MISSING), HUB["expected"])


ORGS = next(r for r in ESTATE["rules"] if r.get("name") == "positive/estate-record-organizations")["value"]


def _hub_machine(record):
    return next(m for m in record["machines"] if "hubKey" in m)


class ContextHubKeyShapeTests(unittest.TestCase):
    """DEC-0128: hostile `contextHubKeys` and `organizations` answer as the contract does (FAC-SEM-073, 076, 134, 147)."""

    def findings(self, value):
        return [[f["code"], f["instancePath"]] for f in fe.estate_record_rules("estate-record", value) if f["code"] != "FAC-SEM-072"]

    def test_every_context_hub_keys_case(self):
        for case in CASES["contextHubKeys"]:
            with self.subTest(case["name"]):
                value = copy.deepcopy(ORGS)
                _hub_machine(value)["contextHubKeys"] = copy.deepcopy(case["contextHubKeys"])
                self.assertEqual(self.findings(value), case["expected"])

    def test_every_organizations_case(self):
        for case in CASES["organizations"]:
            with self.subTest(case["name"]):
                value = copy.deepcopy(ORGS)
                value["organizations"] = copy.deepcopy(case["organizations"])
                if "estate" in case:
                    value["estate"] = case["estate"]
                self.assertEqual(self.findings(value), case["expected"])

    def test_every_hostile_context_of_a_hub_key(self):
        key = _hub_machine(ORGS)["contextHubKeys"][0]["key"]
        for case in CASES["hubKeyContext"]:
            with self.subTest(case["name"]):
                got = fe.hub_key_certified(ORGS, key["kid"], key["x"], 1792454400, context=case["context"])
                self.assertEqual(got, case["expected"])


class DeviceKeyPathTests(unittest.TestCase):
    def test_every_device_key_case(self):
        base = next(r for r in ESTATE["rules"] if r.get("name") == "estate-contexts-ok.json")
        for case in CASES["deviceKeys"]:
            with self.subTest(case["name"]):
                value = copy.deepcopy(base["value"])
                keys = value["machines"][0]["deviceKeys"]
                keys[1]["kid"] = case["kidFromSecond"]
                value["machines"][0]["deviceKeys"] = case["prefix"] + keys
                paths = [f["instancePath"] for f in fe.estate_record_rules(base["kind"], value)
                         if f["instancePath"].startswith("/machines/0/deviceKeys/") and f["instancePath"].endswith("/kid")]
                self.assertEqual(paths, case["paths"])


class PlacementTrustTests(unittest.TestCase):
    def test_a_record_that_is_no_object_places_nothing(self):
        for case in CASES["placementTrust"]:
            with self.subTest(case["name"]):
                self.assertIsNone(fe.placement_trust(case["record"], "m-4c1e", "urn:fabric:agent:example:inbox-digest"))


class EnrollTokenClockTests(unittest.TestCase):
    def test_epoch_seconds_and_a_datetime_answer_alike(self):
        for case in CEREMONY["verify"]:
            with self.subTest(case["name"]):
                ms = ft.parse_rfc3339_ms(case["at"])
                record = case.get("record", CEREMONY["record"])
                when = None if ms != ms else datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc)
                by_date = fc.verify_enroll_token(case["token"], record=record, genesis=CEREMONY["genesis"], at=when)
                by_seconds = fc.verify_enroll_token(case["token"], record=record, genesis=CEREMONY["genesis"], at=ms / 1000)
                self.assertEqual(by_seconds, by_date)
                self.assertEqual(by_seconds, case["answer"])


if __name__ == "__main__":
    unittest.main()
