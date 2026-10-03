"""DEC-0019 — the remote placement in the Python kit; the twin of fabric-service-remote.test.mjs."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(module)
    return module


fs = load("fabric_service")


def remote(**over):
    d = {"protocol": fs.PROTOCOL, "id": "example-agent", "instance": "default", "name": "Example Agent",
         "placement": "remote", "origin": "https://agent.example.com", "auth": {"tokenFile": "/tmp/x/t.token"},
         "lifecycle": {"manager": "none"}, "installedAt": fs.now_iso(), "installedBy": "test"}
    d.update(over)
    return d


class RemotePlacement(unittest.TestCase):
    def test_remote_validates_without_paths_local_still_needs_them(self):
        self.assertEqual(fs.validate_descriptor(remote()), [])
        local = remote(origin="http://127.0.0.1:47300")
        del local["placement"]
        self.assertIn("missing paths", fs.validate_descriptor(local))

    def test_remote_origin_shape(self):
        for origin in ("http://agent.example.com", "https://203.0.113.7", "https://agent.example.com/x", "http://127.0.0.1:47300"):
            self.assertTrue(fs.validate_descriptor(remote(origin=origin)), origin)
        for origin in ("https://agent.localhost", "https://box.local", "https://api.internal"):
            self.assertIn("reserved name", " ".join(fs.validate_descriptor(remote(origin=origin))))
        self.assertEqual(fs.validate_descriptor(remote(origin="https://agent.example.com:8443")), [])

    def test_no_launchd_no_update(self):
        self.assertTrue(fs.validate_descriptor(remote(lifecycle={"manager": "launchd", "label": "a.b.c", "plist": "/x.plist"})))
        self.assertTrue(fs.validate_descriptor(remote(lifecycle={"manager": "none", "label": "a.b.c"})))
        self.assertTrue(fs.validate_descriptor(remote(commands={"update": ["/usr/bin/true"]})))
        self.assertEqual(fs.validate_descriptor(remote(commands={"doctor": ["/usr/bin/true"]})), [])

    def test_guard(self):
        o = "https://agent.example.com"
        self.assertIsNone(fs.check_remote_request(o, "agent.example.com"))
        self.assertIsNone(fs.check_remote_request(o, "agent.example.com", forwarded_proto="https"))
        self.assertIn("Host", fs.check_remote_request(o, "evil.example.com"))
        self.assertIn("https only", fs.check_remote_request(o, "agent.example.com", forwarded_proto="http"))
        self.assertIn("Origin", fs.check_remote_request(o, "agent.example.com", request_origin="https://evil.example.com"))
        self.assertIn("Cross-site", fs.check_remote_request(o, "agent.example.com", sec_fetch_site="cross-site"))

    def test_well_known_behind_token(self):
        token = "x" * 32
        self.assertTrue(fs.well_known_allowed("local", None, token))
        self.assertFalse(fs.well_known_allowed("remote", None, token))
        self.assertTrue(fs.well_known_allowed("remote", "Bearer " + token, token))

    def test_memory_codes_with_platform_key(self):
        key = bytes(32)
        a = fs.LoginCodes(None, store=fs.MemoryCodeStore(), key=key)
        code = a.issue()["url"].split("=", 1)[1]
        session = a.redeem(code)
        self.assertTrue(session and a.session_valid(session))
        self.assertIsNone(a.redeem(code))
        b = fs.LoginCodes(None, store=fs.MemoryCodeStore(), key=key)
        self.assertTrue(b.session_valid(session))
        self.assertIsNone(b.redeem(a.issue()["url"].split("=", 1)[1]))
        with self.assertRaises(fs.ServiceError):
            fs.LoginCodes(None)

    def test_cookie(self):
        h = fs.remote_session_cookie_header("v")
        self.assertTrue(h.startswith("__Host-fabric_session=v; "))
        for part in ("Path=/", "Secure", "HttpOnly", "SameSite=Strict"):
            self.assertIn(part, h)
        self.assertNotIn("Domain", h)

    def test_register_remote(self):
        root = Path(tempfile.mkdtemp()) / "services"
        local = {"protocol": fs.PROTOCOL, "id": "maker", "instance": "default", "name": "Maker", "origin": "http://127.0.0.1:8443",
                 "auth": {"tokenFile": "/tmp/m.token"}, "lifecycle": {"manager": "none"}, "paths": {"data": "/tmp/m", "logs": []},
                 "installedAt": fs.now_iso(), "installedBy": "test"}
        fs.write_descriptor(local, root)
        path = fs.register_remote(service_id="example-agent", name="Example Agent", origin="https://agent.example.com:8443",
                                  token="t" * 40, directory=root)
        d = json.loads(path.read_text())
        self.assertEqual(d["placement"], "remote")
        self.assertEqual(Path(d["auth"]["tokenFile"]).stat().st_mode & 0o777, 0o600)
        with self.assertRaises(fs.ServiceError):
            fs.register_remote(service_id="other", name="O", origin="https://o.example.com", token="short", directory=root)


if __name__ == "__main__":
    unittest.main()


import os  # noqa: E402
import random  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

probe = load("check_service")


@unittest.skipUnless(shutil.which("openssl") and shutil.which("node"), "needs openssl and node")
class GuardVerdict(unittest.TestCase):
    """A platform router answers a foreign Host before the service does (DEC-0019 behind a PaaS)."""

    def test_the_service_refusing_is_a_pass_everywhere(self):
        for rule in ("network.host-check", "network.origin-check", "network.cross-site-check"):
            for remote_placement in (True, False):
                self.assertEqual(probe.guard_verdict(rule, remote_placement, 403, b"")[0], "PASS")

    def test_a_router_refusing_a_foreign_host_is_a_pass_for_a_remote_placement_only(self):
        verdict, evidence = probe.guard_verdict("network.host-check", True, 404, b"no such app")
        self.assertEqual(verdict, "PASS")
        self.assertIn("platform router", evidence)
        self.assertEqual(probe.guard_verdict("network.host-check", True, 421, b"")[0], "PASS")
        self.assertEqual(probe.guard_verdict("network.host-check", False, 404, b"")[0], "FAIL", "loopback has no router")

    def test_the_other_guards_reach_the_service_and_need_its_403(self):
        self.assertEqual(probe.guard_verdict("network.origin-check", True, 404, b"")[0], "FAIL")
        self.assertEqual(probe.guard_verdict("network.cross-site-check", True, 421, b"")[0], "FAIL")

    def test_an_answer_that_discloses_the_document_never_passes(self):
        doc = json.dumps({"protocol": "fabric-service/0.1"}).encode()
        verdict, evidence = probe.guard_verdict("network.host-check", True, 404, doc)
        self.assertEqual(verdict, "FAIL")
        self.assertIn("well-known document", evidence)
        self.assertEqual(probe.guard_verdict("network.host-check", True, 200, doc)[0], "FAIL")
        self.assertEqual(probe.guard_verdict("network.host-check", True, 401, b"")[0], "FAIL")


class ProbeAgainstTheTlsSample(unittest.TestCase):
    """The probe against the shipped online sample, over real TLS — the way a host meets it."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.cert, self.key = self.dir / "cert.pem", self.dir / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=agent.example.com",
                        "-addext", "subjectAltName=DNS:agent.example.com", "-keyout", str(self.key), "-out", str(self.cert)],
                       check=True, capture_output=True)
        self.port = random.randint(48500, 49500)
        self.origin = "https://agent.example.com:%d" % self.port
        token = "p" * 40
        (self.dir / "token").write_text(token)
        os.chmod(self.dir / "token", 0o600)
        (self.dir / "session.key").write_bytes(bytes(32))
        self.services = self.dir / "services"
        fs.register_remote(service_id="example-agent", name="Example Agent", origin=self.origin, token=token, directory=self.services)
        self.child = subprocess.Popen(["node", str(SCRIPTS / "sample-remote-service.mjs"), "--origin", self.origin, "--port", str(self.port),
                                       "--token-file", str(self.dir / "token"), "--session-key-file", str(self.dir / "session.key"),
                                       "--tls-cert", str(self.cert), "--tls-key", str(self.key)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        deadline = time.time() + 5
        line = b""
        while time.time() < deadline and b"example agent on" not in line:
            line = self.child.stdout.readline()
        self.assertIn(b"example agent on", line)

    def tearDown(self):
        self.child.terminate()
        self.child.wait(timeout=5)
        self.child.stdout.close()

    def run_probe(self):
        import io
        import contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = probe.main(["example-agent", "--services-dir", str(self.services), "--json", "--ca-file", str(self.cert),
                             "--connect", "127.0.0.1:%d" % self.port])
        return rc, {r["rule"]: r for r in json.loads(out.getvalue())["results"]}

    def test_the_sample_passes_the_remote_rules(self):
        rc, results = self.run_probe()
        failed = {k: v["evidence"] for k, v in results.items() if v["verdict"] == "FAIL"}
        self.assertEqual(failed, {})
        self.assertEqual(rc, 0)
        for rule in ("well-known.requires-token", "well-known.identity", "network.host-check", "network.cross-site-check",
                     "events.requires-token", "login.single-use", "login.cookie-host-bound"):
            self.assertEqual(results[rule]["verdict"], "PASS", rule)
        self.assertEqual(results["lifecycle.platform"]["verdict"], "NOT_RUN")
        self.assertEqual(results["network.loopback-only"]["verdict"], "NOT_RUN")

    def test_an_untrusted_certificate_is_a_fail_not_a_pass(self):
        import io
        import contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = probe.main(["example-agent", "--services-dir", str(self.services), "--json", "--connect", "127.0.0.1:%d" % self.port])
        results = {r["rule"]: r for r in json.loads(out.getvalue())["results"]}
        self.assertEqual(rc, 1)
        self.assertEqual(results["well-known.answers"]["verdict"], "FAIL")
