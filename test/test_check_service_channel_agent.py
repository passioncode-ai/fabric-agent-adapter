"""FAA-197: the probe's channel-agent rule (DEC-0150, FAC-SEM-162 to 165), held to the contract's own vectors.

Every declaration of test/fixtures/contract/channel-agent-vectors.json (vendored byte for byte by
make_channel_agent_vectors.mjs) runs through check_service_channel_agent.channel_agent_rules, and its findings
{code, instancePath} equal the vector's as a set (the vectors' `about` allows it; duplicates are counted too); a vector
that carries `view` is compared with channel_agent_view. Then the rule check_service.py adds: CA-1's two sites (D1),
a declaration read as not declared reported but never failed (D3), and the well-known answer's 2 MiB cap (D4)."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
CONTRACT = ROOT / "test/fixtures/contract"
VECTORS = json.loads((CONTRACT / "channel-agent-vectors.json").read_text(encoding="utf-8"))
KEY = VECTORS["key"]


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(module)
    return module


ca = load("check_service_channel_agent")
cas = load("check_service_channel_agent_schema")


def document(vector):
    return vector["input"] if "input" in vector else json.loads(vector["inputText"])


def pairs(findings):
    return sorted((f["code"], f["instancePath"]) for f in findings)


def valid_declaration():
    vector = next(d for d in VECTORS["declarations"] if d["name"] == "one project, every member")
    return copy.deepcopy(vector["input"]["provider"]["extensions"][KEY])


class Vendored(unittest.TestCase):
    def test_the_files_are_the_contracts_at_the_pin(self):
        source = json.loads((CONTRACT / "channel-agent.source.json").read_text(encoding="utf-8"))
        pin = json.loads((ROOT / "fabric-contract.lock.json").read_text(encoding="utf-8"))["commit"]
        self.assertEqual(source["commit"], pin, "the pin moved: run make_channel_agent_vectors.mjs at the new pin")
        for name, entry in source["files"].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((CONTRACT / name).read_bytes()).hexdigest(), entry["sha256"])

    def test_the_probe_reads_the_vendored_schema_byte_for_byte(self):
        self.assertEqual(cas.SCHEMA_FILE.read_bytes(), (CONTRACT / "service-channel-agent-extension.schema.json").read_bytes())

    def test_the_reader_reads_every_keyword_the_schema_uses(self):
        self.assertEqual(cas.unsupported(), [])
        self.assertEqual(cas.unsupported({"type": "object", "dependentRequired": {}}), ["dependentRequired"])
        self.assertEqual(cas.unsupported({"type": "string", "format": "email"}), ["format email"])

    def test_the_key_is_the_vectors(self):
        self.assertEqual(ca.KEY, KEY)
        self.assertEqual(len(VECTORS["declarations"]), 148)


class Vectors(unittest.TestCase):
    def test_every_declaration_finds_what_the_contract_finds(self):
        passed = 0
        for vector in VECTORS["declarations"]:
            with self.subTest(vector["name"]):
                self.assertEqual(pairs(ca.channel_agent_rules(document(vector), vector["site"])), pairs(vector["findings"]))
                passed += 1
        self.assertEqual(passed, 148)

    def test_every_view_is_the_contracts(self):
        views = [d for d in VECTORS["declarations"] if "view" in d]
        self.assertEqual(len(views), 13)
        for vector in views:
            with self.subTest(vector["name"]):
                view = ca.channel_agent_view(document(vector), vector["site"])
                self.assertEqual({key: view[key] for key in vector["view"]}, vector["view"])

    def test_no_message_repeats_a_declared_value(self):
        """CA-5: a credential-shaped value or name is placed, never written into a message."""
        for vector in VECTORS["declarations"]:
            if vector["name"] != "a holding text that carries a bearer token":
                continue
            findings = ca.channel_agent_rules(document(vector), vector["site"])
            texts = vector["input"]["provider"]["extensions"][KEY]["projects"][0]["channels"][0]["texts"]["holding"]
            for finding in findings:
                for text in texts.values():
                    self.assertNotIn(text, finding["message"])


class Recipe(unittest.TestCase):
    def test_the_support_agent_recipes_declaration_has_no_finding(self):
        example = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/recipes/support-agent/channel-agent.example.json"
        extensions = json.loads(example.read_text(encoding="utf-8"))
        self.assertEqual(ca.channel_agent_rules({"provider": {"extensions": extensions}}, "manifest"), [])
        self.assertTrue(ca.channel_agent_view({"extensions": extensions}, "well-known")["declared"])


class Schema(unittest.TestCase):
    """The schema half's own readings beyond the vectors' findings: the places a FAC-SEM-162 message names."""

    def test_a_nullable_member_fails_in_one_line(self):
        declaration = valid_declaration()
        declaration["projects"][0]["channels"][0]["decision"] = 5
        lines = cas.schema_errors(declaration)
        self.assertEqual(lines, ["type at /projects/0/channels/0/decision (string), or null"])

    def test_the_none_form_says_what_until_takes(self):
        declaration = valid_declaration()
        declaration["projects"][0]["question_route"] = {"none": "not_used", "until": "2026-01-01"}
        self.assertEqual(cas.schema_errors(declaration), ["not at /projects/0/question_route (until only with not_yet)"])

    def test_a_language_is_written_star_and_a_date_is_a_real_one(self):
        declaration = valid_declaration()
        texts = declaration["projects"][0]["channels"][0]["texts"]
        texts["holding"] = {"x y": "a"}
        declaration["projects"][0]["adopted_at"] = "2026-02-30"
        lines = cas.schema_errors(declaration)
        self.assertIn("format at /projects/0/adopted_at (format date)", lines)
        self.assertTrue(any(line.startswith("propertyNames at /projects/0/channels/0/texts/holding (a member name matching") for line in lines))
        self.assertFalse(any("x y" in line for line in lines))


class Verdict(unittest.TestCase):
    """The rule check_service.py adds as channel-agent.declaration."""

    def manifest(self, declaration=None, **extra):
        doc = {"provider": {"extensions": {} if declaration is None else {KEY: declaration}}}
        doc.update(extra)
        return doc

    def test_a_valid_declaration_in_the_manifest_passes(self):
        verdict, evidence = ca.declaration_verdict(self.manifest(valid_declaration()), True, "", {"extensions": {}})
        self.assertEqual(verdict, "PASS")
        self.assertIn("1 project(s)", evidence)

    def test_findings_on_the_declaration_fail(self):
        declaration = valid_declaration()
        declaration["projects"][0]["channels"][0]["texts"]["final"] = {"en": "a \u2014 b"}
        verdict, evidence = ca.declaration_verdict(self.manifest(declaration), True, "", {})
        self.assertEqual(verdict, "FAIL")
        self.assertIn("FAC-SEM-164 at %s/projects/0/channels/0/texts/final/*" % ca.CHANNEL_AGENT_PATHS["manifest"], evidence)
        self.assertNotIn("\u2014", evidence)

    def test_an_invalid_declaration_at_the_read_site_fails(self):
        declaration = valid_declaration()
        declaration["standard"] = "channel-agent-standard/2"
        verdict, evidence = ca.declaration_verdict(None, False, "", {"extensions": {KEY: declaration}})
        self.assertEqual(verdict, "FAIL")
        self.assertIn("FAC-SEM-162 at %s" % ca.CHANNEL_AGENT_PATHS["well-known"], evidence)

    def test_ca1_a_service_with_a_manifest_is_read_from_the_manifest_only(self):
        bad = valid_declaration()
        bad["standard"] = "channel-agent-standard/2"
        verdict, evidence = ca.declaration_verdict(self.manifest(valid_declaration()), True, "", {"extensions": {KEY: bad}})
        self.assertEqual(verdict, "PASS", "the well-known copy is not the declaration (D1)")
        self.assertIn("the well-known answer's copy is ignored", evidence)
        self.assertIn("1 finding(s): FAC-SEM-162", evidence)
        verdict, evidence = ca.declaration_verdict(self.manifest(), True, "", {"extensions": {KEY: valid_declaration()}})
        self.assertEqual(verdict, "NOT_RUN", "a copy only in the well-known answer of a service with a manifest is not read")
        self.assertIn("read as not declared", evidence)

    def test_ca1_a_service_with_no_manifest_is_read_from_its_well_known_answer(self):
        verdict, _ = ca.declaration_verdict(None, False, "the descriptor names no fabricManifest", {"extensions": {KEY: valid_declaration()}})
        self.assertEqual(verdict, "PASS")

    def test_d3_a_misplaced_key_is_reported_never_failed(self):
        verdict, evidence = ca.declaration_verdict(self.manifest(extensions={KEY: valid_declaration()}), True, "", {})
        self.assertEqual(verdict, "NOT_RUN")
        self.assertIn("read as not declared", evidence)
        self.assertIn("FAC-SEM-162 at /extensions/", evidence)

    def test_d3_a_misplaced_copy_beside_a_read_declaration_does_not_fail_it(self):
        doc = self.manifest(valid_declaration(), capabilities=[{"extensions": {KEY: {"x": 1}}}])
        verdict, evidence = ca.declaration_verdict(doc, True, "", {})
        self.assertEqual(verdict, "PASS")
        self.assertIn("not read, reported: FAC-SEM-162 at /capabilities/0/extensions/", evidence)

    def test_d3_another_versions_key_is_reported_never_failed(self):
        doc = {"provider": {"extensions": {ca.KEY_PREFIX + "0.0": valid_declaration()}}}
        verdict, evidence = ca.declaration_verdict(doc, True, "", {})
        self.assertEqual(verdict, "NOT_RUN")
        self.assertIn("another version is not read (CA-7): /provider/extensions (version 0.0)", evidence)
        doc = {"provider": {"extensions": {ca.KEY_PREFIX + "sk-ABCDEFGHIJKLMNOPQRST": {}}}}
        self.assertNotIn("sk-", ca.declaration_verdict(doc, True, "", {})[1], "a key that is not a version is not echoed")

    def test_nothing_declared_is_not_run(self):
        verdict, evidence = ca.declaration_verdict(None, False, "", {"extensions": {}})
        self.assertEqual(verdict, "NOT_RUN")
        self.assertIn("not a channel agent", evidence)
        self.assertEqual(ca.declaration_verdict(None, False, "", None)[0], "NOT_RUN")

    def test_an_unreadable_manifest_is_not_run(self):
        verdict, evidence = ca.declaration_verdict(None, True, "manifest x does not resolve", {"extensions": {KEY: valid_declaration()}})
        self.assertEqual(verdict, "NOT_RUN")
        self.assertIn("does not resolve", evidence)

    def test_d4_the_well_known_answer_near_or_over_the_2_mib_cap_is_named(self):
        wk = {"extensions": {KEY: valid_declaration()}}
        self.assertNotIn("2 MiB", ca.declaration_verdict(None, False, "", wk, 4096)[1])
        verdict, evidence = ca.declaration_verdict(None, False, "", wk, ca.WELL_KNOWN_NEAR)
        self.assertEqual(verdict, "PASS", "the cap is named, not failed")
        self.assertIn("near the 2 MiB cap", evidence)
        self.assertIn("over the 2 MiB cap", ca.declaration_verdict(None, False, "", wk, ca.WELL_KNOWN_CAP + 1)[1])
        self.assertNotIn("2 MiB", ca.declaration_verdict(None, False, "", {"extensions": {}}, ca.WELL_KNOWN_CAP + 1)[1],
                         "an answer with no declaration owes the rule nothing")


class Probe(unittest.TestCase):
    """check_service.py runs the rule with the manifest the descriptor names and the fetched well-known answer."""

    def probe(self, descriptor, wk, wk_bytes=None):
        checker = load("check_service")
        probe = checker.Probe(Path("/nonexistent"), dict({"origin": "http://127.0.0.1:1"}, **descriptor), Path("/nonexistent"), True)
        probe.wk = wk
        if wk_bytes is not None:
            probe.wk_bytes = wk_bytes
        return probe

    def test_the_rule_reads_the_manifest_the_descriptor_names(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fabric-agent.json"
            path.write_text(json.dumps({"provider": {"extensions": {KEY: valid_declaration()}}}), encoding="utf-8")
            probe = self.probe({"fabricManifest": str(path)}, {"extensions": {}})
            probe.channel_agent_rule()
            self.assertEqual((probe.results[-1]["rule"], probe.results[-1]["verdict"]), ("channel-agent.declaration", "PASS"))

    def test_the_rule_reads_the_well_known_answer_with_no_manifest(self):
        declaration = valid_declaration()
        declaration["projects"].append(copy.deepcopy(declaration["projects"][0]))
        probe = self.probe({}, {"extensions": {KEY: declaration}}, ca.WELL_KNOWN_CAP + 1)
        probe.channel_agent_rule()
        result = probe.results[-1]
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("FAC-SEM-163 at /extensions/", result["evidence"])
        self.assertIn("over the 2 MiB cap", result["evidence"])


if __name__ == "__main__":
    unittest.main()
