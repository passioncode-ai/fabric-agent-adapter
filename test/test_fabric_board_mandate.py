"""FAA-135: the board responder reads the operator's mandate from a request of his own Project (contract
project-comms.md, DEC-0125 MD-3). Reading is opt-in (`agent_id` and `mandate_from`) and fail-closed."""

from __future__ import annotations

import importlib
import json
import sys
import time
import types
import unittest
from unittest import mock

from test_fabric_board import Conversation, fb  # noqa: F401 - the shared conversation against the fake hub
from fake_fabric_hub import OTHER_PROJECT

fm = importlib.import_module("fabric_mandate")  # on the path test_fabric_board set
fe = importlib.import_module("fabric_events")

WALL = 1_793_700_000.0  # the responder's wall clock, in seconds
AT = fm.format_rfc3339(WALL * 1000)
WORDS = "render the teaser for the launch"


def mandate(callee: str = "example-agent", scope=None, source=None) -> dict:
    lead = fm.operator_mandate("task-teaser", WORDS, scope or {"capabilities": ["video.render"], "effects": ["draft"]},
                               "lead-agent", at=AT, source=source)
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
        self.rid = self.board.queue("video.render", text=text, provenance=provenance)
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
                                                            "chain": ["lead-agent", "example-agent"], "caller": OTHER_PROJECT}})
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
                said = [e for e in self.events if e[0] == "board.request.mandate_unread"]
                self.assertEqual(len(said), 1)
                self.assertIn(code, said[0][2])
                self.assertEqual(said[0][3]["data"]["value"], {"request": self.rid, "reason": code},
                                 "the data survives FAC-SEM-101: its reason is under `reason`, never `code`")

    def test_a_broken_block_beside_a_mandate_cancels_nothing(self):
        m = mandate()
        got, covered, _ = self.run_one(body(json.dumps(m), '{"frames": '))
        self.assertEqual(got, m)
        self.assertTrue(covered["ok"])
        self.assertEqual([e for e in self.events if e[0] == "board.request.mandate_unread"], [])

    def test_a_json_block_that_is_no_mandate_is_ignored(self):
        got, covered, _ = self.run_one(body('{"frames": 24}'))
        self.assertIsNone(got)
        self.assertEqual([e for e in self.events if e[0] == "board.request.mandate_unread"], [])

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

    def test_a_crlf_body_is_read(self):
        got, covered, _ = self.run_one(body(json.dumps(mandate())).replace("\n", "\r\n"))
        self.assertTrue(covered["ok"])

    def test_a_deeply_nested_block_never_stops_the_responder(self):
        """On Python 3.9 a block nested 3000 deep raises RecursionError in json.loads: read as no mandate, never a raise."""
        deep = '{"kind": "mandate/1", "x": ' + "[" * 3000 + "]" * 3000 + "}"
        got, covered, _ = self.run_one(body(deep))
        self.assertTrue(got is None or covered["data"]["detail"] == "mandate-malformed")

    def test_a_recursion_error_reads_as_unreadable_on_any_python(self):
        """The catch the 3.9 floor needs, pinned on every interpreter (0.61.0 seam reading 2)."""
        link = importlib.import_module("fabric_board_link")
        request = fb.BoardRequest({"body": {"text": body(json.dumps(mandate()))}, "request": {"id": "r"},
                                   "sender": {"project": OTHER_PROJECT, "principal": {"provenance": "trusted"}}}, "video.render")
        with mock.patch.object(link.json, "loads", side_effect=RecursionError):
            self.assertEqual(link.read_mandate(request, frozenset([OTHER_PROJECT]), "example-agent"), (None, "mandate-unreadable"))

    def test_a_sender_without_a_project_is_never_read(self):
        link = importlib.import_module("fabric_board_link")
        for sender in ({"principal": {"provenance": "trusted"}}, {"project": 42, "principal": {"provenance": "trusted"}},
                       {"project": "", "principal": {"provenance": "trusted"}}):
            request = fb.BoardRequest({"body": {"text": body(json.dumps(mandate()))}, "request": {"id": "r"}, "sender": sender}, "video.render")
            self.assertEqual(link.read_mandate(request, link.PERSONAL_BOARD, "example-agent"), (None, None))

    def test_a_board_block_carries_no_source(self):
        """OA-7: a Project declares no protocols, so its block carries no source; one that does has it dropped."""
        got, covered, _ = self.run_one(body(json.dumps(mandate(source={"project": "example-site", "session": "sess-1"}))))
        self.assertNotIn("source", got)
        self.assertNotIn("source", covered["recordAs"])

    def test_the_warning_reaches_the_real_event_log(self):
        """0.61.0 seam reading 1: a kind with a hyphen is refused by make_event, so the warning never reached a feed."""
        log = fe.JsonlEventLog(self.data / "events.jsonl")
        self.run_one(body(json.dumps(mandate()), json.dumps(mandate())), emit=log.append)
        kinds = [e["kind"] for e in log.fetch(None, 50)]
        self.assertIn("board.request.mandate_unread", kinds)

    def test_a_declared_project_matches_in_any_case(self):
        got, covered, _ = self.run_one(body(json.dumps(mandate())), mandate_from={OTHER_PROJECT.upper()})
        self.assertTrue(covered["ok"])

    def test_a_read_mandate_reaches_no_event_and_no_checkpoint(self):
        log = fe.JsonlEventLog(self.data / "events.jsonl")
        self.run_one(body(json.dumps(mandate())), emit=log.append)
        self.assertNotIn(WORDS, (self.data / "events.jsonl").read_text())
        path = self.data / "board-checkpoint.json"
        self.assertNotIn(WORDS, path.read_text() if path.exists() else "")

    def test_each_fence_stands_on_its_own_line(self):
        """0.61.0 unit and product readings 2: an opener mid-line or a four-backtick fence is no mandate block."""
        m = json.dumps(mandate())
        for text in ("Here it is: ```json\n%s\n```\n" % m, "````json\n%s\n````\n" % m, "```json\n%s```\n" % m,
                     "```json\n%s\n```x\n" % m, "x\r```json\n%s\n```\n" % m, "x\u2028```json\n%s\n```\n" % m,
                     "```jsonc\n%s\n```\n" % m, "```json x\n%s\n```\n" % m, "  ```json\n%s\n  ```\n" % m,
                     "\t```json\n%s\n```\n" % m, "```JSON\n%s\n```\n" % m, "~~~json\n%s\n~~~\n" % m,
                     "- the mandate:\n  ```json\n  %s\n  ```\n" % m):
            with self.subTest(text=text[:20]):
                self.tearDown()
                self.setUp()
                got, covered, _ = self.run_one(text)
                self.assertIsNone(got)

    def test_an_integer_over_4300_digits_reads_as_unreadable_on_every_python(self):
        link = importlib.import_module("fabric_board_link")
        if hasattr(sys, "set_int_max_str_digits"):  # lift the interpreter's own limit: only the kit's may refuse it
            self.addCleanup(sys.set_int_max_str_digits, sys.get_int_max_str_digits())
            sys.set_int_max_str_digits(0)
        for literal, unread in (("7" * 4301, "mandate-unreadable"), ("-" + "7" * 4301, "mandate-unreadable"),
                                ("7" * 4300, None), ("-" + "7" * 4300, None)):
            request = fb.BoardRequest({"body": {"text": body('{"kind": "mandate/1", "n": %s}' % literal)}, "request": {"id": "r"},
                                       "sender": {"project": OTHER_PROJECT, "principal": {"provenance": "trusted"}}}, "video.render")
            got, code = link.read_mandate(request, link.PERSONAL_BOARD, "example-agent")
            self.assertEqual(code, unread, len(literal))
            self.assertEqual(got is None, unread is not None, len(literal))

    def test_a_closing_fence_may_carry_trailing_spaces(self):
        got, covered, _ = self.run_one("```json  \n%s\n```  \t\n" % json.dumps(mandate()))
        self.assertTrue(covered["ok"])

    def test_reading_is_linear_in_the_body(self):
        """0.61.0 unit and seam readings 3: an anchored regex rescanned to the end from every unclosed opener."""
        link = importlib.import_module("fabric_board_link")

        def cost(size: int, shape: str) -> float:
            text = ("```json\n```x\n" * size)[:size] if shape == "unclosed" else "```json\n" * (size // 8) + "```\n"
            request = fb.BoardRequest({"body": {"text": text}, "request": {"id": "r"},
                                       "sender": {"project": OTHER_PROJECT, "principal": {"provenance": "trusted"}}}, "video.render")
            best = float("inf")
            for _ in range(5):
                start = time.perf_counter()
                link.read_mandate(request, link.PERSONAL_BOARD, "example-agent")
                best = min(best, time.perf_counter() - start)
            return best

        for shape in ("unclosed", "nested"):  # nested: every inner opener closed by the same fence (unit reading 4)
            small, large = cost(65536, shape), cost(4 * 65536, shape)
            self.assertLess(large / max(small, 1e-6), 10, "%s: linear is about 4, quadratic about 16" % shape)

    def test_a_uuid_matches_in_any_case_and_any_other_id_as_written(self):
        link = fb._link if hasattr(fb, "_link") else importlib.import_module("fabric_board_link")
        request = fb.BoardRequest({"body": {"text": body(json.dumps(mandate()))}, "request": {"id": "r"},
                                   "sender": {"project": OTHER_PROJECT.upper(), "principal": {"provenance": "trusted"}}}, "video.render")
        self.assertIsNotNone(link.read_mandate(request, link.mandate_options("example-agent", {OTHER_PROJECT}), "example-agent")[0])
        request.sender = {"project": "team-a", "principal": {"provenance": "trusted"}}
        self.assertIsNone(link.read_mandate(request, link.mandate_options("example-agent", {"Team-A"}), "example-agent")[0])
        self.assertIsNotNone(link.read_mandate(request, link.mandate_options("example-agent", {"team-a"}), "example-agent")[0])

    def test_a_clock_that_does_not_read_answers_now_unreadable(self):
        link = importlib.import_module("fabric_board_link")
        for clock in (float("nan"), None, float("inf"), 1e15, -1e15, 1e300, 10 ** 400, True):
            self.assertEqual(link.covers(mandate(), {"capability": "video.render", "effect": "draft"}, "example-agent",
                                         lambda c=clock: c), {"fault": "now-unreadable"})

    def test_the_operators_words_reach_no_checkpoint_during_the_work(self):
        """0.61.0 product reading 5: the checkpoint was read only after the request completed and its entry was gone."""
        during = []

        def outcome(request, ctx):
            path = self.data / "board-checkpoint.json"
            during.append(path.read_text() if path.exists() else "")
            self.seen.append((ctx.mandate, None, None))
            return {"state": "completed", "summary": "Rendered."}

        self.outcome = outcome
        got, _, _ = self.run_one(body(json.dumps(mandate())))
        self.assertIsNotNone(got, "a mandate was read")
        self.assertTrue(during[0], "the request's entry is in the checkpoint while it is worked")
        self.assertNotIn(WORDS, during[0])

    def test_a_responder_refuses_a_bad_agent_id_or_mandate_from(self):
        for kw in ({"agent_id": "Not An Id"}, {"mandate_from": "everyone"}, {"mandate_from": [42]}, {"mandate_from": 42},
                   {"mandate_from": {OTHER_PROJECT: True}}, {"mandate_from": types.MappingProxyType({OTHER_PROJECT: 1})}):
            with self.subTest(kw=kw):
                with self.assertRaises(fb.BoardError):
                    self.responder(**kw)


if __name__ == "__main__":
    unittest.main()
