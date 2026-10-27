# FAA-18 — `working-with-fabric` and the Claude Code session hooks (Fabric 0.4.0 REQ-07, COM-04)

Run: 2026-10-11. Branch `agent/working-with-fabric-20261011`. Requested by the Fabric 0.4.0 release (plan
canvas node C4, REQ-07; open question Q-04 answered "yes": the skill and the hook pack ship here, COM-04's owner).

## Objective

A coding agent opened in a terminal, outside Fabric, learns how to work with Fabric the way a session Fabric
launched already does: find Fabric, have it started by the machine's lifecycle broker when it is down, register
`fabric-mcp` once with no secret, call `fabric_whoami` first, coordinate before it starts (`fabric_work_list`,
`fabric_work_claim`), report while it works, link tasks to backlog rows instead of copying them, and release at the
end. In Claude Code, a hook pack injects the preamble at session start, records each turn as facts with no content,
and releases what the session left claimed at its end — without ever blocking or slowing the session.

## Source ledger

| Source | What it gave |
|---|---|
| fabric `docs/evidence/plans/2026-10-11-release-040-agents-first.md` @ `main` (C1, C4, REQ-07, REQ-08, REQ-38, Q-04) | the skill's steps, the hook pack's three events and their journal events (`session.turn.observed@1`, `session.ended@1`), "link, don't copy" (R-07) |
| fabric `docs/adr/0134-…-on-consent.md` @ `main`, amendment 2 | the registration commands with `--runner`, the per-OS `<Fabric>/bin`, the failure classes (unknown outcome, transport drop, refusal before the call), the 8-live-sessions cap per binding |
| fabric `docs/ux/scenarios.md` SCN-137, SCN-140 @ `main` | the agent-side states (not-running, hub-closed, no-project, waiting, denied, revoked) and the claim states (claimed, related-warned, refused-held, refused-other-project, refused-no-grant, outcome-unknown) |
| fabric `apps/desktop/src/main/fabricMcp.ts`, `fabricMcpMain.ts`, `hub.ts`, `agentRegistry.ts#registryDirs`, `sessionEnroll.ts`, `shared/surfaceTools.ts`, `electron-builder.yml` @ `812876cf` | what exists today: `fabric-mcp` enrolls with `{cwd}` only, one waiting tool until admitted, `hub.json` fields and checks, the registry root per OS, the session tool catalogue (`fabric_task_claim`, `fabric_stage_report`, …), product name `Fabric`, NSIS per-user and `.deb` targets |
| [raw/mcp-server-env.log](../../reports/2026-10-11-working-with-fabric/raw/mcp-server-env.log) | measured 2026-10-11, Claude Code 2.1.296: an MCP stdio server receives `CLAUDE_CODE_SESSION_ID`, equal to the `session_id` its hooks receive |
| this repository `AGENTS.md`, `test/validate.py`, `hooks/hooks.json`, `dashboard_kit.py notice` | stdlib-only scripts, evals before prose, version sync, the existing SessionStart hook's never-fail shape, LC-09 |

## Decisions

1. **One skill, `working-with-fabric`**, in this plugin beside the three builder skills. It is about USING Fabric
   from a coding agent; building or adapting an agent stays with the other three.
2. **The planned tools are named as planned and marked "Fabric 0.4.0"**: `fabric_work_list`, `fabric_work_claim`,
   `fabric_work_release` (REQ-38). On an older Fabric the skill falls back to the tools that exist today
   (`fabric_tasks_list`, `fabric_leases_list`, `fabric_task_claim`, `fabric_task_release`) and says so.
3. **The hooks never spawn a second Fabric session.** Measured hazard: a closed `fabric-mcp` connection does not end
   its enrolled session, and past 8 live sessions per binding Fabric ends the oldest (ADR-0134 amendment 2;
   `sessionEnroll.ts#EnrolledSessions` keeps rows until revoked). A hook that started `fabric-mcp` each turn would
   end the agent's own session after eight turns. So the Stop and SessionEnd hooks talk to Fabric only when the
   running Fabric says in `hub.json` that it supports them (`"features": ["session-hooks/1"]`), and then only
   through `fabric-mcp --rejoin-only --runtime-session-id <id>`, which joins the agent's own enrolled session and
   never asks or mints. Without the feature they read `hub.json` first, return and write nothing (`status` reports them inert). This is the Fabric
   dependency, listed below.
4. **No content, ever.** A turn observation carries the HEAD commit, the count of changed files and the lines added
   and removed against HEAD — no paths, no branch names, no messages, no diff text.
   Amended 2026-10-27 (0.53.0, [brief D1, D2, D7](2026-10-27-faa-140-155-brief.md)): once the running Fabric takes
   them, on Windows too since 0.56.0 (FAA-175), and not when the person turned it off (FAA-160), a turn also carries the other repositories it touched as `{host, owner, name}`, read from the transcript's
   tail; still no local paths, no messages, no diff text.
5. **Never block or slow.** SessionStart reads two small files and prints; Stop and SessionEnd write a spool entry
   and start a detached worker that holds a 10 s deadline. Every hook exits 0; every failure is one log line in the
   adapter's cache folder (0600, rotated at 1 MB). No token is read: the hooks never open the door token or a
   credential, and nothing secret is in argv or the log. Amended 2026-10-27 (0.53.0): once Fabric takes repositories,
   on Windows too since 0.56.0 (FAA-175), and not when the person turned it off (FAA-160), Stop reads the transcript's last 512 KB (message text and tool output, which can hold a secret the session
   displayed; read in memory only, never spooled, logged or sent) and runs `git config` in the repositories it names; a credential embedded in
   an `origin` URL is read with it and dropped in memory, never spooled, logged or sent.
6. **SessionStart injects the preamble only when `fabric` is registered in Claude Code and Fabric is running**; when
   it is registered and Fabric is down, one line says so and points at the lifecycle broker. Unregistered: silent.
7. **Codex gets the MCP entry and first-prompt advice only** — its hooks are unverified, so none ship.
8. **Version 0.10.0** (a new skill and new hooks: minor).

## Fabric dependency (what the hooks need from Fabric 0.4.0)

| # | What | Exact shape |
|---|---|---|
| D1 | `fabric-mcp` enrolls with the runtime session id | for `--runner claude-code`, pass `runtimeSessionId` = env `CLAUDE_CODE_SESSION_ID` in `fabric.session.enroll {cwd, runtimeSessionId}` (`sessionEnroll.ts#enrollSession` already accepts and journals it) |
| D2 | a rejoin-only mode | `fabric-mcp --runner claude-code --rejoin-only --runtime-session-id <id>`: attaches to the live enrolled session of that runtime session in that folder's project; never calls `fabric.access.request`, never mints; with no such session it answers through `fabric_whoami` as not enrolled and offers no other tool |
| D3 | the feature flag | `hub.json` gains `"features": ["session-hooks/1"]` once D1, D2, D4 and D5 ship; the hooks stay inert without it |
| D4 | `fabric_session_observe` | `{event: "turn"\|"end", runtime: "claude-code", runtimeSessionId, observedAt (ISO 8601), head (40 hex or null), filesChanged (int or null), linesAdded (int or null), linesRemoved (int or null), reason (end only: Claude Code's SessionEnd reason), idempotencyKey}` → journals `session.turn.observed@1` / `session.ended@1`; the same key twice is one event |
| D5 | `fabric_work_release` for a whole session | `{claims: "session", outcome: "let-go", reason: "the Claude Code session ended (<reason>)", idempotencyKey}` releases every claim the calling session holds; `claims` may otherwise name claim ids (REQ-38) |
| D6 | a launched-session marker (FAA-12a) | every session Fabric launches carries `FABRIC_LAUNCHED_SESSION=1` in its environment, whatever its adapter (`mcp-config-flag`, `config-content-env`, `acp-session`, `codex-config-home`), so a hook knows Fabric already briefed it; until then the hooks infer it from what `sessionBundle.ts` already gives (variable names only, never a value) |

## REQ table

| REQ | Requirement | Verified by |
|---|---|---|
| W-01 | The skill teaches: find Fabric (`hub.json` per OS, pid), the lifecycle broker sequence, the registration commands per agent and OS, `fabric_whoami` first, list → claim → report → release, `source: {repository, path, id}`, the refusals | scenario evals `test/evals/working-with-fabric/scenarios.json`; `validate.py` |
| W-02 | Triggers in English and Russian; neighbours (building, adapting, Fabric's own code) do not trigger it | `triggers.json` (≥ 18, balanced) |
| W-03 | `fabric_session.py status` reports Fabric, `fabric-mcp`, both registrations and one next action, reading no secret | `test/test_fabric_session.py` |
| W-04 | SessionStart: preamble when registered + running; one line when registered + down; silent otherwise; always exit 0, well under its timeout | tests with fixtures (temporary HOME, fake `hub.json`, live and dead pids) |
| W-05 | Stop/SessionEnd: inert (no process, nothing written) without `session-hooks/1`; with it, a spool entry and a detached worker that calls `fabric_session_observe` / `fabric_work_release` through `fabric-mcp --rejoin-only`; a missing tool degrades to a log line; content-free payloads | tests with a fake `fabric-mcp` (stdio MCP) that records its argv, env and calls |
| W-06 | No secret in argv or logs; the door token never read | tests assert argv and log contents |
| W-07 | Plugin and skill valid; versions in sync | `python3 test/validate.py`; both `claude plugin validate --strict` |
