"""DeepSeek Harness (dsh) native context hook (FAA-370): the installer writes a managed Cordis plugin shim and one
managed block in dsh's home patch layer, keeps every other byte of the layer, refuses layer shapes it cannot edit
safely, and the session-start helper answers the host by name."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'plugins/fabric-agent-adapter/skills/working-with-fabric/scripts'
spec = importlib.util.spec_from_file_location('native_host_install_dsh', SCRIPTS / 'host_hooks.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
FOREIGN = "# my own layer\n- insert:\n    - id: other\n      name: '@example/plugin'\n"


class DshInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name); self.env = {'HOME': str(self.home)}
        self.dsh = self.home / '.dsh'; self.layer = self.dsh / 'cordis.patch.yml'
        self.loader = self.dsh / 'plugins/fabric-agent-adapter.mjs'
        self.lines = []

    def run_cli(self, *args):
        self.lines = []
        return h.main(['--host', 'deepseek-harness', *args], env=self.env, out=self.lines.append, err=self.lines.append)

    def test_dry_run_writes_nothing_then_apply_creates_loader_and_block(self):
        self.assertEqual(self.run_cli(), 0)
        self.assertFalse(self.dsh.exists())
        self.assertEqual(self.run_cli('--apply'), 0)
        loader = self.loader.read_text()
        self.assertTrue(loader.startswith('// ' + h.MARKER))
        self.assertIn('export * from', loader)
        self.assertIn('hosts/deepseek-harness/fabric.mjs', loader)
        layer = self.layer.read_text()
        self.assertIn('- insert:\n    - id: fabric-agent-adapter\n      name: ' + json.dumps(str(self.loader)), layer)
        self.assertEqual(layer.count(h.DSH_END), 1)

    def test_apply_twice_is_unchanged_and_remove_leaves_an_empty_sequence(self):
        self.assertEqual(self.run_cli('--apply'), 0)
        first = self.layer.read_bytes()
        self.assertEqual(self.run_cli('--apply'), 0)
        self.assertEqual(self.layer.read_bytes(), first)
        self.assertEqual(self.run_cli('--remove'), 0)
        self.assertFalse(self.loader.exists())
        self.assertEqual(self.layer.read_text(), '[]\n')

    def test_foreign_rows_are_kept_byte_for_byte(self):
        self.dsh.mkdir(); self.layer.write_text(FOREIGN)
        self.assertEqual(self.run_cli('--apply'), 0)
        self.assertTrue(self.layer.read_text().startswith(FOREIGN))
        self.assertEqual(self.run_cli('--remove'), 0)
        self.assertEqual(self.layer.read_text(), FOREIGN)

    def test_an_empty_flow_list_becomes_the_block(self):
        self.dsh.mkdir(); self.layer.write_text('[]\n')
        self.assertEqual(self.run_cli('--apply'), 0)
        self.assertNotIn('[]', self.layer.read_text())
        self.assertTrue(self.layer.read_text().startswith(h.DSH_BEGIN))

    def test_shapes_it_cannot_edit_are_refused_unchanged(self):
        for text in ('settings:\n  a: 1\n', '[{insert: [{id: x, name: y}]}]\n', h.DSH_BEGIN + '\n- insert: []\n'):
            with self.subTest(text=text):
                self.dsh.mkdir(exist_ok=True); self.layer.write_text(text)
                self.assertEqual(self.run_cli('--apply'), 1)
                self.assertEqual(self.layer.read_text(), text)
                self.assertFalse(self.loader.exists())
                self.assertTrue(any('refused' in line for line in self.lines))

    def test_remove_without_our_block_is_a_byte_exact_noop(self):
        self.dsh.mkdir(); self.layer.write_text(FOREIGN)
        self.assertEqual(self.run_cli('--remove'), 0)
        self.assertEqual(self.layer.read_text(), FOREIGN)

    def test_a_foreign_loader_file_is_refused(self):
        self.loader.parent.mkdir(parents=True); self.loader.write_text('// someone else\n')
        self.assertEqual(self.run_cli('--apply'), 1)
        self.assertEqual(self.loader.read_text(), '// someone else\n')
        self.assertFalse(self.layer.exists())

    def test_dsh_home_and_config_override(self):
        other = self.home / 'elsewhere'
        self.env['DSH_HOME'] = str(other)
        self.assertEqual(self.run_cli('--apply'), 0)
        self.assertTrue((other / 'cordis.patch.yml').exists())
        self.assertFalse(self.dsh.exists())


class DshSessionStartTests(unittest.TestCase):
    def test_host_is_known_and_native(self):
        spec2 = importlib.util.spec_from_file_location('fabric_session_env_dsh', SCRIPTS / 'fabric_session_env.py')
        import sys
        sys.path.insert(0, str(SCRIPTS))
        try:
            env_mod = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(env_mod)
        finally:
            sys.path.remove(str(SCRIPTS))
        self.assertEqual(env_mod.HOSTS['deepseek-harness'], 'DeepSeek Harness')
        self.assertIn('deepseek-harness', env_mod.NATIVE_PLUGIN_HOSTS)


if __name__ == '__main__':
    unittest.main()
