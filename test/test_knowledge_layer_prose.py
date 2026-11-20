"""FAA-366: the knowledge layer of the agents database's D-84 (board request 599b59d6, the operator's words of
2026-11-19): the intake asks it in creating and adapting, the eight parts in order of value, local cached embeddings,
the empty-text trap, and the knowledge map panel's recipe in building-fabric-services."""
from __future__ import annotations

import json
import pathlib
import unittest

SKILLS = pathlib.Path(__file__).resolve().parents[1] / "plugins" / "fabric-agent-adapter" / "skills"
EVALS = pathlib.Path(__file__).resolve().parent / "evals"
PANEL = SKILLS / "building-fabric-services" / "references" / "knowledge-map-panel.md"


def flat(path: pathlib.Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


class KnowledgeLayer(unittest.TestCase):
    def test_part_4_lists_the_eight_parts_in_order(self):
        text = flat(SKILLS / "creating-fabric-agents" / "references" / "agent-knowledge.md")
        self.assertIn("## Part 4: the knowledge layer of an agent that keeps a knowledge base", text)
        parts = [
            "1. **Hybrid search**",
            "2. **A local reranker over the top 30 to 50**",
            "3. **A gold set per language as a gate on every change**",
            "4. **A context header on every chunk**",
            "5. **A link graph beside the index**",
            "6. **Bi-temporal facts**",
            "7. **A compiled wiki for hot topics**",
            "8. **A knowledge map** (`knowledge-map/1`)",
        ]
        positions = [text.index(part) for part in parts]
        self.assertEqual(positions, sorted(positions), "the parts are out of order")
        for phrase in ("decision D-84", "board request `599b59d6`", "recall@5 and MRR@10", "with no LLM judge",
                       "**semantic links**", "only for a question classified multi-hop or global",
                       "never deleted", "the sha256 of the text", "refuse an empty or whitespace-only text",
                       "`built`, `planned` with a reason, or `not needed`", "knowledge-map-panel.md"):
            self.assertIn(phrase, text)

    def test_the_intake_asks_it(self):
        creating = flat(SKILLS / "creating-fabric-agents" / "SKILL.md")
        self.assertIn("| **Does it keep a knowledge base?** |", creating)
        self.assertIn("the agents database's D-84", creating)
        adapting = flat(SKILLS / "adapting-projects-to-fabric" / "SKILL.md")
        self.assertIn("the audit also asks for its knowledge layer, the agents database's D-84", adapting)
        for text in (creating, adapting):
            self.assertIn("[agent knowledge](references/agent-knowledge.md), Part 4", text)

    def test_the_panel_recipe(self):
        self.assertIn("a knowledge map: [its panel](references/knowledge-map-panel.md)",
                      flat(SKILLS / "building-fabric-services" / "SKILL.md"))
        text = flat(PANEL)
        for phrase in ("Circulation", "Living organism", "Atlas", "Galaxy", "Semantic map",
                       "d3 7.9.2 (ISC)", "force-graph 1.52.0 (MIT)", "sigma 4.0.6 + graphology 0.26.0 (MIT)",
                       "cosmos.gl 3.6.0 (MIT)", "never a CDN", "prefers-reduced-motion",
                       "`nodes: [Sigma.DEFAULT_STYLES.nodes, {...}]`", "Call `fitView` after the first frame",
                       "`style-src 'self' 'unsafe-inline'`", "never `script-src`",
                       "similarity 1.0", "Start from **Semantic map**", "FAA-367"):
            self.assertIn(phrase, text)

    def test_the_panel_names_the_maps_real_fields(self):
        text = flat(PANEL)
        for field in ("`schema`", "`built_at`", "`revision`", "`embedder`", "`degraded`", "`nodes[]`", "`edges[]`",
                      "`clusters[]`"):
            self.assertIn(field, text)

    def test_one_scenario_eval_per_skill(self):
        wanted = {
            "creating-fabric-agents": "a-new-agent-with-a-knowledge-base",
            "adapting-projects-to-fabric": "an-existing-agent-with-memory",
            "building-fabric-services": "a-knowledge-map-on-the-dashboard",
        }
        for skill, scenario in wanted.items():
            ids = [s["id"] for s in json.loads((EVALS / skill / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]]
            self.assertIn(scenario, ids, skill)


if __name__ == "__main__":
    unittest.main()
