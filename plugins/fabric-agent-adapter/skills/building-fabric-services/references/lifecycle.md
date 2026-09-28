# Lifecycle — supervisor, install, release layout, state

## launchd plist (generate it with `launchd_plist`)

| Key | Value | Why |
|---|---|---|
| `Label` | reverse-DNS, stable (`com.sshlg.mobile-publisher`) | the host controls the job by label |
| `ProgramArguments` | absolute interpreter + module/script inside a **release** directory | a worktree or checkout path breaks the day it moves |
| `RunAtLoad` | `true` | back at every login |
| `KeepAlive` | `true` | `{SuccessfulExit:false}` leaves a cleanly exited service down |
| `ThrottleInterval` | `10` | bounds a crash loop |
| `ExitTimeOut` | drain time + margin (40 s default) | SIGKILL arrives after it |
| `ProcessType` | `Background` | scheduler hint |
| `EnvironmentVariables` | `PATH` set explicitly; `*_FILE` paths to secrets | never a secret value — the plist is world-readable in backups |
| `StandardOutPath`/`StandardErrorPath` | `~/Library/Logs/<id>/service.log` | one place the host tails |

## Install, upgrade, uninstall

1. Build or unpack the release into `~/.local/share/<id>/releases/<version>-<sha12>/`
   (a venv or `node_modules` inside it). Never edit a release after it is written.
2. `write_descriptor` (port and id claims are checked here).
3. `launchd_install`: write + `plutil -lint`, `enable`, `bootout` and wait until
   `launchctl print gui/<uid>/<label>` fails, `bootstrap` with up to five retries,
   then poll the well-known document until it answers with this `id.instance`.
4. Upgrade = new release, rewrite the plist with the new path, `launchd_install`
   again. Keep the previous release for rollback; prune older ones by count.
5. Uninstall = `launchd_uninstall` + `remove_descriptor`. Data stays.

A host stops a service with `bootout` **and** `disable` (off survives a login) and
starts it with `enable` + `bootstrap`; restart is `kickstart -k`. The service never
implements these verbs itself — its CLI calls launchctl the same way.

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

One structured log (JSON lines) rotated by size (5 × 5 MB is a sane default) plus the
launchd stdout file, truncated at start. Configure logging once, in the entry point.
Never log a token, a cookie, a login code or a request body that may carry one.

## Shutdown

On `SIGTERM`: stop accepting new work, append a `service.stopping` event, drain
in-flight work until `ExitTimeOut` minus a margin, persist what was interrupted so the
next start resumes it, release the lock, exit 0.

## Linux

Until a systemd adapter exists, declare `lifecycle.manager: "none"`. A `systemd --user`
unit with `Restart=always` gives the same guarantees; the host will control it once the
adapter ships. Everything else in this skill applies unchanged.
