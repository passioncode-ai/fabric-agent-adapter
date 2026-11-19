"""FAA-360: the skills teach a project's knowledge surface (board request 52f7914b, the operator's rule of 2026-11-19):
search with verified citations, a hybrid index, two MCP doors, asking through them, and the consumers' audit."""
from __future__ import annotations

import json
import pathlib
import unittest

SKILLS = pathlib.Path(__file__).resolve().parents[1] / "plugins" / "fabric-agent-adapter" / "skills"
EVALS = pathlib.Path(__file__).resolve().parent / "evals"
NAMES = ("adapting-projects-to-fabric", "building-fabric-services", "creating-fabric-agents", "working-with-fabric")
LINK = "[agent knowledge](references/agent-knowledge.md)"


def flat(path: pathlib.Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


class AgentKnowledge(unittest.TestCase):
    def test_the_reference_is_one_text_in_every_skill(self):
        copies = [(SKILLS / name / "references" / "agent-knowledge.md").read_bytes() for name in NAMES]
        self.assertEqual(len(set(copies)), 1, "the four copies differ")

    def test_the_reference_holds_the_three_parts_and_the_callers_side(self):
        text = flat(SKILLS / NAMES[0] / "references" / "agent-knowledge.md")
        for phrase in (
            "board request `52f7914b`",
            "its board request `e968b42b`",  # the template rule is linked, not copied
            "mcp-two-doors.md",
            "keeps only the claims whose quote is found there verbatim within the cited lines",
            "A claim whose quote is not found is dropped, never repaired",
            "**BM25 with stemming**", "**character trigrams**", "**local vectors**",
            "Reciprocal Rank Fusion",
            "**Fresh on every commit, checked before every push.**",
            "recall at 3",
            "`knowledge.search` is one of those operations, read only, called through `execute`",
            "asks that project and never reads its checkout",
            "every 30 minutes",
        ):
            self.assertIn(phrase, text)

    def test_every_skill_links_it(self):
        for name in NAMES:
            text = flat(SKILLS / name / "SKILL.md")
            self.assertIn(LINK, text, name)

    def test_the_observer_audits_the_consumers(self):
        text = flat(SKILLS / "observing-products" / "SKILL.md")
        self.assertIn("### A project others build on: the consumers' audit", (SKILLS / "observing-products" / "SKILL.md").read_text(encoding="utf-8"))
        for phrase in ("every 30 minutes", "which version each consumer pins", "which retired names are still called",
                       "found nothing or had every claim dropped", "never from their repositories", "CO-598"):
            self.assertIn(phrase, text)

    def test_one_scenario_eval_per_skill(self):
        wanted = {
            "adapting-projects-to-fabric": "a-project-other-agents-read",
            "creating-fabric-agents": "a-new-agent-others-build-on",
            "building-fabric-services": "a-service-serves-its-knowledge",
            "working-with-fabric": "asking-another-project-not-its-checkout",
            "observing-products": "a-product-others-build-on",
        }
        for skill, scenario in wanted.items():
            ids = [s["id"] for s in json.loads((EVALS / skill / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]]
            self.assertIn(scenario, ids, skill)


if __name__ == "__main__":
    unittest.main()
