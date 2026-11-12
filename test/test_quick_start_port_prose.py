"""FAA-283: the README quick start picks a free port, and where-agents-run.md covers a shared computer and a member VM."""
from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WHERE = ROOT / "plugins/fabric-agent-adapter/skills/creating-fabric-agents/references/where-agents-run.md"


class QuickStartPort(unittest.TestCase):
    def test_the_quick_start_uses_one_free_port_everywhere(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        mcp = readme.split("### MCP", 1)[1].split("```", 2)[1]
        self.assertIn("PORT=$(python3 -c 'import socket;s=socket.socket();s.bind((\"127.0.0.1\",0));"
                      "print(s.getsockname()[1])')", mcp)
        self.assertIn('serve --port "$PORT"', mcp)
        self.assertIn('register --port "$PORT"', mcp)
        self.assertIn('"$WORK/mcp.json" "$PORT" <<\'EOF\'', mcp)
        self.assertIn('"http://127.0.0.1:%s/mcp" % sys.argv[3]', mcp)
        self.assertIsNone(re.search(r"--port \d|127\.0\.0\.1:\d", mcp), "no port is hard-coded")

    def test_where_agents_run_has_the_shared_computer_and_the_member_vm(self):
        text = " ".join(WHERE.read_text(encoding="utf-8").split())
        for words in ("| **One computer, a personal and an organization account** |", "(contract DEC-0154",
                      "its own port recorded per account", "(HA-1)", "(HA-2)", "(HA-3)",
                      "| **A member's virtual machine** |", "DEC-0154 HA-4", "its callers T2, never token-free",
                      "a port recorded per account, the listener's owner checked before a token is sent"):
            self.assertIn(words, text, words)
        self.assertNotIn("\u2014", text)


class ItsOwnMachine(unittest.TestCase):
    """FAA-230 (placement and own-vault parts): the recipe for an agent on a machine of its own. The port part waits on
    contract DEC-0160 and the row stays open for it."""

    def test_the_recipe_names_the_placement_record_the_refusal_and_the_own_vault(self):
        text = " ".join(WHERE.read_text(encoding="utf-8").split())
        recipe = text.split("## Its own machine: placement, keys and port", 1)[1].split("## ", 1)[0]
        for words in ("`${XDG_DATA_HOME:-~/.local/share}/project-observatory/placement.json`",
                      "`observatory-placement/1`", "`elsewhere`", "`serviceId`", "`label`", "`placedOn`", "`machine`",
                      "refuses to start", "`placed-elsewhere`", "no file", "`placement-unreadable`",
                      "`full machine-move leave LABEL --to MACHINE`", "`full machine-move cutover LABEL`",
                      "Its tests start one copy placed elsewhere and see it refuse", "its own vault", "never copied", "`use_secret.py run`", "issued anew",
                      "DEC-0160", "FAA-225"):
            self.assertIn(words, recipe, words)
        self.assertNotIn("base + uid - 501", text, "the superseded port rule (the 0.73.0 audit, item 1)")
        checklist = text.split("## The checklist", 1)[1]
        self.assertIn("the machine `placement.json` names", checklist)
        self.assertIn("[Its own machine: placement, keys and port](#its-own-machine-placement-keys-and-port)", text)
        self.assertNotIn("\u2014", text)

if __name__ == "__main__":
    unittest.main()
