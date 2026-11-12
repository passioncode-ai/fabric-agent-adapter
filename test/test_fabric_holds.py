"""FAA-298: work a service holds by its own limits, said to the caller (the job's statusMessage in the pause grammar),
pushed to the operator once per hold, and lifted by the operator's scoped answer. The Node twin is
test/fabric-holds.test.mjs; both read test/fixtures/holds/waiting-vectors.json."""
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
sys.path.insert(0, str(SCRIPTS))
holds = importlib.import_module("fabric_holds")
interop = importlib.import_module("fabric_interop")
events_mod = importlib.import_module("fabric_events")
actions = importlib.import_module("fabric_actions")

VECTORS = json.loads((Path(__file__).resolve().parent / "fixtures/holds/waiting-vectors.json").read_text(encoding="utf-8"))
NOW = "2026-11-12T09:00:00Z"


def decision(words="raise it to 150 for today"):
    return actions.operator_decision("limit.lift", words, at="2026-11-12T09:05:00Z")


class Waiting(unittest.TestCase):
    def test_the_vectors_write(self):
        for case in VECTORS["write"]:
            with self.subTest(case=case["input"]):
                i = case["input"]
                self.assertEqual(holds.waiting_message(i["reason"], i["since"], i.get("until"), i.get("message")),
                                 case["statusMessage"])

    def test_the_vectors_refuse(self):
        for case in VECTORS["refuse"]:
            with self.subTest(case=case):
                with self.assertRaises(holds.ServiceError):
                    holds.waiting_message(case["reason"], case["since"], case.get("until"), case.get("message"))

    def test_the_vectors_read(self):
        for case in VECTORS["read"]:
            with self.subTest(answer=case["answer"]):
                self.assertEqual(holds.read_waiting(case["answer"]), case["waiting"])

    def test_a_hold_is_a_pause_every_caller_reads_as_wait(self):
        message = holds.waiting_message("daily-quota", NOW, "2026-11-13T00:00:00Z", "renders")
        answer = {"job": {"id": "j", "status": "working", "statusMessage": message}}
        self.assertEqual(interop.job_caller_action(answer, NOW), {"action": "wait", "notBefore": "2026-11-13T00:00:00Z"})
        self.assertEqual(interop.job_caller_action(dict(answer, job=dict(answer["job"], statusMessage=holds.waiting_message("concurrency", NOW))), NOW),
                         {"action": "wait"})

    def test_a_long_message_is_shortened_to_the_contracts_500(self):
        message = holds.waiting_message("money", NOW, "2026-11-13T00:00:00Z", "x " * 400)
        self.assertLessEqual(len(message), 500)
        self.assertTrue(message.endswith("..."))
        self.assertEqual(holds.read_waiting({"job": {"id": "j", "status": "working", "statusMessage": message}})["reason"], "money")

    def test_hold_job_puts_a_job_store_job_on_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = interop.JobStore(Path(tmp))
            job = store.create("example.render", {"scene": 1})["job"]
            holds.hold_job(store, job["id"], "daily-quota", NOW, "2099-01-01T00:00:00Z", "100 of 100")
            answer = {"job": store.get(job["id"])}
            self.assertEqual(answer["job"]["status"], "working")
            self.assertGreater(answer["job"]["pollIntervalMs"], 0)
            got = holds.read_waiting(answer)
            self.assertEqual(got, {"reason": "daily-quota", "since": NOW, "until": "2099-01-01T00:00:00Z", "message": "100 of 100"})


class OnePushPerHold(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = events_mod.JsonlEventLog(Path(self.tmp.name) / "events.jsonl")
        self.book = holds.HoldBook(Path(self.tmp.name) / "holds.json", events=self.log)

    def tearDown(self):
        self.tmp.cleanup()

    def pushes(self):
        return [e for e in self.log.fetch(None, 200) if e["kind"] == holds.HOLD_EVENT_KIND]

    def test_a_held_job_emits_exactly_one_push_naming_caller_work_reason_and_when(self):
        first = self.book.hold(caller="example-caller", work="the launch video", reason="daily-quota",
                               until="2026-11-13T00:00:00Z", job_id="j1", now=NOW)
        self.assertIsNotNone(first["push"])
        for n in range(2, 5):
            again = self.book.hold(caller="example-caller", work="the launch video", reason="daily-quota",
                                   until="2026-11-13T00:00:00Z", job_id="j%d" % n, now="2026-11-12T09:0%d:00Z" % n)
            self.assertIsNone(again["push"])
        pushed = self.pushes()
        self.assertEqual(len(pushed), 1)
        event = pushed[0]
        self.assertTrue(event["notify"])
        self.assertEqual(event["level"], "notice")
        for words in ("example-caller", "the launch video", "the daily quota", "2026-11-13T00:00:00Z", "Raise the limit"):
            self.assertIn(words, event["text"])
        self.assertEqual(self.book.open_holds(NOW)[0]["jobs"], ["j1", "j2", "j3", "j4"])
        self.assertEqual(holds.read_waiting({"job": {"id": "j1", "status": "working", "statusMessage": first["statusMessage"]}})["since"], NOW)

    def test_another_caller_or_reason_is_another_hold(self):
        self.book.hold(caller="a", work="w", reason="money", now=NOW)
        self.book.hold(caller="b", work="w", reason="money", now=NOW)
        self.book.hold(caller="a", work="w", reason="concurrency", now=NOW)
        self.assertEqual(len(self.pushes()), 3)

    def test_a_hold_that_freed_pushes_again_next_time(self):
        self.book.hold(caller="a", work="w", reason="daily-quota", until="2026-11-12T10:00:00Z", now=NOW)
        self.book.hold(caller="a", work="w", reason="daily-quota", until="2026-11-13T00:00:00Z", now="2026-11-12T11:00:00Z")
        self.book.hold(caller="a", work="w", reason="money", now=NOW)
        self.assertIsNotNone(self.book.release(reason="money", caller="a", now=NOW))
        self.book.hold(caller="a", work="w", reason="money", now=NOW)
        self.assertEqual(len(self.pushes()), 4)

    def test_without_an_event_log_the_push_is_returned(self):
        book = holds.HoldBook(Path(self.tmp.name) / "other.json")
        push = book.hold(caller="a", work="w", reason="concurrency", now=NOW)["push"]
        self.assertEqual((push["kind"], push["level"], push["notify"]), (holds.HOLD_EVENT_KIND, "notice", True))
        self.assertIn("frees by itself when a running job ends", push["text"])
        events_mod.make_event("1", NOW, push["kind"], push["level"], push["text"], subject=push["subject"], notify=True)

    def test_a_credential_in_a_name_is_refused(self):
        with self.assertRaises(holds.ServiceError):
            self.book.hold(caller="sk-or-v1-" + "a1B2" * 12, work="w", reason="money", now=NOW)
        with self.assertRaises(holds.ServiceError):
            self.book.hold(caller="a", work="w", reason="rate", now=NOW)
        with self.assertRaises(holds.ServiceError):  # U+FEFF alone is whitespace in both twins (FAA-316)
            self.book.hold(caller="\ufeff", work="w", reason="money", now=NOW)
        self.assertTrue(self.book.hold(caller="\u0085", work="w", reason="money", now=NOW))

    def test_the_book_file_is_owner_only(self):
        import os
        self.book.hold(caller="a", work="w", reason="money", now=NOW)
        if os.name == "posix":
            self.assertEqual(os.stat(self.book.path).st_mode & 0o777, 0o600)


class ScopedLift(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = holds.HoldBook(Path(self.tmp.name) / "holds.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_lift_for_n_jobs_admits_n_then_the_limit_returns(self):
        self.book.hold(caller="a", work="w", reason="daily-quota", job_id="j1", now=NOW)
        lift = self.book.lift(reason="daily-quota", caller="a", jobs=3, decision=decision("three more for a"), now=NOW)
        self.assertEqual(lift["decision"]["instruction"], "three more for a")
        self.assertEqual(self.book.open_holds(NOW), [])
        got = [self.book.admit(reason="daily-quota", caller="a", now=NOW)["admitted"] for _ in range(4)]
        self.assertEqual(got, [True, True, True, False])
        self.assertFalse(self.book.admit(reason="daily-quota", caller="b", now=NOW)["admitted"])
        self.assertFalse(self.book.lifts(NOW)[0]["live"])

    def test_a_raised_limit_for_today_falls_back_when_the_window_ends(self):
        self.book.lift(reason="daily-quota", limit=150, until="2026-11-13T00:00:00Z", decision=decision(), now=NOW)
        self.assertEqual(self.book.limit(reason="daily-quota", base=100, caller="a", now="2026-11-12T23:59:59Z"), 150)
        self.assertEqual(self.book.limit(reason="daily-quota", base=100, caller="a", now="2026-11-13T00:00:00Z"), 100)
        self.assertEqual(self.book.limit(reason="money", base=100, now=NOW), 100)

    def test_a_money_lift_spends_cost_and_one_job_lift_covers_one_order(self):
        self.book.lift(reason="money", usd=5, caller="a", decision=decision("five dollars more"), now=NOW)
        self.assertTrue(self.book.admit(reason="money", caller="a", cost_usd=3.5, now=NOW)["admitted"])
        self.assertFalse(self.book.admit(reason="money", caller="a", cost_usd=2, now=NOW)["admitted"])
        self.assertTrue(self.book.admit(reason="money", caller="a", cost_usd=1.5, now=NOW)["admitted"])
        self.book.lift(reason="concurrency", job_id="j9", jobs=1, decision=decision("run this order"), now=NOW)
        self.assertFalse(self.book.admit(reason="concurrency", caller="a", job_id="j8", now=NOW)["admitted"])
        self.assertTrue(self.book.admit(reason="concurrency", caller="a", job_id="j9", now=NOW)["admitted"])

    def test_a_lift_needs_the_operators_decision_and_one_size(self):
        with self.assertRaises(holds.ServiceError):
            self.book.lift(reason="money", usd=5, decision={"by": "agent"}, now=NOW)
        with self.assertRaises(holds.ServiceError):
            self.book.lift(reason="money", usd=5, decision=actions.operator_decision("job.approve", "yes", at=NOW), now=NOW)
        with self.assertRaises(holds.ServiceError):
            self.book.lift(reason="money", usd=5, jobs=1, decision=decision(), now=NOW)
        with self.assertRaises(holds.ServiceError):
            self.book.lift(reason="daily-quota", limit=150, decision=decision(), now=NOW)
        with self.assertRaises(holds.ServiceError):
            self.book.lift(reason="daily-quota", jobs=1.5, decision=decision(), now=NOW)

    def test_a_window_that_has_not_started_admits_nothing(self):
        self.book.lift(reason="daily-quota", jobs=2, until="2026-11-13T00:00:00Z", decision=decision(), now=NOW)
        self.assertFalse(self.book.admit(reason="daily-quota", caller="a", now="2026-11-13T00:00:01Z")["admitted"])


if __name__ == "__main__":
    unittest.main()
