# fabric-service/0.1: wire reference

Pinned to `fabric-agent-contract` commit `bfa9a67aa3c6cb808c093e7d83cd59799f1ee7d0`
(`docs/specification/service.md`, DEC-0015; the usage report DEC-0021; Windows and Linux supervision
DEC-0032 and DEC-0033; the operator channel DEC-0034 and DEC-0035; the embedded dashboard DEC-0036;
delegation and the operator session's lifetime DEC-0039; the meter's call window DEC-0041; session handoff DEC-0042;
canonical forms DEC-0043; `degraded[].setup` and `run.mcp.stdio.scope` DEC-0044; delegation sealed and trust tiers
DEC-0045; runner and model profiles DEC-0046; the estate record DEC-0055; one copy under any supervisor and its marker,
the Windows token-file reader DEC-0057; the hub key the estate certifies DEC-0060; signing credentials DEC-0063; the
estate record's 60 s skew DEC-0066; an app's own descriptor DEC-0069; the descriptor for listings DEC-0061; identifier equality
by normal form DEC-0076; the project board's directory page DEC-0077 and a replacement's transferred attempts DEC-0078; an operator's hold DEC-0079, a structured finding DEC-0080 and the owner's settlement DEC-0081; `fabric-connections/0.1` in the protocol register
DEC-0096; a schema pattern never uses a bare dot DEC-0097). The contract's schemas are normative;
this page is the working summary. Extension key:
`https://fabric.passioncode.ai/agent-contract/extensions/service/0.1`.

## Contents

- Descriptor: written by the installer
- Well-known document
- Events page
- Login code and the operator session
- Semantic rules a host applies

## Descriptor: written by the installer

Directory: macOS `~/Library/Application Support/ai.passioncode.fabric/services/`,
Linux `${XDG_DATA_HOME:-~/.local/share}/passioncode-fabric/services/`, Windows
`%LOCALAPPDATA%\passioncode-fabric\services\` (DEC-0032), or `FABRIC_SERVICES_DIR`.
File `<id>.<instance>.json`, mode 0600 (on Windows a protected ACL), atomic.

| Field | Rule |
|---|---|
| `protocol` | `"fabric-service/0.1"` |
| `id`, `instance` | `^[a-z][a-z0-9-]{1,62}$`, `^[a-z][a-z0-9-]{0,31}$` (default `default`); the pair is unique per machine |
| `name`, `summary` | ≤ 80 and ≤ 200 characters |
| `origin` | `http://127.0.0.1:<port>`; the port is a machine-wide claim. Optional for an app's descriptor only (`manager: "person"`, DEC-0069): its live origin and process id are in the app's own liveness file, and a descriptor without an origin claims no port (`FAC-SEM-010`) |
| `auth` | `tokenFile` (0600; on Windows a protected ACL: owner and every granting entry the current user, SYSTEM or Administrators: service.md *Windows token files*, DEC-0032, DEC-0033); `header` default `Authorization` with `scheme` `Bearer`; any other header carries the raw token with `scheme: "none"` |
| `lifecycle` | `manager` `launchd` (then `label` and `plist`), `systemd` (then `unit`, a `systemctl --user` unit), `task-scheduler` (then `task`, a per-user Scheduled Task), `node` (Project Observatory's node supervises it as its child, with no supervisor file, DEC-0061), `person` (an app a person installs and starts, then `app`, the installed app, DEC-0069) or `none`; `unit` and `task` are refused beside any other manager (DEC-0032), `label` and `plist` beside any but `launchd` (DEC-0057), `app` beside any but `person`. Both kits and the probe accept all six; both kits write the unit and the task (`systemd_unit`, `task_xml` / `systemdUnit`, `taskXml`). An app's descriptor says it is installed, never that it runs: the probe checks `app` is still there (`descriptor.app-installed`) and reads no well-known document; a reader that finds the app gone treats the descriptor as stale (`app_descriptor_stale` / `appDescriptorStale`), and an app that writes its own descriptor rewrites it only when `app_descriptor_action` / `appDescriptorAction` says `write` |
| `paths` | `data` (required), `logs[]`, optional `config`, `cache` |
| `commands` | only `doctor` and `update`, argument arrays whose first item is an absolute or `~/` path (Windows: also `C:\…`, `C:/…` or `~\…`, never a network share; DEC-0032) |
| `source.repository`, `fabricManifest` | optional |
| `installedAt`, `installedBy` | when, and who installed it: the installer and its version as a string, or `{by, role?, tool}` (DEC-0061): `by` `person` (with `role` `operator` or `administrator`), `node` or `organization`; `role` for a person only; `tool` the installer and its version. It names a role, never a person. An app's descriptor uses the object form with `by: "person"`. `register_remote` / `registerRemote` and the sample write the object form |
| `runner` | optional `{kind?, credentialKind}` (DEC-0061): `credentialKind` `subscription`, `key`, `platform-metered` or `none`: a kind, never a credential (`FAC-SEM-086` refuses a credential-shaped value here or in `installedBy`); a subscription names its vendor's runner (`claude-code`, `kimi-code`, `codex`) |
| `peer` | optional `{endpoint, custody, residency, maxDataClass}` (DEC-0061): the service is offered to others. `endpoint` `https://<dns-name>[:<port>][/<path>]`, never a reserved name (`FAC-SEM-085`); `custody` `organization-managed` or `personal`; `residency` 1–32 ISO 3166-1 alpha-2 codes, `EU` admitted, user-assigned codes refused; `maxDataClass` `public` < `internal` < `confidential` < `restricted`. An offer needs `runner` and never runs on a subscription. A host sends a request from anyone but the operator only when `peer_refusal` / `peerRefusal` answers null (`FAC-SEM-088`); usage rows may take `route: "platform-metered"` |

## Identifier equality (DEC-0076)

Two identifiers are the same when their normal forms are equal. `normal_identifier` / `normalIdentifier` and
`same_identifier` / `sameIdentifier` (`fabric_identifiers.py`, `fabric-identifiers.mjs`, ports of the contract's
`src/identifiers.ts`, held to its `identifiers.json`) apply RFC 3986 §6.2.2 to a URI: scheme and host lower-cased,
percent-encoding hex upper-cased, unreserved characters decoded, dot segments removed. A `urn:` follows RFC 8141 §3.1
instead: `urn` and the NID lower-cased, nothing decoded, the NSS's case kept. Any other string is its own normal form,
and a value that is not a string is compared as it is. The kits compare by it in FAC-SEM-030/032/034 (routes, bindings,
events), FAC-SEM-076 (estate grants and their revocations) and FAC-SEM-014 (a provider entry's `providerId`), and they
write the identifiers they scaffold in normal form.

## Well-known document: `GET /.well-known/fabric-service`

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
- A `degraded[]` entry may carry `setup: true` (DEC-0044): the source waits for a person to finish setting it up
  (a key not entered, a model not chosen). It is not an outage, and a watcher does not alert on it. The kits pass
  entries through unchanged.
- `configuration` (DEC-0046) MAY say which runner and model profile the service resolved and from where
  (`request`, `agent`, `binding`, `estate`); a usage receipt MAY carry the `route` (`subscription` or `key`). The kits
  build both: `fabric_profiles.configuration` and `make_usage_receipt(route=)` ([profiles](profiles.md)).
- `build` needs `commit` or `digest` (`sha256:<64 hex>`).
- `summary`: at most six tiles; `attention: true` counts toward the host's badge.
- `surfaces.events` is required; `dashboard` and `mcp` when the service has them; `usage`
  (DEC-0021) when the service reports its spend (see [the usage reference](usage.md));
  `operatorChannel.path` (DEC-0034) when the service has an operator channel; its status
  document follows the contract's `operator-channel-status.schema.json` and is token-protected
  like the events feed. The kits do not serve it yet.
- `extensions` MAY carry the embedded dashboard declaration under
  `https://fabric.passioncode.ai/agent-contract/extensions/dashboard/0.1` (`fabric-dashboard/0.1`,
  ED-9): `minWidth` 360…1280 (required), `appearance` ⊆ `scheme`, `theme`, `themes`, `kit`
  (`name@semver`), nothing else. The kits build it with `dashboard_extension()` /
  `dashboardExtension()`; see [the dashboard kit reference](dashboard-kit.md).
- `extensions` MAY say what the service uses under
  `https://fabric.passioncode.ai/agent-contract/extensions/connections/0.1` (`fabric-connections/0.1`, DEC-0096):
  `{connections: [...]}`, at most 64, each `{id, kind, target, state}` with `kind` one of `service`, `model`,
  `connector`, `store`, `channel`, `state` one of `ok`, `degraded`, `down`, `unknown`, and optionally `capability`
  (a `service` only), `label`, `purpose`, `reason`, `lastAt`. No member carries a credential, and each `id` is named
  once: a host hides a list that breaks either rule (FAC-SEM-127). A `degraded[].source` equal to an `id` is that
  connection failing. The kits build it with `connections_extension(declared, degraded, states)` /
  `connectionsExtension(declared, {degraded, states})`: `state` comes from the service's own checks (`states`, by
  `id`), else `degraded` when `degraded[]` names it, else `unknown`; a declaration a host would hide is refused with
  `ServiceError`, and `build_well_known` refuses one passed in by hand. `connections_view` / `connectionsView` read
  a peer's list as Fabric Dashboards does, and `check_service.py` reports `well-known.connections`. Build it each
  time the well-known document is built, from the same `degraded` list:

  ```python
  ext = fs.dashboard_extension()
  ext.update(connections_extension(
      [{"id": "router", "kind": "model", "target": "openai/gpt-5.1", "purpose": "drafts replies"},
       {"id": "notify", "kind": "service", "target": "communicator.default", "capability": "communicator.notify"}],
      degraded=degraded, states={"router": "ok" if model_answered else "down"}))
  ```
- `surfaces.mcp.auth`: `descriptor` (default), `own` (DEC-0024) or `delegation` (DEC-0039, DL-16):
  the MCP surface takes only the estate's delegation tokens, and the top-level
  `auth.delegation {issuer, jwks}` is then required. With `own` or `delegation` the descriptor's
  token is not an MCP credential: a host and the probe never call `/mcp` with it as a caller.
  The kits verify them with `fabric_delegation` / `fabric-delegation.mjs` ([delegation](delegation.md)).

## Events page: `GET /fabric/v1/events?after=<cursor>&limit=<n>`

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

**Machine-readable `data` (DEC-0070).** An event may carry `data {schema, value}` beside its sentence: `schema` is the
absolute URI of a payload schema the service publishes; `value` is an object of at most 32 members, each a scalar (a
string of at most 500 characters, a number, a boolean, null), a list of at most 32 scalars, or an object of at most 32
scalar members. `text` stays the event: a host that ignores `data` loses nothing, and one that does not know the schema
treats `value` as opaque. No string in `value` sits under a credential's name or has a credential's shape
(`FAC-SEM-101`); personal data is the service's own duty. `make_event` / `makeEvent` (and `JsonlEventLog.append`) take
`data=` and refuse one that breaks either rule, naming the place, never the value; `check_service.py` checks the feed it
fetches (`events.data`). A host pinned before DEC-0070 that validates events against a closed copy refuses the member.

**Protocol revisions (DEC-0067).** The well-known document may list `protocols`, the revisions the service accepts: at
most N and N−1 per protocol, consecutive in the contract's register, each `<name>/<revision>` once, 1 to 64 entries
(`FAC-SEM-099`). `build_well_known` / `buildWellKnown` take `protocols=` and check it; list them only once your hosts
are pinned at or after DEC-0067, because the document is closed for an older reader. A service that receives a document
in a revision it does not read answers `negotiate_revision` / `negotiateRevision`'s `schema-unsupported` refusal before
reading it further (HTTP 400, or an MCP `isError` result's `structuredContent`); a receiver that accepts none answers its
own fault `no-accepted-revisions`. `PROTOCOL_REVISIONS` is the contract's register; `check_service.py` reads
`well-known.protocols`.

## Login code and the operator session: `POST /fabric/v1/login-code`

Token required → `{ "url": "/fabric/v1/login?code=<16–256 url-safe chars>", "expiresAt": "…" }`,
single use, at most 120 s, recorded as used before it is honoured. `GET` that URL →
`Set-Cookie` `HttpOnly; SameSite=Strict`, `302` to `surfaces.dashboard.path`.
The session it starts ends 12 h after its last use, 7 days after sign-in, on logout and when the
descriptor token rotates (DEC-0039); a service may shorten either bound, never lengthen one. An
ended session answers `401` on the dashboard page.

## Semantic rules a host applies

| Code | Rule |
|---|---|
| `FAC-SEM-009` | well-known `service.id.instance` equals the descriptor's, else the port holder is `foreign` |
| `FAC-SEM-010` | no two descriptors claim one port or one `id.instance` |
| `FAC-SEM-011` | `ready` carries no degraded source |
| `FAC-SEM-012` | commands start with an absolute or `~/` executable |
| `FAC-SEM-025` | a usage report adds up; an all-unpriced row costs `null`, not `0` (DEC-0021); unmeasured calls are within calls and a day's are its models' sum (DEC-0091) |
