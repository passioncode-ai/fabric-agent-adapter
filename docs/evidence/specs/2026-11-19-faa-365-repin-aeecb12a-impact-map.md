# FAA-365: the repin to Fabric Agent Contract v0.1.0+2026-11-19 (aeecb12a): impact map

The contract moved from `v0.1.0+2026-11-16.6` (`2bbfd780`) to `v0.1.0+2026-11-19` (`aeecb12a`): DEC-0179 (CT-336),
DEC-0180 (CT-340), DEC-0181 (CT-341), DEC-0182 (CT-342), DEC-0183 (CT-343). `contractVersion` stays `0.1.0`; the
previous pin stays in `SUPPORTED_CONTRACT_COMMITS` for bundles issued under it. Source: `git diff 2bbfd780 aeecb12a`
in the contract, 15 files under `src/`, `schemas/` and `fixtures/vectors/` (`git diff --stat 2bbfd780 aeecb12a --
src fixtures/vectors schemas scripts`). The repin was taken for DEC-0183, asked by board request `3bed4856`.

| Decision | What changed in the contract | What the adapter does |
|---|---|---|
| DEC-0183 (CT-343) | spending limits: `period: week` and the known kind `weekly` (SL-1), `editable`, `minUsd`, `maxUsd` on `budgets[]` (SL-3), `limitChanges[]` (SL-4), `months[]` (SL-6), FAC-SEM-031 extended (`src/semantic-rules.ts`, `usageLimits`); `spend-limits-set.schema.json` (SL-2) | ported: `usage_limit_problems` / `usageLimitProblems` take the three fields, the week and the weekly kind, and the SL-3 bounds rule; new `usage_history_problems` / `usageHistoryProblems` check `limitChanges` and `months` as the schema and FAC-SEM-031 do; `usage_report` / `usageReport` count a machine `period: week` limit from Monday 00:00 UTC and pass `limit_changes` / `limitChanges` and `months` through. The contract's four fixtures in `test/fixtures/contract/dec-0025-0027/`; tests `Limits.test_dec_0183_*` and the two `DEC-0183:` Node tests |
| DEC-0179 (CT-336) | `agent-health/1`: `schemas/agent-health.schema.json`, `src/agent-health.ts`, `fixtures/vectors/agent-health.json` | registered as a known protocol revision (`agent-health/1`); the health door in the kit is FAA-346, open |
| DEC-0180 (CT-340) | a compact MCP surface: `surfaces.mcp.compact` in the well-known schema, `compact-mcp-search/1`, `compact-mcp-execute`, FAC-SEM-182 (`compactSurfaceRules` in `src/actions.ts`) | registered `compact-mcp-search/1`; the kit serves the compact mode opt-in since 0.98.0 (FAA-356); FAC-SEM-182 in the kit's well-known reader waits with FAA-355 |
| DEC-0181 (CT-341) | a responder's message says which operation wrote it (`via`, `comms-message.schema.json`, `comms-common.schema.json`) | nothing to port: the kit writes no board message; Fabric owns the board |
| DEC-0182 (CT-342) | the tools probe compares a capability as its search operation (`src/interop-rules.ts`, `operationFindings`; `interop-tool` gains `operation`) | waits: FAA-355 (`interop.tools-match` on a compact surface) |

Regenerated on a clean tree of the pin with the contract's tsx: `vendor_vectors.mjs` (`feed-protocols-vectors.json`
gains `agent-health/1` and `compact-mcp-search/1`; `comms-vectors.json` gains DEC-0181's cases; `usage-attribution-vectors.json`
gains the positive DEC-0183 fixture, 209 to 210 usage cases), `make_levels_vectors.mjs`, `make_load_vectors.mjs`,
`make_source_vectors.mjs` and `make_channel_agent_vectors.mjs` (the recorded commit only).

Waiting, with the reason:

- `spend.limits.set` (DEC-0183 SL-2) as a kit door, and the emergency defaults (SL-5, a SHOULD): the kit holds no
  limit store of its own; a service applies and changes its limits and reports them through `usage_report`. A kit
  door is a backlog row when a service asks for it.
- FAA-346 (`agent-health/1`) and FAA-355 (FAC-SEM-182, CM-7) were planned for this tag; both stay open with their
  targets.
