"""FAA-311: working-with-fabric answers a request to its Project as the pinned contract's DEC-0152 SA-6 says.

The scenario evals are judged by a model, so hosted CI cannot run them; these checks hold the rule in the skill's prose
and in the evals' expectations. The three differences the repin found (docs/evidence/specs/
2026-11-12-faa-258-repin-93e7db16-impact-map.md, DEC-0152): FAA-241 asked the operator at an `active` slot too; the
error rule left a non-retryable refusal without asking; a session without the slot gave a request its state."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/fabric-agent-adapter/skills/working-with-fabric"


def flat(path):
    return " ".join(path.read_text(encoding="utf-8").split())


def section(text, title):
    return text.split("## " + title, 1)[1].split(" ## ", 1)[0]


BOARD = flat(SKILL / "references/project-board.md")
RUN = flat(SKILL / "references/on-demand-session.md")
SCENARIOS = {s["id"]: s for s in json.loads((ROOT / "test/evals/working-with-fabric/scenarios.json")
                                           .read_text(encoding="utf-8"))["scenarios"]}


class LiveSession(unittest.TestCase):
    def test_the_slot_is_read_first_and_an_active_holder_is_left_alone(self):
        text = section(BOARD, "Answering a request addressed to your Project")
        for word in ("first reads that slot in `com.status`",
                     "`active` (a live holder other than this session): leave the request to that holder, send nothing "
                     "and ask no one",
                     "Refused `fenced` (a holder became live meanwhile): as `active`"):
            with self.subTest(word=word[:40]):
                self.assertIn(word, text)
        self.assertNotIn("at any other slot state it sends no reply and still asks", text)

    def test_each_refusal_has_its_one_answer(self):
        text = section(BOARD, "Answering a request addressed to your Project")
        for word in ("`stale`, `absent` at a generation of 1 or more, or no generation or no row shown: send no "
                     "`com.reply`, leave the request queued for that service, and ask the operator",
                     "`absent` at generation 0, with neither the slot nor the Project held: one session of the Project "
                     "replies once that it cannot take the request now, why, and what would lift it",
                     "Refused with any other code: send no reply and decline nothing; with `retryable: true` (`held` "
                     "among them) try again once the cause is gone, otherwise ask the operator, naming the refusal"):
            with self.subTest(word=word[:40]):
                self.assertIn(word, text)

    def test_a_session_without_the_slot_gives_a_request_no_state(self):
        text = section(BOARD, "Answering a request addressed to your Project")
        self.assertIn("A session without the slot does no work on the request and gives it no state", text)
        self.assertNotIn("or you are doing it and give its state", text)
        at_once = section(BOARD, "Answering at once (FAA-205)")
        self.assertIn("A request to your Project is answered only as SA-6 says", at_once)
        self.assertNotIn("at any slot state asks", at_once)

    def test_the_skill_points_at_the_rule(self):
        skill = flat(SKILL / "SKILL.md")
        self.assertIn("a request to your Project goes as project-board.md's SA-6 rule says (an `active` slot's holder "
                      "keeps it and nobody is asked)", skill)


class Readme(unittest.TestCase):
    def test_the_readme_states_the_preamble_rule(self):
        """README.md restates the session preamble (fabric_session_cli.PREAMBLE): an announcement or question gets its
        state in the same turn, a request is read through its capability's slot, never the pre-FAA-311 'stays queued'."""
        readme = flat(ROOT / "README.md")
        for word in ("an announcement or question waiting on its Project gets its state in the same turn",
                     "a request to its Project is read through its capability's slot in `com.status`",
                     "`active` is left to its holder and nobody is asked",
                     "otherwise `com.enroll`, and only the slot's holder gives the request its state"):
            with self.subTest(word=word[:40]):
                self.assertIn(word, readme)
        self.assertNotIn("should take stays queued", readme)


class DispatchedRun(unittest.TestCase):
    def test_step_3_reads_the_slot_and_leaves_an_active_one(self):
        step3 = RUN.split("3. **Take the request.**", 1)[1].split("4. **Do the work**", 1)[0]
        self.assertIn("reads `active`, or a `com.enroll` refused `fenced`", step3)
        self.assertIn("leaves the request to that holder: it enrolls on nothing, sends no `com.reply` and asks no one",
                      step3)
        self.assertNotIn("FAA-241", step3)
        self.assertNotIn("`active`, or `absent` at a generation of 1 or more", step3)

    def test_the_error_rule_asks_after_a_refusal_that_is_not_retryable(self):
        rule = RUN.split("7. **End the run.**", 1)[1].split("## When a run ends without an answer", 1)[0]
        self.assertIn("On an error the session cannot get past", rule)
        self.assertIn("A `com.enroll` refused with any other code than `not_authorized` or `fenced` sends no reply and "
                      "declines nothing: a `retryable` refusal is tried again, and any other is named to the operator",
                      rule)


class Evals(unittest.TestCase):
    def test_the_scenarios_hold_sa_6(self):
        live = " ".join(SCENARIOS["answer-as-responder-or-reply"]["expected"])
        self.assertIn("reads the capability's slot in com.status first", live)
        self.assertIn("at an active slot leaves the request to that holder, sends nothing and asks no one", live)
        self.assertNotIn("stale, active or absent at a later generation, sends no reply and still asks", live)
        run = " ".join(SCENARIOS["a-dispatched-run-whose-enroll-is-refused"]["expected"])
        self.assertNotIn("stale, active, or absent", run)
        self.assertIn("refused with any other code", run)
        turn = " ".join(SCENARIOS["a-request-whose-work-outlasts-the-turn"]["expected"])
        self.assertIn("without the slot does no work on it and gives it no state", turn)
        active = SCENARIOS["a-request-at-an-active-slot-is-left-to-its-holder"]
        self.assertIn("asks the operator", active["trap"])
        self.assertIn("asks no one", " ".join(active["expected"]))
        triggers = json.loads((ROOT / "test/evals/working-with-fabric/triggers.json").read_text(encoding="utf-8"))
        self.assertTrue(any("slot active" in q["query"] and q["shouldTrigger"] for q in triggers["queries"]))


if __name__ == "__main__":
    unittest.main()
