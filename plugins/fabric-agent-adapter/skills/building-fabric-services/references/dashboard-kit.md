# The dashboard kit: `fabric-dashboard/0.1`

Fabric Dashboards shows a service's page in a pane beside its sidebar and the agent console, and the
operator drags the console wider whenever they need it. The page never knows how much room it will
get. Fabric Agent Contract DEC-0036 (`docs/specification/embedded-dashboard.md`, ED-1…ED-10) says what
the page promises; the kit in [`../assets/dashboard-kit/`](../assets/dashboard-kit/) keeps those
promises so a service does not re-derive them.

## Contents

- The rules the page keeps
- Using the kit
- Themes and the host's appearance
- Fabric's button
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
| Navigation that folds | with the script, links that do not fit move into **More** (`data-fd-more-label` names it, `data-fd-no-fold` keeps a nav as is); the summary names the current section (`aria-current`) or counts the folded links, and the fit is measured with that text in place. Moving `aria-current` refits on its own; after changing the links' text call `FabricDashboard.refreshNav(nav)` (since 1.1.3) |
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

## Fabric's button

The kit ships Fabric's button (contract DEC-0040, FB-7): one floating menu button that opens Fabric on this
service. Load it after the stylesheet, with ids only:

```html
<script src="fabric-button.js" defer data-service="example-agent.default" data-service-name="Example Agent"
        data-project="project-a" data-project-name="Project A"></script>
```

- **The menu (FB-4):** "Chat with Fabric about *Example Agent*" always; "Open a coding session in *Project A*" when
  the page knows its project (`data-runner` picks the runner kind). Arrows move, Escape closes and returns focus.
- **Words (since 1.1.4):** English by default, Russian when the page says `<html lang="ru">` (any `ru-*`). The page
  sets its own with `data-label-chat` and `data-label-session` (`{name}` is the service or the project),
  `data-label-open` (the button's accessible name) and `data-label-absent` (the sentence before the link to
  passioncode.ai/fabric). A blank attribute keeps the built-in words; `FabricButton.labelsFor(lang, overrides)` returns
  what a page gets. Product names stay in English in every language.
- **Placement and look (FB-2, FB-3):** bottom-right (bottom-left right-to-left), 16 px off and clear of the safe
  area, above the sticky chrome and below dialogs; the page keeps its height plus 16 px free at the end of the
  scroll. The mark and the word *Fabric*, the mark alone below 480 px; the accessible name is *Open Fabric* (*Открыть
  Fabric* on a Russian page, or the page's `data-label-open`);
  `--ink` on `--panel` with an `--edge` boundary, the pairs the themes are measured on.
- **Links (FL-1…FL-6):** built with the kit's port of the contract's `buildFabricLink`; a value outside the grammar
  (or one shaped like a credential) means no button, never a bad link. A press opens a view in Fabric and starts
  nothing (FB-8).
- **The host (FB-6):** when the host's `fabric_button` cookie says `owner=host`, the page hides its own button.
- **Fabric absent (FB-5):** when the cookie says `fabric=absent`, or `data-fabric="absent"`, or when the page is still
  visible and focused 1.5 s after a link was followed, the menu says that Fabric is not installed and names
  passioncode.ai/fabric to get it. Nothing downloads, nothing retries. A local service's server decides `data-fabric` with
  `fabric_button_presence()` / `fabricButtonPresence()`: `present` while Fabric's own descriptor
  (`services/fabric.default.json`, Fabric ADR-0139) is registered and, for an app's descriptor (`manager: "person"`,
  DEC-0069), its app is still installed; `absent` otherwise. A press only follows a link, so the button never reads
  Fabric's liveness file; a caller that sends Fabric anything reads that file and checks the process first.

`window.FabricButton` exposes `buildFabricLink`, `parseFabricLink` and `parseButtonCookie` for a page that needs
them. The button is optional: a page without the script has no button.

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
<dir>`); without it every rule is `NOT_RUN`, and the probe asks for no login code. ED-3 also fails a link clipped
vertically by the viewport or a clipping ancestor; ED-4 is `NOT_RUN` on a page past its 6000-element cap. It does not measure edge shades or that a refresh keeps
the scroll position: say so in the report. A `NOT_RUN` is not a pass. Exit codes: 0 when no rule fails and at least
one passed, 1 on a `FAIL`, 2 on a usage error, 3 when no rule was measured (every rule `NOT_RUN`, since 0.44.0).

## Upgrading an existing dashboard

A session that starts (or is cleared) in a repository that owns a service, whose dashboard has no
kit or an older one, gets one line from the plugin's SessionStart hook. A repository owns a service
when a descriptor names it as `source.repository`; nowhere else does the line appear, and it names
only that repository's services. **The upgrade is yours to make** when your task lets you change
this repository: do it, keep the service's own edits (step 3), and say in your report what changed.
In the middle of an unrelated task, finish that first or record the upgrade as a next task.

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

- **No Python for the CLI:** copy the files from `assets/dashboard-kit/` by hand and compare the
  first line's version with `kit.json`.
- **The page is built by a framework:** import the files as static assets; keep them unbundled
  or keep the version marker comment, so `status` can still read the version.
- **The page needs a fixed width:** not decided by the profile; declare the `minWidth` it needs
  (up to 1280) and say why in the README.
