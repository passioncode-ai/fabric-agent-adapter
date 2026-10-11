# FAA-20 part two — delegation verifiers (work in progress)

Branch `agent/faa-20-verifiers`, not merged, not released. Spec and REQ table:
[2026-10-12-faa-20-verifiers](../evidence/specs/2026-10-12-faa-20-verifiers.md).

## Done (REQ-01…REQ-08, Python)

- `test/fixtures/delegation/make_vectors.mjs` → `vectors.json`: 65 delegation, 15 approval, 8 header, 5 jcs,
  2 digest and 322 Ed25519 cases. Expected answers come from the contract's `src/delegation.ts` at the pin; the
  Ed25519 cases are checked by OpenSSL. To regenerate: copy the contract's `src/delegation.ts` and
  `src/findings.ts` at the pin into a directory, change `./findings.js` to `./findings.ts`, then run
  `node test/fixtures/delegation/make_vectors.mjs --contract-src <dir> --claims <contract>/fixtures/positive`
  (Node 23.6+).
- `building-fabric-services/scripts/fabric_delegation.py`: Ed25519 in pure Python (RFC 8032, strict), `verify_delegation`,
  `verify_approval`, `read_delegation_token`, `jcs`, `action_digest`, `MemoryJtiStore`, `FileJtiStore`,
  `UNSAFE_NO_JTI_STORE`, `JwksCache` (DL-15), `delegation_gate`, `refusal_tool_result`, `refusal_http`.
- `fabric_interop.McpToolServer(authorize=)`: the gate runs before each handler, and `CallContext.delegation`
  carries the accepted delegation. Built-in job tools are not gated.
- `test/test_fabric_delegation.py`: 18 tests, all OK (`cd test && python3 -m unittest test_fabric_delegation`).

## Open, in this order

1. Node: `fabric-delegation.mjs` with the same API in camelCase (Node `crypto` for Ed25519), and
   `test/fabric-delegation.test.mjs` over the same `vectors.json`.
2. Run the full `npm test` (the `McpToolServer` change touches existing interop tests), plus
   `claude plugin validate --strict` ×2.
3. Scenario eval first, then docs: a new `references/delegation.md`; drop "not yet" from `surfaces-and-auth.md`
   and `protocol.md`; mention it in the SKILL.md references index.
4. An independent review (security: the Ed25519 port and the JSON parsing differences from the contract), then
   the version (next minor after `main`; PR #53 may hold 0.11.0), CHANGELOG, backlog FAA-20, PR, merge, tag and
   release. Re-pin the launcher (passioncode `family.json`, as PC-17 did), then update locally with
   `npx @passioncode-ai/passioncode@latest update`.
5. FAA-20 part three: Fabric's button (FB-7) in the dashboard kit.
