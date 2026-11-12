"""FAA-268: the dashboard-only recipe. Its installer twins (same flags, same descriptor bytes, same last line, a repeat
changes nothing), its entry probed by check_service.py, and the snapshot it shows. No test touches the operator's
descriptors: every run names a temporary services folder."""
import datetime as dt
import http.client
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services"
RECIPE = SKILL / "recipes/dashboard-only"
SCRIPTS = SKILL / "scripts"
REPO = "https://github.com/example/dashboard"
NODE = shutil.which("node")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Installer(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="dashboard-only-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.services = self.base / "services"
        self.folder = self.base / "folder"

    def run_py(self, *extra, folder=None, services=None):
        return subprocess.run([sys.executable, str(RECIPE / "install.py"), "--id", "example-dashboard", "--folder",
                               str(folder or self.folder), "--services-dir", str(services or self.services), *extra],
                              capture_output=True, text=True, timeout=60)

    def test_a_repeat_changes_nothing_and_answers_the_same_line(self):
        first = self.run_py("--repository", REPO)
        self.assertEqual(first.returncode, 0, first.stderr)
        line = json.loads(first.stdout.strip().splitlines()[-1])
        self.assertEqual(sorted(line), ["descriptor", "key", "port"])
        self.assertEqual(line["key"], "example-dashboard.default")
        path = Path(line["descriptor"])
        before = (path.read_bytes(), path.stat().st_mtime_ns, (self.folder / "service.token").read_bytes())
        second = self.run_py("--json")  # no --repository: the installed descriptor answers, nothing is checked again
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout.strip().splitlines(), [first.stdout.strip().splitlines()[-1]])
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns, (self.folder / "service.token").read_bytes()), before)
        d = json.loads(path.read_bytes())
        self.assertNotIn("mcp", json.dumps(d))
        self.assertEqual(d["origin"], "http://127.0.0.1:%d" % line["port"])
        self.assertEqual(oct((self.folder / "service.token").stat().st_mode & 0o777), "0o600")

    def test_refusals_leave_everything_as_it_was(self):
        refused = self.run_py()  # a new install names its repository (FAA-198); the folder has no https origin
        self.assertEqual(refused.returncode, 1)
        self.assertIn("source.repository", refused.stderr)
        self.assertFalse(self.folder.exists())
        self.assertEqual(self.run_py("--repository", REPO).returncode, 0)
        other = self.run_py("--json", folder=self.base / "elsewhere")
        self.assertEqual(other.returncode, 1)
        self.assertIn("not %s" % (self.base / "elsewhere").resolve(), other.stderr)
        self.assertEqual(self.run_py("--nope").returncode, 2)

    def test_a_descriptor_another_installer_wrote_is_left_alone(self):
        self.services.mkdir()
        foreign = self.services / "example-dashboard.default.json"
        foreign.write_text(json.dumps({"id": "example-dashboard", "instance": "default", "installedBy": "someone 1.0"}))
        out = self.run_py("--repository", REPO)
        self.assertEqual(out.returncode, 1)
        self.assertIn("another installer", out.stderr)
        self.assertEqual(json.loads(foreign.read_text())["installedBy"], "someone 1.0")

    def test_a_port_another_descriptor_claims_is_skipped_or_refused(self):
        self.services.mkdir()
        port = free_port()
        (self.services / "other.default.json").write_text(json.dumps({"id": "other", "instance": "default",
                                                                       "origin": "http://127.0.0.1:%d" % port}))
        refused = self.run_py("--repository", REPO, "--port", str(port))
        self.assertEqual(refused.returncode, 1)
        self.assertIn("already claimed by other.default", refused.stderr)
        self.assertFalse(self.folder.exists())
        self.assertEqual(sorted(p.name for p in self.services.iterdir()), ["other.default.json"])
        (self.services / "claims.default.json").write_text(json.dumps({"id": "claims", "instance": "default",
                                                                        "origin": "http://127.0.0.1:47300"}))
        install = load("dashboard_only_install", RECIPE / "install.py")
        picked = install.candidates(self.services, "example-dashboard.default", None)
        self.assertTrue(picked)
        self.assertNotIn(47300, picked)
        self.assertNotIn(port, picked)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_twins_write_the_same_descriptor_and_line(self):
        port = str(free_port())
        py = self.run_py("--repository", REPO, "--port", port, "--name", "Example Dashboard", "--json")
        node_services = self.base / "node-services"
        js = subprocess.run([NODE, str(RECIPE / "install.mjs"), "--id", "example-dashboard", "--folder", str(self.folder),
                             "--services-dir", str(node_services), "--repository", REPO, "--port", port,
                             "--name", "Example Dashboard", "--json"], capture_output=True, text=True, timeout=60)
        self.assertEqual((py.returncode, js.returncode), (0, 0), py.stderr + js.stderr)
        self.assertEqual(js.stdout.replace(str(node_services), "S"), py.stdout.replace(str(self.services), "S"))

        def bytes_of(services):
            d = json.loads((services / "example-dashboard.default.json").read_text())
            d.pop("installedAt")
            return (services / "example-dashboard.default.json").read_text().count("\n"), json.dumps(d)
        self.assertEqual(bytes_of(node_services), bytes_of(self.services))


class Entry(unittest.TestCase):
    """The installed descriptor served by dashboard_service.py and probed by check_service.py."""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="dashboard-only-live-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.services = self.base / "services"
        self.folder = self.base / "folder"
        out = subprocess.run([sys.executable, str(RECIPE / "install.py"), "--id", "example-dashboard", "--folder",
                              str(self.folder), "--services-dir", str(self.services), "--repository", REPO, "--json"],
                             capture_output=True, text=True, check=True, timeout=60)
        self.line = json.loads(out.stdout)
        self.port = self.line["port"]
        self.proc = subprocess.Popen([sys.executable, str(RECIPE / "dashboard_service.py"), "serve", "--descriptor",
                                      self.line["descriptor"]], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.stop)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/.well-known/fabric-service" % self.port, timeout=0.5):
                    return
            except OSError:
                time.sleep(0.1)
        self.fail("the dashboard-only service did not start: %s" % self.proc.stderr.read(2000))

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(10)
        self.proc.stdout.close()
        self.proc.stderr.close()

    def request(self, method, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, headers={"Host": "127.0.0.1:%d" % self.port, **(headers or {})})
        res = conn.getresponse()
        body = res.read()
        conn.close()
        return res.status, res.getheader("Set-Cookie") or "", body

    def well_known(self):
        return json.loads(self.request("GET", "/.well-known/fabric-service")[2])

    def test_check_service_passes_every_rule_it_can_run(self):
        out = subprocess.run([sys.executable, str(SCRIPTS / "check_service.py"), "example-dashboard", "--services-dir",
                              str(self.services), "--json"], capture_output=True, text=True, timeout=120)
        results = {r["rule"]: r for r in json.loads(out.stdout)["results"]}
        self.assertEqual({k: v["evidence"] for k, v in results.items() if v["verdict"] == "FAIL"}, {})
        self.assertEqual(out.returncode, 0)
        for rule in ("well-known.identity", "events.requires-token", "login.single-use", "descriptor.port-claim"):
            self.assertEqual(results[rule]["verdict"], "PASS", rule)

    def test_it_has_a_dashboard_and_no_capability(self):
        doc = self.well_known()
        self.assertEqual(sorted(doc["surfaces"]), ["dashboard", "events"])
        self.assertEqual(doc["degraded"], [{"source": "snapshot", "reason": "missing"}])

    def test_the_page_shows_the_snapshot_escaped(self):
        taken = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        (self.folder / "snapshot.json").write_text(json.dumps({"takenAt": taken, "sections": [
            {"title": "Services", "source": "fabric-dashboards list_services", "columns": ["Service", "State"],
             "rows": [["example-agent.default", "<b>ready</b>"]]}]}))
        self.assertEqual(self.well_known()["degraded"], [])
        token = (self.folder / "service.token").read_text().strip()
        status, _, body = self.request("POST", "/fabric/v1/login-code", {"Authorization": "Bearer " + token})
        self.assertEqual(status, 200)
        status, cookie, _ = self.request("GET", json.loads(body)["url"])
        self.assertEqual(status, 302)
        status, _, page = self.request("GET", "/", {"Cookie": cookie.split(";", 1)[0]})
        self.assertEqual(status, 200)
        self.assertIn(b"example-agent.default", page)
        self.assertIn(b"&lt;b&gt;ready&lt;/b&gt;", page)
        self.assertEqual(self.request("GET", "/")[0], 401)


class Snapshot(unittest.TestCase):
    def test_what_is_not_data_is_degraded(self):
        svc = load("dashboard_only_service", RECIPE / "dashboard_service.py")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "snapshot.json"
            self.assertEqual(svc.read_snapshot(path), {"degraded": "missing"})
            path.write_text("{")
            self.assertEqual(svc.read_snapshot(path), {"degraded": "unreadable"})
            path.write_text(json.dumps({"takenAt": "yesterday", "sections": []}))
            self.assertEqual(svc.read_snapshot(path), {"degraded": "invalid"})
            path.write_text(json.dumps({"takenAt": "2026-11-01T00:00:00Z", "sections": [1]}))
            self.assertEqual(svc.read_snapshot(path), {"degraded": "invalid"})
            path.write_text(json.dumps({"takenAt": "2026-11-01T00:00:00Z", "sections": []}))
            now = dt.datetime(2026, 11, 3, tzinfo=dt.timezone.utc).timestamp()
            self.assertEqual(svc.read_snapshot(path, now)["degraded"], "stale")
            self.assertEqual(svc.read_snapshot(path, now - 86400 * 1.5)["sections"], [])


class Prose(unittest.TestCase):
    def test_the_readme_says_what_waits_and_the_skill_links_it(self):
        text = (RECIPE / "README.md").read_text(encoding="utf-8")
        for needed in ("CT-228", "HA-1", '{"descriptor": "<path>", "key": "<id>.<instance>", "port": <n>}',
                       "changes nothing", "list_services", "no provider key"):
            self.assertIn(needed, text)
        self.assertIn("recipes/dashboard-only/README.md", (SKILL / "SKILL.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
