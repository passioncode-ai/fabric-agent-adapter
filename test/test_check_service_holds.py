"""FAA-298: the probe's `limits.holds` rule. A service that declares limits (a load declaration's limits, a usage
report's budget or budgets) holds work through the kit's fabric_holds, so its caller reads each hold on the job and its
operator hears of it once. Services built before fabric_holds existed cannot have adopted it, so in 0.81.0 a service
that declares limits and holds none through it reads NOT_RUN with a migration note naming fabric_holds, never FAIL."""
import importlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
sys.path.insert(0, str(SCRIPTS))
rules = importlib.import_module("check_service_rules")
fabric_load = importlib.import_module("fabric_load")

WK = {"extensions": fabric_load.load_extension("/fabric/v1/load", 60, {"concurrency": 2, "perCaller": 1, "queueMax": 10})}


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo)] + list(args), check=True, capture_output=True)


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class HoldsRule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "service"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        (self.repo / "fabric_holds.py").write_text("class HoldBook: pass\n", encoding="utf-8")
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_limits.py").write_text("from fabric_holds import HoldBook\n", encoding="utf-8")
        (self.repo / "server.py").write_text("def render(job): return job\n", encoding="utf-8")
        git(self.repo, "add", "-A")

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_declared_limits_are_read(self):
        self.assertEqual(rules.declared_limits(WK), ["load concurrency 2", "load perCaller 1", "load queueMax 10"])
        self.assertEqual(rules.declared_limits({}, {"budget": {"period": "day", "limitUsd": 5}, "budgets": [{}]}),
                         ["usage budget USD 5 a day", "usage budgets (1)"])
        self.assertEqual(rules.declared_limits({"extensions": {fabric_load.LOAD_EXTENSION_KEY: {"path": 1}}}), [])

    def test_no_limits_is_not_run(self):
        self.assertEqual(rules.holds_verdict([], self.repo, "")[0], "NOT_RUN")

    def test_no_checkout_is_not_run_with_why(self):
        self.assertEqual(rules.holds_verdict(["load concurrency 2"], None, "pass --repo"), ("NOT_RUN", "pass --repo"))

    def test_load_limits_not_yet_through_the_kit_are_a_migration_note_not_a_fail(self):
        verdict, evidence = rules.holds_verdict(rules.declared_limits(WK), self.repo, "")
        self.assertEqual(verdict, "NOT_RUN")
        self.assertIn("load concurrency 2", evidence)
        self.assertIn("fabric_holds", evidence)
        self.assertIn("FAA-298", evidence)

    def test_usage_budgets_only_are_a_migration_note_not_a_fail(self):
        verdict, evidence = rules.holds_verdict(["usage budget USD 5 a day"], self.repo, "")
        self.assertEqual(verdict, "NOT_RUN")
        self.assertIn("usage budget USD 5 a day", evidence)
        self.assertIn("fabric_holds", evidence)

    def test_docs_naming_the_kit_do_not_pass(self):
        (self.repo / "README.md").write_text("Holds go through HoldBook and waiting_message.\n", encoding="utf-8")
        (self.repo / "notes.txt").write_text("hold_job\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        self.assertEqual(rules.holds_verdict(rules.declared_limits(WK), self.repo, "")[0], "NOT_RUN")

    def test_a_vendored_probe_rules_file_does_not_pass(self):
        (self.repo / "vendor").mkdir()
        shutil.copy(SCRIPTS / "check_service_rules.py", self.repo / "vendor" / "check_service_rules.py")
        git(self.repo, "add", "-A")
        self.assertEqual(rules.holds_verdict(rules.declared_limits(WK), self.repo, "")[0], "NOT_RUN")

    def test_a_typescript_service_in_a_subfolder_passes(self):
        (self.repo / "src").mkdir()
        (self.repo / "src" / "jobs.ts").write_text("import { holdJob } from '../fabric-holds.mjs';\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        verdict, evidence = rules.holds_verdict(["load queueMax 10"], self.repo, "")
        self.assertEqual(verdict, "PASS", evidence)
        self.assertIn("src/jobs.ts", evidence)

    def test_a_service_file_that_holds_through_the_kit_passes(self):
        (self.repo / "server.py").write_text("from fabric_holds import HoldBook\nbook = HoldBook('holds.json')\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        verdict, evidence = rules.holds_verdict(rules.declared_limits(WK), self.repo, "")
        self.assertEqual(verdict, "PASS", evidence)
        self.assertIn("server.py", evidence)

    def test_a_node_service_passes_too(self):
        (self.repo / "server.mjs").write_text("import { waitingMessage } from './fabric-holds.mjs';\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        self.assertEqual(rules.holds_verdict(["usage budgets (1)"], self.repo, "")[0], "PASS")


if __name__ == "__main__":
    unittest.main()
