"""CO-193: pin-specific gates, including real compiled contract schemas."""
import json
import argparse
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from test_adapt_project import ADAPTER, ROOT, scaffold_args

OLD = '2ce392291c6668598d12cd38327e24696b5ca15c'
NEW = '78b2da018d2c4bd9ac1bde1dc3b7f1a110a175f5'
DEC31 = '623bf61358c339cb10297807b3f024b5d9f1f327'  # DEC-0025…0031; bundles issued under it stay valid
PREVIOUS = '23f9fda4c05f8a3852246ee98d4f2adf74ed0875'  # DEC-0024; bundles issued under it stay valid
PRIOR = '9091d3d6606b0c4b5591a38c3674356a01fd7f55'  # DEC-0021
EARLIER = 'df55c8c54a23251342a7ee57ba95642b7eb39e61'  # DEC-0020
FIXTURES = ROOT / 'test/fixtures/contract-revisions/legacy'


class RevisionTests(unittest.TestCase):
    def test_default_is_new_and_supported_revisions_are_immutable(self):
        self.assertEqual(ADAPTER.CONTRACT_COMMIT, NEW)
        self.assertEqual(ADAPTER.SUPPORTED_CONTRACT_COMMITS, (NEW, DEC31, PREVIOUS, PRIOR, EARLIER, OLD))

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
                     'NOT_RUN: set FABRIC_CONTRACT_OLD and FABRIC_CONTRACT_NEW to exact installed checkouts')
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
