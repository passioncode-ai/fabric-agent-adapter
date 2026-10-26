"""R1 (FAA-70, findings 10, 14 and 15): the hostile inputs of test/fixtures/kit-hostile-inputs-core.json, answered by the
Python kit. test/kit-hostile-core.test.mjs runs the same cases through the Node kit, so the twins cannot drift on them."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from test_fabric_service import load

fs = load("fabric_service")
fi = load("fabric_interop")
FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures/kit-hostile-inputs-core.json").read_text(encoding="utf-8"))


def built(value):
    """{"fakeKey": prefix} becomes prefix + "sk-" + 24 "q" (a key-shaped value made here, never stored in the fixture)."""
    if isinstance(value, dict) and set(value) == {"fakeKey"}:
        return value["fakeKey"] + "s" + "k-" + "q" * 24
    if isinstance(value, list):
        return [built(v) for v in value]
    if isinstance(value, dict):
        return {k: built(v) for k, v in value.items()}
    return value


def answer(fn, args):
    """accepted or refused, as the Python kit answers the case."""
    try:
        if fn == "descriptor":
            d = copy.deepcopy(FIXTURE["bases"][args[0]])
            d.update(args[1])
            return "refused" if fs.validate_descriptor(d) else "accepted"
        if fn == "dashboardExtension":
            return "refused" if fs.dashboard_extension_problems(dict(next(iter(fs.dashboard_extension().values())), **args[0])) else "accepted"
        if fn == "event":
            fs.make_event(1, "2026-10-01T00:00:00Z", args[0], "info", "A note.", trace_id=args[1], span_id=args[2])
        elif fn == "traceparent":
            return "accepted" if fi.parse_traceparent(args[0]) else "refused"
        elif fn == "inputKey":
            with tempfile.TemporaryDirectory() as temp:
                jobs = fi.JobStore(Path(temp))
                job = jobs.create("example.run", {})["job"]["id"]
                jobs.request_input(job, {args[0]: fi.choice_request("Pick.", "x", [("a", "A")])})
        elif fn == "systemdUnit":
            fs.systemd_unit(args[0], args[1], working_directory=Path("/srv/example"), environment=args[2])
        elif fn == "task":
            fs.task_xml(args[0], args[1], working_directory="C:\\example", user="EXAMPLE\\person")
        elif fn == "launchd":
            fs.launchd_plist(args[0], args[1], working_directory=Path("/srv/example"), stdout_path=Path("/srv/example/log"),
                             environment=args[2], exit_timeout=args[3])
        elif fn == "remoteRequest":
            return "refused" if fs.check_remote_request(args[0], args[1], args[2]) else "accepted"
        elif fn == "urlRequest":
            fi.url_request("Open it.", args[0])
        else:
            raise AssertionError("unknown fn %s" % fn)
    except fs.ServiceError:
        return "refused"
    return "accepted"


class HostileInputsCore(unittest.TestCase):
    def test_every_case_answers_as_the_fixture_says(self):
        self.assertGreaterEqual(len(FIXTURE["cases"]), 40)
        for case in FIXTURE["cases"]:
            with self.subTest(case["name"]):
                self.assertEqual(answer(case["fn"], built(case["args"])), case["expect"])

    def test_both_answers_occur_for_every_fn(self):
        seen = {}
        for case in FIXTURE["cases"]:
            seen.setdefault(case["fn"], set()).add(case["expect"])
        self.assertTrue(all(s == {"accepted", "refused"} for s in seen.values()), seen)


if __name__ == "__main__":
    unittest.main()
