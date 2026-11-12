"""fabric_ops_digest.py (FAA-206 part 2): the contract's reference folds on its own vectors (test/fixtures/ops-digest/
vectors.json, from fabric-agent-contract fixtures/vectors/ops-digest.json at the pin), FAC-SEM-166 and FAC-SEM-167 on
its positive and semantic fixtures (rules.json), and the files OpsDigest keeps: an hour written when it closes, the
stop hour kept for the next run, no hour filled across a sleep, each closed day folded once, catch-up included, files
0600. The twin is fabric-ops-digest.test.mjs."""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from test_fabric_service import load

od = load("fabric_ops_digest")
HERE = Path(__file__).resolve().parent
VECTORS = json.loads((HERE / "fixtures/ops-digest/vectors.json").read_text(encoding="utf-8"))
SAMPLE_KEY = "sk-proj-" + "Ab12Cd34Ef56Gh78Ij90"  # a provider-key shape, built here so no file holds one
RULES = json.loads((HERE / "fixtures/ops-digest/rules.json").read_text(encoding="utf-8").replace("@SK@", SAMPLE_KEY))
H = 3600000
T0 = 1793836800000  # 2026-11-05T00:00:00Z


def lines(folder, name):
    path = Path(folder) / name
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


class Folds(unittest.TestCase):
    def test_the_hour_vectors(self):
        self.assertEqual(len(VECTORS["hour"]), 11)
        for v in VECTORS["hour"]:
            with self.subTest(v["name"]):
                i = v["input"]
                self.assertEqual(od.fold_hour(i["counts"], i["from"], i["previous"]), v["expected"])

    def test_the_day_vectors(self):
        self.assertEqual(len(VECTORS["day"]), 4)
        for v in VECTORS["day"]:
            with self.subTest(v["name"]):
                self.assertEqual(od.fold_day(v["input"]["day"], v["input"]["hourly"]), v["expected"])

    def test_a_refused_name_writes_no_hour_and_never_names_the_value(self):
        for op in (SAMPLE_KEY, "users/jdoe/x", "Board.tick", "a..b", "x" * 65):
            with self.subTest(op=op[:12]):
                with self.assertRaises(od.OpsDigestError) as raised:
                    od.fold_hour([{"op": op, "ok": 1, "failed": 0, "unknown": 0}], "2026-11-04T17:00:00Z", None)
                self.assertNotIn(SAMPLE_KEY, str(raised.exception))

    def test_bad_inputs_throw_as_the_reference_does(self):
        with self.assertRaises(od.OpsDigestError):
            od.fold_hour([], "2026-02-30T00:00:00Z", None)
        with self.assertRaises(od.OpsDigestError):
            od.fold_hour([], "9999-12-31T23:00:00Z", None)
        with self.assertRaises(od.OpsDigestError):
            od.fold_hour([{"op": "a", "ok": -1, "failed": 0, "unknown": 0}], "2026-11-04T17:00:00Z", None)
        with self.assertRaises(od.OpsDigestError):
            od.fold_hour([{"op": "a", "ok": True, "failed": 0, "unknown": 0}], "2026-11-04T17:00:00Z", None)
        with self.assertRaises(od.OpsDigestError):
            od.fold_hour([{"op": "a", "ok": 2 ** 53 - 1, "failed": 0, "unknown": 0}] * 2, "2026-11-04T17:00:00Z", None)
        with self.assertRaises(od.OpsDigestError):
            od.fold_day("2026-13-01", [])
        self.assertIsNone(od.fold_day("2026-11-04", []))

    def test_the_home_detector_reads_as_the_contract(self):
        for value in ("api.users/list", "api.get_users/list", "api.my_users/list", "ui.home/open", "x.-Users-a", "~/x", "a ~b/c"):
            self.assertTrue(od.has_home_path(value), value)
        for value in ("api.user/list", "api.get_user/list", "my-users-list", "user-digests", "a/~1/x"):
            self.assertFalse(od.has_home_path(value), value)

    def test_rises(self):
        self.assertTrue(od.is_rise(10, 0) and od.is_rise(10, 5))
        self.assertFalse(od.is_rise(10, 6) or od.is_rise(9, 0))


class Rules(unittest.TestCase):
    def test_the_contract_fixtures(self):
        self.assertEqual(len(RULES["fixtures"]), 17)
        for f in RULES["fixtures"]:
            with self.subTest(f["name"]):
                findings = od.ops_digest_rules(f["kind"], f["input"])
                self.assertEqual(sorted({x["code"] for x in findings}), sorted(set(f["expect"])))
                for x in findings:
                    self.assertNotIn(SAMPLE_KEY, x["message"])

    def test_another_kind_is_not_this_modules(self):
        self.assertIsNone(od.ops_digest_rules("service-descriptor", {}))


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name) / "digests"

    def tearDown(self):
        self.tmp.cleanup()

    def test_an_hour_is_written_when_it_closes_and_an_observed_empty_hour_too(self):
        d = od.OpsDigest(self.folder)
        d.start(T0 + 60000)
        for _ in range(12):
            d.record("board.tick", "failed", T0 + 120000)
        d.record("board.tick", "ok", T0 + 130000)
        d.record("mcp.tools/list", "refused", T0 + 140000)
        self.assertEqual(lines(self.folder, "hourly-2026-11.jsonl"), [])
        d.tick(T0 + H + 5)
        d.tick(T0 + 2 * H + 5)
        hours = lines(self.folder, "hourly-2026-11.jsonl")
        self.assertEqual([h["from"] for h in hours], ["2026-11-05T00:00:00.000Z", "2026-11-05T01:00:00.000Z"])
        self.assertEqual(hours[0]["ops"], [{"op": "board.tick", "ok": 1, "failed": 12, "unknown": 0},
                                           {"op": "mcp.tools/list", "ok": 0, "failed": 0, "unknown": 1}])
        self.assertEqual(hours[0]["risen"], [{"op": "board.tick", "failed": 12, "previous": 0}])
        self.assertEqual(hours[1]["ops"], [])
        for h in hours:
            self.assertEqual(od.ops_digest_rules("ops-digest-hourly", h), [])

    def test_no_hour_is_filled_across_a_sleep(self):
        d = od.OpsDigest(self.folder)
        d.start(T0)
        d.record("a", "ok", T0 + 1)
        d.record("a", "ok", T0 + 5 * H + 1)
        d.tick(T0 + 6 * H)
        self.assertEqual([h["from"][11:13] for h in lines(self.folder, "hourly-2026-11.jsonl")], ["00", "05"])

    def test_the_stop_hour_is_kept_and_written_at_the_next_run_against_the_hour_before(self):
        d = od.OpsDigest(self.folder)
        d.start(T0)
        for _ in range(4):
            d.record("job.run", "failed", T0 + 10)
        d.tick(T0 + H + 10)
        for _ in range(20):
            d.record("job.run", "failed", T0 + H + 20)
        d.stop(T0 + H + 30)
        self.assertEqual(len(lines(self.folder, "hourly-2026-11.jsonl")), 1)
        again = od.OpsDigest(self.folder)
        self.assertEqual(again.start(T0 + 3 * H)["hours"], 1)
        hours = lines(self.folder, "hourly-2026-11.jsonl")
        self.assertEqual(hours[1]["from"], "2026-11-05T01:00:00.000Z")
        self.assertEqual(hours[1]["risen"], [{"op": "job.run", "failed": 20, "previous": 4}])
        self.assertFalse((self.folder / "kept-hour.json").exists())

    def test_a_restart_in_the_same_hour_resumes_it_and_never_writes_two_lines(self):
        d = od.OpsDigest(self.folder)
        d.start(T0)
        d.record("a", "ok", T0 + 1)
        d.stop(T0 + 2)
        again = od.OpsDigest(self.folder)
        again.start(T0 + 3)
        again.record("a", "ok", T0 + 4)
        again.tick(T0 + H + 1)
        hours = lines(self.folder, "hourly-2026-11.jsonl")
        self.assertEqual(len(hours), 1)
        self.assertEqual(hours[0]["ops"], [{"op": "a", "ok": 2, "failed": 0, "unknown": 0}])

    def test_each_closed_day_is_folded_once_and_a_missed_day_at_the_next_run(self):
        d = od.OpsDigest(self.folder)
        d.start(T0 + 22 * H)
        d.record("a", "ok", T0 + 22 * H)
        d.record("a", "failed", T0 + 23 * H)
        d.stop(T0 + 23 * H + 1)
        self.assertEqual(lines(self.folder, "daily-2026-11.jsonl"), [])
        again = od.OpsDigest(self.folder)
        self.assertEqual(again.start(T0 + 50 * H), {"hours": 1, "days": 1})
        again.flush(T0 + 51 * H)
        days = lines(self.folder, "daily-2026-11.jsonl")
        self.assertEqual(len(days), 1)
        self.assertEqual(days[0]["day"], "2026-11-05")
        self.assertEqual(days[0]["hours"], 2)
        self.assertEqual(days[0]["total"], {"ok": 1, "failed": 1, "unknown": 0})
        self.assertEqual(od.ops_digest_rules("ops-digest-daily", days[0]), [])

    @unittest.skipIf(sys.platform == "win32", "file modes are POSIX; Windows keeps the folder's ACL")
    def test_files_are_0600_in_a_0700_folder(self):
        d = od.OpsDigest(self.folder)
        d.start(T0)
        d.tick(T0 + H)
        self.assertEqual(stat.S_IMODE(os.stat(self.folder).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(self.folder / "hourly-2026-11.jsonl").st_mode), 0o600)

    def test_a_refused_name_is_refused_at_record_and_the_day_caps_at_4095_names(self):
        d = od.OpsDigest(self.folder)
        d.start(T0)
        with self.assertRaises(od.OpsDigestError) as raised:
            d.record(SAMPLE_KEY, "ok", T0)
        self.assertNotIn(SAMPLE_KEY, str(raised.exception))
        for i in range(4100):
            d.record("op.n%d" % i, "ok", T0)
        d.tick(T0 + H)
        ops = lines(self.folder, "hourly-2026-11.jsonl")[0]["ops"]
        self.assertEqual(len(ops), 4096)
        self.assertIn({"op": "ops.overflow", "ok": 5, "failed": 0, "unknown": 0}, ops)

    def test_a_reader_skips_bad_lines_and_keeps_the_first_of_an_hour(self):
        self.folder.mkdir(parents=True)
        good = od.fold_hour([{"op": "a", "ok": 1, "failed": 0, "unknown": 0}], "2026-11-05T00:00:00Z", None)
        second = od.fold_hour([{"op": "a", "ok": 9, "failed": 0, "unknown": 0}], "2026-11-05T00:00:00Z", None)
        text = "not json\n" + json.dumps(dict(good, extra=1)) + "\n" + json.dumps(good) + "\n" + json.dumps(second) + "\n"
        (self.folder / "hourly-2026-11.jsonl").write_text(text, encoding="utf-8")
        self.assertEqual(od.read_digests(self.folder, "hourly"), [good])

    def test_record_before_start_is_refused(self):
        with self.assertRaises(od.OpsDigestError):
            od.OpsDigest(self.folder).record("a", "ok", T0)


class Declaration(unittest.TestCase):
    def test_the_default_and_its_refusals(self):
        self.assertEqual(od.ops_digest_extension(), {od.OPS_DIGEST_EXTENSION: [{"dir": "digests", "source": "app"}]})
        for bad in ([], [{"dir": "/abs", "source": "app"}], [{"dir": "users/alice", "source": "app"}],
                    [{"dir": "a/../b", "source": "app"}], [{"dir": "a", "source": "App"}],
                    [{"dir": "a", "source": "app"}, {"dir": "A", "source": "web"}],
                    [{"dir": "ApplicationSupport/MyProduct/Digests2026", "source": "app"}]):
            with self.subTest(bad=bad):
                with self.assertRaises(od.OpsDigestError):
                    od.ops_digest_extension(bad)

    def test_outcome_words(self):
        self.assertEqual([od.outcome_of(w, {"denied": "unknown", "timeout": "failed"}) for w in ("ok", "failed", "timeout", "denied", "skip", 3)],
                         ["ok", "failed", "failed", "unknown", "unknown", "unknown"])


if __name__ == "__main__":
    unittest.main()
