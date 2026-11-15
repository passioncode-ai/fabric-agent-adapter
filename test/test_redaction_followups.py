"""FAA-200 follow-ups (34), (21), (39), (33), (15), (28), (35), (54): where the kit or the probe printed part of a secret
or let a credential form through. The Node twin is test/redaction-followups.test.mjs. Every key-shaped value is made
up and built here at run time, never written whole."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
ADAPTING = ROOT / "plugins/fabric-agent-adapter/skills/adapting-projects-to-fabric/scripts"
sys.path.insert(0, str(SCRIPTS))

KEY = "ghp_" + "Fx9k" * 9  # made up: shaped like a key, never one
AKIA = "AKIA" + "QX7Z" * 4  # made up
SK_RUN = "sk-" + "Ab1d" * 10  # made up, a key DEC-0151 reads


def load(name, folder=SCRIPTS):
    spec = importlib.util.spec_from_file_location(name, folder / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(folder))
    spec.loader.exec_module(module)
    return module


rules = load("check_service_rules")
fh = load("fabric_http")
fs = load("fabric_service")
check = load("check_service")


def descriptor(**extra):
    base = {
        "protocol": fs.PROTOCOL, "id": "sample", "instance": "default", "name": "Sample",
        "origin": "http://127.0.0.1:47210", "auth": {"tokenFile": "/tmp/x/service.token"},
        "lifecycle": {"manager": "none"}, "paths": {"data": "/tmp/x", "logs": []},
        "installedAt": fs.now_iso(), "installedBy": "test", "source": {"repository": "https://github.com/example-org/example-agent"},
    }
    base.update(extra)
    return base


class ShownRepository(unittest.TestCase):
    """(34), (21): a password is cut after the last `@` whenever repository_password reads one."""

    def test_a_password_holding_an_at_never_shows(self):
        self.assertNotIn("fixture-pw9", rules.shown_repository("ssh:@u:fixture-pw9@h.example/r"))
        self.assertEqual(rules.shown_repository("ssh:@u:fixture-pw9@h.example/r"), "h.example/r")
        self.assertEqual(rules.shown_repository("user:p@x:fixture-pw@host.example/o/r"), "host.example/o/r")
        self.assertNotIn("fixture-pw", rules.shown_repository("user:p@x:fixture-pw@host.example/o/r"))
        self.assertEqual(rules.shown_repository("git@github.com:example-org/na@me.git"), "github.com:example-org/na@me.git",
                         "no password: the scp reading stands")

    def test_a_user_holding_a_question_mark_is_no_host(self):
        """(15): the URL standard reads `tok` of `tok?en@host` as the host; the user is never printed."""
        for value in ("https://tok?en@host.example/o/r", "https://tok#en@host.example/o/r"):
            self.assertEqual(rules.shown_repository(value), "<unparseable url>", value)
        for value in ("ssh://tok?en@host.example/o/r", "git://tok#en@host.example/o/r"):
            self.assertNotIn("tok", rules.shown_repository(value), value)

    def test_a_key_shaped_scheme_is_not_printed(self):
        """(33): a scheme is read for a key's shape as written, before it is lower-cased."""
        for value in (AKIA + "://h.example/o/r", SK_RUN + "://h.example/o/r"):
            shown = rules.shown_repository(value)
            self.assertFalse(AKIA.lower() in shown.lower() or SK_RUN.lower() in shown.lower(), "a key-shaped scheme is printed")


class RedactUrl(unittest.TestCase):
    def test_a_key_shaped_scheme_is_redacted(self):
        """(33): `<redacted>:<redacted>`, never the scheme, in redact_url and an HttpError's url."""
        for value in (AKIA + ":x@h.example/r", SK_RUN + "://h.example:99/r", " " + AKIA + "://h.example/r"):
            self.assertTrue(fh.redact_url(value) == "<redacted>:<redacted>", "a key-shaped scheme is printed")
        self.assertEqual(fh.redact_url("ssh://h.example/r"), "ssh:<redacted>", "a scheme with no key's shape keeps its name")
        with self.assertRaises(fh.HttpError) as caught:
            fh.check_url(SK_RUN + "://h.example/r")
        self.assertFalse(SK_RUN.lower() in (str(caught.exception) + str(caught.exception.url)).lower(), "a key-shaped scheme is printed")

    def test_a_user_holding_a_question_mark_is_unparseable(self):
        """(15): the shared kit-http rows hold it; read here once more for the fragment."""
        self.assertEqual(fh.redact_url("https://tok?en@host.example/o/r"), "<unparseable url>")
        self.assertEqual(fh.redact_url("https://tok#en@host.example/o/r"), "<unparseable url>")
        self.assertEqual(fh.redact_url("https://host.example/o/r?next=a@b.example"), "https://host.example/o/r", "after the path")


class MemberNames(unittest.TestCase):
    """(39): a member name shaped like a credential is printed `<redacted>` in descriptor problems and probe evidence."""

    def test_no_problem_names_a_key_shaped_member(self):
        cases = [
            descriptor(installedBy={"by": "node", "tool": "x 1", KEY: "y"}),
            descriptor(runner={"credentialKind": "none", KEY: "y"}),
            descriptor(source={"repository": "https://github.com/example-org/example-agent", KEY: "y"}),
            descriptor(peer={"endpoint": "https://agent.example.com", "custody": "personal", "residency": ["DE"],
                             "maxDataClass": "public", KEY: "y"}, runner={"credentialKind": "none"}),
            descriptor(commands={KEY: ["/bin/x"]}),
        ]
        for value in cases:
            problems = fs.validate_descriptor(value)
            text = "; ".join(problems)
            with self.subTest(members=sorted(k for k in value if isinstance(value[k], dict))):
                self.assertTrue(problems)
                self.assertFalse(KEY in text, "a key-shaped member name is printed")
                self.assertIn("<redacted>", text)
        plain = fs.validate_descriptor(descriptor(source={"repository": "https://github.com/example-org/example-agent", "branch": "main"}))
        self.assertIn("source has no member branch", plain, "a plain name is still named")

    def test_the_probe_evidence_names_no_key_shaped_member(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = fs.write_descriptor(descriptor(), root)
            d = json.loads(path.read_text())
            d["source"] = {"repository": "https://github.com/example-org/example-agent", KEY: "y"}
            p = check.Probe(path, d, root, True)
            p.descriptor_rules()
            verdicts = {r["rule"]: r for r in p.results}
            self.assertEqual(verdicts["descriptor.source-repository"]["verdict"], "NOT_RUN")
            self.assertFalse(any(KEY in r["evidence"] for r in p.results), "a key-shaped member name is printed")
            self.assertIn("<redacted>", verdicts["descriptor.source-repository"]["evidence"])


class LaunchArguments(unittest.TestCase):
    """(28): a URL inside a launch argument is read as a URL: a password in it is a credential."""

    def credential_url(self):
        return "https://" + "u:" + "fixture9pw" + "@h.example/r"

    def test_the_detector_reads_a_url_in_an_argument(self):
        secrets = load("fabric_secrets")
        self.assertTrue(secrets.secret_launch_argument("--remote=" + self.credential_url()))
        self.assertTrue(secrets.secret_launch_argument(KEY))
        self.assertFalse(secrets.secret_launch_argument("--remote=https://h.example/r"))
        self.assertFalse(secrets.secret_launch_argument("--port=47201"))

    def test_a_provider_entry_refuses_it(self):
        provider = load("fabric_provider", ADAPTING)
        entry = {
            "protocol": "fabric-provider/0.1", "id": "example-agent", "providerId": "https://agents.example/providers/example-agent",
            "name": "Example Agent", "manifest": "~/.local/share/example-agent/fabric-agent.json",
            "run": {"mcp": {"stdio": {"command": ["/bin/x", "--remote=" + self.credential_url()]}}},
            "installedAt": "2026-09-30T08:00:00Z", "installedBy": "test",
        }
        problems = provider.validate_provider_entry(entry)
        self.assertTrue(any("run.mcp.stdio.command carries a credential" in p for p in problems), problems)
        self.assertFalse(any("fixture9pw" in p for p in problems))

    def test_a_descriptor_command_refuses_it(self):
        problems = fs.validate_descriptor(descriptor(commands={"doctor": ["/bin/x", "--remote=" + self.credential_url()]}))
        self.assertTrue(any("FAC-SEM-057" in p and "doctor" in p for p in problems), problems)
        self.assertFalse(any("fixture9pw" in p for p in problems))
        self.assertTrue(any("FAC-SEM-057" in p for p in fs.validate_descriptor(descriptor(commands={"doctor": ["/bin/x", KEY]}))))
        self.assertEqual(fs.validate_descriptor(descriptor(commands={"doctor": ["/bin/x", "--remote=https://h.example/r"]})), [])


class SourceRepositoryProbe(unittest.TestCase):
    """(35), (54): a GitHub spelling the estate's readers cannot join, and a source with no host, are no pass."""

    def verdict(self, repository):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = fs.write_descriptor(descriptor(), root)
            d = json.loads(path.read_text())
            d["source"] = {"repository": repository}
            p = check.Probe(path, d, root, True)
            p.descriptor_rules()
            return {r["rule"]: r for r in p.results}["descriptor.source-repository"]

    def test_github_spellings_other_than_owner_and_name(self):
        for value in ("https://github.com/example-org/example-agent/tree/main", "https://www.github.com/example-org/example-agent",
                      "https://github.com/example-org/example-agent#readme", "https://github.com:443/example-org/example-agent",
                      "https://github.com/example-org/example-agent.git/", "http://github.com/example-org/example-agent"):
            found = self.verdict(value)
            with self.subTest(value=value):
                self.assertEqual(found["verdict"], "NOT_RUN", found)
                self.assertIn("https://github.com/example-org/example-agent", found["evidence"])
        for value in ("https://github.com/example-org/example-agent", "https://github.com/example-org/example-agent.git",
                      "https://gitlab.example.com/group/sub/agent"):
            self.assertEqual(self.verdict(value)["verdict"], "PASS", value)

    def test_a_source_with_no_host(self):
        for value in ("x:y", "urn:isbn:1"):
            found = self.verdict(value)
            with self.subTest(value=value):
                self.assertEqual(found["verdict"], "NOT_RUN", found)
                self.assertIn("https://github.com/owner/name", found["evidence"])


if __name__ == "__main__":
    unittest.main()
