# FAA-20 part two — the delegation verifiers in both kits (DEC-0039, Fabric ADR-0144 step 4)

Run: 2026-10-12. Branch `agent/faa-20-verifiers`. Backlog row FAA-20 (part one shipped as 0.10.0). Requested by
the contract's DEC-0039 handoff ("port `verifyDelegation`/`verifyApproval` to the Python and Node kits"); a
service that vendors the kit (one is waiting) re-vendors once these land.

## Objective

A service built with the kit checks a delegation token and an approval offline, exactly as the contract's
verifier at the pin does, in Python and in Node, and answers with the DL-19 refusal shape. Fabric's button
(FB-7) is not in this part; it becomes part three.

## Source ledger

| Source | What it gave |
|---|---|
| contract `src/delegation.ts` at the pin (DEC-0039 merge) | the verifier to port: header and key rules, `authentic`, the DL-13 order and details, `verifyApproval`, `createMemoryJtiStore`, `readDelegationToken`, `jcs`, `actionDigest`, `effectClosure`, `chainDepth`, `hasDuplicateMembers` |
| contract `docs/specification/delegation.md` DL-9…DL-19 | headers (DL-9, DL-10), never in a URL or argv (DL-11), the 11-step table (DL-13), JWKS caching (DL-15: at most 10 minutes; on an unknown `kid` re-read at most once a minute), the approval order and the required jti store (DL-18), the 17 codes and their HTTP status (DL-19), `WWW-Authenticate: Bearer error="invalid_token"` on 401 |
| contract `test/delegation.test.ts` at the pin | the cases each kit must answer the same way: rotation, issuer-unavailable, unauthenticated variants, leeway both ways, audience, depth, whole-name scope, effect closure, approval reuse, RFC 8785 §3.2.2/§3.2.3 example |
| this repository: `fabric_interop.py` `McpToolServer`, `tool_result`; `fabric-interop.mjs` `toolResult`; AGENTS.md "standard library only" | where the gate plugs in, and the constraint that rules out a crypto package in Python |

## Decisions

1. **Python verifies Ed25519 in pure standard-library Python** (RFC 8032 §5.1.7, cofactorless, as OpenSSL
   does: `S` must be below `L`, `A` and `R` must decode, `R` is compared by its encoding). Verification uses only
   public data, so constant time is not required. Proven by RFC 8032 test vectors and by a differential test
   against Node's OpenSSL over generated signatures, including malleated (`S + L`) and non-canonical ones.
2. **New modules, opt-in**: `fabric_delegation.py` and `fabric-delegation.mjs` beside the service kits, so a
   service that vendors the kit copies one more file only when it accepts delegation.
3. **Shared vectors**: `test/fixtures/delegation/vectors.json`, produced by `make_vectors.mjs` with a fixed key and
   clock. The expected answer of every case comes from running the contract's own verifier at the pin over it
   (recorded by the generator), and both kits must match code and detail.
4. **JWKS**: `JwksCache` holds the set at most 10 minutes and re-reads at most once a minute on an unknown `kid`
   (DL-15); a set it cannot read is `issuer-unavailable`. Source: an https URL, an http URL on loopback, or a
   file path.
5. **Jti stores**: memory (single process, tests) and a file store that survives a restart (DL-18), with a lock.
   `UNSAFE_NO_JTI_STORE` exists by name only.
6. **The gate**: `delegation_gate(...)` / `delegationGate(...)` returns, for one `tools/call`, either the accepted
   delegation or a DL-19 refusal; `McpToolServer(authorize=...)` in Python runs it before the handler and puts the
   accepted delegation on the call context. A refusal is a tool result with `isError: true` and
   `structuredContent: {error: {code, data: {detail}}}`; the HTTP form carries the DL-19 status.
7. **`verifyMeterToken` is not ported**: it is the meter's side (DL-21), not a service's.

## REQ table

| REQ | Requirement | Verified by |
|---|---|---|
| REQ-01 | Python Ed25519 verify matches RFC 8032 vectors and Node's OpenSSL over 200+ generated cases; `S ≥ L`, bad points and wrong lengths refused | unit tests |
| REQ-02 | `verify_delegation` / `verifyDelegation` answer every vector with the contract verifier's code and detail | vector tests, both kits |
| REQ-03 | `verify_approval` / `verifyApproval` likewise, including reuse through a jti store and the required-store rule | vector tests |
| REQ-04 | `jcs` / `action_digest` match RFC 8785's example and refuse what has no canonical form; numbers in ECMAScript form | unit tests, both kits |
| REQ-05 | `read_delegation_token` reads `Fabric-Delegation` first (present but empty is a token), then a delegation-typ Bearer | unit tests |
| REQ-06 | `JwksCache` obeys DL-15 and yields `issuer-unavailable` when it cannot read | unit tests with a fake clock and fetcher |
| REQ-07 | the file jti store refuses a second use across a restart and prunes expired ids | unit tests |
| REQ-08 | the gate and `McpToolServer(authorize=)` refuse in the DL-19 shape and pass the delegation to the handler | unit tests |
| REQ-09 | docs: a `references/delegation.md`, `surfaces-and-auth.md` and `protocol.md` no longer say "not yet"; scenario eval first | `test/validate.py` |
| REQ-10 | version, CHANGELOG, backlog FAA-20, release | `test/validate.py`; release run; npm |
