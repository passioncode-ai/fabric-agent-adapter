"""FAA-281: one rule for secrets in a child's environment, the same in every page that states it."""
from __future__ import annotations

import pathlib
import unittest

SKILLS = pathlib.Path(__file__).resolve().parents[1] / "plugins" / "fabric-agent-adapter" / "skills"


def flat(path: pathlib.Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


class SecretsInAChild(unittest.TestCase):
    def test_the_agents_own_process_may_hold_its_key_and_a_child_never_does(self):
        resilience = flat(SKILLS / "creating-fabric-agents" / "references" / "resilience-and-autonomy.md")
        for words in ("The agent's own process may receive its key in its environment from its supervisor or a vault runner",
                      "it never passes that key to a child it starts", "Scrub the child's environment",
                      "over a pipe or file descriptor, or through a vault runner per command"):
            self.assertIn(words, resilience, words)
        models = flat(SKILLS / "creating-fabric-agents" / "references" / "models-and-providers.md")
        for words in ("never pass it on to a child the agent starts", "scrub the child's environment",
                      "a file descriptor or a per-command vault run",
                      "read from the agent's own environment and never passed to a child"):
            self.assertIn(words, models, words)
        lifecycle = flat(SKILLS / "building-fabric-services" / "references" / "lifecycle.md")
        self.assertIn("Keys reach the process through its environment, a 0600 file or a vault, never argv", lifecycle)
        for text in (resilience, models):
            self.assertNotIn("\u2014", text)


if __name__ == "__main__":
    unittest.main()
