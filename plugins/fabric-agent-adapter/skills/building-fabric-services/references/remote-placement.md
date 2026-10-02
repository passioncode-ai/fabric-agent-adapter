# The remote placement — online agents and dashboards

Normative source: `fabric-agent-contract` `docs/specification/service.md` → *Remote placement*,
DEC-0019, at the commit this skill pins. This page is the how-to.

## Is it a remote service?

It is, when it runs outside the operator's computer and the operator wants it in Fabric beside
the local services: a hosted dashboard, an agent on a server, a bot's web console. It keeps the
same objects — well-known document, events feed, login code — at the same paths.

## The descriptor

```json
{
  "protocol": "fabric-service/0.1",
  "id": "example-agent",
  "instance": "default",
  "name": "Example Agent",
  "placement": "remote",
  "origin": "https://agent.example.com",
  "auth": { "tokenFile": "~/Library/Application Support/ai.passioncode.fabric/tokens/example-agent.default.token" },
  "lifecycle": { "manager": "none" },
  "installedAt": "2026-10-02T18:00:00Z",
  "installedBy": "fabric-service register-remote"
}
```

- `origin`: `https://` + a public DNS name + an optional port. No path, query, userinfo or IP
  literal; not `localhost`, `*.local`, `*.internal`, `*.home.arpa`, `*.lan`, `*.localdomain`.
- `lifecycle.manager` is `none`, with no `label` or `plist`. `paths` is optional.
- `commands` may carry `doctor` (a local executable); never `update`.

## On the platform

- **Token**: a random value of at least 16 characters (32 bytes recommended), set as a secret;
  the same value is written on the operator's computer by `registerRemote`. Compare in constant
  time (`tokenMatches`).
- **Session key**: 32 random bytes, a separate secret. With it, sessions survive a deploy; without
  it, every deploy signs the operator out.
- **Codes**: `MemoryCodeStore` — a restart forgets every outstanding code, so none can be replayed.
  Several processes behind one origin need a shared store (a database row with the same
  "used before honoured" write); memory works for one process.
- **Behind a router**: check the platform-set forwarded scheme; `Host` is preserved by common
  platforms and must equal the origin's host.

## What a host does and will not do

| Situation | Host |
|---|---|
| `401` on the well-known document | `down` — the service refused the token; never `foreign` |
| answer names another `id.instance` | `foreign`; the token is not sent again until the descriptor changes |
| certificate invalid or for another name | `down`, the reason names TLS |
| redirect | not followed; `down` |
| one probe missed | not an outage; the last state holds until the threshold |
| start, stop, restart, update | not offered |
| a host older than the remote placement | shows the service as invalid and never contacts it |

## Rotation

Rotate the token by setting the new value on the platform and re-running `registerRemote` on the
operator's computer with it; the old token stops working the moment the platform restarts with the
new value. Rotate the session key on the platform to sign every operator out.
