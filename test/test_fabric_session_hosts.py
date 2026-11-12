"""install-host-hooks for Codex and Kimi Code (FAA-69): `--script` must name an existing file; Kimi Code finds its
block by what the hook runs, not by exact text, so `--apply` repairs a stale path and `--remove` takes a stale or
hand-touched block out; Codex says "updated" when it rewrites its own command."""

import json
from pathlib import Path
import sys
import unittest

from test_fabric_session import Base, fs

STALE = "/old/skills/working-with-fabric/scripts/fabric_session.py"


class HostInstallers(Base):
    def setUp(self):
        super().setUp()
        self.script = self.base / "skills" / "working-with-fabric" / "scripts" / "fabric_session.py"
        self.script.parent.mkdir(parents=True)
        self.script.write_text("# the entry point\n")

    def install(self, host, *flags, script=None):
        argv = ["--host", host, "--script", str(script or self.script)] + list(flags)
        out, err = [], []
        code = fs.install_host_hooks_cli(argv, env=self.env, out=out.append, err=err.append)
        return code, "\n".join(out + err)

    def codex_file(self, doc):
        path = self.home / ".codex" / "hooks.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(doc, indent=2))
        return path

    def kimi_file(self, text):
        path = self.home / ".kimi-code" / "config.toml"
        path.parent.mkdir(exist_ok=True)
        path.write_text(text)
        return path


class ScriptMustExist(HostInstallers):
    def test_codex_refuses_a_script_that_is_not_a_file(self):
        path = self.codex_file({"hooks": {}})
        before = path.read_bytes()
        for flags in ((), ("--apply",)):
            code, out = self.install("codex", *flags, script=self.base / "missing" / "fabric_session.py")
            self.assertEqual(code, 1, flags)
            self.assertIn("is not a file", out)
            self.assertEqual(path.read_bytes(), before)
        code, out = self.install("codex", "--apply", script=self.script.parent)
        self.assertEqual(code, 1, "a folder is not the script")

    def test_kimi_refuses_a_script_that_is_not_a_file(self):
        path = self.kimi_file('default_model = "m"\n')
        code, out = self.install("kimi", "--apply", script=self.base / "missing" / "fabric_session.py")
        self.assertEqual(code, 1)
        self.assertIn("is not a file", out)
        self.assertEqual(path.read_text(), 'default_model = "m"\n')

    def test_removal_needs_no_script(self):
        ours = {"hooks": [{"type": "command", "command": fs.hook_command(STALE, "codex"), "timeout": 5}]}
        path = self.codex_file({"hooks": {"SessionStart": [ours]}})
        code, out = self.install("codex", "--remove", script=STALE)
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(path.read_text()), {"hooks": {}})


class CodexUpdated(HostInstallers):
    def test_a_changed_command_is_reported_as_updated(self):
        ours = {"hooks": [{"type": "command", "command": fs.hook_command(STALE, "codex"), "timeout": 5}]}
        path = self.codex_file({"hooks": {"SessionStart": [ours]}})
        code, out = self.install("codex")
        self.assertIn("would update", out)
        self.assertIn("or the exit contract in a session Fabric started on a board request", out, "FAA-201")
        self.assertIn("records which session holds that request (its session id and, after a /clear, the one it replaced, the agent's process id and a time, 0600", out,
                      "the consent names the write (0.63.0 product reading 4)")
        code, out = self.install("codex", "--apply")
        self.assertEqual(code, 0, out)
        self.assertIn("updated the Fabric preamble hook in", out)
        self.assertNotIn("added", out)
        (hook,) = json.loads(path.read_text())["hooks"]["SessionStart"][0]["hooks"]
        self.assertEqual(hook["command"], fs.hook_command(str(self.script), "codex"))


@unittest.skipIf(fs.tomllib is None, "tomllib needs Python 3.11")
class KimiStale(HostInstallers):
    ORIGINAL = ('default_model = "m"\n\n[[hooks]]\nevent = "SessionStart"\ncommand = "other"\ntimeout = 5\n')
    LATER = '\n[[hooks]]\nevent = "Stop"\ncommand = "keep"\n'

    def hooks(self, path):
        return fs.tomllib.loads(path.read_text())["hooks"]

    def test_apply_repairs_a_stale_path_in_place(self):
        path = self.kimi_file(self.ORIGINAL + fs._kimi_block(fs.hook_command(STALE, "kimi")) + self.LATER)
        code, out = self.install("kimi", "--apply")
        self.assertEqual(code, 0, out)
        self.assertIn("updated the Fabric preamble hook in", out)
        hooks = self.hooks(path)
        self.assertEqual([h["command"] for h in hooks],
                         ["other", fs.hook_command(str(self.script), "kimi"), "keep"])
        self.assertEqual(path.read_text(), self.ORIGINAL + fs._kimi_block(fs.hook_command(str(self.script), "kimi"))
                         + self.LATER)
        self.assertEqual(len(list(path.parent.glob("config.toml.*.bak"))), 1)
        code, out = self.install("kimi", "--apply")
        self.assertIn("already", out)

    def test_remove_takes_out_a_stale_block(self):
        path = self.kimi_file(self.ORIGINAL + fs._kimi_block(fs.hook_command(STALE, "kimi")) + self.LATER)
        code, out = self.install("kimi", "--remove")
        self.assertEqual(code, 0, out)
        self.assertEqual(path.read_text(), self.ORIGINAL + self.LATER)

    def test_a_hand_touched_block_is_still_found(self):
        touched = ('\n[[hooks]]  # mine\nevent = "SessionStart"\ntimeout = 4\ncommand = %s\n'
                   % json.dumps(fs.hook_command(STALE, "kimi")))
        path = self.kimi_file(self.ORIGINAL + touched + self.LATER)
        code, out = self.install("kimi", "--apply")
        self.assertEqual(code, 0, out)
        (ours,) = [h for h in self.hooks(path) if "fabric_session.py" in h["command"]]
        self.assertEqual((ours["command"], ours["timeout"]), (fs.hook_command(str(self.script), "kimi"), 4))
        code, out = self.install("kimi", "--remove")
        self.assertEqual(code, 0, out)
        self.assertEqual([h["command"] for h in self.hooks(path)], ["other", "keep"])
        self.assertEqual(path.read_text(), self.ORIGINAL + self.LATER)

    def test_two_owned_blocks_are_refused(self):
        text = (self.ORIGINAL + fs._kimi_block(fs.hook_command(STALE, "kimi"))
                + fs._kimi_block(fs.hook_command(str(self.script), "kimi")))
        path = self.kimi_file(text)
        code, out = self.install("kimi", "--apply")
        self.assertEqual(code, 1)
        self.assertIn("multiple", out)
        self.assertEqual(path.read_text(), text)


if __name__ == "__main__":
    unittest.main()


class PreambleBound(unittest.TestCase):
    def test_the_preamble_stays_under_hermes_4000_characters_for_every_host(self):
        # FAA-217: Hermes' context plugin takes at most 4000 characters (MAX_CONTEXT_CHARS); the dispatch contract is
        # held under it in test_fabric_session_dispatch, the ordinary preamble here
        for host in fs.HOSTS.values():
            with self.subTest(host=host):
                self.assertLess(len(fs.PREAMBLE.format(host=host)), 4000)
                self.assertLess(len(fs.POINTER.format(host=host)), 4000)


class InsightShape(unittest.TestCase):
    def test_the_insight_shape_is_the_estates_spec(self):
        # FAA-217: the estate's insights specification requires evidence and audience and has the kind market; its
        # collector counts a row without evidence or with an unknown kind as a problem
        doc = Path(__file__).resolve().parents[1] / "plugins/fabric-agent-adapter/skills/working-with-fabric/references/session-hooks.md"
        text = " ".join(doc.read_text(encoding="utf-8").split())
        shape = text.split("An insight/1 line is", 1)[1].split("**A resumed session", 1)[0]
        for words in ("nine required fields", "`schema` `\"insight/1\"`", "`id` (`<agent>-<yyyymmdd>-<n>`)",
                      "`at` (UTC)", "`agent`", "`title` (at most 160 characters)", "`body` (at most 1200 characters)",
                      "`evidence` (a list of one or more", "`audience` (`internal`, `public-maybe` or `public`)",
                      "`lesson`, `finding`, `metric`, `pattern`, `tool`, `market`", "`numbers`", "`tags`", "`next`",
                      "`supersedes`", "An insight without evidence is not written", "the insights specification"):
            self.assertIn(words, shape, words)
        self.assertNotIn("seven required fields", shape)
        self.assertNotIn("provisionally", shape)
