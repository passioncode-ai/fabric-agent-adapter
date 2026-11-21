# DeepSeek Harness (dsh) for Fabric: research notes, 2026-11-20

Scope: read-only research plus an isolated probe under the scratchpad (`DSH_HOME=<scratch>/dsh/home`). Nothing in the adapter repository was edited.

## 1. Install state and upstream

- Not on PATH: `command -v dsh dsh-tui` prints nothing.
- Local clone `~/DATA/deepseek-harness` sits on `master`, 15117 commits behind `origin/master` (`git status -sb`), working tree untouched. Upstream tip `2e39e70496` 2026-11-18 "Merge ... release dsh-0.2.2 rc.5 to master". Newest tag `dsh-v0.2.2-rc.5`; no stable (non-rc) tag. npm `@deepseek-ai/dsh` dist-tags `latest: 0.2.2-rc.5`, bin only `dsh`, `engines.node >=24.9.0` (machine has Node v26.10.0).
- **`dsh-tui` no longer exists.** Commit `10bb9cbf4a` (2026-08-04, before dsh-v0.1.0-rc.7) "cleanup: remove TUI package and legacy dsh entrypoints". Shipped profiles on master: `web` (default), `headless`, `acp`, `sdk`, `sdk-minimal` (`docs/cli-help.md`; bundles under `packages/bundle/`: acp-app, base, headless, sdk-app, sdk-minimal, web-app). Fabric's console catalogue `apps/desktop/src/shared/consoleCatalog.ts` (`{ id: 'deepseek-harness', program: 'dsh-tui' }`) points at a binary that cannot be installed today.
- Notable changes since b150a551b8 (0.1.1-rc.2): plugin market and Plugins page, Git-installed plugin updates (`d2bed0238e`), coded errors for plugins/hooks/MCP/skills (`98e08f2fa2` HookError, `274ca9ccb2` MCP), on-demand MCP tool loading per agent (`7e10357889`), upstream skills from pinned commits (`d25a48ac3c`), Claude Code mods bridge (`docs/subsystems/claude-code-mods.md`), plugin settings, `engines.dsh` compatibility gate for plugins.
- `~/DATA/deepseek-harness-worker` is an empty folder (an old dsh session cwd), not a repo.
- `~/.dsh` exists (Aug 2026): `settings.yaml` (`permission.defaultPreset: danger-full-access`), `.credentials.yaml` (version/refs layout, holds a `DEEPSEEK_API_KEY` ref, value not read), profiles `web`. My headless probe created `~/.dsh/profiles/headless` (dsh's own scaffold, 4 small files).

## 2. Extension model

- Everything is a Cordis plugin (`export const name`, optional `export const inject = [...]`, `export function apply(ctx, config)`), mounted from YAML patch layers. Layer order (`apps/cli/src/profile-boot.ts:205-215`): bundle layers, the profile's `cordis.patch.yml`, then the home-level `$DSH_HOME/cordis.patch.yml` (applies to every profile, outranks the profile layer), then `--patch` overlays. `$DSH_HOME` defaults to `~/.dsh`. A patch file is a top-level YAML array; `- insert: [ {id, name, config} ]` adds rows. `name` may be an absolute file path (verified: `--dump-config` shows `name: file:///.../fabric-native.mjs`).
- Session events a plugin can listen to: `agent/created` ({agent, source: 'startup'|'resume', signal}; awaited before the first turn; `packages/core/agent-loop/src/index.ts:677,748,832`), `agent/pre-step` (prompt), `tools/pre-execute`, `tools/post-execute`, `agent/turn-stopping`, `subagent/start|end`, `agent/disposed`. Context injection: `agent.inject(userMessage)` (what the hooks bridge does, `packages/experimental/hooks-claude-code/src/index.ts:212-223`).
- Claude Code hooks bridge `@deepseek-ai/dsh-hooks-claude-code` (and `dsh-hooks-codex`) runs a Claude `hooks.json`: SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop, SubagentStart/Stop. SessionStart context only from JSON `hookSpecificOutput.additionalContext` with matching `hookEventName` (plain stdout ignored: `hook-protocol/src/codec.ts:59-130`, `merge.ts:83`). `transcript_path` always `''`. **But the npm copy is stale: `dsh plugin --profile acp add @deepseek-ai/dsh-hooks-claude-code@0.0.1-rc.5` is rejected: "incompatible with dsh 0.2.2-rc.5"** (needs `allow-version --accept-risk`). It is not a dependency of the published `@deepseek-ai/dsh` (headless run: `ERR_MODULE_NOT_FOUND`).
- Claude Code mods (`defineMod`) bridge exists, experimental; not needed.

## 3. MCP

- `@deepseek-ai/dsh-mcp-client` ships with dsh. One patch row per server: `{serverName, transport: stdio|streamable-http, command, args, env, cwd | url, headers, toolLoading, failOnStartupError, expandTemplates (${credential:REF})}` (`packages/mcp/mcp-client/README.md`). Tool names `mcp__<serverName>__<tool>`. Register `fabric-mcp` for every profile: insert a row into `$DSH_HOME/cordis.patch.yml`; for one run: `--patch file.yml`. No "ignore project config" flag is needed: dsh reads no project-level MCP file (project layer = `.dsh/skills`, `AGENTS.md`/`CLAUDE.md` only).
- ACP `session/new` takes standard `mcpServers` (stdio needs an ABSOLUTE `command`: relative gave `-32602 mcpServers[0].command must be an absolute path`; HTTP with headers supported; `initialize` answers `mcpCapabilities.http: true`). An initial MCP connection failure rolls the session back.

## 4. Skills

Local provider roots (`docs/subsystems/skills.md:66-75`): `<project>/.dsh/skills`, `<project>/.agents/skills`, `customSkillDirs`, `$DSH_HOME/skills`, `~/.agents/skills` (user-agents), bundled. `~/.agents/skills` on this machine already holds working-with-fabric, adapting-projects-to-fabric, building-fabric-services, creating-fabric-agents. Instruction files: `AGENTS.md`, `CLAUDE.md`.

## 5. Headless / auth

`dsh --profile headless [--json] [--permission-mode P] [--approval-policy ask|never] "task"`; answer on stdout, `--json` for NDJSON events. Real run here failed before the model: `dsh: MISSING_CREDENTIAL: llm-deepseek: no API key for provider route "deepseek-official"` with `DSH_HOME=~/.dsh` (the Aug-2026 credential file is not accepted by 0.2.2-rc.5 headless, cause not inspected to avoid reading the secret). Observatory has no `DEEPSEEK_API_KEY` slot (`use_secret.py names` for four projects of the vault: only OpenRouter keys). So a model-visible run is blocked on a DeepSeek key in the vault (or an OpenRouter route config, untested).

## 6. ACP

`dsh --profile acp`: stable ACP v1 + session/list|resume|close, `session/request_permission` with one-shot allow/reject; **no modes** (`session/set_mode` unsupported), no terminals/plans/elicitation (`packages/acp/acp/README.md:64-82`). Model and `reasoning_effort` are session config options (`configOptions` in the session/new answer: model `["deepseek-official","deepseek-v4-flash"]`, effort default `high`). This is the same shape Fabric already drives for Kimi Code (`acp-session` with HTTP MCP) minus modes.

## 7. Limits

LLM failure codes (`packages/llm/llm/src/error.ts`): `RATE_LIMIT` (retryable), `QUOTA` (exhausted quota or balance), `ACCOUNT_QUOTA` (first-party account tokens, replenished on the billing page), `CONTEXT_WINDOW_EXCEEDED`, `MISSING_CREDENTIAL`, `HTTP_<n>`. Printed as `dsh: <CODE>: <message>` on stderr in headless (seen for MISSING_CREDENTIAL).

## Probe (keyless, isolated DSH_HOME)

Command: `DSH_HOME=<scratch>/dsh-home python3 -I acp_client.py <scratch> <scratch>/node_modules/.bin/dsh --profile acp` with `<scratch>/dsh-home/cordis.patch.yml` = `- insert: [ {id: fabric-agent-adapter, name: '<scratch>/fabric-native.mjs'} ]`, `session/new {cwd, mcpServers:[stdio probe, absolute python3]}`.
Result: `initialize` ok (`agentInfo deepseek-harness-acp 0.0.1`, `mcpCapabilities.http: true`), `session/new` ok with the stdio MCP server connected, `session/close` ok; the native plugin's marker: `{"event":"agent/created","source":"startup","injected":"yes","sessionCwd":"<scratch>/dsh/work"}` (session cwd via `inject = ['workingDirectory']`, `ctx.workingDirectory.ensure(agent, signal)`). No model call, no spend. Not proven: that the model sees the injected text (needs a credential).

## Integration spec: `install-host-hooks --host deepseek-harness`

Use a native Cordis plugin, not the hooks bridge (stale on npm, incompatible).

- Destination: loader `$DSH_HOME/plugins/fabric-agent-adapter.mjs` (default `~/.dsh/plugins/`), managed marker line like the OpenCode and Pi loaders; it imports `../context.mjs`-equivalent by absolute path to the installed skill's `scripts/hosts/context.mjs` (as the other loaders resolve the helper) or embeds the helper path.
- Registration: append one managed block to `$DSH_HOME/cordis.patch.yml` (create it as a one-entry array when absent; accept an existing `[]` or block-sequence file and append; refuse flow-style or non-array YAML without guessing, as the OpenClaw JSON5 refusal does):
  ```yaml
  # fabric-agent-adapter: managed, remove with install-host-hooks --host deepseek-harness --remove
  - insert:
      - id: fabric-agent-adapter
        name: '/Users/<you>/.dsh/plugins/fabric-agent-adapter.mjs'
  ```
  Home level applies to web, headless and acp profiles. Removal deletes the block by its id and marker and the loader file.
- Loader shape:
  ```js
  import { randomUUID } from 'node:crypto'
  import { readContext } from '<skill>/scripts/hosts/context.mjs'
  export const name = 'fabric-agent-adapter'
  export const inject = ['workingDirectory']
  export function apply(ctx) {
    ctx.on('agent/created', async ({ agent, source, signal }) => {
      if (source !== 'startup') return            // resume keeps its history
      const cwd = await ctx.workingDirectory.ensure(agent, signal ?? new AbortController().signal)
      const text = await readContext('deepseek-harness', cwd, { fabricRegistered })
      if (text) agent.inject(Object.freeze({ id: randomUUID(), role: 'user',
        content: [{ type: 'text', text }], source: { kind: 'fabric-agent-adapter' } }))
    })
  }
  ```
  Never throw out of the listener (a throw would block the first turn); `readContext` already returns null on failure/timeout.
- Event: `agent/created` (root agents, awaited before first turn). Not raised for subagents.
- Fabric registration: `fabricRegistered` = a `@deepseek-ai/dsh-mcp-client` row with `serverName: fabric` in the composed config, or for Fabric-launched ACP sessions the `mcpServers` Fabric passes. Simplest robust check at runtime: the tool registry has `mcp__fabric__fabric_whoami` (needs `inject: ['tools']`; API not verified here) else false, and the Python helper decides as for other hosts.
- MCP registration for a person's own sessions: `install-host-hooks` may offer (dry-run first) a second managed row `{id: fabric-mcp, name: '@deepseek-ai/dsh-mcp-client', config: {serverName: fabric, transport: stdio, command: <absolute fabric-mcp>, args: ['--runner','deepseek-harness']}}`.
- Fabric side (board request to Fabric): replace `program: 'dsh-tui'` (removed upstream 2026-08-04) with `dsh` (`web` profile opens a browser UI, not a terminal) or, better, a core `acp-session` descriptor `{program: 'dsh', acp: {args: ['--profile','acp']}}` with HTTP MCP like Kimi Code; no ACP modes, so permission = `session/request_permission` answers only; model via `session/set_config_option`.
