# Hook compatibility: 31 requested hosts

Evidence cut: 2026-10-16. Scope is the 30 IDs in Switchboard `catalog/agents.json` (catalog change `db748f2d471570419c2fb0b62f1c53b1295dc241`, refreshed origin/main checked) plus TabbyML/tabby. Catalog support means MCP/proxy/launch capability, not hook equivalence. The supplied stars/license table is not used as acceptance evidence.

“Native fixture” means the actual installed/pinned host loaded or parsed the adapter in an isolated no-model test. It does not mean account setup, all lifecycle events or live Fabric admission. “Contract checked” means the linked primary-source survey, not a working installed adapter. CLI absence is a PATH observation, not a machine-wide uninstall claim.

| Host ID | Checked hook/context route | Result and evidence |
|---|---|---|
| `claude-code` | Plugin SessionStart JSON; existing feature-gated lifecycle | Existing plugin + native schema checks; [native adapters](../../../../plugins/fabric-agent-adapter/skills/working-with-fabric/references/native-host-hooks.md). Final native receipt in handoff |
| `codex` | SessionStart JSON | Native 0.162.1 reproduces old failure and accepts corrected context; [parser receipt](codex.md) |
| `hermes` | Native frozen prompt section | Native 0.21.4 / 2026.9.21 fixture passed; [module](hermes.md) |
| `opencode` | Native system transform | Native 1.19.0 loader/context fixture passed; [module](opencode-pi.md) |
| `openclaw` | `before_prompt_build` / `prependContext` | Native 2026.10.4 isolated runtime fixture passed; global executable absent; [module and permission negatives](openclaw.md) |
| `pi` | `before_agent_start` structured prompt | Native 1.1.0 loader/context fixture passed; [module](opencode-pi.md) |
| `kimi-code` | Existing `[[hooks]]` SessionStart command | Installed 2.1.1, adapter regression tests retained; current native stdout consumption not exercised. [Official hook contract](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/hooks.html) distinguishes observational events from blocking ones |
| `gemini-cli` | SessionStart JSON `hookSpecificOutput.additionalContext` | Installed 0.63.0; contract checked, no new adapter/native runtime claim. [Official reference](https://geminicli.com/docs/hooks/reference/#sessionstart) requires JSON stdout, timeout milliseconds, startup advisory |
| `cursor-cli` | `sessionStart`, top-level `additional_context` | Installed 2026.09.02-c22c1a3; contract checked, not native-probed. [Official hooks](https://cursor.com/docs/hooks) use a versioned lowercase event map, not Claude's event spelling |
| `cline` | TaskStart/Resume; `contextModification` | Contract checked, CLI absent; CLI blocking differs from VS Code. [Survey](catalog-hermes-group.md) |
| `aider` | Read-only context files / response notification | No general startup-hook contract established; CLI absent. [Survey](catalog-hermes-group.md) |
| `goose` | Open Plugins observer SessionStart; `.goosehints` for context | Installed 1.44.0; observer output is not established as model context. [Survey](catalog-hermes-group.md) |
| `freebuff` | Knowledge files and custom agent `handleSteps` | No general startup-hook contract established; CLI absent. [Survey](catalog-hermes-group.md) |
| `command-code` | Native SessionStart JSON | Contract checked, CLI absent, no adapter/runtime claim. [Survey](catalog-hermes-group.md) |
| `deepseek-harness` | Optional Claude-command compatibility bridge | Contract checked, CLI absent; bridge activation required. [Survey](catalog-hermes-group.md) |
| `zcode` | Native enabled `hooks.events.SessionStart` | Contract checked, CLI absent; timeoutMs differs. [Survey](catalog-hermes-group.md) |
| `auggie` | Native SessionStart script-path contract | Contract checked, CLI absent; arbitrary command strings are not equivalent. [Survey](catalog-hermes-group.md) |
| `kilo` | Native plugin system transform | Installed 7.4.17; contract checked, no new adapter/native-probe. [Survey](catalog-opencode-group.md) |
| `zed` | Personal/project instructions, external agent adapters | No executable startup context hook established; local CLI/app absent at checked paths. [Survey](catalog-opencode-group.md) |
| `tabby` | TabbyML server/API/indexed context | Not an equivalent interactive session hook; CLI absent, no fake hook config. [Survey](catalog-opencode-group.md) |
| `omp` | Native extension `before_agent_start` | Contract checked, CLI absent; Pi structure not assumed. [Survey](catalog-opencode-group.md) |
| `continue` | Native CLI SessionStart JSON plus shared Claude config | Contract checked, CLI absent; duplicate shared-loader risk recorded. [Survey](catalog-opencode-group.md) |
| `crush` | Only PreToolUse documented in inspected hook guide | Startup context unsupported by inspected contract; CLI absent. [Survey](catalog-opencode-group.md) |
| `amp` | Native `agent.start` plugin message | Contract checked, CLI absent; no continuation hook installed. [Survey](catalog-opencode-group.md) |
| `openhands` | Current SDK/CLI hook context | Contract checked, CLI absent; old/new runtime distinction preserved. [Survey](catalog-openclaw-group.md) |
| `qwen-code` | SessionStart context | Contract checked, CLI absent; no adapter/native claim. [Survey](catalog-openclaw-group.md) |
| `copilot-cli` | SessionStart top-level `additionalContext` | Contract checked, CLI absent; older tutorial contradicted by reference. [Survey](catalog-openclaw-group.md) |
| `factory-droid` | SessionStart JSON | Contract checked, CLI absent; no adapter/native claim. [Survey](catalog-openclaw-group.md) |
| `warp` | AGENTS.md / Rules | Installed surface observed; no native lifecycle context hook established. [Survey](catalog-openclaw-group.md) |
| `kiro-cli` | V3 SessionStart versus legacy agentSpawn | Contract checked, CLI absent; no false cross-version parity. [Survey](catalog-openclaw-group.md) |
| `devin` | Claude-compatible user/project hooks | Contract checked, CLI absent; shared settings may duplicate hooks. [Survey](catalog-openclaw-group.md) |

## Outstanding capability boundaries

The six requested native mechanisms have implementation or retained native plugin coverage. Extra hosts were requested for checking and are checked above; the survey does not install 24 additional runtimes or create speculative adapters. A future implementation should begin with the installed Kilo/Gemini/Cursor contracts, then observer/file-context hosts with a separate integration decision. Automated reload of an active app, Fabric enrollment and account consent are not supplied by hook files.

The current task's Fabric tool answered `no-project` after an earlier credential-check outage: the active tool session's folder is not enrolled as a Fabric project. This is an admission prerequisite, not a hook parser failure. No Fabric claim or cross-project board delivery was asserted.
