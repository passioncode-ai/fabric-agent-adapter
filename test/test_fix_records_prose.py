"""Two working-with-fabric rules a model judges in its scenarios (test/evals/working-with-fabric/scenarios.json), held
here by the words the skill must carry, since hosted CI runs no model:

- a solved frequent harness, MCP, account or tooling problem goes to the agents database as a `fix` record beside the
  Observatory lesson (board request 9ea96d90 from fabric-workspace; the base's playbooks/record-fix.md);
- a question with `options` marks one `recommended` (board request 981a7b99 from Fabric: Fabric 0.3.21 refuses options
  with no recommended one, CO-580)."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins/fabric-agent-adapter/skills"
SCENARIOS = {s["id"]: s for s in json.loads((ROOT / "test/evals/working-with-fabric/scenarios.json")
                                            .read_text(encoding="utf-8"))["scenarios"]}


def read(path):
    return " ".join((SKILLS / path).read_text(encoding="utf-8").split())


class FixRecords(unittest.TestCase):
    def test_the_scenario_is_there(self):
        self.assertIn("a-solved-harness-problem-is-a-fix-record", SCENARIOS)

    def test_the_reference_says_how_a_fix_is_sent(self):
        text = read("working-with-fabric/references/agents-database.md")
        for words in ("`fix:", "playbooks/record-fix.md", "`type: fix`", "kind", "verify"):
            self.assertIn(words, text)

    def test_the_retro_step_names_the_fix_record(self):
        self.assertIn("fix record", read("working-with-fabric/SKILL.md"))


class RecommendedOption(unittest.TestCase):
    def test_both_places_that_ask_with_options_mark_one_recommended(self):
        for path in ("working-with-fabric/references/task-context.md", "creating-fabric-agents/references/working-rules.md"):
            with self.subTest(path=path):
                text = read(path)
                self.assertIn("`recommended`", text)
                self.assertIn("CO-580", text)
                self.assertIn("`consequence`", text)

    def test_the_scenario_expects_it(self):
        self.assertTrue(any("recommended" in e for e in SCENARIOS["unsettled-context-asks-once"]["expected"]))


if __name__ == "__main__":
    unittest.main()
