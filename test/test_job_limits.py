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

    def test_queue_full_never_ends_a_job(self):
        """DEC-0104: queue-full is a refusal at a job's start, never a job's end; the schema refuses a job it ended, so
        the store refuses to write one. QUEUE_FULL names the code in the facade."""
        self.assertEqual(fi.QUEUE_FULL, "queue-full")
        job_id = self.start()
        with self.assertRaises(fi.InteropError):
            self.jobs.fail(job_id, fi.QUEUE_FULL, "the queue is full")
        self.assertEqual(self.jobs.fail(job_id, "provider-error", "stopped")["status"], "failed")

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
        intent = "sha256:" + hashlib.sha256('["media.order",{"brief":"x"}]'.encode()).hexdigest()
        self.assertEqual(json.loads((self.jobs.dir / "keys" / name).read_text()), {"job": job_id, "intent": intent})
        self.assertEqual(fi.intent_digest("media.order", {"brief": "x"}), intent)

    def test_a_limited_key_runs_again_only_for_the_same_intent(self):
        """FAA-77 item 39: a quota-exhausted key admitted any intent; it admits only the one it was first sent with."""
        first = self.start()
        self.jobs.quota_exhausted(first, "hourly quota", retryable=True, resets_at="2026-10-19T11:00:00Z")
        later = "2026-10-19T11:00:00Z"
        for capability, given in (("media.order", {"brief": "y"}), ("media.refund", {"brief": "x"}),
                                  ("media.order", {"brief": "x", "to": "someone-else"})):
            with self.subTest(capability=capability, given=given):
                with self.assertRaisesRegex(fi.InteropError, "^idempotency-conflict"):
                    self.jobs.create(capability, given, caller="caller-a", idempotency_key="k-1", now=later)
        self.assertEqual(len(list(self.jobs.dir.glob("job_*.json"))), 1, "a refused intent starts nothing")
        second = self.jobs.create("media.order", {"brief": "x"}, caller="caller-a", idempotency_key="k-1", now=later)["job"]["id"]
        self.assertNotEqual(first, second)
        running = self.start(key="k-2")
        with self.assertRaisesRegex(fi.InteropError, "^idempotency-conflict", msg="a running job's key refuses another intent too"):
            self.jobs.create("media.order", {"brief": "z"}, caller="caller-a", idempotency_key="k-2")
        self.assertEqual(self.jobs.repeat("caller-a", "k-2", self.NOW)["job"]["id"], running)

    def legacy(self, job_id, key="k-1"):
        """Rewrite the key file as a kit before 0.41.0 wrote it: {"job": id}, no intent."""
        import hashlib
        name = hashlib.sha256(json.dumps(["caller-a", key], separators=(",", ":")).encode()).hexdigest() + ".json"
        (self.jobs.dir / "keys" / name).write_text(json.dumps({"job": job_id}) + "\n")

    def test_a_key_file_from_0_40_answers_with_its_job_never_a_conflict(self):
        """FAA-77: a 0.40.0 key file holds only {"job": id}; a retry with that key is answered with the job, as 0.40.0
        answered it, never idempotency-conflict (whose advice, a new key, could run the effect twice)."""
        first = self.start()
        self.legacy(first)
        for capability, given in (("media.order", {"brief": "x"}), ("media.order", {"brief": "y"})):
            with self.subTest(given=given):
                with self.assertRaisesRegex(fi.InteropError, "^Key k-1 already names job %s; answer with that job" % first):
                    self.jobs.create(capability, given, caller="caller-a", idempotency_key="k-1")
        self.assertEqual(self.jobs.repeat("caller-a", "k-1", self.NOW), {"decision": "same", "job": self.jobs.get(first)})
        self.assertEqual(self.jobs.repeat("caller-a", "k-1", self.NOW, capability="media.order", arguments={"brief": "y"})["decision"],
                         "same", "a legacy record answers as before, even for another input")
        self.assertEqual(len(list(self.jobs.dir.glob("job_*.json"))), 1, "nothing started")

    def test_a_limited_key_file_from_0_40_runs_again_only_for_its_own_jobs_input(self):
        held = self.start()
        self.jobs.quota_exhausted(held, "budget", retryable=False)
        self.legacy(held)
        with self.assertRaisesRegex(fi.InteropError, "^Key k-1 already names job %s" % held,
                                    msg="another intent under a legacy key never runs: it is answered with the job"):
            self.jobs.create("media.order", {"brief": "z"}, caller="caller-a", idempotency_key="k-1", limit_holds=False)
        self.assertEqual(len(list(self.jobs.dir.glob("job_*.json"))), 1)
        second = self.jobs.create("media.order", {"brief": "x"}, caller="caller-a", idempotency_key="k-1", limit_holds=False)["job"]["id"]
        self.assertNotEqual(second, held, "the job's own capability and input run again once, as 0.40.0 ran them")
        self.assertEqual(self.jobs.repeat("caller-a", "k-1", self.NOW, capability="media.order", arguments={"brief": "z"})["decision"],
                         "conflict", "the new key file carries the intent")

    def test_repeat_with_the_intent_answers_conflict_for_another_one(self):
        first = self.start()
        self.assertEqual(self.jobs.repeat("caller-a", "k-1", self.NOW, capability="media.order", arguments={"brief": "x"}),
                         {"decision": "same", "job": self.jobs.get(first)})
        for capability, given in (("media.order", {"brief": "y"}), ("media.refund", {"brief": "x"})):
            with self.subTest(capability=capability, given=given):
                self.assertEqual(self.jobs.repeat("caller-a", "k-1", self.NOW, capability=capability, arguments=given),
                                 {"decision": "conflict", "job": self.jobs.get(first)})
        self.assertEqual(self.jobs.repeat("caller-a", "k-1", self.NOW)["decision"], "same", "without the intent: as before")
        self.jobs.quota_exhausted(first, "budget", retryable=False)
        self.assertEqual(self.jobs.repeat("caller-a", "k-1", self.NOW, limit_holds=False, capability="media.order", arguments={"brief": "x"})["decision"], "run")
        self.assertEqual(self.jobs.repeat("caller-a", "k-1", self.NOW, limit_holds=False, capability="media.order", arguments={"brief": "y"})["decision"], "conflict")

    def test_a_lone_surrogate_in_a_key_or_caller_is_refused_with_a_sentence(self):
        """Finding 9: Python raised UnicodeEncodeError from the key's file name; both kits now refuse it."""
        for caller, key in (("caller-a", "\ud800"), ("\udfff", "k-1"), ("caller-a", "a\udc00b")):
            with self.subTest(caller=caller, key=key):
                with self.assertRaisesRegex(fi.InteropError, "lone surrogate"):
                    self.jobs.create("media.order", {"brief": "x"}, caller=caller, idempotency_key=key)
                with self.assertRaisesRegex(fi.InteropError, "lone surrogate"):
                    self.jobs.repeat(caller, key, self.NOW)
        self.assertEqual(list(self.jobs.dir.glob("job_*.json")) if self.jobs.dir.exists() else [], [])
        with self.assertRaisesRegex(fi.InteropError, "RFC 8785"):
            self.jobs.create("media.order", {"brief": "\ud800"}, caller="caller-a", idempotency_key="k-9")

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
