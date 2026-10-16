# Native host context hooks (FAA-48)

Use this when installing, upgrading or diagnosing startup context outside Claude Code. Hook delivery and Fabric admission are separate: the agent still calls `fabric_whoami` and reads its actual answer. No adapter here enrolls a session, starts Fabric or calls a model.

## Supported adapters

| Host | Native integration | Output consumed by host | Activation |
|---|---|---|---|
| Claude Code | Plugin `hooks/hooks.json` | SessionStart `hookSpecificOutput.additionalContext` JSON | Enable the Claude plugin; reload the session |
| Codex | `hooks.SessionStart` in `$CODEX_HOME/hooks.json` | SessionStart JSON, including the event name | Install command hook; inspect `/hooks` if its exact definition needs trust |
| Kimi Code | `[[hooks]]` in `~/.kimi-code/config.toml` | Plain stdout; existing adapter retained | Install command hook; start a new session; current native consumption is not covered by the six-host fixture |
| Hermes | Native plugin prompt section `fabric.context` | Session-frozen section, maximum 4000 characters | Install files, then `hermes plugins enable fabric-agent-adapter` |
| OpenCode | Native `experimental.chat.system.transform` | Appends one unique system string | Install `.js` loader; start a new instance |
| OpenClaw | Plugin `before_prompt_build` | `{prependContext}` | Install native plugin path/config; host runtime must be installed; reload through its owner |
| Pi | Extension `before_agent_start` | Structured section, or preserved forced/legacy system prompt | Install `.js` loader; use the host's extension reload or a new instance |

These adapters were checked against Codex 0.162.1, Hermes 0.21.4 (2026.9.21), OpenCode 1.19.0, OpenClaw 2026.10.4 and Pi 1.1.0. Claude Code 2.1.299 also executed SessionStart through an isolated SDK initialization, without a user turn. A parser/loader fixture does not establish a model run or live Fabric connection.

Codex accepts plain text only when it does not look like JSON. The old `[fabric-agent-adapter]` prefix begins with `[`, so Codex tries JSON parsing and reports `hook returned invalid session start JSON output`. Structured JSON removes that ambiguity.

## Install, update and remove

```sh
python3 <skill-dir>/scripts/fabric_session.py install-host-hooks --host opencode
python3 <skill-dir>/scripts/fabric_session.py install-host-hooks --host opencode --apply --expect-sha256 <printed-digest>
python3 <skill-dir>/scripts/fabric_session.py install-host-hooks --host opencode --remove
```

Use `codex`, `kimi`, `hermes`, `opencode`, `openclaw` or `pi`. Default is a dry run. `--config` overrides the native destination, `--script` selects an absolute `fabric_session.py` in a **complete installed skill**. Keep that path stable; a versioned plugin cache disappears on updates. Reapply after moving the skill. The native installer checks the helper and every required host module before writing a loader.

| Host | Default destination |
|---|---|
| Hermes | `$HERMES_HOME/plugins/fabric-agent-adapter/`, default `~/.hermes/plugins/` |
| OpenCode | `$XDG_CONFIG_HOME/opencode/plugins/fabric-agent-adapter.js`, default `~/.config/` |
| OpenClaw | `$OPENCLAW_CONFIG_PATH`, otherwise `$OPENCLAW_STATE_DIR/openclaw.json`, default `~/.openclaw/` |
| Pi | `$PI_CODING_AGENT_DIR/extensions/fabric-agent-adapter.js`, default `~/.pi/agent/` |

Hermes activation remains its own explicit CLI step. Remove its activation with `hermes plugins disable fabric-agent-adapter`, then remove the loader. The installer does not parse or rewrite arbitrary Hermes YAML.

OpenClaw uses strict JSON. For a JSON5 configuration, use OpenClaw's own config commands; this installer refuses it without guessing. An existing master/entry disable, deny list or denied hook permission is preserved and reported. This adapter needs both `allowConversationAccess` and `allowPromptInjection`; it does not read messages. Removing it drops its recognized load path and owned entry; customized entries are disabled. An existing allow-list entry is retained to avoid changing broader discovery policy. Removal is ownership-limited, not an exact rollback of the whole config.

OpenCode and Pi loader files carry a managed marker. A foreign file at the same destination is refused, not overwritten. Existing unrelated extensions/settings remain. Config replacement uses a backup and a stale-plan hash check; Hermes's multi-file loader is preflighted before writes, but the operation is not a filesystem-wide transaction.

## Runtime and failure boundaries

- Native bridges give the Python helper only a working directory and, when observed, a boolean Fabric registration. Hermes uses its native read-only config, OpenCode its resolved enabled MCP entry, OpenClaw its resolved MCP servers and Pi an exact callable `fabric_whoami` tool name. Config registration is not admission.
- Missing helper/Python, malformed values, excessive output or a four-second deadline produce no context. Existing host errors and permission failures are not silenced globally.
- Fabric-launched sessions are silent. Other native events are not advertised: turn observations, unread counts and rejoin-only release remain Claude-specific and feature-gated.
- A host in Switchboard's catalog may support MCP, proxy or launch while exposing no startup context hook. Never copy this configuration to another host solely because it can launch an agent.

## Verification

The repository has focused tests in `test/test_fabric_session.py`, `test/test_native_hook_install.py`, `test/test_hermes_host.py`, `test/host-hooks-opencode-pi.test.mjs` and `test/openclaw-hooks.test.mjs`. Optional native probes use isolated configuration and neutral fixtures, without paid inference. The task's evidence and full 31-host survey live in the owning repository under `docs/evidence/specs/host-hooks-2026-10-16/`; these repository paths are not required to run the installed skill.
