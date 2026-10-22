#!/usr/bin/env node
// Layout probe for an embedded dashboard (fabric-dashboard/0.1, Fabric Agent Contract DEC-0036).
//
//   node check_dashboard_layout.mjs <url>                  # a page you can open as is
//   node check_dashboard_layout.mjs --service <id>[.<instance>]   # a registered service: signs in with a
//                                                          # one-time login code, reads minWidth (ED-9)
//   options: --widths 360,480,768,1280  --floor N  --height 800  --browser webkit|chromium|firefox
//            --services-dir DIR  --playwright DIR (where node_modules/playwright lives)  --json
//
// It renders the page in a real browser at each width and measures ED-1 (no sideways document
// scroll from the floor up), ED-2 (the floor layout kept below the floor), ED-3 (every navigation
// link visible or inside an open-able menu), ED-4 (wide content in its own keyboard-reachable
// scroll box) and ED-5 (sticky chrome within min(120 px, a quarter of the height), anchors landing
// below it, no nested full-height scroller). What it cannot measure is NOT_RUN with the reason,
// never a pass. WebKit is the default engine (Safari's). Exit 0 when nothing FAILs, 1 when
// something does, 2 on a usage error. It reads; it never clicks a control of the page.
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { homedir, platform } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const EXTENSION_KEY = 'https://fabric.passioncode.ai/agent-contract/extensions/dashboard/0.1';
const RULES = ['ED-1', 'ED-2', 'ED-3', 'ED-4', 'ED-5'];
// The most elements ED-4 and ED-5 walk on one page; past it they say how much they did not see.
const ELEMENT_CAP = 6000;

// A one-time login code is a credential: no report, error or evidence line carries one.
export function scrub(text) {
  return String(text).replace(/([?&#;]code=)[^&#\s"']*/gi, '$1<redacted>');
}

function usage(message) {
  if (message) process.stderr.write(message + '\n');
  process.stderr.write('usage: check_dashboard_layout.mjs <url> | --service <id>[.<instance>] [--widths 360,480,768,1280] [--json]\n');
  process.exit(2);
}

export function parseArgs(argv) {
  const opts = { widths: [360, 480, 768, 1280], height: 800, browser: 'webkit', json: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => { if (i + 1 >= argv.length) usage(`${a} needs a value`); return argv[++i]; };
    if (a === '--json') opts.json = true;
    else if (a === '--service') opts.service = next();
    else if (a === '--widths') opts.widths = next().split(',').map((w) => Number(w.trim()));
    else if (a === '--floor') opts.floor = Number(next());
    else if (a === '--height') opts.height = Number(next());
    else if (a === '--browser') opts.browser = next();
    else if (a === '--services-dir') opts.servicesDir = next();
    else if (a === '--playwright') opts.playwright = next();
    else if (a.startsWith('--')) usage(`unknown option ${a}`);
    else if (!opts.url) opts.url = a;
    else usage('one URL at a time');
  }
  if (!opts.url && !opts.service) usage();
  if (opts.widths.some((w) => !Number.isInteger(w) || w < 200 || w > 4000)) usage('widths are whole CSS pixels, 200…4000');
  if (!['webkit', 'chromium', 'firefox'].includes(opts.browser)) usage('browser is webkit, chromium or firefox');
  return opts;
}

function servicesDir(override) {
  if (override) return override;
  if (process.env.FABRIC_SERVICES_DIR) return process.env.FABRIC_SERVICES_DIR;
  if (platform() === 'darwin') return path.join(homedir(), 'Library/Application Support/ai.passioncode.fabric/services');
  if (platform() === 'win32') return path.join(process.env.LOCALAPPDATA || path.join(homedir(), 'AppData/Local'), 'passioncode-fabric', 'services');
  return path.join(process.env.XDG_DATA_HOME || path.join(homedir(), '.local/share'), 'passioncode-fabric/services');
}

async function loadPlaywright(dir) {
  const bases = [dir, process.env.FABRIC_PLAYWRIGHT, process.cwd()].filter(Boolean);
  for (const base of bases) {
    try {
      const req = createRequire(path.join(path.resolve(base), 'noop.js'));
      const mod = await import(pathToFileURL(req.resolve('playwright')).href);
      return mod.webkit ? mod : mod.default;
    } catch { /* try the next place */ }
  }
  try { const mod = await import('playwright'); return mod.webkit ? mod : mod.default; } catch { return null; }
}

// Sign in to a registered service the protocol's way: the token stays in its file and a header;
// the page gets a one-time code, never the token.
async function serviceTarget(spec, dir) {
  const [id, instance = 'default'] = spec.split(/\.(.+)/);
  const file = path.join(servicesDir(dir), `${id}.${instance}.json`);
  if (!existsSync(file)) throw new Error(`no descriptor for ${id}.${instance} in ${servicesDir(dir)}`);
  const d = JSON.parse(readFileSync(file, 'utf8'));
  const origin = String(d.origin || '').replace(/\/$/, '');
  const auth = d.auth || {};
  let token = '';
  try { token = readFileSync(auth.tokenFile, 'utf8').trim(); } catch { /* reported below */ }
  const header = auth.header || 'Authorization';
  const value = (auth.scheme || 'Bearer') === 'Bearer' ? `Bearer ${token}` : token;
  const remote = d.placement === 'remote';
  const wkRes = await fetch(`${origin}/.well-known/fabric-service`, { headers: remote && token ? { [header]: value } : {} });
  if (!wkRes.ok) throw new Error(`well-known document answered HTTP ${wkRes.status}`);
  const wk = await wkRes.json();
  const dashboard = wk.surfaces?.dashboard;
  if (!dashboard?.path) throw new Error(`${id}.${instance} declares no surfaces.dashboard`);
  const declared = wk.extensions?.[EXTENSION_KEY];
  let url = origin + dashboard.path;
  if (dashboard.login) {
    if (!token) throw new Error(`no readable token file for ${id}.${instance}`);
    const res = await fetch(`${origin}/fabric/v1/login-code`, { method: 'POST', headers: { [header]: value } });
    if (!res.ok) throw new Error(`login-code answered HTTP ${res.status}`);
    url = origin + (await res.json()).url;
  }
  return { url, declared, name: `${id}.${instance}` };
}

// Runs inside the page. Everything it reports is measured from the rendered layout.
function measure([floor, cap]) {
  const de = document.documentElement;
  const vw = de.clientWidth;
  const vh = window.innerHeight;
  const out = { vw, vh, scrollWidth: de.scrollWidth, nav: { total: 0, unreachable: [] }, boxes: [], past: [], nested: [], chrome: 0, anchor: null };
  const cs = (el) => getComputedStyle(el);
  const scrollsX = (el) => /(auto|scroll)/.test(cs(el).overflowX);
  const clipsX = (el) => cs(el).overflowX !== 'visible';
  // Vertically a scroll box (auto, scroll) still lets the reader reach what it holds; hidden and clip do not.
  const clipsY = (el) => /(hidden|clip)/.test(cs(el).overflowY);
  const pinned = (el) => { for (let a = el; a && a !== de; a = a.parentElement) if (cs(a).position === 'fixed') return true; return false; };
  const label = (el) => {
    const id = el.id ? '#' + el.id : '';
    const cls = typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).join('.') : '';
    return (el.tagName.toLowerCase() + id + cls).slice(0, 80);
  };
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && cs(el).visibility !== 'hidden'; };

  // ED-3: a link is reachable when it is fully inside the viewport's width, inside the page's height
  // (the viewport's, for something fixed to it) and not clipped by an ancestor on either axis, or
  // when it sits in a closed <details> whose summary is reachable, or in a menu a visible
  // aria-controls button opens.
  const inViewport = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0 || r.left < -1 || r.right > vw + 1) return false;
    const [top, bottom] = pinned(el) ? [0, vh] : [-window.scrollY, de.scrollHeight - window.scrollY];
    if (r.top < top - 1 || r.bottom > bottom + 1) return false;
    for (let a = el.parentElement; a && a !== de; a = a.parentElement) {
      const x = clipsX(a);
      const y = clipsY(a);
      if (!x && !y) continue;
      const ar = a.getBoundingClientRect();
      if (x && (r.left < ar.left - 1 || r.right > ar.right + 1)) return false;
      if (y && (r.top < ar.top - 1 || r.bottom > ar.bottom + 1)) return false;
    }
    return true;
  };
  const opener = (el) => {
    const details = el.closest('details');
    if (details && !details.open) {
      const summary = details.querySelector(':scope > summary');
      if (summary && inViewport(summary)) return true;
    }
    for (let a = el.parentElement; a; a = a.parentElement) {
      if (!a.id) continue;
      const btn = document.querySelector(`[aria-controls="${CSS.escape(a.id)}"]`);
      if (btn && inViewport(btn)) return true;
    }
    return false;
  };
  for (const nav of document.querySelectorAll('nav, [role="navigation"]')) {
    for (const link of nav.querySelectorAll('a[href]')) {
      out.nav.total++;
      if (!inViewport(link) && !opener(link)) out.nav.unreachable.push((link.textContent || link.getAttribute('href')).trim().slice(0, 40));
    }
  }

  // ED-4: overflowing scroll boxes must be keyboard-reachable; nothing may poke past the viewport
  // unless it is inside a scroll box or clipped by an ancestor that is itself inside the viewport.
  const all = document.body ? document.body.querySelectorAll('*') : [];
  const FOCUSABLE = 'a[href], button, input, select, textarea, [tabindex]';
  out.elements = all.length;
  out.measured = Math.min(all.length, cap);
  let n = 0;
  for (const el of all) {
    if (++n > cap) break;
    if (!visible(el)) continue;
    if (scrollsX(el) && el.scrollWidth > el.clientWidth + 1) {
      const keyboard = el.tabIndex >= 0 || !!el.querySelector(FOCUSABLE);
      const named = !(el.tabIndex >= 0 && !el.querySelector(FOCUSABLE)) || !!(el.getAttribute('aria-label') || el.getAttribute('aria-labelledby'));
      out.boxes.push({ el: label(el), keyboard, named });
    }
    const r = el.getBoundingClientRect();
    // Only the right edge: a page cannot scroll to the left of 0, so content parked there (a skip
    // link) makes no sideways scroll; content past the right edge does, or is cut off.
    if (r.right > vw + 1) {
      let held = false;
      for (let a = el.parentElement; a && a !== de && a !== document.body; a = a.parentElement) {
        if (scrollsX(a)) { held = true; break; }
        if (clipsX(a)) { const ar = a.getBoundingClientRect(); if (ar.right <= vw + 1 && ar.left >= -1) { held = true; break; } }
      }
      if (!held && out.past.length < 12) out.past.push(label(el));
    }
    // ED-5: a nested container that takes the viewport's height and scrolls on its own.
    if (/(auto|scroll)/.test(cs(el).overflowY) && el.scrollHeight > el.clientHeight + 1 && el.clientHeight >= vh * 0.9) out.nested.push(label(el));
  }
  // ED-5: the sticky band at the top, measured after scrolling so sticky elements engage.
  const startY = window.scrollY;
  window.scrollTo(0, Math.min(400, de.scrollHeight));
  for (const el of all) {
    const p = cs(el).position;
    if (p !== 'sticky' && p !== 'fixed') continue;
    const r = el.getBoundingClientRect();
    // A stuck element's visible part is what stays pinned; a negative top lets a header scroll away.
    if (r.height > 0 && r.top <= 2 && r.bottom > 0 && r.bottom < vh / 2 + 200) out.chrome = Math.max(out.chrome, Math.round(r.bottom));
  }
  // ED-5: the first in-page navigation anchor must land below the chrome.
  const anchor = [...document.querySelectorAll('nav a[href^="#"], [role="navigation"] a[href^="#"]')]
    .map((a) => document.getElementById(decodeURIComponent(a.getAttribute('href').slice(1)))).find(Boolean);
  if (anchor && de.scrollHeight > vh) {
    anchor.scrollIntoView({ block: 'start' });
    out.anchor = { el: label(anchor), top: Math.round(anchor.getBoundingClientRect().top) };
  }
  window.scrollTo(0, startY);
  out.rootMinWidth = parseFloat(cs(de).minWidth) || 0;
  out.floor = floor;
  return out;
}

export function verdicts(width, floor, m) {
  const rows = [];
  const add = (rule, verdict, evidence) => rows.push({ rule, width, verdict, evidence });
  if (width < floor) {
    add('ED-2', m.scrollWidth >= floor - 1 ? 'PASS' : 'FAIL',
      `below the floor ${floor}: document ${m.scrollWidth} px wide in ${m.vw} px (root min-width ${m.rootMinWidth || 'none'})`);
    return rows;
  }
  add('ED-1', m.scrollWidth <= m.vw + 1 ? 'PASS' : 'FAIL', `document scrollWidth ${m.scrollWidth} in a ${m.vw} px viewport`);
  if (!m.nav.total) add('ED-3', 'NOT_RUN', 'no <nav> or role="navigation" links on the page');
  else add('ED-3', m.nav.unreachable.length ? 'FAIL' : 'PASS',
    m.nav.unreachable.length ? `${m.nav.unreachable.length} of ${m.nav.total} links unreachable: ${m.nav.unreachable.slice(0, 6).join(', ')}` : `${m.nav.total} links reachable`);
  const badBoxes = m.boxes.filter((b) => !b.keyboard || !b.named);
  // A page larger than the walk: what the walk saw can fail, but it cannot pass for the whole page.
  const capped = m.elements > m.measured ? `only the first ${m.measured} of ${m.elements} elements measured` : '';
  const problems = [];
  if (m.past.length) problems.push(`past the viewport, not in a scroll box: ${m.past.slice(0, 4).join(', ')}`);
  if (badBoxes.length) problems.push(`scroll box without keyboard access or a name: ${badBoxes.slice(0, 4).map((b) => b.el).join(', ')}`);
  if (problems.length) add('ED-4', 'FAIL', problems.join('; ') + (capped ? `; ${capped}` : ''));
  else if (capped) add('ED-4', 'NOT_RUN', `${capped}: ${m.boxes.length} overflowing box(es) keyboard-reachable among them, the rest not seen`);
  else add('ED-4', 'PASS', `${m.boxes.length} overflowing box(es), each keyboard-reachable; edge shades not measured`);
  const limit = Math.min(120, m.vh / 4);
  const ed5 = [];
  if (m.chrome > limit) ed5.push(`sticky chrome ${m.chrome} px > ${Math.round(limit)} px`);
  if (m.nested.length) ed5.push(`nested full-height scroller: ${m.nested.slice(0, 3).join(', ')}`);
  if (m.anchor && m.anchor.top < m.chrome - 1) ed5.push(`anchor ${m.anchor.el} lands at ${m.anchor.top} px, under the ${m.chrome} px chrome`);
  add('ED-5', ed5.length ? 'FAIL' : 'PASS', ed5.join('; ') ||
    `sticky chrome ${m.chrome} px ≤ ${Math.round(limit)} px` + (m.anchor ? `; anchor lands at ${m.anchor.top} px` : '; no in-page anchor to jump to') + '; refresh keeps scroll: not measured' +
    (capped ? `; nested scrollers: ${capped}` : ''));
  return rows;
}

function report(rows, opts, target) {
  rows = rows.map((r) => ({ ...r, evidence: scrub(r.evidence) }));
  target = scrub(target);
  const failed = rows.filter((r) => r.verdict === 'FAIL').length;
  if (opts.json) {
    process.stdout.write(JSON.stringify({ target, browser: opts.browser, results: rows, failed }, null, 2) + '\n');
  } else {
    for (const r of rows) process.stdout.write(`${r.verdict.padEnd(8)} ${(r.rule + (r.width ? '@' + r.width : '')).padEnd(10)} ${r.evidence}\n`);
    process.stdout.write(`\n${rows.length} rule(s), ${failed} FAIL, ${rows.filter((r) => r.verdict === 'NOT_RUN').length} NOT_RUN\n`);
  }
  return failed ? 1 : 0;
}

async function main(argv) {
  const opts = parseArgs(argv);
  // What the report names: the service, never the login URL its one-time code is in.
  const shown = opts.service || opts.url;
  let target = opts.url;
  let floor = opts.floor;
  const notRun = (why) => report(RULES.map((rule) => ({ rule, width: 0, verdict: 'NOT_RUN', evidence: why })), opts, shown);
  // The browser first: a run that cannot measure must not spend a one-time code.
  const pw = await loadPlaywright(opts.playwright);
  if (!pw) return notRun('Playwright is not installed here: npm i -D playwright && npx playwright install webkit (or pass --playwright DIR)');
  let browser;
  try {
    browser = await pw[opts.browser].launch();
  } catch (err) {
    return notRun(`the ${opts.browser} browser does not start: ${String(err.message).split('\n')[0]} (npx playwright install ${opts.browser})`);
  }
  if (opts.service) {
    try {
      const t = await serviceTarget(opts.service, opts.servicesDir);
      target = t.url;
      if (floor === undefined && Number.isInteger(t.declared?.minWidth)) floor = t.declared.minWidth;
    } catch (err) {
      await browser.close();
      return notRun(`could not open the service's dashboard: ${err.message}`);
    }
  }
  floor = floor ?? 360;
  const rows = [];
  try {
    const context = await browser.newContext({ viewport: { width: Math.max(...opts.widths), height: opts.height } });
    const page = await context.newPage();
    const response = await page.goto(target, { waitUntil: 'load' });
    if (response && !response.ok()) {
      return notRun(`the page answered HTTP ${response.status()}`);
    }
    // Measure a settled page: its own data requests done, so a header that grows when the data
    // arrives is not caught between its new size and the script that reacts to it.
    await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
    const widths = [...new Set([floor - 40, ...opts.widths])].filter((w) => w >= 200).sort((a, b) => a - b);
    for (const width of widths) {
      await page.setViewportSize({ width, height: opts.height });
      await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
      await page.waitForTimeout(250);
      await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
      const m = await page.evaluate(measure, [floor, ELEMENT_CAP]);
      rows.push(...verdicts(width, floor, m));
    }
  } catch (err) {
    rows.push({ rule: 'ED-1', width: 0, verdict: 'NOT_RUN', evidence: `the page could not be measured: ${String(err.message).split('\n')[0]}` });
  } finally {
    await browser.close();
  }
  return report(rows, opts, shown);
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  main(process.argv.slice(2)).then((code) => process.exit(code), (err) => { process.stderr.write(String(err?.stack || err) + '\n'); process.exit(2); });
}
