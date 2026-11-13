"""FAA-197: the probe's channel-agent rule (DEC-0150, FAC-SEM-162 to 165), held to the contract's own vectors.

Every declaration of test/fixtures/contract/channel-agent-vectors.json (vendored byte for byte by
make_channel_agent_vectors.mjs) runs through check_service_channel_agent.channel_agent_rules, and its findings
{code, instancePath} equal the vector's in the reference's order; a vector
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
    return [(f["code"], f["instancePath"]) for f in findings]  # in the reference's order


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

    def test_d3_a_declaration_the_reader_reads_as_not_declared_is_reported_never_failed(self):
        declaration = valid_declaration()
        declaration["standard"] = "channel-agent-standard/2"  # an older or other form under the key: CA-2 reads it as not declared
        verdict, evidence = ca.declaration_verdict(None, False, "", {"extensions": {KEY: declaration}})
        self.assertEqual(verdict, "NOT_RUN")
        self.assertIn("read as not declared, never a failure", evidence)
        self.assertIn("FAC-SEM-162 at %s" % ca.CHANNEL_AGENT_PATHS["well-known"], evidence)

    def test_d3_a_credentials_shape_in_any_copy_fails(self):
        shaped = valid_declaration()
        shaped["projects"][0]["channels"][0]["texts"]["final"] = {"en": "key " + "s" + "k-or-v1-" + "a1b2c3d4" * 8}
        cases = [
            ("a well-known copy beside a valid manifest",
             (self.manifest(valid_declaration()), True, "", {"extensions": {KEY: shaped}})),
            ("a well-known copy of a manifest that declares nothing", (self.manifest(), True, "", {"extensions": {KEY: shaped}})),
            ("a well-known copy of an unreadable manifest", (None, True, "x", {"extensions": {KEY: shaped}})),
            ("a capability's copy beside a valid declaration",
             (self.manifest(valid_declaration(), capabilities=[{"extensions": {KEY: shaped}}]), True, "", {})),
            ("the manifest's own extensions", (self.manifest(extensions={KEY: shaped}), True, "", {})),
        ]
        for name, args in cases:
            with self.subTest(name):
                verdict, evidence = ca.declaration_verdict(*args)
                self.assertEqual(verdict, "FAIL")
                self.assertIn("FAC-SEM-165", evidence)
                self.assertNotIn("k-or-v1", evidence)

    def test_d3_a_credentials_shape_always_fails(self):
        declaration = valid_declaration()
        declaration["projects"][0]["channels"][0]["texts"]["final"] = {"en": "key " + "s" + "k-or-v1-" + "a1b2c3d4" * 8}
        verdict, evidence = ca.declaration_verdict(None, False, "", {"extensions": {KEY: declaration}})
        self.assertEqual(verdict, "FAIL", "a credential's shape is never a compatibility matter (FAC-SEM-165)")
        self.assertIn("FAC-SEM-165", evidence)
        self.assertNotIn("k-or-v1", evidence)

    def test_a_copy_shape_failure_also_names_the_read_declarations_findings(self):
        """FAA-250 (6): the copy-shape FAIL named only the copies; the read declaration's own findings join it."""
        shaped = valid_declaration()
        shaped["projects"][0]["channels"][0]["texts"]["final"] = {"en": "key " + "s" + "k-or-v1-" + "a1b2c3d4" * 8}
        declaration = valid_declaration()
        declaration["projects"][0]["channels"][0]["texts"]["final"] = {"en": "a \u2014 b"}
        verdict, evidence = ca.declaration_verdict(self.manifest(declaration), True, "", {"extensions": {KEY: shaped}})
        self.assertEqual(verdict, "FAIL")
        self.assertIn("outside the read declaration", evidence)
        self.assertIn("on the read declaration itself", evidence)

    def test_an_empty_host_ended_by_a_colon_is_no_url(self):
        """`new URL` throws on an empty host ended by `:`, whatever the port: url_parts answers None and the head is read
        by secret_argument alone (shared vectors: test_fabric_profiles.py URL_HOSTS)."""
        for value in ("foo://:/?token=abcdef", "git://:/r?access_token=abcdef", "foo://:80/?token=abcdef",
                      "foo://:/#token=abcdef"):
            with self.subTest(value=value):
                self.assertIsNone(ca.url_parts(value))
                self.assertFalse(ca.shaped_read(value))
        self.assertEqual(ca.url_parts("foo:///?token=abcdef"), ("?token=abcdef", ""))
        self.assertEqual(ca.url_parts("foo://h:/?token=abcdef"), ("?token=abcdef", ""))

    def test_format_characters_newer_than_this_pythons_unicode_are_blank(self):
        """FAA-250 (1): Python 3.9 (Unicode 13) reads U+0890 and U+1343F as unassigned; the contract's \\p{Cf} and newer
        Pythons read them as format characters, so a text of them is blank on every Python."""
        for code in (0x0890, 0x0891, 0x13439, 0x1343F):
            with self.subTest(code=hex(code)):
                self.assertTrue(ca.blank(chr(code)))
                self.assertTrue(ca.blank(" " + chr(code) + "\u200b"))
        self.assertFalse(ca.blank(chr(0x0892)))

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
        doc = {"provider": {"extensions": {ca.KEY_PREFIX + "s" + "k-ABCDEFGHIJKLMNOPQRST": {}}}}
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
        self.assertIn("the well-known answer's copy is not read", evidence)
        self.assertIn("over the 2 MiB cap", ca.declaration_verdict(
            None, True, "x", {"extensions": {KEY: valid_declaration()}}, ca.WELL_KNOWN_CAP + 1)[1])

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

    def test_a_copy_without_the_schema_is_not_run_and_the_later_rules_run(self):
        """FAA-250 (3): a probe copied without service-channel-agent-extension.schema.json raised at the first declared
        service; the rule is NOT_RUN naming the file."""
        from unittest import mock
        checker = load("check_service")
        probe = checker.Probe(Path("/nonexistent"), {"origin": "http://127.0.0.1:1"}, Path("/nonexistent"), True)
        probe.wk = {"extensions": {KEY: valid_declaration()}}
        schema = checker.cac.cas
        with mock.patch.object(schema, "SCHEMA_FILE", Path("/nonexistent/service-channel-agent-extension.schema.json")), \
                mock.patch.object(schema, "_schema", None):
            probe.channel_agent_rule()
        result = probe.results[-1]
        self.assertEqual((result["rule"], result["verdict"]), ("channel-agent.declaration", "NOT_RUN"))
        self.assertIn("service-channel-agent-extension.schema.json", result["evidence"])

    def test_the_rule_reads_the_well_known_answer_with_no_manifest(self):
        declaration = valid_declaration()
        declaration["projects"].append(copy.deepcopy(declaration["projects"][0]))
        probe = self.probe({}, {"extensions": {KEY: declaration}}, ca.WELL_KNOWN_CAP + 1)
        probe.channel_agent_rule()
        result = probe.results[-1]
        self.assertEqual(result["verdict"], "NOT_RUN", "a repeated project: the reader reads it as not declared (D3)")
        self.assertIn("FAC-SEM-163 at /extensions/", result["evidence"])
        self.assertIn("over the 2 MiB cap", result["evidence"])


class LiveSampleService(unittest.TestCase):
    """FAA-250 (2): a declaration fetched through the probe's real HTTP path. The sample's code serves it in its well-known
    answer (the sample itself stays as it is), registered with no manifest, so CA-1 reads the fetched answer, and the probe
    runs as a person runs it."""

    def setUp(self):
        import contextlib
        import io
        import socket
        import threading
        sample = load("sample_service")
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.services = base / "services"
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        common = ["--port", str(port), "--data-dir", str(base / "data")]
        test = self
        self.declaration = None

        class ChannelAgentService(sample.Service):
            def well_known(self):
                wk = super().well_known()
                if test.declaration is not None:
                    wk.setdefault("extensions", {})[KEY] = test.declaration
                return wk

        self.svc = ChannelAgentService(sample.build_parser().parse_args(["serve"] + common))
        self.svc.start()
        self.server = sample.make_server(self.svc)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self.thread.start()
        with contextlib.redirect_stdout(io.StringIO()):  # register prints the descriptor's path
            registered = sample.register(sample.build_parser().parse_args(["register"] + common + ["--services-dir", str(self.services)]))
        self.assertEqual(registered, 0)
        path = self.services / "sample.default.json"
        descriptor = json.loads(path.read_text(encoding="utf-8"))
        descriptor.pop("fabricManifest", None)  # no manifest: the probe reads the declaration from the fetched answer
        path.write_text(json.dumps(descriptor), encoding="utf-8")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.svc.lock.release()
        self.temp.cleanup()

    def rule(self):
        import subprocess
        out = subprocess.run([sys.executable, "-B", str(SCRIPTS / "check_service.py"), "sample", "--services-dir",
                              str(self.services), "--json"], capture_output=True, text=True)
        return {r["rule"]: r for r in json.loads(out.stdout)["results"]}["channel-agent.declaration"]

    def test_a_declaration_in_the_well_known_answer_is_read_through_http(self):
        self.declaration = valid_declaration()
        result = self.rule()
        self.assertEqual(result["verdict"], "PASS", result["evidence"])
        self.assertIn("the well-known answer's extensions", result["evidence"])

    def test_a_declaration_with_findings_fails_through_http(self):
        self.declaration = valid_declaration()
        self.declaration["standard"] = "channel-agent-standard/0"
        result = self.rule()
        self.assertIn(result["verdict"], ("FAIL", "NOT_RUN"), result["evidence"])  # NOT_RUN when read as not declared (D3)
        self.assertIn("FAC-SEM-162", result["evidence"])
        self.assertIn("the well-known answer's extensions", result["evidence"])

    def test_no_declaration_is_not_run(self):
        result = self.rule()
        self.assertEqual(result["verdict"], "NOT_RUN", result["evidence"])
        self.assertIn("not a channel agent", result["evidence"])


if __name__ == "__main__":
    unittest.main()
