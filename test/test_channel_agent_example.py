"""FAA-197: the support-agent recipe's channel-agent declaration is in the form of the channel-agent standard's 13.6 at
its round 4 (2026-11-04): a required member is never null (`{"none": "not_yet", "until": ...}` or
`{"none": "not_used"}`), null only where nothing is decided, `recommendation` only with `answered_signal: "none"`, and
durations in ISO 8601. These checks are the test's own reading of the standard; `check_service.py` takes the contract's
schema once it is published."""
from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/recipes/support-agent/channel-agent.example.json"
KEY = "https://fabric.passioncode.ai/agent-contract/extensions/channel-agent/0.1"
DURATION = re.compile(r"P(?=\d|T\d)(\d+D)?(T(?=\d)(\d+H)?(\d+M)?(\d+S)?)?")
KINDS = {"telegram_dm", "telegram_group", "mail", "store_review", "public_comment", "team_chat", "account"}
REQUIRED = ("project", "side", "lead_agent", "adopted_at", "taxonomy", "tiers", "question_route", "gap_registry",
            "channels", "sources", "declined_sources", "handoff_queues", "evals", "tickets", "recorded_decisions")


def none_form(value) -> bool:
    return isinstance(value, dict) and (value == {"none": "not_used"} or (
        set(value) == {"none", "until"} and value["none"] == "not_yet"
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value["until"])) is not None))


def problems(declaration) -> list:
    found = []
    entry = declaration.get(KEY)
    if not isinstance(entry, dict) or entry.get("standard") != "channel-agent-standard/1":
        return ["no channel-agent-standard/1 declaration under the key"]
    for project in entry.get("projects") or [None]:
        if not isinstance(project, dict):
            found.append("a project is not an object")
            continue
        for member in REQUIRED:
            if project.get(member) is None:
                found.append("%s is missing or null" % member)
        for member in ("question_route", "gap_registry"):
            value = project.get(member)
            if isinstance(value, dict) and "none" in value and not none_form(value):
                found.append("%s: a none form other than not_yet with until, or not_used" % member)
        for code in (project.get("taxonomy") or {}).get("codes", []):
            if not re.fullmatch(r"[a-z0-9_.]{1,64}", str(code.get("code"))):
                found.append("taxonomy code %r" % code.get("code"))
        for tier in project.get("tiers") or []:
            if not re.fullmatch(r"[a-z_]+ >=? \d+", str(tier.get("rule"))) or tier.get("escalate") not in ("at_once", "ladder"):
                found.append("tier %r" % tier.get("code"))
        route = project.get("question_route")
        if isinstance(route, dict) and "none" not in route and not DURATION.fullmatch(str(route.get("expires"))):
            found.append("question_route.expires is not ISO 8601")
        for channel in project.get("channels") or []:
            if channel.get("kind") not in KINDS:
                found.append("channel kind %r" % channel.get("kind"))
            for member in ("final_limit", "first_reply_limit"):
                if not DURATION.fullmatch(str(channel.get(member))):
                    found.append("%s.%s is not ISO 8601" % (channel.get("id"), member))
            for member in ("quiet_window", "late_answer_window"):
                if channel.get(member) is not None and not DURATION.fullmatch(str(channel[member])):
                    found.append("%s.%s is not ISO 8601" % (channel.get("id"), member))
            for name in ("holding", "final"):
                text = (channel.get("texts") or {}).get(name)
                if text is None or (isinstance(text, dict) and "none" in text and not none_form(text)) or (
                        isinstance(text, dict) and "none" not in text
                        and (not text or any(not isinstance(v, str) or not v.strip() for v in text.values()))):
                    found.append("%s.texts.%s is null or empty" % (channel.get("id"), name))
        for source in project.get("sources") or []:
            for member in ("cadence", "max_age"):
                if not DURATION.fullmatch(str(source.get(member))):
                    found.append("source %s.%s is not ISO 8601" % (source.get("id"), member))
        for queue in project.get("handoff_queues") or []:
            if not DURATION.fullmatch(str(queue.get("limit"))):
                found.append("queue %s.limit is not ISO 8601" % queue.get("id"))
            if (queue.get("answered_signal") == "none") != ("recommendation" in queue):
                found.append("queue %s: recommendation only with answered_signal none" % queue.get("id"))
        evals = project.get("evals") or {}
        if evals.get("spend_record") is None and (evals.get("judge_budget_usd") or evals.get("replay_budget_usd")):
            found.append("a budget above 0 without its spend record")
        tickets = project.get("tickets") or {}
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*/[a-z]+/[A-Z][A-Z0-9_]{0,63}", str(tickets.get("token_slot"))):
            found.append("tickets.token_slot is not <project>/<env>/<NAME>")
        if tickets.get("pd_check") is None or (isinstance(tickets["pd_check"], dict) and not none_form(tickets["pd_check"])):
            found.append("tickets.pd_check is null or a bad none form")
    return found


class Example(unittest.TestCase):
    def setUp(self):
        self.declaration = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_the_example_is_in_the_standards_form(self):
        self.assertEqual(problems(self.declaration), [])

    def test_the_example_uses_neutral_names(self):
        text = EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("example", text)
        self.assertNotIn("—", text)
        self.assertNotRegex(text, r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", "no address")

    def test_the_example_config_measures_the_age_the_declaration_names(self):
        config = json.loads((EXAMPLE.parent / "config.example.json").read_text(encoding="utf-8"))
        source = next(s for s in self.declaration[KEY]["projects"][0]["sources"] if s["id"] == "knowledge")
        hours = re.fullmatch(r"PT(\d+)H", source["max_age"])
        self.assertIsNotNone(hours, source["max_age"])
        self.assertEqual(config["knowledgeMaxAgeSeconds"], int(hours.group(1)) * 3600)

    def test_the_checks_catch_each_rule(self):
        project = lambda d: d[KEY]["projects"][0]  # noqa: E731
        cases = [
            ("a null required member", lambda d: project(d).update(gap_registry=None)),
            ("a not_yet without until", lambda d: project(d).update(gap_registry={"none": "not_yet"})),
            ("a null text", lambda d: project(d)["channels"][0]["texts"].update(final=None)),
            ("a null pd_check", lambda d: project(d)["tickets"].update(pd_check=None)),
            ("a recommendation with a signal", lambda d: project(d)["handoff_queues"][0].update(answered_signal="reply-in-thread")),
            ("no recommendation with none", lambda d: project(d)["handoff_queues"][0].pop("recommendation")),
            ("a duration in hours", lambda d: project(d)["channels"][0].update(final_limit="168h")),
            ("a bad kind", lambda d: project(d)["channels"][0].update(kind="sms")),
            ("a bad tier rule", lambda d: project(d)["tiers"][0].update(rule="open_orders is big")),
            ("a budget without a record", lambda d: project(d)["evals"].update(judge_budget_usd=5)),
            ("a bad slot", lambda d: project(d)["tickets"].update(token_slot="prod/token")),
        ]
        for name, change in cases:
            with self.subTest(name):
                broken = copy.deepcopy(self.declaration)
                change(broken)
                self.assertNotEqual(problems(broken), [], name)


if __name__ == "__main__":
    unittest.main()
