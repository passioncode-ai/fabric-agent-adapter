"""FAA-75 (audit finding 33): the trigger-eval runner's scoring, with a fake client (no model is called)."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_evals", ROOT / "test/evals/run_evals.py")
run_evals = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_evals)

SKILLS = {"alpha-skill": "Use when alpha.", "beta-skill": "Use when beta."}


def fake(answers):
    """A client that answers by the request text inside the prompt."""
    def call(prompt):
        for needle, answer in answers.items():
            if needle in prompt.split("Request:", 1)[1]:
                return answer
        return "none"
    return call


class ScoringTests(unittest.TestCase):
    def test_parse_answer_takes_the_named_skill_or_none(self):
        names = list(SKILLS)
        self.assertEqual(run_evals.parse_answer("alpha-skill", names), "alpha-skill")
        self.assertEqual(run_evals.parse_answer("  Beta-Skill.\n", names), "beta-skill")
        self.assertEqual(run_evals.parse_answer("none", names), "none")
        self.assertEqual(run_evals.parse_answer("", names), "none")
        self.assertEqual(run_evals.parse_answer("beta-skill, not alpha-skill", names), "beta-skill")

    def test_a_positive_passes_on_its_skill_and_a_negative_on_anything_else(self):
        queries = [{"query": "do alpha", "shouldTrigger": True}, {"query": "do beta", "shouldTrigger": False},
                   {"query": "do nothing", "shouldTrigger": False}, {"query": "alpha again", "shouldTrigger": True},
                   {"query": "sneaky", "shouldTrigger": False}]
        client = fake({"do alpha": "alpha-skill", "do beta": "beta-skill", "alpha again": "beta-skill", "sneaky": "alpha-skill"})
        results = run_evals.run_cases("alpha-skill", queries, SKILLS, client, jobs=3)
        self.assertEqual([r["passed"] for r in results], [True, True, True, False, False])
        summary = run_evals.summarize("alpha-skill", results)
        self.assertEqual((summary["passed"], summary["cases"], summary["positivesPassed"], summary["negativesPassed"]), (3, 5, "1/2", "2/3"))
        self.assertFalse(summary["aboveThreshold"])

    def test_a_failed_call_is_a_failed_case_never_a_pass(self):
        def broken(prompt):
            raise RuntimeError("claude exited 1")
        results = run_evals.run_cases("alpha-skill", [{"query": "x", "shouldTrigger": False}], SKILLS, broken)
        self.assertFalse(results[0]["passed"])
        self.assertIn("RuntimeError", results[0]["error"])

    def test_the_prompt_lists_every_skill_and_none(self):
        prompt = run_evals.build_prompt(SKILLS, "the request")
        for name in list(SKILLS) + ["none"]:
            self.assertIn("- %s:" % name, prompt)
        self.assertIn("the request", prompt)

    def test_the_real_descriptions_are_read_from_each_skill(self):
        skills = run_evals.load_skills()
        self.assertEqual(set(skills), {"adapting-projects-to-fabric", "building-fabric-services", "creating-fabric-agents", "working-with-fabric"})
        for name, description in skills.items():
            self.assertTrue(description.startswith("Use when"), name)
            self.assertLess(len(description), 1024, name)


class GateTests(unittest.TestCase):
    def test_without_the_opt_in_it_is_not_run_and_never_a_pass(self):
        with mock.patch.dict(os.environ, {"FABRIC_REAL_CLIENT": ""}), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run_evals.main(["--skill", "adapting-projects-to-fabric"]), 2)
        self.assertIn("NOT_RUN", out.getvalue())

    def test_exit_follows_the_threshold(self):
        triggers = json.loads((ROOT / "test/evals/adapting-projects-to-fabric/triggers.json").read_text())
        perfect = {q["query"]: ("adapting-projects-to-fabric" if q["shouldTrigger"] else "none") for q in triggers["queries"]}
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            out = Path(temp) / "r.json"
            self.assertEqual(run_evals.main(["--skill", "adapting-projects-to-fabric", "--json", str(out)], client=fake(perfect)), 0)
            self.assertEqual(json.loads(out.read_text())["skills"][0]["passRate"], 1.0)
            self.assertEqual(run_evals.main(["--skill", "adapting-projects-to-fabric"], client=lambda p: "creating-fabric-agents"), 1)


if __name__ == "__main__":
    unittest.main()
