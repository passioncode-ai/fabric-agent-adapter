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
        building = json.loads((ROOT / "test/evals/building-fabric-services/scenarios.json").read_text(encoding="utf-8"))
        audit = [e for s in building["scenarios"] if s["id"] == "new-service-names-data-and-uptime"
                 for e in s["expected"] if "transfer audit" in e]
        self.assertTrue(audit and "--every-file on a clean copy of what Git would commit" in audit[0], audit)
        queries = json.loads((ROOT / "test/evals/creating-fabric-agents/triggers.json").read_text(encoding="utf-8"))
        self.assertTrue(any(q["shouldTrigger"] and "переносимый с первого дня" in q["query"] for q in queries["queries"]))

    def test_the_grill_asks_uptime_data_and_holder(self):
        grill = section("creating-fabric-agents", GRILL)
        uptime = one_row("creating-fabric-agents/SKILL.md", "**Does it run around the clock?**")
        for words in ("**A** when a capability must answer while the owner's machine is off or asleep",
                      "a cloud host from its first release, Heroku unless a reason names another",
                      "the cloud Fabric-server template once that template's repository exists",
                      "**B** when nothing needs it then: local only, no cloud",
                      "through that agent's MCP or API", "The README names the category"):
            self.assertIn(words, uptime, words)
        data = one_row("creating-fabric-agents/SKILL.md", "**Whose data does it keep?**")
        for words in ("named in the README", "**U** when it keeps data of people outside the owner's team",
                      "never enters the source, a copy of it or its tests", "the schema and synthetic fixtures",
                      "a copy starts with an empty store of its own", "**O** when it keeps none", "In doubt, U.",
                      "the data lives in `<agent>-data` (a kit service: the kit's folders; on a cloud host: a durable store), "
                      "apart from the source, from the first commit"):
            self.assertIn(words, data, words)
        holder = one_row("creating-fabric-agents/SKILL.md", "**Who holds the copyright?**")
        for words in ("a new private agent (built for its owner or for a client) gets a `LICENSE` naming that holder in "
                      "its first commit",
                      "all rights reserved unless the owner gives other terms", "a public product keeps its own licence"):
            self.assertIn(words, holder, words)
        self.assertLess(grill.index("**Where does it run, for whom?**"), grill.index("**Does it run around the clock?**"))
        flat_grill = " ".join(grill.split())
        self.assertIn(data, flat_grill)  # 0.59.0 unit r1: the rows are asked in the grill, not elsewhere
        self.assertIn(holder, flat_grill)

    def test_the_skeleton_gives_the_data_a_home_and_a_licence(self):
        step_2 = " ".join(section("creating-fabric-agents", "Step 2: the project skeleton").split())
        for words in ("Its data has a home of its own from the same commit, the one the grill recorded: `<agent>-data` "
                      "(a folder beside the checkout, or a private repository of that name; a kit service: the kit's "
                      "folders; on a cloud host: a durable store)",
                      "the README names the data kind (U or O) and the uptime category (A or B)",
                      "its first commit carries a `LICENSE` naming the copyright holder the grill recorded"):
            self.assertIn(words, step_2, words)

    def test_every_release_runs_the_transfer_audit(self):
        step_5 = " ".join(section("creating-fabric-agents", "Step 5: check, report, and set the canary expectation").split())
        self.assertIn("Every release of the agent runs it too, in Git mode on the checkout and with `--every-file` on the "
                      "clean copy a transfer would carry (what Git would commit, as building-fabric-services' "
                      "`references/package.md` makes it), as the "
                      "transfer audit "
                      "(each exit 0, with the owner's list or its absence recorded) until the contract's export (CT-194) "
                      "replaces it", step_5)
        for skill in ("creating-fabric-agents", "adapting-projects-to-fabric"):
            reference = flat(skill + "/references/source-and-instance.md")
            self.assertIn("[The data home and its kind](#the-data-home-and-its-kind)", reference)
            for words in ("**The data has a home of its own from the first commit: `<agent>-data`.**",
                          "`<AGENT>_DATA_DIR` names it (its default is `../<agent>-data`, resolved against the checkout's root",
                          "a separate private repository named `<agent>-data`, never to the source's repository",
                          "never connects to the original's", "When in doubt, the kind is U.",
                          "**Every release runs the transfer audit.**",
                          "`check <clean-copy> --every-file` on a clean copy of what Git would commit",
                          "never the checkout itself, whose ignored configuration and dependency folders",
                          # 0.59.0 product r1: the holder's LICENSE meets the owner's list
                          "The one owner's file named this way is the `LICENSE` (a file, never a folder exception): its "
                          "copyright line names the holder, which is authorship and travels with the source", "no other file of the owner's is",
                          "its real-trace corpus and replay samples live in the data home",
                          # 0.59.0 seam r2: a host that does not keep its disk
                          "the data home is a durable store the same variable names",
                          "as building-fabric-services' `references/package.md` makes it"):
                self.assertIn(words, reference, (skill, words))

    def test_step_4_builds_an_uptime_a_agent_online(self):
        # 0.59.0 seam and product r4: the grill sends an A agent to the remote placement; step 4 hands it over there
        step_4 = " ".join(section("creating-fabric-agents", "Step 4: implement against the observables").split())
        self.assertIn("An uptime A agent is built with the same skill as an online service (its remote placement", step_4)

    def test_the_uptime_reference_and_its_checklist(self):
        where = flat("creating-fabric-agents/references/where-agents-run.md")
        for words in ("[Uptime: A or B](#uptime-a-or-b)", "## Uptime: A or B", "**A, around the clock.**",
                      "**B, local only.**", "never from its store",
                      "becomes A for that capability; record the change and move only that capability to the cloud",
                      "Which uptime category is it, A (a cloud host from the first release) or B (local only)?",
                      # 0.59.0 product r1: one answer per placement, and a durable data home on a cloud host
                      "an instance in the person's PassionCode cloud or an organization's cloud runs there",
                      "a paid agent stays in PassionCode's cloud",
                      "On a host with no Fabric hub it answers what reaches its own origin",
                      "a call Fabric admits needs a cloud hub",
                      "never the host's own folder, which a platform such as Heroku does not keep across a restart"):
            self.assertIn(words, where, words)

    def test_a_new_service_records_the_same_answers(self):
        row = one_row("building-fabric-services/SKILL.md", "Data and uptime")
        for words in ("kind U or O", "`<id>-data`", "uptime A or B", "`LICENSE` holder", "transfer audit per release",
                      "creating-fabric-agents"):
            self.assertIn(words, row, words)
        self.assertIn(row, " ".join(section("building-fabric-services", "Step 0: is it a service?").split()))

    def test_every_home_of_the_licence_rule_names_the_holders_licence(self):
        # 0.59.0 seam r1: the reference and the kit skill still said no file is required of a self-built agent
        for path in ("creating-fabric-agents/references/operator-channel-and-repository.md",
                     "adapting-projects-to-fabric/references/operator-channel-and-repository.md"):
            for words in ("except that an agent built new carries a `LICENSE` naming the copyright holder (all rights "
                          "reserved unless the owner gives other terms)",
                          # 0.59.0 product r2: the kit files copied in keep their own licence
                          "files the adapter copies in (the service kit, the dashboard kit) keep their own licence",
                          "`AGPL-3.0-only OR LicenseRef-PassionCode-Commercial` ([COMMERCIAL-LICENSE.md]"):
                self.assertIn(words, flat(path), (path, words))
        # 0.59.0 seam and product r2: an existing project keeps what it has, as the CHANGELOG's Upgrading says
        self.assertIn("an existing one keeps what it has", flat("adapting-projects-to-fabric/SKILL.md"))
        self.assertIn("the kit files the adapter copies in keep their own licence (AGPL-3.0-only OR "
                      "LicenseRef-PassionCode-Commercial)",
                      " ".join(section("creating-fabric-agents", "Step 2: the project skeleton").split()))
        # 0.59.0 seam and product r3: scoped to a service built new, as the CHANGELOG says
        self.assertIn("of these files one built new needs only a `LICENSE` naming its copyright holder (copied kit files keep theirs)",
                      flat("building-fabric-services/SKILL.md"))


if __name__ == "__main__":
    unittest.main()
