"""fabric_a2a_server.py (FAA-10): an Agent Card built from capabilities and checked before it is served, the A2A 1.0
JSON-RPC binding over the interop job store (a task is a job; input-required answers by text or inputResponses; the
result envelope an artifact; another caller's task is not found), server-sent events for a stream, and the bounded
client that reaches only the operator's origins with a credential from the environment. The twin is
fabric-a2a-server.test.mjs. The live interop test against a Hermes A2A endpoint is not here (blocked, FAA-10)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_fabric_service import load

srv = load("fabric_a2a_server")
probe = load("check_service_a2a")
interop = load("fabric_interop")
rules = load("check_service_rules")
ORIGIN = "http://127.0.0.1:47000"
CAPS = [{"name": "notes.draft", "description": "Drafts a note.", "examples": ["Draft a note about Monday."]}]


def authorize(headers):
    return {"key-a": "caller-a", "key-b": "caller-b"}.get(headers.get("x-example-key"))


class Card(unittest.TestCase):
    def test_a_card_from_capabilities_passes_the_reading_side(self):
        card = srv.agent_card(name="Example Agent", description="Drafts notes.", version="0.2.0", url=ORIGIN + "/a2a/v1",
                              capabilities=CAPS, security_schemes={"own": {"apiKeySecurityScheme": {"location": "header", "name": "X-Example-Key"}}})
        self.assertEqual(card["skills"][0]["id"], "notes.draft")
        self.assertEqual(card["supportedInterfaces"], [{"url": ORIGIN + "/a2a/v1", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}])
        self.assertEqual(srv.agent_card_findings(card, origin=ORIGIN), [])

    def test_a_card_that_takes_the_descriptor_token_is_never_served(self):
        with self.assertRaises(srv.A2AError):
            srv.agent_card(name="E", description="d", version="1", url=ORIGIN + "/a2a/v1", capabilities=CAPS,
                           security_schemes={"t": {"apiKeySecurityScheme": {"location": "header", "name": "X-Fabric-Token"}}},
                           descriptor_header="X-Fabric-Token")
        with self.assertRaises(srv.A2AError):
            srv.agent_card(name="E", description="d", version="1", url="http://127.0.0.1:1/a2a", capabilities=[{"name": "bad id!"}])


class Binding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.jobs = interop.JobStore(Path(self.tmp.name) / "jobs")
        self.reply = None

        def handler(start):
            if "hello" in srv.text_of(start.message):
                return srv.agent_message("hi")
            start.start("notes.draft")
            return None
        self.binding = srv.A2ABinding(self.jobs, handler, skills=["notes.draft"], authorize=authorize)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, method, params, key="key-a", **headers):
        body = json.dumps({"jsonrpc": "2.0", "id": 7, "method": method, "params": params}).encode()
        return self.binding.handle(body, dict({"X-Example-Key": key}, **headers))

    def send(self, text, **extra):
        return self.call("SendMessage", {"message": dict({"role": "ROLE_USER", "parts": [{"text": text}], "messageId": "m1"}, **extra)})

    def test_a_reply_with_no_task(self):
        status, body = self.send("hello")
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["message"]["parts"], [{"text": "hi"}])
        self.assertTrue(body["result"]["message"]["contextId"].startswith("ctx-"))

    def test_a_task_is_a_job_and_only_its_caller_reads_it(self):
        task = self.send("draft it", contextId="ctx-1")[1]["result"]["task"]
        self.assertEqual((task["status"]["state"], task["contextId"]), ("TASK_STATE_WORKING", "ctx-1"))
        self.assertEqual(self.call("GetTask", {"id": task["id"]})[1]["result"]["id"], task["id"])
        self.assertEqual(self.call("GetTask", {"id": task["id"]}, key="key-b")[1]["error"]["code"], -32001)
        self.assertEqual(self.call("GetTask", {"id": "job_" + "0" * 24})[1]["error"]["code"], -32001)

    def test_input_required_is_answered_by_text_or_by_input_responses(self):
        task_id = self.send("draft it")[1]["result"]["task"]["id"]
        self.jobs.request_input(task_id, {"tone": interop.choice_request("Which tone?", "tone", [("warm", "Warm"), ("dry", "Dry")])})
        task = self.call("GetTask", {"id": task_id})[1]["result"]
        self.assertEqual(task["status"]["state"], "TASK_STATE_INPUT_REQUIRED")
        self.assertIn("Which tone?", task["status"]["message"]["parts"][0]["text"])
        answered = self.send("warm", taskId=task_id)[1]["result"]["task"]
        self.assertEqual(answered["status"]["state"], "TASK_STATE_WORKING")
        self.jobs.request_input(task_id, {"tone": interop.choice_request("Which tone?", "tone", [("warm", "Warm"), ("dry", "Dry")])})
        message = {"role": "ROLE_USER", "messageId": "m2", "taskId": task_id,
                   "parts": [{"data": {"inputResponses": {"tone": {"action": "accept", "content": {"tone": "dry"}}}}}]}
        self.assertEqual(self.call("SendMessage", {"message": message})[1]["result"]["task"]["status"]["state"], "TASK_STATE_WORKING")
        self.assertEqual(self.send("again", taskId=task_id)[1]["error"]["code"], -32602)

    def test_the_result_envelope_is_an_artifact_and_an_ended_task_is_not_cancelable(self):
        task_id = self.send("draft it")[1]["result"]["task"]["id"]
        envelope = interop.result_envelope(outcome="succeeded", done=[], proof=[], scope={}, not_verified=[], output={"note": "x"},
                                           usage={"inputTokens": 0, "outputTokens": 0, "wallMs": 1}, producer={"id": "example-agent"})
        self.jobs.complete(task_id, envelope)
        task = self.call("GetTask", {"id": task_id})[1]["result"]
        self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED")
        self.assertEqual(task["artifacts"][0]["parts"][0]["data"]["output"], {"note": "x"})
        self.assertEqual(self.call("CancelTask", {"id": task_id})[1]["error"]["code"], -32002)

    def test_cancel_and_failure(self):
        task_id = self.send("draft it")[1]["result"]["task"]["id"]
        self.assertEqual(self.call("CancelTask", {"id": task_id})[1]["result"]["status"]["state"], "TASK_STATE_CANCELED")
        other = self.send("draft it")[1]["result"]["task"]["id"]
        self.jobs.fail(other, "upstream", "the model did not answer")
        status = self.call("GetTask", {"id": other})[1]["result"]["status"]
        self.assertEqual(status["state"], "TASK_STATE_FAILED")
        self.assertEqual(status["message"]["parts"][1]["data"], {"code": "upstream"})

    def test_refusals(self):
        self.assertEqual(self.binding.handle(b"{", {"X-Example-Key": "key-a"})[1]["error"]["code"], -32700)
        self.assertEqual(self.call("Nope", {})[1]["error"]["code"], -32601)
        self.assertEqual(self.call("GetTask", {"id": "x"}, **{"A2A-Version": "0.3"})[1]["error"]["code"], -32009)
        self.assertEqual(self.call("SendMessage", {"message": {"parts": []}})[1]["error"]["code"], -32602)
        self.assertEqual(self.call("GetTask", {"id": "x"}, key="nobody"), (401, None))
        self.assertEqual(self.binding.handle(b"x" * (srv.MAX_BODY + 1), {"X-Example-Key": "key-a"}), (413, None))

    def test_a_stream_sends_the_task_then_each_change(self):
        params = {"message": {"role": "ROLE_USER", "parts": [{"text": "draft it"}], "messageId": "m1"}}
        events = self.binding.stream(params, "caller-a", rid=3, poll_s=0, deadline_s=5,
                                     sleep=lambda s: self.jobs.cancel(self.jobs_last()) if self.jobs_last() else None)
        first = next(events)
        self.assertTrue(first.startswith("data: ") and first.endswith("\n\n"))
        self._last = json.loads(first[6:])["result"]["task"]["id"]
        update = json.loads(next(events)[6:])["result"]["statusUpdate"]
        self.assertEqual((update["status"]["state"], update["final"]), ("TASK_STATE_CANCELED", True))
        self.assertEqual(list(events), [])

    def jobs_last(self):
        return getattr(self, "_last", None)


class Client(unittest.TestCase):
    CARD = {"name": "Peer", "supportedInterfaces": [{"url": "https://peer.example/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}]}

    def transport(self, answers):
        self.sent = []

        def send(method, url, headers, body, timeout_s, max_bytes):
            self.sent.append((method, url, headers, json.loads(body) if body else None))
            return answers.pop(0)
        return send

    def test_only_the_operators_origins(self):
        client = srv.A2AClient(["https://peer.example"], transport=self.transport([]))
        with self.assertRaises(srv.A2AError):
            client.discover("https://other.example")
        with self.assertRaises(srv.A2AError):
            srv.A2AClient([])
        card = dict(self.CARD, supportedInterfaces=[{"url": "https://elsewhere.example/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}])
        client = srv.A2AClient(["https://peer.example:443"], transport=self.transport([(200, {}, json.dumps(card).encode())]))
        with self.assertRaises(srv.A2AError):
            client.discover("https://peer.example")

    def test_discover_call_get_cancel_with_the_key_from_the_environment(self):
        task = {"id": "t1", "contextId": "c1", "status": {"state": "TASK_STATE_WORKING"}}
        answers = [(200, {}, json.dumps(self.CARD).encode())] + [(200, {}, json.dumps({"jsonrpc": "2.0", "id": i, "result": {"task": task}}).encode()) for i in (1, 2, 3)]
        client = srv.A2AClient(["https://peer.example"], credential_env="EXAMPLE_PEER_KEY", transport=self.transport(answers))
        found = client.discover("https://peer.example")
        self.assertEqual(found["url"], "https://peer.example/a2a")
        with mock.patch.dict(os.environ, {"EXAMPLE_PEER_KEY": "k-123"}):
            self.assertEqual(client.call(found["url"], "draft it")["task"]["id"], "t1")
            client.get(found["url"], "t1")
            client.cancel(found["url"], "t1")
        methods = [s[3]["method"] for s in self.sent[1:]]
        self.assertEqual(methods, ["SendMessage", "GetTask", "CancelTask"])
        self.assertEqual(self.sent[1][2]["Authorization"], "Bearer k-123")
        self.assertEqual(self.sent[1][2]["A2A-Version"], "1.0")
        self.assertEqual(self.sent[1][3]["params"]["message"]["role"], "ROLE_USER")

    def test_a_missing_key_and_a_refusal(self):
        client = srv.A2AClient(["https://peer.example"], credential_env="EXAMPLE_PEER_KEY",
                               transport=self.transport([(200, {}, b'{"jsonrpc":"2.0","id":1,"error":{"code":-32001,"message":"no"}}')]))
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(srv.A2AError):
                client.get("https://peer.example/a2a", "t1")
        with mock.patch.dict(os.environ, {"EXAMPLE_PEER_KEY": "k-123"}):
            with self.assertRaises(srv.A2AError) as raised:
                client.get("https://peer.example/a2a", "t1")
        self.assertNotIn("k-123", str(raised.exception))


class Probe(unittest.TestCase):
    """check_service_a2a's rows against a binding the test serves; a command of its own beside check_service.py (D5)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.jobs = interop.JobStore(Path(self.tmp.name) / "jobs")

        def handler(start):
            start.start("notes.draft")
        self.binding = srv.A2ABinding(self.jobs, handler, skills=["notes.draft"], authorize=authorize)
        self.card = srv.agent_card(name="Example Agent", description="Drafts notes.", version="0.2.0", url=ORIGIN + "/a2a/v1",
                                   capabilities=CAPS)
        self.wk = {"surfaces": {"a2a": {"path": "/.well-known/agent-card.json", "protocolVersion": "1.0"}}}

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, method, url, headers, body):
        if method == "GET":
            return (200, self.card) if url == ORIGIN + "/.well-known/agent-card.json" else (404, None)
        status, answer = self.binding.handle(json.dumps(body).encode(), headers)
        return status, answer

    def verdicts(self, rows):
        return {rule: verdict for rule, verdict, _ in rows}

    def test_a_gated_remote_card_and_an_unreadable_surface_are_not_run_as_check_service_says(self):
        gated = lambda status: (lambda method, url, headers, body: (status, None))
        for status in (401, 403):
            rows = probe.a2a_rules(self.wk, ORIGIN, fetch=gated(status), remote=True)
            self.assertEqual(self.verdicts(rows)["a2a.card"], "NOT_RUN", rows)
            self.assertEqual(rules.a2a_card_verdict(self.wk, status, b"", remote=True, origin=ORIGIN,
                                                    descriptor_header="Authorization")[0], "NOT_RUN")
            self.assertIn("DEC-0122 item 2", dict((r, e) for r, _, e in rows)["a2a.card"])
        local = probe.a2a_rules(self.wk, ORIGIN, fetch=gated(401), remote=False)
        self.assertEqual(self.verdicts(local)["a2a.card"], "FAIL")
        bad = {"surfaces": {"a2a": {"path": "no-slash"}}}
        rows = probe.a2a_rules(bad, ORIGIN, fetch=self.fetch)
        self.assertEqual(self.verdicts(rows), {"a2a.surface": "NOT_RUN"})
        self.assertEqual(rules.a2a_card_verdict(bad, 0, b"", remote=False, origin=ORIGIN, descriptor_header="x")[0],
                         "NOT_RUN")

    def test_a_conforming_service_passes_and_task_states_wait_for_a_probe_message(self):
        rows = probe.a2a_rules(self.wk, ORIGIN, fetch=self.fetch, headers={"X-Example-Key": "key-a"})
        self.assertEqual(self.verdicts(rows), {"a2a.surface": "PASS", "a2a.card": "PASS", "a2a.interface": "PASS",
                                               "a2a.task-not-found": "PASS", "a2a.cancel-not-found": "PASS",
                                               "a2a.method-not-found": "PASS", "a2a.task-states": "NOT_RUN"})
        rows = probe.a2a_rules(self.wk, ORIGIN, fetch=self.fetch, headers={"X-Example-Key": "key-a"}, probe_text="ping")
        self.assertEqual(self.verdicts(rows)["a2a.task-states"], "PASS")

    def test_no_key_is_not_run_and_no_surface_is_not_run(self):
        rows = probe.a2a_rules(self.wk, ORIGIN, fetch=self.fetch)
        self.assertEqual(self.verdicts(rows)["a2a.task-not-found"], "NOT_RUN")
        self.assertEqual(probe.a2a_rules({}, ORIGIN, fetch=self.fetch), [("a2a.surface", "NOT_RUN", "the service declares no surfaces.a2a")])

    def test_a_card_with_a_process_member_fails(self):
        self.card = dict(self.card, pid=1)
        self.assertEqual(self.verdicts(probe.a2a_rules(self.wk, ORIGIN, fetch=self.fetch))["a2a.card"], "FAIL")


if __name__ == "__main__":
    unittest.main()
