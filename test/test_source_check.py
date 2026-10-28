"""fabric_source_check.py: instance data in an agent's source, found and never repeated (FAA-188 part 1)."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/adapting-projects-to-fabric/scripts"
spec = importlib.util.spec_from_file_location("fabric_source_check", SCRIPTS / "fabric_source_check.py")
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)

# Every value the check must find is assembled at run time, so none sits in this file as a literal.
HOME_NAME = "jdoe" + "smith"
MAC_HOME = "/Users/" + HOME_NAME + "/projects/notes"
LINUX_HOME = "/home/" + HOME_NAME + "/.config/agent"
WIN_HOME = "C:\\" + "Users\\" + HOME_NAME + "\\agent\\data"
WIN_HOME_JSON = "C:\\\\" + "Users\\\\" + HOME_NAME + "\\\\agent"
WIN_HOME_SLASH = "C:/" + "Users/" + HOME_NAME + "/agent"
FAKE_GITHUB = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz0123456789"
FAKE_OPENAI = "sk" + "-" + "proj" + "Abcdefghijklmnop0123456789"
FAKE_JWT = "ey" + "J" + "hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl"
PEM = "-----BEGIN " + "RSA PRIVATE KEY-----"
OWNER = "Acme" + "Holdings"
ACCOUNT = "owner-" + "account-77"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = sc.run(argv)
    return code, out.getvalue(), err.getvalue()


class Tree(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "agent"
        self.root.mkdir()
        self.outside = self.tmp / "outside"
        self.outside.mkdir()
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.tmp / "home"), "USERPROFILE": str(self.tmp / "home")})
        self.env.start()
        os.environ.pop("FABRIC_INSTANCE_STRINGS", None)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, text, mode="w"):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if mode == "wb":
            path.write_bytes(text)
        else:
            path.write_text(text, encoding="utf-8")
        return path

    def owner_list(self, *lines):
        path = self.outside / "instance-strings.txt"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def json_check(self, *extra):
        code, out, err = run(["check", str(self.root), "--json", *extra])
        return code, json.loads(out) if out else None, out + err


class Findings(Tree):
    def test_a_clean_tree_exits_zero(self):
        self.write("README.md", "# example-agent\n\nData lives in ~/.local/share/example-agent or $EXAMPLE_AGENT_DATA_DIR.\n")
        code, result, _ = self.json_check()
        self.assertEqual(code, 0)
        self.assertEqual(result["findings"], [])
        self.assertFalse(result["blocking"])

    def test_home_paths_on_every_platform(self):
        for i, value in enumerate((MAC_HOME, LINUX_HOME, WIN_HOME, WIN_HOME_JSON, WIN_HOME_SLASH)):
            self.write("cfg%d.txt" % i, "path = %s\n" % value)
        code, result, _ = self.json_check()
        self.assertEqual(code, 1)
        self.assertEqual(sorted(f["path"] for f in result["findings"]), ["cfg%d.txt" % i for i in range(5)])
        self.assertTrue(all(f["kind"] == "home-path" and f["line"] == 1 for f in result["findings"]))

    def test_neutral_homes_and_placeholders_are_not_findings(self):
        self.write("doc.md", "\n".join(["/Users/example/agent", "/home/runner/work", "/Users/Shared/x", "/home/<you>/x",
                                         "C:\\Users\\example\\x", "/Users/$USER/x", "~/agent", "/home/user/x"]) + "\n")
        code, result, _ = self.json_check()
        self.assertEqual(code, 0, result["findings"])

    def test_synthetic_values_and_one_letter_homes_are_not_findings(self):
        self.write("doc.md", "\n".join(["AKIA" + "IOSFODNN7" + "EXAMPLE", "sk" + "-or-v1-test-only-not-a-key",
                                         "sk" + "-fake0123456789abcdef", "/Users/a/Library", "C:/Users/b/x"]) + "\n")
        code, result, _ = self.json_check()
        self.assertEqual(code, 0, result["findings"])

    def test_secret_shapes(self):
        self.write("a.py", "TOKEN = '%s'\n" % FAKE_GITHUB)
        self.write("b.env.txt", "key=%s\n" % FAKE_OPENAI)
        self.write("c.json", '{"jwt": "%s"}\n' % FAKE_JWT)
        self.write("d.pem.txt", PEM + "\n")
        self.write("e.sh", "curl -H 'Authorization: Bearer abcdef0123456789abcd' x\n")
        code, result, _ = self.json_check()
        self.assertEqual(code, 1)
        self.assertEqual(sorted(f["path"] for f in result["findings"] if f["kind"] == "secret"),
                         ["a.py", "b.env.txt", "c.json", "d.pem.txt", "e.sh"])

    def test_prose_about_bearer_tokens_is_not_a_secret(self):
        self.write("doc.md", "Bearer tokens are never written to a file.\nbearer <token> goes in the header.\n")
        code, result, _ = self.json_check()
        self.assertEqual(code, 0, result["findings"])

    def test_owner_strings_without_regard_to_case_and_in_paths(self):
        listed = self.owner_list("# my names", OWNER, ACCOUNT, "ab")
        self.write("notes.md", "Built for %s.\n" % OWNER.upper())
        self.write("data/%s.json" % ACCOUNT, "{}\n")
        code, result, _ = self.json_check("--instance-strings", str(listed))
        self.assertEqual(code, 1)
        rules = {(f["path"], f["line"]): f["rule"] for f in result["findings"]}
        self.assertIn("entry 2", rules[("notes.md", 1)])
        self.assertIn("entry 3", rules[("data/%s.json" % ACCOUNT, 0)])
        self.assertEqual(result["instanceStrings"], 2)  # the comment and the two-letter line are not entries

    def test_the_list_comes_from_the_environment_or_the_default(self):
        self.write("notes.md", "Built for %s.\n" % OWNER)
        listed = self.owner_list(OWNER)
        with mock.patch.dict(os.environ, {"FABRIC_INSTANCE_STRINGS": str(listed)}):
            self.assertEqual(self.json_check()[0], 1)
        default = self.tmp / "home/.config/passioncode-fabric/instance-strings.txt"
        default.parent.mkdir(parents=True)
        default.write_text(OWNER + "\n", encoding="utf-8")
        self.assertEqual(self.json_check()[0], 1)
        default.unlink()
        self.assertEqual(self.json_check()[0], 0)


class NeverRepeated(Tree):
    def test_no_value_and_no_list_entry_reaches_the_output(self):
        listed = self.owner_list(OWNER, ACCOUNT)
        self.write("all.txt", "\n".join([MAC_HOME, WIN_HOME, FAKE_GITHUB, FAKE_OPENAI, FAKE_JWT, PEM, OWNER, ACCOUNT]) + "\n")
        for extra in ([], ["--json"]):
            code, out, err = run(["check", str(self.root), "--instance-strings", str(listed), *extra])
            self.assertEqual(code, 1)
            for value in (HOME_NAME, FAKE_GITHUB, FAKE_OPENAI, FAKE_JWT, "PRIVATE KEY-----", OWNER, ACCOUNT,
                          OWNER.casefold(), ACCOUNT.casefold()):
                self.assertNotIn(value, out + err, extra)
            self.assertIn("all.txt:1: home-path", out) if not extra else None

    def test_text_output_names_path_line_and_kind(self):
        self.write("a.py", "x = 1\nTOKEN = '%s'\n" % FAKE_GITHUB)
        code, out, _ = run(["check", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("a.py:2: secret (a value shaped like a provider key)", out)
        self.assertIn("1 finding(s)", out)
        self.assertIn("(no owner's list)", out)


class WhatIsRead(Tree):
    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

    def test_git_ignored_files_are_not_read(self):
        if not shutil.which("git"):
            self.skipTest("git is not installed")
        self.git("init", "-q")
        self.write(".gitignore", "instance/\n")
        self.write("instance/state.json", '{"home": "%s"}\n' % MAC_HOME)
        self.write("src/app.py", "print('hi')\n")
        code, result, _ = self.json_check()
        self.assertEqual(code, 0, result["findings"])
        self.write("src/leak.py", "P = '%s'\n" % MAC_HOME)  # untracked, not ignored: it would be committed
        code, result, _ = self.json_check()
        self.assertEqual([f["path"] for f in result["findings"]], ["src/leak.py"])

    def test_without_git_the_walk_skips_dependency_folders(self):
        self.write("node_modules/dep/index.js", "x = '%s'\n" % MAC_HOME)
        self.write(".git/config", "url = %s\n" % MAC_HOME)
        self.write("app.js", "ok\n")
        with mock.patch.object(sc, "_git_files", return_value=None):
            code, result, _ = self.json_check()
        self.assertEqual(code, 0, result["findings"])

    def test_ignore_file_and_exclude(self):
        self.write("fixtures/keys.txt", FAKE_GITHUB + "\n")
        self.write("vectors/v.json", FAKE_OPENAI + "\n")
        self.write("app.py", "ok\n")
        self.write(sc.IGNORE_FILE, "# test vectors\nfixtures/\n")
        code, result, _ = self.json_check("--exclude", "vectors/*.json")
        self.assertEqual(code, 0, result["findings"])

    def test_binary_and_large_files_are_counted_not_read(self):
        self.write("img.bin", b"\x89PNG\0\0" + FAKE_GITHUB.encode(), mode="wb")
        self.write("big.txt", "a" * (sc.MAX_BYTES + 1))
        code, result, _ = self.json_check()
        self.assertEqual(code, 0)
        self.assertEqual(result["skipped"]["binary"], 1)
        self.assertEqual(result["skipped"]["large"], 1)


class Refusals(Tree):
    def test_a_list_inside_the_tree_is_refused(self):
        inside = self.write("instance-strings.txt", OWNER + "\n")
        code, out, err = run(["check", str(self.root), "--instance-strings", str(inside)])
        self.assertEqual(code, 2)
        self.assertIn("inside the tree", err)
        self.assertNotIn(OWNER, out + err)

    def test_a_named_list_that_is_missing_is_an_error(self):
        code, _, err = run(["check", str(self.root), "--instance-strings", str(self.outside / "absent.txt")])
        self.assertEqual(code, 2)
        self.assertIn("cannot be read", err)

    def test_a_root_that_is_not_a_folder(self):
        code, _, err = run(["check", str(self.root / "absent")])
        self.assertEqual(code, 2)
        self.assertIn("not a folder", err)

    def test_the_cli_exits_with_the_check(self):
        self.write("a.py", "TOKEN = '%s'\n" % FAKE_GITHUB)
        proc = subprocess.run([__import__("sys").executable, str(SCRIPTS / "fabric_source_check.py"), "check", str(self.root)],
                              capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn(FAKE_GITHUB, proc.stdout + proc.stderr)


SKILLS = ROOT / "plugins/fabric-agent-adapter/skills"


def flat(relative):
    return " ".join((SKILLS / relative).read_text(encoding="utf-8").split())


class TheSkillsTeachIt(unittest.TestCase):
    def test_the_reference_copies_are_identical(self):
        copies = [(SKILLS / s / "references/source-and-instance.md").read_bytes()
                  for s in ("creating-fabric-agents", "adapting-projects-to-fabric")]
        self.assertEqual(copies[0], copies[1])

    def test_creating_lays_out_source_and_instance_from_the_first_commit(self):  # source-apart-from-instance
        step = flat("creating-fabric-agents/SKILL.md").split("## Step 2: the project skeleton")[1].split("## Step 3")[0]
        for words in ("The source stays apart from the instance", "references/source-and-instance.md",
                      "fabric_source_check.py check", "exits 0", "Handing the source over stays the owner's act"):
            self.assertIn(words, step)

    def test_adapting_checks_first_then_moves_values_out(self):  # move-instance-data-out-of-an-existing-agent
        step = flat("adapting-projects-to-fabric/SKILL.md").split("### 4c. Keep the instance out of the source")[1].split("### 5.")[0]
        for words in ("First run", "fabric_source_check.py", "never repeating a value", "Run the check again until it exits 0",
                      "a fresh history is the owner's act"):
            self.assertIn(words, step)

    def test_the_reference_names_the_rules_the_script_keeps(self):
        ref = flat("creating-fabric-agents/references/source-and-instance.md")
        for words in ("never repeats", "Exit `0`: no finding; `1`: at least one", "A list inside the tree is refused",
                      sc.IGNORE_FILE, "~/.config/passioncode-fabric/instance-strings.txt", "FABRIC_INSTANCE_STRINGS"):
            self.assertIn(words, ref)
        self.assertEqual(str(sc.DEFAULT_LIST), "~/.config/passioncode-fabric/instance-strings.txt")


class TheAdapterChecksItself(unittest.TestCase):
    def test_this_repository_has_no_instance_data(self):
        """The adapter's own tree passes, with its test vectors left out by its .fabric-source-ignore."""
        with tempfile.TemporaryDirectory() as folder:
            empty = Path(folder, "instance-strings.txt")
            empty.write_text("", encoding="utf-8")
            code, out, err = run(["check", str(ROOT), "--instance-strings", str(empty)])
        self.assertEqual(code, 0, out + err)


if __name__ == "__main__":
    unittest.main()
