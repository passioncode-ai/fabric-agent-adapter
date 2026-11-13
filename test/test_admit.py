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


#: FAA-328: the cases both private-terms readers answer the same way: (the list's lines, a file's text, the lines it hits).
SHARED_CASES = (
    (["# a comment", TERM, ""], "one\nsee %s here\n" % TERM.upper(), [2]),
    ([TERM], "x%s\n%s-y\n%sz\n" % (TERM, TERM, TERM), [2]),  # not inside a run of ASCII letters and digits
    (["# only a comment", " "], "%s\n" % TERM, []),
    ([TERM, TERM + "-longer"], "a %s-longer b\n" % TERM, [1]),
)


class OneReader(unittest.TestCase):
    """FAA-328: test/validate.py and admit.py read the private-terms list one way (admit.py's, which ships), expand `~`
    in $PASSIONCODE_PRIVATE_TERMS and report paths and lines only, never a term."""

    def setUp(self):
        import importlib.util
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        loaded = []
        for name, path in (("admit_shared", ADMIT), ("validate_shared", ROOT / "test/validate.py")):
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            loaded.append(module)
        self.admit, self.validate = loaded

    def test_both_readers_answer_the_shared_cases(self):
        for terms, text, lines in SHARED_CASES:
            with self.subTest(terms=terms, text=text):
                pattern = self.admit.terms_pattern(terms)
                self.assertEqual(self.admit.term_lines(text, pattern) if pattern else [], lines)
                pattern = self.validate.private_terms_pattern(terms)
                self.assertEqual(self.validate.private_term_lines(text, pattern) if pattern else [], lines)

    def test_the_validator_reads_with_the_shipped_reader(self):
        self.assertIs(self.validate._ADMIT.terms_pattern, self.validate.private_terms_pattern)
        self.assertIs(self.validate._ADMIT.term_lines, self.validate.private_term_lines)

    def test_a_tilde_in_the_variable_is_this_home_and_only_paths_and_lines_are_said(self):
        from unittest import mock
        home = self.tmp / "home"
        (home / "lists").mkdir(parents=True)
        (home / "lists" / "terms.txt").write_text("%s\n" % TERM, encoding="utf-8")
        root = self.tmp / "agent"
        root.mkdir()
        (root / "notes.md").write_text("one\nsee %s here\n" % TERM, encoding="utf-8")
        env = {"PASSIONCODE_PRIVATE_TERMS": "~/lists/terms.txt", "HOME": str(home), "USERPROFILE": str(home)}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(self.admit.terms_file(None), home / "lists" / "terms.txt")
            self.assertEqual(self.validate.private_terms_file(), home / "lists" / "terms.txt")
            step = self.admit.private_terms_step(root, None)
            problems, ran = self.validate.private_term_problems(root, pending={})
        self.assertEqual((step["verdict"], step["lines"]), ("FAIL", ["notes.md: line 2"]))
        self.assertTrue(ran)
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("notes.md: line 2 "), problems[0])
        self.assertNotIn(TERM, json.dumps([step, problems]).lower())

if __name__ == "__main__":
    unittest.main()
