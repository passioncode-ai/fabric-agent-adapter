# Impact map: Fabric Agent Contract `v0.1.0+2026-11-08.1` (`93e7db16`) to `v0.1.0+2026-11-14` (`91c031c4`), FAA-331

Written 2026-11-14 with the repin. `kit/` is `plugins/fabric-agent-adapter/skills/building-fabric-services/scripts/`.

## 1. Source ledger

| Fact | Evidence |
|---|---|
| New pin `91c031c464695ae9661c12f97ce1e5dc3cb5448c` = tag `v0.1.0+2026-11-14`, the newest `v0.1.0+` tag | `git -C fabric-agent-contract tag -l 'v0.1.0+*' --sort=-creatordate` (first line), `git rev-parse 'v0.1.0+2026-11-14^{commit}'` |
| 64 files, +6710 / -778; `src/` changes only in `activity-rules.ts`, `protocol-revisions.ts`, `usage-rules.ts` | `git diff --stat 93e7db16 91c031c4`, the same `-- src` |
| New decisions DEC-0156, DEC-0163, DEC-0164 (the other heading moves in `DECISIONS.md` are reordering) | `diff` of `grep '^### DEC-0'` of `docs/DECISIONS.md` at both commits |
| `contractVersion` stays `0.1.0` | each decision's Compatibility paragraph |

## 2. Per decision

| Decision | What it decides | Kit reader | Verdict |
|---|---|---|---|
| DEC-0156 (CT-220): the operator's word is carried out the first time, OW-1 to OW-6 in `docs/specification/governance-and-roles.md` | prose | working-with-fabric SKILL.md Step 5, creating-fabric-agents `references/practices.md`, scenario `the-operators-word-is-done-the-first-time` | adopted (FAA-207) |
| DEC-0163 (CT-295): a usage report's cost sums hold within each row's rounding (`allowance`, `ROW_ROUNDING_USD`) | `src/usage-rules.ts` | `kit/fabric_usage.py`, `kit/fabric-usage.mjs` (`usage_findings`, `usageFindings`) | adopted (FAA-310 (2)); held by the fixture `service-usage-rounded-rows` in `usage-attribution-vectors.json` |
| DEC-0164 (CT-259): the unit of work as an activity event, kind `unit`, `activity-unit/1` | `src/activity-rules.ts`, `schemas/telemetry-event.schema.json`, `fixtures/vectors/activity-unit.json` | `kit/fabric_protocols.py`, `kit/fabric-protocols.mjs` | register adopted; the kits port no activity collector (Project Observatory's, OE-01a) |

## 3. Vendored vectors, regenerated at `91c031c4`

On a clean tree (`git archive 91c031c4`, the contract checkout's `node_modules` linked), under its `tsx`:
`vendor_vectors.mjs`, `make_load_vectors.mjs`, `make_source_vectors.mjs`. Every file equal to the vendored one except
`feed-protocols-vectors.json` (`activity-unit`), `usage-attribution-vectors.json` (`service-usage-rounded-rows`, 209
cases), and `load-vectors.json` and `source-vectors.json` (their commit field only). The other generators read sources
unchanged between the pins (`git diff --stat 93e7db16 91c031c4` over their inputs prints only `fixtures/catalogue.json`,
five new catalogue lines for fixtures they do not read).
