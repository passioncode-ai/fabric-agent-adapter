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
        # DEC-0039: the server keeps each session's record, so a deploy that forgets the memory store
        # ends the sessions (the host signs in again on the page's 401); a durable store keeps them.
        b = fs.LoginCodes(None, store=fs.MemoryCodeStore(), key=key)
        self.assertFalse(b.session_valid(session))
        self.assertIsNone(b.redeem(a.issue()["url"].split("=", 1)[1]))
        durable = fs.MemoryCodeStore()
        c = fs.LoginCodes(None, store=durable, key=key)
        kept = c.redeem(c.issue()["url"].split("=", 1)[1])
        self.assertTrue(fs.LoginCodes(None, store=durable, key=key).session_valid(kept))
        with self.assertRaises(fs.ServiceError):
            fs.LoginCodes(None)

    def test_cookie(self):
        h = fs.remote_session_cookie_header("v")
        self.assertTrue(h.startswith("__Host-fabric_session=v; "))
        for part in ("Path=/", "Secure", "HttpOnly", "SameSite=Strict"):
            self.assertIn(part, h)
        self.assertNotIn("Domain", h)

    def test_register_remote(self):
        temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp, True)
        root = temp / "services"
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
import socket  # noqa: E402
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

    def test_a_403_that_carries_the_document_does_not_pass(self):
        doc = json.dumps({"error": "forbidden", "service": {"id": "example-agent", "instance": "main"}}).encode()
        for rule in ("network.host-check", "network.origin-check", "network.cross-site-check"):
            verdict, evidence = probe.guard_verdict(rule, True, 403, doc)
            self.assertEqual(verdict, "FAIL", rule)
            self.assertIn("well-known document", evidence)
        refusal = json.dumps({"error": {"code": "forbidden-host", "service": "example-agent"}}).encode()
        self.assertEqual(probe.guard_verdict("network.host-check", True, 403, refusal)[0], "PASS", "a refusal naming its service")


def free_port() -> int:
    """A port the system says is free on 127.0.0.1 now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ProbeAgainstTheTlsSample(unittest.TestCase):
    """The probe against the shipped online sample, over real TLS — the way a host meets it."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.cert, self.key = self.dir / "cert.pem", self.dir / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=agent.example.com",
                        "-addext", "subjectAltName=DNS:agent.example.com", "-keyout", str(self.key), "-out", str(self.cert)],
                       check=True, capture_output=True)
        token = "p" * 40
        (self.dir / "token").write_text(token)
        os.chmod(self.dir / "token", 0o600)
        (self.dir / "session.key").write_bytes(bytes(32))
        # FAA-46: a port the system says is free, not a random one from a fixed range a parallel test may hold; a bind
        # that still loses the race (EADDRINUSE) is retried on a new port, never reported as the sample's failure.
        for _attempt in range(3):
            self.port = free_port()
            self.origin = "https://agent.example.com:%d" % self.port
            self.child = subprocess.Popen(["node", str(SCRIPTS / "sample-remote-service.mjs"), "--origin", self.origin, "--port", str(self.port),
                                           "--token-file", str(self.dir / "token"), "--session-key-file", str(self.dir / "session.key"),
                                           "--tls-cert", str(self.cert), "--tls-key", str(self.key)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            deadline = time.time() + 5
            seen = b""
            while time.time() < deadline and b"example agent on" not in seen and b"EADDRINUSE" not in seen:
                line = self.child.stdout.readline()
                if not line:
                    break
                seen += line
            if b"EADDRINUSE" not in seen:
                break
            self.child.terminate()
            self.child.wait(timeout=5)
            self.child.stdout.close()
        self.assertIn(b"example agent on", seen)
        self.services = self.dir / "services"
        fs.register_remote(service_id="example-agent", name="Example Agent", origin=self.origin, token=token, directory=self.services)

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


class NoTokenVerdict(unittest.TestCase):
    """DEC-0109, CT-114: a remote service's no-token 401 carries none of its data; an identity proxy's page may answer it."""

    ids = ["example-agent", "example-agent.default", "0123456789abcdef0123456789abcdef01234567", "48213"]

    def test_an_empty_401_passes_and_another_status_fails(self):
        self.assertEqual(probe.no_token_verdict(401, b"", self.ids)[0], "PASS")
        for status in (200, 302, 403, 404):
            self.assertEqual(probe.no_token_verdict(status, b"", self.ids)[0], "FAIL", status)

    def test_an_identity_proxys_page_passes(self):
        page = b"<html><title>Sign in</title><p>Access to example-agent.example.workers.dev requires sign-in. Ray ID 9a1b2c</p></html>"
        verdict, evidence = probe.no_token_verdict(401, page, self.ids, "example-agent.example.workers.dev")
        self.assertEqual(verdict, "PASS", evidence)
        self.assertEqual(probe.no_token_verdict(401, b'{"error":"unauthorized"}', self.ids)[0], "PASS")

    def test_the_document_or_an_identity_value_in_the_body_fails(self):
        doc = json.dumps({"protocol": "fabric-service/0.1", "status": "ready"}).encode()
        self.assertEqual(probe.no_token_verdict(401, doc, self.ids)[0], "FAIL")
        self.assertEqual(probe.no_token_verdict(401, b'{"service": {"id": "x"}}', self.ids)[0], "FAIL")
        for named in (b"<p>example-agent is down</p>", b"build 0123456789abcdef0123456789abcdef01234567", b"pid 48213 ready",
                      b"instance example-agent.default"):
            self.assertEqual(probe.no_token_verdict(401, named, self.ids, "example-agent.example.workers.dev")[0], "FAIL", named)

    def test_a_value_inside_another_word_is_not_a_name(self):
        self.assertEqual(probe.no_token_verdict(401, b"pid 482130, my-example-agent2", self.ids)[0], "PASS")

    def test_a_proxy_json_error_naming_its_own_service_is_not_the_document(self):
        # The product reading of 0.48.3: a proxy's JSON error may carry a `service` member of its own (a string); only
        # the document's shape fails: its protocol, a `service` object with an id, a `process` object with a pid.
        for body in (b'{"error":"unauthorized","service":"cloudflare-access"}', b'{"process":"login","status":401}'):
            verdict, evidence = probe.no_token_verdict(401, body, self.ids, "agent.example.com")
            self.assertEqual(verdict, "PASS", (body, evidence))
        for body in (b'{"service":{"id":"x"}}', b'{"process":{"pid":7}}', b'[{"protocol":"fabric-service/0.1"}]'):
            self.assertEqual(probe.no_token_verdict(401, body, self.ids)[0], "FAIL", body)

    def test_a_short_value_is_not_looked_for(self):
        # A Worker reports pid 1, and a sign-in page has a 1 somewhere: it names nothing (fabric-inbox, 2026-10-23).
        self.assertEqual(probe.no_token_verdict(401, b"<p>step 1 of 2</p>", self.ids + ["1"])[0], "PASS")

    def test_a_copy_of_the_document_inside_the_body_fails_whatever_the_ids_length(self):
        # The blind reading of 0.48.0: a 3-character id is not looked for, so a wrapped copy must fail as the document.
        doc = {"protocol": "fabric-service/0.1", "service": {"id": "ink", "instance": "default"}}
        for body in (json.dumps([doc]), json.dumps({"data": doc}), json.dumps({"a": [{"b": doc}]})):
            self.assertEqual(probe.no_token_verdict(401, body.encode(), ["ink", "ink.default"], "ink.example.workers.dev")[0], "FAIL", body)


class NoTokenRecordedOnEveryPath(unittest.TestCase):
    """The blind reading of 0.48.0: a later request's failure must not drop the no-token verdict."""

    def probe_with(self, answers):
        p = probe.Probe(Path("x.json"), {"id": "example-agent", "instance": "default", "origin": "https://agent.example.com",
                                         "placement": "remote"}, Path("."), True)
        calls = iter(answers)

        def request(method, path, headers=None, *rest, **kw):
            answer = next(calls)
            if isinstance(answer, BaseException):
                raise answer
            return answer
        p.request = request
        p.read_token = lambda: setattr(p, "token", "t" * 32)
        p.auth_headers = lambda: {"Authorization": "Bearer x"}
        return p

    def test_every_path_records_the_no_token_verdict_once_before_the_answer(self):
        leak = json.dumps({"protocol": "fabric-service/0.1", "service": {"id": "example-agent"}}).encode()
        doc = json.dumps({"protocol": "fabric-service/0.1", "service": {"id": "example-agent", "instance": "default"},
                          "process": {"pid": 4242}, "status": "ready", "degraded": [], "surfaces": {"events": "/e"}}).encode()
        paths = {
            "a timeout": ([(401, {}, leak), TimeoutError("timed out")], "FAIL"),
            "a TLS reset": ([(401, {}, b""), ConnectionResetError("reset")], "PASS"),
            "a 403": ([(401, {}, b"")] + [(403, {}, b"")] * 3, "PASS"),
            "a body that is not JSON": ([(401, {}, leak)] + [(200, {}, b"<html>")] * 3, "FAIL"),
            "success": ([(401, {}, b"<html>sign in</html>")] + [(200, {}, doc)] * 3, "PASS"),
        }
        for name, (answers, verdict) in paths.items():
            with self.subTest(name):
                p = self.probe_with(answers)
                try:
                    p.well_known_rules()
                except StopIteration:
                    pass  # the success path goes on to rules this stub does not answer
                rules = [r["rule"] for r in p.results]
                self.assertEqual(rules.count("well-known.requires-token"), 1, p.results)
                self.assertLess(rules.index("well-known.requires-token"), rules.index("well-known.answers"))
                self.assertEqual([r["verdict"] for r in p.results if r["rule"] == "well-known.requires-token"], [verdict], name)
        p = self.probe_with([(401, {}, b"")])
        p.read_token = lambda: None
        p.well_known_rules()
        self.assertEqual([r["rule"] for r in p.results], ["well-known.requires-token", "well-known.answers"])

    def test_a_body_nested_past_the_parser_fails_without_a_traceback(self):
        self.assertEqual(probe.no_token_verdict(401, b"[" * 100000 + b"]" * 100000, ["example-agent"])[0], "FAIL")

    def test_a_timeout_after_the_no_token_answer_still_records_it_once(self):
        leak = json.dumps({"protocol": "fabric-service/0.1", "service": {"id": "example-agent"}}).encode()
        p = self.probe_with([(401, {}, leak), TimeoutError("timed out")])
        p.well_known_rules()
        rules = [r["rule"] for r in p.results]
        self.assertEqual(rules.count("well-known.requires-token"), 1, p.results)
        self.assertLess(rules.index("well-known.requires-token"), rules.index("well-known.answers"))
        self.assertEqual([r["verdict"] for r in p.results if r["rule"] == "well-known.requires-token"], ["FAIL"])


class SessionCookieBehindAnEdge(unittest.TestCase):
    """FAA-115: a CDN in front of a remote service (DigitalOcean's Cloudflare edge) adds its own Set-Cookie to the
    login redirect; the probe judges the session cookie by its name, never the first or last header it reads."""

    EDGE = "__cf_bm=abc; path=/; expires=Sat, 24-Oct-26 13:00:00 GMT; domain=.example.com; HttpOnly; Secure; SameSite=None"
    SESSION = "__Host-fabric_session=v; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=3600"

    def test_every_set_cookie_header_is_kept(self):
        merged = probe.merge_headers([("Set-Cookie", "a=1"), ("X-One", "y"), ("set-cookie", "b=2")])
        self.assertEqual(merged, {"set-cookie": "a=1\nb=2", "x-one": "y"})

    def test_the_session_cookie_is_picked_by_its_name(self):
        for lines in ("%s\n%s" % (self.EDGE, self.SESSION), "%s\n%s" % (self.SESSION, self.EDGE)):
            self.assertEqual(probe.session_cookie(lines, remote=True), self.SESSION)
        self.assertEqual(probe.session_cookie("fabric_session=v; Path=/; HttpOnly; SameSite=Strict", remote=False),
                         "fabric_session=v; Path=/; HttpOnly; SameSite=Strict")
        self.assertEqual(probe.session_cookie("", remote=True), "")
        # A service that names its cookie wrongly is still judged on its own cookie, not the edge's.
        self.assertEqual(probe.session_cookie("%s\nsid=v; Path=/" % self.EDGE, remote=True), "sid=v; Path=/")

    def login_probe(self, redeem_headers):
        p = probe.Probe(Path("x.json"), {"id": "example-agent", "instance": "default", "origin": "https://agent.example.com",
                                         "placement": "remote"}, Path("."), False)
        p.wk = {"surfaces": {"dashboard": {"path": "/", "login": "/fabric/v1/login"}}}
        p.token = "t" * 32
        p.auth_headers = lambda: {"Authorization": "Bearer x"}
        answers = iter([(200, {}, json.dumps({"url": "/fabric/v1/login?code=c"}).encode()),
                        (302, redeem_headers, b""), (403, {"set-cookie": self.EDGE}, b"")])
        p.request = lambda *a, **kw: next(answers)
        p.login_rules()
        return {r["rule"]: r for r in p.results}

    def test_an_edge_cookie_before_the_session_cookie_is_not_a_fail(self):
        results = self.login_probe({"set-cookie": "%s\n%s" % (self.EDGE, self.SESSION)})
        failed = {k: v["evidence"] for k, v in results.items() if v["verdict"] == "FAIL"}
        self.assertEqual(failed, {})
        for rule in ("login.cookie-host-bound", "login.single-use", "login.session-lifetime"):
            self.assertEqual(results[rule]["verdict"], "PASS", rule)

    def test_a_session_cookie_that_is_not_host_bound_still_fails(self):
        results = self.login_probe({"set-cookie": "%s\nfabric_session=v; Path=/; HttpOnly; SameSite=Strict; Max-Age=60" % self.EDGE})
        self.assertEqual(results["login.cookie-host-bound"]["verdict"], "FAIL")
        self.assertIn("fabric_session", results["login.cookie-host-bound"]["evidence"])
