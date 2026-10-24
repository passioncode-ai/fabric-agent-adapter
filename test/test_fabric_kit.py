"""FAA-65: the service kit is a manifest-listed set of layered modules, and that set installs and runs on its own.

- kit.json is what the sources say (`fabric_kit.py build --check`), lists every library module, and its order is a
  layering: a module imports only modules listed before it, so the kit has no import cycle and no upward import.
- The shared core (JS values, time, crypto) is defined once, in its home module, in both languages.
- No kit module grows past MAX_LINES; OVERSIZE names the ones still being split and only shrinks.
- `fabric_kit.py install` copies a closure that runs in a clean interpreter with nothing else on its path, and
  `status` tells a current copy from an older release, an edited one, and a one-file copy that is missing modules.
"""
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
KIT = json.loads((SCRIPTS / "kit.json").read_text(encoding="utf-8"))
from test_fabric_service import load  # noqa: E402

fabric_kit = load("fabric_kit")

MAX_LINES = 1000
#: Modules over MAX_LINES. FAA-65 split every one; an entry may only be added with a backlog row that splits it.
OVERSIZE = set()
#: Scripts beside the kit that are programs or tools, not library modules a service copies.
NOT_KIT = {"check_service.py", "check_service_rules.py", "sample_service.py", "dashboard_kit.py", "check_dashboard_link.py", "fabric_kit.py",
           "sample-remote-service.mjs", "check_dashboard_layout.mjs"}
#: The core's home modules, and the local definitions that keep their own on purpose.
CORE_PY = ("fabric_jsvalue.py", "fabric_time.py", "fabric_crypto.py")
CORE_JS = ("fabric-jsvalue.mjs", "fabric-time.mjs", "fabric-crypto.mjs")
KEEP_OWN = {
    ("fabric_identifiers.py", "_double"): "fabric_identifiers.py ships alone in adapting-projects-to-fabric too",
    ("fabric_ceremonies.py", "_b64url"): "a strict decode that raises on a length base64url cannot produce",
}
CORE_ALIASES = {"_js_string", "_show", "_same", "_double", "_number", "_json_equal", "_safe_integer", "_js_to_number",
                "_json_stringify", "_b64url", "_sha256", "_utc_date_ms", "_days_from_civil", "_list", "_indexed"}


def python_defs(path):
    return {n.name for n in ast.parse(path.read_text(encoding="utf-8")).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}


def node_defs(path):
    return set(re.findall(r"^(?:export )?(?:async )?(?:function\*? |const |let |class )([A-Za-z_$][\w$]*)", path.read_text(encoding="utf-8"), re.M))


class Manifest(unittest.TestCase):
    def test_kit_json_is_what_the_sources_say(self):
        self.assertEqual(fabric_kit.build(check=True), [], "run: python3 %s build" % (SCRIPTS / "fabric_kit.py"))

    def test_build_refuses_to_rewrite_a_released_version(self):
        """FAA-111: a build run before kit.json's version moves on rewrote the last release's digests three times
        (0.41.0, 0.47.0, 0.49.0); `build` now refuses when its version already has a release tag and other digests."""
        with tempfile.TemporaryDirectory() as tmp:
            manifest = dict(KIT, history=dict(KIT["history"]))
            manifest["history"][manifest["version"]] = {"fabric_jsvalue.py": "0" * 64}
            path = Path(tmp) / "kit.json"
            path.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
            saved, released = fabric_kit.MANIFEST, fabric_kit._released
            fabric_kit.MANIFEST, fabric_kit._released = path, lambda version: True
            try:
                with self.assertRaises(SystemExit) as refused:
                    fabric_kit.build()
                self.assertIn("v%s" % manifest["version"], str(refused.exception))
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), manifest, "nothing written")
                self.assertIn("kit.json history %s" % manifest["version"], fabric_kit.build(check=True), "check only reports")
                fabric_kit._released = lambda version: False
                self.assertIn("kit.json history %s" % manifest["version"], fabric_kit.build())
            finally:
                fabric_kit.MANIFEST, fabric_kit._released = saved, released

    def test_a_released_version_keeps_its_digests(self):
        """A release's history entry is what that release shipped. `build` writes the entry of kit.json's own version, so
        a build run before the version moves on would rewrite the last release's digests and make its genuine copies read
        `modified` (seen in the 0.41.0 integration). Every release tag present in this clone is compared."""
        tags = subprocess.run(["git", "-C", str(ROOT), "tag", "--list", "v*"], capture_output=True, text=True).stdout.split()
        rel = (SCRIPTS / "kit.json").relative_to(ROOT).as_posix()
        compared = 0
        for tag in tags:
            shown = subprocess.run(["git", "-C", str(ROOT), "show", "%s:%s" % (tag, rel)], capture_output=True, text=True)
            if shown.returncode != 0:
                continue  # a release older than kit.json
            released = json.loads(shown.stdout)
            version = released.get("version")
            if version in released.get("history", {}):
                self.assertEqual(KIT["history"].get(version), released["history"][version], "history %s" % version)
                compared += 1
        if not compared:
            # The hosted `python` job checks out with tags and sets this, so the guard cannot skip there (FAA-82).
            if os.environ.get("FABRIC_REQUIRE_RELEASE_TAGS") == "1":
                self.fail("FABRIC_REQUIRE_RELEASE_TAGS=1 and no release tag in this clone: check out with tags")
            self.skipTest("no release tag in this clone (a shallow checkout)")

    def test_it_lists_every_library_module(self):
        listed = {e["file"] for e in KIT["python"] + KIT["node"]}
        on_disk = {p.name for p in SCRIPTS.glob("*.py")} | {p.name for p in SCRIPTS.glob("*.mjs")}
        self.assertEqual(sorted(on_disk - listed - NOT_KIT), [])
        self.assertEqual(sorted(listed - on_disk), [])

    def test_the_order_is_a_layering(self):
        for lang in ("python", "node"):
            seen = set()
            for entry in KIT[lang]:
                with self.subTest(lang=lang, module=entry["module"]):
                    self.assertEqual([m for m in entry["imports"] if m not in seen], [],
                                     "imports a module listed after it: a cycle or an upward import")
                seen.add(entry["module"])

    def test_the_twins_list_the_same_modules(self):
        self.assertEqual([e["module"].replace("_", "-") for e in KIT["python"]], [e["module"] for e in KIT["node"]])

    def test_a_planted_cycle_is_caught(self):
        entries = [dict(e) for e in KIT["python"]]
        entries[0] = dict(entries[0], imports=[entries[-1]["module"]])
        seen, upward = set(), []
        for entry in entries:
            upward += [m for m in entry["imports"] if m not in seen]
            seen.add(entry["module"])
        self.assertEqual(upward, [entries[-1]["module"]])

    def test_every_kit_module_is_documented(self):
        """FAA-65 REQ-10: the module map names every module kit.json lists, in its layer, and nothing kit.json lacks."""
        text = (SCRIPTS.parent / "references/kit-modules.md").read_text(encoding="utf-8")
        rows = {name: layer for layer, name in re.findall(r"^\| (L[0-9]) \| `([a-z_]+)` \|", text, re.M)}
        self.assertEqual(rows, {e["module"]: e["layer"] for e in KIT["python"]})

    def test_the_version_is_the_adapters(self):
        self.assertEqual(KIT["version"], json.loads((ROOT / "package.json").read_text())["version"])


class Shape(unittest.TestCase):
    def test_no_module_over_the_line_ceiling(self):
        files = [SCRIPTS / e["file"] for e in KIT["python"] + KIT["node"]] + [SCRIPTS / n for n in ("check_service.py",)]
        files += sorted((ROOT / "plugins/fabric-agent-adapter/skills").glob("*/scripts/*.py"))  # every script, kit or not
        files += sorted((ROOT / "plugins/fabric-agent-adapter/skills").glob("*/scripts/*.mjs"))
        over = sorted(f.name for f in files if len(f.read_text(encoding="utf-8").splitlines()) > MAX_LINES)
        self.assertEqual(sorted(set(over) - OVERSIZE), [], "split it, or it would join the shrinking OVERSIZE list")
        self.assertEqual(sorted(OVERSIZE - set(over)), [], "a split module leaves OVERSIZE")

    def test_the_core_is_defined_once(self):
        core = set().union(*(python_defs(SCRIPTS / f) for f in CORE_PY))
        for entry in KIT["python"]:
            if entry["file"] in CORE_PY:
                continue
            twins = (python_defs(SCRIPTS / entry["file"]) & (core | CORE_ALIASES))
            twins -= {name for (f, name) in KEEP_OWN if f == entry["file"]}
            with self.subTest(module=entry["file"]):
                self.assertEqual(sorted(twins), [], "defined in the core; import it from there")
        core_js = set().union(*(node_defs(SCRIPTS / f) for f in CORE_JS))
        for entry in KIT["node"]:
            if entry["file"] in CORE_JS:
                continue
            with self.subTest(module=entry["file"]):
                self.assertEqual(sorted(node_defs(SCRIPTS / entry["file"]) & core_js), [], "defined in the core")


class Install(unittest.TestCase):
    def run_kit(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / "fabric_kit.py"), *map(str, args)], capture_output=True, text=True)

    def test_the_python_closure_runs_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_kit("install", tmp).returncode, 0)
            smoke = Path(tmp) / "smoke.py"
            smoke.write_text(
                "import sys\nassert all('building-fabric-services' not in p for p in sys.path)\n"
                "import fabric_service as fs\n"
                "r = fs.make_usage_receipt('openrouter', 'example-model', input_tokens=1, output_tokens=1, cost_usd=0.01, at='2026-10-21T09:00:00Z')\n"
                "import datetime as dt\nreport = fs.usage_report([r], service_id='example-agent', now=dt.datetime(2026, 10, 21, 12, tzinfo=dt.timezone.utc))\n"
                "assert fs.usage_findings(report) == [], fs.usage_findings(report)\n"
                "print('ok', sorted(m for m in sys.modules if m.startswith('fabric_')))\n", encoding="utf-8")
            run = subprocess.run([sys.executable, "-E", "-s", str(smoke)], capture_output=True, text=True, cwd=tmp)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("fabric_usage", run.stdout)
            self.assertNotIn("fabric_estate", run.stdout, "the service needs no estate reader since FAA-65")
            self.assertEqual(self.run_kit("status", tmp).returncode, 0, self.run_kit("status", tmp).stdout)

    def test_the_node_closure_runs_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_kit("install", tmp, "--lang", "node").returncode, 0)
            (Path(tmp) / "smoke.mjs").write_text(
                "import * as k from './fabric-service.mjs';\n"
                "const r = k.makeUsageReceipt('openrouter', 'example-model', { inputTokens: 1, outputTokens: 1, costUsd: 0.01, at: '2026-10-21T09:00:00Z' });\n"
                "const report = k.usageReport([r], { id: 'example-agent', now: 1792573200000 });\n"
                "if (k.usageFindings(report).length) throw new Error('findings');\nconsole.log('ok');\n", encoding="utf-8")
            run = subprocess.run(["node", str(Path(tmp) / "smoke.mjs")], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)

    def test_every_module_loads_by_path_from_any_folder(self):
        """A service that loads a kit file by its path (spec_from_file_location) from another working directory gets
        its siblings too, as with 0.39.1: the Windows lock holder and copied kits do exactly this."""
        code = ("import importlib.util as u, sys\n"
                "for name in sys.argv[2:]:\n"
                "    s = u.spec_from_file_location('by_path_' + name, sys.argv[1] + '/' + name + '.py')\n"
                "    s.loader.exec_module(u.module_from_spec(s))\n")
        out = subprocess.run([sys.executable, "-E", "-s", "-c", code, str(SCRIPTS)] + [e["module"] for e in KIT["python"]],
                             capture_output=True, text=True, cwd=os.path.abspath(os.sep), timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-500:])

    def test_a_one_file_copy_is_named_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "fabric_service.py").write_bytes((SCRIPTS / "fabric_service.py").read_bytes())
            report = fabric_kit.status(Path(tmp))
            self.assertIn("fabric_usage.py", [m["needs"] for m in report["missing"]])
            self.assertEqual(self.run_kit("status", tmp).returncode, 1)
            closure = {e["file"] for e in fabric_kit.closure(KIT["python"], ["fabric_service"])} - {"fabric_service.py"}
            self.assertEqual(sorted(m["needs"] for m in report["missing"]), sorted(closure),
                             "the whole closure is named at once, not only the direct imports")

    def test_an_older_copy_is_judged_by_its_own_imports(self):
        old = subprocess.run(["git", "-C", str(ROOT), "show",
                              "969a4ca:plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_service.py"],
                             capture_output=True)
        if old.returncode:
            self.skipTest("the 0.39.1 commit is not in this clone")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "fabric_service.py").write_bytes(old.stdout)
            report = fabric_kit.status(Path(tmp))
            self.assertEqual(report["files"][0]["state"], "older")
            needs = {m["needs"] for m in report["missing"]}
            self.assertIn("fabric_estate.py", needs, "the 0.39.1 file imports fabric_estate itself")
            self.assertNotIn("fabric_base.py", needs, "a module only the 0.40.0 file imports is not asked of it")

    def test_an_older_release_and_an_edited_copy_are_told_apart(self):
        shown = subprocess.run(["git", "show", "v0.39.1:plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_share.py"],
                               capture_output=True, cwd=ROOT)
        if shown.returncode:
            self.skipTest("the v0.39.1 tag is not in this clone (CI checks out one commit)")
        old = shown.stdout
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "fabric_share.py").write_bytes(old)
            self.assertEqual(fabric_kit.state_of(Path(tmp) / "fabric_share.py", KIT)["version"], "0.39.1")
            (Path(tmp) / "fabric_share.py").write_bytes(old + b"# a local edit\n")
            self.assertEqual(fabric_kit.state_of(Path(tmp) / "fabric_share.py", KIT)["state"], "modified")
            refused = self.run_kit("install", tmp, "--module", "fabric_share")
            self.assertEqual(refused.returncode, 1)
            self.assertIn("refused", refused.stdout)
            self.assertTrue((Path(tmp) / "fabric_share.py").read_bytes().endswith(b"# a local edit\n"), "the edit is kept")
            self.assertEqual(self.run_kit("install", tmp, "--module", "fabric_share", "--force").returncode, 0)
            self.assertEqual(fabric_kit.state_of(Path(tmp) / "fabric_share.py", KIT)["state"], "current")


if __name__ == "__main__":
    unittest.main()
