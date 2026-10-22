"""dashboard_kit.py notice (FAA-69): the SessionStart hook asks first whether the repository owns a service and
returns quietly when it owns none, and every git call and the tree walk share one deadline under the hook's 5 s."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
SCRIPT = SCRIPTS / "dashboard_kit.py"
REAL_GIT = shutil.which("git")

spec = importlib.util.spec_from_file_location("dashboard_kit_notice_under_test", SCRIPT)
dk = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SCRIPTS))
spec.loader.exec_module(dk)

# A git that writes each subcommand to GIT_LOG; GIT_SLOW lists the subcommands that sleep GIT_SLEEP seconds first.
FAKE_GIT = """#!/bin/sh
sub="$3"
printf '%%s\\n' "$sub" >> "$GIT_LOG"
case " $GIT_SLOW " in *" $sub "*) sleep "$GIT_SLEEP";; esac
exec %s "$@"
"""


@unittest.skipIf(sys.platform == "win32" or not REAL_GIT, "a POSIX shell git wrapper")
class Notice(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="dashboard-notice-"))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.repo = self.base / "repo"
        (self.repo / "web").mkdir(parents=True)
        subprocess.run([REAL_GIT, "-C", str(self.repo), "init", "-q"], check=True)
        subprocess.run([REAL_GIT, "-C", str(self.repo), "config", "remote.origin.url",
                        "git@github.com:example/example-agent.git"], check=True)
        (self.repo / "web/fabric-dashboard.css").write_text("/* fabric-dashboard-kit@0.9.0 */\n")
        (self.repo / "server.py").write_text('SURFACES = {"dashboard": {"path": "/", "login": True}}\n')
        fake = self.base / "bin" / "git"
        fake.parent.mkdir()
        fake.write_text(FAKE_GIT % REAL_GIT)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        self.log = self.base / "git.log"
        self.services = self.base / "services"
        self.services.mkdir()
        # macOS assesses a new executable on its first run, which takes seconds on a loaded machine: not the notice's.
        subprocess.run([str(fake), "-C", str(self.repo), "--version"], capture_output=True, timeout=120,
                       env=dict(os.environ, GIT_LOG=str(self.base / "warm.log"), GIT_SLOW="", GIT_SLEEP="0"))

    def own(self):
        (self.services / "example-agent.default.json").write_text(json.dumps(
            {"protocol": "fabric-service/0.1", "id": "example-agent", "instance": "default",
             "source": {"repository": "https://github.com/example/example-agent"}}))

    def notice(self, slow="", sleep="0"):
        env = dict(os.environ, HOME=str(self.base), FABRIC_SERVICES_DIR=str(self.services), GIT_LOG=str(self.log),
                   GIT_SLOW=slow, GIT_SLEEP=sleep, PATH="%s:%s" % (self.base / "bin", os.environ.get("PATH", "")))
        started = time.monotonic()
        done = subprocess.run([sys.executable, str(SCRIPT), "notice"], input=json.dumps({"cwd": str(self.repo)}),
                              capture_output=True, text=True, env=env, timeout=30)
        return done, time.monotonic() - started

    def calls(self):
        return self.log.read_text().split() if self.log.exists() else []

    def test_a_repository_owning_no_service_is_asked_nothing_else(self):
        done, _ = self.notice()
        self.assertEqual((done.returncode, done.stdout), (0, ""))
        self.assertEqual(self.calls(), ["rev-parse", "config"], "no ls-files, no grep, no walk before the question")

    def test_a_repository_owning_a_service_still_hears_the_line(self):
        self.own()
        done, _ = self.notice()
        self.assertIn("example-agent.default (this repository) is built from fabric-dashboard-kit 0.9.0", done.stdout)

    def test_slow_git_calls_share_one_deadline_under_the_hooks_ceiling(self):
        self.own()
        done, elapsed = self.notice(slow="rev-parse config ls-files grep", sleep="1.9")
        self.assertEqual((done.returncode, done.stdout), (0, ""), "out of time: nothing half-measured is said")
        self.assertLess(elapsed, 5.0, "the hook's timeout in hooks.json is 5 s")

    def test_the_walk_stops_at_the_deadline(self):
        for n in range(50):
            (self.repo / ("d%d" % n)).mkdir()
        with self.assertRaises(dk.OutOfTime):
            dk.find_copies(self.repo, until=time.monotonic() - 1)


if __name__ == "__main__":
    unittest.main()
