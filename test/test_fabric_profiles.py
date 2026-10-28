"""Runner and model profiles in the kit (contract DEC-0046, FAA-19) and the credential detector (DEC-0044), against
vectors whose expected answers come from the contract's own functions at the pin
(test/fixtures/contract/make_profile_vectors.mjs)."""
import base64
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

from test_fabric_service import load

fs = load("fabric_service")
secrets_mod = load("fabric_secrets")
profiles = load("fabric_profiles")
check = load("check_service")
VECTORS = json.loads((Path(__file__).resolve().parent / "fixtures/contract/profile-vectors.json").read_text())


def decode(text):
    return bytes.fromhex(text).decode("utf-8")


class SecretShapeTests(unittest.TestCase):
    def test_every_case_answers_as_the_contract_does(self):
        for name, cases in VECTORS["secrets"].items():
            fn = {"credentialName": secrets_mod.credential_name, "nameWords": secrets_mod.name_words, "secretValue": secrets_mod.secret_value,
                  "secretArgument": secrets_mod.secret_argument, "secretUrl": secrets_mod.secret_url}[name]
            for case in cases:
                value = decode(case["inputHex"])
                with self.subTest(name, value=value[:30]):
                    self.assertEqual(fn(value), case["expected"])
        self.assertGreaterEqual(sum(len(c) for c in VECTORS["secrets"].values()), 120)

    def test_whitespace_dot_and_case_read_as_ecmascript(self):
        """FAA-136: the answers of the contract's src/secret-shape.ts at the pin (00e050b, run under Node 24) where
        Python's own \\s, `.` and case folding differ; both copies of the module answer them."""
        import importlib.util
        copy = Path(__file__).resolve().parent.parent / "plugins/fabric-agent-adapter/skills/adapting-projects-to-fabric/scripts/fabric_secrets.py"
        spec = importlib.util.spec_from_file_location("fabric_secrets_adapting_copy", copy)
        adapting = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapting)
        cases = (("credential_name", "api\x85key", False), ("credential_name", "api\ufeffkey", True),
                 ("credential_name", "api\u2028key", True), ("credential_name", "api\x1ckey", False),
                 ("secret_value", "bearer\ufeffabc", True), ("secret_value", "bearer\x85abc", False),
                 ("secret_value", "bearer \u2028x", False), ("secret_value", "\u017fk-" + "a" * 20, False),
                 ("secret_value", "SK-" + "a" * 20, True), ("secret_value", "Bearer\xa0abc", True),
                 ("secret_argument", "--h=Authorization: Bearer\ufeffabc123456789012", True),
                 ("secret_argument", "--h=Authorization: Bearer\x85abc123456789012", False),
                 ("secret_argument", "x\u3000" + "aB1" * 14, True),
                 # 0.56.0 unit r1: URL parsing trims only U+0000 to U+0020 from the ends, as `new URL` does.
                 ("secret_url", "\xa0https://u:p@x.example/", False), ("secret_url", "\x01https://u:p@x.example/", True),
                 ("secret_url", " https://u:p@x.example/", True), ("secret_url", "\u3000https://x.example/?token=abc", False),
                 ("secret_url", "ht\ttps://h.example/?token=abc", True),  # unit r3: tabs, CR and LF removed as by `new URL`
                 # unit r6: a special scheme's slashes and backslashes after `scheme:` are skipped, as by `new URL`
                 ("secret_url", "https:\\\\u:hunter2@host/", True), ("secret_url", "https:u:hunter2@host/", True),
                 ("secret_url", "https:/u:hunter2@host/", True), ("secret_url", "HTTPS:\\\\u:hunter2@host", True),
                 ("secret_url", "ftp:u:hunter2@host/", True), ("secret_url", "https:///host/?q=\\x", False),
                 ("secret_url", "mailto:u:hunter2@host", False),
                 # unit r7: a `[` or `]` outside an IPv6 host, and one leading `?` before a parameter's name, as `new URL`
                 ("secret_url", "https://user:p[w@h.example/", True), ("secret_url", "https://u[:p@h/?token=abc", True),
                 ("secret_url", "wss:]]:@p?token=abc", True), ("secret_url", "https://h.example/#?token=abc", True),
                 ("secret_url", "https://h.example/??token=abc", True), ("secret_url", "https://[::1]:8080/x", False),
                 ("secret_url", "https://u:@h.example/", False), ("secret_url", "file://u:p@h/x", False),
                 # unit r8: the query and fragment are read percent-encoded, as `new URL` hands them over
                 ("secret_url", 'https://h.example/?x=%zz"' + ("A1b" * 13)[:38], True),
                 ("secret_url", "https://h.example/?x=%zz\u00e9" + ("A1b" * 13)[:38], True),
                 ("secret_url", "https://h.example/#x=%zz<" + ("A1b" * 13)[:38], True),
                 ("secret_url", "https://h.example/?x=%zz\x1aKIA0123456789ABCDEF", True),
                 ("secret_url", "https://h.example/?q=caf\u00e9", False),
                 # unit r9: file is a special scheme too, so its query encodes `'`
                 ("secret_url", "file:///x?x=%zz'" + ("A1b" * 13)[:38], True),
                 ("secret_url", "FILE://h/x?x=%zz'" + ("A1b" * 13)[:38], True))
        for module in (secrets_mod, adapting):
            for name, value, expected in cases:
                with self.subTest(name, value=ascii(value)[:30], module=module.__name__):
                    self.assertEqual(getattr(module, name)(value), expected)


class ResolutionTests(unittest.TestCase):
    def test_every_resolution_answers_as_the_contract_does(self):
        for case in VECTORS["resolutions"]:
            with self.subTest(case["name"]):
                self.assertEqual(profiles.resolve_model_profile(**case["input"]), case["expected"])

    def test_the_order_is_request_agent_binding_estate(self):
        self.assertEqual(profiles.RESOLUTION_ORDER, ("request", "agent", "binding", "estate"))


class RuleTests(unittest.TestCase):
    def test_every_rule_case_answers_as_the_contract_does(self):
        for case in VECTORS["rules"]:
            value = json.loads(decode(case["valueHex"]))
            with self.subTest(case["name"]):
                self.assertEqual(profiles.profile_problems(case["kind"], value), case["expected"])

    def test_an_unknown_kind_is_none(self):
        self.assertIsNone(profiles.profile_problems("something-else", {}))


class RunnerCheckTests(unittest.TestCase):
    """runners.md C2: only a catalogued bare binary on PATH, only its version argv, no shell, at most 5 s; `auth`
    exit 0 means signed in."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bin = Path(self.temp.name)
        self.asked = []

    def tearDown(self):
        self.temp.cleanup()

    def tool(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def unbounded(self, argv, **kw):
        """The probe's own run, recorded, with room to answer on a loaded host: the deadline it asks for is checked
        here, and the deadline itself by the slow cases below, which use a real one (FAA-108)."""
        self.asked.append(kw.get("timeout"))
        return subprocess.run(argv, **dict(kw, timeout=120))

    def entry(self, **extra):
        e = {"kind": "example-code", "name": "Example Code", "binaries": ["example-code"],
             "version": {"argv": ["--version"], "pattern": "^example (\\d+\\.\\d+\\.\\d+)", "timeoutMs": profiles.MAX_PROBE_MS}}  # the most a probe may take: a loaded host starts even a shell slowly
        e.update(extra)
        return e

    @unittest.skipIf(sys.platform == "win32", "a shell script stands in for the runner")
    def test_installed_measured_and_signed_in(self):
        self.tool("example-code", 'if [ "$1" = "--version" ]; then echo "example 1.4.2"; exit 0; fi; if [ "$1" = "auth" ]; then exit 0; fi; exit 3')
        got = profiles.runner_check(self.entry(auth=["auth", "status"]), path=str(self.bin), run=self.unbounded)
        self.assertEqual((got["installed"], got["version"], got["signedIn"], got["problems"]), (True, "1.4.2", True, []))
        self.assertEqual(self.asked, [profiles.MAX_PROBE_MS / 1000.0] * 2, "both probes ask for the catalogued bound")
        self.assertIsNone(got["probe"], "it can serve")
        self.assertTrue(got["binary"].endswith("example-code"))

    @unittest.skipIf(sys.platform == "win32", "a shell script stands in for the runner")
    def test_not_signed_in_and_unreadable_version(self):
        self.tool("example-code", 'if [ "$1" = "--version" ]; then echo "something else"; exit 0; fi; exit 1')
        got = profiles.runner_check(self.entry(auth=["auth", "status"]), path=str(self.bin), run=self.unbounded)
        self.assertEqual((got["installed"], got["version"], got["signedIn"]), (True, None, False))
        self.assertTrue(any("version" in p for p in got["problems"]))
        self.assertEqual(got["probe"], "not-responding", "the walk's order: responding before connected")

    @unittest.skipIf(sys.platform == "win32", "a shell script stands in for the runner")
    def test_the_closed_probe_results(self):
        self.assertEqual(profiles.runner_check(self.entry(), path=str(self.bin))["probe"], "not-installed")
        self.tool("example-code", 'if [ "$1" = "--version" ]; then echo "example 1.4.2"; exit 0; fi; exit 1')
        self.assertEqual(profiles.runner_check(self.entry(auth=["auth", "status"]), path=str(self.bin), run=self.unbounded)["probe"], "not-connected")
        self.assertIsNone(profiles.runner_check(self.entry(), path=str(self.bin), run=self.unbounded)["probe"], "no auth probe: answering is enough")
        self.tool("example-code", 'if [ "$1" = "--version" ]; then echo "example 1.4.2"; exit 0; fi; sleep 5')
        got = profiles.runner_check(self.entry(auth=["auth", "status"], version={"argv": ["--version"], "pattern": "^example (\\d+\\.\\d+\\.\\d+)", "timeoutMs": 300}),
                                    path=str(self.bin))
        self.assertEqual(got["probe"], "not-responding", "an auth probe that does not answer in its bound")
        for result in ("not-installed", "not-responding", "not-connected"):
            self.assertIn(result, profiles.PROBE_RESULTS)


    @unittest.skipIf(sys.platform == "win32", "a shell script stands in for the runner")
    def test_a_slow_version_answer_is_bounded(self):
        self.tool("example-code", "sleep 5; echo 'example 1.0.0'")
        got = profiles.runner_check(self.entry(version={"argv": ["--version"], "pattern": "(\\d+\\.\\d+\\.\\d+)", "timeoutMs": 300}), path=str(self.bin))
        self.assertIsNone(got["version"])
        self.assertTrue(any("did not answer" in p for p in got["problems"]))

    def test_not_installed(self):
        got = profiles.runner_check(self.entry(), path=str(self.bin))
        self.assertEqual((got["installed"], got["binary"], got["version"]), (False, None, None))

    def test_an_entry_outside_the_catalogue_rules_is_never_run(self):
        for bad in (self.entry(binaries=["/bin/sh"]), self.entry(binaries=["../x"]), self.entry(version={"argv": "--version", "pattern": "(x)"}),
                    self.entry(version={"argv": ["--version"], "pattern": "(x)", "timeoutMs": 60000}), self.entry(auth="status")):
            with self.subTest(bad=bad), self.assertRaises(profiles.ProfileError):
                profiles.runner_check(bad, path=str(self.bin))


class ModelUsableTests(unittest.TestCase):
    def setUp(self):
        base = next(c for c in VECTORS["resolutions"] if c["name"] == "profile-resolution-ok.json")["input"]
        self.catalogue = base["catalogue"]
        self.model = self.catalogue["models"][0]["id"]

    def test_catalogued_and_within_classes(self):
        self.assertEqual(profiles.model_usable(self.model, self.catalogue), [])
        classes = self.catalogue["models"][0]["classes"]
        self.assertEqual(profiles.model_usable(self.model, self.catalogue, {"meta": {"id": "p", "revision": 1}, "modelClasses": classes}), [])
        problems = profiles.model_usable(self.model, self.catalogue, {"meta": {"id": "p", "revision": 1}, "modelClasses": ["frontier"]})
        self.assertTrue(problems and "p" in problems[0])
        self.assertTrue(profiles.model_usable("example/none", self.catalogue))

    def test_open_vendor_is_descriptive_in_the_doctor_too(self):
        """DEC-0083: the doctor admits as the resolution does — open-vendor is never checked against the policy, and a
        model whose only class is open-vendor is admitted on nothing."""
        catalogue = {"models": [{"id": "example/open", "classes": ["cheap", "open-vendor"]},
                                {"id": "example/bare", "classes": ["open-vendor"]}]}
        policy = {"meta": {"id": "p", "revision": 1}, "modelClasses": ["cheap"]}
        self.assertEqual(profiles.model_usable("example/open", catalogue, policy), [])
        self.assertEqual(profiles.model_usable("example/bare", catalogue, policy),
                         ["model example/bare has no class but open-vendor, which admits nothing, so policy p does not allow it"])
        self.assertEqual(profiles.model_usable("example/bare", catalogue, dict(policy, modelClasses=["open-vendor"])),
                         ["model example/bare has no class but open-vendor, which admits nothing, so policy p does not allow it"])
        self.assertEqual(profiles.model_usable("example/bare", catalogue), [], "no policy: nothing to admit against")
        for model in ("example/open", "example/bare"):
            resolution = profiles.resolve_model_profile(catalogue=catalogue, profiles=[{"id": "x", "models": [model]}],
                                                        choices={"estate": "x"}, policy=policy)
            self.assertEqual("models" in resolution, profiles.model_usable(model, catalogue, policy) == [], model)


class AdmissionVectorTests(unittest.TestCase):
    """DEC-0083's shared vectors (contract fixtures/vectors/model-admission.json): the resolver and the doctor are the
    kit's two copies of the every-class rule, and both answer every case as the contract's admittedByClasses does."""

    def test_the_resolver_and_the_doctor_admit_as_the_contract_does(self):
        self.assertGreaterEqual(len(VECTORS["admission"]), 8)
        for case in VECTORS["admission"]:
            with self.subTest(case["name"]):
                rows = [] if case["classes"] is None else [{"id": "example/model", "classes": case["classes"]}]
                catalogue = {"models": rows}
                policy = {"meta": {"id": "p", "revision": 1}, "modelClasses": case["modelClasses"]}
                resolved = profiles.resolve_model_profile(catalogue=catalogue, profiles=[{"id": "x", "models": ["example/model"]}],
                                                          choices={"estate": "x"}, policy=policy)
                self.assertEqual("models" in resolved, case["admitted"], "resolver")
                self.assertEqual(profiles.model_usable("example/model", catalogue, policy) == [], case["admitted"], "doctor")


class DoctorOnHostileInputTests(unittest.TestCase):
    """The doctor's model_usable never raises: an id that is an object, a model that is not a string, a policy id whose
    own toString is data or that is null — each answers as the contract's show writes it."""

    def test_hostile_catalogue_and_policy(self):
        catalogue = {"models": [{"id": {"toString": 1}, "classes": ["cheap"]}, {"id": ["x"], "classes": ["cheap"]},
                                {"id": "example/m", "classes": ["strong"]}]}
        self.assertEqual(profiles.model_usable("example/m", catalogue), [])
        self.assertEqual(profiles.model_usable({"toString": 1}, catalogue), ['model {"toString":1} is not in the model catalogue'])
        self.assertEqual(profiles.model_usable(None, catalogue), ["model null is not in the model catalogue"])
        self.assertEqual(profiles.model_usable({"toString": 1, "a": "\ud800"}, catalogue), ['model {"toString":1,"a":"\\ud800"} is not in the model catalogue'])
        self.assertEqual(profiles.model_usable({"toString": 1, "b": 0, "2": 0}, catalogue), ['model {"2":0,"toString":1,"b":0} is not in the model catalogue'])
        for meta, shown in (({"id": {"toString": 1}}, '{"toString":1}'), ({"id": None}, "null"), ({}, "undefined"), ({"id": 7}, "7"),
                            ({"id": {"toString": 1, "a": "\udc00"}}, '{"toString":1,"a":"\\udc00"}'), ({"id": 9007199254740993}, "9007199254740992")):
            self.assertEqual(profiles.model_usable("example/m", catalogue, {"meta": meta, "modelClasses": ["cheap"]}),
                             ["model example/m has class strong, which policy %s does not allow" % shown])


class DuplicateKeyTests(unittest.TestCase):
    """FAC-SEM-058/060 count duplicates as JavaScript's Set does. JSON written by JavaScript never says 1.0, so the vectors
    cannot hold this case; a Python caller can pass one, and 1 and 1.0 are one number."""

    def test_an_integer_and_a_float_of_one_value_are_one_id(self):
        catalogue = {"models": [{"id": 1, "classes": ["cheap"]}, {"id": 1.0, "classes": ["cheap"]}, {"id": True, "classes": ["cheap"]}]}
        found = profiles.profile_problems("model-catalogue", catalogue)
        self.assertEqual([f["instancePath"] for f in found], ["/models/1/id"])
        self.assertEqual(found[0]["message"], "model 1 is catalogued more than once")


class ConfigurationTests(unittest.TestCase):
    """The well-known `configuration` (DEC-0046) and its summary tiles, the dashboard's "Runner & model"."""

    def test_built_from_a_resolution_and_a_runner_profile(self):
        resolution = {"from": "binding", "profile": "default", "models": ["deepseek/deepseek-v4-pro"]}
        runner = {"kind": "runner-profile", "id": "claude-sub", "runnerKind": "claude-code", "route": "subscription", "modelProfile": "default"}
        conf = profiles.configuration(["runner", "model"], resolution, runner)
        self.assertEqual(conf, {"slots": ["runner", "model"], "resolved": {"from": "binding", "runnerProfile": "claude-sub", "runnerKind": "claude-code",
                                                                            "route": "subscription", "modelProfile": "default", "models": ["deepseek/deepseek-v4-pro"]}})
        self.assertEqual(profiles.configuration_summary(conf), [
            {"label": "Runner", "value": "claude-code · subscription"},
            {"label": "Model", "value": "default · deepseek/deepseek-v4-pro"},
        ])

    def test_a_refused_resolution_or_a_bad_slot_is_refused(self):
        for bad in ({"refused": "no-profile"}, {"from": "nowhere", "profile": "default", "models": []}):
            with self.subTest(bad=bad), self.assertRaises(profiles.ProfileError):
                profiles.configuration(["model"], bad)
        with self.assertRaises(profiles.ProfileError):
            profiles.configuration(["runner", "model", "runner"], {"from": "agent", "profile": "default", "models": []})
        with self.assertRaises(profiles.ProfileError):
            profiles.configuration(["model"], {"from": "agent", "profile": "Bad Id", "models": []})
        with self.assertRaises(profiles.ProfileError):
            profiles.configuration(["model"], {"from": "agent", "profile": "default", "models": ["x/y"] * 17})

    def test_build_well_known_carries_it_and_checks_it(self):
        base = dict(service_id="example-agent", instance="default", name="Example", version="1.0.0", build={"commit": "abc1234"},
                    started_at=fs.now_iso(), status="ready", degraded=[], surfaces={"events": {"path": "/fabric/v1/events"}})
        conf = {"slots": ["model"], "resolved": {"from": "estate", "modelProfile": "default", "models": ["deepseek/deepseek-v4-pro"]}}
        self.assertEqual(fs.build_well_known(**base, configuration=conf)["configuration"], conf)
        self.assertNotIn("configuration", fs.build_well_known(**base))
        with self.assertRaises(fs.ServiceError):
            fs.build_well_known(**base, configuration={"slots": ["model"], "resolved": {"from": "estate", "extra": 1}})


class UsageRouteTests(unittest.TestCase):
    def test_a_receipt_carries_its_route_and_the_report_keeps_routes_apart(self):
        a = fs.make_usage_receipt("openrouter", "deepseek/deepseek-v4-pro", input_tokens=10, output_tokens=5, cost_usd=0.01, route="key")
        b = fs.make_usage_receipt("anthropic", "claude", input_tokens=1, output_tokens=1, route="subscription")
        c = fs.make_usage_receipt("openrouter", "deepseek/deepseek-v4-pro", input_tokens=1, output_tokens=1, cost_usd=0.0)
        self.assertEqual((a["route"], b["route"]), ("key", "subscription"))
        self.assertNotIn("route", c)
        with self.assertRaises(fs.ServiceError):
            fs.make_usage_receipt("openrouter", "m", input_tokens=1, output_tokens=1, route="borrowed")
        rows = fs.usage_report([a, b, c], service_id="example-agent")["days"][0]["byModel"]
        self.assertEqual([(r["provider"], r["model"], r.get("route")) for r in rows],
                         [("anthropic", "claude", "subscription"), ("openrouter", "deepseek/deepseek-v4-pro", None), ("openrouter", "deepseek/deepseek-v4-pro", "key")])


class ProbeConfigurationTests(unittest.TestCase):
    def rule(self, wk):
        p = check.Probe.__new__(check.Probe)
        p.results, p.wk = [], wk
        p.configuration_rule()
        return p.results[0]

    def test_verdicts(self):
        good = {"configuration": {"slots": ["runner"], "resolved": {"from": "agent", "runnerKind": "claude-code", "route": "subscription"}}}
        self.assertEqual(self.rule(good)["verdict"], "PASS")
        self.assertEqual(self.rule({})["verdict"], "NOT_RUN")
        self.assertEqual(self.rule({"configuration": {"slots": ["model"], "resolved": {"models": ["Not A Model"]}}})["verdict"], "FAIL")
        self.assertEqual(self.rule({"configuration": "x"})["verdict"], "FAIL")


class RouteRules(unittest.TestCase):
    """FAC-SEM-028…034: the cases in route-vectors.json were answered by the contract's own routeRules at the pin."""

    def test_every_case_answers_as_the_contract_does(self):
        cases = json.loads((Path(__file__).resolve().parent / "fixtures/contract/route-vectors.json").read_text())["cases"]
        self.assertGreaterEqual(len(cases), 40)
        for case in cases:
            with self.subTest(case["name"]):
                # A raw case keeps its JSON text: a big integer or a key order a JavaScript object cannot carry.
                value = json.loads(case["valueText"]) if "valueText" in case else case["value"]
                self.assertEqual(profiles.route_problems(case["kind"], value), case.get("expected"))
        codes = {f["code"] for c in cases for f in (c.get("expected") or [])}
        self.assertEqual(codes, {"FAC-SEM-028", "FAC-SEM-029", "FAC-SEM-030", "FAC-SEM-032", "FAC-SEM-033", "FAC-SEM-034"})
        self.assertIsNone(profiles.route_problems("something-else", {}))
        for kind in ("constructor", "__proto__", "toString", "hasOwnProperty"):
            self.assertIsNone(profiles.route_problems(kind, {}), kind)
            self.assertIsNone(profiles.profile_problems(kind, {}), kind)


if __name__ == "__main__":
    unittest.main()
