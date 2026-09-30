import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/fabric-agent-adapter/skills/adapting-projects-to-fabric/scripts/adapt_project.py"
SPEC = importlib.util.spec_from_file_location("adapt_project", SCRIPT)
assert SPEC and SPEC.loader
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)


def scaffold_args(profile: str, force: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        profile=profile,
        provider_id="https://agents.example/providers/demo",
        provider_name="Demo provider",
        capability_id="https://agents.example/capabilities/demo",
        capability_name="demo.run",
        schema_base="https://agents.example/fabric",
        mcp_mode="streamable-http",
        mcp_url="https://agents.example/mcp",
        agent_card_url="https://agents.example/.well-known/agent-card.json",
        runner_kind="demo-cli",
        executable_ref="urn:executable:demo",
        runtime_arg=[],
        force=force,
        job=False,
    )


class InspectTests(unittest.TestCase):
    def test_detects_native_mcp(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "package.json").write_text(
                json.dumps({"dependencies": {"@modelcontextprotocol/sdk": "1.0.0"}}),
                encoding="utf-8",
            )
            result = ADAPTER.inspect_project(root)
            self.assertEqual(result["recommendedProfile"], "mcp")
            self.assertTrue(result["evidence"]["mcp"])

    def test_keeps_ambiguous_project_undetermined(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "agent-card.json").write_text("{}", encoding="utf-8")
            (root / "mcp.json").write_text("{}", encoding="utf-8")
            result = ADAPTER.inspect_project(root)
            self.assertEqual(result["recommendedProfile"], "undetermined")
            self.assertIsNotNone(result["openQuestion"])


class ScaffoldTests(unittest.TestCase):
    def test_scaffolds_each_profile_and_passes_local_check(self):
        for profile in ("mcp", "a2a", "local-runner"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                result = ADAPTER.scaffold_project(root, scaffold_args(profile))
                self.assertEqual(len(result["created"]), 7)
                check = ADAPTER.check_project(root, None)
                self.assertEqual(check["gates"]["localStructure"]["status"], "PASS")
                self.assertEqual(check["gates"]["declarationShape"]["status"], "NOT_RUN")
                self.assertFalse(check["readyForAdmission"])

    def test_refuses_collision_without_force(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            existing = root / "fabric-agent.json"
            existing.write_text("do not replace", encoding="utf-8")
            with self.assertRaises(ADAPTER.AdaptationError):
                ADAPTER.scaffold_project(root, scaffold_args("mcp"))
            self.assertEqual(existing.read_text(encoding="utf-8"), "do not replace")

    def test_preserves_stdio_mcp_surface(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = scaffold_args("mcp")
            args.mcp_mode = "stdio"
            args.executable_ref = "urn:executable:keyword-server"
            args.runtime_arg = ["--stdio"]
            ADAPTER.scaffold_project(root, args)
            manifest = json.loads((root / "fabric-agent.json").read_text(encoding="utf-8"))
            connection = manifest["capabilities"][0]["profile"]["connection"]
            self.assertEqual(connection["mode"], "stdio")
            self.assertEqual(connection["executableRef"], "urn:executable:keyword-server")

    def test_force_replaces_only_declared_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            unrelated = root / "README.md"
            unrelated.write_text("keep", encoding="utf-8")
            (root / "fabric-agent.json").write_text("old", encoding="utf-8")
            result = ADAPTER.scaffold_project(root, scaffold_args("a2a", force=True))
            self.assertIn("fabric-agent.json", result["replaced"])
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")

    def test_rejects_relative_provider_id(self):
        with tempfile.TemporaryDirectory() as temp:
            args = scaffold_args("mcp")
            args.provider_id = "provider/demo"
            with self.assertRaises(ADAPTER.AdaptationError):
                ADAPTER.scaffold_project(Path(temp), args)


class InteropScaffoldTests(unittest.TestCase):
    """fabric-interop/0.1: a capability is served as the MCP tool of its own name; --job marks long work."""

    def test_mcp_capability_requires_the_tool_of_its_own_name(self):
        with tempfile.TemporaryDirectory() as temp:
            ADAPTER.scaffold_project(Path(temp), scaffold_args("mcp"))
            manifest = json.loads((Path(temp) / "fabric-agent.json").read_text())
            self.assertEqual(manifest["capabilities"][0]["profile"]["requiredFeatures"], ["tool:demo.run"])

    def test_job_flag_writes_the_interop_block(self):
        args = scaffold_args("mcp")
        args.job = True
        with tempfile.TemporaryDirectory() as temp:
            ADAPTER.scaffold_project(Path(temp), args)
            manifest = json.loads((Path(temp) / "fabric-agent.json").read_text())
            self.assertEqual(manifest["capabilities"][0]["extensions"], {ADAPTER.INTEROP_KEY: {"job": True}})
            self.assertEqual(ADAPTER.check_project(Path(temp), None)["gates"]["localStructure"]["status"], "PASS")

    def test_job_flag_is_for_mcp_only(self):
        args = scaffold_args("local-runner")
        args.job = True
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ADAPTER.AdaptationError):
            ADAPTER.scaffold_project(Path(temp), args)

    def test_check_refuses_a_malformed_interop_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ADAPTER.scaffold_project(root, scaffold_args("mcp"))
            manifest = json.loads((root / "fabric-agent.json").read_text())
            manifest["capabilities"][0]["extensions"] = {ADAPTER.INTEROP_KEY: {"job": "yes"}}
            (root / "fabric-agent.json").write_text(json.dumps(manifest))
            check = ADAPTER.check_project(root, None)
            self.assertEqual(check["gates"]["localStructure"]["status"], "FAIL")
            self.assertTrue(any("interop" in r for r in check["gates"]["localStructure"]["receipts"]))

    def test_the_lock_names_the_one_pin(self):
        pin = json.loads((ROOT / "fabric-contract.lock.json").read_text())
        with tempfile.TemporaryDirectory() as temp:
            ADAPTER.scaffold_project(Path(temp), scaffold_args("mcp"))
            lock = json.loads((Path(temp) / "fabric-contract.lock.json").read_text())
            self.assertEqual({k: lock[k] for k in pin}, pin)


class CheckTests(unittest.TestCase):
    def test_secret_like_manifest_field_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ADAPTER.scaffold_project(root, scaffold_args("mcp"))
            path = root / "fabric-agent.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["provider"]["apiKey"] = "never-store-this"
            path.write_text(json.dumps(value), encoding="utf-8")
            result = ADAPTER.check_project(root, None)
            self.assertEqual(result["gates"]["localStructure"]["status"], "FAIL")
            self.assertTrue(any("secret-like" in item for item in result["gates"]["localStructure"]["receipts"]))


if __name__ == "__main__":
    unittest.main()
