"""The systemd unit and the Task Scheduler task (contract DEC-0032, service.md "Supervisor"; FAA-21). The writers are
checked as text and, where the tool exists, by the real reader: `systemd-analyze verify` on Linux, `schtasks /Create`
of a throwaway task (created, read back, deleted, never run) on Windows. Install and uninstall run against a
recording stand-in for systemctl and schtasks, never the real ones (LC-14)."""
import os
import shutil
import subprocess
from pathlib import Path, PureWindowsPath
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from test_fabric_service import load

fs = load("fabric_service")
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


class Recorder:
    """Stands in for systemctl and schtasks: fails a call naming a word in `fail`, prints `out[word]` for one naming it."""

    def __init__(self, fail=(), out=None):
        self.calls, self.fail, self.out = [], set(fail), dict(out or {})

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        code = 1 if any(word in argv for word in self.fail) else 0
        printed = next((text for word, text in self.out.items() if word in argv), "")

        class Result:
            returncode, stdout, stderr = code, printed, "refused" if code else ""
        return Result()


SETTINGS_ORDER = ["MultipleInstancesPolicy", "DisallowStartIfOnBatteries", "StopIfGoingOnBatteries", "StartWhenAvailable",
                  "Enabled", "ExecutionTimeLimit", "RestartOnFailure"]  # the order `schtasks /Query /XML` exports


class SystemdUnitTests(unittest.TestCase):
    def unit(self, **extra):
        return fs.systemd_unit("example-agent.default.service", ["/usr/bin/python3", "/opt/example agent/serve.py", "--port", "47201"],
                               working_directory=Path("/opt/example agent"), **{"description": "Example Agent", **extra})

    def test_the_contracts_settings(self):
        text = self.unit()
        for line in ("Restart=always", "RestartSec=10", "TimeoutStopSec=15", "WantedBy=default.target", "Description=Example Agent",
                     'WorkingDirectory=/opt/example agent', 'Environment="FABRIC_SERVICE_SUPERVISOR=systemd"'):
            self.assertIn(line + "\n", text, line)
        self.assertIn('ExecStart="/usr/bin/python3" "/opt/example agent/serve.py" "--port" "47201"\n', text)

    def test_specifiers_and_variables_are_escaped(self):
        text = fs.systemd_unit("x.service", ["/bin/echo", "100%", "$HOME", 'say "hi"\\'], working_directory=Path("/tmp"))
        self.assertIn('ExecStart="/bin/echo" "100%%" "$$HOME" "say \\"hi\\"\\\\"', text)

    def test_environment_keeps_its_dollar_and_escapes_its_specifiers(self):
        """Finding 17: systemd expands no variable in Environment=, so a $ doubled there reached the service as $$."""
        text = fs.systemd_unit("x.service", ["/bin/x"], working_directory=Path("/tmp"),
                               environment={"EXAMPLE_PRICE": "$5 at 100%", "EXAMPLE_QUOTE": 'a "b" \\c'})
        self.assertIn('Environment="EXAMPLE_PRICE=$5 at 100%%"\n', text)
        self.assertIn('Environment="EXAMPLE_QUOTE=a \\"b\\" \\\\c"\n', text)
        self.assertIn('ExecStart="/opt/$$x/bin" "$$y"\n', fs.systemd_unit("x.service", ["/opt/$x/bin", "$y"], working_directory=Path("/tmp")))

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
            self.unit(environment={"BAD NAME": "x"})
        with self.assertRaises(fs.ServiceError):
            fs.systemd_unit("x.service", ["/bin/x"], working_directory=Path("relative"))

    def test_the_working_directory_is_not_quoted_and_specifiers_stay_literal(self):
        # Quoted, systemd takes the quotes as part of the path and refuses the unit ("path is not absolute").
        text = fs.systemd_unit("x.service", ["/bin/x"], working_directory=Path("/srv/100% x"), description="at 100% %h")
        self.assertIn("WorkingDirectory=/srv/100%% x\n", text)
        self.assertIn("Description=at 100%% %%h\n", text)
        # A unit is a Linux file: a Path built on Windows still names a POSIX directory.
        text = fs.systemd_unit("x.service", ["/bin/x"], working_directory=PureWindowsPath("/opt/a b"))
        self.assertIn("WorkingDirectory=/opt/a b\n", text)

    @unittest.skipUnless(shutil.which("systemd-analyze"), "needs systemd-analyze (the Linux CI job)")
    def test_systemd_accepts_the_unit(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp) / "work dir"
            work.mkdir()
            unit = Path(temp) / "fabric-verify-example.service"
            unit.write_text(fs.systemd_unit(unit.name, [shutil.which("true") or "/bin/true", "a b", "100%"], working_directory=work,
                                            description="Example 100%"))
            out = subprocess.run(["systemd-analyze", "verify", str(unit)], capture_output=True, text=True)
            self.assertNotIn("bad unit file setting", out.stdout + out.stderr)
            self.assertNotIn(unit.name + ":", out.stderr, out.stderr)  # must outlast the 8 s drain (DRAIN_SECONDS)

    def test_install_and_uninstall(self):
        name = "example-agent.default.service"
        reload, enable, restart = (["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", name],
                                   ["systemctl", "--user", "restart", name])
        is_enabled = ["systemctl", "--user", "is-enabled", name]
        with tempfile.TemporaryDirectory() as temp:
            run = Recorder()
            unit_dir = Path(temp) / "systemd/user"
            done = fs.systemd_install(name, self.unit(), unit_dir=unit_dir, run=run, system="linux")
            path = unit_dir / name
            self.assertTrue(path.is_file())
            self.assertEqual(run.calls, [reload, enable, restart], "a first install enables and starts it")
            self.assertEqual(done, path)
            run = Recorder(out={"is-enabled": "enabled\n"})
            fs.systemd_install(name, self.unit(description="v2"), unit_dir=unit_dir, run=run, system="linux")
            self.assertEqual(run.calls, [is_enabled, reload, enable, restart], "an upgrade restarts what runs")
            self.assertIn("Description=v2", path.read_text())
            run = Recorder(out={"is-enabled": "disabled\n"})
            fs.systemd_install(name, self.unit(description="v3"), unit_dir=unit_dir, run=run, system="linux")
            self.assertEqual(run.calls, [is_enabled, reload], "the operator switched it off: it stays off (LC-14)")
            self.assertIn("Description=v3", path.read_text())
            run = Recorder(out={"is-enabled": "disabled\n"})
            fs.systemd_install(name, self.unit(), unit_dir=unit_dir, run=run, system="linux", force_enable=True)
            self.assertEqual(run.calls, [is_enabled, reload, enable, restart])
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
        # DEC-0057: a task's action has no environment, so the marker is an argument.
        self.assertEqual(g("t:Actions/t:Exec/t:Arguments").text, '"C:\\Example App\\serve.py" --port 47201 --fabric-supervisor task-scheduler')
        self.assertEqual(g("t:Actions/t:Exec/t:WorkingDirectory").text, r"C:\Example App")

    def test_xml_is_escaped(self):
        text = fs.task_xml("\\PassionCode\\x", [r"C:\x.exe", "a<b&c"], working_directory=r"C:\w", description="A & <B>", user="H\\u")
        doc = ET.fromstring(text.split("\n", 1)[1])
        self.assertEqual(doc.find("t:RegistrationInfo/t:Description", NS).text, "A & <B>")
        self.assertEqual(doc.find("t:Actions/t:Exec/t:Arguments", NS).text, "a<b&c --fabric-supervisor task-scheduler")

    def test_refusals(self):
        for bad in (dict(task="no-leading-backslash"), dict(argv=["relative.exe"]), dict(argv=[r"C:\x.exe", "--token=" + "s" + "k-" + "w" * 24]),
                    dict(argv=[r"C:\x.exe", "a\x01b"]), dict(cwd="C:\\w\n"), dict(user="")):
            with self.subTest(bad=bad), self.assertRaises(fs.ServiceError), \
                    mock.patch.dict(os.environ, {"USERNAME": ""}):
                fs.task_xml(bad.get("task", "\\PassionCode\\x"), bad.get("argv", [r"C:\x.exe"]), working_directory=bad.get("cwd", r"C:\w"),
                            user=bad.get("user", "H\\u"))

    def test_the_settings_are_in_the_order_task_scheduler_exports(self):
        doc = ET.fromstring(self.task().split("\n", 1)[1])
        names = [child.tag.split("}")[1] for child in doc.find("t:Settings", NS)]
        self.assertEqual(names, SETTINGS_ORDER)

    def test_install_and_uninstall(self):
        task = "\\PassionCode\\example-agent.default"
        run = Recorder(fail={"/Query"})
        fs.task_install(task, self.task(), run=run, system="win32")
        self.assertEqual([c[:2] for c in run.calls], [["schtasks", "/Query"], ["schtasks", "/Create"], ["schtasks", "/Run"]],
                         "a first install creates and runs it")
        create = run.calls[1]
        self.assertEqual(create[2:4], ["/TN", task])
        self.assertIn("/XML", create)
        self.assertIn("/F", create)
        xml_file = Path(create[create.index("/XML") + 1])
        self.assertFalse(xml_file.exists(), "the task file is removed once the task exists")
        enabled = self.task()
        disabled = enabled.replace("<Enabled>true</Enabled>\n    <ExecutionTimeLimit>", "<Enabled>false</Enabled>\n    <ExecutionTimeLimit>")
        self.assertNotEqual(enabled, disabled)
        run = Recorder(out={"/Query": enabled})
        fs.task_install(task, self.task(), run=run, system="win32")
        self.assertEqual([c[:2] for c in run.calls], [["schtasks", "/Query"], ["schtasks", "/Create"], ["schtasks", "/End"], ["schtasks", "/Run"]],
                         "an upgrade restarts what runs")
        run = Recorder(out={"/Query": disabled})
        fs.task_install(task, self.task(), run=run, system="win32")
        self.assertEqual([c[:2] for c in run.calls], [["schtasks", "/Query"], ["schtasks", "/Create"], ["schtasks", "/Change"]],
                         "the operator switched it off: it stays off (LC-14)")
        self.assertIn("/DISABLE", run.calls[2])
        run = Recorder(out={"/Query": disabled})
        fs.task_install(task, self.task(), run=run, system="win32", force_enable=True)
        self.assertEqual([c[:2] for c in run.calls][-2:], [["schtasks", "/End"], ["schtasks", "/Run"]])
        run = Recorder()
        fs.task_uninstall("\\PassionCode\\example-agent.default", run=run, system="win32")
        self.assertEqual([c[:2] for c in run.calls], [["schtasks", "/End"], ["schtasks", "/Delete"]])
        with self.assertRaises(fs.ServiceError):
            fs.task_install("\\PassionCode\\x", self.task(), run=Recorder(), system="linux")
        with self.assertRaises(fs.ServiceError):
            fs.task_install("\\PassionCode\\x", self.task(), run=Recorder(fail={"/Create"}), system="win32")

    @unittest.skipUnless(os.name == "nt", "needs Windows (the windows CI job)")
    def test_task_scheduler_accepts_the_task(self):
        # The real schtasks reads the XML the kit writes; nothing runs (the task is created, read back and deleted).
        task = "\\PassionCode-test\\example-%s" % os.urandom(4).hex()
        user = subprocess.run(["whoami"], capture_output=True, text=True, check=True).stdout.strip()
        text = fs.task_xml(task, [os.path.join(os.environ["SystemRoot"], "System32", "cmd.exe"), "/c", "exit", "0"],
                           working_directory=tempfile.gettempdir(), description="Example & test", user=user)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "task.xml"
            path.write_bytes(text.encode("utf-16"))
            made = subprocess.run(["schtasks", "/Create", "/TN", task, "/XML", str(path), "/F"], capture_output=True, text=True)
        self.assertEqual(made.returncode, 0, made.stdout + made.stderr)
        try:
            back = subprocess.run(["schtasks", "/Query", "/TN", task, "/XML"], capture_output=True, text=True, check=True).stdout
            for fragment in ("<Interval>PT1M</Interval>", "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>", "<LogonType>InteractiveToken</LogonType>"):
                self.assertIn(fragment, back)
        finally:
            subprocess.run(["schtasks", "/Delete", "/TN", task, "/F"], capture_output=True, text=True)


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


SUP = __import__("json").loads((Path(__file__).resolve().parent / "fixtures/contract/supervisor-vectors.json").read_text(encoding="utf-8"))


def lock_outcome_findings(record):
    """FAC-SEM-078 (the contract's lockOutcomeRules, ported for this test): the instance paths a record of a start
    against a held lock breaks."""
    out = []
    marker = fs.supervisor_marker(record["start"].get("env", {}), record["start"].get("argv", []))
    side = record.get("sideEffects")
    if side is not None and not isinstance(side, list):
        out.append("/sideEffects")
    out += ["/sideEffects/%d" % i for i, _ in enumerate(side if isinstance(side, list) else [])]
    count = lambda v, integer: isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 and (not integer or float(v).is_integer())  # noqa: E731
    attempts_ok, waited_ok = count(record.get("attempts"), True), count(record.get("waitedMs"), False)
    if not attempts_ok:
        out.append("/attempts")
    if not waited_ok:
        out.append("/waitedMs")
    attempts, waited = record.get("attempts"), record.get("waitedMs")
    if marker["kind"] == "conflict":
        if attempts_ok and attempts != 0:
            out.append("/attempts")
        if waited_ok and waited != 0:
            out.append("/waitedMs")
    elif marker["kind"] == "manual":
        if attempts_ok and attempts != 1:
            out.append("/attempts")
        if waited_ok and waited != 0:
            out.append("/waitedMs")
    else:
        if attempts_ok and attempts < 1:
            out.append("/attempts")
        if waited_ok and waited > SUP["lockWaitMaxMs"]:
            out.append("/waitedMs")
    outcome = record.get("outcome")
    if not isinstance(outcome, dict):
        return out + ["/outcome"]
    if outcome.get("acquired") is True:
        return out + (["/outcome/acquired"] if marker["kind"] == "conflict" else [])
    if outcome.get("exitStatus") != SUP["exitStatus"]:
        out.append("/outcome/exitStatus")
    message = outcome.get("message") if isinstance(outcome.get("message"), str) else ""
    if marker["kind"] == "conflict":
        names = {"environment": fs.SUPERVISOR_ENV, "argument": fs.SUPERVISOR_ARG}
        if not all(names[f] in message for f in marker["forms"]):
            out.append("/outcome/message")
    elif record.get("holderPid") is None:
        if not __import__("re").search(r"\bunknown\b", message, __import__("re").I):
            out.append("/outcome/message")
    elif not __import__("re").search(r"(?<!\d)%d(?!\d)" % record["holderPid"], message):
        out.append("/outcome/message")
    return out


class SupervisorMarker(unittest.TestCase):
    """DEC-0057 (CT-01, FAA-32): the marker in both forms, held to the contract's service-supervisor.json; what a copy
    does against a held lock, recorded and read as FAC-SEM-078 reads it; the writers and the sample's parser."""

    def test_every_marker_case_answers_as_the_contract_does(self):
        self.assertEqual(len(SUP["cases"]), 22)
        self.assertEqual(list(fs.SUPERVISORS), SUP["managers"])
        for case in SUP["cases"]:
            with self.subTest(case["name"]):
                marker = fs.supervisor_marker(case["env"], case["argv"])
                got = {"kind": marker["kind"], **({"manager": marker["manager"]} if marker["kind"] == "supervised" else {})}
                self.assertEqual(got, case["marker"])
                self.assertEqual(fs.lock_wait_budget_seconds(marker) * 1000, case["waitBudgetMs"])

    def test_the_rule_port_reads_the_contracts_records_as_it_does(self):
        self.assertEqual(len(SUP["lockRecords"]), 11)
        for item in SUP["lockRecords"]:
            with self.subTest(item["name"]):
                self.assertEqual(lock_outcome_findings(item["record"]), item["codes"])

    def start(self, env, argv, *, holder_pid_known=True):
        """One start against a held lock, recorded as FAC-SEM-078 reads it."""
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            holder = fs.InstanceLock(data).acquire()
            if not holder_pid_known:
                (data / "service.lock").write_text("")
            before = sorted(p.name for p in data.iterdir())
            attempts, now = [0], [0.0]
            real = fs.InstanceLock.acquire

            def counting(self_):
                attempts[0] += 1
                return real(self_)

            def sleep(seconds):
                now[0] += seconds

            err = __import__("io").StringIO()
            outcome = {}
            try:
                with mock.patch.object(fs.InstanceLock, "acquire", counting), mock.patch("sys.stderr", err):
                    fs.hold_single_instance(data, sleep=sleep, clock=lambda: now[0], env=env, argv=argv).release()
                outcome = {"acquired": True}
            except SystemExit as exc:
                outcome = {"exitStatus": exc.code, "message": err.getvalue().strip().splitlines()[-1]}
            finally:
                holder.release()
            after = sorted(p.name for p in data.iterdir())
            return {"start": {"env": env, "argv": argv}, "holderPid": os.getpid() if holder_pid_known else None,
                    "attempts": attempts[0], "waitedMs": now[0] * 1000,
                    "sideEffects": [name for name in after if name not in before], "outcome": outcome}

    def test_the_kits_starts_against_a_held_lock_conform(self):
        exe = "/opt/example-agent/bin/example-agent"
        starts = {
            "by hand": ({}, [exe, "serve"], True),
            "the node, by the variable": ({fs.SUPERVISOR_ENV: "node"}, [exe, "serve"], True),
            "a task, by the argument": ({}, [exe, "serve", "--fabric-supervisor", "task-scheduler"], True),
            "the holder unknown": ({}, [exe, "serve"], False),
            "markers that disagree": ({fs.SUPERVISOR_ENV: "launchd"}, [exe, "--fabric-supervisor=task-scheduler"], True),
            "two arguments that disagree": ({}, [exe, "--fabric-supervisor", "systemd", "--fabric-supervisor=node"], True),
            "a bare argument beside the variable": ({fs.SUPERVISOR_ENV: "systemd"}, [exe, "--fabric-supervisor", "--verbose"], True),
        }
        for name, (env, argv, known) in starts.items():
            with self.subTest(name):
                record = self.start(env, argv, holder_pid_known=known)
                self.assertEqual(lock_outcome_findings(record), [], record)
                self.assertEqual(record["outcome"].get("exitStatus"), 75)
                marker = fs.supervisor_marker(env, argv)["kind"]
                self.assertEqual(record["attempts"], {"conflict": 0, "manual": 1}.get(marker, record["attempts"]))
                if marker == "supervised":
                    self.assertEqual(record["waitedMs"], fs.LOCK_WAIT_SUPERVISED_SECONDS * 1000)
                    self.assertGreater(record["attempts"], 1)

    def test_writers_carry_the_marker_and_refuse_one_passed_in(self):
        text = fs.task_xml("\\PassionCode\\x", [r"C:\x.exe", "serve", "--", "--fabric-supervisor", "systemd"],
                           working_directory=r"C:\w", user="H\\u")
        args = ET.fromstring(text.split("\n", 1)[1]).find("t:Actions/t:Exec/t:Arguments", NS).text
        self.assertEqual(args, "serve --fabric-supervisor task-scheduler -- --fabric-supervisor systemd", "before any --")
        self.assertEqual(fs.supervisor_marker({}, [r"C:\x.exe"] + args.split())["manager"], "task-scheduler")
        for writer in (lambda argv: fs.task_xml("\\PassionCode\\x", [r"C:\x.exe"] + argv, working_directory=r"C:\w", user="H\\u"),
                       lambda argv: fs.systemd_unit("x.service", ["/bin/x"] + argv, working_directory=Path("/w")),
                       lambda argv: fs.launchd_plist("ai.x", ["/bin/x"] + argv, working_directory=Path("/w"), stdout_path=Path("/w/o"))):
            for argv in (["--fabric-supervisor", "node"], ["--fabric-supervisor=launchd"], ["--fabric-supervisor"]):
                with self.subTest(argv=argv), self.assertRaises(fs.ServiceError):
                    writer(argv)
        unit = fs.systemd_unit("x.service", ["/bin/x"], working_directory=Path("/w"), environment={fs.SUPERVISOR_ENV: "launchd"})
        self.assertIn("Environment=%s=systemd" % fs.SUPERVISOR_ENV, unit.replace('"', ""))
        self.assertNotIn("launchd", unit, "the unit's writer assigns the marker unconditionally")

    def test_the_samples_parser_accepts_the_marker_in_both_spellings(self):
        sample = load("sample_service")
        parser = sample.build_parser()
        for argv in (["--fabric-supervisor", "node", "serve"], ["--fabric-supervisor=node", "serve"],
                     ["serve", "--fabric-supervisor", "task-scheduler"], ["serve", "--fabric-supervisor=systemd"],
                     ["serve", "--fabric-supervisor"]):  # bare only at the end, before -- or another --flag, as the contract reads it
            with self.subTest(argv=argv):
                args = parser.parse_args(argv + ["--port", "1", "--data-dir", "/tmp/x"])
                self.assertEqual(args.command, "serve")


class DescriptorHygiene(unittest.TestCase):
    """DEC-0057 item 5: one supervisor per descriptor, and a share in either slash is never local; the contract's seven
    killing fixtures (descriptor-negatives.json), each refused for its own reason."""
    REASONS = {'bad-task': 'lifecycle.task must match', 'bad-unit': 'lifecycle.unit must match', 'systemd-with-plist': 'plist belongs to launchd', 'task-scheduler-with-label': 'label belongs to launchd', 'task-without-task-scheduler': 'lifecycle.task belongs to', 'unc-forward-slash': 'never a network share', 'windows-service-manager': 'lifecycle.manager must be'}

    def test_every_killing_fixture_is_refused_for_its_reason(self):
        negatives = __import__("json").loads((Path(__file__).resolve().parent / "fixtures/contract/descriptor-negatives.json").read_text(encoding="utf-8"))["negatives"]
        self.assertEqual(sorted(n["name"] for n in negatives), sorted(self.REASONS))
        for item in negatives:
            with self.subTest(item["name"]):
                self.assertIn(self.REASONS[item["name"]], " ".join(fs.validate_descriptor(item["descriptor"])))

    def test_local_paths(self):
        for path, ok in (("/a", True), ("~/a", True), ("~\\a", True), ("C:/a", True), ("C:\\a", True), ("//srv/a", False),
                         ("/\\srv", False), ("\\\\srv\\a", False), ("a", False)):
            with self.subTest(path=path):
                self.assertEqual(bool(fs._LOCAL_PATH.match(path)), ok)


if __name__ == "__main__":
    unittest.main()
