"""Unit tests for test/validate.py — the strict SKILL.md front-matter parser first.

A plain (unquoted) YAML scalar cannot carry `: ` or ` #`, cannot end in `:` and
cannot open with an indicator character. Claude Code reads such front matter
leniently; a strict YAML reader rejects it and drops the skill. The validator
must see what the strictest reader sees. Standard library only, like every script
here: an independent PyYAML read is a gate command, not a test dependency.
"""

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fabric_validate", ROOT / "test/validate.py")
validate = importlib.util.module_from_spec(spec)
sys.modules["fabric_validate"] = validate
spec.loader.exec_module(validate)


def front(*lines, body="# Body\n"):
    return "---\n" + "\n".join(lines) + "\n---\n" + body


LEGAL_TAIL = (
    "license: " + validate.LICENSE_SPDX,
    "metadata:",
    '  author: PassionCode.ai',
    '  version: "%s"' % validate.VERSION,
)


def skill(description_lines):
    return front("name: demo-skill", *description_lines, *LEGAL_TAIL)


class StrictPlainScalarTests(unittest.TestCase):
    def assertRejected(self, text, fragment):
        with self.assertRaises(ValueError) as caught:
            validate.parse_frontmatter(text)
        self.assertIn(fragment, str(caught.exception))

    def test_planted_unquoted_colon_space_is_rejected(self):
        text = skill(["description: Use when X. Covers the fabric-service/0.1 extension: which surface. NOT for Y."])
        self.assertRejected(text, "mapping values are not allowed")

    def test_the_error_names_line_and_column(self):
        text = skill(["description: Use when X extension: which. NOT for Y."])
        with self.assertRaises(ValueError) as caught:
            validate.parse_frontmatter(text)
        message = str(caught.exception)
        self.assertIn("line 3", message)  # file line: ---, name, description
        self.assertIn("column %d" % (len("description: Use when X extension") + 1), message)

    def test_trailing_colon_is_rejected(self):
        self.assertRejected(skill(["description: Use when this ends with a colon:"]), "mapping values are not allowed")

    def test_space_hash_starts_a_comment_and_is_rejected(self):
        self.assertRejected(skill(["description: Use when X #1 matters. NOT for Y."]), "comment")

    def test_every_leading_indicator_is_rejected(self):
        for ch in "[{*&!|>'\"%@`,]}#":
            with self.subTest(indicator=ch):
                with self.assertRaises(ValueError):
                    validate.parse_frontmatter(skill(["description: %sUse when X. NOT for Y." % ch]))

    def test_leading_dash_question_colon_followed_by_space_is_rejected(self):
        for ch in "-?:":
            with self.subTest(indicator=ch):
                with self.assertRaises(ValueError):
                    validate.parse_frontmatter(skill(["description: %s Use when X." % ch]))

    def test_leading_dash_without_space_is_plain(self):
        data, _ = validate.parse_frontmatter(skill(["description: -Use when X."]))
        self.assertEqual(data["description"], "-Use when X.")

    def test_nested_values_are_checked_too(self):
        text = front("name: demo-skill", "description: Use when X.", "metadata:", "  note: a: b")
        self.assertRejected(text, "mapping values are not allowed")

    def test_colon_without_space_is_legal_in_a_plain_scalar(self):
        data, _ = validate.parse_frontmatter(skill(["description: Use when https://example.org/a:b fails. NOT for Y."]))
        self.assertEqual(data["description"], "Use when https://example.org/a:b fails. NOT for Y.")

    def test_hash_without_leading_space_is_legal(self):
        data, _ = validate.parse_frontmatter(skill(["description: Use when C# code. NOT for Y."]))
        self.assertEqual(data["description"], "Use when C# code. NOT for Y.")


class BlockAndQuotedScalarTests(unittest.TestCase):
    def test_folded_block_keeps_the_exact_single_line_text(self):
        text = skill(["description: >-", "  Use when X extension: which surface", "  (MCP, CLI) # not a comment. NOT for Y."])
        data, body = validate.parse_frontmatter(text)
        self.assertEqual(data["description"], "Use when X extension: which surface (MCP, CLI) # not a comment. NOT for Y.")
        self.assertEqual(data["license"], validate.LICENSE_SPDX)
        self.assertEqual(body, "# Body\n")

    def test_folded_block_blank_line_is_a_newline(self):
        data, _ = validate.parse_frontmatter(skill(["description: >-", "  one", "", "  two"]))
        self.assertEqual(data["description"], "one\ntwo")

    def test_literal_block_keeps_newlines(self):
        data, _ = validate.parse_frontmatter(skill(["description: |-", "  one: a", "  two"]))
        self.assertEqual(data["description"], "one: a\ntwo")

    def test_clip_chomping_keeps_one_trailing_newline(self):
        data, _ = validate.parse_frontmatter(skill(["description: >", "  one"]))
        self.assertEqual(data["description"], "one\n")

    def test_empty_block_scalar_is_rejected(self):
        with self.assertRaises(ValueError):
            validate.parse_frontmatter(skill(["description: >-"]))

    def test_double_quoted_with_colon_space_is_legal(self):
        data, _ = validate.parse_frontmatter(skill(['description: "Use when X: Y. \\"quoted\\" NOT for Z."']))
        self.assertEqual(data["description"], 'Use when X: Y. "quoted" NOT for Z.')

    def test_single_quoted_doubles_its_quote(self):
        data, _ = validate.parse_frontmatter(skill(["description: 'Use when it''s X: Y.'"]))
        self.assertEqual(data["description"], "Use when it's X: Y.")

    def test_text_after_a_closing_quote_is_rejected(self):
        with self.assertRaises(ValueError):
            validate.parse_frontmatter(skill(['description: "Use when X" and more']))

    def test_unterminated_quote_is_rejected(self):
        with self.assertRaises(ValueError):
            validate.parse_frontmatter(skill(['description: "Use when X']))

    def test_duplicate_key_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            validate.parse_frontmatter(skill(["description: Use when X.", "description: Use when Y."]))
        self.assertIn("duplicate key", str(caught.exception))

    def test_unexpected_indented_continuation_is_rejected(self):
        with self.assertRaises(ValueError):
            validate.parse_frontmatter(skill(["description: Use when X", "  continues here."]))

    def test_unclosed_frontmatter_is_rejected(self):
        with self.assertRaises(ValueError):
            validate.parse_frontmatter("---\nname: demo\n")


class RepositorySkillFilesTests(unittest.TestCase):
    """Every SKILL.md the repository ships must survive the strict reader."""

    def skill_files(self):
        files = sorted(p for p in ROOT.rglob("SKILL.md") if ".git" not in p.parts)
        self.assertEqual(len(files), len(validate.SKILL_NAMES))
        return files

    def test_every_shipped_skill_md_parses_strictly(self):
        for path in self.skill_files():
            with self.subTest(skill=path.parent.name):
                data, _ = validate.parse_frontmatter(path.read_text(encoding="utf-8"))
                self.assertLessEqual(len(data["description"]), 1024)
                self.assertTrue(data["description"].startswith("Use when "))

    def test_cli_frontmatter_mode_rejects_a_planted_file_and_accepts_the_real_ones(self):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            bad = Path(temp) / "SKILL.md"
            bad.write_text(skill(["description: Use when X extension: which. NOT for Y."]), encoding="utf-8")
            run = lambda *paths: subprocess.run([sys.executable, str(ROOT / "test/validate.py"), "--frontmatter", *paths],
                                                capture_output=True, text=True)
            failed = run(str(bad))
            self.assertEqual(failed.returncode, 1, failed.stdout)
            self.assertIn("mapping values are not allowed", failed.stdout)
            passed = run(*(str(p) for p in self.skill_files()))
            self.assertEqual(passed.returncode, 0, passed.stdout)

    def test_repository_validates(self):
        self.assertEqual(validate.validator_self_test() + validate.validate_repo(), [])


class LicenseTests(unittest.TestCase):
    """Fabric ADR-0092: AGPL-3.0-only OR the PassionCode.ai commercial licence, in every file that
    states a licence, with LICENSE, COMMERCIAL-LICENSE.md and CLA.md byte for byte the knowledge
    base templates. A copy of the repository that slips back to PolyForm, or drifts, fails."""

    def _validate_copy(self, mutate):
        import shutil
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "repo"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules"))
            mutate(copy)
            run = subprocess.run([sys.executable, str(copy / "test/validate.py")], capture_output=True, text=True)
            return run.returncode, run.stdout + run.stderr

    def test_the_expression_is_the_organizations(self):
        self.assertEqual(validate.LICENSE_SPDX, "AGPL-3.0-only OR LicenseRef-PassionCode-Commercial")

    def test_the_real_tree_passes_the_license_checks(self):
        code, out = self._validate_copy(lambda copy: None)
        self.assertEqual(code, 0, out)

    def test_an_edited_agpl_text_fails(self):
        def mutate(copy):
            lic = copy / "LICENSE"
            lic.write_text(lic.read_text(encoding="utf-8").replace("GNU AFFERO", "GNU AFERO", 1), encoding="utf-8")
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1)
        self.assertIn("LICENSE is not the AGPL-3.0 template", out)

    def test_a_missing_commercial_license_fails(self):
        code, out = self._validate_copy(lambda copy: (copy / "COMMERCIAL-LICENSE.md").unlink())
        self.assertEqual(code, 1)
        self.assertIn("COMMERCIAL-LICENSE.md", out)

    def test_a_drifted_cla_fails(self):
        def mutate(copy):
            cla = copy / "CLA.md"
            cla.write_text(cla.read_text(encoding="utf-8") + "\nAn extra clause.\n", encoding="utf-8")
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1)
        self.assertIn("CLA.md is not the knowledge base template", out)

    def test_a_source_available_badge_fails(self):
        def mutate(copy):
            readme = copy / "README.md"
            readme.write_text(readme.read_text(encoding="utf-8") + "\n![license](https://img.shields.io/badge/license-source--available-blue.svg)\n", encoding="utf-8")
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1)
        self.assertIn("README.md still states the retired licence", out)

    def test_a_readme_without_the_earlier_versions_sentence_fails(self):
        def mutate(copy):
            readme = copy / "README.md"
            readme.write_text(readme.read_text(encoding="utf-8").replace("Versions before", "Releases before"), encoding="utf-8")
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1)
        self.assertIn("README.md ## License", out)

    def test_a_manifest_back_on_polyform_fails(self):
        def mutate(copy):
            manifest = copy / "plugins/fabric-agent-adapter/.claude-plugin/plugin.json"
            manifest.write_text(manifest.read_text(encoding="utf-8").replace(
                validate.LICENSE_SPDX, "PolyForm-Noncommercial-1.0.0 OR LicenseRef-PolyForm-Internal-Use-1.0.0"), encoding="utf-8")
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1)
        self.assertIn("plugin license is out of sync", out)

    def test_a_package_that_does_not_ship_the_commercial_license_fails(self):
        def mutate(copy):
            pkg = copy / "package.json"
            data = json.loads(pkg.read_text(encoding="utf-8"))
            data["files"] = [f for f in data["files"] if f != "COMMERCIAL-LICENSE.md"]
            pkg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1)
        self.assertIn("package.json files whitelist must ship COMMERCIAL-LICENSE.md", out)

    def test_a_pr_template_without_the_cla_sentence_fails(self):
        code, out = self._validate_copy(lambda copy: (copy / ".github/pull_request_template.md").write_text("## What changes\n", encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertIn("opening the pull request means agreeing to CLA.md", out)

    def test_a_pr_template_with_a_cla_checkbox_fails(self):
        def mutate(copy):
            p = copy / ".github/pull_request_template.md"
            p.write_text(p.read_text(encoding="utf-8") + "\n- [ ] I agree to CLA.md for this contribution.\n", encoding="utf-8")
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1)
        self.assertIn("must not ask anyone to tick a CLA checkbox", out)


class RepositoryStandardTests(unittest.TestCase):
    """Each skill tells the repository it builds to follow the PassionCode.ai repository standard,
    and says that an agent someone builds for themselves is outside it."""

    _validate_copy = LicenseTests._validate_copy

    def test_a_skill_that_drops_the_standard_fails(self):
        def mutate(copy):
            skill = copy / "plugins/fabric-agent-adapter/skills/building-fabric-services/SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8").replace("knowledge/repository-standard.md", "knowledge/"), encoding="utf-8")
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1)
        self.assertIn("building-fabric-services: SKILL.md must send a PassionCode.ai repository to the repository standard", out)

    def test_a_skill_that_forgets_the_owners_choice_fails(self):
        def mutate(copy):
            skill = copy / "plugins/fabric-agent-adapter/skills/creating-fabric-agents/SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8").replace("its owner's", "the organization's"), encoding="utf-8")
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1)
        self.assertIn("creating-fabric-agents: SKILL.md must say an agent someone builds for themselves", out)


class PinTests(unittest.TestCase):
    """G-11: one contract pin. fabric-contract.lock.json is it; every live mention equals it."""

    _validate_copy = LicenseTests._validate_copy

    def test_a_readme_naming_another_contract_commit_fails(self):
        def mutate(copy):
            readme = copy / "README.md"
            readme.write_text(readme.read_text(encoding="utf-8") + "\nBuilt against fabric-agent-contract `20a818e648a4c09a60df0126d11626922e8b9094`.\n", encoding="utf-8")
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1)
        self.assertIn("contract pin", out)
        self.assertIn("README.md", out)

    def test_a_script_constant_off_the_pin_fails(self):
        def mutate(copy):
            script = copy / "plugins/fabric-agent-adapter/skills/adapting-projects-to-fabric/scripts/adapt_project.py"
            text = script.read_text(encoding="utf-8")
            pin = json.loads((copy / "fabric-contract.lock.json").read_text())["commit"]
            script.write_text(text.replace(pin, "a5a27092ba0dcc5facfbeae8b359146dfb403e9a"), encoding="utf-8")
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1)
        self.assertIn("adapt_project.py", out)

    def test_a_full_commit_in_any_wording_must_be_the_pin(self):
        def mutate(copy):
            skill = copy / "plugins/fabric-agent-adapter/skills/building-fabric-services/SKILL.md"
            pin = json.loads((copy / "fabric-contract.lock.json").read_text())["commit"]
            skill.write_text(skill.read_text(encoding="utf-8").replace(pin, "20a818e648a4c09a60df0126d11626922e8b9094", 1), encoding="utf-8")
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1)
        self.assertIn("building-fabric-services/SKILL.md", out)

    def test_a_missing_lock_fails(self):
        code, out = self._validate_copy(lambda copy: (copy / "fabric-contract.lock.json").unlink())
        self.assertEqual(code, 1)
        self.assertIn("fabric-contract.lock.json", out)

    def test_dated_records_keep_the_revision_of_their_day(self):
        def mutate(copy):
            note = copy / "docs/handoffs/2026-01-01-old.md"
            note.write_text("Contract pin was `20a818e648a4c09a60df0126d11626922e8b9094`.\n", encoding="utf-8")
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 0, out)

if __name__ == "__main__":
    unittest.main()
