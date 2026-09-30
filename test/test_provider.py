"""fabric_provider.py — the providers/ writer (contract docs/specification/provider.md)."""

import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/adapting-projects-to-fabric/scripts"
spec = importlib.util.spec_from_file_location("fabric_provider", SCRIPTS / "fabric_provider.py")
fp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fp)

# Credential-shaped values are assembled at run time so none sits in the source as a literal.
FAKE_GITHUB = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz0123456789"


def entry(provider_id="example-agent", **extra):
    base = {
        "protocol": "fabric-provider/0.1", "id": provider_id, "providerId": "https://agents.example/providers/%s" % provider_id,
        "name": "Example Agent", "manifest": "~/.local/share/%s/fabric-agent.json" % provider_id,
        "run": {"mcp": {"stdio": {"command": ["~/.local/bin/%s" % provider_id, "mcp"],
                                  "env": {"EXAMPLE_API_KEY": "secret-ref:%s/EXAMPLE_API_KEY" % provider_id}}}},
        "installedAt": "2026-09-30T08:00:00Z", "installedBy": "test",
    }
    base.update(extra)
    return base


class ValidationTests(unittest.TestCase):
    def test_a_conformant_entry_has_no_problems(self):
        self.assertEqual(fp.validate_provider_entry(entry()), [])
        self.assertEqual(fp.validate_provider_entry(entry(run={"mcp": {"url": "http://127.0.0.1:47201/mcp"}})), [])

    def test_each_rule_is_enforced(self):
        cases = {
            "shell string": entry(run={"mcp": {"stdio": {"command": "~/.local/bin/example-agent mcp"}}}),
            "literal env value": entry(run={"mcp": {"stdio": {"command": ["/bin/x"], "env": {"K": "abc123"}}}}),
            "credential behind a reference": entry(run={"mcp": {"stdio": {"command": ["/bin/x"], "env": {"K": "secret-ref:" + FAKE_GITHUB}}}}),
            "lan url": entry(run={"mcp": {"url": "http://192.168.1.2:47201/mcp"}}),
            "not /mcp": entry(run={"mcp": {"url": "http://127.0.0.1:47201/api"}}),
            "both transports": entry(run={"mcp": {"url": "http://127.0.0.1:47201/mcp", "stdio": {"command": ["/bin/x"]}}}),
            "bad id": entry(provider_id="Example_Agent"),
            "manifest is not fabric-agent.json": entry(manifest="~/x/manifest.json"),
            "relative manifest": entry(manifest="fabric-agent.json"),
            "wrong protocol": entry(protocol="fabric-service/0.1"),
            "long name": entry(name="x" * 81),
            "unknown field": entry(token="nope"),
            "providerId missing": {k: v for k, v in entry().items() if k != "providerId"},
            "providerId not a URI": entry(providerId="example-agent"),
        }
        for label, value in cases.items():
            self.assertNotEqual(fp.validate_provider_entry(value), [], label)

    def test_problems_never_quote_an_env_value(self):
        problems = fp.validate_provider_entry(entry(run={"mcp": {"stdio": {"command": ["/bin/x"], "env": {"K": FAKE_GITHUB}}}}))
        self.assertTrue(problems)
        self.assertNotIn(FAKE_GITHUB, " ".join(problems))


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.providers = base / "providers"
        self.services = base / "services"
        self.services.mkdir()
        self.manifest = base / "agent" / "fabric-agent.json"
        self.manifest.parent.mkdir()
        self.manifest.write_text(json.dumps({"contractVersion": "0.1.0", "provider": {"id": "https://agents.example/providers/example-agent"}, "capabilities": []}))

    def e(self, **extra):
        return entry(manifest=str(self.manifest), **extra)

    def tearDown(self):
        self.temp.cleanup()

    def test_default_directory_is_beside_services(self):
        with mock.patch.dict(os.environ, {"FABRIC_SERVICES_DIR": str(self.services)}, clear=False):
            os.environ.pop("FABRIC_PROVIDERS_DIR", None)
            self.assertEqual(fp.providers_dir(), self.services.parent / "providers")
        with mock.patch.dict(os.environ, {"FABRIC_PROVIDERS_DIR": str(self.providers)}):
            self.assertEqual(fp.providers_dir(), self.providers)

    def test_write_is_private_and_reinstall_is_allowed(self):
        path = fp.write_provider_entry(self.e(), self.providers, self.services)
        self.assertEqual(path, self.providers / "example-agent.json")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(json.loads(path.read_text())["id"], "example-agent")
        fp.write_provider_entry(self.e(name="Example Agent 2"), self.providers, self.services)
        self.assertEqual(json.loads(path.read_text())["name"], "Example Agent 2")

    def test_an_id_that_is_already_a_service_is_refused(self):
        (self.services / "example-agent.preview.json").write_text(json.dumps({"protocol": "fabric-service/0.1", "id": "example-agent", "instance": "preview"}))
        with self.assertRaises(fp.ProviderError) as caught:
            fp.write_provider_entry(self.e(), self.providers, self.services)
        self.assertIn("FAC-SEM-013", str(caught.exception))
        self.assertFalse((self.providers / "example-agent.json").exists())

    def test_an_invalid_entry_is_never_written(self):
        with self.assertRaises(fp.ProviderError):
            fp.write_provider_entry(self.e(run={"mcp": {"url": "http://10.0.0.1:1/mcp"}}), self.providers, self.services)
        self.assertFalse(self.providers.exists() and any(self.providers.iterdir()))

    def test_fac_sem_014_the_manifest_resolves_and_names_this_provider(self):
        with self.assertRaises(fp.ProviderError) as caught:
            fp.write_provider_entry(self.e(providerId="https://agents.example/providers/example-writer"), self.providers, self.services)
        self.assertIn("FAC-SEM-014", str(caught.exception))
        with self.assertRaises(fp.ProviderError) as caught:
            fp.write_provider_entry(entry(manifest=str(self.manifest.parent / "missing" / "fabric-agent.json")), self.providers, self.services)
        self.assertIn("FAC-SEM-014", str(caught.exception))
        self.assertFalse(self.providers.exists() and any(self.providers.iterdir()))

    def test_validate_reads_the_file_name(self):
        path = fp.write_provider_entry(self.e(), self.providers, self.services)
        renamed = path.with_name("example-writer.json")
        path.rename(renamed)
        out = subprocess.run([sys.executable, str(SCRIPTS / "fabric_provider.py"), "validate", str(renamed)], capture_output=True, text=True)
        self.assertEqual(out.returncode, 1)
        self.assertIn("file name", out.stdout)

    def test_remove(self):
        fp.write_provider_entry(self.e(), self.providers, self.services)
        self.assertTrue(fp.remove_provider_entry("example-agent", self.providers))
        self.assertFalse(fp.remove_provider_entry("example-agent", self.providers))

    def test_cli_writes_and_removes(self):
        env = dict(os.environ, FABRIC_PROVIDERS_DIR=str(self.providers), FABRIC_SERVICES_DIR=str(self.services))
        write = subprocess.run([sys.executable, str(SCRIPTS / "fabric_provider.py"), "write", "--id", "example-agent",
                                "--name", "Example Agent", "--manifest", str(self.manifest),
                                "--provider-id", "https://agents.example/providers/example-agent",
                                "--installed-by", "test", "--env", "EXAMPLE_API_KEY=secret-ref:example-agent/EXAMPLE_API_KEY",
                                "--stdio", "~/.local/bin/example-agent", "mcp"], capture_output=True, text=True, env=env)
        self.assertEqual(write.returncode, 0, write.stderr)
        written = json.loads((self.providers / "example-agent.json").read_text())
        self.assertEqual(written["run"]["mcp"]["stdio"]["command"], ["~/.local/bin/example-agent", "mcp"])
        refused = subprocess.run([sys.executable, str(SCRIPTS / "fabric_provider.py"), "write", "--id", "example-writer",
                                  "--name", "W", "--manifest", str(self.manifest), "--provider-id", "https://agents.example/providers/example-writer", "--installed-by", "t",
                                  "--env", "K=literal-value", "--stdio", "/bin/x"], capture_output=True, text=True, env=env)
        self.assertEqual(refused.returncode, 1)
        self.assertNotIn("literal-value", refused.stderr)
        remove = subprocess.run([sys.executable, str(SCRIPTS / "fabric_provider.py"), "remove", "example-agent"], capture_output=True, text=True, env=env)
        self.assertEqual(remove.returncode, 0)


if __name__ == "__main__":
    unittest.main()
