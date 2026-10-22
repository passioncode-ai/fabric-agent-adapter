"""CO-193: pin-specific gates, including real compiled contract schemas."""
import json
import argparse
import os
import re
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from test_adapt_project import ADAPTER, ROOT, scaffold_args

OLD = '2ce392291c6668598d12cd38327e24696b5ca15c'
NEW = 'bfa9a67aa3c6cb808c093e7d83cd59799f1ee7d0'
DEC95 = 'c55f2d5a11c9a0197e958e87212fca7ae1154769'  # DEC-0089…0095 (0.39.0…0.42.1); bundles issued under it stay valid
DEC88 = '07042181bfae2a481aa0da1a5651f24c76669c48'  # DEC-0084…0088 (0.36.0…0.37.1); bundles issued under it stay valid
DEC83 = 'd8146cfb0a1c74fc6432284c4356bb0c864b37b5'  # DEC-0083 (0.34.0…0.35.4); bundles issued under it stay valid
DEC82 = '82e163665e156a08aa3b92e4711015582c06162c'  # DEC-0082 (0.33.0); bundles issued under it stay valid
DEC79 = '1636fa97262f4a26e2086572d540c2ee701e0010'  # DEC-0079…0081 (0.32.0); bundles issued under it stay valid
DEC78 = 'f00a7685e3861c27f7899c033fb850a145a1708f'  # DEC-0078 (0.27.0…0.31.0); bundles issued under it stay valid
DEC77 = 'a046f57cf46ea9e3da57ff8ce6a3ed4d26d8774b'  # DEC-0076/0077 (0.25.0…0.27.0); bundles issued under it stay valid
DEC57 = 'fe55fc67cba1a9e34a736da7d148d4fe2a8fbfa0'  # DEC-0057…0075 (0.23.0, 0.27.0); bundles issued under it stay valid
DEC55 = 'b291bf09e0a9f9fd3c16cf540832cd021203b7d1'  # DEC-0055 (estate-record/1, 0.21.0); bundles issued under it stay valid
DEC46 = '0cacd08b0e95b6abf131eae1206b60792138bc3c'  # DEC-0046 and FAA-22/23 era; bundles issued under it stay valid
DEC45 = '2eb91c00e852d9c31d804310d38fad91589fcbac'  # DEC-0041…0045; bundles issued under it stay valid
DEC39 = '8e49fbd5fbbf230e32c1969cd24ac3c22422f0a5'  # DEC-0039; bundles issued under it stay valid
DEC36 = 'a83bec6b47776af688402c18efec507143061f68'  # DEC-0036; bundles issued under it stay valid
DEC35 = '52da526d7cc1e063d74c5b520dbc03d0ace15246'  # DEC-0034, DEC-0035; bundles issued under it stay valid
DEC33 = '78b2da018d2c4bd9ac1bde1dc3b7f1a110a175f5'  # DEC-0032, DEC-0033; bundles issued under it stay valid
DEC31 = '623bf61358c339cb10297807b3f024b5d9f1f327'  # DEC-0025…0031; bundles issued under it stay valid
PREVIOUS = '23f9fda4c05f8a3852246ee98d4f2adf74ed0875'  # DEC-0024; bundles issued under it stay valid
PRIOR = '9091d3d6606b0c4b5591a38c3674356a01fd7f55'  # DEC-0021
EARLIER = 'df55c8c54a23251342a7ee57ba95642b7eb39e61'  # DEC-0020
FIXTURES = ROOT / 'test/fixtures/contract-revisions/legacy'


class RevisionTests(unittest.TestCase):
    def test_default_is_new_and_supported_revisions_are_immutable(self):
        self.assertEqual(ADAPTER.CONTRACT_COMMIT, NEW)
        self.assertEqual(ADAPTER.SUPPORTED_CONTRACT_COMMITS, (NEW, DEC95, DEC88, DEC83, DEC82, DEC79, DEC78, DEC77, DEC57, DEC55, DEC46, DEC45, DEC39, DEC36, DEC35, DEC33, DEC31, PREVIOUS, PRIOR, EARLIER, OLD))

    def test_complete_issued_legacy_bundles_remain_locally_valid(self):
        for profile in ('mcp', 'a2a', 'local-runner'):
            result = ADAPTER.check_project(FIXTURES / profile, None)
            self.assertEqual(result['gates']['localStructure']['status'], 'PASS')
            self.assertFalse(result['readyForAdmission'])

    def test_bad_locks_never_invoke_schema_validator(self):
        for field, value in [('commit', 'a' * 40), ('commit', NEW.upper()),
                             ('commit', None), ('repository', 'https://evil.example/contract'),
                             ('version', '0.2.0'), ('contract', 'forged-contract')]:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                ADAPTER.scaffold_project(root, scaffold_args('mcp'))
                lockpath = root / 'fabric-contract.lock.json'
                lock = json.loads(lockpath.read_text()); lock[field] = value
                lockpath.write_text(json.dumps(lock))
                with patch.object(ADAPTER, '_contract_shape', return_value=('PASS', [])) as validator:
                    result = ADAPTER.check_project(root, root)
                self.assertEqual(result['gates']['localStructure']['status'], 'FAIL')
                self.assertEqual(result['gates']['declarationShape']['status'], 'FAIL')
                validator.assert_not_called()

    def test_nonobject_lock_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); ADAPTER.scaffold_project(root, scaffold_args('mcp'))
            (root / 'fabric-contract.lock.json').write_text('[]')
            self.assertEqual(ADAPTER.check_project(root, None)['gates']['localStructure']['status'], 'FAIL')

    def test_missing_dependencies_are_not_run(self):
        with patch.object(ADAPTER.subprocess, 'run') as run:
            run.side_effect = [argparse.Namespace(stdout=NEW), argparse.Namespace(stdout='')]
            with tempfile.TemporaryDirectory() as temp:
                status, _ = ADAPTER._contract_shape(Path(temp) / 'manifest.json', Path(temp), NEW)
        self.assertEqual(status, 'NOT_RUN')

    def test_dirty_schema_cannot_pass_the_selected_pin(self):
        with patch.object(ADAPTER.subprocess, 'run') as run:
            run.side_effect = [argparse.Namespace(stdout=NEW),
                               argparse.Namespace(stdout=' M schemas/common.schema.json')]
            with tempfile.TemporaryDirectory() as temp:
                status, receipts = ADAPTER._contract_shape(Path(temp) / 'manifest.json', Path(temp), NEW)
        self.assertEqual(status, 'FAIL')
        self.assertIn('modifications', receipts[0])

    def test_absent_checkout_does_not_admit(self):
        result = ADAPTER.check_project(FIXTURES / 'mcp', Path('/does-not-exist-contract'))
        self.assertEqual(result['gates']['declarationShape']['status'], 'NOT_RUN')
        self.assertFalse(result['readyForAdmission'])


@unittest.skipUnless(os.environ.get('FABRIC_CONTRACT_OLD') and os.environ.get('FABRIC_CONTRACT_NEW'),
                     'NOT_RUN: set FABRIC_CONTRACT_OLD to an installed checkout of %s (the legacy fixtures) and '
                     'FABRIC_CONTRACT_NEW to one of %s (the pin)' % (OLD, NEW))
class CompiledRevisionTests(unittest.TestCase):
    def setUp(self):
        self.old = Path(os.environ['FABRIC_CONTRACT_OLD'])
        self.new = Path(os.environ['FABRIC_CONTRACT_NEW'])

    def assertShape(self, root, contract, expected):
        result = ADAPTER.check_project(root, contract)
        self.assertEqual(result['gates']['declarationShape']['status'], expected, result)
        self.assertFalse(result['readyForAdmission'], 'generated placeholders are never admission')

    def test_complete_legacy_all_profiles_against_old_schema(self):
        for profile in ('mcp', 'a2a', 'local-runner'):
            self.assertShape(FIXTURES / profile, self.old, 'PASS')

    def test_current_all_profiles_and_legacy_names(self):
        for profile in ('mcp', 'a2a', 'local-runner'):
            for name in ('demo.run', 'receive_project_message', 'ab', 'a' * 128):
                with self.subTest(profile=profile, name=name), tempfile.TemporaryDirectory() as temp:
                    args = scaffold_args(profile); args.capability_name = name
                    ADAPTER.scaffold_project(Path(temp), args)
                    self.assertShape(Path(temp), self.new, 'PASS')

    def test_declared_effects_and_cost_presets_meet_the_pinned_schema(self):
        """FAA-25: what the scaffolder now writes (effect, idempotency, costPresets) is valid under the pin."""
        for effect in ('none', 'publish', 'charge'):
            with self.subTest(effect=effect), tempfile.TemporaryDirectory() as temp:
                args = scaffold_args('mcp'); args.effect = effect; args.idempotency = 'required'
                args.cost_preset = [['quick', '0.5', 'Quick'], ['deep', '3', 'Deep']]; args.default_cost_preset = 'quick'
                ADAPTER.scaffold_project(Path(temp), args)
                self.assertShape(Path(temp), self.new, 'PASS')

    def test_revision_mismatch_cannot_upgrade_or_downgrade(self):
        self.assertShape(FIXTURES / 'mcp', self.new, 'FAIL')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); ADAPTER.scaffold_project(root, scaffold_args('mcp'))
            self.assertShape(root, self.old, 'FAIL')

    def test_underscores_and_invalid_names_are_rejected_by_exact_schema(self):
        for revision, contract in ((OLD, self.old), (NEW, self.new)):
            names = ['_leading', 'bad space', 'a' * 129, '', 'a', 'Uppercase']
            if revision == OLD:
                names.append('receive_project_message')
            for name in names:
                with self.subTest(revision=revision, name=name), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp); ADAPTER.scaffold_project(root, scaffold_args('mcp'))
                    lockpath = root / 'fabric-contract.lock.json'
                    lock = json.loads(lockpath.read_text());lock['commit'] = revision
                    lockpath.write_text(json.dumps(lock))
                    path = root / 'fabric-agent.json';value = json.loads(path.read_text())
                    value['capabilities'][0]['name'] = name
                    path.write_text(json.dumps(value))
                    self.assertShape(root, contract, 'FAIL')

    def test_the_kit_schemas_carry_the_patterns_of_the_pinned_contract(self):
        """FAA-95: the kit ships closed copies of two contract schemas (their $ref targets inlined). Every pattern in a
        copy must be a pattern of that schema or of a schema its $ref closure reaches at the pin, so a contract fix to
        a pattern (DEC-0097 replaced `.` with `[\\s\\S]`) cannot stay behind in the kit."""
        kit = ROOT / 'plugins/fabric-agent-adapter/skills/building-fabric-services/scripts'
        schemas = self.new / 'schemas'

        def patterns(value, found):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == 'pattern' and isinstance(item, str):
                        found.add(item)
                    patterns(item, found)
            elif isinstance(value, list):
                for item in value:
                    patterns(item, found)
            return found

        def closure(name, seen):
            if name in seen:
                return seen
            seen.add(name)
            text = (schemas / name).read_text()
            for ref in set(re.findall(r'"\$ref":\s*"([^"#]+)(?:#|")', text)):
                closure(ref, seen)
            return seen

        for name in ('fabric-package.schema.json', 'share-registration.schema.json'):
            with self.subTest(schema=name):
                allowed = set()
                for reached in closure(name, set()):
                    patterns(json.loads((schemas / reached).read_text()), allowed)
                shipped = patterns(json.loads((kit / name).read_text()), set())
                self.assertEqual(sorted(shipped - allowed), [], 'patterns the pinned contract does not carry')

    def test_the_backup_secret_names_are_the_pinned_schema_patterns(self):
        """FAA-95: the settings backup kit writes the schema's two secret-name patterns by hand (DEC-0097 replaced
        `.` with `[\\s\\S]` in both); each twin's regex text equals the pinned schema's (Python spells `$` as `\\Z`)."""
        schema = json.loads((self.new / 'schemas/settings-backup.schema.json').read_text())
        patterns = set()
        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == 'pattern' and '[Tt]oken' in item or key == 'pattern' and 'login_codes' in item:
                        patterns.add(item)
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(schema)
        self.assertEqual(len(patterns), 2)
        kit = ROOT / 'plugins/fabric-agent-adapter/skills/building-fabric-services/scripts'
        python = (kit / 'fabric_backups.py').read_text()
        node = (kit / 'fabric-backups.mjs').read_text()
        for pattern in sorted(patterns):
            with self.subTest(pattern=pattern):
                self.assertIn('r"%s\\Z")' % pattern[:-1], python)
                self.assertIn('/%s/;' % pattern, node)
