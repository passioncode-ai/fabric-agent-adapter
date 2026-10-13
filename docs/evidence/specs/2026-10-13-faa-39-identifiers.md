# FAA-39 — identifier equality by normal form (DEC-0076); repin to contract `a046f57`

Run: 2026-10-13. Branch `agent/faa-39-identifiers`. Backlog row FAA-39. Asked for by the contract (CT-18, DEC-0076
items, read in full from the row).

## Source ledger

| Source | What it gave |
|---|---|
| contract DEC-0076, `src/identifiers.ts`, `fixtures/vectors/identifiers.json` at `a046f57` | `normalIdentifier` (RFC 3986 §6.2.2; RFC 8141 §3.1 for `urn:`), `sameIdentifier`; 33 normal, 8 same, 8 different, 6 lax-port cases |
| contract `src/route-rules.ts`, `src/registry-rules.ts`, `src/estate-record-rules.ts` diffs `fe55fc6`→`a046f57` | FAC-SEM-030 (admission capability, ref key's id), 032 (project, capability), 034 (project, capability), 014 (`providerId`), 076 (grant ids and `grant` revocations) |
| contract CT-18 row | the four adapter items: port and run the vectors; apply in 030/032/034 and 014; respelled-id route vectors; the kits write identifiers in their normal form |
| measured: every vendored and generated vector regenerated at `a046f57` | unchanged — the fixtures are written in normal form, so the kits' byte comparisons stay green until respelled cases are added |
| DEC-0077 (`a046f57`, FAC-SEM-107, `com.directory` pages) | the kits' board client is FAA-12b's (another session); recorded as a board row, not built here |

## Decisions

1. **One module per language**, `fabric_identifiers.py` (byte-identical in both skills' `scripts/`, as `fabric_secrets.py`
   is) and `fabric-identifiers.mjs`, a port of `src/identifiers.ts`.
2. **Sites:** FAC-SEM-030/032/034 in `fabric_profiles` / `fabric-profiles`; FAC-SEM-014 in `fabric_provider.py`;
   FAC-SEM-076 in both estate ports (DEC-0076 amends it; the kits port it). FAC-SEM-025 `byProject`, 002, 006, 094,
   096 are no kit surface.
3. **Respelled cases are generated, not hand-written:** the route and estate generators respell an id in their
   fixtures and take the contract's own answer.
4. **Writers emit the normal form** where a kit writes an identifier it is given (the provider id it scaffolds).
5. **Repin to `a046f57`** (contract `main`, includes `4762876`); `fe55fc6` joins the supported revisions. Version 0.25.0.

## REQ table

| REQ | Requirement | Verified by |
|---|---|---|
| REQ-01 | `normal_identifier` / `normalIdentifier`, `same_identifier` / `sameIdentifier` | `identifiers.json`, both kits |
| REQ-02 | FAC-SEM-030/032/034 compare by normal form | respelled route vectors, both kits |
| REQ-03 | FAC-SEM-076 keys grants and `grant` revocations by normal form | respelled estate rule cases, both kits |
| REQ-04 | FAC-SEM-014 compares `providerId` by normal form | provider test |
| REQ-05 | Writers emit the normal form | scaffolder test |
| REQ-06 | Repin `a046f57`; profiles compile under it | `validate.py`; `test_contract_revisions` |
| REQ-07 | Docs, eval, 0.25.0, CHANGELOG, board, handoff, launcher | files; `validate.py` |
