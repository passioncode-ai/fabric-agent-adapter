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

    def test_unknown_arguments_are_a_usage_error(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(run(Path(temp), "--target", "cursor").returncode, 2)


if __name__ == "__main__":
    unittest.main()
