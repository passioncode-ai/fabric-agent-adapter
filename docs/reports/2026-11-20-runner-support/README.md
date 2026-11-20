---
report: runner-support-and-protocol-revision
project: fabric-agent-adapter
date: 2026-11-20
task: FAA-370 (owner's brief of 2026-11-20, CEO window session 53895bdc, package 2 and the protocol part of package 1)
---

# Runner support and the protocol revision, 2026-11-20

Asked by the owner in Fabric's CEO window on 2026-11-20 (brief
`~/Library/Application Support/@fabric/desktop/ceo/inbox/2026-11-20-fabric-focus-protocol-backup-billing-brief.md`):
review the Fabric protocol for load on agents, propose a UI that moves only on milestones, build a support matrix of
the coding agents with real runs, and bring the top (Claude Code, Codex, Hermes, OpenClaw, Pi, Kimi, DeepSeek Harness)
to full support.

## What is in this folder

| File | What |
|---|---|
| [protocol-revision.md](protocol-revision.md) | Inventory of every agent obligation and automatic event, the redundant load with file:line evidence, the milestone-only proposal and its migration. Read at contract `4c978495`, Fabric `c6925be4`, adapter `006f33b6` |
| [deepseek-harness-research.md](deepseek-harness-research.md) | DeepSeek Harness 0.2.2-rc.5: upstream changes since the local clone, its Cordis plugin model, MCP, skills, ACP, limits, the integration spec this release implemented |
| [raw/](raw/) | One file per runner and round: the command, the version, the answer, the exit code. Keys only by name |
| The matrix | [`runner-support.json`](../../../plugins/fabric-agent-adapter/skills/working-with-fabric/references/runner-support.json) and [`runner-support.md`](../../../plugins/fabric-agent-adapter/skills/working-with-fabric/references/runner-support.md), shipped in the skill so Fabric reads them from the installed package |

## The matrix in one line each

Fully supported (real runs: `fabric_whoami`, `com.status` ready, `fabric_work_list`): Claude Code 2.1.329, Codex
0.169.0, Hermes 0.22.2, Pi 1.1.0. Supported with a gap: Kimi Code 2.5.3 (own terminal lists only `fabric_whoami`),
OpenClaw 2026.10.4 (`fabric_whoami` cut at 16,000 characters), DeepSeek Harness 0.2.2-rc.5 (Fabric starts `dsh-tui`,
gone upstream; tool-list race), Kilo 7.4.17 (board not run). Not checked: OpenCode, Cline and the other 18 consoles.

## Findings that change what someone else builds

1. **Fabric changes its tool list after admission.** Kimi Code never takes the change (raw `round2-kimi-code.txt`:
   "the fabric MCP server tools available are only fabric_whoami"); DeepSeek Harness re-syncs and loses
   `fabric_whoami` for a moment (`round2-deepseek-harness.txt`, and a third run: `ToolNotFoundError UNKNOWN_TOOL`).
   One stable list from the first `tools/list`, with a typed refusal before admission, fixes both. Owner: Fabric.
2. **`fabric_whoami` is about 28 KB** (protocol revision §b, measured; rules 11,890 bytes, 61 `machine_agents`).
   OpenClaw cuts tool results at 16,000 characters (`DEFAULT_MAX_LIVE_TOOL_RESULT_CHARS = 16e3` in its dist), and
   `project` comes last, so the agent never learns its project. Owner: Fabric (project and protocol first, rules core
   about 3 KB, the rest on request).
3. **Fabric's catalogue names `dsh-tui`**, removed by DeepSeek Harness in `10bb9cbf4a` (2026-08-04); `fabric-mcp
   --runner deepseek-harness` refuses ("not installed on this computer as Fabric sees it"). Owner: Fabric (`dsh`, or a
   core `acp-session` row `dsh --profile acp` with HTTP MCP like Kimi Code). Interim here: a `dsh-tui -> dsh` link
   (FAA-372 takes it out).
4. **A worktree under `~/DATA/_worktrees/` enrolled into another project.** Claude Code run from
   `~/DATA/_worktrees/faa-runner-support` (a worktree of this repository) answered project `ai-image-maker-app`; the
   same run from the main checkout answered `fabric-agent-adapter` (`raw/claude-code.txt`). Owner: Fabric.
5. **The home screen re-sorts on every turn** (protocol revision §a: `App.tsx:845` re-reads on every work, task,
   agent and session record; `agentWork.ts:45-60` sorts by the freshest of stage, heartbeat, turn, console output).
   The proposal: six milestones (`task.started`, `step.finished`, `waiting.started`, `waiting.cleared`,
   `task.finished`, `task.released`) derived by Fabric from calls agents already make; everything else to the journal
   and a live feed. Owners: the contract (a `work-milestone/1` decision), Fabric (sort modes, live feed, cadences),
   the adapter (FAA-371).

## What this release changed in the adapter

`install-host-hooks --host deepseek-harness` (a Cordis plugin on `agent/created`, injected as the session's first
user message; one managed block in `$DSH_HOME/cordis.patch.yml`), the matrix data and page, the full runner list
`fabric-mcp` takes in Fabric 0.3.26 and each host's registration line in the skill's Step 2.

## On this machine, 2026-11-20

`fabric-mcp` registered for Pi (`~/.pi/agent/mcp.json`) and OpenClaw (`~/.openclaw/openclaw.json`); DeepSeek Harness
installed (`npm install -g @deepseek-ai/dsh@0.2.2-rc.5`) with the link `dsh-tui -> dsh`. The DeepSeek Harness runs used
an isolated home in the session's scratch folder; the person's own `~/.dsh` gets the hook from the installed skill
after the release.

## Not done here, and why

- No `fabric_question_ask` call from any runner: it would put a question to the operator.
- No usage limit was hit, so no runner's limit handling was observed.
- Kimi Code's and Hermes' launch from Fabric over ACP was not run today; their rows cite Fabric's earlier probes.
