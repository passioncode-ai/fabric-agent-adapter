"""FAA-284: working-with-fabric over SSH and from two machines. The reference's key rules are held in its prose, and
the evals cover them."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/fabric-agent-adapter/skills/working-with-fabric"
PAGE = (SKILL / "references/remote-sessions.md").read_text(encoding="utf-8")


def section(title):
    return PAGE.split("## " + title, 1)[1].split("\n## ", 1)[0]


class RemoteSessions(unittest.TestCase):
    def test_with_no_gui_login_fabric_is_never_started_over_ssh(self):
        text = section("Over SSH")
        self.assertIn("stat -f %Su /dev/console", text)
        self.assertIn("launchctl print gui/$(id -u)", text)
        self.assertIn("Do not try to start it: no `open -a`", text)
        self.assertIn("not a reason to retry", text)
        self.assertIn("someone logs in at the screen", text)
        self.assertIn("consent prompt", text)

    def test_two_machines_have_two_boards_and_meet_in_git(self):
        text = section("One Project from two machines")
        self.assertIn("**two boards**", text)
        self.assertRegex(text, re.compile(r"Never carry a task id, claim id, request id or\s+message id"))
        self.assertIn("push before you stop", text)
        self.assertIn('"dispatchOnSharedBoard": true', text)
        self.assertIn("refs/agent-sync/leases/*", text)

    def test_a_run_sent_here_uses_the_board_only_for_its_own_project(self):
        text = section("A board run sent to the other machine")
        self.assertIn("names the request's own Project", text)
        self.assertIn("answer in the run's result", text)

    def test_linked_from_the_skill_and_covered_by_evals(self):
        self.assertIn("[remote sessions](references/remote-sessions.md)", (SKILL / "SKILL.md").read_text(encoding="utf-8"))
        ids = {s["id"] for s in json.loads((ROOT / "test/evals/working-with-fabric/scenarios.json").read_text())["scenarios"]}
        for needed in ("an-ssh-session-with-no-gui-login-does-not-start-fabric", "an-ssh-session-with-a-gui-login-uses-fabric",
                       "one-project-from-two-machines-coordinates-through-git",
                       "a-board-run-sent-to-another-machine-answers-in-its-result"):
            self.assertIn(needed, ids)


if __name__ == "__main__":
    unittest.main()
