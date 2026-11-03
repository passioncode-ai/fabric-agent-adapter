"""FAA-135: the board responder reads the operator's mandate from a request of his own Project (contract
project-comms.md, DEC-0125 MD-3). Reading is opt-in (`agent_id` and `mandate_from`) and fail-closed."""

from __future__ import annotations

import importlib
import json
import unittest

from test_fabric_board import Conversation, fb  # noqa: F401 - the shared conversation against the fake hub
from fake_fabric_hub import OTHER_PROJECT

fm = importlib.import_module("fabric_mandate")  # on the path test_fabric_board set

WALL = 1_793_700_000.0  # the responder's wall clock, in seconds
AT = fm.format_rfc3339(WALL * 1000)
WORDS = "render the teaser for the launch"


def mandate(callee: str = "example-agent", scope=None) -> dict:
    lead = fm.operator_mandate("task-teaser", WORDS, scope or {"capabilities": ["video.render"], "effects": ["draft"]},
                               "lead-agent", at=AT)
    return fm.hand_on(lead, callee, AT)


def body(*blocks: str) -> str:
    return "Render the teaser.\n\n" + "\n\n".join("```json\n%s\n```" % b for b in blocks) + "\n"


class BoardMandateTests(Conversation):
    def setUp(self) -> None:
        super().setUp()
        self.seen = []

        def outcome(request, ctx):
            self.seen.append((ctx.mandate, ctx.mandate_covers({"capability": "video.render", "effect": "draft"}),
                              ctx.mandate_covers({"capability": "video.cut", "effect": "draft"})))
            return {"state": "completed", "summary": "Rendered."}

        self.outcome = outcome

    def run_one(self, text: str, provenance: str = "trusted", **kw):
        self.board.queue("video.render", text=text, provenance=provenance)
        args = dict(agent_id="example-agent", mandate_from={OTHER_PROJECT}, wall=lambda: WALL)
        args.update(kw)
        self.responder(**args).step()
        self.assertEqual(len(self.seen), 1, "the handler ran once")
        return self.seen[0]

    def test_a_trusted_request_from_a_declared_project_carries_its_mandate(self):
        m = mandate()
        got, covered, outside = self.run_one(body(json.dumps(m)))
        self.assertEqual(got, m)
        self.assertEqual(covered, {"ok": True, "recordAs": {"by": "operator", "via": "mandate", "task": "task-teaser",
                                                            "chain": ["lead-agent", "example-agent"]}})
        self.assertFalse(outside["ok"])
        self.assertEqual(outside["data"]["detail"], "outside-mandate: capability")

    def test_the_personal_board_takes_any_trusted_sender(self):
        got, covered, _ = self.run_one(body(json.dumps(mandate())), mandate_from="personal-board")
        self.assertTrue(covered["ok"])

    def test_no_mandate_without_the_opt_in_or_from_another_sender(self):
        text = body(json.dumps(mandate()))
        for kw in ({"mandate_from": None}, {"agent_id": None}, {"mandate_from": {"another-project"}}, {"provenance": "unverified"}):
            with self.subTest(kw=kw):
                self.seen.clear()
                self.tearDown()
                self.setUp()
                provenance = kw.pop("provenance", "trusted")
                got, covered, outside = self.run_one(text, provenance=provenance, **kw)
                self.assertIsNone(got)
                self.assertIsNone(covered, "no mandate travelled: the handler asks the operator as before")
                self.assertIsNone(outside)

    def test_two_blocks_or_an_unreadable_one_is_no_mandate_named_by_its_code(self):
        m = json.dumps(mandate())
        cases = {"two": (body(m, m), "mandate-blocks"),
                 "unreadable": (body('{"kind": "mandate/1", "task": '), "mandate-unreadable"),
                 "nan": (body(m[:-1] + ', "x": NaN}'), "mandate-unreadable")}
        for name, (text, code) in cases.items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                got, covered, _ = self.run_one(text)
                self.assertIsNone(got)
                self.assertIsNone(covered)
                said = [e for e in self.events if e[0] == "board.request.mandate-unread"]
                self.assertEqual(len(said), 1)
                self.assertIn(code, said[0][2])

    def test_a_json_block_that_is_no_mandate_is_ignored(self):
        got, covered, _ = self.run_one(body('{"frames": 24}'))
        self.assertIsNone(got)
        self.assertEqual([e for e in self.events if e[0] == "board.request.mandate-unread"], [])

    def test_a_chain_that_does_not_end_here_is_not_for_this_call(self):
        got, covered, _ = self.run_one(body(json.dumps(mandate(callee="other-agent"))))
        self.assertEqual(got["chain"][-1]["agent"], "other-agent")
        self.assertFalse(covered["ok"])
        self.assertEqual(covered["data"]["detail"], "mandate-not-for-this-call")

    def test_an_expired_mandate_is_refused_by_the_wall_clock(self):
        got, covered, _ = self.run_one(body(json.dumps(mandate())), wall=lambda: WALL + 2 * 24 * 3600)
        self.assertEqual(covered["data"]["detail"], "mandate-expired")

    def test_the_operators_words_reach_no_event_and_no_checkpoint(self):
        self.run_one(body(json.dumps(mandate()), json.dumps(mandate())))
        self.assertNotIn(WORDS, json.dumps([e[2:] for e in self.events]))
        path = self.data / "board-checkpoint.json"
        self.assertNotIn(WORDS, path.read_text() if path.exists() else "")

    def test_a_responder_refuses_a_bad_agent_id_or_mandate_from(self):
        for kw in ({"agent_id": "Not An Id"}, {"mandate_from": "everyone"}, {"mandate_from": [42]}, {"mandate_from": 42}):
            with self.subTest(kw=kw):
                with self.assertRaises(fb.BoardError):
                    self.responder(**kw)


if __name__ == "__main__":
    unittest.main()
