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


def open_to_others(path):
    """What a careless copy does to a file: readable by every account (mode bits on POSIX, an
    Everyone ACE on Windows, where chmod changes only the read-only flag)."""
    if os.name == "nt":
        subprocess.run(["icacls", str(path), "/grant", "*S-1-1-0:(R)"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        os.chmod(path, 0o644)


def assert_private(case, path):
    if os.name == "nt":
        owner, aces = fs.windows_acl(path)
        file = {"isRegularFile": True, "isReparsePoint": False, "realPathInProfile": True, "ownerSid": owner, "aces": aces}
        case.assertIsNone(fs.windows_token_acl_problem(file, fs.windows_user_sid()))
    else:
        case.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


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
            assert_private(self, path)
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
            open_to_others(path)
            with self.assertRaises(fs.ServiceError):
                fs.read_token(path)
            link = Path(temp) / "link.token"
            try:
                link.symlink_to(path)
            except OSError as exc:   # Windows without the symlink privilege
                self.skipTest(f"cannot create a symbolic link here: {exc}")
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


class OperatorSessionTests(unittest.TestCase):
    """DEC-0039 (service.md "The session's lifetime"): 12 h after last use, 7 days after sign-in, logout,
    token rotation — enforced by the server, not by the cookie's Max-Age."""

    HOUR = 3600

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = [1_800_000_000.0]
        self.token = ["t" * 43]

    def tearDown(self):
        self.temp.cleanup()

    def codes(self, **kwargs):
        kwargs.setdefault("token", lambda: self.token[0])
        return fs.LoginCodes(Path(self.temp.name), clock=lambda: self.now[0], **kwargs)

    def sign_in(self, codes):
        return codes.redeem(codes.issue()["url"].split("code=", 1)[1])

    def test_idle_bound_ends_a_session_and_use_refreshes_it(self):
        codes = self.codes()
        session = self.sign_in(codes)
        self.now[0] += 11 * self.HOUR
        self.assertTrue(codes.session_valid(session))
        self.now[0] += 11 * self.HOUR  # 22 h after sign-in, 11 h after the last use
        self.assertTrue(codes.session_valid(session))
        self.now[0] += 12 * self.HOUR + 1
        self.assertFalse(codes.session_valid(session))

    def test_absolute_bound_holds_however_often_it_is_used(self):
        codes = self.codes()
        session = self.sign_in(codes)
        for _ in range(7 * 2):
            self.now[0] += 12 * self.HOUR - 60
            self.assertTrue(codes.session_valid(session))
        self.now[0] = 1_800_000_000.0 + 7 * 24 * self.HOUR
        self.assertFalse(codes.session_valid(session))

    def test_logout_ends_the_session_for_every_copy_of_the_cookie(self):
        codes = self.codes()
        session = self.sign_in(codes)
        self.assertTrue(codes.logout(session))
        self.assertFalse(codes.session_valid(session))
        self.assertFalse(self.codes().session_valid(session))
        self.assertFalse(codes.logout(session))
        self.assertFalse(codes.logout("junk"))

    def test_token_rotation_ends_sessions_begun_under_the_old_token(self):
        codes = self.codes()
        session = self.sign_in(codes)
        self.token[0] = "u" * 43
        self.assertFalse(codes.session_valid(session))
        self.assertTrue(codes.session_valid(self.sign_in(codes)))
        self.assertNotIn("t" * 43, session)

    def test_a_static_token_and_no_token_both_work(self):
        static = self.codes(token="s" * 43)
        self.assertTrue(static.session_valid(self.sign_in(static)))
        bare = fs.LoginCodes(Path(self.temp.name) / "bare", clock=lambda: self.now[0])
        self.assertTrue(bare.session_valid(self.sign_in(bare)))

    def test_shorter_bounds_apply_and_longer_ones_are_clamped(self):
        short = self.codes(idle_seconds=60, max_seconds=600)
        session = self.sign_in(short)
        self.now[0] += 61
        self.assertFalse(short.session_valid(session))
        long = self.codes(idle_seconds=10**9, max_seconds=10**9)
        self.assertEqual((long.idle_seconds, long.max_seconds), (12 * self.HOUR, 7 * 24 * self.HOUR))

    def test_forged_old_format_and_unrecorded_cookies_are_refused(self):
        codes = self.codes()
        session = self.sign_in(codes)
        head, mac = session.rsplit(".", 1)
        self.assertFalse(codes.session_valid(head + "." + ("0" if mac[0] != "0" else "1") + mac[1:]))
        parts = session.split(".")
        later = ".".join(parts[:2] + [str(int(parts[2]) + 7 * 24 * self.HOUR)] + parts[3:])
        self.assertFalse(codes.session_valid(later))  # a moved sign-in time breaks the mac
        sid = "abc"
        import hmac as _hmac, hashlib as _hashlib
        legacy = sid + "." + _hmac.new(codes._key(), sid.encode(), _hashlib.sha256).hexdigest()
        self.assertFalse(codes.session_valid(legacy))
        for bad in (None, "", "v2", "v2.a.b.c.d", "v2.a.notanumber.c." + "0" * 64):
            self.assertFalse(codes.session_valid(bad))
        (Path(self.temp.name) / "login-codes.json").unlink()
        self.assertFalse(codes.session_valid(session))  # signed, but the server holds no record of it

    def test_last_use_is_written_at_most_once_a_minute(self):
        codes = self.codes()
        session = self.sign_in(codes)
        store = Path(self.temp.name) / "login-codes.json"
        before = store.read_bytes()
        self.now[0] += 30
        self.assertTrue(codes.session_valid(session))
        self.assertEqual(store.read_bytes(), before)
        self.now[0] += 31
        self.assertTrue(codes.session_valid(session))
        self.assertNotEqual(store.read_bytes(), before)

    def test_records_are_pruned_after_the_absolute_bound(self):
        codes = self.codes()
        self.sign_in(codes)
        self.now[0] += 7 * 24 * self.HOUR + 2 * self.HOUR
        self.sign_in(codes)
        records = [k for k in json.loads((Path(self.temp.name) / "login-codes.json").read_text()) if k.startswith("s:")]
        self.assertEqual(len(records), 1)

    def test_a_logout_is_not_lost_to_a_concurrent_refresh(self):
        """Review S1: a refresh that loaded the store before a logout must not save over it."""
        import threading
        codes = self.codes()
        session = self.sign_in(codes)
        self.now[0] += 120  # the next check refreshes lastUsedAt, so it saves
        real_save = codes._save
        other = threading.Thread(target=codes.logout, args=(session,))
        def save_while_logging_out(data):
            if not other.is_alive() and other.ident is None:
                other.start()
                other.join(0.3)  # with the lock held, the logout waits for this save
            real_save(data)
        codes._save = save_while_logging_out
        self.assertTrue(codes.session_valid(session))
        codes._save = real_save
        other.join(5)
        self.assertFalse(codes.session_valid(session))

    def test_non_ascii_and_bad_bounds_are_refused_without_raising(self):
        """Review S3, S4: a hostile cookie is a refusal, not an exception; a bound must be a number."""
        codes = self.codes()
        self.sign_in(codes)
        for bad in ("v2.x.1.y." + "\u00e9" * 64, "v2.\u00e9.1.-." + "0" * 64, "v2.x.1.\u00e9." + "0" * 64):
            self.assertFalse(codes.session_valid(bad))
            self.assertFalse(codes.logout(bad))
        for bound in ({"idle_seconds": float("nan")}, {"max_seconds": float("inf")}, {"idle_seconds": "12h"}):
            with self.assertRaises(fs.ServiceError):
                self.codes(**bound)

    def test_cookie_headers_default_to_seven_days_and_can_be_cleared(self):
        self.assertIn("Max-Age=604800", fs.session_cookie_header("v"))
        self.assertIn("Max-Age=604800", fs.remote_session_cookie_header("v"))
        cleared = fs.expired_session_cookie_header()
        self.assertTrue(cleared.startswith("fabric_session=; ") and "Max-Age=0" in cleared)
        remote = fs.expired_session_cookie_header(remote=True)
        self.assertTrue(remote.startswith("__Host-fabric_session=; ") and "Secure" in remote and "Max-Age=0" in remote)


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


    def test_probe_reads_the_launchd_marker_the_way_a_copy_does(self):
        """FAA-05: a plist without FABRIC_SERVICE_SUPERVISOR=launchd starts a copy that exits 75 into a respawn loop."""
        import plistlib
        made = plistlib.loads(fs.launchd_plist("a.b.c", ["/bin/true"], working_directory=Path("/"), stdout_path=Path("/tmp/l")))
        self.assertIsNone(check.marker_problem(made))
        by_argument = {"ProgramArguments": ["/bin/x", "--fabric-supervisor", "launchd"], "EnvironmentVariables": {"PATH": "/bin"}}
        self.assertIsNone(check.marker_problem(by_argument), "the argument form is a marker too (DEC-0057)")
        for plist, words in (
            ({"ProgramArguments": ["/bin/x"], "EnvironmentVariables": {"PATH": "/bin"}}, "no FABRIC_SERVICE_SUPERVISOR"),
            ({"ProgramArguments": ["/bin/x"]}, "no FABRIC_SERVICE_SUPERVISOR"),
            ({"ProgramArguments": ["/bin/x"], "EnvironmentVariables": {fs.SUPERVISOR_ENV: ""}}, "no FABRIC_SERVICE_SUPERVISOR"),
            ({"ProgramArguments": ["/bin/x"], "EnvironmentVariables": {fs.SUPERVISOR_ENV: "systemd"}}, "names systemd"),
            ({"ProgramArguments": ["/bin/x"], "EnvironmentVariables": {fs.SUPERVISOR_ENV: "cron"}}, "names no supervisor"),
            ({"ProgramArguments": ["/bin/x", "--fabric-supervisor", "node"], "EnvironmentVariables": {fs.SUPERVISOR_ENV: "launchd"}}, "disagree"),
            ({"ProgramArguments": ["/bin/x", "--", "--fabric-supervisor", "launchd"]}, "no FABRIC_SERVICE_SUPERVISOR"),
            ({"ProgramArguments": "/bin/x", "EnvironmentVariables": ["launchd"]}, "no FABRIC_SERVICE_SUPERVISOR"),
        ):
            problem = check.marker_problem(plist)
            self.assertIsNotNone(problem, plist)
            self.assertIn(words, problem, plist)
        self.assertIn("exits 75", check.marker_problem({"ProgramArguments": ["/bin/x"]}))

    def test_probe_runs_the_marker_rule_on_the_job_file(self):
        import plistlib
        checker = load("check_service")
        with tempfile.TemporaryDirectory() as tmp:
            plist = Path(tmp) / "job.plist"
            d = descriptor(47110, data=tmp)
            d["lifecycle"] = {"manager": "launchd", "label": "a.b.c", "plist": str(plist)}
            verdicts = {}
            for name, body in (("made", fs.launchd_plist("a.b.c", ["/bin/true"], working_directory=Path("/"), stdout_path=Path("/tmp/l"))),
                               ("old", plistlib.dumps({"Label": "a.b.c", "ProgramArguments": ["/bin/true"], "RunAtLoad": True, "KeepAlive": True}))):
                plist.write_bytes(body)
                p = checker.Probe(Path("/dev/null"), d, Path("/tmp"), True)
                with mock.patch.object(checker.shutil, "which", return_value=None):
                    p.lifecycle_rules()
                verdicts[name] = {r["rule"]: r for r in p.results}["lifecycle.supervisor-marker"]
            self.assertEqual(verdicts["made"]["verdict"], "PASS", verdicts["made"])
            self.assertEqual(verdicts["old"]["verdict"], "FAIL")
            self.assertIn("exits 75", verdicts["old"]["evidence"])


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
                     "login.single-use", "login.session-lifetime", "lifecycle.instance-lock", "descriptor.port-claim"):
            self.assertEqual(results[rule]["verdict"], "PASS", rule)
        self.assertEqual(results["lifecycle.launchd"]["verdict"], "NOT_RUN")

    def test_logout_ends_the_session_and_clears_the_cookie(self):
        """DEC-0039: logout ends the session on the server; a browser write needs the custom header."""
        import http.client
        token = (self.data / "service.token").read_text().strip()
        def request(method, path, headers=None):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            conn.request(method, path, headers={"Host": "127.0.0.1:%d" % self.port, **(headers or {})})
            res = conn.getresponse()
            res.read()
            conn.close()
            return res.status, res.getheader("Set-Cookie") or ""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/fabric/v1/login-code", headers={"Authorization": "Bearer " + token, "Host": "127.0.0.1:%d" % self.port})
        url = json.loads(conn.getresponse().read())["url"]
        conn.close()
        status, set_cookie = request("GET", url)
        self.assertEqual(status, 302)
        cookie = {"Cookie": set_cookie.split(";", 1)[0]}
        self.assertEqual(request("GET", "/", cookie)[0], 200)
        self.assertEqual(request("POST", "/logout", cookie)[0], 403)  # no X-Fabric-Request
        status, cleared = request("POST", "/logout", {**cookie, "X-Fabric-Request": "1"})
        self.assertEqual(status, 204)
        self.assertIn("Max-Age=0", cleared)
        self.assertEqual(request("GET", "/", cookie)[0], 401)

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

    def test_a_bad_content_length_or_body_is_a_400(self):
        """Finding 17: the sample trusted Content-Length (a negative one read to the end of the stream, a word or a JSON
        that is no object crashed the handler, a bad event kind escaped as ServiceError)."""
        import socket
        token = (self.data / "service.token").read_text().strip()

        def raw(path, length, body, extra=""):
            with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
                sock.sendall(("POST %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nAuthorization: Bearer %s\r\nX-Fabric-Request: 1\r\n"
                              "Content-Type: application/json\r\nContent-Length: %s\r\n%s\r\n" % (path, self.port, token, length, extra)).encode()
                             + body)
                return sock.recv(65536).split(b" ", 2)[1]
        mcp = "".join("%s: %s\r\n" % kv for kv in load("fabric_interop").mcp_request_headers("tools/list", {}).items())
        listed = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode()
        self.assertEqual(raw("/mcp", len(listed), listed, mcp), b"200")
        for length in ("-1", "abc", "1e3", str(2 * 1048576)):
            with self.subTest(length=length):
                self.assertEqual(raw("/mcp", length, b"{}", mcp), b"400")
                self.assertEqual(raw("/api/emit", length, b"{}"), b"400")
        for body in (b"[1]", b"{bad", b'{"kind": "Not A Kind"}', b'"text"'):
            with self.subTest(body=body):
                self.assertEqual(raw("/api/emit", len(body), body), b"400")
        note = b'{"text": "still serving"}'
        self.assertEqual(raw("/api/emit", len(note), note), b"200")

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
        open_to_others(self.data / "service.token")
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
        self.assertTrue(checker.same_repository("git@github.com:example-org/x.git", "https://github.com/example-org/x"))
        self.assertFalse(checker.same_repository("git@github.com:example-org/x.git", "https://github.com/example-org/y"))
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

    def test_usage_spend_answers_as_the_contract(self):
        # DEC-0110: the contract's usageSpend, its own test's cases and hostile ones (usage-spend-vectors.json).
        cases = json.loads((ROOT / "test/fixtures/contract/usage-spend-vectors.json").read_text())["cases"]
        self.assertGreaterEqual(len(cases), 40)
        for case in cases:
            self.assertEqual(fs.usage_spend(case["rows"]), case["expected"], case["name"])
        # JSON can carry an integer beyond the double range, which JavaScript reads as Infinity; no vector can (the
        # blind reading of 0.48.0). The contract answers undefined, never an error.
        self.assertIsNone(fs.usage_spend(json.loads('[{"calls": 1, "costUsd": 1' + '0' * 400 + '}]')))
        self.assertIsNone(fs.usage_spend(json.loads('[{"calls": 1' + '0' * 400 + ', "costUsd": 1}]')))

    def test_a_cost_rounds_to_the_micro_dollar_as_the_node_twin_rounds(self):
        # FAA-110: Math.round(x * 1e6) / 1e6, half up on the double product (kit-rounding-cases.json, written by Node).
        cases = json.loads((ROOT / "test/fixtures/kit-rounding-cases.json").read_text())["cases"]
        self.assertGreaterEqual(len(cases), 3000)
        wrong = [(c["x"], fs._round_usd(c["x"]), c["rounded"]) for c in cases if fs._round_usd(c["x"]) != c["rounded"]]
        self.assertEqual(wrong[:5], [], "%d of %d differ" % (len(wrong), len(cases)))
        receipt = fs.make_usage_receipt("openrouter", "m", input_tokens=1, output_tokens=1, cost_usd=5e-7, cost_basis="provider",
                                        at="2026-10-04T01:00:00Z", route="key")
        r = fs.usage_report([receipt], service_id="example-agent", now=self.now, budget={"period": "day", "limitUsd": 5})
        self.assertEqual((r["days"][0]["costUsd"], r["budget"]["spentUsd"]), (1e-6, 1e-6), "half a micro-dollar rounds up, as in Node")

    def test_a_limit_counts_money_never_a_subscriptions_estimate(self):
        # CT-115 (DEC-0110): a subscription's costUsd is an estimate at list price, not money spent.
        at = "2026-10-04T01:00:00Z"
        sub = fs.make_usage_receipt("anthropic", "m", input_tokens=1, output_tokens=1, cost_usd=2.0, cost_basis="price-list", at=at, route="subscription")
        key = fs.make_usage_receipt("openrouter", "m", input_tokens=1, output_tokens=1, cost_usd=0.5, cost_basis="provider", at=at, route="key")
        local = fs.make_usage_receipt("local", "llama", input_tokens=1, output_tokens=1, at=at)
        limits = [{"id": "day", "scope": "machine", "kind": "spend", "period": "day", "limitUsd": 5, "enforced": False},
                  {"id": "hour", "scope": "machine", "kind": "spend", "windowSeconds": 86400, "limitUsd": 5, "enforced": False}]

        def spent(receipts):
            budget = fs.usage_report(receipts, service_id="example-agent", now=self.now, budget={"period": "day", "limitUsd": 5})
            limits_report = fs.usage_report(receipts, service_id="example-agent", now=self.now, budgets=limits)
            return [budget["budget"]["spentUsd"]] + [b["spentUsd"] for b in limits_report["budgets"]], budget

        got, r = spent([sub, key])
        self.assertEqual(r["days"][0]["costUsd"], 2.5, "the day's costUsd still sums every route")
        self.assertEqual(got, [0.5, 0.5, 0.5])
        self.assertEqual(spent([sub])[0], [0, 0, 0], "only a subscription: no money spent")
        self.assertEqual(spent([sub, local])[0], [None, None, None], "an unpriced call off the subscription leaves money unknown")

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
            assert_private(self, ledger.path)
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
        self.assertTrue(any("unknown (null)" in p for p in check.usage_problems(r, "example-agent", "default")))
        self.assertTrue(any("reports for" in p for p in check.usage_problems(self.report(), "example-agent", "preview")))
        r = self.report()
        r["days"][0]["inputTokens"] += 1
        self.assertTrue(any("inputTokens is not the sum" in p for p in check.usage_problems(r, "example-agent", "default")))
        r = self.report()
        r["days"].reverse()
        self.assertTrue(any("run forward" in p for p in check.usage_problems(r, "example-agent", "default")))


class McpOwnAuthTests(unittest.TestCase):
    """DEC-0024: with surfaces.mcp.auth own, the probe does not call MCP with the host's token as a
    caller, and checks only that the surface refuses it."""

    def probe(self, answer):
        p = check.Probe.__new__(check.Probe)
        p.results, p.d, p.token, p.events = [], {"id": "example-agent", "instance": "default"}, "tok", []
        p.wk = {"surfaces": {"mcp": {"path": "/mcp", "transport": "streamable-http", "auth": "own"}, "events": {"path": "/e"}}}
        p.load_manifest = lambda: (None, None, "the descriptor names no fabricManifest")
        def call(method, params):
            if isinstance(answer, Exception):
                raise answer
            return answer
        p.mcp_call = call
        p.interop_rules()
        return {r["rule"]: r for r in p.results}

    def test_a_refused_host_token_passes_and_the_caller_rules_are_not_run(self):
        r = self.probe(OSError("HTTP 401 from /mcp"))
        self.assertEqual(r["interop.mcp-own-auth"]["verdict"], "PASS")
        self.assertEqual(r["interop.tools-match"]["verdict"], "NOT_RUN")
        self.assertIn("DEC-0024", r["interop.tools-match"]["evidence"])

    def test_an_accepted_host_token_fails(self):
        r = self.probe({"result": {"tools": []}})
        self.assertEqual(r["interop.mcp-own-auth"]["verdict"], "FAIL")


class McpDelegationAuthTests(unittest.TestCase):
    """DEC-0039 DL-16: auth delegation is handled like own — the descriptor token is not an MCP credential —
    and the well-known document must then declare auth.delegation {issuer, jwks}."""

    def probe(self, answer, auth="delegation", declared=True):
        p = check.Probe.__new__(check.Probe)
        p.results, p.d, p.token, p.events = [], {"id": "example-agent", "instance": "default"}, "tok", []
        p.wk = {"surfaces": {"mcp": {"path": "/mcp", "transport": "streamable-http", "auth": auth}, "events": {"path": "/e"}}}
        if declared:
            p.wk["auth"] = {"delegation": {"issuer": "https://hub.example", "jwks": "https://hub.example/.well-known/jwks.json"}}
        p.load_manifest = lambda: (None, None, "the descriptor names no fabricManifest")
        calls = []
        def call(method, params):
            calls.append(method)
            if isinstance(answer, Exception):
                raise answer
            return answer
        p.mcp_call = call
        p.interop_rules()
        self.calls = calls
        return {r["rule"]: r for r in p.results}

    def test_delegation_is_checked_like_own(self):
        r = self.probe(OSError("HTTP 401 from /mcp"))
        self.assertEqual(r["interop.mcp-own-auth"]["verdict"], "PASS")
        self.assertIn("DL-16", r["interop.mcp-own-auth"]["evidence"])
        for rule in ("interop.tools-match", "interop.job-tools", "interop.trace-propagation"):
            self.assertEqual(r[rule]["verdict"], "NOT_RUN")
            self.assertIn("DL-16", r[rule]["evidence"])
        self.assertEqual(self.calls, ["tools/list"])  # one refusal check, never a caller

    def test_delegation_accepting_the_host_token_fails(self):
        r = self.probe({"result": {"tools": []}})
        self.assertEqual(r["interop.mcp-own-auth"]["verdict"], "FAIL")

    def test_delegation_must_be_declared(self):
        self.assertEqual(self.probe(OSError("HTTP 401"))["auth.delegation-declared"]["verdict"], "PASS")
        self.assertEqual(self.probe(OSError("HTTP 401"), declared=False)["auth.delegation-declared"]["verdict"], "FAIL")
        self.assertEqual(self.probe(OSError("HTTP 401"), auth="own", declared=False)["auth.delegation-declared"]["verdict"], "NOT_RUN")
        p = check.Probe.__new__(check.Probe)
        p.wk = {"auth": {"delegation": {"issuer": "https://hub.example"}}}
        p.results = []
        p.delegation_declared_rule(None)
        self.assertEqual(p.results[0]["verdict"], "FAIL")
        p.wk, p.results = {"auth": "x"}, []
        p.delegation_declared_rule({"path": "/mcp", "auth": "delegation"})
        self.assertEqual(p.results[0]["verdict"], "FAIL")  # review Q1: a malformed auth is a finding, not a crash


class SessionLifetimeRuleTests(unittest.TestCase):
    """DEC-0039: the cookie set at sign-in does not outlive 7 days."""

    def test_max_age_and_expires(self):
        self.assertIsNone(check.session_lifetime_problem("fabric_session=v; Path=/; HttpOnly; Max-Age=604800"))
        self.assertIsNone(check.session_lifetime_problem("fabric_session=v; Path=/; HttpOnly"))
        self.assertIn("2592000", check.session_lifetime_problem("fabric_session=v; HttpOnly; Max-Age=2592000"))
        far = "Wed, 01 Jan 2098 00:00:00 GMT"
        self.assertIsNotNone(check.session_lifetime_problem("fabric_session=v; Expires=%s; HttpOnly" % far))
        self.assertIsNone(check.session_lifetime_problem("fabric_session=v; Expires=%s; Max-Age=3600" % far))
        self.assertIsNotNone(check.session_lifetime_problem("fabric_session=v; Max-Age=soon"))
