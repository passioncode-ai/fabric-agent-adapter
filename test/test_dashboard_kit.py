"""The dashboard kit (fabric-dashboard/0.1, contract DEC-0036): themes and their contrast, the kit
manifest, the ED-9 declaration in both kits and in the probe, and dashboard_kit.py's commands and
SessionStart notice."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services"
SCRIPTS = SKILL / "scripts"
KIT = SKILL / "assets/dashboard-kit"
HOOKS = ROOT / "plugins/fabric-agent-adapter/hooks/hooks.json"
KEY = "https://fabric.passioncode.ai/agent-contract/extensions/dashboard/0.1"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(module)
    return module


fs = load("fabric_service")
dk = load("dashboard_kit")
cs = load("check_service")


def luminance(hex_colour):
    h = hex_colour.lstrip("#")
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    channels = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# WCAG 2.2 AA (ED-10): body and muted text 4.5:1 on every surface, the accent as link text on a panel
# 4.5:1, text on the accent 4.5:1, status words in ink on their tints 4.5:1; borders that carry
# meaning, focus rings and status dots 3:1 against the surfaces they sit on.
PAIRS = ([(f, b, 4.5) for f in ("ink", "muted") for b in ("bg", "panel", "panel-2")]
         + [("accent", "panel", 4.5), ("accent", "bg", 3.0), ("accent", "panel-2", 3.0), ("accent-ink", "accent", 4.5)]
         + [("edge", b, 3.0) for b in ("bg", "panel", "panel-2")]
         + [(s, b, 3.0) for s in ("ok", "warn", "danger", "info") for b in ("bg", "panel")]
         + [("ink", s + "-weak", 4.5) for s in ("ok", "warn", "danger", "info", "accent")])

# SHELEG Design `workbench` (styles/tokens/workbench.css): graphite is it verbatim, plus `edge`.
WORKBENCH_LIGHT = {"bg": "#f7f8fa", "panel": "#ffffff", "panel-2": "#f7f8fa", "ink": "#1a1f2b", "muted": "#5b6472",
                   "border": "#e6e9ef", "border-strong": "#d7dce4", "accent": "#2f6feb", "accent-weak": "#eaf0fe",
                   "accent-ink": "#ffffff", "ok": "#1a7f37", "ok-weak": "#e6f4ea", "warn": "#9a6700", "warn-weak": "#fff3d6",
                   "danger": "#d1242f", "danger-weak": "#fde8e9", "info": "#2f6feb", "info-weak": "#eaf0fe"}
WORKBENCH_DARK = {"bg": "#0f1218", "panel": "#161b24", "panel-2": "#1b212c", "ink": "#e8ecf3", "muted": "#8a93a6",
                  "border": "#232a36", "border-strong": "#2c3441", "accent": "#4b8bff", "accent-weak": "#1b2740",
                  "accent-ink": "#0f1218", "ok": "#3fb960", "ok-weak": "#12281a", "warn": "#d9a93f", "warn-weak": "#2b2210",
                  "danger": "#e5534b", "danger-weak": "#2d1517", "info": "#4b8bff", "info-weak": "#1b2740"}


class Themes(unittest.TestCase):
    def setUp(self):
        self.themes = json.loads((KIT / "themes.json").read_text(encoding="utf-8"))

    def test_the_reference_set_in_both_schemes(self):
        self.assertEqual(list(self.themes["themes"]), list(fs.REFERENCE_THEMES))
        self.assertEqual(self.themes["default"], "graphite")
        for theme_id, theme in self.themes["themes"].items():
            for scheme in ("light", "dark"):
                self.assertEqual(set(theme[scheme]), set(dk.TOKEN_ORDER), "%s/%s" % (theme_id, scheme))
                for token, value in theme[scheme].items():
                    self.assertRegex(value, r"^#[0-9a-f]{6}$", "%s/%s %s" % (theme_id, scheme, token))

    def test_every_theme_meets_aa(self):
        failures = []
        for theme_id, theme in self.themes["themes"].items():
            for scheme in ("light", "dark"):
                p = theme[scheme]
                for fg, bg, floor in PAIRS:
                    ratio = contrast(p[fg], p[bg])
                    if ratio < floor:
                        failures.append("%s/%s %s on %s %.2f < %.1f" % (theme_id, scheme, fg, bg, ratio, floor))
        self.assertEqual(failures, [])

    def test_the_contrast_check_fails_a_planted_low_contrast_muted(self):
        p = dict(self.themes["themes"]["graphite"]["light"], muted="#9aa1ab")
        self.assertLess(contrast(p["muted"], p["panel-2"]), 4.5)

    def test_graphite_is_workbench_verbatim(self):
        graphite = self.themes["themes"]["graphite"]
        self.assertEqual({k: v for k, v in graphite["light"].items() if k != "edge"}, WORKBENCH_LIGHT)
        self.assertEqual({k: v for k, v in graphite["dark"].items() if k != "edge"}, WORKBENCH_DARK)

    def test_css_and_js_are_built_from_themes_json(self):
        self.assertEqual(dk.build(check=True), [], "run dashboard_kit.py build")

    def test_build_writes_every_theme_rule(self):
        css = dk.theme_css(self.themes)
        for theme_id in fs.REFERENCE_THEMES:
            if theme_id == "graphite":
                self.assertIn(':root, :root[data-theme="graphite"] {', css)
                self.assertIn(':root:not([data-scheme="light"]) {', css)
            else:
                self.assertIn(':root[data-theme="%s"] {' % theme_id, css)
                self.assertIn(':root[data-theme="%s"][data-scheme="dark"] {' % theme_id, css)
                self.assertIn(':root[data-theme="%s"]:not([data-scheme="light"]) {' % theme_id, css)

    def test_a_missing_token_is_refused(self):
        broken = json.loads(json.dumps(self.themes))
        del broken["themes"]["ocean"]["dark"]["edge"]
        with self.assertRaises(dk.KitError):
            dk.theme_css(broken)


class KitFiles(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((KIT / "kit.json").read_text(encoding="utf-8"))
        self.css = (KIT / "fabric-dashboard.css").read_text(encoding="utf-8")
        self.js = (KIT / "fabric-dashboard.js").read_text(encoding="utf-8")

    def test_manifest_names_the_files_and_versions(self):
        self.assertEqual(self.manifest["name"], "fabric-dashboard-kit")
        self.assertEqual(self.manifest["declarationKey"], KEY)
        self.assertEqual("%s@%s" % (self.manifest["name"], self.manifest["version"]), fs.DASHBOARD_KIT)
        for name, digest in self.manifest["files"].items():
            self.assertEqual(hashlib.sha256((KIT / name).read_bytes()).hexdigest(), digest, name)
        self.assertEqual(self.manifest["history"][self.manifest["version"]],
                         {n: self.manifest["files"][n] for n in dk.COPIED})
        for text in (self.css, self.js):
            self.assertEqual(dk.claimed_version_text(text), self.manifest["version"])

    def test_both_kits_name_the_same_kit_and_themes(self):
        mjs = (SCRIPTS / "fabric-service.mjs").read_text(encoding="utf-8")
        self.assertIn("export const DASHBOARD_KIT = '%s';" % fs.DASHBOARD_KIT, mjs)
        self.assertIn("export const REFERENCE_THEMES = %s;" % json.dumps(list(fs.REFERENCE_THEMES)).replace('"', "'"), mjs)
        self.assertEqual(self.manifest["themes"], list(fs.REFERENCE_THEMES))

    def test_css_holds_the_floor_and_the_chrome_budget(self):
        self.assertIn("--fd-floor: 360px;", self.css)
        self.assertIn("html { min-width: var(--fd-floor);", self.css)          # ED-2
        self.assertIn("--fd-chrome-max: 120px;", self.css)                     # ED-5
        self.assertIn("scroll-margin-top: calc(var(--fd-chrome-h)", self.css)  # ED-5 anchors
        self.assertIn("minmax(min(100%, var(--fd-col)), 1fr)", self.css)       # no column below the viewport
        self.assertIn("html[data-fd-host-appearance] [data-fd-appearance-control] { display: none !important; }", self.css)  # ED-6

    def test_css_colours_come_from_tokens(self):
        outside = self.css.replace(self.css[self.css.index(dk.CSS_BEGIN):self.css.index(dk.CSS_END)], "")
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", outside), [])
        self.assertNotIn("@import", self.css)
        self.assertNotRegex(self.css, r"url\(\s*['\"]?https?:")

    def test_js_is_csp_clean(self):
        for banned in ("eval(", "new Function", "innerHTML", "document.write", "http://", "https://"):
            self.assertNotIn(banned, self.js)

    def test_demo_has_no_inline_script_or_style(self):
        demo = (KIT / "demo.html").read_text(encoding="utf-8")
        self.assertNotRegex(demo, r"<script(?![^>]*\bsrc=)")
        self.assertNotIn("style=", demo)
        self.assertNotIn("<style", demo)


class Declaration(unittest.TestCase):
    def test_the_helper_builds_a_valid_value(self):
        value = fs.dashboard_extension()[KEY]
        self.assertEqual(value, {"minWidth": 360, "appearance": ["scheme", "theme"], "themes": list(fs.REFERENCE_THEMES),
                                 "kit": fs.DASHBOARD_KIT})
        self.assertEqual(fs.dashboard_extension_problems(value), [])
        self.assertEqual(fs.dashboard_extension(min_width=480, appearance=(), themes=None, kit=None), {KEY: {"minWidth": 480}})

    def test_invalid_values_are_named(self):
        cases = [
            ({"minWidth": 359}, "outside"),
            ({"minWidth": 1281}, "outside"),
            ({"minWidth": 360.5}, "whole number"),
            ({"minWidth": True}, "whole number"),
            ({}, "required"),
            ({"minWidth": 360, "appearance": ["colour"]}, "appearance"),
            ({"minWidth": 360, "appearance": ["scheme", "scheme"]}, "appearance"),
            ({"minWidth": 360, "themes": []}, "themes"),
            ({"minWidth": 360, "themes": ["Ocean"]}, "themes"),
            ({"minWidth": 360, "kit": "fabric-dashboard-kit"}, "kit"),
            ({"minWidth": 360, "accent": "#fff"}, "unknown field"),
            ([], "not an object"),
        ]
        for value, needle in cases:
            problems = fs.dashboard_extension_problems(value)
            self.assertTrue(any(needle in p for p in problems), "%r → %r" % (value, problems))
        with self.assertRaises(fs.ServiceError):
            fs.dashboard_extension(min_width=200)

    def test_build_well_known_keeps_extensions_and_refuses_a_bad_declaration(self):
        base = dict(service_id="example-agent", instance="default", name="Example", version="1.0.0", build={"commit": "abc1234"},
                    started_at="2026-10-11T09:00:00Z", status="ready", degraded=[],
                    surfaces={"events": {"path": "/fabric/v1/events"}, "dashboard": {"path": "/", "login": True}})
        self.assertNotIn("extensions", fs.build_well_known(**base))
        doc = fs.build_well_known(extensions=fs.dashboard_extension(), **base)
        self.assertEqual(doc["extensions"][KEY]["minWidth"], 360)
        with self.assertRaises(fs.ServiceError):
            fs.build_well_known(extensions={KEY: {"minWidth": 100}}, **base)

    @unittest.skipUnless(os.environ.get("FABRIC_CONTRACT_NEW"), "NOT_RUN: set FABRIC_CONTRACT_NEW to a contract checkout at the pin")
    def test_the_contract_fixtures_agree(self):
        contract = Path(os.environ["FABRIC_CONTRACT_NEW"])
        positive = json.loads((contract / "fixtures/positive/service-dashboard-extension.json").read_text())
        self.assertEqual(fs.dashboard_extension_problems(positive), [])
        self.assertEqual(positive, fs.dashboard_extension()[KEY])
        minimal = contract / "fixtures/positive/service-dashboard-extension-minimal.json"
        if minimal.exists():
            self.assertEqual(fs.dashboard_extension_problems(json.loads(minimal.read_text())), [])
        well_known = json.loads((contract / "fixtures/positive/service-well-known-dashboard.json").read_text())
        self.assertEqual(fs.dashboard_extension_problems(well_known["extensions"][KEY]), [])
        negatives = sorted((contract / "fixtures/negative").glob("service-dashboard-extension-*.json"))
        self.assertTrue(negatives)
        for path in negatives:
            self.assertNotEqual(fs.dashboard_extension_problems(json.loads(path.read_text())), [], path.name)


class DeclaredRule(unittest.TestCase):
    def verdict(self, wk):
        probe = cs.Probe(Path("/nonexistent.json"), {"origin": "http://127.0.0.1:1"}, Path("/nonexistent"), True)
        probe.wk = wk
        probe.dashboard_rules()
        (result,) = probe.results
        self.assertEqual(result["rule"], "dashboard.declared")
        return result["verdict"], result["evidence"]

    def test_verdicts(self):
        self.assertEqual(self.verdict({"surfaces": {}})[0], "NOT_RUN")
        verdict, evidence = self.verdict({"surfaces": {"dashboard": {"path": "/"}}})
        self.assertEqual(verdict, "NOT_RUN")
        self.assertIn("legacy dashboard", evidence)
        verdict, evidence = self.verdict({"surfaces": {"dashboard": {"path": "/"}}, "extensions": fs.dashboard_extension(min_width=400)})
        self.assertEqual(verdict, "PASS")
        self.assertIn("host floor 480", evidence)
        verdict, evidence = self.verdict({"surfaces": {"dashboard": {"path": "/"}},
                                          "extensions": {KEY: {"minWidth": 360, "kit": "fabric-dashboard-kit@0.9.0"}}})
        self.assertEqual(verdict, "PASS")
        self.assertIn("is current", evidence)
        self.assertEqual(self.verdict({"surfaces": {"dashboard": {"path": "/"}}, "extensions": {KEY: {"minWidth": 200}}})[0], "FAIL")


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo)] + list(args), check=True, capture_output=True)


class Cli(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_kit(self, *args, stdin=None, env=None):
        return subprocess.run([sys.executable, str(SCRIPTS / "dashboard_kit.py")] + list(args), input=stdin,
                              capture_output=True, text=True, env=dict(os.environ, **(env or {})), timeout=30)

    def test_install_adds_then_keeps_then_refuses_a_changed_copy(self):
        target = self.base / "static"
        target.mkdir()
        first = self.run_kit("install", str(target))
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("added fabric-dashboard.css", first.stdout)
        self.assertIn(KEY, first.stdout)
        self.assertEqual((target / "fabric-dashboard.css").read_bytes(), (KIT / "fabric-dashboard.css").read_bytes())
        again = self.run_kit("install", str(target))
        self.assertIn("already", again.stdout)
        (target / "fabric-dashboard.css").write_text((KIT / "fabric-dashboard.css").read_text() + "\n.mine { color: red }\n")
        changed = (target / "fabric-dashboard.css").read_text()
        refused = self.run_kit("install", str(target))
        self.assertEqual(refused.returncode, 1)
        self.assertIn("changed after it was copied", refused.stderr)
        self.assertIn("Nothing was written", refused.stderr)
        self.assertEqual((target / "fabric-dashboard.css").read_text(), changed)
        forced = self.run_kit("install", str(target), "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertEqual((target / "fabric-dashboard.css").read_bytes(), (KIT / "fabric-dashboard.css").read_bytes())

    def test_install_replaces_an_untouched_older_copy_and_dry_run_writes_nothing(self):
        kit = self.base / "kit"
        shutil.copytree(KIT, kit)
        old = "/* fabric-dashboard-kit@0.9.0 */\n.old {}\n"
        manifest = json.loads((kit / "kit.json").read_text())
        manifest["history"]["0.9.0"] = {"fabric-dashboard.css": hashlib.sha256(old.encode()).hexdigest(),
                                        "fabric-dashboard.js": "0" * 64}
        (kit / "kit.json").write_text(json.dumps(manifest))
        target = self.base / "static"
        target.mkdir()
        (target / "fabric-dashboard.css").write_text(old)
        planned = dk.install(target, dry_run=True, kit_dir=kit)
        self.assertIn("would be replaced fabric-dashboard.css 0.9.0 with 1.0.0", planned)
        self.assertEqual((target / "fabric-dashboard.css").read_text(), old)
        self.assertFalse((target / "fabric-dashboard.js").exists())
        done = dk.install(target, kit_dir=kit)
        self.assertIn("replaced fabric-dashboard.css 0.9.0 with 1.0.0", done)
        self.assertEqual((target / "fabric-dashboard.css").read_bytes(), (kit / "fabric-dashboard.css").read_bytes())

    def test_install_refuses_an_unmarked_file(self):
        target = self.base / "static"
        target.mkdir()
        (target / "fabric-dashboard.js").write_text("console.log('mine')\n")
        with self.assertRaises(dk.KitError):
            dk.install(target)

    def make_repo(self, origin="git@github.com:example/example-agent.git"):
        repo = self.base / "repo"
        (repo / "web").mkdir(parents=True)
        git(repo, "init", "-q")
        git(repo, "config", "remote.origin.url", origin)
        return repo

    def test_status_names_each_copy_state(self):
        repo = self.make_repo()
        (repo / "web/fabric-dashboard.css").write_bytes((KIT / "fabric-dashboard.css").read_bytes())
        (repo / "web/fabric-dashboard.js").write_text("/* fabric-dashboard-kit@0.9.0 */\n")
        report = dk.status(repo, directory=self.base / "no-services")
        states = {Path(c["path"]).name: c["state"] for c in report["copies"]}
        self.assertEqual(states, {"fabric-dashboard.css": "current", "fabric-dashboard.js": "older"})
        (repo / "web/fabric-dashboard.css").write_text((KIT / "fabric-dashboard.css").read_text() + "/* local */\n")
        report = dk.status(repo, directory=self.base / "no-services")
        self.assertEqual({Path(c["path"]).name: c["state"] for c in report["copies"]}["fabric-dashboard.css"], "changed")

    def test_the_kit_source_is_not_a_copy(self):
        self.assertEqual(dk.status(ROOT, directory=self.base)["copies"], [])

    def services(self, origin):
        directory = self.base / "services"
        directory.mkdir(exist_ok=True)
        (directory / "example-agent.default.json").write_text(json.dumps(
            {"protocol": "fabric-service/0.1", "id": "example-agent", "instance": "default", "source": {"repository": origin}}))
        return directory

    def notice(self, cwd, services_dir):
        started = time.perf_counter()
        done = self.run_kit("notice", stdin=json.dumps({"hook_event_name": "SessionStart", "cwd": str(cwd)}),
                            env={"FABRIC_SERVICES_DIR": str(services_dir)})
        return done, time.perf_counter() - started

    def test_notice_for_an_older_copy_and_silence_when_current(self):
        repo = self.make_repo()
        (repo / "web/fabric-dashboard.css").write_text("/* fabric-dashboard-kit@0.9.0 */\n")
        done, elapsed = self.notice(repo, self.base / "none")
        self.assertEqual(done.returncode, 0)
        self.assertEqual(len(done.stdout.strip().splitlines()), 1)
        self.assertIn("fabric-dashboard-kit 0.9.0; 1.0.0 is current", done.stdout)
        self.assertIn("tell the operator", done.stdout)
        self.assertLess(elapsed, 2.0)
        (repo / "web/fabric-dashboard.css").write_bytes((KIT / "fabric-dashboard.css").read_bytes())
        done, _ = self.notice(repo, self.base / "none")
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_notice_for_a_service_with_a_dashboard_and_no_kit(self):
        repo = self.make_repo("https://github.com/example/example-agent")
        services = self.services("git@github.com:example/example-agent.git")
        done, _ = self.notice(repo, services)
        self.assertEqual(done.stdout, "", "no dashboard surface in the code yet: silent")
        (repo / "server.py").write_text('SURFACES = {"dashboard": {"path": "/", "login": True}}\n')
        done, _ = self.notice(repo, services)
        self.assertIn("example-agent.default has a dashboard without fabric-dashboard-kit", done.stdout)

    def test_notice_is_silent_outside_a_repository_and_on_bad_input(self):
        outside = self.base / "plain"
        outside.mkdir()
        for stdin in (json.dumps({"cwd": str(outside)}), "not json", ""):
            done = self.run_kit("notice", stdin=stdin, env={"FABRIC_SERVICES_DIR": str(self.base)})
            self.assertEqual(done.returncode, 0)
            if stdin.startswith("{"):
                self.assertEqual(done.stdout, "")
        done = self.run_kit("notice", stdin=json.dumps({"cwd": str(self.base / "missing")}))
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_the_plugin_hook_runs_the_notice(self):
        hooks = json.loads(HOOKS.read_text(encoding="utf-8"))
        (entry,) = hooks["hooks"]["SessionStart"]
        (hook,) = entry["hooks"]
        self.assertEqual(hook["type"], "command")
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/skills/building-fabric-services/scripts/dashboard_kit.py", hook["command"])
        self.assertTrue(hook["command"].endswith(" notice"))
        self.assertLessEqual(hook.get("timeout", 60), 10)

    def test_build_check_reports_drift(self):
        kit = self.base / "kit"
        shutil.copytree(KIT, kit)
        themes = json.loads((kit / "themes.json").read_text())
        themes["themes"]["ocean"]["light"]["accent"] = "#0b6e8b"
        (kit / "themes.json").write_text(json.dumps(themes))
        self.assertIn("fabric-dashboard.css", dk.build(kit, check=True))
        dk.build(kit)
        self.assertEqual(dk.build(kit, check=True), [])
        self.assertIn("#0b6e8b", (kit / "fabric-dashboard.css").read_text())


if __name__ == "__main__":
    unittest.main()
