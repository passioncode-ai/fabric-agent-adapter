# FAA-17 — the dashboard kit (`fabric-dashboard/0.1`, contract DEC-0036)

Run: task-pipeline, 2026-10-11. Branch `agent/faa-17-dashboard-kit`. Contract decision DEC-0036 merged
into fabric-agent-contract `main` as `a83bec6b47776af688402c18efec507143061f68` (PR #27).

## Objective

A Fabric service's dashboard is shown inside Fabric Dashboards beside the agent console. The console
can take up to half the window, so a page that assumed a desktop width loses its navigation and
scrolls sideways (measured on the brand board: 4 of 14 navigation links visible at 380 px, a 410 px
document in a 380 px view). DEC-0036 states what a page promises (ED-1…ED-6), what a host promises
(ED-7, ED-8) and how a page declares it (ED-9, ED-10). This run gives every agent built with the
adapter a kit that meets the page side, a probe that measures it, a declaration check, and a notice
that tells an already-built dashboard it has an update to take.

## Source ledger

| Source | What it gave |
|---|---|
| contract `docs/specification/embedded-dashboard.md` @ `a83bec6` | ED-1…ED-10, the carrier cookie, the reference theme ids, the probe's named rules |
| contract `schemas/service-dashboard-extension.schema.json` @ `a83bec6` | the ED-9 declaration shape the probe checks |
| sshlg-brand-agent `docs/handoffs/2026-10-11-embedded-dashboard-profile.md` | the operator's decisions (360/480, release), the kit's file list, the hook's detection rule |
| sheleg-design `styles/workbench.md` (1.64.0) | the graphite token layer verbatim, its AA gotchas (status words in `--ink`, no accent text on `--bg`/`--panel-2`) |
| this repository `AGENTS.md`, `docs/backlog.md`, `test/validate.py`, commit `3537587` | the pin-move precedent, version sync, stdlib-only scripts, evals before prose, LC-09 footprint |
| `building-fabric-services/references/dashboard.md` | the existing page principles the kit extends (CSP, calm refresh, partial failure) |
| graph | none built for this repository (`graphify-out/` absent) |
| wiki | the projects wiki holds no page on DEC-0036 or a dashboard kit (grep, 2026-10-11) |
| retro | no `docs/evidence/retro.md`; the one retrospective is `retrospectives/2026-08-27-retro.md` |

## Decisions (the grill, resolved from the operator's recorded decisions)

The operator's standing instruction of 2026-10-11 (relayed by fabric-switchboard-93) is not to stop
for confirmation; every branch below is resolved from a recorded decision or the recommended default.

1. **Floor 360, host floor 480** — the operator, 2026-10-11 (handoff).
2. **Graphite is workbench verbatim**; the other six reference themes are new palettes in the same
   structure (same token names, same radii, type and spacing; only colours change). They are this
   run's design decisions, made out loud; the AA test is their judge, not taste.
3. **Theme selection in markup**: `<html data-theme="<id>" data-scheme="light|dark">`. With no
   `data-scheme` the page follows `prefers-color-scheme`. An unknown theme falls back to graphite (ED-6).
4. **One source for palettes**: `themes.json`; `dashboard_kit.py build` writes the theme block of
   `fabric-dashboard.css` between markers, and a test fails when the two disagree.
5. **Plain files, no build step for consumers**: a CSS file and a classic script, both same-origin and
   CSP-clean (no inline script, no `eval`, no CDN).
6. **Layout probe uses Playwright WebKit by default** (Safari first, the operator's browser rule);
   `--browser chromium|firefox` when asked. Without Playwright every rule is `NOT_RUN` with the reason.
7. **`dashboard.declared` is NOT_RUN, not FAIL, for an undeclared dashboard** — ED-9 is a SHOULD; a
   legacy dashboard is still protected by ED-7. A declared value that breaks the schema is a FAIL.
8. **The notice is a plugin SessionStart hook** that prints one line only in a repository whose
   dashboard has no kit or an older one, and nothing elsewhere; it always exits 0 and never writes.
   It tells the agent to update with the operator's go-ahead. LC-09 in `AGENTS.md` declares it.
9. **Versions**: kit `1.0.0` (the contract fixture names `fabric-dashboard-kit@1.0.0`); adapter `0.9.0`.
10. **Pin**: the default contract pin moves to `a83bec6`; `52da526` joins the supported revisions.
11. **Release**: PR, CI read, merge, then the `v0.9.0` tag. The tag publishes to npm, so pushing it
    is the operator's approval step; the launcher re-pin follows the release.

## REQ table (frozen; adding is free, removing needs the operator)

| REQ | Requirement | Verified by |
|---|---|---|
| REQ-1 | `assets/dashboard-kit/fabric-dashboard.css`: token layer, 7 reference themes × light/dark, root `min-width: 360px`, fluid grids, wrapping nav + More menu styles, scroll boxes with edge shades and keyboard focus, sticky chrome ≤ 120 px with `scroll-margin-top` | `test/test_dashboard_kit.py` (structure), layout probe on the demo page |
| REQ-2 | Every theme meets WCAG 2.2 AA in both schemes: body text 4.5:1, muted text 4.5:1, borders that carry meaning and focus rings 3:1, accent-ink on accent 4.5:1 | `test/test_dashboard_kit.py::ThemeContrast` |
| REQ-3 | `fabric-dashboard.js`: reads `fabric_appearance` (v=1), applies scheme/theme, hides page appearance controls while the cookie is present, re-applies on cookie change or visibility, folds overflowing nav links into More, marks overflowing boxes, optional theme picker | `test/fabric-dashboard-kit.test.mjs` (cookie parser), layout probe on the demo page |
| REQ-4 | `kit.json`: kit name, version, sha256 of each kit file, theme ids; matches the files | `test/test_dashboard_kit.py::KitManifest` |
| REQ-5 | `scripts/check_dashboard_layout.mjs`: ED-1, ED-2, ED-3, ED-4, ED-5 measured at 360/480/768/1280 (and below the floor), PASS/FAIL/NOT_RUN table or `--json`; `--service <id>` signs in with a login code; NOT_RUN without Playwright | `test/test_dashboard_layout.py` (demo page passes, a planted broken page fails; NOT_RUN path) |
| REQ-6 | `check_service.py` rule `dashboard.declared` (ED-9): PASS for a valid declaration, FAIL for an invalid one, NOT_RUN for none | `test/test_dashboard_kit.py::DeclaredRule` + the existing probe tests |
| REQ-7 | Both kits' `build_well_known` accept `extensions`; a `dashboard_extension()` helper builds the ED-9 value; the sample service declares it | `test/test_fabric_service.py`, `test/fabric-service.test.mjs` |
| REQ-8 | `scripts/dashboard_kit.py status|install|build|notice`: status reports kit version per repository; install copies the kit files into a directory, never overwriting a changed file without `--force`; build regenerates the theme block | `test/test_dashboard_kit.py::Cli` |
| REQ-9 | Plugin SessionStart hook: one line in a repo with an un-kitted or older-kit dashboard, silence elsewhere, exit 0 always, under 300 ms | `test/test_dashboard_kit.py::Notice`, `claude plugin validate --strict` |
| REQ-10 | `references/dashboard-kit.md`: rules, kit use, upgrading an existing dashboard; SKILL.md step 5 links it; `references/dashboard.md` point 8 points at the kit | `test/validate.py` (links), scenario evals |
| REQ-11 | Evals first: a scenario for the narrow host pane and one for upgrading a dashboard; a trigger query | `test/validate.py`, the eval files |
| REQ-12 | Contract pin `a83bec6`, `52da526` supported; version 0.9.0 in every manifest; CHANGELOG; backlog FAA-17; SKILL-CARD; README; AGENTS.md LC-09 | `npm test`, `claude plugin validate --strict` ×2 |
| REQ-13 | Release: PR green and merged; tag `v0.9.0` is the operator's approval step; the handoff names it and the launcher re-pin | PR checks read, handoff |

## Module map

Walking skeleton first: the CSS + demo page + layout probe prove the floor before the rest is built.

| Module | REQs |
|---|---|
| M1 kit files | REQ-1, REQ-2, REQ-3, REQ-4 |
| M2 layout probe | REQ-5 |
| M3 declaration (probe rule + kits) | REQ-6, REQ-7 |
| M4 CLI and notice hook | REQ-8, REQ-9 |
| M5 doctrine and evals | REQ-10, REQ-11 |
| M6 pin, version, release | REQ-12, REQ-13 |

## Not done here

- The host side (ED-7 host floor, ED-8 carrier writer, the theme picker in the host): fabric-dashboards
  FD-39/FD-40, another session's worktree.
- The brand board adopting the kit: sshlg-brand-agent, the next task after this release.
