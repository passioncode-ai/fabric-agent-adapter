"""working-with-fabric (FAA-68): the session spool's failure paths, each injected. A JSON-RPC error or an unreadable
entry drops that entry and the rest still goes out; a wrapped fabric-mcp that ignores the end of its stdin is ended
with its whole process group inside the deadline; a `ps` that fails is "unknown", never "not launched"; turn facts are
the turn's own; watch-mail keeps its delay inside its bounds and shares the once-a-minute rejoin; stale folders go
even while the hooks are inert, and a stale worker lock is taken without a check-then-act race."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import textwrap
import time
import unittest

from test_fabric_session import SID, Base, fs

ENV = sys.modules["fabric_session_env"]
CLI = sys.modules["fabric_session_cli"]
MCP = sys.modules["fabric_session_mcp"]

# A fake fabric-mcp. FAKE_ERROR names the call that gets a JSON-RPC error ("turn", "release", "end"); FAKE_HANG makes
# it ignore the end of its stdin; FAKE_PID_FILE receives its pid.
FAULT_MCP = textwrap.dedent('''\
    import json, os, sys, time
    record = os.environ["FAKE_MCP_RECORD"]
    if os.environ.get("FAKE_PID_FILE"):
        open(os.environ["FAKE_PID_FILE"], "w").write(str(os.getpid()))
    fail = os.environ.get("FAKE_ERROR", "")
    tools = ["fabric_whoami", "fabric_session_observe", "fabric_work_release", "com.status"]
    def write(kind, value):
        with open(record, "a") as f:
            f.write(json.dumps({"kind": kind, "value": value}) + "\\n")
    def send(message):
        sys.stdout.write(json.dumps(message) + "\\n"); sys.stdout.flush()
    write("argv", sys.argv[1:])
    for line in sys.stdin:
        m = json.loads(line)
        if "id" not in m:
            continue
        method = m["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "f", "version": "0"}}
        elif method == "tools/list":
            result = {"tools": [{"name": n} for n in tools]}
        else:
            write("call", m["params"])
            name, args = m["params"]["name"], m["params"].get("arguments") or {}
            which = "release" if name == "fabric_work_release" else args.get("event")
            if which == fail:
                send({"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32602, "message": "secret /private/path"}})
                continue
            text = json.dumps({"board": {"state": "ready"}, "unread": 1}) if name == "com.status" else "recorded"
            result = {"content": [{"type": "text", "text": text}]}
        send({"jsonrpc": "2.0", "id": m["id"], "result": result})
    if os.environ.get("FAKE_HANG"):
        time.sleep(60)
    write("exit", 0)
''')


class Faults(Base):
    def setUp(self):
        super().setUp()
        self.hub(features=["session-hooks/1"])
        self.record = self.base / "record.jsonl"
        server = self.base / "bin" / "fault_mcp.py"
        server.parent.mkdir()
        server.write_text(FAULT_MCP)
        self.server = server
        self.register(command=sys.executable)
        config = json.loads((self.home / ".claude.json").read_text())
        config["mcpServers"]["fabric"]["args"] = ["-S", str(server)]
        (self.home / ".claude.json").write_text(json.dumps(config))
        self.env["FAKE_MCP_RECORD"] = str(self.record)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        for key, value in (("user.email", "t@example.invalid"), ("user.name", "t"), ("commit.gpgsign", "false")):
            subprocess.run(["git", "-C", str(self.repo), "config", key, value], check=True)
        (self.repo / "tracked.txt").write_text("one\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "c"], check=True)
        self.directory = fs.session_dir(SID, self.env)
        # The ancestor walk reads the real process table; these tests inject its answer (LaunchedUnknown) or none.
        original = CLI.launched_by_ancestor
        CLI.launched_by_ancestor = lambda env=None: False
        self.addCleanup(setattr, CLI, "launched_by_ancestor", original)

    def records(self, kind):
        if not self.record.exists():
            return []
        return [r["value"] for r in map(json.loads, self.record.read_text().splitlines()) if r["kind"] == kind]

    def spool(self, event, **extra):
        return fs.hook_spool(dict({"session_id": SID, "cwd": str(self.repo)}, **extra), event, self.env,
                             spawn=lambda directory: None)

    def called(self):
        return [(c["name"], (c.get("arguments") or {}).get("event")) for c in self.records("call")]


class Delivery(Faults):
    def test_a_json_rpc_error_drops_that_entry_and_the_end_still_goes_out(self):
        self.env["FAKE_ERROR"] = "turn"
        self.spool("turn")
        self.spool("end", reason="other")
        fs.deliver(self.directory, self.env, deadline_s=8)
        self.assertEqual(self.called(), [("fabric_session_observe", "turn"), ("fabric_work_release", None),
                                         ("fabric_session_observe", "end")])
        self.assertFalse(self.directory.exists(), "the end was delivered, so the spool goes")
        log = self.log_text()
        self.assertIn("event=turn tool=fabric_session_observe answer=error:-32602", log)
        self.assertNotIn("/private/path", log)

    def test_an_error_on_the_release_still_sends_the_end_observation(self):
        self.env["FAKE_ERROR"] = "release"
        self.spool("end", reason="other")
        fs.deliver(self.directory, self.env, deadline_s=8)
        self.assertEqual(self.called(), [("fabric_work_release", None), ("fabric_session_observe", "end")])
        self.assertFalse(self.directory.exists())

    def test_a_later_worker_is_not_blocked_by_an_entry_that_failed(self):
        self.env["FAKE_ERROR"] = "turn"
        self.spool("turn")
        fs.deliver(self.directory, self.env, deadline_s=8)
        self.assertEqual(list(self.directory.glob("*-turn.json")), [], "the refused turn was dropped")
        del self.env["FAKE_ERROR"]
        self.spool("end", reason="other")
        fs.deliver(self.directory, self.env, deadline_s=8)
        self.assertEqual(self.called()[-2:], [("fabric_work_release", None), ("fabric_session_observe", "end")])

    def test_an_unreadable_entry_is_dropped_and_the_rest_is_delivered(self):
        self.spool("turn")
        (self.directory / "00000000000000000001-turn.json").write_text("{not json")
        (self.directory / "00000000000000000002-turn.json").write_text("[1, 2]")
        (self.directory / "00000000000000000003-turn.json").write_bytes(b"\xff\xfe")
        self.spool("end", reason="other")
        fs.deliver(self.directory, self.env, deadline_s=8)
        self.assertEqual(self.called(), [("fabric_session_observe", "turn"), ("fabric_work_release", None),
                                         ("fabric_session_observe", "end")])
        self.assertFalse(self.directory.exists())
        self.assertEqual(self.log_text().count("outcome=dropped reason='unreadable entry'"), 3)

    def test_an_unreadable_first_entry_still_finds_the_registration(self):
        self.directory.mkdir(parents=True)
        (self.directory / "00000000000000000001-turn.json").write_text("{not json")
        self.spool("end", reason="other")
        fs.deliver(self.directory, self.env, deadline_s=8)
        self.assertEqual(self.called(), [("fabric_work_release", None), ("fabric_session_observe", "end")])


class Wrapped(Faults):
    @unittest.skipIf(sys.platform == "win32", "a POSIX shell wrapper")
    def test_a_wrapped_server_that_ignores_its_stdin_end_is_ended_within_the_deadline(self):
        pid_file = self.base / "server.pid"
        wrapper = self.base / "bin" / "wrap.sh"
        wrapper.write_text("#!/bin/sh\n%s -S %s\n" % (sys.executable, self.server))  # not exec: the shell stays
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        config = json.loads((self.home / ".claude.json").read_text())
        config["mcpServers"]["fabric"] = {"command": str(wrapper), "args": []}
        (self.home / ".claude.json").write_text(json.dumps(config))
        self.env.update(FAKE_HANG="1", FAKE_PID_FILE=str(pid_file))
        self.spool("turn")
        started = time.monotonic()
        fs.deliver(self.directory, self.env, deadline_s=5.0)
        elapsed = time.monotonic() - started
        # The deadline, the close's grace and its bounded waits; the server itself would hold on for 60 s.
        self.assertLess(elapsed, 12.0, "the worker ends near its deadline, not when the wrapped server gives up")
        pid = int(pid_file.read_text())
        until = time.monotonic() + 3
        while fs.pid_alive(pid) and time.monotonic() < until:
            time.sleep(0.1)
        self.assertFalse(fs.pid_alive(pid), "the server behind the wrapper is ended with its group")
        self.assertEqual(self.called(), [("fabric_session_observe", "turn"), ("com.status", None)])


class LaunchedUnknown(Faults):
    def test_a_failing_ps_is_unknown_not_false(self):
        self.assertIsNone(fs.launched_by_ancestor(self.env, process=lambda pid: (None, 0)))
        marker = str(fs.fabric_root(env=self.env) / "sessions" / "s1" / "mcp.json")
        self.assertTrue(fs.launched_by_ancestor(self.env, process=lambda pid: ("claude --mcp-config " + marker, 1)))
        self.assertFalse(fs.launched_by_ancestor(self.env, process=lambda pid: ("claude", 1)))

    def walk(self, answer):
        calls = []

        def fake(env=None):
            calls.append(1)
            return answer
        original = CLI.launched_by_ancestor
        CLI.launched_by_ancestor = fake
        self.addCleanup(setattr, CLI, "launched_by_ancestor", original)
        return calls

    def test_an_unknown_launcher_spools_nothing_and_releases_nothing(self):
        self.walk(None)
        self.assertEqual(self.spool("turn"), "skipped: whether Fabric launched this session is unknown")
        self.assertEqual(self.spool("end"), "skipped: whether Fabric launched this session is unknown")
        self.assertFalse(self.directory.exists(), "no spool, so no worker can release the session's claims")

    def test_a_launched_session_is_remembered_so_the_walk_runs_once(self):
        calls = self.walk(True)
        self.assertEqual(self.spool("turn"), "skipped: launched by Fabric")
        self.assertEqual(self.spool("turn"), "skipped: launched by Fabric")
        self.assertEqual(len(calls), 1, "the positive answer is kept in the session's folder")
        self.assertEqual(list(self.directory.glob("*-*.json")), [], "nothing is spooled")
        self.assertEqual(self.spool("end"), "skipped: launched by Fabric")
        self.assertFalse(self.directory.exists(), "the marker goes with the session's end")

    @unittest.skipUnless(sys.platform == "darwin", "macOS reads the process table with ps")
    def test_a_slow_ps_on_the_real_hook_spools_nothing(self):
        fake_bin = self.base / "slowbin"
        fake_bin.mkdir()
        ps = fake_bin / "ps"
        ps.write_text("#!/bin/sh\nsleep 3\n")
        ps.chmod(ps.stat().st_mode | stat.S_IXUSR)
        done, _ = self.run_hook("stop", {"session_id": SID, "cwd": str(self.repo)},
                                extra_env={"PATH": "%s:%s" % (fake_bin, self.env.get("PATH", ""))})
        self.assertEqual(done.returncode, 0)
        self.assertFalse(self.directory.exists())


class TurnFacts(Faults):
    def test_each_turn_carries_the_facts_measured_when_it_ended(self):
        self.spool("turn")                                   # nothing changed yet
        (self.repo / "a.txt").write_text("x\n")
        self.spool("turn")                                   # one untracked file
        for n in range(5):
            (self.repo / ("b%d.txt" % n)).write_text("y\n")  # later work, not this turn's
        stored = [json.loads(p.read_text()) for p in sorted(self.directory.glob("*-turn.json"))]
        self.assertEqual([s["facts"]["filesChanged"] for s in stored], [0, 1])
        for entry in stored:
            self.assertEqual(sorted(entry["facts"]), ["filesChanged", "head", "linesAdded", "linesRemoved"])
            self.assertNotIn("a.txt", json.dumps(entry["facts"]))
        fs.deliver(self.directory, self.env, deadline_s=8)
        turns = [c["arguments"] for c in self.records("call") if c["name"] == "fabric_session_observe"]
        self.assertEqual([t["filesChanged"] for t in turns], [0, 1])

    def test_an_entry_without_facts_sends_nulls_and_measures_nothing_late(self):
        self.directory.mkdir(parents=True)
        (self.directory / "00000000000000000001-turn.json").write_text(json.dumps({
            "event": "turn", "runtimeSessionId": SID, "cwd": str(self.repo), "observedAt": "2026-10-22T00:00:00Z"}))
        (self.repo / "late.txt").write_text("x\n")
        fs.deliver(self.directory, self.env, deadline_s=8)
        (turn,) = [c["arguments"] for c in self.records("call") if c["name"] == "fabric_session_observe"]
        self.assertEqual([turn[k] for k in ("head", "filesChanged", "linesAdded", "linesRemoved")], [None] * 4)

    def test_stored_facts_of_the_wrong_shape_are_not_sent(self):
        self.directory.mkdir(parents=True)
        (self.directory / "00000000000000000001-turn.json").write_text(json.dumps({
            "event": "turn", "runtimeSessionId": SID, "cwd": str(self.repo), "observedAt": "2026-10-22T00:00:00Z",
            "facts": {"head": "/private/path", "filesChanged": -1, "linesAdded": True, "linesRemoved": "3",
                      "extra": "x"}}))
        fs.deliver(self.directory, self.env, deadline_s=8)
        (turn,) = [c["arguments"] for c in self.records("call") if c["name"] == "fabric_session_observe"]
        self.assertEqual([turn[k] for k in ("head", "filesChanged", "linesAdded", "linesRemoved")], [None] * 4)
        self.assertNotIn("extra", turn)


class WatchMailBounds(unittest.TestCase):
    def run_watch(self, results, rng, interval=10):
        waits, polls = [], iter(results)

        def wait(seconds):
            waits.append(seconds)
            return len(waits) >= len(results)
        fs.watch_mail(SID, Path("."), {}, interval, poll=lambda: next(polls), out=lambda line: None,
                      wait=wait, stop=lambda: False, rng=lambda: rng)
        return waits

    def test_the_delay_after_jitter_never_falls_under_the_floor(self):
        waits = self.run_watch([("ok", 0)] * 3, rng=0.0, interval=10)
        self.assertEqual(min(waits), fs.WATCH_MIN_INTERVAL_S)

    def test_the_delay_after_jitter_never_passes_the_cap(self):
        waits = self.run_watch([("down", "x")] * 12, rng=1.0, interval=600)
        self.assertEqual(max(waits), fs.WATCH_MAX_BACKOFF_S)

    def test_a_wait_for_the_rejoin_mark_keeps_the_count_and_says_nothing(self):
        said, waits, polls = [], [], iter([("ok", 2), ("wait", 30.0), ("ok", 2)])

        def wait(seconds):
            waits.append(seconds)
            return len(waits) >= 3
        fs.watch_mail(SID, Path("."), {}, 10, poll=lambda: next(polls), out=said.append,
                      wait=wait, stop=lambda: False, rng=lambda: 0.5)
        self.assertEqual(said, [fs.UNREAD_LINE % 2], "a skipped look neither resets the count nor reports trouble")
        self.assertEqual(waits[1], 30.0)


class WatchMailRejoinMark(Faults):
    def test_a_fresh_rejoin_mark_starts_no_fabric_mcp(self):
        self.directory.mkdir(parents=True)
        (self.directory / "rejoined").write_text("")
        kind, value = fs.poll_unread(SID, self.repo, self.env, deadline_s=8)
        self.assertEqual(kind, "wait")
        self.assertTrue(0 < value <= fs.REJOIN_MIN_INTERVAL_S)
        self.assertEqual(self.records("argv"), [])

    def test_a_poll_marks_its_rejoin_for_the_stop_worker(self):
        self.directory.mkdir(parents=True)
        old = time.time() - fs.REJOIN_MIN_INTERVAL_S - 5
        (self.directory / "rejoined").write_text("")
        os.utime(self.directory / "rejoined", (old, old))
        self.assertEqual(fs.poll_unread(SID, self.repo, self.env, deadline_s=8), ("ok", 1))
        self.assertTrue(fs.rejoined_recently(self.directory))
        self.assertEqual(self.spool("turn"), "spooled: rejoined recently")

    def test_a_poll_without_a_session_folder_makes_none(self):
        self.assertEqual(fs.poll_unread(SID, self.repo, self.env, deadline_s=8), ("ok", 1))
        self.assertFalse(self.directory.exists(), "the folder is the hooks' to make, after their launch check")


class Housekeeping(Faults):
    def stale_folder(self):
        folder = fs.state_root(env=self.env) / "sessions" / "11111111-1111-4111-8111-111111111111"
        folder.mkdir(parents=True)
        (folder / "00000000000000000001-turn.json").write_text("{}")
        old = time.time() - fs.SESSION_STALE_S - 60
        for item in (folder / "00000000000000000001-turn.json", folder):
            os.utime(item, (old, old))
        return folder

    def test_stale_folders_are_pruned_while_fabric_is_down(self):
        folder = self.stale_folder()
        (fs.fabric_root(env=self.env) / "hub.json").unlink()
        self.assertEqual(self.spool("turn"), "inert: Fabric is not running")
        self.assertFalse(folder.exists())

    def test_stale_folders_are_pruned_when_fabric_lacks_the_feature(self):
        folder = self.stale_folder()
        self.hub(features=[])
        self.assertTrue(self.spool("turn").startswith("inert:"))
        self.assertFalse(folder.exists())

    def test_a_stale_lock_is_taken_and_leaves_nothing_behind(self):
        self.directory.mkdir(parents=True)
        lock = self.directory / "worker.lock"
        lock.write_text("1")
        old = time.time() - fs.LOCK_STALE_S - 5
        os.utime(lock, (old, old))
        self.assertTrue(fs._try_lock(lock, self.directory))
        self.assertEqual(lock.read_text(), str(os.getpid()))
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), ["worker.lock"])

    def test_a_live_lock_is_not_taken(self):
        self.directory.mkdir(parents=True)
        lock = self.directory / "worker.lock"
        lock.write_text("1")
        self.assertFalse(fs._try_lock(lock, self.directory))
        self.assertEqual(lock.read_text(), "1")

    def test_a_lock_renewed_between_the_look_and_the_take_is_left_alone(self):
        """The check-then-act race: another worker replaces the stale lock with its own right after this one judged
        it stale. The rename takes a file that is no longer the stale one, so it is put back, untouched."""
        self.directory.mkdir(parents=True)
        lock = self.directory / "worker.lock"
        lock.write_text("1")
        old = time.time() - fs.LOCK_STALE_S - 5
        os.utime(lock, (old, old))

        def another_worker_wins():
            lock.unlink()
            lock.write_text("4242")
        self.assertFalse(MCP._try_lock(lock, self.directory, _between=another_worker_wins))
        self.assertEqual(lock.read_text(), "4242")
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), ["worker.lock"])


if __name__ == "__main__":
    unittest.main()
