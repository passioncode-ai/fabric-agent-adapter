"""The lifecycle layer of the service kit, held to the organization's lifecycle contract.

Every launchd test runs against a FAKE launchctl and plutil placed first on PATH, with a
throwaway label: no test here can load, unload, enable or disable a real job (LC-14).
"""

import http.server
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(module)
    return module


fs = load("fabric_service")

FAKE_LAUNCHCTL = textwrap.dedent('''\
    #!{python}
    """A launchctl stand-in: the state lives in $FAKE_LAUNCHCTL_STATE, never in launchd."""
    import json, os, plistlib, sys
    path = os.environ["FAKE_LAUNCHCTL_STATE"]
    st = json.load(open(path))
    args = sys.argv[1:]
    st["calls"].append(args)
    rc, out = 0, ""

    def label_of(target):
        return target.rsplit("/", 1)[1]  # gui/<uid>/<label> or system/<label>

    verb = args[0] if args else ""
    if verb == "print":
        label = label_of(args[1])
        lag = st["pending_unload"].get(label)
        if lag is not None:
            if lag <= 0:
                st["loaded"].remove(label)
                del st["pending_unload"][label]
            else:
                st["pending_unload"][label] = lag - 1
        if label in st["loaded"]:
            out = "%s = {{\\n\\tpid = 4242\\n}}\\n" % args[1]
        else:
            rc, out = 113, "Could not find service in domain"
    elif verb == "print-disabled":
        if st.get("print_disabled_fails"):
            rc, out = 1, "Unrecognized target"
        else:
            rows = []
            for label, value in st["overrides"].items():
                if st.get("legacy"):
                    value = "true" if value == "disabled" else "false"
                rows.append('\\t"%s" => %s' % (label, value))
            out = "disabled services = {{\\n" + "\\n".join(rows) + "\\n}}\\n\\nlogin item associations = {{\\n}}\\n"
    elif verb in ("enable", "disable"):
        st["overrides"][label_of(args[1])] = verb + "d"
    elif verb == "bootout":
        label = label_of(args[1])
        if label in st["loaded"]:
            if st.get("unload_lag"):
                st["pending_unload"][label] = st["unload_lag"]
            else:
                st["loaded"].remove(label)
        else:
            rc, out = 3, "Boot-out failed: 3: No such process"
    elif verb == "bootstrap":
        label = plistlib.load(open(args[2], "rb"))["Label"]
        if st.get("bootstrap_error"):
            rc, out = 5, st["bootstrap_error"]
        elif st["overrides"].get(label) == "disabled":
            rc, out = 5, "Bootstrap failed: 5: Input/output error"
        elif label in st["loaded"]:
            rc, out = 5, "Bootstrap failed: 5: Input/output error"
        else:
            st["loaded"].append(label)
    else:
        rc, out = 64, "fake launchctl: unknown verb %s" % verb
    json.dump(st, open(path, "w"))
    (sys.stdout if rc == 0 else sys.stderr).write(out)
    sys.exit(rc)
''')


class FakeLaunchd:
    """A temp dir holding fake `launchctl` and `plutil`, first on PATH while the context lasts."""

    def __init__(self, **state):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.state_path = self.dir / "state.json"
        base = {"loaded": [], "overrides": {}, "calls": [], "pending_unload": {}}
        base.update(state)
        self.state_path.write_text(json.dumps(base))
        launchctl = self.dir / "launchctl"
        launchctl.write_text(FAKE_LAUNCHCTL.format(python=sys.executable))
        plutil = self.dir / "plutil"
        plutil.write_text("#!/bin/sh\nexit 0\n")
        for tool in (launchctl, plutil):
            tool.chmod(0o755)
        self._env = mock.patch.dict(os.environ, {"PATH": "%s%s%s" % (self.dir, os.pathsep, os.environ.get("PATH", "")),
                                                  "FAKE_LAUNCHCTL_STATE": str(self.state_path)})

    def __enter__(self):
        self._env.start()
        assert shutil.which("launchctl") == str(self.dir / "launchctl"), "the real launchctl must never be reached"
        return self

    def __exit__(self, *exc):
        self._env.stop()
        self.temp.cleanup()

    @property
    def state(self):
        return json.loads(self.state_path.read_text())

    def verbs(self):
        return [call[0] for call in self.state["calls"]]


class WellKnown:
    """A loopback server answering /.well-known/fabric-service with one identity."""

    def __init__(self, service_id, instance="default"):
        doc = json.dumps({"service": {"id": service_id, "instance": instance}}).encode()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Length", str(len(doc)))
                self.end_headers()
                self.wfile.write(doc)

            def log_message(self, *args):
                return

        self.server = fs.LoopbackHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def throwaway_label():
    return "ai.passioncode.test.lifecycle-%s" % secrets.token_hex(4)


class LaunchdInstallTests(unittest.TestCase):
    """LC-14: install and upgrade never re-enable what the operator disabled."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.label = throwaway_label()
        self.plist = Path(self.temp.name) / (self.label + ".plist")
        self.web = WellKnown("example-agent")

    def tearDown(self):
        self.web.close()
        self.temp.cleanup()

    def install(self, version="1", **kw):
        body = fs.launchd_plist(self.label, ["/bin/echo", version], working_directory=Path(self.temp.name),
                                stdout_path=Path(self.temp.name) / "service.log")
        return fs.launchd_install(self.label, self.plist, body, origin=self.web.origin,
                                  service_id="example-agent", timeout=5, **kw)

    def test_faa267_a_listener_the_job_cannot_prove_names_the_way_round(self):
        sup = sys.modules["fabric_supervisors"]
        body = fs.launchd_plist(self.label, ["/bin/echo", "1"], working_directory=Path(self.temp.name),
                                stdout_path=Path(self.temp.name) / "service.log")
        restricted = (None, sup._po.TABLE_RESTRICTED + ": netstat printed nothing to this process")
        with FakeLaunchd(), mock.patch.object(sup, "_read_well_known", return_value=restricted) as read, \
                mock.patch.object(sup, "launchd_pid", return_value=4242) as job:
            with self.assertRaises(fs.ServiceError) as caught:
                fs.launchd_install(self.label, self.plist, body, origin=self.web.origin, service_id="example-agent",
                                   timeout=1)
        self.assertIn("could not be proved this service's: table-restricted: ", str(caught.exception))
        self.assertIn("Apple's /usr/bin/python3", str(caught.exception))
        vouches = [c.kwargs["vouch_pid"] for c in read.call_args_list]
        self.assertIsNone(vouches[0], "a first read needs no pid")
        self.assertEqual(set(vouches[1:]), {4242}, "after a restricted answer the job's pid vouches")
        self.assertTrue(job.called)
        self.assertIs(fs.launchd_pid, sup.launchd_pid, "the facade carries it, as the Node one carries launchdPid")

    def test_faa267_a_readable_table_asks_launchctl_for_no_pid(self):
        sup = sys.modules["fabric_supervisors"]
        with FakeLaunchd(), mock.patch.object(sup, "launchd_pid") as job:
            self.install()
        job.assert_not_called()

    def test_lc14_first_install_enables_and_starts(self):
        with FakeLaunchd() as fake:
            doc = self.install()
            self.assertEqual(doc["service"]["id"], "example-agent")
            self.assertEqual(fake.state["overrides"], {self.label: "enabled"})
            self.assertIn(self.label, fake.state["loaded"])

    def test_lc14_install_disable_upgrade_stays_disabled(self):
        with FakeLaunchd() as fake:
            self.install("1")
            # The operator switches it off the way a host does: bootout, then disable.
            subprocess.run(["launchctl", "bootout", "gui/%d/%s" % (os.getuid(), self.label)], check=True)
            subprocess.run(["launchctl", "disable", "gui/%d/%s" % (os.getuid(), self.label)], check=True)
            calls_before = len(fake.state["calls"])
            result = self.install("2")
            later = fake.state["calls"][calls_before:]
            self.assertEqual(fake.state["overrides"][self.label], "disabled")
            self.assertNotIn(self.label, fake.state["loaded"])
            self.assertNotIn("enable", [c[0] for c in later])
            self.assertNotIn("bootstrap", [c[0] for c in later])
            self.assertIs(result["disabled"], True)
            # The new release is what starts once the operator turns it back on.
            self.assertEqual(plistlib.loads(self.plist.read_bytes())["ProgramArguments"], ["/bin/echo", "2"])

    def test_lc14_legacy_print_disabled_format_is_read_too(self):
        with FakeLaunchd(legacy=True) as fake:
            subprocess.run(["launchctl", "disable", "gui/%d/%s" % (os.getuid(), self.label)], check=True)
            result = self.install()
            self.assertIs(result["disabled"], True)
            self.assertNotIn("bootstrap", fake.verbs())

    def test_lc14_an_unreadable_override_table_never_enables(self):
        with FakeLaunchd(print_disabled_fails=True) as fake:
            self.install()
            self.assertNotIn("enable", fake.verbs())
            self.assertIn(self.label, fake.state["loaded"])

    def test_lc14_upgrade_of_a_running_service_restarts_it_without_enable(self):
        with FakeLaunchd() as fake:
            self.install("1")
            calls_before = len(fake.state["calls"])
            self.install("2")
            later = [c[0] for c in fake.state["calls"][calls_before:]]
            self.assertEqual(later.count("bootout"), 1)
            self.assertEqual(later.count("bootstrap"), 1)
            self.assertNotIn("enable", later)

    def test_lc14_the_operator_can_ask_for_enable_explicitly(self):
        with FakeLaunchd() as fake:
            subprocess.run(["launchctl", "disable", "gui/%d/%s" % (os.getuid(), self.label)], check=True)
            doc = self.install(force_enable=True)
            self.assertEqual(doc["service"]["id"], "example-agent")
            self.assertEqual(fake.state["overrides"][self.label], "enabled")


class LaunchdUninstallTests(unittest.TestCase):
    """LC-14: uninstall removes what install added and waits for the job to be gone."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.label = throwaway_label()
        self.plist = Path(self.temp.name) / (self.label + ".plist")
        self.plist.write_bytes(fs.launchd_plist(self.label, ["/bin/true"], working_directory=Path("/"),
                                                stdout_path=Path(self.temp.name) / "l"))

    def tearDown(self):
        self.temp.cleanup()

    def test_lc14_uninstall_waits_for_unload_and_clears_the_override(self):
        with FakeLaunchd(loaded=[self.label], overrides={self.label: "disabled"}, unload_lag=3) as fake:
            result = fs.launchd_uninstall(self.label, self.plist, timeout=5)
            self.assertNotIn(self.label, fake.state["loaded"], "returned before launchd unloaded the job")
            self.assertGreaterEqual(fake.verbs().count("print"), 4)
            self.assertFalse(self.plist.exists())
            # launchctl has no verb that deletes an override; enabled is the neutral state, so a
            # later fresh install is not mistaken for an operator's disable.
            self.assertEqual(fake.state["overrides"][self.label], "enabled")
            self.assertEqual(result["unloaded"], True)

    def test_lc14_uninstall_that_cannot_unload_says_so(self):
        with FakeLaunchd(loaded=[self.label], unload_lag=10 ** 6):
            started = time.monotonic()
            with self.assertRaises(fs.ServiceError) as caught:
                fs.launchd_uninstall(self.label, self.plist, timeout=0.5)
            self.assertLess(time.monotonic() - started, 5)
            self.assertIn(self.label, str(caught.exception))

    def test_lc14_purge_removes_data_only_when_asked(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home, "XDG_DATA_HOME": "",
                                                                                 "XDG_STATE_HOME": "", "XDG_CACHE_HOME": ""}):
            dirs = fs.service_dirs("example-agent")
            for d in dirs.values():
                d.mkdir(parents=True)
                (d / "keep.txt").write_text("x")
            with FakeLaunchd():
                fs.launchd_uninstall(self.label, self.plist, timeout=1)
            self.assertTrue(all(d.exists() for d in dirs.values()), "data must stay without purge")
            self.plist.write_bytes(b"")
            with FakeLaunchd():
                result = fs.launchd_uninstall(self.label, self.plist, timeout=1, purge=True, service_id="example-agent")
            self.assertFalse(any(d.exists() for d in dirs.values()))
            self.assertEqual(sorted(result["purged"]), sorted(str(d) for d in dirs.values()))

    def test_lc14_purge_of_one_instance_keeps_the_others(self):
        """FAA-125 (REQ-9): an organization's instance has its own folders (D16), and purging it removes only those;
        the personal instance (``instance`` absent or ``default``) purges what it always did."""
        paths = load("fabric_paths")
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home, "XDG_DATA_HOME": "",
                                                                                 "XDG_STATE_HOME": "", "XDG_CACHE_HOME": ""}):
            personal = fs.service_dirs("example-agent")
            org = paths.instance_dirs("example-agent", "org-acme-rehearsal")
            for d in list(personal.values()) + list(org.values()):
                d.mkdir(parents=True, exist_ok=True)
                (d / "keep.txt").write_text("x")
            with FakeLaunchd():
                result = fs.launchd_uninstall(self.label, self.plist, timeout=1, purge=True, service_id="example-agent",
                                              instance="org-acme-rehearsal")
            self.assertFalse(any(d.exists() for d in org.values()))
            self.assertTrue(all((d / "keep.txt").exists() for d in personal.values()), "the personal instance stays")
            self.assertEqual(sorted(result["purged"]), sorted(str(d) for d in org.values()))
            with FakeLaunchd():
                result = fs.launchd_uninstall(self.label, self.plist, timeout=1, purge=True, service_id="example-agent",
                                              instance="default")
            self.assertEqual(sorted(result["purged"]), sorted(str(d) for d in personal.values()))
            with FakeLaunchd(), self.assertRaises(fs.ServiceError):
                fs.launchd_uninstall(self.label, self.plist, timeout=1, purge=True, service_id="example-agent",
                                     instance="Not An Instance")

    def test_lc14_purge_needs_the_service_id(self):
        with FakeLaunchd():
            with self.assertRaises(fs.ServiceError):
                fs.launchd_uninstall(self.label, self.plist, timeout=1, purge=True)


class SupervisedLockTests(unittest.TestCase):
    """LC-03 / F8: a held lock under KeepAlive backs off in-process instead of a 10 s respawn loop."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        self.holder = fs.InstanceLock(self.data).acquire()

    def tearDown(self):
        self.holder.release()
        self.temp.cleanup()

    def test_by_hand_a_held_lock_still_exits_75_at_once(self):
        slept = []
        with mock.patch.dict(os.environ, {fs.SUPERVISOR_ENV: ""}):
            with self.assertRaises(SystemExit) as caught:
                fs.hold_single_instance(self.data, sleep=slept.append)
        self.assertEqual(caught.exception.code, fs.EXIT_ALREADY_RUNNING)
        self.assertEqual(slept, [])

    def test_supervised_copy_takes_over_when_the_holder_leaves(self):
        def sleep(seconds):
            slept.append(seconds)
            if len(slept) == 3:
                self.holder.release()

        slept = []
        with mock.patch.dict(os.environ, {fs.SUPERVISOR_ENV: "launchd"}):
            lock = fs.hold_single_instance(self.data, sleep=sleep)
        self.assertEqual(len(slept), 3)
        lock.release()

    def test_supervised_copy_backs_off_then_exits_75(self):
        now = [0.0]
        slept = []

        def sleep(seconds):
            slept.append(seconds)
            now[0] += seconds

        with mock.patch.dict(os.environ, {fs.SUPERVISOR_ENV: "launchd"}):
            with self.assertRaises(SystemExit) as caught:
                fs.hold_single_instance(self.data, sleep=sleep, clock=lambda: now[0])
        self.assertEqual(caught.exception.code, fs.EXIT_ALREADY_RUNNING)
        self.assertAlmostEqual(sum(slept), fs.LOCK_WAIT_SUPERVISED_SECONDS, delta=0.01)
        self.assertEqual(slept[:3], [0.5, 1.0, 2.0], "the back-off grows")
        self.assertLessEqual(max(slept), 30.0, "and is capped")
        # Under KeepAlive with ThrottleInterval 10 that is a handful of starts an hour, not 360.
        starts_per_hour = 3600 / (fs.LOCK_WAIT_SUPERVISED_SECONDS + 10)
        self.assertLess(starts_per_hour, 15)

    def test_the_plist_marks_launchd_supervision(self):
        plist = plistlib.loads(fs.launchd_plist("a.b.c", ["/bin/true"], working_directory=Path("/"),
                                                stdout_path=Path("/tmp/l")))
        self.assertEqual(plist["EnvironmentVariables"][fs.SUPERVISOR_ENV], "launchd")

    def test_a_real_supervised_process_waits_before_exiting_75(self):
        code = ("import sys; sys.path.insert(0, %r); import fabric_service as fs; "
                "fs.hold_single_instance(%r, wait_seconds=1.5)" % (str(SCRIPTS), str(self.data)))
        started = time.monotonic()
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20,
                             env=dict(os.environ, **{fs.SUPERVISOR_ENV: "launchd"}))
        elapsed = time.monotonic() - started
        self.assertEqual(out.returncode, 75)
        self.assertGreaterEqual(elapsed, 1.4)
        self.assertIn(str(os.getpid()), out.stderr)


class RotationTests(unittest.TestCase):
    """LC-12: logs are bounded by size, private, and the launchd stdout file is capped."""

    def test_lc12_writing_past_the_cap_rotates(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "logs" / "service.jsonl"
            log = fs.RotatingLog(path, max_bytes=1000, backups=3)
            for i in range(300):
                log.write("info", "line %d %s" % (i, "x" * 60))
            files = sorted(p.name for p in path.parent.iterdir())
            self.assertEqual(files, ["service.jsonl", "service.jsonl.1", "service.jsonl.2", "service.jsonl.3"])
            for p in path.parent.iterdir():
                self.assertLessEqual(p.stat().st_size, 1000)
                self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            last = json.loads(path.read_text().splitlines()[-1])
            self.assertTrue(last["message"].startswith("line 299 "))
            self.assertEqual(last["level"], "info")
            self.assertRegex(last["at"], r"^\d{4}-\d\d-\d\dT")

    def test_lc12_default_cap_is_five_by_five_megabytes(self):
        log = fs.RotatingLog(Path(tempfile.gettempdir()) / "unused.jsonl")
        self.assertEqual((log.max_bytes, log.backups), (5 * 1024 * 1024, 5))

    def test_lc12_a_line_larger_than_the_cap_is_cut_not_unbounded(self):
        with tempfile.TemporaryDirectory() as temp:
            log = fs.RotatingLog(Path(temp) / "s.jsonl", max_bytes=300, backups=1)
            log.write("error", "y" * 5000)
            for p in Path(temp).iterdir():
                self.assertLessEqual(p.stat().st_size, 300)

    def test_lc12_stdout_file_is_capped_at_start(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "service.log"
            path.write_bytes(b"a" * 2000)
            self.assertTrue(fs.cap_stdout_log(path, max_bytes=1000))
            self.assertEqual(path.stat().st_size, 0)
            self.assertEqual((Path(temp) / "service.log.1").stat().st_size, 2000)
            path.write_bytes(b"b" * 10)
            self.assertFalse(fs.cap_stdout_log(path, max_bytes=1000))
            self.assertEqual(path.stat().st_size, 10)
            self.assertFalse(fs.cap_stdout_log(Path(temp) / "absent.log"))


DRAIN_SCRIPT = textwrap.dedent('''\
    import sys, threading, time
    sys.path.insert(0, %(scripts)r)
    import fabric_service as fs
    work_seconds, deadline, hang = float(sys.argv[1]), float(sys.argv[2]), sys.argv[3] == "hang"
    done = threading.Event()
    drain = fs.Drain(deadline=deadline, grace=0.5)

    def on_stop(drained):
        print("drained" if drained else "interrupted", flush=True)
        if hang:
            time.sleep(60)
        done.set()

    drain.install(on_stop, on_stopping=lambda: print("stopping", flush=True))

    def job():
        with drain.work():
            time.sleep(work_seconds)
            print("job finished", flush=True)

    if work_seconds > 0:
        threading.Thread(target=job, daemon=True).start()
        time.sleep(0.2)
    print("ready", flush=True)
    done.wait()
    try:
        with drain.work():
            print("new work accepted", flush=True)
    except fs.Stopping:
        print("new work refused", flush=True)
''')


class DrainTests(unittest.TestCase):
    """LC-01: SIGTERM reaches exit within the deadline, idle or busy; a hung hand-over is cut."""

    def run_until_signal(self, work_seconds, deadline, hang=False):
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / "drain_probe.py"
            script.write_text(DRAIN_SCRIPT % {"scripts": str(SCRIPTS)})
            proc = subprocess.Popen([sys.executable, str(script), str(work_seconds), str(deadline),
                                     "hang" if hang else "ok"], stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(proc.stdout.readline().strip(), "ready")
                started = time.monotonic()
                proc.send_signal(signal.SIGTERM)
                code = proc.wait(timeout=15)
                elapsed = time.monotonic() - started
                return code, elapsed, proc.stdout.read()
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                proc.stdout.close()

    def test_lc01_idle_service_exits_at_once(self):
        code, elapsed, out = self.run_until_signal(0, deadline=8)
        self.assertEqual(code, 0)
        self.assertLess(elapsed, 2)
        self.assertIn("stopping", out)
        self.assertIn("drained", out)
        self.assertIn("new work refused", out)

    def test_lc01_busy_service_finishes_its_work_then_exits(self):
        code, elapsed, out = self.run_until_signal(1.0, deadline=8)
        self.assertEqual(code, 0)
        self.assertLess(elapsed, 5)
        self.assertLess(out.index("job finished"), out.index("drained"))

    def test_lc01_work_past_the_deadline_is_interrupted_inside_it(self):
        code, elapsed, out = self.run_until_signal(30, deadline=1)
        self.assertEqual(code, 0)
        self.assertLess(elapsed, 4)
        self.assertIn("interrupted", out)
        self.assertNotIn("job finished", out)

    def test_lc01_a_hung_hand_over_is_cut_by_the_hard_exit(self):
        code, elapsed, out = self.run_until_signal(0, deadline=1, hang=True)
        self.assertEqual(code, fs.EXIT_HARD_STOP)
        self.assertLess(elapsed, 4)

    def test_default_deadline_fits_lc01_and_the_plist(self):
        drain = fs.Drain()
        self.assertLessEqual(drain.deadline + drain.grace, 10, "LC-01: at most 10 s with work in flight")
        plist = plistlib.loads(fs.launchd_plist("a.b.c", ["/bin/true"], working_directory=Path("/"),
                                                stdout_path=Path("/tmp/l")))
        self.assertGreater(plist["ExitTimeOut"], drain.deadline + drain.grace,
                           "launchd's SIGKILL must come after the service's own hard exit")


class SampleServiceStopTests(unittest.TestCase):
    """LC-01 on the reference service itself: SIGTERM ends it inside the deadline, exit 0."""

    def test_lc01_sample_service_stops_on_sigterm(self):
        with tempfile.TemporaryDirectory() as temp:
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
            proc = subprocess.Popen([sys.executable, str(SCRIPTS / "sample_service.py"), "serve", "--port", str(port),
                                     "--data-dir", temp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.time() + 10
                while time.time() < deadline:
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                            break
                    except OSError:
                        time.sleep(0.1)
                started = time.monotonic()
                proc.send_signal(signal.SIGTERM)
                self.assertEqual(proc.wait(timeout=15), 0)
                self.assertLess(time.monotonic() - started, 5)
                events = (Path(temp) / "events.jsonl").read_text()
                self.assertIn("service.stopping", events)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()


class PruneReleasesTests(unittest.TestCase):
    """LC-11 / LC-15: the current release and the one before it stay; older ones go."""

    def make(self, root, names):
        for i, name in enumerate(names):
            d = root / name
            (d / "bin").mkdir(parents=True)
            stamp = 1_700_000_000 + i * 60
            os.utime(d, (stamp, stamp))

    def test_lc15_two_builds_later_two_releases_remain(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make(root, ["1.0.0-aaa", "1.1.0-bbb", "1.2.0-ccc", "1.3.0-ddd"])
            removed = fs.prune_releases(root, current=root / "1.3.0-ddd")
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["1.2.0-ccc", "1.3.0-ddd"])
            self.assertEqual(sorted(p.name for p in removed), ["1.0.0-aaa", "1.1.0-bbb"])

    def test_lc15_a_rolled_back_current_release_is_never_pruned(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make(root, ["1.0.0-aaa", "1.1.0-bbb", "1.2.0-ccc"])
            fs.prune_releases(root, current=root / "1.0.0-aaa")
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["1.0.0-aaa", "1.2.0-ccc"])

    def test_lc15_a_symlink_or_file_is_left_alone_and_keep_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make(root, ["1.0.0-aaa", "1.1.0-bbb", "1.2.0-ccc"])
            (root / "current").symlink_to(root / "1.2.0-ccc")
            (root / "receipt.json").write_text("{}")
            fs.prune_releases(root, current=root / "current")
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["1.1.0-bbb", "1.2.0-ccc", "current", "receipt.json"])
            with self.assertRaises(fs.ServiceError):
                fs.prune_releases(root, keep=1)



class LaunchdSystemDomainTests(unittest.TestCase):
    """FAA-278: a LaunchDaemon in launchd's system domain, for a headless Mac with no GUI login after a FileVault
    restart. Status and pid read without root; install and uninstall need root; the job's own pid proves its answer."""

    def setUp(self):
        self.sup = sys.modules["fabric_supervisors"]
        self.temp = tempfile.TemporaryDirectory()
        self.label = throwaway_label()
        self.plist = Path(self.temp.name) / (self.label + ".plist")
        self.web = WellKnown("example-agent")

    def tearDown(self):
        self.web.close()
        self.temp.cleanup()

    def body(self, **kw):
        return fs.launchd_plist(self.label, ["/bin/echo", "1"], working_directory=Path(self.temp.name),
                                stdout_path=Path(self.temp.name) / "service.log", **kw)

    def test_a_plist_in_launch_daemons_is_the_system_domain(self):
        self.assertEqual(fs.launchd_domain(Path("/Library/LaunchDaemons/%s.plist" % self.label)), "system")
        self.assertEqual(fs.launchd_domain(self.plist), "gui/%d" % os.getuid())
        self.assertEqual(fs.launchd_domain(domain="system"), "system")
        self.assertEqual(fs.launchd_domain(Path("/Library/LaunchDaemons/x.plist"), "gui"), "gui/%d" % os.getuid())
        self.assertEqual(fs.launchd_domain(), "gui/%d" % os.getuid(), "the default is unchanged")
        with self.assertRaises(fs.ServiceError):
            fs.launchd_domain(domain="user")

    def test_the_plist_names_its_user(self):
        self.assertEqual(plistlib.loads(self.body(user_name="agentuser"))["UserName"], "agentuser")
        self.assertNotIn("UserName", plistlib.loads(self.body()), "no UserName unless asked: a gui job runs as its user")
        for bad in ("Root User", "", "a" * 40, "x;y", "../x"):
            with self.subTest(bad=bad), self.assertRaises(fs.ServiceError):
                self.body(user_name=bad)

    def test_status_and_pid_read_the_system_domain_without_root(self):
        with FakeLaunchd(loaded=[self.label]) as fake, mock.patch.object(self.sup.os, "geteuid", return_value=501):
            self.assertTrue(fs.launchd_loaded(self.label, "system"))
            self.assertEqual(fs.launchd_pid(self.label, "system"), 4242)
            self.assertIn(["print", "system/%s" % self.label], fake.state["calls"])
            fs.launchd_loaded(self.label)
            self.assertEqual(fake.state["calls"][-1], ["print", "gui/%d/%s" % (os.getuid(), self.label)],
                             "without a domain the user's gui domain, as before")

    def test_install_and_uninstall_without_root_refuse_before_anything(self):
        with FakeLaunchd() as fake, mock.patch.object(self.sup.os, "geteuid", return_value=501):
            with self.assertRaises(fs.ServiceError) as caught:
                fs.launchd_install(self.label, self.plist, self.body(user_name="agentuser"), origin=self.web.origin,
                                   service_id="example-agent", timeout=1, domain="system")
            self.assertIn("installed by root", str(caught.exception))
            self.assertIn("launchctl bootstrap system %s" % self.plist, str(caught.exception))
            self.assertFalse(self.plist.exists(), "nothing written")
            with self.assertRaises(fs.ServiceError) as caught:
                fs.launchd_uninstall(self.label, self.plist, domain="system")
            self.assertIn("removed by root", str(caught.exception))
            self.assertEqual(fake.state["calls"], [], "no launchctl call")

    @unittest.skipUnless(sys.platform == "darwin", "a LaunchDaemon is macOS's; the socket table names its pid there")
    def test_root_installs_and_the_jobs_own_pid_proves_the_answer(self):
        with FakeLaunchd() as fake, mock.patch.object(self.sup.os, "geteuid", return_value=0), \
                mock.patch.object(self.sup, "launchd_pid", return_value=os.getpid()):
            doc = fs.launchd_install(self.label, self.plist, self.body(user_name="agentuser"), origin=self.web.origin,
                                     service_id="example-agent", timeout=5, domain="system")
            self.assertEqual(doc["service"]["id"], "example-agent")
            self.assertIn(["bootstrap", "system", str(self.plist)], fake.state["calls"])
            self.assertIn(["bootout", "system/%s" % self.label], fake.state["calls"])
            self.assertIn(["print-disabled", "system"], fake.state["calls"])
            fs.launchd_uninstall(self.label, self.plist, domain="system")
            self.assertFalse(self.plist.exists())
            self.assertEqual(fake.state["calls"][-1], ["enable", "system/%s" % self.label])

    @unittest.skipUnless(sys.platform == "darwin", "a LaunchDaemon is macOS's; the socket table names its pid there")
    def test_root_refuses_an_answer_another_process_gives(self):
        with FakeLaunchd(), mock.patch.object(self.sup.os, "geteuid", return_value=0), \
                mock.patch.object(self.sup, "launchd_pid", return_value=999999):
            with self.assertRaises(fs.ServiceError) as caught:
                fs.launchd_install(self.label, self.plist, self.body(user_name="agentuser"), origin=self.web.origin,
                                   service_id="example-agent", timeout=1, domain="system")
        self.assertIn("is not this LaunchDaemon's", str(caught.exception))
        self.assertIn("pid 999999", str(caught.exception))

    def test_a_purge_of_a_launch_daemon_is_refused(self):
        with FakeLaunchd() as fake, mock.patch.object(self.sup.os, "geteuid", return_value=0):
            with self.assertRaises(fs.ServiceError) as caught:
                fs.launchd_uninstall(self.label, self.plist, domain="system", purge=True, service_id="example-agent")
            self.assertIn("belongs to its UserName", str(caught.exception))
            self.assertEqual(fake.state["calls"], [])

    def test_a_launch_daemon_needs_a_user_name(self):
        with FakeLaunchd() as fake, mock.patch.object(self.sup.os, "geteuid", return_value=0):
            with self.assertRaises(fs.ServiceError) as caught:
                fs.launchd_install(self.label, self.plist, self.body(), origin=self.web.origin,
                                   service_id="example-agent", timeout=1, domain="system")
            self.assertIn("needs UserName", str(caught.exception))
            self.assertFalse(self.plist.exists())
            self.assertEqual(fake.state["calls"], [])

    def test_a_user_name_only_in_the_environment_is_refused(self):
        body = self.body(environment={"UserName": "agentuser"})
        with FakeLaunchd() as fake, mock.patch.object(self.sup.os, "geteuid", return_value=0):
            with self.assertRaises(fs.ServiceError) as caught:
                fs.launchd_install(self.label, self.plist, body, origin=self.web.origin,
                                   service_id="example-agent", timeout=1, domain="system")
            self.assertIn("needs UserName", str(caught.exception))
            self.assertEqual(fake.state["calls"], [])

    def test_a_label_another_user_name_holds_is_refused(self):
        self.plist.write_bytes(self.body(user_name="otheruser"))
        with FakeLaunchd() as fake, mock.patch.object(self.sup.os, "geteuid", return_value=0):
            with self.assertRaises(fs.ServiceError) as caught:
                fs.launchd_install(self.label, self.plist, self.body(user_name="agentuser"), origin=self.web.origin,
                                   service_id="example-agent", timeout=1, domain="system")
            self.assertIn("otheruser's LaunchDaemon", str(caught.exception))
            self.assertEqual(fake.state["calls"], [])
        self.assertIn(b"otheruser", self.plist.read_bytes(), "the other account's plist is untouched")

    def test_the_system_domain_is_macos_only_and_its_folder_ignores_case(self):
        with mock.patch.object(self.sup.sys, "platform", "linux"):
            with self.assertRaises(fs.ServiceError) as caught:
                fs.launchd_domain(domain="system")
            self.assertIn("macOS only", str(caught.exception))
        if sys.platform == "darwin":
            self.assertEqual(fs.launchd_domain(Path("/library/launchdaemons/x.plist")), "system")

    @unittest.skipUnless(sys.platform == "darwin", "lsof -p asks a macOS process")
    def test_a_restricted_table_is_proved_by_the_jobs_lsof_or_named(self):
        po = self.sup._po
        port = self.web.server.server_address[1]
        hidden = po.Owner(po.UNKNOWN, None, None, "sysctl", po.TABLE_RESTRICTED + ": probe")
        listening = "p%d\nn127.0.0.1:%d\n" % (os.getpid(), port)
        with mock.patch.object(po, "server_end", return_value=hidden), mock.patch.object(po, "_run", return_value=listening):
            doc, why = self.sup._read_job_well_known(self.web.origin, os.getpid())
        self.assertEqual((doc or {}).get("service", {}).get("id"), "example-agent", why)
        wildcard = "p%d\nn*:%d\n" % (os.getpid(), port)
        for out in ("", wildcard):
            with self.subTest(lsof=out), mock.patch.object(po, "server_end", return_value=hidden), \
                    mock.patch.object(po, "_run", return_value=out):
                doc, why = self.sup._read_job_well_known(self.web.origin, os.getpid())
            self.assertIsNone(doc, "a wildcard bind is not vouched for (RT-3)")
            self.assertTrue(why.startswith(po.TABLE_RESTRICTED), why)
        with self.assertRaises(fs.ServiceError):
            self.sup._JobConnection("127.0.0.1", port, None, 1.0)

    def test_a_gui_bootstrap_without_a_session_names_the_system_domain(self):
        error = "Bootstrap failed: 125: Domain does not support specified action"
        with FakeLaunchd(bootstrap_error=error), mock.patch.object(self.sup.time, "sleep"):
            with self.assertRaises(fs.ServiceError) as caught:
                fs.launchd_install(self.label, self.plist, self.body(), origin=self.web.origin,
                                   service_id="example-agent", timeout=1)
        self.assertIn("no GUI login session", str(caught.exception))
        self.assertIn("/Library/LaunchDaemons", str(caught.exception))
        self.assertIn("remove the LaunchAgent", str(caught.exception))
        with FakeLaunchd(bootstrap_error="Bootstrap failed: 5: Input/output error"), \
                mock.patch.object(self.sup.time, "sleep"):
            with self.assertRaises(fs.ServiceError) as caught:
                fs.launchd_install(self.label, self.plist, self.body(), origin=self.web.origin,
                                   service_id="example-agent", timeout=1)
        self.assertNotIn("GUI login", str(caught.exception), "an I/O error is not a missing session")
        with FakeLaunchd(bootstrap_error="Bootstrap failed: 5: Input/output error in /tmp/125/x.plist"), \
                mock.patch.object(self.sup.time, "sleep"):
            with self.assertRaises(fs.ServiceError) as caught:
                fs.launchd_install(self.label, self.plist, self.body(), origin=self.web.origin,
                                   service_id="example-agent", timeout=1)
        self.assertNotIn("GUI login", str(caught.exception), "125 in a path is not the error code")


if __name__ == "__main__":
    unittest.main()
