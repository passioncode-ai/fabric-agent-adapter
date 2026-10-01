"""Frozen handoff artifacts and CLI exit codes; not model-behaviour evals."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / 'plugins/fabric-agent-adapter/skills'
SCRIPT = SKILLS / 'building-fabric-services/scripts/check_dashboard_link.py'

class DashboardLinksTest(unittest.TestCase):
    def test_frozen_handoffs_through_cli(self):
        cases = json.loads((ROOT / 'test/evals/dashboard-links/cases.json').read_text())['cases']
        for case in cases:
            with self.subTest(case=case['id']):
                result = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(case['input']), text=True, capture_output=True)
                self.assertEqual(result.returncode, 0 if case['expected_ok'] else 1, result.stderr)
                self.assertEqual(json.loads(result.stdout)['ok'], case['expected_ok'])

    def test_malformed_and_credential_inputs_fail_without_echo(self):
        baseline = json.loads((ROOT / 'test/evals/dashboard-links/cases.json').read_text())['cases'][0]['input']
        bad = ['null', '[]', '{', 'x' * 65537]
        for field, value in [('open_link', 'fabric-dashboards://service/example-agent.preview'),
                             ('http_url', 'http://127.0.0.1:47195/dashboard?token=secret-fixture')]:
            item = json.loads(json.dumps(baseline)); item['resolved'][field] = value
            bad.append(json.dumps(item))
        for raw in bad:
            result = subprocess.run([sys.executable, str(SCRIPT)], input=raw, text=True, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout), {'ok': False, 'reason': 'dashboard_handoff_refused'})
            self.assertNotIn('secret-fixture', result.stdout + result.stderr)

    def test_shared_payload_is_self_contained_and_identical(self):
        for relative in ['scripts/check_dashboard_link.py', 'references/dashboard-links.md']:
            contents = [(SKILLS / name / relative).read_bytes() for name in ['building-fabric-services', 'creating-fabric-agents', 'adapting-projects-to-fabric']]
            self.assertEqual(contents[0], contents[1])
            self.assertEqual(contents[1], contents[2])

if __name__ == '__main__':
    unittest.main()
