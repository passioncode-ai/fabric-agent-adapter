# Surfaces and auth

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
- Register it into a client config with the service's own command
  (`<tool> mcp-register`), which writes `{"type":"http","url":"http://127.0.0.1:<port>/mcp","headers":{...}}`
  atomically, aborts if the file changed meanwhile, and keeps one 0600 backup. The token
  goes in `headers`, never in the URL — every log that records a URL prints its query
  string.
- Ship server `instructions` that tell a caller where to start and that every answer
  carries `degraded`.

## CLI for people and scripts

`<tool> service status|start|stop|restart` (launchctl on the label, then the
well-known document), `<tool> dashboard` (resolve the exact service and use the Fabric Dashboards host
opener first; installed-but-failed never falls back to a browser; only confirmed
absence permits explicit browser fallback and its one-time login flow), `<tool> doctor --json`
(the same checks the probe runs, plus provider keys), `--json` on every command. Print
a sign-in link only when stdout is a terminal.

## A2A for remote agents

Remote reach goes through A2A `1.0` over HTTPS or an authenticated gateway in front of
MCP — never by binding a LAN address. A tunnel (Tailscale Serve and the like) is an
outward surface with its own token lifetime; watch it like a service, because nothing
else will notice it expire.

## Token

- Created once with `ensure_token` at first start, after the instance lock.
- Stored at the descriptor's `auth.tokenFile`, 0600, owner-checked, never a symlink.
- Compared in constant time (`token_matches`).
- Rotation is an operator act: write a new file, restart, re-run `mcp-register`.
- Same-user processes can read it. The protocol defends against web pages and
  mistakes, not against hostile code running as the operator — say so in SECURITY.md.

## Dashboard session

- `POST /fabric/v1/login-code` (token) → single-use code, at most 120 s, persisted as
  used before it is honoured, burned even when expired.
- `GET /fabric/v1/login?code=` → `HttpOnly; SameSite=Strict` cookie, 302 to the
  dashboard. Sessions are HMAC-signed; `revoke_all` rotates the key and ends every
  session at once.
- Browser writes need the cookie **and** a custom header such as `X-<Tool>-Request: 1`,
  which forces a preflight the service never answers.
- A dashboard that is deliberately read-open to local pages declares
  `"login": false`; its writes still need the header.

## Headers every response carries

`Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, a CSP with no inline
script, and `frame-ancestors 'self'` unless the page must never be embedded. Fabric
Dashboards shows pages in a native view, not a frame, so `X-Frame-Options: DENY` does
not stop it.
