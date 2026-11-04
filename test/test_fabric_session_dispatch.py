"""FAA-201: a session Fabric started on a board request (Fabric's spec, sections 3.4 to 3.6). A session is the run only
when its own prompt's first line `fabric-dispatch/1 workflow=... handoff=... request=...` names the same three as
FABRIC_DISPATCH_WORKFLOW, FABRIC_DISPATCH_HANDOFF and FABRIC_DISPATCH_REQUEST (spec 3.5, board thread 1add3c03): the
environment alone makes none. A line with no workflow in the environment is quoted text. Session start prints the exit
contract on that condition in place of the usual preamble; the prompt hook gives the verdict."""
from __future__ import annotations

import importlib
import json
import os
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
        # Switchboard's main at e0309b2, never released, set FABRIC_DISPATCH_WORKFLOW and SWITCHBOARD_LAUNCH_ID only
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

    def test_the_run_is_the_line_and_the_environment_naming_the_same_three(self):
        # Fabric's spec 3.5 (board thread 1add3c03): the environment alone makes no run
        other = LINE.replace(REQUEST, "11111111-2222-4333-8444-555555555555")
        self.assertEqual(cli.dispatch_of(ENV, LINE), (FULL, []))
        self.assertEqual(cli.dispatch_of(ENV, other), (None, ["request"]))
        self.assertEqual(cli.dispatch_of(ENV, "hello"), (None, []), "no line: a helper, no run")
        self.assertEqual(cli.dispatch_of({}, LINE), (None, []), "a line with no workflow in the environment is text")
        self.assertEqual(cli.dispatch_of({}, "hello"), (None, []))

    def test_an_environment_without_all_three_makes_no_run(self):
        only = {"FABRIC_DISPATCH_WORKFLOW": WF}
        self.assertEqual(cli.dispatch_of(only, LINE), (None, ["handoff", "request"]))
        self.assertFalse(cli.dispatch_complete(cli.dispatch_from_env(only)))
        self.assertTrue(cli.dispatch_complete(cli.dispatch_from_env(ENV)))
        other = LINE.replace(WF, "wf_fedcba9876543210")
        self.assertEqual(cli.dispatch_of(ENV, other), (None, ["workflow"]))

    def test_the_contract_names_the_steps_and_no_dash(self):
        text = cli.dispatch_contract(FULL, conditional=True)
        for word in (WF, HANDOFF, REQUEST, "fabric_whoami", "observatory_checkpoint_latest", "com.get",
                     "observatory_handoff_accept", "owner", "idempotencyKey", "executor", "leaseId", "com.enroll",
                     "com.claim", "com.accept", "com.effect_begin", "com.responder_replace", "com.reconcile",
                     "com.renew", "com.progress", "run-ends-at", "com.reply", "com.complete", "failed_known",
                     "observatory_checkpoint_write", "stepId", "goal", "close: true", "OBS-323", "blocked",
                     "never wait for a person", "fabric_effect_request", "on-demand-session.md", "a production step",
                     "only when its own prompt's first line is exactly `%s`" % LINE, "it is a helper",
                     "say so in the request's thread and stop"):
            self.assertIn(word, text)
        self.assertNotIn("—", text)

    def test_the_closing_write_names_its_workflow_and_the_board_reads_are_real_tools(self):
        # 0.63.0 readings 2: a checkpoint_write without workflowId starts a new workflow; com.get takes a message id
        text = cli.dispatch_contract(FULL)
        step6 = text[text.index(" 6. "):text.index(" 7. ")]
        self.assertIn("`workflowId` %s" % WF, step6)
        for word in ("`com.get` {message: <request>}", "`com.list` {thread: <the `thread` com.get answered>}", "`com.status`",
                     "expectedGeneration", "in_progress checkpoint", "the launcher's prompt names"):
            self.assertIn(word, text)
        self.assertNotIn("earlier checkpoints", text, "Observatory has no tool that reads them")
        for word in ("repeats `goal`, `constraints`, `artifacts` and `credentials` of `checkpoint.body`",
                     "its goal describes the request", "the packet's body with `done` and `notes` added"):
            self.assertIn(word, text, "Observatory keeps only the latest body (0.63.0 readings 3)")
        # 0.63.0 seam reading 4: Observatory's write redacts board-request:, board-thread: and fabric-project: refs,
        # and refuses the decorated credentials of the top-level answer or the accept's pack
        self.assertNotIn("<board-thread>", text)
        self.assertNotIn("its goal names the request", text)
        self.assertIn("never its top-level `credentials` or the accept answer's `pack`", text)

    def test_an_incomplete_environment_is_told_it_holds_no_run(self):
        text = cli.DISPATCH_INCOMPLETE.format(workflow=WF)
        for words in (WF, "no session here is a run", "Do the task you were given only",
                      "the launcher's environment lacks them"):
            self.assertIn(words, text)

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

    def test_session_start_prints_the_conditional_contract_in_place_of_the_preamble(self):
        self.register()
        self.hub()
        (self.repo / "fabric-agent.json").write_text("{}")
        done, elapsed = self.start(ENV)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.context(done), cli.dispatch_contract(FULL, SID, conditional=True))
        self.assertNotEqual(self.context(done), fs.PREAMBLE.format(host="Claude Code"))
        self.assertFalse((cli.state_root(env=self.env) / "dispatch").exists(), "the start elects no holder")
        self.assertLess(elapsed, 2.0)

    def test_an_environment_without_all_three_gets_the_incomplete_line(self):
        self.register()
        self.hub()
        (self.repo / "fabric-agent.json").write_text("{}")
        sb = {"FABRIC_DISPATCH_WORKFLOW": WF, "SWITCHBOARD_LAUNCH_ID": "launch-1"}
        self.assertEqual(self.context(self.start(sb)[0]), cli.DISPATCH_INCOMPLETE.format(workflow=WF))
        context = self.context(self.prompt(sb, LINE)[0])
        self.assertEqual(context, cli.DISPATCH_OTHER.format(fields="handoff, request"))

    def test_the_contract_does_not_wait_for_a_registration_or_a_project_sign(self):
        self.assertIn(WF, self.context(self.start(ENV)[0]))

    def test_codex_and_kimi_get_the_contract(self):
        for host, plain in (("codex", False), ("kimi", True)):
            done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "startup"},
                                    extra_env=ENV, args=("--host", host))
            text = done.stdout if plain else self.context(done)
            self.assertIn("observatory_handoff_accept", text, host)

    def test_a_native_bridge_is_always_told_the_contract_and_writes_no_record(self):
        # 0.63.0 seam reading 6: the bridges pass {cwd} and no session id; the contract is the conditional one
        for host in ("opencode", "hermes"):
            for _ in range(2):
                done, _ = self.run_hook("session-start", {"cwd": str(self.repo)},
                                        extra_env=dict(ENV, FABRIC_LAUNCHED_SESSION="1"), args=("--host", host))
                self.assertIn("observatory_handoff_accept", done.stdout, host)
                self.assertIn("only when its own prompt's first line", done.stdout, host)
        self.assertFalse((cli.state_root(env=self.env) / "dispatch").exists())
        longest = dict(FULL, handoff="handoff:" + "x" * 120)
        self.assertLess(len(cli.dispatch_contract(longest, conditional=True)), 4000, "Hermes' MAX_CONTEXT_CHARS")

    def test_a_resumed_dispatch_is_quiet(self):
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "resume"},
                                extra_env=ENV)
        self.assertEqual(done.stdout, "")

    def test_a_launched_session_on_a_request_gets_the_contract(self):
        for marker in ({"FABRIC_LAUNCHED_SESSION": "1"}, {"FABRIC_ACP_SESSION": "x"}):
            with self.subTest(marker=marker):
                self.assertIn(WF, self.context(self.start(dict(ENV, **marker))[0]))
                self.assertIn("this session is the run", self.context(self.prompt(dict(ENV, **marker), LINE)[0]))
                self.assertEqual(self.prompt(dict(ENV, **marker), "hi")[0].stdout, "", "nothing else")

    def test_a_line_without_the_environment_is_quoted_text(self):
        # 0.63.0 seam r1: a pasted board message in an interactive session is not a dispatch
        done, _ = self.prompt({}, LINE + "\n\nAnswer the request.")
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_a_first_prompt_that_disagrees_with_the_environment_is_no_run(self):
        other = LINE.replace(REQUEST, "11111111-2222-4333-8444-555555555555")
        context = self.context(self.prompt(ENV, other)[0])
        self.assertEqual(context, cli.DISPATCH_OTHER.format(fields="request"))
        for words in ("this session is no run", "Say so in the request's thread", "take nothing", "and stop"):
            self.assertIn(words, context)
        self.assertNotIn("observatory_handoff_accept", context)
        self.assertFalse((cli.state_root(env=self.env) / "dispatch").exists(), "no holder for a disagreeing line")

    def test_a_session_inside_the_run_is_told_the_run_holds_the_dispatch(self):
        # 0.63.0 seam r2: `claude -p` from the run's own shell inherits FABRIC_DISPATCH_*
        other = "4c1d2e3f-0a1b-4c5d-8e9f-0123456789ab"
        self.start(ENV)
        self.assertIn("this session is the run", self.context(self.prompt(ENV, LINE)[0]))
        done, _ = self.run_hook("session-start", {"session_id": other, "cwd": str(self.repo), "source": "startup"},
                                extra_env=ENV)
        self.assertIn("No such line: it is a helper", self.context(done), "a helper is told by the condition")
        done, _ = self.run_hook("user-prompt-submit", {"session_id": other, "cwd": str(self.repo), "prompt": "read it"},
                                extra_env=ENV)
        self.assertEqual(done.stdout, "", "a helper's own prompt makes no run")
        done, _ = self.run_hook("user-prompt-submit", {"session_id": other, "cwd": str(self.repo), "prompt": LINE},
                                extra_env=ENV)
        nested = self.context(done)
        self.assertEqual(nested, cli.DISPATCH_NESTED.format(workflow=WF), "the line again in another session")
        for word in ("observatory_handoff_accept", "com.responder_replace", "com.claim`"):
            self.assertNotIn(word, nested)
        self.assertIn("this session is the run", self.context(self.prompt(ENV, LINE)[0]), "the holder is told again")

    def test_a_new_launch_of_the_same_workflow_is_a_new_holder(self):
        # 0.63.0 unit r3: spec 3.6 lets the next cycle dispatch the same workflow once more
        other = "4c1d2e3f-0a1b-4c5d-8e9f-0123456789ab"
        first = dict(ENV, SWITCHBOARD_LAUNCH_ID="launch-1")
        second = dict(ENV, SWITCHBOARD_LAUNCH_ID="launch-2")
        self.assertIn("this session is the run", self.context(self.prompt(first, LINE)[0]))
        done, _ = self.run_hook("user-prompt-submit", {"session_id": other, "cwd": str(self.repo), "prompt": LINE},
                                extra_env=second)
        self.assertIn("this session is the run", self.context(done))

    def test_the_dispatch_id_keys_the_holder_when_it_is_set(self):
        other = "4c1d2e3f-0a1b-4c5d-8e9f-0123456789ab"
        one = dict(ENV, FABRIC_DISPATCH_ID="d-1", SWITCHBOARD_LAUNCH_ID="launch-1")
        self.assertIn("this session is the run", self.context(self.prompt(one, LINE)[0]))
        same = dict(one, SWITCHBOARD_LAUNCH_ID="launch-other")  # the dispatch id, not the launch id, decides
        done, _ = self.run_hook("user-prompt-submit", {"session_id": other, "cwd": str(self.repo), "prompt": LINE},
                                extra_env=same)
        self.assertEqual(self.context(done), cli.DISPATCH_NESTED.format(workflow=WF))
        again = dict(ENV, FABRIC_DISPATCH_ID="d-2", SWITCHBOARD_LAUNCH_ID="launch-1")
        done, _ = self.run_hook("user-prompt-submit", {"session_id": other, "cwd": str(self.repo), "prompt": LINE},
                                extra_env=again)
        self.assertIn("this session is the run", self.context(done), "a new dispatch is a new holder")

    def test_a_clear_with_no_record_or_a_corrupt_one_holds_nothing(self):
        # Fabric's spec 3.5: only a prompt's line makes the run, so a clear with no record of one holds no dispatch
        env = dict(self.env, **ENV)
        self.assertFalse(cli.dispatch_holder(FULL, SID, env, take_over=True))
        self.assertFalse((cli.state_root(env=env) / "dispatch").exists() and any(
            (cli.state_root(env=env) / "dispatch").glob("*.json")))
        cli.dispatch_holder(FULL, SID, env)
        record = next((cli.state_root(env=env) / "dispatch").glob("*.json"))
        record.write_text("not json")
        other = "4c1d2e3f-0a1b-4c5d-8e9f-0123456789ab"
        self.assertFalse(cli.dispatch_holder(FULL, other, env, take_over=True))
        self.assertEqual(record.read_text(), "not json", "a record that is not one is left alone")

    def test_on_windows_any_clear_takes_the_record(self):
        from unittest import mock
        env = dict(self.env, **ENV)
        with mock.patch.object(cli.os, "getppid", return_value=111):
            cli.dispatch_holder(FULL, SID, env)
        other = "4c1d2e3f-0a1b-4c5d-8e9f-0123456789ab"
        with mock.patch.object(cli.os, "getppid", return_value=222), mock.patch.object(cli, "_WINDOWS", True):
            self.assertTrue(cli.dispatch_holder(FULL, other, env, take_over=True), "a new Git Bash every hook")
        record = next((cli.state_root(env=env) / "dispatch").glob("*.json"))
        self.assertEqual(json.loads(record.read_text())["session"], other, "the record moved")
        with mock.patch.object(cli.os, "getppid", return_value=333):
            self.assertTrue(cli.dispatch_holder(FULL, other, env), "the cleared session holds it at its next prompt")
            self.assertFalse(cli.dispatch_holder(FULL, SID, env))

    def test_a_clear_moves_the_record_only_in_the_holders_process(self):
        from unittest import mock
        env = dict(self.env, **ENV)
        nested, nested2, cleared = ("4c1d2e3f-0a1b-4c5d-8e9f-0123456789ab", "5d2e3f40-1b2c-4d6e-9fa0-123456789abc",
                                    "6e3f4051-2c3d-4e7f-8a0b-23456789abcd")
        with mock.patch.object(cli.os, "getppid", return_value=111):
            self.assertTrue(cli.dispatch_holder(FULL, SID, env))
        with mock.patch.object(cli.os, "getppid", return_value=222):
            self.assertFalse(cli.dispatch_holder(FULL, nested, env))
            self.assertFalse(cli.dispatch_holder(FULL, nested2, env, take_over=True), "a nested session's /clear")
        with mock.patch.object(cli.os, "getppid", return_value=111):
            self.assertTrue(cli.dispatch_holder(FULL, cleared, env, take_over=True), "the holder's /clear")
            self.assertTrue(cli.dispatch_holder(FULL, cleared, env), "the record moved: the cleared session holds it")
            self.assertFalse(cli.dispatch_holder(FULL, SID, env))

    def test_a_malformed_dispatch_id_falls_back_to_the_launch_id(self):
        other = "4c1d2e3f-0a1b-4c5d-8e9f-0123456789ab"
        for bad in ("a/b", "x" * 65, "a:b"):  # Switchboard's --dispatch-id form, [A-Za-z0-9._-]{1,64}
            with self.subTest(bad=bad[:5]):
                env = dict(self.env, **ENV)
                env["FABRIC_DISPATCH_ID"] = bad
                self.assertTrue(cli.dispatch_holder(FULL, SID, dict(env, SWITCHBOARD_LAUNCH_ID="l-%d" % len(bad))))
                self.assertTrue(cli.dispatch_holder(FULL, other, dict(env, SWITCHBOARD_LAUNCH_ID="l2-%d" % len(bad))),
                                "another launch id is another holder")

    def test_a_cut_short_write_leaves_no_temporary_file_past_the_prune(self):
        from unittest import mock
        import time
        env = dict(self.env, **ENV)
        cli.dispatch_holder(FULL, SID, env)
        env_module = importlib.import_module("fabric_session_env")
        with mock.patch.object(env_module.os, "replace", side_effect=OSError(28, "No space left on device")):
            cli.dispatch_holder(FULL, "4c1d2e3f-0a1b-4c5d-8e9f-0123456789ab", env, take_over=True)
        folder = cli.state_root(env=env) / "dispatch"
        self.assertTrue(list(folder.glob(".*.tmp")), "the cut-short write left its temporary file")
        fs.prune_stale_sessions(env=env, now=time.time() + fs.SESSION_STALE_S + 60)
        self.assertEqual(list(folder.glob(".*.tmp")), [])

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

    def test_a_session_start_on_a_request_prunes_old_records(self):
        # 0.63.0 product reading 4: a machine where only Codex or Kimi run dispatched sessions has no turn or end hook
        import os
        env = dict(self.env, **ENV)
        cli.dispatch_holder(dict(FULL, handoff="handoff:ffffffffffffffff"), SID, env)
        old = next((cli.state_root(env=env) / "dispatch").glob("*.json"))
        os.utime(old, (1, 1))
        spool = cli.state_root(env=env) / "sessions" / "4c1d2e3f-0a1b-4c5d-8e9f-0123456789ab"
        spool.mkdir(parents=True)
        (spool / "end.json").write_text("{}")
        for path in (spool / "end.json", spool):
            os.utime(path, (1, 1))
        self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "startup"},
                      extra_env=ENV, args=("--host", "codex"))
        self.assertFalse(old.exists())
        self.assertTrue(spool.exists(), "a Claude Code spool stays the turn and end hooks' (0.63.0 seam reading 5)")

    def test_the_turn_hook_prunes_in_a_session_fabric_launched_too(self):
        # 0.63.0 product reading 6: "the turn and end hooks always prune" held only outside a launched session
        import os
        env = dict(self.env, **ENV)
        cli.dispatch_holder(FULL, SID, env)
        old = next((cli.state_root(env=env) / "dispatch").glob("*.json"))
        os.utime(old, (1, 1))
        said = cli.hook_spool({"session_id": "4c1d2e3f-0a1b-4c5d-8e9f-0123456789ab", "cwd": str(self.repo)}, "turn",
                              env=dict(env, FABRIC_LAUNCHED_SESSION="1"), spawn=lambda *a, **k: None)
        self.assertEqual(said, "skipped: launched by Fabric")
        self.assertFalse(old.exists())

    def test_a_dispatched_session_gets_no_unread_line(self):
        # 0.63.0 product reading 7: the contract says no board sweep; the FAA-205 unread line would say the opposite
        env = dict(self.env, **ENV)
        folder = cli.session_dir(SID, env)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "board.json").write_text(json.dumps({"unread": 5}))
        said = cli.hook_user_prompt_submit({"session_id": SID, "prompt": LINE}, env)
        text = json.loads(said)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("this session is the run", text)
        self.assertNotIn("unread on the project board", text)
        self.assertIsNone(cli.hook_user_prompt_submit({"session_id": SID, "prompt": "go on"}, env))
        # nor nudges, and the nudges file stays where it is; a helper inside the run is the same (seam reading 8)
        nudges = folder / fs.NUDGES_FILE
        nudges.write_text(json.dumps(["claim your task"]))
        self.assertIsNone(cli.hook_user_prompt_submit({"session_id": SID, "prompt": "go on"}, env))
        self.assertTrue(nudges.exists())
        other = "4c1d2e3f-0a1b-4c5d-8e9f-0123456789ab"
        inner = cli.session_dir(other, env)
        inner.mkdir(parents=True, exist_ok=True)
        (inner / "board.json").write_text(json.dumps({"unread": 5}))
        self.assertIsNone(cli.hook_user_prompt_submit({"session_id": other, "prompt": "go on"}, env))

    def test_session_start_names_a_uuid_session_id_and_no_other(self):
        # 0.63.0 seam reading 8: Observatory takes a sessionId only as a lowercase UUID
        uuid = "1a2b3c4d-0a1b-4c5d-8e9f-0123456789ab"
        self.assertIn("This session's sessionId: %s." % uuid, cli.dispatch_contract(FULL, uuid))
        self.assertNotIn("This session's sessionId", cli.dispatch_contract(FULL, "s-aaa"))
        self.assertNotIn("This session's sessionId", cli.dispatch_contract(FULL, uuid.upper()))
        done, _ = self.run_hook("session-start", {"session_id": uuid, "cwd": str(self.repo), "source": "startup"},
                                extra_env=ENV)
        self.assertIn(uuid, self.context(done))

    def test_work_that_outlasts_the_run_is_left_accepted(self):
        text = cli.dispatch_contract(FULL)
        self.assertIn("otherwise it is left accepted for the next run", text, "Fabric dispatches it since fff4b6d9")
        self.assertIn("when the request's deadline is not after run-ends-at plus 10 minutes (no next run starts that close to it), "
                      "`com.complete` failed_known", text,
                      "no run comes after the deadline (0.63.0 product reading 12)")

    def test_the_prompt_hooks_confirmation_names_the_session_id(self):
        # 0.63.0 unit reading 9: the confirmation carries the id when it is a lowercase UUID
        uuid = "1a2b3c4d-0a1b-4c5d-8e9f-0123456789ab"
        done, _ = self.run_hook("user-prompt-submit", {"session_id": uuid, "cwd": str(self.repo), "prompt": LINE},
                                extra_env=ENV)
        self.assertEqual(self.context(done), cli.DISPATCH_IS_RUN + " This session's sessionId: %s." % uuid)

    def test_a_record_just_inside_seven_days_stays(self):
        import os, time
        env = dict(self.env, **ENV)
        cli.dispatch_holder(FULL, SID, env)
        record = next((cli.state_root(env=env) / "dispatch").glob("*.json"))
        now = time.time()
        os.utime(record, (now - fs.SESSION_STALE_S + 60,) * 2)
        importlib.import_module("fabric_session_env").prune_dispatch_records(env=env, now=now)
        self.assertTrue(record.exists())

    def test_a_cleared_holder_is_told_not_to_accept_again(self):
        # 0.63.0 seam reading 9: the accept was made under the id the /clear replaced
        uuid = "1a2b3c4d-0a1b-4c5d-8e9f-0123456789ab"
        cleared = "2b3c4d5e-1b2c-4d6e-9fa0-123456789abc"
        self.run_hook("user-prompt-submit", {"session_id": uuid, "cwd": str(self.repo), "prompt": LINE}, extra_env=ENV)
        done, _ = self.run_hook("session-start", {"session_id": cleared, "cwd": str(self.repo), "source": "clear"},
                                extra_env=ENV)
        text = self.context(done)
        self.assertTrue(text.startswith(cli.DISPATCH_HEAD.format(**FULL)), "the cleared holder is the run")
        self.assertIn("Never accept it under the new id", text)
        self.assertIn("sessionId %s" % uuid, text, "the id the accept was made under (0.63.0 seam reading 10)")
        self.assertIn("`accept-%s`" % HANDOFF, text, "the key, from the handoff (0.63.0 unit reading 12)")
        self.assertNotIn(cleared, text)
        # the prompt hook says the same when the line comes again, never the new id (unit and seam readings 10)
        done, _ = self.run_hook("user-prompt-submit", {"session_id": cleared, "cwd": str(self.repo), "prompt": LINE},
                                extra_env=ENV)
        text = self.context(done)
        self.assertIn("sessionId %s" % uuid, text)
        self.assertIn("`accept-%s`" % HANDOFF, text)
        self.assertIn("Never accept it under the new id", text)
        self.assertNotIn(cleared, text)

    def test_the_cleared_notice_names_the_whole_replay(self):
        # 0.63.0 readings 11: Observatory replays only the same sessionId, key, owner and executor
        uuid = "1a2b3c4d-0a1b-4c5d-8e9f-0123456789ab"
        text = cli.dispatch_cleared(uuid, HANDOFF)
        for words in ("sessionId %s" % uuid, "`accept-%s`" % HANDOFF,
                      "still shows the handoff pending, no accept was made", "Never accept it under the new id",
                      "as the first accept passed them", "its `holder` is the owner", "carries an `accountRef`", "the lease it shows is Fabric's, not this run's", "no executor (the launcher's prompt is gone)",
                      "`agent:<provider>` (such as `agent:claude-code`) when Switchboard started the run", "A replay Observatory refuses"):
            self.assertIn(words, text)
        for previous in (None, "", "S-ABC", uuid.upper()):
            with self.subTest(previous=previous):
                self.assertIn("cannot name the session id the clear replaced", cli.dispatch_cleared(previous))
                self.assertNotIn("replaying it exactly", cli.dispatch_cleared(previous))
        self.assertIn("`accept-<handoff>`, the handoff the packet names", cli.dispatch_cleared(uuid))
        self.assertIn("the key `accept-<handoff>`, no executor", cli.dispatch_contract(FULL),
                      "step 2's fallback key can be replayed after a /clear (product reading 18)")
        self.assertIn("A lapsed or refused handoff holds no lease: end the run without touching the request",
                      cli.dispatch_contract(FULL))
        # 0.63.0 unit reading 15: the owner with no launcher named, the conflict's ending, and a pending accept with no
        # handoff known that presumes no first accept's key
        self.assertIn("the owner `agent:<name>` step 2 names and no executor", cli.dispatch_cleared(uuid))
        # 0.63.0 product reading 16: a pending accept takes the owner from step 2, never the lease's holder
        pending = cli.dispatch_cleared(uuid, HANDOFF).split("still shows the handoff pending")[1]
        self.assertNotIn("holder", pending)
        # 0.63.0 unit reading 17: the owner's fallback, the scope of the lease reading, and a pending key from step 2
        self.assertIn("else `agent:<name>`", pending)
        self.assertIn("Once the handoff is taken (neither pending nor lapsed, and the lease's `handoffId` is it)",
                      cli.dispatch_cleared(uuid, HANDOFF))
        self.assertIn("Read only this dispatch's handoff (%s)" % HANDOFF, cli.dispatch_cleared(uuid, HANDOFF))
        self.assertIn("the key `accept-%s`" % HANDOFF, pending)
        tail = cli.dispatch_cleared(uuid).split("still shows the handoff pending")[1]
        self.assertIn("the key `accept-<handoff>`", tail)
        self.assertNotIn("first accept used", tail)
        self.assertIn("(when it names none: your `owner` `agent:<name>`, the key `accept-<handoff>`, no executor)",
                      cli.dispatch_contract(FULL), "step 2's fallback, which the notices point at (unit reading 16)")
        self.assertIn("the `owner`, `idempotencyKey` and `executor` the launcher's prompt names", cli.dispatch_contract(FULL))
        self.assertIn("gets no lease back: end the run without touching the request", text)
        self.assertIn("with the key `accept-<handoff>`, the handoff the packet names, the owner `agent:<name>` step 2 names, no executor and this session's own sessionId", cli.dispatch_cleared(None))
        self.assertIn("observatory_lesson", cli.dispatch_contract(FULL), "step 7's retro")
        self.assertIn("insight/1", cli.dispatch_contract(FULL), "step 7's retro (0.63.0 unit reading 12)")

    def test_a_second_clear_names_the_first_holder(self):
        from unittest import mock
        env = dict(self.env, **ENV)
        a, b, c = ("1a2b3c4d-0a1b-4c5d-8e9f-0123456789ab", "2b3c4d5e-1b2c-4d6e-9fa0-123456789abc",
                   "3c4d5e6f-2c3d-4e7f-8a0b-23456789abcd")
        with mock.patch.object(cli.os, "getppid", return_value=111):
            cli.dispatch_holder(FULL, a, env)
            cli.dispatch_holder(FULL, b, env, take_over=True)
            cli.dispatch_holder(FULL, c, env, take_over=True)
        self.assertEqual(cli.dispatch_cleared_from(FULL, env), a)

    def test_after_an_unknown_id_the_next_clear_names_the_session_told_to_accept(self):
        # 0.63.0 seam reading 13: a clear that could not name the replaced id told the session it started to accept
        # a pending handoff under its own id; the next clear names that session
        from unittest import mock
        env = dict(self.env, **ENV)
        a, b, c = ("S-ABC", "2b3c4d5e-1b2c-4d6e-9fa0-123456789abc", "3c4d5e6f-2c3d-4e7f-8a0b-23456789abcd")
        with mock.patch.object(cli.os, "getppid", return_value=111):
            cli.dispatch_holder(FULL, a, env)
            cli.dispatch_holder(FULL, b, env, take_over=True)
            cli.dispatch_holder(FULL, c, env, take_over=True)
        self.assertEqual(cli.dispatch_cleared_from(FULL, env), b)
        self.assertIn("sessionId %s" % b, cli.dispatch_cleared(cli.dispatch_cleared_from(FULL, env), HANDOFF, c))
        self.assertNotIn(c, cli.dispatch_cleared(cli.dispatch_cleared_from(FULL, env), HANDOFF, c))

    def test_a_pending_handoff_is_accepted_under_the_id_every_later_clear_names(self):
        # 0.63.0 seam and unit readings 13: the cleared holder is never told to accept under its own new id when the
        # replaced one is known, and the id it accepts under is the one the next clear names
        from unittest import mock
        env = dict(self.env, **ENV)
        a, b, c = ("1a2b3c4d-0a1b-4c5d-8e9f-0123456789ab", "2b3c4d5e-1b2c-4d6e-9fa0-123456789abc",
                   "3c4d5e6f-2c3d-4e7f-8a0b-23456789abcd")
        with mock.patch.object(cli.os, "getppid", return_value=111):
            cli.dispatch_holder(FULL, a, env)
            cli.dispatch_holder(FULL, b, env, take_over=True)
            told = cli.dispatch_cleared(cli.dispatch_cleared_from(FULL, env), HANDOFF, b)
            cli.dispatch_holder(FULL, c, env, take_over=True)
        self.assertIn("accept it now with that same sessionId", told)
        self.assertNotIn(b, told)
        self.assertNotIn("as step 2 says", told)
        self.assertEqual(cli.dispatch_cleared_from(FULL, env), a, "the id the pending accept was made under")

    def test_both_hooks_give_a_cleared_session_its_new_id_when_the_replaced_one_is_unknown(self):
        # 0.63.0 seam reading 13: a holder whose id the notice cannot name; the clear names the new id for a pending
        # handoff, at session start and when the line comes again
        new = "2b3c4d5e-1b2c-4d6e-9fa0-123456789abc"
        self.run_hook("user-prompt-submit", {"session_id": "S-ABC", "cwd": str(self.repo), "prompt": LINE},
                      extra_env=ENV)
        done, _ = self.run_hook("session-start", {"session_id": new, "cwd": str(self.repo), "source": "clear"},
                                extra_env=ENV)
        self.assertIn("this session's own sessionId (%s)" % new, self.context(done))
        done, _ = self.run_hook("user-prompt-submit", {"session_id": new, "cwd": str(self.repo), "prompt": LINE},
                                extra_env=ENV)
        self.assertIn("this session's own sessionId (%s)" % new, self.context(done))

    def test_on_windows_a_reused_process_id_names_no_holder(self):
        # 0.63.0 unit reading 15: Windows reuses process ids, so the same parent proves nothing there
        from unittest import mock
        env = dict(self.env, **ENV)
        holder, nested = "1a2b3c4d-0a1b-4c5d-8e9f-0123456789ab", "2b3c4d5e-1b2c-4d6e-9fa0-123456789abc"
        with mock.patch.object(cli.os, "getppid", return_value=777), mock.patch.object(cli, "_WINDOWS", True):
            cli.dispatch_holder(FULL, holder, env)
            cli.dispatch_holder(FULL, nested, env, take_over=True)
            self.assertEqual(cli.dispatch_cleared_from(FULL, env), "")
            self.assertIn("On Windows a later /clear names no id either",
                          cli.dispatch_cleared(cli.dispatch_cleared_from(FULL, env), HANDOFF, nested))

    def test_on_windows_the_new_id_is_said_not_to_be_named_again(self):
        # 0.63.0 unit reading 14: a later clear on Windows names no id, so the notice does not promise a replay
        from unittest import mock
        new = "2b3c4d5e-1b2c-4d6e-9fa0-123456789abc"
        with mock.patch.object(cli, "_WINDOWS", True):
            self.assertIn("On Windows a later /clear names no id either", cli.dispatch_cleared("", HANDOFF, new))
        self.assertNotIn("On Windows", cli.dispatch_cleared("", HANDOFF, new))

    def test_an_id_the_notice_cannot_name_is_not_carried_on(self):
        # 0.63.0 unit reading 14: a first holder outside the UUID form, then two clears: the next names the second
        from unittest import mock
        env = dict(self.env, **ENV)
        b, c = "2b3c4d5e-1b2c-4d6e-9fa0-123456789abc", "3c4d5e6f-2c3d-4e7f-8a0b-23456789abcd"
        with mock.patch.object(cli.os, "getppid", return_value=111):
            cli.dispatch_holder(FULL, "S-ABC", env)
            cli.dispatch_holder(FULL, b, env, take_over=True)
            cli.dispatch_holder(FULL, c, env, take_over=True)
        self.assertEqual(cli.dispatch_cleared_from(FULL, env), b)

    def test_each_lease_state_gets_one_instruction(self):
        # 0.63.0 unit reading 18: the lapsed sentence, whole and once, in the named and the unknown notice
        lapsed = ("When `observatory_checkpoint_latest` shows the handoff lapsed, no accept was made and none can be: "
                  "end the run without touching the request.")
        for text in (cli.dispatch_cleared("1a2b3c4d-0a1b-4c5d-8e9f-0123456789ab", HANDOFF),
                     cli.dispatch_cleared("1a2b3c4d-0a1b-4c5d-8e9f-0123456789ab"), cli.dispatch_cleared(None, HANDOFF),
                     cli.dispatch_cleared("")):
            with self.subTest(text=text[:60]):
                self.assertIn(lapsed, text)
                self.assertEqual(text.count("handoff lapsed"), 1)
                self.assertEqual(text.count("still shows the handoff pending"), 1)
                # 0.63.0 seam reading 18: only this dispatch's handoff decides the state
                self.assertIn("Read only this dispatch's handoff (", text)
                self.assertIn("shows another one, pending, lapsed or in the lease, end the run", text)
                self.assertNotIn("end the run", text.split("still shows the handoff pending")[1])

    def test_an_unknown_id_gives_the_new_one_for_a_pending_handoff(self):
        new = "2b3c4d5e-1b2c-4d6e-9fa0-123456789abc"
        for previous in (None, ""):
            with self.subTest(previous=previous):
                text = cli.dispatch_cleared(previous, HANDOFF, new)
                self.assertIn("with the key `accept-%s`, the owner `agent:<provider>`" % HANDOFF, text)
                self.assertIn("this session's own sessionId (%s)" % new, text)
                # 0.63.0 product reading 17: nothing to replay is said first, and a lapsed handoff ends the run
                self.assertTrue(text.index("cannot be replayed") < text.index("still shows the handoff pending"))
                # 0.63.0 unit reading 18: each lease state's whole sentence, once
                self.assertIn("shows the handoff taken and this session holds no leaseId for it, end the run without "
                              "touching the request", text)
                self.assertNotIn("end the run", text.split("still shows the handoff pending")[1])
                self.assertIn("end the run without touching the request", text)
                self.assertNotIn("Never accept it under the new id", text)
        self.assertNotIn("(", cli.dispatch_cleared(None, None, "not-a-uuid").split("own sessionId")[1].split(".")[0])

    def test_a_clear_with_no_readable_record_reads_as_no_clear(self):
        env = dict(self.env, **ENV)
        self.assertFalse(cli.dispatch_holder(FULL, SID, env, take_over=True))
        self.assertIsNone(cli.dispatch_cleared_from(FULL, env), "no record: nothing was cleared")

    def test_on_windows_a_clear_names_no_holder(self):
        from unittest import mock
        env = dict(self.env, **ENV)
        holder, nested = "1a2b3c4d-0a1b-4c5d-8e9f-0123456789ab", "2b3c4d5e-1b2c-4d6e-9fa0-123456789abc"
        with mock.patch.object(cli.os, "getppid", return_value=111):
            cli.dispatch_holder(FULL, holder, env)
        with mock.patch.object(cli.os, "getppid", return_value=222), mock.patch.object(cli, "_WINDOWS", True):
            cli.dispatch_holder(FULL, nested, env, take_over=True)
        self.assertEqual(cli.dispatch_cleared_from(FULL, env), "", "a nested session must not learn the holder's id")

    def test_the_contract_names_this_sessions_id_for_the_accept(self):
        # 0.63.0 seam reading 7: Observatory asks a retry of the acceptance to send the same sessionId
        self.assertIn("this session's own `sessionId` (the same on a retry)", cli.dispatch_contract(FULL))

    def test_a_clear_in_the_holder_keeps_the_contract(self):
        # 0.63.0 seam r3: /clear gives the same run a new session id; a session with no record of the run gets the
        # conditional contract, and its prompt decides
        cleared, other = "4c1d2e3f-0a1b-4c5d-8e9f-0123456789ab", "5d2e3f40-1b2c-4d6e-9fa0-123456789abc"
        done, _ = self.run_hook("session-start", {"session_id": other, "cwd": str(self.repo), "source": "clear"},
                                extra_env=ENV)
        self.assertEqual(self.context(done), cli.dispatch_contract(FULL, other, conditional=True), "no run yet")
        self.prompt(ENV, LINE)
        done, _ = self.run_hook("session-start", {"session_id": cleared, "cwd": str(self.repo), "source": "clear"},
                                extra_env=ENV)
        self.assertTrue(self.context(done).startswith(cli.DISPATCH_HEAD.format(**FULL)))
        self.assertIn("observatory_handoff_accept", self.context(done))

    def test_the_reference_says_a_codex_run_needs_the_hook_trusted(self):
        # 0.63.0 seam reading 4: Codex runs a hooks.json hook only when the home's config.toml trusts it, and
        # Switchboard links hooks.json, not config.toml, into its isolated homes
        text = (Path(cli.__file__).resolve().parents[1] / "references" / "on-demand-session.md").read_text()
        flat = " ".join(text.split())
        self.assertIn("that run's `CODEX_HOME` trusts it", flat)
        self.assertIn("since 0.7.8 carries the person's trust", flat, "Switchboard 0.7.8 of 2026-11-04 carries it")
        self.assertNotRegex(flat, r"Switchboard[^.]*not yet in a release", "Switchboard 0.7.8 is released")

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
        for junk in ("wf_xyz", "1"):  # 0.63.0 unit reading 6: a malformed workflow is no dispatch, as for the hooks
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = mail.watch_mail_cli(["--session-id", SID, "--cwd", str(self.repo)],
                                           env=dict(env, FABRIC_DISPATCH_WORKFLOW=junk))
            self.assertEqual(code, 2, "stopped further on: no fabric registered in this home")
            self.assertNotIn("started on a board request", err.getvalue(), junk)
            self.assertIn("no MCP server named fabric", err.getvalue())

    def test_without_the_line_the_prompt_hook_prints_no_contract(self):
        # Vesta's VES-BOARD-SPAWN-HARDEN 2: without FABRIC_DISPATCH_* no exit contract; with it and no line, none either
        self.assertEqual(self.prompt({}, "answer the request in thread 1")[0].stdout, "")
        self.assertEqual(self.prompt(ENV, "read the diff and report")[0].stdout, "")
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "startup"})
        self.assertNotIn("observatory_handoff_accept", done.stdout)

if __name__ == "__main__":
    unittest.main()
