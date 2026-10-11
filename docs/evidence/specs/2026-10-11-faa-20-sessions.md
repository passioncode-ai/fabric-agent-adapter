# FAA-20, first increment — contract DEC-0039 in the probe and the kits' operator session

Run: 2026-10-11. Branch `agent/faa-20-dec0039-sessions`. Backlog row FAA-20, issue #52. Requested by the
contract's DEC-0039 handoff and by fabric-workspace (issue #52); a service that vendors the kit waits for this
release to re-vendor once.

## Objective

A service built with the kit keeps an operator session no longer than DEC-0039 allows, and the server, not the
browser, enforces that: 12 h after last use, 7 days after the login code was redeemed, on logout, and when the
descriptor token rotates. The probe treats `surfaces.mcp.auth: "delegation"` like `own` (DL-16). The contract
pin moves to the DEC-0039 merge so both rules are normative under the pin.

Not in this increment (FAA-20 stays open for them): `verifyDelegation`/`verifyApproval` in the kits, Fabric's
button (FB-7) in the dashboard kit.

## Source ledger

| Source | What it gave |
|---|---|
| contract `docs/specification/service.md` §"The session's lifetime" (`#operator-session-lifetime`) at the DEC-0039 merge | the four ends, "a service MAY shorten either bound and MUST NOT lengthen one", "a request within the bounds refreshes the 12 hours" |
| contract `src/operator-session.ts` `operatorSessionExpiresAt` at the DEC-0039 merge | the rule as code: `min(lastUsedAt + idle, signedInAt + max)`, `null` after logout or token rotation, longer policies clamped |
| contract `docs/specification/service.md` "An ended session is answered on the page" | an ended session answers `401` on the page; the host MAY sign in again at most once a minute per page |
| contract `docs/specification/delegation.md` DL-16 | `mcp.auth: "delegation"` accepts only delegation tokens; a host and a probe MUST NOT call it with the descriptor token; `auth.delegation {issuer, jwks}` is then required |
| contract `schemas/service-well-known.schema.json` diff pin → DEC-0039 merge | `mcp.auth` enum gains `delegation`; top-level `auth.delegation`; an `allOf` requiring it with `delegation` |
| contract diff pin → DEC-0039 merge, `schemas/` | additive only: new schemas (delegation, approval, grant-check, spend-policy, fabric-link), optional new properties in manifest, usage and governance; governance `effects` relaxed by an `anyOf`; interop-agent-call's pattern moved to a `$ref` |
| contract handoff `docs/handoffs/2026-10-11-delegation-and-fabric-button.md` | the adapter's open items, and "repin to this change's merge commit" |
| this repository: `fabric_service.py` `LoginCodes` (`session_valid` checks only the HMAC), `fabric-service.mjs` `LoginCodes`, `check_service.py` `interop.mcp-own-auth` and `login.single-use`, the sample services, `references/surfaces-and-auth.md`, `references/remote-placement.md` | the code under change; nothing enforces any session bound today and cookies default to `Max-Age` 30 days |
| `docs/handoffs/2026-10-10-contract-pin-52da526.md` | the repin procedure: lock file and every live pin mention, the old default joins `SUPPORTED_CONTRACT_COMMITS`, the three-profile compatibility review, both compiled-schema arms |
| `docs/evidence/retro.md`, `docs/evidence/verification.md`, `graphify-out/` | none found in this repository |

## Decisions (grill closed from the sources; the operator may overturn any of them)

1. **Pin → the DEC-0039 merge of contract PR #30**, not contract `main`. The handoff names that commit; later
   decisions (DEC-0041 meter, DEC-0042 session handoff) get their own review. The DEC-0036 merge (0.9.0's
   default) joins the supported revisions.
2. **The session is a signed claim plus a server record.** The cookie value is
   `v2.<sid>.<signedInAt>.<tokenRevision>.<mac>` (HMAC-SHA256 over everything before the mac, with the session
   key). The code store, the same one that holds login codes, keeps a record per session (`lastUsedAt`, logout),
   so idle and logout are enforced by the server. A cookie without a record is refused.
3. **A cookie of the old format (`<sid>.<mac>`) is refused.** After the upgrade, every operator signs in once
   more; the host does that by itself on the page's `401`.
4. **A remote service with `MemoryCodeStore` loses its sessions on a deploy.** That is the price of an
   enforceable logout and idle bound without a durable disk; the host signs in again on the `401`. A service that
   needs sessions across deploys passes a durable `store`. `references/remote-placement.md` says so instead of
   "sessions survive a deploy".
5. **Token rotation is seen through the token itself**: `LoginCodes(..., token=)` takes the descriptor token or
   a callable that returns the current one; the revision is an HMAC of the token under the session key (so the
   cookie reveals nothing about it). Without `token=` the kit cannot see a rotation; it stays accepted for
   compatibility, and the docs and the samples pass it.
6. **The last-use write is throttled to once a minute.** That shortens the idle bound by at most 60 s, which the
   contract allows; it keeps a busy page from writing the store on every request.
7. **Logout** is a kit method (`logout` / `logout`) plus a header that clears the cookie; the contract defines no
   logout route, so the service chooses its own.
8. **Cookie `Max-Age` defaults to 7 days** (the absolute bound), never the idle bound: the server decides.
9. **The probe** adds `login.session-lifetime` (the cookie set at login does not outlive 7 days) and
   `auth.delegation-declared` (with `mcp.auth: "delegation"`, `auth.delegation` names an issuer and a JWKS), and
   handles `delegation` like `own` for the token-refusal check and the `NOT_RUN` caller rules.
10. **Version**: the next minor after whatever `main` carries at merge time (0.10.0 is taken by PR #53 if it lands
    first). Released by tag after the merge, per the operator's release rule.

## REQ table

| REQ | Requirement | Verified by |
|---|---|---|
| REQ-01 | Python `LoginCodes`: a session ends 12 h after last use; use within the bound refreshes it | unit test with a patched clock |
| REQ-02 | Python: a session ends 7 days after redemption however often it is used | unit test |
| REQ-03 | Python: `logout()` ends it on the server, and a copy of the cookie is refused afterwards | unit test |
| REQ-04 | Python: a session begun under one descriptor token is refused once the token rotates | unit test |
| REQ-05 | Python: shorter `idle_seconds`/`max_seconds` apply; longer ones are clamped to 12 h / 7 d | unit test |
| REQ-06 | Python: a forged mac, an old-format cookie and a cookie with no server record are refused | unit test |
| REQ-07 | Python: cookie headers default to `Max-Age` 604800; a clearing header exists for logout | unit test |
| REQ-08 | Node `LoginCodes`: REQ-01…REQ-07 with the same behaviour | `node --test` |
| REQ-09 | Remote (`MemoryCodeStore` + key): sessions work; a new store (a deploy) refuses the old cookie | unit tests, Python and Node |
| REQ-10 | Probe: `mcp.auth: "delegation"` is checked for refusing the descriptor token, caller rules `NOT_RUN` (DL-16) | unit test |
| REQ-11 | Probe: `auth.delegation-declared` PASS/FAIL/NOT_RUN | unit test |
| REQ-12 | Probe: `login.session-lifetime` FAIL for a cookie over 7 days, PASS at or under | unit test + the live sample service |
| REQ-13 | The sample services (Python local, Node remote) pass `token=` and offer logout | live-service test; the probe against the sample |
| REQ-14 | Pin → the DEC-0039 merge everywhere; the DEC-0036 merge joins the supported revisions; both compiled-schema arms pass | `test/validate.py`, `test_contract_revisions` with real checkouts |
| REQ-15 | Docs: `surfaces-and-auth.md`, `remote-placement.md`, `protocol.md` say the lifetime and DL-16; a scenario eval written first | `test/validate.py`; eval file diff precedes prose |
| REQ-16 | Version, CHANGELOG, backlog FAA-20 progress, README/SKILL-CARD pin; issue #52 closed with the receipt | `test/validate.py`; release run; `npm view` |
