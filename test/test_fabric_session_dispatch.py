"""FAA-201: a session Fabric started on a board request (Fabric's spec at c02e97c2, sections 3.4 to 3.6, and its
answer of 2026-11-04 on the first line). The session is told by FABRIC_DISPATCH_WORKFLOW, FABRIC_DISPATCH_HANDOFF and
FABRIC_DISPATCH_REQUEST, or by its prompt's first line `fabric-dispatch/1 workflow=... handoff=... request=...`; its
hooks then print the exit contract in place of the usual preamble, and the environment wins over the line."""
from __future__ import annotations

import importlib
import json
import unittest

from test_fabric_session import Base, SID, fs

cli = importlib.import_module("fabric_session_cli")

WF = "wf_0123456789abcdef"
HANDOFF = "handoff:5f0e9c2a-1b7d-4c3e-9a8f-2d6b4e1c7a90"
REQUEST = "262ff4f7-6ba0-4a84-9704-cf830ace244d"
ENV = {"FABRIC_DISPATCH_WORKFLOW": WF, "FABRIC_DISPATCH_HANDOFF": HANDOFF, "FABRIC_DISPATCH_REQUEST": REQUEST}
LINE = "fabric-dispatch/1 workflow=%s handoff=%s request=%s" % (WF, HANDOFF, REQUEST)


class Parsing(unittest.TestCase):
    def test_the_environment_names_a_dispatch(self):
        self.assertEqual(cli.dispatch_from_env(ENV), {"workflow": WF, "handoff": HANDOFF, "request": REQUEST})

    def test_a_partial_or_malformed_environment_names_none(self):
        for broken in ({"FABRIC_DISPATCH_WORKFLOW": WF},
                       dict(ENV, FABRIC_DISPATCH_WORKFLOW="wf_0123"),
                       dict(ENV, FABRIC_DISPATCH_WORKFLOW="WF_0123456789ABCDEF"),
                       dict(ENV, FABRIC_DISPATCH_HANDOFF="5f0e9c2a"),
                       dict(ENV, FABRIC_DISPATCH_HANDOFF="handoff:a b"),
                       dict(ENV, FABRIC_DISPATCH_REQUEST="not-a-uuid"),
                       dict(ENV, FABRIC_DISPATCH_REQUEST=REQUEST + "\n")):
            self.assertIsNone(cli.dispatch_from_env(broken), broken)
        self.assertIsNone(cli.dispatch_from_env({}))

    def test_the_first_line(self):
        self.assertEqual(cli.dispatch_from_line(LINE + "\n\nAnswer the request."),
                         {"workflow": WF, "handoff": HANDOFF, "request": REQUEST})
        self.assertEqual(cli.dispatch_from_line(LINE), {"workflow": WF, "handoff": HANDOFF, "request": REQUEST})

    def test_only_the_exact_first_line(self):
        for text in ("Answer it.\n" + LINE,                                   # not the first line
                     LINE.replace(" handoff", "  handoff"),                    # two spaces
                     "fabric-dispatch/1 handoff=%s workflow=%s request=%s" % (HANDOFF, WF, REQUEST),  # another order
                     "fabric-dispatch/2" + LINE[len("fabric-dispatch/1"):],    # another revision
                     " " + LINE, LINE + " extra=1", "", None, 7):
            self.assertIsNone(cli.dispatch_from_line(text), text)

    def test_the_environment_wins_and_a_mismatch_is_named(self):
        other = LINE.replace(REQUEST, "11111111-2222-4333-8444-555555555555")
        dispatch, mismatch = cli.dispatch_of(ENV, other)
        self.assertEqual(dispatch["request"], REQUEST)
        self.assertEqual(mismatch, ["request"])
        self.assertEqual(cli.dispatch_of(ENV, LINE), (cli.dispatch_from_env(ENV), []))
        self.assertEqual(cli.dispatch_of({}, LINE), (cli.dispatch_from_line(LINE), []))
        self.assertEqual(cli.dispatch_of({}, "hello"), (None, []))

    def test_the_contract_names_the_steps_and_no_dash(self):
        text = cli.dispatch_contract({"workflow": WF, "handoff": HANDOFF, "request": REQUEST}, ["request"])
        for word in (WF, HANDOFF, REQUEST, "observatory_checkpoint_latest", "observatory_handoff_accept",
                     "com.claim", "com.reply", "com.complete", "failed_known", "close", "never wait for a person",
                     "fabric_effect_request", "request"):
            self.assertIn(word, text)
        self.assertNotIn("—", text)
        self.assertNotIn("fabric_whoami` first", text)


class Hooks(Base):
    def test_session_start_prints_the_contract_in_place_of_the_preamble(self):
        self.register()
        self.hub()
        (self.repo / "fabric-agent.json").write_text("{}")
        done, elapsed = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "startup"},
                                      extra_env=ENV)
        self.assertEqual(done.returncode, 0, done.stderr)
        context = json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(context, cli.dispatch_contract(cli.dispatch_from_env(ENV), []))
        self.assertNotEqual(context, fs.PREAMBLE.format(host="Claude Code"))
        self.assertLess(elapsed, 2.0)

    def test_the_contract_does_not_wait_for_a_registration_or_a_project_sign(self):
        # The dispatcher starts the run in the project's folder; the contract tells it how to end even when the hook
        # cannot see `fabric` registered or Fabric running (it then completes nothing and says so).
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "startup"},
                                extra_env=ENV)
        self.assertIn(WF, json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_codex_and_kimi_get_the_contract(self):
        for host, plain in (("codex", False), ("kimi", True)):
            done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "startup"},
                                    extra_env=ENV, args=("--host", host))
            text = done.stdout if plain else json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("observatory_handoff_accept", text, host)

    def test_a_resumed_dispatch_is_quiet(self):
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "resume"},
                                extra_env=ENV)
        self.assertEqual(done.stdout, "")

    def test_the_first_prompt_tells_a_session_with_no_environment(self):
        payload = {"session_id": SID, "cwd": str(self.repo), "prompt": LINE + "\n\nAnswer the request."}
        done, _ = self.run_hook("user-prompt-submit", payload)
        self.assertEqual(done.returncode, 0, done.stderr)
        context = json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(REQUEST, context)
        self.assertIn("observatory_handoff_accept", context)
        done, _ = self.run_hook("user-prompt-submit", dict(payload, prompt="And then?"))
        self.assertEqual(done.stdout, "", "a later prompt without the line adds nothing")

    def test_a_first_prompt_that_disagrees_with_the_environment(self):
        other = LINE.replace(REQUEST, "11111111-2222-4333-8444-555555555555")
        done, _ = self.run_hook("user-prompt-submit", {"session_id": SID, "cwd": str(self.repo), "prompt": other},
                                extra_env=ENV)
        context = json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(REQUEST, context)
        self.assertNotIn("11111111-2222", context)
        self.assertIn("disagrees", context)

    def test_a_dispatch_line_the_environment_already_told_adds_nothing(self):
        done, _ = self.run_hook("user-prompt-submit", {"session_id": SID, "cwd": str(self.repo), "prompt": LINE},
                                extra_env=ENV)
        self.assertEqual(done.stdout, "", "session start already printed the contract")


if __name__ == "__main__":
    unittest.main()
