# The dashboard kit — `fabric-dashboard/0.1`

Fabric Dashboards shows a service's page in a pane beside its sidebar and the agent console, and the
operator drags the console wider whenever they need it. The page never knows how much room it will
get. Fabric Agent Contract DEC-0036 (`docs/specification/embedded-dashboard.md`, ED-1…ED-10) says what
the page promises; the kit in [`../assets/dashboard-kit/`](../assets/dashboard-kit/) keeps those
promises so a service does not re-derive them.

## Contents

- The rules the page keeps
- Using the kit
- Themes and the host's appearance
- Declaring it
- Proving it
- Upgrading an existing dashboard
- When something is missing

## The rules the page keeps

| Rule | What it means for the page | How the kit does it |
|---|---|---|
| ED-1 floor | usable from 360 CSS px up (or the larger `minWidth` it declares), no sideways document scroll | fluid grids `repeat(auto-fit, minmax(min(100%, N), 1fr))`, no fixed widths, `overflow-wrap` on text |
| ED-2 below the floor | keeps the floor layout and lets the document scroll | `html { min-width: 360px }` |
| ED-3 navigation | every destination reachable at every width, never a strip that only scrolls sideways | the list wraps; with the script, links that do not fit move into a **More** menu |
| ED-4 wide content | tables, logs, code, charts scroll in their own box, which shows it scrolls and takes keyboard focus | `.fd-scroll`: edge shades, a visible scrollbar, `tabindex="0"` and a name added by the script |
| ED-5 one scroller | the document is the only full-height scroller; sticky chrome ≤ min(120 px, 25 % of the height); anchors land below it; a refresh keeps scroll and focus | `.fd-chrome` sticky; when header + navigation are taller than the budget the header scrolls away and the navigation stays; `scroll-margin-top` from the measured height |
| ED-6 appearance | follows `prefers-color-scheme`; the host's cookie wins over the page's own choice and hides the page's controls; colour never carries meaning alone | the script reads `fabric_appearance`, sets `data-theme`/`data-scheme`, hides `[data-fd-appearance-control]` |

The kit cannot keep two of them for you: **a refresh must keep the scroll position and focus**
(replace changed regions, never the whole page; see [dashboard principles](dashboard.md) point 3),
and **meaning never by colour alone** (put the word next to the dot: `.fd-chip` with a `.fd-dot`).

## Using the kit

```bash
python3 <skill-dir>/scripts/dashboard_kit.py install <the directory your page's static files are served from>
```

It copies `fabric-dashboard.css` and `fabric-dashboard.js` (each starts with
`fabric-dashboard-kit@<version>`). Serve both same-origin and link them; nothing is inline:

```html
<html lang="en" data-fd-appearance="scheme theme">
<link rel="stylesheet" href="/static/fabric-dashboard.css">
<link rel="stylesheet" href="/static/app.css">            <!-- the page's own rules, var(--…) only -->
<script src="/static/fabric-dashboard.js" defer></script>
```

Never edit the copied files: the page's own rules go in its own stylesheet, consuming the tokens.
`install` refuses to replace a copy the service changed. The page's skeleton is in
[`demo.html`](../assets/dashboard-kit/demo.html); the parts:

| Part | Markup |
|---|---|
| Sticky chrome | `<div class="fd-chrome"><header class="fd-header">…</header><nav class="fd-nav" aria-label="Sections"><ul class="fd-nav-list"><li><a href="#jobs">Jobs</a></li>…</ul></nav></div>` |
| Page body | `<main class="fd-page">`, sections with `id`s the navigation links to |
| Grids | `.fd-grid` (cards, 320 px columns), `.fd-grid--tiles` (160 px), `.fd-grid--wide` (480 px); `--fd-col` sets your own |
| Wide content | `<div class="fd-scroll" data-fd-label="Jobs table"><table class="fd-table">…</table></div>`, `<pre class="fd-scroll">` |
| Atoms | `.fd-card`, `.fd-tile`, `.fd-chip` + `.fd-dot` + `.fd-s-ok\|warn\|danger\|info`, `.fd-btn`, `.fd-btn--primary`, `.fd-input`, `.fd-select`, `.fd-banner`, `.fd-empty`, `.fd-pairs` |
| Own appearance controls | `<select data-fd-theme-picker>`, `<select data-fd-scheme-picker>` (the script fills them; hidden while the host owns appearance) |

Tokens are the workbench layer (`--bg`, `--panel`, `--panel-2`, `--ink`, `--muted`, `--border`,
`--border-strong`, `--accent`, `--accent-weak`, `--accent-ink`, the four status pairs) plus `--edge`,
a border that carries meaning (inputs, menus, scroll boxes) at 3:1. Accent-coloured text sits only on
`--panel`. Status words stay in `--ink`; the colour is in the dot and the tint.

## Themes and the host's appearance

Seven reference themes, each light and dark, all WCAG 2.2 AA (ED-10): `graphite` (default, workbench
verbatim), `fabric` (PassionCode.ai plum), `paper`, `forest`, `ocean`, `ember`, `contrast`. They are
generated from `themes.json` into the CSS by `dashboard_kit.py build`; `test/test_dashboard_kit.py`
measures every pair. A page selects one with `<html data-theme="ocean" data-scheme="dark">`; without
`data-scheme` it follows the operator's system.

The host carries the operator's choice as the cookie `fabric_appearance=v=1&scheme=dark&theme=ocean`
(ED-8). The script applies it, marks the root `data-fd-host-appearance` and hides the page's own
controls while it is present; an unknown `theme` is `graphite`. `data-fd-appearance="scheme"` limits
what the page applies (declare the same in `appearance`). The page re-reads the cookie when it
changes (`cookieStore`) and when it becomes visible again.

## Declaring it

When the page meets ED-1…ED-6, say so in the well-known document (ED-9):

```python
fs.build_well_known(..., extensions=fs.dashboard_extension())          # minWidth 360, both fields, 7 themes, the kit
```

Node: `buildWellKnown({ ..., extensions: dashboardExtension() })`. Pass `min_width`/`minWidth` when the
page needs more than 360 (a host then gives it `max(480, minWidth)`), and `themes` when the page ships
fewer. A dashboard without the declaration is a *legacy dashboard*: the host still gives it 480 px
and promises nothing else.

## Proving it

```bash
node <skill-dir>/scripts/check_dashboard_layout.mjs --service <id>[.<instance>]   # signs in with a login code
node <skill-dir>/scripts/check_dashboard_layout.mjs http://127.0.0.1:<port>/dashboard
python3 <skill-dir>/scripts/check_service.py <id>                                   # dashboard.declared (ED-9)
```

The layout probe renders the page in WebKit (Safari's engine; `--browser chromium` on request) at
the floor minus 40 and at 360, 480, 768 and 1280 px, and reports ED-1…ED-5 per width. It needs
Playwright where it runs (`npm i -D playwright && npx playwright install webkit`, or `--playwright
<dir>`); without it every rule is `NOT_RUN`. It does not measure edge shades or that a refresh keeps
the scroll position: say so in the report. A `NOT_RUN` is not a pass.

## Upgrading an existing dashboard

A session that starts in a repository whose dashboard has no kit or an older one gets one line from
the plugin's SessionStart hook. That line is a notice, not an instruction to act: **tell the
operator and update only with their go-ahead** — the page is theirs and may be open while you work.

1. `dashboard_kit.py status` names each copy: `current`, `older`, `changed` (edited after it was
   copied) or `unmarked`, and the services built from this repository.
2. A page with no kit: move its colour, type and spacing values onto the kit's tokens (its own
   palette becomes a theme in its stylesheet: `:root[data-theme="…"]`), replace fixed widths with the
   kit's grids, put the navigation in `.fd-nav`, wrap wide tables and logs in `.fd-scroll`, remove
   any nested full-height scroller, and drop a scheme toggle the kit's picker replaces.
3. A page with an older kit: `dashboard_kit.py install <dir>`. A `changed` copy is refused; move the
   edits into the page's own files, then install (or `--force` when the operator says the edits go).
4. Raise `kit` in the declaration (`dashboard_extension()` does it), restart the service, and run
   both probes above. Report the layout table with every `NOT_RUN`.

## When something is missing

- **No Python for the CLI:** copy the two files from `assets/dashboard-kit/` by hand and compare the
  first line's version with `kit.json`.
- **The page is built by a framework:** import the two files as static assets; keep them unbundled
  or keep the version marker comment, so `status` can still read the version.
- **The page needs a fixed width:** not decided by the profile; declare the `minWidth` it needs
  (up to 1280) and say why in the README.
