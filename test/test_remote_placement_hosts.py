"""FAA-280: a remote service registered from several hosts, one token per host. The pattern
remote-placement.md gives (every token compared with the kit's token_matches, one LoginCodes per host) is run here on
the kit itself, and the page's rule is held in its prose."""
import importlib
import re
import secrets
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services"
sys.path.insert(0, str(SKILL / "scripts"))
fs = importlib.import_module("fabric_service")  # the kit, beside its other modules

PAGE = (SKILL / "references/remote-placement.md").read_text(encoding="utf-8")


def host_of(authorization, tokens):  # the page's code, as written there
    matched = [host for host, token in sorted(tokens.items()) if fs.token_matches(authorization, token)]
    return matched[0] if matched else None


class SeveralHosts(unittest.TestCase):
    def setUp(self):
        self.tokens = {"laptop": secrets.token_urlsafe(32), "studio": secrets.token_urlsafe(32)}
        key = secrets.token_bytes(32)
        self.codes = {h: fs.LoginCodes(None, store=fs.MemoryCodeStore(), key=key, token=t) for h, t in self.tokens.items()}

    def sign_in(self, host):
        issued = self.codes[host_of("Bearer " + self.tokens[host], self.tokens)].issue()
        code = issued["url"].split("code=", 1)[1]
        cookies = [c for c in (codes.redeem(code) for codes in self.codes.values()) if c]
        self.assertEqual(len(cookies), 1)  # only the instance that issued it redeems it
        return cookies[0]

    def valid(self, cookie):
        return any(codes.session_valid(cookie) for codes in self.codes.values())

    def test_each_host_is_its_own_bearer(self):
        self.assertEqual(host_of("Bearer " + self.tokens["laptop"], self.tokens), "laptop")
        self.assertEqual(host_of("Bearer " + self.tokens["studio"], self.tokens), "studio")
        self.assertIsNone(host_of("Bearer " + "x" * 43, self.tokens))
        self.assertIsNone(host_of(None, self.tokens))
        self.assertTrue(fs.well_known_allowed("remote", "Bearer " + self.tokens["studio"], self.tokens["studio"]))

    def test_revoking_one_host_ends_only_its_sessions(self):
        laptop, studio = self.sign_in("laptop"), self.sign_in("studio")
        self.assertTrue(self.valid(laptop) and self.valid(studio))
        revoked = self.tokens.pop("laptop")
        self.codes["laptop"] = fs.LoginCodes(None, store=fs.MemoryCodeStore(), key=secrets.token_bytes(32),
                                             token=secrets.token_urlsafe(32))  # the platform restarted without it
        self.assertIsNone(host_of("Bearer " + revoked, self.tokens))
        self.assertFalse(self.valid(laptop))
        self.assertTrue(self.valid(studio))


class Prose(unittest.TestCase):
    def section(self):
        return PAGE.split("## Registered from several hosts", 1)[1].split("\n## ", 1)[0]

    def test_the_rule_is_one_token_per_registering_host(self):
        text = self.section()
        self.assertIn("its own token", text)
        self.assertIn("never copied from one\nhost to another", text)
        self.assertIn("no early return", text)
        self.assertIn("`well-known.requires-token` passes\n  on each", text)
        self.assertIn("FAA-204", text)
        self.assertIn("[Registered from several hosts](#registered-from-several-hosts)", PAGE)

    def test_the_page_no_longer_assumes_one_computer_per_token(self):
        self.assertNotIn("re-running `registerRemote` on the\noperator's computer", PAGE)
        self.assertNotRegex(PAGE, re.compile(r"written on the operator's computer by `registerRemote`"))


if __name__ == "__main__":
    unittest.main()
