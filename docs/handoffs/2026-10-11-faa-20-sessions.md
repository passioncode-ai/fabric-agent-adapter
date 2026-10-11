# FAA-20 part one — DEC-0039 operator session lifetime, DL-16 in the probe, pin → the DEC-0039 merge (0.10.0)

Branch `agent/faa-20-dec0039-sessions`, cut from `origin/main` after PR #56. Spec and REQ table:
[2026-10-11-faa-20-sessions](../evidence/specs/2026-10-11-faa-20-sessions.md). Backlog row FAA-20, issue #52.

## Objective

Make the kits' operator session obey contract DEC-0039 on the server (12 h idle, 7 days absolute, logout, token
rotation), make the probe treat `surfaces.mcp.auth: "delegation"` like `own` (DL-16), and move the contract pin
to the DEC-0039 merge (contract PR #30) so both are normative under the pin.

## Completed

- `fabric_service.py` and `fabric-service.mjs` `LoginCodes`: signed claim `v2.<sid>.<signedInAt>.<tokenRevision>.<mac>`
  plus a per-session record in the code store; `session_valid` enforces both bounds and refreshes the idle bound
  (one write a minute at most); `logout`; `token=` for rotation; `idle_seconds`/`max_seconds` clamp; `clock=` for
  tests; cookie headers default to `Max-Age` 604800; `expired_session_cookie_header` /
  `expiredSessionCookieHeader`.
- `check_service.py`: `delegation` handled like `own`; rules `auth.delegation-declared` and
  `login.session-lifetime`; `session_lifetime_problem()`.
- Sample services: `token=` and `POST /logout` (needs `X-Fabric-Request`).
- Pin `a83bec6` → `8e49fbd`, `a83bec6` joins the supported revisions (lock file, README, SKILL-CARD, the three
  skills, `adapt_project.py`, `protocol.md`, `test/validate.py`, `test_contract_revisions.py`).
- Docs: `surfaces-and-auth.md`, `remote-placement.md`, `protocol.md` (now with Contents). Evals first:
  `operator-session-lifetime`, `mcp-auth-delegation`. CHANGELOG 0.10.0; version 0.10.0 everywhere.

## Compatibility review (the three profiles)

Between `a83bec6` and `8e49fbd`: DEC-0037 (spend policy), DEC-0038 (grant windows), DEC-0039 (delegation),
DEC-0040 (Fabric's button). New schemas and optional properties only; the provider manifest gains optional cost
presets; MCP, A2A and local-runner profile declarations do not change. The compiled-schema arms (old `2ce3922`,
new `8e49fbd`, clean checkouts with `pnpm install --frozen-lockfile`) are the check; see the PR body.

## Decisions

See the spec's Decisions. The two the operator may want to overturn: an old-format cookie is refused (one more
sign-in after the upgrade, done by the host on the 401), and a remote service with `MemoryCodeStore` loses its
sessions on a deploy.

## Open

- FAA-20 part two: `verifyDelegation`/`verifyApproval` in both kits with the contract's vectors (RFC 8785
  example, the DL-13 refusal table), and Fabric's button (FB-7) in the dashboard kit.
- PR #53 (FAA-18) carried 0.10.0; it moves to the next minor once this lands.

## Next task

FAA-20 part two: port `verifyDelegation` and `verifyApproval` from contract `src/delegation.ts` and
`src/delegation-rules.ts` (at the pin) to `fabric_service.py`/`fabric_interop.py` and the Node kit, with the
contract's fixtures as test vectors.
