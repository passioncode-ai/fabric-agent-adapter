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

    def handoff(self, page):
        from urllib.parse import quote
        item = json.loads((ROOT / 'test/evals/dashboard-links/cases.json').read_text())['cases'][0]['input']
        link = 'fabric-dashboards://service/example-agent.default?path=' + quote(page, safe='')
        item['resolved'].update(open_link=link, http_url='http://127.0.0.1:47195' + page)
        item['action']['url'] = link
        result = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(item), text=True, capture_output=True)
        return result.returncode, json.loads(result.stdout)

    def test_dashboard_pages_still_pass(self):
        for page in ['/dashboard#/jobs/1', '/dashboard?tab=jobs', '/dashboard?job=4bf92f3577b34da6a3ce929d0e0e4736',
                     '/dashboard/', '/fabric/v1/login-help', '/dashboard?keyboard=on']:
            with self.subTest(page=page):
                self.assertEqual(self.handoff(page), (0, {'ok': True, 'kind': 'native_link'}))

    def test_the_login_endpoint_is_refused_however_it_is_spelled(self):
        # Finding 47: the gate compared the raw path, so a dot segment walked past it.
        for page in ['/fabric/v1/login?code=x', '/fabric/v1/./login?code=x', '/fabric/v1/../v1/login?code=x',
                     '/fabric/x/../v1/login', '/fabric/v1%2Flogin?code=x', '/fabric/v1%2flogin', '/fabric%5Cv1/login',
                     '/fabric//v1/login', '/fabric/v1/login/', '/FABRIC/V1/LOGIN', '/fabric/v1/%2e/login',
                     '/fabric/v1/%2E%2E/v1/login', '/dashboard/./jobs', '/dashboard/../dashboard']:
            with self.subTest(page=page):
                self.assertEqual(self.handoff(page), (1, {'ok': False, 'reason': 'dashboard_handoff_refused'}))

    def test_credential_parameters_are_refused(self):
        # Finding 47: the list missed code and api_key; it now follows fabric-button's credential rules.
        for page in ['/dashboard?code=one-time', '/dashboard?api_key=x', '/dashboard?apikey=x', '/dashboard?key=x',
                     '/dashboard?auth=x', '/dashboard?accessToken=x', '/dashboard?Login-Code=x', '/dashboard?session_id=x',
                     '/dashboard?client_secret=x', '/dashboard?x=eyJhbGciOiJ.eyJzdWIiOiIx.c2ln',
                     '/dashboard?x=sk-abcdefghijklmnopqrstuv', '/dashboard?x=Bearer%20abc',
                     '/dashboard?note=aB3' + 'xY9' * 13, '/dashboard#token=abc', '/dashboard#/jobs?code=abc',
                     '/dashboard?tab=jobs&TOKEN=x']:
            with self.subTest(page=page):
                self.assertEqual(self.handoff(page), (1, {'ok': False, 'reason': 'dashboard_handoff_refused'}))

    def gate(self, service, link, page):
        # The gate imported as a module, so its reason is visible; the CLI adds only the fixed refusal.
        import importlib.util
        spec = importlib.util.spec_from_file_location('check_dashboard_link', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        item = json.loads((ROOT / 'test/evals/dashboard-links/cases.json').read_text())['cases'][0]['input']
        item['resolved'].update(service=service, open_link=link, http_url='http://127.0.0.1:47195' + (page or '/'))
        item['action']['url'] = link
        try:
            return module.check(item)['ok'], None
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            return False, str(error)

    def test_contract_page_link_vectors_agree_with_the_gate(self):
        # D10: every link FAC-SEM-143 refuses (DEC-0123 vectors at the pin) is refused as a native link with an
        # available host, the legacy open?service= form included (D8); every link the host's link tool builds passes
        # unless the gate's own login and credential rules, stricter than the grammar, refuse its page.
        from urllib.parse import parse_qs
        stricter = {'dot_segment', 'encoded_separator', 'login_link_is_not_dashboard', 'credential_query'}
        fixtures = ROOT / 'test/fixtures/contract'
        groups = [json.loads((fixtures / name).read_text()) for name in
                  ['page-link-vectors.json', 'page-link-extra-vectors.json']]
        refused = built = 0
        for group in groups:
            for vector in group['links']:
                url = vector['input'].get('url')
                if not vector['expected']:
                    continue
                page = None
                if isinstance(url, str) and '?' in url:
                    paths = parse_qs(url.split('?', 1)[1], keep_blank_values=True).get('path', [])
                    page = paths[0] if len(paths) == 1 and paths[0].startswith('/') else None
                with self.subTest(link=vector['name']):
                    self.assertEqual(self.gate('example-agent.default', url, page)[0], False)
                refused += 1
            for vector in group['builds']:
                if vector['expected'] is None:
                    continue
                spec = vector['input']
                ok, reason = self.gate(spec['service'] + '.' + spec['instance'], vector['expected'], spec.get('path'))
                with self.subTest(build=vector['name']):
                    self.assertTrue(ok or reason in stricter, reason)
                built += 1
        self.assertGreater(refused, 40)
        self.assertGreater(built, 40)
        legacy = 'fabric-dashboards://open?service=example-agent.default'
        self.assertIn(legacy, [v['input'].get('url') for v in groups[0]['links'] if v['expected']])

    def test_shared_payload_is_self_contained_and_identical(self):
        for relative in ['scripts/check_dashboard_link.py', 'references/dashboard-links.md']:
            contents = [(SKILLS / name / relative).read_bytes() for name in ['building-fabric-services', 'creating-fabric-agents', 'adapting-projects-to-fabric']]
            self.assertEqual(contents[0], contents[1])
            self.assertEqual(contents[1], contents[2])

if __name__ == '__main__':
    unittest.main()
