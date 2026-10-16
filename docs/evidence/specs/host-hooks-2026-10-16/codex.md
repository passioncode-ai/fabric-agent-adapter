# Codex SessionStart parser regression

Verified against installed `codex-cli 0.162.1` with `python3 test/native/codex_hooks.py`. The real app-server `hooks/list` discovers one owned synthetic hook; `config/batchWrite` trusts only its inspected exact hash in an isolated home. No bypass flag, global trust change or real provider is used. A synthetic turn against a closed loopback fixture triggers startup hooks; no model service is called.

| Case | Native result |
|---|---|
| `[fabric-agent-adapter] native fixture` | `failed`, exact error `hook returned invalid session start JSON output` |
| JSON `hookSpecificOutput` with `SessionStart` and the same additionalContext | `completed`, context entry contains the fixture |

The focused helper regression failed on baseline with JSONDecodeError, then passed after Codex switched to the Claude-compatible JSON envelope. Source: [Codex 0.162.1 parser](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/hooks/src/engine/output_parser.rs#L360) treats leading `{` or `[` as JSON-looking; [event parser](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/hooks/src/events/session_start.rs#L287) emits the reported error. Plain text is not universally forbidden; the prefix ambiguity caused this failure.

`PYTHONPATH=test python3 -m unittest test_fabric_session -q`: 63 tests passed before installer-upgrade coverage was added. Final aggregate checks are recorded in the handoff. Native parser success does not prove Fabric admission.
