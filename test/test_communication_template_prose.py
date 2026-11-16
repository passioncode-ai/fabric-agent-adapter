"""The Fabric communication agent template (FAA-262, 0.75.0): the scenario that grades a build from it, and each phrase
of the template that scenario's expected lines rely on. A rewording of the template that drops one fails here."""
import json
import re
import unittest

from test_action_and_dashboard_prose import ROOT, flat

TEMPLATE = "creating-fabric-agents/references/communication-agent-template.md"
# FAA-265 moved the prompt into the template folder; the reader's page keeps how to use it.
FOLDER_TEMPLATE = "creating-fabric-agents/templates/communication-agent/TEMPLATE.md"


def template_text():
    return flat(TEMPLATE) + " " + flat(FOLDER_TEMPLATE)
SCENARIO = "a-channel-agent-starts-from-the-communication-template"
# Each expected line of the scenario, and the template phrases it rests on (whitespace normalised).
RESTS_ON = {
    0: ["Fill in the brief (section 0 of the prompt)", "a question for the owner before the build"],
    1: ["Batch a person's burst into one turn", "Claim the ticket atomically with an idempotency key before any model call"],
    2: ["Triage (the planning model, thinking low, no knowledge in the prompt) of the whole batch",
        "Any ask, even a vague one", "a complaint about the product"],
    3: ["Analyse, plan and draft in ONE call", "injection {suspected, what}", "scope (the product or off-topic)", "evidence (the knowledge ids it used)",
        "a separate cheap drafter after the plan scored lower at the same cost, so there is none"],
    4: ["Final pass (the planning model, thinking low) only when an action returned information the reply must use"],
    5: ["then a checker of another vendor than the model that drafted this turn", "never the plan's own `evidence`",
        "whose plan has no injection verdict, or whose call failed, is held"],
    6: ["every other channel hands a lead to its queue", "a sales agent of its own owns the CRM and the lead",
        "Prices, discounts and terms only from the knowledge or the CRM"],
    7: ["default USD 100 a month for a new agent", "the code stops a little under the key's limit"],
}


def scenario(name=SCENARIO):
    data = json.loads((ROOT / "test/evals/creating-fabric-agents/scenarios.json").read_text(encoding="utf-8"))
    return next(s for s in data["scenarios"] if s["id"] == name)


# FAA-264: the scenario that grades the routes, their outcomes and the cheap safety rules, and the phrases it rests on.
ROUTES_SCENARIO = "the-communication-template-gives-each-route-its-outcome-and-its-guards"
ROUTES_RESTS_ON = {
    0: ["The route a turn took gives its one A1 outcome", "2 covered partly: the covered part answered, the rest named",
        "has no entry of its own in A1's list: the template records it as shown"],
    1: ["the operator's link-code message on the answering bot", "counted in `not_a_ticket` volume, CA-8",
        "the message quoted and its sender id, kept apart from the logs rule 5 bounds"],
    2: ["only where the channel's `clarifying_question` is true",
        "`replies_enabled: false` sends nothing: every ticket goes on arrival to its handoff queue"],
    3: ["Pre-send gates, one list in this order", "the route decides the skip, never the draft's markers",
        "on a skipped route, no link, handle, mail, phone number or number"],
    4: ["Under it a daily guard", "the agent refuses to go live", "writes a commitments-ledger row"],
    5: ["each with its expected route and A1 outcome"],
}
A1_OUTCOMES = ("answered", "general guidance", "not covered", "handed off", "small talk", "limit", "error")


def section_text():
    """The prompt: the fenced block of the folder's TEMPLATE.md."""
    text = (ROOT / "plugins/fabric-agent-adapter/skills" / FOLDER_TEMPLATE).read_text(encoding="utf-8")
    return text.split("```text\n", 1)[1].rsplit("```", 1)[0]


def section(number):
    prompt = section_text()
    start = prompt.index("\n## %d. " % number)
    end = prompt.find("\n## %d. " % (number + 1), start)
    return prompt[start:end if end > 0 else len(prompt)]


def batches():
    """Section 9's adversarial batches, one string per item, continuation lines joined."""
    listed = section(9).split("A1 outcome (section 8's table), all passing:\n", 1)[1]
    listed = listed.split("\n- ", 1)[0]
    items = []
    for line in listed.splitlines():
        if line.startswith("  - "):
            items.append(line[4:].strip())
        elif line.strip():
            items[-1] += " " + line.strip()
    return items


def newest_changelog_entry():
    notes = (ROOT / "plugins/fabric-agent-adapter/skills" / FOLDER_TEMPLATE).parent.joinpath("CHANGELOG.md").read_text(
        encoding="utf-8")
    return notes.split("\n## ", 2)[1]


class TheTemplateCarriesWhatItsScenarioGrades(unittest.TestCase):
    def test_every_expected_line_has_its_phrases(self):
        expected = scenario()["expected"]
        self.assertEqual(len(expected), len(RESTS_ON))
        body = template_text()
        for i, phrases in RESTS_ON.items():
            for phrase in phrases:
                with self.subTest(line=i, phrase=phrase):
                    self.assertIn(" ".join(phrase.split()), body)

    def test_the_routes_scenario_rests_on_the_template(self):
        expected = scenario(ROUTES_SCENARIO)["expected"]
        self.assertEqual(len(expected), len(ROUTES_RESTS_ON))
        body = " ".join(section_text().split())
        for i, phrases in ROUTES_RESTS_ON.items():
            for phrase in phrases:
                with self.subTest(line=i, phrase=phrase):
                    self.assertIn(" ".join(phrase.split()), body)

    def test_every_event_kind_it_names_passes_the_kit_writers_kind_rule(self):
        """FAA-264 item 29: the kinds are read from the template's own events bullet, so a kind added there is held to
        the kit's rule and to the manifest's list without a second copy here."""
        import importlib
        import sys
        sys.path.insert(0, str(ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"))
        events = importlib.import_module("fabric_events")
        bullet = flat(FOLDER_TEMPLATE).split("- Events out, on /fabric/v1/events:", 1)[1].split(" - ", 1)[0]
        kinds = set(re.findall(r"\b[a-z]+(?:\.[a-z_]+)+\b", bullet)) - {"support.quality_daily's"}
        self.assertIn("support.quality_daily", kinds)
        manifest = json.loads((ROOT / "plugins/fabric-agent-adapter/skills" / FOLDER_TEMPLATE).parent.joinpath(
            "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(kinds, set(manifest["events"]))
        for kind in sorted(kinds):
            with self.subTest(kind=kind):
                events.make_event("1", "2026-11-07T00:00:00Z", kind, "info", "x")
        self.assertNotIn("handedOff", template_text())

    def test_the_recipe_readme_skips_check_reply_by_the_templates_routes(self):
        readme = flat("building-fabric-services/recipes/support-agent/README.md")
        for phrase in ("an off-topic plan", "a plan whose only actions are ask_clarification or handoff",
                       "a triage reply", "never the draft's markers"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readme)
                self.assertIn(phrase, template_text())
        self.assertNotIn("no fact to cite", readme)
        self.assertNotIn("no fact to cite", template_text())

    def test_the_declaration_rules_a_builder_follows_hold_under_the_probe(self):
        """0.75.0 readings, round 10: a real answered signal drops the queue's recommendation (FAC-SEM-164), and the
        operator's in-chat decision is carried out once, never held again (CA-8, the standard's 4.10)."""
        body = template_text()
        for phrase in ("replaces with a real signal and then drops its `recommendation`",
                       "carried out once within CA-8's bounds and never held again"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)

    def test_the_templates_changelog_counts_the_adversarial_batches_it_lists(self):
        """FAA-264: the batches are counted by the template's own changelog entry for its version, not by the
        adapter's 0.75.0 line, which names the count of that release."""
        said = re.search(r"(\d+) adversarial batches", " ".join(newest_changelog_entry().split()))
        self.assertIsNotNone(said)
        self.assertEqual(int(said.group(1)), len(batches()))

    def test_every_adversarial_batch_names_its_route_and_an_a1_outcome(self):
        """FAA-264 item 51: every batch carries its expected route and outcome, the outcome from A1's fixed list (or
        none, for a message that is no person's turn)."""
        found = batches()
        self.assertGreaterEqual(len(found), 20)
        for item in found:
            with self.subTest(batch=item[:60]):
                match = re.search(r"Route: (.+?)\. Outcome: (.+?)\.?$", item)
                self.assertIsNotNone(match, item)
                self.assertTrue(match.group(2).startswith(A1_OUTCOMES + ("none",)), match.group(2))

    def test_the_route_table_gives_each_route_one_a1_outcome(self):
        """FAA-264 items 9 and 49: section 8's table maps each route to one outcome of A1's list; general guidance has
        a route, and the rows A1 has no entry for are marked and sent to the standard's owner."""
        rows = [line for line in section(8).splitlines() if re.match(r"\s{4}[0-9].* \| ", line)]
        self.assertGreaterEqual(len(rows), 12)
        outcomes = set()
        for row in rows:
            outcome = row.rsplit(" | ", 1)[1].strip()
            with self.subTest(row=row.strip()[:50]):
                self.assertTrue(outcome.startswith(A1_OUTCOMES + ("none",)), outcome)
            outcomes.update(o for o in A1_OUTCOMES if outcome.startswith(o))
        self.assertEqual(outcomes, set(A1_OUTCOMES))
        self.assertTrue(any("covered partly" in row and row.endswith("general guidance") for row in rows))
        self.assertIn("thread f0823e73", " ".join(section(8).split()))

    def test_the_prompt_carries_no_double_hyphen_and_steps_keep_their_indent(self):
        """FAA-264 item 52: rule 7 forbids `--` in text a person reads, the diagram included, and every step's
        continuation line is indented three spaces like its neighbours."""
        prompt = section_text()
        self.assertNotIn("--", prompt.replace("(`--`, a spaced hyphen", ""))
        steps = "0. " + section(3).split("\n0. ", 1)[1]
        for line in steps.splitlines():
            if line.strip() and not re.match(r"[0-9]\. ", line):
                with self.subTest(line=line[:50]):
                    self.assertTrue(line.startswith("   "), line)

    def test_the_cheap_safety_rules_are_written(self):
        """FAA-264 items 13, 21, 25, 27, 38 and the scenario that grades them."""
        body = " ".join(section_text().split())
        for phrase in ("counted in `not_a_ticket` volume", "only where the channel's `clarifying_question` is true",
                       "`replies_enabled: false` sends nothing: every ticket goes on arrival to its handoff queue",
                       "Under it a daily guard", "the agent refuses to go live",
                       "writes a commitments-ledger row with its owner and the channel's `final_limit` as its due date",
                       "the message quoted and its sender id"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)


if __name__ == "__main__":
    unittest.main()
