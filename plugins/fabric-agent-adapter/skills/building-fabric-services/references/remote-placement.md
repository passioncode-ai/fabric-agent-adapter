# The remote placement: online agents and dashboards

Normative source: `fabric-agent-contract` `docs/specification/service.md` → *Remote placement*,
DEC-0019, at the commit this skill pins. This page is the how-to.

## Is it a remote service?

It is, when it runs outside the operator's computer and the operator wants it in Fabric beside
the local services: a hosted dashboard, an agent on a server, a bot's web console. It keeps the
same objects (well-known document, events feed, login code) at the same paths.

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
- `installedBy` is the installer's name and version as a string (`"example-installer 1.2.0"`), or
  `{by, role?, tool}` where `by` is `person`, `node` or `organization` and `role` (`operator`, `administrator`) is a
  person's only. There is no `agent` kind: an agent that registers a service writes the string form, or
  `{by: "person", role: "operator", tool: "<agent> <version>"}` when a person asked it to. `registerRemote` defaults to
  the person form with `tool: "fabric-service register-remote"`.

**A TypeScript app (Next.js and the like):** TypeScript's `include` and typescript-eslint skip dot folders by default,
so `app/.well-known/fabric-service/route.ts` is neither type-checked nor linted until the project names it, for example
`"include": [..., "src/app/.well-known/**/*.ts"]` in `tsconfig.json`. Check it is: put a type error in the route and
watch the gate fail.

## On the platform

- **Token**: a random value of at least 16 characters (32 bytes recommended), set as a secret;
  the same value is written on the operator's computer by `registerRemote`. Compare in constant
  time (`tokenMatches`).
- **Session key**: 32 random bytes, a separate secret; rotating it signs every operator out.
- **Codes and sessions**: `MemoryCodeStore`: a restart forgets every outstanding code, so none
  can be replayed, and every session record, so a deploy signs the operator out (DEC-0039: the
  server keeps each session's last use and logout). The host signs in again on the page's `401`.
  To keep sessions across a deploy, pass a durable store (any object with `load()` and `save()`).
  Several processes behind one origin need a shared store (a database row with the same
  "used before honoured" write); memory works for one process.
- **Behind a router**: check the platform-set forwarded scheme; `Host` is preserved by common
  platforms and must equal the origin's host.

## Checking it

`check_service.py <id>` probes a remote placement over verified TLS. Behind a platform router
(Heroku, Fly, Render, a CDN) a request that names a foreign `Host` never reaches the process: the
router answers it, usually `404` or `421`. The probe counts that as the refusal it is, as long as
the body is not the well-known document. The Origin and cross-site checks name the right `Host`,
reach the service, and still need its own `403`.

Without the token the well-known route answers `401` with none of the service's data (DEC-0109). The kit's server
answers it with an empty body. An identity proxy in front of the service (Cloudflare Access, for one) may answer that
`401` with its own sign-in page: `well-known.requires-token` passes it when the page neither parses as the well-known
document nor names the service's identity values (its id, `id.instance`, build, or pid, as whole words). The probe
takes the service's own host name out first, because a sign-in page names the address it guards, and does not look for
a value shorter than four characters, because a platform's pid is often `1`.

## What a host does and will not do

| Situation | Host |
|---|---|
| `401` on the well-known document | `down`: the service refused the token; never `foreign` |
| answer names another `id.instance` | `foreign`; the token is not sent again until the descriptor changes |
| certificate invalid or for another name | `down`, the reason names TLS |
| redirect | not followed; `down` |
| one probe missed | not an outage; the last state holds until the threshold |
| start, stop, restart, update | not offered |
| a host older than the remote placement | shows the service as invalid and never contacts it |

## Rotation

Rotate the token by setting the new value on the platform and re-running `registerRemote` on the
operator's computer with it; the old token stops working the moment the platform restarts with the
new value, and so does every session begun under it when `LoginCodes` has `token=`. Rotate the
session key on the platform to sign every operator out.
