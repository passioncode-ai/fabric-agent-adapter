// Fabric's button (DEC-0040, FB-1…FB-8, FL-1…FL-6) in the dashboard kit (FB-7).
// The link grammar is checked against the contract's own parseFabricLink and buildFabricLink answers
// (test/fixtures/contract/fabric-links.json). The behaviour in a page is checked in WebKit, Safari's engine,
// through Playwright when it is installed (FABRIC_PLAYWRIGHT=<dir with node_modules/playwright>); otherwise that
// part is skipped and says so.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import { createRequire } from 'node:module';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import vm from 'node:vm';

const here = path.dirname(fileURLToPath(import.meta.url));
const KIT = path.join(here, '../plugins/fabric-agent-adapter/skills/building-fabric-services/assets/dashboard-kit');
const SOURCE = fs.readFileSync(path.join(KIT, 'fabric-button.js'), 'utf8');
const VECTORS = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/contract/fabric-links.json'), 'utf8'));

function load() {
  const sandbox = { URLSearchParams, Map, Set, Array, Object, TypeError, console };
  sandbox.globalThis = sandbox;
  vm.runInNewContext(SOURCE, sandbox);
  return sandbox.FabricButton;
}
const plain = (value) => JSON.parse(JSON.stringify(value));

test('every link the contract parses, the button parses the same way (FL-1…FL-5)', () => {
  const fb = load();
  assert.ok(VECTORS.parse.length >= 40);
  for (const c of VECTORS.parse) assert.deepEqual(plain(fb.parseFabricLink(c.url)), c.expected, c.url);
});

test('the button builds only the links the contract builds (FL-6)', () => {
  const fb = load();
  for (const c of VECTORS.build) {
    if (c.throws) assert.throws(() => fb.buildFabricLink(c.link), TypeError, JSON.stringify(c.link));
    else assert.equal(fb.buildFabricLink(c.link), c.expected);
  }
});

test('the host cookie (FB-6) and the menu items (FB-4)', () => {
  const fb = load();
  assert.deepEqual(plain(fb.parseButtonCookie('a=1; fabric_button=v=1&owner=host&fabric=absent')), { owner: 'host', fabric: 'absent' });
  assert.deepEqual(plain(fb.parseButtonCookie('fabric_button="v=1&owner=page"')), { owner: 'page' });
  assert.equal(fb.parseButtonCookie('fabric_button=v=2&owner=host'), null, 'an unknown version is ignored');
  assert.equal(fb.parseButtonCookie(''), null);
  assert.deepEqual(plain(fb.parseButtonCookie('fabric_button=v=1&owner=root&fabric=maybe')), {}, 'unknown values are left out');
  const items = fb.menuItems({ service: 'example-agent.default', serviceName: 'Example Agent', project: 'project-a', projectName: 'Project A', runner: 'claude-code' });
  assert.deepEqual(plain(items), [
    { label: 'Chat with Fabric about Example Agent', href: 'fabric://chat?service=example-agent.default&project=project-a' },
    { label: 'Open a coding session in Project A', href: 'fabric://session/new?project=project-a&runner=claude-code' },
  ]);
  assert.equal(fb.menuItems({ service: 'example-agent' }).length, 1, 'no project, no session item');
  assert.throws(() => fb.menuItems({ service: 'Example Agent' }), TypeError, 'a bad id never becomes a link');
});

test('the script is CSP-clean and names one address only', () => {
  for (const banned of ['eval(', 'new Function', 'innerHTML', 'outerHTML', 'document.write', 'insertAdjacentHTML']) assert.ok(!SOURCE.includes(banned), banned);
  const urls = SOURCE.match(/https?:\/\/[^\s'"`)]+/g) ?? [];
  assert.deepEqual([...new Set(urls)].sort(), ['http://www.w3.org/2000/svg', 'https://passioncode.ai/fabric']);
});

// ---- in a page, in WebKit ----

async function playwright() {
  const bases = [process.env.FABRIC_PLAYWRIGHT, process.cwd()].filter(Boolean);
  for (const base of bases) {
    try {
      const req = createRequire(path.join(path.resolve(base), 'noop.js'));
      const mod = await import(pathToFileURL(req.resolve('playwright')).href);
      return mod.webkit ? mod : mod.default;
    } catch { /* next */ }
  }
  return null;
}

function page(attrs, dir = 'ltr') {
  const data = Object.entries(attrs).map(([k, v]) => ` data-${k}="${v}"`).join('');
  return `<!doctype html><html lang="en" dir="${dir}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<link rel="stylesheet" href="/fabric-dashboard.css"></head><body><main>${'<p class="row">row</p>'.repeat(60)}<p id="last">last row</p></main>
<script src="/fabric-button.js" defer${data}></script></body></html>`;
}

function serve(routes) {
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://x');
    if (url.pathname === '/fabric-dashboard.css' || url.pathname === '/fabric-button.js') {
      res.writeHead(200, { 'Content-Type': url.pathname.endsWith('.css') ? 'text/css' : 'text/javascript' });
      return res.end(fs.readFileSync(path.join(KIT, url.pathname.slice(1))));
    }
    const route = routes[url.pathname];
    if (!route) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', ...(route.cookie ? { 'Set-Cookie': `fabric_button=${route.cookie}; Path=/; SameSite=Strict` } : {}) });
    res.end(route.html);
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

test('in WebKit: placement, name, menu and keyboard, the host cookie, Fabric absent (FB-1…FB-5)', async (t) => {
  const pw = await playwright();
  if (!pw) { t.skip('NOT_RUN: Playwright is not installed here (set FABRIC_PLAYWRIGHT)'); return; }
  let browser;
  try { browser = await pw.webkit.launch(); } catch (err) { t.skip(`NOT_RUN: WebKit does not start: ${String(err.message).split('\n')[0]}`); return; }
  const attrs = { service: 'example-agent.default', 'service-name': 'Example Agent', project: 'project-a', 'project-name': 'Project A' };
  const server = await serve({
    '/': { html: page(attrs) },
    '/rtl': { html: page(attrs, 'rtl') },
    '/host': { html: page(attrs), cookie: 'v%3D1%26owner%3Dhost' },
    '/absent': { html: page(attrs), cookie: 'v%3D1%26owner%3Dpage%26fabric%3Dabsent' },
    '/chat-only': { html: page({ service: 'example-agent' }) },
  });
  const origin = `http://127.0.0.1:${server.address().port}`;
  try {
    const context = await browser.newContext({ viewport: { width: 1024, height: 700 } });
    const p = await context.newPage();
    await p.goto(`${origin}/`);
    const button = p.getByRole('button', { name: 'Open Fabric' });
    await button.waitFor();
    // FB-2, FB-3: bottom-right, 16 px off, at least 44 × 44, the word shown at this width.
    const box = await button.boundingBox();
    assert.ok(box.width >= 44 && box.height >= 44, `target ${box.width}×${box.height}`);
    assert.ok(Math.abs(1024 - (box.x + box.width) - 16) <= 1 && Math.abs(700 - (box.y + box.height) - 16) <= 1, `at ${box.x},${box.y}`);
    assert.equal(await p.locator('.fd-fabric-button-label').isVisible(), true);
    assert.equal(await button.getAttribute('aria-haspopup'), 'menu');
    // FB-2: the last row scrolls clear of the button.
    await p.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    const last = await p.locator('#last').boundingBox();
    assert.ok(last.y + last.height <= box.y, `last row ends at ${last.y + last.height}, the button starts at ${box.y}`);
    // FB-4: the menu, the first item focused, arrows, Escape returns focus.
    await button.click();
    assert.equal(await button.getAttribute('aria-expanded'), 'true');
    const items = p.getByRole('menuitem');
    assert.deepEqual(await items.allTextContents(), ['Chat with Fabric about Example Agent', 'Open a coding session in Project A']);
    assert.deepEqual(await items.evaluateAll((els) => els.map((a) => a.getAttribute('href'))),
      ['fabric://chat?service=example-agent.default&project=project-a', 'fabric://session/new?project=project-a']);
    assert.equal(await p.evaluate(() => document.activeElement.textContent), 'Chat with Fabric about Example Agent');
    await p.keyboard.press('ArrowDown');
    assert.equal(await p.evaluate(() => document.activeElement.textContent), 'Open a coding session in Project A');
    await p.keyboard.press('ArrowDown');
    assert.equal(await p.evaluate(() => document.activeElement.textContent), 'Chat with Fabric about Example Agent', 'the arrows wrap');
    await p.keyboard.press('Escape');
    assert.equal(await button.getAttribute('aria-expanded'), 'false');
    assert.equal(await p.evaluate(() => document.activeElement.getAttribute('aria-label')), 'Open Fabric');
    assert.equal(await p.locator('.fd-fabric-button-note').isVisible(), false);
    // FB-3: below 480 px the mark alone; the name stays.
    await p.setViewportSize({ width: 360, height: 640 });
    assert.equal(await p.locator('.fd-fabric-button-label').isVisible(), false);
    assert.ok((await button.boundingBox()).width >= 44);
    // FB-2: right-to-left, bottom-left.
    await p.setViewportSize({ width: 1024, height: 700 });
    await p.goto(`${origin}/rtl`);
    const rtl = await p.getByRole('button', { name: 'Open Fabric' }).boundingBox();
    assert.ok(Math.abs(rtl.x - 16) <= 1, `rtl at ${rtl.x}`);
    // FB-1, FB-6: the host draws its own; the page hides its button.
    await p.goto(`${origin}/host`);
    await p.waitForLoadState('load');
    assert.equal(await p.locator('.fd-fabric-button').count(), 0);
    // FB-5: the host says Fabric is absent: the menu says how to get it.
    await p.goto(`${origin}/absent`);
    await p.getByRole('button', { name: 'Open Fabric' }).click();
    const get = p.locator('.fd-fabric-button-get');
    assert.equal(await get.isVisible(), true);
    assert.equal(await p.locator('.fd-fabric-button-note').textContent(), 'Fabric is not installed. Get it at passioncode.ai/fabric');
    assert.deepEqual([await get.getAttribute('href'), await get.getAttribute('rel'), await get.getAttribute('target')], ['https://passioncode.ai/fabric', 'noopener', '_blank']);
    // FB-4, FB-5: the way to get Fabric is a menu item the arrows reach, not a link only a pointer can.
    await p.keyboard.press('Escape');
    await p.getByRole('button', { name: 'Open Fabric' }).focus();
    await p.keyboard.press('Enter');
    assert.deepEqual(await p.getByRole('menuitem').allTextContents(),
      ['Chat with Fabric about Example Agent', 'Open a coding session in Project A', 'passioncode.ai/fabric']);
    const focused = () => p.evaluate(() => document.activeElement.textContent);
    await p.keyboard.press('ArrowUp');
    assert.equal(await focused(), 'passioncode.ai/fabric', 'up from the first item wraps to the get link');
    await p.keyboard.press('ArrowDown');
    assert.equal(await focused(), 'Chat with Fabric about Example Agent');
    await p.keyboard.press('End');
    assert.equal(await focused(), 'passioncode.ai/fabric');
    await p.keyboard.press('Escape');
    await p.keyboard.press('ArrowUp');
    assert.equal(await focused(), 'passioncode.ai/fabric', 'ArrowUp on the button opens at the last item');
    await p.keyboard.press('Escape');
    // FB-5: with no signal, following a link that nothing takes leaves the page focused: the note shows after 1.5 s.
    await context.clearCookies();
    await p.goto(`${origin}/chat-only`);
    assert.equal(await p.getByRole('menuitem').count(), 0);
    await p.getByRole('button', { name: 'Open Fabric' }).click();
    assert.equal(await p.getByRole('menuitem').count(), 1, 'no project: the chat item only');
    await p.evaluate(() => { document.querySelector('.fd-fabric-button-item').addEventListener('click', (e) => e.preventDefault()); });
    await p.getByRole('menuitem').click();
    assert.equal(await p.locator('.fd-fabric-button-note').isVisible(), false, 'not before 1.5 s');
    await p.waitForTimeout(1800);
    assert.equal(await p.locator('.fd-fabric-button-note').isVisible(), true);
    await context.close();
  } finally {
    await browser.close();
    server.close();
  }
});
