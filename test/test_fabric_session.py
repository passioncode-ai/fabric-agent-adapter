"""working-with-fabric: fabric_session.py — where Fabric is, the registrations, the Claude Code session hooks
(SessionStart preamble, Stop turn observation and unread count, SessionEnd release, UserPromptSubmit unread line),
watch-mail and install-host-hooks. Hooks are driven with fixtures: a temporary HOME, a fake hub.json with a live or
dead pid, and a fake fabric-mcp that speaks MCP on stdio and records what it was asked."""

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
    tools = {{"connect": ["fabric_whoami", "fabric_session_observe", "fabric_work_release", "fabric_tasks_list", "com.status"],
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
            if m["params"]["name"] == "com.status":
                board = os.environ.get("FAKE_MCP_BOARD")
                said = open(board).read().strip() if board and os.path.exists(board) else "0"
                if said == "refuse":
                    answer = {{"isError": True, "content": [{{"type": "text", "text": json.dumps({{"error": {{
                        "code": "not_authorized", "message": "secret /private/path", "retryable": False}}}})}}]}}
                elif said.startswith("degraded"):
                    answer = {{"content": [{{"type": "text", "text": json.dumps({{"protocol": "fabric-project-comms/0.1",
                        "board": {{"state": "degraded", "reason": "Telegram is off."}}, "project": "p1", "responders": [],
                        "unread": int(said.split(":")[1])}})}}]}}
                elif said == "unavailable":
                    answer = {{"content": [{{"type": "text", "text": json.dumps({{"protocol": "fabric-project-comms/0.1",
                        "board": {{"state": "unavailable", "reason": "The board could not be read."}}, "project": "p1",
                        "responders": [], "transport": {{"telegram": "off"}}}})}}]}}
                else:
                    answer = {{"content": [{{"type": "text", "text": json.dumps({{"protocol": "fabric-project-comms/0.1",
                        "board": {{"state": "ready"}}, "project": "p1", "responders": [], "transport": {{"telegram": "off"}},
                        "unread": int(said)}})}}]}}
                send({{"jsonrpc": "2.0", "id": m["id"], "result": answer}})
            elif mode == "refuse":
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
                    if k not in ("XDG_DATA_HOME", "XDG_CACHE_HOME", "LOCALAPPDATA", "CODEX_HOME", "CLAUDE_CODE_SESSION_ID",
                                 "FABRIC_SERVICES_DIR", "FABRIC_LAUNCHED_SESSION", "FABRIC_ACP_SESSION",
                                 "FABRIC_BRIDGE_URL", "KILO_CONFIG_CONTENT")}
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

    def run_hook(self, event, payload, extra_env=None, args=(), wrapper=()):
        env = dict(self.env, **(extra_env or {}))
        started = time.perf_counter()
        done = subprocess.run(list(wrapper) + [sys.executable, "-S", str(SCRIPT), "hook", event] + list(args),
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
        for word in ("fabric_whoami", "fabric_work_list", "fabric_work_claim", "fabric_work_release", "source: {repository, path, id}",
                     "com.status", "com.list", "com.read_ack", "com.submit"):
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
        while time.monotonic() < until and len(self.records("call")) < 2:
            time.sleep(0.1)
        self.assertEqual([c["name"] for c in self.records("call")], ["fabric_session_observe", "com.status"])


class Active(Base):
    """A running Fabric that advertises session-hooks/1, a fake fabric-mcp registered as `fabric`, a git repository."""

    def setUp(self):
        super().setUp()
        self.hub(features=["session-hooks/1"])
        self.record = self.base / "record.jsonl"
        self.board = self.base / "board.txt"
        fake = self.base / "bin" / "fabric-mcp"
        fake.parent.mkdir()
        fake.write_text(FAKE_MCP.format(python=sys.executable))
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        self.fake = fake
        self.register(command=str(fake))
        self.env["FAKE_MCP_RECORD"] = str(self.record)
        self.env["FAKE_MCP_BOARD"] = str(self.board)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def records(self, kind):
        if not self.record.exists():
            return []
        return [r["value"] for r in map(json.loads, self.record.read_text().splitlines()) if r["kind"] == kind]

    def unread(self, value):
        self.board.write_text(str(value))

    def turn(self):
        spawned = []
        fs.hook_spool({"session_id": SID, "cwd": str(self.repo)}, "turn", self.env, spawn=spawned.append)
        fs.deliver(spawned[0], self.env, deadline_s=8)
        return spawned[0]

    def prompt(self, extra_env=None):
        done, elapsed = self.run_hook("user-prompt-submit", {"session_id": SID, "cwd": str(self.repo), "prompt": "x"},
                                      extra_env=extra_env)
        self.assertEqual(done.returncode, 0)
        self.assertLess(elapsed, 2.0)
        return json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"] if done.stdout.strip() else None


class BoardUnread(Active):
    def test_the_stop_worker_writes_the_unread_count_to_the_session_spool(self):
        self.unread(3)
        directory = self.turn()
        self.assertEqual([c["name"] for c in self.records("call")], ["fabric_session_observe", "com.status"])
        board = json.loads((directory / "board.json").read_text())
        self.assertEqual(board["unread"], 3)
        self.assertEqual(stat.S_IMODE((directory / "board.json").stat().st_mode), 0o600)
        self.assertIn("tool=com.status answer=ok unread=3", self.log_text())

    def test_an_unreadable_board_or_a_refusal_is_no_count(self):
        for said in ("unavailable", "refuse"):
            self.unread(said)
            directory = self.turn()
            self.assertIsNone(json.loads((directory / "board.json").read_text())["unread"], said)
        log = self.log_text()
        self.assertIn("board=unavailable", log)
        self.assertIn("answer=refused:not_authorized", log)
        self.assertNotIn("/private/path", log)

    def test_a_degraded_board_that_gives_a_count_is_read(self):
        self.unread("degraded:2")
        directory = self.turn()
        self.assertEqual(json.loads((directory / "board.json").read_text())["unread"], 2)
        self.assertIn("answer=ok unread=2 board=degraded", self.log_text())
        self.assertEqual(fs.board_unread({"structuredContent": {"board": {"state": "degraded"}}})[0], None,
                         "degraded and no count: still no count")

    def test_the_end_of_a_session_asks_no_board_status(self):
        self.unread(2)
        spawned = []
        fs.hook_spool({"session_id": SID, "cwd": str(self.repo)}, "end", self.env, spawn=spawned.append)
        fs.deliver(spawned[0], self.env, deadline_s=8)
        self.assertNotIn("com.status", [c["name"] for c in self.records("call")])

    def test_the_prompt_hook_prints_one_line_only_when_the_count_rises(self):
        self.assertIsNone(self.prompt(), "no count yet: silent")
        self.unread(2)
        self.turn()
        self.assertEqual(self.prompt(), "2 unread on the project board — com.list")
        self.assertIsNone(self.prompt(), "the same count is not repeated")
        self.unread(1)
        self.turn()
        self.assertIsNone(self.prompt(), "a fall is not news")
        self.unread(4)
        self.turn()
        self.assertEqual(self.prompt(), "4 unread on the project board — com.list")
        self.unread(0)
        self.turn()
        self.assertIsNone(self.prompt())

    def test_the_prompt_hook_survives_a_broken_spool(self):
        directory = fs.session_dir(SID, self.env)
        directory.mkdir(parents=True)
        for text in ("{broken", json.dumps({"unread": "3"}), json.dumps({"unread": -1}), json.dumps([1])):
            (directory / "board.json").write_text(text)
            self.assertIsNone(self.prompt(), text)
        for stdin in ("not json", "", json.dumps({"session_id": "../x"})):
            done, _ = self.run_hook("user-prompt-submit", stdin)
            self.assertEqual((done.returncode, done.stdout), (0, ""))


class WatchMail(Active):
    def watch(self, polls, interval=60, **kw):
        """Run watch_mail with fake time: stop after `polls` polls; return (exit code, printed lines, sleeps)."""
        printed, sleeps, done = [], [], {"polls": 0}
        real_poll = kw.pop("poll", None) or (lambda: fs.poll_unread(SID, self.repo, self.env, deadline_s=8))

        def poll():
            done["polls"] += 1
            return real_poll()

        code = fs.watch_mail(SID, self.repo, self.env, interval=interval, poll=poll, out=printed.append,
                             wait=lambda seconds: sleeps.append(seconds) or False,
                             stop=lambda: done["polls"] >= polls, rng=kw.pop("rng", lambda: 0.5), **kw)
        return code, printed, sleeps

    def test_prints_when_the_unread_count_rises(self):
        counts = iter([0, 2, 2, 1, 3])
        code, printed, sleeps = self.watch(5, poll=lambda: ("ok", next(counts)))
        self.assertEqual(code, 0)
        self.assertEqual(printed, ["2 unread on the project board — com.list", "3 unread on the project board — com.list"])
        self.assertEqual(sleeps, [60.0] * 5)

    def test_jitter_stays_within_twenty_percent(self):
        for r, expected in ((0.0, 48.0), (1.0, 72.0)):
            _, _, sleeps = self.watch(1, poll=lambda: ("ok", 0), rng=lambda r=r: r)
            self.assertEqual(len(sleeps), 1)
            self.assertAlmostEqual(sleeps[0], expected)

    def test_fabric_down_backs_off_to_a_bound_and_says_so_once(self):
        _, printed, sleeps = self.watch(8, interval=60, poll=lambda: ("down", "Fabric is not running"))
        self.assertEqual(sleeps, [120.0, 240.0, 480.0, 900.0, 900.0, 900.0, 900.0, 900.0])
        self.assertEqual(len(printed), 1)
        self.assertIn("Fabric is not running", printed[0])
        self.assertNotIn("unread", printed[0])

    def test_recovery_resets_the_interval(self):
        answers = iter([("down", "x"), ("down", "x"), ("ok", 1), ("ok", 1)])
        _, printed, sleeps = self.watch(4, poll=lambda: next(answers))
        self.assertEqual(sleeps, [120.0, 240.0, 60.0, 60.0])
        self.assertEqual(printed[-1], "1 unread on the project board — com.list")

    def test_the_interval_has_a_floor_so_it_never_spins(self):
        _, _, sleeps = self.watch(2, interval=0, poll=lambda: ("ok", 0))
        self.assertEqual(sleeps, [float(fs.WATCH_MIN_INTERVAL_S)] * 2)

    def test_a_real_poll_through_fake_fabric_mcp(self):
        self.unread(5)
        self.assertEqual(fs.poll_unread(SID, self.repo, self.env, deadline_s=8), ("ok", 5))
        (argv,) = self.records("argv")
        self.assertEqual(argv[-3:], ["--rejoin-only", "--runtime-session-id", SID])
        self.unread("unavailable")
        self.assertEqual(fs.poll_unread(SID, self.repo, self.env, deadline_s=8)[0], "unavailable")
        self.hub(features=[])
        self.assertEqual(fs.poll_unread(SID, self.repo, self.env, deadline_s=8)[0], "down")
        self.hub(pid=self.dead_pid(), features=["session-hooks/1"])
        self.assertEqual(fs.poll_unread(SID, self.repo, self.env, deadline_s=8)[0], "down")
        self.assertEqual(len(self.records("argv")), 2, "no fabric-mcp starts while Fabric is down")

    def test_the_cli_needs_a_session_id_and_exits_on_stdin_close(self):
        done = subprocess.run([sys.executable, str(SCRIPT), "watch-mail", "--cwd", str(self.repo)],
                              capture_output=True, text=True, env=self.env, timeout=10)
        self.assertEqual(done.returncode, 2)
        self.assertIn("CLAUDE_CODE_SESSION_ID", done.stderr)
        self.unread(1)
        proc = subprocess.Popen([sys.executable, str(SCRIPT), "watch-mail", "--interval", "10", "--cwd", str(self.repo)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                env=dict(self.env, CLAUDE_CODE_SESSION_ID=SID))
        line = proc.stdout.readline()
        self.assertEqual(line.strip(), "1 unread on the project board — com.list")
        started = time.perf_counter()
        proc.stdin.close()
        self.assertEqual(proc.wait(timeout=10), 0)
        self.assertLess(time.perf_counter() - started, 8.0)
        proc.stdout.close()

    def test_the_cli_exits_on_a_signal(self):
        import signal
        proc = subprocess.Popen([sys.executable, str(SCRIPT), "watch-mail", "--interval", "10", "--cwd", str(self.repo)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True,
                                env=dict(self.env, CLAUDE_CODE_SESSION_ID=SID))
        until = time.monotonic() + 10
        while time.monotonic() < until and not self.records("call"):
            time.sleep(0.1)
        self.assertIsNone(proc.poll(), "stdin from /dev/null is not a closed pipe: keep watching")
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(proc.wait(timeout=10), 0)
        proc.stdout.close()


class LaunchedByFabric(Active):
    def test_the_marker_and_existing_signals(self):
        self.assertIsNone(fs.fabric_launched(self.env))
        for extra in ({"FABRIC_LAUNCHED_SESSION": "1"}, {"FABRIC_ACP_SESSION": "x"}, {"FABRIC_BRIDGE_URL": "x"},
                      {"KILO_CONFIG_CONTENT": "x"}, {"CODEX_HOME": str(self.root / "sessions" / "s1" / "codex-home")}):
            self.assertIsNotNone(fs.fabric_launched(dict(self.env, **extra)), extra)
        for extra in ({"FABRIC_LAUNCHED_SESSION": "0"}, {"FABRIC_LAUNCHED_SESSION": ""},
                      {"CODEX_HOME": str(self.home / ".codex")}):
            self.assertIsNone(fs.fabric_launched(dict(self.env, **extra)), extra)

    def test_every_hook_is_silent_in_a_launched_session(self):
        services = self.home / "services"
        services.mkdir()
        (services / "a.default.json").write_text('{"origin": "http://127.0.0.1:1"}')
        self.env["FABRIC_SERVICES_DIR"] = str(services)
        marker = {"FABRIC_LAUNCHED_SESSION": "1"}
        for host in ("claude", "codex", "kimi"):
            done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)}, extra_env=marker,
                                    args=["--host", host])
            self.assertEqual((done.returncode, done.stdout), (0, ""), host)
        self.assertEqual(fs.hook_spool({"session_id": SID, "cwd": str(self.repo)}, "turn", dict(self.env, **marker),
                                       spawn=self.fail), "skipped: launched by Fabric")
        directory = fs.session_dir(SID, self.env)
        directory.mkdir(parents=True)
        (directory / "board.json").write_text(json.dumps({"unread": 3}))
        self.assertIsNone(self.prompt(extra_env=marker))

    @unittest.skipIf(sys.platform == "win32", "the ancestor check reads POSIX process tables")
    def test_a_claude_code_fabric_started_is_recognised_by_its_mcp_config(self):
        wrapper = [sys.executable, "-c",
                   "import subprocess, sys; i = sys.argv.index('--'); sys.exit(subprocess.run(sys.argv[i + 1:]).returncode)",
                   "--mcp-config", str(self.root / "sessions" / "s1" / "mcp.json"), "--strict-mcp-config", "--"]
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)}, wrapper=wrapper)
        self.assertEqual((done.returncode, done.stdout), (0, ""))
        elsewhere = [a if a != str(self.root / "sessions" / "s1" / "mcp.json") else str(self.base / "mcp.json") for a in wrapper]
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)}, wrapper=elsewhere)
        self.assertIn("fabric_whoami", done.stdout)


class ServicesLine(Base):
    NOTE = ("Fabric on this machine: {total} service descriptors in {dir} ({local} local on 127.0.0.1), protocol "
            "fabric-service/0.1 — probe GET <origin>/.well-known/fabric-service, or call the fabric-dashboards MCP "
            "list_services if connected. Never kill these services directly; their supervisor owns them.")

    def services(self):
        directory = self.base / "svc"
        directory.mkdir()
        (directory / "a.default.json").write_text('{\n  "origin": "http://127.0.0.1:4100",\n  "auth": {}\n}')
        (directory / "b.default.json").write_text('{"origin": "http://localhost:4200"}')
        (directory / "c.default.json").write_text('{"origin": "https://example.invalid"}')
        (directory / "notes.txt").write_text("not a descriptor")
        (directory / ".a.default.json.tmp.json").write_text('{"origin": "http://127.0.0.1:1"}')  # hidden: not counted
        self.env["FABRIC_SERVICES_DIR"] = str(directory)
        return directory

    def test_the_line_matches_the_machine_note(self):
        self.assertIsNone(fs.services_line(self.env))
        directory = self.services()
        self.assertEqual(fs.services_line(self.env), self.NOTE.format(total=3, dir=directory, local=2))

    def test_default_services_folder_per_os(self):
        self.assertEqual(fs.services_dir("darwin", {"HOME": "/Users/a"}),
                         Path("/Users/a/Library/Application Support/ai.passioncode.fabric/services"))
        self.assertEqual(fs.services_dir("linux", {"HOME": "/h"}), Path("/h/.local/share/passioncode-fabric/services"))
        self.assertEqual(fs.services_dir("win32", {"HOME": "C:/U", "LOCALAPPDATA": "C:/L"}),
                         Path("C:/L") / "passioncode-fabric" / "services")
        self.assertEqual(fs.services_dir("darwin", {"HOME": "/h", "FABRIC_SERVICES_DIR": "/s"}), Path("/s"))

    def test_session_start_carries_it_for_every_host(self):
        directory = self.services()
        line = self.NOTE.format(total=3, dir=directory, local=2)
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)})
        self.assertEqual(json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"], line)
        for host in ("codex", "kimi"):
            done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)}, args=["--host", host])
            self.assertEqual(done.stdout.strip(), line, host)


class OtherHosts(Base):
    def test_codex_gets_the_preamble_as_text_when_registered(self):
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)}, args=["--host", "codex"])
        self.assertEqual((done.returncode, done.stdout), (0, ""), "not registered: silent")
        codex = self.home / ".codex"
        codex.mkdir()
        (codex / "config.toml").write_text('[mcp_servers.fabric]\ncommand = "/opt/Fabric/resources/bin/fabric-mcp"\n')
        self.hub()
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)}, args=["--host", "codex"])
        self.assertIn("this Codex has its MCP server `fabric`", done.stdout)
        for word in ("fabric_whoami", "com.status", "com.list", "com.submit"):
            self.assertIn(word, done.stdout)
        self.assertNotIn("hookSpecificOutput", done.stdout)

    def test_kimi_reads_its_own_mcp_json(self):
        kimi = self.home / ".kimi-code"
        kimi.mkdir()
        (kimi / "mcp.json").write_text(json.dumps({"mcpServers": {"fabric": {"command": "/x/fabric-mcp", "args": []}}}))
        self.hub(pid=self.dead_pid())
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)}, args=["--host", "kimi"])
        self.assertIn("Fabric is not running", done.stdout)
        self.assertIn("lifecycle_ensure_running", done.stdout)

    def test_no_rejoin_for_other_hosts(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('RUNNER = "claude-code"', source)
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)}, args=["--host", "other"])
        self.assertEqual((done.returncode, done.stdout), (0, ""))


class InstallHostHooks(Base):
    SCRIPT_PATH = "/opt/skills/working-with-fabric/scripts/fabric_session.py"

    def install(self, host, *flags, config=None):
        argv = ["install-host-hooks", "--host", host, "--script", self.SCRIPT_PATH] + list(flags)
        if config:
            argv += ["--config", str(config)]
        out, err = [], []
        code = fs.install_host_hooks_cli(argv[1:], env=self.env, out=out.append, err=err.append)
        return code, "\n".join(out + err), "\n".join(err)

    def codex_file(self, doc):
        path = self.home / ".codex" / "hooks.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(doc, indent=2))
        path.chmod(0o640)
        return path

    def test_dry_run_is_the_default_and_writes_nothing(self):
        path = self.codex_file({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "other", "timeout": 5}]}]}})
        before = path.read_bytes()
        code, out, _ = self.install("codex")
        self.assertEqual(code, 0)
        self.assertIn("dry run", out)
        self.assertIn("hook session-start --host codex", out)
        self.assertIn(str(path), out)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.glob("*.bak")), [])

    def test_the_dry_run_prints_no_value_from_the_file(self):
        self.codex_file({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "timeout": 5,
                                                              "command": "env TOKEN=VALUE-SENTINEL other"}]}]}})
        code, out, _ = self.install("codex")
        self.assertEqual(code, 0)
        self.assertNotIn("VALUE-SENTINEL", out)
        self.kimi_file('[providers.x]\napi_key = "VALUE-SENTINEL"\n')
        code, out, _ = self.install("kimi")
        self.assertEqual(code, 0)
        self.assertNotIn("VALUE-SENTINEL", out)

    def test_apply_backs_up_adds_one_entry_and_keeps_the_rest(self):
        original = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "other", "timeout": 5}]}],
                              "Stop": [{"hooks": [{"type": "command", "command": "keep"}]}]}}
        path = self.codex_file(original)
        before = path.read_bytes()
        code, out, _ = self.install("codex", "--apply")
        self.assertEqual(code, 0, out)
        (backup,) = path.parent.glob("hooks.json.*.bak")
        self.assertEqual(backup.read_bytes(), before)
        doc = json.loads(path.read_text())
        self.assertEqual(doc["hooks"]["Stop"], original["hooks"]["Stop"])
        self.assertEqual(doc["hooks"]["SessionStart"][0], original["hooks"]["SessionStart"][0])
        (ours,) = [h for e in doc["hooks"]["SessionStart"] for h in e["hooks"] if "fabric_session.py" in h["command"]]
        self.assertEqual(ours["command"], "python3 -S %s hook session-start --host codex" % self.SCRIPT_PATH)
        self.assertLessEqual(ours["timeout"], 5)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        code, out, _ = self.install("codex", "--apply")
        self.assertEqual(code, 0)
        self.assertIn("already", out)
        self.assertEqual(len(list(path.parent.glob("hooks.json.*.bak"))), 1, "nothing to change: no second backup")
        code, out, _ = self.install("codex", "--remove")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(path.read_text()), original)

    def test_a_missing_file_is_created_on_apply_only(self):
        path = self.home / ".codex" / "hooks.json"
        code, out, _ = self.install("codex")
        self.assertEqual(code, 0)
        self.assertFalse(path.exists())
        code, out, _ = self.install("codex", "--apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(json.loads(path.read_text())["hooks"]["SessionStart"]), 1)

    def test_a_changed_shape_is_refused(self):
        for doc in ({"hooks": []}, {"hooks": {"SessionStart": {"x": 1}}}, [1], {"hooks": {"SessionStart": [{"hooks": "x"}]}}):
            path = self.codex_file(doc)
            before = path.read_bytes()
            code, _, err = self.install("codex", "--apply")
            self.assertEqual(code, 1, doc)
            self.assertIn("shape", err)
            self.assertEqual(path.read_bytes(), before)
        path.write_text("{broken")
        code, _, err = self.install("codex", "--apply")
        self.assertEqual(code, 1)

    def test_a_file_that_changed_since_the_dry_run_is_refused(self):
        path = self.codex_file({"hooks": {}})
        code, out, _ = self.install("codex")
        digest = [line.split()[-1] for line in out.splitlines() if "sha256" in line][0]
        path.write_text(json.dumps({"hooks": {"Stop": []}}))
        code, _, err = self.install("codex", "--apply", "--expect-sha256", digest)
        self.assertEqual(code, 1)
        self.assertIn("changed", err)

    def kimi_file(self, text):
        path = self.home / ".kimi-code" / "config.toml"
        path.parent.mkdir(exist_ok=True)
        path.write_text(text)
        return path

    @unittest.skipIf(fs.tomllib is None, "tomllib needs Python 3.11")
    def test_kimi_appends_one_hooks_table_and_removes_it_exactly(self):
        original = ('default_model = "m"\n\n[[hooks]]\nevent = "SessionStart"\ncommand = "other"\ntimeout = 5\n'
                    '# >>> managed (do not edit) >>>\n[[hooks]]\nevent = "Stop"\ncommand = "keep"\n# <<< managed <<<\n')
        path = self.kimi_file(original)
        code, out, _ = self.install("kimi")
        self.assertEqual(path.read_text(), original)
        self.assertIn('event = "SessionStart"', out)
        code, out, _ = self.install("kimi", "--apply")
        self.assertEqual(code, 0, out)
        text = path.read_text()
        self.assertTrue(text.startswith(original))
        hooks = fs.tomllib.loads(text)["hooks"]
        self.assertEqual(len(hooks), 3)
        self.assertEqual(hooks[-1]["command"], "python3 -S %s hook session-start --host kimi" % self.SCRIPT_PATH)
        (backup,) = path.parent.glob("config.toml.*.bak")
        self.assertEqual(backup.read_text(), original)
        code, out, _ = self.install("kimi", "--apply")
        self.assertIn("already", out)
        code, out, _ = self.install("kimi", "--remove")
        self.assertEqual(code, 0, out)
        self.assertEqual(path.read_text(), original)

    @unittest.skipIf(fs.tomllib is None, "tomllib needs Python 3.11")
    def test_kimi_refuses_a_hooks_key_of_another_shape(self):
        for text in ('hooks = "x"\n', '[hooks]\nevent = "x"\n', "not = [toml\n"):
            path = self.kimi_file(text)
            code, _, err = self.install("kimi", "--apply")
            self.assertEqual(code, 1, text)
            self.assertEqual(path.read_text(), text)

    def test_kimi_apply_without_a_toml_reader_is_refused(self):
        path = self.kimi_file('default_model = "m"\n')
        saved = fs.tomllib
        fs.tomllib = None
        try:
            code, _, err = self.install("kimi", "--apply")
        finally:
            fs.tomllib = saved
        self.assertEqual(code, 1)
        self.assertIn("3.11", err)
        self.assertEqual(path.read_text(), 'default_model = "m"\n')

    def test_an_unknown_host_is_refused(self):
        code, _, err = self.install("claude", "--apply")
        self.assertEqual(code, 2)


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
    def test_the_four_events_run_the_script_within_short_timeouts(self):
        hooks = json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]
        expected = {"SessionStart": "hook session-start", "Stop": "hook stop", "SessionEnd": "hook session-end",
                    "UserPromptSubmit": "hook user-prompt-submit"}
        for event, tail in expected.items():
            commands = [h for e in hooks[event] for h in e["hooks"] if "fabric_session.py" in h["command"]]
            self.assertEqual(len(commands), 1, event)
            (hook,) = commands
            self.assertIn("${CLAUDE_PLUGIN_ROOT}/skills/working-with-fabric/scripts/fabric_session.py", hook["command"])
            self.assertTrue(hook["command"].endswith(tail), hook["command"])
            self.assertLessEqual(hook["timeout"], 5)


if __name__ == "__main__":
    unittest.main()
