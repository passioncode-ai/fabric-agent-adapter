# Impact map: Fabric Agent Contract `v0.1.0+2026-11-14` (`91c031c4`) to `v0.1.0+2026-11-14.2` (`ced7b292`), FAA-333

Written 2026-11-14 with the repin. `kit/` is `plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/`.

## 1. Source ledger

| Fact | Evidence |
|---|---|
| New pin `ced7b29265c424688602dda998c0ea4db2ba46a9` = tag `v0.1.0+2026-11-14.2` | `git -C fabric-agent-contract rev-parse 'v0.1.0+2026-11-14.2^{}'` |
| 78 files, +15478 / -270; `src/` changes in `actions.ts`, `delegation.ts`, `delegation-rules.ts`, `extensions.ts`, `mandate.ts`, `org-membership.ts`, `protocol-revisions.ts`, `semantic-*.ts`, `signing-challenges.ts`, new `levels.ts` | `git diff --stat 91c031c4 ced7b292` |
| New decisions DEC-0162 (CT-250, authority levels) and DEC-0166 (CT-285, a place's autonomy profile) | the contract's release announcement on the board, 2026-11-14; `docs/DECISIONS.md` |
| `contractVersion` stays `0.1.0` | each decision's Compatibility paragraph |

## 2. Per decision

| Decision | What it decides | Kit reader | Verdict |
|---|---|---|---|
| DEC-0162 LV-1: `org-membership/2` (role `architect`, `projects`) | `src/org-membership.ts` | `kit/fabric_levels.py`, `kit/fabric-levels.mjs` (`verify_org_membership`, `org_key_set_well_formed`) | adopted; `levels.json` `verify` (6) |
| DEC-0162 LV-2 to LV-7, LV-10, LV-11: the level decision and mandate, the bounds | `src/levels.ts`, `src/actions.ts`, `src/mandate.ts` | `fabric_levels` (`level_standing`, `level_short_of`, `level_rules`), `fabric_actions` (`action_decision`, `_by_level`), `fabric_mandate` (`mandate_covers`) and their Node twins | adopted; `levels.json` `actions` (64) and `mandates` (23) |
| DEC-0162 LV-5: the token's `mem` | `src/delegation.ts`, `schemas/delegation-token.schema.json` | `kit/fabric_delegation.py`, `kit/fabric-delegation.mjs` (claim shape) | adopted; two delegation vectors |
| DEC-0162 LV-5, LV-7: `extensions/authority/0.1` | `schemas/service-authority-extension.schema.json`, `authorityView`, `authorityExtensionRules` | `fabric_actions` (`authority_view`, `authority_extension_rules`) | adopted; `actions-vectors.json` `authorities` (3) and three catalogue fixtures |
| DEC-0162: `levels/1`, `org-membership/2` | `src/protocol-revisions.ts` | `kit/fabric_protocols.py`, `kit/fabric-protocols.mjs` | adopted |
| DEC-0162 item 8: a level holder's word carries a task | prose | working-with-fabric `references/authority-levels.md`, scenario `a-level-holders-word-in-an-organization` | adopted |
| DEC-0166 AU-1 to AU-7: the standing mandate, `prof`, FAC-SEM-173, `standing/1` | `src/mandate.ts`, `src/actions.ts`, `schemas/mandate.schema.json` | `fabric_mandate` (`profile_digest`, standing shape, `mandate_covers`, `mandate_rules`), `fabric_actions`, `fabric_delegation` (`prof`), `fabric_protocols` | adopted; `profile.json` `actions` (49) and `documents` (11) |
| The gate's wiring of levels (`McpToolServer`, the board responder) | none in the contract: a service's own reading | `kit/fabric_interop.py`, `kit/fabric-interop.mjs` | open, FAA-334 |

## 3. Vendored vectors, regenerated at `ced7b292`

On a clean tree (`git archive ced7b292`, the contract checkout's `node_modules` linked), under its `tsx`:
`vendor_vectors.mjs`, `make_load_vectors.mjs`, `make_source_vectors.mjs`, `make_ceremony_vectors.mjs`,
`make_job_limit_vectors.mjs`, `make_share_vectors.mjs`, `make_actions_vectors.mjs`, `make_mandate_vectors.mjs`,
`make_connections_vectors.mjs`, `make_page_link_vectors.mjs`, the new `make_levels_vectors.mjs`, and
`make_channel_agent_vectors.mjs` in a worktree of the pin; `test/fixtures/delegation/make_vectors.mjs` with four new
token cases. Changed: `actions-vectors.json` (two decision fixtures, the levels well-known, the authority fixtures),
`mandate-vectors.json` (two level mandates), `feed-protocols-vectors.json` (`levels`, `org-membership` 2, `standing`),
the delegation vectors (four cases), and `load-vectors.json`, `source-vectors.json` and `channel-agent.source.json` in
their commit only. New: `levels-vectors.json`, `standing-vectors.json`.
