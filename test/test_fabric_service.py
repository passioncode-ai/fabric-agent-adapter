import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(module)
    return module


fs = load("fabric_service")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def descriptor(port, service_id="sample", instance="default", data="/tmp/x"):
    return {
        "protocol": fs.PROTOCOL, "id": service_id, "instance": instance, "name": "Sample",
        "origin": "http://127.0.0.1:%d" % port, "auth": {"tokenFile": data + "/service.token"},
        "lifecycle": {"manager": "none"}, "paths": {"data": data, "logs": []},
        "installedAt": fs.now_iso(), "installedBy": "test",
    }


class LockTests(unittest.TestCase):
    def test_second_holder_is_refused_with_the_pid(self):
        with tempfile.TemporaryDirectory() as temp:
            first = fs.InstanceLock(Path(temp)).acquire()
            with self.assertRaises(fs.AlreadyRunning) as caught:
                fs.InstanceLock(Path(temp)).acquire()
            self.assertEqual(caught.exception.holder_pid, os.getpid())
            first.release()
            fs.InstanceLock(Path(temp)).acquire().release()


class DescriptorTests(unittest.TestCase):
    def test_port_is_a_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fs.write_descriptor(descriptor(8791, "asset-foundry", "preview"), root)
            with self.assertRaises(fs.ServiceError) as caught:
                fs.write_descriptor(descriptor(8791, "copylot"), root)
            self.assertIn("8791", str(caught.exception))
            self.assertIn("asset-foundry.preview", str(caught.exception))

    def test_reinstall_of_the_same_instance_is_allowed_and_private(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fs.write_descriptor(descriptor(8795), root)
            path = fs.write_descriptor(descriptor(8795), root)
            self.assertEqual(path.name, "sample.default.json")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertTrue(fs.remove_descriptor("sample", "default", root))

    def test_invalid_descriptors_are_refused(self):
        bad = descriptor(8766)
        bad["origin"] = "http://0.0.0.0:8766"
        bad["commands"] = {"doctor": "brandctl check && echo ok"}
        problems = fs.validate_descriptor(bad)
        self.assertTrue(any("origin" in p for p in problems))
        self.assertTrue(any("argument array" in p for p in problems))
        custom = descriptor(8787)
        custom["auth"] = {"tokenFile": "/tmp/t", "header": "X-Foundry-Token", "scheme": "Bearer"}
        self.assertTrue(any("scheme must be none" in p for p in fs.validate_descriptor(custom)))


class TokenAndNetworkTests(unittest.TestCase):
    def test_token_file_must_be_private(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "service.token"
            token = fs.ensure_token(path)
            self.assertEqual(fs.read_token(path), token)
            os.chmod(path, 0o644)
            with self.assertRaises(fs.ServiceError):
                fs.read_token(path)
            link = Path(temp) / "link.token"
            link.symlink_to(path)
            with self.assertRaises(fs.ServiceError):
                fs.read_token(link)

    def test_token_matches_only_the_declared_scheme(self):
        self.assertTrue(fs.token_matches("Bearer abcdefghijklmnopqr", "abcdefghijklmnopqr"))
        self.assertFalse(fs.token_matches("abcdefghijklmnopqr", "abcdefghijklmnopqr"))
        self.assertTrue(fs.token_matches("abcdefghijklmnopqr", "abcdefghijklmnopqr", scheme="none"))
        self.assertFalse(fs.token_matches(None, "abcdefghijklmnopqr"))

    def test_request_guard(self):
        self.assertIsNone(fs.check_request(8710, "127.0.0.1:8710"))
        self.assertIsNone(fs.check_request(8710, "localhost:8710", "http://localhost:8710"))
        self.assertIsNotNone(fs.check_request(8710, "evil.example"))
        self.assertIsNotNone(fs.check_request(8710, "127.0.0.1:8710", "http://evil.example"))
        self.assertIsNotNone(fs.check_request(8710, "127.0.0.1:8710", None, "cross-site"))


class LoginCodeTests(unittest.TestCase):
    def test_code_is_single_use_across_a_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            codes = fs.LoginCodes(Path(temp))
            url = codes.issue()["url"]
            code = url.split("code=", 1)[1]
            session = codes.redeem(code)
            self.assertTrue(codes.session_valid(session))
            self.assertIsNone(fs.LoginCodes(Path(temp)).redeem(code))
            codes.revoke_all()
            self.assertFalse(codes.session_valid(session))

    def test_expired_code_is_burned(self):
        with tempfile.TemporaryDirectory() as temp:
            codes = fs.LoginCodes(Path(temp), ttl=0)
            code = codes.issue()["url"].split("code=", 1)[1]
            time.sleep(0.01)
            self.assertIsNone(codes.redeem(code))


class DocumentTests(unittest.TestCase):
    def test_ready_with_degraded_sources_is_reported_as_degraded(self):
        doc = fs.build_well_known(service_id="sample", instance="default", name="S", version="0.1.0",
                                  build={"commit": "abcdef1"}, started_at=fs.now_iso(), status="ready",
                                  degraded=[{"source": "llm", "reason": "no key"}],
                                  surfaces={"events": {"path": "/fabric/v1/events"}})
        self.assertEqual(doc["status"], "degraded")
        self.assertEqual(doc["protocol"], "fabric-service/0.1")

    def test_events_page_and_log(self):
        with tempfile.TemporaryDirectory() as temp:
            log = fs.JsonlEventLog(Path(temp) / "events.jsonl")
            for n in range(5):
                log.append("demo.note", "info", "Note number %d." % n)
            first = fs.events_page(log.fetch, None, 2)
            self.assertEqual([e["id"] for e in first["events"]], ["4", "5"])
            after = fs.events_page(log.fetch, "2", 10)
            self.assertEqual([e["id"] for e in after["events"]], ["3", "4", "5"])
            empty = fs.events_page(log.fetch, "5", 10)
            self.assertEqual(empty, {"events": [], "cursor": "5"})
            self.assertEqual(fs.parse_limit("999"), fs.EVENTS_MAX_LIMIT)

    def test_event_rules(self):
        with self.assertRaises(fs.ServiceError):
            fs.make_event(1, fs.now_iso(), "job.failed", "critical", "It failed.")
        with self.assertRaises(fs.ServiceError):
            fs.make_event(1, fs.now_iso(), "job.failed", "error", "It failed.", link="https://evil.example")
        with self.assertRaises(fs.ServiceError):
            fs.make_event(1, fs.now_iso(), "JobFailed", "error", "It failed.")

    def test_plist_refuses_secrets_and_keeps_alive(self):
        with self.assertRaises(fs.ServiceError):
            fs.launchd_plist("a.b.c", ["/bin/true"], working_directory=Path("/"), stdout_path=Path("/tmp/l"),
                             environment={"OPENROUTER_API_KEY": "x"})
        import plistlib
        plist = plistlib.loads(fs.launchd_plist("a.b.c", ["/bin/true"], working_directory=Path("/"),
                                                stdout_path=Path("/tmp/l"), environment={"TOKEN_FILE": "/t"}))
        self.assertIs(plist["KeepAlive"], True)
        self.assertIs(plist["RunAtLoad"], True)


class LiveServiceTests(unittest.TestCase):
    """The sample service, probed by check_service.py, with defects planted on purpose."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.data = base / "data"
        self.services = base / "services"
        self.port = free_port()
        self.proc = self.spawn()
        self.wait_ready()
        subprocess.run([sys.executable, str(SCRIPTS / "sample_service.py"), "register", "--port", str(self.port),
                        "--data-dir", str(self.data), "--services-dir", str(self.services)], check=True,
                       capture_output=True)

    def tearDown(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(10)
        self.proc.stdout.close()
        self.proc.stderr.close()
        self.temp.cleanup()

    def spawn(self, *extra):
        return subprocess.Popen([sys.executable, str(SCRIPTS / "sample_service.py"), "serve", "--port", str(self.port),
                                 "--data-dir", str(self.data), *extra], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def wait_ready(self):
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/.well-known/fabric-service" % self.port, timeout=0.5):
                    return
            except OSError:
                time.sleep(0.1)
        self.fail("sample service did not start")

    def check(self):
        out = subprocess.run([sys.executable, str(SCRIPTS / "check_service.py"), "sample", "--services-dir",
                              str(self.services), "--json"], capture_output=True, text=True)
        return out.returncode, {r["rule"]: r for r in json.loads(out.stdout)["results"]}

    def test_conformant_service_passes_every_rule_it_can_run(self):
        code, results = self.check()
        failed = {k: v["evidence"] for k, v in results.items() if v["verdict"] == "FAIL"}
        self.assertEqual(failed, {})
        self.assertEqual(code, 0)
        for rule in ("well-known.identity", "network.host-check", "events.requires-token", "events.page",
                     "login.single-use", "lifecycle.instance-lock", "descriptor.port-claim"):
            self.assertEqual(results[rule]["verdict"], "PASS", rule)
        self.assertEqual(results["lifecycle.launchd"]["verdict"], "NOT_RUN")

    def test_second_copy_exits_75_and_leaves_the_first_serving(self):
        second = subprocess.run([sys.executable, str(SCRIPTS / "sample_service.py"), "serve", "--port",
                                 str(free_port()), "--data-dir", str(self.data)], capture_output=True, text=True, timeout=10)
        self.assertEqual(second.returncode, 75)
        self.assertIn(str(self.proc.pid), second.stderr)
        self.assertIsNone(self.proc.poll())
        _, results = self.check()
        self.assertEqual(results["events.page"]["verdict"], "PASS")

    def test_planted_foreign_identity_is_caught(self):
        path = self.services / "sample.default.json"
        doc = json.loads(path.read_text())
        doc["id"] = "webpilot"
        path.rename(self.services / "webpilot.default.json")
        (self.services / "webpilot.default.json").write_text(json.dumps(doc))
        os.chmod(self.services / "webpilot.default.json", 0o600)
        out = subprocess.run([sys.executable, str(SCRIPTS / "check_service.py"), "webpilot", "--services-dir",
                              str(self.services), "--json"], capture_output=True, text=True)
        verdicts = {r["rule"]: r["verdict"] for r in json.loads(out.stdout)["results"]}
        self.assertEqual(verdicts["well-known.identity"], "FAIL")
        self.assertEqual(out.returncode, 1)

    def test_planted_open_token_file_is_caught(self):
        os.chmod(self.data / "service.token", 0o644)
        code, results = self.check()
        self.assertEqual(results["auth.token-file"]["verdict"], "FAIL")
        self.assertEqual(code, 1)

    def test_planted_port_clash_is_caught(self):
        clash = descriptor(self.port, "copylot", data=str(self.data))
        (self.services / "copylot.default.json").write_text(json.dumps(clash))
        _, results = self.check()
        self.assertEqual(results["descriptor.port-claim"]["verdict"], "FAIL")


class StateRuleTests(unittest.TestCase):
    """Data may live in a data repository, never in the service's own code checkout."""

    def probe(self, data, source):
        checker = load("check_service")
        d = descriptor(8710, data=str(data))
        if source:
            d["source"] = {"repository": source}
        p = checker.Probe(Path("/dev/null"), d, Path("/tmp"), True)
        inside = subprocess.run(["git", "-C", str(data), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        p.state_rule(Path(data), inside)
        return p.results[-1]["verdict"]

    def repo(self, root, remote):
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "remote", "add", "origin", remote], check=True)

    def test_verdicts(self):
        checker = load("check_service")
        self.assertTrue(checker.same_repository("git@github.com:ssheleg/x.git", "https://github.com/ssheleg/x"))
        self.assertFalse(checker.same_repository("git@github.com:ssheleg/x.git", "https://github.com/ssheleg/y"))
        with tempfile.TemporaryDirectory() as temp:
            code = Path(temp) / "code"
            self.repo(code, "git@github.com:passioncode-ai/svc.git")
            (code / "data").mkdir()
            self.assertEqual(self.probe(code / "data", "https://github.com/passioncode-ai/svc"), "FAIL")
            store = Path(temp) / "store"
            self.repo(store, "git@github.com:passioncode-ai/svc-registry.git")
            self.assertEqual(self.probe(store, "https://github.com/passioncode-ai/svc"), "PASS")
            self.assertEqual(self.probe(store, None), "NOT_RUN")
            plain = Path(temp) / "plain"
            plain.mkdir()
            self.assertEqual(self.probe(plain, "https://github.com/passioncode-ai/svc"), "PASS")
            rel = Path(temp) / "releases" / "0.1.0"
            rel.mkdir(parents=True)
            self.assertEqual(self.probe(rel, "https://github.com/passioncode-ai/svc"), "FAIL")


if __name__ == "__main__":
    unittest.main()
