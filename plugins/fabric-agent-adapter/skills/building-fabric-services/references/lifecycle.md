# Lifecycle: supervisor, install, release layout, state

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
- [The system domain](#the-system-domain)
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
refuses a port another instance declares, and one another OS account listens on, read with the kit's
`fabric_peer_owner`, FAA-225; the recorded port per account and its claim file wait on contract DEC-0160), the service's directories, and commands as argument arrays that never
carry a credential. Only `doctor` and `update` are commands a host may run.

**Started is not ready.** Readiness is the well-known document, `GET /.well-known/fabric-service`: answered without
authentication, from memory, in under 100 ms, with `service.id` and `service.instance` equal to the descriptor's,
on a listener of this OS account (DEC-0154 HA-2: another account's listener is `foreign-user` whatever it answers; a
LaunchDaemon's root installer reads it as *The system domain* says). `well_known_of(origin)` / `wellKnownOf(origin)` read
it so a status tells HA-2's order apart: None / null when nothing answers (`down`), a `ForeignUserAnswer` whose
`reason` starts `foreign-user` or `table-restricted`, else the document; `fetch_well_known` keeps answering None for
both (FAA-259). Every loopback spelling of an origin (`127.0.0.1`, another `127/8` address, `localhost`, `[::1]`) is read
on a checked connection (FAA-257). `launchd_install` takes an injected reader, `fetch_well_known=` and
`fetch_job_well_known=`, as the Node `launchdInstall` takes `fetchWellKnown` and `fetchJobWellKnown`.
`status` is `starting`, `ready`, `degraded` or `stopping`; `degraded` is always present, and an empty list asserts
full health. A process that cannot serve does not answer, and a host derives `down`. An install or upgrade polls
that document until `service.id` matches (at most 40 s) before it calls the service started (the launchd installers;
systemd and Task Scheduler do not poll yet, FAA-253).

| Id | Rule | Here | Kit (Python / Node) |
|---|---|---|---|
| LC-01 | **Quit reaches exit within a deadline.** Every trigger (`SIGTERM`, `SIGINT`, logout, the app's own quit) ends the process: within 5 s idle, within 10 s with work in flight, then a hard exit (an idle board responder waits 3 s at most for its session's DELETE, FAA-173; one with work can take up to that hard exit). Nothing starts after quit begins | [Shutdown](#shutdown) | `Drain` / `Drain` |
| LC-02 | **Every child has an owner, a deadline and a process group.** No subprocess without a timeout; on timeout or the parent's exit the whole group goes; no orphan survives. Locks and shared resources are released in `finally` | your own code | none |
| LC-03 | **A job is bounded and exclusive.** One copy holds `service.lock`; a scheduled job has a watchdog shorter than its interval, shares its lock with every manual entry point, bounds every network call and records each run's outcome. Long work is journalled before it starts | [One copy under a supervisor](#one-copy-under-a-supervisor) | `hold_single_instance` / `holdSingleInstance` |
| LC-04 | **Credentials are silent after setup.** No background prompt; a credential read that is denied or absent is cached and backs off until a person acts | [Directories](#directories) (secret files 0600) | none |
| LC-05 | **Identity is stable across updates.** The supervisor runs a stable executable inside a release directory, never an interpreter by a versioned package-manager path; signed builds are pinned by team and identifier | [launchd plist](#launchd-plist-generate-it-with-launchd_plist-or-launchdplist-both-kits-write-the-same-bytes) | none |
| LC-09 | **The footprint is declared.** The service's `AGENTS.md` names every resident process, its supervisor label, unit or task and its port, who starts each and who stops it | the descriptor and the supervisor file | `write_descriptor`, `launchd_plist`, `systemd_unit` / `systemdUnit`, `task_xml` / `taskXml` |
| LC-11 | **An update is a lifecycle event.** An upgrade writes a new immutable release and restarts through the supervisor; the previous release is kept for rollback, older ones are pruned | [Install, upgrade, uninstall](#install-upgrade-uninstall) | `prune_releases` / `pruneReleases` |
| LC-12 | **Every file is bounded.** Logs rotate by size (5 × 5 MB), mode 0600, never in `/tmp`; temporary leftovers are swept at start | [Logs](#logs) | `RotatingLog`, `cap_stdout_log` / `RotatingLog`, `capStdoutLog` |
| LC-14 | **The operator's intent wins; uninstall is symmetric.** No install or upgrade re-enables what the operator turned off; uninstall removes what install added (supervisor file, override, descriptor), and data goes only on an explicit purge | [Install, upgrade, uninstall](#install-upgrade-uninstall), [Linux and Windows](#linux-and-windows) | `launchd_install` / `launchdInstall`, `launchd_uninstall` / `launchdUninstall`; `systemd_install` / `systemdInstall`, `task_install` / `taskInstall` and their uninstalls |
| LC-15 | **Builds clean up after themselves.** At most the current release and the one before it remain; the prune runs inside the installer, not later | [Install, upgrade, uninstall](#install-upgrade-uninstall) | `prune_releases` / `pruneReleases` |
| LC-21 | **A secret never travels in a command line.** Keys reach the process through its environment, a 0600 file or a vault, never argv; a supervisor file carries no secret | [launchd plist](#launchd-plist-generate-it-with-launchd_plist-or-launchdplist-both-kits-write-the-same-bytes), [Linux and Windows](#linux-and-windows) | the supervisor-file writers refuse a secret-shaped value |
| LC-22 | **Work survives a restart.** Work started but not finished is journalled on disk, without secrets, before it starts; the restarted service takes it back or cleans it up | [Shutdown](#shutdown) | none (the service's own journal) |

## launchd plist (generate it with `launchd_plist` or `launchdPlist`; both kits write the same bytes)

| Key | Value | Why |
|---|---|---|
| `Label` | reverse-DNS, stable (`com.example.example-agent`) | the host controls the job by label |
| `ProgramArguments` | absolute interpreter + module/script inside a **release** directory | a worktree or checkout path breaks the day it moves |
| `RunAtLoad` | `true` | back at every login (a LaunchDaemon: at every boot) |
| `KeepAlive` | `true` | `{SuccessfulExit:false}` leaves a cleanly exited service down |
| `ThrottleInterval` | `10` | bounds a crash loop |
| `ExitTimeOut` | above the drain and its hard exit (15 s default; `Drain` ends by 10 s) | SIGKILL arrives after it, so it must never come first |
| `ProcessType` | `Standard`, never `Background`, and no `Nice` > 0 or `LowPriorityIO` | a host probes the service and agents call it while the Mac is busy; a background job is starved for tens of seconds under load and every host reports an outage that never happened (the probe's `lifecycle.priority` rule fails it) |
| `EnvironmentVariables` | `PATH` set explicitly; `*_FILE` paths to secrets; `FABRIC_SERVICE_SUPERVISOR=launchd` | never a secret value: the plist is world-readable in backups; the supervisor marker is how the lock knows to back off (the probe's `lifecycle.supervisor-marker` rule fails a plist without it: a copy that finds the lock held would exit 75 at once into a respawn every `ThrottleInterval`) |
| `StandardOutPath`/`StandardErrorPath` | `~/Library/Logs/<id>/service.log` | one place the host tails |

## Install, upgrade, uninstall

1. Build or unpack the release into `~/.local/share/<id>/releases/<version>-<sha12>/`
   (a venv or `node_modules` inside it). Never edit a release after it is written.
2. `write_descriptor` (port and id claims are checked here, and a new descriptor without `source.repository` is
   refused; a rewrite of an installed one warns, FAA-198). "Port claim" here is the kit's older sense, a port no other
   descriptor declares; the pinned contract's HA-1 claim file per OS account, and a port free on the whole computer,
   are not written or checked yet (FAA-225, after the contract's CT-228).
3. `launchd_install` (Node: `await launchdInstall(...)`, the same steps): write + `plutil -lint`, read `launchctl print-disabled gui/<uid>`,
   `enable` **only when no override is recorded** (a first install), `bootout` and wait
   until `launchctl print gui/<uid>/<label>` fails, `bootstrap` with up to five retries,
   then poll the well-known document until it answers with this `id.instance` on a listener of this OS account
   (DEC-0154 HA-2: another account's listener, or one whose owner cannot be told, is `foreign-user` and never a
   successful install; the error names it). Where the socket table hides other processes (macOS 27.2 under an
   ad-hoc-signed interpreter), the installer vouches with its own job's pid from `launchctl print`, for a listen on
   exactly `127.0.0.1` alone (DEC-0155 RT-3; a wildcard bind is never vouched for since FAA-312); a listener it
   cannot prove reads `table-restricted` and the error names the way round it (FAA-267). The pid is the job's own, so a
   `ProgramArguments` wrapper that starts the server as a child (`sh -c` without `exec`, `uv run`, `npm start`) cannot
   vouch for it: on such a host start the server with `exec` or run the installer from Apple's `/usr/bin/python3`.
   A LaunchDaemon reads its answer differently: *The system domain*, below.
4. Upgrade = new release, rewrite the plist with the new path, `launchd_install`
   again, then `prune_releases(releases_dir, current=<new release>)`: the running release
   and the one before it stay for rollback, older ones go (LC-11, LC-15).
5. Uninstall = `launchd_uninstall` (Node: `await launchdUninstall(...)`) + `remove_descriptor`. Data stays; `purge=True`
   (with `service_id`) removes data, logs and cache when the operator asks; a LaunchDaemon refuses `purge` (*The system
   domain*, below).

**The operator's intent wins (LC-14).** A host stops a service with `bootout` **and**
`disable` (off survives a login) and starts it with `enable` + `bootstrap`; restart is
`kickstart -k`. An install or upgrade never re-enables a label the operator disabled: it
rewrites the plist, so the new release is what starts once they turn it back on, and
answers `{"disabled": true, ...}` instead of the well-known document. `force_enable=True`
is for an operator who asked for the service to be switched on. The service never
implements these verbs itself; its CLI calls launchctl the same way.

**Uninstall is symmetric.** `launchd_uninstall` boots the job out and **waits** until
launchd reports it gone (it raises, removing nothing, if the job is still loaded at the
timeout), removes the plist, and resets the override to `enabled`. launchctl has no verb
that deletes an override, and a leftover `disabled` would make a later fresh install stay
off. Tests use a throwaway label or a fake `launchctl` first on `PATH`, never the
operator's real jobs.

## The system domain

A `gui/<uid>` job (a LaunchAgent) runs only while its user is logged in. A headless Mac that a FileVault restart
(`fdesetup authrestart`) leaves with no GUI login, or an SSH session of a user with no GUI login, has none: `bootstrap`
answers error 125 ("Domain does not support specified action") and the installer's error says to remove the LaunchAgent
it wrote (`launchd_uninstall`) and use the system domain (FAA-278). There the job is a **LaunchDaemon**: launchd starts
it at boot, before any login, as the account its `UserName` names.

- **The plist**: `launchd_plist(..., user_name="<short name>")` (Node: `userName`) writes `UserName`, which a system
  install requires (without it the job would run as root, which every client refuses); the file goes in
  `/Library/LaunchDaemons/<label>.plist`. A plist there is in the system domain by its path (the folder's case is
  ignored); `domain="system"` (Node: `domain: 'system'`) says so for any path, and an explicit domain wins over the
  path, except that an install refuses a pair launchd would contradict: `domain="system"` with a plist in a
  `LaunchAgents` folder (launchd also loads that into `gui/<uid>` at login) and `domain="gui"` with a plist in
  `/Library/LaunchDaemons` (launchd loads it at boot as root). A domain name given as the plist path (`"system"`,
  `"gui"`) is refused, never read as a relative path (FAA-286). Everything else is a LaunchAgent's.
  `UserName` is the account whose Fabric and agents call the service: clients of another account refuse it (HA-2).
- **Who runs which step.** The release, the descriptor and the service token are written as the `UserName` (steps 1 and
  2 above, for example with `sudo -u <user> -H`), so they live in that user's home with its modes, and the plist's
  working directory and log paths name that home; only the plist, `launchd_install` and `launchd_uninstall` run as root,
  and at uninstall `remove_descriptor` runs as the `UserName` again. A service moved from a LaunchAgent is uninstalled
  as one first, so launchd never holds both: the install refuses a plist of the same label left in the `UserName`'s
  `~/Library/LaunchAgents`, and the probe's `lifecycle.one-copy` fails a label loaded in both domains (FAA-286). The descriptor's `lifecycle.plist` names the path exactly,
  `/Library/LaunchDaemons/<label>.plist`: a host that reads the folder by its spelling then knows the domain too.
- **The label is the machine's.** `/Library/LaunchDaemons` and the system domain are shared by every account of the
  Mac, so a LaunchDaemon's label is unique on the machine, not per account (put the account in it on a Mac with a
  personal and an organization account); an install refuses, before writing anything, a label another plist holds
  (the one launchd loaded the job from, or any plist of that label in the same folder) and the plist at its path when it
  names another `UserName` or another label; an uninstall refuses a label another plist holds before its `bootout`,
  which would stop that plist's job, so pass it the label the plist at its path names; in either domain an uninstall
  refuses a plist at its path that names another label, before its `bootout` (FAA-286).
- **Root installs and removes it.** `launchd_install` and `launchd_uninstall` in the system domain refuse, before writing
  anything, in a process that is not root, and name the command to run as root (`launchctl bootstrap system <plist>`,
  `launchctl bootout system/<label>`, removing the plist and `launchctl enable system/<label>`, as `launchd_uninstall`
  does). `purge` is refused: the data belongs to the `UserName`, so remove it as that user. Upgrade is the same install
  again as root, so a descriptor's `commands.update` for a LaunchDaemon runs as root, writes the new release (and any
  descriptor it rewrites) as the `UserName` as an install does, and runs only the plist and `launchd_install` as root; a
  host without root reports it as the operator's. Its commands name absolute paths: `~` would be root's home, and the
  probe's `lifecycle.plist` fails a LaunchDaemon command that starts with `~`, as it fails a LaunchDaemon plist without
  `UserName` (FAA-286). A host's verbs need root too and keep LC-14 (off stays off, across a boot as well as a login): stop is
  `bootout` + `disable system/<label>`, start is `enable` + `bootstrap system <plist>`, restart is
  `kickstart -k system/<label>`; a host or broker without root reports the job read-only.
- **Status and pid read without root**: `launchd_loaded(label, "system")` and `launchd_pid(label, "system")` ask
  `launchctl print system/<label>`, and `launchd_override(label, "system")` asks `launchctl print-disabled system`
  (Node: the `domain: 'system'` option), both of which any account may read; the probe's `lifecycle.one-copy` reads the
  domain from the descriptor's plist the same way.
- **The answer the installer waits for**: root reads the service's listener as another account's, so the installer takes
  the job's pid from `launchctl print system/<label>` and reads the token-free well-known document only on a connection
  that pid accepted, while the pid runs as the `UserName`'s uid (`ps`) and listens on exactly `127.0.0.1` (`lsof -p`);
  an install refuses a `UserName` that is not a short name, no account of the Mac or root, and an origin other than
  `http://127.0.0.1:<port>`, where nothing could prove it. Where the socket table is restricted it accepts a port that
  pid listens on at exactly `127.0.0.1`, the weaker vouch SECURITY.md names (DEC-0155 RT-3). A `ProgramArguments` wrapper that
  starts the server as a child cannot pass either check, and the refusal says so: start the server with `exec`. An
  install refused after its bootstrap leaves the job loaded, and its plist starts it again at boot; the error says so,
  and as root `launchctl bootout system/<label>` and removing the plist (or `launchd_uninstall`) take it away. A
  bootstrap that fails all five tries removes the plist the call wrote, and names one that was there before, which
  would load at the next boot (FAA-286). A plist that does not parse is refused as such before anything is written,
  never as a missing `UserName`; the Node installer refuses a binary plist and reads only the root dict's keys. For hosts and the probe the domain comes from the plist's folder alone, so a LaunchDaemon's plist must live
  in `/Library/LaunchDaemons` even when the installer is given `domain="system"`: the installer neither moves nor checks
  it. A descriptor field for the domain is the contract's CT-234, open.
- **A contract exception, accepted in principle.** At the pin, HA-2 reads a launch daemon's listener as another
  account's and nothing it answers as the service's; the pin's RT-3 (DEC-0155) vouches only for the caller's own uid. The
  root installer reads its own job's token-free well-known answer anyway, proved by launchd's pid, that pid's uid and its
  bind on exactly `127.0.0.1` (`lsof -p`, never a wildcard), and sends no credential; under a restricted socket table the
  first proof is the RT-3 weaker vouch (the pid listens on the port; that it accepted the connection is not shown). The contract owner accepted this in
  principle as DEC-0161 (RT-3 extended to launchd's system domain, the restricted-table vouch included; proposed, its
  text after its readings), so it stays a departure from the pin until the next repin (FAA-288).
  Every other client keeps HA-2 as written.
- **Hosts.** A host or broker that reads launchd only in `gui/<uid>` sees a LaunchDaemon as not loaded and must not load
  its plist into `gui/<uid>`. Fabric Dashboards from 0.8.39 takes the domain from the plist's folder and offers no verbs
  for a system job; the lifecycle broker is still asked (FAA-287). A product with its own launchd reader (a status
  page's `launchd_pid`, an installer of its own in another language) that asks only `gui/<uid>` reports a LaunchDaemon
  as not loaded: move that reader to the plist's domain before the product moves to the system domain (FAA-286).
- **Off macOS the twins differ, on purpose.** Python's `launchd_domain()` answers `gui/<uid>` on Linux (it refuses only
  Windows), so the kit's launchd tests run on Linux CI against a fake `launchctl`; Node's `launchdDomain()` refuses off
  `darwin` unless a test passes `platform: 'darwin'`. Neither runs launchd off macOS: install with
  `systemd_install` / `task_install` there (FAA-286 item 5, recorded rather than aligned).

## One copy under a supervisor

Started by hand, a copy that finds `service.lock` held prints one sentence naming the
holder (or saying the holder is unknown, when its pid cannot be read) and exits 75 at once.
Under launchd that exit is a respawn every `ThrottleInterval` (10 s), forever, and under
systemd one every `RestartSec`. So a copy its supervisor started, and that says so with the
**supervisor marker**, backs off in-process (0.5 s doubling to 30 s, 300 s in all), takes over
if the holder leaves, and exits 75 only when the wait runs out: a few starts an hour instead of
360. It touches nothing while it waits. Two installs sharing one data directory are still the
defect to remove; the back-off only stops the loop from costing the machine.

A context refusal (`fabric_context`, exit 78: no record, a revoked grant, a folder of another context) is the same
loop under `KeepAlive`, so a supervised copy waits the same back-off, holding nothing and with the lock released,
before it exits 78 (FAA-279); started by hand it exits 78 at once.

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
- Markers that disagree (the variable and the argument with different values, the argument
  twice, or a bare or empty argument beside the variable) exit 75 at once, before the lock and
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
tool}`, `source.repository` (the app's own repository; its first write is refused without it, FAA-198) and no `origin`:
it says the app is installed, never that it runs. The installer writes it; where there is none
(a macOS app dragged into Applications), the app writes it on a start when `app_descriptor_action` /
`appDescriptorAction` answers `write` (no descriptor yet, another version in `installedBy.tool`, or another path than
`lifecycle.app`), and never from an App Translocation path. Its live origin and process id go in its own liveness file,
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

One structured log (JSON lines) rotated by size (`RotatingLog(dirs["logs"] / "service.jsonl")`,
5 × 5 MB by default, files 0600 in a 0700 directory), plus the launchd stdout file, which
`cap_stdout_log` copies to `.1` and truncates at start once it passes 5 MB (launchd holds it
open for append, so it is truncated in place, never renamed). Configure logging once, in the
entry point. Never log a token, a cookie, a login code or a request body that may carry one.

## Shutdown

On `SIGTERM`: stop accepting new work, append a `service.stopping` event, drain
in-flight work, persist what was interrupted so the next start resumes it, release the
lock, exit 0, within 10 s with work in flight (LC-01). `Drain` does the timing:

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

- **Quit reaches exit through both doors.** A broker asks the platform's own quit first (on
  macOS `NSRunningApplication.terminate()`, the path Cmd+Q and the Dock take) and `SIGTERM` a few
  seconds later. Handle both and exit inside the deadline (LC-01). A desktop app
  that answers `SIGTERM` by closing its window and staying alive is stopped late or not at all.
- **A background launch stays in the background.** A broker opens the app non-activating
  (`NSWorkspace.OpenConfiguration.activates = false`); do not call `app.focus()`, `show()` on a
  focused window, or activate on `ready` when nobody asked for a window. Taking focus from the
  person is the one side effect they always notice.
- **Identity is the designated requirement.** A broker pins the app by team + bundle id, so an
  update signed by the same team keeps working and anything else is refused (LC-05). Never ship an
  ad-hoc or differently signed build to a machine that pins you.
- **Starting is not ready.** Expose readiness the broker can probe without a person (the
  well-known document for a service, a process-level answer for a plain app) and keep it honest
  while the app is still starting.

## Linux and Windows

Both kits write and install the supervisor file the contract names (DEC-0032, service.md
*Supervisor*); the two kits write byte-identical files. A supervisor file never carries a
secret: the writers refuse a credential-shaped argument, environment name or value, and any
control character (a line break would end a unit line early).

**Linux: a systemd user unit.** `systemd_unit(unit, argv, working_directory=…)` /
`systemdUnit(unit, argv, {workingDirectory})` writes `Restart=always`, `RestartSec=10`,
`TimeoutStopSec` above the drain (15 s default), `KillMode=mixed`, `WantedBy=default.target`
and `FABRIC_SERVICE_SUPERVISOR=systemd` (always, whatever the caller passed), quoting every argument (`%` → `%%`, `$` → `$$`).
`WorkingDirectory=` is written unquoted: systemd reads it as the rest of the line, so quotes would
become part of the path and the unit would be refused (`systemd-analyze verify` checks it in CI). The
descriptor says `"lifecycle": {"manager": "systemd", "unit": "<id>.<instance>.service"}`.

| Verb | Command |
|---|---|
| install, upgrade | `systemd_install` / `systemdInstall`: write `~/.config/systemd/user/<unit>`, `daemon-reload`, `enable`, `restart` (so the new unit is what runs). A unit already installed that `is-enabled` reports `disabled` stays off: the file is rewritten and nothing starts (LC-14), unless `force_enable`. With `origin` and `service_id` it then polls the well-known answer as `launchd_install` does until this account's listener answers (another account's is refused, DEC-0154 HA-2; FAA-253); Node's `systemdInstall` then returns a promise |
| stop, keep off | `systemctl --user disable --now <unit>` |
| uninstall | `systemd_uninstall` / `systemdUninstall`: `disable --now`, remove the unit, `daemon-reload` |

A user unit runs while the person is logged in; one that must run without a session needs
`loginctl enable-linger <user>`, which is the operator's decision, not the installer's.

**Windows: a per-user Scheduled Task.** `task_xml(task, argv, working_directory=…)` /
`taskXml(task, argv, {workingDirectory})` writes a task with a logon trigger for the current
user, `InteractiveToken` and `LeastPrivilege` (no administrator rights), restart on failure
every minute, no execution time limit and `MultipleInstancesPolicy` `IgnoreNew`, its settings in the
order `schtasks` exports them; the arguments are quoted the way the C runtime parses them. The Windows
CI job has the real `schtasks` create, read back and delete such a task. The descriptor says
`"lifecycle": {"manager": "task-scheduler", "task": "\\PassionCode\\<id>.<instance>"}`.

| Verb | Command |
|---|---|
| install, upgrade | `task_install` / `taskInstall`: `schtasks /Create /TN <task> /XML <file> /F` from a UTF-16 file it then removes, then `/End` (when it existed) and `/Run`. A task already installed and disabled stays off: it is recreated and disabled again (LC-14), unless `force_enable`. With `origin` and `service_id` it then polls as `launchd_install` does and returns the answer (FAA-253); Node's `taskInstall` then returns a promise |
| stop, keep off | `schtasks /End /TN <task>`, then `schtasks /Change /TN <task> /DISABLE` |
| uninstall | `task_uninstall` / `taskUninstall`: `/End`, then `/Delete /F` |

A task cannot set an environment variable, so `task_xml` / `taskXml` write the marker as an
argument, `--fabric-supervisor task-scheduler`, before any `--`: a copy the Task Scheduler starts
backs off in-process like one under launchd or systemd. `IgnoreNew` keeps the scheduler from
starting a second copy. Measured (FAA-38, [report](https://github.com/passioncode-ai/fabric-agent-adapter/blob/main/docs/reports/2026-10-13-faa-38-windows-exit75/README.md)):
`RestartOnFailure` does not restart a task whose action exits 75, so that wait is the only recovery there; a copy
that still exits 75 stays down until the next logon.

**One copy on each system.** The Python kit takes `flock` (Linux) or a locked byte
(Windows); the Node kit cannot, so it holds a name instead: an abstract unix socket on Linux,
a named pipe on Windows (`lock_name` / `lockName`), each gone with the process. The Python kit
holds the same name beside its file lock, so the two kits exclude each other everywhere, and
`check_service.py` reports the lock held when either is. The probe only looks (`/proc/net/unix`,
`WaitNamedPipeW`); it never takes the name, so it cannot make a service that is starting fail. On Linux the Node kit's
name needs Node 22 or later: Node 18 and early 20 collapse every abstract socket name into one, and later 20 pads it so
no Python copy or probe sees it, so the Node kit refuses to start there with a sentence naming Node 22 (FAA-72).

**A lock that moves under its holder (FAA-303).** `acquire` checks that the inode it locked is the file at the path
(FAA-293), which closes the race between two copies starting at once. A folder swapped under a copy that already holds
the lock (a data import replacing the data folder) is a second case. On Linux and Windows the path-keyed name above
still keeps a second copy out. On macOS the lock is `flock` (Python) or `O_EXLOCK` (Node), both on an inode, so a
second copy locks the new file and starts. There `hold_single_instance` / `holdSingleInstance` start a watch on the
held lock (`InstanceLock.watch` / `InstanceLock#watch`): every `LOCK_WATCH_SECONDS` (2 s; one `stat` and one `fstat`)
the holder compares the inode it locked with the file at the path, and once the path names another file (the imported
folder's lock, or the one a second copy made) it stops at once with 75 and one sentence naming the path
(`lost_lock_message` / `lostLockMessage`), so the copy started on the new folder runs alone. The two copies overlap for
at most one interval. The stop is abrupt on purpose (`stop_lost_holder` / `stopLostHolder`: `os._exit`,
`process.exit`): a graceful shutdown would write the old copy's state into the folder now at the path, which is not the
one it read. Under a supervisor the stopped copy is restarted and takes the new folder's lock, or waits as above while
another copy holds it. A path that is gone or cannot be
read now (a folder removed, a permission, an I/O error) is read as nothing there yet and tried again next time: a
second copy has to make a file there to start, and the watch then sees that file. `release` ends the watch. Pass
`on_lost` / `onLost` to `hold_single_instance` / `holdSingleInstance` (or call `watch` yourself on an `InstanceLock`) to
react otherwise. A path-keyed name on macOS was weighed and left: it needs a file outside the data folder, in a folder
the system never cleans and every copy of every user can write, which the standard library cannot promise; and a
watch also stops a holder that would otherwise go on writing stale state into the imported folder.

**Token files on Windows.** The privacy of `service.token` is its ACL (service.md *Windows
token files*): the kits write a protected list: the user, SYSTEM and Administrators, set before the
token's bytes go in, any entry already there dropped. On read, `windows_token_acl_problem` /
`windowsTokenAclProblem` decide over what was read: the file's flags, its owner SID and each ACE
as `{type, sid, mask}` (DEC-0057, `FAC-SEM-079`, held to the contract's
`fixtures/vectors/windows-token.json`): a reparse point, a directory, a real path outside the
profile, another owner, an allow ACE with a non-zero mask for any other SID, an ACE of another type
than allow or deny (an object or callback ACE), or anything unreadable is refused, naming the SID;
deny ACEs and an allow with an empty mask grant nothing; SIDs compare case-insensitively. The Python
kit reads the ACEs from the file's SDDL (`acl_from_sddl`); the Node kit reads them with Windows
PowerShell 5.1 (.NET's raw descriptor, no modules), converting .NET's signed mask to the unsigned
one, and writes the list with `icacls`; the path goes through the environment, never a command line.
An inherit-only ACE applies to children, not to the file, and is not read.
