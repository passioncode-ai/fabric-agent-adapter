"""A service's pages as Fabric Dashboards' open_link (contract DEC-0123, PL-1 to PL-4, FAC-SEM-143; FAA-132) in the
Python kit, held to the contract's own answers: test/fixtures/contract/page-link-vectors.json (the contract's vectors)
and page-link-extra-vectors.json (the kit's WHATWG URL inputs, decision D11 of the 0.51.0 brief, answered by the
reference). The Node twin is test/fabric-page-links.test.mjs."""

import importlib
import json
import re
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
sys.path.insert(0, str(SCRIPTS))
pl = importlib.import_module("fabric_page_links")

FIXTURES = Path(__file__).resolve().parent / "fixtures/contract"
V = json.loads((FIXTURES / "page-link-vectors.json").read_text(encoding="utf-8"))
X = json.loads((FIXTURES / "page-link-extra-vectors.json").read_text(encoding="utf-8"))


def build(case):
    i = case["input"]
    try:
        return pl.dashboards_link(i["service"], i["instance"], i["path"])
    except pl.PageLinkError:
        return None


class ContractVectors(unittest.TestCase):
    def test_the_constants_are_the_contracts(self):
        c = V["constants"]
        self.assertEqual(pl.MAX_PAGE_PATH_LENGTH, c["MAX_PAGE_PATH_LENGTH"])
        self.assertEqual(pl.MAX_PAGE_LINK_LENGTH, c["MAX_PAGE_LINK_LENGTH"])
        self.assertEqual(pl.SERVICE_ID.pattern.replace("\\Z", "$"), c["SERVICE_ID"])
        self.assertEqual(pl.INSTANCE.pattern.replace("\\Z", "$"), c["INSTANCE"])

    def test_every_build(self):
        for c in V["builds"]:
            with self.subTest(c["name"]):
                self.assertEqual(build(c), c["expected"])

    def test_every_link(self):
        for c in V["links"]:
            url = c["input"]["url"]
            with self.subTest(c["name"]):
                self.assertEqual(pl.page_link_rules("page-link", {"url": url}), c["findings"])
                self.assertEqual(pl.page_link_findings(url, "/url", "the link"), c["findings"])
                self.assertEqual(pl.parse_dashboards_link(url), c["parsed"])
                self.assertIs(pl.is_loopback_page_url(url), c["loopback"])

    def test_every_request(self):
        for c in V["requests"]:
            with self.subTest(c["name"]):
                self.assertEqual(pl.input_request_link_findings(c["input"]), c["findings"])

    def test_another_kind_is_not_ours(self):
        self.assertIsNone(pl.page_link_rules("estate-record", {"url": "http://127.0.0.1/"}))


class KitInputs(unittest.TestCase):
    """D11: the WHATWG URL points the Python port reads by hand, each answered by the reference."""

    def test_every_build(self):
        for c in X["builds"]:
            with self.subTest(c["name"]):
                self.assertEqual(build(c), c["expected"])

    def test_every_parse(self):
        for c in X["parses"]:
            with self.subTest(c["name"]):
                self.assertEqual(pl.parse_dashboards_link(c["input"]["url"]), c["expected"])

    def test_every_loopback_url(self):
        for c in X["loopback"]:
            with self.subTest(ascii(c["input"]["url"])):
                self.assertIs(pl.is_loopback_page_url(c["input"]["url"]), c["expected"])

    def test_every_link(self):
        for c in X["links"]:
            with self.subTest(c["name"]):
                self.assertEqual(pl.page_link_findings(c["input"]["url"], "/url", "the link"), c["expected"])

    def test_every_request(self):
        for c in X["requests"]:
            with self.subTest(c["name"]):
                self.assertEqual(pl.input_request_link_findings(c["input"]), c["expected"])


class Shape(unittest.TestCase):
    def test_a_refused_build_names_every_problem(self):
        with self.assertRaises(pl.PageLinkError) as refused:
            pl.dashboards_link("A", "B", "relative")
        self.assertEqual(str(refused.exception), "the service is not a service id; the instance is not an instance name; "
                                                 "the path is not a path on the service origin")

    def test_a_python_surrogate_pair_is_one_character(self):
        """JavaScript reads a high and a low surrogate side by side as one character; so does the port."""
        pair = chr(0xD83D) + chr(0xDE00)  # two code points, as a Python string can hold them
        self.assertEqual(pl.dashboards_link("example-agent", "default", "/" + pair),
                         pl.dashboards_link("example-agent", "default", "/\U0001F600"))
        self.assertEqual(pl.dashboards_link("example-agent", "default", "/\U0001F600"),
                         "fabric-dashboards://service/example-agent.default?path=%2F%F0%9F%98%80")
        self.assertEqual(pl.dashboards_link("example-agent", "default", "/x?q=" + pair),
                         "fabric-dashboards://service/example-agent.default?path=%2Fx%3Fq%3D%F0%9F%98%80")

    def test_no_em_dash_in_messages(self):
        text = (SCRIPTS / "fabric_page_links.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search("\u2014", text))


if __name__ == "__main__":
    unittest.main()
