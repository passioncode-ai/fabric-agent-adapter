// The dashboard kit's script (appearance carrier, ED-6/ED-8), the Node service kit's ED-9
// declaration, and the layout probe's verdicts (ED-1…ED-5) as pure functions.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const skill = path.join(here, '../plugins/fabric-agent-adapter/skills/building-fabric-services');
const require = createRequire(import.meta.url);
const kit = require(path.join(skill, 'assets/dashboard-kit/fabric-dashboard.js'));
const svc = await import(path.join(skill, 'scripts/fabric-service.mjs'));
const layout = await import(path.join(skill, 'scripts/check_dashboard_layout.mjs'));
const KEY = 'https://fabric.passioncode.ai/agent-contract/extensions/dashboard/0.1';

test('the carrier cookie is read as v=1 scheme and theme', () => {
  assert.deepEqual(kit.parseAppearance('fabric_appearance=v=1&scheme=dark&theme=ocean'), { scheme: 'dark', theme: 'ocean' });
  assert.deepEqual(kit.parseAppearance('a=b; fabric_appearance=v%3D1%26scheme%3Dlight; c=d'), { scheme: 'light' });
  assert.deepEqual(kit.parseAppearance('fabric_appearance="v=1&theme=paper"'), { theme: 'paper' });
  assert.equal(kit.parseAppearance('fabric_appearance=v=2&scheme=dark'), null, 'an unknown version is ignored');
  assert.equal(kit.parseAppearance('other=1'), null);
  assert.equal(kit.parseAppearance(''), null);
  assert.deepEqual(kit.parseAppearance('fabric_appearance=v=1&scheme=sepia&theme=Bad_Id'), {}, 'malformed fields are dropped');
  assert.equal(kit.parseAppearance('fabric_appearance=%E0%A4%A'), null, 'a broken encoding is no cookie');
});

test('the host wins over the stored choice; an unknown theme is the default', () => {
  const themes = kit.themes;
  assert.deepEqual(themes, svc.REFERENCE_THEMES);
  assert.deepEqual(kit.resolveAppearance({ scheme: 'dark', theme: 'ocean' }, { scheme: 'light', theme: 'paper' }, themes),
    { theme: 'ocean', scheme: 'dark', host: true });
  assert.deepEqual(kit.resolveAppearance({ theme: 'ocean' }, { scheme: 'light' }, themes),
    { theme: 'ocean', scheme: null, host: true }, 'with the host in charge the stored scheme is not used');
  assert.deepEqual(kit.resolveAppearance(null, { scheme: 'light', theme: 'paper' }, themes), { theme: 'paper', scheme: 'light', host: false });
  assert.deepEqual(kit.resolveAppearance({ theme: 'neon' }, null, themes), { theme: 'graphite', scheme: null, host: true });
  assert.deepEqual(kit.resolveAppearance(null, null, themes), { theme: 'graphite', scheme: null, host: false });
  assert.deepEqual(kit.resolveAppearance({ scheme: 'dark', theme: 'ocean' }, null, themes, ['scheme']),
    { theme: 'graphite', scheme: 'dark', host: true }, 'a page that applies only the scheme keeps its theme');
});

test('the Node kit builds and checks the ED-9 declaration like the Python kit', () => {
  assert.deepEqual(svc.dashboardExtension(), { [KEY]: { minWidth: 360, appearance: ['scheme', 'theme'], themes: svc.REFERENCE_THEMES, kit: svc.DASHBOARD_KIT } });
  assert.deepEqual(svc.dashboardExtension({ minWidth: 480, appearance: [], themes: null, kit: null }), { [KEY]: { minWidth: 480 } });
  assert.throws(() => svc.dashboardExtension({ minWidth: 200 }), /outside 360…1280/);
  for (const [value, needle] of [[{}, 'required'], [{ minWidth: 360, x: 1 }, 'unknown field'], [{ minWidth: 360, themes: ['Ocean'] }, 'themes'],
    [{ minWidth: 360, appearance: ['colour'] }, 'appearance'], [{ minWidth: 360, kit: 'kit' }, 'kit'], [[], 'not an object']]) {
    assert.ok(svc.dashboardExtensionProblems(value).some((p) => p.includes(needle)), JSON.stringify(value));
  }
  const base = { id: 'example-agent', instance: 'default', name: 'Example', version: '1.0.0', build: { commit: 'abc1234' },
    startedAt: '2026-10-11T09:00:00Z', status: 'ready', surfaces: { events: { path: '/fabric/v1/events' }, dashboard: { path: '/' } } };
  assert.equal('extensions' in svc.buildWellKnown(base), false);
  assert.equal(svc.buildWellKnown({ ...base, extensions: svc.dashboardExtension() }).extensions[KEY].minWidth, 360);
  assert.throws(() => svc.buildWellKnown({ ...base, extensions: { [KEY]: { minWidth: 100 } } }), /Dashboard declaration/);
});

test('layout verdicts: below the floor, overflow, navigation, boxes, chrome', () => {
  const ok = { vw: 360, vh: 800, scrollWidth: 360, nav: { total: 5, unreachable: [] }, boxes: [{ el: 'div.fd-scroll', keyboard: true, named: true }],
    past: [], nested: [], chrome: 40, anchor: { el: 'section#a', top: 48 }, rootMinWidth: 360 };
  assert.ok(layout.verdicts(360, 360, ok).every((r) => r.verdict === 'PASS'));
  assert.equal(layout.verdicts(320, 360, { ...ok, vw: 320, scrollWidth: 360 })[0].verdict, 'PASS');
  assert.equal(layout.verdicts(320, 360, { ...ok, vw: 320, scrollWidth: 320 })[0].verdict, 'FAIL', 'collapsing below the floor fails ED-2');
  const by = (rows) => Object.fromEntries(rows.map((r) => [r.rule, r.verdict]));
  assert.equal(by(layout.verdicts(360, 360, { ...ok, scrollWidth: 410 }))['ED-1'], 'FAIL');
  assert.equal(by(layout.verdicts(360, 360, { ...ok, nav: { total: 14, unreachable: ['Calendar'] } }))['ED-3'], 'FAIL');
  assert.equal(by(layout.verdicts(360, 360, { ...ok, nav: { total: 0, unreachable: [] } }))['ED-3'], 'NOT_RUN');
  assert.equal(by(layout.verdicts(360, 360, { ...ok, boxes: [{ el: 'div', keyboard: false, named: true }] }))['ED-4'], 'FAIL');
  assert.equal(by(layout.verdicts(360, 360, { ...ok, past: ['table.wide'] }))['ED-4'], 'FAIL');
  assert.equal(by(layout.verdicts(360, 360, { ...ok, chrome: 121 }))['ED-5'], 'FAIL', '120 px is the ceiling');
  assert.equal(by(layout.verdicts(360, 360, { ...ok, vh: 400, chrome: 101 }))['ED-5'], 'FAIL', 'a quarter of the height when smaller');
  assert.equal(by(layout.verdicts(360, 360, { ...ok, anchor: { el: 'h2', top: 10 } }))['ED-5'], 'FAIL', 'an anchor under the chrome');
  assert.equal(by(layout.verdicts(360, 360, { ...ok, nested: ['div.pane'] }))['ED-5'], 'FAIL');
});

test('probe arguments', () => {
  assert.deepEqual(layout.parseArgs(['http://x/']).widths, [360, 480, 768, 1280]);
  assert.equal(layout.parseArgs(['http://x/']).browser, 'webkit', 'Safari\'s engine by default');
  assert.deepEqual(layout.parseArgs(['--service', 'example-agent.preview', '--widths', '360,1440']).widths, [360, 1440]);
});
