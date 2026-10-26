"""The sample service over MCP, and check_service.py's interop rules, with defects planted on purpose."""

import http.client
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
SERVICE_KEY = "https://fabric.passioncode.ai/agent-contract/extensions/service/0.1"
PARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(module)
    return module


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveSample(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.data = base / "data"
        self.services = base / "services"
        self.port = free_port()
        self.proc = subprocess.Popen([sys.executable, str(SCRIPTS / "sample_service.py"), "serve", "--port", str(self.port),
                                      "--data-dir", str(self.data)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/.well-known/fabric-service" % self.port, timeout=0.5):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            self.fail("sample service did not start")
        subprocess.run([sys.executable, str(SCRIPTS / "sample_service.py"), "register", "--port", str(self.port),
                        "--data-dir", str(self.data), "--services-dir", str(self.services)], check=True, capture_output=True)
        self.token = (self.data / "service.token").read_text().strip()
        self.descriptor = json.loads((self.services / "sample.default.json").read_text())
        self.manifest_path = Path(os.path.expanduser(self.descriptor["fabricManifest"]))

    def tearDown(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(10)
        self.proc.stdout.close()
        self.proc.stderr.close()
        self.temp.cleanup()

    def mcp(self, method, params, rid=1):
        params = dict(params)
        params["_meta"] = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                           "io.modelcontextprotocol/clientCapabilities": {}, "traceparent": PARENT}
        body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}).encode()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("POST", "/mcp", body=body, headers={"Host": "127.0.0.1:%d" % self.port, "Authorization": "Bearer " + self.token,
                                                              "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
            resp = conn.getresponse()
            return resp.status, json.loads(resp.read() or b"null")
        finally:
            conn.close()

    def check(self):
        out = subprocess.run([sys.executable, str(SCRIPTS / "check_service.py"), "sample", "--services-dir",
                              str(self.services), "--json"], capture_output=True, text=True)
        return out.returncode, {r["rule"]: r for r in json.loads(out.stdout)["results"]}


class SampleInteropTests(LiveSample):
    def test_mcp_requires_the_token(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/mcp", body=b"{}", headers={"Host": "127.0.0.1:%d" % self.port, "Content-Type": "application/json"})
        self.assertEqual(conn.getresponse().status, 401)
        conn.close()

    def test_a_job_runs_through_a_choice_to_a_traced_result(self):
        status, response = self.mcp("tools/call", {"name": "sample.draft", "arguments": {"topic": "titles"}})
        self.assertEqual(status, 200)
        job_id = response["result"]["structuredContent"]["job"]["id"]
        _, got = self.mcp("tools/call", {"name": "fabric.job.get", "arguments": {"id": job_id}}, 2)
        job = got["result"]["structuredContent"]["job"]
        self.assertEqual(job["status"], "input_required")
        request = job["inputRequests"]["title_choice"]
        self.assertEqual(request["params"]["mode"], "form")
        choice = request["params"]["requestedSchema"]["properties"]["title"]["oneOf"][0]["const"]
        _, done = self.mcp("tools/call", {"name": "fabric.job.get", "arguments": {
            "id": job_id, "inputResponses": {"title_choice": {"action": "accept", "content": {"title": choice}}}}}, 3)
        job = done["result"]["structuredContent"]["job"]
        self.assertEqual(job["status"], "completed")
        self.assertEqual(sorted(job["result"]), ["artifacts", "contractVersion", "createdAt", "done", "id", "notVerified", "outcome",
                                                 "output", "producer", "proof", "scope", "trace", "usage"])
        self.assertEqual(done["result"]["_meta"]["traceparent"], job["result"]["trace"]["traceparent"])
        self.assertIn(TRACE, job["result"]["trace"]["traceparent"])
        page = json.loads(urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:%d/fabric/v1/events?limit=50" % self.port, headers={"Authorization": "Bearer " + self.token})).read())
        traced = [e for e in page["events"] if e.get("traceId")]
        self.assertTrue(traced, "job events carry the trace")
        self.assertTrue(all(e["traceId"] == TRACE and len(e["spanId"]) == 16 for e in traced))

    def test_a_job_survives_a_restart(self):
        _, response = self.mcp("tools/call", {"name": "sample.draft", "arguments": {"topic": "titles"}})
        job_id = response["result"]["structuredContent"]["job"]["id"]
        self.proc.terminate()
        self.proc.wait(10)
        self.proc.stdout.close()
        self.proc.stderr.close()
        self.proc = subprocess.Popen([sys.executable, str(SCRIPTS / "sample_service.py"), "serve", "--port", str(self.port),
                                      "--data-dir", str(self.data)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                _, got = self.mcp("tools/call", {"name": "fabric.job.get", "arguments": {"id": job_id}}, 4)
                break
            except OSError:
                time.sleep(0.1)
        self.assertEqual(got["result"]["structuredContent"]["job"]["id"], job_id)


class ProbeInteropTests(LiveSample):
    RULES = ("interop.output-schema-object", "interop.manifest-link", "interop.well-known-capabilities", "interop.tools-match", "interop.job-tools",
             "interop.unknown-job", "interop.trace-propagation", "interop.events-trace")

    def test_the_sample_passes_every_interop_rule(self):
        code, results = self.check()
        # well-known.fast times this machine (100 ms median), not the interop rules: under a loaded host it is the one
        # verdict allowed to fail here, and the probe's exit then follows it.
        failed = {k: v["evidence"] for k, v in results.items() if v["verdict"] == "FAIL"}
        timing = failed.pop("well-known.fast", None)
        self.assertEqual(failed, {})
        self.assertIn(results["well-known.fast"]["verdict"], ("PASS", "FAIL"))
        self.assertEqual(code, 1 if timing else 0)
        for rule in self.RULES:
            self.assertEqual(results[rule]["verdict"], "PASS", "%s: %s" % (rule, results[rule]["evidence"]))

    def test_planted_manifest_naming_another_service_is_caught(self):
        manifest = json.loads(self.manifest_path.read_text())
        manifest["provider"]["extensions"][SERVICE_KEY]["descriptor"] = "writer.default"
        self.manifest_path.write_text(json.dumps(manifest))
        code, results = self.check()
        self.assertEqual(results["interop.manifest-link"]["verdict"], "FAIL")
        self.assertEqual(code, 1)

    def test_planted_schema_drift_is_caught(self):
        schema_path = next(self.manifest_path.parent.glob("fabric/schemas/*echo-output*.json"))
        schema = json.loads(schema_path.read_text())
        schema["required"] = []
        schema_path.write_text(json.dumps(schema))
        _, results = self.check()
        self.assertEqual(results["interop.tools-match"]["verdict"], "FAIL")
        self.assertIn("sample.echo", results["interop.tools-match"]["evidence"])

    def test_planted_capability_missing_from_the_manifest_is_caught(self):
        manifest = json.loads(self.manifest_path.read_text())
        manifest["capabilities"] = [c for c in manifest["capabilities"] if c["name"] != "sample.draft"]
        self.manifest_path.write_text(json.dumps(manifest))
        _, results = self.check()
        self.assertEqual(results["interop.well-known-capabilities"]["verdict"], "FAIL")


class ProbeRuleUnitTests(unittest.TestCase):
    """Defects a live sample cannot be made to show: a fresh job for an unknown id, a foreign trace."""

    def probe(self, answers):
        checker = load("check_service")
        probe = checker.Probe(Path("/nonexistent"), {"origin": "http://127.0.0.1:1"}, Path("/nonexistent"), True)
        probe.mcp_call = lambda method, params: answers[params.get("name", method)]
        return probe

    def test_a_fresh_job_for_an_unknown_id_fails(self):
        fresh = {"result": {"isError": False, "structuredContent": {"job": {"id": "new", "status": "working"}}}}
        probe = self.probe({"fabric.job.get": fresh})
        probe.unknown_job_rule(["fabric.job.get"])
        self.assertEqual(probe.results[-1]["verdict"], "FAIL")

    def test_a_foreign_trace_in_the_answer_fails(self):
        probe = self.probe({})
        probe.trace_rule({"result": {"_meta": {"traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01"}}}, PARENT)
        self.assertEqual(probe.results[-1]["verdict"], "FAIL")
        probe.trace_rule({"result": {"_meta": {"traceparent": "00-" + TRACE + "-00f067aa0ba902b7-01"}}}, PARENT)
        self.assertEqual(probe.results[-1]["verdict"], "FAIL", "echoing the caller's own span is not a child span")

    def test_a_job_tool_serving_the_bare_output_schema_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            out = {"$id": "urn:x:out", "type": "object"}
            (Path(temp) / "x.schema.json").write_text(json.dumps(out))
            (Path(temp) / "in.schema.json").write_text(json.dumps({"$id": "urn:x:in", "type": "object"}))
            cap = {"name": "example.draft", "effect": "draft", "idempotency": "none", "inputSchema": "urn:x:in", "outputSchema": "urn:x:out",
                   "profile": {"kind": "mcp"}, "extensions": {SERVICE_KEY.replace("service", "interop"): {"job": True}}}
            probe = self.probe({})
            fi = load("fabric_interop")
            bare = {"name": "example.draft", "inputSchema": {"$id": "urn:x:in", "type": "object"}, "outputSchema": out, "annotations": {}}
            probe.tools_match_rule([cap], Path(temp) / "fabric-agent.json", {"example.draft": bare})
            self.assertEqual(probe.results[-1]["verdict"], "FAIL")
            probe.tools_match_rule([cap], Path(temp) / "fabric-agent.json", {"example.draft": dict(bare, outputSchema=fi.job_tool_output_schema(out))})
            self.assertEqual(probe.results[-1]["verdict"], "PASS", probe.results[-1]["evidence"])

    def test_a_tool_whose_output_schema_root_is_not_object_fails(self):
        probe = self.probe({})
        probe.object_root_rule({"a": {"name": "a", "outputSchema": {"type": "object"}}, "b": {"name": "b"},
                                "c": {"name": "c", "outputSchema": {"oneOf": [{"type": "object"}]}}})
        self.assertEqual(probe.results[-1]["verdict"], "FAIL")
        self.assertIn("c", probe.results[-1]["evidence"])
        probe.object_root_rule({"a": {"name": "a", "outputSchema": {"type": "object", "oneOf": [{"type": "object"}]}}, "b": {"name": "b"}})
        self.assertEqual(probe.results[-1]["verdict"], "PASS")

    def test_events_with_half_a_trace_fail(self):
        probe = self.probe({})
        probe.events_trace_rule([{"id": "1", "traceId": TRACE}])
        self.assertEqual(probe.results[-1]["verdict"], "FAIL")
        probe.events_trace_rule([{"id": "1"}, {"id": "2", "traceId": TRACE, "spanId": "00f067aa0ba902b7"}])
        self.assertEqual(probe.results[-1]["verdict"], "PASS")



ACTIONS_KEY = "https://fabric.passioncode.ai/agent-contract/extensions/actions/0.1"
ACTIONS_VECTORS = json.loads((ROOT / "test/fixtures/contract/actions-vectors.json").read_text())


def with_actions(actions, dashboard=True, capabilities=("sample.echo", "sample.draft")):
    """A well-known document's surfaces and the actions declaration, as the probe reads them."""
    wk = {"surfaces": {"mcp": {"path": "/mcp", "capabilities": list(capabilities)}, "events": {"path": "/e"}}}
    if dashboard:
        wk["surfaces"]["dashboard"] = {"path": "/", "login": True}
    if actions is not None:
        wk["extensions"] = {ACTIONS_KEY: {"actions": actions}}
    return wk


class ProbeActionsRuleTests(unittest.TestCase):
    """DEC-0121 (FAC-SEM-142, D10): the probe's pure verdicts on a declaration and the tools a service lists."""

    def setUp(self):
        self.rules = load("check_service_rules")

    def test_well_known_actions_follows_fac_sem_142_on_every_contract_fixture(self):
        for case in ACTIONS_VECTORS["wellKnowns"]:
            verdict, evidence = self.rules.well_known_actions_verdict(case["document"])
            self.assertEqual(verdict, "FAIL" if case["findings"] else "PASS", "%s: %s" % (case["name"], evidence))
            if case["findings"]:
                self.assertIn("FAC-SEM-142", evidence, case["name"])
                # Each finding is named at its place inside the declaration (the whole key for an invalid one).
                self.assertIn(case["findings"][0].split("~10.1", 1)[1] or "extensions/actions/0.1", evidence, case["name"])

    def test_well_known_actions_is_not_run_without_a_declaration(self):
        verdict, evidence = self.rules.well_known_actions_verdict(with_actions(None))
        self.assertEqual(verdict, "NOT_RUN")
        self.assertIn("extensions/actions/0.1", evidence)
        self.assertEqual(self.rules.well_known_actions_verdict("not a document")[0], "NOT_RUN")

    def test_action_tools_fails_on_a_declared_tool_tools_list_does_not_serve(self):
        actions = [{"id": "approve-draft", "title": "Approve", "tool": "sample.publish", "gate": "relayed"},
                   {"id": "echo", "title": "Echo", "tool": "sample.echo", "gate": "none"}]
        verdict, evidence = self.rules.action_tools_verdict(with_actions(actions, capabilities=["sample.echo", "sample.publish"]),
                                                            {"sample.echo": {}, "sample.draft": {}})
        self.assertEqual(verdict, "FAIL")
        self.assertIn("approve-draft", evidence)
        self.assertIn("sample.publish", evidence)
        self.assertNotIn("sample.echo is not", evidence)

    def test_action_tools_passes_when_every_declared_tool_is_served(self):
        actions = [{"id": "echo", "title": "Echo", "tool": "sample.echo", "gate": "none"},
                   {"id": "draft", "title": "Draft", "tool": "sample.draft", "gate": "relayed"}]
        verdict, evidence = self.rules.action_tools_verdict(with_actions(actions), {"sample.echo": {}, "sample.draft": {}})
        self.assertEqual(verdict, "PASS", evidence)
        self.assertIn("2", evidence)

    def test_action_tools_is_not_run_without_a_readable_declaration_or_a_listing(self):
        self.assertEqual(self.rules.action_tools_verdict(with_actions(None), {"sample.echo": {}})[0], "NOT_RUN")
        invalid = with_actions([{"id": "x", "title": "X", "tool": "sample.echo", "gate": "sometimes"}])
        verdict, evidence = self.rules.action_tools_verdict(invalid, {"sample.echo": {}})
        self.assertEqual(verdict, "NOT_RUN")
        self.assertIn("well-known.actions", evidence)
        ok = with_actions([{"id": "echo", "title": "Echo", "tool": "sample.echo", "gate": "none"}])
        verdict, evidence = self.rules.action_tools_verdict(ok, None, "no readable token")
        self.assertEqual((verdict, evidence), ("NOT_RUN", "no readable token"))

    def test_a_dashboard_without_a_declaration_is_not_run_never_a_failure(self):
        verdict, evidence = self.rules.actions_declared_verdict(with_actions(None))
        self.assertEqual(verdict, "NOT_RUN")
        for words in ("minItems", "read-only", "CT-126", "DEC-0121"):
            self.assertIn(words, evidence)

    def test_a_dashboard_with_a_valid_declaration_passes_and_an_invalid_one_fails(self):
        ok = with_actions([{"id": "echo", "title": "Echo", "tool": "sample.echo", "gate": "none"}])
        self.assertEqual(self.rules.actions_declared_verdict(ok)[0], "PASS")
        bad = with_actions([{"id": "echo", "title": "Echo", "tool": "sample.echo", "gate": "none", "humanStep": "sign-in"}])
        verdict, evidence = self.rules.actions_declared_verdict(bad)
        self.assertEqual(verdict, "FAIL")
        self.assertIn("well-known.actions", evidence)
        self.assertEqual(self.rules.actions_declared_verdict(with_actions(None, dashboard=False))[0], "NOT_RUN")
        self.assertEqual(self.rules.actions_declared_verdict(with_actions([], dashboard=True))[0], "FAIL")  # minItems 1


class ActionsServiceProbeTests(unittest.TestCase):
    """A kit service built here (the sample's code, its well-known document given a declaration; D15: the sample
    itself stays as it is), probed live: PASS, FAIL and NOT_RUN for well-known.actions, interop.action-tools and
    dashboard.actions-declared."""

    def setUp(self):
        import threading
        sample = load("sample_service")
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.services = base / "services"
        port = free_port()
        common = ["--port", str(port), "--data-dir", str(base / "data")]
        test = self

        class ActionsService(sample.Service):
            def well_known(self):
                wk = super().well_known()
                wk["surfaces"]["mcp"]["capabilities"] += test.extra_capabilities
                if test.actions is not None:
                    wk.setdefault("extensions", {})[ACTIONS_KEY] = {"actions": test.actions}
                return wk

        self.actions, self.extra_capabilities = None, []
        self.svc = ActionsService(sample.build_parser().parse_args(["serve"] + common))
        self.svc.start()
        self.server = sample.make_server(self.svc)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self.thread.start()
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):  # register prints the descriptor's path
            registered = sample.register(sample.build_parser().parse_args(["register"] + common + ["--services-dir", str(self.services)]))
        self.assertEqual(registered, 0)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.svc.lock.release()
        self.temp.cleanup()

    def check(self):
        out = subprocess.run([sys.executable, str(SCRIPTS / "check_service.py"), "sample", "--services-dir",
                              str(self.services), "--json"], capture_output=True, text=True)
        return {r["rule"]: r for r in json.loads(out.stdout)["results"]}

    def verdicts(self, results):
        return {rule: results[rule]["verdict"] for rule in ("well-known.actions", "interop.action-tools", "dashboard.actions-declared")}

    def test_a_declaration_whose_tools_are_served_passes(self):
        self.actions = [{"id": "echo", "title": "Echo the text", "tool": "sample.echo", "gate": "none"},
                        {"id": "draft-note", "title": "Draft a note", "tool": "sample.draft", "gate": "relayed"}]
        results = self.check()
        self.assertEqual(self.verdicts(results), {"well-known.actions": "PASS", "interop.action-tools": "PASS",
                                                  "dashboard.actions-declared": "PASS"}, results)

    def test_a_declared_tool_tools_list_does_not_serve_fails(self):
        self.actions = [{"id": "publish-note", "title": "Publish", "tool": "sample.publish", "gate": "relayed"}]
        self.extra_capabilities = ["sample.publish"]  # listed on the surface, so FAC-SEM-142 holds; tools/list lacks it
        results = self.check()
        self.assertEqual(self.verdicts(results), {"well-known.actions": "PASS", "interop.action-tools": "FAIL",
                                                  "dashboard.actions-declared": "PASS"}, results)
        self.assertIn("publish-note", results["interop.action-tools"]["evidence"])

    def test_a_declaration_fac_sem_142_finds_fails(self):
        self.actions = [{"id": "echo", "title": "Echo", "tool": "sample.echo", "gate": "none"},
                        {"id": "echo", "title": "Echo again", "tool": "sample.echo", "gate": "none"}]
        results = self.check()
        self.assertEqual(results["well-known.actions"]["verdict"], "FAIL")
        self.assertIn("declared twice", results["well-known.actions"]["evidence"])

    def test_a_dashboard_with_no_declaration_is_not_run(self):
        results = self.check()
        self.assertEqual(self.verdicts(results), {"well-known.actions": "NOT_RUN", "interop.action-tools": "NOT_RUN",
                                                  "dashboard.actions-declared": "NOT_RUN"}, results)
        self.assertIn("CT-126", results["dashboard.actions-declared"]["evidence"])


if __name__ == "__main__":
    unittest.main()
