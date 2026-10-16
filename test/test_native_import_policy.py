"""A native host import exception must not weaken the shipped stdlib boundary."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('native_import_validator', Path(__file__).with_name('validate.py'))
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class NativeImportPolicyTests(unittest.TestCase):
    def check_source(self, relative, source):
        errors = []
        path = validator.ROOT / relative
        with patch.object(Path, 'read_text', return_value=source):
            validator.validate_python_imports(path, errors)
        return errors

    def test_native_config_import_is_allowed_only_in_hermes_bridge(self):
        bridge = 'plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/hosts/hermes/__init__.py'
        source = 'from hermes_cli.config import load_config_readonly\n'
        self.assertEqual(self.check_source(bridge, source), [])
        self.assertTrue(self.check_source('plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/fabric_session.py', source))
        self.assertTrue(self.check_source(bridge.replace('/hermes/', '/another-host/'), source))

    def test_exception_does_not_allow_arbitrary_native_or_third_party_modules(self):
        bridge = 'plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/hosts/hermes/__init__.py'
        for source in ('import hermes_cli\n', 'from hermes_cli.other import value\n', 'import requests\n'):
            with self.subTest(source=source):
                self.assertTrue(self.check_source(bridge, source))
        self.assertEqual(self.check_source(bridge, 'import json\nfrom collections.abc import Mapping\n'), [])


if __name__ == '__main__':
    unittest.main()
