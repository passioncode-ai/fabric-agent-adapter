"""DEC-0070 (an event's data) and DEC-0067 (protocol revisions) in the Python service kit (FAA-35, FAA-37); the twin of
fabric-service-feed-protocols.test.mjs. Held to the contract's answers (test/fixtures/contract/feed-protocols-vectors.json,
vendor_vectors.mjs)."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from test_fabric_service import load

fs = load("fabric_service")
probe = load("check_service")
V = json.loads((Path(__file__).resolve().parent / "fixtures/contract/feed-protocols-vectors.json").read_text(encoding="utf-8"))


def paths(findings):
    return [f["instancePath"] for f in findings]


class Revisions(unittest.TestCase):
    def test_the_register_is_the_contracts(self):
        self.assertEqual({k: list(v) for k, v in fs.PROTOCOL_REVISIONS.items()}, V["register"])

    def test_negotiate_revision(self):
        self.assertEqual(len(V["negotiation"]), 7)
        for c in V["negotiation"]:
            with self.subTest(c["name"]):
                self.assertEqual(fs.negotiate_revision(c["received"], c["accepted"]), c["expect"])
        self.assertEqual(fs.negotiate_revision("fabric-service/0.1", ["bad", 7]), {"fault": "no-accepted-revisions"})
        self.assertEqual(len(fs.negotiate_revision("x" * 200, ["fabric-service/0.1"])["error"]["data"]["protocol"]), 80)
        self.assertEqual(fs.accepted_revisions("fabric-service"), ["fabric-service/0.1"])
        self.assertEqual(fs.accepted_revisions("nothing"), [])

    def test_fac_sem_099(self):
        for c in V["protocolLists"]:
            with self.subTest(list=str(c["list"])[:40]):
                prefix = "" if isinstance(c["list"], list) else "/protocols"
                self.assertEqual(paths(fs.protocols_findings(c["list"], prefix)), [f["instancePath"] for f in c["findings"]])

    def test_two_revisions_are_n_and_n_minus_one(self):
        """The register has one revision per protocol at this pin, so N−1 does not exist yet: the rule is held on a
        register with three revisions of one protocol, as the contract states it (FAC-SEM-099)."""
        from unittest import mock
        with mock.patch.dict(fs.PROTOCOL_REVISIONS, {"example-protocol": ("1", "2", "3")}):
            self.assertEqual(fs.protocols_findings(["example-protocol/2", "example-protocol/3"], ""), [])
            self.assertEqual(paths(fs.protocols_findings(["example-protocol/1", "example-protocol/3"], "")), ["/1"])
            self.assertEqual(fs.accepted_revisions("example-protocol"), ["example-protocol/3", "example-protocol/2"])
            self.assertEqual(fs.accepted_revisions("example-protocol", "1"), ["example-protocol/1"])

    def test_the_well_known_document_lists_protocols_only_when_given_and_valid(self):
        base = dict(service_id="example-agent", instance="default", name="Example Agent", version="1.0.0", build={"commit": "0" * 40},
                    started_at="2026-10-13T08:00:00Z", status="ready", degraded=[], surfaces={"events": {"path": "/fabric/v1/events"}})
        self.assertNotIn("protocols", fs.build_well_known(**base))
        self.assertEqual(fs.build_well_known(**base, protocols=["fabric-service/0.1"])["protocols"], ["fabric-service/0.1"])
        for bad in (["fabric-service/0.2"], ["fabric-service/0.1", "fabric-service/0.1"], []):
            with self.subTest(bad=bad), self.assertRaises(fs.ServiceError):
                fs.build_well_known(**base, protocols=bad)


class FeedData(unittest.TestCase):
    def test_contract_fixtures(self):
        for f in V["fixtures"]:
            if not f["name"].startswith("service-events-page"):
                continue
            with self.subTest(f["name"]):
                problems = [p for e in f["document"]["events"] if "data" in e for p in fs.feed_data_problems(e["data"])]
                self.assertEqual(not problems, f["valid"], problems)

    def test_a_value_nested_too_deep_names_its_place(self):
        """FAA-122: a list of objects in `value` is refused naming the first place that nests too deep."""
        cases = (({"cited": [{"id": "a1", "coverage": 0.8}]}, "data.value.cited[0] is an object"),
                 ({"counts": {"by": [1, 2]}}, "data.value.counts.by is a list"),
                 ({"note": ["x" * 501]}, "data.value.note[0] is a string over 500 characters"),
                 ({"many": list(range(33))}, "it has 33 entries"))
        for value, said in cases:
            with self.subTest(said=said):
                (problem,) = fs.feed_data_problems({"schema": "urn:example:schema:day:1", "value": value})
                self.assertIn(said, problem)
        self.assertEqual(fs.feed_data_problems({"schema": "urn:example:schema:day:1",
                                                "value": {"citedIds": ["a1", "b2"], "citedCoverage": [0.8, 0.4]}}), [])

    def test_fac_sem_101_at_the_contracts_places(self):
        self.assertEqual(len(V["feedPages"]), 10)
        for c in V["feedPages"]:
            with self.subTest(value=list(c["page"]["events"][0]["data"]["value"])):
                self.assertEqual(paths(fs.feed_data_findings(c["page"])), [f["instancePath"] for f in c["findings"]])

    def test_an_event_takes_data_and_refuses_a_credential(self):
        data = {"schema": "https://example.com/schemas/note.json", "value": {"notes": 3, "inputTokens": 1200}}
        self.assertEqual(fs.make_event(1, "2026-10-13T08:00:00Z", "job.done", "info", "A note was drafted.", data=data)["data"], data)
        for bad in ({"schema": "https://example.com/s.json", "value": {"apiKey": "abc"}}, {"schema": "s.json", "value": {}},
                    {"schema": "https://example.com/s.json", "value": {"x": "y" * 501}}, {"value": {}}):
            with self.subTest(bad=bad), self.assertRaises(fs.ServiceError) as caught:
                fs.make_event(1, "2026-10-13T08:00:00Z", "job.done", "info", "A note was drafted.", data=bad)
            self.assertNotIn("abc", str(caught.exception), "a refusal names the place, never the value")

    def test_the_log_keeps_data(self):
        temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp, True)
        log = fs.JsonlEventLog(temp / "events.jsonl")
        log.append("job.done", "info", "A note was drafted.", data={"schema": "https://example.com/s.json", "value": {"notes": 1}})
        self.assertEqual(log.fetch(None, 10)[0]["data"]["value"], {"notes": 1})


class ProbeRules(unittest.TestCase):
    """check_service.py reads FAC-SEM-099 on the well-known document and FAC-SEM-101 on the feed it fetches."""

    def probe(self, wk, page):
        d = {"protocol": "fabric-service/0.1", "id": "example-agent", "instance": "default", "name": "Example Agent",
             "origin": "http://127.0.0.1:47299", "auth": {"tokenFile": "~/x.token"}, "lifecycle": {"manager": "none"},
             "paths": {"data": "~/x"}, "installedAt": "2026-10-13T08:00:00Z", "installedBy": "test"}
        temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp, True)
        pr = probe.Probe(Path("/tmp/x.json"), d, temp, skip_login=True)
        pr.token = "t" * 32
        pr.read_token = lambda: None

        def request(method, path, headers=None, body=None):
            if path.startswith("/.well-known"):
                return 200, {"content-type": "application/json"}, json.dumps(wk).encode()
            return (200 if headers else 401), {}, json.dumps(page).encode()
        pr.request = request
        pr.well_known_rules()
        pr.auth_rules()
        return {r["rule"]: r for r in pr.results}

    def test_protocols_and_event_data(self):
        wk = fs.build_well_known(service_id="example-agent", instance="default", name="Example Agent", version="1.0.0",
                                 build={"commit": "0" * 40}, started_at="2026-10-13T08:00:00Z", status="ready", degraded=[],
                                 surfaces={"events": {"path": "/fabric/v1/events"}}, protocols=["fabric-service/0.1"])
        good = {"events": [fs.make_event(1, "2026-10-13T08:00:00Z", "job.done", "info", "A note was drafted.",
                                         data={"schema": "https://example.com/s.json", "value": {"notes": 1}})], "cursor": "1"}
        results = self.probe(wk, good)
        self.assertEqual((results["well-known.protocols"]["verdict"], results["events.data"]["verdict"]), ("PASS", "PASS"))
        bad_wk = dict(wk, protocols=["fabric-service/0.2"])
        bad_page = {"events": [dict(good["events"][0], data={"schema": "https://example.com/s.json", "value": {"apiKey": "abc"}})], "cursor": "1"}
        results = self.probe(bad_wk, bad_page)
        self.assertEqual((results["well-known.protocols"]["verdict"], results["events.data"]["verdict"]), ("FAIL", "FAIL"))
        self.assertNotIn("abc", results["events.data"]["evidence"])
        results = self.probe(dict(wk), {"events": [], "cursor": None})
        self.assertNotIn("events.data", results, "a feed without data has no data rule")

    def test_connections_fac_sem_127(self):
        """DEC-0096: the probe reads a declared connections list as a host does; a list a host would hide fails, and
        the credential that hid it never reaches the evidence."""
        fcn = load("fabric_connections")
        key = fcn.CONNECTIONS_EXTENSION_KEY
        good = [{"id": "router", "kind": "model", "target": "openai/gpt-5.1", "state": "ok"}]
        wk = fs.build_well_known(service_id="example-agent", instance="default", name="Example Agent", version="1.0.0",
                                 build={"commit": "0" * 40}, started_at="2026-10-13T08:00:00Z", status="ready", degraded=[],
                                 surfaces={"events": {"path": "/fabric/v1/events"}}, extensions={key: {"connections": good}})
        page = {"events": [], "cursor": None}
        self.assertEqual(self.probe(wk, page)["well-known.connections"]["verdict"], "PASS")
        secret = "sk-AbCdEf0123456789xyzQ"
        bad = dict(wk, extensions={key: {"connections": [dict(good[0], purpose="uses " + secret)]}})
        result = self.probe(bad, page)["well-known.connections"]
        self.assertEqual(result["verdict"], "FAIL")
        self.assertNotIn(secret, result["evidence"])
        self.assertNotIn("well-known.connections", self.probe(dict(wk, extensions={}), page), "an optional extension")


if __name__ == "__main__":
    unittest.main()
