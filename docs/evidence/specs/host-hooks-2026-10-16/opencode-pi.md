# OpenCode and Pi native context adapters

As of 2026-10-16. Scope: context injection only. Registration, native loading and actual Fabric admission are separate evidence layers. No model calls or Fabric enrollment were made by these probes.

## Contracts

| Host | Verified runtime | Native contract and discovery |
|---|---|---|
| OpenCode | `opencode --version`: `1.19.0` | Async plugin factory returns `experimental.chat.system.transform(input, output)`, where `output.system` is a mutable string array. Local `.opencode/plugins/` and global `~/.config/opencode/plugins/` load JS/TS files. Bundled `.mjs` entry is imported by a `.js` installation shim. |
| Pi | Installed `@earendil-works/pi-coding-agent/package.json`: `1.1.0` | Default extension factory registers `before_agent_start`. `event.systemPromptOptions.sections` is mutable; `forceSystemPrompt` overrides those sections. Global `~/.pi/agent/extensions/`, project `.pi/extensions/`, and explicit extension paths are supported. A `.js` shim imports the bundled `.mjs` entry. |

Primary sources:

- [OpenCode plugin docs](https://opencode.ai/docs/plugins/): discovery, factory, load order. Local and npm variants are not automatically the same plugin.
- [OpenCode 1.19.0 hook types](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/plugin/src/index.ts#L291): transform input/output.
- [OpenCode 1.19.0 loader](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/opencode/src/plugin/index.ts#L103): every legacy module export is treated as a factory; entry files export only `default`.
- [OpenCode 1.19.0 CLI](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/opencode/src/cli/effect-cmd.ts): `debug config` initializes native plugins and disposes the instance. `debug startup` only prints a timing number and is not loading evidence.
- [Pi official extension docs](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md). Installed 1.1.0 declarations `dist/core/extensions/types.d.ts:708`, `dist/core/system-prompt.d.ts`, loader `dist/core/extensions/loader.js:550`, runner `dist/core/extensions/runner.js:1121` were checked directly.

## Implementation boundaries

`scripts/hosts/context.mjs` calls `python3 -S scripts/fabric_session.py hook session-start --host <host>` without a shell. JSON stdin contains cwd and, only when explicitly provided as true by an embedding host, `fabric_registered`. It does not transmit prompts, full configuration, credentials or messages. Deadline is at most four seconds, each output buffer at most 64 KiB; missing executables/scripts, nonzero exits, control output and timeouts produce no context. Python owns Fabric-launched suppression, registration and unavailable-service notices.

OpenCode preserves existing system strings and checks the stable adapter marker before appending. Its native `config` hook observes only whether resolved `mcp.fabric` is a non-disabled, shaped local/remote entry; only the boolean crosses into Python. Pi checks `getAllTools()` for the exact callable names `fabric_whoami` or `mcp__fabric__fabric_whoami`. No similarly named server or tool qualifies. An absent/not-yet-connected tool registry yields no registration claim. Pi writes one named section, preserves other sections, and appends once to an earlier forced prompt. A legacy Pi event without structured options receives a replacement containing the original prompt plus context. No factory starts resident work. Neither adapter observes turn completion or releases claims; those require separate proven runtime identity contracts.

Pi `mcp.json` registration does not prove callable tools: `--no-mcp`, disabled builtin MCP, or a replacement `/mcp` extension can disable connections. `getMcpServers()` includes extension registrations, not all builtin file registrations. These adapters do not infer admission from registration.

## Focused checks

`node --test test/host-hooks-opencode-pi.test.mjs`: **13 focused cases**, plus **two optional native cases**. Before implementation this command failed because the new helper module was absent. Cases verify JSON stdin and shell metacharacters, missing executable/script, nonzero output, timeout, buffer limit, control characters, malformed host objects, existing prompt preservation, duplicate injection including service-only context without a preamble marker, Pi structured/forced/legacy prompts, graceful context failure, and affirmative/disabled/unknown registration observations.

Pi native no-model probe through the installed `loadExtensions(paths, cwd)` returned:

```json
{"host":"pi","version":"1.1.0","nativeLoader":true,"extensions":1,"errors":0,"handlers":1,"contextInjected":true,"modelsCalled":0}
```

The probe copied the actual adapter/helper into an isolated temporary bundle and supplied a neutral fixture Python context generator. It exercised Pi's native loader and the registered callback, not a provider request or actual Fabric admission. Temporary files were removed.

OpenCode isolated probe initially timed out before a receipt (55 seconds). Its native bootstrap installs `@opencode-ai/plugin` in empty config directories; source `packages/core/src/npm.ts:147` exposes this dependency step. A later machine check also found disk pressure (116 MiB free); neither cause alone was established. The bounded probe used isolated HOME/XDG directories, disabled updates/model fetching/default plugins, no model or MCP configuration, and cleaned its temporary files.

The subsequent offline bootstrap probe passed. It pre-created an empty `node_modules` and lockfile root declaring `@opencode-ai/plugin`; the pure-JS adapter imports no SDK, so no package or registry call is needed for this probe. Native OpenCode initialized both the installation-shaped `.js` re-export shim and a fixture probe, with no plugin-load errors. The probe invoked the real returned transform twice and asserted one insertion with existing context preserved.

Runnable probes are in the same test file, enabled explicitly:

```sh
FAA_PI_LOADER=/path/to/pi-coding-agent/dist/core/extensions/loader.js \
FAA_OPENCODE_BIN=/path/to/opencode \
node --test test/host-hooks-opencode-pi.test.mjs
```

Two native-inclusive runs passed 14 cases; a subsequent service-only duplicate regression was added and fixed. Final run: **15 passed, 0 failed, 0 skipped** on the recorded installed versions, including Pi's actual `.js` re-export shim and OpenCode plugin-load diagnostics. `git diff --check` also exited 0. This proves loader acceptance and fixture context transformation, not live Fabric admission. The optional tests skip when runtime paths are not supplied; ordinary repository CI does not claim native-host coverage from those skips.

The managed shims in `scripts/host_hooks.py` use absolute file URIs and preserve relative imports inside the bundled adapter. They export only the default factory. Existing sessions must reload extensions or restart under their normal host lifecycle; installation itself does not mutate a running extension runtime. Pi supports `/reload`; OpenCode startup loading requires a new instance/session host as appropriate.
