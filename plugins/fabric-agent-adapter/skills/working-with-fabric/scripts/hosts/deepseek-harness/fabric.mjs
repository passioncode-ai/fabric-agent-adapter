// #region native-host-context — docs: plugins/fabric-agent-adapter/skills/working-with-fabric/references/native-host-hooks.md
// DeepSeek Harness (dsh) loads this as a Cordis plugin from its home layer ($DSH_HOME/cordis.patch.yml, every
// profile: web, headless, acp). On a root agent's start it asks the shared helper for the session-start context and
// injects it as the session's first user message, the way dsh's own hooks bridge delivers a SessionStart context.
// A resumed agent keeps its history and is told nothing again. Nothing here may throw: dsh awaits `agent/created`
// before the first turn, so a failure means no context, never a blocked session (FAA-370).
import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { readContext } from '../context.mjs';

export const name = 'fabric-agent-adapter';
export const inject = ['workingDirectory'];

// Whether the home layer registers Fabric's MCP: a `@deepseek-ai/dsh-mcp-client` row with `serverName: fabric`. dsh
// reads no project-level MCP file, so the home layer is the one place a person's own session registers it. Like the
// other native bridges this is a boolean observation for the helper, never enrollment.
export async function fabricRegistered(env = process.env) {
  try {
    const home = env.DSH_HOME || path.join(os.homedir(), '.dsh');
    const text = await readFile(path.join(home, 'cordis.patch.yml'), 'utf8');
    return text.length <= 1024 * 1024 && /dsh-mcp-client/.test(text) &&
      /^\s*serverName:\s*['"]?fabric['"]?\s*$/m.test(text);
  } catch { return false; }
}

export function apply(ctx) {
  ctx.on('agent/created', async (event) => {
    try {
      const agent = event?.agent;
      if (!agent || event.source !== 'startup' || typeof agent.inject !== 'function') return;
      const signal = event.signal ?? new AbortController().signal;
      const cwd = await ctx.workingDirectory?.ensure?.(agent, signal);
      if (typeof cwd !== 'string' || !cwd) return;
      const context = await readContext('deepseek-harness', cwd, {fabricRegistered: await fabricRegistered()});
      if (!context) return;
      agent.inject(Object.freeze({
        id: randomUUID(),
        role: 'user',
        content: [{type: 'text', text: context}],
        source: {kind: 'fabric-agent-adapter'},
      }));
    } catch { /* No context is the only failure mode a session start may see. */ }
  });
}
// #endregion native-host-context
