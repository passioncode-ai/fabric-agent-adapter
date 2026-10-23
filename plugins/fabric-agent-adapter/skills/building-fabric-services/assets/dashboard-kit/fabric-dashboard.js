/* fabric-dashboard-kit@1.1.3 · fabric-dashboard/0.1 (Fabric Agent Contract DEC-0036)
   Load it same-origin with <script src="fabric-dashboard.js" defer></script>: no inline script, no
   eval, nothing from a CDN. It applies the host's appearance (ED-6, ED-8), folds navigation that
   does not fit into a More menu (ED-3), makes wide boxes keyboard-reachable (ED-4) and keeps
   anchors below the sticky chrome (ED-5). Without it the page still holds: the navigation wraps.
   Do not edit in place; `dashboard_kit.py install` replaces it on an upgrade. */
(function (root) {
  'use strict';

  var KIT = 'fabric-dashboard-kit';
  var VERSION = '1.1.3';
  /* fabric-dashboard-kit:theme-ids:begin */
  var THEMES = ['graphite', 'fabric', 'paper', 'forest', 'ocean', 'ember', 'contrast'];
/* fabric-dashboard-kit:theme-ids:end */
  var DEFAULT_THEME = 'graphite';
  var COOKIE = 'fabric_appearance';
  var STORE_KEY = 'fabric-dashboard:appearance';
  var THEME_ID = /^[a-z][a-z0-9-]{0,31}$/;

  /** The carrier cookie's value as {scheme, theme}, or null when absent or of an unknown version.
      Fields that are missing or malformed are left out; the page then uses its defaults. */
  function parseAppearance(cookieHeader) {
    if (typeof cookieHeader !== 'string' || !cookieHeader) return null;
    var parts = cookieHeader.split(';');
    for (var i = 0; i < parts.length; i++) {
      var part = parts[i].replace(/^\s+/, '');
      if (part.indexOf(COOKIE + '=') !== 0) continue;
      var raw = part.slice(COOKIE.length + 1);
      if (raw.charAt(0) === '"' && raw.charAt(raw.length - 1) === '"') raw = raw.slice(1, -1);
      var fields = {};
      try { raw = decodeURIComponent(raw); } catch (e) { return null; }
      raw.split('&').forEach(function (pair) {
        var eq = pair.indexOf('=');
        if (eq > 0) fields[pair.slice(0, eq)] = pair.slice(eq + 1);
      });
      if (fields.v !== '1') return null;
      var out = {};
      if (fields.scheme === 'light' || fields.scheme === 'dark') out.scheme = fields.scheme;
      if (fields.theme && THEME_ID.test(fields.theme)) out.theme = fields.theme;
      return out;
    }
    return null;
  }

  /** What the page shows: the host's choice wins over the stored one (ED-6); an unknown theme is
      the default theme; a missing scheme follows prefers-color-scheme (returned as null). */
  function resolveAppearance(host, stored, themes, applies) {
    themes = themes || THEMES;
    applies = applies || ['scheme', 'theme'];
    var source = host || stored || {};
    var theme = applies.indexOf('theme') >= 0 ? source.theme : undefined;
    var scheme = applies.indexOf('scheme') >= 0 ? source.scheme : undefined;
    return {
      theme: theme && themes.indexOf(theme) >= 0 ? theme : DEFAULT_THEME,
      scheme: scheme === 'light' || scheme === 'dark' ? scheme : null,
      host: !!host
    };
  }

  var api = { kit: KIT, version: VERSION, themes: THEMES.slice(), parseAppearance: parseAppearance, resolveAppearance: resolveAppearance };
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (typeof document === 'undefined') return;

  var doc = document;
  var html = doc.documentElement;
  root.FabricDashboard = api;

  function readStored() {
    try {
      var v = JSON.parse(root.localStorage.getItem(STORE_KEY) || 'null');
      return v && typeof v === 'object' ? v : null;
    } catch (e) { return null; }
  }
  function writeStored(v) {
    try { root.localStorage.setItem(STORE_KEY, JSON.stringify(v)); } catch (e) { /* private window: the choice lasts this visit */ }
  }
  function applies() {
    var declared = html.getAttribute('data-fd-appearance');
    return declared == null ? ['scheme', 'theme'] : declared.split(/\s+/).filter(Boolean);
  }

  function applyAppearance() {
    var host = parseAppearance(doc.cookie);
    var a = resolveAppearance(host, readStored(), THEMES, applies());
    if (a.theme === DEFAULT_THEME) html.removeAttribute('data-theme'); else html.setAttribute('data-theme', a.theme);
    if (a.scheme) html.setAttribute('data-scheme', a.scheme); else html.removeAttribute('data-scheme');
    if (a.host) html.setAttribute('data-fd-host-appearance', ''); else html.removeAttribute('data-fd-host-appearance');
    syncPickers(a);
    return a;
  }

  /* ---- the page's own appearance controls (hidden while the host owns appearance) ---- */
  function syncPickers(a) {
    var themePickers = doc.querySelectorAll('select[data-fd-theme-picker]');
    for (var i = 0; i < themePickers.length; i++) themePickers[i].value = a.theme;
    var schemePickers = doc.querySelectorAll('select[data-fd-scheme-picker]');
    for (var j = 0; j < schemePickers.length; j++) schemePickers[j].value = a.scheme || 'auto';
  }
  function setupPickers() {
    var themePickers = doc.querySelectorAll('select[data-fd-theme-picker]');
    for (var i = 0; i < themePickers.length; i++) {
      var sel = themePickers[i];
      sel.setAttribute('data-fd-appearance-control', '');
      if (!sel.options.length) {
        THEMES.forEach(function (id) {
          var opt = doc.createElement('option');
          opt.value = id;
          opt.textContent = id.charAt(0).toUpperCase() + id.slice(1);
          sel.appendChild(opt);
        });
      }
      sel.addEventListener('change', function (e) {
        var stored = readStored() || {};
        stored.theme = e.target.value;
        writeStored(stored);
        applyAppearance();
      });
    }
    var schemePickers = doc.querySelectorAll('select[data-fd-scheme-picker]');
    for (var j = 0; j < schemePickers.length; j++) {
      var s = schemePickers[j];
      s.setAttribute('data-fd-appearance-control', '');
      if (!s.options.length) {
        [['auto', 'System'], ['light', 'Light'], ['dark', 'Dark']].forEach(function (o) {
          var opt = doc.createElement('option');
          opt.value = o[0];
          opt.textContent = o[1];
          s.appendChild(opt);
        });
      }
      s.addEventListener('change', function (e) {
        var stored = readStored() || {};
        if (e.target.value === 'auto') delete stored.scheme; else stored.scheme = e.target.value;
        writeStored(stored);
        applyAppearance();
      });
    }
  }

  function watchAppearance() {
    if (root.cookieStore && typeof root.cookieStore.addEventListener === 'function') {
      root.cookieStore.addEventListener('change', function (e) {
        var touched = [].concat(e.changed || [], e.deleted || []);
        for (var i = 0; i < touched.length; i++) if (touched[i].name === COOKIE) { applyAppearance(); return; }
      });
    }
    doc.addEventListener('visibilitychange', function () { if (!doc.hidden) applyAppearance(); });
    root.addEventListener('focus', applyAppearance);
  }

  /* ---- navigation: fold what does not fit into More (ED-3) ---- */
  function foldNav(nav) {
    if (typeof nav.fdRefresh === 'function') { nav.fdRefresh(); return; } // folded already: refit, no second observers
    var list = nav.querySelector('.fd-nav-list');
    if (!list) return;
    nav.classList.add('fd-nav--fold');
    var more = nav.querySelector(':scope > .fd-more');
    if (!more) {
      more = doc.createElement('details');
      more.className = 'fd-more';
      var summary = doc.createElement('summary');
      summary.textContent = nav.getAttribute('data-fd-more-label') || 'More';
      var menu = doc.createElement('ul');
      menu.className = 'fd-more-list';
      more.appendChild(summary);
      more.appendChild(menu);
      nav.appendChild(more);
      more.addEventListener('click', function (e) {
        if (e.target.closest && e.target.closest('a')) more.open = false;
      });
      more.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && more.open) { more.open = false; summary.focus(); }
      });
      doc.addEventListener('click', function (e) { if (more.open && !more.contains(e.target)) more.open = false; });
    }
    var menuList = more.querySelector('.fd-more-list');
    var summaryEl = more.querySelector('summary');
    var label = nav.getAttribute('data-fd-more-label') || 'More';

    // An item that sticks out by a fraction of a pixel is cut but leaves scrollWidth (rounded) unchanged: compare the
    // last item's edge with the list's, on the side the text runs to.
    var overflows = function () {
      if (list.scrollWidth > list.clientWidth + 1) return true;
      var last = list.lastElementChild;
      if (!last) return false;
      var a = last.getBoundingClientRect(), b = list.getBoundingClientRect();
      return root.getComputedStyle(list).direction === 'rtl' ? a.left < b.left - 0.5 : a.right > b.right + 0.5;
    };
    function summarize() {
      var current = menuList.querySelector('[aria-current]:not([aria-current="false"])');
      summaryEl.textContent = current ? label + ': ' + current.textContent.trim() : label + ' (' + menuList.children.length + ')';
    }
    function layout() {
      // Moving a focused link out of the document loses focus: keep it on the same link across the refit.
      var focused = doc.activeElement && nav.contains(doc.activeElement) ? doc.activeElement : null;
      fit();
      if (focused && focused.isConnected && doc.activeElement !== focused) focused.focus({ preventScroll: true });
    }
    function fit() {
      // Put every item back in its place, then move the last ones out until the rest fit.
      while (menuList.firstChild) list.appendChild(menuList.firstChild);
      more.hidden = true;
      if (!overflows()) { summaryEl.textContent = label; return; }
      more.hidden = false;
      var items = list.children;
      // The summary names the current section or counts the folded ones, and its text takes room from the list, so
      // set it after every move and measure again with it in place (a longer summary left a half-cut item, FAA-104).
      summarize();
      while (items.length && overflows()) {
        menuList.insertBefore(items[items.length > 1 ? items.length - 1 : 0], menuList.firstChild);
        summarize();
      }
    }
    layout();
    if (typeof root.ResizeObserver === 'function') new root.ResizeObserver(function () { layout(); }).observe(nav);
    else root.addEventListener('resize', layout);
    // A page that moves aria-current (its route changed) gets a fresh summary and fit, without telling the kit.
    if (typeof root.MutationObserver === 'function') {
      new root.MutationObserver(layout).observe(nav, { subtree: true, attributes: true, attributeFilter: ['aria-current'] });
    }
    nav.fdRefresh = layout;
  }

  /* A page can also ask for a new fit itself, for example after it changed the items' text. */
  function refreshNav(nav) {
    if (nav && typeof nav.fdRefresh === 'function') nav.fdRefresh();
  }

  /* ---- wide boxes: keyboard-reachable, with a name, marked when they overflow (ED-4) ---- */
  var FOCUSABLE = 'a[href], button, input, select, textarea, [tabindex]';
  function prepareScrollBox(box) {
    if (!box.querySelector(FOCUSABLE) && !box.hasAttribute('tabindex')) {
      box.setAttribute('tabindex', '0');
      if (!box.hasAttribute('role')) box.setAttribute('role', 'region');
      if (!box.hasAttribute('aria-label') && !box.hasAttribute('aria-labelledby')) {
        var caption = box.querySelector('caption');
        box.setAttribute('aria-label', box.getAttribute('data-fd-label') || (caption && caption.textContent.trim()) || 'Scrollable content');
      }
    }
    function mark() {
      if (box.scrollWidth > box.clientWidth + 1) box.setAttribute('data-fd-overflow', '');
      else box.removeAttribute('data-fd-overflow');
    }
    mark();
    if (typeof root.ResizeObserver === 'function') new root.ResizeObserver(mark).observe(box);
  }

  /* ---- sticky chrome: at most min(120 px, a quarter of the height) stays pinned (ED-5) ---- */
  function measureChrome() {
    var chrome = doc.querySelector('.fd-chrome');
    if (!chrome) return;
    function set() {
      var height = Math.ceil(chrome.getBoundingClientRect().height);
      var limit = Math.min(parseFloat(getComputedStyle(html).getPropertyValue('--fd-chrome-max')) || 120, root.innerHeight / 4);
      var header = chrome.querySelector('.fd-header');
      var lift = 0;
      if (height > limit && header) lift = Math.min(Math.ceil(header.getBoundingClientRect().height), height);
      html.style.setProperty('--fd-chrome-top', lift ? -lift + 'px' : '0px');
      html.style.setProperty('--fd-chrome-h', Math.max(0, height - lift) + 'px');
    }
    set();
    if (typeof root.ResizeObserver === 'function') new root.ResizeObserver(set).observe(chrome);
    root.addEventListener('resize', set);
  }

  function init() {
    html.classList.add('fd-js');
    setupPickers();
    applyAppearance();
    watchAppearance();
    var navs = doc.querySelectorAll('nav.fd-nav');
    for (var i = 0; i < navs.length; i++) if (!navs[i].hasAttribute('data-fd-no-fold')) foldNav(navs[i]);
    var boxes = doc.querySelectorAll('.fd-scroll');
    for (var j = 0; j < boxes.length; j++) prepareScrollBox(boxes[j]);
    measureChrome();
  }

  api.applyAppearance = applyAppearance;
  api.prepareScrollBox = prepareScrollBox;
  api.foldNav = foldNav;
  api.refreshNav = refreshNav;
  // Apply the theme before first paint when loaded without defer; the rest waits for the DOM.
  applyAppearance();
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', init); else init();
})(typeof window !== 'undefined' ? window : this);
