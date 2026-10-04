---
name: building-fabric-services
description: >-
  Use when handing out or opening a Fabric service dashboard, building a local agent service on a
  macOS machine, or making an ONLINE agent or dashboard (https origin, the remote placement) a
  Fabric service — «сделай агенту дашборд», «локальный сервис агента», «онлайн-дашборд в Fabric»,
  «подключи агента к Fabric Dashboards», "make this agent a local service", "make an online
  dashboard a Fabric service", "fabric-service protocol", "add the well-known endpoint". Covers
  fabric-service/0.1: surfaces, token and one-time login, state, one copy, launchd, descriptor,
  well-known document, events; online: the https guard, the token-gated well-known document, the
  __Host- cookie, registering it on the operator's computer; ships Python and Node kits, a TLS
  sample and a live probe. NOT for a one-off script or cron job, a hosted product with no agent
  behind it, the provider manifest (adapting-projects-to-fabric), or building Fabric Dashboards.
license: AGPL-3.0-only OR LicenseRef-PassionCode-Commercial
compatibility: Python 3.9+ or Node.js 20+ for the kits; the probe needs Python 3.9+. launchd steps are macOS-only (Linux services use lifecycle manager none until a systemd adapter exists). Dashboard handoff optionally uses Fabric Dashboards MCP link/host_status/open; without it, report unresolved host capability. The contract checkout is optional.
metadata:
  author: PassionCode.ai
  version: "0.7.0"
  contract-version: "0.1.0"
  extension: "fabric-service/0.1"
  extension-commit: "df55c8c54a23251342a7ee57ba95642b7eb39e61"
---

# Building Fabric services

A **service** is an agent that keeps running on the operator's computer: it holds
state, answers other agents, and shows a dashboard. This skill makes one that is
always alive, comes back after a restart, never runs twice, keeps its state through a
reinstall, and appears in Fabric Dashboards by itself — the `fabric-service/0.1`
extension of the Fabric Agent Contract (DEC-0015).

Every rule below exists because a real service on this estate broke it. Treat them as
non-negotiable; the kit implements them so you call a function instead of
re-deriving a rule.

## Boundary

Use it to create a service, to bring an existing local server under the protocol, or
to review one. Do not use it for:

- a script, a cron job or a one-shot CLI — nothing stays running, so there is nothing
  to supervise; a launchd `StartInterval` job needs no descriptor;
- a hosted product with no agent behind it. An online agent or dashboard that should appear in
  Fabric IS in scope: it is the remote placement — read [Online services](#online-services--the-remote-placement);
- the provider manifest and admission bundle — that is `adapting-projects-to-fabric`
  (a service that is also a provider does both);
- the Fabric Dashboards app itself.

## Step 0 — is it a service?

It is a service when at least one is true: other agents call it while the operator is
away; it runs jobs longer than one request; it owns a store other tools read; the
operator watches it on a page. Otherwise build a CLI and stop here.

Answer before writing code, and record the answers in the project README:

| Question | Answer shape |
|---|---|
| `id` | `^[a-z][a-z0-9-]{1,62}$`, stable forever (it names the data directory) |
| Port | one number; run the claim check below before choosing it |
| Who calls it | the named agents or people, and through which surface (Step 1) |
| What it stores | the store, where it lives (Step 2, rule 5), and what survives uninstall |
| What it tells the operator | the events worth a notification (Step 5) |

## Step 1 — choose the surfaces

| Caller | Surface | Why |
|---|---|---|
| Another agent on this machine | MCP `2026-07-28`, `streamable-http`, at `/mcp` on the service origin, token in a header | one process serves every session; stdio-per-session once left twenty stray servers on this machine |
| The operator or a script | a CLI: `<tool> service status\|start\|stop\|restart`, `<tool> dashboard`, `<tool> doctor --json` | every verb delegates to launchd and the well-known document, never to its own process table |
| A remote agent | A2A `1.0` over HTTPS, or MCP behind an authenticated gateway | loopback reachability is not authorization |
| The dashboard page | same-origin REST under `/api`, session cookie plus a custom request header | the CSRF defence all four existing dashboards use |

Read [the surfaces and auth reference](references/surfaces-and-auth.md) when wiring
MCP registration into a client config, the login flow or the CSRF header.

When other agents or Fabric call the service over MCP, it follows `fabric-interop/0.1`:
each manifest capability is the tool of its name, long work is a job with a stable id,
a question for a person is an elicitation, and every call carries one trace. Read
[the interop reference](references/interop.md) before writing an MCP tool; the helpers
are in [`scripts/fabric_interop.py`](scripts/fabric_interop.py) and
[`scripts/fabric-interop.mjs`](scripts/fabric-interop.mjs).

## Step 2 — the non-negotiables

1. **Loopback only.** Bind `127.0.0.1`. Refuse any `Host` other than
   `127.0.0.1:<port>`, `localhost:<port>`, `[::1]:<port>`; refuse a foreign `Origin` and
   `Sec-Fetch-Site: cross-site` — on every path, the well-known one included.
   *(A throwaway `python -m http.server` bound to every interface served a source tree to the local network.)*
2. **One copy, locked before any side effect.** Take the exclusive lock on
   `<data>/service.lock` first — before resuming jobs, starting a scheduler, migrating
   a store or even creating a token. Held → print one sentence naming the holder's pid
   and exit **75**. Binding the port is not a lock. Under launchd the kit backs off
   in-process first (up to 300 s), so a duplicate is a few starts an hour, not a
   `KeepAlive` respawn every 10 s. *(A second copy re-queued the first
   copy's running jobs in its startup hook, before its bind failed.)*
3. **launchd is the only supervisor.** `RunAtLoad` true, `KeepAlive` true,
   `ThrottleInterval` 10, `ExitTimeOut` above your drain time. Never start yourself
   from a CLI with `nohup` or `&`; never let a host spawn you. *(`KeepAlive
   {SuccessfulExit:false}` left a cleanly exited service down; hand-started copies
   raced launchd's.)*
4. **Build identity.** The well-known document carries the git commit or a package
   digest and the process start time. *(A service ran on stale code after an edit and
   burned budget; nothing showed which build was answering.)*
5. **State outside code.** Data and config in `~/Library/Application Support/<id>/`,
   logs in `~/Library/Logs/<id>/`, cache in `~/Library/Caches/<id>/`; the service's own
   access token in a 0600 file it generates (principle 6). **Every provider credential the
   service uses comes from Project Observatory, by name** — the plist starts the service
   with `use_secret.py serve --consumer <label> <project> <NAME>[,<NAME>] -- <command>`, which
   reads the vault only and records the consumer so a rotation names it; never a copy of a
   key in a `.env`, a config file or the plist. Never inside the service's own code checkout or a release directory; a
   repository that versions the data itself is a store and is fine — declare
   `source.repository` so the probe can tell them apart. *(Deleting a checkout left a
   plist launchd retried every 10 s, and the data went with it.)*
6. **Tokens stay in files and headers.** Mode 0600, owner-checked, never a symlink;
   never in a query string, an argument vector or a plist. The dashboard gets a
   one-time login code, never the token.
7. **`degraded` is always present.** An empty list asserts full health; `ready` with a
   non-empty list is a lie the kit corrects to `degraded`.
8. **Atomic writes.** Temporary file, fsync, rename — for the store's side files, the
   descriptor and the token.

## Step 3 — build it with the kit

Copy the kit into the service (each is one self-contained file): Python
[`scripts/fabric_service.py`](scripts/fabric_service.py), Node
[`scripts/fabric-service.mjs`](scripts/fabric-service.mjs). Both share file formats, and
their locks exclude each other. The complete worked example is
[`scripts/sample_service.py`](scripts/sample_service.py) — read it before writing a
handler.

Startup order is the part that goes wrong; keep it exactly:

```python
import fabric_service as fs

dirs = fs.service_dirs("example-agent")
lock = fs.hold_single_instance(dirs["data"])        # 1. lock — exits 75 if held (backs off first under launchd)
token = fs.ensure_token(dirs["data"] / "service.token")  # 2. only now touch state
log = fs.JsonlEventLog(dirs["data"] / "events.jsonl")    #    (or a view over your own log)
codes = fs.LoginCodes(dirs["data"] / "auth")
resume_jobs()                                        # 3. side effects after the lock
fs.LoopbackHTTPServer(("127.0.0.1", port), Handler)  # 4. bind loopback, no resolver
```

Node: `const lock = await holdSingleInstance(dirs.data)` first, then the same order.

On every request call `check_request(port, host, origin, sec_fetch_site)` and answer
403 with its sentence when it returns one. Serve the four protocol routes:

| Route | Auth | Kit |
|---|---|---|
| `GET /.well-known/fabric-service` | none, guard still applies | `build_well_known(...)` — from memory, under 100 ms |
| `GET /fabric/v1/events?after=&limit=` | service token | `events_page(fetch, after, parse_limit(limit))` |
| `POST /fabric/v1/login-code` | service token | `LoginCodes.issue()` |
| `GET /fabric/v1/login?code=` | the code | `LoginCodes.redeem(code)` → `Set-Cookie: session_cookie_header(...)`, 302 to the dashboard |

`SIGTERM` drains in-flight work, then exits — 10 s at most, inside `ExitTimeOut`
(`fs.Drain` / `new Drain()`: `with drain.work():` refuses new work once a stop began);
interrupted work resumes on the next start. Log through `RotatingLog` (5 × 5 MB, 0600)
and call `cap_stdout_log` once at start.

The MCP surface (`POST /mcp`, service token) is `fabric_interop.McpToolServer.handle`
in Python; jobs live in `fabric_interop.JobStore(dirs["data"] / "jobs")`, created after
the lock like every other piece of state. Add `"mcp": {"path": "/mcp", "transport":
"streamable-http", "capabilities": [...]}` to the well-known surfaces, and point the
descriptor's `fabricManifest` at a manifest whose service key names this
`<id>.<instance>` — `sample_service.py register` shows both.

## Step 4 — install it

The installer, not the service, owns the plist and the descriptor. Sequence:

1. `write_descriptor(descriptor)` — refuses a port or `id.instance` another descriptor
   claims. A preview or branch copy is a second **instance**, never a second id — and it is
   one more service the operator sees, probes and gets notified by. Verify a release with its
   own doctor or self-check before it replaces `default`; a temporary instance is uninstalled
   (`launchd_uninstall`, `remove_descriptor`) as soon as its check is done, not left running.
2. `launchd_plist(...)` then `launchd_install(...)` — writes and lints the plist,
   `bootout` and waits for the unload, `bootstrap` with retries on the transient I/O
   error, then polls the well-known document until it answers with **this** identity.
   A label the operator disabled stays disabled: only a first install enables.
3. Uninstall: `launchd_uninstall` (waits for the unload, removes the plist, resets the
   override; `purge=True` removes data only when the operator asks), `remove_descriptor`.
4. After an upgrade, `prune_releases(releases_dir, current=…)` keeps the running release
   and the one before it.

Code runs from an immutable release directory; an upgrade writes a new release,
rewrites the plist and restarts. Read [the lifecycle reference](references/lifecycle.md)
for the plist fields, the release layout, log rotation, behaving under a host lifecycle broker
and the Linux case.

## Step 5 — the dashboard and the events

The dashboard is a same-origin page: no inline script, strict CSP, polling that pauses
while the operator types or a dialog is open, one panel's failure never blanks the
others, and every error is a sentence with the next action. Read
[the dashboard reference](references/dashboard.md) before building the page.

The events feed is a **view over the log you already keep** — a jobs table, a JSONL
journal — not a second store. Each event is one sentence a person reads; set
`notify: true` only when the operator must decide, or something failed or degrades their
work — once per episode, with a `subject` and a `link` to the page that resolves it. A
question's kind says so (`*.awaiting_*`, `*.approval_*`, `human_step.opened`). The service
raises no banners of its own: the host is the one channel. Read
[the events reference](references/events-and-notifications.md) for mapping an existing
log, retention and notification policy.

## Step 6 — verify

Run the probe against the live service — it reads the descriptor, then checks every
rule it can reach and says which it could not:

```bash
python3 <skill-dir>/scripts/check_service.py <id>[.<instance>]
```

It reports `PASS`, `FAIL` or `NOT_RUN` per rule (descriptor, port claim, well-known
shape, identity, latency, Host/Origin/cross-site guards, loopback bind, token file,
events auth and shape, single-use login, state outside code, instance lock, plist,
launchd pid equals answering pid, and the `interop.*` rules: manifest link, capability
list, tools equal to the manifest, job tools, unknown job, trace propagation, event
trace pairs) and exits 1 on any `FAIL`. A `NOT_RUN` is not a pass —
name it in the report.

Then prove the lock: start a second copy by hand against the same data directory; it
must exit 75 while the first keeps serving. Prove recovery: `kill -9` the launchd pid;
the well-known document must answer again with a new pid within about 15 seconds.

## The repository around the service

**For a PassionCode.ai repository**, the service's repository follows the organization's
[repository standard](https://github.com/passioncode-ai/fabric-workspace/blob/main/knowledge/repository-standard.md) (`knowledge/repository-standard.md`
in the organization's knowledge base; a clone has it at `fabric-workspace/knowledge/`) from its
first commit:

- `LICENSE`, `COMMERCIAL-LICENSE.md` and `CLA.md` copied byte for byte from the knowledge base's
  `templates/`, and `AGPL-3.0-only OR LicenseRef-PassionCode-Commercial` in every manifest and
  every SKILL.md `license:`; `SECURITY.md` when the repository is public;
- a README whose first heading is the full name, with `## Quick start for a new teammate`
  (Install; Configure, key names only; MCP, the registration command and one proving tool call,
  verified with a real client in a temporary config; Develop) and `## License`;
- an `AGENTS.md` that opens with the template's *Read first* block and closes with *After work*,
  and a `CLAUDE.md` whose first line is `@AGENTS.md`.

org-index `scripts/check_format.py` reports 0 findings for it before it is called done. **An agent
someone builds for themselves is not a PassionCode.ai repository:** its licence is its owner's
choice, nothing about it is published or listed by the organization, and none of these files is
required of it — though the verified MCP quick start is still how anyone learns to drive it.

## Online services — the remote placement

An agent or a dashboard that runs online — on a platform, a server, a hosted app — becomes a
Fabric service with the same four routes and one descriptor on the operator's computer
(`placement: "remote"`, DEC-0019). Nothing about launchd, the lock or loopback applies; three
things change and the kits implement each:

| | What the online service does | Kit |
|---|---|---|
| Guard | refuse a foreign `Host`/`Origin` and `cross-site`; behind a TLS router refuse a forwarded scheme that is not `https` | `checkRemoteRequest` / `check_remote_request` |
| Well-known | only for the token; otherwise `401` with an **empty** body | `wellKnownAllowed('remote', …)` / `well_known_allowed` |
| Session | `__Host-fabric_session`, `Secure`; codes in memory, the key from a platform secret so sessions survive a deploy | `remoteSessionCookieHeader`, `new LoginCodes(null, 120, { store: new MemoryCodeStore(), key })` |

1. **Serve the four routes** in the app that already exists — not beside it. The complete worked
   example is [`scripts/sample-remote-service.mjs`](scripts/sample-remote-service.mjs): it runs
   with its own TLS or behind a platform router.
2. **Secrets live on the platform:** the service token and the session key (32 bytes) are
   platform secrets, never in the repository, a URL or an argument vector. A provider key the
   remote service needs is issued and kept in Project Observatory, pushed to the platform, and
   the movement recorded with `vault.py moved --at <provider>`, so the platform's copy is
   known rather than invisible.
3. **Register it on the operator's computer** — the installer side, run there:
   `registerRemote({ id, name, origin, token })` / `register_remote(...)` writes the token file
   (0600) and the descriptor; pass the token from a file or stdin, never in argv. Public names
   only in public artifacts: a private service is registered by a local descriptor and nowhere
   else.
4. **Verify** with the probe: `check_service.py <id>` checks TLS, the token-gated well-known
   document, the guards, events, the single-use login and the host-bound cookie; launchd, lock
   and loopback rules are `NOT_RUN` with that reason.

Read [the remote placement reference](references/remote-placement.md) for the failure
behaviour a host shows, rotation, a multi-process platform, and what a host will not do.

## Migrating an existing service

Read [the migration reference](references/migrating-a-service.md) — the order of
changes that keeps the service answering throughout, and what each existing service on
this estate needs.

## When something is missing

- **Not macOS / no launchd:** declare `lifecycle.manager: "none"`; hosts show the
  service read-only. Keep every other rule.
- **No Python:** use the Node kit; run the probe from any machine that has Python and
  can reach the port, or mark the probe `NOT_RUN` with the reason.
- **Neither kit fits the framework:** implement the four routes and the lock by hand
  against [the protocol reference](references/protocol.md); the probe is the judge.
- **No contract checkout:** the protocol reference is pinned to the extension commit
  in this skill's metadata; do not reconstruct fields from memory.
- **Fabric Dashboards not installed:** nothing changes — the service is complete
  without a host; the descriptor waits for one.

## Gotchas

- `lsof` shows `*:<port>` or `0.0.0.0` → the bind is wrong even if the Host check works.
- A health probe that only checks HTTP 200 accepts any program on the port. Compare
  `service.id` and `service.instance` — two services here once defaulted to ports
  another service already held.
- `launchctl bootstrap` right after `bootout` fails with I/O error 5 until the unload
  finishes; wait, then retry.
- Under launchd `PATH` is bare. Pin the interpreter by absolute path; set `PATH`
  explicitly in the plist; never copy the whole shell environment into it.
- A plist pointing at a worktree or a checkout breaks the day it moves. Point it at a
  release.
- `http.server.HTTPServer` asks the resolver for its FQDN between `bind()` and
  `listen()`. With a slow resolver (a macOS CI runner, a Mac offline) the port is bound
  but silent: connects time out instead of being refused. Use `fs.LoopbackHTTPServer`.
- `logging.basicConfig` called twice: the second call is a no-op, so a server's own
  log file stays empty. Configure logging once, in the entry point.
- Hand-made `.plist.bak` files in `~/Library/LaunchAgents` are never cleaned up; keep
  backups elsewhere.

## Completion format

Report: the `id`, port and surfaces with the Step 0 answers; files created or changed;
the probe table verbatim with every `NOT_RUN` explained; the lock and kill-9 results
with pids; and the one next command. Never call a service conformant while the probe
reports a `FAIL`.

## Dashboard handoff — also for consumers

When handing a registered service dashboard to a person, or writing the generated
agent's completion/notification instructions, read and apply
[dashboard links](references/dashboard-links.md): use the host's `open_link`,
check the target device and host, and run the bundled output gate before delivery.
An installed host failure never means browser fallback. This applies in Claude
Code, Codex and other providers; it needs no host-specific hook. MCP unavailable:
report the unresolved capability or use an approved project resolver; no automatic
client configuration. Python unavailable: perform the reference's manual checks
and report the executable gate NOT_RUN. Headless agents need no dashboard.
