"""check_dashboard_layout.mjs (fabric-dashboard/0.1 ED-1…ED-5) against the kit's demo page, a page with
planted defects, and the live sample service signed in with a login code.

The browser rules need Playwright and its WebKit: set FABRIC_PLAYWRIGHT to a directory whose
node_modules holds playwright (`npm i -D playwright && npx playwright install webkit`). Without it
those tests are skipped as NOT_RUN, and the probe's own NOT_RUN path is still tested."""

import http.server
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
KIT = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/assets/dashboard-kit"
PROBE = SCRIPTS / "check_dashboard_layout.mjs"
BROKEN = ROOT / "test/fixtures/dashboard-layout/broken.html"
PLAYWRIGHT = os.environ.get("FABRIC_PLAYWRIGHT", "")
NODE = shutil.which("node")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(KIT), **kwargs)

    def log_message(self, *args):
        return


def probe(*args, cwd=None, env=None, script=PROBE):
    done = subprocess.run([NODE, str(script), "--json"] + list(args), capture_output=True, text=True, timeout=240,
                          cwd=cwd, env=dict(os.environ, **(env or {})))
    return done.returncode, json.loads(done.stdout or "{}"), done.stderr


@unittest.skipUnless(NODE, "NOT_RUN: node is not on PATH")
class WithoutPlaywright(unittest.TestCase):
    def test_every_rule_is_not_run_with_the_reason(self):
        with tempfile.TemporaryDirectory() as empty:
            env = {"FABRIC_PLAYWRIGHT": "", "NODE_PATH": ""}
            # A bare import('playwright') resolves upward from the script's own folder, so a Playwright
            # installed in any parent (a home folder's node_modules) would be found. Run a copy from
            # the empty folder: the probe imports node: modules only.
            script = Path(empty).resolve() / PROBE.name
            shutil.copy(PROBE, script)
            code, report, _ = probe("http://127.0.0.1:9/", "--playwright", empty, cwd=empty, env=env, script=script)
        self.assertEqual(code, 3, "nothing was measured: never a pass (FAA-96)")
        self.assertEqual(report["failed"], 0)
        self.assertEqual({r["rule"] for r in report["results"]}, {"ED-1", "ED-2", "ED-3", "ED-4", "ED-5"})
        for r in report["results"]:
            self.assertEqual(r["verdict"], "NOT_RUN")
            self.assertIn("Playwright is not installed", r["evidence"])

    def test_a_service_without_playwright_mints_no_login_code(self):
        # Finding 46: the probe loads Playwright and the browser before it asks for a one-time code, so a
        # run that cannot measure never spends a code and never prints a login URL.
        minted = []

        class Service(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _json(self, obj):
                body = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._json({"surfaces": {"dashboard": {"path": "/", "login": True}}})

            def do_POST(self):
                minted.append(self.path)
                self._json({"url": "/fabric/v1/login?code=ONE-TIME-CODE-1234"})

        port = free_port()
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Service)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as empty:
                base = Path(empty).resolve()
                (base / "token").write_text("example-token\n")
                (base / "services").mkdir()
                (base / "services" / "example-agent.default.json").write_text(json.dumps(
                    {"id": "example-agent", "instance": "default", "origin": "http://127.0.0.1:%d" % port,
                     "auth": {"tokenFile": str(base / "token")}}))
                script = base / PROBE.name
                shutil.copy(PROBE, script)
                for extra in ([], ["--json"]):
                    done = subprocess.run([NODE, str(script), "--service", "example-agent", "--services-dir",
                                           str(base / "services"), "--playwright", str(base)] + extra,
                                          capture_output=True, text=True, timeout=60, cwd=str(base),
                                          env=dict(os.environ, FABRIC_PLAYWRIGHT="", NODE_PATH=""))
                    self.assertEqual(done.returncode, 3, done.stderr)  # nothing measured (FAA-96)
                    self.assertNotIn("code=", done.stdout + done.stderr)
                    self.assertIn("Playwright is not installed", done.stdout)
                    if extra:
                        self.assertEqual(json.loads(done.stdout)["target"], "example-agent")
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(minted, [])

    def test_usage_errors_exit_2(self):
        self.assertEqual(subprocess.run([NODE, str(PROBE)], capture_output=True).returncode, 2)
        self.assertEqual(subprocess.run([NODE, str(PROBE), "x", "--widths", "10"], capture_output=True).returncode, 2)


def node_eval(source):
    done = subprocess.run([NODE, "--input-type=module", "-e", source], capture_output=True, text=True, timeout=60)
    if done.returncode:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


@unittest.skipUnless(NODE, "NOT_RUN: node is not on PATH")
class Verdicts(unittest.TestCase):
    """The rules' verdicts from a measurement, without a browser."""

    MEASURED = {"vw": 360, "vh": 800, "scrollWidth": 360, "nav": {"total": 2, "unreachable": []}, "boxes": [],
                "past": [], "nested": [], "chrome": 40, "anchor": None, "rootMinWidth": 0, "floor": 360,
                "elements": 9000, "measured": 6000}

    def verdicts(self, m):
        return {r["rule"]: r for r in node_eval(
            "import { verdicts } from %s; process.stdout.write(JSON.stringify(verdicts(360, 360, %s)));"
            % (json.dumps(PROBE.as_uri()), json.dumps(m)))}

    def test_a_page_past_the_element_cap_is_not_a_silent_pass(self):
        rows = self.verdicts(self.MEASURED)
        self.assertEqual(rows["ED-4"]["verdict"], "NOT_RUN", rows["ED-4"])
        self.assertIn("6000 of 9000", rows["ED-4"]["evidence"])
        self.assertIn("6000 of 9000", rows["ED-5"]["evidence"])

    def test_a_defect_found_before_the_cap_still_fails(self):
        rows = self.verdicts(dict(self.MEASURED, past=["div.wide"]))
        self.assertEqual(rows["ED-4"]["verdict"], "FAIL")
        self.assertIn("6000 of 9000", rows["ED-4"]["evidence"])

    def test_a_page_under_the_cap_passes(self):
        rows = self.verdicts(dict(self.MEASURED, elements=40, measured=40))
        self.assertEqual(rows["ED-4"]["verdict"], "PASS")
        self.assertNotIn("of 40", rows["ED-4"]["evidence"])

    def test_a_login_code_never_reaches_the_evidence(self):
        out = node_eval("import { scrub } from %s; process.stdout.write(JSON.stringify(scrub("
                        "'page.goto: net::ERR at http://127.0.0.1:1/fabric/v1/login?code=abc-123&x=1')));"
                        % json.dumps(PROBE.as_uri()))
        self.assertNotIn("abc-123", out)
        self.assertIn("code=<redacted>", out)


@unittest.skipUnless(NODE and PLAYWRIGHT, "NOT_RUN: set FABRIC_PLAYWRIGHT to a directory with playwright and its webkit")
class InWebKit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", cls.port), Quiet)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_the_demo_page_holds_at_every_width(self):
        code, report, err = probe("http://127.0.0.1:%d/demo.html" % self.port, "--playwright", PLAYWRIGHT)
        self.assertEqual(code, 0, json.dumps(report, indent=1) + err)
        widths = {(r["rule"], r["width"]) for r in report["results"]}
        for width in (360, 480, 768, 1280):
            for rule in ("ED-1", "ED-3", "ED-4", "ED-5"):
                self.assertIn((rule, width), widths)
        self.assertIn(("ED-2", 320), widths)
        self.assertEqual([r for r in report["results"] if r["verdict"] != "PASS"], [])

    def test_the_demo_page_holds_in_chromium_too(self):
        code, report, _ = probe("http://127.0.0.1:%d/demo.html" % self.port, "--playwright", PLAYWRIGHT,
                                "--browser", "chromium", "--widths", "360,1280")
        if all(r["verdict"] == "NOT_RUN" for r in report["results"]):
            self.skipTest("NOT_RUN: chromium is not installed for this Playwright")
        self.assertEqual(code, 0, json.dumps(report, indent=1))

    def test_a_short_window_lets_the_header_scroll_away(self):
        code, report, _ = probe("http://127.0.0.1:%d/demo.html" % self.port, "--playwright", PLAYWRIGHT,
                                "--widths", "360,768", "--height", "420")
        self.assertEqual(code, 0, json.dumps(report, indent=1))

    def test_every_planted_defect_is_caught(self):
        code, report, _ = probe(BROKEN.as_uri(), "--playwright", PLAYWRIGHT, "--widths", "360")
        self.assertEqual(code, 1)
        verdicts = {r["rule"]: r for r in report["results"] if r["width"] == 360}
        self.assertEqual({k: v["verdict"] for k, v in verdicts.items()},
                         {"ED-1": "FAIL", "ED-3": "FAIL", "ED-4": "FAIL", "ED-5": "FAIL"})
        self.assertIn("unreachable", verdicts["ED-3"]["evidence"])
        self.assertIn("div.fixed", verdicts["ED-4"]["evidence"])
        self.assertIn("sticky chrome 200 px", verdicts["ED-5"]["evidence"])
        self.assertIn("nested full-height scroller", verdicts["ED-5"]["evidence"])

    def test_a_nav_cut_off_below_its_first_row_fails_ed3(self):
        code, report, _ = probe((BROKEN.parent / "clipped-nav.html").as_uri(), "--playwright", PLAYWRIGHT,
                                "--widths", "360")
        rows = {r["rule"]: r for r in report["results"] if r["width"] == 360}
        self.assertEqual(rows["ED-3"]["verdict"], "FAIL", rows["ED-3"])
        self.assertIn("unreachable", rows["ED-3"]["evidence"])
        self.assertEqual(code, 1)

    def test_content_past_the_element_cap_is_not_run(self):
        code, report, _ = probe((BROKEN.parent / "past-the-cap.html").as_uri(), "--playwright", PLAYWRIGHT,
                                "--widths", "360")
        rows = {r["rule"]: r for r in report["results"] if r["width"] == 360}
        self.assertEqual(rows["ED-4"]["verdict"], "NOT_RUN", rows["ED-4"])
        self.assertIn("6000 of", rows["ED-4"]["evidence"])
        # The same wide block under the cap is an ED-4 FAIL (the reviewer's nocap page); ED-1 sees the
        # document's width either way, so the run fails on ED-1 alone.
        self.assertEqual(rows["ED-1"]["verdict"], "FAIL")
        self.assertEqual(code, 1)

    def test_the_live_sample_service_signs_in_and_holds(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            port = free_port()
            proc = subprocess.Popen([sys.executable, str(SCRIPTS / "sample_service.py"), "serve", "--port", str(port),
                                     "--data-dir", str(base / "data")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.time() + 10
                while True:
                    try:
                        with urllib.request.urlopen("http://127.0.0.1:%d/.well-known/fabric-service" % port, timeout=0.5) as r:
                            wk = json.load(r)
                        break
                    except OSError:
                        if time.time() > deadline:
                            self.fail("sample service did not start")
                        time.sleep(0.1)
                self.assertEqual(wk["extensions"]["https://fabric.passioncode.ai/agent-contract/extensions/dashboard/0.1"]["minWidth"], 360)
                subprocess.run([sys.executable, str(SCRIPTS / "sample_service.py"), "register", "--port", str(port),
                                "--data-dir", str(base / "data"), "--services-dir", str(base / "services")],
                               check=True, capture_output=True)
                code, report, err = probe("--service", "sample", "--services-dir", str(base / "services"),
                                          "--playwright", PLAYWRIGHT, "--widths", "360,768")
                self.assertEqual(code, 0, json.dumps(report, indent=1) + err)
                self.assertTrue(report["results"])
                self.assertTrue(all(r["verdict"] == "PASS" for r in report["results"]), json.dumps(report, indent=1))
                checked = subprocess.run([sys.executable, str(SCRIPTS / "check_service.py"), "sample", "--services-dir",
                                          str(base / "services"), "--json", "--skip-login"], capture_output=True, text=True)
                rules = {r["rule"]: r for r in json.loads(checked.stdout)["results"]}
                self.assertEqual(rules["dashboard.declared"]["verdict"], "PASS", rules["dashboard.declared"])
            finally:
                proc.terminate()
                proc.wait(10)


if __name__ == "__main__":
    unittest.main()
