"""FAA-201: a session Fabric started on a board request (Fabric's spec at 1329b60f, sections 3.4 to 3.6). The session is
told by FABRIC_DISPATCH_WORKFLOW (alone is enough: Switchboard's SB-247 sets only it), with FABRIC_DISPATCH_HANDOFF and
FABRIC_DISPATCH_REQUEST when the launcher sets them; the prompt's first line `fabric-dispatch/1 workflow=... handoff=...
request=...` fills what the environment left out and never wins over it. A line with no workflow in the environment is
quoted text. The hooks print the exit contract in place of the usual preamble, launched by Fabric or not."""
from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path

from test_fabric_session import Base, SID, fs

cli = importlib.import_module("fabric_session_cli")

WF = "wf_0123456789abcdef"
HANDOFF = "handoff:5f0e9c2a1b7d4c3e"
REQUEST = "262ff4f7-6ba0-4a84-9704-cf830ace244d"
ENV = {"FABRIC_DISPATCH_WORKFLOW": WF, "FABRIC_DISPATCH_HANDOFF": HANDOFF, "FABRIC_DISPATCH_REQUEST": REQUEST}
LINE = "fabric-dispatch/1 workflow=%s handoff=%s request=%s" % (WF, HANDOFF, REQUEST)
FULL = {"workflow": WF, "handoff": HANDOFF, "request": REQUEST}


class Parsing(unittest.TestCase):
    def test_the_environment_names_a_dispatch(self):
        self.assertEqual(cli.dispatch_from_env(ENV), FULL)

    def test_the_workflow_alone_names_a_dispatch(self):
        # Switchboard's SB-247 (e0309b2) sets FABRIC_DISPATCH_WORKFLOW and SWITCHBOARD_LAUNCH_ID only (0.63.0 seam r1)
        self.assertEqual(cli.dispatch_from_env({"FABRIC_DISPATCH_WORKFLOW": WF, "SWITCHBOARD_LAUNCH_ID": "l-1"}),
                         {"workflow": WF})
        for name, value in (("FABRIC_DISPATCH_HANDOFF", "5f0e9c2a"), ("FABRIC_DISPATCH_HANDOFF", "handoff:a b"),
                            ("FABRIC_DISPATCH_REQUEST", "not-a-uuid"), ("FABRIC_DISPATCH_REQUEST", REQUEST + "\n")):
            told = cli.dispatch_from_env(dict(ENV, **{name: value}))
            self.assertEqual(told["workflow"], WF)
            self.assertNotIn(name.rsplit("_", 1)[1].lower(), told, "a malformed value is left out")

    def test_a_missing_or_malformed_workflow_names_none(self):
        for broken in (dict(ENV, FABRIC_DISPATCH_WORKFLOW="wf_0123"),
                       dict(ENV, FABRIC_DISPATCH_WORKFLOW="WF_0123456789ABCDEF"),
                       {k: v for k, v in ENV.items() if k != "FABRIC_DISPATCH_WORKFLOW"}, {}):
            self.assertIsNone(cli.dispatch_from_env(broken), broken)

    def test_the_first_line(self):
        self.assertEqual(cli.dispatch_from_line(LINE + "\n\nAnswer the request."), FULL)
        self.assertEqual(cli.dispatch_from_line(LINE), FULL)
        self.assertEqual(cli.dispatch_from_line(LINE + "\r\n\r\nAnswer the request."), FULL, "a CRLF line")

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
        self.assertEqual(cli.dispatch_of(ENV, LINE), (FULL, []))
        self.assertEqual(cli.dispatch_of({}, LINE), (None, []), "a line with no workflow in the environment is text")
        self.assertEqual(cli.dispatch_of({}, "hello"), (None, []))

    def test_the_line_fills_what_the_environment_left_out_for_the_same_workflow(self):
        only = {"FABRIC_DISPATCH_WORKFLOW": WF}
        self.assertEqual(cli.dispatch_of(only, LINE), (FULL, []))
        other = LINE.replace(WF, "wf_fedcba9876543210")
        self.assertEqual(cli.dispatch_of(only, other), ({"workflow": WF}, ["workflow"]), "another workflow fills nothing")

    def test_the_contract_names_the_steps_and_no_dash(self):
        text = cli.dispatch_contract(FULL, ["request"])
        for word in (WF, HANDOFF, REQUEST, "fabric_whoami", "observatory_checkpoint_latest", "com.get",
                     "observatory_handoff_accept", "owner", "idempotencyKey", "executor", "leaseId", "com.enroll",
                     "com.claim", "com.accept", "com.effect_begin", "com.responder_replace", "com.reconcile",
                     "com.renew", "com.progress", "run-ends-at", "com.reply", "com.complete", "failed_known",
                     "observatory_checkpoint_write", "stepId", "goal", "close: true", "OBS-323", "blocked",
                     "never wait for a person", "fabric_effect_request", "on-demand-session.md", "disagrees"):
            self.assertIn(word, text)
        self.assertNotIn("—", text)

    def test_the_closing_write_names_its_workflow_and_the_board_reads_are_real_tools(self):
        # 0.63.0 readings 2: a checkpoint_write without workflowId starts a new workflow; com.get takes a message id
        text = cli.dispatch_contract(FULL)
        step6 = text[text.index(" 6. "):text.index(" 7. ")]
        self.assertIn("`workflowId` %s" % WF, step6)
        for word in ("`com.get` {message: <request>}", "`com.list` {thread: <board-thread>}", "`com.status`",
                     "expectedGeneration", "in_progress checkpoint", "the launcher's prompt names"):
            self.assertIn(word, text)
        self.assertNotIn("earlier checkpoints", text, "Observatory has no tool that reads them")
        for word in ("repeats the packet's `goal`, `constraints`, `artifacts` and `credentials`", "its goal names the request",
                     "the packet's body with `done` and `notes` added"):
            self.assertIn(word, text, "Observatory keeps only the latest body (0.63.0 readings 3)")

    def test_the_contract_points_at_the_packet_for_what_the_environment_left_out(self):
        text = cli.dispatch_contract({"workflow": WF})
        self.assertIn(WF, text)
        self.assertIn("the handoff the packet names", text)
        self.assertIn("the request the packet names", text)

    def test_the_statuses_the_contract_names_are_observatorys(self):
        # Observatory's checkpoint_write takes in_progress, done and blocked today; failed arrives with OBS-323
        text = cli.dispatch_contract(FULL)
        self.assertIn("done for completed", text)
        self.assertIn("until then blocked", text)


class Hooks(Base):
    def start(self, env):
        return self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "startup"},
                             extra_env=env)

    def prompt(self, env, text):
        return self.run_hook("user-prompt-submit", {"session_id": SID, "cwd": str(self.repo), "prompt": text},
                             extra_env=env)

    @staticmethod
    def context(done):
        return json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_session_start_prints_the_contract_in_place_of_the_preamble(self):
        self.register()
        self.hub()
        (self.repo / "fabric-agent.json").write_text("{}")
        done, elapsed = self.start(ENV)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.context(done), cli.dispatch_contract(FULL))
        self.assertNotEqual(self.context(done), fs.PREAMBLE.format(host="Claude Code"))
        self.assertLess(elapsed, 2.0)

    def test_switchboards_environment_gets_the_contract_not_the_preamble(self):
        self.register()
        self.hub()
        (self.repo / "fabric-agent.json").write_text("{}")
        sb = {"FABRIC_DISPATCH_WORKFLOW": WF, "SWITCHBOARD_LAUNCH_ID": "launch-1"}
        done, _ = self.start(sb)
        self.assertEqual(self.context(done), cli.dispatch_contract({"workflow": WF}))
        self.assertNotIn("fabric_work_claim", self.context(done))
        context = self.context(self.prompt(sb, LINE)[0])
        self.assertIn(HANDOFF, context, "the line adds the handoff the environment left out")
        self.assertIn(REQUEST, context)

    def test_the_contract_does_not_wait_for_a_registration_or_a_project_sign(self):
        self.assertIn(WF, self.context(self.start(ENV)[0]))

    def test_codex_and_kimi_get_the_contract(self):
        for host, plain in (("codex", False), ("kimi", True)):
            done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "startup"},
                                    extra_env=ENV, args=("--host", host))
            text = done.stdout if plain else self.context(done)
            self.assertIn("observatory_handoff_accept", text, host)

    def test_a_resumed_dispatch_is_quiet(self):
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "resume"},
                                extra_env=ENV)
        self.assertEqual(done.stdout, "")

    def test_a_launched_session_on_a_request_gets_the_contract(self):
        for marker in ({"FABRIC_LAUNCHED_SESSION": "1"}, {"FABRIC_ACP_SESSION": "x"}):
            with self.subTest(marker=marker):
                self.assertIn(WF, self.context(self.start(dict(ENV, **marker))[0]))
                only = dict({"FABRIC_DISPATCH_WORKFLOW": WF}, **marker)
                self.assertIn(REQUEST, self.context(self.prompt(only, LINE)[0]))
                self.assertEqual(self.prompt(only, "hi")[0].stdout, "", "a launched session gets nothing else")

    def test_a_line_without_the_environment_is_quoted_text(self):
        # 0.63.0 seam r1: a pasted board message in an interactive session is not a dispatch
        done, _ = self.prompt({}, LINE + "\n\nAnswer the request.")
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_a_first_prompt_that_disagrees_with_the_environment(self):
        other = LINE.replace(REQUEST, "11111111-2222-4333-8444-555555555555")
        context = self.context(self.prompt(ENV, other)[0])
        self.assertIn(REQUEST, context)
        self.assertNotIn("11111111-2222", context)
        self.assertIn("disagrees", context)

    def test_a_session_inside_the_run_is_told_the_run_holds_the_dispatch(self):
        # 0.63.0 seam r2: `claude -p` from the run's own shell inherits FABRIC_DISPATCH_*
        other = "4c1d2e3f-0a1b-4c5d-8e9f-0123456789ab"
        self.assertIn("observatory_handoff_accept", self.context(self.start(ENV)[0]))
        done, _ = self.run_hook("session-start", {"session_id": other, "cwd": str(self.repo), "source": "startup"},
                                extra_env=ENV)
        nested = self.context(done)
        self.assertEqual(nested, cli.DISPATCH_NESTED.format(workflow=WF))
        for word in ("observatory_handoff_accept", "com.responder_replace", "com.claim`"):
            self.assertNotIn(word, nested)
        self.assertIn("observatory_handoff_accept", self.context(self.start(ENV)[0]), "the holder is told again")
        sb = {"FABRIC_DISPATCH_WORKFLOW": WF, "SWITCHBOARD_LAUNCH_ID": "launch-1"}
        self.start(sb)
        done, _ = self.run_hook("user-prompt-submit", {"session_id": other, "cwd": str(self.repo), "prompt": LINE},
                                extra_env=sb)
        self.assertEqual(done.stdout, "", "the line adds nothing to a nested session")

    def test_a_new_launch_of_the_same_workflow_is_a_new_holder(self):
        # 0.63.0 unit r3: spec 3.6 lets the next cycle dispatch the same workflow once more
        other = "4c1d2e3f-0a1b-4c5d-8e9f-0123456789ab"
        first = dict(ENV, SWITCHBOARD_LAUNCH_ID="launch-1")
        second = dict(ENV, SWITCHBOARD_LAUNCH_ID="launch-2")
        self.assertIn("observatory_handoff_accept", self.context(self.start(first)[0]))
        done, _ = self.run_hook("session-start", {"session_id": other, "cwd": str(self.repo), "source": "startup"},
                                extra_env=second)
        self.assertIn("observatory_handoff_accept", self.context(done))
        wf_only = {"FABRIC_DISPATCH_WORKFLOW": WF, "SWITCHBOARD_LAUNCH_ID": "launch-3"}
        done, _ = self.run_hook("session-start", {"session_id": other, "cwd": str(self.repo), "source": "startup"},
                                extra_env=wf_only)
        self.assertIn("observatory_handoff_accept", self.context(done))

    def test_the_dispatch_id_keys_the_holder_when_it_is_set(self):
        other = "4c1d2e3f-0a1b-4c5d-8e9f-0123456789ab"
        one = dict(ENV, FABRIC_DISPATCH_ID="d-1", SWITCHBOARD_LAUNCH_ID="launch-1")
        self.assertIn("observatory_handoff_accept", self.context(self.start(one)[0]))
        same = dict(one, SWITCHBOARD_LAUNCH_ID="launch-other")  # the dispatch id, not the launch id, decides
        done, _ = self.run_hook("session-start", {"session_id": other, "cwd": str(self.repo), "source": "startup"},
                                extra_env=same)
        self.assertEqual(self.context(done), cli.DISPATCH_NESTED.format(workflow=WF))
        again = dict(ENV, FABRIC_DISPATCH_ID="d-2", SWITCHBOARD_LAUNCH_ID="launch-1")
        done, _ = self.run_hook("session-start", {"session_id": other, "cwd": str(self.repo), "source": "startup"},
                                extra_env=again)
        self.assertIn("observatory_handoff_accept", self.context(done), "a new dispatch is a new holder")

    def test_the_holder_fails_open(self):
        from unittest import mock
        env = dict(self.env, **ENV)
        self.assertTrue(cli.dispatch_holder(FULL, "../not one", env), "an id that is not one")
        self.assertTrue(cli.dispatch_holder(FULL, None, env))
        with mock.patch.object(cli.os, "fdopen", side_effect=OSError(28, "No space left on device")):
            self.assertTrue(cli.dispatch_holder(FULL, SID, env), "a full disk")
        folder = cli.state_root(env=env) / "dispatch"
        self.assertEqual([p for p in folder.glob("*.json") if p.stat().st_size == 0], [], "no half record is left")
        self.assertTrue(cli.dispatch_holder(FULL, SID, env), "the same session holds it after the failed write")
        blocked = dict(env, HOME=str(self.base / "nowhere-file"))
        (self.base / "nowhere-file").write_text("x")  # a file where the home folder should be: nothing can be made
        self.assertTrue(cli.dispatch_holder(FULL, SID, blocked), "a folder that cannot be made")
        record = next(folder.glob("*.json"))
        record.write_text("not json")
        self.assertFalse(cli.dispatch_holder(FULL, "4c1d2e3f-0a1b-4c5d-8e9f-0123456789ab", env),
                         "an unreadable record is held by someone else")

    def test_old_dispatch_records_are_pruned(self):
        import os, time
        env = dict(self.env, **ENV)
        cli.dispatch_holder(FULL, SID, env)
        cli.dispatch_holder(dict(FULL, handoff="handoff:ffffffffffffffff"), SID, env)
        folder = cli.state_root(env=env) / "dispatch"
        old, fresh = sorted(folder.glob("*.json"))
        os.utime(old, (1, 1))
        fs.prune_stale_sessions(env=env, now=time.time())
        self.assertEqual(list(folder.glob("*.json")), [fresh])

    def test_a_clear_in_the_holder_keeps_the_contract(self):
        # 0.63.0 seam r3: /clear gives the same run a new session id; a nested claude -p starts with `startup`
        cleared, nested = "4c1d2e3f-0a1b-4c5d-8e9f-0123456789ab", "5d2e3f40-1b2c-4d6e-9fa0-123456789abc"
        self.assertIn("observatory_handoff_accept", self.context(self.start(ENV)[0]))
        done, _ = self.run_hook("session-start", {"session_id": cleared, "cwd": str(self.repo), "source": "clear"},
                                extra_env=ENV)
        self.assertIn("observatory_handoff_accept", self.context(done))
        done, _ = self.run_hook("session-start", {"session_id": nested, "cwd": str(self.repo), "source": "startup"},
                                extra_env=ENV)
        self.assertEqual(self.context(done), cli.DISPATCH_NESTED.format(workflow=WF))

    def test_one_workflow_pattern_for_every_reader(self):
        dashboard_kit = (Path(cli.__file__).resolve().parents[2] / "building-fabric-services/scripts/dashboard_kit.py")
        env_module = importlib.import_module("fabric_session_env")
        self.assertIn('re.fullmatch(r"%s"' % env_module.DISPATCH_WORKFLOW, dashboard_kit.read_text())
        mail = importlib.import_module("fabric_session_mail")
        self.assertIs(mail.DISPATCH_WORKFLOW, env_module.DISPATCH_WORKFLOW)

    def test_watch_mail_refuses_a_dispatched_session(self):
        mail = importlib.import_module("fabric_session_mail")
        env = {"HOME": str(self.home), "FABRIC_DISPATCH_WORKFLOW": WF}
        import contextlib, io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(mail.watch_mail_cli(["--session-id", SID, "--cwd", str(self.repo)], env=env), 2)
        self.assertIn("started on a board request", err.getvalue())

    def test_a_dispatch_line_the_environment_already_told_adds_nothing(self):
        self.assertEqual(self.prompt(ENV, LINE)[0].stdout, "", "session start already printed the contract")


if __name__ == "__main__":
    unittest.main()
