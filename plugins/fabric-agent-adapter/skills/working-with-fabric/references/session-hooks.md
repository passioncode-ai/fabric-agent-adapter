# The Claude Code session hooks (COM-04)

Read this when a person asks what the plugin's Fabric hooks do, where they log, how to turn them off, or what they
need from Fabric. They live in the plugin's `hooks/hooks.json` and run `scripts/fabric_session.py hook <event>`.
They run in Claude Code only; Codex and the other agents get the MCP entry and first-prompt advice (SKILL.md).

## Contents

- What each hook does
- What they never do
- Where they log, and how to turn them off
- What they need from Fabric

## What each hook does

| Event | When it acts | What it does |
|---|---|---|
| SessionStart (every source) | Claude Code has an MCP server named `fabric` (local, project or user scope) | Fabric running: adds the preamble — call `fabric_whoami` first; `fabric_work_list`, then `fabric_work_claim`, before work; `fabric_work_release` at the end. Fabric down: one line pointing at the lifecycle broker. Not registered: nothing. |
| Stop (each turn) | as above, and the running Fabric's `hub.json` lists `"session-hooks/1"` in `features` | spools one entry and starts a detached worker that sends `fabric_session_observe {event: "turn", head, filesChanged, linesAdded, linesRemoved, …}` through Fabric |
| SessionEnd | as for Stop | spools the end; the worker sends `fabric_work_release {claims: "session", outcome: "let-go", …}`, then `fabric_session_observe {event: "end", reason}`, and removes the session's spool |

Without `session-hooks/1`, Stop and SessionEnd read `hub.json`, return, and write nothing; `fabric_session.py
status` says "Session hooks: inert". That is the
state of every Fabric before the 0.4.0 release that ships the dependency below.

## What they never do

- **Block or slow the session.** Each hook has a 5 s ceiling in `hooks.json`; the script reads two small files and
  returns in tens of milliseconds. Every call to Fabric happens in a detached worker with a 10 s deadline. Every
  hook exits 0, on every path.
- **Read a secret.** The hooks never open Fabric's door token or an enrollment credential; `fabric-mcp` holds
  those. Nothing secret is in argv (the worker's argv is the script and a spool folder) or in the log.
- **Send content.** A turn is the HEAD commit, the number of files that differ from it (untracked included) and the
  lines added and removed against it — no path, no branch name, no commit message, no diff text. Git runs with
  `--no-optional-locks`, so it never takes the index lock from under the agent.
- **Start a second Fabric session.** A `fabric-mcp` the hooks started on their own would enroll a new session each
  turn, and Fabric ends a binding's oldest live session past eight (ADR-0134 amendment 2) — the agent's own. So the
  worker runs `fabric-mcp --rejoin-only --runtime-session-id <id>`, which joins the session the agent already holds,
  and only when Fabric says it supports that (`session-hooks/1`).
- **Retry in a loop.** A refused call is logged by its error code and dropped; an answer that never came is logged
  as `outcome=unknown`. The calls carry an `idempotencyKey`, so a repeat is the same event.

## Where they log, and how to turn them off

One line per event that did something, never content: `~/Library/Caches/ai.passioncode.fabric-agent-adapter/hooks.log`
(macOS), `$XDG_CACHE_HOME/fabric-agent-adapter/hooks.log` (Linux, default `~/.cache`),
`%LOCALAPPDATA%\fabric-agent-adapter\hooks.log` (Windows). Mode 0600, rotated at 1 MB to `hooks.log.1`. The
per-session spool is `sessions/<session id>/` beside it, capped at 50 turns and removed at the session's end.

Turn them off with Claude Code's own switch (`/hooks`, or `"disableAllHooks": true` in settings), or remove the
`fabric` MCP server — every hook is silent without it. Uninstalling the plugin removes them; delete the cache folder
above to leave nothing behind.

## What they need from Fabric

Each line is a Fabric 0.4.0 dependency; until all ship, the hooks stay inert.

| # | Need | Shape |
|---|---|---|
| D1 | `fabric-mcp` enrolls with the runtime session id | for `--runner claude-code`, `runtimeSessionId` = env `CLAUDE_CODE_SESSION_ID` in `fabric.session.enroll {cwd, runtimeSessionId}` (Claude Code 2.1.296 gives MCP stdio servers that variable, equal to the hooks' `session_id`) |
| D2 | rejoin only | `fabric-mcp --runner claude-code --rejoin-only --runtime-session-id <id>` attaches to that runtime session's live enrolled session; never asks, never mints; otherwise only `fabric_whoami`, as not enrolled |
| D3 | the flag | `hub.json` `"features": ["session-hooks/1"]` once D1, D2, D4 and D5 ship |
| D4 | `fabric_session_observe` | `{event: "turn" or "end", runtime: "claude-code", runtimeSessionId, observedAt, head, filesChanged, linesAdded, linesRemoved, reason (end only), idempotencyKey}` → `session.turn.observed@1`, `session.ended@1` |
| D5 | release a whole session | `fabric_work_release {claims: "session", outcome: "let-go", reason, idempotencyKey}` |
