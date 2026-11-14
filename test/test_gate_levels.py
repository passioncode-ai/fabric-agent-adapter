"""FAA-334: the kit's gate reads levels and a place's profile by itself (DEC-0162 LV-5, LV-7; DEC-0166 AU-3).

action_gate (both twins) answers every action case of the contract's levels.json and profile.json as actionDecision
does, and McpToolServer, given a service's authority configuration, decides a level holder's word on a tool call
without the service calling the gate itself. The Node twin's gate runs the same cases in fabric-levels.test.mjs."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from test_fabric_service import load

fd = load("fabric_delegation")
fa = load("fabric_actions")
fi = load("fabric_interop")
fr = load("fabric_interop_rules")
ft = load("fabric_time")
AUTHORITY_EXTENSION_KEY, authority_view = fa.AUTHORITY_EXTENSION_KEY, fa.authority_view
InteropError, McpToolServer = fi.InteropError, fi.McpToolServer
action_gate, authority_config_problem, authority_gate_inputs = fr.action_gate, fr.authority_config_problem, fr.authority_gate_inputs
parse_rfc3339_ms = ft.parse_rfc3339_ms

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "test/fixtures/contract"
#: action_decision's input names, as action_gate takes them.
GATE_NAMES = {"target": "target", "approval": "approval", "actionDigest": "action_digest", "humanStepUrl": "human_step_url",
              "now": "now", "self": "self_id", "effect": "effect", "callerAgent": "caller_agent", "spendUsd": "spend_usd",
              "project": "project", "mandateCapability": "mandate_capability", "levels": "levels",
              "actionLevel": "action_level", "context": "context", "tokenMem": "token_mem", "tokenProf": "token_prof",
              "standing": "standing", "elicited": "elicited", "tier": "tier", "caller": "caller", "action": "action"}


def action_cases():
    for name in ("levels-vectors.json", "standing-vectors.json"):
        for case in json.loads((FIXTURES / name).read_text(encoding="utf-8"))["actions"]:
            yield name, case


def gate_answers_as(gated, expected):
    """action_gate's answer is actionDecision's: its record, or DL-19's refusal of it with the fault beside it."""
    if expected.get("ok") is True:
        return gated.get("ok") is True and gated["record"] == expected["recordAs"]
    return gated.get("ok") is False and gated["refusal"] == fd.refusal_from_action(expected) and gated.get("fault") == expected.get("fault")


class ActionGateVectors(unittest.TestCase):
    def test_every_level_and_profile_case_passes_through_the_gate(self):
        seen = 0
        for file, case in action_cases():
            inputs = case["input"]
            meta = {key: inputs[key] for key in ("decision", "mandate") if key in inputs}
            unknown = sorted(set(inputs) - set(GATE_NAMES) - {"decision", "mandate"})
            self.assertEqual(unknown, [], "%s: %s takes inputs action_gate cannot pass" % (file, case["name"]))
            kwargs = {"tier": None, "caller": None, **{GATE_NAMES[k]: v for k, v in inputs.items() if k in GATE_NAMES}}
            with self.subTest(file=file, case=case["name"]):
                self.assertTrue(gate_answers_as(action_gate(meta=meta, **kwargs), case["expected"]))
            seen += 1
        self.assertEqual(seen, 113)  # 64 level cases and 49 profile cases at the pin


def server_case(case):
    """A level vector a tool call can carry as it is: the decision in _meta, no approval, elicitation or mandate, and a
    configuration the server accepts (a case of the service's own fault is the configuration's, refused at start)."""
    inputs = case["input"]
    if any(k in inputs for k in ("approval", "elicited", "mandate", "self")) or "fault" in case["expected"]:
        return False
    return inputs["action"]["gate"] == "relayed" and isinstance(inputs.get("levels"), dict) and inputs["levels"]


class McpToolServerReadsLevels(unittest.TestCase):
    def serve(self, inputs, authority=None):
        clock = parse_rfc3339_ms(inputs["now"]) / 1000
        claims = {"mem": inputs["tokenMem"]} if "tokenMem" in inputs else None
        verdict = {"ok": True, "tier": inputs["tier"], "principal": "operator", "caller": inputs["caller"],
                   "chain": [], "claims": claims, "kid": None}
        authority = authority if authority is not None else {"levels": inputs["levels"], **(
            {"actionLevels": {inputs["action"]["id"]: inputs["actionLevel"]}} if "actionLevel" in inputs else {})}
        server = McpToolServer("example-agent", "0.1.0", clock=lambda: clock, authority=authority,
                               authorize=lambda tool, headers, tier=None: verdict)
        seen = []
        server.add_tool({"name": inputs["action"]["tool"], "inputSchema": {"type": "object"}},
                        lambda arguments, context: seen.append(context.record) or {"ok": True},
                        action=inputs["action"], effect=inputs.get("effect"), project=inputs.get("project"),
                        context=inputs.get("context"))
        meta = {"decision": inputs["decision"]} if "decision" in inputs else {}
        answer = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": inputs["action"]["tool"], "arguments": {}, "_meta": meta}},
                               tier=inputs["tier"])
        return answer["result"], seen

    @staticmethod
    def without_digest(error):
        data = {k: v for k, v in (error.get("data") or {}).items() if k != "actionDigest"}
        return {**{k: v for k, v in error.items() if k not in ("data", "message")}, "data": data}

    def test_a_level_holders_word_is_decided_on_a_tool_call(self):
        served = 0
        for _, case in action_cases():
            if not server_case(case):
                continue
            inputs, expected = case["input"], case["expected"]
            with self.subTest(case=case["name"]):
                result, seen = self.serve(inputs)
                if expected.get("ok") is True:
                    self.assertEqual(seen, [expected["recordAs"]])
                else:
                    self.assertEqual(seen, [])
                    # The server binds its own digest of {tool, arguments}; the vector's is a fixed stand-in.
                    error, want = (self.without_digest(r["structuredContent"]["error"]) for r in (
                        result, fd.refusal_tool_result(fd.refusal_from_action(expected))))
                    self.assertEqual(error, want)
            served += 1
        self.assertGreaterEqual(served, 40)

    def test_without_authority_a_level_decision_is_as_if_absent(self):
        case = next(c for _, c in action_cases() if c["name"] == "an administrator decides from T0")
        inputs = dict(case["input"])
        server = McpToolServer("example-agent", "0.1.0", identify=lambda headers, tier: inputs["caller"],
                               clock=lambda: parse_rfc3339_ms(inputs["now"]) / 1000)
        server.add_tool({"name": inputs["action"]["tool"], "inputSchema": {"type": "object"}}, lambda a, c: {"ok": True},
                        action=inputs["action"])
        answer = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": inputs["action"]["tool"], "arguments": {}, "_meta": {"decision": inputs["decision"]}}}, tier="T0")
        self.assertEqual(answer["result"]["structuredContent"]["error"]["code"], "operator-decision-required")

    def test_the_configuration_is_checked_at_start(self):
        case = next(c for _, c in action_cases() if c["name"] == "an administrator decides from T0")
        levels = case["input"]["levels"]
        for bad in ({}, {"levels": {}}, {"levels": [levels]}, {"actionLevels": {"x": "Owner"}}, {"standing": False},
                    {"levels": levels, "other": 1}):
            with self.subTest(authority=bad):
                self.assertIsNotNone(authority_config_problem(bad))
                with self.assertRaises(InteropError):
                    McpToolServer("example-agent", "0.1.0", authority=bad)
        self.assertIsNone(authority_config_problem({"levels": levels, "actionLevels": {"approve-reply": "admin"}, "standing": True}))

    def test_a_relayed_action_names_its_effect_on_a_server_reading_levels(self):
        case = next(c for _, c in action_cases() if c["name"] == "an administrator decides from T0")
        server = McpToolServer("example-agent", "0.1.0", authority={"levels": case["input"]["levels"]})
        with self.assertRaises(InteropError):
            server.add_tool({"name": "reviews.approve", "inputSchema": {"type": "object"}}, lambda a, c: {},
                            action=case["input"]["action"])
        with self.assertRaises(InteropError):
            server.add_tool({"name": "reviews.approve", "inputSchema": {"type": "object"}}, lambda a, c: {},
                            action=case["input"]["action"], effect="reply", context=7)

    def test_the_declaration_names_each_organization_without_its_key_set(self):
        case = next(c for _, c in action_cases() if c["name"] == "an administrator decides from T0")
        levels = case["input"]["levels"]
        server = McpToolServer("example-agent", "0.1.0", authority={"levels": levels, "actionLevels": {"approve-reply": "admin"},
                                                                    "standing": True})
        declared = server.authority_extension()
        self.assertEqual(declared["levels"], [{"org": org, "audience": entry["audience"]} for org, entry in levels.items()])
        self.assertNotIn("keySet", json.dumps(declared))
        view = authority_view({"extensions": {AUTHORITY_EXTENSION_KEY: declared}})
        self.assertTrue(view["valid"], view)
        self.assertIsNone(McpToolServer("example-agent", "0.1.0").authority_extension())

    def test_mem_and_prof_come_from_the_verified_claims_only(self):
        self.assertEqual(authority_gate_inputs({"standing": True}, "a", "personal", {"mem": "sha256:" + "1" * 64, "prof": "sha256:" + "2" * 64}),
                         {"standing": True, "context": "personal", "token_mem": "sha256:" + "1" * 64, "token_prof": "sha256:" + "2" * 64})
        self.assertEqual(authority_gate_inputs({"standing": True}, "a", 7, None), {"standing": True})
        self.assertEqual(authority_gate_inputs(None, "a", "personal", {"mem": "x"}), {})


if __name__ == "__main__":
    unittest.main()
