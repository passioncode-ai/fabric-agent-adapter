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
            "id with a trailing newline (R1, FAA-72)": [["quick\n", "1", "x"]],
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


def replace_every_sentinel(root: Path) -> None:
    """What an author does before admission: real schemas, fixture, assertions, author, data classes; no template block."""
    manifest_path = root / "fabric-agent.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["provider"]["createdBy"] = "https://agents.example/people/author"
    manifest["provider"]["contentHash"] = "sha256:" + "1" * 64
    capability = manifest["capabilities"][0]
    capability["dataClasses"] = ["project-internal"]
    capability["profile"]["probes"][0]["assertions"] = ["returns the keyword list for the fixture domain"]
    manifest.pop("extensions", None)
    manifest_path.write_text(json.dumps(manifest))
    (root / "fabric/schemas/capability-input.schema.json").write_text(json.dumps(
        {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Keyword request", "type": "object",
         "properties": {"domain": {"type": "string"}}, "required": ["domain"]}))
    (root / "fabric/schemas/capability-output.schema.json").write_text(json.dumps(
        {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Keyword list", "type": "object",
         "properties": {"keywords": {"type": "array"}}, "required": ["keywords"]}))
    (root / "fabric/fixtures/admission-input.json").write_text(json.dumps({"domain": "example.com"}))
    (root / "fabric/probes/assertions.md").write_text("# Probe\n\n- Returns at least one keyword for example.com.\n")


class TemplateSentinelTests(unittest.TestCase):
    """FAA-71 (audit finding 19): check warns on every template sentinel still present, and readyForAdmission stays
    false while any remains."""

    def warnings_after(self, profile="mcp", **overrides):
        args = scaffold_args(profile)
        for key, value in overrides.items():
            setattr(args, key, value)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ADAPTER.scaffold_project(root, args)
            return ADAPTER.check_project(root, None)

    def test_a_fresh_scaffold_names_each_sentinel(self):
        result = self.warnings_after()
        joined = "\n".join(result["warnings"])
        for expected in ("fabric/schemas/capability-input.schema.json", "fabric/schemas/capability-output.schema.json",
                         "provider.createdBy", "assertions", "/capabilities/0/dataClasses", "/provider/identity/method",
                         "fabric/fixtures/admission-input.json", "fabric/probes/assertions.md", "provider.contentHash"):
            self.assertIn(expected, joined, result["warnings"])
        self.assertFalse(result["readyForAdmission"])

    def test_placeholders_in_any_generated_file_are_named(self):
        result = self.warnings_after("a2a", agent_card_url="https://replace.invalid/.well-known/agent-card.json")
        self.assertTrue(any("agentCardUrl" in w for w in result["warnings"]), result["warnings"])
        self.assertTrue(any("skillIds" in w for w in result["warnings"]), result["warnings"])
        result = self.warnings_after("local-runner", runner_kind="replace-me")
        self.assertTrue(any("runnerKind" in w for w in result["warnings"]), result["warnings"])

    def test_given_values_are_not_marked_as_defaulted(self):
        result = self.warnings_after(data_class=["confidential"], created_by="https://agents.example/people/author",
                                     probe_assertion=["returns three keywords"], identity_method="oauth2")
        joined = "\n".join(result["warnings"])
        for absent in ("dataClasses", "createdBy", "/provider/identity/method", "/profile/probes/0/assertions", "probes[0].assertions"):
            self.assertNotIn(absent, joined, result["warnings"])

    def test_local_install_identity_is_not_a_sentinel(self):
        result = self.warnings_after("local-runner")
        self.assertNotIn("/provider/identity/method", "\n".join(result["warnings"]))

    def test_no_warning_once_every_sentinel_is_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ADAPTER.scaffold_project(root, scaffold_args("mcp"))
            replace_every_sentinel(root)
            result = ADAPTER.check_project(root, None)
            self.assertEqual(result["warnings"], [])
            self.assertEqual(result["gates"]["localStructure"]["status"], "PASS")

    def test_a_template_block_left_behind_keeps_admission_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ADAPTER.scaffold_project(root, scaffold_args("mcp"))
            original = json.loads((root / "fabric-agent.json").read_text())
            replace_every_sentinel(root)
            manifest = json.loads((root / "fabric-agent.json").read_text())
            manifest["extensions"] = original["extensions"]
            (root / "fabric-agent.json").write_text(json.dumps(manifest))
            self.assertTrue(ADAPTER.check_project(root, None)["warnings"])


class ContractRunnerTests(unittest.TestCase):
    """FAA-71 (audit finding 20): check --contract runs the checkout's own tsx, never `pnpm exec`."""

    def test_the_checkout_tsx_is_called_directly(self):
        from unittest import mock
        import subprocess as sp
        with tempfile.TemporaryDirectory() as temp:
            contract = Path(temp) / "contract"
            (contract / "node_modules/.bin").mkdir(parents=True)
            (contract / "node_modules/.bin/tsx").write_text("#!/bin/sh\n")
            manifest = Path(temp) / "fabric-agent.json"
            manifest.write_text("{}")
            calls = []

            def fake_run(argv, **kwargs):
                calls.append(list(argv))
                out = ADAPTER.CONTRACT_COMMIT + "\n" if argv[:2] == ["git", "rev-parse"] else ""
                return sp.CompletedProcess(argv, 0, stdout=out, stderr="")

            with mock.patch.object(ADAPTER.subprocess, "run", side_effect=fake_run):
                status, _ = ADAPTER._contract_shape(manifest, contract, ADAPTER.CONTRACT_COMMIT)
            self.assertEqual(status, "PASS")
            runner = calls[-1]
            self.assertEqual(runner[0], str(contract / "node_modules/.bin/tsx"))
            self.assertNotIn("pnpm", runner)


class InspectAndCheckRobustnessTests(unittest.TestCase):
    """FAA-71 (audit finding 21)."""

    def test_a_client_mcp_config_is_not_an_mcp_surface(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"x": {"command": "x"}}}))
            (root / "settings.json").write_text(json.dumps({"mcpServers": {"y": {"url": "http://127.0.0.1:1234/mcp"}}}))
            result = ADAPTER.inspect_project(root)
            self.assertNotIn("mcp", result["candidateProfiles"])
            self.assertEqual(result["recommendedProfile"], "undetermined")
            self.assertTrue(result["evidence"]["mcp-client-config"])
            self.assertIn("MCP client", result["openQuestion"])

    def test_a_client_config_beside_a_server_keeps_the_server(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".mcp.json").write_text(json.dumps({"mcpServers": {}}))
            (root / "package.json").write_text(json.dumps({"dependencies": {"@modelcontextprotocol/sdk": "1"}}))
            self.assertEqual(ADAPTER.inspect_project(root)["recommendedProfile"], "mcp")

    def test_a_non_utf8_manifest_is_a_typed_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ADAPTER.scaffold_project(root, scaffold_args("mcp"))
            (root / "fabric-agent.json").write_bytes(b"\xff\xfe{not utf-8")
            result = ADAPTER.check_project(root, None)
            self.assertEqual(result["gates"]["localStructure"]["status"], "FAIL")
            self.assertTrue(any(r.startswith("invalid-json:fabric-agent.json") for r in result["gates"]["localStructure"]["receipts"]))

    def test_dry_run_writes_nothing_and_shows_each_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "fabric-agent.json").write_text("old manifest\n")
            args = scaffold_args("mcp")
            args.dry_run = True
            result = ADAPTER.scaffold_project(root, args)
            self.assertTrue(result["dryRun"])
            self.assertEqual(result["wouldReplace"], ["fabric-agent.json"])
            self.assertIn("fabric/FABRIC-CONFORMANCE.md", result["wouldCreate"])
            self.assertIn("-old manifest", result["diffs"]["fabric-agent.json"])
            self.assertEqual((root / "fabric-agent.json").read_text(), "old manifest\n")
            self.assertFalse((root / "fabric").exists())

    def test_force_without_dry_run_still_replaces(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "fabric-agent.json").write_text("old manifest\n")
            args = scaffold_args("mcp", force=True)
            args.dry_run = False
            ADAPTER.scaffold_project(root, args)
            self.assertIn("contractVersion", (root / "fabric-agent.json").read_text())

    def test_the_cli_dry_run_prints_the_diff(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "fabric-agent.json").write_text("old manifest\n")
            out = io.StringIO()
            argv = ["scaffold", temp, "--profile", "mcp", "--provider-id", "https://agents.example/p", "--capability-id",
                    "https://agents.example/c", "--capability-name", "demo.run", "--schema-base", "https://agents.example/fabric",
                    "--effect", "none", "--dry-run"]
            with contextlib.redirect_stdout(out):
                self.assertEqual(ADAPTER.main(argv), 0)
            self.assertIn("--- fabric-agent.json", out.getvalue())
            self.assertIn("-old manifest", out.getvalue())
            self.assertEqual((Path(temp) / "fabric-agent.json").read_text(), "old manifest\n")


class StatusSpellingTests(unittest.TestCase):
    """FAA-74 (audit finding 32): one spelling of the unverified status, the one check prints."""

    def test_the_conformance_report_says_NOT_VERIFIED(self):
        with tempfile.TemporaryDirectory() as temp:
            ADAPTER.scaffold_project(Path(temp), scaffold_args("mcp"))
            text = (Path(temp) / "fabric/FABRIC-CONFORMANCE.md").read_text()
            self.assertIn("NOT_VERIFIED", text)
            self.assertNotIn("NOT VERIFIED", text)
