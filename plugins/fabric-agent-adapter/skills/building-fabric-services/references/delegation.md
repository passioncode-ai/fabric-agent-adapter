# Delegation: checking who acts for whom (DEC-0039)

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
- Who must present a token
- Approvals
- What a refusal looks like
- Keys and the cache
- Keys the estate record certifies
- What the kit does not do

## Declaring it

In the well-known document: `surfaces.mcp.auth: "delegation"` (only delegation tokens) and
`auth.delegation: {issuer, jwks}`: the `iss` you trust (`urn:fabric:estate:<id>`) and where the key set is read.
The descriptor's token stays the host's: it is never a caller's credential on `/mcp` (DL-12). The probe checks
the declaration (`auth.delegation-declared`) and that `/mcp` refuses the descriptor token.

## Wiring the gate

```python
import fabric_delegation as fd, fabric_interop as fi
keys = fd.JwksCache(well_known["auth"]["delegation"]["jwks"])          # https, loopback http, or a file; one 5 s deadline per fetch
gate = fd.delegation_gate(audience="example-agent", jwks=keys, issuer=well_known["auth"]["delegation"]["issuer"],  # required
                          effects={"example.write": "draft", "example.publish": "publish"})   # each tool's manifest effect
server = fi.McpToolServer("example-agent", VERSION, authorize=gate)    # pass the request headers to handle()
# in a handler: ctx.delegation["principal"], ["caller"], ["chain"]; record the chain with the work
```

```js
import { JwksCache, delegationGate, refusalToolResult } from './fabric-delegation.mjs';
const gate = delegationGate({ audience: 'example-agent', jwks: new JwksCache(wk.auth.delegation.jwks), issuer: wk.auth.delegation.issuer,
  effects: { 'example.write': 'draft' } });
const verdict = await gate(params.name, req.headers);
if (!verdict.ok) return refusalToolResult(verdict);
```

## Who must present a token

DL-25 places each caller in a tier by its origin: **T0** a loopback caller under the owner's account that the
service's own local floor (the descriptor token, the Host guard) has authenticated; **T1** an enrolled machine of
the same owner; **T2** everyone else, and any call relayed onto loopback from off the machine (a tunnel, a proxy, the
hub forwarding a T2 caller). DL-26: a T0 or T1 caller is never required to present a token; pass the tier,
`gate(tool, headers, tier="T0")` or `server.handle(message, headers, tier="T0")`, and the call passes with no
delegation. A token such a caller presents is still verified and refused when invalid. A T2 caller takes the whole
profile. Money limits and human gates bind at every tier.

**The family and the agent network** (DEC-0130, wording settled by DEC-0137). The operator's family is every agent
placed on a machine of his estate and his own local sessions; a callee recognises it only by placing the caller in T0
or T1 (DL-27). It is neither a context (`personal` and `org:<orgId>` stay the only ones) nor a tier: it is open to
what DL-26 opens, everything open to the operator in the call's context, which for a tokenless call is the callee
instance's own context. No claim of a caller places it in the family: a call relayed onto loopback stays T2 unless the
relay proves the origin's tier, and a caller under another OS account stays T2 (DL-28). The agent network is every
agent a caller can reach, the family included; outside the family a caller is T2, with a token per call (DL-29). Money
limits, human gates, the contexts, the credential source (never another agent's key or vault slot), the machine
profiles on calls over the relay, and a relayed action's decision or mandate still bind inside the family (DEC-0137).
Every T0 process of the owner's account counts as the family, one he did not install included, so a product that must
hold against a hostile local process adds its own approval (FAA-148). The kit's tiers already do this; nothing changes in code.

The token is read from `Fabric-Delegation` first (a forwarded call; present but empty is refused, never skipped),
then from `Authorization: Bearer` when the bearer is a delegation JWT (DL-9, DL-10). A tool with no declared
effect is refused (`unknown-state`), never guessed. The checks run in the DL-13 order; nothing about a token is
believed before its signature. The built-in job tools (`fabric.job.get`, `fabric.job.cancel`) are gated too: by the
job's own capability and effect, and only for the principal and caller that started the job (another caller is
`scope-not-granted`); `on_input` gets the checked delegation on its context. Start jobs with `ctx.start_job()` so the
job records who started it.

**A partner in the chain** (DEC-0090). A token a partner's agent presents for a customer organization carries the
partner as the innermost actor: `{partner: "org:<id>"}`, exactly that member, under at least one agent. It counts
toward the depth limit and ends the chain; outermost, with an `act` beneath, or as `personal` it is
`malformed-chain`. A node with a `sub` beside `partner` is checked as an agent, yet `ctx.delegation["chain"]` lists it
by its `org:` id, as the contract's `chainOf` does; the schema refuses such a node, so a correct issuer never mints one
(raised with the contract, FAA-64). Job ownership and idempotency keys follow `(principal, caller)` and do not include
the partner (FAA-64). `chain_depth(act)` /
`chainDepth(act)` answer the contract's depth, infinity for a chain that is not one. Minting a partner's token (its
grant, FAC-SEM-124) is the issuer's, not the kit's.

## Approvals

An action with an external effect may need the operator's approval (DL-17, DL-18). The order is fixed: the token,
then the grant check where there is one, then `verify_approval` / `verifyApproval`, which consumes the approval's
`jti` last, then the action. Without an approval, answer `approval-required` with
`action_digest(action)` / `actionDigest(action)` (the SHA-256 of the action's RFC 8785 form, `jcs`) so the caller
can ask the hub. When the meter denies a grant check, answer `refusal_from_denial(denial)` /
`refusalFromDenial(denial)`: the meter's code unchanged, its window and level in `error.data` (DL-21 step 6). Keep consumed ids in `FileJtiStore` (owner-only through the kit's private writer: 0600, on Windows a protected ACL; survives a restart); `MemoryJtiStore` is for tests
and `UNSAFE_NO_JTI_STORE` exists only by name. No store at all, or a store file that cannot be read, is
`unknown-state`, never a pass.

## What a refusal looks like

DL-19: an MCP tool answers `refusal_tool_result(r)` / `refusalToolResult(r)`: `isError: true` and
`structuredContent: {error: {code, message, data: {detail}}}`; an HTTP route answers `refusal_http(r)` /
`refusalHttp(r)` with the code's status (401 for `unauthenticated`, `token-expired`, `principal-unproven`, with
`WWW-Authenticate: Bearer error="invalid_token"`; 503 for `issuer-unavailable` and `unknown-state`; 403 for the
rest, `profile-forbids` included: DEC-0106's refusal of a call between two machines of one estate that a machine's
profile does not allow). A published key the service cannot use (of small order, for another use, or published twice) is the
issuer's fault, `issuer-unavailable` (DEC-0045); a gate without a trusted issuer refuses everything as
`no-trusted-issuer`. `detail` is a short machine word; the token, the approval and the keys never appear in a result or a log.

DEC-0121 adds three codes to the one set, each 403: `operator-decision-required` (a `relayed` action called without the
operator's decision), `decision-invalid` (a decision for another action or object, outside its 24 hours, or malformed)
and `human-step-required`, which carries `data.humanStep` (`sign-in`, `consent`, `payment`, `secret`,
`spend-above-limit`, `passkey`) and `data.url` (an https URL or a path on the service's origin) beside `detail`.
`refusal_from_action` / `refusalFromAction` turn an action decision into that refusal; a service's own fault never
reaches the caller and reads as `unknown-state`, but for `mandate-capability-missing` (DEC-0141 MJ-1): the caller
reads `operator-decision-required` with that `data.detail`, since no mandate covers the step and only a decision does. Since 0.51.0 the `operator-decision-required` message (free text in
DL-19, at most 500 characters) also names, in order, the routes for a client that cannot set `_meta`: Fabric's
`agent.call` with `call.decision` once the hub forwards it (CT-125), the service's own elicitation, else the action's
page as Fabric Dashboards' `open_link`; both kits carry the same sentence. The gate that answers them is in
[the interop reference](interop.md#actions).

## Keys and the cache

`JwksCache` holds the estate's key set at most 10 minutes and, on a `kid` it does not hold, re-reads at most once
a minute (DL-15), and waits 10 s after a failed read before trying again; after 10 minutes without a successful read it answers nothing, and the verifier says
`issuer-unavailable`. It reads https, http on loopback only, or a file; a URL with credentials is refused. The
Python kit also refuses, https included, a URL holding a space or ASCII control character before its first `#` (it
reads the URL up to there, as Node does), or a character outside ASCII in its path or query (urllib would send it
and every read fail; a trailing ASCII space or line break is trimmed as urllib reads it; a Unicode space ending the
part before the first `#` is refused, as `check_url` refuses it, though urllib would trim it and read the keys,
because Node keeps it percent-encoded; a leading space is refused as not a URL), a host holding `%`, a backslash, a Unicode space or a control character (urllib
would decode or dial it as another host), a bracketed host that is no IPv6 address, a port above
65535, no host, and an empty userinfo. The Node kit accepts several of these as `new URL` reads them, among them a `%`
host decoded, a backslash as `/`, a tab or line break removed, an empty userinfo dropped and an extra slash before the
host skipped. The
Python kit verifies Ed25519 itself (RFC 8032, standard library only, strict as OpenSSL: `S` below the group order,
canonical points, no small-order key); it follows no redirect when it reads the key set; the Node kit uses `node:crypto` and refuses small-order keys
itself (`isSmallOrderKey`), because Node before 26 lets OpenSSL accept a signature under one.

## Keys the estate record certifies

A verifier that also reads the estate's record (DEC-0055, DEC-0060, [the estate record reference](estate-record.md))
trusts a `kid` only while the revision it reads certifies it (DL-14, row 4a, right after the signature). Pass the
current verified revision as `estate=` / `{ estate }`, as a value or as a function returning it, with
`estate_applied` / `estateApplied` and `estate_revocations` / `estateRevocations`, to `delegation_gate`,
`verify_delegation` or `verify_approval`.
- An uncertified `kid` is the token's fault: `unauthenticated` (`approval-invalid` for an approval), detail
  `kid-not-certified`.
- A revision that cannot be read, is outside its window, is lower than the applied one or forks it is the trust
  source's fault: `issuer-unavailable`, detail `estate-unreadable`, `estate-outside-window`, `estate-rolled-back` or
  `estate-forked`.
- Without `estate` (the option left out), nothing changes. An explicit `null` (Python `None`) for `estate`, its
  applied mark or its revocations is an unreadable source, `estate-unreadable`, in both kits (FAA-78).
- Every verifier refuses a clock that is not a number of seconds `unknown-state` `no-clock` before row 1: a NaN clock
  would make every time row false and pass an expired token.
- **Which hub key a token is checked against** (DL-14a, DEC-0128). An organization's tokens are signed by that
  organization context's own hub key (`machines[].contextHubKeys`), under the context issuer its pin names
  (`organizations[].iss`, `urn:fabric:context:<opaque>`, never the estate id). An instance that serves an organization
  passes its context as `estate_context=` / `{ estateContext }` to `delegation_gate` or `verify_delegation`, once the
  record pins its organization (until then its tokens are refused `kid-not-certified`, brief D5), and that pin's `iss`
  as `issuer`: the `kid` is then trusted only when one machine lists it for that context with that key and
  the record pins the organization. Without it, or with `personal`, the personal `hubKey` is read, so a context key
  never verifies a personal token and the personal key never an organization's; any other value (`Org:x`, a trailing
  space, a number) certifies nothing. `verify_approval` takes no context (the contract's `VerifyApprovalOptions`
  declares none at the pin), so it reads the personal keys. Held to `contextCases` and `contextVerifier` in `test/fixtures/contract/hub-key-vectors.json`.

## What the kit does not do

It does not mint tokens, check attenuation against a parent (the issuer's rule, DL-5), check a grant or a spend
window (the meter's, DL-21), or decide which actions need an approval or the operator's decision: the service
declares that in its action table (each action's gate, [interop](interop.md#actions)).
