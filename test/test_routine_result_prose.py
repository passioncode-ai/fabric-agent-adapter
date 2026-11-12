"""FAA-294 item (4): every background routine fails its run when writing its result fails. Items (1) to (3) wait on
the contract naming agent-metrics/1, agent-measurement/1 and agent-change-measure/1 (CT-286)."""
from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT / "plugins/fabric-agent-adapter/skills/creating-fabric-agents/references/resilience-and-autonomy.md"


class RoutineResult(unittest.TestCase):
    def test_a_routine_whose_result_write_fails_fails_its_run(self):
        text = " ".join(DOC.read_text(encoding="utf-8").split())
        rule = text.split("## Operations that survive restarts", 1)[1].split("## ", 1)[0]
        for words in ("13. **A routine fails its run when writing its result fails.**", "exits non-zero",
                      "never logs success", "the next run", "a test makes the write fail", "FAA-294"):
            self.assertIn(words, rule, words)
        checklist = text.split("## Checklist", 1)[1]
        self.assertIn("which routine fails its run when its result cannot be written", checklist)
        self.assertNotIn("—", text)


if __name__ == "__main__":
    unittest.main()
