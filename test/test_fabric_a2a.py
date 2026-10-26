"""fabric_a2a.py: the reading side of DEC-0122 (decision D4 of the 0.51.0 brief). `surfaces.a2a` is read as the
contract's schema reads it, on the three catalogue fixtures (vendored with their schema errors in
test/fixtures/contract/a2a-vectors.json) and the kit's own hostile inputs (test/fixtures/kit-a2a-cases.json, shared with
fabric-a2a.test.mjs); `build_well_known` writes the member and never publishes an invalid one; `agent_card_findings`
reports what a public Agent Card must not carry (D5, D6)."""
import json
import unittest
from pathlib import Path

from test_fabric_service import fs, load

fa2 = load("fabric_a2a")
ServiceError = fs.ServiceError  # the class build_well_known raises
HERE = Path(__file__).resolve().parent
VECTORS = json.loads((HERE / "fixtures/contract/a2a-vectors.json").read_text(encoding="utf-8"))
SAMPLE_KEY = "sk-" + "Ab1" * 8  # a provider-key shape, built here so no file holds one
CASES = json.loads((HERE / "fixtures/kit-a2a-cases.json").read_text(encoding="utf-8").replace("@SK@", SAMPLE_KEY))
BASE = dict(service_id="example-agent", instance="default", name="Example", version="1.0.0", build={"commit": "0" * 40},
            started_at="2026-10-26T00:00:00Z", status="ready", degraded=[])


def keyed(findings):
    return [{"instancePath": f["instancePath"], "keyword": f["keyword"]} for f in findings]


class SurfaceMember(unittest.TestCase):
    def test_the_three_catalogue_fixtures_read_as_the_contract_reads_them(self):
        self.assertEqual([f["name"] for f in VECTORS["fixtures"]],
                         ["service-well-known-a2a", "service-well-known-a2a-old-version", "service-well-known-a2a-url"])
        for fixture in VECTORS["fixtures"]:
            with self.subTest(fixture["name"]):
                surface = fixture["document"]["surfaces"]["a2a"]
                self.assertEqual(keyed(fa2.a2a_surface_findings(surface)), fixture["errors"])
                self.assertEqual(fa2.a2a_surface_problems(surface) == [], fixture["valid"])
                view = fa2.a2a_view(fixture["document"])
                self.assertTrue(view["declared"])
                self.assertEqual(view["valid"], fixture["valid"])

    def test_the_kits_own_inputs(self):
        self.assertEqual(len(CASES["surfaces"]), 26)
        for case in CASES["surfaces"]:
            with self.subTest(case["name"]):
                findings = fa2.a2a_surface_findings(case["value"])
                self.assertEqual(keyed(findings), case["findings"])
                self.assertTrue(all(isinstance(f["message"], str) and f["message"] for f in findings))

    def test_a_surface_is_built_and_checked(self):
        self.assertEqual(fa2.a2a_surface(), {"path": "/.well-known/agent-card.json", "protocolVersion": "1.0"})
        self.assertEqual(fa2.a2a_surface("/a2a/card"), {"path": "/a2a/card", "protocolVersion": "1.0"})
        for bad in ("a2a/card", "//x", "/a b", "/x\n", 7):
            with self.subTest(bad=bad), self.assertRaises(ServiceError):
                fa2.a2a_surface(bad)

    def test_the_view_never_raises_and_tells_absence_from_invalidity(self):
        for wk in (None, [], "x", {}, {"surfaces": None}, {"surfaces": []}, {"surfaces": {"events": {"path": "/e"}}}):
            with self.subTest(wk=wk):
                self.assertEqual(fa2.a2a_view(wk)["declared"], False)
        view = fa2.a2a_view({"surfaces": {"a2a": None}})
        self.assertEqual((view["declared"], view["valid"], view["path"]), (True, False, None))
        view = fa2.a2a_view({"surfaces": {"a2a": {"path": "/c", "protocolVersion": "1.0"}}})
        self.assertEqual((view["declared"], view["valid"], view["path"], view["findings"]), (True, True, "/c", []))


class WellKnownDocument(unittest.TestCase):
    def test_build_well_known_writes_the_member(self):
        surfaces = {"events": {"path": "/fabric/v1/events"}}
        doc = fs.build_well_known(surfaces=surfaces, a2a=fa2.a2a_surface(), **BASE)
        self.assertEqual(doc["surfaces"]["a2a"], {"path": "/.well-known/agent-card.json", "protocolVersion": "1.0"})
        self.assertNotIn("a2a", surfaces, "the caller's surfaces are not changed")
        self.assertTrue(fa2.a2a_view(doc)["valid"])
        given = fs.build_well_known(surfaces={"events": {"path": "/e"}, "a2a": {"path": "/c", "protocolVersion": "1.0"}}, **BASE)
        self.assertEqual(given["surfaces"]["a2a"]["path"], "/c")
        self.assertNotIn("a2a", fs.build_well_known(surfaces={"events": {"path": "/e"}}, **BASE)["surfaces"])

    def test_build_well_known_refuses_an_invalid_member_either_way(self):
        for fixture in VECTORS["fixtures"][1:]:
            surface = fixture["document"]["surfaces"]["a2a"]
            with self.subTest(fixture["name"], via="surfaces"), self.assertRaises(ServiceError) as caught:
                fs.build_well_known(surfaces={"events": {"path": "/e"}, "a2a": surface}, **BASE)
            self.assertIn("surfaces.a2a", str(caught.exception))
            with self.subTest(fixture["name"], via="a2a"), self.assertRaises(ServiceError):
                fs.build_well_known(surfaces={"events": {"path": "/e"}}, a2a=surface, **BASE)
        with self.assertRaises(ServiceError) as caught:
            fs.build_well_known(surfaces={"events": {"path": "/e"}, "a2a": fa2.a2a_surface()}, a2a=fa2.a2a_surface(), **BASE)
        self.assertIn("not both", str(caught.exception))


class AgentCard(unittest.TestCase):
    def test_the_kits_own_cards(self):
        self.assertEqual(len(CASES["cards"]), 25)
        for case in CASES["cards"]:
            o = case["options"]
            with self.subTest(case["name"]):
                findings = fa2.agent_card_findings(case["card"], origin=o["origin"], remote=o["remote"],
                                                   descriptor_header=o["descriptorHeader"])
                self.assertEqual([{"code": f["code"], "instancePath": f["instancePath"]} for f in findings], case["findings"])
                for finding in findings:
                    self.assertNotIn(SAMPLE_KEY, finding["message"], "a finding names the place, never the value")

    def test_without_an_origin_the_interfaces_place_is_not_judged(self):
        card = {"supportedInterfaces": [{"url": "http://127.0.0.1:1/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}]}
        self.assertEqual(fa2.agent_card_findings(card), [])
        self.assertEqual([f["code"] for f in fa2.agent_card_findings(card, remote=True)], ["interface-scheme"])

    def test_a_deep_card_is_walked_without_recursion(self):
        card = {"supportedInterfaces": [{"url": "http://127.0.0.1:1/", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}]}
        node = card
        for _ in range(5000):
            node["x"] = {}
            node = node["x"]
        node["y"] = SAMPLE_KEY
        self.assertEqual([f["code"] for f in fa2.agent_card_findings(card)], ["secret"])


if __name__ == "__main__":
    unittest.main()
