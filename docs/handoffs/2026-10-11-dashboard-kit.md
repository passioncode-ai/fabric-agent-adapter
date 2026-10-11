# Dashboard kit (`fabric-dashboard/0.1`, DEC-0036) and release 0.9.0 (FAA-17)

Branch `agent/faa-17-dashboard-kit`, cut from `origin/main` `9e830a2` (0.8.3). Objective (operator,
2026-10-11): a Fabric service's dashboard narrowed inside Fabric Dashboards beside the agent console lost
its navigation; fix it at the factory level — a kit every agent inherits, a notice for dashboards already
built, theme presets — with the brand board as the first adopter. Spec, decisions and REQ table:
[docs/evidence/specs/2026-10-11-dashboard-kit.md](../evidence/specs/2026-10-11-dashboard-kit.md).

## Completed

- Contract PR #27 (DEC-0036) merged into fabric-agent-contract `main` as `a83bec6` by this run.
- `building-fabric-services/assets/dashboard-kit/`: `fabric-dashboard.css`, `fabric-dashboard.js`,
  `themes.json` (seven reference themes × light/dark, AA), `kit.json` (1.0.0, digests, history), `demo.html`.
- `scripts/dashboard_kit.py` (`status`, `install`, `build`, `notice`), `scripts/check_dashboard_layout.mjs`
  (WebKit by default), `check_service.py` rule `dashboard.declared`, `dashboard_extension()` /
  `dashboardExtension()` and `extensions` in both kits' well-known builders; the sample service's page is
  built on the kit and declares it.
- Plugin hook `plugins/fabric-agent-adapter/hooks/hooks.json` (SessionStart → `dashboard_kit.py notice`);
  `AGENTS.md` LC-09 declares it.
- `references/dashboard-kit.md`, SKILL.md steps 5 and 6, `references/dashboard.md` point 8,
  `references/protocol.md`, README, SKILL-CARD; evals (three scenarios, two triggers) written first.
- Contract pin → `a83bec6b47776af688402c18efec507143061f68`; `52da526` joins the supported revisions;
  version 0.9.0; CHANGELOG 0.9.0; backlog FAA-17. `test/validate.py` no longer reads a hash inside a link
  to a dated handoff as a pin (`docs/handoffs` was already excluded), with a test.

## Compatibility review (the three profiles)

`52da526..a83bec6` is one decision, DEC-0036: `docs/specification/embedded-dashboard.md`,
`schemas/service-dashboard-extension.schema.json`, fixtures and the `dashboard` extension key. The
provider manifest and the MCP, A2A and local-runner profiles do not change; every descriptor and
well-known document the kits wrote before stays valid (the declaration is optional, ED-9 SHOULD).

## Decisions

- Graphite = the SHELEG Design workbench layer verbatim plus `--edge` (a 3:1 meaningful border); the other
  six themes are this run's palettes, judged by the AA test, not by taste.
- `dashboard.declared` is NOT_RUN for an undeclared (legacy) dashboard, FAIL only for an invalid value.
- The notice is one line, read-only, exit 0 always, and tells the agent to act only with the operator's
  go-ahead. It fires for an older or unmarked kit copy, or for a service whose descriptor names this
  repository (`source.repository`) and whose code declares a dashboard surface, with no kit copy.
- Sticky chrome over budget: the header scrolls away (negative sticky `top`) and the navigation stays.

## Checks run

See the PR body (exact commands and their last lines). Measured by hand on this run: the layout probe on
`demo.html` 17 rules 0 FAIL in WebKit (Playwright 1.61.1) at 320/360/480/768/1280; the planted-defect page
fails ED-1, ED-3, ED-4, ED-5; the live sample service signs in and passes at 360 and 768;
screenshots at 360 (graphite light, ocean dark) and 1280 (fabric light, ember dark) looked at.
Notice latency on this machine (load average ≈ 50): median 294–443 ms; in-process steps 15–46 ms each.

## Not done here / open

1. Chromium arm of the layout probe: NOT_RUN (no Chromium for the local Playwright).
2. Release: after the PR merges, the `v0.9.0` tag publishes to npm (`release.yml`); pushing it is the
   operator's approval step. Then the launcher `passioncode` re-pins `family.json` and releases, and
   `npx @passioncode-ai/passioncode@latest update` updates this machine.
3. The host side (ED-7 host floor, ED-8 carrier writer, the theme picker): fabric-dashboards FD-39/FD-40,
   another session's worktree `../fabric-dashboards-host-floor` (local commit `bb13b1c`, not pushed).
4. The brand board adopts the kit (sshlg-brand-agent, its handoff step 4).

## Next task

Merge this PR after its checks, then (operator) push tag `v0.9.0`; then the launcher re-pin.
