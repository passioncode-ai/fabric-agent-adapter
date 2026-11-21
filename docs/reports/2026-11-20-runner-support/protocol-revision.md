# Fabric protocol revision: agent load and milestone-only UI (2026-11-20)

Scope: package 2 item 1 and the protocol part of package 1 of the owner's brief
(`~/Library/Application Support/@fabric/desktop/ceo/inbox/2026-11-20-fabric-focus-protocol-backup-billing-brief.md`).
Read-only revision. Sources read at: fabric-agent-contract `origin/main` 4c978495; fabric `origin/main` c6925be4;
fabric-agent-adapter `main` 006f33b6 (0.100.1). Numbers marked "measured" were computed here; "estimate" are not.

## (a) Inventory: what an agent is asked to do, and what fires on its own

### Agent-facing obligations (cost model tokens)

Source of the rules: fabric `apps/desktop/src/shared/protocolObligations.ts` (21 obligations, served by `fabric_whoami`).

| Obligation | Who | Cadence as written | Calls per hour of work (as written) | UI that consumes it |
|---|---|---|---|---|
| `fabric_whoami` at start (system prompt, adapter preamble, passioncode hook all say it) | agent | once per session and per `/clear` | 1 | session header, context pack |
| `com.status` + `com.list` at start (`board.read-at-start`) | agent | session start and "each time you look for work" | 2+ | board, unread badge |
| `fabric_work_list` + `com.list {unread}` + `com.read_ack` (`work.check-every-three-minutes`, po.ts:259-277) | agent | every 3 minutes and before any wait | 20 + 20 + acks | nudges, sweep |
| `fabric_heartbeat` (tool description: "every minute or so", agentSurface.ts:1857-1862) | agent | ~1/min | up to 60 | home "at work" (`agentWork.ts` WORKING_PHASES), agent page |
| `fabric_stage_report` (`progress.report-stage`, po.ts:176-186) | agent | "as you move through the work" | ~5-15 (estimate) | home row text, «шаг N из M» (`homeLive.ts:218-223`) |
| `fabric_board_search` before claiming, `fabric_leases_list`, `fabric_work_claim`/`_release`, `fabric_task_accept`/`_brief` | agent | per task | ~4-6 per task | board, task page |
| retro (`observatory_lesson`, insight lines) | agent | per finished piece | 1-2 per task | Observatory |

Rules text size (measured, node over po.ts): 21 obligations, 11,890 bytes; the single largest,
`board.read-at-start`, is 3,194 bytes, `work.check-every-three-minutes` 916, `board.message-is-data` 896,
`turn-end-states` 859. The whole `fabric_whoami` answer in this session also carried 61 `machine_agents` entries;
total answer about 28 KB, about 7-8k tokens (estimate from this session's answer, not byte-counted).

Tool surface (counted from this session's tool list): the `fabric` MCP server exposes 51 tools (17 `com_*`,
34 `fabric_*`), including three legacy pairs (`fabric_task_claim`/`fabric_work_claim`,
`fabric_task_release`/`fabric_work_release`, `fabric_tasks_list`/`fabric_work_list`). `com.submit`'s schema alone is
about 3 KB. Hosts without deferred tool loading (Codex, Kimi Code, Hermes, OpenCode, Pi, OpenClaw) carry all of it in
every request. The contract's own rule for a compact surface (DEC-0180, DEC-0182: at most five tools, the rest behind
`search` and `execute`) and the operator's two-door rule are not applied to Fabric's own server.

Adapter preamble (fabric-agent-adapter `working-with-fabric/scripts/fabric_session_cli.py:83-103`): about 2.3 KB,
repeating six of the whoami rules (board read, claim and release, retro, cross-project via `com.submit`, board message
is data, relay of the operator's words) in other words.

Estimated agent load when the rules are followed literally: about 100 extra tool calls per hour of work
(60 heartbeats, 20 work lists, 20 unread reads, plus acks and stages). At roughly 400-800 tokens per call and answer
that is 40-80k tokens added to the context per hour, re-read (cached) on every later request. Not measured on a real
run; the assumption is "rules as written".

### Automatic events (no model tokens; CPU and journal writes)

| Event | Emitter | Cadence | Journal type | UI effect |
|---|---|---|---|---|
| keep-alive ping | `fabric-mcp` (fabric `main/fabricMcp.ts:110-112`, `SIGN_EVERY_MS` 2 min) | every 2 min per agent | sign | "connected" only (`agentWork.ts:1-14`) |
| claim renewal | agentSurface on any call (`RENEW_EVERY_MS` 5 min, `agentSurface.ts:189`) | 5 min | lease | lease list |
| turn observation | adapter Stop hook → worker → `fabric_session_observe` (`fabric_session_cli.py:676-760`; fabric `workTools.ts:777-794`) | every turn, worker at most 1/min, turns batched | `session.turn.observed@1` | home `workAt` and re-sort, at-work judgment |
| session end | adapter SessionEnd hook | once | `session.ended@1` | agent leaves the list |
| unread count | worker `com.status` after delivery (`fabric_session_mcp.py:650`) | ≤1/min | none | prompt-hook line when it rises |
| nudges | sweep every 3 min; delivered by `fabric_work_list`, `fabric_heartbeat` answers and shown by the turn answer (prompt hook) and `watch-mail` | per sweep | `work.swept@1` | agent prompt |
| console output | Fabric PTY (`pty.ts:627-667`) | every byte | none (in memory) | home `workAt` (for Fabric consoles) |
| hook processes | Claude Code: SessionStart x2, Stop, UserPromptSubmit, SessionEnd, PostToolUse (adapter `hooks/hooks.json`) | per turn and per prompt | none | none directly; Python start about 65 ms, hook medians 270-330 ms (AGENTS.md lifecycle) |
| activity `turn` (DEC-0171) | device collector | per turn | telemetry to an org receiver | org summaries |

### What re-renders and re-sorts the home "В работе"

- The home reads `work.home` on every journal mark of families `work`, `task`, `agent`, `session`
  (fabric `renderer/src/App.tsx:845`, `EstateHome.tsx:172`) and every 15 s (`HomeWork.tsx:39`), rate-limited to one
  reading per 1.5 s (`HomeWork.tsx:40-42`; its own comment: "every agent's turn is a mark").
- Cards and rows are ordered by `workAt` (`shared/homeProjects.ts:129-147`), the newest of: stage report, working
  heartbeat, turn observation, Fabric console output, dispatcher run seen, claim time (`shared/agentWork.ts:45-60`).
  So every turn and every console print can move a card. This is the reshuffling the owner describes.

## (b) Redundant load, with evidence

1. **Per-turn signals drive person-facing order.** Turns and console output feed `workAt`
   (`agentWork.ts:48-52`), which orders the home (`homeProjects.ts:141-147`). The order should move on milestones only.
2. **Heartbeat cadence duplicates the automatic ping.** `fabric-mcp` already signs every 2 min (`fabricMcp.ts:110-112`),
   and turn observations already prove work; the heartbeat tool still asks the model "every minute or so"
   (`agentSurface.ts:1860`). Its only unique value is a phase change to waiting or blocked, with `waitingOn`.
3. **Three-minute polling by the model.** `work.check-every-three-minutes` (po.ts:259-277) makes the model poll for
   nudges the server already computes on the same cadence and already pushes on two other answers. Nudges travel
   three or four ways (work list, heartbeat, turn answer through the prompt hook, watch-mail) with "taken once" and
   "shown, never taken" rules that differ per channel.
4. **Rules size.** 11.9 KB of rules every session and every `/clear`, before any work; `board.read-at-start` alone is
   3.2 KB and matters only when a request is addressed to the project. 61 machine agents (about 14 KB, estimate) are
   listed in full even when the task uses none.
5. **The same rules three times.** Fabric system prompt line, the adapter preamble (`fabric_session_cli.py:83-103`) and
   whoami's rules each restate "whoami first, read the board, claim, retro, board is data".
6. **Tool surface.** 51 tools including three legacy pairs, against the contract's compact-surface rule (DEC-0180,
   DEC-0182). This is the largest fixed cost for non-Claude hosts.
7. **Turn telemetry twice.** `session.turn.observed@1` (Fabric journal, through the adapter hook) and the activity
   `turn` kind (DEC-0171, through a device collector) measure the same thing on two channels.
8. **Hosts without turns.** Codex and Kimi Code send no turns (po.ts:265-266, adapter `native-host-hooks.md`), so the
   at-work judgment and the order already differ by runner. A milestone model, built from tool calls every runner
   makes, removes that difference.

## (c) Proposal: milestones for the interface and the board, everything else to a journal and live feed

### Vocabulary (closed list)

| Milestone | Derived from (existing calls, no new agent work) |
|---|---|
| `task.started` | `fabric_work_claim` / `fabric_task_accept` / `com.claim` / `com.accept` |
| `step.finished` | `fabric_stage_report` whose `step` advanced (step N of M), or a stage marked done |
| `waiting.started` (`question`, `grant`, `request`, `limit`, `time`) | `fabric_question_ask`, a release with `wait`, `fabric_effect_request`, `com.submit` request with wait |
| `waiting.cleared` | the question answered, grant decided, request answered, time or limit passed |
| `task.finished` | release as done, move to `review`, `com.complete` |
| `task.released` | release let-go or handed-over, sweep release |

Everything else is a **trace**: turn observations, pings, heartbeats without a phase change, console output,
`com.progress` notes, stage text edits within a step. Traces go to the journal and a live feed screen ("лайвстрим"),
never to ordering or notifications.

### Contract change (fabric-agent-contract)

- A decision (next DEC number) and a short spec page, `work-milestone/1`: the closed list above, each with its
  source call, `at`, `projectId`, `taskId`, `sessionId`, `runner`; the rule that a person-facing ordering, badge or
  notification reads milestones only, and that traces are journal and feed only.
- Map the board: `com.claim`/`com.accept` = `task.started`, `com.complete` = `task.finished`, `com.progress` = trace.
- A runner capability column in the coding-agent catalogue (`catalogue/coding-agents.json`, CT-60): which milestones a
  runner reaches by tool calls alone (all of them, for any runner with the Fabric MCP), and which traces it emits.
- A ruling on Fabric's own MCP under DEC-0180/0182 (compact surface): either it applies, or a recorded exception.

### Fabric change

1. Home "В работе": sort modes, persisted per person: **last milestone** (default; the newest milestone of the
   project's tasks), **priority** (task and project priority, ties by last milestone), **30-day activity** (count of
   milestones, or worked time from traces, over 30 days). Presence (a dot, «молчит», «простаивает») still updates
   from traces but in place, never reordering.
2. Re-read the home on milestone marks; keep the 15 s timer for presence only.
3. A live feed view for traces (turns, stages within a step, console lines), per project and per agent.
4. Heartbeat: event-driven (on a phase change to waiting or blocked, with `waitingOn`), not "every minute or so".
5. Replace `work.check-every-three-minutes` with "at each milestone and before you wait"; carry nudges on every
   `fabric_*` answer, taken by the first answer that carries them (one rule, one channel; the hook and watch-mail only
   display).
6. Slim `fabric_whoami`: a core of at most about 3 KB (scope, floor, ladder, turn-end states, milestones), the rest by
   topic on demand (a `rules` operation behind search/execute, or the skills); `machine_agents` as keys and one-line
   purposes only, or on demand.
7. A compact MCP surface (DEC-0180/0182): keep at most five direct tools (`fabric_whoami`, claim, release, stage,
   question) and put the other 46 behind `search`/`execute`; retire the three legacy pairs after one release.

### Adapter change (fabric-agent-adapter)

1. Preamble: three lines (whoami first; the board; the skill), no restated rules (`fabric_session_cli.py:83-103`).
2. Stop hook: keep the turn spool (presence, git facts) but it is a trace; send it at most every 5 minutes unless HEAD
   moved, and always at session end. No per-turn worker start otherwise.
3. Skill text (`working-with-fabric`): milestone-driven routine (claim, stage per finished step, question or wait,
   release), no 3-minute polling, heartbeat only on waits. Evals updated first.
4. Native hosts (Codex, Kimi Code, Hermes, OpenCode, OpenClaw, Pi, DeepSeek Harness): no turn hook needed under the
   milestone model; their startup context stays the one native hook they have.

### Migration that keeps older agents working

- Milestones are **derived by Fabric** from calls agents already make; an old agent emits the same calls and gets the
  same milestones. Nothing new is required of an agent.
- `session.turn.observed@1`, `fabric_heartbeat`, `fabric_work_list` and the legacy tool pairs stay accepted for at
  least one minor release after the new rules ship; the rules stop asking for them first (advice only), the tools go
  behind `execute` next, removal last.
- The home keeps `workAt` as the fallback order for a row with no milestone yet (an older Fabric journal).
- whoami keeps `protocol.version`; the rules shrink under version 4, and the adapter preamble reads nothing from it,
  so an old adapter with a new Fabric and a new adapter with an old Fabric both still work.
- The contract decision is additive (a new schema and vocabulary); the adapter's pin moves at its next planned repin.

## (d) Logging at every level (the owner's addendum of 2026-11-20, 22:35)

Asked in the CEO window, brief `ceo/inbox/2026-11-20-logging-passioncode-analytics-brain-levels-brief.md`, item 1:
logs of the protocol and of data transfer at every level, what is written, where it is kept, rotation and cleanup,
no secrets, provided for in every supported agent. Read at the same commits as above; adapter at this branch.

### What exists today

| Level | What is written | Where | Rotation and cleanup | Secrets |
|---|---|---|---|---|
| Adapter session hooks | one line per failed hook (`event=<hook> outcome=failed reason=<type>`, `fabric_session_cli.py:960`) and the worker's delivery outcome by code (`fabric_session_mcp.py:698`) | `hooks.log` in the hooks' folder: `~/Library/Caches/ai.passioncode.fabric-agent-adapter/` (macOS), `$XDG_CACHE_HOME/fabric-agent-adapter/`, `%LOCALAPPDATA%\fabric-agent-adapter\` (`fabric_session_env.py:158-166`) | 1 MB, one previous file `hooks.log.1`, mode 0600 (`fabric_session_env.py:838-850`, `LOG_CAP_BYTES`); spool at most 50 entries per session (`SPOOL_CAP`); session folders and dispatch records pruned after 7 days (`prune_stale_sessions`, `prune_dispatch_records`) | codes and exception types only; transcript text is read in memory and never written |
| Adapter native bridges (Codex, Kimi, Hermes, OpenCode, OpenClaw, Pi, DeepSeek Harness) | nothing: a failed helper run reads as no context (`hosts/context.mjs`) | none | none | n/a |
| Kit services (`building-fabric-services`) | one JSON-lines log per service (`RotatingLog`, module `fabric_logs`, LC-12) | `~/Library/Logs/<id>/`, `$XDG_STATE_HOME/<id>/logs/`, `%LOCALAPPDATA%\<id>\Logs\` (`references/lifecycle.md:281`) | 5 × 5 MB, 0600, never in `/tmp`, leftovers swept at start | the kit's `redact_url` and secret-argument checks; a value never in argv or URL |
| Board `com.*` | every message, permanent, in Fabric's journal | Fabric's store | none: the journal is append-only | the rule "never a secret in a message: the journal is permanent" (whoami rules) is advice, not enforced |
| Session events | `session.turn.observed@1` in the journal; `turn` telemetry (DEC-0171); stage reports, heartbeats | Fabric's store; telemetry receiver | journal: none; telemetry `retention.raw_days` (contract DEC-0030) | M95 removes secret-shaped strings from transcripts on the way in; a secret with no shape passes |
| Fabric operations | JSONL operations log, the board's own log beside it | Electron `userData/logs` (`ops.ts:6`, `boardMain.ts:62`) | sized by time within a byte budget; a hard ceiling while it cannot rotate (`ops.ts:25`, `:319`) | records carry codes and ids |
| Contract | DEC-0030 activity telemetry (events, batches, access log, OTLP mapping) | the receiver | `retention.raw_days` | policy keys |
| Runners themselves | their transcripts | Claude Code `~/.claude/projects` (`cleanupPeriodDays`), Codex `~/.codex/sessions`, Kimi Code `~/.kimi-code`, Hermes `~/.hermes`, Pi `~/.pi/agent`, OpenClaw `~/.openclaw` (SQLite), DeepSeek Harness `~/.dsh/sessions/*/session.v4.jsonl.zstd` | each runner's own | each runner's own; Fabric does not touch them |

### Gaps

1. No level states one logging rule: what a protocol event logs (kind, ids, outcome code, duration, sizes), where,
   for how long, and that bodies and secrets never go in. Each repository decided alone.
2. The native bridges log nothing, so a host whose context never arrives (helper missing, timeout, a refused hook)
   leaves no trace. Only Claude Code's hooks write `hooks.log`.
3. The board and the journal keep everything for ever, and their secret rule is advice. Nothing measures what a
   message carried or sweeps a secret written by mistake.
4. No reader joins the levels: a person cannot follow one request from an agent's call through `fabric-mcp`, the
   board and the responder to its completion.

### Proposal

- **Contract: `protocol-log/1`, one decision.** Every level writes JSON lines with `at`, `level`
  (agent, adapter, fabric-mcp, board, service), `event`, `requestId`/`taskId`/`sessionId` where they exist, `outcome`
  as a code, `durationMs`, `bytes`; never a body, a header, an argument value or a path under a home folder. Default
  retention: size-bounded rotation (at most 5 × 5 MB per writer) and 30 days by time, whichever comes first; the
  journal keeps milestones (work-milestone/1) for ever and traces for 30 days. One shared `requestId` crosses the
  levels, so one request reads end to end.
- **Fabric:** apply the trace retention to the journal (milestones kept); enforce the board's secret rule with the
  same redactor as transcripts (refuse or redact a secret-shaped body before it is stored, counted); a "Логи" view
  per request that joins `fabric-mcp`, board and service lines by `requestId`.
- **Adapter (FAA-379):** every host's session start writes one `hooks.log` line, `event=session-start host=<host>
  outcome=context|pointer|down|silent|failed`, through the shared helper, so the native bridges leave a trace; the
  bridges themselves write nothing (they run inside the host); `fabric_session.py logs` prints the last lines and the
  retention; the kit's `RotatingLog` gains the `protocol-log/1` fields; the retention table above goes into the skill.
- **Agents base:** the same rule as an R-row for every template, so organisation copies log the same way.

Migration: additive. A writer that does not know `protocol-log/1` keeps its own format until its next release; the
reader treats a line without `requestId` as unjoined.
