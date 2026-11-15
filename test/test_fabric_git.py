"""FAA-190 items 66, 67, 100, 103, 44: every reader in the adapter runs Git through fabric_git, so Git comes from no folder
inside the tree it reads, runs no command the tree's configuration names, never sees the caller's Git location and
writes no trace. Each reader is held to it on a real repository here; the module's own rules first."""

import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins/fabric-agent-adapter/skills"
KIT = SKILLS / "building-fabric-services/scripts"
HOME_FILE = KIT / "fabric_git.py"
COPIES = [SKILLS / s / "scripts/fabric_git.py"
          for s in ("adapting-projects-to-fabric", "creating-fabric-agents", "working-with-fabric")]
REAL_GIT = shutil.which("git")


def load(folder: Path, name: str):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    spec = importlib.util.spec_from_file_location("%s_under_git_test" % name, folder / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fg = load(KIT, "fabric_git")


class Module(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fabric-git-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_copies_are_identical(self):
        for copy in COPIES:
            with self.subTest(copy=copy.parent.parent.name):
                self.assertEqual(copy.read_bytes(), HOME_FILE.read_bytes(), "copy fabric_git.py byte for byte")

    @unittest.skipIf(os.name == "nt", "a POSIX executable")
    def test_a_git_in_a_folder_inside_the_tree_it_reads_is_skipped(self):
        tree = self.tmp / "tree"
        inner = tree / "node_modules" / ".bin"
        inner.mkdir(parents=True)
        (inner / "git").write_text("#!/bin/sh\nexit 0\n")
        (inner / "git").chmod(0o755)
        outer = self.tmp / "bin"
        outer.mkdir()
        (outer / "git").write_text("#!/bin/sh\nexit 0\n")
        (outer / "git").chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([str(inner), str(outer)])}):
            self.assertEqual(fg.executable([tree]), str(outer / "git"))
            self.assertEqual(fg.executable(), str(inner / "git"))  # no tree named: the first absolute folder
            self.assertEqual(fg.command(tree, ["status"])[0], str(outer / "git"))
        link = self.tmp / "via-link"
        link.symlink_to(inner, target_is_directory=True)  # a folder outside reached through a link: resolved first
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([str(link), str(outer)])}):
            self.assertEqual(fg.executable([tree]), str(outer / "git"))

    def test_the_environment_drops_the_location_and_the_traces(self):
        caller = {name: "/elsewhere" for name in fg.LOCATION}
        caller.update({"GIT_TRACE": "/tmp/t", "GIT_TRACE_PACKET": "1", "git_trace2_event": "/tmp/e",
                       "GIT_TEST_FSMONITOR": "x", "GIT_AUTHOR_NAME": "Example", "PATH": "/bin"})
        env = fg.environment(caller)
        self.assertEqual([k for k in env if k.upper() in fg.LOCATION], [])
        self.assertEqual(sorted(k for k in env if k.upper().startswith("GIT_TRACE")),
                         ["GIT_TRACE2", "GIT_TRACE2_EVENT", "GIT_TRACE2_PERF"])
        self.assertEqual({env[k] for k in ("GIT_TRACE2", "GIT_TRACE2_EVENT", "GIT_TRACE2_PERF")}, {"0"})
        self.assertNotIn("GIT_TEST_FSMONITOR", env)
        self.assertEqual((env["GIT_AUTHOR_NAME"], env["PATH"], env["GIT_OPTIONAL_LOCKS"]), ("Example", "/bin", "0"))

    def test_every_call_turns_the_fsmonitors_off(self):
        argv = fg.command(self.tmp, ["ls-files"], trees=[])
        if argv is None:
            self.skipTest("no git")
        self.assertEqual(argv[1:5], ["-c", "core.fsmonitor=", "-c", "core.useBuiltinFSMonitor=false"])
        self.assertEqual(argv[5:], ["-C", str(self.tmp), "ls-files"])

    def test_no_reader_runs_git_but_through_the_module(self):
        """Every script of the skills runs Git through fabric_git (fabric_git itself, and the recipes copied into a
        service, aside)."""
        bare = re.compile(r"""\[\s*["']git["']\s*,|which\(\s*["']git["']\s*\)""")
        offenders = []
        for script in sorted(SKILLS.glob("*/scripts/*.py")):
            if script.name == "fabric_git.py":
                continue
            for number, line in enumerate(script.read_text(encoding="utf-8").splitlines(), 1):
                if bare.search(line):
                    offenders.append("%s/%s:%d" % (script.parent.parent.name, script.name, number))
        self.assertEqual(offenders, [])


@unittest.skipIf(os.name == "nt" or not REAL_GIT, "a POSIX script as Git's fsmonitor")
class Readers(unittest.TestCase):
    """Each reader on a repository whose configuration names an fsmonitor script, with another repository's GIT_DIR
    exported: the script never runs and the reader reads its own repository."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fabric-git-readers-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.marker = self.tmp / "fsmonitor-ran"
        script = self.tmp / "fsmonitor.sh"
        script.write_text("#!/bin/sh\necho ran >> '%s'\n" % self.marker)
        script.chmod(0o755)
        self.repo = self.tmp / "example-agent"
        self.repo.mkdir()
        self.git(self.repo, "init", "-q")
        self.git(self.repo, "config", "user.email", "agent@example.com")
        self.git(self.repo, "config", "user.name", "Example")
        self.git(self.repo, "config", "remote.origin.url", "git@github.com:example/example-agent.git")
        (self.repo / "agent.py").write_text("print('hi')\n")
        (self.repo / ".gitignore").write_text("forced.txt\n")  # tracked though ignored: only its own index lists it
        (self.repo / "forced.txt").write_text("x\n")
        self.git(self.repo, "add", "-f", "agent.py", ".gitignore", "forced.txt")
        self.git(self.repo, "commit", "-q", "-m", "one")
        (self.repo / "untracked.txt").write_text("x\n")
        self.git(self.repo, "config", "core.fsmonitor", str(script))
        self.other = self.tmp / "other"
        self.other.mkdir()
        self.git(self.other, "init", "-q")
        self.git(self.other, "config", "remote.origin.url", "git@github.com:example/other.git")
        self.exported = {"GIT_DIR": str(self.other / ".git"), "GIT_INDEX_FILE": str(self.other / ".git" / "index")}

    def both(self, read):
        """`read()` plain (the tree's fsmonitor would run) and under another repository's exported GIT_DIR."""
        plain = read()
        self.assertNoScript()
        with mock.patch.dict(os.environ, self.exported):
            exported = read()
        self.assertEqual(exported, plain, "the caller's GIT_DIR changed what was read")
        return plain

    @staticmethod
    def git(repo, *args):
        env = {k: v for k, v in os.environ.items() if k not in fg.LOCATION}
        subprocess.run([REAL_GIT, "-c", "core.fsmonitor=", "-C", str(repo), *args], check=True, capture_output=True,
                       env=env)

    def assertNoScript(self):
        self.assertFalse(self.marker.exists(), "the tree's fsmonitor script ran")

    def test_adapt_project_lists_its_own_files_and_runs_no_fsmonitor(self):
        adapt = load(SKILLS / "adapting-projects-to-fabric/scripts", "adapt_project")
        self.assertEqual(self.both(lambda: adapt._top_level(self.repo)),
                         [".gitignore", "agent.py", "forced.txt", "untracked.txt"])

    def test_admit_lists_its_own_files_and_runs_no_fsmonitor(self):
        admit = load(SKILLS / "creating-fabric-agents/scripts", "admit")
        self.assertEqual(self.both(lambda: admit.listed_files(self.repo)),
                         [".gitignore", "agent.py", "forced.txt", "untracked.txt"])

    def test_dashboard_kit_reads_its_own_repository(self):
        dk = load(KIT, "dashboard_kit")
        self.assertEqual(Path(self.both(lambda: dk.repo_root(self.repo))).resolve(), self.repo.resolve())
        listed = self.both(lambda: dk.git(self.repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard"))
        self.assertEqual(sorted(listed.strip("\0").split("\0")), [".gitignore", "agent.py", "forced.txt", "untracked.txt"])

    def test_the_descriptor_build_info_is_its_own_repository(self):
        desc = load(KIT, "fabric_descriptor")
        head = subprocess.run([REAL_GIT, "-C", str(self.repo), "rev-parse", "--short=12", "HEAD"], capture_output=True,
                              text=True, env={k: v for k, v in os.environ.items() if k not in fg.LOCATION}).stdout.strip()
        with mock.patch.dict(os.environ, {"FABRIC_BUILD_COMMIT": ""}):
            info = self.both(lambda: {k: v for k, v in desc.build_info(self.repo).items() if k != "builtAt"})
        self.assertEqual(info, {"commit": head, "dirty": False})

    def test_the_session_reads_its_own_repository(self):
        folder = SKILLS / "working-with-fabric/scripts"
        env = load(folder, "fabric_session_env")
        mcp = load(folder, "fabric_session_mcp")
        self.assertEqual(self.both(lambda: env._origin(self.repo)), "git@github.com:example/example-agent.git")
        facts = self.both(lambda: mcp.git_facts(self.repo, budget_s=20))
        self.assertEqual(facts["filesChanged"], 1)  # untracked.txt
        self.assertTrue(facts["head"])

    def test_the_opener_rule_reads_its_own_checkout(self):
        """Item 100: under another repository's GIT_DIR (a hook's) the opener rule read that index and passed."""
        rules = load(KIT, "check_service_rules")
        opener = self.repo / "scripts" / "open-dashboard.sh"
        opener.parent.mkdir()
        opener.write_text("#!/bin/sh\nopen -a Safari http://127.0.0.1:47190/\n")
        self.git(self.repo, "add", "scripts/open-dashboard.sh")
        self.git(self.repo, "commit", "-q", "-m", "opener")
        verdict, evidence = self.both(lambda: rules.opens_in_host_verdict(
            self.repo, 47190, "http://127.0.0.1:47190", "/dashboard", budget=20))
        self.assertEqual(verdict, "FAIL", evidence)
        path, why = self.both(lambda: rules.service_checkout({}, str(self.repo)))
        self.assertEqual(Path(path).resolve(), self.repo.resolve(), why)


if __name__ == "__main__":
    unittest.main()
