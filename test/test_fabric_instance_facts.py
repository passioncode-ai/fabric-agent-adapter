"""fabric_instance_facts.py: fabric-instance-facts/0.1 (DEC-0173, FAC-SEM-180, FAA-342). The reader and the rules answer
every case of the contract's fixtures/vectors/instance-facts.json and the kit's hostile cases, vendored as
test/fixtures/contract/instance-facts-vectors.json with each answer re-computed by the contract's functions at the pin;
the descriptor writer and the well-known builder keep the extension key and its value as given. The Node twin runs the
same file in fabric-instance-facts.test.mjs."""
import json
import tempfile
import unittest
from pathlib import Path

from test_fabric_service import descriptor, fs, load

fif = load("fabric_instance_facts")

HERE = Path(__file__).resolve().parent
V = json.loads((HERE / "fixtures/contract/instance-facts-vectors.json").read_text(encoding="utf-8"))
KEY = "https://fabric.passioncode.ai/agent-contract/extensions/instance-facts/0.1"
FACTS = {"access": {"audience": "operator", "entry": "own-signin"}, "tenancy": {"mode": "single"},
         "space": {"kind": "user", "account": "agents-1"}}
KINDS = (("service-descriptor", "descriptor"), ("service-well-known", "wellKnown"), ("service-observation", "pair"))


class VectorTests(unittest.TestCase):
    def test_the_key_is_the_contracts(self):
        self.assertEqual(fif.INSTANCE_FACTS_EXTENSION_KEY, V["key"])
        self.assertEqual(fif.INSTANCE_FACTS_EXTENSION_KEY, KEY)

    def test_every_case_reads_as_the_contract_does(self):
        self.assertEqual(len([c for c in V["cases"] if not c["name"].startswith("hostile: ")]), 38)
        self.assertGreaterEqual(len(V["cases"]), 69)
        for c in V["cases"]:
            with self.subTest(c["name"]):
                read = fif.instance_facts(c["descriptor"], c["wellKnown"])
                self.assertEqual(read, c["read"])
                self.assertEqual(list(read["facts"]), list(c["read"]["facts"]), "the facts' order")

    def test_every_case_finds_as_the_contract_does(self):
        for c in V["cases"]:
            for kind, key in KINDS:
                expected = c["findings"][key]
                if expected is None:
                    continue
                value = c[key] if key != "pair" else {"descriptor": c["descriptor"], "wellKnown": c["wellKnown"]}
                with self.subTest(c["name"], kind=kind):
                    self.assertEqual(fif.instance_facts_rules(kind, value), expected)

    def test_other_kinds_and_shapes_answer_nothing(self):
        for kind, value in (("service-directory", {}), ("service-descriptor", None), ("service-well-known", []),
                            ("service-observation", "x")):
            self.assertEqual(fif.instance_facts_rules(kind, value), [])
        self.assertEqual(fif.instance_facts(None, None),
                         {"declared": False, "facts": {}, "refused": [], "foreign": False, "invalid": []})


class PassThroughTests(unittest.TestCase):
    """DEC-0173 IF-1: the extension is the service's own declaration; the kit's writers keep its key and value."""

    def test_the_descriptor_writer_keeps_the_key(self):
        with tempfile.TemporaryDirectory() as temp:
            desc = dict(descriptor(47931, "facts-keeper"), extensions={KEY: json.loads(json.dumps(FACTS))})
            self.assertEqual(fs.validate_descriptor(desc), [])
            written = json.loads(fs.write_descriptor(desc, Path(temp) / "services", port_owner=lambda port: None).read_text("utf-8"))
            self.assertEqual(list(written["extensions"]), [KEY])
            self.assertEqual(written["extensions"][KEY], FACTS)
            self.assertEqual(fif.instance_facts_rules("service-descriptor", written), [])

    def test_the_well_known_builder_keeps_the_key(self):
        doc = fs.build_well_known(service_id="facts-keeper", instance="default", name="Example", version="1.0.0",
                                  build={"commit": "0" * 40}, started_at="2026-11-16T00:00:00Z", status="ready",
                                  degraded=[], surfaces={"events": {"path": "/fabric/v1/events"}},
                                  extensions={KEY: {"access": {"audience": "organization"}, "tenancy": {"mode": "shared"}}})
        self.assertEqual(doc["extensions"], {KEY: {"access": {"audience": "organization"}, "tenancy": {"mode": "shared"}}})
        self.assertEqual(fif.instance_facts_rules("service-well-known", doc), [])
        # The pair with a local descriptor finds what neither document alone shows; the builder never refuses it, so a
        # service's update never fails on a rule its next pin brings (the probe reports it).
        pair = {"descriptor": descriptor(47931, "facts-keeper"), "wellKnown": doc}
        self.assertEqual([f["instancePath"].rsplit("/", 2)[-2:] for f in fif.instance_facts_rules("service-observation", pair)],
                         [["access", "audience"], ["tenancy", "mode"]])


class ProbeTests(unittest.TestCase):
    def test_the_probe_verdict(self):
        check = load("check_service_rules")
        local = descriptor(47931, "facts-keeper")
        self.assertEqual(check.instance_facts_verdict(local, {"service": {"id": "facts-keeper"}})[0], "NOT_RUN")
        good = dict(local, extensions={KEY: FACTS})
        verdict, evidence = check.instance_facts_verdict(good, {"service": {"id": "facts-keeper", "instance": "default"}})
        self.assertEqual(verdict, "PASS", evidence)
        self.assertIn("audience operator", evidence)
        wk = {"service": {"id": "facts-keeper", "instance": "default"}, "extensions": {KEY: {"space": {"kind": "system"}}}}
        verdict, evidence = check.instance_facts_verdict(local, wk)
        self.assertEqual(verdict, "FAIL")
        self.assertIn("FAC-SEM-180", evidence)
        self.assertIn("/wellKnown/extensions/", evidence)


if __name__ == "__main__":
    unittest.main()
