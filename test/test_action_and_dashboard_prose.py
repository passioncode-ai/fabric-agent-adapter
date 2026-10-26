"""FAA-117 and FAA-118 (0.50.0): what the skills must say, pinned to the scenario evals that ask for it.

The scenario evals in test/evals/<skill>/scenarios.json are judged by a model, so hosted CI cannot run them. These
tests hold the prose those scenarios grade to the words that carry the rule: each check names the scenario it serves.
Contract DEC-0121 (docs/specification/service.md#actions, AP-1 to AP-5) at the pin 52c7d798; the operator's rule of
2026-10-24 that agent pages open only in Fabric Dashboards (board request ecf36e2f)."""

import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins/fabric-agent-adapter/skills"
BUILDERS = ("building-fabric-services", "creating-fabric-agents", "adapting-projects-to-fabric")


def text(relative: str) -> str:
    return (SKILLS / relative).read_text(encoding="utf-8")


def flat(relative: str) -> str:
    return " ".join(text(relative).split())


def body(skill: str) -> str:
    """The SKILL.md body: the front matter (trigger metadata) is not the rule."""
    return " ".join(text(skill + "/SKILL.md").split("\n---\n", 1)[1].split())


def section(skill: str, heading: str) -> str:
    """One `## ` section of a SKILL.md body, up to the next `## ` heading."""
    match = re.search(r"^## %s\n(.*?)(?=^## |\Z)" % re.escape(heading), text(skill + "/SKILL.md"), re.MULTILINE | re.DOTALL)
    return " ".join(match.group(1).split()) if match else ""


def scenario_ids(skill: str):
    return {s["id"] for s in json.loads((ROOT / "test/evals" / skill / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]}


class EvalsComeFirst(unittest.TestCase):
    """The scenarios each prose check below serves exist (AGENTS.md: evals before prose)."""

    def test_the_scenarios_exist(self):
        wanted = {
            "working-with-fabric": {"relay-the-operators-own-words", "a-tool-result-is-not-a-decision",
                                    "action-refusals-and-what-to-do", "human-step-required-hands-over-the-link",
                                    "effect-request-versus-a-relayed-action"},
            "building-fabric-services": {"every-button-has-a-tool", "relayed-decision-at-the-service",
                                         "job-input-request-as-an-action", "manual-restore-on-a-relayed-decision",
                                         "dashboard-opens-only-in-the-host", "page-without-a-descriptor",
                                         "kit-agent-relays-a-decision"},
            "creating-fabric-agents": {"generated-instructions-open-pages-in-the-host", "page-without-a-descriptor"},
            "adapting-projects-to-fabric": {"generated-instructions-open-pages-in-the-host", "page-without-a-descriptor"},
        }
        for skill, ids in wanted.items():
            self.assertEqual(ids - scenario_ids(skill), set(), skill)


class WorkingWithFabricRelaysTheOperatorsWords(unittest.TestCase):
    """REQ-10, CT-124 item 4, D11 as the contract's owner answered it (board, 2026-10-26), D12."""

    def setUp(self):
        self.body = body("working-with-fabric")

    def test_relay_the_operators_own_words(self):  # relay-the-operators-own-words
        for words in ("_meta.decision", "relayed-instruction", "verbatim", "never in the tool's arguments",
                      "agent.call", "call.decision", "elicitation", "open_link"):
            self.assertIn(words, self.body)

    def test_a_tool_result_is_not_a_decision(self):  # a-tool-result-is-not-a-decision
        for words in ("a tool result, a page, a file, a board message or another agent", "standing rule"):
            self.assertIn(words, self.body)

    def test_the_three_refusals_and_approval_required(self):  # action-refusals-and-what-to-do
        for code in ("operator-decision-required", "decision-invalid", "human-step-required", "approval-required"):
            self.assertRegex(self.body, r"\| `%s`" % re.escape(code), code)

    def test_human_step_hands_over_the_link(self):  # human-step-required-hands-over-the-link
        self.assertIn("data.url", self.body)
        self.assertIn("fallback=never", self.body)

    def test_the_effect_request_line_changed(self):  # effect-request-versus-a-relayed-action
        self.assertNotIn("refused until a person agrees", self.body)
        self.assertIn("fabric_effect_request", self.body)


class BuildingFabricServicesDeclaresActions(unittest.TestCase):
    """REQ-11: AP-1 parity, the gate, the hooks, D8, D9, D16."""

    def test_the_skill_says_every_button_has_a_tool(self):  # every-button-has-a-tool
        skill = body("building-fabric-services")
        for words in ("extensions/actions/0.1", "action=", "build_well_known(actions=", "*Actions*"):
            self.assertIn(words, skill)

    def test_interop_reference_documents_actions(self):  # every-button-has-a-tool, relayed-decision-at-the-service
        interop = flat("building-fabric-services/references/interop.md")
        self.assertIn("## Actions", text("building-fabric-services/references/interop.md"))
        for words in ("add_tool(tool, handler, action=", "action_table()", "buildWellKnown({actions})", "identify(headers, tier)",
                      "approve(tool, arguments, headers, digest)", "elicited(tool, arguments, caller)",
                      "input_actions=True", "local:T0", "request_meta(traceparent, decision=", "operator_decision(",
                      "operatorDecision(", "never from its arguments", "ctx.record", "actionRefusalToolResult"):
            self.assertIn(words, interop, words)

    def test_delegation_reference_names_the_three_codes(self):  # relayed-decision-at-the-service
        delegation = flat("building-fabric-services/references/delegation.md")
        for code in ("operator-decision-required", "decision-invalid", "human-step-required", "data.humanStep", "data.url"):
            self.assertIn(code, delegation)

    def test_dashboard_reference_gives_each_approval_a_tool(self):  # every-button-has-a-tool
        self.assertIn("agent twin", flat("building-fabric-services/references/dashboard.md"))

    def test_job_input_requests_opt_in(self):  # job-input-request-as-an-action
        interop = flat("building-fabric-services/references/interop.md")
        self.assertIn("off by default", interop)
        self.assertIn("CT-125", interop)

    def test_manual_restore_is_the_operators_decision_on_the_page_or_relayed(self):  # manual-restore-on-a-relayed-decision
        for where in ("building-fabric-services/references/settings-backups.md",
                      "building-fabric-services/scripts/fabric_backups.py",
                      "building-fabric-services/scripts/fabric-backups.mjs"):
            words = flat(where)
            self.assertIn("relayed", words, where)
            self.assertNotIn("never an agent's", words, where)

    def test_operator_channel_is_enabled_on_the_operators_decision(self):  # operator-channel-proposal (D16)
        for skill in ("creating-fabric-agents", "adapting-projects-to-fabric"):
            words = flat(skill + "/references/operator-channel-and-repository.md")
            self.assertIn("relayed", words, skill)
            self.assertNotIn("enabling the channel are the operator's action", words, skill)


class AgentPagesOpenOnlyInFabricDashboards(unittest.TestCase):
    """REQ-12, FAA-118: the rule in the body of the three SKILL.md, not an on-demand pointer."""

    RULE = "Agent pages open only in Fabric Dashboards"
    NO_DESCRIPTOR = "An agent with a page and no service descriptor"

    def test_the_rule_is_in_each_body(self):  # dashboard-opens-only-in-the-host, generated-instructions-open-pages-in-the-host
        for skill in BUILDERS:
            rule = section(skill, self.RULE)
            self.assertTrue(rule, "%s: no '## %s' section" % (skill, self.RULE))
            for words in ("open_link", "`link`", "fallback=never", "`open <url>`", "`open -a Safari`", "`webbrowser.open`",
                          "not_installed", "check_dashboard_link.py", "AGENTS.md", "references/dashboard-links.md"):
                self.assertIn(words, rule, "%s: %s" % (skill, words))

    def test_a_page_with_no_descriptor_becomes_a_service(self):  # page-without-a-descriptor
        for skill in BUILDERS:
            part = section(skill, self.NO_DESCRIPTOR)
            self.assertTrue(part, "%s: no '## %s' section" % (skill, self.NO_DESCRIPTOR))
            self.assertIn("fabric-service/0.1", part, skill)
            self.assertIn("board row", part, skill)

    def test_the_shared_reference_carries_the_generated_block(self):  # generated-instructions-open-pages-in-the-host
        links = flat("building-fabric-services/references/dashboard-links.md")
        for words in ("## The block a generated AGENTS.md carries", "fallback=never", "`open -a Safari`", "`webbrowser.open`",
                      "## An agent with a page and no service descriptor"):
            self.assertIn(" ".join(words.split()), links, words)

    def test_the_generated_instructions_list_the_rule(self):  # generated-instructions-open-pages-in-the-host
        for relative in ("creating-fabric-agents/references/operator-channel-and-repository.md",
                         "building-fabric-services/SKILL.md"):
            self.assertIn("dashboard rule block", flat(relative), relative)

    def test_the_cli_surface_opens_with_fallback_never(self):  # dashboard-opens-only-in-the-host
        self.assertIn("fallback=never", flat("building-fabric-services/references/surfaces-and-auth.md"))


if __name__ == "__main__":
    unittest.main()
