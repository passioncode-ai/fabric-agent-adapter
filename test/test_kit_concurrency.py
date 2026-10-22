"""R3 (FAA-70, findings 11 and 12): the Python kit's stores are load-modify-save, and a ThreadingHTTPServer runs their
callers side by side. Each store a threaded server reaches holds a lock per directory or file; these tests slow the
write down so a missing lock shows as a lost update, two jobs for one key or a terminal job that changed."""
import tempfile
import threading
import time
import unittest
from pathlib import Path

from test_fabric_service import load

fi = load("fabric_interop")
fe = load("fabric_events")


def slow(obj, name, seconds=0.05):
    """Make obj.name sleep before it runs, so two threads interleave where a lock is missing."""
    original = getattr(obj, name)

    def wrapper(*args, **kwargs):
        time.sleep(seconds)
        return original(*args, **kwargs)
    setattr(obj, name, wrapper)


def together(*calls):
    """Run the calls on threads at once; answer each one's result or the exception it raised."""
    out = [None] * len(calls)

    def run(i, call):
        try:
            out[i] = ("ok", call())
        except Exception as exc:  # noqa: BLE001 - the test reads which call raised
            out[i] = ("raised", exc)
    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return out


def envelope():
    return fi.result_envelope(outcome="succeeded", done=[], proof=[], scope={}, not_verified=[], output={},
                              usage={"inputTokens": 0, "outputTokens": 0, "wallMs": 1}, producer={"id": "x"})


class JobStoreUnderThreads(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name) / "jobs"

    def test_a_cancel_and_a_complete_race_to_one_terminal_state(self):
        store = fi.JobStore(self.dir)
        job_id = store.create("example.run", {})["job"]["id"]
        slow(store, "_save")
        results = together(lambda: store.cancel(job_id), lambda: store.complete(job_id, envelope()))
        kinds = sorted(kind for kind, _ in results)
        self.assertEqual(kinds, ["ok", "raised"], "exactly one of the two transitions may land")
        winner = next(value for kind, value in results if kind == "ok")
        self.assertEqual(store.get(job_id)["status"], winner["status"])

    def test_one_key_names_one_job_however_many_callers_race(self):
        stores = [fi.JobStore(self.dir) for _ in range(4)]  # separate instances share the directory's lock
        for store in stores:
            slow(store, "_save")
        results = together(*[lambda s=s: s.create("example.run", {"n": 1}, caller="c", idempotency_key="k1")["job"]["id"]
                             for s in stores])
        made = {value for kind, value in results if kind == "ok"}
        self.assertEqual(len(made), 1, results)
        self.assertEqual(len(list(self.dir.glob("job_*.json"))), 1)
        self.assertTrue(all(isinstance(value, fi.InteropError) for kind, value in results if kind == "raised"))

    def test_pause_on_a_terminal_job_changes_nothing(self):
        store = fi.JobStore(self.dir)
        job_id = store.create("example.run", {})["job"]["id"]
        store.cancel(job_id)
        before = store.get(job_id)
        with self.assertRaises(fi.InteropError):
            store.pause(job_id, resets_at="2099-01-01T00:00:00Z")
        self.assertEqual(store.get(job_id), before)


class EventLogUnderThreads(unittest.TestCase):
    def test_every_append_is_kept_with_its_own_id(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            logs = [fe.JsonlEventLog(path) for _ in range(4)]  # instances on one file share its lock
            for log in logs:
                slow(log, "_all", 0.002)
            results = together(*[lambda log=log: [log.append("demo.note", "info", "note")["id"] for _ in range(10)]
                                 for log in logs])
            self.assertTrue(all(kind == "ok" for kind, _ in results), results)
            ids = [i for _, batch in results for i in batch]
            self.assertEqual(len(ids), 40)
            self.assertEqual(len(set(ids)), 40, "an id was handed out twice")
            self.assertEqual(len(logs[0].fetch(None, 200)), 40, "an append was lost")


if __name__ == "__main__":
    unittest.main()
