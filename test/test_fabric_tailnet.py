"""FAA-297: fabric_tailnet.py, identity behind `tailscale serve`, on the vectors its Node twin answers too."""
import importlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"))
ft = importlib.import_module("fabric_tailnet")

FIXTURE = json.loads((Path(__file__).parent / "fixtures/tailnet/vectors.json").read_text(encoding="utf-8"))


class Vectors(unittest.TestCase):
    def setUp(self):
        self.perimeter = ft.load_perimeter(FIXTURE["perimeter"])
        self.keys = ft.load_keys(FIXTURE["keys"])

    def test_every_vector(self):
        for v in FIXTURE["vectors"]:
            with self.subTest(v["name"]):
                got = ft.authorize(listener=v["listener"], peer=v["peer"], headers=[tuple(h) for h in v["headers"]],
                                   perimeter=self.perimeter, surface=v["surface"], target=v["target"], keys=self.keys)
                expect = v["expect"]
                self.assertEqual(got["status"], expect["status"])
                self.assertEqual(got["code"], expect["code"])
                self.assertEqual(got["login"], expect["login"])
                self.assertEqual(got["groups"], expect["groups"])
                self.assertEqual(got.get("key"), expect.get("key"))
                self.assertEqual(got["allowed"], expect["status"] == 200)

    def test_every_refusal_code_is_exercised(self):
        self.assertEqual({v["expect"]["code"] for v in FIXTURE["vectors"]} - {"ok"}, set(ft.REFUSALS))

    def test_bad_perimeters(self):
        for case in FIXTURE["badPerimeters"]:
            with self.subTest(case["name"]):
                with self.assertRaises(ft.PerimeterError) as caught:
                    ft.load_perimeter(case["doc"])
                self.assertEqual(caught.exception.code, case["code"])

    def test_bad_keys(self):
        for case in FIXTURE["badKeys"]:
            with self.subTest(case["name"]):
                with self.assertRaises(ft.PerimeterError) as caught:
                    ft.load_keys(case["keys"])
                self.assertEqual(caught.exception.code, case["code"])

    def test_hash_key(self):
        self.assertEqual(ft.hash_key(FIXTURE["hashKey"]["in"]), FIXTURE["hashKey"]["out"])
        with self.assertRaises(ValueError):
            ft.hash_key("")


class Edges(unittest.TestCase):
    def setUp(self):
        self.perimeter = ft.load_perimeter(FIXTURE["perimeter"])

    def test_headers_as_a_mapping(self):
        got = ft.authorize(listener="serve", peer="127.0.0.1", headers={"Tailscale-User-Login": "cy@example.com"},
                           perimeter=self.perimeter, surface="dashboard", target="vitals")
        self.assertEqual(got["code"], "ok")

    def test_fabric_listener_without_serve_headers_is_not_this_modules_call(self):
        with self.assertRaises(ValueError):
            ft.authorize(listener="fabric", peer="127.0.0.1", headers={}, perimeter=self.perimeter,
                         surface="dashboard", target="vitals")

    def test_unknown_surface(self):
        with self.assertRaises(ValueError):
            ft.authorize(listener="serve", peer="127.0.0.1", headers={}, perimeter=self.perimeter, surface="a2a",
                         target="x")

    def test_no_answer_carries_a_key(self):
        keys = ft.load_keys(FIXTURE["keys"])
        got = ft.authorize(listener="serve", peer="127.0.0.1",
                           headers=[("tailscale-user-login", "ana@example.com"), ("authorization", "Bearer example-key-ana")],
                           perimeter=self.perimeter, surface="mcp", target="cve.scan", keys=keys)
        self.assertNotIn("example-key-ana", json.dumps(got))
        self.assertNotIn("sha256", json.dumps(got))


if __name__ == "__main__":
    unittest.main()
