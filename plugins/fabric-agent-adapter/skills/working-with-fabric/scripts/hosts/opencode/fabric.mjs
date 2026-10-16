// #region native-host-context — docs: plugins/fabric-agent-adapter/skills/working-with-fabric/references/native-host-hooks.md
import { readContext } from '../context.mjs';

const marker = '[fabric-agent-adapter]';

// OpenCode's legacy loader treats every export as a plugin factory.
export default async function fabricPlugin({directory} = {}) {
  let fabricRegistered = false;
  return {
    config: async config => {
      const entry = config?.mcp?.fabric;
      // Observe the host's resolved configuration; never read or forward secrets.
      fabricRegistered = !!entry && typeof entry === 'object' && entry.enabled !== false &&
        ((entry.type === 'local' && Array.isArray(entry.command) && entry.command.length > 0) ||
         (entry.type === 'remote' && typeof entry.url === 'string' && entry.url.length > 0));
    },
    'experimental.chat.system.transform': async (_input, output) => {
      if (!Array.isArray(output?.system) || output.system.some(part => typeof part === 'string' && part.includes(marker))) return;
      const context = await readContext('opencode', directory, {fabricRegistered});
      if (context && !output.system.includes(context)) output.system.push(context);
    },
  };
}
// #endregion native-host-context
