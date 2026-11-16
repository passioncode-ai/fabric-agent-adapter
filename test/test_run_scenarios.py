"""test/evals/run_scenarios.py (FAA-339): the scenario runner's gate, its judge parsing and its verdicts, with a fake agent
and a fake judge; no model is called."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("run_scenarios", ROOT / "test/evals/run_scenarios.py")
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)

SCENARIO = {"id": "example", "request": "Do the example.", "expected": ["reads the README first", "says it is done"]}


def judge_saying(*verdicts):
    def judge(prompt):
        judge.prompts.append(prompt)
        return json.dumps({"verdicts": [{"index": i, "met": met, "evidence": quote} for i, (met, quote) in enumerate(verdicts)]})
    judge.prompts = []
    return judge


def agent_saying(text):
    def agent(system, request, folder):
        agent.calls.append((system, request, folder, (folder / "SKILL.md").is_file()))
        return text
    agent.calls = []
    return agent


class ParseVerdicts(unittest.TestCase):
    def test_a_quote_is_needed_and_a_missing_index_is_not_met(self):
        text = json.dumps({"verdicts": [{"index": 0, "met": True, "evidence": "I read the README"},
                                        {"index": 1, "met": True, "evidence": "  "}]})
        verdicts = rs.parse_verdicts(text, 3)
        self.assertEqual([v["met"] for v in verdicts], [True, False, False])

    def test_fenced_json_reads_and_no_json_refuses(self):
        self.assertTrue(rs.parse_verdicts('```json\n{"verdicts": [{"index": 0, "met": true, "evidence": "x"}]}\n```', 1)[0]["met"])
        with self.assertRaises(ValueError):
            rs.parse_verdicts("I think it passed", 1)

    def test_out_of_range_and_non_boolean_verdicts_are_not_met(self):
        text = json.dumps({"verdicts": [{"index": 5, "met": True, "evidence": "x"}, {"index": 0, "met": "yes", "evidence": "x"}]})
        self.assertEqual([v["met"] for v in rs.parse_verdicts(text, 1)], [False])


class RunCases(unittest.TestCase):
    def test_every_expectation_met_passes_and_the_agent_works_in_a_copy_of_the_skill(self):
        agent = agent_saying("I read the README, then say it is done.")
        judge = judge_saying((True, "I read the README"), (True, "say it is done"))
        result = rs.run_case("working-with-fabric", SCENARIO, agent, judge)
        self.assertTrue(result["passed"])
        self.assertEqual(result["met"], "2/2")
        system, request, folder, had_skill = agent.calls[0]
        self.assertTrue(had_skill)
        self.assertFalse(folder.exists())  # the copy is removed after the case
        self.assertNotEqual(folder.resolve(), (rs.SKILLS / "working-with-fabric").resolve())
        self.assertIn("You cannot run anything", system)
        self.assertNotIn("\n---\n", system[:200])  # the front matter is not part of the instructions
        self.assertEqual(request, "Do the example.")
        self.assertIn("1. says it is done", judge.prompts[0])

    def test_one_unmet_expectation_fails_and_a_failed_call_is_a_named_failure(self):
        result = rs.run_case("working-with-fabric", SCENARIO, agent_saying("x"), judge_saying((True, "x"), (False, "")))
        self.assertFalse(result["passed"])
        self.assertEqual(result["met"], "1/2")

        def broken(system, request, folder):
            raise RuntimeError("claude exited 1")
        result = rs.run_case("working-with-fabric", SCENARIO, broken, judge_saying())
        self.assertFalse(result["passed"])
        self.assertIn("claude exited 1", result["error"])


class Main(unittest.TestCase):
    def test_not_run_without_the_real_client_or_the_judges_key(self):
        with mock.patch.dict(os.environ, {"FABRIC_REAL_CLIENT": "", "OPENROUTER_API_KEY": ""}):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(rs.main(["--skill", "working-with-fabric"]), 2)
        self.assertIn("NOT_RUN", out.getvalue())

    def test_a_run_records_its_verdicts_and_exits_by_them(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        scenarios = json.loads((rs.EVALS / "working-with-fabric/scenarios.json").read_text(encoding="utf-8"))["scenarios"]
        first = scenarios[0]
        judge = judge_saying(*[(True, "quote %d" % i) for i in range(len(first["expected"]))])
        with contextlib.redirect_stdout(io.StringIO()):
            code = rs.main(["--skill", "working-with-fabric", "--scenario", first["id"], "--record", str(folder)],
                           agent=agent_saying("an answer"), judge=judge)
        self.assertEqual(code, 0)
        report = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        self.assertEqual([r["id"] for r in report["results"]], [first["id"]])
        self.assertIn("| working-with-fabric | `%s` |" % first["id"], (folder / "README.md").read_text(encoding="utf-8"))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(rs.main(["--skill", "working-with-fabric", "--scenario", first["id"]],
                                     agent=agent_saying("x"), judge=judge_saying()), 1)

    def test_an_unknown_scenario_is_refused(self):
        with self.assertRaises(SystemExit):
            rs.select(["working-with-fabric"], ["no-such-scenario"])


if __name__ == "__main__":
    unittest.main()
