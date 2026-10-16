# Additional catalog hosts: hook research

Read-only snapshot, 2026-10-16. Catalog scope came from Switchboard's agent
catalog; its integration claims are not host hook verification. Presence below
means PATH resolution, not successful runtime initialization or authentication.
No additional host adapters, hooks, settings or services were installed here.

| Host | Local presence | Verified primary-source context mechanism | Acceptance and next step |
|---|---|---|---|
| OpenHands CLI | `openhands` absent | `.openhands/hooks.json` in the actual conversation working folder; `session_start`/`SessionStart`, command JSON stdin with `working_dir`, stdout top-level `additionalContext`. Claude wrapper/PascalCase forms accepted. [Official hooks](https://docs.openhands.dev/openhands/usage/customization/hooks) | Research only. CLI is cataloged as deprecated; current SDK/Agent Canvas documentation does not establish the exact retired CLI loader. Pin an intended CLI/SDK version and prove loading before support. |
| Qwen Code | `qwen` absent | `settings.json` hooks; `SessionStart` sources startup/resume/clear/compact; command JSON stdin; structured `hookSpecificOutput` with matching event and `additionalContext`, or successful plain stdout for session context. [Pinned upstream hooks](https://github.com/QwenLM/qwen-code/blob/b4614845f016ba4e74e38536ce0d98a61d7e764d/docs/users/features/hooks.md) | Research only; candidate command adapter. Preserve hook disablement, workspace trust and other commands. Native parser/loading not exercised. |
| GitHub Copilot CLI | `copilot` absent | `.github/hooks/*.json` and personal `~/.copilot/hooks/*.json`; `sessionStart` command hook consumes top-level JSON `additionalContext`. [Current reference](https://docs.github.com/en/copilot/reference/hooks-reference) | Research only; candidate command adapter. Current reference explicitly contradicts an older official tutorial saying output is ignored; pin runtime and test current parser. Do not substitute SDK callback contracts. |
| Factory Droid | `droid` absent | `SessionStart` handles startup/resume/clear/compact. Successful stdout can add context; structured `hookSpecificOutput.additionalContext` accepted. Native hooks and enabled plugin `hooks/hooks.json` coexist. [Official reference](https://docs.factory.com/harness/hooks) | Research only; candidate command adapter. Preserve project/user/managed hook merge. Runtime/account-dependent load not exercised. |
| Warp | `warp` resolves to installed TUI; desktop app present | Project `AGENTS.md` and global Rules are documented context mechanisms. [Official context guide](https://docs.warp.dev/getting-started/quickstart/coding-in-warp/) | No native agent-lifecycle context hook established by the reviewed sources. OSC notification hooks and shell integration are different surfaces. Use instructions/MCP pending native contract evidence; do not call support impossible or claim hook parity. |
| Kiro CLI | `kiro-cli` absent | V3 standalone `.kiro/hooks/*.json` or profile hook array; canonical `SessionStart`, legacy `AgentSpawn`/`agentSpawn`; successful shell stdout adds context. [Trigger reference](https://kiro.dev/docs/hooks/types/), [profile schema](https://kiro.dev/docs/custom-agents/configuration-reference/) | Research only; version-specific candidate. CLI 2.x object hooks and V3 array/hooks documents differ. Pin version; do not apply IDE blocking guarantees to CLI. |
| Devin CLI | `devin` absent | `.devin/hooks.v1.json` is the unwrapped hooks object; user config `~/.config/devin/config.json` nests `hooks`. `SessionStart` consumes `hookSpecificOutput.additionalContext`. Claude settings are also read by default when `read_config_from.claude` is enabled. [Official hook reference](https://docs.devin.ai/cli/extensibility/hooks/overview) | Research only; candidate command adapter. Discover inherited Claude hooks to prevent duplicate registration. Desktop legacy Cascade and cloud hooks are distinct; no parity claim. |

OpenHands SDK type evidence separately confirms `SessionStart`/`SessionEnd` and
`working_dir` at [SDK commit 6530325](https://github.com/OpenHands/software-agent-sdk/blob/6530325e9dd0ea1b6b4f1994d7dab52764cfc3f1/openhands-sdk/openhands/sdk/hooks/types.py).
This is not evidence that every historical OpenHands CLI release loads those hooks.

Presence receipt: Python `shutil.which` for the catalog binary names; bounded
Warp symlink metadata confirmed a real installed TUI target and desktop app.
No agent sessions, credentials, logs or private configuration content were read.
Account gates and no-model native probes for these additional hosts remain
unverified; documentation alone does not close installation/runtime acceptance.
