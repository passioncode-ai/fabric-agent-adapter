# The session hooks (COM-04, FAA-12a)

Read this when a person asks what the plugin's Fabric hooks do, where they log, how to turn them off, or what they
need from Fabric. In Claude Code they live in the plugin's `hooks/hooks.json` and run
`scripts/fabric_session.py hook <event>`. Codex and Kimi Code get one hook, the session-start preamble, which
`install-host-hooks` adds to their own config on the person's consent.

## Contents

- What each hook does
- Codex and Kimi Code
- `watch-mail`
- A session Fabric launched
- What they never do
- Where they log, and how to turn them off
- What they need from Fabric

## What each hook does

| Event | When it acts | What it does |
|---|---|---|
| SessionStart (every source) | Claude Code has an MCP server named `fabric` (local, project or user scope) | Fabric running: adds the preamble — `fabric_whoami` first; `com.status` and `com.list`, `com.read_ack` only what was read; `fabric_work_list`, then `fabric_work_claim`; `fabric_work_release` at the end; ask another Project only through `com.submit`. Fabric down: one line pointing at the lifecycle broker. Not registered: no preamble. |
| SessionStart, any host | the machine has `fabric-service/0.1` descriptors | adds one line: how many descriptors, where, how many on 127.0.0.1, how to probe them, never kill them (the same text as the machine's `fabric-session-note.sh`; hidden files are not counted) |
| Stop (each turn) | as for SessionStart, and the running Fabric's `hub.json` lists `"session-hooks/1"` in `features` | spools one entry and starts a detached worker that sends `fabric_session_observe {event: "turn", head, filesChanged, linesAdded, linesRemoved, …}`, then reads `com.status` and keeps the unread count in the session's spool (`board.json`) |
| UserPromptSubmit | the session's spool holds a count | adds ONE line, `N unread on the project board — com.list`, only when the count rose since the last line; a fall or the same count says nothing. It reads two small files and never calls Fabric. |
| SessionEnd | as for Stop | spools the end; the worker sends `fabric_work_release {claims: "session", outcome: "let-go", …}`, then `fabric_session_observe {event: "end", reason}`, and removes the session's spool |

Without `session-hooks/1`, Stop and SessionEnd read `hub.json`, return, and write nothing, so UserPromptSubmit has
nothing to show; `fabric_session.py status` says "Session hooks: inert". That is every Fabric before the release
that ships the dependencies below. A board that cannot be read (`unavailable`, a refusal) leaves no count — never a
zero; a `degraded` board that still gives the count is read.

## Codex and Kimi Code

`fabric_session.py hook session-start --host codex|kimi` emits structured SessionStart JSON for Codex and plain text
for Kimi when the host has `fabric`
registered (`[mcp_servers.fabric]` in `$CODEX_HOME/config.toml`; `mcpServers.fabric` in `~/.kimi-code/mcp.json`),
plus the service line. Nothing else: no turn observation and no unread line, because a rejoin needs the runtime
session id Fabric keeps with the enrollment, which only Claude Code supplies today (D1).

`install-host-hooks --host codex|kimi` is a dry run by default. It prints the file, its sha256, and the one entry it
would add — never a value already in the file — and the `--apply --expect-sha256 <digest>` command. With `--apply` it
backs the file up (`<file>.<UTC stamp>.bak`, never overwriting an earlier backup), keeps the file's mode, refuses a
file whose shape is not `{"hooks": {"<Event>": [{"hooks": [...]}]}}` (Codex) or an array of `[[hooks]]` tables
(Kimi Code, read back with `tomllib`: Python 3.11+), and refuses one that changed since the dry run. `--remove` takes
the entry out again. Codex may ask the person to trust a new hook (`/hooks`) before it runs. The hook runs the
`fabric_session.py` of the skills install (`~/.agents/skills/working-with-fabric/`) when there is one, else this
script's own path; a plugin cache path changes with each update, so pass `--script <a stable path>` there.

Native Hermes, OpenCode, OpenClaw and Pi bridges are described in [native host hooks](native-host-hooks.md).
They consume the same context through their own APIs. They never use the Claude-only rejoin/turn lifecycle.

## `watch-mail`

`fabric_session.py watch-mail [--interval 60]` is for an idle Claude Code session waiting on the board; the agent
starts it under a background watcher. It rejoins the session (`CLAUDE_CODE_SESSION_ID`, or `--session-id`) through
`fabric-mcp --rejoin-only` for each look, prints one line each time the unread count rises, and waits `interval`
± 20 % between looks (never under 10 s). While Fabric is down or the board unreadable it says so once and backs off,
doubling to at most 15 minutes. It exits on its stdin's end (when started with a pipe), SIGTERM, SIGINT or SIGHUP,
or when its parent is gone. It refuses to start in a session Fabric launched, and without a `fabric` registration.

## A session Fabric launched

Every hook, and `watch-mail`, is silent there: Fabric briefed that session itself. The signals, cheapest first —
only variable names are looked at, never a value (two of them carry the session's credential):

1. `FABRIC_LAUNCHED_SESSION=1` — the marker Fabric is asked to set (D6). `0` or empty is not the marker.
2. What Fabric already gives (`apps/desktop/src/main/sessionBundle.ts`): `FABRIC_ACP_SESSION` (ACP sessions),
   `FABRIC_BRIDGE_URL` (the stdio bridge), `KILO_CONFIG_CONTENT` (Kilo), and `CODEX_HOME` inside
   `<Fabric's folder>/sessions/` (Codex).
3. Claude Code launched by Fabric has no variable yet: its command line holds `--mcp-config
   <Fabric's folder>/sessions/<id>/mcp.json`. SessionStart, and Stop once per session, look for that in a few
   ancestor processes (`ps`, bounded to 0.5 s each); only the match is used, nothing is kept or logged.

## What they never do

- **Block or slow the session.** Each hook has a 5 s ceiling in `hooks.json`; the script reads a few small files and
  returns in tens of milliseconds. Every call to Fabric happens in a detached worker with a 10 s deadline. Every
  hook exits 0, on every path.
- **Read a secret.** The hooks never open Fabric's door token or an enrollment credential; `fabric-mcp` holds
  those. Nothing secret is in argv (the worker's argv is the script and a spool folder) or in the log.
- **Send or read content.** A turn is the HEAD commit, the number of files that differ from it (untracked included)
  and the lines added and removed against it — no path, branch name, commit message or diff text. The board is read
  as a count (`com.status`), never a message. Git runs with `--no-optional-locks`.
- **Start a second Fabric session.** A `fabric-mcp` started on its own would enroll a new session, and Fabric ends a
  binding's oldest live session past eight (ADR-0134 amendment 2) — the agent's own. The worker and `watch-mail` run
  `fabric-mcp --rejoin-only --runtime-session-id <id>`, and only when Fabric advertises `session-hooks/1`.
- **Retry in a loop.** A refused call is logged by its error code and dropped; an answer that never came is logged
  as `outcome=unknown`. The calls carry an `idempotencyKey`, so a repeat is the same event.

## Where they log, and how to turn them off

One line per event that did something, never content: `~/Library/Caches/ai.passioncode.fabric-agent-adapter/hooks.log`
(macOS), `$XDG_CACHE_HOME/fabric-agent-adapter/hooks.log` (Linux, default `~/.cache`),
`%LOCALAPPDATA%\fabric-agent-adapter\hooks.log` (Windows). Mode 0600, rotated at 1 MB to `hooks.log.1`. The
per-session spool is `sessions/<session id>/` beside it (turn entries capped at 50, `board.json`, `board.shown`),
removed at the session's end.

Turn them off with Claude Code's own switch (`/hooks`, or `"disableAllHooks": true` in settings), or remove the
`fabric` MCP server — the preamble and the Fabric calls stop without it. Uninstalling the plugin removes them; delete
the cache folder above to leave nothing behind. Codex and Kimi Code: `install-host-hooks --host <host> --remove`.

## What they need from Fabric

Each is a Fabric dependency; until D1–D5 ship, Stop, SessionEnd and UserPromptSubmit stay inert. D6 only makes the
launched-session check exact.

| # | Need | Shape |
|---|---|---|
| D1 | `fabric-mcp` enrolls with the runtime session id | for `--runner claude-code`, `runtimeSessionId` = env `CLAUDE_CODE_SESSION_ID` in `fabric.session.enroll {cwd, runtimeSessionId}` (Claude Code 2.1.296 gives MCP stdio servers and Bash commands that variable, equal to the hooks' `session_id`) |
| D2 | rejoin only | `fabric-mcp --runner claude-code --rejoin-only --runtime-session-id <id>` attaches to that runtime session's live enrolled session; never asks, never mints; otherwise only `fabric_whoami`, as not enrolled |
| D3 | the flag | `hub.json` `"features": ["session-hooks/1"]` once D1, D2, D4 and D5 ship |
| D4 | `fabric_session_observe` | `{event: "turn" or "end", runtime: "claude-code", runtimeSessionId, observedAt, head, filesChanged, linesAdded, linesRemoved, reason (end only), idempotencyKey}` → `session.turn.observed@1`, `session.ended@1` |
| D5 | release a whole session | `fabric_work_release {claims: "session", outcome: "let-go", reason, idempotencyKey}` |
| D6 | a launched-session marker | `FABRIC_LAUNCHED_SESSION=1` in the environment of every session Fabric launches, whatever its adapter; until then, the inference above |
