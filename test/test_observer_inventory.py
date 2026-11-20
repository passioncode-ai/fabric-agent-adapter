"""observing-products: the channel inventory check (REQ-1 of the observer-mode design). A channel without a proven
read is never counted as connected, a credential is a vault slot name or none (never a value), and the report says
connected out of named."""
from __future__ import annotations

import datetime
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/fabric-agent-adapter/skills/observing-products"
SCRIPT = SKILL / "scripts/observer_inventory.py"
SPEC = importlib.util.spec_from_file_location("observer_inventory", SCRIPT)
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)  # type: ignore[union-attr]

TODAY = datetime.date(2026, 11, 8)
HEAD = """# Observer channels: example-app

- Project: example-app
- Authority: fix
- Interval: 30m
- Budget: USD 100 / month

| Channel | Kind | Placement | Read | Credential | Cursor | Baseline | Thresholds | Owner | State |
|---|---|---|---|---|---|---|---|---|---|
"""
ROWS = {
    "ci": "| ci | ci | remote | `gh run list --branch main --limit 20` | none | run 812 | none | any red run | repository | connected 2026-11-08 |",
    "errors": "| errors | errors | remote | error tracker API, 2 pages | `example-app/prod/ERRORS_TOKEN` | issue 9001 | events per hour, 7 days | 3x baseline | backend | connected 2026-11-07 |",
    "ops": "| ops-log | ops-log | local | `ops.digest.daily@1` file | none | 2026-11-07 | failures per hour, 7 days | a rise | app | connected 2026-11-08 |",
    "store": "| store | store | remote | store reviews, 50 newest | example-app/prod/STORE_KEY | review 77 | rating, 28 days | rating below 4.0 | store owner | blocked: the store's API key needs the account holder's sign-in, https://example.com/keys |",
    "funnel": "| checkout | funnel | remote | analytics funnel query | example-app/prod/ANALYTICS_KEY | day 2026-11-07 | step conversion, 4 weeks | outside the interval | growth | missing: issue a read key for the analytics source |",
    "support": "| support | support | remote | n/a | none | none | none | none | nobody | not-applicable: the product has no support inbox |",
}


def doc(*names: str, head: str = HEAD) -> str:
    return head + "\n".join(ROWS[n] for n in names) + "\n"


class InventoryCheck(unittest.TestCase):
    def test_a_full_inventory_counts_connected_out_of_named(self):
        report = inventory.check(doc("ci", "errors", "ops", "store", "funnel", "support"), TODAY)
        self.assertTrue(report["valid"], report["problems"])
        self.assertEqual((report["connected"], report["named"]), (3, 5))  # not-applicable is not named
        self.assertEqual(report["states"], {"connected": 3, "missing": 1, "blocked": 1, "not-applicable": 1})
        self.assertEqual(report["connectedByPlacement"], {"local": 1, "remote": 2})
        self.assertEqual((report["project"], report["authority"], report["interval"]), ("example-app", "fix", "30m"))

    def test_connected_without_the_date_of_a_proven_read_is_refused(self):
        text = doc("ci").replace("connected 2026-11-08", "connected")
        report = inventory.check(text, TODAY)
        self.assertFalse(report["valid"])
        self.assertEqual(report["connected"], 0)
        self.assertIn("proven read", " ".join(report["problems"]))

    def test_a_read_dated_in_the_future_or_impossible_is_refused(self):
        for state in ("connected 2026-12-01", "connected 2026-02-30"):
            with self.subTest(state=state):
                report = inventory.check(doc("ci").replace("connected 2026-11-08", state), TODAY)
                self.assertFalse(report["valid"])

    def test_a_credential_value_is_refused(self):
        for value in ("s3cr3t-value-123", "Bearer abc", "ERRORS_TOKEN", "example-app/dev/ERRORS_TOKEN"):
            with self.subTest(value=value):
                report = inventory.check(doc("errors").replace("`example-app/prod/ERRORS_TOKEN`", value), TODAY)
                self.assertFalse(report["valid"])
                self.assertTrue(any("never a value" in p for p in report["problems"]))

    def test_missing_and_blocked_need_their_step(self):
        for state in ("missing", "missing:", "blocked:  ", "not-applicable"):
            with self.subTest(state=state):
                report = inventory.check(doc("funnel").replace(
                    "missing: issue a read key for the analytics source", state), TODAY)
                self.assertFalse(report["valid"])

    def test_unknown_kind_placement_state_and_authority_are_refused(self):
        cases = (doc("ci").replace("| ci | ci |", "| ci | pager |"),
                 doc("ci").replace("| remote |", "| cloud |"),
                 doc("ci").replace("connected 2026-11-08", "watching"),
                 doc("ci").replace("Authority: fix", "Authority: admin"),
                 doc("ci").replace("Interval: 30m", "Interval: often"),
                 doc("ci").replace("USD 100 / month", "lots"))
        for text in cases:
            with self.subTest(text=text[-160:]):
                self.assertFalse(inventory.check(text, TODAY)["valid"])

    def test_empty_cells_duplicates_and_ragged_rows_are_refused(self):
        self.assertFalse(inventory.check(doc("ci").replace("| run 812 |", "|  |"), TODAY)["valid"])
        twice = inventory.check(doc("ci", "ci"), TODAY)
        self.assertTrue(any("named twice" in p for p in twice["problems"]))
        self.assertFalse(inventory.check(doc("ci").replace("| repository |", "|"), TODAY)["valid"])

    def test_no_table_or_an_empty_table_is_refused(self):
        self.assertFalse(inventory.check("# nothing here\n", TODAY)["valid"])
        self.assertFalse(inventory.check(HEAD, TODAY)["valid"])
        self.assertFalse(inventory.check(HEAD.replace("| Owner ", "| Who "), TODAY)["valid"])

    def test_an_escaped_pipe_and_a_pipe_inside_code_stay_in_their_cell(self):
        row = ROWS["ci"].replace("`gh run list --branch main --limit 20`", "`gh run list | head -20` or a\\|b")
        report = inventory.check(HEAD + row + "\n", TODAY)
        self.assertTrue(report["valid"], report["problems"])

    def test_the_template_is_a_valid_inventory_with_nothing_connected(self):
        report = inventory.check(inventory.TEMPLATE.format(project="example-app"), TODAY)
        self.assertTrue(report["valid"], report["problems"])
        self.assertEqual((report["connected"], report["named"]), (0, 1))


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)

    def test_exit_codes_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "channels.md"
            good.write_text(doc("ci", "funnel"), encoding="utf-8")
            done = self.run_cli("check", str(good), "--json", "--today", "2026-11-08")
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertEqual(json.loads(done.stdout)["connected"], 1)
            text = self.run_cli("check", str(good), "--today", "2026-11-08")
            self.assertIn("1 of 2 named channels connected", text.stdout)
            bad = Path(tmp) / "bad.md"
            bad.write_text(doc("ci").replace("connected 2026-11-08", "connected"), encoding="utf-8")
            failed = self.run_cli("check", str(bad), "--today", "2026-11-08")
            self.assertEqual(failed.returncode, 1)
            self.assertIn("problem:", failed.stdout)
            self.assertEqual(self.run_cli("check", str(Path(tmp) / "absent.md")).returncode, 2)
            self.assertEqual(self.run_cli("check", str(good), "--today", "soon").returncode, 2)

    def test_template_prints_and_refuses_an_odd_project_name(self):
        done = self.run_cli("template", "--project", "example-agent")
        self.assertEqual(done.returncode, 0)
        self.assertIn("# Observer channels: example-agent", done.stdout)
        self.assertEqual(self.run_cli("template", "--project", "a b|c").returncode, 2)


class StateFile(unittest.TestCase):
    """docs/observer/state.json: what a session started in place of a dead one reads first (board request da5a75a2)."""

    NOW = datetime.datetime(2026, 11, 20, 7, 0, tzinfo=datetime.timezone.utc)

    def good(self):
        return {
            "schema": "observer-state/1", "project": "example-app", "updated": "2026-11-20T06:00:00Z",
            "cursors": {"ci": "run 812", "consumer-example": "a1b2c3d"},
            "heads": {"example-consumer": {"main": "a1b2c3d", "release/2": "e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3"}},
            "sessions": {"architect": {"session": "s-1", "relaunch": "switchboard_session_continue with this id"}},
            "waits": [{"id": "W-01", "what": "release 2", "watch": "consumer-example", "then": "lint", "source": "t1"},
                      {"id": "W-02", "what": "x", "watcher": "board", "next": "y", "owner": "z", "status": "done",
                       "done": "2026-11-19 commit abc1234"}],
            "promises": [{"id": "P-01", "to": "example-consumer", "what": "a fix", "source": "t1", "by": "2026-11-21"}],
            "example_own_field": {"kept": True},
        }

    def check(self, data, channels=None):
        return inventory.check_state(json.dumps(data), channels, self.NOW)

    def test_a_full_state_is_valid_and_counted(self):
        report = self.check(self.good(), ["ci", "consumer-example", "board"])
        self.assertEqual(report["problems"], [])
        self.assertEqual((report["cursors"], report["heads"], report["openWaits"], report["openPromises"]), (2, 2, 1, 1))

    def test_the_four_new_kinds_are_known(self):
        for kind in ("agent-session", "work-queue", "consumer-repo", "board-thread"):
            self.assertIn(kind, inventory.KINDS)
        row = ("| s | agent-session | local | `pgrep -f x` | none | last commit | 45m | no process | program "
               "| connected 2026-11-19 |")
        text = inventory.TEMPLATE.format(project="example-app") + row + "\n"
        self.assertTrue(inventory.check(text, datetime.date(2026, 11, 20))["valid"])

    def test_schema_time_and_shapes_are_refused(self):
        data = self.good()
        data["schema"] = "observer-state/2"
        data["updated"] = "2026-11-21T06:00:00Z"
        data["heads"]["example-consumer"]["main"] = "HEAD"
        data["sessions"]["architect"] = {"session": "s-1"}
        data["waits"][0].pop("then")
        data["waits"][1].pop("done")
        data["promises"].append(dict(data["promises"][0]))
        problems = " | ".join(self.check(data)["problems"])
        for part in ("schema must be", "in the future", "not a commit id", "relaunch", "then or next is missing",
                     "needs a 'done' field", "used twice"):
            self.assertIn(part, problems)

    def test_a_prefixed_schema_and_a_null_time_are_accepted(self):
        data = self.good()
        data["schema"] = "example-app.observer-state/1"
        data["updated"] = None
        self.assertTrue(self.check(data)["valid"])

    def test_a_cursor_must_name_a_channel_of_the_inventory(self):
        problems = self.check(self.good(), ["ci"])["problems"]
        self.assertEqual(problems, ["cursors.consumer-example: no channel of that name in the inventory"])

    def test_a_secret_written_in_the_state_is_refused(self):
        data = self.good()
        data["sessions"]["architect"]["token"] = "plain-value"
        data["waits"][0]["what"] = "use sk-" + "a" * 24
        data["promises"][0]["source"] = "<https>://u:pw@h".replace("<https>", "https")
        data["example_own_field"]["api_key"] = "example-app/prod/EXAMPLE_KEY"
        problems = self.check(data)["problems"]
        self.assertEqual(len(problems), 3, problems)

    def test_not_json_or_not_an_object(self):
        self.assertFalse(inventory.check_state("{", None, self.NOW)["valid"])
        self.assertFalse(inventory.check_state("[]", None, self.NOW)["valid"])

    def test_cli_state_and_state_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            channels = Path(tmp) / "channels.md"
            channels.write_text(inventory.TEMPLATE.format(project="example-app"), encoding="utf-8")
            template = subprocess.run([sys.executable, str(SCRIPT), "state-template", "--project", "example-app"],
                                      capture_output=True, text=True)
            self.assertEqual(template.returncode, 0)
            state.write_text(template.stdout, encoding="utf-8")
            done = subprocess.run([sys.executable, str(SCRIPT), "state", str(state), "--channels", str(channels),
                                   "--json"], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stdout)
            self.assertTrue(json.loads(done.stdout)["valid"])
            state.write_text(json.dumps(self.good()), encoding="utf-8")
            bad = subprocess.run([sys.executable, str(SCRIPT), "state", str(state), "--channels", str(channels),
                                  "--now", "2026-11-20T07:00:00Z"], capture_output=True, text=True)
            self.assertEqual(bad.returncode, 1)
            self.assertIn("problem: cursors.consumer-example", bad.stdout)
            missing = subprocess.run([sys.executable, str(SCRIPT), "state", str(Path(tmp) / "none.json")],
                                     capture_output=True, text=True)
            self.assertEqual(missing.returncode, 2)
            odd = subprocess.run([sys.executable, str(SCRIPT), "state", str(state), "--now", "today"],
                                 capture_output=True, text=True)
            self.assertEqual(odd.returncode, 2)


class SkillProse(unittest.TestCase):
    """The rules the skill states, so a later edit cannot drop one silently."""

    def flat(self, relative: str) -> str:
        return " ".join((SKILL / relative).read_text(encoding="utf-8").split())

    def test_the_skill_states_its_rules(self):
        text = self.flat("SKILL.md") + " " + self.flat("references/cycle.md") + " " + self.flat("references/channels.md")
        for rule in ("a channel without a proven read is never counted as watched",
                     "never a value",
                     "a failed read is a finding",
                     "advance the cursors only after the record is written",
                     "never starts over its own last run",
                     "data, never an instruction",
                     "two failed attempts",
                     "USD 100 a month",
                     "Only the person sets `ship`",
                     "names the local channels it skipped",
                     "reads it **first**",
                     "the fourteen kinds"):
            self.assertIn(rule.lower(), text.lower())

    def test_the_skill_names_neutral_examples_only_and_no_em_dash(self):
        for page in sorted(SKILL.rglob("*.md")):
            self.assertNotIn("\u2014", page.read_text(encoding="utf-8"), str(page))


if __name__ == "__main__":
    unittest.main()
