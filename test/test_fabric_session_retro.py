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


def _nested(value, depth):
    for _ in range(depth):
        value = {"structuredContent": value}
    return value


def release(name="mcp__fabric__fabric_work_release", response=None, **given):
    payload = {"hook_event_name": "PostToolUse", "tool_name": name, "tool_input": given}
    if response is not None:
        payload["tool_response"] = response
    return payload


class Words(unittest.TestCase):
    def test_the_line_says_what_fabric_asks(self):
        for word in ("released this work as done", "in this turn", "`observatory_lesson`", "one class key per lesson",
                     "insight/1", "the project's `insights/` folder (outside the repository when that is public)", "one line that says so", "Without `observatory_lesson`, say it in this turn's answer",
                     "No values"):
            self.assertIn(word, cli.RETRO_LINE)
        # 0.64.0 product reading 2: the line names the retro itself (Fabric's fabric_whoami asks it only since 0.3.16)
        self.assertNotIn("fabric_whoami", cli.RETRO_LINE)
        self.assertNotIn("—", cli.RETRO_LINE)

    def test_the_preamble_names_the_retro_at_the_end(self):
        text = " ".join(cli.PREAMBLE.split())
        # self-contained: Fabric 0.3.15 and earlier do not carry retro-after-work (0.64.0 seam reading 1)
        self.assertIn("When a piece of work ends (released as done, or the session about to end), write its retro in "
                      "the same turn: `observatory_lesson` for what went wrong (or your answer without it), insight/1 "
                      "lines in the project's `insights/` (outside the repository when that is public) for what you learned, or one line that there is nothing.", text)
        self.assertNotIn("—", text)


class Released(unittest.TestCase):
    def test_a_release_of_finished_work_is_done(self):
        for payload in (release(how="done"), release(outcome="done"), release(how="done", taskId="t"),
                        release("mcp__plugin_x_fabric__fabric_work_release", how="done"),
                        release("mcp__fabric__fabric_task_release", outcome="succeeded"),
                        release(how="done", response={"released": True}),
                        release(how="done", response=[{"type": "text", "text": "ok"}]),
                        release(how="done", response=[{"type": "text", "text": '{"released": true, "claims": ["c1"]}'}]),
                        release(how="done", taskId="t", response=[{"type": "text", "text":
                            '{"released": true, "claim_id": "c", "how": "done", "task_moved_to": null, "seq": 7, '
                            '"code": "task-not-moved"}'}]),
                        release(how="done", response={"content": [{"type": "text", "text": '{"released": true}'}]}),
                        release(how="done", response={"structuredContent": {"released": True}}),
                        release(how="done", response='{"released": true}'),
                        release(how="done", response="[1]"),
                        release(how="done", response="null"),
                        release(how="done", response={"structuredContent": {"ok": True}}),
                        release(how="done", response={"released": 1}),
                        release(how="done", response={"released": 0}),
                        release("mcp__fabric__fabric_task_release", outcome="succeeded",
                                response={"released": True, "at": "2026-11-05T10:00:00Z"}),
                        release(how="done", response=_nested({"released": False}, 8)),
                        release(how="done", response={"released": ["c1"]}),
                        release(how="done", response="[" * 100000 + "]" * 100000),
                        release(how="done", response=[{"type": "image", "text": '{"released": false}'}]),
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
                        release(how="done", response=json.dumps({"content": [{"type": "text",
                                                                                "text": '{"released": false}'}]})),
                        release(how="done", response=[{"type": "text", "text": '{"released": false, "code": "x"}'},
                                                      {"type": "text", "text": "more"}]),
                        release("mcp__my_fabric__fabric_work_release", how="done"),
                        release(how="done", response=[{"type": "text", "text": "note"},
                                                      {"type": "text", "text": '{"released": false}'}]),
                        release(how="done", response=json.dumps([{"type": "text", "text": '{"released": false}'}])),
                        release(how="done", response={"structuredContent": {"ok": 1}, "content": [
                            {"type": "text", "text": '{"released": false}'}]}),
                        release("xmcp__fabric__fabric_work_release", how="done"),
                        release(how="done", response={"released": True, "code": "already-released"}),
                        release(how="done", taskId="t", response=[{"type": "text", "text":
                            '{"released": true, "claim_id": "c", "how": "done", "at": "2026-11-05T10:00:00Z", '
                            '"task_moved_to": null, "code": "task-not-moved"}'}]),
                        release(how="done", taskId="t", response={"released": False, "code": "released-by-operator",
                                                                  "at": "2026-11-05T10:00:00Z"}),
                        release(how="done", claims="session", response=[{"type": "text", "text":
                            '{"released": true, "claims": [], "note": "this session holds no live claim"}'}]),
                        release("mcp__evil__fabric_work_release", how="done"),
                        release("mcp__plugin_x__fabric_work_release", how="done"),
                        release("mcp__a__fabric__fabric_work_release", how="done"),
                        release("mcp__fabric__x__fabric_work_release", how="done"),
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
        matcher = re.compile(hooks[0]["matcher"])  # Claude Code tests it unanchored (RegExp.test), as re.search does
        for name in ("mcp__fabric__fabric_work_release", "mcp__fabric__fabric_task_release",
                     "mcp__plugin_x_fabric__fabric_work_release"):
            self.assertTrue(matcher.search(name), name)
        for name in ("mcp__fabric__fabric_work_claim", "Bash", "mcp__fabric__fabric_whoami", "fabric_work_release",
                     "mcp__evil__fabric_work_release", "mcp__fabric__fabric_work_release_all",
                     "xmcp__fabric__fabric_work_release", "mcp__plugin_x__fabric_work_release",
                     "mcp__my_fabric__fabric_work_release", "mcp__plugin_x_fabric__fabric_work_release__x"):
            self.assertFalse(matcher.search(name), name)
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

    def test_a_note_in_cyrillic_reaches_the_hook_whatever_the_locale(self):
        # 0.64.0 seam reading 5: the host writes UTF-8; Windows before 3.15 decodes a text stream with its code page
        import subprocess, sys
        payload = json.dumps(release(how="done", note="Сделано, тесты зелёные"), ensure_ascii=False).encode("utf-8")
        script = ROOT / "plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/fabric_session.py"
        for encoding in ("cp1252", "cp1251", "utf-8"):
            done = subprocess.run([sys.executable, "-S", str(script), "hook", "post-tool-use"], input=payload,
                                  capture_output=True, env=dict(self.env, PYTHONIOENCODING=encoding), timeout=10)
            self.assertEqual(done.returncode, 0, encoding)
            self.assertIn(b"PostToolUse", done.stdout, encoding)

    def _raw(self, payload):
        import subprocess, sys
        script = ROOT / "plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/fabric_session.py"
        return subprocess.run([sys.executable, "-S", str(script), "hook", "post-tool-use"], input=payload,
                              capture_output=True, env=dict(self.env, PYTHONIOENCODING="cp1252"), timeout=20)

    def test_the_input_is_read_as_its_bytes(self):
        # FAA-210: a BOM, a long Cyrillic note under the cap and a stray byte are read; a payload over the cap is not
        body = json.dumps(release(how="done", note="Сделано"), ensure_ascii=False).encode("utf-8")
        self.assertIn(b"PostToolUse", self._raw(b"\xef\xbb\xbf" + body).stdout, "a UTF-8 BOM")
        long_note = json.dumps(release(how="done", note="ж" * 700000), ensure_ascii=False).encode("utf-8")
        self.assertGreater(len(long_note), 1024 * 1024)
        self.assertIn(b"PostToolUse", self._raw(long_note).stdout, "about 1.4 MB of Cyrillic, under the cap")
        stray = body.replace("Сделано".encode("utf-8"), b"\xff\xfe")
        self.assertIn(b"PostToolUse", self._raw(stray).stdout, "a byte that is no UTF-8 reads as a replacement")
        over = json.dumps(release(how="done", note="x" * (cli.HOOK_INPUT_CAP + 10))).encode("utf-8")
        done = self._raw(over)
        self.assertEqual((done.returncode, done.stdout), (0, b""), "over the cap is read as nothing")

    def test_the_cap_and_a_text_stream_in_process(self):
        # FAA-210: exactly the cap is read, one byte over it is nothing; a stream with no bytes buffer drops its BOM
        import io
        from unittest import mock

        class Bytes:
            def __init__(self, data):
                self.buffer = io.BytesIO(data)

            def isatty(self):
                return False

        body = json.dumps({"hook_event_name": "PostToolUse"}).encode("utf-8")
        exact = body + b" " * (cli.HOOK_INPUT_CAP - len(body))
        with mock.patch.object(cli.sys, "stdin", Bytes(exact)):
            self.assertEqual(cli.read_hook_input(), {"hook_event_name": "PostToolUse"}, "exactly the cap")
        with mock.patch.object(cli.sys, "stdin", Bytes(exact + b" ")):
            self.assertEqual(cli.read_hook_input(), {}, "one byte over the cap")
        with mock.patch.object(cli.sys, "stdin", io.StringIO("\ufeff" + body.decode("utf-8"))):
            self.assertEqual(cli.read_hook_input(), {"hook_event_name": "PostToolUse"}, "a text stream with a BOM")

    def test_other_hosts_get_no_post_tool_hook(self):
        for host in ("codex", "kimi", "hermes"):
            done, _ = self.run_hook("post-tool-use", release(how="done"), args=("--host", host))
            self.assertEqual((done.returncode, done.stdout), (0, ""), host)


if __name__ == "__main__":
    unittest.main()
