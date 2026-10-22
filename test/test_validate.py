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
import tempfile
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
        files = sorted(p for p in ROOT.rglob("SKILL.md") if validate.in_this_tree(p, ROOT))
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

    def test_an_em_dash_in_text_people_read_fails(self):  # FAA-64: the operator's rule, held here
        for rel in ("README.md", "plugins/fabric-agent-adapter/skills/building-fabric-services/references/usage.md",
                    "test/evals/building-fabric-services/scenarios.json", "install.sh", "bin/fabric-agent-adapter.js",
                    "plugins/fabric-agent-adapter/skills/building-fabric-services/assets/dashboard-kit/demo.html",
                    ".github/workflows/release.yml", ".github/pull_request_template.md"):  # R6: .github too (FAA-73)
            def mutate(copy, rel=rel):
                path = copy / rel
                path.write_text(path.read_text(encoding="utf-8").replace("the", "the \u2014", 1), encoding="utf-8")
            with self.subTest(rel):
                code, out = self._validate_copy(mutate)
                self.assertNotEqual(code, 0, out)
                self.assertIn("%s:" % rel, out)
                self.assertIn("U+2014", out)

    def test_release_state_in_the_readme_fails(self):  # FAA-64: README said 0.21.0 until 0.39.1
        for sentence in ("This source checkout is 0.1.0.", "0.1.0 is the latest published npm release."):
            def mutate(copy, sentence=sentence):
                path = copy / "README.md"
                path.write_text(path.read_text(encoding="utf-8") + "\n" + sentence + "\n", encoding="utf-8")
            with self.subTest(sentence):
                code, out = self._validate_copy(mutate)
                self.assertNotEqual(code, 0, out)
                self.assertIn("release state", out)

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


class TextForPeopleTests(unittest.TestCase):
    """FAA-52: a new agent that writes text for people carries the no-em-dash rule (U+2014) in its
    prompt and a check that fails on it, from the grill, the resilience reference and an eval."""

    _validate_copy = LicenseTests._validate_copy
    SKILL = "plugins/fabric-agent-adapter/skills/creating-fabric-agents"

    def _drop(self, rel, needle):
        def mutate(copy):
            path = copy / rel
            path.write_text(path.read_text(encoding="utf-8").replace(needle, "a dash"), encoding="utf-8")
        return self._validate_copy(mutate)

    def test_a_grill_without_the_rule_fails(self):
        code, out = self._drop(self.SKILL + "/SKILL.md", "U+2014")
        self.assertEqual(code, 1)
        self.assertIn("creating-fabric-agents: SKILL.md's grill must ask whether the agent writes text people read", out)

    def test_a_resilience_reference_without_the_rule_fails(self):
        code, out = self._drop(self.SKILL + "/references/resilience-and-autonomy.md", "U+2014")
        self.assertEqual(code, 1)
        self.assertIn("creating-fabric-agents: resilience-and-autonomy.md must state the no-em-dash rule", out)

    def test_evals_without_the_scenario_fail(self):
        code, out = self._drop("test/evals/creating-fabric-agents/scenarios.json", "text-for-people-carries-no-em-dash")
        self.assertEqual(code, 1)
        self.assertIn("creating-fabric-agents: scenarios.json must cover text for people", out)


class KnowledgePackTests(unittest.TestCase):
    """FAA-58: a new agent starts from what the estate learned: where it runs (contexts, clouds), which models and
    keys, how it orchestrates and learns, and the practices production agents taught us."""

    _validate_copy = LicenseTests._validate_copy
    SKILL = "plugins/fabric-agent-adapter/skills/creating-fabric-agents"

    def _replace(self, rel, needle, by="a question"):
        def mutate(copy):
            path = copy / rel
            path.write_text(path.read_text(encoding="utf-8").replace(needle, by), encoding="utf-8")
        return self._validate_copy(mutate)

    def test_a_grill_without_where_it_runs_fails(self):
        code, out = self._replace(self.SKILL + "/SKILL.md", "Where does it run, for whom?")
        self.assertEqual(code, 1)
        self.assertIn("creating-fabric-agents: SKILL.md's grill must ask where it runs, which models, who pays and how it learns", out)

    def test_a_skill_that_does_not_link_a_knowledge_reference_fails(self):
        code, out = self._replace(self.SKILL + "/SKILL.md", "](references/models-and-providers.md)", "]()")
        self.assertEqual(code, 1)
        self.assertIn("creating-fabric-agents: SKILL.md must link references/models-and-providers.md", out)

    def test_a_reference_without_its_checklist_fails(self):
        code, out = self._replace(self.SKILL + "/references/where-agents-run.md", "## The checklist", "## The end")
        self.assertEqual(code, 1)
        self.assertIn("creating-fabric-agents: references/where-agents-run.md must end with its checklist", out)

    def test_evals_without_the_cloud_scenario_fail(self):
        code, out = self._replace("test/evals/creating-fabric-agents/scenarios.json", "agent-for-a-personal-and-an-organization-cloud", "x")
        self.assertEqual(code, 1)
        self.assertIn("creating-fabric-agents: scenarios.json must cover an agent for clouds and models", out)


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

    def test_legacy_pin_in_another_live_file_is_not_an_exception(self):
        def mutate(copy):
            with (copy / "README.md").open("a") as note:
                note.write('\nLegacy contract: 2ce392291c6668598d12cd38327e24696b5ca15c\n')
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1, out)
        self.assertIn("README.md", out)

    def test_allowlist_cannot_be_expanded_or_forged(self):
        def mutate(copy):
            script = copy / validate.PIN_ADAPTER
            text = script.read_text()
            script.write_text(text.replace('2ce392291c6668598d12cd38327e24696b5ca15c', 'a' * 40))
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1, out)
        self.assertIn("reviewed list", out)

    def test_default_cannot_be_reset_to_supported_legacy(self):
        def mutate(copy):
            script = copy / validate.PIN_ADAPTER
            text = script.read_text()
            script.write_text(text.replace(validate.PIN_SUPPORTED_DECLARATION,
                validate.PIN_SUPPORTED_DECLARATION + '\nCONTRACT_COMMIT = "2ce392291c6668598d12cd38327e24696b5ca15c"'))
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1, out)
        self.assertIn("contract pin", out)

    def test_allowlist_cannot_be_reassigned_dynamically(self):
        def mutate(copy):
            script = copy / validate.PIN_ADAPTER
            with script.open("a") as note:
                note.write('\nSUPPORTED_CONTRACT_COMMITS = tuple()\n')
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1, out)
        self.assertIn("immutable declaration", out)

    def test_local_lease_renewal_file_is_not_distribution_json(self):
        def mutate(copy):
            note = copy / '.agent-sync/renew/run--fabric-contract.lock.json'
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text('123 pid renewal metadata\n')
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 0, out)

    def test_canonical_default_cannot_be_forged(self):
        def mutate(copy):
            path = copy / "fabric-contract.lock.json"
            pin = json.loads(path.read_text()); pin['commit'] = 'a' * 40
            path.write_text(json.dumps(pin))
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1, out)
        self.assertIn("reviewed current revision", out)

    def test_source_repository_constant_must_match_lock(self):
        def mutate(copy):
            script = copy / validate.PIN_ADAPTER
            text = script.read_text()
            script.write_text(text.replace(
                'CONTRACT_REPOSITORY = "https://github.com/passioncode-ai/fabric-agent-contract"',
                'CONTRACT_REPOSITORY = "https://evil.example/contract"'))
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1, out)
        self.assertIn("CONTRACT_REPOSITORY", out)

    def _assert_dynamic_suffix_rejected(self, constant, suffix):
        def mutate(copy):
            script = copy / validate.PIN_ADAPTER
            lines = script.read_text().splitlines()
            script.write_text('\n'.join(line + suffix if line.startswith(constant + ' = ')
                                        else line for line in lines) + '\n')
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1, out)
        self.assertIn(constant, out)

    def test_contract_commit_dynamic_suffix_is_rejected(self):
        self._assert_dynamic_suffix_rejected('CONTRACT_COMMIT', ' + "bad"')

    def test_contract_version_dynamic_suffix_is_rejected(self):
        self._assert_dynamic_suffix_rejected('CONTRACT_VERSION', ' + "bad"')

    def test_contract_repository_dynamic_suffix_is_rejected(self):
        self._assert_dynamic_suffix_rejected('CONTRACT_REPOSITORY', ' + "/forged"')

    def test_pin_bindings_cannot_be_changed_by_alternative_writes(self):
        mutations = [
            'CONTRACT_VERSION += "bad"',
            'del CONTRACT_VERSION',
            'CONTRACT_VERSION: str = "0.1.0"',
            'def CONTRACT_VERSION():\n    return "0.1.0"',
            'globals()["CONTRACT_VERSION"] = "bad"',
            'namespace = globals\nnamespace()["CONTRACT_VERSION"] = "bad"',
            'exec("CONTRACT_VERSION = chr(120)")',
            'sys.modules[__name__].CONTRACT_VERSION = "bad"',
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                def mutate(copy):
                    script = copy / validate.PIN_ADAPTER
                    with script.open('a') as out:
                        out.write('\n' + mutation + '\n')
                code, out = self._validate_copy(mutate)
                self.assertEqual(code, 1, out)
                self.assertIn('contract pin', out)

    def test_semicolon_reassignment_and_chained_assignment_are_rejected(self):
        self._assert_dynamic_suffix_rejected('CONTRACT_VERSION', '; CONTRACT_VERSION = "bad"')
        def mutate(copy):
            script = copy / validate.PIN_ADAPTER
            script.write_text(script.read_text().replace(
                'CONTRACT_VERSION = "0.1.0"', 'other = CONTRACT_VERSION = "0.1.0"'))
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1, out)
        self.assertIn('plain top-level assignment', out)

    @unittest.skipUnless(sys.version_info >= (3, 10), 'match bindings require Python 3.10+')
    def test_pattern_capture_cannot_replace_pin_binding(self):
        def mutate(copy):
            script = copy / validate.PIN_ADAPTER
            with script.open('a') as out:
                out.write('\nmatch "bad":\n    case CONTRACT_VERSION:\n        pass\n')
        code, out = self._validate_copy(mutate)
        self.assertEqual(code, 1, out)
        self.assertIn('immutable declaration', out)

    def test_a_link_to_a_dated_handoff_is_not_a_pin_but_the_same_hash_in_prose_is(self):
        import tempfile
        old = "52da526d7cc1e063d74c5b520dbc03d0ace15246"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "docs").mkdir()
            (root / "docs/backlog.md").write_text("| FAA-x | the contract pin moved | [handoff](handoffs/2026-10-10-contract-pin-52da526.md) |\n")
            self.assertEqual(validate.contract_pin_drift(root, "a" * 40), [])
            (root / "docs/backlog.md").write_text("| FAA-x | the contract pin moved to `52da526` | [handoff](handoffs/x.md) |\n")
            self.assertEqual(len(validate.contract_pin_drift(root, "a" * 40)), 1)
            self.assertEqual(validate.contract_pin_drift(root, old), [])

    def test_exact_source_literals_match_runtime_and_default_bundle(self):
        from test_adapt_project import ADAPTER, scaffold_args
        import tempfile
        pin = json.loads((ROOT / 'fabric-contract.lock.json').read_text())
        errors = []
        validate.validate_contract_pin(errors)
        self.assertEqual(errors, [])
        self.assertEqual(ADAPTER.CONTRACT_COMMIT, pin['commit'])
        self.assertEqual(ADAPTER.CONTRACT_VERSION, pin['version'])
        self.assertEqual(ADAPTER.CONTRACT_REPOSITORY, pin['repository'])
        with tempfile.TemporaryDirectory() as temp:
            ADAPTER.scaffold_project(Path(temp), scaffold_args('mcp'))
            lock = json.loads((Path(temp) / 'fabric-contract.lock.json').read_text())
            self.assertEqual({key: lock[key] for key in pin}, pin)


class WorktreeTests(unittest.TestCase):
    """FAA-50: a git worktree under `.worktrees/` is another checkout; validating it as this tree failed the main
    checkout whenever a worktree of another branch sat beside it."""

    def test_a_worktree_beside_the_tree_is_not_validated(self):
        root = validate.ROOT
        self.assertFalse(validate.in_this_tree(root / ".worktrees" / "other" / "CHANGELOG.md"))
        self.assertFalse(validate.in_this_tree(root / ".git" / "config"))
        self.assertTrue(validate.in_this_tree(root / "CHANGELOG.md"))
        self.assertTrue(validate.in_this_tree(root / "docs" / "worktrees-notes.md"))

    def test_the_pin_check_skips_a_worktree_with_another_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "README.md").write_text("contract commit at the pin\n")
            other = root / ".worktrees" / "old" / "README.md"
            other.parent.mkdir(parents=True)
            other.write_text("contract commit 0cacd08b0e95b6abf131eae1206b60792138bc3c\n")
            self.assertEqual(validate.contract_pin_drift(root, validate.PIN_DEFAULT_COMMIT), [])
            (root / "NOTES.md").write_text("contract commit 0cacd08b0e95b6abf131eae1206b60792138bc3c\n")
            self.assertTrue(validate.contract_pin_drift(root, validate.PIN_DEFAULT_COMMIT))


class BoardRowTests(unittest.TestCase):
    """The task board's rows split into the header's columns, as the workspace aggregator reads them."""

    TABLE = "| ID | Item | Status | Source |\n|---|---|---|---|\n"

    def test_a_pipe_in_a_cell_is_refused_escaped_or_not(self):
        for cell in ("`--to me\\|person`", "a|b"):
            found = validate.malformed_board_rows(self.TABLE + "| X-1 | %s | open | here |\n" % cell)
            self.assertEqual(len(found), 1, cell)
            self.assertIn("docs/backlog.md:3", found[0])

    def test_a_well_formed_table_passes(self):
        self.assertEqual(validate.malformed_board_rows(self.TABLE + "| X-1 | item | open | here |\n\ntext\n| A | B |\n|---|---|\n| 1 | 2 |\n"), [])

    def test_the_repository_board_is_well_formed(self):
        board = (Path(__file__).resolve().parent.parent / "docs/backlog.md").read_text(encoding="utf-8")
        self.assertEqual(validate.malformed_board_rows(board), [])



if __name__ == "__main__":
    unittest.main()


class PluginLifecycleGateTests(unittest.TestCase):
    """FAA-22 (LC-19) and FAA-23 (LC-21) for the adapter's own plugin."""

    def test_the_plugin_declares_no_mcp_server_and_no_credential_in_a_hook(self):
        import tempfile
        v = validate
        with tempfile.TemporaryDirectory() as temp:
            plugin = Path(temp)
            (plugin / ".claude-plugin").mkdir()
            (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "x"}))
            (plugin / "hooks").mkdir()
            (plugin / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "python3 x.py notice"}]}]}}))
            errors = []
            v.validate_plugin_lifecycle(errors, plugin)
            self.assertEqual(errors, [])
            (plugin / ".mcp.json").write_text(json.dumps({"mcpServers": {"x": {"command": "node"}}}))
            (plugin / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "x --token=" + "s" + "k-" + "z" * 24}]}]}}))
            errors = []
            v.validate_plugin_lifecycle(errors, plugin)
            self.assertTrue(any("LC-19" in e for e in errors), errors)
            self.assertTrue(any("LC-21" in e for e in errors), errors)


class PrivateSourceDeferralTests(unittest.TestCase):
    """A public skill page states its rule; it never defers to fabric-workspace, which its reader cannot open (N-12)."""

    def test_a_paragraph_that_lets_a_private_page_win_is_refused(self):
        text = ("# Page\n\nThis page implements the [contract](https://github.com/passioncode-ai/fabric-workspace/blob/main/"
                "knowledge/lifecycle.md).\nWhere the two differ, the contract wins and this page is the defect.\n")
        found = validate.private_source_deferrals(text)
        self.assertEqual(len(found), 1, found)
        self.assertTrue(found[0].startswith("line 3: "), found)

    def test_that_page_wins_is_refused_too(self):
        text = "The rule lives in fabric-workspace `knowledge/agents-first.md`; where the two differ, that page wins.\n"
        self.assertEqual(len(validate.private_source_deferrals(text)), 1)

    def test_provenance_without_deferral_and_a_deferral_without_a_private_source_pass(self):
        self.assertEqual(validate.private_source_deferrals(
            "Inside PassionCode.ai it implements fabric-workspace `knowledge/lifecycle.md`, cited for provenance.\n"), [])
        self.assertEqual(validate.private_source_deferrals(
            "Where this page and the public specification disagree, the specification wins.\n\n"
            "The operator's intent wins (LC-14).\n"), [])

    def test_every_shipped_skill_page_is_free_of_private_deferrals(self):
        for page in sorted((ROOT / "plugins").rglob("*.md")):
            self.assertEqual(validate.private_source_deferrals(page.read_text(encoding="utf-8")), [], str(page))


def _tree(files):
    """A throwaway tree holding only the given {relative path: text} files."""
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp, root


class DollarAnchorTests(unittest.TestCase):
    """R1 (audit 2026-10-22): `$` also matches before a trailing newline in Python, never in JavaScript, so a
    `$`-anchored whole-value pattern lets the Python twin accept what the Node twin refuses."""

    KIT = "plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/fabric_example.py"
    SESSION = "plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/hosts/example/__init__.py"

    def test_the_hazard_is_real(self):
        import re
        self.assertIsNotNone(re.match(r"^[a-z]+$", "abc\n"))
        self.assertIsNone(re.match(r"^[a-z]+\Z", "abc\n"))

    def test_a_planted_dollar_is_found_in_every_checked_call(self):
        for call in ("compile", "match", "search"):
            with self.subTest(call=call):
                found = validate.dollar_anchored_patterns('import re\nNAME = re.%s(r"^[a-z]+$", "x")\n' % call)
                self.assertEqual(found, [(2, call, "^[a-z]+$")])

    def test_backslash_z_an_escaped_dollar_and_fullmatch_pass(self):
        for source in ('import re\nre.compile(r"^[a-z]+\\Z")\n',
                       'import re\nre.compile(r"price\\$")\n',
                       'import re\nre.fullmatch(r"^[a-z]+$", "x")\n',
                       'import re\nre.sub(r"\\.git$", "", "x")\n',
                       'import re\nre.compile(r"a$b")\n'):
            with self.subTest(source=source):
                self.assertEqual(validate.dollar_anchored_patterns(source), [])

    def test_an_escaped_backslash_before_the_dollar_still_anchors(self):
        self.assertEqual(len(validate.dollar_anchored_patterns('import re\nre.compile(r"a\\\\$")\n')), 1)

    ADAPT = "plugins/fabric-agent-adapter/skills/adapting-projects-to-fabric/scripts/adapt_example.py"
    CREATE = "plugins/fabric-agent-adapter/skills/creating-fabric-agents/scripts/nested/create_example.py"

    def test_the_repository_scan_fails_on_a_planted_pattern_in_every_skill(self):
        """FAA-72: the guard covers every skill's scripts, not only the service kit and working-with-fabric."""
        for rel in (self.KIT, self.SESSION, self.ADAPT, self.CREATE):
            with self.subTest(rel=rel):
                tmp, root = _tree({rel: 'import re\nID = re.compile(r"^[a-z]+$")\n'})
                with tmp:
                    problems = validate.dollar_anchor_problems(root, allow={})
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("%s:2 re.compile" % rel, problems[0])
                self.assertIn("R1", problems[0])

    def test_the_fixed_pattern_passes(self):
        tmp, root = _tree({self.KIT: 'import re\nID = re.compile(r"^[a-z]+\\Z")\n'})
        with tmp:
            self.assertEqual(validate.dollar_anchor_problems(root, allow={}), [])

    def test_an_allowlisted_multiline_use_passes_and_needs_its_reason(self):
        tmp, root = _tree({self.KIT: 'import re\nre.search(r"^x$", "x", re.MULTILINE)\n'})
        with tmp:
            self.assertEqual(validate.dollar_anchor_problems(root, allow={(self.KIT, "^x$"): "multiline"}), [])
            problems = validate.dollar_anchor_problems(root, allow={(self.KIT, "^x$"): " "})
        self.assertTrue(any("has no reason" in p for p in problems), problems)

    def test_a_stale_allowlist_entry_fails(self):
        tmp, root = _tree({self.KIT: 'import re\nre.compile(r"^x\\Z")\n'})
        with tmp:
            problems = validate.dollar_anchor_problems(root, allow={(self.KIT, "^x$"): "converted elsewhere"})
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("matches nothing any more", problems[0])

    def test_the_real_tree_passes_with_the_current_allowlist(self):
        self.assertEqual(validate.dollar_anchor_problems(), [])


class WorkflowGuardTests(unittest.TestCase):
    """R5 and FAA-72/FAA-73: the hosted gates must be able to fail, and the release path must be safe."""

    def _problems(self, rel, edit):
        files = {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8")
                 for p in sorted((ROOT / ".github/workflows").glob("*.yml"))}
        files[rel] = edit(files[rel])
        self.assertNotEqual(files[rel], (ROOT / rel).read_text(encoding="utf-8"), "the edit planted nothing")
        tmp, root = _tree(files)
        with tmp:
            return validate.workflow_problems(root)

    def test_the_real_workflows_pass(self):
        self.assertEqual(validate.workflow_problems(), [])

    def test_a_floating_action_tag_fails(self):
        import re
        problems = self._problems(".github/workflows/release.yml",
                                  lambda t: re.sub(r"actions/checkout@[0-9a-f]{40} # v[0-9.]+", "actions/checkout@v4", t, count=1))
        self.assertTrue(any("moving ref" in p for p in problems), problems)

    def test_a_sha_without_its_version_comment_fails(self):
        import re
        problems = self._problems(".github/workflows/validate.yml",
                                  lambda t: re.sub(r"(actions/setup-node@[0-9a-f]{40}) # v[0-9.]+", r"\1", t, count=1))
        self.assertTrue(any("moving ref" in p for p in problems), problems)

    def test_npm_at_latest_fails(self):
        problems = self._problems(".github/workflows/release.yml",
                                  lambda t: t.replace("npm install -g npm@12.2.0", "npm install -g npm@latest"))
        self.assertTrue(any("@latest" in p for p in problems), problems)

    def test_a_job_without_a_timeout_fails(self):
        problems = self._problems(".github/workflows/validate.yml",
                                  lambda t: t.replace("    timeout-minutes: 10\n", "", 1))
        self.assertTrue(any("timeout-minutes" in p for p in problems), problems)

    def test_the_nightly_and_the_gated_jobs_cannot_be_dropped(self):
        for needle in ("schedule:", "FABRIC_CONTRACT_OLD:", 'python-version: "3.9"', 'node-version: "18"',
                       "runs-on: macos-", "cancel-in-progress: true", '-p "test_fabric_session.py"'):
            with self.subTest(needle=needle):
                problems = self._problems(".github/workflows/validate.yml", lambda t: t.replace(needle, "removed:"))
                self.assertTrue(any(repr(needle) in p for p in problems), problems)

    def test_a_per_push_trigger_fails(self):
        problems = self._problems(".github/workflows/validate.yml",
                                  lambda t: t.replace("  workflow_dispatch:\n", "  workflow_dispatch:\n  push:\n", 1))
        self.assertTrue(any("must not run on push" in p for p in problems), problems)

    def test_a_release_created_before_the_smoke_test_fails(self):
        def swap(text):
            smoke = text.index("      - name: Smoke test before anything is public")
            create = text.index("      - name: Create or refresh the GitHub release")
            tail = text.index("\n  publish:")
            return text[:smoke] + text[create:tail] + "\n" + text[smoke:create] + text[tail:]
        problems = self._problems(".github/workflows/release.yml", swap)
        self.assertTrue(any("before `gh release create`" in p for p in problems), problems)

    def test_an_action_sha_is_not_a_contract_pin_but_any_other_commit_is(self):
        pin = validate.PIN_DEFAULT_COMMIT
        action = "11d5960a326750d5838078e36cf38b85af677262"
        good = "steps:\n  - uses: actions/checkout@%s # v4.4.0\n" % action
        tmp, root = _tree({".github/workflows/x.yml": good})
        with tmp:
            self.assertEqual(validate.contract_pin_drift(root, pin), [])
        bad = good + "  - run: echo %s\n" % action
        tmp, root = _tree({".github/workflows/x.yml": bad})
        with tmp:
            drift = validate.contract_pin_drift(root, pin)
        self.assertEqual(len(drift), 1, drift)
        self.assertIn(".github/workflows/x.yml:3", drift[0])
        tmp, root = _tree({"docs.md": "uses: actions/checkout@%s # v4.4.0\n" % action})
        with tmp:
            self.assertEqual(len(validate.contract_pin_drift(root, pin)), 1, "the exemption is for workflows only")
