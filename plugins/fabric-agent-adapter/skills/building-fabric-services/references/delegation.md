# Delegation — checking who acts for whom (DEC-0039)

A service that other agents of the estate call checks each call offline with the kit's verifier: the estate hub
signs a delegation token naming the person (`sub`), the actor chain (`act`), this service (`aud`), the
capabilities (`scope`) and the effect ceiling (`effect`); the service checks the signature against the estate's
published keys and answers `ok` or one refusal code. Contract: `docs/specification/delegation.md` (DL-1…DL-19)
at the pin. Python: [`scripts/fabric_delegation.py`](../scripts/fabric_delegation.py); Node:
[`scripts/fabric-delegation.mjs`](../scripts/fabric-delegation.mjs). Both answer the shared vectors exactly as the
contract's own verifier does.

## Contents

- Declaring it
- Wiring the gate
- Approvals
- What a refusal looks like
- Keys and the cache
- What the kit does not do

## Declaring it

In the well-known document: `surfaces.mcp.auth: "delegation"` (only delegation tokens) and
`auth.delegation: {issuer, jwks}` — the `iss` you trust (`urn:fabric:estate:<id>`) and where the key set is read.
The descriptor's token stays the host's: it is never a caller's credential on `/mcp` (DL-12). The probe checks
the declaration (`auth.delegation-declared`) and that `/mcp` refuses the descriptor token.

## Wiring the gate

```python
import fabric_delegation as fd, fabric_interop as fi
keys = fd.JwksCache(well_known["auth"]["delegation"]["jwks"])          # https, loopback http, or a file
gate = fd.delegation_gate(audience="example-agent", jwks=keys, issuer=well_known["auth"]["delegation"]["issuer"],
                          effects={"example.write": "draft", "example.publish": "publish"})   # each tool's manifest effect
server = fi.McpToolServer("example-agent", VERSION, authorize=gate)    # pass the request headers to handle()
# in a handler: ctx.delegation["principal"], ["caller"], ["chain"] — record the chain with the work
```

```js
import { JwksCache, delegationGate, refusalToolResult } from './fabric-delegation.mjs';
const gate = delegationGate({ audience: 'example-agent', jwks: new JwksCache(wk.auth.delegation.jwks), issuer: wk.auth.delegation.issuer,
  effects: { 'example.write': 'draft' } });
const verdict = await gate(params.name, req.headers);
if (!verdict.ok) return refusalToolResult(verdict);
```

The token is read from `Fabric-Delegation` first (a forwarded call; present but empty is refused, never skipped),
then from `Authorization: Bearer` when the bearer is a delegation JWT (DL-9, DL-10). A tool with no declared
effect is refused (`unknown-state`), never guessed. The checks run in the DL-13 order; nothing about a token is
believed before its signature. The built-in job tools (`fabric.job.get`, `fabric.job.cancel`) are not gated: the
contract does not yet say how a job read is scoped, and a job id is unguessable.

## Approvals

An action with an external effect may need the operator's approval (DL-17, DL-18). The order is fixed: the token,
then the grant check where there is one, then `verify_approval` / `verifyApproval`, which consumes the approval's
`jti` last, then the action. Without an approval, answer `approval-required` with
`action_digest(action)` / `actionDigest(action)` — the SHA-256 of the action's RFC 8785 form (`jcs`) — so the caller
can ask the hub. Keep consumed ids in `FileJtiStore` (0600, survives a restart); `MemoryJtiStore` is for tests
and `UNSAFE_NO_JTI_STORE` exists only by name. No store at all is `unknown-state`.

## What a refusal looks like

DL-19: an MCP tool answers `refusal_tool_result(r)` / `refusalToolResult(r)` — `isError: true` and
`structuredContent: {error: {code, message, data: {detail}}}`; an HTTP route answers `refusal_http(r)` /
`refusalHttp(r)` with the code's status (401 for `unauthenticated`, `token-expired`, `principal-unproven`, with
`WWW-Authenticate: Bearer error="invalid_token"`; 503 for `issuer-unavailable` and `unknown-state`; 403 for the
rest). `detail` is a short machine word; the token, the approval and the keys never appear in a result or a log.

## Keys and the cache

`JwksCache` holds the estate's key set at most 10 minutes and, on a `kid` it does not hold, re-reads at most once
a minute (DL-15); after 10 minutes without a successful read it answers nothing, and the verifier says
`issuer-unavailable`. It reads https, http on loopback only, or a file; a URL with credentials is refused. The
Python kit verifies Ed25519 itself (RFC 8032, standard library only, strict as OpenSSL: `S` below the group order,
canonical points); the Node kit uses `node:crypto`.

## What the kit does not do

It does not mint tokens, check attenuation against a parent (the issuer's rule, DL-5), check a grant or a spend
window (the meter's, DL-21), or decide which actions need an approval — the service decides that.
