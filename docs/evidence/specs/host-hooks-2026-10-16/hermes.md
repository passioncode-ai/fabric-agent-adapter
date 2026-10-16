# Hermes native context adapter

Scope: RM-05 / HH-2, HH-4. The adapter registers a cache-safe system prompt section; it does not claim Claude lifecycle parity, board admission, or an automatic task watcher.

## Contract evidence

Verified installed distribution: Homebrew `hermes-agent/2026.9.21_2`, Python module `hermes_cli.__version__ = 0.21.4`, `__release_date__ = 2026.9.21`. Source references below are relative to that distribution's `libexec/lib/python3.13/site-packages/`.

| Contract | Installed source |
|---|---|
| User plugin directory and opt-in, with explicit disabled taking precedence | `hermes_cli/plugins_discovery.py:81`, `:141`, `:180` |
| Native `register(ctx)` loader and isolated plugin errors | `hermes_cli/plugins_loader.py:265` |
| Readonly plugin setting lookup | `hermes_cli/plugins.py:257` |
| Bounded system prompt section registration | `hermes_cli/plugins.py:940` |
| Session info contains cwd; render once and restore persisted prompt | `agent/system_prompt.py:86`, `:112` |
| Deterministic rendering, empty/error/over-budget text skipped | `hermes_cli/plugins_dispatch.py:452` |
| `on_session_start` fires after prompt build; return ignored | `agent/conversation_loop.py:761` |
| `pre_llm_call` context is ephemeral user-message context | `agent/turn_context.py:730` |

Official versioned sources were checked on 2026-10-16: [plugin API](https://github.com/NousResearch/hermes-agent/blob/v2026.9.21/hermes_cli/plugins.py), [system prompt](https://github.com/NousResearch/hermes-agent/blob/v2026.9.21/agent/system_prompt.py), [discovery](https://github.com/NousResearch/hermes-agent/blob/v2026.9.21/hermes_cli/plugins_discovery.py). Installed line offsets differ from the tag. The [current hook guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/hooks.md) also distinguishes gateway-only `HOOK.yaml` hooks from CLI-capable plugins.

## Behavior and installation contract

Source: `plugins/fabric-agent-adapter/skills/working-with-fabric/scripts/hosts/hermes/`.

- Hermes must discover this as user plugin `fabric-agent-adapter` and have it in `plugins.enabled`. Preserve unrelated entries and explicit disables.
- `register()` creates only `fabric.context`, positioned `after_memory`, capped at 4,000 characters. Hermes freezes it into the session prompt.
- The section invokes the shared helper via Python `-S`, no shell, stdin `{cwd, fabric_registered}`, host `hermes`, with a four-second deadline and discarded stderr. A reader caps buffered stdout at 16,001 bytes and kills the owned subprocess group when output exceeds 16,000 bytes; stdin is capped at 4,096 bytes. The registration boolean comes from native `load_config_readonly()` and `mcp_servers.fabric`; no server configuration or credentials leave the process. Missing helper, failed subprocess, invalid metadata/output, and timeout return empty context.
- When the directory is copied outside its package hierarchy, set the absolute nonsecret helper path in `plugins.entries.fabric-agent-adapter.settings.session_script`. In the package hierarchy the default is `../../fabric_session.py` relative to this module's directory.
- A frozen section can describe startup state only. Later Fabric availability changes require a new/rebuilt session prompt. The plugin does not alter tools, approvals, providers, messages, models, registrations, services, or files.
- Shared helper Fabric-launched-session guards remain root-owned integration requirements. Registration is not live connection or admission.

Native configuration commands, supported by `hermes_cli/plugins_cmd.py:1108` and `hermes_cli/config.py:3443`, `:3620`:

```sh
hermes config set plugins.entries.fabric-agent-adapter.settings.session_script /absolute/package/scripts/fabric_session.py
hermes plugins enable fabric-agent-adapter
# Removal, only for state introduced by this installation:
hermes plugins disable fabric-agent-adapter
hermes config unset plugins.entries.fabric-agent-adapter.settings.session_script
```

Enable merges the enabled/disabled sets; it does not replace unrelated plugin entries. This manifest requests no external dependencies or privileged capabilities. Native enable takes effect next session.

## Checks actually run

`python3 -m unittest discover -s test -p test_hermes_host.py -v`: initial pre-implementation run failed because adapter was absent; final implementation run passed all eleven tests. Tests exercise actual helper execution, argv/stdin protocol, native registration shape and disable handling, missing/relative paths, malformed metadata/output, nonzero exit, timeout, OS/decode errors, old API absence, excessive input and real infinite-output/sleeping subprocesses.

Native no-model probe used the installed Hermes Python, a temporary HOME/HERMES_HOME, an empty bundled-plugin directory, project plugins disabled, and a JSON-compatible YAML config enabling only the copied adapter with a fixture helper. It invoked the real `PluginManager.discover_and_load()`, `render_system_prompt_sections()` and `unload()`. Assertions proved one enabled adapter, one matching text section and no section after unload. Process exit 0, stderr empty:

```json
{"version":"0.21.4","release":"2026.9.21","native_discovery":true,"prompt_section_render":true,"native_registration_bool":true,"unload":true,"model_calls":0}
```

This proves native discovery and section delivery with fixture context, not live Fabric MCP admission or a paid model turn. No global Hermes config was written by this module work.

Replay the isolated native check with the installed Hermes runtime interpreter (path supplied by the caller):

```sh
python3 test/native/hermes_hooks.py --python /path/to/hermes/runtime/python3
```

The final bounded reader implementation passed this same native probe with empty stderr. The isolated probe writes only under a temporary home and uses a fixture MCP declaration that is never connected.

## Current-runtime follow-up

The installed host changed during final delivery: Homebrew 0.21.4 was replaced on PATH by native Hermes 0.21.5 (2026.9.24, upstream a928a959). Two isolated native checks replayed the fixture through the command returned by `hermes --print-runtime-command`, retaining its bootstrap before executing the fixture. Both passed discovery, boolean registration observation, prompt-section rendering and unload with zero model calls. Native stderr contained isolated-runtime dependency preparation; adapter context delivery passed. See the aggregate handoff for installed configuration and evidence limits.
