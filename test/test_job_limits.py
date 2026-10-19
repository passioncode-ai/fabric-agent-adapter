"""Jobs under limits and uncertain effects (contract DEC-0087, FAC-SEM-119/120; FAA-56) in the Python interop kit:
the contract's vectors as test/fixtures/contract/job-limit-vectors.json vendors them, and the provider's side on a real
JobStore: a paused job, quota-exhausted, outcome-unknown, keys per caller and the answer to a repeated key, and the
usage gate between fabric-interop/0.1 and 0.2 readers."""

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
sys.path.insert(0, str(SCRIPTS))
fi = importlib.import_module("fabric_interop")

V = json.loads((Path(__file__).resolve().parent / "fixtures/contract/job-limit-vectors.json").read_text())


class VectorTests(unittest.TestCase):
    def test_every_pause_case(self):
        for c in V["pause"]:
            with self.subTest(c["name"]):
                self.assertEqual(fi.read_job_pause(c["answer"]), c["expected"])

    def test_every_caller_case(self):
        for c in V["caller"]:
            with self.subTest(c["name"]):
                answer = fi.job_caller_action(c["answer"], c["now"]) if "now" in c else fi.job_caller_action(c["answer"])
                self.assertEqual(answer, c["expected"])

    def test_every_key_case(self):
        for c in V["key"]:
            with self.subTest(c["name"]):
                self.assertEqual(fi.intent_idempotency_key(c["intent"]), c["expected"])

    def test_every_usage_case(self):
        for c in V["usage"]:
            with self.subTest(c["name"]):
                found = ["%s %s" % (f["code"], f["instancePath"]) for f in fi.usage_findings(c["usage"], "")]
                self.assertEqual(found, c["findings"])

    def test_every_reader_case(self):
        for c in V["reader"]:
            with self.subTest(c["name"]):
                self.assertIs(fi.reads_null_usage(c["meta"]), c["expected"])

    def test_every_semantic_fixture(self):
        for c in V["rules"]:
            with self.subTest(c["name"]):
                self.assertEqual(fi.job_limit_rules(c["kind"], c["value"]), c["findings"])

    def test_hostile_input_never_throws(self):
        for value in (None, 0, "x", [], {}, {"job": None}, {"job": {"id": "", "status": "failed"}}, float("nan")):
            fi.read_job_pause(value)
            fi.job_caller_action(value, value)
            self.assertIsNone(fi.intent_idempotency_key(value))
            fi.reads_null_usage(value)
            fi.usage_findings(value, "")
        self.assertIsNone(fi.intent_idempotency_key({"agentId": "a", "capability": "c", "input": {"n": float("inf")}}))
        self.assertIsNone(fi.intent_idempotency_key({"agentId": "a", "capability": "c", "input": {"s": "\ud800"}}))


class ProviderTests(unittest.TestCase):
    NOW = "2026-10-19T10:00:00Z"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.jobs = fi.JobStore(Path(self.tmp.name) / "jobs")

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, caller="caller-a", key="k-1"):
        return self.jobs.create("media.order", {"brief": "x"}, caller=caller, idempotency_key=key)["job"]["id"]

    def test_a_paused_job_reads_as_paused_and_a_caller_waits(self):
        job_id = self.start()
        job = self.jobs.pause(job_id, resets_at="2026-10-19T12:00:00Z", text="the provider's hourly quota")
        self.assertEqual(job["statusMessage"], "quota-exhausted until 2026-10-19T12:00:00Z: the provider's hourly quota")
        self.assertEqual(fi.read_job_pause({"job": job}), {"paused": True, "resetsAt": "2026-10-19T12:00:00Z"})
        self.assertEqual(fi.job_caller_action({"job": job}, self.NOW), {"action": "wait", "notBefore": "2026-10-19T12:00:00Z"})
        self.assertEqual(self.jobs.pause(job_id)["statusMessage"], "quota-exhausted")
        for bad in ("2026-10-19T12:00:00+02:00", "2026-02-30T12:00:00Z", "2026-10-19T12:00:00.1234Z"):
            with self.assertRaises(fi.InteropError):
                self.jobs.pause(job_id, resets_at=bad)
        with self.assertRaises(fi.InteropError):
            self.jobs.pause(job_id, text=" \t")

    def test_quota_exhausted_carries_its_data(self):
        job_id = self.start()
        job = self.jobs.quota_exhausted(job_id, "the monthly plan is used up", retryable=True, resets_at="2026-11-01T00:00:00Z")
        self.assertEqual(job["error"], {"code": "quota-exhausted", "message": "the monthly plan is used up",
                                        "data": {"retryable": True, "resetsAt": "2026-11-01T00:00:00Z"}})
        self.assertEqual(fi.job_caller_action({"job": job}, self.NOW), {"action": "resend", "notBefore": "2026-11-01T00:00:00Z"})
        other = self.start(key="k-2")
        with self.assertRaises(fi.InteropError, msg="resetsAt only with retryable: true"):
            self.jobs.quota_exhausted(other, "x", retryable=False, resets_at="2026-11-01T00:00:00Z")
        job = self.jobs.quota_exhausted(other, "a person raises the budget", retryable=False)
        self.assertEqual(fi.job_caller_action({"job": job}, self.NOW), {"action": "person"})

    def test_outcome_unknown_is_reconciled_never_resent(self):
        job_id = self.start()
        job = self.jobs.outcome_unknown(job_id, "the payment request timed out after it was sent", {"mayHaveRun": True})
        self.assertEqual(job["error"]["code"], "outcome-unknown")
        self.assertEqual(fi.job_caller_action({"job": job}, self.NOW), {"action": "reconcile"})
        self.assertEqual(self.jobs.repeat("caller-a", "k-1", self.NOW)["decision"], "same")
        with self.assertRaises(fi.InteropError):
            self.start()

    def test_keys_are_per_caller(self):
        first = self.start(caller="caller-a")
        second = self.start(caller="caller-b")
        self.assertNotEqual(first, second, "two callers that send the same key never share a job")
        self.assertEqual(self.jobs.repeat("caller-a", "k-1", self.NOW), {"decision": "same", "job": self.jobs.get(first)})
        self.assertEqual(self.jobs.repeat("caller-c", "k-1", self.NOW), {"decision": "new", "job": None})
        with self.assertRaises(fi.InteropError, msg="a key that names a running job is answered with it, not run twice"):
            self.start(caller="caller-a")

    def test_a_repeated_key_after_a_limit_runs_once_when_the_limit_no_longer_holds(self):
        first = self.start()
        self.jobs.quota_exhausted(first, "hourly quota", retryable=True, resets_at="2026-10-19T11:00:00Z")
        self.assertEqual(self.jobs.repeat("caller-a", "k-1", self.NOW)["decision"], "same", "before the reset")
        self.assertEqual(self.jobs.repeat("caller-a", "k-1", "2026-10-19T11:00:00Z")["decision"], "run")
        second = self.jobs.create("media.order", {"brief": "x"}, caller="caller-a", idempotency_key="k-1", now="2026-10-19T11:00:00Z")["job"]["id"]
        self.assertNotEqual(first, second)
        self.assertEqual(self.jobs.repeat("caller-a", "k-1", "2026-10-19T11:00:01Z"), {"decision": "same", "job": self.jobs.get(second)},
                         "the key now names the job that ran, once")

    def test_a_person_act_and_an_approval_let_the_key_run_again(self):
        held = self.start()
        self.jobs.quota_exhausted(held, "budget", retryable=False)
        self.assertEqual(self.jobs.repeat("caller-a", "k-1", self.NOW)["decision"], "same")
        self.assertEqual(self.jobs.repeat("caller-a", "k-1", self.NOW, limit_holds=False)["decision"], "run")
        window = self.start(key="k-2")
        self.jobs.fail(window, "limit-reached", "the grant's spend window is used up", {"approval": "urn:example:approval:1"})
        self.assertEqual(self.jobs.repeat("caller-a", "k-2", self.NOW)["decision"], "same")
        self.assertEqual(self.jobs.repeat("caller-a", "k-2", self.NOW, approval_granted=True)["decision"], "run")
        done = self.start(key="k-3")
        self.jobs.fail(done, "bad-input", "the brief is empty")
        self.assertEqual(self.jobs.repeat("caller-a", "k-3", self.NOW, limit_holds=False, approval_granted=True)["decision"], "same")

    def test_the_key_file_is_the_one_the_node_kit_reads(self):
        import hashlib
        job_id = self.start(caller="caller-a", key="k-1")
        name = hashlib.sha256('["caller-a","k-1"]'.encode()).hexdigest() + ".json"
        self.assertEqual(json.loads((self.jobs.dir / "keys" / name).read_text()), {"job": job_id})

    def test_the_usage_gate(self):
        measured = {"inputTokens": 1200, "outputTokens": None, "wallMs": 5100, "costUsd": None}
        old = {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
        new = fi.request_meta()
        self.assertEqual(new["protocols"], ["fabric-interop/0.1", "fabric-interop/0.2"])
        self.assertEqual(fi.usage_toward(measured, old), {"inputTokens": 1200, "outputTokens": 0, "wallMs": 5100, "costUsd": 0},
                         "toward a 0.1 reader: the measured lower bound, no null, no partial")
        self.assertEqual(fi.usage_toward(measured, new), dict(measured, partial=True), "toward a 0.2 reader: null, partial true")
        self.assertEqual(fi.usage_toward({"inputTokens": 1, "outputTokens": 2, "wallMs": 3}, new), {"inputTokens": 1, "outputTokens": 2, "wallMs": 3})
        with self.assertRaises(fi.InteropError, msg="partial false beside a null is FAC-SEM-119"):
            fi.usage_toward(dict(measured, partial=False), new)
        envelope = dict(outcome="succeeded", done=[], proof=[], scope={}, not_verified=[], output={}, producer={"agent": "example-agent"})
        self.assertEqual(fi.result_envelope(usage=measured, **envelope)["usage"]["outputTokens"], 0, "no request meta: a 0.1 reader")
        self.assertIsNone(fi.result_envelope(usage=measured, request_meta=new, **envelope)["usage"]["outputTokens"])
        with self.assertRaises(fi.InteropError):
            fi.result_envelope(usage={"inputTokens": -1, "outputTokens": 0, "wallMs": 0}, request_meta=new, **envelope)


if __name__ == "__main__":
    unittest.main()
