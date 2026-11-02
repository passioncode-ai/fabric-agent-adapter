"""FAA-191 (0.59.0): what creating-fabric-agents and building-fabric-services must say so that a new agent is portable
from its first commit (RM-36; the operator's decision of 2026-10-30 and its addition of 2026-11-02, relayed on the
board): a data home of its own and the kind of its data, an uptime category asked at intake, a LICENSE naming the
copyright holder, and the transfer audit at every release until the contract's export (CT-194). Pinned to the scenario
evals `portable-from-day-zero` and `new-service-names-data-and-uptime`, which a model judges and hosted CI cannot run."""

import json
import unittest

from test_action_and_dashboard_prose import ROOT, flat, scenario_ids, section, text

GRILL = "Step 0: the intake grill"


def one_row(skill_md: str, head: str) -> str:
    rows = [" ".join(line.split()) for line in text(skill_md).splitlines() if line.startswith("| " + head + " |")]
    if len(rows) != 1:
        raise AssertionError("%s: %d rows start with %r" % (skill_md, len(rows), head))
    return rows[0]


class PortableFromDayZero(unittest.TestCase):
    def test_the_scenarios_and_the_trigger_exist(self):
        self.assertIn("portable-from-day-zero", scenario_ids("creating-fabric-agents"))
        self.assertIn("new-service-names-data-and-uptime", scenario_ids("building-fabric-services"))
        queries = json.loads((ROOT / "test/evals/creating-fabric-agents/triggers.json").read_text(encoding="utf-8"))
        self.assertTrue(any(q["shouldTrigger"] and "переносимый с первого дня" in q["query"] for q in queries["queries"]))

    def test_the_grill_asks_uptime_data_and_holder(self):
        grill = section("creating-fabric-agents", GRILL)
        uptime = one_row("creating-fabric-agents/SKILL.md", "**Does it run around the clock?**")
        for words in ("**A** when a capability must answer while the owner's machine is off or asleep",
                      "a cloud host from its first release, Heroku unless a reason names another",
                      "the cloud Fabric-server template once that template's repository exists",
                      "**B** when nothing needs it then: a local service only, no cloud",
                      "through that agent's MCP or API", "The README names the category"):
            self.assertIn(words, uptime, words)
        data = one_row("creating-fabric-agents/SKILL.md", "**Whose data does it keep?**")
        for words in ("named in the README", "**U** when it keeps data of people outside the owner's team",
                      "never enters the source, a copy of it or its tests", "the schema and synthetic fixtures",
                      "a copy starts with an empty store of its own", "**O** when it keeps none", "In doubt, U.",
                      "the data lives in `<agent>-data`, apart from the source, from the first commit"):
            self.assertIn(words, data, words)
        holder = one_row("creating-fabric-agents/SKILL.md", "**Who holds the copyright?**")
        for words in ("gets a `LICENSE` naming that holder in its first commit",
                      "all rights reserved unless the owner gives other terms", "a public product keeps its own licence"):
            self.assertIn(words, holder, words)
        self.assertLess(grill.index("**Where does it run, for whom?**"), grill.index("**Does it run around the clock?**"))

    def test_the_skeleton_gives_the_data_a_home_and_a_licence(self):
        step_2 = " ".join(section("creating-fabric-agents", "Step 2: the project skeleton").split())
        for words in ("Its data has a home of its own from the same commit, `<agent>-data` (a folder beside the checkout, "
                      "or a private repository of that name)",
                      "the README names the data kind (U or O) and the uptime category (A or B)",
                      "its first commit carries a `LICENSE` naming the copyright holder the grill recorded"):
            self.assertIn(words, step_2, words)

    def test_every_release_runs_the_transfer_audit(self):
        step_5 = " ".join(section("creating-fabric-agents", "Step 5: check, report, and set the canary expectation").split())
        self.assertIn("Every release of the agent runs it too, in Git mode and with `--every-file`, as the transfer audit "
                      "(each exit 0, with the owner's list or its absence recorded) until the contract's export (CT-194) "
                      "replaces it", step_5)
        for skill in ("creating-fabric-agents", "adapting-projects-to-fabric"):
            reference = flat(skill + "/references/source-and-instance.md")
            self.assertIn("[The data home and its kind](#the-data-home-and-its-kind)", reference)
            for words in ("**The data has a home of its own from the first commit: `<agent>-data`.**",
                          "`<AGENT>_DATA_DIR` names it (its default is `../<agent>-data`)",
                          "a separate private repository named `<agent>-data`, never to the source's repository",
                          "never connects to the original's", "When in doubt, the kind is U.",
                          "**Every release runs the transfer audit.**"):
                self.assertIn(words, reference, (skill, words))

    def test_the_uptime_reference_and_its_checklist(self):
        where = flat("creating-fabric-agents/references/where-agents-run.md")
        for words in ("[Uptime: A or B](#uptime-a-or-b)", "## Uptime: A or B", "**A, around the clock.**",
                      "**B, local only.**", "never from its store",
                      "becomes A for that capability; record the change and move only that capability to the cloud",
                      "Which uptime category is it, A (a cloud host from the first release) or B (local only)?"):
            self.assertIn(words, where, words)

    def test_a_new_service_records_the_same_answers(self):
        row = one_row("building-fabric-services/SKILL.md", "Data and uptime")
        for words in ("kind U or O", "`<id>-data`", "uptime A or B", "`LICENSE` holder", "transfer audit per release",
                      "creating-fabric-agents"):
            self.assertIn(words, row, words)
        self.assertIn(row, " ".join(section("building-fabric-services", "Step 0: is it a service?").split()))


if __name__ == "__main__":
    unittest.main()
