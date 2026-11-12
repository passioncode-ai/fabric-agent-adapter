"""new_agent.py (FAA-270, North Star G21): one command creates an agent project with the contract built in, its source
manifest and its placement guard; and adapt_project.py source, which lays down fabric.source.json (FAA-261)."""

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/adapting-projects-to-fabric/scripts"
KIT = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
sys.path.insert(0, str(SCRIPTS))
import importlib.util  # noqa: E402


def _load(name, folder):
    """A script beside the skill's others, loaded by its path and kept under its own name for its siblings."""
    if name not in sys.modules:
        found = importlib.util.spec_from_file_location(name, folder / (name + ".py"))
        module = importlib.util.module_from_spec(found)
        sys.modules[name] = module
        found.loader.exec_module(module)
    return sys.modules[name]


ap = _load("adapt_project", SCRIPTS)
sc = _load("fabric_source_check", SCRIPTS)
na = _load("new_agent", SCRIPTS)


def new(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = na.main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class NewAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.folder = self.tmp / "example-agent"
        self.empty_list = self.tmp / "instance-strings.txt"
        self.empty_list.write_text("", encoding="utf-8")

    def source_check(self, folder):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sc.run(["check", str(folder), "--instance-strings", str(self.empty_list)])
        return code, out.getvalue()

    def test_a_new_project_carries_the_contract_its_source_manifest_and_its_placement_guard(self):
        code, out, err = new(self.folder, "--id", "example-agent")
        self.assertEqual(code, 0, err)
        answer = json.loads(out.strip().splitlines()[-1])
        self.assertEqual((answer["id"], answer["profile"], answer["service"], answer["repeated"]), ("example-agent", "mcp", False, False))
        self.assertEqual(answer["folder"], str(self.folder.resolve()))
        for path in ("fabric-agent.json", "fabric-contract.lock.json", "fabric.source.json", "src/placement.py",
                     "tests/test_placement.py", "config/placement.example.json", "README.md", "LICENSE", ".gitignore"):
            self.assertIn(path, answer["created"])
            self.assertTrue((self.folder / path).is_file(), path)
        lock = json.loads((self.folder / "fabric-contract.lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["commit"], ap.CONTRACT_COMMIT)
        manifest = json.loads((self.folder / "fabric.source.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["format"], "fabric-source/1")
        self.assertEqual([s["name"] for s in manifest["slots"]], ["PUBLISHER_URI", "PLACEMENT_RECORD"])
        placement = json.loads((self.folder / "config/placement.example.json").read_text(encoding="utf-8"))
        self.assertEqual(placement["schema"], "observatory-placement/1")
        self.assertEqual(placement["elsewhere"][0]["serviceId"], "example-agent.default")
        # the generated project passes the source check under its own manifest, and its own tests
        code, report = self.source_check(self.folder)
        self.assertEqual(code, 0, report)
        self.assertIn("fabric.source.json decides the source", report)
        tests = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"], cwd=str(self.folder),
                               capture_output=True, text=True)
        self.assertEqual(tests.returncode, 0, tests.stderr)
        # adapt_project.py check reads the bundle: structure passes, the sentinels are named
        result = ap.check_project(self.folder, None)
        self.assertEqual(result["gates"]["localStructure"]["status"], "PASS")
        self.assertFalse(result["readyForAdmission"])

    def test_a_repeat_changes_nothing_and_another_folder_is_refused(self):
        self.assertEqual(new(self.folder, "--id", "example-agent")[0], 0)
        before = {p: p.read_bytes() for p in self.folder.rglob("*") if p.is_file()}
        code, out, _ = new(self.folder, "--id", "example-agent", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"folder": str(self.folder.resolve()), "id": "example-agent", "profile": "mcp",
                                           "service": False, "created": [], "repeated": True})
        self.assertEqual({p: p.read_bytes() for p in self.folder.rglob("*") if p.is_file()}, before)
        code, _, err = new(self.folder, "--id", "other-agent")
        self.assertEqual(code, 1)
        self.assertIn("not empty", err)
        other = self.tmp / "notes"
        other.mkdir()
        (other / "keep.md").write_text("mine\n", encoding="utf-8")
        self.assertEqual(new(other, "--id", "example-agent")[0], 1)
        self.assertEqual(new(other, "--id", "example-agent", "--force")[0], 0)
        self.assertEqual((other / "keep.md").read_text(encoding="utf-8"), "mine\n")

    def test_usage_and_refusals(self):
        self.assertEqual(new(self.folder, "--id", "Example_Agent")[0], 1)
        self.assertEqual(new(self.folder, "--id", "example-agent", "--capability", "No Name")[0], 1)
        self.assertEqual(new(self.folder)[0], 2)
        self.assertFalse(self.folder.exists())
        code, out, _ = new(self.folder, "--id", "example-agent", "--profile", "local-runner", "--effect", "draft", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["profile"], "local-runner")

    def test_a_service_project_wires_the_kits_sample_and_passes_check_service(self):
        code, out, err = new(self.folder, "--id", "example-agent", "--service", "--json")
        self.assertEqual(code, 0, err)
        answer = json.loads(out)
        self.assertIn("service/service.py", answer["created"])
        self.assertIn("service/fabric_service.py", answer["created"])
        manifest = json.loads((self.folder / "fabric.source.json").read_text(encoding="utf-8"))
        self.assertIn("service/", manifest["include"])
        self.assertIn("SUPERVISOR_LABEL", [s["name"] for s in manifest["slots"]])
        status = subprocess.run([sys.executable, "-B", str(KIT / "fabric_kit.py"), "status", "--json", str(self.folder / "service")],
                                capture_output=True, text=True)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(self.source_check(self.folder)[0], 0)
        data, services, port = self.tmp / "data", self.tmp / "services", free_port()
        service = [sys.executable, "-B", str(self.folder / "service" / "service.py")]
        proc = subprocess.Popen(service + ["serve", "--id", "example-agent", "--port", str(port), "--data-dir", str(data)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.time() + 15
            while True:
                try:
                    with urllib.request.urlopen("http://127.0.0.1:%d/.well-known/fabric-service" % port, timeout=0.5):
                        break
                except OSError:
                    if time.time() > deadline:
                        self.fail("the generated service did not start")
                    time.sleep(0.1)
            subprocess.run(service + ["register", "--id", "example-agent", "--port", str(port), "--data-dir", str(data),
                                      "--services-dir", str(services), "--repository", "https://github.com/example-org/example-agent"],
                           check=True, capture_output=True)
            checked = subprocess.run([sys.executable, "-B", str(KIT / "check_service.py"), "example-agent", "--services-dir",
                                      str(services), "--json"], capture_output=True, text=True)
            report = json.loads(checked.stdout)
            self.assertEqual(report["failed"], 0, [r for r in report["results"] if r["verdict"] == "FAIL"])
            self.assertEqual(checked.returncode, 0)
        finally:
            proc.terminate()
            proc.wait(10)


if __name__ == "__main__":
    unittest.main()
