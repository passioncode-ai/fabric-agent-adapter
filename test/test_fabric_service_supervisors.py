"""The systemd unit and the Task Scheduler task (contract DEC-0032, service.md "Supervisor"; FAA-21). The writers are
checked as text; install and uninstall run against a recording stand-in for systemctl and schtasks, never the real
ones (LC-14)."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from test_fabric_service import load

fs = load("fabric_service")
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


class Recorder:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        code = 1 if any(word in argv for word in self.fail) else 0

        class Result:
            returncode, stdout, stderr = code, "", "refused" if code else ""
        return Result()


class SystemdUnitTests(unittest.TestCase):
    def unit(self, **extra):
        return fs.systemd_unit("example-agent.default.service", ["/usr/bin/python3", "/opt/example agent/serve.py", "--port", "47201"],
                               working_directory=Path("/opt/example agent"), **{"description": "Example Agent", **extra})

    def test_the_contracts_settings(self):
        text = self.unit()
        for line in ("Restart=always", "RestartSec=10", "TimeoutStopSec=15", "WantedBy=default.target", "Description=Example Agent",
                     'WorkingDirectory="/opt/example agent"', 'Environment="FABRIC_SERVICE_SUPERVISOR=systemd"'):
            self.assertIn(line + "\n", text, line)
        self.assertIn('ExecStart="/usr/bin/python3" "/opt/example agent/serve.py" "--port" "47201"\n', text)

    def test_specifiers_and_variables_are_escaped(self):
        text = fs.systemd_unit("x.service", ["/bin/echo", "100%", "$HOME", 'say "hi"\\'], working_directory=Path("/tmp"))
        self.assertIn('ExecStart="/bin/echo" "100%%" "$$HOME" "say \\"hi\\"\\\\"', text)

    def test_refusals(self):
        with self.assertRaises(fs.ServiceError):
            fs.systemd_unit("bad name", ["/bin/x"], working_directory=Path("/tmp"))
        with self.assertRaises(fs.ServiceError):
            fs.systemd_unit("x.service", ["relative/x"], working_directory=Path("/tmp"))
        with self.assertRaises(fs.ServiceError):
            fs.systemd_unit("x.service", ["/bin/x", "line\nbreak"], working_directory=Path("/tmp"))
        with self.assertRaises(fs.ServiceError):  # no supervisor file carries a secret (service.md)
            fs.systemd_unit("x.service", ["/bin/x"], working_directory=Path("/tmp"), environment={"API_KEY": "abc"})
        with self.assertRaises(fs.ServiceError):
            fs.systemd_unit("x.service", ["/bin/x", "--key=" + "s" + "k-" + "q" * 24], working_directory=Path("/tmp"))
        with self.assertRaises(fs.ServiceError):
            self.unit(stop_timeout=5)
        with self.assertRaises(fs.ServiceError):  # a tab or a line break would end the line early
            self.unit(description="Example\nExecStartPre=/bin/sh")
        with self.assertRaises(fs.ServiceError):
            self.unit(environment={"BAD NAME": "x"})  # must outlast the 8 s drain (DRAIN_SECONDS)

    def test_install_and_uninstall(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Recorder()
            unit_dir = Path(temp) / "systemd/user"
            done = fs.systemd_install("example-agent.default.service", self.unit(), unit_dir=unit_dir, run=run, system="linux")
            path = unit_dir / "example-agent.default.service"
            self.assertTrue(path.is_file())
            self.assertEqual(run.calls, [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", "example-agent.default.service"]])
            self.assertEqual(done, path)
            run = Recorder()
            fs.systemd_uninstall("example-agent.default.service", unit_dir=unit_dir, run=run, system="linux")
            self.assertFalse(path.exists())
            self.assertEqual(run.calls, [["systemctl", "--user", "disable", "--now", "example-agent.default.service"], ["systemctl", "--user", "daemon-reload"]])

    def test_a_failed_enable_is_reported_and_off_linux_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(fs.ServiceError):
                fs.systemd_install("x.service", self.unit(), unit_dir=Path(temp), run=Recorder(fail={"enable"}), system="linux")
            with self.assertRaises(fs.ServiceError):
                fs.systemd_install("x.service", self.unit(), unit_dir=Path(temp), run=Recorder(), system="darwin")


class TaskSchedulerTests(unittest.TestCase):
    def task(self, **extra):
        return fs.task_xml("\\PassionCode\\example-agent.default", [r"C:\Program Files\Example\python.exe", r"C:\Example App\serve.py", "--port", "47201"],
                           working_directory=r"C:\Example App", description="Example Agent", user="HOST\\person", **extra)

    def test_the_contracts_settings(self):
        doc = ET.fromstring(self.task().split("\n", 1)[1])
        g = lambda path: doc.find(path, NS)
        self.assertEqual(g("t:RegistrationInfo/t:URI").text, "\\PassionCode\\example-agent.default")
        self.assertEqual(g("t:Triggers/t:LogonTrigger/t:UserId").text, "HOST\\person")
        self.assertEqual(g("t:Principals/t:Principal/t:LogonType").text, "InteractiveToken")
        self.assertEqual(g("t:Principals/t:Principal/t:RunLevel").text, "LeastPrivilege")
        self.assertEqual(g("t:Settings/t:ExecutionTimeLimit").text, "PT0S")
        self.assertEqual(g("t:Settings/t:RestartOnFailure/t:Interval").text, "PT1M")
        self.assertEqual(g("t:Settings/t:MultipleInstancesPolicy").text, "IgnoreNew")
        self.assertEqual(g("t:Actions/t:Exec/t:Command").text, r"C:\Program Files\Example\python.exe")
        self.assertEqual(g("t:Actions/t:Exec/t:Arguments").text, '"C:\\Example App\\serve.py" --port 47201')
        self.assertEqual(g("t:Actions/t:Exec/t:WorkingDirectory").text, r"C:\Example App")

    def test_xml_is_escaped(self):
        text = fs.task_xml("\\PassionCode\\x", [r"C:\x.exe", "a<b&c"], working_directory=r"C:\w", description="A & <B>", user="H\\u")
        doc = ET.fromstring(text.split("\n", 1)[1])
        self.assertEqual(doc.find("t:RegistrationInfo/t:Description", NS).text, "A & <B>")
        self.assertEqual(doc.find("t:Actions/t:Exec/t:Arguments", NS).text, "a<b&c")

    def test_refusals(self):
        for bad in (dict(task="no-leading-backslash"), dict(argv=["relative.exe"]), dict(argv=[r"C:\x.exe", "--token=" + "s" + "k-" + "w" * 24]),
                    dict(argv=[r"C:\x.exe", "a\x01b"]), dict(cwd="C:\\w\n"), dict(user="")):
            with self.subTest(bad=bad), self.assertRaises(fs.ServiceError), \
                    mock.patch.dict(os.environ, {"USERNAME": ""}):
                fs.task_xml(bad.get("task", "\\PassionCode\\x"), bad.get("argv", [r"C:\x.exe"]), working_directory=bad.get("cwd", r"C:\w"),
                            user=bad.get("user", "H\\u"))

    def test_install_and_uninstall(self):
        run = Recorder()
        fs.task_install("\\PassionCode\\example-agent.default", self.task(), run=run, system="win32")
        self.assertEqual([c[:3] for c in run.calls], [["schtasks", "/Create", "/TN"], ["schtasks", "/Run", "/TN"]])
        self.assertIn("/XML", run.calls[0])
        self.assertIn("/F", run.calls[0])
        xml_file = Path(run.calls[0][run.calls[0].index("/XML") + 1])
        self.assertFalse(xml_file.exists(), "the task file is removed once the task exists")
        run = Recorder()
        fs.task_uninstall("\\PassionCode\\example-agent.default", run=run, system="win32")
        self.assertEqual([c[:2] for c in run.calls], [["schtasks", "/End"], ["schtasks", "/Delete"]])
        with self.assertRaises(fs.ServiceError):
            fs.task_install("\\PassionCode\\x", self.task(), run=Recorder(), system="linux")
        with self.assertRaises(fs.ServiceError):
            fs.task_install("\\PassionCode\\x", self.task(), run=Recorder(fail={"/Create"}), system="win32")


class SupervisedBackOff(unittest.TestCase):
    """A copy systemd restarts backs off on a held lock the way a launchd one does: an immediate exit 75
    would be a restart every RestartSec, forever."""

    def test_systemd_waits_and_a_hand_start_does_not(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            holder = fs.InstanceLock(data).acquire()
            slept = []

            def sleep(seconds):
                slept.append(seconds)
                holder.release()

            with mock.patch.dict(os.environ, {fs.SUPERVISOR_ENV: "systemd"}):
                self.assertTrue(fs.supervised())
                fs.hold_single_instance(data, sleep=sleep).release()
            self.assertEqual(slept, [fs.LOCK_BACKOFF_FIRST_SECONDS])
            holder = fs.InstanceLock(data).acquire()
            try:
                with mock.patch.dict(os.environ, {fs.SUPERVISOR_ENV: "cron"}), self.assertRaises(SystemExit):
                    self.assertFalse(fs.supervised())
                    fs.hold_single_instance(data, sleep=slept.append)
            finally:
                holder.release()
            self.assertEqual(len(slept), 1)


if __name__ == "__main__":
    unittest.main()
