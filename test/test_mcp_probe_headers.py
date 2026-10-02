"""check_service.py against strict MCP 2026-07-28 servers and a legacy (initialize-based) one.

Streamable HTTP 2026-07-28 mirrors body fields into headers: `Mcp-Method` on every request,
`Mcp-Name` on tools/call, prompts/get (params.name) and resources/read (params.uri), and a server
that processes the body MUST answer a missing or mismatched header with 400 and JSON-RPC
`HeaderMismatch` (-32020). A legacy server (2025-11-25 and earlier) opens a session with
`initialize` and `notifications/initialized`; the probe detects that era from a 4xx whose body is
not a recognized modern error and falls back, as the spec's Backward Compatibility section says.

Both fixtures are local, standard-library servers on 127.0.0.1.
"""

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import http.client


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
TOKEN = "fixture-token"
MODERN = "2026-07-28"
LEGACY = "2025-11-25"
SESSION = "fixture-session-1"
HEADER_MISMATCH = -32020
UNSUPPORTED_PROTOCOL_VERSION = -32022
NAMED = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(module)
    return module


checker = load("check_service")
fi = load("fabric_interop")


def decode_name(value):
    if value.startswith("=?base64?") and value.endswith("?="):
        return base64.b64decode(value[len("=?base64?"):-2]).decode("utf-8")
    return value


def answer(rid, method, params):
    """What both fixtures serve once a request is accepted: tools/list and fabric.job.get."""
    span = fi.child_traceparent(((params or {}).get("_meta") or {}).get("traceparent"))
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": [
            {"name": "fabric.job.get", "inputSchema": {"type": "object"}}], "_meta": {"traceparent": span}}}
    if method == "tools/call" and params.get("name") == "fabric.job.get":
        return {"jsonrpc": "2.0", "id": rid, "result": fi.unknown_job_result(str((params.get("arguments") or {}).get("id")), traceparent=span)}
    return None


class Fixture(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, mode):
        # "strict", "legacy", "broken_modern" (dual-era, modern path refused with a non-modern
        # error), "unsupported", "empty_list", "empty_call", "legacy_bad_notification"
        self.mode = mode
        self.seen = []
        self.initialized = False
        self.deleted = []
        super().__init__(("127.0.0.1", 0), Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, payload=None, headers=None):
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if payload is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self):
        h = {k.lower(): v for k, v in self.headers.items()}
        self.server.seen.append({"method": "DELETE", "headers": h, "body": None})
        if h.get("mcp-session-id") == SESSION:
            self.server.deleted.append(h)
            self.server.initialized = False
            return self.reply(200)
        self.reply(404)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        message = json.loads(raw or b"null")
        h = {k.lower(): v for k, v in self.headers.items()}
        self.server.seen.append({"method": message.get("method"), "headers": h, "body": message})
        if h.get("authorization") != "Bearer " + TOKEN:
            return self.reply(401)
        getattr(self, self.server.mode)(message, h)

    # modern, header-validating (what an SDK v2 server does) ---------------------------------
    def strict(self, message, h):
        rid, method, params = message.get("id"), message.get("method"), message.get("params") or {}

        def mismatch(text):
            self.reply(400, {"jsonrpc": "2.0", "id": rid, "error": {"code": HEADER_MISMATCH, "message": "Header mismatch: " + text}})

        version = (params.get("_meta") or {}).get("io.modelcontextprotocol/protocolVersion")
        if "mcp-protocol-version" not in h:
            return mismatch("MCP-Protocol-Version is missing")
        if h["mcp-protocol-version"] != version:
            return mismatch("MCP-Protocol-Version %r does not match body %r" % (h["mcp-protocol-version"], version))
        if "mcp-method" not in h:
            return mismatch("Mcp-Method is missing")
        if h["mcp-method"] != method:
            return mismatch("Mcp-Method %r does not match body %r" % (h["mcp-method"], method))
        if method in NAMED:
            if "mcp-name" not in h:
                return mismatch("Mcp-Name is missing")
            if decode_name(h["mcp-name"]) != params.get(NAMED[method]):
                return mismatch("Mcp-Name %r does not match body %r" % (h["mcp-name"], params.get(NAMED[method])))
        if version != MODERN:
            return self.reply(400, {"jsonrpc": "2.0", "id": rid, "error": {"code": UNSUPPORTED_PROTOCOL_VERSION, "message": "Unsupported protocol version",
                                                                          "data": {"supported": [MODERN], "requested": version}}})
        if "id" not in message:
            return self.reply(202)
        if (self.server.mode, method) in (("empty_list", "tools/list"), ("empty_call", "tools/call")):
            return self.reply(200)  # 200 with no body: a handler that wrote nothing, or a proxy
        result = answer(rid, method, params)
        if result is None:
            return self.reply(404, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}})
        self.reply(200, result)

    # a modern server that refuses every version the probe names --------------------------------
    def unsupported(self, message, h):
        self.reply(400, {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": UNSUPPORTED_PROTOCOL_VERSION, "message": "Unsupported protocol version",
                                                                             "data": {"supported": ["2099-01-01"], "requested": MODERN}}})

    empty_list = strict
    empty_call = strict

    # legacy 2025-11-25 Streamable HTTP: initialize, a session, then requests ----------------------
    def broken_modern(self, message, h):
        self.legacy(message, h, pre_session_code=-32600)

    def legacy_bad_notification(self, message, h):
        if message.get("method") == "notifications/initialized":
            return self.reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "Bad Request: no"}})
        self.legacy(message, h)

    def legacy(self, message, h, pre_session_code=-32000):
        rid, method, params = message.get("id"), message.get("method"), message.get("params") or {}
        if method == "initialize":
            asked = params.get("protocolVersion")
            return self.reply(200, {"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": asked if asked in ("2025-06-18", LEGACY) else LEGACY, "capabilities": {"tools": {}},
                "serverInfo": {"name": "example-agent", "version": "1"}}}, {"Mcp-Session-Id": SESSION})
        if h.get("mcp-session-id") != SESSION:
            # what a 2025-11-25 SDK answers before initialize: not a recognized modern error
            return self.reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": pre_session_code, "message": "Bad Request: Server not initialized"}})
        if h.get("mcp-protocol-version") != LEGACY:
            return self.reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "Bad Request: Unsupported protocol version"}})
        if method == "notifications/initialized":
            self.server.initialized = True
            return self.reply(202)
        if not self.server.initialized:
            return self.reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "Bad Request: not initialized"}})
        result = answer(rid, method, params)
        if result is None:
            return self.reply(200, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}})
        self.reply(200, result)


class FixtureCase(unittest.TestCase):
    mode = "strict"

    def setUp(self):
        self.server = Fixture(self.mode)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def probe(self, declared=None):
        """A probe pointed at the fixture; `declared` writes a manifest whose mcp capability names that protocolRevision."""
        descriptor = {"id": "example-agent", "instance": "default", "origin": "http://127.0.0.1:%d" % self.port}
        if declared is not None:
            directory = tempfile.TemporaryDirectory()
            self.addCleanup(directory.cleanup)
            manifest = Path(directory.name) / "fabric-agent.json"
            manifest.write_text(json.dumps({"capabilities": [{"name": "example.echo", "profile": {"kind": "mcp", "protocolRevision": declared}}]}))
            descriptor["fabricManifest"] = str(manifest)
        probe = checker.Probe(Path("/nonexistent"), descriptor, Path("/nonexistent"), True)
        probe.token = TOKEN
        probe.wk = {"surfaces": {"mcp": {"path": "/mcp"}}}
        return probe

    def raw(self, message, headers):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            base = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "Authorization": "Bearer " + TOKEN}
            base.update(headers)
            conn.request("POST", "/mcp", body=json.dumps(message).encode(), headers=base)
            resp = conn.getresponse()
            return resp.status, json.loads(resp.read() or b"null")
        finally:
            conn.close()

    def methods(self):
        return [s["method"] for s in self.server.seen]


def modern(method, params=None, rid=1):
    body = dict(params or {})
    body["_meta"] = {"io.modelcontextprotocol/protocolVersion": MODERN, "io.modelcontextprotocol/clientCapabilities": {}}
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": body}


class HeaderDerivationTests(unittest.TestCase):
    """The headers come from the JSON-RPC body and nothing else."""

    def test_every_request_names_its_method(self):
        for method in ("tools/list", "server/discover", "initialize", "ping"):
            self.assertEqual(checker.mcp_headers({"jsonrpc": "2.0", "id": 1, "method": method, "params": {}}), {"Mcp-Method": method})

    def test_a_notification_names_its_method_too(self):
        self.assertEqual(checker.mcp_headers({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                         {"Mcp-Method": "notifications/initialized"})

    def test_named_methods_carry_mcp_name_from_the_body(self):
        cases = (("tools/call", {"name": "fabric.job.get", "arguments": {}}, "fabric.job.get"),
                 ("prompts/get", {"name": "example-prompt"}, "example-prompt"),
                 ("resources/read", {"uri": "file:///example/config.json"}, "file:///example/config.json"))
        for method, params, name in cases:
            self.assertEqual(checker.mcp_headers({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}),
                             {"Mcp-Method": method, "Mcp-Name": name})

    def test_a_named_method_without_a_name_sends_no_mcp_name(self):
        self.assertEqual(checker.mcp_headers({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}}), {"Mcp-Method": "tools/call"})

    def test_unsafe_names_use_the_base64_sentinel(self):
        # the spec's own encoding table
        for value, encoded in (("us-west1", "us-west1"),
                               ("Hello, 世界", "=?base64?SGVsbG8sIOS4lueVjA==?="),
                               (" padded ", "=?base64?IHBhZGRlZCA=?="),
                               ("line1\nline2", "=?base64?bGluZTEKbGluZTI=?="),
                               ("=?base64?literal?=", "=?base64?PT9iYXNlNjQ/bGl0ZXJhbD89?=")):
            self.assertEqual(checker.encode_header_value(value), encoded, value)
            self.assertEqual(decode_name(checker.encode_header_value(value)), value)


class StrictFixtureTests(FixtureCase):
    """The fixture is strict: a missing or wrong header is refused, so a pass below means something."""

    def test_missing_headers_are_refused_with_header_mismatch(self):
        status, body = self.raw(modern("tools/list"), {"MCP-Protocol-Version": MODERN})
        self.assertEqual((status, body["error"]["code"]), (400, HEADER_MISMATCH))
        status, body = self.raw(modern("tools/call", {"name": "fabric.job.get", "arguments": {"id": "x"}}),
                                {"MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/call"})
        self.assertEqual((status, body["error"]["code"]), (400, HEADER_MISMATCH))
        self.assertIn("Mcp-Name", body["error"]["message"])

    def test_wrong_headers_are_refused_with_header_mismatch(self):
        status, body = self.raw(modern("tools/list"), {"MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/call"})
        self.assertEqual((status, body["error"]["code"]), (400, HEADER_MISMATCH))
        status, body = self.raw(modern("tools/call", {"name": "fabric.job.get", "arguments": {"id": "x"}}),
                                {"MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/call", "Mcp-Name": "fabric.job.cancel"})
        self.assertEqual((status, body["error"]["code"]), (400, HEADER_MISMATCH))
        status, body = self.raw(modern("tools/list"), {"MCP-Protocol-Version": "2025-11-25", "Mcp-Method": "tools/list"})
        self.assertEqual((status, body["error"]["code"]), (400, HEADER_MISMATCH))

    def test_matching_headers_are_served(self):
        status, body = self.raw(modern("tools/call", {"name": "fabric.job.get", "arguments": {"id": "x"}}),
                                {"MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/call", "Mcp-Name": "=?base64?ZmFicmljLmpvYi5nZXQ=?="})
        self.assertEqual(status, 200)
        self.assertTrue(body["result"]["isError"])


class ProbeAgainstStrictServerTests(FixtureCase):
    def test_tools_list_and_a_named_call_pass_with_matching_headers(self):
        probe = self.probe()
        listing = probe.mcp_call("tools/list", {})
        self.assertEqual([t["name"] for t in listing["result"]["tools"]], ["fabric.job.get"])
        called = probe.mcp_call("tools/call", {"name": "fabric.job.get", "arguments": {"id": "probe-x"}})
        self.assertTrue(called["result"]["isError"])
        self.assertEqual(self.methods(), ["tools/list", "tools/call"], "no handshake against a modern server")
        listed, call = self.server.seen
        self.assertEqual(listed["headers"]["mcp-method"], "tools/list")
        self.assertNotIn("mcp-name", listed["headers"])
        self.assertEqual((call["headers"]["mcp-method"], call["headers"]["mcp-name"]), ("tools/call", "fabric.job.get"))
        self.assertEqual(call["headers"]["mcp-protocol-version"], MODERN)

    def test_the_interop_rules_pass_end_to_end(self):
        probe = self.probe()
        probe.interop_rules()
        verdicts = {r["rule"]: r["verdict"] for r in probe.results}
        self.assertEqual(verdicts["interop.unknown-job"], "PASS", probe.results)
        self.assertEqual(verdicts["interop.trace-propagation"], "PASS", probe.results)
        self.assertNotIn("FAIL", verdicts.values(), probe.results)
        self.assertNotIn("initialize", self.methods())

    def test_a_header_mismatch_is_reported_not_fallen_back_from(self):
        probe = self.probe()
        original = checker.mcp_headers
        checker.mcp_headers = lambda message: {"Mcp-Method": "ping"}  # a deliberately wrong derivation
        try:
            with self.assertRaises(OSError) as caught:
                probe.mcp_call("tools/list", {})
        finally:
            checker.mcp_headers = original
        self.assertIn("HTTP 400", str(caught.exception))
        self.assertIn("-32020", str(caught.exception))
        self.assertEqual(self.methods(), ["tools/list"], "a modern error is never a reason to try initialize")


class ProbeAgainstUnsupportedVersionTests(FixtureCase):
    mode = "unsupported"

    def test_an_unsupported_version_error_is_modern_and_surfaces(self):
        with self.assertRaises(OSError) as caught:
            self.probe().mcp_call("tools/list", {})
        self.assertIn("-32022", str(caught.exception))
        self.assertEqual(self.methods(), ["tools/list"])


class ProbeAgainstLegacyServerTests(FixtureCase):
    mode = "legacy"

    def test_the_probe_falls_back_to_initialize_and_keeps_the_session(self):
        probe = self.probe()
        listing = probe.mcp_call("tools/list", {})
        self.assertEqual([t["name"] for t in listing["result"]["tools"]], ["fabric.job.get"])
        called = probe.mcp_call("tools/call", {"name": "fabric.job.get", "arguments": {"id": "probe-x"}})
        self.assertTrue(called["result"]["isError"])
        self.assertEqual(self.methods(), ["tools/list", "initialize", "notifications/initialized", "tools/list", "tools/call"],
                         "one modern attempt, then the legacy era is remembered")
        init, note, listed, call = self.server.seen[1:]
        self.assertEqual(init["body"]["params"]["protocolVersion"], LEGACY)
        self.assertEqual(init["headers"]["mcp-method"], "initialize")
        self.assertEqual(note["headers"]["mcp-method"], "notifications/initialized")
        self.assertNotIn("id", note["body"])
        for later in (note, listed, call):
            self.assertEqual(later["headers"]["mcp-session-id"], SESSION)
            self.assertEqual(later["headers"]["mcp-protocol-version"], LEGACY)
            self.assertNotIn("io.modelcontextprotocol/protocolVersion", (later["body"].get("params") or {}).get("_meta") or {})
        self.assertEqual(call["headers"]["mcp-name"], "fabric.job.get")
        self.assertEqual(probe.mcp_era, "legacy")

    def test_without_a_declared_revision_the_legacy_pass_is_named_not_hidden(self):
        probe = self.probe()
        probe.interop_rules()
        results = {r["rule"]: r for r in probe.results}
        self.assertEqual(results["interop.unknown-job"]["verdict"], "PASS", probe.results)
        self.assertEqual(results["interop.trace-propagation"]["verdict"], "PASS", probe.results)
        era = results["interop.mcp-revision"]
        self.assertEqual(era["verdict"], "NOT_RUN", era)
        self.assertIn("legacy %s session" % LEGACY, era["evidence"])
        self.assertIn("-32000", era["evidence"], "the modern refusal is quoted")

    def test_a_service_declaring_only_a_legacy_revision_passes_legacy(self):
        probe = self.probe(declared=LEGACY)
        probe.interop_rules()
        era = {r["rule"]: r for r in probe.results}["interop.mcp-revision"]
        self.assertEqual(era["verdict"], "PASS", era)
        self.assertIn("legacy %s session" % LEGACY, era["evidence"])

    def test_a_service_declaring_2026_07_28_fails_when_only_legacy_works(self):
        probe = self.probe(declared=MODERN)
        probe.interop_rules()
        era = {r["rule"]: r for r in probe.results}["interop.mcp-revision"]
        self.assertEqual(era["verdict"], "FAIL", era)
        self.assertIn(MODERN, era["evidence"])
        self.assertIn(LEGACY, era["evidence"])

    def test_the_legacy_session_is_closed_with_delete(self):
        probe = self.probe()
        probe.interop_rules()
        self.assertEqual(len(self.server.deleted), 1, self.methods())
        self.assertEqual(self.server.deleted[0]["mcp-protocol-version"], LEGACY)
        self.assertEqual(self.methods()[-1], "DELETE")
        self.assertIsNone(probe.mcp_session)


class ProbeAgainstBrokenModernPathTests(FixtureCase):
    """A dual-era server whose 2026-07-28 path is broken: the legacy session works, the contract does not."""
    mode = "broken_modern"

    def test_a_fallback_pass_fails_the_declared_revision(self):
        probe = self.probe(declared=MODERN)
        probe.interop_rules()
        results = {r["rule"]: r for r in probe.results}
        self.assertEqual(results["interop.unknown-job"]["verdict"], "PASS", "the legacy session itself works")
        era = results["interop.mcp-revision"]
        self.assertEqual(era["verdict"], "FAIL", era)
        self.assertIn("-32600", era["evidence"])
        self.assertIn("legacy %s session" % LEGACY, era["evidence"])


class ProbeAgainstStrictServerEraTests(FixtureCase):
    def test_a_modern_server_passes_the_revision_rule(self):
        probe = self.probe(declared=MODERN)
        probe.interop_rules()
        era = {r["rule"]: r for r in probe.results}["interop.mcp-revision"]
        self.assertEqual(era["verdict"], "PASS", era)
        self.assertIn(MODERN, era["evidence"])
        self.assertNotIn("DELETE", self.methods(), "no session, nothing to close")

    def test_modern_requests_carry_client_info(self):
        self.probe().mcp_call("tools/list", {})
        meta = self.server.seen[0]["body"]["params"]["_meta"]
        self.assertEqual(meta["io.modelcontextprotocol/clientInfo"]["name"], "fabric-check-service")
        self.assertIn("version", meta["io.modelcontextprotocol/clientInfo"])


class EmptyListBodyTests(FixtureCase):
    mode = "empty_list"

    def test_an_empty_200_on_tools_list_fails_instead_of_dropping_rules(self):
        probe = self.probe(declared=MODERN)
        probe.interop_rules()
        results = {r["rule"]: r for r in probe.results}
        self.assertEqual(results["interop.tools-match"]["verdict"], "FAIL", probe.results)
        self.assertIn("no JSON-RPC object", results["interop.tools-match"]["evidence"])

    def test_mcp_call_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.probe().mcp_call("tools/list", {})


class EmptyCallBodyTests(FixtureCase):
    mode = "empty_call"

    def test_an_empty_200_on_tools_call_fails_the_rule_without_a_crash(self):
        probe = self.probe()
        probe.interop_rules()
        results = {r["rule"]: r for r in probe.results}
        self.assertEqual(results["interop.unknown-job"]["verdict"], "FAIL", probe.results)
        self.assertIn("no JSON-RPC object", results["interop.unknown-job"]["evidence"])


class EmptySseBodyTests(unittest.TestCase):
    def test_an_event_stream_without_data_is_not_a_message(self):
        with self.assertRaises(ValueError):
            checker.rpc_body({"content-type": "text/event-stream"}, b": keep-alive\n\n")
        with self.assertRaises(ValueError):
            checker.rpc_body({"content-type": "application/json"}, b"[1, 2]")


class FailedLegacyOpenTests(FixtureCase):
    mode = "legacy_bad_notification"

    def test_a_failed_handshake_leaves_no_session_behind(self):
        probe = self.probe()
        with self.assertRaises(OSError) as caught:
            probe.mcp_call("tools/list", {})
        self.assertIn("notifications/initialized", str(caught.exception))
        self.assertIsNone(probe.mcp_session)
        self.assertIsNone(probe.mcp_era)
        self.assertEqual(probe.mcp_revision, fi.MCP_REVISION)


if __name__ == "__main__":
    unittest.main()
