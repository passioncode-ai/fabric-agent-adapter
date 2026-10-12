"""DEC-0061 and DEC-0069 in the Python service kit (FAA-34); the twin of fabric-service-descriptors.test.mjs.

The validator is held to every service-descriptor fixture of the contract at the pin, and the ports to its vectors
(test/fixtures/contract/descriptor-fixtures.json, service-peer-vectors.json, app-descriptor-vectors.json, made by
vendor_vectors.mjs). The local channel (DEC-0075) is not a kit surface yet: its six negatives are the only fixtures the
validator does not refuse, and that set is pinned so a new one is noticed."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from test_fabric_service import load

fs = load("fabric_service")
probe = load("check_service")
HERE = Path(__file__).resolve().parent
FIX = json.loads((HERE / "fixtures/contract/descriptor-fixtures.json").read_text(encoding="utf-8"))
PEER = json.loads((HERE / "fixtures/contract/service-peer-vectors.json").read_text(encoding="utf-8"))
APP = json.loads((HERE / "fixtures/contract/app-descriptor-vectors.json").read_text(encoding="utf-8"))
LOCAL_CHANNEL = {"service-descriptor-local-channel-home", "service-descriptor-local-channel-bad-sid",
                 "service-descriptor-remote-with-channel", "service-descriptor-channels-without-local",
                 "service-descriptor-local-channel-multibyte", "service-descriptor-local-channel-both"}


def fixture(name):
    return copy.deepcopy(next(d["descriptor"] for d in FIX["descriptors"] if d["name"] == name))


class ContractFixtures(unittest.TestCase):
    def test_every_valid_descriptor_is_accepted(self):
        valid = [d for d in FIX["descriptors"] if d["valid"]]
        self.assertEqual(len(valid), 10)
        for d in valid:
            with self.subTest(d["name"]):
                self.assertEqual(fs.validate_descriptor(d["descriptor"]), [])

    def test_every_invalid_descriptor_is_refused_but_the_local_channel(self):
        accepted = {d["name"] for d in FIX["descriptors"] if not d["valid"] and not fs.validate_descriptor(d["descriptor"])}
        self.assertEqual(accepted, LOCAL_CHANNEL)

    def test_fac_sem_085_and_086_at_the_contracts_places(self):
        self.assertEqual(len(FIX["semantic"]), 3)
        for s in FIX["semantic"]:
            with self.subTest(s["name"]):
                found = [p for p in fs.validate_descriptor(s["document"]) if p.startswith("FAC-SEM-")]
                self.assertEqual(len(found), len(s["findings"]))
                for want in s["findings"]:
                    self.assertTrue(any(p.startswith(want["code"]) and (want["instancePath"] in p or want["code"] == "FAC-SEM-085") for p in found), (want, found))

    def test_reasons(self):
        reasons = {"service-descriptor-node-with-label": "label belongs to launchd", "service-descriptor-node-with-unit": "unit belongs",
                   "service-descriptor-person-with-plist": "plist belongs to launchd", "service-descriptor-person-without-app": "lifecycle.app",
                   "service-descriptor-app-beside-launchd": "lifecycle.app belongs to manager person", "service-descriptor-without-origin": "missing origin",
                   "service-descriptor-person-installed-by-string": "as a person", "service-descriptor-remote-under-node": "manager must be none",
                   "service-descriptor-peer-without-runner": "declares runner", "service-descriptor-peer-subscription": "never runs on a subscription",
                   "service-descriptor-runner-subscription-wrong-runner": "vendor's runner", "service-descriptor-installed-by-node-with-role": "a person only"}
        for name, reason in reasons.items():
            with self.subTest(name):
                self.assertIn(reason, " ".join(fs.validate_descriptor(fixture(name))))


class Ports(unittest.TestCase):
    def test_peer_refusal(self):
        self.assertEqual(len(PEER["cases"]), 22)
        for c in PEER["cases"]:
            with self.subTest(c["name"]):
                self.assertEqual(fs.peer_refusal(c["descriptor"], c["dataClass"]), c["refusal"])

    def test_residency_as_the_schema_reads_it(self):
        base = fixture("service-descriptor-peer")
        for code in PEER["residency"]["accepted"]:
            with self.subTest(accepted=code):
                base["peer"]["residency"] = [code]
                self.assertEqual(fs.validate_descriptor(base), [])
        for code in PEER["residency"]["refused"]:
            with self.subTest(refused=code):
                base["peer"]["residency"] = [code]
                self.assertIn("peer.residency", " ".join(fs.validate_descriptor(base)))

    def test_app_descriptor_action_and_stale(self):
        for c in APP["action"]:
            with self.subTest(c["name"]):
                self.assertEqual(fs.app_descriptor_action(c["existing"], c["tool"], c["appPath"]), c["expect"])
        for c in APP["stale"]:
            with self.subTest(c["name"]):
                self.assertIs(fs.app_descriptor_stale(c["descriptor"], c["appPresent"]), c["expect"])


class Readers(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.app = self.dir / "Example App.app"
        self.app.mkdir()
        self.desc = fixture("service-descriptor-person-app")
        self.desc["lifecycle"]["app"] = str(self.app)

    def test_fabric_button_presence(self):
        services = self.dir / "services"
        self.assertEqual(fs.fabric_button_presence(services), "absent", "no services directory")
        services.mkdir()
        fabric = dict(self.desc, id="fabric", instance="default")
        fs.write_descriptor(fabric, services)
        self.assertEqual(fs.fabric_button_presence(services), "present")
        self.app.rmdir()
        self.assertEqual(fs.fabric_button_presence(services), "absent", "an app's descriptor whose app is gone is stale")
        supervised = fixture("service-descriptor-node")
        supervised.update(id="fabric", instance="default")
        (services / "fabric.default.json").write_text(json.dumps(supervised))
        self.assertEqual(fs.fabric_button_presence(services), "present", "a supervised Fabric with an origin")
        (services / "fabric.default.json").write_text("{not json")
        self.assertEqual(fs.fabric_button_presence(services), "absent")
        (services / "fabric.default.json").write_text(json.dumps({"id": "fabric"}))
        self.assertEqual(fs.fabric_button_presence(services), "absent", "an invalid descriptor is no Fabric")

    def test_app_descriptors_claim_no_port_and_the_probe_reads_them_as_installed(self):
        services = self.dir / "services"
        first = fs.write_descriptor(self.desc, services)
        second = fs.write_descriptor(dict(self.desc, id="other-app"), services)
        self.assertTrue(first.exists() and second.exists(), "two apps without an origin never clash")
        results = {r["rule"]: r for r in probe.Probe(first, self.desc, services, skip_login=True).run()}
        self.assertEqual(results["descriptor.valid"]["verdict"], "PASS", results["descriptor.valid"])
        self.assertEqual(results["descriptor.port-claim"]["verdict"], "PASS")
        self.assertIn("claims no port", results["descriptor.port-claim"]["evidence"])
        self.assertEqual(results["descriptor.app-installed"]["verdict"], "PASS")
        self.assertEqual(results["well-known.answers"]["verdict"], "NOT_RUN")
        self.app.rmdir()
        results = {r["rule"]: r for r in probe.Probe(first, self.desc, services, skip_login=True).run()}
        self.assertEqual(results["descriptor.app-installed"]["verdict"], "FAIL")
        self.assertIn("stale", results["descriptor.app-installed"]["evidence"])


class Writers(unittest.TestCase):
    def test_register_remote_writes_who_installed_it_and_takes_runner_and_peer(self):
        services = Path(tempfile.mkdtemp())
        path = fs.register_remote(service_id="example-inbox", name="Example Inbox", origin="https://inbox.example.com",
                                  token="t" * 32, directory=services)
        written = json.loads(path.read_text())
        self.assertEqual(written["installedBy"], {"by": "person", "role": "operator", "tool": "fabric-service register-remote"})
        offered = fixture("service-descriptor-peer-remote")
        path = fs.register_remote(service_id="example-inbox", instance="offered", name="Example Inbox", origin="https://inbox.example.com",
                                  token="t" * 32, directory=services, runner=offered["runner"], peer=offered["peer"],
                                  installed_by={"by": "person", "role": "administrator", "tool": "example-inbox register-remote 1.0.0"})
        written = json.loads(path.read_text())
        self.assertEqual((written["runner"], written["peer"]), (offered["runner"], offered["peer"]))
        with self.assertRaises(fs.ServiceError):
            fs.register_remote(service_id="example-inbox", instance="bad", name="X", origin="https://inbox.example.com", token="t" * 32,
                               directory=services, peer=offered["peer"])  # an offer without runner

    def test_the_sample_writes_the_object_form(self):
        sample = load("sample_service")
        services = Path(tempfile.mkdtemp())
        args = sample.build_parser().parse_args(["register", "--port", "47299", "--data-dir", str(services / "data"), "--services-dir", str(services)])
        self.assertEqual(sample.register(args), 0)
        written = json.loads(next(services.glob("*.json")).read_text())
        self.assertEqual(written["installedBy"]["by"], "person")
        self.assertEqual(fs.validate_descriptor(written), [])

    def test_usage_rows_take_the_platform_metered_route(self):
        receipt = fs.make_usage_receipt("example", "example-model", input_tokens=1, output_tokens=1, route="platform-metered")
        self.assertEqual(receipt["route"], "platform-metered")
        with self.assertRaises(fs.ServiceError):
            fs.make_usage_receipt("example", "example-model", input_tokens=1, output_tokens=1, route="metered")
        self.assertNotIn("platform-metered", fs.ROUTES, "a configuration's route stays subscription or key")


if __name__ == "__main__":
    unittest.main()
