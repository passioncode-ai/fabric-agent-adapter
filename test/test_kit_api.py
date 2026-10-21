"""FAA-65: every name a kit module made public at v0.39.1 is still importable from that module. Services copied the
kit; splitting it into modules must not break `import fabric_service as fs; fs.<name>`."""
import importlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins/fabric-agent-adapter/skills"
SNAPSHOT = json.loads((Path(__file__).parent / "fixtures/kit-api/kit-api-0.39.1.json").read_text(encoding="utf-8"))
DIRS = [SKILLS / "building-fabric-services/scripts", SKILLS / "working-with-fabric/scripts"]


class PublicApi(unittest.TestCase):
    def test_every_0_39_1_name_is_still_there(self):
        for d in DIRS:
            if str(d) not in sys.path:
                sys.path.insert(0, str(d))
        for module, names in SNAPSHOT["python"].items():
            with self.subTest(module=module):
                mod = importlib.import_module(module)
                missing = [n for n in names if not hasattr(mod, n)]
                self.assertEqual(missing, [], "%s lost public names it had at v0.39.1" % module)

    def test_the_snapshot_is_not_empty(self):
        self.assertGreater(sum(map(len, SNAPSHOT["python"].values())), 500)
        self.assertIn("fabric_service", SNAPSHOT["python"])


if __name__ == "__main__":
    unittest.main()
