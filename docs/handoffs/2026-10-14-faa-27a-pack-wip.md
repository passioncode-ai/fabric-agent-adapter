# Handoff — FAA-27a `pack` / `sign` / `verify` (work in progress, not released)

Branch `agent/faa-27a-pack`. The row is FAA-27a (`RM-28 pilot`) in `docs/backlog.md`, and it takes in FAA-36. It answers the
adapter's row in the RM-28 pilot's §4 (fabric-workspace#212).

## Done (on this branch)

- `building-fabric-services/scripts/fabric_package.py` and `fabric-package.mjs` are twins. They carry:
  - the contract's `packageDigest`, `packageSigningInput`, `verifyPackage` (PK-1…PK-10), `checkPackageFolder` and
    `consumerPlacement`;
  - FAC-SEM-064, 065, 066 and 102, and a schema check against `fabric-package.schema.json` (bundled from the contract
    at the pin);
  - Ed25519 signing, with Python following RFC 8032 on stdlib only;
  - `pack`, `sign` and `verify`: dry run by default, `--apply` writes.
- `bin/fabric-agent-adapter.js` routes `pack`, `sign` and `verify` to the kit.
- `test/fixtures/contract/vendor_vectors.mjs` writes `package-vectors.json` and the bundled schema, every case
  re-answered by the contract's own functions. Run it with
  `<contract>/node_modules/.bin/tsx vendor_vectors.mjs --contract <archive at pin> --contract-src <staged src>`, with
  the contract's `node_modules` reachable from the staged folder. The other vendored files came out byte-identical.
- Tests:
  - `test/test_fabric_package.py`: 15 cases;
  - `test/fabric-package.test.mjs`: 15 cases, including both kits writing the same bytes;
  - `test/test_installer.py`: one case.

## Checks run

- Python: 613 tests, OK.
- Node: 195 tests, 0 failed.
- `validate.py`: OK.

## Next task (in this order)

1. Three planted defects survive. Add a case for each:
   - `checkPackageFolder` file-unlisted: verify after adding a file, in both kits;
   - JS `codePoints`: an astral character at `maxLength`;
   - files[] sort order: a name where UTF-16 order differs from code-point order.
2. Write the trigger and scenario evals in `test/evals/building-fabric-services/`, then the docs:
   - `references/package.md`;
   - a SKILL.md section;
   - README's CLI section;
   - SKILL-CARD;
   - CHANGELOG 0.31.0 with the version sync.
3. Set FAA-27a and FAA-36 to in review under a lease. Then: PR, CI, merge, tag `v0.31.0`, npm, launcher repin, and
   the receipts.
