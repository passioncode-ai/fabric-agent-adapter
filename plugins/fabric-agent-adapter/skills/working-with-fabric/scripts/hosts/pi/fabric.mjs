// #region native-host-context — docs: plugins/fabric-agent-adapter/skills/working-with-fabric/references/native-host-hooks.md
import { readContext } from '../context.mjs';

const marker = '[fabric-agent-adapter]';

export default function fabricExtension(pi) {
  pi.on('before_agent_start', async (event, ctx) => {
    if (!event || !ctx) return;
    const options = event.systemPromptOptions;
    if (typeof options?.forceSystemPrompt === 'string' && options.forceSystemPrompt.includes(marker)) return;
    if (!options && typeof event.systemPrompt === 'string' && event.systemPrompt.includes(marker)) return;
    if (options?.sections?.fabric_agent_adapter) return;
    let fabricRegistered = false;
    try {
      const tools = pi.getAllTools?.();
      fabricRegistered = Array.isArray(tools) && tools.some(tool =>
        tool?.exposure !== 'hidden' &&
        (tool?.name === 'fabric_whoami' || tool?.name === 'mcp__fabric__fabric_whoami'));
    } catch { /* Early startup or a disabled tool registry is not registration. */ }
    const context = await readContext('pi', ctx.cwd, {fabricRegistered});
    if (!context) return;
    if (typeof options?.forceSystemPrompt === 'string') {
      if (options.forceSystemPrompt.includes(context)) return;
      options.forceSystemPrompt += '\n\n' + context;
    } else if (options && typeof options === 'object') {
      options.sections ??= {};
      if (typeof options.sections !== 'object' || Array.isArray(options.sections)) return;
      options.sections.fabric_agent_adapter = context;
    } else if (typeof event.systemPrompt === 'string') {
      if (event.systemPrompt.includes(context)) return;
      // Older Pi versions expose only the replacement-prompt return contract.
      return {systemPrompt:event.systemPrompt + '\n\n' + context};
    }
  });
}
// #endregion native-host-context
