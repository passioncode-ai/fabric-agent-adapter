// #region native-host-context — docs: plugins/fabric-agent-adapter/skills/working-with-fabric/references/native-host-hooks.md
// Native OpenClaw prompt hook. Never observes conversation content or sends messages.
import { readContext } from '../context.mjs';

function fabricRegistered(config) {
  const servers = config?.mcp?.servers;
  if (!servers || typeof servers !== 'object' || Array.isArray(servers)) return false;
  return ['fabric', 'fabric-mcp'].some(name => {
    const entry = Object.hasOwn(servers, name) ? servers[name] : undefined;
    return entry && typeof entry === 'object' && !Array.isArray(entry)
      && entry.enabled !== false
      && [entry.command, entry.url].some(value => typeof value === 'string' && value.trim());
  });
}

export function createPlugin(contextReader = readContext) {
  return {
    id: 'fabric-agent-adapter',
    name: 'Fabric Agent Adapter',
    description: 'Adds bounded Fabric context through the native prompt hook.',
    register(api) {
      api.on('before_prompt_build', async (_event, ctx) => {
        // workspaceDir is optional in the host contract. Do not substitute the
        // Gateway process directory, which can belong to a different project.
        if (typeof ctx?.workspaceDir !== 'string' || !ctx.workspaceDir.trim()) return;
        try {
          // Configured is not connected/admitted. Forward only the boolean,
          // never server configuration, headers, environment or credentials.
          const options = fabricRegistered(api.config) ? { fabricRegistered: true } : {};
          const context = await contextReader('openclaw', ctx.workspaceDir, options);
          ctx.hookInvocation?.assertActive();
          if (typeof context !== 'string' || !context.trim()) return;
          return { prependContext: context };
        } catch {
          // Missing dependencies, unavailable context and expired invocations
          // must not stop an unrelated turn or leak diagnostics into its prompt.
          return;
        }
      });
    },
  };
}

export default createPlugin();
// #endregion native-host-context
