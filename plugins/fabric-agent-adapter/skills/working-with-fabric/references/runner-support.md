# Runner support: which coding agents work with Fabric (FAA-370)

The data is [runner-support.json](runner-support.json) (`runner-support/1`), the source Fabric's «Полностью
поддерживаются / Не проверены» section reads. Measured on 2026-11-20 against Fabric 0.3.26 with adapter 0.101.0. A
verified check is a real run with a model: the agent, in a checkout of a Fabric project, called `fabric_whoami`, the
board's `com.status` and `fabric_work_list`, and answered from what came back. A `--runner` name Fabric accepts, or a
launch, is not support on its own. The raw runs are in the adapter repository under
`docs/reports/2026-11-20-runner-support/raw/`.

## Fully supported

| Runner | Version | Fabric starts it | `fabric-mcp` and board | Startup context | Notes |
|---|---|---|---|---|---|
| Claude Code | 2.1.329 | connected (`--mcp-config`) | run: whoami, board ready, work list | plugin hooks, and the turn hooks | the only runner whose turns reach Fabric |
| Codex | 0.169.0 | connected (`CODEX_HOME` config) | run: whoami, board, work list | `hooks.json` SessionStart | once in three runs the model said the tool was absent without calling it |
| Hermes Agent | 0.22.2 | connected (ACP, stdio bridge) | run: whoami, board, work list | native plugin `fabric.context` | a CEO runner |
| Pi | 1.1.0 | a console; its own `fabric-mcp` | run: whoami, board, work list | extension `before_agent_start` | registered here on 2026-11-20 with `pi mcp add`; no model key of its own here |

## Supported with a gap

| Runner | Version | What works | The gap, and whose fix it is |
|---|---|---|---|
| Kimi Code | 2.5.3 | whoami answered; Fabric's ACP launch connects (Fabric's probe) | in its own terminal it lists only `fabric_whoami`: it does not take Fabric's `tools/list_changed` after admission, so the board and work tools are absent. Fabric: keep one tool list from the first `tools/list` |
| OpenClaw | 2026.10.4 | board ready, work list; context plugin loaded | `fabric_whoami`'s answer (about 28 KB) is cut at 16,000 characters, so the project and the rules are lost. Fabric: project first, a shorter answer |
| DeepSeek Harness | 0.2.2-rc.5 | context hook (new, `install-host-hooks --host deepseek-harness`), whoami, board, work list | Fabric's catalogue starts `dsh-tui`, which dsh removed on 2026-08-04: `fabric-mcp` refuses until Fabric names `dsh` (an interim `dsh-tui -> dsh` link made the runs pass); `fabric_whoami` read as an unknown tool in two of three runs while Fabric changed the tool list. Fabric for both |
| Kilo Code | 7.4.17 | whoami with the session config Fabric gives it | the board was not run; no startup context hook |

## Not checked

OpenCode (a context hook exists, `fabric-mcp` is not registered here), Cline (Fabric: not connected), and every other
console in Fabric's catalogue: Gemini CLI, Goose, Cursor CLI, Aider, Amp, Crush, Qwen Code, GitHub Copilot CLI, Factory
Droid, Kiro CLI, Devin CLI, Continue, Command Code, Auggie CLI, Freebuff, omp, ZCode, OpenHands CLI.

## Registering `fabric-mcp` per runner

No secret in any entry; `<Fabric>` is the app's `bin` folder (Step 0 of the skill).

| Runner | Registration |
|---|---|
| Claude Code | `claude mcp add --scope user fabric -- "<Fabric>/bin/fabric-mcp" --runner claude-code` |
| Codex | `codex mcp add fabric -- "<Fabric>/bin/fabric-mcp" --runner codex` |
| Kimi Code | `~/.kimi-code/mcp.json`: `mcpServers.fabric` = `{"command": "<Fabric>/bin/fabric-mcp", "args": ["--runner", "kimi-code"]}` |
| Pi | `pi mcp add fabric -- "<Fabric>/bin/fabric-mcp" --runner pi` |
| OpenClaw | `openclaw mcp set fabric '{"command":"<Fabric>/bin/fabric-mcp","args":["--runner","openclaw"]}'` |
| Hermes | `mcp_servers.fabric.command` (and `args: [--runner, hermes]`) in `~/.hermes/config.yaml` |
| DeepSeek Harness | a `@deepseek-ai/dsh-mcp-client` row in `~/.dsh/cordis.patch.yml` ([native hooks](native-host-hooks.md)) |

The runner names Fabric 0.3.26 takes: `claude-code`, `codex`, `kilo`, `hermes`, `cline`, `kimi-code`, `opencode`,
`gemini-cli`, `goose`, `cursor-cli`, `pi`, `openclaw`, `aider`, `amp`, `crush`, `qwen-code`, `copilot-cli`,
`factory-droid`, `kiro-cli`, `devin`, `continue`, `command-code`, `auggie`, `freebuff`, `omp`, `zcode`,
`deepseek-harness`, `openhands`.

## Not run for any runner

`fabric_question_ask` sits on the same surface as the tools above, but a call puts a question to the operator, so no
probe made one. Limits: Claude Code and Codex go through Switchboard's usage; DeepSeek Harness prints `RATE_LIMIT`,
`QUOTA` and `ACCOUNT_QUOTA`; no runner's limit was hit in these runs.

## Run it again

Register `fabric-mcp` for the runner (the skill's Step 2), then from a Fabric project's checkout, outside a session
Fabric launched (`FABRIC_LAUNCHED_SESSION` unset), give the runner this one prompt and keep its answer: «Use the Fabric
MCP tools, once each and in this order: fabric_whoami; then com.status; then fabric_work_list. Reply with one line
only: "OK whoami=<project.name> board=<board.state> work=<number of claims listed>", writing ERR for any part that
failed or was absent.» Update the JSON's `measuredAt`, the versions and the states from what came back.
