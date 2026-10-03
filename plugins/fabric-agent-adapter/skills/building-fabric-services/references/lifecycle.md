# Lifecycle — supervisor, install, release layout, state

This page implements the organization's
[product lifecycle contract](https://github.com/passioncode-ai/fabric-workspace/blob/main/knowledge/lifecycle.md)
(rules LC-01…LC-15) for `fabric-service/0.1` services. Where the two differ, the contract
wins and this page is the defect. The rule each section serves:

| Contract rule | Here | Kit (Python / Node) |
|---|---|---|
| LC-01 quit reaches exit within a deadline | [Shutdown](#shutdown) | `Drain` / `Drain` |
| LC-03 a job is bounded and exclusive | [one copy under launchd](#one-copy-under-launchd) | `hold_single_instance` / `holdSingleInstance` |
| LC-09 the footprint is declared | the descriptor and the plist; the service's own `AGENTS.md` names its label and port | `write_descriptor`, `launchd_plist` |
| LC-11 previous release kept, older pruned | [Install, upgrade, uninstall](#install-upgrade-uninstall) | `prune_releases` / `pruneReleases` |
| LC-12 every file is bounded | [Logs](#logs) | `RotatingLog`, `cap_stdout_log` / `RotatingLog`, `capStdoutLog` |
| LC-14 operator intent wins; uninstall is symmetric | [Install, upgrade, uninstall](#install-upgrade-uninstall) | `launchd_install`, `launchd_uninstall` (Python) |
| LC-15 builds clean up after themselves | release pruning runs inside the installer, not later | `prune_releases` / `pruneReleases` |

## Contents

- [launchd plist](#launchd-plist-generate-it-with-launchd_plist)
- [Install, upgrade, uninstall](#install-upgrade-uninstall)
- [One copy under launchd](#one-copy-under-launchd)
- [Directories](#directories)
- [Logs](#logs)
- [Shutdown](#shutdown)
- [Linux](#linux)

## launchd plist (generate it with `launchd_plist`)

| Key | Value | Why |
|---|---|---|
| `Label` | reverse-DNS, stable (`com.example.example-agent`) | the host controls the job by label |
| `ProgramArguments` | absolute interpreter + module/script inside a **release** directory | a worktree or checkout path breaks the day it moves |
| `RunAtLoad` | `true` | back at every login |
| `KeepAlive` | `true` | `{SuccessfulExit:false}` leaves a cleanly exited service down |
| `ThrottleInterval` | `10` | bounds a crash loop |
| `ExitTimeOut` | above the drain and its hard exit (15 s default; `Drain` ends by 10 s) | SIGKILL arrives after it, so it must never come first |
| `ProcessType` | `Standard` — never `Background`, and no `Nice` > 0 or `LowPriorityIO` | a host probes the service and agents call it while the Mac is busy; a background job is starved for tens of seconds under load and every host reports an outage that never happened (the probe's `lifecycle.priority` rule fails it) |
| `EnvironmentVariables` | `PATH` set explicitly; `*_FILE` paths to secrets; `FABRIC_SERVICE_SUPERVISOR=launchd` | never a secret value — the plist is world-readable in backups; the supervisor marker is how the lock knows to back off |
| `StandardOutPath`/`StandardErrorPath` | `~/Library/Logs/<id>/service.log` | one place the host tails |

## Install, upgrade, uninstall

1. Build or unpack the release into `~/.local/share/<id>/releases/<version>-<sha12>/`
   (a venv or `node_modules` inside it). Never edit a release after it is written.
2. `write_descriptor` (port and id claims are checked here).
3. `launchd_install`: write + `plutil -lint`, read `launchctl print-disabled gui/<uid>`,
   `enable` **only when no override is recorded** (a first install), `bootout` and wait
   until `launchctl print gui/<uid>/<label>` fails, `bootstrap` with up to five retries,
   then poll the well-known document until it answers with this `id.instance`.
4. Upgrade = new release, rewrite the plist with the new path, `launchd_install`
   again, then `prune_releases(releases_dir, current=<new release>)`: the running release
   and the one before it stay for rollback, older ones go (LC-11, LC-15).
5. Uninstall = `launchd_uninstall` + `remove_descriptor`. Data stays; `purge=True`
   (with `service_id`) removes data, logs and cache when the operator asks.

**The operator's intent wins (LC-14).** A host stops a service with `bootout` **and**
`disable` (off survives a login) and starts it with `enable` + `bootstrap`; restart is
`kickstart -k`. An install or upgrade never re-enables a label the operator disabled: it
rewrites the plist, so the new release is what starts once they turn it back on, and
answers `{"disabled": true, ...}` instead of the well-known document. `force_enable=True`
is for an operator who asked for the service to be switched on. The service never
implements these verbs itself — its CLI calls launchctl the same way.

**Uninstall is symmetric.** `launchd_uninstall` boots the job out and **waits** until
launchd reports it gone (it raises, removing nothing, if the job is still loaded at the
timeout), removes the plist, and resets the override to `enabled`. launchctl has no verb
that deletes an override, and a leftover `disabled` would make a later fresh install stay
off. Tests use a throwaway label or a fake `launchctl` first on `PATH` — never the
operator's real jobs.

## One copy under launchd

Started by hand, a copy that finds `service.lock` held prints one sentence naming the
holder and exits 75 at once. Under launchd that exit is a respawn every `ThrottleInterval`
(10 s), forever. So a copy whose plist carries `FABRIC_SERVICE_SUPERVISOR=launchd` backs
off in-process — 0.5 s doubling to 30 s, 300 s in all — takes over if the holder leaves,
and exits 75 only when the wait runs out: a few starts an hour instead of 360. It touches
nothing while it waits. Two installs sharing one data directory are still the defect to
remove; the back-off only stops the loop from costing the machine.

## Directories

| What | macOS | Linux |
|---|---|---|
| data + config | `~/Library/Application Support/<id>/` | `${XDG_DATA_HOME:-~/.local/share}/<id>/` |
| logs | `~/Library/Logs/<id>/` | `${XDG_STATE_HOME:-~/.local/state}/<id>/logs/` |
| cache (deletable any time) | `~/Library/Caches/<id>/` | `${XDG_CACHE_HOME:-~/.cache}/<id>/` |
| code | `~/.local/share/<id>/releases/…` | same |

A repository that versions the data itself (a registry, a plan) may hold the data; the
service's own code checkout and its releases may not. Directories 0700, secret files 0600. A store carries a schema version and the service
refuses to open a store newer than its code. The cache holds only what can be rebuilt;
anything the operator would miss belongs in data.

## Logs

One structured log (JSON lines) rotated by size — `RotatingLog(dirs["logs"] / "service.jsonl")`,
5 × 5 MB by default, files 0600 in a 0700 directory — plus the launchd stdout file, which
`cap_stdout_log` copies to `.1` and truncates at start once it passes 5 MB (launchd holds it
open for append, so it is truncated in place, never renamed). Configure logging once, in the
entry point. Never log a token, a cookie, a login code or a request body that may carry one.

## Shutdown

On `SIGTERM`: stop accepting new work, append a `service.stopping` event, drain
in-flight work, persist what was interrupted so the next start resumes it, release the
lock, exit 0 — within 10 s with work in flight (LC-01). `Drain` does the timing:

```python
drain = fs.Drain()                       # drain 8 s, hard exit 2 s later (EXIT_HARD_STOP, 70)
drain.install(lambda drained: server.shutdown(),
              on_stopping=lambda: log.append("service.stopping", "info", "Stopping."))
with drain.work():                       # raises fs.Stopping once a stop has begun -> answer 503
    handle(request)
```

Work longer than the drain is journalled before it starts and resumes on the next start;
it is never a reason to raise the deadline.

## Linux

Until a systemd adapter exists, declare `lifecycle.manager: "none"`. A `systemd --user`
unit with `Restart=always` gives the same guarantees; the host will control it once the
adapter ships. Everything else in this skill applies unchanged.
