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
                     '/dashboard?x=sk-' + 'Ab1' + 'cdefghijklmnopqrstuv',  # a key DEC-0151 reads, built from pieces '/dashboard?x=Bearer%20abc',
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

    def test_the_gate_is_agent_side_and_the_project_pins_its_own_fixture(self):  # FAA-129
        doc = (SKILLS / 'building-fabric-services/references/dashboard-links.md').read_text(encoding='utf-8')
        gate = doc.split('## Portable output gate', 1)[1].split('## Degradation', 1)[0]
        flat = ' '.join(gate.split())
        for words in ('The gate is **agent-side**', 'never run by that project\'s CI', 'would always be NOT_RUN',
                      'pins the same negative fixture in its own test suite, without calling the gate'):
            self.assertIn(words, flat, words)
        snippet = gate.split('```python', 1)[1].split('```', 1)[0]
        self.assertNotIn('check_dashboard_link', snippet)
        open_link = 'fabric-dashboards://service/example-agent.default?path=%2Fdashboard'
        renderers = {
            'native': (lambda resolved, host_state: 'Done. Open: ' + resolved['open_link'], True),
            'raw-http': (lambda resolved, host_state: 'Done. Open: ' + resolved['http_url'], False),
            'both': (lambda resolved, host_state: resolved['open_link'] + ' or http://localhost:47195/', False),
            'legacy': (lambda resolved, host_state: open_link + ' fabric-dashboards://open?service=example-agent.default', False),
        }
        for name, (render, ok) in renderers.items():
            with self.subTest(renderer=name):
                space = {}
                exec(compile(snippet, 'dashboard-links.md', 'exec'), space)
                space['render'] = render
                test = space['RenderedDashboardLinks']('test_rendered_output_has_no_raw_loopback_or_legacy_link')
                result = unittest.TestResult()
                test.run(result)
                self.assertEqual(result.wasSuccessful(), ok, result.failures or result.errors)

    def run_bytes(self, payload, encoding):
        import os
        env = dict(os.environ, PYTHONIOENCODING=encoding)
        env.pop('PYTHONUTF8', None)
        return subprocess.run([sys.executable, str(SCRIPT)], input=payload, capture_output=True, env=env)

    def test_the_handoff_is_read_as_utf8_bytes_whatever_the_code_page(self):  # FAA-210
        # Windows before Python 3.15 decodes a text stdin with its code page; the gate reads bytes as UTF-8 (a BOM
        # dropped), so a Cyrillic or BOM-led handoff is read the same under every code page.
        from urllib.parse import quote
        item = json.loads((ROOT / 'test/evals/dashboard-links/cases.json').read_text())['cases'][0]['input']
        page = '/dashboard?tab=задачи'
        link = 'fabric-dashboards://service/example-agent.default?path=' + quote(page, safe='')
        item['resolved'].update(open_link=link, http_url='http://127.0.0.1:47195' + page)
        item['action']['url'] = link
        item['target_device'] = item['viewer_device'] = 'рабочая станция'
        body = json.dumps(item, ensure_ascii=False).encode('utf-8')
        for encoding in ('cp1251', 'cp1252', 'utf-8'):
            for name, payload in (('plain', body), ('bom', b'\xef\xbb\xbf' + body)):
                with self.subTest(encoding=encoding, payload=name):
                    result = self.run_bytes(payload, encoding)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(json.loads(result.stdout), {'ok': True, 'kind': 'native_link'})

    def test_bytes_that_are_no_utf8_and_a_deep_document_are_refused_plainly(self):  # FAA-210
        body = json.dumps(json.loads((ROOT / 'test/evals/dashboard-links/cases.json').read_text())['cases'][0]['input'])
        refused = {'ok': False, 'reason': 'dashboard_handoff_refused'}
        for name, payload in (('stray byte', body.replace('workstation', 'work\xff', 1).encode('latin-1')),
                              ('deep', b'[' * 32000 + b']' * 32000), ('over the cap', b' ' * 65537 + body.encode())):
            with self.subTest(payload=name):
                result = self.run_bytes(payload, 'cp1252')
                self.assertEqual(result.returncode, 1)
                self.assertEqual(json.loads(result.stdout), refused)
                self.assertEqual(result.stderr, b'', 'no traceback')
        # the cap counts bytes: 65,536 of them pass, 65,537 do not
        padded = body.encode() + b' ' * (65536 - len(body.encode()))
        self.assertEqual(self.run_bytes(padded, 'utf-8').returncode, 0)
        self.assertEqual(self.run_bytes(padded + b' ', 'utf-8').returncode, 1)

    def test_a_browser_only_on_not_installed_and_unsupported_is_none(self):  # FAA-137
        # Contract DEC-0123 PL-3 would also allow a browser on `unsupported` (a system the host does not ship for);
        # the operator's machine rule allows one only on a confirmed `not_installed`, and macOS never reports
        # `unsupported`, so the gate keeps refusing it. dashboard-links.md says so.
        item = json.loads((ROOT / 'test/evals/dashboard-links/cases.json').read_text())['cases'][0]['input']
        item['action'] = {'kind': 'browser_link', 'url': item['resolved']['http_url']}
        item['listener_owner'] = 'this-account'
        for state, fallback, ok in (('not_installed', 'if_absent', True), ('not_installed', 'never', False),
                                    ('unsupported', 'if_absent', False), ('unsupported', 'never', False),
                                    ('handler_mismatch', 'if_absent', False), ('unknown', 'if_absent', False)):
            with self.subTest(state=state, fallback=fallback):
                item['host'] = {'state': state}
                item['fallback'] = fallback
                result = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(item), text=True,
                                        capture_output=True)
                self.assertEqual(result.returncode, 0 if ok else 1)
        doc = ' '.join((SKILLS / 'building-fabric-services/references/dashboard-links.md').read_text(
            encoding='utf-8').split())
        for words in ('`unsupported`', 'DEC-0123 PL-3', 'the operator', 'macOS never reports it', 'no fallback'):
            self.assertIn(words, doc, words)

    def test_a_raw_loopback_address_opens_only_after_its_listener_is_this_accounts(self):  # FAA-251, DEC-0154 PL-3
        item = json.loads((ROOT / 'test/evals/dashboard-links/cases.json').read_text())['cases'][0]['input']
        item['action'] = {'kind': 'browser_link', 'url': item['resolved']['http_url']}
        item['host'] = {'state': 'not_installed'}
        item['fallback'] = 'if_absent'
        for owner, ok in (('this-account', True), ('another-account', False), ('system', False), ('unknown', False),
                          ('none', False), ('foreign-user', False), (None, False), ('mine', False), (1, False)):
            with self.subTest(owner=owner):
                if owner is None:
                    item.pop('listener_owner', None)
                else:
                    item['listener_owner'] = owner
                result = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(item), text=True,
                                        capture_output=True)
                self.assertEqual(result.returncode, 0 if ok else 1)
        # the owner never gates the native link: Fabric Dashboards checks its own listener (FD-158)
        item['listener_owner'] = 'another-account'
        item['host'] = {'state': 'available'}
        item['action'] = {'kind': 'native_link', 'url': item['resolved']['open_link']}
        result = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(item), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0)

    def test_shared_payload_is_self_contained_and_identical(self):
        for relative in ['scripts/check_dashboard_link.py', 'references/dashboard-links.md']:
            contents = [(SKILLS / name / relative).read_bytes() for name in ['building-fabric-services', 'creating-fabric-agents', 'adapting-projects-to-fabric']]
            self.assertEqual(contents[0], contents[1])
            self.assertEqual(contents[1], contents[2])

if __name__ == '__main__':
    unittest.main()
