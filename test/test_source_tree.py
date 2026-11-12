"""fabric_source_tree.py: the contract's source rules (DEC-0149, FAC-SEM-156 to 160) at parity with its vectors, and
fabric_source_check.py under a source manifest (FAA-261)."""

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/adapting-projects-to-fabric/scripts"
VECTORS = json.loads((ROOT / "test/fixtures/contract/source-vectors.json").read_text(encoding="utf-8"))
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


sc = _load("fabric_source_check", SCRIPTS)
st = _load("fabric_source_tree", SCRIPTS)
ap = _load("adapt_project", SCRIPTS)

# Every value the check must find is assembled at run time, so none sits in this file as a literal.
HOME_NAME = "jdoe" + "smith"
FAKE_GITHUB = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz0123456789"


class Vectors(unittest.TestCase):
    """The port answers every case of the contract's source vectors as the contract does."""

    def test_vectors_are_the_pinned_contracts(self):
        lock = json.loads((ROOT / "fabric-contract.lock.json").read_text(encoding="utf-8"))
        self.assertEqual(VECTORS["contract"], lock["commit"])
        self.assertEqual((len(VECTORS["tree"]), len(VECTORS["patches"])), (91, 32))

    def test_tree(self):
        for case in VECTORS["tree"]:
            with self.subTest(case["name"]):
                self.assertEqual(st.source_tree_problems(case["input"]), case["expected"])

    def test_patches(self):
        for case in VECTORS["patches"]:
            with self.subTest(case["name"]):
                self.assertEqual(st.patch_paths_allowed(case["input"]["manifest"], case["input"]["paths"]), case["expected"])

    def test_manifest_rules(self):
        for case in VECTORS["manifests"]:
            with self.subTest(case["name"]):
                got = [{"code": f["code"], "instancePath": f["instancePath"]} for f in st.manifest_findings(case["input"])]
                self.assertEqual(got, case["expected"])

    def test_package_rule(self):
        for case in VECTORS["packages"]:
            with self.subTest(case["name"]):
                got = st.package_findings(case["input"]["source"], case["input"]["package"])
                self.assertEqual([{"code": f["code"], "instancePath": f["instancePath"]} for f in got], case["expected"])

    def test_constants_are_the_contracts(self):
        constants = VECTORS["constants"]
        self.assertEqual(sorted(constants["NEUTRAL_HOMES"]), sorted(sc.NEUTRAL_HOMES))
        self.assertEqual(tuple(constants["SYNTHETIC"]), sc.SYNTHETIC)
        self.assertEqual(tuple(constants["KEY_SHAPE_SOURCES"]), sc.KEY_SHAPE_SOURCES)
        self.assertEqual([p["source"] for p in constants["SOURCE_HOME_PATHS"]],
                         [p.pattern.replace("(?:\\\\|/)+", "(?:\\\\|\\/)+").replace("/", "\\/").replace("\\\\/", "\\/")
                          for p in sc.HOME_PATHS])
        for name in ("CREDENTIAL_FILE", "CREDENTIAL_FILE_OK", "TOKEN_FILE"):
            self.assertEqual(constants[name]["source"], "^" + getattr(st, name).pattern[:-2] + "$", name)

    def test_packer_members_come_from_the_slots(self):
        manifest = {"format": "fabric-source/1", "include": ["src/"], "slots": [
            {"name": "MAIL_OAUTH", "kind": "secret", "purpose": "reads the mailbox"},
            {"name": "BOARD_TOKEN", "kind": "secret", "purpose": "posts to the board", "optional": True},
            {"name": "JOURNAL", "kind": "store", "purpose": "the digests so far", "path": "journal.sqlite"},
            {"name": "SUPERVISOR_LABEL", "kind": "config", "purpose": "the launchd label of this installation"}]}
        secrets, state = st.package_members(manifest)
        self.assertEqual(secrets, [{"name": "MAIL_OAUTH", "purpose": "reads the mailbox"},
                                   {"name": "BOARD_TOKEN", "purpose": "posts to the board", "optional": True}])
        self.assertEqual(state, [{"path": "journal.sqlite", "purpose": "the digests so far"}])
        self.assertEqual(st.package_findings(manifest, {"secrets": secrets, "state": state}), [])


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = sc.run(argv)
    return code, out.getvalue(), err.getvalue()


class FolderUnderAManifest(unittest.TestCase):
    """`fabric_source_check.py check` on a tree whose root holds fabric.source.json: the manifest decides the source."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.write("LICENSE", "Licensed under the terms in this file.\n")
        self.write("README.md", "# Example agent\n\nSee [the guide](docs/guide.md).\n")
        self.write("docs/guide.md", "# Guide\n")
        self.write("src/main.py", "NAME = 'example-agent'\n")
        self.manifest({"format": "fabric-source/1", "include": ["src/", "docs/", "README.md", "LICENSE"],
                       "slots": [{"name": "EXAMPLE_API_KEY", "kind": "secret", "purpose": "calls the example API"}]})
        self.list = Path(tempfile.mkdtemp()) / "instance-strings.txt"
        self.addCleanup(shutil.rmtree, self.list.parent, ignore_errors=True)
        self.list.write_text("# none\n", encoding="utf-8")

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def manifest(self, value):
        self.write("fabric.source.json", json.dumps(value))

    def check(self, *extra):
        return run(["check", str(self.root), "--instance-strings", str(self.list), *extra])

    def test_a_clean_tree_passes(self):
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("fabric.source.json decides the source", out)

    def test_a_file_outside_include_is_not_read(self):
        self.write("notes/journal.md", "path " + "/home/" + HOME_NAME + "/x\n")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)

    def test_a_home_path_blocks_and_is_never_repeated(self):
        self.write("src/paths.py", "DATA = '/Users/" + HOME_NAME + "/data'\n")
        code, out, _ = self.check()
        self.assertEqual(code, 1)
        self.assertIn("src/paths.py:1:", out)
        self.assertIn("home-path", out)
        self.assertNotIn(HOME_NAME, out)

    def test_a_credential_blocks_and_is_never_repeated(self):
        self.write("src/keys.py", "TOKEN = '" + FAKE_GITHUB + "'\n")
        code, out, _ = self.check("--json")
        self.assertEqual(code, 1)
        result = json.loads(out)
        self.assertEqual([(f["path"], f["line"], f["kind"]) for f in result["findings"]], [("src/keys.py", 1, "credential")])
        self.assertNotIn(FAKE_GITHUB, out)

    def test_warnings_alone_pass(self):
        self.write("docs/guide.md", "# Guide\n\nBack to [the notes](../notes/x.md).\n")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("warning: link-outside", out)

    def test_an_instance_string_names_its_line_in_the_list(self):
        owner = "Acme" + "Holdings"
        self.list.write_text("# owner\n" + owner + "\n", encoding="utf-8")
        self.write("src/about.py", "BY = '" + owner + "'\n")
        code, out, _ = self.check()
        self.assertEqual(code, 1)
        self.assertIn("line 2 of the owner's list", out)
        self.assertNotIn(owner, out)

    def test_a_declared_home_is_found_in_a_source_file(self):
        self.list.write_text("home: alice\n", encoding="utf-8")
        self.write("src/paths.py", "DATA = '/Users/alice/data'\n")
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("home-path", out)

    def test_a_manifest_finding_blocks(self):
        self.manifest({"format": "fabric-source/1", "include": ["src/", "docs/", "README.md", "LICENSE"],
                       "slots": [{"name": "EXAMPLE_API_KEY", "kind": "secret", "purpose": "one"},
                                 {"name": "EXAMPLE_API_KEY", "kind": "secret", "purpose": "two"}]})
        code, out, _ = self.check()
        self.assertEqual(code, 1)
        self.assertIn("FAC-SEM-156 at /slots/1/name", out)

    def test_a_nested_repository_in_the_source_blocks(self):
        self.write("src/vendor/lib/x.py", "X = 1\n")
        (self.root / "src/vendor/lib/.git").mkdir()
        code, out, _ = self.check()
        self.assertEqual(code, 1)
        self.assertIn("src/vendor/lib:0:0: nested-repository", out)

    def test_a_manifest_of_another_format_is_refused(self):
        self.write("fabric.source.json", json.dumps({"format": "fabric-source/2", "include": ["src/"]}))
        code, _, err = self.check()
        self.assertEqual(code, 2)
        self.assertIn("not a fabric-source/1 manifest", err)

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_git_mode_reads_what_git_would_commit(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.write(".gitignore", "src/local.py\n")
        self.write("src/local.py", "DATA = '/Users/" + HOME_NAME + "/data'\n")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("what Git would commit", out)


class SourceSubcommandTests(unittest.TestCase):
    """adapt_project.py source: fabric.source.json from the project's top-level entries, the kit's slots named."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for path in ("src/main.py", "README.md", "LICENSE", ".env", "node_modules/x/index.js", "notes.md"):
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x\n", encoding="utf-8")

    def run_source(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ap.main(["source", str(self.root), *argv, "--json"])
        return code, out.getvalue(), err.getvalue()

    def test_the_proposal_names_the_top_level_source_and_leaves_the_instance_out(self):
        code, out, _ = self.run_source("--dry-run", "--secret", "EXAMPLE_API_KEY:calls the example API",
                                       "--store", "JOURNAL:journal.sqlite:what the agent wrote", "--service")
        self.assertEqual(code, 0)
        manifest = json.loads(out)["manifest"]
        self.assertEqual(manifest["include"], ["LICENSE", "README.md", "notes.md", "src/"])
        self.assertEqual([(s["name"], s["kind"]) for s in manifest["slots"]],
                         [("EXAMPLE_API_KEY", "secret"), ("JOURNAL", "store"), ("PLACEMENT_RECORD", "endpoint"),
                          ("SUPERVISOR_LABEL", "config"), ("SERVICE_PORT", "config")])
        self.assertFalse((self.root / "fabric.source.json").exists())

    def test_an_existing_manifest_is_the_owners(self):
        self.assertEqual(self.run_source()[0], 0)
        self.assertTrue((self.root / "fabric.source.json").is_file())
        code, _, err = self.run_source()
        self.assertEqual(code, 2)
        self.assertIn("is the owner's", err)
        self.assertEqual(self.run_source("--force")[0], 0)

    def test_a_slot_holding_a_value_is_refused(self):
        key = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz0123456789"
        code, out, err = self.run_source("--secret", "EXAMPLE_API_KEY:" + key)
        self.assertEqual(code, 2)
        self.assertNotIn(key, out + err)
        self.assertEqual(self.run_source("--secret", "lower:purpose")[0], 2)


if __name__ == "__main__":
    unittest.main()
