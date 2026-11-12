"""FAA-282: the operator channel sends through the estate's messaging gateway, and a polling token has one poller."""
from __future__ import annotations

import pathlib
import unittest

SKILLS = pathlib.Path(__file__).resolve().parents[1] / "plugins" / "fabric-agent-adapter" / "skills"
PAGES = [SKILLS / name / "references" / "operator-channel-and-repository.md"
         for name in ("adapting-projects-to-fabric", "creating-fabric-agents")]


class OperatorChannelGateway(unittest.TestCase):
    def test_both_copies_carry_the_gateway_and_the_single_poller(self):
        self.assertEqual(PAGES[0].read_bytes(), PAGES[1].read_bytes())
        text = " ".join(PAGES[0].read_text(encoding="utf-8").split())
        for words in ("a messaging gateway service the operator chose for sending",
                      "the channel sends through that gateway and does not call the messenger itself",
                      "the agent's own bot above is the contract's form (DEC-0034, OC-11)",
                      "has exactly one poller across every machine", "`409 Conflict`",
                      "Check placement before polling", "`poller-elsewhere`",
                      "a test starts a second instance placed elsewhere and sees it stay off the token"):
            self.assertIn(words, text, words)
        self.assertNotIn("—", text)


if __name__ == "__main__":
    unittest.main()
