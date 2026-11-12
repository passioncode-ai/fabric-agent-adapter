"""fabric_connections.py: fabric-connections/0.1 (DEC-0096, FAC-SEM-127). The reader answers every case of the
contract's fixtures/vectors/connections.json (vendored as test/fixtures/contract/connections-vectors.json, each case
re-answered by the contract's connectionsView); the Node twin runs the same file in fabric-connections.test.mjs."""
import json
import unittest
from pathlib import Path

from test_fabric_service import fs, load

fc = load("fabric_connections")
ServiceError = fc.ServiceError  # the class the kit raises (a second load would make another one)
build_well_known = fs.build_well_known

V = json.loads((Path(__file__).resolve().parent / "fixtures/contract/connections-vectors.json").read_text(encoding="utf-8"))
KEY = fc.CONNECTIONS_EXTENSION_KEY
INPUTS = json.loads((Path(__file__).resolve().parent / "fixtures/kit-connections-inputs.json").read_text(encoding="utf-8"))
EXTRA = json.loads((Path(__file__).resolve().parent / "fixtures/contract/connections-extra-vectors.json").read_text(encoding="utf-8"))


class Vectors(unittest.TestCase):
    def test_every_case_answers_as_the_contract_does(self):
        self.assertEqual(len(V["cases"]), 134)
        for case in V["cases"]:
            with self.subTest(case["name"]):
                view = fc.connections_view(case["input"])
                self.assertEqual({k: view[k] for k in case["expected"]}, case["expected"])
                self.assertEqual(bool(view["errors"]), view["reported"])

    def test_every_kit_input_answers_as_the_contract_does(self):
        """The kit's own inputs (test/fixtures/kit-connections-inputs.json), answered by the contract's connectionsView:
        ECMAScript's whitespace, word boundary and case folding in the credential shapes, and URLs WHATWG refuses."""
        self.assertEqual(len(EXTRA["cases"]), len(INPUTS["inputs"]))
        for index, case in enumerate(EXTRA["cases"]):
            with self.subTest(index=index):
                view = fc.connections_view(case["input"])
                self.assertEqual({k: view[k] for k in case["expected"]}, case["expected"])

    def test_rules_name_fac_sem_127_only_for_a_reported_value(self):
        for case in V["cases"]:
            with self.subTest(case["name"]):
                findings = fc.connections_rules(case["input"])
                self.assertEqual(bool(findings), case["expected"]["reported"])
                self.assertTrue(all(f["code"] == "FAC-SEM-127" for f in findings))

    def test_the_reader_never_raises(self):
        for value in (None, [], "x", 1, {"extensions": None}, {"extensions": {KEY: None}}, {"extensions": {KEY: {"connections": [None, 1]}}},
                      {"extensions": {KEY: {"connections": [{"id": "a", "kind": "model", "target": "x/y", "state": "ok"}]}}, "degraded": [None, {"source": 1}]}):
            with self.subTest(value=value):
                fc.connections_view(value)


class IdnaHosts(unittest.TestCase):
    """FAA-98: a non-ASCII host is refused only where every Node from 20 to 26 refuses it (the closed side stays)."""
    TABLES = json.loads((Path(__file__).resolve().parent / "fixtures/idna/idna-tables.json").read_text(encoding="utf-8"))

    def test_the_idna_tables_are_the_measured_ones(self):
        self.assertEqual([list(r) for r in fc._IDNA_DISALLOWED], self.TABLES["disallowed"])
        self.assertEqual([list(r) for r in fc._IDNA_IGNORED], self.TABLES["ignored"])
        self.assertEqual(self.TABLES["nodes"][0][:3], "v20")
        for table in (fc._IDNA_DISALLOWED, fc._IDNA_IGNORED):
            self.assertEqual(list(table), sorted(table))
            self.assertTrue(all(a <= b for a, b in table))

    def test_refused_for_certain(self):
        for host in ("\ue000", "a\U000f0000b", "a\u0085b", "a\u00a0b", "a\uff0fb", "a\u2488b", "\u00ad", "\u00ad\u200b",
                     "\u0301a", "a.\u0301", "a\u200db", "\u200cb", "a\u05d0b", "\u0628a", "\u05d0\u0661\u06f1",
                     "\uff19\uff19\uff19.\uff11", "a.\uff11", "%ef%bc%8f"):
            with self.subTest(host=ascii(host)):
                self.assertFalse(fc._domain_ok(host))

    def test_left_to_the_doubt_or_valid(self):
        for host in ("b\u00fccher", "\u65e5\u672c", "\u05d0\u05d1", "a.\u05d0", "1.\u05d0", "\u0660",
                     "\u0915\u094d\u200d\u0937", "\u0628a\u200c\u0627", "\u05d0a\u094d\u200d", "a\u061db",
                     "\u0345", "a.\u17b4", "\uff11\uff12\uff17.\uff10.\uff10.\uff11", "\u3002", "\U000e0100a",
                     "xn--bcher-kva\u00e9", "a\U0001f600b"):
            with self.subTest(host=ascii(host)):
                self.assertTrue(fc._domain_ok(host))

    def test_a_mapped_address_is_read_as_one(self):
        """A host UTS46 maps to ASCII is read by the ASCII rules: a credential in `https://u:p@１２７.０.０.１` is read."""
        view = fc.connections_view({"extensions": {KEY: {"connections": [
            {"id": "a", "kind": "connector", "target": "https://u:p@\uff11\uff12\uff17.\uff10.\uff10.\uff11/", "state": "ok"}]}}})
        self.assertTrue(view["reported"])

    def test_an_empty_host_ended_by_a_colon_is_refused(self):
        """`new URL` throws on an empty host ended by `:`, with an empty port or a port: the URL is read as an argument
        only, so its parameters are not read (shared vectors: test_fabric_profiles.py URL_HOSTS)."""
        for value in ("foo://:/?token=abcdef", "git://:/r?access_token=abcdef", "foo://:80/?token=abcdef",
                      "foo://:/#token=abcdef", "foo://u:pw@:/x"):
            with self.subTest(value=value):
                self.assertIsNone(fc._whatwg_parts(value))
                self.assertFalse(fc._secret_url(value))
        self.assertIsNotNone(fc._whatwg_parts("foo:///?token=abcdef"))
        self.assertTrue(fc._secret_url("foo://h:/?token=abcdef"))


class DateTime(unittest.TestCase):
    """ajv-formats `date-time`, full mode: what the contract's validator accepts for `lastAt`."""

    def test_the_forms(self):
        for value, ok in (("2026-10-22T10:00:00Z", True), ("2026-10-22t10:00:00z", True), ("2026-10-22 10:00:00Z", True),
                          ("2026-10-22T10:00:00.5+02:00", True), ("2026-10-22T10:00:00+0200", True), ("2026-10-22T10:00:00+02", True),
                          ("2026-10-22T10:00:00", False), ("2026-10-22", False), ("2026-02-29T00:00:00Z", False),
                          ("2024-02-29T00:00:00Z", True), ("2026-10-22T23:59:60Z", True), ("2026-10-22T22:59:60Z", False),
                          ("2026-10-22T24:00:00Z", False), ("2026-10-22T10:00:00+24:00", False), ("2026-10-22T10:00:00Z\n", False),
                          ("２０２６-10-22T10:00:00Z", False)):
            with self.subTest(value=value):
                self.assertIs(fc.date_time(value), ok)


class Producer(unittest.TestCase):
    DECLARED = [{"id": "router", "kind": "model", "target": "openai/gpt-5.1", "purpose": "answers"},
                {"id": "notify", "kind": "service", "target": "communicator.default", "capability": "communicator.notify"},
                {"id": "crm", "kind": "connector", "target": "hubspot"}]

    def test_state_from_checks_then_degraded_then_unknown(self):
        ext = fc.connections_extension(self.DECLARED, degraded=[{"source": "crm", "reason": "token expired"}],
                                       states={"router": "ok"})
        states = {c["id"]: c["state"] for c in ext[KEY]["connections"]}
        self.assertEqual(states, {"router": "ok", "notify": "unknown", "crm": "degraded"})

    def test_a_declared_state_is_kept(self):
        ext = fc.connections_extension([dict(self.DECLARED[0], state="down")], states={"router": "ok"})
        self.assertEqual(ext[KEY]["connections"][0]["state"], "down")

    def test_a_declaration_a_host_would_hide_is_refused(self):
        for bad in ([self.DECLARED[0], dict(self.DECLARED[0])],  # an id twice
                    [{"id": "x", "kind": "connector", "target": "api", "purpose": "key sk-AbCdEf0123456789xyzQ"}],  # a credential
                    [{"id": "x", "kind": "model", "target": "a/b", "capability": "c.d"}],  # capability on a model
                    [{"id": "X", "kind": "store", "target": "db"}]):  # the id's pattern
            with self.subTest(bad=bad), self.assertRaises(ServiceError):
                fc.connections_extension(bad)

    def test_odd_input_is_refused_with_service_error_only(self):
        for declared, kwargs in ((["x"], {}), ([None], {}), ([[("id", "a")]], {}), (None, {}), ("ab", {}),
                                 ([self.DECLARED[2]], {"degraded": "x"}), ([self.DECLARED[2]], {"states": ["router"]}),
                                 ([self.DECLARED[0]], {"states": {"router": ""}})):
            with self.subTest(declared=declared, kwargs=kwargs), self.assertRaises(ServiceError):
                fc.connections_extension(declared, **kwargs)
        ext = fc.connections_extension([self.DECLARED[2]], degraded=None, states=None)
        self.assertEqual(ext[KEY]["connections"][0]["state"], "unknown")

    def test_a_secret_shaped_member_name_never_reaches_the_message(self):
        secret = "sk-AbCdEf0123456789xyzQ"
        value = {"connections": [dict(self.DECLARED[2], state="ok", **{secret: 1})], secret: 2}
        findings = fc.connections_rules({"extensions": {KEY: value}})
        self.assertTrue(findings)
        self.assertNotIn(secret, json.dumps(findings))
        with self.assertRaises(ServiceError) as raised:
            fc.connections_extension([dict(self.DECLARED[2], **{secret: 1})])
        self.assertNotIn(secret, str(raised.exception))

    def test_the_well_known_document_carries_it_and_a_host_reads_it(self):
        ext = fc.connections_extension(self.DECLARED, degraded=[{"source": "crm", "reason": "token expired"}])
        doc = build_well_known(service_id="example-agent", instance="default", name="Example", version="1.0.0",
                               build={"commit": "0" * 40}, started_at="2026-10-22T00:00:00Z", status="degraded",
                               degraded=[{"source": "crm", "reason": "token expired"}], surfaces={"events": "/fabric/v1/events"},
                               extensions=ext)
        view = fc.connections_view(doc)
        self.assertTrue(view["declared"])
        self.assertEqual([c["failing"] for c in view["connections"]], [False, False, True])

    def test_build_well_known_refuses_an_invalid_declaration(self):
        with self.assertRaises(ServiceError):
            build_well_known(service_id="example-agent", instance="default", name="Example", version="1.0.0",
                             build={"commit": "0" * 40}, started_at="2026-10-22T00:00:00Z", status="ready", degraded=[],
                             surfaces={"events": "/fabric/v1/events"},
                             extensions={KEY: {"connections": [{"id": "a", "kind": "nope", "target": "t", "state": "ok"}]}})


if __name__ == "__main__":
    unittest.main()
