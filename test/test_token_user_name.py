"""DEC-0177 (CT-329): a URL's user name that is a token makes `secret_url` refuse the URL, in both Python copies."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
COPIES = [ROOT / "plugins/fabric-agent-adapter/skills" / skill / "scripts/fabric_secrets.py"
          for skill in ("building-fabric-services", "adapting-projects-to-fabric")]
TOKEN = "a1" * 20  # 40 characters holding a letter and a digit, built at run time: a classic token's shape, never a key


def load(path):
    spec = importlib.util.spec_from_file_location("fabric_secrets_token_user_%s" % path.parent.parent.name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TokenUserName(unittest.TestCase):
    def test_the_shape(self):
        for path in COPIES:
            s = load(path)
            self.assertTrue(s.token_user_name(TOKEN))
            self.assertTrue(s.token_user_name("A_" + "b-9" * 13))
            for user in ("git", "deploy-bot", "a" * 40, "1" * 40, TOKEN[:39], TOKEN + "!", ""):
                self.assertFalse(s.token_user_name(user), user)

    def test_secret_url_refuses_a_token_user(self):
        for path in COPIES:
            s = load(path)
            scheme = "https"
            self.assertTrue(s.secret_url("%s://%s@github.com/o/r.git" % (scheme, TOKEN)))
            self.assertTrue(s.secret_url("%s://%s@github.com/o/r.git" % (scheme, "%61" + TOKEN[1:])), "read decoded")
            self.assertFalse(s.secret_url("%s://git@github.com/o/r.git" % scheme))
            self.assertFalse(s.secret_url("%s://deploy-bot@example.com/r" % scheme))


class StoredManifestUrl(unittest.TestCase):
    def test_a_manifest_url_with_a_token_user_is_refused(self):
        # FAA-343 (13): the contract's fixtures/semantic/command-line-token-user-in-manifest-url.json, rebuilt here
        import sys
        sys.path.insert(0, str(ROOT / "plugins/fabric-agent-adapter/skills/adapting-projects-to-fabric/scripts"))
        import adapt_project
        url = "https" + "://" + TOKEN + "@agents.example/mcp"
        manifest = {"capabilities": [{"profile": {"connection": {"mode": "streamable-http", "url": url}}}]}
        self.assertTrue(any("capability[0].url" in p for p in adapt_project._credential_problems(manifest)))
        manifest["capabilities"][0]["profile"]["connection"]["url"] = "https://git@agents.example/mcp"
        self.assertEqual(adapt_project._credential_problems(manifest), [])


if __name__ == "__main__":
    unittest.main()
