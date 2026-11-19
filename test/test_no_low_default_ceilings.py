"""No low default spend ceiling in what a builder copies (FAA-364, board request 12caaa48).

The operator's order of 2026-11-19, recorded by the agents base as D-79 on R33 O16: a default money limit is large
(50, 100, 1000 USD); a lower one is set only by a person or by a proven pipeline. The recipes' example configs and the
skills' documented examples are what a new agent starts from, so none of them may carry a ceiling under 50.
"""
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins" / "fabric-agent-adapter" / "skills"
FLOOR_USD = 50
# ceiling_usd=2.0 (Python) or ceilingUsd: 2 (JavaScript) in a documented example
DOC_CEILING = re.compile(r"\b(?:ceiling_usd\s*=|ceilingUsd\s*:)\s*([0-9]+(?:\.[0-9]+)?)\b")


def low_ceilings_in(text):
    """The documented ceilings under the floor in one text, as (line number, match)."""
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in DOC_CEILING.finditer(line):
            if float(match.group(1)) < FLOOR_USD:
                found.append((number, match.group(0)))
    return found


class NoLowDefaultCeilings(unittest.TestCase):
    def test_recipe_example_configs_hold_a_large_ceiling(self):
        configs = sorted((SKILLS / "building-fabric-services" / "recipes").glob("*/config.example.json"))
        self.assertTrue(configs, "no recipe example config found")
        for path in configs:
            config = json.loads(path.read_text(encoding="utf-8"))
            if "ceilingUsd" not in config:
                continue
            with self.subTest(config=str(path.relative_to(ROOT))):
                self.assertGreaterEqual(float(config["ceilingUsd"]), FLOOR_USD)

    def test_documented_examples_hold_a_large_ceiling(self):
        low = []
        for path in sorted(SKILLS.rglob("*.md")):
            for number, text in low_ceilings_in(path.read_text(encoding="utf-8")):
                low.append(f"{path.relative_to(ROOT)}:{number}: {text}")
        self.assertEqual(low, [], "a documented example carries a low default ceiling")

    def test_the_check_reads_both_twins_and_catches_a_low_one(self):
        self.assertEqual(low_ceilings_in("Client(ceiling_usd=2.0, window"), [(1, "ceiling_usd=2.0")])
        self.assertEqual(low_ceilings_in("new Client({ ceilingUsd: 2, ledger"), [(1, "ceilingUsd: 2")])
        self.assertEqual(low_ceilings_in("new Client({ ceilingUsd: 95, window"), [])


if __name__ == "__main__":
    unittest.main()
