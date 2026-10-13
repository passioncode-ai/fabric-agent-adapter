# FAA-35 + FAA-37 — feed event `data` (DEC-0070) and `protocols` in the well-known document (DEC-0067)

Run: 2026-10-13. Branch `agent/faa-35-37-feed-protocols`. Board rows FAA-35, FAA-37. Pin `a046f57` (both decisions in
it). Version 0.26.0.

## Source ledger

| Source | What it gave |
|---|---|
| contract DEC-0070, `src/feed-data.ts`, `schemas/service-events-page.schema.json` (`data`, `dataScalar`, `dataValue`), fixtures `service-events-page-data*` | optional `data {schema, value}`: an absolute URI; `value` ≤ 32 members, each a scalar (string ≤ 500), a list ≤ 32 scalars or an object ≤ 32 scalar members; FAC-SEM-101: no string under a credential's name or of a credential's shape, at either level |
| contract DEC-0067, `src/protocol-revisions.ts`, `fixtures/vectors/protocol-revisions.json`, `common.schema.json#/$defs/protocols`, fixtures `service-well-known-protocols*` | the register; N and N−1; `protocols` 1–64 unique `<name>/<revision>`; FAC-SEM-099; `negotiateRevision` answers ok, `schema-unsupported` or the receiver's own `no-accepted-revisions` |
| contract CT-18 | "the kits may list `protocols` in the well-known document; they send it only to readers pinned at or after DEC-0067"; "the kits let a service add `data` to a feed event" |
| this repository: `make_event`, `JsonlEventLog.append`, `build_well_known` (both kits), `check_service.py` | where each rule lands |

## Decisions

1. `make_event` / `makeEvent` take `data`; an invalid or credential-carrying `data` is refused when the event is made, so
   no feed carries one. `check_service.py` reads FAC-SEM-101 on the feed it fetches.
2. `build_well_known` / `buildWellKnown` take `protocols` (absent by default): a service lists them only once its hosts
   are pinned at or after DEC-0067, since the well-known object is closed for an older reader. FAC-SEM-099 is checked
   when it is given and by the probe.
3. Ports: `PROTOCOL_REVISIONS` (held equal to the contract's register), `parse_revision`, `accepted_revisions`,
   `negotiate_revision`, `protocols_findings`, `feed_data_findings`.

## REQ table

| REQ | Requirement | Verified by |
|---|---|---|
| REQ-01 | Events take `data` within the schema's bounds | contract `service-events-page-data*` fixtures through both kits |
| REQ-02 | FAC-SEM-101 refuses a credential in `data` | semantic cases, both kits; probe test |
| REQ-03 | `protocols` in the well-known document, FAC-SEM-099 | `service-well-known-protocols*` fixtures; rule cases |
| REQ-04 | `negotiate_revision` / `negotiateRevision`; the register equals the contract's | `protocol-revisions.json`; register vector |
| REQ-05 | Docs, eval, 0.26.0, CHANGELOG, board, handoff, launcher | files; `validate.py` |
