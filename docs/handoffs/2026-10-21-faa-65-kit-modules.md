# FAA-65: the kits as production modules, release 0.40.0 (2026-10-21)

## Objective

The operator asked to refactor the ready kits to production grade: split the modules, share one core, add date
helpers, connectors and a ready support agent, check the whole module, without breaking services that copy the kit.
Brief and design: [brief](../evidence/specs/2026-10-21-faa-65-kit-modules-brief.md),
[design](../evidence/specs/2026-10-21-faa-65-kit-modules-design.md).

## Done

| Wave | Commit | What |
|---|---|---|
| 1 | `614b4d7` | shared core (`fabric_jsvalue`, `fabric_time`, `fabric_crypto`, both languages), `kit.json`, `fabric_kit.py`, layering and size tests, the 0.39.1 API snapshot |
| 2 | `e21ded3` | `fabric_service` split into 12 modules behind the facade, both languages; the `_URI` defined-twice bug fixed |
| 3 | `bef93a3` | `fabric_board` split (shapes, session, fixture), probe rules to `check_service_rules.py`, probe self-check in a clean subprocess, `fabric_session` split into five modules |
| 4 | `6f40599`, `9fa9a2c` | `fabric_http` and `fabric_openrouter`, both languages, shared cases |
| 5 | `b12cda5` | `recipes/support-agent/` |
| 6 | `fe0f202` | `kit-modules.md`, `connectors.md`, SKILL.md step 3, README, AGENTS.md, CHANGELOG, backlog FAA-66 and FAA-67 |

## Checks actually run

- Full gate per wave: `python3 test/validate.py`, `python3 -m unittest discover -s test`, `node --test 'test/*.test.mjs'`,
  `claude plugin validate ./plugins/fabric-agent-adapter --strict` (wave 3: 739 Python OK, 249 Node pass; one Node
  failure seen once under a load average of 120 did not repeat in three runs).
- Planted defects watched fail: API snapshot, core defined once, stale manifest, upward import, whole-float count,
  entry-point paths (wave 3); seven connector defects (wave 4); five recipe defects (wave 5); a missing module-map row
  (wave 6).
- Installed closures run alone: `fabric_kit.py install --module fabric_openrouter` (9 files per language), imported
  under `python3 -E -s` and `node`.

## Decisions

- The brief's deferrals stay deferred: a data or analytics agent recipe (FAA-66), a Telegram connector (FAA-67,
  routed through `telegram-dev` first).
- `fabric_openrouter` counts a receipt without a cost at this attempt's worst case unless `unmeasured_call_usd` says
  otherwise: a ceiling that ignored unmeasured calls could be passed silently.
- Recipes may import kit modules listed in `kit.json` (`test/validate.py`), nothing else.

## Open

Filled in at release.

## Next task

Filled in at release.
