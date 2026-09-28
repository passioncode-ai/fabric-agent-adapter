---
name: building-fabric-services
description: Use when building or running an agent as a long-lived local service with a dashboard on the operator's Mac — «сделай агенту дашборд», «локальный сервис агента», «дашборд должен всегда работать и не плодить копии», «где агенту хранить настройки», «подключи агента к Fabric Dashboards», "make this agent a local service", "always-on dashboard", "fabric-service protocol", "add the well-known endpoint", "migrate a service to fabric-service". Covers the fabric-service/0.1 extension: which surface to expose (MCP streamable HTTP, CLI, A2A), the token and one-time login, where state, config, logs and cache live, one copy per machine, launchd, the descriptor, the well-known document, the events feed and notifications; ships Python and Node reference kits and a live conformance probe. NOT for a one-off script or cron job, a hosted SaaS, the provider manifest itself (adapting-projects-to-fabric), or building Fabric Dashboards.
license: MIT
compatibility: Python 3.9+ or Node.js 20+ for the kits; the probe needs Python 3.9+. launchd steps are macOS-only (Linux services use lifecycle manager none until a systemd adapter exists). No network or package install; the contract checkout is optional.
metadata:
  author: passioncode-ai
  version: "0.4.0"
  contract-version: "0.1.0"
  extension: "fabric-service/0.1"
  extension-commit: "cc9ed2d13413397bb16f616f50cbb153d788fed8"
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
- a hosted SaaS — the protocol is loopback-only by design;
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

## Step 2 — the non-negotiables

1. **Loopback only.** Bind `127.0.0.1`. Refuse any `Host` other than
   `127.0.0.1:<port>`, `localhost:<port>`, `[::1]:<port>`; refuse a foreign `Origin` and
   `Sec-Fetch-Site: cross-site` — on every path, the well-known one included.
   *(A `python -m http.server` on `*:8766` served source code to the LAN here.)*
2. **One copy, locked before any side effect.** Take the exclusive lock on
   `<data>/service.lock` first — before resuming jobs, starting a scheduler, migrating
   a store or even creating a token. Held → print one sentence naming the holder's pid
   and exit **75**. Binding the port is not a lock. *(A second copy re-queued the first
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
   logs in `~/Library/Logs/<id>/`, cache in `~/Library/Caches/<id>/`; secrets in a 0600
   file. Never inside the repository or a release directory. *(Deleting a checkout left
   a plist launchd retried every 10 s, and the data went with it.)*
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

dirs = fs.service_dirs("mobile-publisher")
lock = fs.hold_single_instance(dirs["data"])        # 1. lock — exits 75 if held
token = fs.ensure_token(dirs["data"] / "service.token")  # 2. only now touch state
log = fs.JsonlEventLog(dirs["data"] / "events.jsonl")    #    (or a view over your own log)
codes = fs.LoginCodes(dirs["data"] / "auth")
resume_jobs()                                        # 3. side effects after the lock
serve("127.0.0.1", port)                             # 4. bind loopback
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

`SIGTERM` drains in-flight work within `ExitTimeOut`, then exits; interrupted work
resumes on the next start.

## Step 4 — install it

The installer, not the service, owns the plist and the descriptor. Sequence:

1. `write_descriptor(descriptor)` — refuses a port or `id.instance` another descriptor
   claims. A preview or branch copy is a second **instance**, never a second id.
2. `launchd_plist(...)` then `launchd_install(...)` — writes and lints the plist,
   `bootout` and waits for the unload, `bootstrap` with retries on the transient I/O
   error, then polls the well-known document until it answers with **this** identity.
3. Uninstall: `launchd_uninstall`, `remove_descriptor`; keep data unless the operator
   asks to purge.

Code runs from an immutable release directory; an upgrade writes a new release,
rewrites the plist and restarts. Read [the lifecycle reference](references/lifecycle.md)
for the plist fields, the release layout, log rotation and the Linux case.

## Step 5 — the dashboard and the events

The dashboard is a same-origin page: no inline script, strict CSP, polling that pauses
while the operator types or a dialog is open, one panel's failure never blanks the
others, and every error is a sentence with the next action. Read
[the dashboard reference](references/dashboard.md) before building the page.

The events feed is a **view over the log you already keep** — a jobs table, a JSONL
journal — not a second store. Each event is one sentence a person reads; set
`notify: true` only for what the operator must act on or would want to hear about
unprompted, with a `link` to the page that resolves it. Read
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
launchd pid equals answering pid) and exits 1 on any `FAIL`. A `NOT_RUN` is not a pass —
name it in the report.

Then prove the lock: start a second copy by hand against the same data directory; it
must exit 75 while the first keeps serving. Prove recovery: `kill -9` the launchd pid;
the well-known document must answer again with a new pid within about 15 seconds.

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
- `logging.basicConfig` called twice: the second call is a no-op, so a server's own
  log file stays empty. Configure logging once, in the entry point.
- Hand-made `.plist.bak` files in `~/Library/LaunchAgents` are never cleaned up; keep
  backups elsewhere.

## Completion format

Report: the `id`, port and surfaces with the Step 0 answers; files created or changed;
the probe table verbatim with every `NOT_RUN` explained; the lock and kill-9 results
with pids; and the one next command. Never call a service conformant while the probe
reports a `FAIL`.
