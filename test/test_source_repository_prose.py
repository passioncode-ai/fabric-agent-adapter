"""FAA-200 (32), (42): the examples remote-placement.md and provider-entry.md give for `source.repository` are read by the
kit as the pages say, by both Python copies of fabric_secrets and by the Node twin. Since FAA-258 (DEC-0151 at the pin)
a host label and a digit-free or upper-case `sk-` are names; the pages once said the opposite. protocol.md tells an
upgrading installer how to give its fixtures a source and to filter the rewrite warning by class, which works."""
import importlib
import importlib.util
import sys
import tempfile
import warnings
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins/fabric-agent-adapter/skills"
REMOTE = (SKILLS / "building-fabric-services/references/remote-placement.md").read_text(encoding="utf-8")
PROTOCOL = (SKILLS / "building-fabric-services/references/protocol.md").read_text(encoding="utf-8")
PROVIDER = (SKILLS / "adapting-projects-to-fabric/references/provider-entry.md").read_text(encoding="utf-8")
COPIES = [SKILLS / skill / "scripts/fabric_secrets.py" for skill in ("building-fabric-services", "adapting-projects-to-fabric")]
STRONG = "sk-" + "Ab1d" * 10  # made up at run time: an `sk-` shape with a digit and an upper-case letter, never a key

NAMES = ["https://task-pipeline-dashboard.example.com/o/r", "https://github.com/example-org/task-pipeline-dashboard",
         "https://github.com/Example-Org/Task-Pipeline-Dashboard", "https://github.com/example-org/sk-learn-example-notebooks",
         "https://github.com/example-org/SK-" + "AbCd" * 10]
CREDENTIALS = ["https://github.com/example-org/" + STRONG, "https://github.com/example-org/x-" + STRONG,
               "https://github.com/example-org/%73k-" + STRONG[3:], "https://" + STRONG + ".example.com/o/r"]


def load(path):
    spec = importlib.util.spec_from_file_location("fabric_secrets_prose_%s" % path.parent.parent.name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RepositoryProse(unittest.TestCase):
    def test_the_pages_name_the_examples_the_kit_reads(self):
        for page in (REMOTE, PROVIDER):
            flat = " ".join(page.split())
            self.assertIn("task-pipeline-dashboard.example.com", flat)
            self.assertIn("DEC-0151", flat)
            self.assertNotIn("task-pipeline-dashboard.example.com` is refused", flat)
            self.assertNotIn("16 more characters is not", flat)
        self.assertIn("`sk-learn-example-notebooks` (no digit)", " ".join(REMOTE.split()))

    def test_each_python_copy_reads_the_examples_as_the_pages_say(self):
        for path in COPIES:
            secrets = load(path)
            for value in NAMES:
                with self.subTest(copy=path.parent.parent.name, name=value):
                    self.assertFalse(secrets.repository_credential(value))
            for value in CREDENTIALS:
                with self.subTest(copy=path.parent.parent.name, credential=value[:40]):
                    self.assertTrue(secrets.repository_credential(value))

    @unittest.skipUnless(shutil.which("node"), "node is not on PATH")
    def test_the_node_twin_reads_them_alike(self):
        module = (SKILLS / "building-fabric-services/scripts/fabric-secrets.mjs").as_uri()
        script = ("import(%s).then(m => { const v = JSON.parse(process.argv[1]);"
                  " process.stdout.write(JSON.stringify(v.map(x => m.repositoryCredential(x)))); })" % json.dumps(module))
        out = subprocess.run(["node", "-e", script, json.dumps(NAMES + CREDENTIALS)], capture_output=True, text=True,
                             timeout=60, check=True).stdout
        self.assertEqual(json.loads(out), [False] * len(NAMES) + [True] * len(CREDENTIALS))


class UpgradingProse(unittest.TestCase):
    FILTER = 'warnings.filterwarnings("ignore", category=NoSourceRepositoryWarning)'

    def test_protocol_names_the_fixture_and_the_filter_by_class(self):
        row = [line for line in PROTOCOL.splitlines() if line.startswith("| `source.repository` |")][0]
        self.assertIn("the fixture of a test suite that writes a temporary services folder too", row)
        self.assertIn(self.FILTER, row)
        self.assertIn("never by its message text", row)
        self.assertIn("naming an installed `source.repository` it drops, FAA-200 (41)", row)
        self.assertIn("`repository_from_origin` / `repositoryFromOrigin` spell a git origin, scp form included", row)
        self.assertIn("DEC-0089 item 2", row)

    def test_the_filter_the_page_gives_keeps_a_rewrite_quiet(self):
        sys.path.insert(0, str(SKILLS / "building-fabric-services/scripts"))
        try:
            fs = importlib.import_module("fabric_service")
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            descriptor = {"protocol": fs.PROTOCOL, "id": "sample", "instance": "default", "name": "Sample",
                          "origin": "http://127.0.0.1:47197", "auth": {"tokenFile": temp + "/service.token"},
                          "lifecycle": {"manager": "none"}, "paths": {"data": temp, "logs": []},
                          "installedAt": fs.now_iso(), "installedBy": "test"}
            with self.assertRaises(fs.ServiceError):  # the fixture without a source: a new install is refused
                fs.write_descriptor(dict(descriptor), root, port_owner=lambda port: None)
            fs.write_descriptor(dict(descriptor, source={"repository": "https://github.com/example-org/example-agent"}),
                                root, port_owner=lambda port: None)
            with warnings.catch_warnings(record=True) as seen:
                warnings.simplefilter("always")
                exec(self.FILTER, {"warnings": warnings, "NoSourceRepositoryWarning": fs.NoSourceRepositoryWarning})
                fs.write_descriptor(dict(descriptor), root, port_owner=lambda port: None)
            self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
