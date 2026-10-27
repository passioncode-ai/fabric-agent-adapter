"""fabric_interop.py — the kit's fabric-interop/0.1 helpers (contract docs/specification/interop.md)."""

import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock


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
    return {"type": "object", "oneOf": [{"type": "object", "required": ["id", "contractVersion", "outcome", "done", "proof", "scope", "notVerified", "artifacts",
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

    def test_an_output_schema_that_is_not_object_rooted_is_refused(self):
        for bad in ({"type": "array", "items": {"type": "string"}}, {"oneOf": [{"type": "object"}]}, {"type": "string"}):
            with self.assertRaises(fi.InteropError, msg=bad):
                fi.tool_for_capability({"name": "example.echo", "effect": "none", "idempotency": "none"}, {"type": "object"}, bad)
        server = fi.McpToolServer("example-agent", "1.0.0")
        with self.assertRaises(fi.InteropError):
            server.add_tool({"name": "example.raw", "inputSchema": {"type": "object"}, "outputSchema": {"oneOf": [{"type": "object"}]}}, lambda a, c: {})

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

    def test_url_mode_hands_over_an_open_link_never_a_raw_local_address(self):
        """DEC-0123 PL-4, FAC-SEM-143 (D12 of the 0.51.0 brief): a URL-mode request on the service's own page carries
        its open_link; a raw loopback address and a fabric-dashboards: link outside the grammar are refused when the
        request is built."""
        link = "fabric-dashboards://service/example-agent.default?path=%2Fdashboard%2Fdrafts%2F7"
        self.assertEqual(fi.url_request("Approve the draft.", link)["params"]["url"], link)
        self.assertEqual(fi.url_request("Open it.", "fabric-dashboards://service/example-agent.default")["params"]["mode"], "url")
        for url in ("http://127.0.0.1:4100/x", "http://localhost:4100/dashboard", "http://127.1/", "https://127.0.0.1/",
                    "http://[::1]:4100/", "http://0/", "http://loc%61lhost/", "fabric-dashboards://open?service=example-agent.default",
                    "fabric-dashboards://service/Bad", " fabric-dashboards://service/example-agent.default?path=x",
                    "http://agents.example/", "ftp://files.example/", "/dashboard"):
            with self.subTest(url), self.assertRaises(fi.InteropError):
                fi.url_request("Open it.", url)
        with self.assertRaises(fi.InteropError) as refused:
            fi.url_request("Open it.", "http://127.0.0.1:4100/x")
        self.assertIn("open_link", str(refused.exception))
        self.assertIn("DEC-0123", str(refused.exception))

    def test_page_answer_is_pl4s_shape(self):
        self.assertEqual(fi.page_answer("example-agent", "default"), {"open_link": "fabric-dashboards://service/example-agent.default"})
        self.assertEqual(fi.page_answer("example-agent", "default", "/jobs/7", http_url="http://127.0.0.1:4100/jobs/7"),
                         {"open_link": "fabric-dashboards://service/example-agent.default?path=%2Fjobs%2F7",
                          "http_url": "http://127.0.0.1:4100/jobs/7"})
        for args in (("Example", "default"), ("example-agent", "default", "jobs"), ("example-agent", "default", "/x?token=abc")):
            with self.subTest(args), self.assertRaises(fi.InteropError):
                fi.page_answer(*args)


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

    def test_a_url_mode_request_on_a_raw_local_address_is_refused_at_request_input(self):
        """FAC-SEM-143 on kind interop-input-requests: a hand-built URL-mode request with a loopback url never reaches
        the job; the job stays working."""
        store = fi.JobStore(self.dir)
        job_id = store.create("example.draft", {})["job"]["id"]
        raw = {"method": "elicitation/create", "params": {"mode": "url", "message": "Approve.", "url": "http://127.0.0.1:4100/x"}}
        with self.assertRaises(fi.InteropError) as refused:
            store.request_input(job_id, {"approve": raw})
        self.assertIn("/inputRequests/approve/params/url", str(refused.exception))
        self.assertEqual(store.get(job_id)["status"], "working")
        link = fi.url_request("Approve.", "fabric-dashboards://service/example-agent.default?path=%2Fdrafts%2F7")
        self.assertEqual(store.request_input(job_id, {"approve": link})["status"], "input_required")

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

    def test_initialize_handshake_for_clients_that_still_send_it(self):
        # Claude Code 2.1.285 opens every HTTP server with initialize; without it the server is "failed".
        for asked, answered in (("2025-06-18", "2025-06-18"), ("2025-11-25", "2025-11-25"), ("2026-07-28", "2026-07-28"), ("1999-01-01", fi.MCP_REVISION)):
            result = self.server.handle({"jsonrpc": "2.0", "id": 7, "method": "initialize",
                                         "params": {"protocolVersion": asked, "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}})["result"]
            self.assertEqual(result["protocolVersion"], answered, asked)
            self.assertIn("tools", result["capabilities"])
            self.assertEqual(result["serverInfo"]["name"], "example-agent")
        self.assertEqual(self.server.handle({"jsonrpc": "2.0", "id": 8, "method": "ping"})["result"], {})
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_every_listed_output_schema_is_object_rooted(self):
        for tool in self.call("tools/list")["result"]["tools"]:
            if "outputSchema" in tool:
                self.assertEqual(tool["outputSchema"].get("type"), "object", tool["name"])

    def test_protocol_errors(self):
        self.assertEqual(self.call("resources/list")["error"]["code"], -32601)
        self.assertEqual(self.call("tools/call", {"name": "nope", "arguments": {}})["error"]["code"], -32602)
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}}))

    def test_params_that_are_not_objects_are_invalid_params(self):
        """Finding 17: a non-object params, _meta or arguments, or a name that is no string, crashed the handler."""
        for params in ("x", [1], 5, True, {"_meta": "x"}, {"_meta": [1]}, {"_meta": []}, {"_meta": 0}, {"name": "example.echo", "arguments": "x"},
                       {"name": "example.echo", "arguments": [1]}, {"name": ["example.echo"]}, {"name": {"a": 1}},
                       {"name": "fabric.job.get", "arguments": "job_x"}, {"name": "fabric.job.cancel", "arguments": [1]}):
            with self.subTest(params=params):
                response = self.server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": params},
                                              {"Mcp-Method": "tools/call"})
                self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("result", self.server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": None}))

    def test_a_request_without_trace_context_starts_a_new_trace(self):
        result = self.call("tools/call", {"name": "example.echo", "arguments": {"text": "hi"}}, traceparent=None)["result"]
        self.assertIsNotNone(fi.parse_traceparent(result["_meta"]["traceparent"]))


if __name__ == "__main__":
    unittest.main()


class McpStandardHeaderTests(unittest.TestCase):
    """MCP 2026-07-28 Streamable HTTP: Mcp-Method on every request, Mcp-Name on tools/call,
    prompts/get and resources/read; a server rejects a mismatch (the official server SDK answers
    -32020, and a local agent's live server did on 2026-10-04 when the probe omitted them)."""

    CALL = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "sample.echo", "arguments": {}}}

    def test_a_declared_2026_request_without_the_headers_is_refused(self):
        self.assertIn("Mcp-Method header is absent", fi.mcp_header_problem(self.CALL, {"MCP-Protocol-Version": fi.MCP_REVISION}))
        self.assertIn("Mcp-Name header is absent", fi.mcp_header_problem(self.CALL, {"mcp-protocol-version": fi.MCP_REVISION, "mcp-method": "tools/call"}))

    def test_headers_that_disagree_with_the_body_are_refused_whatever_the_revision(self):
        self.assertIn("disagrees", fi.mcp_header_problem(self.CALL, {"Mcp-Method": "tools/list"}))
        self.assertIn("Mcp-Name disagrees", fi.mcp_header_problem(self.CALL, {"Mcp-Method": "tools/call", "Mcp-Name": "other"}))
        read = {"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": "file:///a"}}
        self.assertIn("params.uri", fi.mcp_header_problem(read, {"Mcp-Method": "resources/read", "Mcp-Name": "file:///b"}))

    # MCP 2026-07-28 Streamable HTTP, "Value Encoding": the spec's own examples.
    SPEC_EXAMPLES = (("us-west1", "us-west1"), ("Hello, 世界", "=?base64?SGVsbG8sIOS4lueVjA==?="),
                     (" padded ", "=?base64?IHBhZGRlZCA=?="), ("line1\nline2", "=?base64?bGluZTEKbGluZTI=?="),
                     ("=?base64?literal?=", "=?base64?PT9iYXNlNjQ/bGl0ZXJhbD89?="))

    def test_header_values_use_the_base64_sentinel_exactly_as_the_spec_shows(self):
        for value, header in self.SPEC_EXAMPLES:
            self.assertEqual(fi.encode_header_value(value), header, value)
            self.assertEqual(fi.decode_header_value(header), value, value)

    def test_a_name_outside_the_safe_set_is_sent_encoded_and_checked_decoded(self):
        call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "погода", "arguments": {}}}
        headers = fi.mcp_request_headers("tools/call", call["params"])
        self.assertTrue(headers["Mcp-Name"].startswith("=?base64?"))
        self.assertIsNone(fi.mcp_header_problem(call, headers), "a server decodes before comparing")
        self.assertIn("disagrees", fi.mcp_header_problem(call, dict(headers, **{"Mcp-Name": fi.encode_header_value("другое")})))
        self.assertIn("malformed", fi.mcp_header_problem(call, dict(headers, **{"Mcp-Name": "=?base64?***?="})))
        self.assertIn("malformed", fi.mcp_header_problem(call, dict(headers, **{"Mcp-Name": "погода"})), "raw non-ASCII is invalid")

    def test_matching_headers_and_earlier_clients_pass(self):
        self.assertIsNone(fi.mcp_header_problem(self.CALL, fi.mcp_request_headers("tools/call", self.CALL["params"])))
        self.assertIsNone(fi.mcp_header_problem(self.CALL, {}), "an earlier revision may omit them")
        self.assertIsNone(fi.mcp_header_problem(self.CALL, None), "a caller that passes no headers keeps the old behaviour")
        self.assertEqual(fi.mcp_request_headers("tools/list", {}), {"MCP-Protocol-Version": fi.MCP_REVISION, "Mcp-Method": "tools/list"})

    def test_the_server_answers_a_mismatch_with_the_header_error(self):
        server = fi.McpToolServer("sample", "0.0.1")
        answer = server.handle(self.CALL, {"MCP-Protocol-Version": fi.MCP_REVISION})
        self.assertEqual(answer["error"]["code"], fi.HEADER_MISMATCH)
        listed = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}, fi.mcp_request_headers("tools/list", {}))
        self.assertIn("tools", listed["result"])


# --- DEC-0121: a tool registered with an action runs action_decision (REQ-7, REQ-8, D8, D9, D11) -----------------

fa = load("fabric_actions")
fd = load("fabric_delegation")
NOW = "2026-10-24T09:30:00Z"
NOW_SECONDS = 1_792_834_200  # NOW as epoch seconds
RELAYED = {"id": "approve-reply", "title": "Approve the reply", "tool": "reviews.approve", "gate": "relayed"}
NONE = {"id": "retry-job", "title": "Retry", "tool": "jobs.retry", "gate": "none"}
HUMAN = {"id": "connect-store", "title": "Connect the store", "tool": "accounts.connect", "gate": "human", "humanStep": "consent"}
DECISION = {"by": "operator", "via": "relayed-instruction", "action": "approve-reply", "target": "reply-7",
            "instruction": "Agent: Approve the reply to Anna? Operator: yes", "at": "2026-10-24T09:29:00Z"}
OBJECT = {"type": "object"}


class ActionGateTests(unittest.TestCase):
    """McpToolServer runs fabric_actions.action_decision for a tool registered with an action, after the authorize
    gate and before the handler; a refusal is DL-19's structuredContent; the handler gets the record."""

    def server(self, **options):
        self.seen = []
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.jobs = fi.JobStore(Path(self.temp.name) / "jobs")
        options.setdefault("clock", lambda: NOW_SECONDS)
        server = fi.McpToolServer("example-agent", "1.0.0", jobs=self.jobs, **options)
        keep = lambda args, ctx: self.seen.append(ctx) or {"done": True}
        server.add_tool({"name": "reviews.approve", "inputSchema": OBJECT}, keep, action=RELAYED, target="reply")
        server.add_tool({"name": "jobs.retry", "inputSchema": OBJECT}, keep, action=NONE)
        server.add_tool({"name": "accounts.connect", "inputSchema": OBJECT}, keep, action=HUMAN, human_step_url="/connect/store")
        server.add_tool({"name": "example.echo", "inputSchema": OBJECT}, keep)
        server.add_tool({"name": "example.ask", "inputSchema": OBJECT}, lambda args, ctx: ctx.start_job())
        return server

    def call(self, server, name, arguments=None, meta=None, tier="T0", headers=None):
        params = {"name": name, "arguments": {"reply": "reply-7"} if arguments is None else arguments,
                  "_meta": dict({"traceparent": PARENT}, **(meta or {}))}
        return server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}, headers, tier=tier)["result"]

    def refusal(self, result):
        self.assertTrue(result["isError"])
        error = result["structuredContent"]["error"]
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        self.assertTrue(1 <= len(error["data"]["detail"]) <= 80)
        self.assertEqual(error["message"], fd.REFUSAL_MESSAGES[error["code"]])
        return error

    def test_arguments_with_no_canonical_form_are_answered_never_raised(self):
        # Seam reading of 0.50.0: a lone surrogate or a non-finite number has no JCS form, so no digest; the call is
        # answered -32602 at every tier, and a tool with no action still takes it as before.
        for tier in ("T0", "T1", "T2"):
            deep = json.loads('[' * 900 + '1' + ']' * 900)  # past the JCS recursion, still valid JSON
            for bad in ("\ud800", float("nan"), float("inf"), deep):
                with self.subTest(tier=tier, bad=repr(bad)):
                    server = self.server()
                    params = {"name": "reviews.approve", "arguments": {"reply": "reply-7", "x": bad}, "_meta": {"traceparent": PARENT}}
                    answer = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}, None, tier=tier)
                    self.assertEqual(answer["error"]["code"], -32602, answer)
                    self.assertEqual(self.seen, [])
                    plain = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                           "params": {"name": "example.echo", "arguments": {"x": bad}, "_meta": {"traceparent": PARENT}}}, None, tier=tier)
                    self.assertFalse(plain["result"]["isError"])

    def test_a_service_fault_reaches_on_fault_and_never_the_caller(self):
        faults = []
        server = self.server(on_fault=lambda tool, fault: faults.append((tool, fault)))
        error = self.refusal(self.call(server, "reviews.approve", meta={"decision": DECISION}, tier="T2"))
        self.assertEqual((error["code"], error["data"]["detail"]), ("unknown-state", "service-fault"))
        self.assertEqual(faults, [("reviews.approve", "caller-missing")])
        faults.clear()
        server = self.server(on_fault=lambda tool, fault: faults.append((tool, fault)), approve=lambda *a: {"ok": False, "code": "weird"},
                             identify=lambda headers, tier: "agent:example")
        error = self.refusal(self.call(server, "reviews.approve", meta={"decision": DECISION}, tier="T2"))
        self.assertEqual((error["code"], error["data"]["detail"]), ("unknown-state", "service-fault"))
        self.assertEqual(faults, [("reviews.approve", "approval-outcome-unreadable")])

    def test_a_relayed_action_from_t0_without_a_decision_is_operator_decision_required(self):
        server = self.server()
        error = self.refusal(self.call(server, "reviews.approve"))
        self.assertEqual((error["code"], error["data"]), ("operator-decision-required", {"detail": "no-decision"}))
        self.assertEqual(self.seen, [])

    def test_a_valid_decision_runs_the_tool_and_records_the_operator_with_the_authenticated_caller(self):
        for tier in ("T0", "T1"):
            with self.subTest(tier):
                server = self.server()
                result = self.call(server, "reviews.approve", {"reply": "reply-7", "caller": "agent:claimed"},
                                   {"decision": DECISION, "caller": "agent:claimed"}, tier=tier)
                self.assertFalse(result["isError"])
                ctx = self.seen[-1]
                self.assertEqual(ctx.record, {"by": "operator", "via": "relayed-instruction", "caller": "local:" + tier})
                self.assertEqual((ctx.tier, ctx.caller, ctx.decision), (tier, "local:" + tier, DECISION))
        server = self.server(identify=lambda headers, tier: "agent:" + headers["X-Agent"])
        self.call(server, "reviews.approve", meta={"decision": DECISION}, headers={"X-Agent": "claude-code"})
        self.assertEqual(self.seen[-1].record["caller"], "agent:claude-code")

    def test_a_caller_the_authorize_gate_accepted_is_the_one_recorded(self):
        gate = lambda tool, headers, tier="T2": {"ok": True, "tier": tier, "principal": "person:p", "caller": "agent:token-caller"}
        server = self.server(authorize=gate, identify=lambda headers, tier: "agent:not-this")
        self.call(server, "reviews.approve", meta={"decision": DECISION})
        self.assertEqual(self.seen[-1].record["caller"], "agent:token-caller")
        self.assertEqual(self.seen[-1].delegation["caller"], "agent:token-caller")
        refusing = self.server(authorize=lambda tool, headers, tier="T2": {"ok": False, "code": "unauthenticated", "detail": "no-token"})
        self.assertEqual(self.refusal(self.call(refusing, "reviews.approve", tier="T2"))["code"], "unauthenticated")

    def test_a_t2_caller_is_asked_for_an_approval_with_the_digest_and_its_decision_changes_nothing(self):
        server = self.server(identify=lambda headers, tier: "agent:remote")
        error = self.refusal(self.call(server, "reviews.approve", meta={"decision": DECISION}, tier="T2"))
        digest = fd.action_digest({"tool": "reviews.approve", "arguments": {"reply": "reply-7"}})
        self.assertEqual((error["code"], error["data"]), ("approval-required", {"detail": "no-approval", "actionDigest": digest}))
        self.assertEqual(self.seen, [])

    def test_an_accepted_approval_is_the_approvers_and_a_bad_one_is_refused_as_verified(self):
        asked = []
        def approve(tool, arguments, headers, digest):
            asked.append((tool, digest))
            return headers.get("approval")
        server = self.server(identify=lambda headers, tier: "agent:remote", approve=approve)
        ok = {"ok": True, "approver": "person:operator", "method": "passkey", "claims": {}, "kid": "k"}
        self.call(server, "reviews.approve", tier="T2", headers={"approval": ok})
        self.assertEqual(self.seen[-1].record, {"by": "person:operator", "via": "approval", "caller": "agent:remote"})
        bad = {"ok": False, "code": "approval-reused", "detail": "jti-consumed"}
        self.assertEqual(self.refusal(self.call(server, "reviews.approve", tier="T2", headers={"approval": bad}))["code"], "approval-reused")
        missing = {"ok": False, "code": "approval-required", "detail": "no-approval", "data": {"actionDigest": "sha256:" + "0" * 64}}
        self.assertEqual(self.refusal(self.call(server, "reviews.approve", tier="T2", headers={"approval": missing}))["data"]["actionDigest"],
                         fd.action_digest({"tool": "reviews.approve", "arguments": {"reply": "reply-7"}}))
        for malformed in ({"ok": False, "code": "approval-invalid"}, {"ok": False, "code": "not-a-code", "detail": "x"}):
            with self.subTest(malformed=malformed):  # an outcome that is not verify_approval's is the service's fault
                error = self.refusal(self.call(server, "reviews.approve", tier="T2", headers={"approval": malformed}))
                self.assertEqual((error["code"], error["data"]["detail"]), ("unknown-state", "service-fault"))
        self.call(server, "jobs.retry", tier="T2", headers={"approval": ok})  # an action that needs no decision spends no approval
        self.assertEqual([tool for tool, _ in asked], ["reviews.approve"] * 5)

    def test_a_t2_call_with_no_identity_is_the_services_fault(self):
        error = self.refusal(self.call(self.server(), "reviews.approve", meta={"decision": DECISION}, tier="T2"))
        self.assertEqual((error["code"], error["data"]["detail"]), ("unknown-state", "service-fault"))

    def test_a_human_step_is_refused_with_its_step_and_link_at_every_tier(self):
        for tier in ("T0", "T1", "T2"):
            with self.subTest(tier):
                server = self.server()
                error = self.refusal(self.call(server, "accounts.connect", {}, {"decision": dict(DECISION, action="connect-store")}, tier=tier))
                self.assertEqual((error["code"], error["data"]),
                                 ("human-step-required", {"detail": "human-step", "humanStep": "consent", "url": "/connect/store"}))
                self.assertEqual(self.seen, [])

    def test_an_action_of_the_callers_own_runs_without_a_decision(self):
        server = self.server()
        self.assertFalse(self.call(server, "jobs.retry", {})["isError"])
        self.assertEqual((self.seen[-1].record, self.seen[-1].decision), ("caller", None))

    def test_a_decision_in_the_arguments_is_ignored(self):
        server = self.server()
        error = self.refusal(self.call(server, "reviews.approve", {"reply": "reply-7", "decision": DECISION, "_meta": {"decision": DECISION}}))
        self.assertEqual(error["code"], "operator-decision-required")

    def test_a_decision_that_is_not_valid_for_this_call_is_decision_invalid(self):
        bad = {
            "another action": dict(DECISION, action="reject-reply"),
            "another object": dict(DECISION, target="reply-8"),
            "an hour ahead": dict(DECISION, at="2026-10-24T10:30:00Z"),
            "two days old": dict(DECISION, at="2026-10-22T09:30:00Z"),
            "a decision named an elicitation": dict(DECISION, via="elicitation"),
            "not the operator": dict(DECISION, by="agent"),
            "null": None,
            "a string": "yes",
        }
        for name, decision in bad.items():
            with self.subTest(name):
                server = self.server()
                error = self.refusal(self.call(server, "reviews.approve", meta={"decision": decision}))
                self.assertEqual((error["code"], error["data"]), ("decision-invalid", {"detail": "invalid-decision"}))
                self.assertEqual(self.seen, [])

    def test_the_services_own_elicitation_record_is_the_operators_decision(self):
        records = []
        server = self.server(elicited=lambda tool, arguments, caller: records.append((tool, caller)) or True)
        self.call(server, "reviews.approve")
        self.assertEqual(self.seen[-1].record, {"by": "operator", "via": "elicitation", "caller": "local:T0"})
        self.assertEqual(records, [("reviews.approve", "local:T0")])
        server = self.server(elicited=lambda tool, arguments, caller: "yes")  # only True is a record
        self.assertEqual(self.refusal(self.call(server, "reviews.approve"))["code"], "operator-decision-required")

    def test_a_tool_without_an_action_is_unchanged(self):
        server = self.server()
        self.assertFalse(self.call(server, "example.echo", {}, {"decision": "not even a decision"}, tier="T2")["isError"])
        self.assertEqual((self.seen[-1].record, self.seen[-1].decision), (None, None))

    def test_the_action_table_is_what_was_registered_and_a_bad_one_is_refused(self):
        server = self.server()
        self.assertEqual(server.action_table(), [RELAYED, NONE, HUMAN])
        doc = fs.build_well_known(service_id="example-agent", instance="default", name="Example", version="1.0.0",
                                  build={"commit": "0" * 40}, started_at=NOW, status="ready", degraded=[],
                                  surfaces={"events": {"path": "/fabric/v1/events"},
                                            "mcp": {"path": "/mcp", "transport": "streamable-http",
                                                    "capabilities": [t["name"] for t in server.tools]}},
                                  actions=server.action_table())
        self.assertEqual(fa.actions_view(doc)["actions"], [RELAYED, NONE, HUMAN])
        bad = {
            "another tool": ({"name": "reviews.reject"}, RELAYED, {}),
            "an unknown gate": ({"name": "reviews.approve"}, dict(RELAYED, gate="page"), {}),
            "a human step without its link": ({"name": "accounts.connect"}, HUMAN, {}),
            "a link that is neither https nor a path": ({"name": "accounts.connect"}, HUMAN, {"human_step_url": "http://x"}),
            "a target that is neither a name nor a function": ({"name": "reviews.approve"}, RELAYED, {"target": 7}),
        }
        for name, (tool, action, extra) in bad.items():
            with self.subTest(name), self.assertRaises(fi.InteropError):
                fi.McpToolServer("x", "1").add_tool(dict(tool, inputSchema=OBJECT), lambda a, c: {}, action=action, **extra)

    def test_a_target_function_names_the_object(self):
        server = fi.McpToolServer("x", "1", clock=lambda: NOW_SECONDS)
        seen = []
        server.add_tool({"name": "reviews.approve", "inputSchema": OBJECT}, lambda a, c: seen.append(c.record) or {},
                        action=RELAYED, target=lambda arguments: arguments["review"]["reply"])
        self.assertFalse(self.call(server, "reviews.approve", {"review": {"reply": "reply-7"}}, {"decision": DECISION})["isError"])
        self.assertTrue(self.call(server, "reviews.approve", {"review": {"reply": "reply-8"}}, {"decision": DECISION})["isError"])
        self.assertEqual(len(seen), 1)


class InputActionTests(unittest.TestCase):
    """D8: a job's input request is an action (id its key, tool fabric.job.get, gate relayed), gated per key only when
    the service opts in with input_actions=True; off by default."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def start(self, **options):
        self.inputs = []
        jobs = fi.JobStore(Path(self.temp.name) / ("jobs-%d" % len(os.listdir(self.temp.name))))
        server = fi.McpToolServer("example-agent", "1.0.0", jobs=jobs, clock=lambda: NOW_SECONDS,
                                  on_input=lambda job_id, matched, ctx: self.inputs.append((matched, ctx)), **options)
        server.add_tool({"name": "example.ask", "inputSchema": OBJECT}, lambda args, ctx: ctx.start_job())
        handle = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": "example.ask", "arguments": {}}})["result"]["structuredContent"]
        job_id = handle["job"]["id"]
        jobs.request_input(job_id, {"pick": fi.choice_request("Which?", "choice", [("a", "A"), ("b", "B")]),
                                    "note": fi.form_request("A note?", {"text": {"type": "string"}})})
        return server, jobs, job_id

    def answer(self, server, job_id, responses, decision=None, tier="T0"):
        meta = {"traceparent": PARENT}
        if decision is not None:
            meta["decision"] = decision
        return server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                              "params": {"name": "fabric.job.get", "arguments": {"id": job_id, "inputResponses": responses},
                                         "_meta": meta}}, tier=tier)["result"]

    def key_decision(self, key):
        return {"by": "operator", "via": "relayed-instruction", "action": key, "instruction": "Agent: Which? Operator: a", "at": NOW}

    def test_off_by_default_the_answer_is_taken_as_before(self):
        server, jobs, job_id = self.start()
        result = self.answer(server, job_id, {"pick": {"action": "accept", "content": {"choice": "a"}}})
        self.assertFalse(result["isError"])
        self.assertEqual(jobs.get(job_id)["status"], "working")
        self.assertEqual(list(self.inputs[0][0]), ["pick"])
        self.assertIsNone(self.inputs[0][1].input_records)

    def test_on_an_answer_without_a_decision_is_refused_and_nothing_is_applied(self):
        server, jobs, job_id = self.start(input_actions=True)
        error = self.answer(server, job_id, {"pick": {"action": "accept", "content": {"choice": "a"}}})["structuredContent"]["error"]
        self.assertEqual(error["code"], "operator-decision-required")
        self.assertEqual(jobs.get(job_id)["status"], "input_required")
        self.assertEqual(self.inputs, [])

    def test_on_a_decision_for_the_key_answers_it_and_hands_on_input_the_record(self):
        server, jobs, job_id = self.start(input_actions=True)
        result = self.answer(server, job_id, {"pick": {"action": "accept", "content": {"choice": "a"}}}, self.key_decision("pick"))
        self.assertFalse(result["isError"])
        self.assertEqual(jobs.get(job_id)["status"], "working")
        matched, ctx = self.inputs[0]
        self.assertEqual(list(matched), ["pick"])
        self.assertEqual(ctx.input_records, {"pick": {"by": "operator", "via": "relayed-instruction", "caller": "local:T0"}})

    def test_on_one_decision_covers_one_key(self):
        server, jobs, job_id = self.start(input_actions=True)
        both = {"pick": {"action": "accept", "content": {"choice": "a"}}, "note": {"action": "decline"}}
        self.assertEqual(self.answer(server, job_id, both, self.key_decision("pick"))["structuredContent"]["error"]["code"], "decision-invalid")
        self.assertEqual(self.answer(server, job_id, {"note": {"action": "decline"}}, self.key_decision("pick"))["structuredContent"]["error"]["code"],
                         "decision-invalid")
        self.assertEqual(jobs.get(job_id)["status"], "input_required")
        self.assertEqual(self.inputs, [])

    def test_on_a_key_the_job_does_not_ask_and_a_plain_read_are_not_gated(self):
        server, jobs, job_id = self.start(input_actions=True)
        self.assertFalse(self.answer(server, job_id, {"other": {"action": "accept"}})["isError"])
        read = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                              "params": {"name": "fabric.job.get", "arguments": {"id": job_id}}}, tier="T0")["result"]
        self.assertFalse(read["isError"])
        self.assertEqual(jobs.get(job_id)["status"], "input_required")

    def test_on_a_t2_answer_needs_an_approval(self):
        server, jobs, job_id = self.start(input_actions=True, identify=lambda headers, tier: "agent:remote")
        error = self.answer(server, job_id, {"pick": {"action": "accept", "content": {"choice": "a"}}}, self.key_decision("pick"), tier="T2")["structuredContent"]["error"]
        self.assertEqual(error["code"], "approval-required")
        self.assertTrue(error["data"]["actionDigest"].startswith("sha256:"))


class RequestMetaDecisionTests(unittest.TestCase):
    """REQ-8: a caller built on the kit relays the operator's decision in _meta.decision, never in arguments."""

    def test_the_decision_rides_in_meta(self):
        meta = fi.request_meta(PARENT, decision=DECISION)
        self.assertEqual(meta["decision"], DECISION)
        self.assertEqual(meta["traceparent"], PARENT)
        self.assertNotIn("decision", fi.request_meta(PARENT))
        meta["decision"]["instruction"] = "changed"
        self.assertEqual(DECISION["instruction"], "Agent: Approve the reply to Anna? Operator: yes")

    def test_a_decision_the_schema_refuses_is_never_sent(self):
        vectors = json.loads((ROOT / "test/fixtures/contract/actions-vectors.json").read_text(encoding="utf-8"))
        decisions = [case for case in vectors["fixtures"] if case["schema"] == "decision.schema.json"]
        self.assertTrue(any(case["valid"] for case in decisions) and any(not case["valid"] for case in decisions))
        for case in decisions:
            with self.subTest(case["name"]):
                if case["valid"]:
                    self.assertEqual(fi.request_meta(PARENT, decision=case["document"])["decision"], case["document"])
                else:
                    with self.assertRaises(fi.InteropError):
                        fi.request_meta(PARENT, decision=case["document"])


# --- DEC-0125: the operator's mandate in _meta.mandate (FAA-131, brief D25, D26) ------------------------------------

fm = load("fabric_mandate")
REPLY_SCOPE = {"actions": ["approve-reply"], "effects": ["reply"]}


def lead_mandate(scope=None, at="2026-10-24T09:00:00Z"):
    """The operator told the lead agent to answer the reviews; the lead hands the task to example-agent."""
    stated = fm.operator_mandate("answer the reviews", "answer every review from this week", scope or REPLY_SCOPE,
                                 "example-lead", at=at)
    return fm.hand_on(stated, "example-agent", "2026-10-24T09:10:00Z")


class RequestMetaMandateTests(unittest.TestCase):
    def test_the_mandate_rides_in_meta_copied(self):
        mandate = lead_mandate()
        meta = fi.request_meta(PARENT, mandate=mandate)
        self.assertEqual(meta["mandate"], mandate)
        self.assertIsNot(meta["mandate"], mandate)
        self.assertNotIn("mandate", fi.request_meta(PARENT))
        both = fi.request_meta(PARENT, decision=DECISION, mandate=mandate)
        self.assertEqual((both["decision"], both["mandate"]), (DECISION, mandate))

    def test_a_mandate_fac_sem_144_refuses_is_never_sent(self):
        vectors = json.loads((ROOT / "test/fixtures/contract/mandate-vectors.json").read_text(encoding="utf-8"))
        for case in vectors["fixtures"]:
            with self.subTest(case["name"]):
                if case["valid"]:  # to a callee that reads source (DEC-0126 OA-7), exactly as given
                    sent = fi.request_meta(PARENT, mandate=case["document"], target_protocols=[fm.OPERATOR_SOURCE_PROTOCOL])
                    self.assertEqual(sent["mandate"], case["document"])
                else:
                    with self.assertRaises(fi.InteropError):
                        fi.request_meta(PARENT, mandate=case["document"])
        widened = lead_mandate()
        widened["chain"][-1]["scope"] = {"actions": ["approve-reply"], "effects": ["publish"]}
        for bad in ("yes", [], widened):
            with self.subTest(bad=bad), self.assertRaises(fi.InteropError):
                fi.request_meta(PARENT, mandate=bad)


class ActionGateMandateTests(unittest.TestCase):
    def gate(self, **extra):
        options = {"action": RELAYED, "tier": "T0", "caller": "local:T0", "meta": {"mandate": lead_mandate()}, "target": "reply-7",
                   "now": NOW, "self_id": "example-agent", "effect": "reply"}
        options.update(extra)
        return fi.action_gate(options.pop("action"), **options)

    def test_a_covered_call_is_the_operators_act_recorded_via_the_mandate(self):
        answer = self.gate()
        self.assertEqual(answer, {"ok": True, "decision": None, "mandate": lead_mandate(),
                                  "record": {"by": "operator", "via": "mandate", "task": "answer the reviews",
                                             "chain": ["example-lead", "example-agent"], "caller": "local:T0"}})

    def test_a_service_that_names_no_agent_id_does_not_read_a_mandate(self):
        answer = self.gate(self_id=None)
        self.assertEqual((answer["refusal"]["code"], answer["refusal"]["detail"]), ("operator-decision-required", "no-decision"))

    def test_an_effect_the_service_did_not_name_is_its_own_fault(self):
        answer = self.gate(effect=None)
        self.assertEqual((answer["refusal"]["code"], answer["fault"]), ("unknown-state", "effect-missing"))

    def test_what_the_mandate_does_not_cover_is_named(self):
        error = fd.refusal_error(self.gate(effect="publish")["refusal"])["error"]
        self.assertEqual((error["code"], error["data"]), ("operator-decision-required", {"detail": "outside-mandate: effect"}))
        tight = lead_mandate(dict(REPLY_SCOPE, perCallMaxUsd=1))
        error = fd.refusal_error(self.gate(meta={"mandate": tight}, spend_usd=2)["refusal"])["error"]
        self.assertEqual(error["data"], {"detail": "outside-mandate: spend", "estimateUsd": 2, "perCallMaxUsd": 1})
        error = fd.refusal_error(self.gate(caller_agent="example-other")["refusal"])["error"]
        self.assertEqual((error["code"], error["data"]), ("decision-invalid", {"detail": "mandate-not-for-this-call"}))
        error = fd.refusal_error(self.gate(now="2026-10-25T09:00:00Z")["refusal"])["error"]
        self.assertEqual(error["data"], {"detail": "mandate-expired"})
        error = fd.refusal_error(self.gate(meta={"mandate": "yes"})["refusal"])["error"]
        self.assertEqual(error["data"], {"detail": "mandate-malformed"})

    def test_a_spend_or_project_function_that_fails_never_raises_and_fails_closed(self):
        # Seam reading of 0.51.0: the server's spend and project functions are the service's code; a raise or a
        # non-finite estimate reads as no estimate, so a mandate with a ceiling refuses the spend.
        tight = lead_mandate(dict(REPLY_SCOPE, perCallMaxUsd=1))
        for spend in (lambda a: 1 / 0, lambda a: float("nan"), lambda a: float("inf")):
            server = fi.McpToolServer("example-agent", "1.0.0", agent_id="example-agent", clock=lambda: NOW_SECONDS)
            server.add_tool({"name": "reviews.approve", "inputSchema": OBJECT}, lambda args, ctx: {"done": True}, action=RELAYED,
                            target="reply", effect="reply", spend=spend, project=lambda a: 1 / 0)
            params = {"name": "reviews.approve", "arguments": {"reply": "reply-7"}, "_meta": {"traceparent": PARENT, "mandate": tight}}
            answer = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}, None, tier="T0")
            error = answer["result"]["structuredContent"]["error"]
            self.assertEqual((error["code"], error["data"]["detail"]), ("operator-decision-required", "outside-mandate: spend"))

    def test_the_direct_gate_reads_spend_and_project_failing_closed(self):
        """FAA-139: action_gate reads as McpToolServer does: a spend past the float range, NaN or infinite is none (a
        ceiling refuses it, and no 5000-digit number reaches the refusal), a project that is no string is unreadable."""
        tight = lead_mandate(dict(REPLY_SCOPE, perCallMaxUsd=1))
        scoped = lead_mandate(dict(REPLY_SCOPE, projects=["alpha"]))
        for index, spend in enumerate((10 ** 5000, 10 ** 400, float("nan"), float("inf"), "0.5", True)):
            with self.subTest(spend=index):
                answer = self.gate(meta={"mandate": tight}, spend_usd=spend)
                result = fd.refusal_tool_result(answer["refusal"])
                json.dumps(result, allow_nan=False)
                self.assertEqual(result["structuredContent"]["error"]["data"]["detail"], "outside-mandate: spend")
        for project in (7, ["alpha"], {"id": "alpha"}):
            with self.subTest(project=project):
                answer = self.gate(meta={"mandate": scoped}, spend_usd=0.5, project=project)
                self.assertEqual(fd.refusal_error(answer["refusal"])["error"]["data"]["detail"], "outside-mandate: project")
        self.assertTrue(self.gate(meta={"mandate": scoped}, spend_usd=0.5, project="alpha")["ok"])
        self.assertTrue(self.gate(meta={"mandate": tight}, spend_usd=1)["ok"])

    def test_a_job_step_reads_spend_and_project_as_the_answer_does(self):
        """0.56.0 seam r1: job_step (a job's start) and action_gate (its answer) read one step alike, failing closed."""
        tight = lead_mandate(dict(REPLY_SCOPE, perCallMaxUsd=1))
        scoped = lead_mandate(dict(REPLY_SCOPE, projects=["alpha"]))
        call = dict(tier="T0", now=NOW, self_id="example-agent", capability="reviews.approve", key="approve-reply",
                    effect="reply")
        for spend in (float("nan"), float("inf"), 10 ** 400, "0.5", True):
            with self.subTest(spend=repr(spend)[:12]):
                step = fi.job_step(tight, spend_usd=spend, **call)
                self.assertEqual((step["covered"], step["detail"]), (False, "outside-mandate: spend"))
        for project in (7, ["alpha"]):
            with self.subTest(project=project):
                step = fi.job_step(scoped, spend_usd=0.5, project=project, **call)
                self.assertEqual((step["covered"], step["detail"]), (False, "outside-mandate: project"))
        self.assertTrue(fi.job_step(scoped, spend_usd=0.5, project="alpha", **call)["covered"])
        self.assertTrue(fi.job_step(tight, spend_usd=1, **call)["covered"])

    def test_a_huge_spend_and_a_raising_project_fail_closed(self):
        # Second seam reading of 0.51.0: an int past the float range never raises; a project function that raises
        # never reads as "no project", which a mandate limited to projects would cover.
        tight = lead_mandate(dict(REPLY_SCOPE, perCallMaxUsd=1))
        scoped = lead_mandate(dict(REPLY_SCOPE, projects=["alpha"]))
        cases = ((dict(spend=lambda a: 10 ** 400), tight, "outside-mandate: spend"), (dict(spend=10 ** 400), tight, "outside-mandate: spend"),
                 (dict(spend=lambda a: 10 ** 5000), tight, "outside-mandate: spend"),
                 (dict(spend=0.5, project=lambda a: 1 / 0), scoped, "outside-mandate: project"),
                 (dict(spend=0.5, project=lambda a: 7), scoped, "outside-mandate: project"))
        for options, mandate, detail in cases:
            server = fi.McpToolServer("example-agent", "1.0.0", agent_id="example-agent", clock=lambda: NOW_SECONDS)
            server.add_tool({"name": "reviews.approve", "inputSchema": OBJECT}, lambda args, ctx: {"done": True}, action=RELAYED,
                            target="reply", effect="reply", **options)
            params = {"name": "reviews.approve", "arguments": {"reply": "reply-7"}, "_meta": {"traceparent": PARENT, "mandate": mandate}}
            answer = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}, None, tier="T0")
            error = answer["result"]["structuredContent"]["error"]
            json.dumps(answer)  # a past-the-float estimate never reaches the wire as a 5000-digit integer
            self.assertNotIn("estimateUsd", error["data"]) if detail.endswith("spend") else None
            self.assertEqual(error["data"]["detail"], detail, options)
            # Third product reading: the MD-4 wording reaches the caller through the gate, not only a hand-built refusal.
            self.assertIn("pass this refusal", error["message"])
            plain = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": dict(params, _meta={"traceparent": PARENT})},
                                  None, tier="T0")
            self.assertEqual(plain["result"]["structuredContent"]["error"]["data"]["detail"], "no-decision", options)
            self.assertNotIn("pass this refusal", plain["result"]["structuredContent"]["error"]["message"])

    def test_a_decision_beside_a_mandate_decides(self):
        answer = self.gate(meta={"mandate": lead_mandate(), "decision": DECISION})
        self.assertEqual((answer["record"]["via"], answer["decision"]), ("relayed-instruction", DECISION))
        self.assertNotIn("mandate", answer)


class McpMandateTests(unittest.TestCase):
    """McpToolServer(agent_id=...) reads _meta.mandate for a relayed action registered with its effect (DEC-0125)."""

    def server(self, **options):
        self.seen = []
        options.setdefault("clock", lambda: NOW_SECONDS)
        server = fi.McpToolServer("example-agent", "1.0.0", **options)
        keep = lambda args, ctx: self.seen.append(ctx) or {"done": True}
        server.add_tool({"name": "reviews.approve", "inputSchema": OBJECT}, keep, action=RELAYED, target="reply", effect="reply",
                        spend=lambda arguments: arguments.get("cost"), project="example-site")
        return server

    def call(self, server, meta, arguments=None, tier="T0"):
        params = {"name": "reviews.approve", "arguments": {"reply": "reply-7"} if arguments is None else arguments,
                  "_meta": dict({"traceparent": PARENT}, **meta)}
        return server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}, None, tier=tier)["result"]

    def test_a_covered_call_runs_and_the_handler_gets_the_record_and_the_mandate(self):
        mandate = lead_mandate()
        result = self.call(self.server(agent_id="example-agent"), {"mandate": mandate})
        self.assertFalse(result["isError"], result)
        ctx = self.seen[-1]
        self.assertEqual(ctx.record, {"by": "operator", "via": "mandate", "task": "answer the reviews",
                                      "chain": ["example-lead", "example-agent"], "caller": "local:T0"})
        self.assertEqual((ctx.mandate, ctx.decision), (mandate, None))

    def test_the_services_estimate_and_project_are_read(self):
        server = self.server(agent_id="example-agent")
        tight = lead_mandate(dict(REPLY_SCOPE, perCallMaxUsd=1, projects=["example-site"]))
        error = self.call(server, {"mandate": tight}, {"reply": "reply-7", "cost": 2})["structuredContent"]["error"]
        self.assertEqual(error["data"], {"detail": "outside-mandate: spend", "estimateUsd": 2, "perCallMaxUsd": 1})
        self.assertFalse(self.call(server, {"mandate": tight}, {"reply": "reply-7", "cost": 0.5})["isError"])
        elsewhere = lead_mandate(dict(REPLY_SCOPE, projects=["other-site"]))
        self.assertEqual(self.call(server, {"mandate": elsewhere})["structuredContent"]["error"]["data"], {"detail": "outside-mandate: project"})

    def test_an_authenticated_caller_must_be_the_agent_before_this_one(self):
        verdict = lambda name: (lambda tool, headers, tier="T2": {"ok": True, "tier": tier, "principal": "person:p", "caller": name})
        server = self.server(agent_id="example-agent", authorize=verdict("example-other"))
        error = self.call(server, {"mandate": lead_mandate()})["structuredContent"]["error"]
        self.assertEqual((error["code"], error["data"]), ("decision-invalid", {"detail": "mandate-not-for-this-call"}))
        server = self.server(agent_id="example-agent", authorize=verdict("example-lead"))
        self.assertFalse(self.call(server, {"mandate": lead_mandate()})["isError"])

    def test_a_t2_callers_mandate_changes_nothing(self):
        server = self.server(agent_id="example-agent", identify=lambda headers, tier: "agent:remote")
        error = self.call(server, {"mandate": lead_mandate()}, tier="T2")["structuredContent"]["error"]
        self.assertEqual(error["code"], "approval-required")
        self.assertEqual(self.seen, [])

    def test_without_an_agent_id_the_mandate_is_not_read(self):
        error = self.call(self.server(), {"mandate": lead_mandate()})["structuredContent"]["error"]
        self.assertEqual((error["code"], error["data"]), ("operator-decision-required", {"detail": "no-decision"}))

    def test_a_mandate_in_the_arguments_is_ignored(self):
        server = self.server(agent_id="example-agent")
        error = self.call(server, {}, {"reply": "reply-7", "mandate": lead_mandate()})["structuredContent"]["error"]
        self.assertEqual(error["code"], "operator-decision-required")

    def test_construction_refuses_what_could_never_read_a_mandate(self):
        with self.assertRaises(fi.InteropError):
            fi.McpToolServer("x", "1", agent_id="Example Agent")
        server = fi.McpToolServer("x", "1", agent_id="example-agent")
        for extra in ({}, {"effect": "Reply"}, {"effect": "reply", "spend": "1"}, {"effect": "reply", "project": 7}):
            with self.subTest(extra=extra), self.assertRaises(fi.InteropError):
                server.add_tool({"name": "reviews.approve", "inputSchema": OBJECT}, lambda a, c: {}, action=RELAYED, **extra)
        plain = fi.McpToolServer("x", "1")  # a server that reads no mandate needs no effect, as before
        plain.add_tool({"name": "reviews.approve", "inputSchema": OBJECT}, lambda a, c: {}, action=RELAYED)


# --- DEC-0126: where the operator said the words (`source`, OA-1 to OA-7; FAA-134) ----------------------------------

SOURCE = {"project": "example-analyst", "session": "sess-0042"}
SOURCE_WORDS = ("example-analyst", "sess-0042")


def relayed_mandate(scope=None):
    stated = fm.operator_mandate("answer the reviews", "answer every review from this week", scope or REPLY_SCOPE,
                                 "example-lead", at="2026-10-24T09:00:00Z", source=SOURCE)
    return fm.hand_on(stated, "example-agent", "2026-10-24T09:10:00Z")


class OperatorSourceTests(unittest.TestCase):
    """OA-6: a service keeps `source` in the record it hands back; OA-7: a caller sends it only to a target listing
    operator-source/1, and nothing the kit writes for another party (a tool result, a refusal, a job's public state)
    carries it."""

    def server(self, **options):
        self.seen = []
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        options.setdefault("clock", lambda: NOW_SECONDS)
        server = fi.McpToolServer("example-agent", "1.0.0", jobs=fi.JobStore(Path(self.temp.name) / "jobs"), **options)
        keep = lambda args, ctx: self.seen.append(ctx) or {"done": True}
        server.add_tool({"name": "reviews.approve", "inputSchema": OBJECT}, keep, action=RELAYED, target="reply", effect="reply")
        return server

    def call(self, server, meta, tier="T0"):
        params = {"name": "reviews.approve", "arguments": {"reply": "reply-7"}, "_meta": dict({"traceparent": PARENT}, **meta)}
        return server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}, None, tier=tier)["result"]

    def test_request_meta_sends_source_only_to_a_target_that_lists_it(self):
        decision = dict(DECISION, source=SOURCE)
        mandate = relayed_mandate()
        for target in (None, [], ["fabric-service/0.1"], "operator-source/1", {"operator-source/1": True}):
            with self.subTest(target=target):
                meta = fi.request_meta(PARENT, decision=decision, mandate=mandate, target_protocols=target)
                self.assertNotIn("source", meta["decision"])
                self.assertNotIn("source", meta["mandate"])
                self.assertEqual(meta["decision"], {k: v for k, v in decision.items() if k != "source"})
        meta = fi.request_meta(PARENT, decision=decision, mandate=mandate, target_protocols=["operator-source/1"])
        self.assertEqual((meta["decision"]["source"], meta["mandate"]["source"]), (SOURCE, SOURCE))
        self.assertEqual((decision["source"], mandate["source"]), (SOURCE, SOURCE))  # the caller's own record keeps it
        meta["mandate"]["source"]["project"] = "changed"
        self.assertEqual(mandate["source"]["project"], "example-analyst")
        with self.assertRaises(fi.InteropError):  # an unplaced source is refused before anything is sent
            fi.request_meta(PARENT, decision=dict(DECISION, source={"project": "example-analyst"}))

    def test_a_service_records_the_source_of_a_decision_and_of_a_mandate(self):
        server = self.server(agent_id="example-agent")
        relayed = dict(DECISION, at=NOW, source=SOURCE)
        self.assertFalse(self.call(server, {"decision": relayed})["isError"])
        self.assertEqual(self.seen[-1].record, {"by": "operator", "via": "relayed-instruction", "caller": "local:T0", "source": SOURCE})
        self.assertFalse(self.call(server, {"mandate": relayed_mandate()})["isError"])
        self.assertEqual(self.seen[-1].record["source"], SOURCE)
        self.assertEqual(self.seen[-1].record["via"], "mandate")

    def test_a_server_that_reads_source_lists_operator_source(self):
        self.assertEqual(self.server(agent_id="example-agent").well_known_protocols(["fabric-service/0.1"]),
                         ["fabric-service/0.1", "operator-source/1"])
        self.assertEqual(self.server().well_known_protocols(), ["operator-source/1"])  # a relayed action reads a decision's
        plain = fi.McpToolServer("example-agent", "1.0.0")
        self.assertEqual(plain.well_known_protocols(["fabric-service/0.1"]), ["fabric-service/0.1"])
        self.assertEqual(self.server(agent_id="example-agent").well_known_protocols(["operator-source/1"]), ["operator-source/1"])
        document = fs.build_well_known(service_id="example-agent", instance="default", name="Example", version="1.0.0",
                                       build={"commit": "0" * 40}, started_at=NOW, status="ready", degraded=[],
                                       surfaces={"events": {"path": "/fabric/v1/events"}},
                                       protocols=self.server(agent_id="example-agent").well_known_protocols(["fabric-service/0.1"]))
        self.assertIn("operator-source/1", document["protocols"])

    def test_nothing_the_kit_writes_for_another_party_carries_the_source(self):
        """OA-7, AP-2: tool results, refusals and a job's public state never carry `source` or the operator's words."""
        server = self.server(agent_id="example-agent")
        written = []
        relayed = dict(DECISION, at=NOW, source=SOURCE)
        written.append(self.call(server, {"decision": relayed}))
        written.append(self.call(server, {"decision": dict(relayed, at="2026-10-20T09:00:00Z")}))  # refused: too old
        written.append(self.call(server, {"mandate": relayed_mandate()}))
        written.append(self.call(server, {"mandate": relayed_mandate({"actions": ["other"], "effects": ["reply"]})}))
        written.append(self.call(server, {"decision": relayed}, tier="T2"))
        self.assertTrue(any(r["isError"] for r in written) and any(not r["isError"] for r in written))
        text = json.dumps(written)
        for word in SOURCE_WORDS + ("answer every review from this week",):
            self.assertNotIn(word, text)
        self.assertTrue(all("source" in ctx.record for ctx in self.seen))  # the service's own record has it


class JobApprovalStepTests(unittest.TestCase):
    """REQ-8, interop C3.3 and conformance ("a job's approval step included"): a job reads the mandate its start call
    carried at its own approval step, and an answer's _meta.mandate that covers the step."""

    def start(self, meta, **options):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.jobs = fi.JobStore(Path(self.temp.name) / "jobs")
        self.contexts, self.inputs = [], []
        options.setdefault("agent_id", "example-agent")
        server = fi.McpToolServer("example-agent", "1.0.0", jobs=self.jobs, clock=lambda: NOW_SECONDS,
                                  on_job_started=lambda job_id, ctx: self.contexts.append((job_id, ctx)),
                                  on_input=lambda job_id, matched, ctx: self.inputs.append((matched, ctx)), **options)
        server.add_tool({"name": "reviews.approve", "inputSchema": OBJECT}, lambda args, ctx: ctx.start_job())
        result = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "reviews.approve", "arguments": {}, "_meta": dict({"traceparent": PARENT}, **meta)}}, tier="T0")["result"]
        self.assertFalse(result["isError"], result)
        return server

    def step(self, **extra):
        job_id, ctx = self.contexts[-1]
        request = fi.choice_request("Publish the reply?", "choice", [("yes", "Yes"), ("no", "No")])
        return job_id, ctx.approval_step(job_id, "approve-reply", request, effect=extra.pop("effect", "reply"), **extra)

    def test_a_step_the_mandate_covers_asks_nothing_and_is_recorded_with_its_source(self):
        self.start({"mandate": relayed_mandate()})
        job_id, record = self.step()
        self.assertEqual(record, {"by": "operator", "via": "mandate", "task": "answer the reviews",
                                  "chain": ["example-lead", "example-agent"], "source": SOURCE})
        self.assertEqual(self.jobs.get(job_id)["status"], "working")

    def test_a_step_it_does_not_cover_waits_naming_the_part(self):
        self.start({"mandate": lead_mandate({"actions": ["other-action"], "effects": ["reply"]})})
        job_id, record = self.step()
        self.assertIsNone(record)
        job = self.jobs.get(job_id)
        self.assertEqual(job["status"], "input_required")
        self.assertIn("outside-mandate: action", job["statusMessage"])
        self.assertEqual(list(job["inputRequests"]), ["approve-reply"])

    def test_an_expired_mandate_waits_saying_it_expired(self):
        stated = fm.operator_mandate("t", "answer the reviews", REPLY_SCOPE, "example-lead", at="2026-10-23T09:00:00Z",
                                     expires_at="2026-10-24T09:20:00Z")
        self.start({"mandate": fm.hand_on(stated, "example-agent", "2026-10-23T09:10:00Z")})
        job_id, record = self.step()
        self.assertIsNone(record)
        self.assertIn("expired", self.jobs.get(job_id)["statusMessage"])

    def test_a_null_mandate_reads_as_malformed_at_the_start_as_at_the_answer(self):
        """FAA-178: `_meta.mandate: null` is present, not absent: the step waits saying the mandate cannot be read, as
        an answer carrying it is refused mandate-malformed."""
        self.start({"mandate": None})
        job_id, record = self.step(message="Publish it?")
        self.assertIsNone(record)
        self.assertIn("mandate-malformed", self.jobs.get(job_id)["statusMessage"])
        answer = fi.action_gate({"id": "approve-reply", "title": "Answer", "tool": "fabric.job.get", "gate": "relayed"}, tier="T0",
                                caller="local:T0", meta={"mandate": None}, now=NOW, self_id="example-agent", effect="reply",
                                mandate_capability="reviews.approve")
        self.assertEqual(fd.refusal_error(answer["refusal"])["error"]["data"]["detail"], "mandate-malformed")

    def test_without_a_mandate_or_an_agent_id_the_step_asks_as_before(self):
        self.start({})
        job_id, record = self.step(message="Publish it?")
        self.assertIsNone(record)
        self.assertEqual(self.jobs.get(job_id)["statusMessage"], "Publish it?")
        self.start({"mandate": lead_mandate()}, agent_id=None)
        job_id, record = self.step()
        self.assertIsNone(record)
        self.assertEqual(self.jobs.get(job_id)["status"], "input_required")

    def test_an_answer_carrying_a_mandate_that_covers_the_step_is_taken(self):
        server = self.start({}, input_actions=True)
        job_id, _ = self.step()
        self.assertEqual(self.jobs.private(job_id)["steps"], {"approve-reply": {"effect": "reply"}})
        answer = lambda meta: server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "fabric.job.get", "arguments": {"id": job_id, "inputResponses": {"approve-reply": {"action": "accept", "content": {"choice": "yes"}}}},
            "_meta": dict({"traceparent": PARENT}, **meta)}}, tier="T0")["result"]
        refused = answer({"mandate": lead_mandate({"actions": ["other-action"], "effects": ["reply"]})})
        self.assertEqual(refused["structuredContent"]["error"]["data"], {"detail": "outside-mandate: action"})
        self.assertEqual(self.jobs.get(job_id)["status"], "input_required")
        self.assertFalse(answer({"mandate": relayed_mandate()})["isError"])
        self.assertEqual(self.jobs.get(job_id)["status"], "working")
        self.assertEqual(self.inputs[-1][1].input_records["approve-reply"]["source"], SOURCE)
        public = json.dumps([self.jobs.get(job_id), refused])  # OA-7: the job's public state and the refusal
        self.assertFalse(any(word in public for word in SOURCE_WORDS))

    def answer(self, server, job_id, meta):
        return server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "fabric.job.get", "arguments": {"id": job_id, "inputResponses": {"approve-reply": {"action": "accept", "content": {"choice": "yes"}}}},
            "_meta": dict({"traceparent": PARENT}, **meta)}}, tier="T0")["result"]

    def test_a_capabilities_scoped_mandate_reads_the_same_at_the_start_and_on_the_answer(self):
        # Seam round 1: the answer path read the step under fabric.job.get; it reads it under the job's capability.
        scope = {"capabilities": ["reviews.approve"], "actions": ["approve-reply"], "effects": ["reply"]}
        self.start({"mandate": relayed_mandate(scope)})
        _, record = self.step()
        self.assertIsNotNone(record, "covered at the start")
        server = self.start({}, input_actions=True)
        job_id, _ = self.step()
        self.assertFalse(self.answer(server, job_id, {"mandate": relayed_mandate(scope)})["isError"], "and on the answer")
        self.assertEqual(self.jobs.get(job_id)["status"], "working")

    def camel_server(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.jobs = fi.JobStore(Path(self.temp.name) / "jobs")
        self.contexts, self.inputs, self.faults = [], [], []
        server = fi.McpToolServer("example-agent", "1.0.0", jobs=self.jobs, clock=lambda: NOW_SECONDS, agent_id="example-agent",
                                  input_actions=True, on_job_started=lambda job_id, ctx: self.contexts.append((job_id, ctx)),
                                  on_input=lambda job_id, matched, ctx: self.inputs.append((matched, ctx)),
                                  on_fault=lambda tool, fault: self.faults.append((tool, fault)))
        server.add_tool({"name": "reviewsApprove", "inputSchema": OBJECT}, lambda args, ctx: ctx.start_job())
        return server

    def start_camel(self, server, meta):
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "reviewsApprove", "arguments": {}, "_meta": dict({"traceparent": PARENT}, **meta)}}, tier="T0")

    def test_a_tool_name_that_is_no_capability_still_takes_a_decision_on_a_kept_step(self):
        # Seam round 2: a camelCase tool keeps the action readable, so a decision is still taken.
        server = self.camel_server()
        self.start_camel(server, {})
        job_id, _ = self.step()
        decision = {"by": "operator", "via": "relayed-instruction", "action": "approve-reply",
                    "instruction": "Agent: Publish the reply? Operator: yes", "at": "2026-10-24T09:30:00Z"}
        taken = self.answer(server, job_id, {"decision": decision})
        self.assertFalse(taken["isError"], taken)
        self.assertEqual(self.jobs.get(job_id)["status"], "working")
        self.assertEqual(self.jobs.private(job_id)["steps"], {}, "the answered step is gone in the same write")

    def test_the_start_and_the_answer_read_a_mandate_alike_whatever_the_tool_is_named(self):
        # Seam round 3 made the start and the answer agree; DEC-0141 MJ-1 (0.54.0): a job whose tool is no capability
        # name has no capability a mandate can read its step under, so both refuse whatever the scope, the answer as
        # operator-decision-required with the job left input_required.
        for scope in ({"capabilities": ["fabric.job.get"], "actions": ["approve-reply"], "effects": ["reply"]},
                      {"actions": ["approve-reply"], "effects": ["reply"]}):
            server = self.camel_server()
            self.start_camel(server, {"mandate": relayed_mandate(scope)})
            job_id, record = self.step()
            self.assertIsNone(record, scope)
            self.assertIn("mandate-capability-missing", self.jobs.get(job_id)["statusMessage"])
            self.assertEqual(self.faults, [("reviewsApprove", "mandate-capability-missing")], "the start hears it")
            server = self.camel_server()
            self.start_camel(server, {})
            job_id, _ = self.step()
            refused = self.answer(server, job_id, {"mandate": relayed_mandate(scope)})
            self.assertTrue(refused["isError"], scope)
            self.assertEqual(refused["structuredContent"]["error"]["code"], "operator-decision-required")
            self.assertEqual(refused["structuredContent"]["error"]["data"]["detail"], "mandate-capability-missing")
            self.assertEqual(self.jobs.get(job_id)["status"], "input_required")
            self.assertEqual(self.faults, [("reviewsApprove", "mandate-capability-missing")], "and the answer, by the same name")

    def test_a_job_created_under_another_name_is_read_under_it_at_the_start_and_the_answer(self):
        # FAA-179 (5): approval_step read self.tool while the answer read the job's stored capability.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.jobs = fi.JobStore(Path(self.temp.name) / "jobs")
        self.contexts, self.inputs, self.faults = [], [], []
        server = fi.McpToolServer("example-agent", "1.0.0", jobs=self.jobs, clock=lambda: NOW_SECONDS, agent_id="example-agent",
                                  input_actions=True, on_job_started=lambda job_id, ctx: self.contexts.append((job_id, ctx)),
                                  on_fault=lambda tool, fault: self.faults.append((tool, fault)))

        def handler(args, ctx):
            handle = ctx.server.jobs.create("reviews.approve", args, ctx.traceparent, None, ctx.delegation)
            ctx.server.job_started(handle["job"]["id"], ctx)
            return handle
        server.add_tool({"name": "reviewsApprove", "inputSchema": OBJECT}, handler)
        self.start_camel(server, {"mandate": relayed_mandate()})
        job_id, record = self.step()
        self.assertEqual((record or {}).get("via"), "mandate", "the start reads the step under reviews.approve")
        self.assertEqual(self.faults, [])

    def test_the_start_hands_any_job_step_fault_to_on_fault(self):
        # 0.54.0 readings 4 (unit, seam): approval_step reports every job_step fault, not only MJ-1's.
        server = self.camel_server()
        self.start_camel(server, {"mandate": relayed_mandate()})
        unreadable = {"covered": False, "message": None, "fault": "now-unreadable"}
        with mock.patch.object(fi, "job_step", lambda *a, **k: unreadable):
            job_id, record = self.step()
        self.assertIsNone(record)
        self.assertEqual(self.faults, [("reviewsApprove", "now-unreadable")])
        self.assertEqual(self.jobs.get(job_id)["status"], "input_required")

    def test_a_kept_step_does_not_outlive_its_question(self):
        # Seam round 1: a later plain question under the same key is not answered by a mandate alone.
        server = self.start({}, input_actions=True)
        job_id, _ = self.step()
        self.assertFalse(self.answer(server, job_id, {"mandate": relayed_mandate()})["isError"])
        request = fi.choice_request("Publish another reply?", "choice", [("yes", "Yes"), ("no", "No")])
        self.jobs.request_input(job_id, {"approve-reply": request})
        self.assertEqual(self.jobs.private(job_id)["steps"], {})
        refused = self.answer(server, job_id, {"mandate": relayed_mandate()})
        self.assertTrue(refused["isError"])
        self.assertEqual(refused["structuredContent"]["error"]["code"], "operator-decision-required")
        self.assertEqual(self.jobs.get(job_id)["status"], "input_required")

    def test_a_step_names_its_effect(self):
        self.start({"mandate": lead_mandate()})
        with self.assertRaises(fi.InteropError):
            self.step(effect="Reply")
        job_id, _ = self.contexts[-1]
        with self.assertRaises(fi.InteropError):
            self.jobs.request_input(job_id, {"a": fi.form_request("x", {"t": {"type": "string"}})}, steps={"b": {"effect": "reply"}})

    def test_job_step_is_the_rule(self):
        call = dict(tier="T0", now=NOW, self_id="example-agent", capability="reviews.approve", key="approve-reply", effect="reply")
        self.assertEqual(fi.job_step(None, **call), {"covered": False, "message": None})
        self.assertEqual(fi.job_step(lead_mandate(), **dict(call, tier="T2")), {"covered": False, "message": None})
        self.assertEqual(fi.job_step(lead_mandate(), **dict(call, now="never"))["fault"], "now-unreadable")
        malformed = fi.job_step({"kind": "mandate/1"}, **call)
        self.assertEqual(malformed["detail"], "mandate-malformed")
        self.assertIn("cannot be read", malformed["message"])
        self.assertTrue(fi.job_step(lead_mandate(), **dict(call, caller_agent="example-lead"))["covered"])
        self.assertEqual(fi.job_step(lead_mandate(), **dict(call, caller_agent="example-other"))["detail"], "mandate-not-for-this-call")

    def test_an_unusable_job_capability_is_read_alike_at_both_ends(self):
        """DEC-0141 MJ-1, as the Node twin: the start (job_step) and the answer (action_gate) refuse an unusable job
        capability; a T2 caller's mandate is still ignored first (MD-5)."""
        mandate = lead_mandate({"actions": ["approve-reply"], "effects": ["reply"]})
        for capability in ("replyDraft", "fabric.job.get", ""):
            with self.subTest(capability=capability):
                call = dict(now=NOW, self_id="example-agent", capability=capability, key="approve-reply", effect="reply")
                step = fi.job_step(mandate, tier="T0", **call)
                self.assertEqual((step["covered"], step["fault"]), (False, "mandate-capability-missing"))
                self.assertIn("mandate-capability-missing", step["message"])
                self.assertEqual(fi.job_step(mandate, tier="T2", **call), {"covered": False, "message": None})
        action = {"id": "approve-reply", "title": "Answer approve-reply", "tool": "fabric.job.get", "gate": "relayed"}
        for mandate_capability in (None, "", "  ", "Reviews Approve", "fabric.job.get"):
            with self.subTest(mandate_capability=mandate_capability):
                refused = fi.action_gate(action, tier="T0", caller="local:T0", meta={"mandate": mandate}, now=NOW,
                                         self_id="example-agent", effect="reply", mandate_capability=mandate_capability)
                self.assertEqual(refused["ok"], False)
                self.assertEqual(refused["fault"], "mandate-capability-missing")
                self.assertEqual(refused["refusal"]["code"], "operator-decision-required")
                self.assertEqual(refused["refusal"]["data"]["detail"], "mandate-capability-missing")
                inputs = {"action": action, "tier": "T0", "caller": "local:T0", "mandate": mandate, "now": NOW,
                          "self": "example-agent", "effect": "reply"}
                if mandate_capability is not None:
                    inputs["mandateCapability"] = mandate_capability
                said = fi.action_refusal_tool_result(fa.action_decision(inputs))
                self.assertEqual(said["structuredContent"]["error"]["code"], "operator-decision-required")
                self.assertEqual(said["structuredContent"]["error"]["data"]["detail"], "mandate-capability-missing")
