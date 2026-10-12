"""Settings backups, the feed client's token header and every spending limit in the usage report — contract DEC-0025
and DEC-0027 in the Python kit (FAA-13); the twin of fabric-service-backups.test.mjs. The contract's fixtures at the
pin are copied to test/fixtures/contract/dec-0025-0027/, and the canonical-form vectors to fixtures/contract/canonical.json."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

from test_fabric_service import load

fs = load("fabric_service")
HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures/contract/dec-0025-0027"


def fixture(name):
    return json.loads((FIXTURES / (name + ".json")).read_text(encoding="utf-8"))


NOW = dt.datetime(2026, 10, 5, 2, 0, 0, 123000, tzinfo=dt.timezone.utc)
TABLES = {
    "projects": {"columns": ["id", "name", "archived"], "rows": [["p-001", "Quarterly report", False], ["p-002", "Board memo", True]]},
    "secret_bindings": {"columns": ["project_id", "slot", "secret_name"], "rows": [["p-001", "llm", "EXAMPLE_LLM_KEY"]]},
}


def backup(tables=None, now=NOW, reason="daily"):
    return fs.make_settings_backup(service_id="example-agent", instance="default", version="0.4.0", schema=7,
                                   tables=copy.deepcopy(tables or TABLES), reason=reason, now=now)


class CanonicalForm(unittest.TestCase):
    def test_the_contract_vectors(self):
        vectors = json.loads((HERE / "fixtures/contract/canonical.json").read_text(encoding="utf-8"))["settings"]["vectors"]
        ran = 0
        for v in vectors:
            if "expected" not in v:
                continue
            value = json.loads(v["inputJson"]) if "inputJson" in v else v["input"]
            with self.subTest(v["name"]):
                self.assertEqual(fs.settings_canonical_json(value), v["expected"])
                ran += 1
        self.assertGreater(ran, 2)

    def test_the_contract_refusals(self):
        refuses = json.loads((HERE / "fixtures/contract/canonical.json").read_text(encoding="utf-8"))["settings"]["refuses"]
        self.assertGreaterEqual(len(refuses), 7)
        for v in refuses:
            value = json.loads(v["inputJson"]) if "inputJson" in v else v.get("input")
            with self.subTest(v["name"]), self.assertRaises(fs.ServiceError):
                fs.settings_canonical_json(value)

    def test_what_has_no_canonical_form_is_refused(self):
        for value in (0.5, 2 ** 53, -(2 ** 53), float("nan"), {"a": object()}):
            with self.subTest(value=value), self.assertRaises(fs.ServiceError):
                fs.settings_canonical_json(value)
        with self.assertRaises(fs.ServiceError) as caught:
            fs.settings_canonical_json({"price": 0.5})
        self.assertIn("decimal string", str(caught.exception), "a fraction is told how to be stored")

    def test_the_positive_fixture_checksum(self):
        doc = fixture("positive-settings-backup")
        self.assertEqual(fs.settings_backup_digest(doc["tables"]), doc["sha256"])


class BackupFile(unittest.TestCase):
    def test_the_contract_fixtures(self):
        self.assertEqual(fs.settings_backup_problems(fixture("positive-settings-backup")), [])
        for name, needle in (("negative-settings-backup-account-connections", "account_connections"),
                             ("negative-settings-backup-fraction", "FAC-SEM-035"),
                             ("negative-settings-backup-no-checksum", "sha256"),
                             ("negative-settings-backup-token-column", "access_token"),
                             ("negative-settings-backup-wrong-format", "format"),
                             ("semantic-settings-backup-bad-checksum", "FAC-SEM-035 /sha256")):
            with self.subTest(name):
                problems = fs.settings_backup_problems(fixture(name))
                self.assertTrue(any(needle in p for p in problems), problems)

    def test_counts_widths_and_surrogates(self):
        doc = backup()
        doc["counts"]["projects"] = 3
        self.assertTrue(any("/counts/projects" in p for p in fs.settings_backup_problems(doc)))
        doc = backup()
        doc["counts"]["ghost"] = 0
        self.assertTrue(any("ghost" in p for p in fs.settings_backup_problems(doc)))
        doc = backup()
        doc["tables"]["projects"]["rows"][0].append("extra")
        self.assertTrue(any("row has 4 values for 3 columns" in p for p in fs.settings_backup_problems(doc)))
        doc = backup()
        doc["tables"]["projects"]["rows"][0][1] = "lone \ud800"
        self.assertTrue(any("surrogate" in p for p in fs.settings_backup_problems(doc)))

    def test_what_the_schema_refuses_is_refused_and_never_crashes(self):
        cases = []
        doc = backup(); doc["reason"] = "daily\n"; cases.append((doc, "reason"))
        doc = backup(); doc["sha256"] += "\n"; cases.append((doc, "sha256"))
        doc = backup(); doc["created_at"] = "2026-02-30T00:00:00Z"; cases.append((doc, "created_at"))
        doc = backup(); doc["extensions"] = {"not a uri": 1}; cases.append((doc, "extensions"))
        doc = backup(); doc["tables"]["projects"]["rows"][0][1] = "x" * 1048577; cases.append((doc, "longer than"))
        doc = backup(); doc["tables"]["projects"]["columns"].append("name\n"); cases.append((doc, "column projects.name"))
        doc = backup(); doc["tables"]["lone\ud800"] = {"columns": ["id"], "rows": []}; doc["counts"]["lone\ud800"] = 0
        cases.append((doc, "lone"))
        for doc, needle in cases:
            with self.subTest(needle):
                problems = fs.settings_backup_problems(doc)
                self.assertTrue(any(needle in p for p in problems), problems)
        doc = backup(); doc["created_at"] = "2026-10-05T04:00:00.5+02:00"
        self.assertEqual(fs.settings_backup_problems(doc), [], "an RFC 3339 offset is a date-time too")

    def test_nan_is_not_json(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings-20261005T020000000000Z.json"
            doc = backup()
            doc["extensions"] = {"https://example.com/ext": "PLACEHOLDER"}
            path.write_text(json.dumps(doc).replace('"PLACEHOLDER"', "NaN"), encoding="utf-8")   # where nothing else looks
            with self.assertRaises(fs.ServiceError):
                fs.read_settings_backup(path)

    def test_make_writes_counts_checksum_and_time(self):
        doc = backup()
        self.assertEqual(doc["format"], "fabric-settings-backup/1")
        self.assertEqual(doc["created_at"], "2026-10-05T02:00:00.123000Z")
        self.assertEqual(doc["counts"], {"projects": 2, "secret_bindings": 1})
        self.assertEqual(doc["sha256"], fs.settings_backup_digest(doc["tables"]))
        self.assertEqual(fs.settings_backup_problems(doc), [])

    def test_make_refuses_what_a_backup_never_holds(self):
        for tables in ({"operator_sessions": {"columns": ["id"], "rows": []}},
                       {"bindings": {"columns": ["id", "client_secret"], "rows": []}},
                       {"prices": {"columns": ["id", "usd"], "rows": [["a", 0.5]]}}):
            with self.subTest(tables=list(tables)), self.assertRaises(fs.ServiceError):
                backup(tables)
        with self.assertRaises(fs.ServiceError):
            backup(reason="Daily!")


class BackupFolder(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "settings-backups" / "example-agent" / "default"

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_root_per_system(self):
        env = {"APPDATA": "/fake/Roaming", "XDG_CONFIG_HOME": "/fake/config"}
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            self.assertEqual(fs.settings_backup_root("darwin"), Path.home() / "Library/Application Support/PassionCode")
            self.assertEqual(fs.settings_backup_root("win32"), Path("/fake/Roaming") / "PassionCode")
            self.assertEqual(fs.settings_backup_root("linux"), Path("/fake/config") / "PassionCode")
            self.assertEqual(fs.settings_backup_dir("example-agent", "default", root=Path("/r")),
                             Path("/r/settings-backups/example-agent/default"))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_write_is_named_by_time_private_and_skips_an_unchanged_snapshot(self):
        first = fs.write_settings_backup(backup(), self.dir)
        self.assertEqual(first.name, "settings-20261005T020000123000Z.json")
        if os.name != "nt":
            self.assertEqual(first.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.dir.stat().st_mode & 0o777, 0o700)
        self.assertIsNone(fs.write_settings_backup(backup(now=NOW + dt.timedelta(days=1)), self.dir), "unchanged: not written")
        changed = copy.deepcopy(TABLES)
        changed["projects"]["rows"].append(["p-003", "New", False])
        second = fs.write_settings_backup(backup(changed, now=NOW + dt.timedelta(days=1)), self.dir)
        self.assertEqual(fs.settings_backups(self.dir), [second, first], "newest first")
        self.assertEqual(fs.read_settings_backup(second)["counts"]["projects"], 3)

    def test_a_left_temporary_file_is_removed_and_fourteen_are_kept(self):
        self.dir.mkdir(parents=True)
        left = self.dir / ".settings-x.json.tmp1"
        left.write_text("half")
        two_hours_ago = time.time() - 7200
        os.utime(left, (two_hours_ago, two_hours_ago))
        filling = self.dir / ".settings-y.json.tmp2"   # a concurrent writer is still filling this one
        for day in range(20):
            tables = copy.deepcopy(TABLES)
            tables["projects"]["rows"].append(["p-%03d" % (100 + day), "Day %d" % day, False])
            fs.write_settings_backup(backup(tables, now=NOW + dt.timedelta(days=day)), self.dir)
        kept = fs.settings_backups(self.dir)
        self.assertEqual(len(kept), fs.SETTINGS_BACKUP_KEEP)
        self.assertEqual(kept[0].name, "settings-20261024T020000123000Z.json")
        self.assertEqual([p.name for p in self.dir.iterdir() if not p.name.startswith("settings-")], [])
        filling.write_text("half")
        fs.write_settings_backup(backup(now=NOW + dt.timedelta(days=30)), self.dir)
        self.assertTrue(filling.exists(), "a young temporary file belongs to a writer still at work")

    def test_a_clock_that_stepped_back_never_deletes_the_new_snapshot(self):
        for day in range(15):
            tables = copy.deepcopy(TABLES)
            tables["projects"]["rows"].append(["p-%03d" % (200 + day), "Day %d" % day, False])
            fs.write_settings_backup(backup(tables, now=NOW + dt.timedelta(days=day)), self.dir)
        tables = copy.deepcopy(TABLES)
        tables["projects"]["rows"].append(["p-999", "Written after the clock stepped back", False])
        written = fs.write_settings_backup(backup(tables, now=NOW - dt.timedelta(days=365)), self.dir)
        self.assertTrue(written.exists())
        self.assertEqual(len(fs.settings_backups(self.dir)), fs.SETTINGS_BACKUP_KEEP)

    def test_a_damaged_newest_file_does_not_suppress_a_good_snapshot(self):
        self.dir.mkdir(parents=True)
        doc = backup()
        damaged = self.dir / "settings-20991231T000000000000Z.json"
        damaged.write_text(json.dumps({"sha256": doc["sha256"]}), encoding="utf-8")
        self.assertIsNotNone(fs.write_settings_backup(doc, self.dir))
        (self.dir / "settings-20991231T000000000001Z.json").write_text("[]", encoding="utf-8")
        tables = copy.deepcopy(TABLES)
        tables["projects"]["rows"].append(["p-777", "x", False])
        self.assertIsNotNone(fs.write_settings_backup(backup(tables), self.dir))

    def test_an_impossible_name_makes_a_snapshot_due_and_never_crashes(self):
        self.dir.mkdir(parents=True)
        (self.dir / "settings-20261345T000000000000Z.json").write_text("{}")
        self.assertTrue(fs.backup_due(self.dir, now=NOW))

    def test_due_after_a_day(self):
        self.assertTrue(fs.backup_due(self.dir, now=NOW))
        fs.write_settings_backup(backup(), self.dir)
        self.assertFalse(fs.backup_due(self.dir, now=NOW + dt.timedelta(hours=23)))
        self.assertTrue(fs.backup_due(self.dir, now=NOW + dt.timedelta(hours=24, seconds=1)))

    def test_a_damaged_file_is_refused_and_skipped_naming_it(self):
        good = fs.write_settings_backup(backup(), self.dir)
        tables = copy.deepcopy(TABLES)
        tables["projects"]["rows"].append(["p-009", "Later", False])
        bad = fs.write_settings_backup(backup(tables, now=NOW + dt.timedelta(days=1)), self.dir)
        doc = json.loads(bad.read_text(encoding="utf-8"))
        doc["tables"]["projects"]["rows"][0][1] = "tampered"
        bad.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaises(fs.ServiceError) as caught:
            fs.read_settings_backup(bad)
        self.assertIn("checksum", str(caught.exception))
        path, chosen, skipped = fs.newest_intact_backup(self.dir)
        self.assertEqual(path, good)
        self.assertEqual(chosen["counts"]["projects"], 2)
        self.assertEqual([p for p, _ in skipped], [bad])

    def test_an_empty_snapshot_is_not_a_source(self):
        good = fs.write_settings_backup(backup(), self.dir)
        empty = {name: {"columns": t["columns"], "rows": []} for name, t in TABLES.items()}
        fs.write_settings_backup(backup(empty, now=NOW + dt.timedelta(days=1)), self.dir)
        self.assertEqual(fs.newest_intact_backup(self.dir)[0], good)


class Restore(unittest.TestCase):
    def test_adds_missing_rows_never_overwrites_and_names_what_it_drops(self):
        doc = backup()
        current = {
            "projects": {"columns": ["id", "name", "owner"], "key": ["id"], "required": ["id", "name"], "existing": [("p-001",)]},
            "secret_bindings": {"columns": ["project_id", "slot", "secret_name", "scope"], "key": ["project_id", "slot"],
                                "required": ["project_id", "slot", "scope"], "existing": []},
        }
        plan = fs.restore_plan(doc, current)
        projects = plan["tables"]["projects"]
        self.assertEqual(projects["insert"], [{"id": "p-002", "name": "Board memo"}])
        self.assertEqual(projects["present"], 1)
        self.assertEqual(projects["droppedColumns"], ["archived"])
        self.assertEqual(projects["defaultedColumns"], ["owner"])
        bindings = plan["tables"]["secret_bindings"]
        self.assertEqual(bindings["insert"], [])
        self.assertEqual(bindings["missingRequired"], ["scope"])
        self.assertEqual(bindings["refused"], [{"key": ["p-001", "llm"], "reason": "required column scope is not in the snapshot"}])

    def test_a_table_the_service_no_longer_has_is_named(self):
        plan = fs.restore_plan(backup(), {"projects": {"columns": ["id", "name", "archived"], "key": ["id"], "required": [], "existing": []}})
        self.assertEqual(plan["unknownTables"], ["secret_bindings"])
        self.assertEqual(len(plan["tables"]["projects"]["insert"]), 2)

    def test_a_key_the_snapshot_holds_twice_is_refused_in_the_preview(self):
        tables = copy.deepcopy(TABLES)
        tables["projects"]["rows"].append(["p-002", "Board memo again", False])
        plan = fs.restore_plan(backup(tables), {"projects": {"columns": ["id", "name", "archived"], "key": ["id"], "required": [], "existing": []}})
        self.assertEqual(len(plan["tables"]["projects"]["insert"]), 2)
        self.assertEqual(plan["tables"]["projects"]["refused"], [{"key": ["p-002"], "reason": "the snapshot holds this key twice"}])

    def test_a_damaged_backup_is_never_planned(self):
        doc = backup()
        doc["sha256"] = "0" * 64
        with self.assertRaises(fs.ServiceError):
            fs.restore_plan(doc, {})


class FeedClient(unittest.TestCase):
    def test_the_header_the_descriptor_declares(self):
        token = "t" * 20
        self.assertEqual(fs.token_header({}, token), ("Authorization", "Bearer " + token))
        self.assertEqual(fs.token_header({"header": "X-Example-Token", "scheme": "none"}, token), ("X-Example-Token", token))
        self.assertEqual(fs.token_header({"scheme": "Bearer"}, token), ("Authorization", "Bearer " + token))

    def test_the_contract_fixtures(self):
        for name, ok in (("semantic-service-feed-request-custom-header", True), ("semantic-service-feed-request-assumed-bearer", False)):
            doc = fixture(name)
            sent = fs.token_header(doc["descriptor"]["auth"], doc["token"])
            matches = doc["request"]["headers"].get(sent[0]) == sent[1]
            self.assertEqual(matches, ok, name)


class Limits(unittest.TestCase):
    def test_the_contract_fixtures(self):
        self.assertEqual(fs.usage_limit_problems(fixture("positive-service-usage-budgets")), [])
        for name, needle in (("negative-service-usage-budgets-bad-scope", "scope"), ("negative-service-usage-budgets-unknown-field", "note"),
                             ("negative-service-usage-budgets-zero-limit", "limitUsd")):
            with self.subTest(name):
                problems = fs.usage_limit_problems(fixture(name))
                self.assertTrue(any(needle in p for p in problems), problems)

    def limits_problems(self, *limits, budget=None):
        report = {"budgets": list(limits)}
        if budget is not None:
            report["budget"] = budget
        return fs.usage_limit_problems(report)

    def test_fac_sem_031(self):
        daily = {"id": "machine.daily", "scope": "machine", "kind": "daily", "period": "day", "limitUsd": 5, "spentUsd": 1.0, "enforced": True}
        cases = [
            ((daily, dict(daily)), "appears twice"),
            (({**daily, "id": "p", "scope": "project"},), "names its project in subject"),
            (({**daily, "id": "m", "subject": "x"},), "has no subject"),
            (({**daily, "windowSeconds": 86400},), "one window"),
            (({"id": "j", "scope": "job", "kind": "per_job", "limitUsd": 2, "spentUsd": 0.5, "enforced": True},), "nothing is spent"),
            (({"id": "j", "scope": "job", "kind": "per_job", "period": "day", "limitUsd": 2, "spentUsd": None, "enforced": True},), "no window"),
            (({**daily, "period": "month"},), "a daily limit"),
            (({**daily, "kind": "monthly", "period": None, "windowSeconds": 86400},), "a monthly limit"),
            (({"id": "v", "scope": "machine", "kind": "velocity", "limitUsd": None, "spentUsd": 0, "enforced": True},), "velocity"),
            (({"id": "e", "scope": "machine", "kind": "emergency", "limitUsd": 500, "spentUsd": 0, "enforced": True},), "names the window"),
            (({**daily, "limitUsd": None},), "only a relative limit"),
            (({**daily, "enforced": False, "tripped": True},), "not enforced cannot have stopped"),
        ]
        for limits, needle in cases:
            limits = tuple({k: v for k, v in l.items() if v is not None or k in ("limitUsd", "spentUsd")} for l in limits)
            with self.subTest(needle):
                problems = self.limits_problems(*limits)
                self.assertTrue(any(needle in p for p in problems), problems)
        self.assertEqual(self.limits_problems(daily, {"id": "custom", "scope": "machine", "kind": "night_cap", "limitUsd": 1,
                                                      "spentUsd": 0, "enforced": False}), [], "an unknown kind is never refused")
        self.assertEqual(self.limits_problems(daily, budget={"period": "day", "limitUsd": 5, "spentUsd": 1.0}), [])
        self.assertTrue(any("budget repeats" in p for p in self.limits_problems(daily, budget={"period": "month", "limitUsd": 5, "spentUsd": 1.0})))

    def test_the_report_counts_a_machine_period_limit_and_refuses_an_incoherent_one(self):
        now = dt.datetime(2026, 10, 4, 16, 0, tzinfo=dt.timezone.utc)
        receipts = [fs.make_usage_receipt("anthropic", "m", input_tokens=10, output_tokens=5, cost_usd=0.25, cost_basis="provider",
                                          at="2026-10-04T10:00:00Z"),
                    fs.make_usage_receipt("anthropic", "m", input_tokens=10, output_tokens=5, cost_usd=0.5, cost_basis="provider",
                                          at="2026-10-01T10:00:00Z")]
        report = fs.usage_report(receipts, service_id="example-agent", now=now, budget={"period": "month", "limitUsd": 100},
                                 budgets=[{"id": "machine.monthly", "scope": "machine", "kind": "monthly", "period": "month", "limitUsd": 100, "enforced": True},
                                          {"id": "machine.daily", "scope": "machine", "kind": "daily", "period": "day", "limitUsd": 5, "enforced": False},
                                          {"id": "job.cap", "scope": "job", "kind": "per_job", "limitUsd": 2, "enforced": True}])
        by_id = {l["id"]: l for l in report["budgets"]}
        self.assertEqual(by_id["machine.monthly"]["spentUsd"], 0.75)
        self.assertEqual(by_id["machine.daily"]["spentUsd"], 0.25)
        self.assertIsNone(by_id["job.cap"]["spentUsd"])
        self.assertEqual(report["budget"], {"period": "month", "limitUsd": 100.0, "spentUsd": 0.75})
        self.assertEqual(fs.usage_limit_problems(report), [])
        with self.assertRaises(fs.ServiceError):
            fs.usage_report(receipts, service_id="example-agent", now=now,
                            budgets=[{"id": "p", "scope": "project", "kind": "daily", "period": "day", "limitUsd": 5, "enforced": True}])
        with self.assertRaises(fs.ServiceError) as caught:
            fs.usage_report(receipts, service_id="example-agent", now=now, budgets=["machine.daily"])
        self.assertIn("is an object", str(caught.exception))
        rolling = fs.usage_report(receipts, service_id="example-agent", now=now, budgets=[
            {"id": "machine.24h", "scope": "machine", "kind": "emergency", "windowSeconds": 86400, "limitUsd": 50, "enforced": True}])
        self.assertEqual(rolling["budgets"][0]["spentUsd"], 0.25, "a rolling machine window is counted from the receipts")

    def test_the_descriptor_names_its_header_and_scheme_the_schema_way(self):
        base = {"protocol": fs.PROTOCOL, "id": "example-agent", "instance": "default", "name": "Example", "origin": "http://127.0.0.1:47195",
                "auth": {"tokenFile": "~/t"}, "lifecycle": {"manager": "none"}, "paths": {"data": "~/d", "logs": []},
                "installedAt": "2026-10-05T00:00:00Z", "installedBy": "test"}
        self.assertEqual(fs.validate_descriptor(base), [])
        for auth, needle in (({"tokenFile": "~/t", "header": "X Token", "scheme": "none"}, "auth.header"),
                             ({"tokenFile": "~/t", "scheme": "Basic"}, "auth.scheme")):
            with self.subTest(needle):
                self.assertTrue(any(needle in p for p in fs.validate_descriptor({**base, "auth": auth})))


if __name__ == "__main__":
    unittest.main()
