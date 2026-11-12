# The session hooks (COM-04, FAA-12a)

Read this when a person asks what the plugin's Fabric hooks do, where they log, how to turn them off, or what they
need from Fabric. In Claude Code they live in the plugin's `hooks/hooks.json` and run
`scripts/fabric_session.py hook <event>`. Codex and Kimi Code get one hook, the session-start preamble (or the exit contract in a session started on a board
request), which
`install-host-hooks` adds to their own config on the person's consent.

## Contents

- What each hook does
- Codex and Kimi Code
- `watch-mail`
- A session Fabric launched
- A session started on a board request
- What they never do
- Where they log, and how to turn them off
- What they need from Fabric

## What each hook does

Each hook runs `python3 -S <script>`. On Windows, Claude Code runs a hook command in Git Bash, or in PowerShell when Git
Bash is not installed ([hooks reference](https://code.claude.com/docs/en/hooks)), so `python3` must name Python 3.9 or
later there: Python from python.org names itself `python` and `py`, and the Microsoft Store alias for `python3` opens
the Store until Python is installed from it. Where `python3 --version` fails in Git Bash, every hook fails on each
session start and turn; FAA-183 tracks making the plugin find the interpreter itself.

| Event | When it acts | What it does |
|---|---|---|
| SessionStart (`startup`, `clear`; the plugin's matcher, and the script ignores `compact` and `resume` for every host) | Claude Code has an MCP server named `fabric` (local, project or user scope, read from the `.claude.json` in `CLAUDE_CONFIG_DIR` when it is set, else `~/.claude.json`, where Claude Code reads it; FAA-218, FAA-234; a local entry is the one keyed by the folder's git root, or the folder itself outside git, never an ancestor's, as Claude Code applies it, FAA-235) | Fabric running, in a project that uses Fabric (below): adds the preamble: `fabric_whoami` first; `com.status` and `com.list`, `com.read_ack` only what was read, and an announcement or question that waits on the Project answered in the same turn with its state, the result later (FAA-205), a request through its capability's slot: an `active` holder keeps it and nobody is asked, and only a holder gives its state (DEC-0152 SA-6, FAA-311); `fabric_work_list`, then `fabric_work_claim`; `fabric_work_release` at the end, and, when a piece of work or the session ends, its retro (`observatory_lesson`, insight/1 lines in `insights/` (below), or one line that there is nothing; FAA-206; a measured win also to `agents-db.contribute`, FAA-277); ask another Project only through `com.submit`. Fabric running in a folder with no such sign (a user-scope registration reaches every folder): one line pointing at `fabric_whoami`, which names the project when Fabric serves the folder anyway (FAA-60). Fabric down, in a project that uses Fabric: one line, skip `fabric_whoami` and the board, start Fabric through the lifecycle broker only if the task needs it. Fabric down anywhere else, or not registered: nothing. On a Mac, a registered command that is an absolute path to another user's copy of `fabric-mcp` (outside the home, neither this user's nor root's; Claude Code's entry, Codex's `config.toml`, Kimi Code's `mcp.json`) gets one line first, also when nothing else is said, naming it and `fabric_session.py status`, which says how to register your own; a bare name is left to `status`, which looks it up on `PATH` (FAA-232). |
| Stop (each turn) | as for SessionStart, and the running Fabric's `hub.json` lists `"session-hooks/1"` in `features` | measures the turn's facts (HEAD, files changed, lines added and removed: counts and ids only, git sharing 1.5 s) and names the other Git repositories the turn touched (FAA-140, below: only once Fabric takes them), spools them in one entry and starts a detached worker that sends `fabric_session_observe {event: "turn", head, filesChanged, linesAdded, linesRemoved, …}` as stored (with `repositories` only where that tool's input schema lists the field as an array of items with host, owner and name requiring nothing else, at most its `maxItems`, each item meeting what the schema says of its fields or left out; a turn spooled with the mark and delivered to a Fabric whose schema no longer takes them goes without them, and the log says so once per session; with a Fabric that never took them nothing is read and nothing is logged), keeps the `nudges` its answer carries (Fabric 0.3.14: each `{kind, says, task_id?, request_id?}`, shown on a turn once, at most five; it stays for `fabric_work_list` and `fabric_heartbeat`, so it may come again there: act on it once) in `nudges.json`, then reads `com.status` and keeps the unread count in the session's spool (`board.json`) |
| UserPromptSubmit | the session's spool holds a count or nudges, and the session was not started on a board request (nor runs inside such a run) | adds ONE line, `N unread on the project board: com.list; answer what waits on you in this turn: ...` (FAA-205: its state now, the result later), only when the count rose since the last line (a fall or the same count says nothing), then each nudge's `says` once, as Fabric writes it (Fabric 0.3.14 starts each with `Fabric:`; any other line gets the tag `Fabric reminder: `), one line each, at most five lines of at most 400 characters; the nudges file is taken by renaming it away before they are printed (FAA-142). It reads, renames and writes small files in the session's folder and never calls Fabric. |
| SessionEnd | as for Stop | spools the end; the worker sends `fabric_work_release {claims: "session", outcome: "let-go", …}` (with `observedAt`, the time the hook fired, where the tool's input schema names it: Fabric 0.3.9 then refuses an end from before the session enrolled), then `fabric_session_observe {event: "end", reason}`, and removes the session's spool. Reason `clear` ends nothing: `/clear` keeps the agent process and its fabric-mcp, so no claim is released and no end observed; turns already spooled still go out (since 0.42.0). Their nudges stay in the old id's folder and are not printed here; Fabric 0.3.14 only shows a nudge on a turn's answer and keeps it for `fabric_work_list` and `fabric_heartbeat`, so the new session gets it there (board `b605a636`; decision of 0.51.2, FAA-142) |
| PostToolUse (the plugin's matcher: Fabric's `fabric_work_release` and `fabric_task_release` only) | the call released a claim as done (`how`, or `outcome` when `how` is absent, done; the older tool's `outcome` succeeded) and Fabric's answer did not refuse it or release nothing (`released: false`, Fabric's refusal; `already-released`; a `claims: "session"` release with no live claim, `claims: []`; a repeat, which Fabric answers with the first release's `at`; a claim the operator released first, `released-by-operator`; a repeat after a first answer the agent never saw (lost in the client, or `unconfirmed`), and a session release answered `partial` or `unconfirmed`; in each the session-end retro still stands; a payload over 4 MiB is read as nothing and gets no line, as on every hook (below); or `isError`; an answer the hook cannot read keeps the line) | adds ONE line naming the retro in this turn (`observatory_lesson`, or the turn's answer without it; insight/1 lines in `insights/` (below); or one line that there is nothing; a measured win also to `agents-db.contribute`, FAA-277; FAA-206, Fabric's `retro-after-work`, since Fabric 0.3.16, `e1eecec0`); reads no file, calls nothing, also in a session Fabric launched |

Every hook reads at most 4 MiB of its input (`HOOK_INPUT_CAP`) as UTF-8 bytes: a byte order mark is dropped, a byte
that is no UTF-8 reads as U+FFFD, and a payload over the cap is read as nothing (FAA-210, since 0.67.0; 0.64.0 to
0.66.0 counted 1 MiB of bytes and read a BOM as nothing).

An insight/1 line is one JSON object per line with nine required fields, as the insights specification the estate's
collector reads states them (FAA-217): `schema` `"insight/1"`, `id` (`<agent>-<yyyymmdd>-<n>`), `at` (UTC), `agent`,
`kind` (`lesson`, `finding`, `metric`, `pattern`, `tool`, `market`), `title` (at most 160 characters), `body` (at most
1200 characters), `evidence` (a list of one or more: `file:line`, a command and its output, a link, a run id) and
`audience` (`internal`, `public-maybe` or `public`); optional `numbers` (each with what it measures and its source),
`tags`, `next` and `supersedes` (the id of a row it corrects; a row is never rewritten). An insight without evidence is
not written, and the collector counts a row without evidence or with an unknown kind as a problem. It never holds a
value, a person's name or a client's text. Fabric's ADR-0188 §5 names insight/1 without a shape; this is the shape
the specification's owner keeps. A session writes them in the project's `insights/` folder,
one JSONL file a month, the place Observatory named for its reader (OBS-331, board thread `f7758225`): in the
project's data folder when it has one or the repository is public, else in the repository, never inside a public one
(Observatory's own copy rule keeps `insights/` out of a public copy): a public repository with no data folder yet gets
one. The data folder is the one the project's AGENTS.md names, else `<name>-data/` beside the main checkout (not beside a
worktree), as the estate keeps them. The retro line and the preamble say so since 0.67.0.

**A resumed session and a session Fabric does not hold** (since 0.42.0, board thread `02bf19c5`). `claude --resume`
keeps the session id, so an end that was kept for a retry (its release got no answer) would be delivered to the resumed
process and release its live claims: the worker drops, with a log line, every end followed by a later turn of the same
id, and keeps the retry only while the end is the newest entry. When `fabric-mcp --rejoin-only` exits 3 (Fabric 0.3.9:
no session holds the id), the worker drops the spool, writes a `no-session` mark in the session's folder and logs it
once; for 15 minutes the hooks spool nothing for that id (an end removes the folder), then one rejoin tries again.

**The other repositories a turn touched** (FAA-140, Fabric CO-367). Only after a worker has seen the running Fabric's
`fabric_session_observe` declare `repositories` as an array of items with `host`, `owner` and `name` that require
nothing else does the Stop hook read the
session's transcript at all: the worker then leaves `observe-takes-repositories` in the hooks' folder (beside
`hooks.log`) and removes it when the schema stops saying so (after a Fabric downgrade, the turns that end before a worker next
reaches the running Fabric, about a minute (longer while rejoins fail, or after a no-session hold, whose own turns are not read), are still read; none of their names is sent); without it nothing below happens. With it, the hook reads the last 512 KB of the
transcript (the payload's `transcript_path`; earlier turns included) and uses only the entries after the last prompt
the person typed. Those lines hold message text and tool output too (file contents, command output: a secret the session displayed can be there; it stays in memory and is never spooled, logged or sent); of each entry it uses only a tool call's
name and path argument: the `file_path` of Edit, Write and MultiEdit, the `notebook_path` of NotebookEdit, and in a
Bash command `cd <absolute path>` and `git -C <path>`, split only in commands that hold `cd`, `git` or `pushd` (in any case), at most 64 K
characters of command text a turn. A relative `-C` is read against the folder the command last changed into with an absolute
`cd`, else the session's folder; after a `cd` to a relative or unknown folder (`cd sub`, `cd ~`, `cd -`) it is left
out (FAA-166). A `cd` inside `( )`, in a pipeline's stage or in a list sent to the background with `&` moves only a
subshell, so a later relative `-C` is read against the folder before it; a newline ends a command, as `;` does (a `#` comment ends at its line, a `\` continuation joins two), a
here-document's body is text, and `pushd` moves like `cd` (an unbalanced quote in a here-document's body, or a quoted
lone `&`, pipe sign, `(` or `)`, can make the hook skip that command or read it wrongly, FAA-187). On Windows (FAA-175) Git Bash's paths
are read as drive paths: `/c/...`, `/cygdrive/c/...`, `C:/...` and a quoted `C:\...` (Git Bash reads an unquoted
backslash as an escape, so `cd C:\work` goes to `C:work`, which is left out); another `/...` (Git's own root, which only
`cygpath` resolves) is left out. A Cygwin or MSYS2 Python reads its own POSIX paths (FAA-177). These are the repositories the turn
*touched*: a `cd` or a read-only `git -C <path> log` names one as much as an edit does. A subagent's entries are not
read, so a repository only a subagent touched is not named. Each
path is resolved with one `git rev-parse --show-toplevel` and its repository's `origin` with one `git config --get
remote.origin.url`, every call inside the same 1.5 s as the turn's facts (the facts first, and spooled before the walk starts, so a hook ended during it still leaves them; the folder checks run beside the hook, which waits for them no longer than the budget, then writes the entry again with the repositories it found, FAA-161); a path outside every
checkout costs no git call, and when the budget runs out the hook spools what it found. Each repository is named
`{host, owner, name}` from its `origin` (https, `ssh://`, `git@host:owner/name`; credentials, a port and `.git`
dropped; a nested group stays in `owner`, and on a self-hosted ssh remote `owner` is the folder path on that server
before the repository's name, which may hold a user name). The repository of the session's folder when the turn ends (the Stop payload's `cwd`; any checkout of it: a worktree, a clone), a repository whose `origin`
is missing or does not parse, and a second checkout of one repository are not named; at most 10. No local path leaves the hook; a
missing or unreadable transcript names none and is no error. The list can miss a repository (FAA-174): in a turn whose
entries pass 512 KB, an edit that large tool output pushed out of the tail is not named. Claude Code keeps the Bash folder between calls while it
stays inside the session's folder, so each Bash call is read against the folder the one before it left the shell in
(FAA-184): an absolute `cd` inside the session's folder carries to the next call, and a folder outside it, or one not
known here (a relative `cd`, `popd`, a call past the cap), is the session's folder again. A `cd` into a folder Claude
Code allows outside the session's (an added working directory) is read as reset, so a relative `git -C` after it can
still name a wrong repository. Turn the read off (FAA-160)
with `FABRIC_SESSION_NO_REPOSITORIES=1` in the environment, or a file named `no-repositories` in the hooks' folder:
the turn's facts are still sent, without `repositories` (any value of the variable but empty or `0` turns it off; the
file sits in a cache folder a cleaner may empty, so the variable, set in Claude Code's settings `env`, is the lasting form:
it reached hooks declared in settings and in a plugin's `hooks.json` in runs on macOS, recorded in the owning
repository's `docs/evidence/runs/2026-10-27-settings-env-reaches-hooks.md`; Windows is FAA-183's run);
`fabric_session.py status` says whether the read is on, off, waiting for Fabric (not running, without `session-hooks/1`,
or not taking the repositories yet) or not done because `fabric` is not registered for the folder, as the environment
of the shell it runs in has it; its "Session hooks" line describes Fabric alone.

**`status`** (FAA-233, FAA-239) judges each registration it reads (Claude Code's, Codex's `[mcp_servers.fabric]` `command`, Kimi Code's `mcpServers.fabric`) for another user's copy and names the re-registration for that host. With `PASSIONCODE_APPLICATIONS` set, it names a value that is not an absolute path (read as unset, as the launcher reads it), a registration of a copy outside that folder (which the launcher does not update), the user's own copy in `~/Applications` it no longer takes, and a folder this user cannot enter, where it advises `~/Applications` with the variable unset. Native bridges (Hermes, OpenCode, OpenClaw, Pi) pass the hooks a boolean registration, not a command, so neither the session start nor `status` judges their copy.

**A project that uses Fabric** (`project_uses_fabric`), cheapest sign first: `fabric` registered at local or project
scope for the folder (user scope is every folder's, so it says nothing about this one); a `fabric-agent.json`,
`fabric-contract.lock.json` or `fabric.package.json` file from the folder up to its checkout's root (the folder alone
outside a checkout; never above it); or a service descriptor whose `source.repository` is the checkout's
`remote.origin.url`. The machine's service descriptors are no longer counted into the session: the host's own
instructions say how to read Fabric services (since 0.38.0).

Without `session-hooks/1`, Stop and SessionEnd read `hub.json`, return, and spool nothing (they only remove stale
session folders, below), so UserPromptSubmit has nothing to show; `fabric_session.py status` says "Session hooks: inert". That is every Fabric before the release
that ships the dependencies below. A board that cannot be read (`unavailable`, a refusal) leaves no count, never a
zero; a `degraded` board that still gives the count is read.

## Codex and Kimi Code

`fabric_session.py hook session-start --host codex|kimi` emits structured SessionStart JSON for Codex and plain text
for Kimi when the host has `fabric`
registered (`[mcp_servers.fabric]` in `$CODEX_HOME/config.toml`; `mcpServers.fabric` in `~/.kimi-code/mcp.json`),
under the same rules. Nothing else: no turn observation and no unread line, because a rejoin needs the runtime
session id Fabric keeps with the enrollment, which only Claude Code supplies today (D1).

`install-host-hooks --host codex|kimi` is a dry run by default. It prints the file, its sha256, and the one entry it
would add (never a value already in the file) and the `--apply --expect-sha256 <digest>` command. With `--apply` it
backs the file up (`<file>.<UTC stamp>.bak`, never overwriting an earlier backup), keeps the file's mode, refuses a
file whose shape is not `{"hooks": {"<Event>": [{"hooks": [...]}]}}` (Codex) or an array of `[[hooks]]` tables
(Kimi Code, read back with `tomllib`: Python 3.11+), and refuses one that changed since the dry run. It refuses a
`--script` that is not an existing file. Our own entry, found by what it runs (for Kimi Code each `[[hooks]]` table is
read on its own, so a hand-touched one is still found), is rewritten in place to the new script (`updated`) rather
than added a second time. `--remove` takes the entry out again, stale or not, and needs no script. Codex may ask the person to trust a new hook (`/hooks`) before it runs. Codex keys that trust by event, group and index, so
`--remove` names the SessionStart groups after the removed one that it moves, which Codex asks the person to approve
again. The hook runs the
`fabric_session.py` of the skills install (`~/.agents/skills/working-with-fabric/`) when there is one, else this
script's own path; a plugin cache path changes with each update, so pass `--script <a stable path>` there.

Native Hermes, OpenCode, OpenClaw and Pi bridges are described in [native host hooks](native-host-hooks.md).
They consume the same context through their own APIs. They never use the Claude-only rejoin/turn lifecycle.

## `watch-mail`

`fabric_session.py watch-mail [--interval 60]` is for an idle Claude Code session waiting on the board; the agent
starts it under a background watcher. It rejoins the session (`CLAUDE_CODE_SESSION_ID`, or `--session-id`) through
`fabric-mcp --rejoin-only` for each look, prints one line each time the unread count rises (and the nudges of turns its
look delivered), and waits `interval`
± 20 % between looks (after the jitter never under 10 s and never over 15 minutes). It shares the session's
once-a-minute rejoin with the Stop worker: a look within a minute of the last rejoin (the worker's `rejoined` mark or
its own) waits instead, and its own rejoin renews that mark when the session's folder exists. Because its looks keep
that mark fresh, a Stop-hook turn usually waits in the spool while it runs: a look that finds spooled turns delivers
them through its own rejoin, as the worker would, and reads the board's count the worker writes (FAA-89). The nudges of
turns its own look delivered it prints, each once, the same way (`nudges.watch.json`), except when that look also
delivered the session's end, which removes the folder. More than five pending, or a file that cannot be written, drops
the rest from this output (Fabric keeps them for `fabric_work_list`): the log names how many (`dropped=`, `lost=`), never
what they say; those the Stop worker delivered wait for the next prompt (FAA-142). While Fabric is down or
the board unreadable it says so once and backs off, doubling to at most 15 minutes. It exits on its stdin's end (when started with a pipe), SIGTERM, SIGINT or SIGHUP,
or when its parent is gone. It refuses to start in a session Fabric launched, in a session started on a board request, and without a `fabric`
registration.

## A session Fabric launched

Every hook, and `watch-mail`, is silent there: Fabric briefed that session itself. Three exceptions: a session
started on a board request gets its exit contract and, at its prompt, the prompt hook's verdict on the dispatch line
(the run, none, or nested; below), and the PostToolUse retro line after a release of finished
work is said there too, since Fabric gives no such line at that moment (FAA-206). The signals, cheapest first;
only variable names are looked at, never a value (two of them carry the session's credential):

1. `FABRIC_LAUNCHED_SESSION=1`: the marker Fabric is asked to set (D6). `0` or empty is not the marker.
2. What Fabric already gives (`apps/desktop/src/main/sessionBundle.ts`): `FABRIC_ACP_SESSION` (ACP sessions),
   `FABRIC_BRIDGE_URL` (the stdio bridge), `KILO_CONFIG_CONTENT` (Kilo), and `CODEX_HOME` inside
   `<Fabric's folder>/sessions/` (Codex).
3. Claude Code launched by Fabric has no variable yet: its command line holds `--mcp-config
   <Fabric's folder>/sessions/<id>/mcp.json`. SessionStart, and Stop once per session, look for that in a few
   ancestor processes (`ps`, bounded to 0.5 s each); only the match is used, nothing is logged. A match is kept as
   an empty `launched` file in the session's folder, so the walk runs once and nothing is spooled after it. A `ps`
   that fails or runs out of time is "unknown", never "not launched": that hook spools nothing (so no worker can
   release a launched session's claims) and the next one looks again.

## A session started on a board request

A session Fabric started to answer one board request (FAA-201) carries `FABRIC_DISPATCH_WORKFLOW`,
`FABRIC_DISPATCH_HANDOFF` and `FABRIC_DISPATCH_REQUEST`, and its prompt's first line `fabric-dispatch/1 workflow=...
handoff=... request=...` names the same three: only that makes it the run (Fabric's spec 3.5), since a reader or a
subshell inherits the environment. SessionStart, which sees no prompt yet, prints the exit contract on that condition
in place of the preamble, whatever the folder shows, without reading Fabric's files, and also in a session Fabric
launched: there the contract is the one thing it prints; an environment without all three gets one line saying no
session under it is a run. The prompt hook, which sees the line, says the session is the run, or, for a line that
disagrees, that it is none and stops after saying so in the request's thread; a line with no workflow in the
environment is quoted text. The first session whose line names the dispatch holds it (a record in `dispatch/`, below;
a `/clear` in its process keeps it): another gets one line instead, telling it not to accept, claim, complete or
close. The prompt hook prints no unread line and no nudges there, nor in a session inside the run, and leaves the nudges file where it is. The turn and end hooks work as in any other session (silent in a launched one); their worker still reads the count and keeps the nudges, which nothing prints. What the session then does:
[on-demand session](on-demand-session.md).

## What they never do

- **Block or slow the session.** Each hook has a 5 s ceiling in `hooks.json`; the script reads a few small files and
  returns in about the time Python takes to start (a few hundred milliseconds under load, [raw](https://github.com/passioncode-ai/fabric-agent-adapter/blob/main/docs/reports/2026-11-05-faa-206-retro/raw/hook-timing.log)), plus the turn's git facts in Stop and SessionEnd and, in Stop once Fabric takes them, the transcript's
  tail and the other repositories' names (the git calls share at most 1.5 s; the tail read is at most 512 KB). Every call to Fabric happens in a detached worker with a 10 s deadline; at its end the worker closes
  `fabric-mcp`'s stdin and then ends its whole process group, so a wrapper (`npx`, a shell script,
  `fabric-mcp.cmd`) cannot keep it waiting. Every hook exits 0, on every path, once `python3` starts (above; FAA-183).
- **Keep a secret.** The hooks never open Fabric's door token or an enrollment credential; `fabric-mcp` holds
  those. Nothing secret is in argv (the worker's argv is the script and a spool folder) or in the log. Once Fabric
  takes repositories, an `origin` URL that embeds a credential (`<https>://user:token@host/...`) is read by
  `git config` with it; the Stop hook drops the credential in memory before anything is spooled, logged or sent.
- **Send content, or use more than it reads for.** A turn is the HEAD commit, the number of files that differ from it
  (untracked included) and the lines added and removed against it, and, once Fabric takes them, the other repositories
  it touched by their `origin` name (`{host, owner, name}`), and its branch (below); no path, commit message or diff
  text. The branch (FAA-152, contract DEC-0140 PR-3; Fabric 0.3.16, CO-459) is `git symbolic-ref --short -q HEAD`,
  one more git call inside the same 1.5 s, null on a detached head, and goes with a turn (never the end) only where
  `fabric_session_observe` declares `branch`, null only where its schema allows it and a name outside its pattern
  not at all; Fabric shows it on this machine's screens and never stores or shares it. Turn it off with
  `FABRIC_SESSION_NO_BRANCH=1` (any value but empty or `0`): no branch is read or sent. The role PR-3 also defines
  is not sent: Fabric's enrollment takes no role yet. The
  transcript's tail is read, message text and tool output with it, and only tool names and path arguments are used; a sent turn's log
  line counts its repositories, never names them. The board is read
  as a count (`com.status`), never a message. Git runs with `--no-optional-locks`.
- **Start a second Fabric session.** A `fabric-mcp` started on its own would enroll a new session, and Fabric ends a
  binding's oldest live session past eight (ADR-0134 amendment 2): the agent's own. The worker and `watch-mail` run
  `fabric-mcp --rejoin-only --runtime-session-id <id>`, and only when Fabric advertises `session-hooks/1`.
- **Rejoin more than once a minute.** Every rejoin spends the agent's Fabric request budget, which every session of
  the machine shares. A turn within 60 s of the session's last successful rejoin (the worker marks it as `rejoined`
  in the session's folder) is spooled and waits for the next worker; the end of a session always starts one (FAA-53).
- **Retry in a loop.** A refused call, or one answered with a JSON-RPC error, is logged by its error code and its
  entry dropped; an entry that cannot be read is logged as `outcome=dropped` and dropped. The entries after it, the
  end's release and the end observation still go out. An answer that never came is logged as `outcome=unknown` and
  leaves the spool to the next worker. The calls carry an `idempotencyKey`, so a repeat is the same event.

## Where they log, and how to turn them off

One line per event that did something, never content: `~/Library/Caches/ai.passioncode.fabric-agent-adapter/hooks.log`
(macOS), `$XDG_CACHE_HOME/fabric-agent-adapter/hooks.log` (Linux, default `~/.cache`),
`%LOCALAPPDATA%\fabric-agent-adapter\hooks.log` (Windows). Mode 0600, rotated at 1 MB to `hooks.log.1`. The
per-session spool is `sessions/<session id>/` beside it (turn entries capped at 50, each holding the session's folder when
the turn ended (the Stop payload's `cwd`) and, when the turn touched another repository (only once Fabric takes them), `repositories` as `{host, owner, name}`; `board.json`, `board.shown`, `repositories.degraded` (the once-a-session note that repositories were left out: the schema no longer takes them, or refused every item), and the nudges not yet printed: `nudges.json` for the prompt
hook, `nudges.watch.json` for `watch-mail`, each taken by renaming it away; a
folder untouched for 7 days, whose worker failed or whose session ended without SessionEnd, is removed by the next
Stop or SessionEnd hook, even while the hooks are inert; an end entry whose release or observation got no answer stays
for the next worker, and the folder goes only once the end is delivered; a stale worker lock is taken by renaming it, never by a
check and a delete),
removed at the session's end.
`dispatch/<key>.json` beside it records which session holds a dispatch (FAA-201: the first session id for its
`FABRIC_DISPATCH_ID` when set, else for the workflow, the handoff and `SWITCHBOARD_LAUNCH_ID`, with the agent's process
id, 0600; a `/clear` in that process moves it to the new session id and keeps
`cleared_from`, the id the first clear replaced (or, when that was unknown, the session the first clear started), for a
replayed accept; on Windows, where each hook's parent is a new Git Bash, a `/clear` never moves it and holds nothing, and the cleared session is told it is nested; on a host whose shell does not exec the hook command (dash before 0.5.11) the holder's own `/clear` is told it is nested and stays a helper, unmeasured; a `/clear` with no record yet is told the conditional contract; the prompt hook writes it, on the first prompt whose line names the dispatch; a missing or unreadable record holds nothing on a `/clear`), a hook given no session id (a native bridge) writes none and is told the conditional contract; removed after 7 days by the Stop and SessionEnd hooks and by the next session start on a board request (Codex and Kimi have only that hook).

Turn only the transcript read off with `FABRIC_SESSION_NO_REPOSITORIES=1` or a `no-repositories` file in the folder
above (FAA-160). That folder is a cache: a cache cleaner may remove the file, and the read is on again; the variable,
set where Claude Code starts, does not depend on it. Turn them off with Claude Code's own switch (`/hooks`, or `"disableAllHooks": true` in settings), or remove the
`fabric` MCP server; the preamble and the Fabric calls stop without it. Uninstalling the plugin removes them; delete
the cache folder above to leave nothing behind. Codex and Kimi Code: `install-host-hooks --host <host> --remove`.

## What they need from Fabric

Each is a Fabric dependency; until D1–D5 ship, Stop, SessionEnd and UserPromptSubmit stay inert. D6 only makes the
launched-session check exact.

| # | Need | Shape |
|---|---|---|
| D1 | `fabric-mcp` enrolls with the runtime session id | for `--runner claude-code`, `runtimeSessionId` = env `CLAUDE_CODE_SESSION_ID` in `fabric.session.enroll {cwd, runtimeSessionId}` (Claude Code 2.1.296 gives MCP stdio servers and Bash commands that variable, equal to the hooks' `session_id`) |
| D2 | rejoin only | `fabric-mcp --runner claude-code --rejoin-only --runtime-session-id <id>` attaches to that runtime session's live enrolled session; never asks, never mints; otherwise only `fabric_whoami`, as not enrolled; Fabric 0.3.9 exits 3 at once when no session holds the id |
| D3 | the flag | `hub.json` `"features": ["session-hooks/1"]` once D1, D2, D4 and D5 ship |
| D4 | `fabric_session_observe` | `{event: "turn" or "end", runtime: "claude-code", runtimeSessionId, observedAt, head, filesChanged, linesAdded, linesRemoved, reason (end only), repositories (turn only, optional), branch (turn only, optional; Fabric 0.3.16), idempotencyKey}` → `session.turn.observed@1`, `session.ended@1`; `repositories` (FAA-140, proposed to Fabric on `a8bdda7a`, accepted on `d3f9e6fb`) is at most 10 `{host, owner, name}` and is sent only where the tool's input schema lists it with items carrying host, owner and name, so a Fabric without it gets the call it gets today; from Fabric 0.3.14 a turn's answer is `{recorded, seq, nudges?}`, each nudge `{kind, says, task_id?, request_id?}` shown on a turn once, at most five, the same (with `repeated: true`) on a repeat of the turn's `idempotencyKey` within an hour, and kept for `fabric_work_list` and `fabric_heartbeat` (FAA-142; re-read against the tag `v0.3.14`, `7e43dc03`, FAA-143: `workTools.ts` `fabric_session_observe`, `abandonedSweepRun.ts` `TURN_NUDGES_MAX` and `TURN_REPEAT_MS`, `shared/abandonedSweep.ts` `nudgeText`, which starts every `says` with `Fabric:`) |
| D5 | release a whole session | `fabric_work_release {claims: "session", outcome: "let-go", reason, idempotencyKey}`; `observedAt` too where its input schema names it (Fabric 0.3.9: `stale-end` for an end observed before the session enrolled) |
| D6 | a launched-session marker | `FABRIC_LAUNCHED_SESSION=1` in the environment of every session Fabric launches, whatever its adapter; until then, the inference above |
