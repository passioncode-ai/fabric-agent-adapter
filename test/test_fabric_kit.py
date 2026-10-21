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
#: Modules over MAX_LINES while FAA-65 splits them; an entry leaves when its module is split, and none is ever added.
OVERSIZE = {"fabric_service.py", "fabric-service.mjs", "fabric_board.py", "fabric-board.mjs", "fabric_session.py"}
#: Scripts beside the kit that are programs or tools, not library modules a service copies.
NOT_KIT = {"check_service.py", "sample_service.py", "dashboard_kit.py", "check_dashboard_link.py", "fabric_kit.py",
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

    def test_the_version_is_the_adapters(self):
        self.assertEqual(KIT["version"], json.loads((ROOT / "package.json").read_text())["version"])


class Shape(unittest.TestCase):
    def test_no_module_over_the_line_ceiling(self):
        files = [SCRIPTS / e["file"] for e in KIT["python"] + KIT["node"]] + [SCRIPTS / n for n in ("check_service.py",)]
        files.append(ROOT / "plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/fabric_session.py")
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
            self.assertIn("fabric_estate", run.stdout)
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

    def test_a_one_file_copy_is_named_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "fabric_service.py").write_bytes((SCRIPTS / "fabric_service.py").read_bytes())
            report = fabric_kit.status(Path(tmp))
            self.assertIn("fabric_estate.py", [m["needs"] for m in report["missing"]])
            self.assertEqual(self.run_kit("status", tmp).returncode, 1)

    def test_an_older_release_and_an_edited_copy_are_told_apart(self):
        old = subprocess.run(["git", "show", "v0.39.1:plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_share.py"],
                             capture_output=True, cwd=ROOT, check=True).stdout
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
