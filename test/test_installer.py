import json
import os
from pathlib import Path
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

if __name__ == "__main__":
    unittest.main()
