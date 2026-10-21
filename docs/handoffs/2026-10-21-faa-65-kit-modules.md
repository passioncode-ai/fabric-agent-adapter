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
| review 1 | `f8d7cd4` | blind unit, seam, product readings: ceiling bypass through params, lost receipts for maybe-billed attempts, a facade not loadable by path, `status` on old copies, doc errors |
| review 2 | `72fb085` | a cut connection kept no receipt, `max_completion_tokens`/`n`, unmeasured calls counted too low, strict prices, Python deadline before headers |
| review 3 | `2164214` | an answer with no usage counted too low, image/file parts refused, Python overflow and deep JSON, a watchdog for trickled headers, the CI-only `git show v0.39.1` test |

## Checks actually run

- Full gate per wave: `python3 test/validate.py`, `python3 -m unittest discover -s test`, `node --test 'test/*.test.mjs'`,
  `claude plugin validate ./plugins/fabric-agent-adapter --strict` (wave 3: 739 Python OK, 249 Node pass; one Node
  failure seen once under a load average of 120 did not repeat in three runs).
- Planted defects watched fail: API snapshot, core defined once, stale manifest, upward import, whole-float count,
  entry-point paths (wave 3); seven connector defects (wave 4); five recipe defects (wave 5); a missing module-map row
  (wave 6).
- After the fixes: full local gate on `72fb085` (782 Python OK, 262 Node, both `plugin validate`), the full Python
  suite in a depth-1 clone of `2164214` (785 OK, as CI checks out), and every module installed alone and loaded from
  outside the repo in both languages (seam round 3).
- Installed closures run alone: `fabric_kit.py install --module fabric_openrouter` (9 files per language), imported
  under `python3 -E -s` and `node`.

## Decisions

- The brief's deferrals stay deferred: a data or analytics agent recipe (FAA-66), a Telegram connector (FAA-67,
  routed through `telegram-dev` first).
- `fabric_openrouter` counts an attempt that may have been billed without usage (a timeout, a cut connection, an
  unreadable or usage-free 200) at that attempt's own worst case while the client runs, and at `unmeasured_call_usd`
  (default: the current attempt's worst case) after a restart: over-counting is the safe side of a spend ceiling.
- Only text content is sent: image, audio and file parts are billed in ways a byte count cannot bound.
- Recipes may import kit modules listed in `kit.json` (`test/validate.py`), nothing else.

## Released

PR #149 merged as `e778a22` after CI on the exact head `662c39b` (run 39676626184: python, windows, claude-plugin
success; the run before it, on `2164214`, failed the two Linux trickle tests, fixed in `662c39b` and verified in a
Linux container first). Tag `v0.40.0`, release run 39676912200 success, npm `@passioncode-ai/fabric-agent-adapter@0.40.0`.
Launcher passioncode 0.2.19 (PR #129, merge `7c87742`, release run 39678127978); `npx --yes
@passioncode-ai/passioncode@0.2.19 update` installed the adapter byte-identical to `v0.40.0` (145 of 145 files). Wiki
card `projects/fabric-agent-adapter/` (vault commit `a05fbc46`). Roll call answered on board thread `1316a045`.

## Open

- Notes from review round 3 left as notes (not blocking): the `provider` routing param is not refused (documented);
  two `Client` objects on one ledger each reserve only their own calls (documented: one client per key); `redact_url`
  keeps path parameters (documented as scheme, host, port and path).
- Services that vendor the kit (asset-foundry, cmo-creative-agent, observatory, brand-agent) keep their copies until
  they update with `fabric_kit.py install`; their owners decide when.

## Next task

FAA-66: a data or analytics agent recipe on the kit (numbers computed by code, never by the model; receipts through
`fabric_openrouter`), then FAA-67 after `telegram-dev` decides whether a Telegram connector belongs in this kit.
