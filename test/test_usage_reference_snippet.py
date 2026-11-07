"""The Python call `references/usage.md` gives for every limit (DEC-0027) runs against the kit as written (0.75.0
seam reading 7: it showed `ledger.report(..., budgets=...)`, which the Python ledger refuses)."""
import importlib
import pathlib
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services"


class TheEveryLimitSnippetRuns(unittest.TestCase):
    def test_the_python_block_after_every_limit_returns_its_budgets(self):
        sys.path.insert(0, str(SKILL / "scripts"))
        fabric_usage = importlib.import_module("fabric_usage")
        text = (SKILL / "references/usage.md").read_text(encoding="utf-8")
        section = text.split("**Every limit (DEC-0027).**", 1)[1]
        code = re.search(r"```python\n(.*?)```", section, re.S).group(1)
        with tempfile.TemporaryDirectory() as folder:
            ledger = fabric_usage.JsonlUsageLedger(pathlib.Path(folder) / "usage.jsonl")
            report = eval(code, {"fabric_usage": fabric_usage, "ledger": ledger, "ID": "example-agent", "INSTANCE": "default"})
        self.assertEqual(3, len(report["budgets"]))


if __name__ == "__main__":
    unittest.main()
