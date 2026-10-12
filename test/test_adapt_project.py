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
        effect="none",
        idempotency="none",
        cost_preset=[],
        default_cost_preset=None,
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


class EffectAndCostTests(unittest.TestCase):
    """FAA-25 (target architecture v4, Stage 0): every capability's effect is declared, never defaulted, and the
    manifest carries the costPresets the author gives (DEC-0037)."""

    def manifest(self, **overrides):
        args = scaffold_args("mcp")
        for key, value in overrides.items():
            setattr(args, key, value)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ADAPTER.scaffold_project(root, args)
            return json.loads((root / "fabric-agent.json").read_text())

    def test_the_declared_effect_and_idempotency_are_written(self):
        cap = self.manifest(effect="publish", idempotency="required")["capabilities"][0]
        self.assertEqual((cap["effect"], cap["idempotency"]), ("publish", "required"))

    def test_a_missing_or_unknown_effect_is_refused_never_defaulted(self):
        for effect in (None, "", "launch"):
            with self.subTest(effect=effect), self.assertRaises(ADAPTER.AdaptationError):
                self.manifest(effect=effect)
        args = scaffold_args("mcp")
        del args.effect
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ADAPTER.AdaptationError):
            ADAPTER.scaffold_project(Path(temp), args)

    def test_cost_presets_are_written_for_the_capability(self):
        manifest = self.manifest(cost_preset=[["quick", "0.5", "Quick draft"], ["deep", "3", "Deep research"]], default_cost_preset="quick")
        self.assertEqual(manifest["costPresets"], [
            {"id": "quick", "capability": "demo.run", "label": "Quick draft", "maxUsd": 0.5, "default": True},
            {"id": "deep", "capability": "demo.run", "label": "Deep research", "maxUsd": 3.0},
        ])
        self.assertNotIn("costPresets", self.manifest())

    def test_bad_cost_presets_are_refused(self):
        cases = {
            "bad id": [["Quick", "1", "x"]],
            "negative": [["quick", "-1", "x"]],
            "not a number": [["quick", "lots", "x"]],
            "not finite": [["quick", "inf", "x"]],
            "empty label": [["quick", "1", ""]],
            "duplicate id": [["quick", "1", "a"], ["quick", "2", "b"]],
        }
        for name, presets in cases.items():
            with self.subTest(name), self.assertRaises(ADAPTER.AdaptationError):
                self.manifest(cost_preset=presets)
        with self.assertRaises(ADAPTER.AdaptationError):
            self.manifest(cost_preset=[["quick", "1", "a"]], default_cost_preset="deep")
        with self.assertRaises(ADAPTER.AdaptationError):
            self.manifest(default_cost_preset="quick")

    def test_the_cli_requires_effect(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as temp:
            argv = ["scaffold", temp, "--profile", "mcp", "--provider-id", "https://agents.example/p", "--capability-id",
                    "https://agents.example/c", "--capability-name", "demo.run", "--schema-base", "https://agents.example/fabric"]
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
                ADAPTER.main(argv)
            self.assertEqual(stop.exception.code, 2)
            self.assertEqual(ADAPTER.main(argv + ["--effect", "draft", "--cost-preset", "quick", "0.25", "Quick", "--json"]), 0)
            manifest = json.loads((Path(temp) / "fabric-agent.json").read_text())
            self.assertEqual((manifest["capabilities"][0]["effect"], manifest["costPresets"][0]["maxUsd"]), ("draft", 0.25))


class LifecycleRuleTests(unittest.TestCase):
    """LC-19 (FAA-22) and LC-21 (FAA-23): no per-session stdio server in a plugin, no credential in argv or a URL."""

    def scaffold(self, root, **overrides):
        args = scaffold_args("mcp")
        for key, value in overrides.items():
            setattr(args, key, value)
        ADAPTER.scaffold_project(root, args)

    def receipts(self, root):
        return ADAPTER.check_project(root, None)["gates"]["localStructure"]

    def test_scaffold_refuses_a_credential_in_a_runtime_argument(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ADAPTER.AdaptationError):
            self.scaffold(Path(temp), mcp_mode="stdio", runtime_arg=["--key=" + "Zk9yZ2V0VGhp" + "c0lzQVNlY3JldEtleTEyMzQ1Njc4OTA"])

    def test_check_refuses_a_credential_in_an_argument_or_a_url(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.scaffold(root, mcp_mode="stdio", runtime_arg=["--verbose"])
            self.assertEqual(self.receipts(root)["status"], "PASS")
            manifest = json.loads((root / "fabric-agent.json").read_text())
            manifest["capabilities"][0]["profile"]["connection"]["args"] = ["--api-key=" + "s" + "k-" + "y" * 24]
            (root / "fabric-agent.json").write_text(json.dumps(manifest))
            gate = self.receipts(root)
            self.assertEqual(gate["status"], "FAIL")
            self.assertTrue(any("LC-21" in r for r in gate["receipts"]), gate)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.scaffold(root, mcp_url="https://agents.example/mcp?api_key=abc")
            self.assertTrue(any("LC-21" in r for r in self.receipts(root)["receipts"]))

    def test_check_flags_a_plugin_stdio_server_started_in_every_session(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.scaffold(root)
            plugin = root / "plugins" / "example"
            (plugin / ".claude-plugin").mkdir(parents=True)
            (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "example"}))
            (plugin / ".mcp.json").write_text(json.dumps({"mcpServers": {"example": {"command": "node", "args": ["server.js"]}}}))
            gate = self.receipts(root)
            self.assertEqual(gate["status"], "FAIL")
            self.assertTrue(any("LC-19" in r and "example" in r for r in gate["receipts"]), gate)
            (plugin / ".mcp.json").write_text(json.dumps({"mcpServers": {"example": {"type": "http", "url": "http://127.0.0.1:47201/mcp"}}}))
            self.assertEqual(self.receipts(root)["status"], "PASS")
            (plugin / ".mcp.json").write_text(json.dumps({"mcpServers": {"example": {"type": "http", "url": "http://127.0.0.1:47201/mcp?token=abc"}}}))
            self.assertTrue(any("LC-21" in r for r in self.receipts(root)["receipts"]))
            (plugin / ".mcp.json").unlink()
            (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "example", "mcpServers": {"x": {"command": "python3", "args": ["-m", "x"]}}}))
            self.assertTrue(any("LC-19" in r for r in self.receipts(root)["receipts"]))

    def test_the_detector_copies_are_identical(self):
        base = Path(__file__).resolve().parents[1] / "plugins/fabric-agent-adapter/skills"
        self.assertEqual((base / "adapting-projects-to-fabric/scripts/fabric_secrets.py").read_bytes(),
                         (base / "building-fabric-services/scripts/fabric_secrets.py").read_bytes())
