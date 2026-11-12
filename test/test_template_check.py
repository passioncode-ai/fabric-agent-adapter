"""The agent template folder: its JSON Schemas and template_check.py (fabric-workspace S2, decision W0-Q8; FAA-265)."""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/fabric-agent-adapter/skills/creating-fabric-agents"
SCRIPT = SKILL / "scripts/template_check.py"
SCHEMAS = SKILL / "schemas/template"
EXAMPLE = ROOT / "test/fixtures/templates/example-agent"

_spec = importlib.util.spec_from_file_location("template_check", SCRIPT)
tc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tc)

# The keywords the interpreter in template_check.py implements; a schema that used another would be checked silently
# less than it says.
KEYWORDS = {"$schema", "$id", "$ref", "$defs", "title", "description", "type", "required", "properties",
            "additionalProperties", "patternProperties", "enum", "items", "minItems", "maxItems", "uniqueItems",
            "minLength", "maxLength", "pattern", "minimum", "minProperties", "oneOf"}


def keywords(node, found):
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            if key in ("properties", "patternProperties", "$defs"):
                for sub in value.values():
                    keywords(sub, found)
            elif key in ("items", "additionalProperties") and isinstance(value, dict):
                keywords(value, found)
            elif key == "oneOf":
                for sub in value:
                    keywords(sub, found)
    return found


class TemplateFolder(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name) / "example-agent"
        shutil.copytree(EXAMPLE, self.folder)

    def tearDown(self):
        self.temp.cleanup()

    def edit(self, name, change):
        """Change the file's document in place (`change` mutates it; what it returns is ignored)."""
        path = self.folder / name
        doc = json.loads(path.read_text())
        change(doc)
        path.write_text(json.dumps(doc))

    def put(self, name, doc):
        (self.folder / name).write_text(json.dumps(doc))

    def errors(self, legacy=False):
        return [f for f in tc.check_folder(self.folder, legacy=legacy) if f["level"] == "error"]

    def messages(self, legacy=False, level="error"):
        return ["%s %s: %s" % (f["file"], f["path"], f["message"])
                for f in tc.check_folder(self.folder, legacy=legacy) if f["level"] == level]

    def test_the_example_template_passes(self):
        self.assertEqual(tc.check_folder(EXAMPLE), [])

    def test_every_part_of_the_folder_is_required(self):
        for name in ("TEMPLATE.md", "assembly.md", "CHANGELOG.md", "manifest.json", "connections.json", "access.json",
                     "data-rooms.json"):
            with self.subTest(name=name):
                moved = self.folder / name
                kept = Path(self.temp.name) / name
                moved.rename(kept)
                self.assertIn("%s $: is missing" % name, self.messages())
                kept.rename(moved)
        shutil.rmtree(self.folder / "checks")
        self.assertIn("checks/ $: holds no acceptance check", self.messages())

    def test_the_header_names_the_folder_and_manifest_the_same_template_and_version(self):
        text = (self.folder / "TEMPLATE.md").read_text()
        (self.folder / "TEMPLATE.md").write_text(text.replace("version: 1.0.0", "version: 1.1.0"))
        found = self.messages()
        self.assertIn('manifest.json $.version: is "1.0.0", TEMPLATE.md names "1.1.0"', found)
        self.assertIn("CHANGELOG.md $: has no entry for version 1.1.0", found)
        renamed = self.folder.rename(Path(self.temp.name) / "another-name")
        self.folder = renamed
        self.assertTrue(any('is "example-agent", the folder is "another-name"' in m for m in self.messages()))

    def test_the_header_is_checked_against_its_schema(self):
        text = (self.folder / "TEMPLATE.md").read_text()
        for old, new, says in (("readiness: draft", "readiness: ready", "must be one of"),
                               ("version: 1.0.0", "version: v1", "does not match"),
                               ("  checked: 2026-11-08\n", "", "lacks checked"),
                               ("family: support", "family: Support Desk", "does not match")):
            with self.subTest(old=old):
                (self.folder / "TEMPLATE.md").write_text(text.replace(old, new))
                self.assertTrue(any(m.startswith("TEMPLATE.md") and says in m for m in self.messages()), self.messages())
        (self.folder / "TEMPLATE.md").write_text("# no front matter\n")
        self.assertIn("TEMPLATE.md $: does not start with a front matter block (---)", self.messages())

    def test_the_operating_rules_are_inherited_by_reference(self):
        text = (self.folder / "TEMPLATE.md").read_text()
        (self.folder / "TEMPLATE.md").write_text(text.replace("A1 to A12", "the operating rules"))
        self.assertIn("TEMPLATE.md $: does not inherit the operating rules A1 to A12 by reference", self.messages())

    def test_connections_are_checked(self):
        self.edit("connections.json", lambda d: d[0].update(direction="sideways"))
        self.assertTrue(any("connections.json $[0].direction: must be one of" in m for m in self.messages()))
        self.edit("connections.json", lambda d: d[0].pop("direction"))
        self.assertIn("connections.json $[0]: lacks direction", self.messages())
        self.edit("connections.json", lambda d: d[0].update(direction="read", grant_value="abc"))
        self.assertIn("connections.json $[0].grant_value: is not a key of this file's schema", self.messages())

    def test_a_variant_must_be_declared(self):
        self.edit("connections.json", lambda d: d[1].update(variants=["edge"]))
        self.assertIn('connections.json $: names variant "edge" that TEMPLATE.md does not declare', self.messages())
        self.edit("connections.json", lambda d: d[1].update(variants=["cloud"]))
        self.edit("manifest.json", lambda d: d["variants"].update(edge={"placement": "edge"}))
        self.assertIn("manifest.json $.variants.edge: is not a variant TEMPLATE.md declares", self.messages())

    def test_manifest_parts_sit_at_the_top_or_in_every_variant(self):
        self.edit("manifest.json", lambda d: d["variants"]["local"].pop("placement"))
        self.assertIn("manifest.json $: lacks placement, at the top or in variants local", self.messages())
        self.edit("manifest.json", lambda d: d.pop("variants"))
        self.assertIn("manifest.json $: lacks placement", self.messages())
        self.edit("manifest.json", lambda d: d.update(placement={"per": "organization"}, budget=None))
        self.assertIn("manifest.json $.budget: must be object or string", self.messages())

    def test_a_contract_protocol_names_what_it_was_checked_against(self):
        self.edit("manifest.json", lambda d: d["contract"]["service"].pop("checked_against"))
        self.assertTrue(any("manifest.json $.contract" in m and "checked_against" in m for m in self.messages()))

    def test_access_has_the_four_levels_and_nobody_above_the_owner(self):
        self.edit("access.json", lambda d: d["levels"]["owner"].update(escalates=["ask someone"]))
        self.assertIn("access.json $.levels.owner.escalates: must hold at most 0 item(s)", self.messages())
        self.edit("access.json", lambda d: d["levels"].pop("member"))
        self.assertIn("access.json $.levels: lacks member", self.messages())
        self.edit("access.json", lambda d: d.update({"x-household": "a template's own note"}))
        self.assertNotIn("x-household", " ".join(self.messages()))

    def test_data_rooms_name_blocks_and_access(self):
        self.edit("data-rooms.json", lambda d: d[0].update(blocks=[]))
        self.assertIn("data-rooms.json $[0].blocks: needs at least 1 item(s)", self.messages())
        self.edit("data-rooms.json", lambda d: d[0].update(blocks=["answers"], access="everything"))
        self.assertTrue(any("data-rooms.json $[0].access: must be one of" in m for m in self.messages()))

    def test_older_spellings_are_errors_and_warnings_under_legacy(self):
        self.put("connections.json", [
            {"class": "knowledge base", "connector": "c", "grant": "g", "required": "optional, when asked",
             "mode": "read and write (its own pages)", "variant": "cloud, local"}])
        self.put("access.json", {
            "owner": {"withoutAsking": ["x"], "withApproval": [], "escalates": []},
            "administrator": {"without_asking": [], "with_approval": [], "escalates": []},
            "project architect": {"without_asking": [], "with_approval": [], "escalates": []},
            "member": {"without_asking": [], "with_approval": [], "escalates": []},
            "never_by_any_level": ["send outside"], "household": "a note"})
        self.put("data-rooms.json", [{"room": "r", "block": "b", "access": "read and write by pull request"}])
        self.edit("manifest.json", lambda d: d.update(spend=d.pop("budget")) or d["contract"]["service"].update(
            checkedAgainst=d["contract"]["service"].pop("checked_against")))
        strict = self.messages()
        self.assertTrue(strict)
        self.assertEqual(self.errors(legacy=True), [], self.messages(legacy=True))
        warnings = self.messages(legacy=True, level="warning")
        for expected in ("connections.json $[0].class: write source_class",
                         'connections.json $[0].mode: write direction: "read-write", scope: "read and write (its own pages)"',
                         "connections.json $[0].required: write required as true or false, the condition in when",
                         "connections.json $[0].variant: write variants as a list of variant ids",
                         "access.json $: put the levels under levels",
                         "access.json $.levels.project architect: write project_architect",
                         "access.json $.levels.owner.withoutAsking: write without_asking",
                         "access.json $.never_by_any_level: write never",
                         "access.json $.household: a key of this template's own: write x-household",
                         "data-rooms.json $[0].block: write blocks as a list",
                         "manifest.json $.spend: write budget",
                         "manifest.json $.contract.service.checkedAgainst: write checked_against"):
            self.assertIn(expected, warnings)

    def test_a_gap_no_rewrite_fills_is_a_warning_only_under_legacy(self):
        self.edit("connections.json", lambda d: d[0].pop("direction"))
        self.assertIn("connections.json $[0]: lacks direction", self.messages())
        self.assertEqual(self.errors(legacy=True), [])
        self.assertIn("connections.json $[0]: lacks direction; required from schema 1 on",
                      self.messages(legacy=True, level="warning"))

    def test_every_variant_is_left_out_under_legacy(self):
        self.edit("connections.json", lambda d: d[1].update(variants=["all"]))
        self.assertEqual(self.errors(legacy=True), [])
        self.assertIn("connections.json $[1].variants: every variant: leave variants out",
                      self.messages(legacy=True, level="warning"))

    def test_the_command_line(self):
        out = subprocess.run([sys.executable, str(SCRIPT), "--json", str(EXAMPLE)], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), {"ok": True, "folders": {str(EXAMPLE): []}})
        (self.folder / "assembly.md").unlink()
        out = subprocess.run([sys.executable, str(SCRIPT), str(self.folder)], capture_output=True, text=True)
        self.assertEqual(out.returncode, 1)
        self.assertIn("error assembly.md $: is missing", out.stdout)
        self.assertEqual(subprocess.run([sys.executable, str(SCRIPT)], capture_output=True).returncode, 2)
        self.assertEqual(subprocess.run([sys.executable, str(SCRIPT), "--strict", str(EXAMPLE)],
                                        capture_output=True).returncode, 2)


class Schemas(unittest.TestCase):
    def test_every_schema_is_2020_12_and_uses_only_what_the_check_reads(self):
        names = sorted(p.name for p in SCHEMAS.glob("*.schema.json"))
        self.assertEqual(names, ["access.schema.json", "connections.schema.json", "data-rooms.schema.json",
                                 "manifest.schema.json", "template-header.schema.json"])
        for name in names:
            with self.subTest(name=name):
                schema = json.loads((SCHEMAS / name).read_text())
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertTrue(schema["$id"].endswith("/schemas/template/" + name))
                self.assertEqual(keywords(schema, set()) - KEYWORDS, set())

    def test_the_header_reader(self):
        header = tc.read_header("---\ntemplate:\n  id: a-b  # comment\n  variants: [x, y]\n  sources: 3\n"
                                "  name: \"A: b\"\n---\nbody\n")
        self.assertEqual(header, {"template": {"id": "a-b", "variants": ["x", "y"], "sources": 3, "name": "A: b"}})
        for text, says in (("no\n", "does not start"), ("---\ntemplate:\n  id: a\n", "not closed"),
                           ("---\nnot a key\n---\n", "is not `key: value`"),
                           ("---\ntemplate:\n  variants: [a,\n---\n", "list is not closed")):
            with self.subTest(text=text), self.assertRaises(ValueError) as caught:
                tc.read_header(text)
            self.assertIn(says, str(caught.exception))


if __name__ == "__main__":
    unittest.main()


TEMPLATES = SKILL / "templates"
REFERENCE = SKILL / "references/communication-agent-template.md"


class ShippedTemplates(unittest.TestCase):
    """FAA-265: the communication agent template moved from one reference into its folder, which passes the check."""

    def test_every_shipped_template_folder_passes_without_legacy(self):
        folders = sorted(p for p in TEMPLATES.iterdir() if p.is_dir())
        self.assertIn(TEMPLATES / "communication-agent", folders)
        for folder in folders:
            with self.subTest(folder=folder.name):
                self.assertEqual(tc.check_folder(folder), [])

    def test_the_prompt_lives_in_the_folder_and_the_reference_points_at_it(self):
        template = (TEMPLATES / "communication-agent/TEMPLATE.md").read_text(encoding="utf-8")
        reference = REFERENCE.read_text(encoding="utf-8")
        for section in ("## 0. The brief", "## 3. The inbound pipeline", "## 9. Acceptance"):
            with self.subTest(section=section):
                self.assertIn(section, template)
                self.assertNotIn(section, reference)
        self.assertIn("../templates/communication-agent/TEMPLATE.md", reference)
        self.assertIn("../../references/communication-agent-template.md", template)

    def test_the_reference_names_the_database_question_as_open_for_its_owner(self):
        reference = " ".join(REFERENCE.read_text(encoding="utf-8").split())
        self.assertIn("Open for the agents database's owner (FAA-265)", reference)
        self.assertIn("one source holds each kind of agent", reference)

    def test_the_folder_check_runs_from_the_command_line(self):
        run = subprocess.run([sys.executable, str(SCRIPT), "--json", str(TEMPLATES / "communication-agent")],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(json.loads(run.stdout)["ok"])
