# FAA-20 part two — delegation verifiers in both kits (0.11.0)

Branch `agent/faa-20-verifiers`. Spec and REQ table: [2026-10-12-faa-20-verifiers](../evidence/specs/2026-10-12-faa-20-verifiers.md).

## Completed

- `building-fabric-services/scripts/fabric_delegation.py` (standard library only, Ed25519 per RFC 8032, as strict as
  OpenSSL) and `fabric-delegation.mjs` (node:crypto) each provide:
  - the verifiers and token reading: `verify_delegation`, `verify_approval`, `read_delegation_token`;
  - canonical JSON and digests: `jcs`, `action_digest`;
  - replay stores: memory, file, and `UNSAFE_NO_JTI_STORE`;
  - `JwksCache` (DL-15);
  - the gate and the DL-19 refusal shapes.
  Names are camelCase in Node.
- `fabric_interop.McpToolServer(authorize=)` gates every tool. Job tools are gated by the job's owner.
- Shared vectors: `test/fixtures/delegation/vectors.json`. Expected answers come from the contract's verifier and from OpenSSL.
- An independent review found seven defects, among them a small-order key forgery in the Python verifier. All are fixed, each with a regression test that failed first.
- Docs: `references/delegation.md`, plus `surfaces-and-auth.md`, `protocol.md` and a pointer in SKILL.md. Evals were written first. CHANGELOG 0.11.0.

## Regenerating the vectors

1. Copy the contract's `src/delegation.ts` and `src/findings.ts` at the pin into a directory.
2. In that copy, rewrite `./findings.js` to `./findings.ts`.
3. Run `node test/fixtures/delegation/make_vectors.mjs --contract-src <dir> --claims <contract>/fixtures/positive` (Node 23.6+).

## Open

- FAA-20 part four: Fabric's button (FB-7) in the dashboard kit.
- After a repin past the DEC-0039 merge:
  - DEC-0043 canonical vectors for the `jcs` ports;
  - DEC-0044 `run.mcp.stdio.scope` (FAA-22);
  - `secret-shape.ts` and FAC-SEM-057 (FAA-23).
- PR #53 (FAA-18) also claimed this minor version; it moves to the next one.

## Next task

Release 0.11.0 (tag after the merge), re-pin the passioncode launcher to `v0.11.0` as PC-17 did, update locally.
Then FAA-20 part four (FB-7).
