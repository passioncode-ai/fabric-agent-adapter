# Remote sessions: over SSH, and one Project from two machines

Read this when the session runs over SSH, or when the same repository is worked on from two computers (two Macs of
one operator, a laptop and a studio). Fabric's behaviour cited here is Fabric 0.3.20 (its CHANGELOG and the on-demand
sessions spec, §3.9 *Two machines, sleep, retries and memory*); verify it against the running Fabric's own rules from
`fabric_whoami` when they disagree (FAA-284).

## Contents

- [Over SSH](#over-ssh)
- [One Project from two machines](#one-project-from-two-machines)
- [A board run sent to the other machine](#a-board-run-sent-to-the-other-machine)

## Over SSH

Fabric is a desktop app in its user's GUI login session, and the lifecycle broker that starts it runs there too
(launchd's `gui/<uid>` domain). So the first question over SSH is whether that user has a GUI login on the machine:

| Check (macOS) | Answer | Means |
|---|---|---|
| `stat -f %Su /dev/console` | your own user name | you are logged in at the screen: Fabric and the broker can run |
| `stat -f %Su /dev/console` | `root`, or another user | the login window, or someone else: no GUI session of yours |
| `launchctl print gui/$(id -u) >/dev/null 2>&1; echo $?` | not `0` (`Could not find domain`) | no GUI session of yours |

`SSH_CONNECTION` in the environment says the session came in over SSH; it says nothing about a GUI login.

**With your GUI session on that machine**, everything works as in a terminal at the screen: `hub.json` names Fabric's
loopback origin, `fabric-mcp` reaches it from the SSH session, and Step 1's broker calls work. One difference: a
consent prompt (`waiting for the operator to allow this coding agent`) is on that machine's screen, not yours. Tell the
person where it is, and call `fabric_whoami` again in a moment; never loop fast.

**With no GUI session** (a headless Mac after a FileVault restart, a machine nobody is logged in to), Fabric cannot
run there:

- No `hub.json`, or one whose `pid` is dead, is no Fabric (Step 0). Do not try to start it: no `open -a`, no
  `launchctl bootstrap gui/<uid>`, no running the binary. A broker call that fails, times out or answers that the
  target cannot start is that, not a reason to retry.
- Say once that Fabric is unreachable on this machine because its user has no GUI login, and name the human gate:
  someone logs in at the screen (or over Screen Sharing) as that user. Skip `fabric_whoami` and the board, report
  nothing to Fabric that did not reach it, and do the work that needs no Fabric.
- Leave the work where the next session finds it without the board: commit and push the branch, and write the
  repository's handoff entry with the exact next task. The board learns of it once a session with Fabric reads it.
- A service of your own that must run with no login is a LaunchDaemon, not a LaunchAgent: building-fabric-services,
  `references/lifecycle.md`, *The system domain*. Fabric itself is not one.

## One Project from two machines

Each Fabric keeps its board in its own store. Two machines each running Fabric have **two boards**: a Project, its
tasks, claims, board requests and messages on one are not on the other, even for the same repository.

- `fabric_whoami` on each machine names that machine's Project. Never carry a task id, claim id, request id or
  message id from one machine's board to the other's: it does not exist there, and a call with it is refused or,
  worse, names something else.
- Claim the work on the machine where you do it. A claim on the laptop's board does not stop a session on the studio:
  what both machines see is Git. Before starting, `git fetch` and read the other machine's pushed branches and the
  repository's handoff entries; where the repository coordinates agents with agent-sync, its leases are refs on
  `origin` (`git ls-remote origin 'refs/agent-sync/leases/*'`), which both machines see.
- Finish as on one machine, plus one rule: push before you stop, so the other machine's next session sees the branch.
  An unpushed worktree on one machine is invisible to the other.
- The session hooks spool and the watch-mail watcher are per machine and per session; nothing in them travels.
- **A shared board.** When two Fabrics read one external board (a stack named by `SUPABASE_URL`), only one machine may
  dispatch: `"dispatchOnSharedBoard": true` in that machine's Fabric `settings.json`, and on no other. Two dispatchers
  on one board would both start a run for one request; nothing on the board coordinates them yet (Fabric's CO-567).

## A board run sent to the other machine

Fabric can start a board request's run on the machine that holds the repository (the `dispatchTargets` key of its
`settings.json`, through Switchboard over SSH). Such a run has no board of the request's Fabric: its instructions carry
the request and its thread as text, and its answer goes back through the run's result, which the sending Fabric posts in
the request's thread.

- Use `com.*` for that request only when `fabric_whoami` on this machine names the request's own Project
  (`fabric-project:<id>` as the instructions give it). A Fabric on this machine keeps a board of its own, where the
  request does not exist: replying there answers nothing.
- Otherwise answer in the run's result, in the form its exit contract asks, and say what was done with its evidence.
