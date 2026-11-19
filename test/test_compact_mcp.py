"""McpToolServer.serve_compact: two doors, search and execute (FAA-356, agents database R33 O15, decision D-72)."""

import importlib.util
import json
from pathlib import Path
import subprocess
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
PARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
OBJECT = {"type": "object"}
RELAYED = {"id": "approve-reply", "title": "Approve the reply", "tool": "reviews.approve", "gate": "relayed"}
MEASURED = {"calls": 40, "total": 100, "window": "2026-11-11/2026-11-18"}


class CompactListingTests(unittest.TestCase):

    def server(self, compact=True, direct=None, tools=6, jobs=True, retired=None, **options):
        self.seen = []
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        store = fi.JobStore(Path(self.temp.name) / "jobs") if jobs else None
        server = fi.McpToolServer("example-agent", "1.0.0", jobs=store, **options)
        keep = lambda args, ctx: self.seen.append((ctx.tool, args, ctx)) or {"done": True}
        server.add_tool({"name": "reviews.approve", "description": "Approve a drafted reply", "inputSchema": OBJECT},
                        keep, action=RELAYED, target="reply")
        server.add_tool({"name": "notes.write", "description": "Write a note",
                         "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}, "idempotencyKey": {"type": "string"}},
                                         "examples": [{"text": "hello"}]}}, keep)
        for n in range(tools - 2):
            server.add_tool({"name": "example.op%d" % n, "description": "Operation %d" % n, "inputSchema": OBJECT}, keep)
        if compact:
            server.serve_compact("example-agent", direct, retired=retired)
        return server

    def rpc(self, server, method, params=None, headers=None, tier="T0"):
        return server.handle({"jsonrpc": "2.0", "id": 7, "method": method, "params": params or {}}, headers, tier=tier)

    def call(self, server, name, arguments, headers=None, tier="T0", meta=None):
        params = {"name": name, "arguments": arguments, "_meta": dict({"traceparent": PARENT}, **(meta or {}))}
        return self.rpc(server, "tools/call", params, headers, tier)["result"]

    def names(self, server):
        return [t["name"] for t in self.rpc(server, "tools/list")["result"]["tools"]]

    def test_the_listing_is_two_doors(self):
        self.assertEqual(self.names(self.server(jobs=False, tools=7)), ["example-agent.search", "example-agent.execute"])

    def test_the_job_tools_take_their_seats_with_no_measurement(self):
        # D-72: fabric.job.get and fabric.job.cancel sit beside the doors while the server has a job store
        self.assertEqual(self.names(self.server()), ["fabric.job.get", "fabric.job.cancel",
                                                     "example-agent.search", "example-agent.execute"])

    def test_without_serve_compact_the_listing_is_unchanged(self):
        names = self.names(self.server(compact=False))
        self.assertEqual(len(names), 8)
        self.assertIn("fabric.job.get", names)

    def test_a_short_listing_stays_as_it_is(self):
        server = self.server(tools=3)  # three tools and the two job tools: five
        self.assertEqual(self.names(server), ["reviews.approve", "notes.write", "example.op0", "fabric.job.get", "fabric.job.cancel"])

    def test_a_measured_direct_tool_is_listed_before_the_doors(self):
        server = self.server(direct={"notes.write": MEASURED})
        self.assertEqual(self.names(server), ["notes.write", "fabric.job.get", "fabric.job.cancel",
                                              "example-agent.search", "example-agent.execute"])
        three = {"example.op%d" % n: MEASURED for n in range(3)}
        self.assertEqual(self.names(self.server(direct=three, jobs=False)),
                         ["example.op0", "example.op1", "example.op2", "example-agent.search", "example-agent.execute"])

    def test_a_direct_tool_without_a_measured_case_is_refused(self):
        for measured in (None, {"calls": 19, "total": 20, "window": "w"}, {"calls": 29, "total": 100, "window": "w"},
                         {"calls": 40, "total": 30, "window": "w"}, {"calls": 40, "total": 100}, {"calls": True, "total": 100, "window": "w"}):
            with self.subTest(measured=measured), self.assertRaises(fi.InteropError):
                self.server(direct={"notes.write": measured})
        with self.assertRaises(fi.InteropError):
            self.server(direct={"example.op%d" % n: MEASURED for n in range(4)}, tools=6, jobs=False)
        with self.assertRaises(fi.InteropError):  # the job tools hold two of the three seats
            self.server(direct={"example.op%d" % n: MEASURED for n in range(2)}, tools=6)
        with self.assertRaises(fi.InteropError):
            self.server(direct={"not.served": MEASURED})
        with self.assertRaises(fi.InteropError):  # a job tool needs no measured seat of its own
            self.server(direct={"fabric.job.get": MEASURED})

    def test_search_marks_a_retired_name_with_its_day(self):
        found = self.call(self.server(direct={"notes.write": MEASURED}, retired="2026-11-19"),
                          "example-agent.search", {})["structuredContent"]
        ops = {op["name"]: op for op in found["operations"]}
        self.assertEqual(ops["example.op0"]["retired"], "2026-11-19")
        self.assertNotIn("retired", ops["notes.write"])  # listed directly
        self.assertNotIn("retired", ops["fabric.job.get"])  # listed beside the doors
        unmarked = self.call(self.server(), "example-agent.search", {})["structuredContent"]
        self.assertNotIn("retired", unmarked["operations"][0])
        mark = fi.COMPACT_RETIRED_META
        server = self.server(direct={"notes.write": MEASURED}, retired="2026-11-19")
        by_name = self.call(server, "example.op0", {})
        self.assertFalse(by_name["isError"])
        self.assertEqual(by_name["_meta"][mark], {"since": "2026-11-19", "replacedBy": "example-agent.execute"})
        self.assertIn("traceparent", by_name["_meta"])
        self.assertNotIn("retired", by_name.get("structuredContent") or {})  # the outputSchema still holds
        for unmarked_call in (self.call(server, "notes.write", {"text": "a"}),  # listed directly
                              self.call(server, "example-agent.execute", {"operation": "example.op0"}),
                              self.call(self.server(), "example.op0", {})):  # no retired day given
            self.assertNotIn(mark, unmarked_call.get("_meta") or {})
        for day in ("2026-13-01", "19.11.2026", 20261119):
            with self.subTest(day=day), self.assertRaises(fi.InteropError):
                self.server(retired=day)

    def test_the_domain_and_the_door_names_are_checked(self):
        server = self.server(compact=False)
        for domain in ("", "Example", "a b", None):
            with self.subTest(domain=domain), self.assertRaises(fi.InteropError):
                server.serve_compact(domain)
        server.add_tool({"name": "taken.search", "inputSchema": OBJECT}, lambda a, c: {})
        with self.assertRaises(fi.InteropError):
            server.serve_compact("taken")
        server.serve_compact("example-agent")
        with self.assertRaises(fi.InteropError):
            server.add_tool({"name": "example-agent.execute", "inputSchema": OBJECT}, lambda a, c: {})

    def test_search_answers_every_operation_with_its_gate_example_and_calls(self):
        server = self.server()
        self.call(server, "notes.write", {"text": "a"})
        found = self.call(server, "example-agent.search", {})["structuredContent"]
        self.assertEqual(found["total"], 8)
        ops = {op["name"]: op for op in found["operations"]}
        self.assertEqual(set(ops), {"reviews.approve", "notes.write", "example.op0", "example.op1", "example.op2",
                                    "example.op3", "fabric.job.get", "fabric.job.cancel"})
        self.assertEqual(ops["reviews.approve"]["gate"], "relayed")
        self.assertEqual(ops["notes.write"]["gate"], "none")
        self.assertEqual(ops["notes.write"]["example"], {"text": "hello"})
        self.assertEqual(ops["notes.write"]["calls"], 1)
        self.assertEqual(ops["notes.write"]["inputSchema"]["properties"]["text"], {"type": "string"})
        narrowed = self.call(server, "example-agent.search", {"query": "REPLY approve"})["structuredContent"]
        self.assertEqual([op["name"] for op in narrowed["operations"]], ["reviews.approve"])
        bad = self.call(server, "example-agent.search", {"query": 3})
        self.assertTrue(bad["isError"])
        self.assertEqual(bad["structuredContent"]["error"]["code"], "invalid-arguments")

    def test_execute_runs_the_operation_as_a_call_by_its_name(self):
        server = self.server()
        result = self.call(server, "example-agent.execute", {"operation": "notes.write", "arguments": {"text": "a"}})
        self.assertFalse(result["isError"])
        self.assertEqual(self.seen[-1][:2], ("notes.write", {"text": "a"}))
        self.assertEqual(server.calls, {"notes.write": 1})

    def test_execute_keeps_the_action_gate(self):
        server = self.server()
        refused = self.call(server, "example-agent.execute", {"operation": "reviews.approve", "arguments": {"reply": "r-7"}})
        self.assertTrue(refused["isError"])
        self.assertEqual(refused["structuredContent"]["error"]["code"], "operator-decision-required")
        self.assertEqual(self.seen, [])

    def test_execute_keeps_the_authorize_gate_under_the_operations_name(self):
        asked = []
        gate = lambda tool, headers, tier="T2": asked.append(tool) or {"ok": tool == "notes.write", "code": "scope-not-granted",
                                                                         "detail": "not-granted"}
        server = self.server(authorize=gate)
        self.assertFalse(self.call(server, "example-agent.execute", {"operation": "notes.write", "arguments": {}}, tier="T2")["isError"])
        refused = self.call(server, "example-agent.execute", {"operation": "example.op0"}, tier="T2")
        self.assertEqual(refused["structuredContent"]["error"]["code"], "scope-not-granted")
        self.assertEqual(asked, ["notes.write", "example.op0"])

    def test_execute_rewrites_mcp_name_so_the_header_check_passes(self):
        server = self.server()
        params = {"name": "example-agent.execute", "arguments": {"operation": "notes.write", "arguments": {}}}
        headers = fi.mcp_request_headers("tools/call", params)
        headers["Authorization"] = "Bearer x"
        seen_headers = []
        server.handlers["notes.write"] = lambda args, ctx: {"ok": True}
        server._identify = lambda h, tier: seen_headers.append((h.get("mcp-name"), h.get("authorization"))) or "agent:x"
        answer = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}, headers, tier="T0")
        self.assertFalse(answer["result"]["isError"], answer)
        self.assertEqual(seen_headers, [("notes.write", "Bearer x")])

    def test_execute_answers_typed_refusals(self):
        server = self.server()
        unknown = self.call(server, "example-agent.execute", {"operation": "notes.wirte"})["structuredContent"]["error"]
        self.assertEqual(unknown["code"], "unknown-operation")
        self.assertIn("notes.write", unknown["near"])
        for arguments in ({}, {"operation": 1}, {"operation": "notes.write", "arguments": []}, {"operation": "notes.write", "x": 1},
                          {"operation": "example.op0", "idempotencyKey": "key-12345"},
                          {"operation": "notes.write", "idempotencyKey": "short"},
                          {"operation": "notes.write", "idempotencyKey": "key-12345", "arguments": {"idempotencyKey": "other-123"}}):
            with self.subTest(arguments=arguments):
                error = self.call(server, "example-agent.execute", arguments)["structuredContent"]["error"]
                self.assertEqual(error["code"], "invalid-arguments")
        for door in ("example-agent.execute", "example-agent.search"):
            error = self.call(server, "example-agent.execute", {"operation": door})["structuredContent"]["error"]
            self.assertEqual(error["code"], "unknown-operation")
        self.assertEqual(self.seen, [])

    def test_execute_passes_the_idempotency_key_the_operation_takes(self):
        server = self.server()
        self.call(server, "example-agent.execute", {"operation": "notes.write", "arguments": {"text": "a"}, "idempotencyKey": "key-12345"})
        self.assertEqual(self.seen[-1][1], {"text": "a", "idempotencyKey": "key-12345"})

    def test_a_tool_keeps_answering_by_its_own_name(self):
        server = self.server()
        self.assertFalse(self.call(server, "example.op1", {})["isError"])
        job = self.call(server, "fabric.job.get", {"id": "job-unknown-1234"})
        self.assertIn("structuredContent", job)
        through = self.call(server, "example-agent.execute", {"operation": "fabric.job.get", "arguments": {"id": "job-unknown-1234"}})
        self.assertEqual(through["structuredContent"], job["structuredContent"])

    def test_results_are_json_text_too(self):
        server = self.server()
        result = self.call(server, "example-agent.search", {"query": "note"})
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])


def free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class CompactProbeTests(unittest.TestCase):
    """check_service.py against a live kit service whose listing is two doors: interop.compact-listing, and the
    capabilities still checked one by one through search (interop.tools-match)."""

    def setUp(self):
        import contextlib
        import io
        import threading
        sample = load("sample_service")
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.services = base / "services"
        port = free_port()
        common = ["--port", str(port), "--data-dir", str(base / "data")]
        test = self
        self.compact, self.direct, self.extra = True, None, 3

        class CompactService(sample.Service):
            def start(self):
                super().start()
                for n in range(test.extra):  # served but not declared, like a service's own helper tools
                    self.mcp.add_tool({"name": "sample.extra%d" % n, "description": "Extra %d" % n, "inputSchema": OBJECT},
                                      lambda args, ctx: {"ok": True})
                if test.compact:
                    self.mcp.serve_compact("sample", test.direct)

        self.sample, self.CompactService, self.common = sample, CompactService, common

    def run_probe(self):
        import contextlib
        import io
        import threading
        sample = self.sample
        svc = self.CompactService(sample.build_parser().parse_args(["serve"] + self.common))
        svc.start()
        server = sample.make_server(svc)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        thread.start()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sample.register(sample.build_parser().parse_args(
                    ["register"] + self.common + ["--services-dir", str(self.services)])), 0)
            out = subprocess.run([sys.executable, str(SCRIPTS / "check_service.py"), "sample", "--services-dir",
                                  str(self.services), "--json"], capture_output=True, text=True)
            return {r["rule"]: r for r in json.loads(out.stdout)["results"]}
        finally:
            server.shutdown()
            server.server_close()
            svc.lock.release()
            self.temp.cleanup()

    def test_two_doors_pass_and_every_capability_is_still_checked(self):
        results = self.run_probe()
        self.assertEqual(results["interop.compact-listing"]["verdict"], "PASS", results["interop.compact-listing"])
        self.assertIn("sample.search", results["interop.compact-listing"]["evidence"])
        self.assertEqual(results["interop.tools-match"]["verdict"], "PASS", results["interop.tools-match"])
        self.assertEqual(results["interop.job-tools"]["verdict"], "PASS", results["interop.job-tools"])

    def test_a_full_listing_of_more_than_five_is_not_run(self):
        self.compact = False
        results = self.run_probe()
        self.assertEqual(results["interop.compact-listing"]["verdict"], "NOT_RUN")
        self.assertIn("serve_compact", results["interop.compact-listing"]["evidence"])
        self.assertEqual(results["interop.tools-match"]["verdict"], "PASS")

    def test_a_short_listing_passes(self):
        self.extra = 0
        results = self.run_probe()
        self.assertEqual(results["interop.compact-listing"]["verdict"], "PASS")

    def test_a_direct_tool_without_its_measured_case_fails(self):
        results = self.run_probe_with_unmeasured_direct()
        self.assertEqual(results["interop.compact-listing"]["verdict"], "FAIL")
        self.assertIn("sample.extra0", results["interop.compact-listing"]["evidence"])

    def run_probe_with_unmeasured_direct(self):
        self.direct = {"sample.extra0": MEASURED}
        server_class = self.sample.fi.McpToolServer  # the sample's own copy of the module
        original = server_class._operation

        def drop_direct(server, tool):  # a server that lists a direct tool but hides its measurement
            operation = original(server, tool)
            operation.pop("direct", None)
            return operation
        server_class._operation = drop_direct
        self.addCleanup(setattr, server_class, "_operation", original)
        return self.run_probe()


if __name__ == "__main__":
    unittest.main()
