"""fabric_load.py: the call queue and the load report of DEC-0104 (FAA-289). Every case of the contract's
fixtures/vectors/agent-network.json queue, admit, caller and position groups, its job-queue, service-load and
service-well-known-load semantic fixtures and its service-load and service-load-extension catalogue fixtures, and the
kit's own hostile inputs, each answered by the contract's functions and validator at the pin (vendored as
test/fixtures/contract/load-vectors.json by make_load_vectors.mjs); the Node twin runs the same file in
fabric-load.test.mjs."""
import json
import unittest
from pathlib import Path

from test_fabric_service import fs, load

fl = load("fabric_load")
ServiceError = fl.ServiceError

HERE = Path(__file__).resolve().parent
V = json.loads((HERE / "fixtures/contract/load-vectors.json").read_text(encoding="utf-8"))
LOCK = json.loads((HERE.parent / "fabric-contract.lock.json").read_text(encoding="utf-8"))
MISSING = load("fabric_jsvalue").MISSING


def js(value):
    """JSON text with sorted keys: equal only when JavaScript's isDeepStrictEqual would be (true is not 1)."""
    return json.dumps(value, sort_keys=True)


class Vectors(unittest.TestCase):
    def test_the_vectors_are_the_pins(self):
        self.assertEqual(V["commit"], LOCK["commit"])
        self.assertEqual(V["extensionKey"], fl.LOAD_EXTENSION_KEY)
        self.assertEqual((len(V["queue"]), len(V["admit"]), len(V["caller"]), len(V["position"])), (29, 19, 23, 16))

    def test_the_next_job(self):
        for c in V["queue"]:
            self.assertEqual(js(fl.next_queued_job(c["queue"], c["running"], c["limits"])), js(c["expected"]), c["name"])

    def test_admission(self):
        for c in V["admit"]:
            got = fl.admit_job(c["queue"], c["running"], c["job"], c["limits"], c["retryAfterSeconds"])
            self.assertEqual(js(got), js(c["expected"]), c["name"])

    def test_the_caller_key(self):
        for c in V["caller"]:
            got = fl.job_caller_key(c.get("accepted", MISSING), c.get("credential", MISSING))
            self.assertEqual(got, c["expected"], c["name"])

    def test_the_position(self):
        for c in V["position"]:
            self.assertEqual(js(fl.read_queue_position(c["statusMessage"])), js(c["expected"]), c["name"])

    def test_the_status_message(self):
        for c in V["status"]:
            self.assertEqual(fl.queue_status_message(c["position"], c["length"]), c["expected"], c["name"])
            if c["expected"] is not None:
                self.assertEqual(fl.read_queue_position(c["expected"]), {"position": c["position"], "length": c["length"]})

    def test_the_semantic_fixtures(self):
        self.assertEqual(len(V["rules"]), 12)
        for c in V["rules"]:
            if c["kind"] == "job-queue":
                got = fl.job_queue_rules(c["value"])
            elif c["kind"] == "service-load":
                got = fl.load_report_rules(c["value"])
            else:
                got = [{"code": f["code"], "instancePath": f["instancePath"]} for f in fl.load_extension_rules(c["value"])]
            self.assertEqual(got, c["findings"], c["name"])

    def test_the_declarations(self):
        for c in V["declarations"]:
            view = fl.load_view({"extensions": {V["extensionKey"]: c["value"]}})
            self.assertTrue(view["declared"], c["name"])
            self.assertEqual(view["valid"], c["valid"], "%s: %s" % (c["name"], view["errors"]))
            self.assertEqual(view["errors"] == [], c["valid"], c["name"])
            self.assertEqual(js(view["load"]), js(c["value"] if c["valid"] else None), c["name"])
            got = fl.load_extension_rules({"extensions": {V["extensionKey"]: c["value"]}})
            self.assertEqual([{"code": f["code"], "instancePath": f["instancePath"]} for f in got], c["findings"], c["name"])
        for c in V["documents"]:
            got = fl.load_extension_rules(c["value"])
            self.assertEqual([{"code": f["code"], "instancePath": f["instancePath"]} for f in got], c["findings"], c["name"])

    def test_the_reports(self):
        for c in V["reports"]:
            problems = fl.load_report_problems(c["value"])
            self.assertEqual(problems == [], c["valid"], "%s: %s" % (c["name"], problems))
            self.assertEqual(fl.load_report_rules(c["value"]), c["findings"], c["name"])

    def test_the_catalogue_agrees_with_the_validator(self):
        for c in V["declarations"] + V["reports"]:
            if "catalogue" in c:
                self.assertEqual(c["catalogue"], c["valid"], c["name"])


class Builders(unittest.TestCase):
    LIMITS = {"concurrency": 4, "perCaller": 2, "queueMax": 50}

    def test_a_declaration_reads_back(self):
        entry = fl.load_extension("/fabric/v1/load", 3600, self.LIMITS)
        self.assertEqual(list(entry), [fl.LOAD_EXTENSION_KEY])
        view = fl.load_view({"extensions": entry})
        self.assertEqual((view["declared"], view["valid"]), (True, True))
        self.assertEqual(fl.load_extension_rules({"extensions": entry}), [])

    def test_a_declaration_a_reader_would_hide_is_refused(self):
        for args in (("load", 3600, self.LIMITS), ("/load", 30, self.LIMITS), ("/load", 3600, {**self.LIMITS, "concurrency": 0}),
                     ("/load", 3600, {"concurrency": 1}), ("//x", 3600, self.LIMITS), ("/load", 3600, None)):
            with self.subTest(args=args), self.assertRaises(ServiceError):
                fl.load_extension(*args)

    def test_the_declared_limits_are_copied(self):
        limits = dict(self.LIMITS)
        entry = fl.load_extension("/load", 60, limits)
        limits["concurrency"] = 0
        self.assertEqual(entry[fl.LOAD_EXTENSION_KEY]["limits"]["concurrency"], 4)

    def test_a_node_queues_with_its_declared_limits(self):
        """The cycle a hosting node runs: admit, give each waiting job its place, start what next_queued_job names."""
        limits = fl.load_extension("/load", 60, {"concurrency": 1, "perCaller": 1, "queueMax": 1})[fl.LOAD_EXTENSION_KEY]["limits"]
        a = fl.job_caller_key({"ok": True, "principal": "urn:person:a", "caller": "writer", "chain": ["writer"]}, "hub")
        b = fl.job_caller_key(None, "local-session")
        queue, running = [], []
        first = {"id": "j1", "caller": a, "at": "2026-10-22T09:00:01Z"}
        self.assertEqual(fl.admit_job(queue, running, first, limits, 30), {"admit": True})
        self.assertEqual(fl.next_queued_job([first], running, limits), "j1")
        running.append({"id": "j1", "caller": a})
        second = {"id": "j2", "caller": b, "at": "2026-10-22T09:00:02Z"}
        self.assertEqual(fl.admit_job(queue, running, second, limits, 30), {"admit": True})
        queue.append(second)
        self.assertEqual(fl.queue_status_message(queue.index(second) + 1, len(queue)), "queued 1 of 1")
        third = {"id": "j3", "caller": a, "at": "2026-10-22T09:00:03Z"}
        refused = fl.admit_job(queue, running, third, limits, 30)
        self.assertEqual((refused["admit"], refused["error"]["code"], refused["error"]["data"]["retryAfterSeconds"]), (False, "queue-full", 30))
        self.assertIsNone(fl.next_queued_job(queue, running, limits))
        running.clear()
        self.assertEqual(fl.next_queued_job(queue, running, limits), "j2")

    def test_the_refusal_code_is_the_interop_rules(self):
        rules = load("fabric_interop_rules")
        self.assertEqual(fl.admit_job([], [], None, {}, 1)["error"]["code"], rules.QUEUE_FULL)

    def test_nothing_raises_on_what_it_reads(self):
        odd = [None, 7, "x", [], {}, [None], {"windows": "x"}, {"extensions": None}, True]
        for value in odd:
            with self.subTest(value=value):
                fl.next_queued_job(value, value, value)
                fl.admit_job(value, value, value, value, value)
                fl.job_caller_key(value, value)
                fl.queue_status_message(value, value)
                fl.read_queue_position(value)
                fl.job_queue_rules(value)
                fl.load_report_rules(value)
                fl.load_report_problems(value)
                fl.load_view(value)
                fl.load_extension_rules(value)


class Facade(unittest.TestCase):
    NAMES = ("LOAD_EXTENSION_KEY", "LOAD_REPORT_TYPE", "QUEUE_FULL_MESSAGE", "QUEUE_LENGTH_MAX", "DEFAULT_RETRY_AFTER_SECONDS",
             "job_caller_key", "next_queued_job", "admit_job", "queue_status_message", "read_queue_position",
             "job_queue_rules", "load_report_rules", "load_report_problems", "load_view", "load_extension_rules", "load_extension")

    def test_the_facade_exports_the_module(self):
        for name in self.NAMES:
            with self.subTest(name=name):
                value = getattr(fs, name)
                if callable(value):
                    self.assertEqual((value.__module__, value.__name__), ("fabric_load", name))
                else:
                    self.assertEqual(value, getattr(fl, name))

if __name__ == "__main__":
    unittest.main()
