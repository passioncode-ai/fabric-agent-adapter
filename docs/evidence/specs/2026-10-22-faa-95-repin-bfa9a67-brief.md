# Brief: FAA-95, repin to contract `bfa9a67` as 0.43.0

**Request:** the operator's «дальше до конца» (2026-10-22): take the next row, FAA-95, the repin the contract asked for
on board threads `d0d274d0` and `cd8496a2`. Route: task-pipeline 1.99.1; a repin is a compatibility change (the README's
pin rule), so the full flow, recorded in this file as the last runs did.

## Source ledger

| Source | What it says |
|---|---|
| contract `c55f2d5..bfa9a67` (`git log`, `git diff`) | the review (#137, #138, `40eb352`), the plan (#139) and DEC-0097 (#140, `bfa9a67`, a security fix to schema patterns); `src/delegation.ts` names a partner in the chain only for a partner actor; `src/protocol-revisions.ts` adds `fabric-connections` |
| board `d0d274d0`, `cd8496a2`, `dac84a34` | the three points (register, pin-schema members, `$ref` closure); `bfa9a67` is the contract's `main` |
| `docs/handoffs/2026-10-20-faa-61-repin-c55f2d5.md` | the repin's procedure: pin everywhere, the old commit joins the supported list, vectors regenerated from the contract's staged sources |

Contradictions: the row named `40eb352`; the contract moved to `bfa9a67` the same day with a security fix. Decision D1.

## Requirements

| REQ | What | Verified by |
|---|---|---|
| REQ-1 | The pin is `bfa9a67` in every live file; `c55f2d5` is supported | `python3 test/validate.py`; `test_contract_revisions` with both checkouts installed |
| REQ-2 | Every vendored vector regenerated from the contract's functions at the pin | the generators exit 0; the diff holds only the contract's new cases |
| REQ-3 | Both delegation verifiers answer the new chain vector | `test_fabric_delegation`, `fabric-delegation.test.mjs`, red before the change |
| REQ-4 | Both protocol registers equal the contract's | `test_fabric_service_feed_protocols`, the Node twin |
| REQ-5 | The kit's schema copies carry the pin's patterns, with a guard | the new contract-gated test, red before the copy was updated |

## Decisions

| Id | Decision | Source |
|---|---|---|
| D1 | Pin `bfa9a67`, not `40eb352`: it is `40eb352` plus the plan and DEC-0097 | contract `main`, board `dac84a34` |
| D2 | FAA-62 (emit `extensions/connections/0.1`) is the next release, not this one | the row's own order; a repin release stays a repin |
| D3 | The generators run on a staged copy of the contract's sources in which one parameter property (`http-signature.ts:66`) is written out: Node 26 strips types but no longer transforms them; the staged copy is scratch, the contract is untouched | Node 26 removed `--experimental-transform-types` |
| D4 | No code walks the manifest's `connection.oneOf`, so the `allOf` change needs no edit | `grep -rn oneOf plugins` |
