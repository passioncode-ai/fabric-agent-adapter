// The dashboard kit's section navigation in a real WebKit (FAA-104, a finding from research-agent on board thread
// 288afbce): the More summary's own text must not leave a half-cut item beside it, and it must follow the current
// section when the page moves aria-current. Needs Playwright's WebKit: set FABRIC_PLAYWRIGHT to a directory whose
// node_modules holds playwright, as test_dashboard_layout.py does; without it these tests are skipped.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const KIT = path.join(here, '../plugins/fabric-agent-adapter/skills/building-fabric-services/assets/dashboard-kit');
const dir = process.env.FABRIC_PLAYWRIGHT || '';
let webkit = null;
try {
  if (dir) ({ webkit } = createRequire(path.join(dir, 'package.json'))('playwright'));
} catch { webkit = null; }
const skip = webkit ? false : 'NOT_RUN: set FABRIC_PLAYWRIGHT to a directory with playwright and its WebKit';

const SECTIONS = ['Обзор', 'Задания', 'Исследования', 'Цепочки', 'Источники', 'Обучение', 'Настройки'];
function page(current) {
  const items = SECTIONS.map((s, i) => `<li><a href="#s${i}"${i === current ? ' aria-current="page"' : ''}>${s}</a></li>`).join('');
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<link rel="stylesheet" href="/fabric-dashboard.css"></head><body><header class="fd-bar">
<nav class="fd-nav" aria-label="Разделы" data-fd-more-label="Ещё"><ul class="fd-nav-list">${items}</ul></nav></header>
<script src="/fabric-dashboard.js"></script></body></html>`;
}

// The kit reads document.cookie, which an about:blank page refuses: serve the page from an http origin.
async function open(p, current) {
  await p.route('http://kit.test/**', (route) => {
    const name = new URL(route.request().url()).pathname.slice(1);
    if (!name) return route.fulfill({ contentType: 'text/html; charset=utf-8', body: page(current) });
    const type = name.endsWith('.css') ? 'text/css' : 'text/javascript';
    return route.fulfill({ contentType: `${type}; charset=utf-8`, body: fs.readFileSync(path.join(KIT, name), 'utf8') });
  });
  await p.goto('http://kit.test/');
  await p.waitForSelector('.fd-nav--fold');
}

// A ResizeObserver runs before the next paint: two frames after a resize the kit has laid the bar out again.
const settle = (p) => p.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));

// Every item left in the bar is whole: none is clipped by the list's own edge.
async function state(p) {
  return p.evaluate(() => {
    const list = document.querySelector('.fd-nav-list');
    const edge = list.getBoundingClientRect().right;
    const clipped = [...list.children].filter((li) => li.getBoundingClientRect().right > edge + 0.5).map((li) => li.textContent.trim());
    const summary = document.querySelector('.fd-more > summary');
    return { clipped, overflow: list.scrollWidth > list.clientWidth + 1, summary: summary ? summary.textContent : null,
      inBar: [...list.children].map((li) => li.textContent.trim()) };
  });
}

test('from 360 to 640 px the More summary\'s text leaves no half-cut item beside it', { skip }, async () => {
  const browser = await webkit.launch();
  try {
    // The overflow depends on the exact width: sweep the narrow range at every current section.
    const p = await browser.newPage({ viewport: { width: 390, height: 844 } });
    const bad = [];
    for (const current of SECTIONS.keys()) {
      await p.unrouteAll();
      await open(p, current);
      for (let width = 360; width <= 640; width += 5) {
        await p.setViewportSize({ width, height: 844 });
        await settle(p);
        const s = await state(p);
        if (s.clipped.length || s.overflow) bad.push({ width, current: SECTIONS[current], ...s });
      }
    }
    assert.deepEqual(bad.slice(0, 3), [], `${bad.length} widths leave a cut item`);
  } finally {
    await browser.close();
  }
});

test('the More summary follows aria-current when the page moves it', { skip }, async () => {
  const browser = await webkit.launch();
  try {
    const p = await browser.newPage({ viewport: { width: 390, height: 844 } });
    await open(p, 5);
    assert.match((await state(p)).summary, /Обучение/);
    await p.evaluate(() => {
      document.querySelectorAll('.fd-nav a').forEach((a) => a.removeAttribute('aria-current'));
      [...document.querySelectorAll('.fd-nav a')].find((a) => a.textContent === 'Настройки').setAttribute('aria-current', 'page');
    });
    await settle(p);
    let s = await state(p);
    assert.match(s.summary, /Настройки/, JSON.stringify(s));
    assert.deepEqual(s.clipped, [], JSON.stringify(s));
    // And back to a section that sits in the bar: the summary counts what is folded again.
    await p.evaluate(() => {
      document.querySelectorAll('.fd-nav a').forEach((a) => a.removeAttribute('aria-current'));
      [...document.querySelectorAll('.fd-nav a')].find((a) => a.textContent === 'Обзор').setAttribute('aria-current', 'page');
    });
    await settle(p);
    s = await state(p);
    assert.match(s.summary, /^Ещё \(\d+\)$/, JSON.stringify(s));
    assert.deepEqual(s.clipped, [], JSON.stringify(s));
  } finally {
    await browser.close();
  }
});
