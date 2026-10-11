"""working-with-fabric: fabric_session.py — where Fabric is, the registrations, and the Claude Code session hooks
(SessionStart preamble, Stop turn observation, SessionEnd release). Hooks are driven with fixtures: a temporary
HOME, a fake hub.json with a live or dead pid, and a fake fabric-mcp that speaks MCP on stdio and records what it
was asked."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/fabric-agent-adapter/skills/working-with-fabric"
SCRIPT = SKILL / "scripts/fabric_session.py"
HOOKS = ROOT / "plugins/fabric-agent-adapter/hooks/hooks.json"
SID = "3bdea652-86ec-487f-b7c0-d8c28241c49a"


def load():
    spec = importlib.util.spec_from_file_location("fabric_session", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fs = load()

FAKE_MCP = textwrap.dedent('''\
    #!{python}
    """A fake fabric-mcp: lists only fabric_whoami until initialized, then announces its session tools."""
    import json, os, sys
    record = os.environ["FAKE_MCP_RECORD"]
    mode = os.environ.get("FAKE_MCP_MODE", "connect")
    def write(kind, value):
        with open(record, "a") as f:
            f.write(json.dumps({{"kind": kind, "value": value}}) + "\\n")
    write("argv", sys.argv[1:])
    write("env", {{"CLAUDE_CODE_SESSION_ID": os.environ.get("CLAUDE_CODE_SESSION_ID")}})
    connected = False
    tools = {{"connect": ["fabric_whoami", "fabric_session_observe", "fabric_work_release", "fabric_tasks_list"],
             "old-fabric": ["fabric_whoami", "fabric_tasks_list", "fabric_task_claim"],
             "refuse": ["fabric_whoami", "fabric_session_observe", "fabric_work_release"],
             "never": ["fabric_whoami"]}}[mode]
    def send(message):
        sys.stdout.write(json.dumps(message) + "\\n"); sys.stdout.flush()
    for line in sys.stdin:
        m = json.loads(line)
        method = m.get("method")
        if method == "initialize":
            send({{"jsonrpc": "2.0", "id": m["id"], "result": {{"protocolVersion": m["params"]["protocolVersion"],
                  "capabilities": {{"tools": {{"listChanged": True}}}}, "serverInfo": {{"name": "fabric", "version": "0.4.0"}}}}}})
        elif method == "notifications/initialized":
            if mode != "never":
                connected = True
                send({{"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}})
        elif method == "tools/list":
            names = tools if connected else ["fabric_whoami"]
            send({{"jsonrpc": "2.0", "id": m["id"], "result": {{"tools": [{{"name": n, "inputSchema": {{"type": "object"}}}} for n in names]}}}})
        elif method == "tools/call":
            write("call", m["params"])
            if mode == "refuse":
                send({{"jsonrpc": "2.0", "id": m["id"], "result": {{"isError": True,
                      "content": [{{"type": "text", "text": "not enrolled /private/path"}}],
                      "structuredContent": {{"error": {{"code": "not-enrolled"}}}}}}}})
            else:
                send({{"jsonrpc": "2.0", "id": m["id"], "result": {{"content": [{{"type": "text", "text": "recorded"}}]}}}})
    write("exit", 0)
''')


class Base(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="fabric-session-"))
        self.home = self.base / "home"
        self.home.mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("XDG_DATA_HOME", "XDG_CACHE_HOME", "LOCALAPPDATA", "CODEX_HOME", "CLAUDE_CODE_SESSION_ID")}
        self.env["HOME"] = str(self.home)
        self.root = fs.fabric_root(env=self.env)
        self.repo = self.base / "work"
        self.repo.mkdir()

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def hub(self, pid=None, features=None, **over):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "hub-door-token").write_text("DOOR-TOKEN-SENTINEL")
        doc = {"protocol": "fabric-hub/0.1", "origin": "http://127.0.0.1:47070", "mcp": "/mcp",
               "doorTokenFile": str(self.root / "hub-door-token"), "pid": pid or os.getpid(),
               "startedAt": "2026-10-11T00:00:00Z"}
        if features is not None:
            doc["features"] = features
        doc.update(over)
        (self.root / "hub.json").write_text(json.dumps(doc))

    def register(self, command="/Applications/Fabric.app/Contents/Resources/bin/fabric-mcp", scope="user", kind=None):
        entry = {"command": command, "args": ["--runner", "claude-code"]}
        if kind:
            entry["type"] = kind
        config = {"mcpServers": {"fabric": entry}} if scope == "user" else {
            "projects": {str(self.repo.resolve()): {"mcpServers": {"fabric": entry}}}}
        (self.home / ".claude.json").write_text(json.dumps(config))

    def dead_pid(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        return proc.pid

    def run_hook(self, event, payload, extra_env=None):
        env = dict(self.env, **(extra_env or {}))
        started = time.perf_counter()
        done = subprocess.run([sys.executable, "-S", str(SCRIPT), "hook", event],
                              input=payload if isinstance(payload, str) else json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=10)
        return done, time.perf_counter() - started

    def log_text(self):
        path = fs.state_root(env=self.env) / "hooks.log"
        return path.read_text() if path.exists() else ""


class Paths(unittest.TestCase):
    def test_fabric_root_per_os_matches_fabric_registry_dirs(self):
        self.assertEqual(fs.fabric_root("darwin", {"HOME": "/Users/a"}),
                         Path("/Users/a/Library/Application Support/ai.passioncode.fabric"))
        self.assertEqual(fs.fabric_root("linux", {"HOME": "/home/a"}), Path("/home/a/.local/share/passioncode-fabric"))
        self.assertEqual(fs.fabric_root("linux", {"HOME": "/home/a", "XDG_DATA_HOME": "/x"}), Path("/x/passioncode-fabric"))
        self.assertEqual(fs.fabric_root("win32", {"HOME": "C:/Users/a", "LOCALAPPDATA": "C:/L"}),
                         Path("C:/L") / "passioncode-fabric")

    def test_fabric_bin_per_os(self):
        self.assertIn(Path("/Applications/Fabric.app/Contents/Resources/bin/fabric-mcp"),
                      fs.fabric_bin_candidates("darwin", {"HOME": "/Users/a"}))
        self.assertEqual(fs.fabric_bin_candidates("linux", {"HOME": "/h"}), [Path("/opt/Fabric/resources/bin/fabric-mcp")])
        (win,) = fs.fabric_bin_candidates("win32", {"HOME": "C:/U", "LOCALAPPDATA": "C:/L"})
        self.assertEqual(win.name, "fabric-mcp.cmd")
        self.assertIn("Programs", win.parts)

    def test_state_root_is_never_fabric_root(self):
        for platform in ("darwin", "linux", "win32"):
            env = {"HOME": "/h", "LOCALAPPDATA": "/L"}
            self.assertNotEqual(fs.state_root(platform, env), fs.fabric_root(platform, env))


class Hub(Base):
    def test_absent_dead_and_foreign_hubs(self):
        self.assertEqual(fs.locate_hub(self.root)["state"], "not-running")
        self.hub(pid=self.dead_pid())
        self.assertEqual(fs.locate_hub(self.root)["state"], "not-running")
        for over in ({"protocol": "other/1"}, {"origin": "http://localhost:47070"}, {"mcp": "/other"}, {"pid": "1"}):
            self.hub(**over)
            self.assertEqual(fs.locate_hub(self.root)["state"], "not-a-hub", over)
        (self.root / "hub.json").write_text("{not json")
        self.assertEqual(fs.locate_hub(self.root)["state"], "not-a-hub")

    def test_a_fifo_is_not_read(self):
        self.root.mkdir(parents=True)
        os.mkfifo(str(self.root / "hub.json"))
        started = time.perf_counter()
        self.assertEqual(fs.locate_hub(self.root)["state"], "not-a-hub")
        self.assertLess(time.perf_counter() - started, 1.0)

    def test_running_hub_and_its_features(self):
        self.hub(features=["session-hooks/1", 3])
        hub = fs.locate_hub(self.root)
        self.assertEqual((hub["state"], hub["features"]), ("running", ["session-hooks/1"]))

    def test_the_door_token_is_never_read(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for needle in ('"doorTokenFile"', "hub-door-token", ".credential", "enrollments", "Authorization"):
            self.assertNotIn(needle, source)


class Registrations(Base):
    def test_user_local_and_project_scopes(self):
        self.assertIsNone(fs.claude_registration(self.repo, self.env))
        self.register()
        reg = fs.claude_registration(self.repo, self.env)
        self.assertEqual((reg["scope"], reg["fabricMcp"], reg["args"]), ("user", True, ["--runner", "claude-code"]))
        self.register(scope="local")
        self.assertEqual(fs.claude_registration(self.repo / "sub", self.env)["scope"], "local")
        (self.home / ".claude.json").unlink()
        (self.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"fabric": {
            "command": "C:\\Fabric\\resources\\bin\\fabric-mcp.cmd", "args": [], "env": {"X": "secret"}}}}))
        reg = fs.claude_registration(self.repo, self.env)
        self.assertEqual((reg["scope"], reg["fabricMcp"]), ("project", True))
        self.assertNotIn("env", reg)

    def test_an_http_entry_is_not_fabric_mcp(self):
        self.register(kind="http")
        self.assertIsNone(fs.claude_registration(self.repo, self.env))

    def test_codex_toml_headers(self):
        codex = self.home / ".codex"
        codex.mkdir()
        self.assertFalse(fs.codex_registered(self.env))
        for header in ('[mcp_servers.fabric]', '["mcp_servers"."fabric"]', '[mcp_servers."fabric"]'):
            (codex / "config.toml").write_text('model = "x"\n%s\ncommand = "/opt/Fabric/resources/bin/fabric-mcp"\n' % header)
            self.assertTrue(fs.codex_registered(self.env), header)
        (codex / "config.toml").write_text('[mcp_servers.fabric-dashboards]\ncommand = "x"\n')
        self.assertFalse(fs.codex_registered(self.env))


class SessionStart(Base):
    def test_silent_when_fabric_is_not_registered(self):
        self.hub()
        done, elapsed = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "startup"})
        self.assertEqual((done.returncode, done.stdout), (0, ""))
        self.assertLess(elapsed, 2.0)

    def test_the_preamble_when_registered_and_running(self):
        self.register()
        self.hub()
        done, elapsed = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "startup"})
        self.assertEqual(done.returncode, 0)
        out = json.loads(done.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        for word in ("fabric_whoami", "fabric_work_list", "fabric_work_claim", "fabric_work_release", "source: {repository, path, id}"):
            self.assertIn(word, out["additionalContext"])
        self.assertNotIn("DOOR-TOKEN-SENTINEL", done.stdout)
        self.assertLess(elapsed, 2.0)

    def test_one_line_when_registered_and_down(self):
        self.register()
        self.hub(pid=self.dead_pid())
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)})
        context = json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("not running", context)
        self.assertIn("lifecycle_ensure_running", context)
        self.assertIn("never launch it yourself", context)

    def test_bad_input_never_fails(self):
        self.register()
        for stdin in ("not json", "", "[]", json.dumps({"cwd": str(self.base / "missing")})):
            done, _ = self.run_hook("session-start", stdin)
            self.assertEqual(done.returncode, 0, stdin)
        (self.home / ".claude.json").write_text("{broken")
        done, _ = self.run_hook("session-start", {"cwd": str(self.repo)})
        self.assertEqual((done.returncode, done.stdout), (0, ""))


class StopAndEndInert(Base):
    def test_without_the_feature_nothing_runs_and_nothing_is_written(self):
        self.register()
        self.hub()  # a Fabric that does not advertise session-hooks/1 — every Fabric up to 0.4.0 wave 1
        spawned = []
        for event in ("turn", "turn", "end"):
            said = fs.hook_spool({"session_id": SID, "cwd": str(self.repo)}, event, self.env, spawn=spawned.append)
            self.assertEqual(said, "inert: this Fabric does not advertise session-hooks/1")
        self.assertEqual(spawned, [], "no fabric-mcp may start: it would enroll a session per turn")
        self.assertFalse(fs.state_root(env=self.env).exists(), "an inert hook writes nothing")
        self.hub(pid=self.dead_pid(), features=["session-hooks/1"])
        self.assertEqual(fs.hook_spool({"session_id": SID, "cwd": str(self.repo)}, "turn", self.env, spawn=spawned.append),
                         "inert: Fabric is not running")
        self.assertEqual(spawned, [])

    def test_silent_and_stateless_when_not_registered(self):
        self.hub(features=["session-hooks/1"])
        self.assertEqual(fs.hook_spool({"session_id": SID, "cwd": str(self.repo)}, "turn", self.env, spawn=self.fail),
                         "skipped: fabric is not registered")
        self.assertFalse(fs.state_root(env=self.env).exists())

    def test_a_bad_session_id_is_refused(self):
        self.register()
        self.hub(features=["session-hooks/1"])
        for sid in ("../../etc", "", None, "a" * 200):
            self.assertEqual(fs.hook_spool({"session_id": sid, "cwd": str(self.repo)}, "turn", self.env, spawn=self.fail),
                             "skipped: no session id")

    def test_the_hook_process_exits_zero_and_fast(self):
        self.register()
        self.hub()
        for event in ("stop", "session-end"):
            done, elapsed = self.run_hook(event, {"session_id": SID, "cwd": str(self.repo)})
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
            self.assertLess(elapsed, 2.0)


class StopAndEndActive(Base):
    def setUp(self):
        super().setUp()
        self.hub(features=["session-hooks/1"])
        self.record = self.base / "record.jsonl"
        fake = self.base / "bin" / "fabric-mcp"
        fake.parent.mkdir()
        fake.write_text(FAKE_MCP.format(python=sys.executable))
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        self.register(command=str(fake))
        self.env["FAKE_MCP_RECORD"] = str(self.record)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        for key, value in (("user.email", "t@example.invalid"), ("user.name", "t"), ("commit.gpgsign", "false")):
            subprocess.run(["git", "-C", str(self.repo), "config", key, value], check=True)
        (self.repo / "tracked.txt").write_text("one\ntwo\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "c"], check=True)
        (self.repo / "tracked.txt").write_text("one\nTWO\nthree\n")
        (self.repo / "private-name.txt").write_text("untracked content\n")

    def records(self, kind):
        if not self.record.exists():
            return []
        return [r["value"] for r in map(json.loads, self.record.read_text().splitlines()) if r["kind"] == kind]

    def spool(self, event, **extra):
        spawned = []
        said = fs.hook_spool(dict({"session_id": SID, "cwd": str(self.repo)}, **extra), event, self.env, spawn=spawned.append)
        return said, spawned

    def test_a_turn_and_the_end_reach_fabric_with_facts_only(self):
        said, spawned = self.spool("turn")
        self.assertEqual(said, "spooled: worker started")
        (entry,) = sorted(spawned[0].glob("*-turn.json"))
        self.assertEqual(sorted(json.loads(entry.read_text())), ["cwd", "event", "observedAt", "runtimeSessionId"])
        self.spool("end", reason="prompt_input_exit")
        lines = fs.deliver(spawned[0], self.env, deadline_s=8)
        (argv,) = self.records("argv")
        self.assertEqual(argv, ["--runner", "claude-code", "--rejoin-only", "--runtime-session-id", SID])
        self.assertEqual(self.records("env"), [{"CLAUDE_CODE_SESSION_ID": SID}])
        calls = self.records("call")
        self.assertEqual([c["name"] for c in calls], ["fabric_session_observe", "fabric_work_release", "fabric_session_observe"])
        turn, release, end = (c["arguments"] for c in calls)
        head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual({k: turn[k] for k in ("event", "runtime", "runtimeSessionId", "head", "filesChanged", "linesAdded", "linesRemoved")},
                         {"event": "turn", "runtime": "claude-code", "runtimeSessionId": SID, "head": head,
                          "filesChanged": 2, "linesAdded": 2, "linesRemoved": 1})
        self.assertEqual((release["claims"], release["outcome"]), ("session", "let-go"))
        self.assertIn("prompt_input_exit", release["reason"])
        self.assertEqual((end["event"], end["reason"]), ("end", "prompt_input_exit"))
        self.assertNotEqual(turn["idempotencyKey"], end["idempotencyKey"])
        sent = json.dumps(calls)
        for leaked in ("private-name", "tracked.txt", "untracked content", "TWO", "DOOR-TOKEN-SENTINEL", str(self.repo)):
            self.assertNotIn(leaked, sent)
        self.assertEqual(len(lines), 3)
        log = self.log_text()
        for leaked in (str(self.repo), "private-name", "DOOR-TOKEN-SENTINEL"):
            self.assertNotIn(leaked, log)
        self.assertFalse(spawned[0].exists(), "the session's folder goes once its end is delivered")
        self.assertEqual(self.records("exit"), [0], "fabric-mcp is closed by the end of its stdin")

    def test_an_older_fabric_without_the_tools_degrades_to_a_log_line(self):
        self.env["FAKE_MCP_MODE"] = "old-fabric"
        _, spawned = self.spool("turn")
        fs.deliver(spawned[0], self.env, deadline_s=8)
        self.spool("turn")
        fs.deliver(spawned[0], self.env, deadline_s=8)
        self.assertEqual(self.records("call"), [])
        self.assertEqual(self.log_text().count("outcome=degraded"), 1)
        self.assertEqual(list(spawned[0].glob("*-turn.json")), [])

    def test_a_refusal_is_logged_by_its_code_never_its_text(self):
        self.env["FAKE_MCP_MODE"] = "refuse"
        _, spawned = self.spool("turn")
        fs.deliver(spawned[0], self.env, deadline_s=8)
        log = self.log_text()
        self.assertIn("answer=refused:not-enrolled", log)
        self.assertNotIn("/private/path", log)

    def test_a_session_that_never_joins_ends_at_the_deadline(self):
        self.env["FAKE_MCP_MODE"] = "never"
        _, spawned = self.spool("turn")
        started = time.perf_counter()
        fs.deliver(spawned[0], self.env, deadline_s=1.0)
        self.assertLess(time.perf_counter() - started, 5.0)
        self.assertIn("outcome=unknown", self.log_text())
        self.assertEqual(self.records("call"), [])

    def test_fabric_gone_before_delivery_drops_the_spool(self):
        _, spawned = self.spool("turn")
        self.hub(features=[])
        fs.deliver(spawned[0], self.env, deadline_s=8)
        self.assertEqual(self.records("argv"), [], "no fabric-mcp starts once the feature is gone")
        self.assertIn("outcome=dropped", self.log_text())
        self.assertEqual(list(spawned[0].glob("*-turn.json")), [])

    def test_one_worker_per_session_and_the_end_always_starts_one(self):
        directory = fs.session_dir(SID, self.env)
        directory.mkdir(parents=True)
        (directory / "worker.lock").write_text("1")
        said, spawned = self.spool("turn")
        self.assertEqual((said, spawned), ("spooled: a worker is running", []))
        said, spawned = self.spool("end")
        self.assertEqual(len(spawned), 1)

    def test_the_spool_is_capped(self):
        directory = fs.session_dir(SID, self.env)
        (directory).mkdir(parents=True)
        (directory / "worker.lock").write_text("1")
        for _ in range(fs.SPOOL_CAP + 7):
            self.spool("turn")
        self.assertEqual(len(list(directory.glob("*-turn.json"))), fs.SPOOL_CAP)

    def test_the_detached_worker_runs_from_the_real_hook(self):
        done, elapsed = self.run_hook("stop", {"session_id": SID, "cwd": str(self.repo)})
        self.assertEqual((done.returncode, done.stdout), (0, ""))
        self.assertLess(elapsed, 2.0, "the hook returns before Fabric is called")
        until = time.monotonic() + 10
        while time.monotonic() < until and not self.records("call"):
            time.sleep(0.1)
        self.assertEqual([c["name"] for c in self.records("call")], ["fabric_session_observe"])


class Status(Base):
    def setUp(self):
        super().setUp()
        self.saved = fs.fabric_bin_candidates
        fs.fabric_bin_candidates = lambda platform=None, env=None: [self.base / "no-fabric" / "fabric-mcp"]

    def tearDown(self):
        fs.fabric_bin_candidates = self.saved
        super().tearDown()

    def test_one_next_action_per_state(self):
        report = fs.status(self.repo, self.env)
        self.assertIn("Install Fabric", report["next"])
        self.register()
        report = fs.status(self.repo, self.env)
        self.assertIn("lifecycle_ensure_running", report["next"])
        self.hub(protocol="x")
        self.assertIn("could not be verified", fs.status(self.repo, self.env)["next"])
        self.hub()
        report = fs.status(self.repo, self.env)
        self.assertEqual((report["next"], report["sessionHooks"]), ("Call fabric_whoami.", "inert"))
        (self.home / ".claude.json").unlink()
        binary = self.base / "no-fabric" / "fabric-mcp"
        binary.parent.mkdir()
        binary.write_text("")
        self.assertEqual(fs.status(self.repo, self.env)["next"],
                         'Register it once: claude mcp add --scope user fabric -- "%s" --runner claude-code' % binary)

    def test_the_cli_prints_and_reads_no_token(self):
        self.register()
        self.hub()
        done = subprocess.run([sys.executable, str(SCRIPT), "status", "--cwd", str(self.repo)],
                              capture_output=True, text=True, env=self.env, timeout=10)
        self.assertEqual(done.returncode, 0)
        self.assertIn("Next: Call fabric_whoami.", done.stdout)
        self.assertNotIn("DOOR-TOKEN-SENTINEL", done.stdout)
        done = subprocess.run([sys.executable, str(SCRIPT), "status", "--json", "--cwd", str(self.repo)],
                              capture_output=True, text=True, env=self.env, timeout=10)
        self.assertEqual(json.loads(done.stdout)["hub"]["state"], "running")


class PluginHooks(unittest.TestCase):
    def test_the_three_events_run_the_script_within_short_timeouts(self):
        hooks = json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]
        expected = {"SessionStart": "hook session-start", "Stop": "hook stop", "SessionEnd": "hook session-end"}
        for event, tail in expected.items():
            commands = [h for e in hooks[event] for h in e["hooks"] if "fabric_session.py" in h["command"]]
            self.assertEqual(len(commands), 1, event)
            (hook,) = commands
            self.assertIn("${CLAUDE_PLUGIN_ROOT}/skills/working-with-fabric/scripts/fabric_session.py", hook["command"])
            self.assertTrue(hook["command"].endswith(tail), hook["command"])
            self.assertLessEqual(hook["timeout"], 5)


if __name__ == "__main__":
    unittest.main()
