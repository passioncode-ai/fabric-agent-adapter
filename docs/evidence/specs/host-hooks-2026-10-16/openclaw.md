# OpenClaw native context contract

Verified 2026-10-16 against OpenClaw **2026.10.4**, release commit
`383c124cc32ffee3f8e56f549b88da94d269a4af`. The npm registry's `latest` metadata and
the isolated executable agree. The published Node requirement is
`>=24.16.0 <25 || >=26.1.0`; the probe used Node 26.10.0.

## Contract and implementation

The adapter uses a native plugin, with `openclaw.plugin.json`, a package declaring
`openclaw.extensions`, and a default plugin object registering exactly one typed
`before_prompt_build` handler. It contributes `{prependContext}` and leaves the
existing prompt, conversation, tools and policies intact. The helper receives
only the host identifier and the host-resolved workspace; missing workspace
causes no action. It never reads the event's conversation content. Each invocation
is bounded by the shared helper; expired host invocations discard their result.

The plugin API's `api.config` exposes native `mcp.servers`. Only enabled,
nonempty `fabric`/`fabric-mcp` definitions produce `fabricRegistered: true` for
the helper. No command, URL, headers, environment or secrets leave that config
boundary. This is configuration evidence only; per-session tool policy and
reachability still require a proving call. Sources: [plugin API](https://github.com/openclaw/openclaw/blob/383c124cc32ffee3f8e56f549b88da94d269a4af/src/plugins/plugin-api.types.ts),
[MCP schema](https://github.com/openclaw/openclaw/blob/383c124cc32ffee3f8e56f549b88da94d269a4af/src/config/zod-schema.mcp-server.ts),
[MCP guide](https://github.com/openclaw/openclaw/blob/383c124cc32ffee3f8e56f549b88da94d269a4af/docs/tools/mcp.md).

Native loading needs plugin enablement and the existing allow/deny policy to
permit this plugin. Its entry must permit conversation hooks through
`hooks.allowConversationAccess: true`; `hooks.allowPromptInjection: false`
prevents registration. These permissions belong under `hooks`, not `config`.
Explicit installation grants only this plugin's intended permissions; it must
not disable other policies or enable all plugins.

Authoritative pinned sources:

- [Plugin example, loading probe and permission rules](https://github.com/openclaw/openclaw/blob/383c124cc32ffee3f8e56f549b88da94d269a4af/docs/plugins/hooks.md)
- [Optional workspace/session fields and invocation lifetime](https://github.com/openclaw/openclaw/blob/383c124cc32ffee3f8e56f549b88da94d269a4af/src/plugins/hook-agent-context.types.ts)
- [Prompt return fields](https://github.com/openclaw/openclaw/blob/383c124cc32ffee3f8e56f549b88da94d269a4af/src/plugins/hook-before-agent-start.types.ts)
- [Native plugin manifest](https://github.com/openclaw/openclaw/blob/383c124cc32ffee3f8e56f549b88da94d269a4af/docs/plugins/manifest.md)

Internal `agent:bootstrap` hooks are a separate API. Their mutable bootstrap
records are subject to downstream filename/session/privacy filtering and budgets.
This adapter does not register a fictional `SessionStart` native event, return
Claude JSON into a JavaScript hook, or use `event.messages` as context injection.

## Verification receipt

Focused gate: `node --test test/openclaw-hooks.test.mjs` → **8 passed**, exit 0.
Tests cover registration/manifests, context-only contribution, missing workspace,
failed/empty helper, expired invocation, separate current workspaces, native MCP
registration and disabled/malformed registration without forwarding secrets.

No preexisting OpenClaw executable/package was found in PATH or the bounded
Homebrew, nvm, npm-global, pnpm, Volta and bun candidate locations. A skills-only
directory is not a runtime installation. An isolated temporary prefix was used:

```sh
npm install --ignore-scripts --no-audit --no-fund --prefix "$probe" openclaw@2026.10.4
node "$probe/node_modules/openclaw/openclaw.mjs" --version
```

Install exit 0, 341 packages; version output `OpenClaw 2026.10.4 (383c124)`.
The native probe used a disposable workspace, `OPENCLAW_STATE_DIR` and
`OPENCLAW_CONFIG_PATH`, no inherited credentials, and an allowlist containing
only this adapter. `plugins.load.paths` pointed at the repository's native
plugin directory, with both hook permissions explicitly true:

```sh
node "$probe/node_modules/openclaw/openclaw.mjs" plugins inspect fabric-agent-adapter --runtime --json
```

Exit 0. Selected native output (private temporary paths omitted):

```json
{
  "plugin": {"id":"fabric-agent-adapter","status":"loaded","imported":true,"hookCount":1},
  "typedHooks":[{"name":"before_prompt_build"}],
  "diagnostics":[],
  "services":[],
  "tools":[],
  "httpRouteCount":0,
  "policy":{"allowPromptInjection":true,"allowConversationAccess":true}
}
```

The host additionally reports `hook-only-plugin-shape` as an informational,
supported compatibility path. One slow SQLite schema transaction warning was
on stderr and did not corrupt JSON stdout. Inspection created only disposable
local state; it started no Gateway/service and made no model call.

Negative native probe: setting only `allowConversationAccess:false` and running
the same inspect command returned exit 0 with `typedHooks:[]` and a warning
that this specific conversation hook was blocked. The plugin's `loaded` status
alone therefore does not prove hook registration. The installer must preserve
an explicit policy denial instead of silently changing it.

Final implementation rerun (including native MCP-config detection) again returned
exit 0, `loaded`, `imported:true`, exactly `before_prompt_build`, and no diagnostics.
An earlier attempt could not save its output because the machine ran out of disk
space; it is not counted as a passing receipt. The final command printed its
selected result directly and completed before the owned disposable npm prefix
was removed. `df -k` available space changed from 615704 to 1258640 KiB across
that exact cleanup (642936 KiB increase); no unrelated cache or installed runtime
was removed. The isolated probe is reproducible from the recipe above, not a
retained installation.

The optional executable regression is
[`test/native/openclaw_hooks.py`](../../../../test/native/openclaw_hooks.py):

```sh
python3 test/native/openclaw_hooks.py /path/to/openclaw
# Alternatively pass an installed npm prefix or its openclaw.mjs entry.
python3 test/native/openclaw_hooks.py /path/to/npm-prefix
```

It installs nothing and runs in disposable local state with a credential-free
environment. It checks native import/registration and both independent permission
denials. Every runtime command has a deadline, with owned process-group cleanup
on POSIX timeout. No model, Gateway, MCP connection or account is required.
The original positive/conversation-denied commands above were run against the
real runtime; the reusable script was added after deleting the disposable
installation and was syntax/help checked; a disposable fake executable also
exercised all three probe assertion/control-flow paths. That is probe-fixture
validation, not native host acceptance. Its third prompt-injection-denied
case still needs a retained compatible runtime to execute, and is not reported
as an already-run native result.

This proves native loading/registration plus focused handler behavior. It does
not establish model consumption, Fabric enrollment, available MCP tools, global
runtime installation, or an already-running Gateway's reload. Those remain
separate acceptance layers owned by the aggregate installation matrix.

## Permanent installation follow-up

After the initial isolated-runtime receipt, OpenClaw 2026.10.4 (383c124) was installed permanently. The package-specific reviewed postinstall exited 0, `fs-safe` reported `ready`, and the pending lifecycle marker was absent. `python3 test/native/openclaw_hooks.py <installed CLI>` exited 0 for the positive case and both native permission denials. This supersedes the earlier PATH-absence observation and the unrun third native case; it does not claim a Gateway/model session or Fabric admission. Global adapter configuration is recorded in the aggregate handoff.
