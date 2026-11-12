# Surfaces and auth

## Contents

- [MCP for agents](#mcp-for-agents)
- [CLI for people and scripts](#cli-for-people-and-scripts)
- [A2A for remote agents](#a2a-for-remote-agents)
- [Behind tailscale serve](#behind-tailscale-serve)
- [Token](#token)
- [Dashboard session](#dashboard-session)
- [Headers every response carries](#headers-every-response-carries)

## MCP for agents

- One server inside the service process, `streamable-http`, at `/mcp` on the service
  origin, stateless JSON responses unless the tools stream.
- Authenticate with the service token in the declared header. OAuth is for remote
  multi-user servers, not for a loopback service.
- **Or keep the two roles apart (DEC-0024).** The descriptor's token is the host's: it reads
  events and the usage report, and it mints operator login codes. An MCP token sits in every
  client's `~/.claude.json`. When that matters, give agents their own token (`service.token`
  for agents, `host.token` named by the descriptor), declare `surfaces.mcp.auth: "own"`, and
  make `/mcp` refuse the host's token. `check_service.py` then checks only that refusal
  (`interop.mcp-own-auth`) and leaves the caller rules NOT_RUN.
- **Delegation (DEC-0039, DL-16).** `surfaces.mcp.auth: "delegation"` means `/mcp` takes only
  the estate's delegation tokens; declare `auth.delegation {issuer, jwks}` in the well-known
  document. The probe treats it like `own` and checks the declaration
  (`auth.delegation-declared`). The kits verify the tokens: put `delegation_gate` /
  `delegationGate` in front of the tools (see [the delegation reference](delegation.md)).
- Register it into a client config with the service's own command
  (`<tool> mcp-register`), which first establishes that the port's listener is this OS account's (the contract's
  DEC-0154 HA-2: `fabric_peer_owner.server_end` on a connection of its own, as `check_service.py`'s `listener.owner`
  does; otherwise `foreign-user` and nothing is written), then writes
  `{"type":"http","url":"http://127.0.0.1:<port>/mcp","headers":{...}}` atomically, aborts if the file changed meanwhile, and keeps one 0600 backup. The token
  goes in `headers`, never in the URL: every log that records a URL prints its query
  string. An HTTP registration starts nothing per session: every client session talks to the
  one resident service (LC-19). A stdio server, by contrast, is a process per session; keep
  one only at project scope.
- Ship server `instructions` that tell a caller where to start and that every answer
  carries `degraded`.

## CLI for people and scripts

`<tool> service status|start|stop|restart` (launchctl on the label in the domain `launchd_domain(plist)` names; for a
LaunchDaemon start, stop and restart are root's, and a CLI without root reports the job read-only, lifecycle.md, The system
domain; then the
well-known document from this OS account's listener, else `foreign-user`: protocol.md, The listener's owner), `<tool> dashboard` (resolve the exact registered service with the `fabric-dashboards`
MCP, run `check_dashboard_link.py` on the action, then open its `open_link` with the host's `open` and
`fallback=never`; never `open <url>`, `open -a Safari`, `xdg-open` or `webbrowser.open`; an installed host that
failed is reported, never replaced by a browser; only a confirmed `not_installed` host permits an explicit browser
fallback and its one-time login flow; [dashboard links](dashboard-links.md)), `<tool> doctor --json`
(the same checks the probe runs, plus provider keys), `--json` on every command. Print
a sign-in link only when stdout is a terminal.

## A2A for remote agents

Remote reach goes through A2A `1.0` over HTTPS or an authenticated gateway in front of
MCP, never by binding a LAN address. A tunnel (Tailscale Serve and the like) is an
outward surface with its own token lifetime; watch it like a service, because nothing
else will notice it expire.

A service that answers A2A peers names its public Agent Card in the well-known document's `surfaces.a2a`
(DEC-0122; [the wire reference](protocol.md)). What that card may say:

- On a local placement the public card answers without the token (Host and Origin checks still apply) and its
  interface URLs are on the service's loopback origin, for peers on this computer; on a remote placement they are
  `https`, and a card that is not open is gated by the service's own credentials or an identity proxy.
- An A2A peer is never given the descriptor's token: no interface accepts it and no `securitySchemes` entry names
  it. A2A callers bring the service's own credentials or the estate's delegation tokens; the extended card needs
  one of them.
- The public card carries no secret and none of the well-known document's process members (`build`, `process`,
  `pid`, `status`, `summary`, `degraded`). An extension it declares for a Fabric fact (`uri` under
  `https://fabric.passioncode.ai/`) carries `required: false`; the probe also accepts it absent, which A2A reads as
  false (a protobuf-written card drops a false default), and flags `required: true` or a non-boolean.

`agent_card_findings(card, origin=, remote=, descriptor_header=)` / `agentCardFindings(card, {origin, remote,
descriptorHeader})` report each of these by `code` and place, never the value. The probe runs two rules:

| Rule | PASS when | NOT_RUN when |
|---|---|---|
| `well-known.a2a` | `surfaces.a2a` is the schema's (`FAIL` names each schema error's place and keyword) | no `surfaces.a2a` |
| `a2a.card` | the card at `surfaces.a2a.path`, asked with no `Authorization` header and never the descriptor's token, answers 200 with JSON that has no finding; on a local placement any other answer is a `FAIL` | no member, an unreadable one, or a remote card that answers 401 or 403 (a card that is not open; a refusal is not nonconformance) |

A probe cannot see whether an interface would take the descriptor's token without sending it, which DEC-0122
forbids, so it reads the card only and never calls an interface: an API-key scheme in the descriptor's own
`auth.header` is a finding, and with `Authorization` (the default) the card cannot show it.

## Behind tailscale serve

An agent on a server (a VM, a teammate's machine) can reach people on the tailnet through `tailscale serve`, which
proxies HTTPS on the node's tailnet name to a loopback listener and adds the caller's `Tailscale-User-Login`. The
kit's `fabric_tailnet.py` / `fabric-tailnet.mjs` (FAA-297) turn that into a decision; the agent wires it into its own
handler.

- **A listener of serve's own.** Any process on the machine can send `Tailscale-User-Login` to a loopback port, so the
  header is believed only on a listener that serve alone uses: a second loopback port, or, where the installed
  `tailscale serve` can proxy to one, a Unix socket whose mode keeps other accounts out. Pass `listener="serve"` and the
  connection's peer (`"unix"` for a socket). On any other listener a request carrying serve's headers is refused
  (`serve-header-off-serve`); the Fabric listener keeps its session key and never reads them.
- **A perimeter generated, not kept by hand.** `load_perimeter` / `loadPerimeter` take a `tailnet-perimeter/1`
  document: `generatedFrom {registry, revision, at}` (required: a file without its source is refused,
  `perimeter-not-generated`) and `groups {name: {members, dashboards, capabilities}}`. The organization's generator
  writes it from its access registry; the agent reloads it when the file changes.
- **A personal key for MCP.** `load_keys` / `loadKeys` take `[{id, login, sha256, capabilities}]`, the key's
  `hash_key` / `hashKey` only. A call on the `mcp` surface needs `Authorization: Bearer <key>`; the key must belong to
  the caller's login and its capabilities may not be wider than that login's groups.
- **The answer.** `authorize(listener=, peer=, headers=, perimeter=, surface="dashboard"|"mcp", target=, keys=)`
  answers `{allowed, status, code, login, groups}` (and `key`, the key's id, on an allowed MCP call). Send the
  status and the code as they are; no answer carries a key or its hash.

| Code | Status | When |
|---|---|---|
| `serve-header-off-serve` | 403 | serve's headers on a listener that is not serve's |
| `peer-not-loopback` | 403 | the serve listener was reached from another address |
| `identity-missing`, `identity-ambiguous`, `identity-malformed` | 401 | no login, two, or not a login |
| `not-in-perimeter` | 403 | the login is in no group |
| `dashboard-not-granted` | 403 | no group of the login lists the dashboard |
| `key-required`, `key-unknown` | 401 | an MCP call without a bearer key, or with one not on the list |
| `key-not-yours` | 403 | the key belongs to another login |
| `key-wider-than-group` | 403 | the key's capabilities exceed the login's groups |
| `capability-not-granted` | 403 | the key does not carry the capability called |

A tagged node (a server, not a person) gets no identity header from serve and is refused `identity-missing`; a
machine caller uses the estate's delegation tokens instead. The serve listener is an outward surface: watch it like
the A2A tunnel above.

## Token

- Created once with `ensure_token` at first start, after the instance lock.
- Stored at the descriptor's `auth.tokenFile`, 0600, owner-checked, never a symlink.
- Compared in constant time (`token_matches`).
- Rotation is an operator act: write a new file, restart, re-run `mcp-register` (which checks the listener's owner again).
- Same-user processes can read it. The protocol defends against web pages and
  mistakes, not against hostile code running as the operator; say so in SECURITY.md.

## Dashboard session

- `POST /fabric/v1/login-code` (token) → single-use code, at most 120 s, persisted as
  used before it is honoured, burned even when expired.
- `GET /fabric/v1/login?code=` → `HttpOnly; SameSite=Strict` cookie, 302 to the
  dashboard. `revoke_all` rotates the session key and ends every session at once.
- **The session's lifetime (DEC-0039).** A session ends 12 h after its last use, 7 days after
  the code was redeemed however often it is used, on logout, and when the descriptor token
  rotates. The server enforces all four, not the cookie: `LoginCodes` signs a claim (session
  id, sign-in time, token revision) into the cookie and keeps a record per session (last use,
  logout) in its code store; `session_valid` refuses a session past either bound and refreshes
  the 12 hours on use (at most one write a minute). Pass `token=` (the descriptor token, or a
  callable returning the current one), or a rotation goes unseen. `idle_seconds` and
  `max_seconds` may shorten the bounds; longer values are clamped. The cookie headers default to
  `Max-Age` 7 days, and the probe's `login.session-lifetime` fails a longer one.
- **Logout** is the service's own route and a browser write (the custom header below):
  `codes.logout(cookie)` ends the session for every copy of the cookie, and
  `expired_session_cookie_header()` (`expiredSessionCookieHeader()`) clears the browser's copy.
- An ended session answers `401` on the dashboard page itself, so the host can sign in again.
- Browser writes need the cookie **and** a custom header such as `X-<Tool>-Request: 1`,
  which forces a preflight the service never answers.
- A dashboard that is deliberately read-open to local pages declares
  `"login": false`; its writes still need the header.

## Headers every response carries

`Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, a CSP with no inline
script, and `frame-ancestors 'self'` unless the page must never be embedded. Fabric
Dashboards shows pages in a native view, not a frame, so `X-Frame-Options: DENY` does
not stop it.
