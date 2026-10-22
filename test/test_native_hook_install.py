"""Native host installation preserves foreign state and fences stale plans."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/host_hooks.py'
spec = importlib.util.spec_from_file_location('native_host_install', SCRIPT)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)

class NativeInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name); self.env = {'HOME':str(self.home)}
        self.lines = []
    def run_cli(self, host, *args):
        self.lines = []
        return h.main(['--host', host, *args], env=self.env, out=self.lines.append, err=self.lines.append)
    def test_js_plan_apply_update_remove_and_conflict(self):
        for host, rel in [('opencode','.config/opencode/plugins/fabric-agent-adapter.js'), ('pi','.pi/agent/extensions/fabric-agent-adapter.js')]:
            with self.subTest(host=host):
                p=self.home/rel
                self.assertEqual(self.run_cli(host),0); self.assertFalse(p.exists())
                self.assertEqual(self.run_cli(host,'--apply','--expect-sha256','wrong'),1); self.assertFalse(p.exists())
                self.assertEqual(self.run_cli(host,'--apply'),0)
                original=p.read_text(); self.assertIn('export { default }', original)
                self.assertEqual(self.run_cli(host,'--apply'),0); self.assertEqual(original,p.read_text())
                self.assertEqual(self.run_cli(host,'--remove'),0); self.assertFalse(p.exists())
                p.write_text('// unrelated plugin\n')
                self.assertEqual(self.run_cli(host,'--apply'),1); self.assertEqual(p.read_text(),'// unrelated plugin\n')
    def test_hermes_files_leave_foreign_plugin_and_native_enable_separate(self):
        foreign=self.home/'.hermes/plugins/other';foreign.mkdir(parents=True);(foreign/'__init__.py').write_text('pass')
        self.assertEqual(self.run_cli('hermes','--apply'),0)
        root=self.home/'.hermes/plugins/fabric-agent-adapter'
        self.assertIn('spec_from_file_location',(root/'__init__.py').read_text())
        self.assertTrue((root/'plugin.yaml').exists()); self.assertTrue(any('hermes plugins enable' in s for s in self.lines))
        self.assertEqual(self.run_cli('hermes','--remove'),0);self.assertFalse(root.exists());self.assertTrue(foreign.exists())
    def test_openclaw_preserves_settings_and_enforces_policy(self):
        p=self.home/'.openclaw/openclaw.json';p.parent.mkdir()
        base={'other': {'keep': True},'plugins':{'allow':['other'],'entries':{'other':{'enabled':True}}}}
        p.write_text(json.dumps(base))
        self.assertEqual(self.run_cli('openclaw','--apply'),0)
        v=json.loads(p.read_text());self.assertEqual(v['other'],base['other']);self.assertEqual(v['plugins']['entries']['other'],{'enabled':True})
        entry=v['plugins']['entries']['fabric-agent-adapter'];self.assertTrue(entry['hooks']['allowConversationAccess'])
        self.assertEqual(self.run_cli('openclaw','--apply'),0)
        self.assertEqual(self.run_cli('openclaw','--remove'),0)
        v=json.loads(p.read_text());self.assertNotIn('fabric-agent-adapter',v['plugins']['entries'])
        self.assertEqual(v['other'],base['other'])
        self.assertEqual(self.run_cli('openclaw','--apply'),0)
        v['plugins']['deny']=['fabric-agent-adapter'];p.write_text(json.dumps(v));before=p.read_bytes()
        self.assertEqual(self.run_cli('openclaw','--apply'),1);self.assertEqual(p.read_bytes(),before)
    def test_symlink_and_malformed_configs_untouched(self):
        dest=self.home/'elsewhere';dest.write_text('{}')
        p=self.home/'.openclaw/openclaw.json';p.parent.mkdir();p.symlink_to(dest)
        self.assertEqual(self.run_cli('openclaw','--apply'),1);self.assertTrue(p.is_symlink());self.assertEqual(dest.read_text(),'{}')
        p.unlink();p.write_text('{invalid');self.assertEqual(self.run_cli('openclaw','--apply'),1);self.assertEqual(p.read_text(),'{invalid')

    def test_old_skill_without_native_sources_does_not_install_broken_loader(self):
        old=self.home/'old/fabric_session.py';old.parent.mkdir();old.write_text('pass')
        for host in ('hermes','opencode','pi','openclaw'):
            self.assertEqual(self.run_cli(host,'--apply','--script',str(old)),1)
            self.assertFalse(h.destination(host,self.env).exists())

    def test_hermes_remove_needs_no_source_hosts_folder(self):
        """FAA-69: the skill the loader was installed from moved or lost its hosts/ folder; removal reads nothing there."""
        root=self.home/'.hermes/plugins/fabric-agent-adapter'
        old=self.home/'old/fabric_session.py';old.parent.mkdir();old.write_text('pass')
        for script in (old, self.home/'gone/fabric_session.py'):
            with self.subTest(script=script):
                self.assertEqual(self.run_cli('hermes','--apply'),0);self.assertTrue((root/'plugin.yaml').exists())
                self.assertEqual(self.run_cli('hermes','--remove','--script',str(script)),0,self.lines)
                self.assertFalse(root.exists())

    def test_openclaw_remove_absent_adapter_is_byte_exact_noop(self):
        p=self.home/'.openclaw/openclaw.json';p.parent.mkdir();p.write_text('{"unrelated": true}\n')
        before=p.read_bytes()
        self.assertEqual(self.run_cli('openclaw','--remove'),0)
        self.assertEqual(p.read_bytes(),before)
    def test_openclaw_remove_drops_our_load_path_when_its_folder_is_gone(self):
        """FAA-90: the ownership check read the folder's manifest, so a load path whose plugin folder was deleted (an
        older install, a moved checkout) was never removed. A path in our layout whose folder is gone is dropped."""
        gone = str(self.home / 'old/plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/hosts/openclaw')
        foreign = str(self.home / 'other-plugin')
        p = self.home/'.openclaw/openclaw.json'; p.parent.mkdir()
        p.write_text(json.dumps({'plugins': {'entries': {h.IDENTITY: {'enabled': True, 'hooks': {'allowConversationAccess': True, 'allowPromptInjection': True}}}, 'load': {'paths': [gone, foreign]}}}))
        self.assertEqual(self.run_cli('openclaw', '--remove'), 0)
        doc = json.loads(p.read_text())
        self.assertEqual(doc['plugins']['load']['paths'], [foreign])
        self.assertNotIn(h.IDENTITY, doc['plugins'].get('entries', {}))
    def test_openclaw_remove_reads_a_home_relative_load_path(self):
        """A `~/` load path is read where it points: a live folder whose manifest names another plugin is kept, a gone
        one in our layout is dropped (round-2 reading of 0.44.0)."""
        import os
        from unittest import mock
        live = '~/live/plugins/x/skills/working-with-fabric/scripts/hosts/openclaw'
        gone = '~/gone/plugins/x/skills/working-with-fabric/scripts/hosts/openclaw'
        folder = self.home / 'live/plugins/x/skills/working-with-fabric/scripts/hosts/openclaw'
        folder.mkdir(parents=True)
        (folder / 'openclaw.plugin.json').write_text(json.dumps({'id': 'someone-else'}))
        p = self.home/'.openclaw/openclaw.json'; p.parent.mkdir()
        p.write_text(json.dumps({'plugins': {'entries': {h.IDENTITY: {'enabled': True, 'hooks': {'allowConversationAccess': True, 'allowPromptInjection': True}}}, 'load': {'paths': [live, gone]}}}))
        with mock.patch.dict(os.environ, {'HOME': str(self.home)}):
            self.assertEqual(self.run_cli('openclaw', '--remove'), 0)
        self.assertEqual(json.loads(p.read_text())['plugins']['load']['paths'], [live])

if __name__=='__main__':unittest.main()
