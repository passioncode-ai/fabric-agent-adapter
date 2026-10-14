# Lifecycle — supervisor, install, release layout, state

**This page is the rule** for anyone who builds, installs or runs a `fabric-service/0.1` service with this
skill. Everything you must follow is stated here or in the public Fabric Agent Contract's
[service specification, *Lifecycle*](https://github.com/passioncode-ai/fabric-agent-contract/blob/main/docs/specification/service.md#lifecycle), which this page
implements and links; where the two disagree, the specification is right and this page is the defect (report it in
this repository). Inside
PassionCode.ai the same rules make up the organization's product lifecycle contract, kept in its knowledge base. The
`LC-` ids below are that contract's, given for provenance only: nothing behind them is needed to follow this page.

## Contents

- [The rules](#the-rules)
- [launchd plist](#launchd-plist-generate-it-with-launchd_plist-or-launchdplist-both-kits-write-the-same-bytes)
- [Install, upgrade, uninstall](#install-upgrade-uninstall)
- [One copy under a supervisor](#one-copy-under-a-supervisor)
- [An app's own descriptor and the node](#an-apps-own-descriptor-and-the-node)
- [Directories](#directories)
- [Logs](#logs)
- [Shutdown](#shutdown)
- [Being managed by a host lifecycle broker](#being-managed-by-a-host-lifecycle-broker)
- [Linux and Windows](#linux-and-windows)

## The rules

**The supervisor owns the process.** A local service runs under exactly one supervisor, named in its descriptor's
`lifecycle.manager`: `launchd` (macOS), `systemd` (Linux), `task-scheduler` (Windows) or `node` (Project
Observatory's node supervising its children). An app a person starts says `person` and has no supervisor; where a host
runs a lifecycle broker, the broker is the one that quits it ([below](#being-managed-by-a-host-lifecycle-broker)).
Starting, stopping and restarting go through the supervisor and nothing else:

- **Never kill a service.** A host, an agent, an installer or the service's own CLI never starts a service process
  directly and never kills or signals one. It asks the supervisor: on macOS `bootout` + `disable` to stop and keep
  off, `enable` + `bootstrap` to start, `kickstart -k` to restart; [Linux and Windows](#linux-and-windows) have
  their own verbs; a node's child is started, stopped and restarted only through the node.
- **State comes from the supervisor**: `launchctl print`, `systemctl --user show`, the task's state and last run,
  or the node's record. Compare the supervisor's pid with the well-known `process.pid` to see a second copy.
- **Restart is the supervisor's.** A service that exits is started again, no sooner than 10 s after its last start
  (`KeepAlive` with `ThrottleInterval` 10, `Restart=always` with `RestartSec=10`, the node likewise; a scheduled task
  restarts on failure every minute). A restart onto new code shows as a new `service.build`.
- **Off stays off.** The operator's off survives a login, an upgrade and a reinstall (LC-14).

**The descriptor is the installation.** The installer writes one descriptor per instance (`<id>.<instance>.json`,
atomic, mode 0600) and the uninstaller removes it; a running service never writes its own, except an app
([below](#an-apps-own-descriptor-and-the-node)). It names the supervisor and its file (`label` and `plist`, `unit`,
or `task`; none for `node` and `person`), the `origin` `http://127.0.0.1:<port>` (a port is a claim: an installer
refuses a port another instance declares), the service's directories, and commands as argument arrays that never
carry a credential. Only `doctor` and `update` are commands a host may run.

**Started is not ready.** Readiness is the well-known document, `GET /.well-known/fabric-service`: answered without
authentication, from memory, in under 100 ms, with `service.id` and `service.instance` equal to the descriptor's.
`status` is `starting`, `ready`, `degraded` or `stopping`; `degraded` is always present, and an empty list asserts
full health. A process that cannot serve does not answer, and a host derives `down`. An install or upgrade polls
that document until `service.id` matches (at most 40 s) before it calls the service started.

| Id | Rule | Here | Kit (Python / Node) |
|---|---|---|---|
| LC-01 | **Quit reaches exit within a deadline.** Every trigger (`SIGTERM`, `SIGINT`, logout, the app's own quit) ends the process: within 5 s idle, within 10 s with work in flight, then a hard exit. Nothing starts after quit begins | [Shutdown](#shutdown) | `Drain` / `Drain` |
| LC-02 | **Every child has an owner, a deadline and a process group.** No subprocess without a timeout; on timeout or the parent's exit the whole group goes; no orphan survives. Locks and shared resources are released in `finally` | your own code | — |
| LC-03 | **A job is bounded and exclusive.** One copy holds `service.lock`; a scheduled job has a watchdog shorter than its interval, shares its lock with every manual entry point, bounds every network call and records each run's outcome. Long work is journalled before it starts | [One copy under a supervisor](#one-copy-under-a-supervisor) | `hold_single_instance` / `holdSingleInstance` |
| LC-04 | **Credentials are silent after setup.** No background prompt; a credential read that is denied or absent is cached and backs off until a person acts | [Directories](#directories) (secret files 0600) | — |
| LC-05 | **Identity is stable across updates.** The supervisor runs a stable executable inside a release directory, never an interpreter by a versioned package-manager path; signed builds are pinned by team and identifier | [launchd plist](#launchd-plist-generate-it-with-launchd_plist-or-launchdplist-both-kits-write-the-same-bytes) | — |
| LC-09 | **The footprint is declared.** The service's `AGENTS.md` names every resident process, its supervisor label, unit or task and its port, who starts each and who stops it | the descriptor and the supervisor file | `write_descriptor`, `launchd_plist`, `systemd_unit` / `systemdUnit`, `task_xml` / `taskXml` |
| LC-11 | **An update is a lifecycle event.** An upgrade writes a new immutable release and restarts through the supervisor; the previous release is kept for rollback, older ones are pruned | [Install, upgrade, uninstall](#install-upgrade-uninstall) | `prune_releases` / `pruneReleases` |
| LC-12 | **Every file is bounded.** Logs rotate by size (5 × 5 MB), mode 0600, never in `/tmp`; temporary leftovers are swept at start | [Logs](#logs) | `RotatingLog`, `cap_stdout_log` / `RotatingLog`, `capStdoutLog` |
| LC-14 | **The operator's intent wins; uninstall is symmetric.** No install or upgrade re-enables what the operator turned off; uninstall removes what install added (supervisor file, override, descriptor), and data goes only on an explicit purge | [Install, upgrade, uninstall](#install-upgrade-uninstall), [Linux and Windows](#linux-and-windows) | `launchd_install` / `launchdInstall`, `launchd_uninstall` / `launchdUninstall`; `systemd_install` / `systemdInstall`, `task_install` / `taskInstall` and their uninstalls |
| LC-15 | **Builds clean up after themselves.** At most the current release and the one before it remain; the prune runs inside the installer, not later | [Install, upgrade, uninstall](#install-upgrade-uninstall) | `prune_releases` / `pruneReleases` |
| LC-21 | **A secret never travels in a command line.** Keys reach the process through its environment, a 0600 file or a vault, never argv; a supervisor file carries no secret | [launchd plist](#launchd-plist-generate-it-with-launchd_plist-or-launchdplist-both-kits-write-the-same-bytes), [Linux and Windows](#linux-and-windows) | the supervisor-file writers refuse a secret-shaped value |
| LC-22 | **Work survives a restart.** Work started but not finished is journalled on disk, without secrets, before it starts; the restarted service takes it back or cleans it up | [Shutdown](#shutdown) | — (the service's own journal) |

## launchd plist (generate it with `launchd_plist` or `launchdPlist`; both kits write the same bytes)

| Key | Value | Why |
|---|---|---|
| `Label` | reverse-DNS, stable (`com.example.example-agent`) | the host controls the job by label |
| `ProgramArguments` | absolute interpreter + module/script inside a **release** directory | a worktree or checkout path breaks the day it moves |
| `RunAtLoad` | `true` | back at every login |
| `KeepAlive` | `true` | `{SuccessfulExit:false}` leaves a cleanly exited service down |
| `ThrottleInterval` | `10` | bounds a crash loop |
| `ExitTimeOut` | above the drain and its hard exit (15 s default; `Drain` ends by 10 s) | SIGKILL arrives after it, so it must never come first |
| `ProcessType` | `Standard` — never `Background`, and no `Nice` > 0 or `LowPriorityIO` | a host probes the service and agents call it while the Mac is busy; a background job is starved for tens of seconds under load and every host reports an outage that never happened (the probe's `lifecycle.priority` rule fails it) |
| `EnvironmentVariables` | `PATH` set explicitly; `*_FILE` paths to secrets; `FABRIC_SERVICE_SUPERVISOR=launchd` | never a secret value — the plist is world-readable in backups; the supervisor marker is how the lock knows to back off (the probe's `lifecycle.supervisor-marker` rule fails a plist without it: a copy that finds the lock held would exit 75 at once into a respawn every `ThrottleInterval`) |
| `StandardOutPath`/`StandardErrorPath` | `~/Library/Logs/<id>/service.log` | one place the host tails |

## Install, upgrade, uninstall

1. Build or unpack the release into `~/.local/share/<id>/releases/<version>-<sha12>/`
   (a venv or `node_modules` inside it). Never edit a release after it is written.
2. `write_descriptor` (port and id claims are checked here).
3. `launchd_install` (Node: `await launchdInstall(...)`, the same steps): write + `plutil -lint`, read `launchctl print-disabled gui/<uid>`,
   `enable` **only when no override is recorded** (a first install), `bootout` and wait
   until `launchctl print gui/<uid>/<label>` fails, `bootstrap` with up to five retries,
   then poll the well-known document until it answers with this `id.instance`.
4. Upgrade = new release, rewrite the plist with the new path, `launchd_install`
   again, then `prune_releases(releases_dir, current=<new release>)`: the running release
   and the one before it stay for rollback, older ones go (LC-11, LC-15).
5. Uninstall = `launchd_uninstall` (Node: `await launchdUninstall(...)`) + `remove_descriptor`. Data stays; `purge=True`
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

## One copy under a supervisor

Started by hand, a copy that finds `service.lock` held prints one sentence naming the
holder (or saying the holder is unknown, when its pid cannot be read) and exits 75 at once.
Under launchd that exit is a respawn every `ThrottleInterval` (10 s), forever, and under
systemd one every `RestartSec`. So a copy its supervisor started, and that says so with the
**supervisor marker**, backs off in-process — 0.5 s doubling to 30 s, 300 s in all — takes over
if the holder leaves, and exits 75 only when the wait runs out: a few starts an hour instead of
360. It touches nothing while it waits. Two installs sharing one data directory are still the
defect to remove; the back-off only stops the loop from costing the machine.

The marker (contract DEC-0057, CT-01) is the variable `FABRIC_SERVICE_SUPERVISOR=<manager>` or
the argument `--fabric-supervisor <manager>` (also `--fabric-supervisor=<manager>`), after the
executable and before any `--`; `<manager>` is `launchd`, `systemd`, `task-scheduler` or `node`
(Project Observatory's node, which supervises the services it starts). The writer of the
supervisor file writes it: `launchd_plist` and `systemd_unit` / `systemdUnit` set the variable,
always; `task_xml` / `taskXml` put the argument in the task's `Arguments`, because a task's action
carries no environment. Each writer refuses a marker already in the program arguments. A copy
never infers supervision from its parent process.

- `supervisor_marker(env, argv)` / `supervisorMarker({env, argv})` reads both forms and answers
  `supervised` (with the manager), `manual` or `conflict`. Only an empty variable counts as no
  marker; a bare `--fabric-supervisor` (followed by nothing, by `--` or by another `--…` flag,
  none of which it consumes) names no manager.
- Markers that disagree — the variable and the argument with different values, the argument
  twice, or a bare or empty argument beside the variable — exit 75 at once, before the lock and
  whether or not it is held, naming both markers.
- A service's own argument parser accepts the flag in both spellings and ignores it: in Python,
  `add_supervisor_argument(parser)` (argparse otherwise exits 2 on an unknown flag); the sample
  service adds it to the parser and to each command.
- The kits are held to the contract's `fixtures/vectors/service-supervisor.json`, and their
  starts against a held lock are recorded and read as `FAC-SEM-078` reads them
  (`test/*supervisors*`).

## An app's own descriptor and the node

**An app** a person installs and starts has no supervisor (contract DEC-0069). Its descriptor says
`"lifecycle": {"manager": "person", "app": "<the installed bundle or executable>"}`, `installedBy {by: "person", role,
tool}` and no `origin`: it says the app is installed, never that it runs. The installer writes it; where there is none
(a macOS app dragged into Applications), the app writes it on a start when `app_descriptor_action` /
`appDescriptorAction` answers `write` — no descriptor yet, another version in `installedBy.tool`, or another path than
`lifecycle.app` — and never from an App Translocation path. Its live origin and process id go in its own liveness file,
rewritten on every start and removed on quit; a caller that sends anything reads that file and checks the process.
`write_descriptor` claims no port for it, and a reader that finds `lifecycle.app` gone treats the descriptor as stale.

**The node** (DEC-0061): `"lifecycle": {"manager": "node"}` is a local service Project Observatory's node installed and
supervises as its child. There is no supervisor file, so `label`, `plist`, `unit` and `task` are refused beside it; the
node starts the child with the supervisor marker (`--fabric-supervisor node` or the variable) and owns Install, Off,
Code, Uninstall and state.

## Directories

| What | macOS | Linux | Windows (DEC-0032) |
|---|---|---|---|
| data + config | `~/Library/Application Support/<id>/` | `${XDG_DATA_HOME:-~/.local/share}/<id>/` | `%LOCALAPPDATA%\<id>\` |
| logs | `~/Library/Logs/<id>/` | `${XDG_STATE_HOME:-~/.local/state}/<id>/logs/` | `%LOCALAPPDATA%\<id>\Logs\` |
| cache (deletable any time) | `~/Library/Caches/<id>/` | `${XDG_CACHE_HOME:-~/.cache}/<id>/` | `%LOCALAPPDATA%\<id>\Cache\` |
| code | `~/.local/share/<id>/releases/…` | same | under `%LOCALAPPDATA%` too, never a network share |
| settings backups ([DEC-0025](settings-backups.md)) | `~/Library/Application Support/PassionCode/settings-backups/<id>/<instance>/` | `${XDG_CONFIG_HOME:-~/.config}/PassionCode/settings-backups/…` | `%APPDATA%\PassionCode\settings-backups\…` |

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

## Being managed by a host lifecycle broker

A host may run a lifecycle broker: one always-on per-user service that agents ask to start,
stop and restart products, instead of launching or killing them themselves. A product it manages
has to survive being driven from outside:

- **Quit reaches exit through both doors.** A broker asks the platform's own quit first — on
  macOS `NSRunningApplication.terminate()`, the path Cmd+Q and the Dock take — and `SIGTERM` a few
  seconds later. Handle both and exit inside the deadline (LC-01). A desktop app
  that answers `SIGTERM` by closing its window and staying alive is stopped late or not at all.
- **A background launch stays in the background.** A broker opens the app non-activating
  (`NSWorkspace.OpenConfiguration.activates = false`); do not call `app.focus()`, `show()` on a
  focused window, or activate on `ready` when nobody asked for a window. Taking focus from the
  person is the one side effect they always notice.
- **Identity is the designated requirement.** A broker pins the app by team + bundle id, so an
  update signed by the same team keeps working and anything else is refused (LC-05). Never ship an
  ad-hoc or differently signed build to a machine that pins you.
- **Starting is not ready.** Expose readiness the broker can probe without a person — the
  well-known document for a service, a process-level answer for a plain app — and keep it honest
  while the app is still starting.

## Linux and Windows

Both kits write and install the supervisor file the contract names (DEC-0032, service.md
*Supervisor*); the two kits write byte-identical files. A supervisor file never carries a
secret: the writers refuse a credential-shaped argument, environment name or value, and any
control character (a line break would end a unit line early).

**Linux — a systemd user unit.** `systemd_unit(unit, argv, working_directory=…)` /
`systemdUnit(unit, argv, {workingDirectory})` writes `Restart=always`, `RestartSec=10`,
`TimeoutStopSec` above the drain (15 s default), `KillMode=mixed`, `WantedBy=default.target`
and `FABRIC_SERVICE_SUPERVISOR=systemd` (always, whatever the caller passed), quoting every argument (`%` → `%%`, `$` → `$$`).
`WorkingDirectory=` is written unquoted: systemd reads it as the rest of the line, so quotes would
become part of the path and the unit would be refused (`systemd-analyze verify` checks it in CI). The
descriptor says `"lifecycle": {"manager": "systemd", "unit": "<id>.<instance>.service"}`.

| Verb | Command |
|---|---|
| install, upgrade | `systemd_install` / `systemdInstall`: write `~/.config/systemd/user/<unit>`, `daemon-reload`, `enable`, `restart` (so the new unit is what runs). A unit already installed that `is-enabled` reports `disabled` stays off: the file is rewritten and nothing starts (LC-14), unless `force_enable` |
| stop, keep off | `systemctl --user disable --now <unit>` |
| uninstall | `systemd_uninstall` / `systemdUninstall`: `disable --now`, remove the unit, `daemon-reload` |

A user unit runs while the person is logged in; one that must run without a session needs
`loginctl enable-linger <user>`, which is the operator's decision, not the installer's.

**Windows — a per-user Scheduled Task.** `task_xml(task, argv, working_directory=…)` /
`taskXml(task, argv, {workingDirectory})` writes a task with a logon trigger for the current
user, `InteractiveToken` and `LeastPrivilege` (no administrator rights), restart on failure
every minute, no execution time limit and `MultipleInstancesPolicy` `IgnoreNew`, its settings in the
order `schtasks` exports them; the arguments are quoted the way the C runtime parses them. The Windows
CI job has the real `schtasks` create, read back and delete such a task. The descriptor says
`"lifecycle": {"manager": "task-scheduler", "task": "\\PassionCode\\<id>.<instance>"}`.

| Verb | Command |
|---|---|
| install, upgrade | `task_install` / `taskInstall`: `schtasks /Create /TN <task> /XML <file> /F` from a UTF-16 file it then removes, then `/End` (when it existed) and `/Run`. A task already installed and disabled stays off: it is recreated and disabled again (LC-14), unless `force_enable` |
| stop, keep off | `schtasks /End /TN <task>`, then `schtasks /Change /TN <task> /DISABLE` |
| uninstall | `task_uninstall` / `taskUninstall`: `/End`, then `/Delete /F` |

A task cannot set an environment variable, so `task_xml` / `taskXml` write the marker as an
argument, `--fabric-supervisor task-scheduler`, before any `--`: a copy the Task Scheduler starts
backs off in-process like one under launchd or systemd. `IgnoreNew` keeps the scheduler from
starting a second copy. Measured (FAA-38, [report](https://github.com/passioncode-ai/fabric-agent-adapter/blob/main/docs/reports/2026-10-13-faa-38-windows-exit75/README.md)):
`RestartOnFailure` does not restart a task whose action exits 75, so that wait is the only recovery there; a copy
that still exits 75 stays down until the next logon.

**One copy on each system.** The Python kit takes `flock` (Linux) or a locked byte
(Windows); the Node kit cannot, so it holds a name instead — an abstract unix socket on Linux,
a named pipe on Windows (`lock_name` / `lockName`), each gone with the process. The Python kit
holds the same name beside its file lock, so the two kits exclude each other everywhere, and
`check_service.py` reports the lock held when either is. The probe only looks (`/proc/net/unix`,
`WaitNamedPipeW`); it never takes the name, so it cannot make a service that is starting fail.

**Token files on Windows.** The privacy of `service.token` is its ACL (service.md *Windows
token files*): the kits write a protected list — the user, SYSTEM and Administrators, set before the
token's bytes go in, any entry already there dropped. On read, `windows_token_acl_problem` /
`windowsTokenAclProblem` decide over what was read — the file's flags, its owner SID and each ACE
as `{type, sid, mask}` (DEC-0057, `FAC-SEM-079`, held to the contract's
`fixtures/vectors/windows-token.json`): a reparse point, a directory, a real path outside the
profile, another owner, an allow ACE with a non-zero mask for any other SID, an ACE of another type
than allow or deny (an object or callback ACE), or anything unreadable is refused, naming the SID;
deny ACEs and an allow with an empty mask grant nothing; SIDs compare case-insensitively. The Python
kit reads the ACEs from the file's SDDL (`acl_from_sddl`); the Node kit reads them with Windows
PowerShell 5.1 (.NET's raw descriptor, no modules), converting .NET's signed mask to the unsigned
one, and writes the list with `icacls`; the path goes through the environment, never a command line.
An inherit-only ACE applies to children, not to the file, and is not read.
