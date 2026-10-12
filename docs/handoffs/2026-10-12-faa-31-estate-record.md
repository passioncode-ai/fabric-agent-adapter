# Handoff — FAA-31: the estate record in both kits, pin to b291bf0 (0.21.0)

**Objective.** Port contract DEC-0055 into both kits, and repin to the merge of contract PR #54 (`b291bf0`).
- `verifyEstateRecord`, the rules FAC-SEM-072…076 and the WebAuthn assertion check (contract CT-18).
- In the delegation verifier, trust a `kid` only while a current estate revision certifies it (CT-20).

**Done.**

- `scripts/fabric_estate.py` and `scripts/fabric-estate.mjs`.
- The `estate` option in both delegation verifiers.
- The settings canonical form refuses lone surrogates (CT-25).
- The pin moved, with `0cacd08` kept as a supported revision.
- Docs: `references/estate-record.md` (new), `delegation.md`, `SKILL.md`. The eval scenario
  `estate-record-and-certified-keys` was written first.

**Checks run.**

- `test/test_fabric_estate.py` and `test/fabric-estate.test.mjs` run against `test/fixtures/contract/estate-vectors.json`.
  - `make_estate_vectors.mjs` generated it with Node ≥ 24 from the contract's sources at b291bf0, staged with their
    `.js` imports rewritten to `.ts`. It also uses `fixtures/vectors/estate-record.json` (which the generator checks
    is still current), the 38 `fixtures/semantic/estate-*.json`, and the positive records.
  - Both kits match exactly.
- Strict ES256: on a malleated, padded or trailing signature, the pure-Python verifier answers as OpenSSL does in Node.
- Mutation testing: 42 planted defects, all caught. Five survived at first: a coordinate at p, the `s` range, DER
  minimality, a trailing byte, and the hub key's `x`. A test was added for each, and they are now caught.
- `test_contract_revisions` compiled-schema checks pass for both pins (`FABRIC_CONTRACT_OLD` = `2ce3922`, `FABRIC_CONTRACT_NEW` = `b291bf0`,
  clean checkouts with `pnpm install --frozen-lockfile`): all three profiles valid under the new pin.
- The full suites, `test/validate.py` and both strict plugin validations pass.

- An independent review found nothing critical. It reported 5 Python divergences or exceptions, all fixed with
  tests or vectors:
  - a full-width digit in dates, which would have let a revision through;
  - `Number()` read differently from JavaScript;
  - RecursionError on deeply nested client data;
  - OverflowError on a huge revision;
  - a lone surrogate in a pinned RP ID.

  It also raised two CT-20 design points: `estate` must be a verified revision, and the highest one, otherwise a
  rollback is possible. Both are now in the docs as requirements.

**Decisions.**

- The contract's other decisions in this range (devices DEC-0052/0053, activity, `fabric-package/1`
  DEC-0050/0051, telemetry) have no kit surface yet. Packages are FAA-26/27, which still wait for Fabric.
- An uncertified `kid` is refused as the token's fault (`unauthenticated` / `approval-invalid`,
  `kid-not-certified`). An unreadable record is the trust source's fault (`issuer-unavailable`,
  `estate-unreadable`).

**Open.**
- FAA-32 (the supervisor marker as an argument) waits for contract P4-01.
- FAA-26…29 and the rest are as in the backlog.

**Next task.**
1. Re-pin the passioncode launcher to v0.21.0 and update the local install.
2. Then take FAA-32 when the contract session sends P4-01's merge commit.
