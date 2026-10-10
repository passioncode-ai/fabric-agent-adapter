# fabric-service/0.1 — wire reference

Pinned to `fabric-agent-contract` commit `52da526d7cc1e063d74c5b520dbc03d0ace15246`
(`docs/specification/service.md`, DEC-0015; the usage report DEC-0021; Windows and Linux supervision
DEC-0032 and DEC-0033; the operator channel DEC-0034 and DEC-0035). The contract's schemas are normative;
this page is the working summary. Extension key:
`https://fabric.passioncode.ai/agent-contract/extensions/service/0.1`.

## Descriptor — written by the installer

Directory: macOS `~/Library/Application Support/ai.passioncode.fabric/services/`,
Linux `${XDG_DATA_HOME:-~/.local/share}/passioncode-fabric/services/`, Windows
`%LOCALAPPDATA%\passioncode-fabric\services\` (DEC-0032), or `FABRIC_SERVICES_DIR`.
File `<id>.<instance>.json`, mode 0600 (on Windows a protected ACL), atomic.

| Field | Rule |
|---|---|
| `protocol` | `"fabric-service/0.1"` |
| `id`, `instance` | `^[a-z][a-z0-9-]{1,62}$`, `^[a-z][a-z0-9-]{0,31}$` (default `default`); the pair is unique per machine |
| `name`, `summary` | ≤ 80 and ≤ 200 characters |
| `origin` | `http://127.0.0.1:<port>`; the port is a machine-wide claim |
| `auth` | `tokenFile` (0600; on Windows a protected ACL — owner and every granting entry the current user, SYSTEM or Administrators: service.md *Windows token files*, DEC-0032, DEC-0033); `header` default `Authorization` with `scheme` `Bearer`; any other header carries the raw token with `scheme: "none"` |
| `lifecycle` | `manager` `launchd` (then `label` and `plist`), `systemd` (then `unit`, a `systemctl --user` unit), `task-scheduler` (then `task`, a per-user Scheduled Task) or `none`; `unit` and `task` are refused beside any other manager (DEC-0032). The Python kit and the probe accept all four; the Node kit still accepts only `launchd` and `none` (FAA-16) |
| `paths` | `data` (required), `logs[]`, optional `config`, `cache` |
| `commands` | only `doctor` and `update`, argument arrays whose first item is an absolute or `~/` path (Windows: also `C:\…`, `C:/…` or `~\…`, never a network share — DEC-0032) |
| `source.repository`, `fabricManifest` | optional |
| `installedAt`, `installedBy` | when and by which installer version |

## Well-known document — `GET /.well-known/fabric-service`

No auth; the Host/Origin guard applies; answered from memory in under 100 ms.

```json
{
  "protocol": "fabric-service/0.1",
  "service": { "id": "example-agent", "instance": "default", "name": "Example Agent",
               "version": "0.2.0", "build": { "commit": "8b80be9", "dirty": false, "builtAt": "2026-09-28T17:40:00Z" } },
  "process": { "pid": 58090, "startedAt": "2026-09-28T17:41:02Z" },
  "status": "degraded",
  "degraded": [{ "source": "llm", "reason": "No model key: drafting is paused." }],
  "summary": [{ "label": "Jobs running", "value": 2 }, { "label": "Awaiting you", "value": 1, "attention": true }],
  "surfaces": { "dashboard": { "path": "/dashboard", "login": true },
                "mcp": { "path": "/mcp", "transport": "streamable-http" },
                "events": { "path": "/fabric/v1/events" } },
  "update": { "available": null }
}
```

- `status`: `starting | ready | degraded | stopping`. No answer means `down`.
- `build` needs `commit` or `digest` (`sha256:<64 hex>`).
- `summary`: at most six tiles; `attention: true` counts toward the host's badge.
- `surfaces.events` is required; `dashboard` and `mcp` when the service has them; `usage`
  (DEC-0021) when the service reports its spend — see [the usage reference](usage.md);
  `operatorChannel.path` (DEC-0034) when the service has an operator channel — its status
  document follows the contract's `operator-channel-status.schema.json` and is token-protected
  like the events feed. The kits do not serve it yet.

## Events page — `GET /fabric/v1/events?after=<cursor>&limit=<n>`

Token required. `limit` default 50, maximum 200. Without `after`: the newest `limit`,
ascending. `cursor` is the last id returned, or the `after` you sent when the page is
empty, or `null` for an empty log. Retain at least seven days or 1000 events.

```json
{ "events": [ { "id": "4213", "at": "2026-09-28T17:55:10Z", "kind": "job.awaiting_choice",
                "level": "notice", "text": "The Q3 report draft is ready for your approval.",
                "subject": { "type": "report", "id": "q3", "label": "Q3 report" },
                "link": "/dashboard#/approvals/77", "notify": true } ],
  "cursor": "4213" }
```

`kind` is dotted lowercase; `level` is `info | notice | warning | error`; `link` is a
path on the service origin, never an absolute URL. Optional SSE stream at
`surfaces.events.stream` carrying the same objects.

## Login code — `POST /fabric/v1/login-code`

Token required → `{ "url": "/fabric/v1/login?code=<16–256 url-safe chars>", "expiresAt": "…" }`,
single use, at most 120 s, recorded as used before it is honoured. `GET` that URL →
`Set-Cookie` `HttpOnly; SameSite=Strict`, `302` to `surfaces.dashboard.path`.

## Semantic rules a host applies

| Code | Rule |
|---|---|
| `FAC-SEM-009` | well-known `service.id.instance` equals the descriptor's, else the port holder is `foreign` |
| `FAC-SEM-010` | no two descriptors claim one port or one `id.instance` |
| `FAC-SEM-011` | `ready` carries no degraded source |
| `FAC-SEM-012` | commands start with an absolute or `~/` executable |
| `FAC-SEM-025` | a usage report adds up; an all-unpriced row costs `null`, not `0` (DEC-0021) |
