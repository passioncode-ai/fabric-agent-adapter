"""FAA-271: admit.py chains the source check, the probe, the template check and the private-terms check, reports each
as PASS, FAIL or NOT_RUN, and never prints what a check found."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins/fabric-agent-adapter/skills"
ADMIT = SKILLS / "creating-fabric-agents/scripts/admit.py"
TEMPLATE = SKILLS / "creating-fabric-agents/templates/communication-agent"
HOME = "/" + "Users/" + "jq" + "vxmorrow" + "/agent/data"  # a home path put together at run time
TERM = "zq" + "-made-" + "term"


class Admit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "agent"
        self.root.mkdir()
        (self.root / "README.md").write_text("# Example agent\n", encoding="utf-8")
        self.config = self.tmp / "config"
        self.config.mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("FABRIC_INSTANCE_STRINGS", "PASSIONCODE_PRIVATE_TERMS", "XDG_CONFIG_HOME", "APPDATA")}
        # no owner's list and no private-terms list but the ones a test names: the operator's own never leak in
        self.env.update(XDG_CONFIG_HOME=str(self.config), APPDATA=str(self.config),
                        PASSIONCODE_PRIVATE_TERMS=str(self.tmp / "no-list.txt"))

    def admit(self, *args):
        done = subprocess.run([sys.executable, "-B", str(ADMIT), str(self.root), "--json"] + list(args),
                              capture_output=True, text=True, env=self.env)
        report = json.loads(done.stdout)
        return done.returncode, {s["step"]: s for s in report["steps"]}, report, done.stdout

    def test_a_clean_agent_is_admitted_and_the_rest_is_named_not_run(self):
        code, steps, report, _ = self.admit()
        self.assertEqual(code, 0, steps)
        self.assertTrue(report["admitted"])
        self.assertEqual(steps["source"]["verdict"], "PASS")
        for step in ("probe", "template", "private-terms"):
            self.assertEqual(steps[step]["verdict"], "NOT_RUN", step)
        self.assertIn("not a pass", steps["private-terms"]["evidence"])

    def test_instance_data_is_no_admission_and_is_never_printed(self):
        (self.root / "config.py").write_text("DATA = %r\n" % HOME, encoding="utf-8")
        code, steps, report, out = self.admit()
        self.assertEqual(code, 1)
        self.assertFalse(report["admitted"])
        self.assertEqual(steps["source"]["verdict"], "FAIL")
        self.assertTrue(any("config.py" in line for line in steps["source"]["lines"]))
        self.assertNotIn(HOME.split("/")[2], out)

    def test_a_template_folder_is_checked_strictly(self):
        code, steps, _, _ = self.admit("--template", str(TEMPLATE))
        self.assertEqual(steps["template"]["verdict"], "PASS", steps["template"])
        self.assertEqual(code, 0)
        empty = self.tmp / "example-template"
        empty.mkdir()
        code, steps, _, _ = self.admit("--template", str(empty))
        self.assertEqual(steps["template"]["verdict"], "FAIL")
        self.assertEqual(code, 1)

    def test_a_service_with_no_descriptor_fails_the_probe(self):
        services = self.tmp / "services"
        services.mkdir()
        code, steps, _, _ = self.admit("--service", "example-agent", "--services-dir", str(services))
        self.assertEqual(steps["probe"]["verdict"], "FAIL")
        self.assertEqual(code, 1)

    def test_a_private_term_is_named_by_path_and_line_only(self):
        terms = self.tmp / "terms.txt"
        terms.write_text("# a comment\n%s\n" % TERM, encoding="utf-8")
        (self.root / "notes.md").write_text("one\nsee %s here\n" % TERM.upper(), encoding="utf-8")
        code, steps, _, out = self.admit("--private-terms", str(terms))
        self.assertEqual(code, 1)
        self.assertEqual(steps["private-terms"]["verdict"], "FAIL")
        self.assertEqual(steps["private-terms"]["lines"], ["notes.md: line 2"])
        self.assertNotIn(TERM, out.lower())
        (self.root / "notes.md").write_text("nothing private\n", encoding="utf-8")
        code, steps, _, _ = self.admit("--private-terms", str(terms))
        self.assertEqual((code, steps["private-terms"]["verdict"]), (0, "PASS"))

    def test_a_folder_that_is_not_there_is_a_usage_error(self):
        done = subprocess.run([sys.executable, "-B", str(ADMIT), str(self.tmp / "absent")], capture_output=True, text=True,
                              env=self.env)
        self.assertEqual(done.returncode, 2)


if __name__ == "__main__":
    unittest.main()
