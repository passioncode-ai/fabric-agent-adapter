# Handoff — FAA-18: `working-with-fabric` and the Claude Code session hooks (0.10.0)

Date: 2026-10-11. Branch `agent/working-with-fabric-20261011` from `origin/main` `7e45e6b`; [PR #53](https://github.com/passioncode-ai/fabric-agent-adapter/pull/53). Entry point: the
[spec](../evidence/specs/2026-10-11-working-with-fabric.md).

## Objective

Fabric 0.4.0 REQ-07 (plan canvas C4; COM-04, whose owner is this repository; Q-04): a coding agent opened in a
terminal works in a project through Fabric, and Claude Code sessions are enrolled, journalled (no content) and ended
through a hook pack.

## Done

- `plugins/fabric-agent-adapter/skills/working-with-fabric/` — `SKILL.md`, `references/session-hooks.md`,
  `scripts/fabric_session.py` (`status`, `hook session-start|stop|session-end`, `deliver`).
- `plugins/fabric-agent-adapter/hooks/hooks.json` — SessionStart, Stop and SessionEnd entries beside the
  dashboard-kit notice.
- Evals first: `test/evals/working-with-fabric/triggers.json` (22, English and Russian), `scenarios.json` (7).
- `test/test_fabric_session.py` (29 tests); `test/validate.py` checks four skills; version 0.10.0 everywhere;
  README, AGENTS.md (LC-09 footprint with measured timings), SKILL-CARD, CHANGELOG, backlog FAA-18.
- Evidence: [raw/mcp-server-env.log](../reports/2026-10-11-working-with-fabric/raw/mcp-server-env.log) (an MCP
  stdio server gets `CLAUDE_CODE_SESSION_ID`), [raw/hook-timing.log](../reports/2026-10-11-working-with-fabric/raw/hook-timing.log),
  [raw/gates.log](../reports/2026-10-11-working-with-fabric/raw/gates.log),
  [raw/planted-defects.log](../reports/2026-10-11-working-with-fabric/raw/planted-defects.log).

## Decisions

- The Stop and SessionEnd hooks never start their own `fabric-mcp` session: a closed connection does not end an
  enrolled session and Fabric ends a binding's oldest live session past eight (ADR-0134 amendment 2), so a per-turn
  hook would end the agent's own session. They act only when `hub.json` advertises `session-hooks/1`, through
  `fabric-mcp --rejoin-only --runtime-session-id <id>`; until then they read `hub.json` and return.
- The planned `fabric_work_*` tools are named as planned and marked Fabric 0.4.0; the skill falls back to
  `fabric_task_claim` / `fabric_task_release` on an older Fabric.
- No Codex hooks ship (unverified); the skill gives the MCP entry and first-prompt advice.

## Open

- **Fabric side (D1–D5 in the spec)** — until all ship, Stop/SessionEnd are inert: `fabric-mcp` enrolls with
  `runtimeSessionId` from `CLAUDE_CODE_SESSION_ID`; `--rejoin-only --runtime-session-id`; `hub.json`
  `"features": ["session-hooks/1"]`; `fabric_session_observe`; `fabric_work_release {claims: "session"}`.
- The release: merge the PR after CI, then the `v0.10.0` tag (the release flow; not done here by instruction).
- A live check against a real Fabric 0.4.0 once D1–D5 land: a real Claude Code session in a terminal, journal rows
  `session.turn.observed@1` and `session.ended@1` (REQ-07's own evidence).
- The Windows and Linux `<Fabric>/bin` defaults are electron-builder's (`%LOCALAPPDATA%\Programs\Fabric`,
  `/opt/Fabric`); Fabric's wave 7 writes the per-OS setup paths — re-check the skill's table then.

## Checks run

See [raw/gates.log](../reports/2026-10-11-working-with-fabric/raw/gates.log): `python3 test/validate.py`, the Python
suite, the Node suite, both `claude plugin validate --strict`.

## Next task

Fabric: implement D1–D5 and advertise `session-hooks/1`; then, here, run the live REQ-07 check above and record it.
