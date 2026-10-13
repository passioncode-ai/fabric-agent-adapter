"""DEC-0076 identifier equality in the Python kits (FAA-39); the twin of fabric-identifiers.test.mjs. Held to the
contract's fixtures/vectors/identifiers.json (test/fixtures/contract/identifier-vectors.json, vendor_vectors.mjs)."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins/fabric-agent-adapter/skills"
spec = importlib.util.spec_from_file_location("fabric_identifiers", SKILLS / "building-fabric-services/scripts/fabric_identifiers.py")
fi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fi)
V = json.loads((ROOT / "test/fixtures/contract/identifier-vectors.json").read_text(encoding="utf-8"))


class Vectors(unittest.TestCase):
    def test_normal_forms(self):
        self.assertEqual(len(V["normal"]), 33)
        for c in V["normal"]:
            with self.subTest(c["name"]):
                self.assertEqual(fi.normal_identifier(c["input"]), c["expected"])

    def test_same_and_different(self):
        for a, b in V["same"]:
            with self.subTest(same=(a, b)):
                self.assertTrue(fi.same_identifier(a, b))
        for a, b in V["different"]:
            with self.subTest(different=(a, b)):
                self.assertFalse(fi.same_identifier(a, b))

    def test_the_lax_ports_mistakes_are_not_made(self):
        for c in V["laxPorts"]:
            with self.subTest(c["name"]):
                self.assertEqual(fi.normal_identifier(c["input"]), c["expected"])
                self.assertNotEqual(fi.normal_identifier(c["input"]), c["wrong"])

    def test_values_that_are_not_strings(self):
        self.assertIsNone(fi.normal_identifier(7))
        self.assertTrue(fi.same_identifier(None, None))
        self.assertTrue(fi.same_identifier(1, 1.0))
        self.assertFalse(fi.same_identifier(True, 1))
        self.assertFalse(fi.same_identifier("1", 1))
        self.assertFalse(fi.same_identifier({}, {}))

    def test_the_copies_are_identical(self):
        self.assertEqual((SKILLS / "adapting-projects-to-fabric/scripts/fabric_identifiers.py").read_bytes(),
                         (SKILLS / "building-fabric-services/scripts/fabric_identifiers.py").read_bytes())


class Writers(unittest.TestCase):
    def test_the_provider_entry_is_checked_and_written_in_normal_form(self):
        spec = importlib.util.spec_from_file_location("fabric_provider", SKILLS / "adapting-projects-to-fabric/scripts/fabric_provider.py")
        fp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fp)
        temp = Path(tempfile.mkdtemp())
        manifest = temp / "fabric-agent.json"
        manifest.write_text(json.dumps({"provider": {"id": "https://agents.example/providers/example-agent"}, "capabilities": []}))
        entry = {"protocol": "fabric-provider/0.1", "id": "example-agent", "providerId": "HTTPS://Agents.Example/providers/%65xample-agent",
                 "name": "Example Agent", "manifest": str(manifest), "run": {"mcp": {"url": "http://127.0.0.1:47201/mcp"}},
                 "installedAt": "2026-10-13T08:00:00Z", "installedBy": "test"}
        path = fp.write_provider_entry(entry, temp / "providers", temp / "services")
        self.assertEqual(json.loads(path.read_text())["providerId"], "https://agents.example/providers/example-agent")
        with self.assertRaises(fp.ProviderError) as caught:  # the path's case is significant: another provider
            fp.write_provider_entry(dict(entry, providerId="https://agents.example/providers/Example-agent"), temp / "providers2", temp / "services")
        self.assertIn("FAC-SEM-014", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
