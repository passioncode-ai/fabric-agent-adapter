/* fabric-dashboard-kit@1.1.3 · Fabric's button (Fabric Agent Contract DEC-0040, FB-1…FB-8, FL-1…FL-6)
   Load it same-origin, after fabric-dashboard.css, with the service it opens Fabric on:
     <script src="fabric-button.js" defer data-service="example-agent.default" data-service-name="Example Agent"
             data-project="project-a" data-project-name="Project A"></script>
   One floating menu button: "Chat with Fabric about <service>" and, when the page knows its project, "Open a coding
   session in <project>". Its links carry ids only and open a view in Fabric, nothing more (FB-8). It hides itself
   when the host draws its own (the fabric_button cookie, FB-6) and says how to get Fabric when Fabric is absent
   (FB-5). No inline script, no eval, nothing from a CDN; the only address it names is passioncode.ai/fabric.
   Do not edit in place; `dashboard_kit.py install` replaces it on an upgrade. */
(function (root) {
  'use strict';

  var VERSION = '1.1.3';
  var COOKIE = 'fabric_button';
  var GET_FABRIC = 'https://passioncode.ai/fabric';
  var ABSENT_AFTER_MS = 1500;
  var MAX_LINK_LENGTH = 2048;

  // ---- fabric:// links: a port of the contract's src/fabric-links.ts and src/secret-shape.ts (FL-1…FL-6) ----

  var AGENT_ID = /^[a-z][a-z0-9-]{1,62}(\.[a-z][a-z0-9-]{0,31})?$/;
  var PROJECT_REF = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
  var RUNNER_KIND = /^[a-z][a-z0-9-]{1,62}$/;
  var SHAPE = /^fabric:\/\/(chat|session\/new)\/?(?:\?([^#]*))?(?:#(.*))?$/;
  var KNOWN = {
    chat: { service: AGENT_ID, project: PROJECT_REF },
    'session.new': { project: PROJECT_REF, runner: RUNNER_KIND }
  };
  var PROMPT_WORDS = ['prompt', 'message', 'msg', 'text', 'instruction', 'instructions'];
  var CREDENTIAL_WORDS = ['token', 'secret', 'password', 'passwd', 'pass', 'passphrase', 'credential', 'credentials', 'cookie',
    'authorization', 'bearer', 'jwt', 'otp', 'apikey', 'signature', 'sig', 'accesstoken', 'idtoken', 'authtoken',
    'refreshtoken', 'sessionid', 'sessiontoken', 'logincode', 'authcode', 'privatekey', 'clientsecret', 'secretkey', 'accesskey'];
  var CREDENTIAL_PAIRS = {
    key: ['private', 'api', 'access', 'secret', 'session', 'auth', 'signing', 'encryption', 'master', 'client', 'login', 'refresh'],
    auth: ['token', 'code', 'header'],
    session: ['token', 'id'],
    code: ['login', 'auth', 'access', 'session']
  };
  var JWT_SHAPE = /eyJ[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]*/;
  var SECRET_VALUE = /(^bearer\s.+|sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abposr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|glpat-[A-Za-z0-9_-]{20,})/i;
  var LONG_RUN = /[A-Za-z0-9+/=_-]{40,}/g;

  function nameWords(name) {
    return name.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
      .split(/[\s._-]+/).filter(Boolean).map(function (w) { return w.toLowerCase(); });
  }
  function withSingulars(words) {
    return words.concat(words.filter(function (w) { return w.length > 2 && /s$/.test(w); }).map(function (w) { return w.slice(0, -1); }));
  }
  function credentialName(name) {
    var split = nameWords(name);
    var words = withSingulars(split);
    if (words.some(function (w) { return CREDENTIAL_WORDS.indexOf(w) >= 0; })) return true;
    if (split.length === 1 && words.some(function (w) { return Object.prototype.hasOwnProperty.call(CREDENTIAL_PAIRS, w); })) return true;
    return Object.keys(CREDENTIAL_PAIRS).some(function (w) {
      return words.indexOf(w) >= 0 && CREDENTIAL_PAIRS[w].some(function (p) { return words.indexOf(p) >= 0; });
    });
  }
  function longSecret(value) {
    return (value.match(LONG_RUN) || []).some(function (run) { return /[a-z]/.test(run) && /[A-Z]/.test(run) && /[0-9]/.test(run); });
  }
  function secretValue(value) { return JWT_SHAPE.test(value) || SECRET_VALUE.test(value) || longSecret(value); }
  function decodeKeepingPlus(raw) { try { return decodeURIComponent(raw); } catch (e) { return raw; } }
  function firstKey(text) { var it = new URLSearchParams(text).keys().next(); return it.done ? '' : it.value; }
  function rawValues(query) {
    var values = new Map();
    query.split('&').forEach(function (piece) {
      if (piece === '') return;
      var at = piece.indexOf('=');
      var name = firstKey(at < 0 ? piece : piece.slice(0, at));
      values.set(name, (values.get(name) || []).concat(at < 0 ? '' : decodeKeepingPlus(piece.slice(at + 1))));
    });
    return values;
  }
  function promptName(name) { return nameWords(name).some(function (w) { return PROMPT_WORDS.indexOf(w) >= 0; }); }
  function flat(lists) { return lists.reduce(function (a, b) { return a.concat(b); }, []); }

  /** The contract's parseFabricLink: {ok: true, link, ignored} or {ok: false, problems}. */
  function parseFabricLink(url) {
    if (url.length > MAX_LINK_LENGTH) return { ok: false, problems: ['a link is at most ' + MAX_LINK_LENGTH + ' characters'] };
    var match = SHAPE.exec(url.replace(/^fabric:/i, 'fabric:'));
    if (!match) return { ok: false, problems: ['not fabric://chat or fabric://session/new'] };
    var action = match[1] === 'chat' ? 'chat' : 'session.new';
    var params = new URLSearchParams(match[2] || '');
    var problems = [];
    var fragment = match[3] || '';
    if (fragment) {
      var pieces = Array.from(new URLSearchParams(fragment));
      var raw = flat(Array.from(rawValues(fragment).values()));
      if (secretValue(fragment) || raw.some(secretValue) || pieces.some(function (p) { return (p[1] !== '' && credentialName(p[0])) || secretValue(p[1]) || secretValue(p[0]); })) {
        problems.push('the fragment could carry a credential; a link never does');
      }
    }
    var ignored = [];
    var values = {};
    var known = KNOWN[action];
    var rawQuery = rawValues(match[2] || '');
    Array.from(new Set(Array.from(params.keys()))).forEach(function (name) {
      var all = params.getAll(name);
      if (promptName(name)) { problems.push('the parameter ' + name + ' carries words to act on; a link carries ids only'); return; }
      if (credentialName(name) || secretValue(name) || all.some(secretValue) || (rawQuery.get(name) || []).some(secretValue)) {
        problems.push('the parameter ' + name + ' could carry a credential; a link never does'); return;
      }
      var grammar = Object.prototype.hasOwnProperty.call(known, name) ? known[name] : undefined;
      if (!grammar) { ignored.push(name); return; }
      if (all.length > 1) { problems.push(name + ' is given ' + all.length + ' times'); return; }
      var value = all[0] || '';
      if (!grammar.test(value)) {
        problems.push(name + ' is not a valid ' + (name === 'service' ? 'agent id' : name === 'runner' ? 'runner kind' : 'project id or slug')); return;
      }
      values[name] = value;
    });
    var named = function (re) { return problems.some(function (p) { return re.test(p); }); };
    if (action === 'chat' && values.service === undefined && values.project === undefined && !named(/^(service|project) /)) problems.push('a chat link names a service, a project or both');
    if (action === 'session.new' && values.project === undefined && !named(/^project /)) problems.push('a session link names its project');
    if (problems.length) return { ok: false, problems: problems };
    var link = action === 'chat' ? { action: action } : { action: action, project: values.project };
    if (action === 'chat') { if (values.service) link.service = values.service; if (values.project) link.project = values.project; }
    else if (values.runner) link.runner = values.runner;
    return { ok: true, link: link, ignored: ignored };
  }

  /** The contract's buildFabricLink: throws on a value the grammar refuses, so a page cannot emit a bad link. */
  function buildFabricLink(link) {
    var query = new URLSearchParams();
    if (link.action === 'chat') {
      if (link.service !== undefined) query.set('service', link.service);
      if (link.project !== undefined) query.set('project', link.project);
    } else {
      query.set('project', link.project);
      if (link.runner !== undefined) query.set('runner', link.runner);
    }
    var url = 'fabric://' + (link.action === 'chat' ? 'chat' : 'session/new') + '?' + query.toString();
    var parsed = parseFabricLink(url);
    if (!parsed.ok) throw new TypeError(parsed.problems.join('; '));
    return url;
  }

  /** FB-6: the host's cookie as {owner, fabric}, or null when absent or of an unknown version. */
  function parseButtonCookie(cookieHeader) {
    if (typeof cookieHeader !== 'string' || !cookieHeader) return null;
    var parts = cookieHeader.split(';');
    for (var i = 0; i < parts.length; i++) {
      var part = parts[i].replace(/^\s+/, '');
      if (part.indexOf(COOKIE + '=') !== 0) continue;
      var raw = part.slice(COOKIE.length + 1);
      if (raw.charAt(0) === '"' && raw.charAt(raw.length - 1) === '"') raw = raw.slice(1, -1);
      var fields = new URLSearchParams(decodeKeepingPlus(raw));
      if (fields.get('v') !== '1') return null;
      var out = {};
      if (fields.get('owner') === 'host' || fields.get('owner') === 'page') out.owner = fields.get('owner');
      if (fields.get('fabric') === 'present' || fields.get('fabric') === 'absent') out.fabric = fields.get('fabric');
      return out;
    }
    return null;
  }

  /** The menu items for a page: the chat link always, the session link when the page knows its project. */
  function menuItems(options) {
    var items = [];
    var chat = { action: 'chat', service: options.service };
    if (options.project) chat.project = options.project;
    items.push({ label: 'Chat with Fabric about ' + (options.serviceName || options.service), href: buildFabricLink(chat) });
    if (options.project) {
      var session = { action: 'session.new', project: options.project };
      if (options.runner) session.runner = options.runner;
      items.push({ label: 'Open a coding session in ' + (options.projectName || options.project), href: buildFabricLink(session) });
    }
    return items;
  }

  // ---- the button (FB-1…FB-6) ----

  var SVG = 'http://www.w3.org/2000/svg';

  function mark(doc) {
    var svg = doc.createElementNS(SVG, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    svg.setAttribute('class', 'fd-fabric-button-mark');
    var path = doc.createElementNS(SVG, 'path');
    path.setAttribute('d', 'M5 5h14v3H8v3h9v3H8v5H5z'); // the Fabric mark: an F
    path.setAttribute('fill', 'currentColor');
    svg.appendChild(path);
    return svg;
  }

  function el(doc, tag, attrs, text) {
    var node = doc.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text !== undefined) node.textContent = text;
    return node;
  }

  /** Mount the button in `doc`. Returns the button, or null when the host draws its own (FB-1, FB-6). */
  function mount(doc, options) {
    var cookie = parseButtonCookie(doc.cookie);
    if (cookie && cookie.owner === 'host') return null;
    var items = menuItems(options);
    var absent = options.fabric === 'absent' || (cookie && cookie.fabric === 'absent');

    var wrap = el(doc, 'div', { 'class': 'fd-fabric-button-wrap' });
    var button = el(doc, 'button', { type: 'button', 'class': 'fd-fabric-button', 'aria-haspopup': 'menu', 'aria-expanded': 'false', 'aria-label': 'Open Fabric' });
    button.appendChild(mark(doc));
    button.appendChild(el(doc, 'span', { 'class': 'fd-fabric-button-label', 'aria-hidden': 'true' }, 'Fabric'));
    var menu = el(doc, 'div', { role: 'menu', 'class': 'fd-fabric-button-menu', 'aria-label': 'Fabric' });
    menu.hidden = true;
    var links = items.map(function (item) {
      var a = el(doc, 'a', { role: 'menuitem', href: item.href, tabindex: '-1', 'class': 'fd-fabric-button-item' }, item.label);
      menu.appendChild(a);
      return a;
    });
    var note = el(doc, 'p', { 'class': 'fd-fabric-button-note', role: 'note' });
    note.appendChild(doc.createTextNode('Fabric is not installed. Get it at '));
    // The way to get Fabric is a menu item too, so the arrows reach it whenever the note shows.
    var get = el(doc, 'a', { role: 'menuitem', href: GET_FABRIC, target: '_blank', rel: 'noopener', tabindex: '-1', 'class': 'fd-fabric-button-get' }, 'passioncode.ai/fabric');
    note.appendChild(get);
    note.hidden = !absent;
    menu.appendChild(note);
    wrap.appendChild(menu);
    wrap.appendChild(button);
    doc.body.appendChild(wrap);
    doc.documentElement.classList.add('fd-has-fabric-button');

    function reachable() { return note.hidden ? links : links.concat([get]); }
    function open(focusFirst) {
      menu.hidden = false;
      button.setAttribute('aria-expanded', 'true');
      if (focusFirst && reachable().length) reachable()[0].focus();
    }
    function close(refocus) {
      menu.hidden = true;
      button.setAttribute('aria-expanded', 'false');
      if (refocus) button.focus();
    }
    function move(by) {
      var all = reachable();
      if (!all.length) return;
      var at = all.indexOf(doc.activeElement);
      all[(at + by + all.length) % all.length].focus();
    }
    button.addEventListener('click', function () { if (menu.hidden) open(true); else close(true); });
    button.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault(); open(false);
        var all = reachable();
        if (all.length) (e.key === 'ArrowDown' ? all[0] : all[all.length - 1]).focus();
      }
    });
    menu.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); close(true); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
      else if (e.key === 'Home' || e.key === 'End') {
        e.preventDefault();
        var all = reachable();
        if (all.length) all[e.key === 'Home' ? 0 : all.length - 1].focus();
      }
      else if (e.key === 'Tab') { close(false); }
    });
    doc.addEventListener('click', function (e) { if (!menu.hidden && !wrap.contains(e.target)) close(false); });
    // FB-5: a page cannot see which schemes this computer handles. If, after following a link, the page is still
    // visible and focused 1.5 s later, Fabric did not take it: say how to get Fabric, once, and never retry.
    links.forEach(function (a) {
      a.addEventListener('click', function () {
        root.setTimeout(function () {
          if (doc.visibilityState === 'visible' && doc.hasFocus()) { note.hidden = false; open(false); }
        }, ABSENT_AFTER_MS);
      });
    });
    return button;
  }

  function optionsFrom(script) {
    var d = script.dataset;
    return { service: d.service, serviceName: d.serviceName, project: d.project, projectName: d.projectName, runner: d.runner, fabric: d.fabric };
  }

  var api = { version: VERSION, parseFabricLink: parseFabricLink, buildFabricLink: buildFabricLink, parseButtonCookie: parseButtonCookie,
    menuItems: menuItems, credentialName: credentialName, secretValue: secretValue, nameWords: nameWords, mount: mount };
  root.FabricButton = api;

  var doc = root.document;
  var script = doc && doc.currentScript;
  if (script && script.dataset && script.dataset.service) {
    var start = function () {
      try { mount(doc, optionsFrom(script)); } catch (err) { if (root.console) root.console.warn('fabric-button: not shown — ' + err.message); }
    };
    if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start); else start();
  }
})(typeof window !== 'undefined' ? window : globalThis);
