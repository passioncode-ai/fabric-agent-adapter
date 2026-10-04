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
from unittest import mock
import urllib.error
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
check = load("check_service")


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


class LoopbackServerTests(unittest.TestCase):
    """http.server's server_bind() calls socket.getfqdn() between bind() and listen(); a Mac
    with a slow resolver then holds the port bound but silent (seen on a macOS CI runner)."""

    def test_binding_never_asks_the_resolver(self):
        import http.server
        with mock.patch("socket.getfqdn", side_effect=AssertionError("resolver asked at bind")):
            srv = fs.LoopbackHTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
        try:
            self.assertEqual(srv.server_name, "127.0.0.1")
            self.assertTrue(srv.daemon_threads)
        finally:
            srv.server_close()

    def test_the_sample_service_uses_it(self):
        sample = load("sample_service")
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch("socket.getfqdn", side_effect=AssertionError("resolver asked at bind")):
            args = sample.main.__globals__["argparse"].Namespace(
                id="sample", instance="default", name="Sample", port=0, data_dir=temp,
                token_file=None, degraded=None)
            svc = sample.Service(args)
            srv = sample.make_server(svc)
            srv.server_close()
        self.assertIsInstance(srv, sample.fs.LoopbackHTTPServer)


class LockTests2(unittest.TestCase):
    def test_a_garbled_pid_file_reads_as_no_pid(self):
        # str.isdigit() accepts a superscript two; int() of it raised instead of saying "unknown".
        with tempfile.TemporaryDirectory() as temp:
            for text in ("\u00b2", "12x", ""):
                (Path(temp) / "pid").write_text(text)
                self.assertIsNone(fs._read_pid(Path(temp) / "pid"), repr(text))
            (Path(temp) / "pid").write_text("4242\n")
            self.assertEqual(fs._read_pid(Path(temp) / "pid"), 4242)


class DescriptorTests(unittest.TestCase):
    def test_port_is_a_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fs.write_descriptor(descriptor(47191, "maker", "preview"), root)
            with self.assertRaises(fs.ServiceError) as caught:
                fs.write_descriptor(descriptor(47191, "writer"), root)
            self.assertIn("47191", str(caught.exception))
            self.assertIn("maker.preview", str(caught.exception))

    def test_reinstall_of_the_same_instance_is_allowed_and_private(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fs.write_descriptor(descriptor(47195), root)
            path = fs.write_descriptor(descriptor(47195), root)
            self.assertEqual(path.name, "sample.default.json")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertTrue(fs.remove_descriptor("sample", "default", root))

    def test_invalid_descriptors_are_refused(self):
        bad = descriptor(47166)
        bad["origin"] = "http://0.0.0.0:47166"
        bad["commands"] = {"doctor": "brandctl check && echo ok"}
        problems = fs.validate_descriptor(bad)
        self.assertTrue(any("origin" in p for p in problems))
        self.assertTrue(any("argument array" in p for p in problems))
        custom = descriptor(47187)
        custom["auth"] = {"tokenFile": "/tmp/t", "header": "X-Example-Token", "scheme": "Bearer"}
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
        self.assertIsNone(fs.check_request(47110, "127.0.0.1:47110"))
        self.assertIsNone(fs.check_request(47110, "localhost:47110", "http://localhost:47110"))
        self.assertIsNotNone(fs.check_request(47110, "evil.example"))
        self.assertIsNotNone(fs.check_request(47110, "127.0.0.1:47110", "http://evil.example"))
        self.assertIsNotNone(fs.check_request(47110, "127.0.0.1:47110", None, "cross-site"))


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
        self.assertEqual(plist["ProcessType"], "Standard", "a Background job is starved under load")
        self.assertEqual(check.priority_problems(plist), [])

    def test_probe_names_a_background_priority_job(self):
        slow = {"Label": "a.b.c", "RunAtLoad": True, "KeepAlive": True, "ProcessType": "Background", "Nice": 5, "LowPriorityIO": True}
        self.assertEqual(check.priority_problems(slow), ["ProcessType is Background", "Nice is 5", "low-priority I/O"])
        self.assertEqual(check.plist_problems(slow, "a.b.c"), [])
        self.assertEqual(check.priority_problems({"ProcessType": "Interactive"}), [])
        self.assertEqual(check.plist_problems({"Label": "x", "RunAtLoad": True, "KeepAlive": False}, "a.b.c"),
                         ["Label 'x'", "KeepAlive is False, not true"])


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
                     "usage.requires-token", "usage.report",
                     "login.single-use", "lifecycle.instance-lock", "descriptor.port-claim"):
            self.assertEqual(results[rule]["verdict"], "PASS", rule)
        self.assertEqual(results["lifecycle.launchd"]["verdict"], "NOT_RUN")

    def test_mcp_without_the_2026_standard_headers_is_a_400(self):
        """The sample checks Mcp-Method/Mcp-Name as MCP 2026-07-28 requires; the probe sends them."""
        fi_mod = load("fabric_interop")
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode()
        token = (self.data / "service.token").read_text().strip()
        def post(headers):
            req = urllib.request.Request("http://127.0.0.1:%d/mcp" % self.port, data=body, method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + token, **headers})
            try:
                return urllib.request.urlopen(req, timeout=5).status
            except urllib.error.HTTPError as exc:
                return exc.code
        self.assertEqual(post({"MCP-Protocol-Version": fi_mod.MCP_REVISION}), 400)
        self.assertEqual(post(fi_mod.mcp_request_headers("tools/list", {})), 200)

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
        doc["id"] = "runner"
        path.rename(self.services / "runner.default.json")
        (self.services / "runner.default.json").write_text(json.dumps(doc))
        os.chmod(self.services / "runner.default.json", 0o600)
        out = subprocess.run([sys.executable, str(SCRIPTS / "check_service.py"), "runner", "--services-dir",
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
        clash = descriptor(self.port, "writer", data=str(self.data))
        (self.services / "writer.default.json").write_text(json.dumps(clash))
        _, results = self.check()
        self.assertEqual(results["descriptor.port-claim"]["verdict"], "FAIL")


class StateRuleTests(unittest.TestCase):
    """Data may live in a data repository, never in the service's own code checkout."""

    def probe(self, data, source):
        checker = load("check_service")
        d = descriptor(47110, data=str(data))
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


class UsageReportTests(unittest.TestCase):
    """DEC-0021: the usage report a service answers at surfaces.usage, from its own receipts."""

    def setUp(self):
        self.case = json.loads((ROOT / "test/fixtures/usage/receipts.json").read_text())
        import datetime as dt
        self.now = dt.datetime(2026, 10, 4, 12, tzinfo=dt.timezone.utc)

    def report(self, **kw):
        return fs.usage_report(self.case["receipts"], service_id="example-agent", now=self.now, **kw)

    def test_days_models_and_sums(self):
        r = self.report()
        e = self.case["expect"]
        self.assertEqual([d["date"] for d in r["days"]], e["days"], "31-day window, oldest first; an old receipt drops out")
        d0, d1 = r["days"]
        self.assertEqual(d0["calls"], e["day0"]["calls"])
        self.assertEqual(d0["inputTokens"], e["day0"]["inputTokens"])
        self.assertAlmostEqual(d0["costUsd"], e["day0"]["costUsd"], places=6)
        self.assertEqual(d0["byModel"][0]["costBasis"], "mixed", "provider and price-list on one model")
        self.assertEqual(d1["unpricedCalls"], 1)
        self.assertAlmostEqual(d1["costUsd"], e["day1"]["costUsd"], places=6)
        local = [m for m in d1["byModel"] if m["provider"] == "local"][0]
        self.assertIsNone(local["costUsd"], "unknown is null, never 0")
        for day in r["days"]:
            for field in ("calls", "unpricedCalls", "inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens"):
                self.assertEqual(day[field], sum(m[field] for m in day["byModel"]), field)

    def test_a_day_of_only_unpriced_calls_costs_null(self):
        r = fs.usage_report([fs.make_usage_receipt("local", "llama", input_tokens=1, output_tokens=1, at="2026-10-04T01:00:00Z")],
                            service_id="example-agent", now=self.now, budget={"period": "day", "limitUsd": 5})
        self.assertIsNone(r["days"][0]["costUsd"])
        self.assertIsNone(r["budget"]["spentUsd"], "spend against the budget is unknown, not 0")

    def test_budget_counts_the_current_month(self):
        self.assertAlmostEqual(self.report(budget={"period": "month", "limitUsd": 100})["budget"]["spentUsd"],
                               self.case["expect"]["budgetMonthSpent"], places=6)
        with self.assertRaises(fs.ServiceError):
            self.report(budget={"period": "week", "limitUsd": 1})

    def test_receipt_refuses_what_the_report_cannot_carry(self):
        with self.assertRaises(fs.ServiceError):
            fs.make_usage_receipt("Anthropic", "m", input_tokens=1, output_tokens=1)
        with self.assertRaises(fs.ServiceError):
            fs.make_usage_receipt("anthropic", "m", input_tokens=-1, output_tokens=1)
        with self.assertRaises(fs.ServiceError):
            fs.make_usage_receipt("anthropic", "m", input_tokens=1, output_tokens=1, cost_usd=0.1, cost_basis="unknown")
        with self.assertRaises(fs.ServiceError):
            fs.make_usage_receipt("anthropic", "m", input_tokens=1, output_tokens=1, cost_basis="provider")
        receipt = fs.make_usage_receipt("anthropic", "m", input_tokens=1, output_tokens=1)
        self.assertEqual((receipt["costUsd"], receipt["costBasis"]), (None, "unknown"))
        self.assertNotIn("prompt", receipt)

    def test_ledger_is_private_bounded_and_survives_a_torn_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = fs.JsonlUsageLedger(Path(tmp) / "usage" / "usage.jsonl")
            for r in self.case["receipts"]:
                ledger.record(r)
            self.assertEqual(os.stat(ledger.path).st_mode & 0o777, 0o600)
            with open(ledger.path, "a") as f:
                f.write('{"torn":')
            self.assertEqual(len(ledger.receipts()), 5)
            ledger.record(self.case["receipts"][3])
            self.assertEqual(len(ledger.receipts()), 6, "a receipt written after a torn line is not glued to it")
            self.assertEqual(ledger.prune(self.now), 1, "the August receipt goes")
            self.assertEqual(len(ledger.receipts()), 5)
            self.assertNotIn("torn", ledger.path.read_text(), "the rewrite drops the torn line")
            self.assertEqual([d["date"] for d in ledger.report(service_id="example-agent", now=self.now)["days"]], self.case["expect"]["days"])


class UsageCheckTests(unittest.TestCase):
    """check_service.py reads a declared usage report and holds it to FAC-SEM-025."""

    def report(self):
        case = json.loads((ROOT / "test/fixtures/usage/receipts.json").read_text())
        import datetime as dt
        return fs.usage_report(case["receipts"], service_id="example-agent", now=dt.datetime(2026, 10, 4, 12, tzinfo=dt.timezone.utc))

    def test_the_kits_report_passes(self):
        self.assertEqual(check.usage_problems(self.report(), "example-agent", "default"), [])

    def test_zero_for_unknown_wrong_service_and_bad_sums_fail(self):
        r = self.report()
        [m for m in r["days"][1]["byModel"] if m["provider"] == "local"][0]["costUsd"] = 0
        self.assertTrue(any("must be null" in p for p in check.usage_problems(r, "example-agent", "default")))
        self.assertTrue(any("reports for" in p for p in check.usage_problems(self.report(), "example-agent", "preview")))
        r = self.report()
        r["days"][0]["inputTokens"] += 1
        self.assertTrue(any("inputTokens is not the sum" in p for p in check.usage_problems(r, "example-agent", "default")))
        r = self.report()
        r["days"].reverse()
        self.assertTrue(any("run forward" in p for p in check.usage_problems(r, "example-agent", "default")))
