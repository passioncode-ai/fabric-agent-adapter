"""DEC-0032 in the Python service kit: services on Windows and Linux.

Cross-OS cases check the descriptor rules (a supervisor per system, Windows paths, no network
share), the folders per OS and the Windows token rule on SIDs already read. The `Windows` cases
run only on a Windows runner (the `windows` job): the instance lock between two processes, a token
written and read back, and the refusals the rule names.
"""
import copy
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
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

# The contract's fixtures at the pin (fixtures/positive/service-descriptor-task-scheduler.json,
# -systemd.json), reduced to the fields these rules read.
TASK = {
    "protocol": "fabric-service/0.1", "id": "example-agent", "instance": "default", "name": "Example Agent",
    "origin": "http://127.0.0.1:47195",
    "auth": {"tokenFile": "~\\AppData\\Local\\example-agent\\service.token", "header": "X-Example-Token", "scheme": "none"},
    "lifecycle": {"manager": "task-scheduler", "task": "\\PassionCode\\example-agent.default"},
    "paths": {"data": "C:\\Users\\example\\AppData\\Local\\example-agent",
              "logs": ["C:\\Users\\example\\AppData\\Local\\example-agent\\Logs\\service.log"]},
    "commands": {"doctor": ["C:\\Users\\example\\AppData\\Local\\Programs\\example-agent\\example-agent.exe", "doctor", "--json"]},
    "installedAt": "2026-09-28T18:00:00Z", "installedBy": "example-agent service install 0.2.0",
}
SYSTEMD = dict(copy.deepcopy(TASK), auth={"tokenFile": "~/.local/share/example-agent/service.token"},
               lifecycle={"manager": "systemd", "unit": "example-agent.service"},
               paths={"data": "~/.local/share/example-agent", "logs": []},
               commands={"doctor": ["~/.local/bin/example-agent", "doctor"]})


def changed(base, **life):
    doc = copy.deepcopy(base)
    doc["lifecycle"] = life
    return doc


class Descriptors(unittest.TestCase):
    def test_the_contract_positive_fixtures_are_valid(self):
        self.assertEqual(fs.validate_descriptor(TASK), [])
        self.assertEqual(fs.validate_descriptor(SYSTEMD), [])

    def test_a_manager_without_its_job_is_refused(self):
        self.assertTrue(any("declares unit" in p for p in fs.validate_descriptor(changed(SYSTEMD, manager="systemd"))))
        self.assertTrue(any("declares task" in p for p in fs.validate_descriptor(changed(TASK, manager="task-scheduler"))))

    def test_a_job_beside_another_manager_is_refused(self):
        problems = fs.validate_descriptor(changed(SYSTEMD, manager="none", unit="example-agent.service"))
        self.assertTrue(any("unit belongs to manager systemd" in p for p in problems), problems)
        problems = fs.validate_descriptor(changed(TASK, manager="systemd", unit="x.service", task="\\PassionCode\\x"))
        self.assertTrue(any("task belongs to manager task-scheduler" in p for p in problems), problems)

    def test_an_unknown_manager_is_refused(self):
        problems = fs.validate_descriptor(changed(TASK, manager="windows-service"))
        self.assertTrue(any("launchd, systemd, task-scheduler or none" in p for p in problems), problems)

    def test_a_network_share_is_never_a_local_path(self):
        for share in ("\\\\server\\share\\service.token", "\\\\?\\C:\\x\\service.token", "//server/share/t"):
            doc = copy.deepcopy(TASK)
            doc["auth"]["tokenFile"] = share
            self.assertTrue(any("never a network share" in p for p in fs.validate_descriptor(doc)), share)

    def test_a_remote_service_carries_no_supervisor(self):
        doc = copy.deepcopy(TASK)
        doc.update(placement="remote", origin="https://agent.example.com")
        doc["lifecycle"] = {"manager": "none", "task": "\\PassionCode\\x"}
        doc.pop("commands")
        self.assertTrue(any("no Task Scheduler task" in p for p in fs.validate_descriptor(doc)))

    def test_windows_paths_expand(self):
        with mock.patch.object(fs.os.path, "expanduser", side_effect=lambda p: p), \
                mock.patch.object(fs, "Path", side_effect=lambda p: mock.Mock(is_absolute=lambda: True)):
            fs.expand("C:\\Users\\x\\data")
            fs.expand("~\\AppData\\Local\\x")
        with self.assertRaises(fs.ServiceError):
            fs.expand("\\\\server\\share\\x")


class Folders(unittest.TestCase):
    def test_windows_services_folder_is_local_app_data(self):
        with mock.patch.object(fs.sys, "platform", "win32"), \
                mock.patch.dict(os.environ, {"LOCALAPPDATA": "/fake/Local"}, clear=False):
            os.environ.pop("FABRIC_SERVICES_DIR", None)
            self.assertEqual(fs.services_dir(), Path("/fake/Local") / "passioncode-fabric" / "services")
            dirs = fs.service_dirs("example-agent")
            self.assertEqual(dirs["data"], Path("/fake/Local/example-agent"))
            self.assertEqual(dirs["logs"], Path("/fake/Local/example-agent/Logs"))

    def test_the_override_wins_everywhere(self):
        for platform in ("win32", "linux", "darwin"):
            with mock.patch.object(fs.sys, "platform", platform), \
                    mock.patch.dict(os.environ, {"FABRIC_SERVICES_DIR": "/elsewhere"}):
                self.assertEqual(fs.services_dir(), Path("/elsewhere"))

    def test_launchd_is_asked_only_on_macos(self):
        for platform, named in (("win32", "Task Scheduler"), ("linux", "systemd")):
            with mock.patch.object(fs.sys, "platform", platform), \
                    mock.patch.object(fs.os, "getuid", side_effect=AssertionError("getuid off macOS"), create=True):
                with self.assertRaises(fs.ServiceError) as caught:
                    fs.launchd_loaded("ai.passioncode.test")
                self.assertIn(named, str(caught.exception))


class WindowsTokenRule(unittest.TestCase):
    USER = "S-1-5-21-1-2-3-1001"

    def problem(self, owner, granting):
        return fs.token_acl_problem(Path("C:/t"), owner, granting, self.USER)

    def test_the_user_system_and_administrators_may_hold_access(self):
        self.assertIsNone(self.problem(self.USER, [self.USER, "S-1-5-18", "S-1-5-32-544"]))

    def test_another_owner_is_refused_by_sid(self):
        self.assertIn("S-1-5-32-544", self.problem("S-1-5-32-544", [self.USER]))

    def test_any_other_grant_is_refused_by_sid(self):
        for sid in ("S-1-1-0", "S-1-5-11", "S-1-5-32-545", "S-1-3-0", "S-1-5-21-9-9-9-1002"):
            self.assertIn(sid, self.problem(self.USER, [self.USER, sid]))


@unittest.skipUnless(os.name == "nt", "needs Windows")
class Windows(unittest.TestCase):
    def setUp(self):
        # Inside the profile, as the rule requires: the runner's TEMP is under it.
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_second_process_is_refused_and_reads_the_pid(self):
        holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
            import importlib.util, sys, time
            from pathlib import Path
            spec = importlib.util.spec_from_file_location("fs", {str(SCRIPTS / 'fabric_service.py')!r})
            fs = importlib.util.module_from_spec(spec); spec.loader.exec_module(fs)
            fs.InstanceLock(Path({str(self.dir)!r})).acquire()
            print("held", flush=True)
            time.sleep(60)
            """)], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            with self.assertRaises(fs.AlreadyRunning) as caught:
                fs.InstanceLock(self.dir).acquire()
            self.assertEqual(caught.exception.holder_pid, holder.pid)
        finally:
            holder.kill()
            holder.wait()
        fs.InstanceLock(self.dir).acquire().release()   # the OS released it with the process

    def test_a_token_written_by_the_kit_reads_back(self):
        path = self.dir / "svc" / "service.token"
        token = fs.ensure_token(path)
        self.assertEqual(fs.read_token(path), token)
        owner, granting = fs.windows_acl(path)
        self.assertEqual(owner, fs.windows_user_sid())
        self.assertTrue(set(granting) <= {fs.windows_user_sid(), "S-1-5-18", "S-1-5-32-544"}, granting)
        self.assertEqual(path.read_bytes(), token.encode())   # binary: no CRLF, no BOM

    def test_a_token_shared_with_everyone_is_refused_by_sid(self):
        path = self.dir / "svc" / "service.token"
        fs.ensure_token(path)
        subprocess.run(["icacls", str(path), "/grant", "*S-1-1-0:(R)"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with self.assertRaises(fs.ServiceError) as caught:
            fs.read_token(path)
        self.assertIn("S-1-1-0", str(caught.exception))

    def test_a_link_is_refused(self):
        target = self.dir / "svc" / "service.token"
        fs.ensure_token(target)
        link = self.dir / "link.token"
        try:
            os.symlink(target, link)
        except OSError as exc:
            self.skipTest(f"this account cannot create a symbolic link: {exc}")
        with self.assertRaises(fs.ServiceError):
            fs.read_token(link)

    def test_the_log_is_written_in_binary(self):
        (self.dir / "logs").mkdir()
        fs.RotatingLog(self.dir / "logs" / "service.log").write("info", "one")
        fs.RotatingLog(self.dir / "logs" / "service.log").write("info", "two")
        self.assertNotIn(b"\r\n", (self.dir / "logs" / "service.log").read_bytes())


if __name__ == "__main__":
    unittest.main()
