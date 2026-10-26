"""check_service.py rule dashboard.opens-in-host (FAA-118, the operator rule of 2026-10-24, decision D13): a service's
checkout opens its own pages only through Fabric Dashboards, never with a browser opener. The matcher on its own
(true and false positives), the verdict over a real Git checkout, finding the checkout, and the live probe."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_probe_interop import SCRIPTS, LiveSample, load

rules = load("check_service_rules")
PORT = 47190
ORIGIN = "http://127.0.0.1:%d" % PORT


def found(path, text, port=PORT, origin=ORIGIN, dashboard_path="/dashboard"):
    return rules.opener_findings(path, text, port, origin, dashboard_path)


# A browser opener aimed at the service's own pages: each is a FAIL wherever the service keeps it.
TRUE_POSITIVES = [
    ("scripts/open-dashboard.sh", "#!/bin/sh\nopen -a Safari http://127.0.0.1:47190/\n"),
    ("bin/dash", 'open -a "Google Chrome" "http://localhost:47190/dashboard"\n'),
    ("bin/login", "open http://127.0.0.1:47190/fabric/v1/login?code=$CODE\n"),
    ("bin/bundle", "open -b com.apple.Safari http://127.0.0.1:47190/\n"),
    ("bin/linux", 'xdg-open "http://127.0.0.1:${PORT}/"\n'),
    ("bin/win.cmd", 'start "" "http://127.0.0.1:47190/"\n'),
    ("bin/win2.cmd", "cmd /c start http://localhost:47190\n"),
    ("agent/cli.py", 'import webbrowser\n\ndef show(port):\n    webbrowser.open("http://127.0.0.1:%d/" % port)\n'),
    ("agent/later.py", 'import webbrowser\nurl = "http://127.0.0.1:%d/" % port\nlog("opening")\nwebbrowser.open(url)\n'),
    ("agent/argv.py", 'subprocess.run(["open", "-a", "Safari", dashboard_url], check=True)\n'),
    ("agent/remote.py", 'webbrowser.open_new_tab("https://agent.example.com/dashboard")\n'),
    ("src/cli.mjs", 'import open from "open";\n\nawait open(`http://127.0.0.1:${port}/`);\n'),
    ("src/cli.cjs", "const browse = require('open');\nbrowse(dashboardUrl);\n"),
    ("src/spawn.mjs", 'execFile("xdg-open", ["http://localhost:47190/"]);\n'),
    ("src/exec.mjs", "exec(`open ${dashboardUrl}`);\n"),
    ("src/main.js", 'shell.openExternal("http://127.0.0.1:47190/");\n'),
    ("AGENTS.md", "## Dashboard\n\nOpen it with `open -a Safari http://127.0.0.1:47190/`.\n"),
    ("docs/run.md", "Start it, then:\n\n```sh\nopen -a Safari http://127.0.0.1:47190/\n```\n"),
    ("package.json", '{"scripts": {"dashboard": "open http://localhost:47190/"}}\n'),
    ("Makefile", "dashboard:\n\t@open http://localhost:47190/\n"),
    ("bin/up", "./serve --port 47190 && open -a Safari http://127.0.0.1:47190/\n"),
]

# What looks like an opener and is not one aimed at the service's pages: each reads as nothing.
FALSE_POSITIVES = [
    ("README.md", "Safari is the agent browser for web pages: test the public site in Safari first.\n"),
    ("AGENTS.md", "Never run `open -a Safari http://127.0.0.1:47190/`: open it through Fabric Dashboards.\n"),
    ("docs/dashboard.md", "Do not use `xdg-open http://127.0.0.1:47190/`; the host opens the page.\n"),
    ("test/test_open.py", 'webbrowser.open("http://127.0.0.1:47190/")\n'),
    ("tests/e2e.sh", "open -a Safari http://127.0.0.1:47190/\n"),
    ("src/ui.test.mjs", 'shell.openExternal("http://127.0.0.1:47190/");\n'),
    ("src/__tests__/open.js", 'shell.openExternal("http://127.0.0.1:47190/");\n'),
    ("fixtures/raw-open.sh", "open http://127.0.0.1:47190/\n"),
    ("agent/files.py", 'with open("http://127.0.0.1:47190/x.json") as f:\n    pass\nopen(log_path, "a")\n'),
    ("static/page.js", 'window.open("/dashboard");\ndocument.open("http://127.0.0.1:47190/")\n'),
    ("agent/host.py", 'subprocess.run(["open", open_link], check=True)\n'),
    ("bin/host", 'open "fabric-dashboards://service/example-agent.default?path=/dashboard"\n'),
    ("bin/host2", 'open -a "Fabric Dashboards" "fabric-dashboards://service/example-agent.default"\n'),
    ("agent/fallback.py", 'if host["state"] == "not_installed" and fallback == "if_absent":\n'
                          '    # a confirmed absence, the only browser exception\n'
                          '    webbrowser.open("http://127.0.0.1:47190/")\n'),
    ("agent/gate.py", "webbrowser.open(browser_link)  # check_dashboard_link.py allowed it\n"),
    ("agent/docs.py", 'webbrowser.open("https://docs.example.org/guide")\n'),
    ("bin/files", 'xdg-open "$REPORT_FILE"\n'),
    ("agent/old.py", "# open -a Safari http://127.0.0.1:47190/ was how it used to open\n"),
    ("src/old.mjs", "// shell.openExternal('http://127.0.0.1:47190/')\n"),
    ("bin/ports", "open http://127.0.0.1:471900/\n".replace("127.0.0.1", "192.0.2.1")),
    ("src/page.mjs", 'import open from "open";\nconst file = fs.open(path);\n'),
    # Prose that tells a person what to open, a report quoting a finding, the host's own app.
    ("README.md", "Run `npm run dev`, then open `http://localhost:47190` and sign in.\n"),
    ("docs/obs.md", "```sh\ncurl -s http://localhost:9090/ready\n# every job up; then open https://obs.example.org\n```\n"),
    ("docs/survey.json", '{"finding": "server.py:4951 open_dashboard uses webbrowser.open (system default)"}\n'),
    ("src/cli.ts", 'const installed = (await exec("open", ["-Ra", "Fabric Dashboards"])).code === 0;\n'),
    # A message that names an address for a person, another tool's own `open` subcommand, two code spans in a sentence.
    ("start.sh", 'echo "Run ./stop.sh first, or open http://localhost:47190"\n'),
    ("Makefile", '\t@echo "dev up: open http://localhost:47190 and use the dev sign-in"\n'),
    ("agent/hint.py", 'print("Open http://127.0.0.1:47190/ in Fabric Dashboards"); log("then open http://localhost:47190")\n'),
    ("docs/browse.md", "Run `playwright-cli open http://localhost:47190/checkout` to see it.\n"),
    ("docs/brief.md", '| 10 | proxy | `agent-browser --proxy "http://127.0.0.1:9" open https://example.com` | refused |\n'),
    ("docs/scenarios.md", "The operator runs `publisher service start`; it prints the address `http://127.0.0.1:47190`.\n"),
]


class MatcherTests(unittest.TestCase):
    def test_every_opener_aimed_at_the_service_is_found(self):
        for path, text in TRUE_POSITIVES:
            origin = "https://agent.example.com" if "remote" in path else ORIGIN
            hits = found(path, text, origin=origin)
            self.assertTrue(hits, "%s should be found:\n%s" % (path, text))
            line, snippet = hits[0]
            self.assertIsInstance(line, int)
            self.assertIn(snippet.strip(), text)

    def test_mentions_tests_comments_the_host_route_and_the_fallback_are_not(self):
        for path, text in FALSE_POSITIVES:
            self.assertEqual(found(path, text), [], "%s should not be found:\n%s" % (path, text))

    def test_the_line_named_is_the_openers(self):
        hits = found("agent/later.py", 'import webbrowser\nurl = "http://127.0.0.1:%d/" % port\nlog("opening")\nwebbrowser.open(url)\n')
        self.assertEqual([h[0] for h in hits], [4])

    def test_a_target_further_back_than_the_window_is_not_an_aim(self):
        text = 'url = "http://127.0.0.1:47190/"\n' + "pass\n" * 10 + "webbrowser.open(url)\n"
        self.assertEqual(found("agent/far.py", text), [])

    def test_a_loopback_url_of_another_port_is_another_tool(self):
        # Seam reading of 0.50.0: a local Storybook or docs server is not this service's page.
        self.assertEqual(found("scripts/storybook.sh", "open http://localhost:6006\n"), [])
        self.assertEqual(found("Makefile", "\t@open http://127.0.0.1:4000/docs\n"), [])
        self.assertEqual(len(found("bin/x", "open http://localhost:%d/\n" % PORT)), 1)
        self.assertEqual(len(found("bin/x", "open http://localhost/dashboard\n")), 1, "no port: may be the service")

    def test_the_root_dashboard_path_alone_is_no_aim(self):
        self.assertEqual(found("bin/x", "open https://example.org/\n", dashboard_path="/"), [])

    def test_odd_input_reads_as_nothing(self):
        self.assertEqual(rules.opener_findings("x.py", "", 0, "", ""), [])
        self.assertEqual(rules.opener_findings("x.py", "open -a Safari http://127.0.0.1:1/\n", 0, None, None)[0][0], 1)


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class VerdictTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "example-agent"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "agent@example.com")
        git(self.repo, "config", "user.name", "Example")
        (self.repo / "README.md").write_text("Safari is the agent browser for web pages.\n")
        (self.repo / "agent.py").write_text('subprocess.run(["open", open_link], check=True)\n')

    def tearDown(self):
        self.temp.cleanup()

    def commit(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text) if isinstance(text, bytes) else path.write_text(text)
        git(self.repo, "add", name)
        git(self.repo, "commit", "-q", "-m", "add %s" % name)

    def verdict(self, **kw):
        return rules.opens_in_host_verdict(self.repo, PORT, ORIGIN, "/dashboard", **kw)

    def test_a_checkout_that_opens_through_the_host_passes(self):
        self.commit("bin/open", 'open "fabric-dashboards://service/example-agent.default?path=/dashboard"\n')
        verdict, evidence = self.verdict()
        self.assertEqual(verdict, "PASS", evidence)
        self.assertIn("Fabric Dashboards", evidence)

    def test_a_tracked_browser_opener_fails_with_its_place(self):
        self.commit("scripts/open-dashboard.sh", "#!/bin/sh\nopen -a Safari http://127.0.0.1:47190/\n")
        verdict, evidence = self.verdict()
        self.assertEqual(verdict, "FAIL")
        self.assertIn("scripts/open-dashboard.sh:2", evidence)
        self.assertIn("fallback=never", evidence)

    def test_only_tracked_text_is_read(self):
        (self.repo / "local.sh").write_text("open -a Safari http://127.0.0.1:47190/\n")  # untracked
        self.commit("blob.bin", b"\x00\x01open -a Safari http://127.0.0.1:47190/\n")  # binary
        verdict, evidence = self.verdict()
        self.assertEqual(verdict, "PASS", evidence)

    def test_a_folder_that_is_not_a_checkout_is_not_run(self):
        verdict, evidence = rules.opens_in_host_verdict(Path(self.temp.name), PORT, ORIGIN, "/dashboard")
        self.assertEqual(verdict, "NOT_RUN")
        self.assertIn("not a Git checkout", evidence)

    def test_a_spent_budget_is_not_run(self):
        self.commit("scripts/open-dashboard.sh", "open -a Safari http://127.0.0.1:47190/\n")
        verdict, evidence = self.verdict(budget=0)
        self.assertEqual(verdict, "NOT_RUN")
        self.assertIn("budget", evidence)


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class CheckoutTests(unittest.TestCase):
    SOURCE = "https://github.com/example/example-agent"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "example-agent"
        (self.repo / "bin").mkdir(parents=True)
        git(self.repo, "init", "-q")
        git(self.repo, "remote", "add", "origin", "git@github.com:example/example-agent.git")

    def tearDown(self):
        self.temp.cleanup()

    def test_an_explicit_checkout_is_its_root(self):
        path, why = rules.service_checkout({}, str(self.repo / "bin"))
        self.assertEqual(path.resolve(), self.repo.resolve(), why)
        path, why = rules.service_checkout({}, self.temp.name)
        self.assertIsNone(path)
        self.assertIn("--repo", why)

    def test_a_command_inside_the_named_source_finds_it(self):
        d = {"source": {"repository": self.SOURCE}, "commands": {"doctor": [str(self.repo / "bin/doctor"), "--json"]}}
        path, why = rules.service_checkout(d, None)
        self.assertEqual(path.resolve(), self.repo.resolve(), why)

    def test_the_manifest_inside_the_named_source_finds_it(self):
        d = {"source": {"repository": self.SOURCE}, "fabricManifest": str(self.repo / "fabric-agent.json")}
        path, why = rules.service_checkout(d, None)
        self.assertEqual(path.resolve(), self.repo.resolve(), why)

    def test_a_checkout_of_another_repository_is_not_the_service(self):
        d = {"source": {"repository": "https://github.com/example/other"}, "commands": {"doctor": [str(self.repo / "bin/doctor")]}}
        path, why = rules.service_checkout(d, None)
        self.assertIsNone(path)
        self.assertIn("--repo", why)

    def test_no_source_names_no_checkout(self):
        path, why = rules.service_checkout({"commands": {"doctor": [str(self.repo / "bin/doctor")]}}, None)
        self.assertIsNone(path)
        self.assertIn("source.repository", why)
        self.assertIsNone(rules.service_checkout({"source": "x", "commands": "y", "fabricManifest": 3}, None)[0])


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class LiveOpensInHostTests(LiveSample):
    """The sample service, probed with --repo pointing at a checkout built here."""

    def checkout(self, files):
        repo = Path(self.temp.name) / "checkout"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "agent@example.com")
        git(repo, "config", "user.name", "Example")
        for name, text in files.items():
            (repo / name).write_text(text)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "files")
        return repo

    def probe(self, *extra):
        out = subprocess.run([sys.executable, str(SCRIPTS / "check_service.py"), "sample", "--services-dir",
                              str(self.services), "--json", *extra], capture_output=True, text=True)
        return {r["rule"]: r for r in json.loads(out.stdout)["results"]}["dashboard.opens-in-host"]

    def test_no_checkout_is_not_run(self):
        result = self.probe()
        self.assertEqual(result["verdict"], "NOT_RUN")
        self.assertIn("source.repository", result["evidence"])

    def test_a_raw_safari_open_fails_and_the_hosts_link_passes(self):
        bad = self.checkout({"open.sh": "open -a Safari http://127.0.0.1:%d/\n" % self.port})
        result = self.probe("--repo", str(bad))
        self.assertEqual(result["verdict"], "FAIL", result)
        self.assertIn("open.sh:1", result["evidence"])
        shutil.rmtree(bad)
        good = self.checkout({"open.sh": 'open "fabric-dashboards://service/sample.default?path=/"\n'})
        self.assertEqual(self.probe("--repo", str(good))["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
