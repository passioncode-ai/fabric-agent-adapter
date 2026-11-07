---
report:
  id: fabric-agent-adapter/2026-11-07-north-star-plan
  title: "Plan 2026-11-07: what is left for the Fabric Agent Adapter, ordered by the North Star"
  kind: plan
  project: fabric-agent-adapter
  domains: [templates, agent-creation, isolation, measure, learning, release]
  as_of: 2026-11-07
  status: active
  valid_until: 2026-11-28
  summary: >-
    Every open row of this repository's backlog, the board work of 2026-11-06 and 2026-11-07 and the North Star of
    the organization, read side by side: which North Star gaps the adapter owns or shares, what is left for each, and
    the order to build it in, around the coordinator's pause and the 2026-11-21 organization slice.
---

# What is left for the Fabric Agent Adapter, ordered by the North Star

The operator's request (2026-11-07): «давай составим план что осталось сделать на базе логов, но смержи с виженом из
north star документа в fabric workspace». This is the adapter's cut; the estate's cut is fabric-workspace
`docs/plans/2026-11-07-remaining-to-north-star/README.md`, and this page follows its waves and its decisions. A row's
state changes only in [docs/backlog.md](../../backlog.md); the next cut replaces this one.

## Sources

- The North Star: fabric-workspace `knowledge/north-star.md` at `origin/main` (2026-11-07), §5 «Organization agent
  templates» and «Creation and lifecycle», §11, and the gaps table §14; the estate plan named above; the template page
  `knowledge/system/templates.md` (S2, W0-Q8).
- This repository at `main` `e16dc608` (tag `v0.75.0`, released and published 2026-11-07), its
  [backlog](../../backlog.md) and [handoffs](../../handoffs/).
- The board of 2026-11-06 and 2026-11-07: the estate review `eefa7959`, ports and owners `1fe66e6e`, the dashboard
  page service `38c35e11`, a host agent's macOS 27.2 report (cross-session, recorded in FAA-266 and FAA-267).

## Where we are

- **Released today:** 0.74.0 (the listener's owner before any loopback credential, DEC-0154 HA-2) and 0.75.0 (the
  communication agent template, FAA-262). The template is the first organization agent template, one file until the
  template schema (FAA-265); S2 lists it.
- **Ready, not released:** the macOS 27.2 fix (FAA-266, FAA-267) on branch `fix-plist-env-path` (`59888fa7`),
  measured on the host agent's Mac: an install under a Homebrew Python passes, a root listener is still refused.
- **The register:** 271 rows, 112 open after this change (6 P1, 21 P2, 61 P3, 24 unprioritised; counted from the
  status cells, done, released, closed and deferred left out). About 60 of the open rows are follow-ups from blind
  readings that block nothing (FAA-143 to FAA-264); they are the debt to sweep, not new work.
- **North Star gaps the adapter owns:** G21, G23 (with each agent's owner), the template schema, G27 (with
  Observatory), G1-b. Before this change none of them had an adapter row except G2 (FAA-249); FAA-269 to FAA-271
  (below) and FAA-265 fill them.

## What the North Star asks of the adapter

| North Star | Gap | Adapter rows | State |
| --- | --- | --- | --- |
| §5 «A new agent starts from the adapter's template with the contract built in» | G21: no one command creates an agent project with its placement record and source manifest | FAA-270 (new), with FAA-26 (the `new` CLI it grows from), FAA-188 part 2 (portable agents), FAA-261 (DEC-0149: `fabric.source.json`), FAA-230 (an agent's own machine), FAA-225 (HA-1 port claim) | unblocked: DEC-0149 and DEC-0154 accepted 2026-11-07; FAA-261 waits on the pause |
| §5 Organization agent templates, delivered on day one | G23: host admin, PM, data room, assessment exist only as instances | FAA-265 (the schema and validator for a template folder, W0-Q8), then one extraction per template with its owner | the first template (communication agent) is released as one file; the host admin's extraction (E6) asks for the folder and validator |
| §0 The measure | G1-b: the adapter kit writes the activity event on every accepted unit | FAA-269 (new) | waits on OBS-378 (G1-a, the event schema) |
| §3 Levels | G2: levels in every product | FAA-249 | waits on the pause and the contract's CT-250 |
| §11 Security | G27: no admission check that a new agent follows the templates and the contract | FAA-271 (new), with Observatory | the adapter's part is the check itself (`check_service.py`, the source check, the private-terms check); the role is Observatory's |
| §11 Isolation (DEC-0154) | HA-1 to HA-3 | FAA-225, FAA-227, FAA-228, FAA-230, FAA-258 (CT-254), FAA-266, FAA-267 | HA-2 shipped in 0.74.0; the macOS 27.2 fix ready; CT-254 still an open PR |
| §6 The board and agents outside Fabric | working-with-fabric | FAA-133, FAA-201, FAA-206, FAA-248, FAA-252 and the smaller rows | live; P1 rows FAA-201 and FAA-206 have shipped parts |
| §7 Learning: every loop closes | lessons become rules | FAA-206 (retro after work, log digests in every adapted agent) | part 1 released (0.64.0) |
| §4 Platform layer: Dashboards | a dashboard of one's own is a page service (operator, 2026-11-07, decision 8) | FAA-268 (`recipes/dashboard-only/`, shape agreed with Dashboards) | wave 2 per Dashboards; small |
| §4 Platform layer: the Telegram gateway (G20) | agents send through the organization's gateway | FAA-67 (a Telegram connector for services) | to re-scope: a client of the gateway, never a bot of the agent's own |
| §6 A2A outward | RM-17 | FAA-10 | decided, not built |
| §10 Deployment and continuity | local and cloud form, every supervisor | FAA-204, FAA-253, FAA-183 (Windows) | P2, open |

## The order

### Wave 1: now to 2026-11-13

1. Release the macOS 27.2 fix (FAA-266, FAA-267) as 0.76.0; the host agent re-vendors and reinstalls from a clean
   release. No dependency.
2. File the gap rows: G21 (FAA-270), G1-b (FAA-269), G27 (FAA-271) (done in this change; the estate plan's wave 1,
   item 9).
3. FAA-265: the template folder's JSON Schema and validator, so the host admin template (E6) and the communication
   agent template can move into folders. No dependency (W0-Q8 decided).
4. FAA-268: the dashboard-only recipe (small, its shape agreed on the board).
5. FAA-264's items that change what a builder ships (35: the operator-decision route and `check_reply`; 41: a channel
   people write to is uptime A; 42: the sales agent never writes on the lead's channel), as a guidance release.
6. FAA-258 the day the contract tags CT-254.

### Wave 2: the organization slice, 2026-11-21

1. FAA-270 (G21): `fabric-agent-adapter new` writes the project with its placement record and `fabric.source.json`,
   with FAA-261 (DEC-0149) once the pause lifts.
2. FAA-225 and FAA-230 (HA-1 port claim, an agent's own machine) once the contract's CT-228 publishes the claim file;
   FAA-227 (HA-3).
3. FAA-249 (levels) designed against CT-250; code in wave 3, after the DEC.

### Wave 3: after the slice

1. Templates out of the pilot's instances, one folder each, with their owners: host admin (E6), then PM, data room,
   assessment (G23); the Linux form of the host template with the host agent (G28).
2. FAA-269 (G1-b): the kit writes the activity event on every accepted unit, after OBS-378.
3. FAA-271 (G27): the admission check, with Observatory's security role.
4. FAA-249 as code; FAA-10 (A2A outward).

### Throughout: the debt

One sweep release a week for the readings' follow-ups (FAA-143 to FAA-264), oldest first, so the register shrinks
while the waves land; FAA-263 (SKILL.md headroom) before the next prose change to `building-fabric-services` or
`working-with-fabric`.

## Decisions only the operator can make (from the estate plan) that hold adapter rows

| Decision | Adapter rows it holds |
| --- | --- |
| 1: accept the shared source of truth and lift the pause | FAA-249, FAA-261 |
| 9: the acts agents may finish without a person, as the machine's permission rule (G19) | every release step this repository does on its own |
| A human gate on npmjs.com: register `release.yml` as the trusted publisher | FAA-87 |

## Drift between the vision and the records

| The vision or the estate plan says | The records say | Fix |
| --- | --- | --- |
| G21, G23's schema, G27: «to be filed», «none filed» | FAA-270, FAA-265, FAA-271 filed | the coordinator updates §14 |
| The communication agent template «exists as one file in adapter 0.75.0 work, not on main» | on `main` at `e16dc608`, released as 0.75.0 | the estate plan's next cut |
| G20: agents send through the organization's gateway | FAA-67 plans a Telegram connector in the kit | re-scope FAA-67 to a gateway client |
