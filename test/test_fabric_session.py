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
from unittest import mock


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
             "never": ["fabric_whoami"], "no-session": ["fabric_whoami"]}}[mode]
    def send(message):
        sys.stdout.write(json.dumps(message) + "\\n"); sys.stdout.flush()
    for line in sys.stdin:
        m = json.loads(line)
        method = m.get("method")
        if method == "initialize":
            send({{"jsonrpc": "2.0", "id": m["id"], "result": {{"protocolVersion": m["params"]["protocolVersion"],
                  "capabilities": {{"tools": {{"listChanged": True}}}}, "serverInfo": {{"name": "fabric", "version": "0.4.0"}}}}}})
        elif method == "notifications/initialized":
            if mode == "no-session":  # Fabric 0.3.9 (TR-11): a rejoin that finds no session exits 3 at once
                write("exit", 3)
                sys.exit(3)
            if mode != "never":
                connected = True
                send({{"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}})
        elif method == "tools/list":
            names = tools if connected else ["fabric_whoami"]
            def schema(n):
                if n == "fabric_work_release" and os.environ.get("FAKE_MCP_RELEASE_OBSERVED"):
                    return {{"type": "object", "properties": {{"claims": {{"type": "string"}}, "observedAt": {{"type": "string"}}}}}}
                shape = os.environ.get("FAKE_MCP_OBSERVE_REPOSITORIES")
                if n == "fabric_session_observe" and shape:
                    items = {{"type": "string"}} if shape == "strings" else {{"type": "object", "properties": {{k: {{"type": "string"}} for k in ("host", "owner", "name", "path")}}}}
                    if shape == "required-path":
                        items["required"] = ["host", "owner", "name", "path"]
                    field = {{"type": "array", "items": items}}
                    if shape == "max1":
                        field["maxItems"] = 1
                    if shape == "owner-flat":
                        items["properties"]["owner"]["pattern"] = "^[^/]+$"
                    if shape == "untyped":
                        field.pop("type")
                    return {{"type": "object", "properties": {{"event": {{"type": "string"}}, "repositories": field}}}}
                return {{"type": "object"}}
            send({{"jsonrpc": "2.0", "id": m["id"], "result": {{"tools": [{{"name": n, "inputSchema": schema(n)}} for n in names]}}}})
        elif method == "tools/call":
            write("call", m["params"])
            if m["params"]["name"] == os.environ.get("FAKE_MCP_HANG_ON"):
                continue  # this call is never answered: the worker's deadline ends it
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
            elif m["params"]["name"] == "fabric_session_observe" and os.environ.get("FAKE_MCP_NUDGES") \
                    and os.path.exists(os.environ["FAKE_MCP_NUDGES"]):
                # Fabric 0.3.14 (FAA-142): a turn's answer may carry nudges; the file holds the answer's JSON.
                text = open(os.environ["FAKE_MCP_NUDGES"]).read()
                send({{"jsonrpc": "2.0", "id": m["id"], "result": {{"content": [{{"type": "text", "text": text}}]}}}})
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

    def fabric_mcp(self, script):
        """How a host runs `script` as fabric-mcp: the file itself (its shebang) on POSIX; on Windows, which runs no
        shebang, a .cmd beside it, the way Fabric ships fabric-mcp.cmd there."""
        if sys.platform != "win32":
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
            return script
        wrapper = script.with_name(script.name + ".cmd")
        wrapper.write_text('@"%s" "%s" %%*\r\n' % (sys.executable, script))
        return wrapper

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


class Annotations(unittest.TestCase):
    def test_the_worker_lock_hints_resolve(self):
        """FAA-68: _try_lock's annotation names Callable; without its import get_type_hints raised NameError."""
        import typing
        fabric_session_mcp = importlib.import_module("fabric_session_mcp")
        hints = typing.get_type_hints(fabric_session_mcp._try_lock)
        self.assertEqual(hints["return"], bool)


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

    @unittest.skipIf(sys.platform == "win32", "Windows has no FIFO in the file system (os.mkfifo)")
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
        (self.repo / "fabric-agent.json").write_text("{}")  # the project works through Fabric (FAA-60)
        done, elapsed = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "startup"})
        self.assertEqual(done.returncode, 0)
        out = json.loads(done.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        for word in ("fabric_whoami", "fabric_work_list", "fabric_work_claim", "fabric_work_release", "source: {repository, path, id}",
                     "com.status", "com.list", "com.read_ack", "com.submit"):
            self.assertIn(word, out["additionalContext"])
        self.assertNotIn("DOOR-TOKEN-SENTINEL", done.stdout)
        self.assertLess(elapsed, 2.0)

    def test_a_pointer_when_running_in_a_project_without_a_sign(self):
        # FAA-60: `fabric` at user scope reaches every folder; one line points at fabric_whoami instead of the routine.
        self.register()
        self.hub()
        done, elapsed = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "startup"})
        context = json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(context, fs.POINTER.format(host="Claude Code"))
        self.assertEqual(len(context.splitlines()), 1)
        self.assertLessEqual(len(context), 320)
        self.assertIn("fabric_whoami", context)
        self.assertIn("working-with-fabric", context)
        self.assertNotIn("com.status", context)
        self.assertNotIn("\u2014", context)
        self.assertLess(elapsed, 2.0)
        self.register(scope="project")  # bound to this folder: the routine
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "startup"})
        self.assertEqual(json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"], fs.PREAMBLE.format(host="Claude Code"))

    def test_one_short_line_when_registered_down_and_the_project_uses_fabric(self):
        self.register()
        self.hub(pid=self.dead_pid())
        (self.repo / "fabric-agent.json").write_text("{}")
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "startup"})
        context = json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(context, fs.DOWN_NOTICE)
        self.assertEqual(len(context.splitlines()), 1)
        self.assertLessEqual(len(context), 240)
        self.assertIn("not running", context)
        self.assertIn("skip `fabric_whoami`", context)
        self.assertIn("lifecycle_ensure_running", context)
        self.assertIn("never launch it yourself", context)
        self.assertNotIn("\u2014", context)

    def test_silent_when_down_in_a_project_that_does_not_use_fabric(self):
        self.register()  # user scope: every folder of the machine sees it, so it says nothing about this project
        for hub in (lambda: None, lambda: self.hub(pid=self.dead_pid())):
            hub()
            for host in ("claude", "codex", "kimi"):
                if host == "codex":
                    (self.home / ".codex").mkdir(exist_ok=True)
                    (self.home / ".codex" / "config.toml").write_text('[mcp_servers.fabric]\ncommand = "fabric-mcp"\n')
                done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "startup"},
                                        args=["--host", host])
                self.assertEqual((done.returncode, done.stdout), (0, ""), host)

    def test_compact_and_resume_are_silent(self):
        self.register()
        self.hub()
        for source in ("compact", "resume"):
            done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": source})
            self.assertEqual((done.returncode, done.stdout), (0, ""), source)
        for source in ("startup", "clear", None):
            payload = {"session_id": SID, "cwd": str(self.repo)}
            if source:
                payload["source"] = source
            done, _ = self.run_hook("session-start", payload)
            self.assertIn("fabric_whoami", done.stdout, source)

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
        self.active_repository()

    def active_repository(self):
        self.hub(features=["session-hooks/1"])
        self.record = self.base / "record.jsonl"
        fake = self.base / "bin" / "fabric-mcp"
        fake.parent.mkdir()
        fake.write_text(FAKE_MCP.format(python=sys.executable))
        self.register(command=str(self.fabric_mcp(fake)))
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
        self.assertEqual(sorted(json.loads(entry.read_text())), ["cwd", "event", "facts", "observedAt", "runtimeSessionId"])
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

    def test_an_end_whose_release_never_answered_stays_for_the_next_worker(self):
        """FAA-68: `ended` was set before the release call, so a release that timed out removed the whole spool and
        the claim release was never retried. The end entry stays; a later worker sends the release once."""
        _, spawned = self.spool("end", reason="prompt_input_exit")
        self.env["FAKE_MCP_HANG_ON"] = "fabric_work_release"
        # The deadline is what ends the hanging call, so it must leave the fake fabric-mcp time to start, shake hands and
        # receive the call even on a loaded machine: at 1.5 s it sometimes had not reached the call (FAA-101).
        fs.deliver(spawned[0], self.env, deadline_s=6)
        self.assertIn("outcome=unknown", self.log_text())
        self.assertTrue(spawned[0].is_dir(), "the session's folder stays while its end is undelivered")
        self.assertEqual(len(list(spawned[0].glob("*-end.json"))), 1, "the end entry stays for the next worker")
        self.assertEqual([c["name"] for c in self.records("call")], ["fabric_work_release"])
        del self.env["FAKE_MCP_HANG_ON"]
        fs.deliver(spawned[0], self.env, deadline_s=8)
        calls = self.records("call")
        self.assertEqual([c["name"] for c in calls[1:]], ["fabric_work_release", "fabric_session_observe"],
                         "the later worker sends the release once, then the end observation")
        self.assertEqual(calls[0]["arguments"]["idempotencyKey"], calls[1]["arguments"]["idempotencyKey"],
                         "the retried release carries the same key")
        self.assertFalse(spawned[0].exists(), "the folder goes once the end is delivered")

    def test_the_release_carries_observed_at_where_its_schema_names_it(self):
        """Fabric 0.3.9 (board thread 02bf19c5, ask 1): the session-wide release says when the end was observed, so the
        hub refuses an end from before the session enrolled (`stale-end`)."""
        self.env["FAKE_MCP_RELEASE_OBSERVED"] = "1"
        _, spawned = self.spool("end", reason="prompt_input_exit")
        (entry,) = spawned[0].glob("*-end.json")
        observed = json.loads(entry.read_text())["observedAt"]
        fs.deliver(spawned[0], self.env, deadline_s=8)
        (release,) = [c["arguments"] for c in self.records("call") if c["name"] == "fabric_work_release"]
        self.assertEqual(release["observedAt"], observed)

    def test_the_release_leaves_observed_at_out_where_its_schema_does_not_name_it(self):
        """A host whose release schema is strict and older than 0.3.9 would refuse the field: it is sent only where
        the tool's advertised input schema names it."""
        _, spawned = self.spool("end", reason="prompt_input_exit")
        fs.deliver(spawned[0], self.env, deadline_s=8)
        (release,) = [c["arguments"] for c in self.records("call") if c["name"] == "fabric_work_release"]
        self.assertNotIn("observedAt", release)

    def test_clear_ends_nothing(self):
        """Fabric 0.3.9 (02bf19c5, ask 2): /clear keeps the agent process and its fabric-mcp, so its SessionEnd releases
        no claim and observes no end. A turn spooled before it still goes out."""
        said, spawned = self.spool("end", reason="clear")
        self.assertEqual(said, "skipped: /clear keeps the Fabric session")
        self.assertEqual(spawned, [])
        self.assertFalse(fs.session_dir(SID, self.env).exists(), "no folder is made for a /clear")
        directory = fs.session_dir(SID, self.env)
        fs.spool(directory, {"event": "turn", "runtimeSessionId": SID, "cwd": str(self.repo),
                             "observedAt": "2026-10-22T00:00:00Z", "facts": {}})
        said, spawned = self.spool("end", reason="clear")
        self.assertEqual(said, "skipped: /clear keeps the Fabric session")
        self.assertEqual(spawned, [directory], "the pending turn still goes out")
        self.assertEqual(list(directory.glob("*-end.json")), [])
        fs.deliver(directory, self.env, deadline_s=8)
        self.assertEqual([c["name"] for c in self.records("call") if c["name"] != "com.status"], ["fabric_session_observe"])
        self.assertTrue(directory.is_dir(), "the folder stays: the session did not end")

    def test_an_end_followed_by_a_turn_of_the_same_session_is_dropped(self):
        """Fabric 0.3.9 (02bf19c5, ask 3) and FAA-83: `claude --resume` keeps the session id, so an end kept after a
        release timeout must not be delivered once the resumed session spools a turn: it would release live claims."""
        directory = fs.session_dir(SID, self.env)
        fs.spool(directory, {"event": "end", "runtimeSessionId": SID, "cwd": str(self.repo), "reason": "other",
                             "observedAt": "2026-10-18T00:00:00Z", "facts": {}})
        said, spawned = self.spool("turn")
        self.assertEqual(said, "spooled: worker started")
        fs.deliver(directory, self.env, deadline_s=8)
        self.assertEqual([c["name"] for c in self.records("call") if c["name"] != "com.status"], ["fabric_session_observe"])
        self.assertEqual(self.records("call")[0]["arguments"]["event"], "turn")
        self.assertIn("event=end outcome=dropped", self.log_text())
        self.assertTrue(directory.is_dir(), "the resumed session goes on")
        self.assertEqual(list(directory.glob("*-end.json")), [])

    def test_a_rejoin_that_finds_no_session_is_recorded_once(self):
        """Fabric 0.3.9 (02bf19c5, ask 4): fabric-mcp --rejoin-only exits 3 when no session holds the id. The spool is
        dropped, the folder is marked, and for NO_SESSION_HOLD_S the hooks spool nothing for that id."""
        self.env["FAKE_MCP_MODE"] = "no-session"
        _, spawned = self.spool("turn")
        started = time.perf_counter()
        fs.deliver(spawned[0], self.env, deadline_s=8)
        self.assertLess(time.perf_counter() - started, 4.0, "exit 3 is not held to the deadline")
        self.assertEqual(self.records("call"), [])
        self.assertEqual(self.records("exit"), [3])
        self.assertEqual(list(spawned[0].glob("*-*.json")), [])
        self.assertTrue((spawned[0] / fs.NO_SESSION_MARK).exists())
        self.assertEqual(self.log_text().count("outcome=no-session"), 1)
        said, again = self.spool("turn")
        self.assertEqual(said, "skipped: Fabric holds no session for it")
        self.assertEqual(again, [])
        self.assertEqual(list(spawned[0].glob("*-*.json")), [])
        old = time.time() - fs.NO_SESSION_HOLD_S - 5
        os.utime(str(spawned[0] / fs.NO_SESSION_MARK), (old, old))
        said, again = self.spool("turn")
        self.assertEqual(said, "spooled: worker started", "the mark expires: a Fabric that re-enrolled is found again")
        said, _ = self.spool("end", reason="prompt_input_exit")
        self.assertEqual(said, "spooled: worker started")

    def test_clear_starts_a_worker_even_while_one_runs(self):
        """A running worker may have read the spool before the last turn landed, and no later hook comes for the old
        id after /clear: a new worker is started anyway; it waits for the lock (blind reading of 0.42.0, finding 1)."""
        directory = fs.session_dir(SID, self.env)
        fs.spool(directory, {"event": "turn", "runtimeSessionId": SID, "cwd": str(self.repo),
                             "observedAt": "2026-10-22T00:00:00Z", "facts": {}})
        (directory / "worker.lock").write_text("")
        said, spawned = self.spool("end", reason="clear")
        self.assertEqual(said, "skipped: /clear keeps the Fabric session")
        self.assertEqual(spawned, [directory])

    def test_no_session_with_an_end_in_the_spool_removes_the_folder(self):
        """The end was the session's last hook, so nothing would remove its folder before the 7-day prune."""
        self.env["FAKE_MCP_MODE"] = "no-session"
        _, spawned = self.spool("end", reason="prompt_input_exit")
        fs.deliver(spawned[0], self.env, deadline_s=8)
        self.assertEqual(self.records("call"), [])
        self.assertFalse(spawned[0].exists())

    def test_watch_mail_names_a_session_fabric_does_not_hold(self):
        self.env["FAKE_MCP_MODE"] = "no-session"
        self.assertEqual(fs.poll_unread(SID, self.repo, self.env, deadline_s=8),
                         ("down", "Fabric holds no session for this id"))

    def test_a_server_that_closes_stdin_and_exits_3_later_is_no_session(self):
        """FAA-97: a broken pipe waited only 1 s for the exit status, so a server still alive then was logged as
        `outcome=unknown` and its spool kept. The wait now runs to the deadline."""
        script = self.base / "late-exit.py"
        script.write_text("import os, sys, time\nos.close(0)\ntime.sleep(2.0)\nsys.exit(3)\n")
        client = fs.McpStdio([sys.executable, str(script)], str(self.base), self.env, time.monotonic() + 8)
        time.sleep(0.5)
        try:
            with self.assertRaises(fs.NoSessionError):
                client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
        finally:
            client.close()

    def test_an_end_while_no_session_is_held_removes_the_folder(self):
        directory = fs.session_dir(SID, self.env)
        directory.mkdir(parents=True)
        (directory / fs.NO_SESSION_MARK).write_text("")
        said, spawned = self.spool("end", reason="prompt_input_exit")
        self.assertEqual(said, "skipped: Fabric holds no session for it")
        self.assertFalse(directory.exists())

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

    def test_a_turn_soon_after_a_rejoin_waits_for_the_next_worker(self):
        # FAA-53: every rejoin costs the machine's shared Fabric budget; a session rejoins at most once a minute.
        _, spawned = self.spool("turn")
        fs.deliver(spawned[0], self.env, deadline_s=8)
        self.assertTrue((spawned[0] / "rejoined").is_file())
        said, again = self.spool("turn")
        self.assertEqual((said, again), ("spooled: rejoined recently", []))
        self.assertEqual(len(list(spawned[0].glob("*-turn.json"))), 1, "the turn waits in the spool")
        said, ended = self.spool("end")
        self.assertEqual(said, "spooled: worker started", "the end always starts a worker")
        fs.deliver(ended[0], self.env, deadline_s=8)
        names = [c["name"] for c in self.records("call")]
        self.assertEqual(names, ["fabric_session_observe", "com.status", "fabric_session_observe",
                                 "fabric_work_release", "fabric_session_observe"])
        self.assertEqual(len(self.records("argv")), 2, "two rejoins for three hook events")

    def test_a_turn_after_the_interval_rejoins(self):
        _, spawned = self.spool("turn")
        fs.deliver(spawned[0], self.env, deadline_s=8)
        old = time.time() - fs.REJOIN_MIN_INTERVAL_S - 1
        os.utime(spawned[0] / "rejoined", (old, old))
        said, again = self.spool("turn")
        self.assertEqual((said, len(again)), ("spooled: worker started", 1))

    def test_a_rejoin_that_failed_marks_nothing(self):
        self.env["FAKE_MCP_MODE"] = "never"
        _, spawned = self.spool("turn")
        fs.deliver(spawned[0], self.env, deadline_s=1.0)
        self.assertFalse((spawned[0] / "rejoined").exists())
        said, again = self.spool("turn")
        self.assertEqual((said, len(again)), ("spooled: worker started", 1), "a failed rejoin is retried next turn")

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

    def test_stale_session_folders_are_pruned_when_a_hook_spools(self):
        """FAA-50: a folder whose worker failed, or whose session ended without SessionEnd, is never retried; the next
        spooling hook removes folders older than SESSION_STALE_S, never its own, never one whose worker is running."""
        root = fs.state_root(env=self.env) / "sessions"
        old = time.time() - fs.SESSION_STALE_S - 60

        def folder(name, locked=False, age=old):
            path = root / name
            path.mkdir(parents=True, exist_ok=True)
            (path / "01791848106008551000-end.json").write_text("{}")
            if locked:
                (path / "worker.lock").write_text("1")
            for item in list(path.iterdir()) + [path]:
                os.utime(item, (age, age) if not (locked and item.name == "worker.lock") else None)
            return path

        stale = folder("11111111-1111-4111-8111-111111111111")
        running = folder("22222222-2222-4222-8222-222222222222", locked=True)
        fresh = folder("33333333-3333-4333-8333-333333333333", age=time.time())
        own = folder(SID)
        self.spool("turn")
        self.assertFalse(stale.exists(), "a stale folder is removed")
        self.assertTrue(running.exists(), "a folder whose worker holds the lock stays")
        self.assertTrue(fresh.exists(), "a recent folder stays")
        self.assertTrue((own / "01791848106008551000-end.json").exists(), "the spooling session's own folder stays")
        self.assertEqual(fs.prune_stale_sessions(self.env), 0, "nothing else is stale")

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
        self.fake = fake
        self.register(command=str(self.fabric_mcp(fake)))
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
        # A turn within REJOIN_MIN_INTERVAL_S of a rejoin starts no worker (FAA-53); deliver it by hand.
        fs.hook_spool({"session_id": SID, "cwd": str(self.repo)}, "turn", self.env, spawn=lambda directory: None)
        directory = fs.session_dir(SID, self.env)
        fs.deliver(directory, self.env, deadline_s=8)
        return directory

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
        if sys.platform != "win32":  # POSIX permission bits; Windows keeps only read-only
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
        self.assertEqual(self.prompt(), "2 unread on the project board: com.list")
        self.assertIsNone(self.prompt(), "the same count is not repeated")
        self.unread(1)
        self.turn()
        self.assertIsNone(self.prompt(), "a fall is not news")
        self.unread(4)
        self.turn()
        self.assertEqual(self.prompt(), "4 unread on the project board: com.list")
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


class TurnNudges(Active):
    """FAA-142 (Fabric ask dfb43ffb): a turn's answer may carry `nudges`; the worker keeps them in the session's spool
    and the prompt hook prints each `says` once, on the next prompt."""

    def setUp(self):
        super().setUp()
        self.nudges = self.base / "nudges.json"
        self.env["FAKE_MCP_NUDGES"] = str(self.nudges)

    def answer(self, value):
        self.nudges.write_text(value if isinstance(value, str) else json.dumps(value))

    def test_a_turn_s_nudges_reach_the_next_prompt_once(self):
        self.answer({"recorded": True, "nudges": [
            {"kind": "claim", "says": "Your claim on the task lapsed: claim it again or let it go.", "task_id": "t1"},
            {"kind": "board", "says": "An answer waits for you on the board.", "request_id": "r1"}]})
        directory = self.turn()
        if sys.platform != "win32":
            self.assertEqual(stat.S_IMODE((directory / fs.NUDGES_FILE).stat().st_mode), 0o600)
        self.assertEqual(self.prompt(), "Fabric reminder: Your claim on the task lapsed: claim it again or let it go.\n"
                                        "Fabric reminder: An answer waits for you on the board.")
        self.assertIsNone(self.prompt(), "each is given once")
        self.assertIn("nudges=2 dropped=0", self.log_text())
        self.assertNotIn("lapsed", self.log_text(), "the log names a count, never the text")

    def test_nudges_sit_beside_the_unread_line(self):
        self.unread(2)
        self.answer({"nudges": [{"kind": "board", "says": "Mark what you handled read."}]})
        self.turn()
        self.assertEqual(self.prompt(), "2 unread on the project board: com.list\nFabric reminder: Mark what you handled read.")

    def test_two_turns_before_a_prompt_keep_both_without_repeats(self):
        first = {"kind": "claim", "says": "One.", "task_id": "t1"}
        self.answer({"nudges": [first]})
        self.turn()
        self.answer({"nudges": [first, {"kind": "claim", "says": "Two."}]})
        self.turn()
        self.assertEqual(self.prompt(), "Fabric reminder: One.\nFabric reminder: Two.")

    def test_fabric_s_own_sentence_is_printed_as_given(self):
        # The shape Fabric 0.3.14 answers (board e94ec9c0, release/0.3.14 b63dedb6): {recorded, seq, nudges?}, and
        # every `says` starts with "Fabric:", so it gets no second tag.
        self.answer({"recorded": True, "seq": 7, "nudges": [
            {"kind": "claim-lapsed", "says": "Fabric: your claim on task 12 lapsed; claim it again or let it go.",
             "task_id": "t12"}]})
        self.turn()
        self.assertEqual(self.prompt(), "Fabric: your claim on task 12 lapsed; claim it again or let it go.")

    def test_a_full_pending_list_logs_what_it_dropped(self):
        self.answer({"nudges": [{"kind": "k", "says": "n%d" % i} for i in range(fs.MAX_NUDGES)]})
        self.turn()
        self.answer({"nudges": [{"kind": "k", "says": "late%d" % i} for i in range(3)]})
        self.turn()
        self.assertIn("nudges=3 dropped=3", self.log_text())

    def test_one_answer_over_the_cap_logs_its_drop(self):
        self.answer({"nudges": [{"kind": "k", "says": "n%d" % i} for i in range(fs.MAX_NUDGES + 2)]})
        self.turn()
        self.assertIn("nudges=%d dropped=2" % (fs.MAX_NUDGES + 2), self.log_text())

    def test_a_failed_write_puts_the_pending_ones_back(self):
        directory = fs.session_dir(SID, self.env)
        directory.mkdir(parents=True)
        fs._write_private(directory / fs.NUDGES_FILE, json.dumps(["A"]))
        mcp = sys.modules["fabric_session_mcp"]
        real, calls = mcp._write_private, []

        def flaky(path, text):
            calls.append(text)
            if len(calls) == 1:
                raise PermissionError("denied")
            real(path, text)
        mcp._write_private = flaky
        said = []
        try:
            mcp._keep_nudges(directory, [{"says": "B"}], said.append, SID)
        finally:
            mcp._write_private = real
        self.assertEqual(fs.take_nudges(directory), ["A"], "the pending one is back; only this turn's B is lost")
        self.assertIn("outcome=lost lost=1", said[0])

    def test_lost_counts_this_turn_s_capped_lines_and_both_failed_writes(self):
        """FAA-143: with five pending and the write failing, the turn's lines past the cap are lost too; when the
        write-back fails as well, the pending ones are counted lost with them, and nothing is left behind."""
        mcp = sys.modules["fabric_session_mcp"]
        real = mcp._write_private
        for fail_both, pending, expected in ((False, ["P%d" % i for i in range(fs.MAX_NUDGES)], 3),
                                             (True, ["P1", "P2"], 5)):
            with self.subTest(fail_both=fail_both):
                directory = fs.session_dir(SID, self.env)
                directory.mkdir(parents=True, exist_ok=True)
                real(directory / fs.NUDGES_FILE, json.dumps(pending))
                calls = []

                def flaky(path, text):
                    calls.append(text)
                    if len(calls) == 1 or fail_both:
                        raise PermissionError("denied")
                    real(path, text)
                mcp._write_private = flaky
                said = []
                try:
                    mcp._keep_nudges(directory, [{"says": "T1"}, {"says": "T2"}, {"says": "T3"}], said.append, SID)
                finally:
                    mcp._write_private = real
                self.assertIn("outcome=lost lost=%d" % expected, said[0])
                self.assertEqual(fs.take_nudges(directory), [] if fail_both else pending)

    def test_lost_counts_past_the_item_cap(self):
        """0.56.0 unit r1: a full answer (MAX_NUDGE_ITEMS lines) and pending lines lost together are all counted."""
        mcp = sys.modules["fabric_session_mcp"]
        real = mcp._write_private
        directory = fs.session_dir(SID, self.env)
        directory.mkdir(parents=True, exist_ok=True)
        real(directory / fs.NUDGES_FILE, json.dumps(["P1", "P2"]))

        def broken(path, text):
            raise PermissionError("denied")
        mcp._write_private = broken
        said = []
        try:
            mcp._keep_nudges(directory, [{"says": "line %d" % i} for i in range(fs.MAX_NUDGE_ITEMS)], said.append, SID)
        finally:
            mcp._write_private = real
        self.assertIn("outcome=lost lost=%d" % (fs.MAX_NUDGE_ITEMS + 2), said[0])

    def test_a_long_list_is_read_in_linear_time_up_to_its_cap(self):
        """FAA-143: only the first MAX_NUDGE_ITEMS items are read, and repeats are found by a set."""
        many = [{"says": "line %d" % i} for i in range(fs.MAX_NUDGE_ITEMS + 500)]
        lines = fs.nudge_lines(many, limit=None)
        self.assertEqual(len(lines), fs.MAX_NUDGE_ITEMS)
        self.assertEqual(lines[-1], "line %d" % (fs.MAX_NUDGE_ITEMS - 1))
        self.assertEqual(fs.nudge_lines([{"says": "a"}, {"says": "b"}, {"says": "a"}], limit=None), ["a", "b"])

    def test_an_empty_absent_or_odd_list_prints_nothing(self):
        for value in ({"nudges": []}, {"recorded": True}, {"nudges": "go"}, {"nudges": [1, None, "x", {"kind": "a"},
                      {"kind": "a", "says": 7}, {"kind": "a", "says": "   "}]}, "not json", [1, 2]):
            self.answer(value)
            directory = self.turn()
            self.assertFalse((directory / fs.NUDGES_FILE).exists(), value)
            self.assertIsNone(self.prompt(), value)

    def test_nudges_are_bounded_and_one_line_each(self):
        many = [{"kind": "k", "says": "n%d" % i} for i in range(fs.MAX_NUDGES + 4)]
        many[0] = {"kind": "k", "says": "first\nsecond\x07" + "x" * (fs.MAX_NUDGE_CHARS + 50)}
        self.answer({"nudges": many})
        self.turn()
        lines = self.prompt().split("\n")
        self.assertEqual(len(lines), fs.MAX_NUDGES)
        self.assertTrue(lines[0].startswith(fs.NUDGE_PREFIX + "first second"))
        self.assertLessEqual(len(lines[0]), len(fs.NUDGE_PREFIX) + fs.MAX_NUDGE_CHARS)
        self.assertNotIn("\x07", lines[0])

    def test_the_end_of_a_session_keeps_no_nudges(self):
        self.answer({"nudges": [{"kind": "claim", "says": "Late."}]})
        spawned = []
        fs.hook_spool({"session_id": SID, "cwd": str(self.repo)}, "end", self.env, spawn=spawned.append)
        fs.deliver(spawned[0], self.env, deadline_s=8)
        self.assertFalse(spawned[0].exists(), "the session's folder goes at its end")

    def test_clear_carries_no_nudges_and_makes_no_folder(self):
        # Decision (0.51.2): nudges are not carried across /clear. Carrying them made the new id's folder before the
        # launched-session walk (FAA-68) and keyed on a cwd Claude Code resets at /clear (seam round 2). The new
        # session's preamble sends the agent to fabric_work_list, which shows the same reminders.
        new = "9f1c2d3e-4b5a-4c6d-8e7f-0a1b2c3d4e5f"
        self.answer({"nudges": [{"kind": "claim", "says": "Late."}]})
        self.turn()
        fs.hook_spool({"session_id": SID, "cwd": str(self.repo), "reason": "clear"}, "end", self.env,
                      spawn=lambda directory: None)
        fs.hook_session_start({"session_id": new, "cwd": str(self.repo), "source": "clear"}, self.env)
        self.assertFalse(fs.session_dir(new, self.env).exists(), "SessionStart makes no session folder")
        self.assertIsNone(fs.hook_user_prompt_submit({"session_id": new, "cwd": str(self.repo)}, self.env))

    def test_a_merge_during_a_take_is_never_lost(self):
        # The worker may merge between the prompt hook's take and its read (seam finding): a repeat at worst.
        directory = fs.session_dir(SID, self.env)
        directory.mkdir(parents=True)
        fs._write_private(directory / fs.NUDGES_FILE, json.dumps(["A"]))
        real = fs.read_small
        sys.modules["fabric_session_env"].read_small = lambda path, *a: (
            sys.modules["fabric_session_mcp"]._keep_nudges(directory, [{"says": "B"}], lambda line: None, SID) if path.name.startswith(".nudges.json.taken") else None,
            real(path, *a))[1]
        try:
            first = fs.take_nudges(directory)
        finally:
            sys.modules["fabric_session_env"].read_small = real
        self.assertEqual(first, ["A"])
        self.assertEqual(fs.take_nudges(directory), ["B"], "the merge made meanwhile waits for the next take")

    def test_the_prompt_hook_survives_a_broken_nudges_file(self):
        directory = fs.session_dir(SID, self.env)
        directory.mkdir(parents=True)
        for text in ("{broken", json.dumps({"nudges": [1]}), json.dumps("x"), json.dumps([{"says": 5}])):
            (directory / fs.NUDGES_FILE).write_text(text)
            self.assertIsNone(self.prompt(), text)


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

    def test_watch_mail_prints_the_nudges_of_a_turn_its_look_delivered_once(self):
        nudges = self.base / "nudges.json"
        nudges.write_text(json.dumps({"nudges": [{"kind": "claim", "says": "Your claim lapsed."}]}))
        self.env["FAKE_MCP_NUDGES"] = str(nudges)
        fs.hook_spool({"session_id": SID, "cwd": str(self.repo)}, "turn", self.env, spawn=lambda directory: None)
        code, printed, _ = self.watch(1)
        self.assertEqual(code, 0)
        self.assertEqual(printed.count("Fabric reminder: Your claim lapsed."), 1)
        self.assertIsNone(fs.hook_user_prompt_submit({"session_id": SID}, self.env), "the prompt hook does not repeat it")

    def test_watch_mail_prints_a_fabric_line_as_fabric_wrote_it(self):
        """FAA-143: a reminder that starts `Fabric:` is printed untagged by watch-mail, as by the prompt hook."""
        nudges = self.base / "nudges.json"
        nudges.write_text(json.dumps({"nudges": [{"kind": "claim", "says": "Fabric: your claim lapsed."}]}))
        self.env["FAKE_MCP_NUDGES"] = str(nudges)
        fs.hook_spool({"session_id": SID, "cwd": str(self.repo)}, "turn", self.env, spawn=lambda directory: None)
        code, printed, _ = self.watch(1)
        self.assertEqual(code, 0)
        self.assertEqual(printed.count("Fabric: your claim lapsed."), 1)
        self.assertFalse(any(fs.NUDGE_PREFIX in line for line in printed))

    def test_watch_mail_leaves_the_stop_worker_s_nudges_to_the_prompt(self):
        nudges = self.base / "nudges.json"
        nudges.write_text(json.dumps({"nudges": [{"kind": "claim", "says": "Your claim lapsed."}]}))
        self.env["FAKE_MCP_NUDGES"] = str(nudges)
        fs.hook_spool({"session_id": SID, "cwd": str(self.repo)}, "turn", self.env, spawn=lambda directory: None)
        fs.deliver(fs.session_dir(SID, self.env), self.env, deadline_s=8)  # the Stop worker
        code, printed, _ = self.watch(1, poll=lambda: ("wait", 30.0))
        self.assertFalse([line for line in printed if "Your claim lapsed." in line])
        self.assertEqual(json.loads(fs.hook_user_prompt_submit({"session_id": SID}, self.env))
                         ["hookSpecificOutput"]["additionalContext"], "Fabric reminder: Your claim lapsed.")

    def test_prints_when_the_unread_count_rises(self):
        counts = iter([0, 2, 2, 1, 3])
        code, printed, sleeps = self.watch(5, poll=lambda: ("ok", next(counts)))
        self.assertEqual(code, 0)
        self.assertEqual(printed, ["2 unread on the project board: com.list", "3 unread on the project board: com.list"])
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
        self.assertEqual(printed[-1], "1 unread on the project board: com.list")

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

    def test_a_look_delivers_the_spooled_turns_in_the_same_rejoin(self):
        # FAA-89: while watch-mail runs, its looks keep the session's rejoin mark fresh, so a Stop-hook turn waits in the
        # spool. The look delivers it: one fabric-mcp, the turn observed, the board's count read, the spool empty.
        fs.hook_spool({"session_id": SID, "cwd": str(self.repo)}, "turn", self.env, spawn=lambda directory: None)
        directory = fs.session_dir(SID, self.env)
        self.assertEqual(len(list(directory.glob("*-turn.json"))), 1)
        self.unread(4)
        self.assertEqual(fs.poll_unread(SID, self.repo, self.env, deadline_s=8), ("ok", 4))
        self.assertEqual(len(self.records("argv")), 1, "one rejoin for the look and the spool")
        self.assertEqual([c["name"] for c in self.records("call")], ["fabric_session_observe", "com.status"])
        self.assertEqual(list(directory.glob("*-*.json")), [])
        kind, left = fs.poll_unread(SID, self.repo, self.env, deadline_s=8)
        self.assertEqual(kind, "wait")
        self.assertGreater(left, 0)
        self.assertEqual(len(self.records("argv")), 1, "the next look within the minute starts no fabric-mcp")

    def test_the_count_after_delivering_is_read_strictly(self):
        # The unit reading of 0.49.0: a negative count is no count; a fresh board.json that does not parse means the
        # board was answered but cannot be read; a session whose end the look delivered is gone, not down.
        mail = sys.modules["fabric_session_mail"]
        directory = fs.session_dir(SID, self.env)
        cases = [('{"unread": -1}', "unavailable"), ("[3]", "unavailable"), ("{not json", "unavailable"),
                 ('{"unread": 2}', "ok"), (None, "ended")]
        saved = mail.deliver
        try:
            for body, kind in cases:
                directory.mkdir(parents=True, exist_ok=True)

                def deliver(folder, env, deadline_s, body=body, **_):
                    if body is None:
                        shutil.rmtree(folder)
                    else:
                        (folder / "board.json").write_text(body, encoding="utf-8")
                mail.deliver = deliver
                verdict = mail._deliver_and_count(directory, self.env, 8)
                self.assertEqual(verdict[0], "down" if kind == "ended" else kind, body)
                if kind == "ok":
                    self.assertEqual(verdict[1], 2)
                if kind == "ended":
                    self.assertIn("session ended", verdict[1])
        finally:
            mail.deliver = saved

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
        self.assertEqual(line.strip(), "1 unread on the project board: com.list")
        started = time.perf_counter()
        proc.stdin.close()
        self.assertEqual(proc.wait(timeout=10), 0)
        self.assertLess(time.perf_counter() - started, 8.0)
        proc.stdout.close()

    @unittest.skipIf(sys.platform == "win32", "Windows ends a process without a catchable SIGTERM (TerminateProcess)")
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


MCP = sys.modules["fabric_session_mcp"]


def prompt_entry(text="do the thing"):
    return {"type": "user", "message": {"role": "user", "content": text}}


def tool_entry(name, **arguments):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_x", "name": name, "input": arguments}]}}


def result_entry():
    return {"type": "user", "toolUseResult": {}, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_x", "content": "RESULT-TEXT-SENTINEL"}]}}


class OriginNames(unittest.TestCase):
    """FAA-140 (D1): a repository is named {host, owner, name} from its origin, credentials and `.git` stripped."""

    def test_the_forms_git_writes(self):
        cases = {
            "https://github.com/acme/one.git": ("github.com", "acme", "one"),
            "https://user:TOKEN-SENTINEL@github.com/acme/one": ("github.com", "acme", "one"),
            "https://x-access-token:p@ss@github.com/acme/one.git/": ("github.com", "acme", "one"),
            "http://GitHub.com:8080/Acme/One.git": ("github.com", "Acme", "One"),
            "git@github.com:acme/two.git": ("github.com", "acme", "two"),
            "bitbucket.org:team/three": ("bitbucket.org", "team", "three"),
            "ssh://git@bitbucket.org:7999/team/four.git": ("bitbucket.org", "team", "four"),
            "git+ssh://git@gitlab.com/group/sub/five.git": ("gitlab.com", "group/sub", "five"),
            " https://github.com/acme/six.git\n": ("github.com", "acme", "six"),
        }
        for url, (host, owner, name) in cases.items():
            with self.subTest(url=url):
                self.assertEqual(MCP.parse_origin(url), {"host": host, "owner": owner, "name": name})

    def test_what_names_no_remote_repository_is_dropped(self):
        for url in ("", "/srv/git/one.git", "file:///srv/git/one.git", "C:/repos/one", "C:\\repos\\one",
                    "https://github.com/one", "https://github.com/", "github.com", "https://host_bad/a/b",
                    "https://github.com/acme/../x", "https://github.com/acme/.git", "https://u:p/x@github.com/a/b",
                    "https://github.com/acme/on e", "ftp://github.com/acme/one", "x" * 3000):
            with self.subTest(url=url[:40]):
                self.assertIsNone(MCP.parse_origin(url))


class BashPaths(unittest.TestCase):
    def test_cd_to_an_absolute_path_and_git_dash_c(self):
        cwd = Path("/work/start")
        got = MCP.bash_paths("cd /a/b && git -C ../c -c core.x=y status; (cd /d) | git --no-pager -C /e log -C "
                             "&& cd relative && cd ~ && cd && /usr/bin/git -C '/f g' diff && echo git -C /not-git",
                             cwd, windows=False)
        self.assertEqual(got, ["/a/b", "/a/c", "/d", "/e", "/f g"])

    def test_a_relative_dash_c_follows_the_last_absolute_cd(self):
        """FAA-166: `-C ../x` after `cd /work/other` is /work/x, not a folder beside the start folder."""
        self.assertEqual(MCP.bash_paths("cd /work/other && git -C ../sibling status", Path("/home/me/proj"),
                                        windows=False), ["/work/other", "/work/sibling"])
        self.assertEqual(MCP.bash_paths("git -C ../sibling status", Path("/home/me/proj"), windows=False),
                         ["/home/me/sibling"])

    def test_a_relative_dash_c_after_an_unknown_cd_names_nothing(self):
        """FAA-166: after `cd relative`, `cd ~`, `cd -` or a bare `cd` the shell's folder is not known here."""
        for cd in ("cd rel", "cd ~", "cd -", "cd", "cd $HOME"):
            with self.subTest(cd=cd):
                self.assertEqual(MCP.bash_paths(cd + " && git -C ../x status; git -C y log", Path("/w"),
                                                windows=False), [])
        self.assertEqual(MCP.bash_paths("cd rel && cd /a && git -C b log", Path("/w"), windows=False), ["/a", "/a/b"])

    def test_windows_reads_git_bash_and_native_paths(self):
        """FAA-175: Git Bash writes /c/..., /cygdrive/c/..., C:/... and C:\\...; the Stop hook reads them as drive
        paths. Another /... (Git's own root) is not this host's and is left out."""
        got = MCP.bash_paths(r'cd /c/Users/me/one && git -C ../two status; cd "C:\work\three"; git -C D:/four log; '
                             r"cd 'C:\five'; cd C:\unquoted; cd /tmp; git -C x log; cd /cygdrive/e/six",
                             Path(r"C:\Users\me\proj"), windows=True)
        self.assertEqual(got, [r"C:\Users\me\one", r"C:\Users\me\two", r"C:\work\three", r"D:\four", r"C:\five",
                               r"E:\six"])
        self.assertEqual(MCP.bash_paths("git -C ../two log", Path(r"C:\Users\me\proj"), windows=True),
                         [r"C:\Users\me\two"])
        self.assertEqual(MCP.bash_paths("git.exe -C /d/x log", Path(r"C:\w"), windows=True), [r"D:\x"])
        self.assertEqual(MCP.bash_paths("GIT.EXE -C /d/x log", Path(r"C:\w"), windows=True), [r"D:\x"],
                         "Windows names are case-blind (0.56.0 unit r1)")
        # Git Bash reads an unquoted backslash as an escape: `cd C:\work` goes to `C:work`, which is not named.
        self.assertEqual(MCP.bash_paths(r"cd C:\work", Path(r"C:\w"), windows=True), [])
        self.assertEqual(MCP.bash_paths(r"git -C C:\work st", r"D:\proj", windows=True), [],
                         "a drive-relative C:work is not known here (0.56.0 unit r4)")

    def test_a_subshell_or_pipe_cd_does_not_move_the_base(self):
        """0.56.0 unit r1, r2: a cd in `( )`, in a pipeline's stage or in a list sent to the background moves only a
        subshell, so a later relative -C is read against the folder before it; a pipe or `( )` with no cd changes
        nothing, `||` keeps the folder as `&&` does, and a newline ends a command."""
        cases = {
            "(cd /a) && git -C b log": ["/a", "/w/b"],
            "cd /a | git -C b log": ["/a", "/w/b"],
            "cd /a & git -C b log": ["/a", "/w/b"],
            "(cd /a && git -C b log)": ["/a", "/a/b"],
            "cd /a && (cd /b) && git -C c log": ["/a", "/b", "/a/c"],
            "ls | wc -l && git -C ../other commit": ["/other"],
            "git -C ../one log | head; git -C ../two commit": ["/one", "/two"],
            "(make) && git -C x commit": ["/w/x"],
            "cd /a || exit 1; git -C sub commit": ["/a", "/a/sub"],
            "cd /a\ngit -C sub log": ["/a", "/a/sub"],
            "cd /a >/dev/null 2>&1; git -C sub log": ["/a", "/a/sub"],
            # 0.56.0 product r3: a `#` comment ends at its line, and a `\` continuation joins two lines.
            "git status  # note\ngit -C /x log": ["/x"],
            "cd /a # go\ngit -C sub log": ["/a", "/a/sub"],
            "ls # don't\ncd /y": ["/y"],
            "git \\\n  -C /x log": ["/x"],
            "cd /a # x\ncd /b\ngit -C sub status": ["/a", "/b", "/b/sub"],
            # 0.56.0 unit r3: `&>` redirects, a here-document's body is text, reserved words and pushd are read.
            "cd /a && make &>/dev/null && git -C sub status": ["/a", "/a/sub"],
            "cd /a &>> log; git -C sub log": ["/a", "/a/sub"],
            "cd /a >|/dev/null && git -C sub status": ["/a", "/a/sub"],
            "cat > deploy.sh <<'EOF'\ncd /srv/app\ngit -C sub pull\nEOF": [],
            "cat <<X\ncd /a\nX\ngit -C sub status": ["/w/sub"],
            "cat <<-EOF\n\tcd /q\n\tEOF\ncd /r": ["/r"],
            "cat <<<\"cd /z\"; git -C s log": ["/w/s"],
            "{ cd /a; }; git -C sub status": ["/a", "/a/sub"],
            "if true; then cd /a; fi; git -C sub status": ["/a", "/a/sub"],
            "X=1 cd /a; git -C s log": ["/a", "/a/s"],
            "cd /a && pushd /b && git -C sub status": ["/a", "/b", "/b/sub"],
            "cd /a && popd && git -C sub status": ["/a"],
            # 0.56.0 unit r4: a here-string has no body; a comment never hides a here-document's line ends; git reads a
            # relative -C against the -C before it and runs in the last
            'jq . <<< "$x"\ncd /b && git -C r status': ["/b", "/b/r"],
            "cat > s.sh <<'EOF'  # c\ncd /srv/other\nEOF\ncd /b": ["/b"],
            "cat > f <<'EOF'\nx\n# c\nEOF\ncd /b": ["/b"],
            "cat > f <<'EOF'\nx # c\nEOF\ncd /b": ["/b"],
            "git -C /a -C b status": ["/a/b"],
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                self.assertEqual(MCP.bash_paths(command, Path("/w"), windows=False), expected)

    def test_cygwin_and_msys_read_posix_paths(self):
        """FAA-177: a Cygwin or MSYS2 Python names its own /cygdrive/c/... paths; only native Windows translates."""
        for platform in ("cygwin", "msys"):
            with self.subTest(platform=platform), mock.patch.object(MCP.sys, "platform", platform):
                self.assertEqual(MCP.bash_paths("cd /cygdrive/c/work && git -C ../x log", Path("/home/me")),
                                 ["/cygdrive/c/work", "/cygdrive/c/x"])
        with mock.patch.object(MCP.sys, "platform", "win32"):
            self.assertEqual(MCP.bash_paths("cd /c/work", Path("C:\\w")), ["C:\\work"])

    def test_a_command_that_does_not_parse_names_nothing(self):
        for windows in (False, True):
            self.assertEqual(MCP.bash_paths("cd '/a/b", Path("/w"), windows=windows), [])
            self.assertEqual(MCP.bash_paths("", Path("/w"), windows=windows), [])


class TranscriptReadSwitch(unittest.TestCase):
    """FAA-175 and FAA-160: the mark turns the transcript read on on every platform; the person turns it off."""

    def env_with_mark(self, base):
        env = {"XDG_CACHE_HOME": base, "LOCALAPPDATA": base, "HOME": base}
        mark = fs.state_root(env=env) / fs.REPOSITORIES_MARK
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text("")
        return env

    def test_the_mark_reads_on_windows_too(self):
        with tempfile.TemporaryDirectory() as base:
            env = self.env_with_mark(base)
            for platform in ("win32", "linux", "darwin", "cygwin"):
                with self.subTest(platform=platform), mock.patch.object(fs.sys, "platform", platform):
                    self.assertTrue(fs.repositories_wanted(env))

    def test_the_person_turns_it_off(self):
        with tempfile.TemporaryDirectory() as base:
            env = self.env_with_mark(base)
            for value, off in (("1", True), ("yes", True), ("0", False), ("", False)):
                with self.subTest(value=value):
                    self.assertEqual(fs.repositories_wanted(dict(env, **{fs.NO_REPOSITORIES_ENV: value})), not off)
                    self.assertEqual(fs.repositories_off(dict(env, **{fs.NO_REPOSITORIES_ENV: value})), off)
            (fs.state_root(env=env) / fs.NO_REPOSITORIES_MARK).write_text("")
            self.assertTrue(fs.repositories_off(env))
            self.assertFalse(fs.repositories_wanted(env))

    def test_without_the_mark_nothing_is_read(self):
        with tempfile.TemporaryDirectory() as base:
            env = {"XDG_CACHE_HOME": base, "LOCALAPPDATA": base, "HOME": base}
            self.assertFalse(fs.repositories_wanted(env))
            self.assertFalse(fs.repositories_off(env))


class TurnRepositories(Base):
    """FAA-140: the Stop hook names the other repositories the turn changed (REQ-1) and the worker sends them only
    where fabric_session_observe takes `repositories` (REQ-2)."""

    active_repository = StopAndEndActive.active_repository
    records = StopAndEndActive.records

    def setUp(self):
        super().setUp()
        self.active_repository()
        subprocess.run(["git", "-C", str(self.repo), "config", "remote.origin.url", "https://github.com/acme/start.git"],
                       check=True)
        self.transcript = self.base / "transcript.jsonl"
        self.mark = fs.state_root(env=self.env) / fs.REPOSITORIES_MARK
        self.mark.parent.mkdir(parents=True, exist_ok=True)
        self.mark.write_text("")  # as a worker leaves it once Fabric takes repositories

    def git_repo(self, name, origin=None):
        folder = self.base / name
        subprocess.run(["git", "init", "-q", str(folder)], check=True)
        if origin:
            subprocess.run(["git", "-C", str(folder), "config", "remote.origin.url", origin], check=True)
        return folder

    def write_transcript(self, entries, filler=b""):
        with open(self.transcript, "wb") as handle:
            for entry in entries:
                if entry is None:
                    handle.write(filler)
                    continue
                handle.write(json.dumps(entry).encode() + b"\n")

    def spool_turn(self, transcript=None):
        payload = {"session_id": SID, "cwd": str(self.repo), "hook_event_name": "Stop", "stop_hook_active": False}
        if transcript is not False:
            payload["transcript_path"] = str(transcript or self.transcript)
        spawned = []
        said = fs.hook_spool(payload, "turn", self.env, spawn=spawned.append)
        entry = sorted(fs.session_dir(SID, self.env).glob("*-turn.json"))[-1]
        return said, json.loads(entry.read_text())

    def test_the_turn_names_the_other_repositories_it_changed_and_no_path(self):
        one = self.git_repo("one", "https://user:TOKEN-SENTINEL@github.com/acme/one.git")
        two = self.git_repo("two", "git@bitbucket.org:team/two.git")
        three = self.git_repo("three", "ssh://git@github.com/acme/three")
        four = self.git_repo("four", "https://github.com/acme/four.git")
        seven = self.git_repo("seven", "https://github.com/acme/seven.git")
        bare = self.git_repo("no-origin")
        read_only = self.git_repo("read-only", "https://github.com/acme/read-only.git")
        earlier = self.git_repo("earlier", "https://github.com/acme/earlier.git")
        (two / "sub").mkdir()
        self.write_transcript([
            prompt_entry("an earlier turn"), tool_entry("Edit", file_path=str(earlier / "x.txt")), result_entry(),
            prompt_entry("PROMPT-TEXT-SENTINEL"),
            tool_entry("Edit", file_path=str(one / "a.txt"), old_string="OLD-SENTINEL", new_string="b"), result_entry(),
            tool_entry("Write", file_path=str(two / "sub" / "new.txt"), content="CONTENT-SENTINEL"), result_entry(),
            tool_entry("Bash", command="cd '%s' && make" % three), result_entry(),
            tool_entry("Bash", command="git -C ../four status"), result_entry(),
            tool_entry("MultiEdit", file_path=str(one / "c.txt"), edits=[]), result_entry(),
            tool_entry("NotebookEdit", notebook_path=str(seven / "n.ipynb"), new_source="x"), result_entry(),
            tool_entry("Edit", file_path=str(bare / "a.txt")), result_entry(),
            tool_entry("Edit", file_path=str(self.repo / "tracked.txt")), result_entry(),
            tool_entry("Read", file_path=str(read_only / "a.txt")), result_entry(),
            tool_entry("Write", file_path=str(self.base / "outside" / "loose.txt")), result_entry(),
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}},
        ])
        said, entry = self.spool_turn()
        self.assertEqual(said, "spooled: worker started")
        self.assertEqual(entry["repositories"], [
            {"host": "github.com", "owner": "acme", "name": "one"},
            {"host": "bitbucket.org", "owner": "team", "name": "two"},
            {"host": "github.com", "owner": "acme", "name": "three"},
            {"host": "github.com", "owner": "acme", "name": "four"},
            {"host": "github.com", "owner": "acme", "name": "seven"}])
        stored = json.dumps({k: v for k, v in entry.items() if k != "cwd"})
        for leaked in (str(self.base), "TOKEN-SENTINEL", "PROMPT-TEXT-SENTINEL", "CONTENT-SENTINEL", "OLD-SENTINEL",
                       "RESULT-TEXT-SENTINEL", "read-only", "earlier", "start"):
            self.assertNotIn(leaked, stored)
        self.assertNotIn(str(self.base), self.log_text())

    def test_at_most_ten_repositories(self):
        folders = [self.git_repo("r%02d" % i, "https://github.com/acme/r%02d.git" % i) for i in range(12)]
        self.write_transcript([prompt_entry()] + [tool_entry("Bash", command="cd '%s'" % f) for f in folders])
        _, entry = self.spool_turn()
        self.assertEqual([r["name"] for r in entry["repositories"]], ["r%02d" % i for i in range(10)])

    def test_two_checkouts_of_one_repository_are_named_once(self):
        a = self.git_repo("a", "https://github.com/acme/same.git")
        b = self.git_repo("b", "git@github.com:acme/same")
        self.write_transcript([prompt_entry(), tool_entry("Edit", file_path=str(a / "x")),
                               tool_entry("Edit", file_path=str(b / "x"))])
        _, entry = self.spool_turn()
        self.assertEqual(entry["repositories"], [{"host": "github.com", "owner": "acme", "name": "same"}])

    def test_another_checkout_of_the_start_repository_is_not_named(self):
        """A worktree or a second clone of the start folder's repository has another toplevel but the same origin: it
        is the start folder's repository, not another one."""
        clone = self.git_repo("clone", "git@github.com:acme/start.git")
        other = self.git_repo("other", "https://github.com/acme/other.git")
        self.write_transcript([prompt_entry(), tool_entry("Edit", file_path=str(clone / "x")),
                               tool_entry("Edit", file_path=str(other / "x"))])
        _, entry = self.spool_turn()
        self.assertEqual(entry["repositories"], [{"host": "github.com", "owner": "acme", "name": "other"}])

    def test_a_missing_or_unreadable_transcript_names_none_and_is_no_error(self):
        garbage = self.base / "garbage.jsonl"
        garbage.write_bytes(b"\xff\xfe not json\n{\"type\": 3}\n[1, 2]\n")
        for transcript in (False, self.base / "absent.jsonl", self.base, garbage):
            with self.subTest(transcript=str(transcript)):
                _remove = fs.session_dir(SID, self.env)
                shutil.rmtree(_remove, ignore_errors=True)
                said, entry = self.spool_turn(transcript)
                self.assertEqual(said, "spooled: worker started")
                self.assertNotIn("repositories", entry)
                self.assertIsInstance(entry["facts"]["head"], str)

    def test_only_the_tail_of_a_long_transcript_is_read(self):
        early = self.git_repo("early", "https://github.com/acme/early.git")
        late = self.git_repo("late", "https://github.com/acme/late.git")
        filler = b"".join(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "x" * 1000}]}}).encode() + b"\n" for _ in range(600))
        self.write_transcript([tool_entry("Edit", file_path=str(early / "x")), None,
                               tool_entry("Edit", file_path=str(late / "x"))], filler=filler)
        self.assertGreater(self.transcript.stat().st_size, MCP.TRANSCRIPT_TAIL_BYTES + 1000)
        self.assertEqual(MCP.turn_paths(str(self.transcript), self.repo), [str(late / "x")])

    def test_bash_text_is_split_within_a_cap_and_never_after_the_budget(self):
        """Seam reading 1: a long unterminated quote costs shlex its whole length, so a turn's Bash text is capped."""
        one = self.git_repo("one", "https://github.com/acme/one.git")
        noisy = "git log '" + "x" * 64000  # unterminated
        self.write_transcript([prompt_entry()] + [tool_entry("Bash", command=noisy) for _ in range(8)]
                              + [tool_entry("Bash", command="echo no-word-here " + "y" * 64000),
                                 tool_entry("Edit", file_path=str(one / "x"))])
        started = time.monotonic()
        self.assertEqual(MCP.turn_paths(str(self.transcript), self.repo), [str(one / "x")])
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(MCP.turn_paths(str(self.transcript), self.repo, until=time.monotonic()), [])

    def test_a_spent_budget_names_none(self):
        one = self.git_repo("one", "https://github.com/acme/one.git")
        self.write_transcript([prompt_entry(), tool_entry("Edit", file_path=str(one / "x"))])
        self.assertEqual(MCP.turn_repositories(str(self.transcript), self.repo, until=time.monotonic()), [])
        self.assertEqual(len(MCP.turn_repositories(str(self.transcript), self.repo, until=time.monotonic() + 5)), 1)

    def test_a_subagent_entry_and_a_meta_prompt_do_not_end_the_turn(self):
        one = self.git_repo("one", "https://github.com/acme/one.git")
        side = self.git_repo("side", "https://github.com/acme/side.git")
        meta = dict(prompt_entry("caveat"), isMeta=True)
        sidechain = dict(tool_entry("Edit", file_path=str(side / "x")), isSidechain=True)
        self.write_transcript([prompt_entry(), tool_entry("Edit", file_path=str(one / "x")), meta, sidechain])
        self.assertEqual(MCP.turn_paths(str(self.transcript), self.repo), [str(one / "x")])

    def test_the_end_entry_carries_no_repositories(self):
        one = self.git_repo("one", "https://github.com/acme/one.git")
        self.write_transcript([prompt_entry(), tool_entry("Edit", file_path=str(one / "x"))])
        fs.hook_spool({"session_id": SID, "cwd": str(self.repo), "transcript_path": str(self.transcript)}, "end",
                      self.env, spawn=lambda d: None)
        (entry,) = fs.session_dir(SID, self.env).glob("*-end.json")
        self.assertNotIn("repositories", json.loads(entry.read_text()))

    def read_on(self):
        """The worker's tests take turns that carry repositories on every host: the hook's read is turned on as the mark
        turns it on where it is allowed, so these tests also run on Windows, where the gate is off (FAA-175)."""
        return mock.patch.object(sys.modules["fabric_session_cli"], "repositories_wanted", lambda env=None: True)

    def deliver_two_turns(self):
        one = self.git_repo("one", "https://github.com/acme/one.git")
        self.write_transcript([prompt_entry(), tool_entry("Edit", file_path=str(one / "x"))])
        with self.read_on():
            self.spool_turn()
            self.spool_turn()
        fs.deliver(fs.session_dir(SID, self.env), self.env, deadline_s=8)
        return [c["arguments"] for c in self.records("call") if c["name"] == "fabric_session_observe"]

    def test_the_worker_sends_repositories_where_the_schema_lists_them(self):
        self.env["FAKE_MCP_OBSERVE_REPOSITORIES"] = "1"
        turns = self.deliver_two_turns()
        self.assertEqual([t["repositories"] for t in turns], [[{"host": "github.com", "owner": "acme", "name": "one"}]] * 2)
        log = self.log_text()
        self.assertIn("repositories=1", log)
        self.assertNotIn("acme", log)

    def test_without_the_mark_the_hook_reads_no_transcript(self):
        """Product and seam readings 1: until a worker saw Fabric take `repositories`, the Stop hook does not open the
        transcript at all (nothing changes for a Fabric before the 2026-11-21 slice)."""
        self.mark.unlink()
        one = self.git_repo("one", "https://github.com/acme/one.git")
        self.write_transcript([prompt_entry(), tool_entry("Edit", file_path=str(one / "x"))])
        with mock.patch.object(MCP, "_transcript_tail", side_effect=AssertionError("the transcript was read")):
            _, entry = self.spool_turn()
        self.assertNotIn("repositories", entry)

    def test_the_worker_writes_the_mark_from_the_schema_and_removes_it_when_it_goes(self):
        self.mark.unlink()
        self.env["FAKE_MCP_OBSERVE_REPOSITORIES"] = "1"
        self.spool_turn(transcript=False)
        fs.deliver(fs.session_dir(SID, self.env), self.env, deadline_s=8)
        self.assertTrue(self.mark.exists())
        for shape in ("strings", ""):  # another item shape, then none: the hook stops reading transcripts
            self.env["FAKE_MCP_OBSERVE_REPOSITORIES"] = shape
            self.spool_turn(transcript=False)
            fs.deliver(fs.session_dir(SID, self.env), self.env, deadline_s=8)
            self.assertFalse(self.mark.exists(), shape)
            self.mark.write_text("")

    def test_a_mark_another_worker_removed_never_ends_the_delivery(self):
        """Seam reading 2: the mark is shared by every session's worker; losing a race on it is logged, nothing more."""
        self.env["FAKE_MCP_OBSERVE_REPOSITORIES"] = "strings"
        self.spool_turn(transcript=False)
        plain = Path.unlink

        def unlink(path, *args, **kwargs):
            if path.name == fs.REPOSITORIES_MARK:
                raise FileNotFoundError(str(path))  # another worker removed it first
            return plain(path, *args, **kwargs)
        with mock.patch.object(Path, "unlink", unlink):
            fs.deliver(fs.session_dir(SID, self.env), self.env, deadline_s=8)
        self.assertEqual(len([c for c in self.records("call") if c["name"] == "fabric_session_observe"]), 1)
        self.assertEqual(list(fs.session_dir(SID, self.env).glob("*-turn.json")), [])
        self.assertIn("the repositories mark: FileNotFoundError", self.log_text())

    def test_a_field_of_another_shape_is_not_sent(self):
        """Seam reading 3: items of another type, an item that requires more than host, owner and name, or a field
        that is not declared an array: nothing is sent, the turn's facts still are."""
        for shape in ("strings", "required-path", "untyped"):
            with self.subTest(shape=shape):
                self.env["FAKE_MCP_OBSERVE_REPOSITORIES"] = shape
                turns = self.deliver_two_turns()
                self.assertEqual(len(turns), 2)
                for turn in turns:
                    self.assertNotIn("repositories", turn)
                    self.assertIn("filesChanged", turn)
                self.assertEqual(self.log_text().count("does not take repositories"), 1)
                self.tearDown()
                self.setUp()

    def test_an_item_the_schema_refuses_is_left_out_and_the_turn_still_goes(self):
        """Seam reading 4: a nested-group owner against a schema that refuses a slash is left out, never the turn."""
        self.env["FAKE_MCP_OBSERVE_REPOSITORIES"] = "owner-flat"
        flat, nested = self.git_repo("flat", "https://github.com/acme/flat.git"), self.git_repo("nested", "https://gitlab.com/group/sub/nested.git")
        self.write_transcript([prompt_entry(), tool_entry("Edit", file_path=str(flat / "x")), tool_entry("Edit", file_path=str(nested / "y"))])
        with self.read_on():
            self.spool_turn()
        fs.deliver(fs.session_dir(SID, self.env), self.env, deadline_s=8)
        (turn,) = [c["arguments"] for c in self.records("call") if c["name"] == "fabric_session_observe"]
        self.assertEqual(turn["repositories"], [{"host": "github.com", "owner": "acme", "name": "flat"}])
        self.assertIn("filesChanged", turn)

    def test_at_most_the_schemas_max_items_are_sent(self):
        self.env["FAKE_MCP_OBSERVE_REPOSITORIES"] = "max1"
        one, two = self.git_repo("one", "https://github.com/acme/one.git"), self.git_repo("two", "https://github.com/acme/two.git")
        self.write_transcript([prompt_entry(), tool_entry("Edit", file_path=str(one / "x")), tool_entry("Edit", file_path=str(two / "y"))])
        with self.read_on():
            self.spool_turn()
        fs.deliver(fs.session_dir(SID, self.env), self.env, deadline_s=8)
        (turn,) = [c["arguments"] for c in self.records("call") if c["name"] == "fabric_session_observe"]
        self.assertEqual(turn["repositories"], [{"host": "github.com", "owner": "acme", "name": "one"}])

    def test_the_worker_drops_repositories_where_the_schema_does_not_list_them(self):
        turns = self.deliver_two_turns()
        self.assertEqual(len(turns), 2)
        for turn in turns:
            self.assertNotIn("repositories", turn)
        log = self.log_text()
        self.assertEqual(log.count("does not take repositories"), 1, "said once per session")
        self.assertNotIn("acme", log)


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


class NoServicesLine(Base):
    """The machine's descriptor-count line is gone: the host's own instructions carry how to read Fabric services."""

    def services(self, origin="https://example.invalid"):
        directory = self.base / "svc"
        directory.mkdir(exist_ok=True)
        (directory / "a.default.json").write_text(json.dumps({
            "origin": "http://127.0.0.1:4100", "id": "a", "instance": "default", "auth": {"tokenFile": "/x/TOKEN-PATH"},
            "source": {"repository": origin}}))
        (directory / "b.default.json").write_text('{"origin": "http://localhost:4200"}')
        (directory / "notes.txt").write_text("not a descriptor")
        self.env["FABRIC_SERVICES_DIR"] = str(directory)
        return directory

    def test_descriptors_alone_say_nothing_for_any_host(self):
        self.services()
        self.assertFalse(hasattr(fs, "services_line"))
        self.assertFalse(hasattr(fs, "SERVICES_NOTE"))
        for host in ("claude", "codex", "kimi", "hermes"):
            done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)}, args=["--host", host])
            self.assertEqual((done.returncode, done.stdout), (0, ""), host)

    def test_the_preamble_carries_no_service_line(self):
        self.services()
        self.register()
        self.hub()
        (self.repo / "fabric-agent.json").write_text("{}")
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "startup"})
        context = json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(context, fs.PREAMBLE.format(host="Claude Code"))
        self.assertNotIn("TOKEN-PATH", done.stdout)

    def test_default_services_folder_per_os(self):
        self.assertEqual(fs.services_dir("darwin", {"HOME": "/Users/a"}),
                         Path("/Users/a/Library/Application Support/ai.passioncode.fabric/services"))
        self.assertEqual(fs.services_dir("linux", {"HOME": "/h"}), Path("/h/.local/share/passioncode-fabric/services"))
        self.assertEqual(fs.services_dir("win32", {"HOME": "C:/U", "LOCALAPPDATA": "C:/L"}),
                         Path("C:/L") / "passioncode-fabric" / "services")
        self.assertEqual(fs.services_dir("darwin", {"HOME": "/h", "FABRIC_SERVICES_DIR": "/s"}), Path("/s"))



class ProjectUsesFabric(Base):
    """Which projects hear that Fabric is down: those with a Fabric contract file, a project-bound registration, or a
    service descriptor that names their repository. Everything else is silent."""

    def git_repo(self, origin=None):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        if origin:
            subprocess.run(["git", "-C", str(self.repo), "config", "remote.origin.url", origin], check=True)
        sub = self.repo / "pkg" / "deep"
        sub.mkdir(parents=True)
        return sub

    def test_nothing_marks_a_plain_folder(self):
        self.assertIsNone(fs.project_uses_fabric(self.repo, self.env))
        self.assertIsNone(fs.project_uses_fabric(self.base / "missing", self.env))

    def test_each_contract_file_anywhere_from_the_folder_to_the_checkout_root(self):
        sub = self.git_repo()
        for name in fs.FABRIC_MARKERS:
            (self.repo / name).write_text("{}")
            self.assertEqual(fs.project_uses_fabric(sub, self.env), name)
            (self.repo / name).unlink()
        (sub / "fabric-agent.json").write_text("{}")
        self.assertEqual(fs.project_uses_fabric(sub, self.env), "fabric-agent.json")

    def test_a_file_above_the_checkout_or_a_folder_by_that_name_does_not_count(self):
        sub = self.git_repo()
        (self.base / "fabric-agent.json").write_text("{}")  # the parent of the checkout: another project
        (self.repo / "fabric-contract.lock.json").mkdir()
        self.assertIsNone(fs.project_uses_fabric(sub, self.env))

    def test_a_project_bound_registration_counts_and_a_user_one_does_not(self):
        self.register(scope="user")
        self.assertIsNone(fs.project_uses_fabric(self.repo, self.env, fs.claude_registration(self.repo, self.env)))
        self.register(scope="local")
        self.assertEqual(fs.project_uses_fabric(self.repo, self.env, fs.claude_registration(self.repo, self.env)),
                         "registration")
        (self.home / ".claude.json").unlink()
        (self.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"fabric": {"command": "fabric-mcp"}}}))
        self.assertEqual(fs.project_uses_fabric(self.repo, self.env, fs.claude_registration(self.repo, self.env)),
                         "registration")

    def test_a_service_descriptor_naming_this_repository(self):
        sub = self.git_repo("git@github.com:example/example-agent.git")
        directory = self.base / "svc"
        directory.mkdir()
        self.env["FABRIC_SERVICES_DIR"] = str(directory)
        (directory / "other.default.json").write_text(json.dumps({"source": {"repository": "https://github.com/x/y"}}))
        (directory / "broken.default.json").write_text("{not json")
        self.assertIsNone(fs.project_uses_fabric(sub, self.env))
        (directory / "example-agent.default.json").write_text(json.dumps(
            {"id": "example-agent", "source": {"repository": "https://github.com/Example/example-agent"}}))
        self.assertEqual(fs.project_uses_fabric(sub, self.env), "service")

    def test_down_line_for_each_sign_and_for_every_host(self):
        self.register(scope="local")
        self.hub(pid=self.dead_pid())
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo), "source": "startup"})
        self.assertEqual(json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"], fs.DOWN_NOTICE)
        (self.repo / "fabric.package.json").write_text("{}")
        (self.home / ".codex").mkdir()
        (self.home / ".codex" / "config.toml").write_text('[mcp_servers.fabric]\ncommand = "fabric-mcp"\n')
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)}, args=["--host", "codex"])
        self.assertEqual(json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"], fs.DOWN_NOTICE)


class OtherHosts(Base):
    def test_codex_gets_valid_session_start_json_when_registered(self):
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)}, args=["--host", "codex"])
        self.assertEqual((done.returncode, done.stdout), (0, ""), "not registered: silent")
        codex = self.home / ".codex"
        codex.mkdir()
        (codex / "config.toml").write_text('[mcp_servers.fabric]\ncommand = "/opt/Fabric/resources/bin/fabric-mcp"\n')
        self.hub()
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)}, args=["--host", "codex"])
        self.assertIn("this Codex has `fabric` registered; this folder carries no sign", done.stdout, "FAA-60: the pointer")
        (self.repo / "fabric-agent.json").write_text("{}")
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)}, args=["--host", "codex"])
        self.assertIn("this Codex has its MCP server `fabric`", done.stdout)
        for word in ("fabric_whoami", "com.status", "com.list", "com.submit"):
            self.assertIn(word, done.stdout)
        output = json.loads(done.stdout)
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIsInstance(output["hookSpecificOutput"]["additionalContext"], str)

    def test_native_plugins_use_plain_context_and_only_boolean_registration_evidence(self):
        self.hub()
        for host in ("hermes", "opencode", "openclaw", "pi"):
            for registered in (True, False, "true", 1, None):
                with self.subTest(host=host, registered=registered):
                    done, _ = self.run_hook("session-start", {"cwd": str(self.repo), "fabric_registered": registered},
                                            args=["--host", host])
                    self.assertEqual(done.returncode, 0)
                    if registered is True:
                        self.assertIn("fabric_whoami", done.stdout)
                        self.assertNotIn("hookSpecificOutput", done.stdout)
                    else:
                        self.assertEqual(done.stdout, "")

    def test_kimi_reads_its_own_mcp_json(self):
        kimi = self.home / ".kimi-code"
        kimi.mkdir()
        (kimi / "mcp.json").write_text(json.dumps({"mcpServers": {"fabric": {"command": "/x/fabric-mcp", "args": []}}}))
        self.hub(pid=self.dead_pid())
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)}, args=["--host", "kimi"])
        self.assertEqual(done.stdout, "", "a project that does not use Fabric hears nothing")
        (self.repo / "fabric-contract.lock.json").write_text("{}")
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)}, args=["--host", "kimi"])
        self.assertIn("Fabric is not running", done.stdout)
        self.assertIn("lifecycle_ensure_running", done.stdout)

    def test_no_rejoin_for_other_hosts(self):
        source = "\n".join(p.read_text(encoding="utf-8") for p in sorted(SCRIPT.parent.glob("fabric_session*.py")))  # FAA-65
        self.assertIn('RUNNER = "claude-code"', source)
        done, _ = self.run_hook("session-start", {"session_id": SID, "cwd": str(self.repo)}, args=["--host", "other"])
        self.assertEqual((done.returncode, done.stdout), (0, ""))


class InstallHostHooks(Base):
    def setUp(self):
        super().setUp()
        # FAA-69: --script must name an existing file.
        script = self.base / "opt/skills/working-with-fabric/scripts/fabric_session.py"
        script.parent.mkdir(parents=True)
        script.write_text("# the entry point\n")
        self.SCRIPT_PATH = str(script)

    def test_the_default_script_is_the_entry_point(self):
        # FAA-65: the code moved into modules beside fabric_session.py; a hook must still run fabric_session.py.
        script = fs.default_hook_script({"HOME": str(self.base / "no-home")})
        self.assertEqual(script.name, "fabric_session.py")
        self.assertTrue(script.is_file())

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

    def test_codex_removal_names_the_hook_groups_it_moves(self):
        """Codex trusts a hook by event, group and index: removing our group moves the groups after it, and the person
        must re-approve them in /hooks. A removal that moves nothing says nothing about it."""
        other = {"hooks": [{"type": "command", "command": "other", "timeout": 5}]}
        later = {"hooks": [{"type": "command", "command": "later", "timeout": 5}]}
        ours = {"hooks": [{"type": "command", "command": fs.hook_command(self.SCRIPT_PATH, "codex"), "timeout": 5}]}
        path = self.codex_file({"hooks": {"SessionStart": [other, ours, later, later]}})
        code, out, _ = self.install("codex", "--remove")
        self.assertEqual(code, 0, out)
        self.assertIn("2 SessionStart hook group(s) after the removed one moved", out)
        self.assertEqual(json.loads(path.read_text())["hooks"]["SessionStart"], [other, later, later])
        path = self.codex_file({"hooks": {"SessionStart": [other, ours]}})
        code, out, _ = self.install("codex", "--remove")
        self.assertEqual(code, 0, out)
        self.assertNotIn("after the removed one moved", out)

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
        self.assertEqual(ours["command"], fs.hook_command(self.SCRIPT_PATH, "codex"))  # quoted the platform's way
        self.assertLessEqual(ours["timeout"], 5)
        if sys.platform != "win32":  # POSIX permission bits; Windows keeps only read-only
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

    def test_codex_upgrades_one_owned_command_and_preserves_group_policy(self):
        old=fs.hook_command('/old/fabric_session.py', 'codex')
        group={"matcher":"startup|resume", "hooks":[{"type":"command", "command":old,"timeout":4},
                                                         {"type":"command", "command":"other"}]}
        path=self.codex_file({"hooks":{"SessionStart":[group]}})
        code,out,_=self.install('codex','--apply')
        self.assertEqual(code,0,out)
        new=json.loads(path.read_text())['hooks']['SessionStart'][0]
        self.assertEqual(new['matcher'],group['matcher'])
        self.assertEqual(new['hooks'][1],group['hooks'][1])
        self.assertEqual(new['hooks'][0]['command'],fs.hook_command(self.SCRIPT_PATH,'codex'))
        self.assertEqual(new['hooks'][0]['timeout'],4)

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
        self.assertEqual(hooks[-1]["command"], fs.hook_command(self.SCRIPT_PATH, "kimi"))
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
        hosts = sys.modules["fabric_session_hosts"]  # the module that reads it (FAA-65)
        saved = hosts.tomllib
        hosts.tomllib = None
        try:
            code, _, err = self.install("kimi", "--apply")
        finally:
            hosts.tomllib = saved
        self.assertEqual(code, 1)
        self.assertIn("3.11", err)
        self.assertEqual(path.read_text(), 'default_model = "m"\n')

    def test_an_unknown_host_is_refused(self):
        code, _, err = self.install("claude", "--apply")
        self.assertEqual(code, 2)


class Status(Base):
    def setUp(self):
        super().setUp()
        self.env_module = sys.modules["fabric_session_env"]  # find_fabric_bin reads it there (FAA-65)
        self.saved = self.env_module.fabric_bin_candidates
        self.env_module.fabric_bin_candidates = lambda platform=None, env=None: [self.base / "no-fabric" / "fabric-mcp"]

    def tearDown(self):
        self.env_module.fabric_bin_candidates = self.saved
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
        self.assertIn("Repositories of a turn: not read until Fabric takes them", done.stdout)
        done = subprocess.run([sys.executable, str(SCRIPT), "status", "--json", "--cwd", str(self.repo)],
                              capture_output=True, text=True, env=self.env, timeout=10)
        self.assertEqual(json.loads(done.stdout)["hub"]["state"], "running")

    def test_status_names_the_transcript_read_switch(self):
        """FAA-160: status says whether the Stop hook reads the transcript and how to turn it off."""
        self.assertEqual(fs.status(self.repo, self.env)["transcriptRead"], "waiting")
        mark = fs.state_root(env=self.env) / fs.REPOSITORIES_MARK
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text("")
        self.assertEqual(fs.status(self.repo, self.env)["transcriptRead"], "on")
        self.assertEqual(fs.status(self.repo, dict(self.env, **{fs.NO_REPOSITORIES_ENV: "1"}))["transcriptRead"], "off")
        done = subprocess.run([sys.executable, str(SCRIPT), "status", "--cwd", str(self.repo)],
                              capture_output=True, text=True, env=self.env, timeout=10)
        self.assertIn("Repositories of a turn: read from the session's transcript (turn off: "
                      "FABRIC_SESSION_NO_REPOSITORIES=1)", done.stdout)


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

    def test_session_start_runs_at_startup_and_clear_only(self):
        hooks = json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]
        (entry,) = [e for e in hooks["SessionStart"] if "fabric_session.py" in e["hooks"][0]["command"]]
        self.assertEqual(entry.get("matcher"), "startup|clear", "compact and resume keep what the session already has")


if __name__ == "__main__":
    unittest.main()
