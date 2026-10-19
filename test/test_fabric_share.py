"""Share grants into an organization and their registrations (contract DEC-0086; FAA-54) in the Python kit, held to
the contract's cases as test/fixtures/contract/share-vectors.json vendors them, and the vendored schema."""

import importlib
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts"
sys.path.insert(0, str(SCRIPTS))
fs = importlib.import_module("fabric_share")

V = json.loads((Path(__file__).resolve().parent / "fixtures/contract/share-vectors.json").read_text())
SCHEMA = json.loads((SCRIPTS / "share-registration.schema.json").read_text())


class ShareTests(unittest.TestCase):
    def test_every_grant_id_case(self):
        for c in V["grantId"]:
            with self.subTest(c["name"]):
                self.assertIs(fs.is_share_grant_id(c["value"]), c["ok"])

    def test_every_org_context_case(self):
        for c in V["orgContext"]:
            with self.subTest(repr(c["value"])):
                self.assertIs(fs.is_org_context(c["value"]), c["ok"])

    def test_every_rule_case(self):
        for c in V["rules"]:
            with self.subTest(c["name"]):
                self.assertEqual(fs.share_rules(c["kind"], c["value"]), c["expected"])

    def test_every_attribution_case(self):
        for c in V["attribution"]:
            with self.subTest(c["name"]):
                self.assertEqual(fs.share_rules("device-attribution", c["value"]), c["expected"])

    def test_another_kind_is_not_ours(self):
        self.assertIsNone(fs.share_rules("estate-record", {}))

    def test_the_vendored_schema_is_self_contained_and_agrees_with_the_kit(self):
        refs = [ref for ref in json.dumps(SCHEMA).split('"$ref": "')[1:] if not ref.startswith("#")]
        self.assertEqual(refs, [], "every reference stays inside the copy")
        self.assertEqual(SCHEMA["$defs"]["shareGrantId"]["pattern"], "^" + fs.SHARE_GRANT_ID.pattern.replace("\\Z", "$"))
        self.assertEqual(SCHEMA["$defs"]["orgContextId"]["pattern"], "^" + fs.ORG_CONTEXT.pattern.replace("\\Z", "$"))


if __name__ == "__main__":
    unittest.main()
