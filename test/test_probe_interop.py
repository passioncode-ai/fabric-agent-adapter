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
        self.assertEqual({k: v["evidence"] for k, v in results.items() if v["verdict"] == "FAIL"}, {})
        self.assertEqual(code, 0)
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


if __name__ == "__main__":
    unittest.main()
