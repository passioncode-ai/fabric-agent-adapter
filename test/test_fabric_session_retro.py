"""FAA-206 part 1: the retro after work. A Claude Code PostToolUse hook on Fabric's release tools says the retro
Fabric's `retro-after-work` asks for when a claim is released as done, and only then; the preamble names it for the
end of the work or the session."""
from __future__ import annotations

import json
import re
import time
import unittest
from pathlib import Path

from test_fabric_session import Base, fs

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "plugins/fabric-agent-adapter/hooks/hooks.json"
cli = fs


def release(name="mcp__fabric__fabric_work_release", response=None, **given):
    payload = {"hook_event_name": "PostToolUse", "tool_name": name, "tool_input": given}
    if response is not None:
        payload["tool_response"] = response
    return payload


class Words(unittest.TestCase):
    def test_the_line_says_what_fabric_asks(self):
        for word in ("released this work as done", "in this turn", "`fabric_whoami`", "retro-after-work",
                     "`observatory_lesson`", "one class key per lesson", "insight/1", "one line that says so",
                     "No values"):
            self.assertIn(word, cli.RETRO_LINE)
        self.assertNotIn("—", cli.RETRO_LINE)

    def test_the_preamble_names_the_retro_at_the_end(self):
        text = " ".join(cli.PREAMBLE.split())
        self.assertIn("When a piece of work ends (released as done, or the session about to end), write the retro "
                      "`fabric_whoami` asks for in the same turn.", text)
        self.assertNotIn("—", text)


class Released(unittest.TestCase):
    def test_a_release_of_finished_work_is_done(self):
        for payload in (release(how="done"), release(outcome="done"), release(how="done", taskId="t"),
                        release("mcp__plugin_x_fabric__fabric_work_release", how="done"),
                        release("mcp__fabric__fabric_task_release", outcome="succeeded"),
                        release(how="done", response={"released": True}),
                        release(how="done", response=[{"type": "text", "text": "ok"}]),
                        release(how="done", response=[{"type": "text", "text": '{"released": true, "claims": []}'}]),
                        release(how="done", response={"content": [{"type": "text", "text": '{"released": true}'}]}),
                        release(how="done", response={"structuredContent": {"released": True}}),
                        release(how="done", response='{"released": true}'),
                        release(how="done", outcome="let-go"),
                        release(outcome="done", how=None)):
            with self.subTest(payload=payload):
                self.assertTrue(cli.released_done(payload))

    def test_every_other_call_is_not(self):
        for payload in (release(how="let-go"), release(how="handed-over"), release(outcome="let-go"), release(),
                        release("mcp__fabric__fabric_task_release", outcome="failed"),
                        release("mcp__fabric__fabric_task_release", how="done"),
                        release("mcp__fabric__fabric_work_claim", how="done"),
                        release("fabric_work_release", how="done"),
                        release("mcp__fabric__fabric_work_release_all", how="done"),
                        release(how="done", response={"isError": True, "content": []}),
                        release(how="let-go", outcome="done"),
                        release("mcp__fabric__fabric_task_release", how="succeeded"),
                        release(how="done", response=[{"type": "text", "text":
                                                       '{"released": false, "code": "not-held", "reason": "x"}'}]),
                        release(how="done", response='{"released": false, "code": "bad-input"}'),
                        release(how="done", response={"released": False, "code": "not-yours"}),
                        release(how="done", response={"content": [{"type": "text", "text": '{"released": false}'}]}),
                        release("mcp__fabric__fabric_task_release", outcome="succeeded",
                                response=[{"type": "text", "text": '{"released": false, "reason": "you do not hold that task"}'}]),
                        release(how="done", response={"released": "true"}),
                        release(how="done", response={"structuredContent": {"released": False, "code": "partial"}}),
                        {"tool_name": "mcp__fabric__fabric_work_release", "tool_input": "done"},
                        {"tool_name": None, "tool_input": {"how": "done"}}, [], None, "x"):
            with self.subTest(payload=payload):
                self.assertFalse(cli.released_done(payload))


class Facade(unittest.TestCase):
    def test_the_facade_exports_the_hook(self):
        said = json.loads(fs.hook_post_tool_use(release(how="done")))
        self.assertEqual(said["hookSpecificOutput"]["additionalContext"], fs.RETRO_LINE)
        self.assertIsNone(fs.hook_post_tool_use(release(how="let-go")))
        self.assertEqual(set(fs.RETRO_DONE), {"fabric_work_release", "fabric_task_release"})


class Registration(unittest.TestCase):
    def test_hooks_json_registers_the_release_tools_only(self):
        hooks = json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]["PostToolUse"]
        self.assertEqual(len(hooks), 1)
        matcher = re.compile(hooks[0]["matcher"])
        for name in ("mcp__fabric__fabric_work_release", "mcp__fabric__fabric_task_release",
                     "mcp__plugin_x_fabric__fabric_work_release"):
            self.assertTrue(matcher.fullmatch(name), name)
        for name in ("mcp__fabric__fabric_work_claim", "Bash", "mcp__fabric__fabric_whoami", "fabric_work_release"):
            self.assertFalse(matcher.fullmatch(name), name)
        (command,) = hooks[0]["hooks"]
        self.assertEqual(command["timeout"], 5)
        self.assertTrue(command["command"].endswith("fabric_session.py\" hook post-tool-use"), command["command"])


class Hook(Base):
    def test_the_hook_says_the_line_after_a_done_release_and_nothing_else(self):
        started = time.perf_counter()
        done, _ = self.run_hook("post-tool-use", release(how="done", taskId="t1"))
        self.assertLess(time.perf_counter() - started, 5.0, "the hook's timeout in hooks.json is 5 s")
        self.assertEqual(done.returncode, 0)
        said = json.loads(done.stdout)["hookSpecificOutput"]
        self.assertEqual(said, {"hookEventName": "PostToolUse", "additionalContext": cli.RETRO_LINE})
        refused = [{"type": "text", "text": '{"released": false, "code": "not-held"}'}]
        for payload in (release(how="let-go"), release("mcp__fabric__fabric_work_claim", how="done"),
                        release(how="done", response={"isError": True}), release(how="done", response=refused),
                        "not json", ""):
            with self.subTest(payload=payload):
                quiet, _ = self.run_hook("post-tool-use", payload)
                self.assertEqual((quiet.returncode, quiet.stdout), (0, ""))

    def test_other_hosts_get_no_post_tool_hook(self):
        for host in ("codex", "kimi", "hermes"):
            done, _ = self.run_hook("post-tool-use", release(how="done"), args=("--host", host))
            self.assertEqual((done.returncode, done.stdout), (0, ""), host)


if __name__ == "__main__":
    unittest.main()
