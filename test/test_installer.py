import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin/fabric-agent-adapter.js"
SKILLS = sorted(p.name for p in (ROOT / "plugins/fabric-agent-adapter/skills").iterdir() if p.is_dir())


def run(home, *args):
    env = dict(os.environ, HOME=str(home))
    return subprocess.run(["node", str(BIN), *args], capture_output=True, text=True, env=env)


def fake_plugin(home):
    install = home / ".claude/plugins/cache/fabric-agent-adapter/fabric-agent-adapter/0.4.2"
    (install / "skills").mkdir(parents=True)
    (home / ".claude/plugins/installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {"fabric-agent-adapter@fabric-agent-adapter": [{"installPath": str(install)}]}}))


def launcher_links(home):
    """Hub links the PassionCode launcher owns: ~/.agents/skills/<name> -> ~/.passioncode/current/..."""
    links = {}
    for name in SKILLS:
        target = home / ".passioncode/current/plugins/fabric-agent-adapter/skills" / name
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("launcher copy")
        link = home / ".agents/skills" / name
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
        links[name] = (link, target)
    return links


class InstallerTests(unittest.TestCase):
    def test_default_installs_into_the_agents_hub_and_never_into_claude(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            result = run(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in SKILLS:
                self.assertTrue((home / ".agents/skills" / name / "SKILL.md").is_file())
            self.assertFalse((home / ".claude/skills").exists())

    def test_claude_copy_is_refused_while_the_plugin_is_installed(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            fake_plugin(home)
            result = run(home, "--target", "claude")
            self.assertEqual(result.returncode, 1)
            self.assertIn("would shadow it", result.stderr)
            self.assertFalse((home / ".claude/skills").exists())

    def test_prune_moves_shadowing_copies_aside(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            fake_plugin(home)
            shadow = home / ".claude/skills" / SKILLS[0]
            shadow.mkdir(parents=True)
            (shadow / "SKILL.md").write_text("stale")
            result = run(home, "--prune-shadow")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(shadow.exists())
            self.assertTrue(any((home / ".claude/skills-shadow-backup").iterdir()))

    def test_launcher_managed_hub_links_survive_force(self):
        # LC-14 / F16: one owner per artefact on disk. A plain copy over the launcher's link
        # freezes the skill at this version and the launcher no longer updates it.
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            links = launcher_links(home)
            result = run(home, "--force")
            self.assertEqual(result.returncode, 0, result.stderr)
            for name, (link, target) in links.items():
                self.assertTrue(link.is_symlink(), name)
                self.assertEqual(Path(os.readlink(link)), target)
            self.assertIn("npx @passioncode-ai/passioncode@latest update", result.stdout)

    def test_install_sh_leaves_launcher_links_alone(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            links = launcher_links(home)
            result = subprocess.run(["bash", str(ROOT / "install.sh")], capture_output=True, text=True,
                                    env=dict(os.environ, HOME=str(home)))
            self.assertEqual(result.returncode, 0, result.stderr)
            for name, (link, target) in links.items():
                self.assertTrue(link.is_symlink(), name)
                self.assertEqual(Path(os.readlink(link)), target)
            self.assertIn("passioncode", result.stdout)

    def test_install_sh_still_installs_where_nothing_is_managed(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            result = subprocess.run(["bash", str(ROOT / "install.sh")], capture_output=True, text=True,
                                    env=dict(os.environ, HOME=str(home)))
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in SKILLS:
                self.assertTrue((home / ".agents/skills" / name / "SKILL.md").is_file())

    def test_unknown_arguments_are_a_usage_error(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(run(Path(temp), "--target", "cursor").returncode, 2)


    def test_help_names_the_org_scoped_launcher(self):
        # The bare `passioncode` name on npm is not ours; pointing people at it hands them
        # whoever registers it.
        with tempfile.TemporaryDirectory() as temp:
            out = run(Path(temp), "--help").stdout
        self.assertIn("npx @passioncode-ai/passioncode@latest update", out)
        self.assertNotIn("npx passioncode@", out)

    def test_the_package_commands_run_the_kit_and_install_nothing(self):
        """FAA-27a: pack / sign / verify are the kit's fabric-package.mjs behind the npm command."""
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            folder = home / "pkg"
            folder.mkdir()
            out = run(home, "pack", str(folder))
            self.assertEqual(out.returncode, 1, out.stderr)
            self.assertIn("fabric.package.json", json.loads(out.stdout)["error"])
            self.assertFalse((home / ".agents").exists(), "a package command installs no skill")
            self.assertEqual(run(home, "sign", str(folder)).returncode, 2, "sign without --key is a usage error")
            self.assertIn("pack <folder>", run(home, "--help").stdout)


def package_copy(base):
    """A copy of the package (bin, install.sh, the skills) whose sources a test may break."""
    pkg = base / "pkg"
    shutil.copytree(ROOT / "bin", pkg / "bin")
    shutil.copy(ROOT / "install.sh", pkg / "install.sh")
    shutil.copytree(ROOT / "plugins/fabric-agent-adapter/skills", pkg / "plugins/fabric-agent-adapter/skills",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return pkg, pkg / "plugins/fabric-agent-adapter/skills"


def run_pkg(pkg, home, *args):
    return subprocess.run(["node", str(pkg / "bin/fabric-agent-adapter.js"), *args], capture_output=True, text=True,
                          env=dict(os.environ, HOME=str(home)))


def install_sh(pkg, home, *args):
    return subprocess.run(["bash", str(pkg / "install.sh"), *args], capture_output=True, text=True,
                          env=dict(os.environ, HOME=str(home)))


def tree(path):
    return sorted(str(p.relative_to(path)) for p in path.rglob("*"))


class ReplaceSafely(unittest.TestCase):
    """FAA-80 (findings 50, 51): no installer deletes a copy it was not asked to replace, and a failure leaves
    either the old copy or nothing, never half of each."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name).resolve()
        self.home = base / "home"
        self.home.mkdir()
        self.pkg, self.skills = package_copy(base)
        self.hub = self.home / ".agents/skills"
        self.name = SKILLS[0]
        self.broken = None

    def tearDown(self):
        if self.broken:
            self.broken.chmod(0o644)
        self.temp.cleanup()

    def break_a_source_file(self):
        if os.geteuid() == 0:
            self.skipTest("NOT_RUN: root reads a file whatever its mode")
        self.broken = self.skills / self.name / "SKILL.md"
        self.broken.chmod(0)

    def test_install_sh_keeps_a_copy_it_did_not_make_unless_forced(self):
        mine = self.hub / self.name
        mine.mkdir(parents=True)
        (mine / "MY-NOTES.md").write_text("mine")
        result = install_sh(self.pkg, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((mine / "MY-NOTES.md").read_text(), "mine")
        self.assertIn("--force", result.stdout)
        for name in SKILLS[1:]:
            self.assertTrue((self.hub / name / "SKILL.md").is_file(), name)
        forced = install_sh(self.pkg, self.home, "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertFalse((mine / "MY-NOTES.md").exists())
        self.assertTrue((mine / "SKILL.md").is_file())
        self.assertEqual(sorted(p.name for p in self.hub.iterdir()), SKILLS, "no temporary folder left behind")

    def test_install_sh_rejects_an_unknown_argument(self):
        result = install_sh(self.pkg, self.home, "--frce")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.hub.exists())

    def test_no_installer_copies_bytecode(self):
        cache = self.skills / self.name / "scripts/__pycache__"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "x.cpython-39.pyc").write_bytes(b"\0")
        (self.skills / self.name / "stray.pyc").write_bytes(b"\0")
        for runner in (install_sh, run_pkg):
            with self.subTest(runner=runner.__name__):
                shutil.rmtree(self.hub, ignore_errors=True)
                result = runner(self.pkg, self.home)
                self.assertEqual(result.returncode, 0, result.stderr)
                copied = tree(self.hub / self.name)
                self.assertIn("SKILL.md", copied)
                self.assertFalse([p for p in copied if "__pycache__" in p or p.endswith(".pyc")], copied)

    def test_node_a_failed_skill_is_reported_and_leaves_no_half_copy(self):
        self.break_a_source_file()
        result = run_pkg(self.pkg, self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(self.name, result.stderr)
        self.assertFalse((self.hub / self.name).exists(), "nothing half-copied")
        for name in SKILLS[1:]:
            self.assertTrue((self.hub / name / "SKILL.md").is_file(), "the other skills still install: " + name)
        self.assertEqual(sorted(p.name for p in self.hub.iterdir()), SKILLS[1:], "no temporary folder left behind")
        # The rerun after the cause is fixed installs it, and claims nothing it did not do.
        self.broken.chmod(0o644)
        again = run_pkg(self.pkg, self.home)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("Installed %s" % self.name, again.stdout)
        self.assertEqual(tree(self.hub / self.name), tree(self.skills / self.name))

    def test_node_a_failed_replace_keeps_the_old_copy(self):
        old = self.hub / self.name
        old.mkdir(parents=True)
        (old / "SKILL.md").write_text("old copy")
        self.break_a_source_file()
        result = run_pkg(self.pkg, self.home, "--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(tree(old), ["SKILL.md"])
        self.assertEqual((old / "SKILL.md").read_text(), "old copy")
        self.assertEqual(sorted(p.name for p in self.hub.iterdir()), SKILLS, "no temporary folder left behind")

    def test_install_sh_a_failed_replace_keeps_the_old_copy(self):
        old = self.hub / self.name
        old.mkdir(parents=True)
        (old / "SKILL.md").write_text("old copy")
        self.break_a_source_file()
        result = install_sh(self.pkg, self.home, "--force")
        self.assertEqual(result.returncode, 1)
        self.assertIn(self.name, result.stderr)
        self.assertEqual((old / "SKILL.md").read_text(), "old copy")
        self.assertEqual(tree(old), ["SKILL.md"])
        self.assertEqual(sorted(p.name for p in self.hub.iterdir()), SKILLS, "no temporary folder left behind")

    def test_node_a_copy_that_differs_is_not_called_installed(self):
        partial = self.hub / self.name
        partial.mkdir(parents=True)
        (partial / "SKILL.md").write_text((self.skills / self.name / "SKILL.md").read_text())
        result = run_pkg(self.pkg, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        line = [l for l in result.stdout.splitlines() if self.name + " " in l + " " and str(partial) in l][0]
        self.assertNotIn("already installed", line)
        self.assertIn("differs", line)
        self.assertIn("--force", line)
        again = run_pkg(self.pkg, self.home)
        self.assertIn("up to date", [l for l in again.stdout.splitlines() if str(self.hub / SKILLS[1]) in l][0])


if __name__ == "__main__":
    unittest.main()
