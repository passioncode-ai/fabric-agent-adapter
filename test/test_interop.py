"""fabric_interop.py — the kit's fabric-interop/0.1 helpers (contract docs/specification/interop.md)."""

import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(module)
    return module


fi = load("fabric_interop")
fs = load("fabric_service")
PARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
USAGE = {"inputTokens": 10, "outputTokens": 5, "wallMs": 120}
SCOPE = {"project": "urn:fabric:project:example", "run": "urn:fabric:run:r-1", "node": "urn:fabric:node:n-1",
         "binding": {"id": "urn:fabric:binding:b", "revision": 1, "contentHash": "sha256:" + "1" * 64}, "writeScopes": []}


PRODUCER = {"id": "urn:fabric:provider:example-agent", "revision": 1, "contentHash": "sha256:" + "2" * 64}
ENVELOPE_KEYS = ["artifacts", "contractVersion", "createdAt", "done", "id", "notVerified", "outcome", "output", "producer", "proof", "scope", "usage"]
# The canonical job-tool union of the contract (DEC-0017, docs/specification/interop.md, jobToolOutputSchema).
HANDLE = {"type": "object", "required": ["job"], "additionalProperties": False, "properties": {"job": {"type": "object", "required": ["id", "status"], "additionalProperties": False,
          "properties": {"id": {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[A-Za-z0-9._:-]+$"}, "status": {"const": "working"}}}}}


def union(output):
    return {"oneOf": [{"type": "object", "required": ["id", "contractVersion", "outcome", "done", "proof", "scope", "notVerified", "artifacts",
                                                     "createdAt", "producer", "output", "usage"], "properties": {"output": output}}, HANDLE]}


def envelope(**extra):
    base = dict(outcome="partial", done=[{"claimId": "DRAFT", "statement": "A draft was written."}], proof=[], scope=SCOPE,
                not_verified=[{"claim": "DRAFT", "reason": "not checked"}], output={"title": "a"}, usage=USAGE, producer=PRODUCER)
    base.update(extra)
    return fi.result_envelope(**base)


class TraceTests(unittest.TestCase):
    def test_parse_accepts_w3c_and_refuses_the_rest(self):
        self.assertEqual(fi.parse_traceparent(PARENT)["trace_id"], "4bf92f3577b34da6a3ce929d0e0e4736")
        for bad in (PARENT.upper(), "00-" + "0" * 32 + "-00f067aa0ba902b7-01", "00-4bf92f3577b34da6a3ce929d0e0e4736-" + "0" * 16 + "-01",
                    "ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01", "garbage", None):
            self.assertIsNone(fi.parse_traceparent(bad), bad)

    def test_child_keeps_the_trace_and_takes_a_new_span(self):
        child = fi.child_traceparent(PARENT)
        parsed = fi.parse_traceparent(child)
        self.assertEqual(parsed["trace_id"], "4bf92f3577b34da6a3ce929d0e0e4736")
        self.assertNotEqual(parsed["span_id"], "00f067aa0ba902b7")

    def test_a_missing_or_broken_parent_starts_a_new_trace(self):
        for parent in (None, "garbage"):
            self.assertIsNotNone(fi.parse_traceparent(fi.child_traceparent(parent)))

    def test_events_carry_trace_ids_as_a_pair(self):
        span = fi.parse_traceparent(fi.child_traceparent(PARENT))
        event = fs.make_event(1, fs.now_iso(), "job.done", "info", "The draft is ready.", trace_id=span["trace_id"], span_id=span["span_id"])
        self.assertEqual((event["traceId"], event["spanId"]), (span["trace_id"], span["span_id"]))
        with self.assertRaises(fs.ServiceError):
            fs.make_event(1, fs.now_iso(), "job.done", "info", "The draft is ready.", trace_id=span["trace_id"])
        with self.assertRaises(fs.ServiceError):
            fs.make_event(1, fs.now_iso(), "job.done", "info", "The draft is ready.", trace_id="XYZ", span_id="00f067aa0ba902b7")
        self.assertNotIn("traceId", fs.make_event(1, fs.now_iso(), "service.started", "info", "Started."))


class ToolTests(unittest.TestCase):
    def test_annotations_follow_the_declared_effect(self):
        self.assertEqual(fi.expected_annotations("none", "none"), {"readOnlyHint": True})
        self.assertEqual(fi.expected_annotations("delete", "required"), {"destructiveHint": True, "idempotentHint": True})
        self.assertEqual(fi.expected_annotations("publish", "supported"), {})

    def test_a_job_tool_serves_the_union_and_the_capability_keeps_its_output(self):
        out = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
        self.assertEqual(fi.job_tool_output_schema(out), union(out))
        for cap in ({"name": "example.draft", "effect": "draft", "idempotency": "none", "job": True},
                    {"name": "example.draft", "effect": "draft", "idempotency": "none", "extensions": {fi.EXTENSION_KEY: {"job": True}}}):
            self.assertEqual(fi.tool_for_capability(cap, {"type": "object"}, out)["outputSchema"], union(out))
        self.assertIs(fi.tool_for_capability({"name": "example.echo", "effect": "none", "idempotency": "none"}, {"type": "object"}, out)["outputSchema"], out)

    def test_a_capability_is_served_as_a_tool_of_the_same_name(self):
        schema_in = {"type": "object", "properties": {"text": {"type": "string"}}}
        schema_out = {"type": "object"}
        tool = fi.tool_for_capability({"name": "example.echo", "effect": "none", "idempotency": "required"}, schema_in, schema_out)
        self.assertEqual(tool["name"], "example.echo")
        self.assertIs(tool["inputSchema"], schema_in)
        self.assertIs(tool["outputSchema"], schema_out)
        self.assertEqual(tool["annotations"], {"readOnlyHint": True, "idempotentHint": True})


class EnvelopeAndChoiceTests(unittest.TestCase):
    def test_envelope_is_the_full_result_envelope(self):
        env = envelope()
        self.assertEqual(sorted(env), ENVELOPE_KEYS)
        self.assertEqual(env["contractVersion"], "0.1.0")
        self.assertTrue(env["id"].startswith("urn:fabric:result:"))
        traced = envelope(traceparent=PARENT)
        self.assertEqual(traced["trace"], {"traceparent": PARENT})
        self.assertNotIn("trace", envelope(traceparent="garbage"))

    def test_envelope_refuses_succeeded_with_unverified_claims(self):
        with self.assertRaises(fi.InteropError):
            envelope(outcome="succeeded")
        with self.assertRaises(fi.InteropError):
            envelope(outcome="done")
        self.assertEqual(envelope(outcome="succeeded", not_verified=[])["outcome"], "succeeded")

    def test_envelope_refuses_bad_usage(self):
        with self.assertRaises(fi.InteropError):
            envelope(usage={"inputTokens": 1, "outputTokens": -1, "wallMs": 1})
        with self.assertRaises(fi.InteropError):
            envelope(usage={"inputTokens": 1})

    def test_choice_is_a_titled_single_select(self):
        req = fi.choice_request("Pick the title.", "title", [("a", "Choosing a title"), ("b", "How titles work")])
        field = req["params"]["requestedSchema"]["properties"]["title"]
        self.assertEqual(req["method"], "elicitation/create")
        self.assertEqual(req["params"]["mode"], "form")
        self.assertEqual(field["oneOf"], [{"const": "a", "title": "Choosing a title"}, {"const": "b", "title": "How titles work"}])

    def test_form_mode_never_asks_for_a_secret(self):
        for field in ("api_key", "password", "accessToken"):
            with self.assertRaises(fi.InteropError, msg=field):
                fi.form_request("Paste it.", {field: {"type": "string"}})
        with self.assertRaises(fi.InteropError):
            fi.form_request("Paste it.", {"value": {"type": "string", "title": "Your secret key"}})
        self.assertEqual(fi.url_request("Connect the account.", "https://publish.example/connect")["params"]["mode"], "url")


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name) / "jobs"

    def tearDown(self):
        self.temp.cleanup()

    def test_handle_then_state_survive_a_restart(self):
        handle = fi.JobStore(self.dir).create("example.draft", {"topic": "t"}, traceparent=PARENT)
        self.assertEqual(handle, {"job": {"id": handle["job"]["id"], "status": "working"}})
        again = fi.JobStore(self.dir)
        job = again.get(handle["job"]["id"])
        self.assertEqual(job["status"], "working")
        self.assertIn("updatedAt", job)
        path = self.dir / (handle["job"]["id"] + ".json")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(fi.parse_traceparent(again.traceparent(handle["job"]["id"]))["trace_id"], "4bf92f3577b34da6a3ce929d0e0e4736")

    def test_unknown_job_is_an_error_never_a_fresh_job(self):
        store = fi.JobStore(self.dir)
        with self.assertRaises(fi.UnknownJob):
            store.get("job_nope")
        result = fi.unknown_job_result("job_nope")
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["code"], "unknown-job")
        self.assertEqual(list(self.dir.glob("*.json")) if self.dir.exists() else [], [])

    def test_lifecycle_through_a_choice(self):
        store = fi.JobStore(self.dir)
        job_id = store.create("example.draft", {})["job"]["id"]
        choice = fi.choice_request("Pick the title.", "title", [("a", "A"), ("b", "B")])
        state = store.request_input(job_id, {"title_choice": choice}, "Two titles are ready.")
        self.assertEqual(state["status"], "input_required")
        self.assertIn("title_choice", state["inputRequests"])
        answers = store.answer(job_id, {"title_choice": {"action": "accept", "content": {"title": "a"}}})
        self.assertEqual(answers["title_choice"]["content"]["title"], "a")
        self.assertEqual(store.get(job_id)["status"], "working")
        self.assertNotIn("inputRequests", store.get(job_id))
        done = store.complete(job_id, envelope())
        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["result"]["usage"], USAGE)
        with self.assertRaises(fi.InteropError):
            store.cancel(job_id)

    def test_the_envelope_carries_the_job_trace_and_must_agree_with_it(self):
        store = fi.JobStore(self.dir)
        job_id = store.create("example.draft", {}, traceparent=PARENT)["job"]["id"]
        self.assertEqual(store.complete(job_id, envelope())["result"]["trace"], {"traceparent": PARENT})
        other = store.create("example.draft", {}, traceparent=PARENT)["job"]["id"]
        with self.assertRaises(fi.InteropError):
            store.complete(other, envelope(traceparent=fi.child_traceparent(PARENT)))
        self.assertEqual(store.get(other)["status"], "working")

    def test_answers_for_unknown_keys_are_ignored(self):
        store = fi.JobStore(self.dir)
        job_id = store.create("example.draft", {})["job"]["id"]
        store.request_input(job_id, {"k": fi.choice_request("Pick.", "x", [("a", "A")])}, "Pick one.")
        self.assertEqual(store.answer(job_id, {"other": {"action": "accept"}}), {})
        self.assertEqual(store.get(job_id)["status"], "input_required")

    def test_failure_and_cancellation_are_terminal(self):
        store = fi.JobStore(self.dir)
        failed = store.create("example.draft", {})["job"]["id"]
        self.assertEqual(store.fail(failed, -32603, "The model was unavailable.")["error"]["code"], -32603)
        cancelled = store.create("example.draft", {})["job"]["id"]
        self.assertEqual(store.cancel(cancelled)["status"], "cancelled")
        with self.assertRaises(fi.InteropError):
            store.complete(cancelled, envelope())


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.jobs = fi.JobStore(Path(self.temp.name) / "jobs")
        echo = fi.tool_for_capability({"name": "example.echo", "effect": "none", "idempotency": "required"},
                                      {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                                      {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]})
        draft = fi.tool_for_capability({"name": "example.draft", "effect": "draft", "idempotency": "none"}, {"type": "object"}, {"type": "object"})
        self.server = fi.McpToolServer("example-agent", "1.0.0", jobs=self.jobs)
        self.server.add_tool(echo, lambda args, ctx: {"text": args["text"]})
        self.server.add_tool(draft, lambda args, ctx: ctx.start_job())

    def tearDown(self):
        self.temp.cleanup()

    def call(self, method, params=None, rid=1, traceparent=PARENT):
        params = dict(params or {})
        meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}
        if traceparent:
            meta["traceparent"] = traceparent
        params["_meta"] = meta
        return self.server.handle({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})

    def test_tools_list_names_the_capabilities_and_the_job_tools(self):
        names = [tool["name"] for tool in self.call("tools/list")["result"]["tools"]]
        self.assertEqual(names, ["example.echo", "example.draft", "fabric.job.get", "fabric.job.cancel"])

    def test_a_call_answers_as_a_child_span_of_the_caller(self):
        response = self.call("tools/call", {"name": "example.echo", "arguments": {"text": "hi"}})
        result = response["result"]
        self.assertEqual(result["structuredContent"], {"text": "hi"})
        self.assertFalse(result["isError"])
        span = fi.parse_traceparent(result["_meta"]["traceparent"])
        self.assertEqual(span["trace_id"], "4bf92f3577b34da6a3ce929d0e0e4736")
        self.assertNotEqual(span["span_id"], "00f067aa0ba902b7")

    def test_a_job_capability_returns_a_handle_and_job_get_finds_it(self):
        handle = self.call("tools/call", {"name": "example.draft", "arguments": {}})["result"]["structuredContent"]
        self.assertEqual(handle["job"]["status"], "working")
        got = self.call("tools/call", {"name": "fabric.job.get", "arguments": {"id": handle["job"]["id"]}})["result"]
        self.assertEqual(got["structuredContent"]["job"]["id"], handle["job"]["id"])
        self.assertEqual(fi.parse_traceparent(got["_meta"]["traceparent"])["trace_id"], "4bf92f3577b34da6a3ce929d0e0e4736")
        self.jobs.complete(handle["job"]["id"], envelope())
        done = self.call("tools/call", {"name": "fabric.job.get", "arguments": {"id": handle["job"]["id"]}})["result"]
        self.assertEqual(done["_meta"]["traceparent"], done["structuredContent"]["job"]["result"]["trace"]["traceparent"])

    def test_an_unknown_job_is_an_error_result(self):
        result = self.call("tools/call", {"name": "fabric.job.get", "arguments": {"id": "job_missing"}})["result"]
        self.assertTrue(result["isError"])
        self.assertIn("unknown-job", result["content"][0]["text"])

    def test_protocol_errors(self):
        self.assertEqual(self.call("resources/list")["error"]["code"], -32601)
        self.assertEqual(self.call("tools/call", {"name": "nope", "arguments": {}})["error"]["code"], -32602)
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}}))

    def test_a_request_without_trace_context_starts_a_new_trace(self):
        result = self.call("tools/call", {"name": "example.echo", "arguments": {"text": "hi"}}, traceparent=None)["result"]
        self.assertIsNotNone(fi.parse_traceparent(result["_meta"]["traceparent"]))


if __name__ == "__main__":
    unittest.main()
