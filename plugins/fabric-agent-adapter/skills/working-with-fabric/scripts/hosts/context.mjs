// #region native-host-context — docs: plugins/fabric-agent-adapter/skills/working-with-fabric/references/native-host-hooks.md
// Shared, non-resident bridge. A context hook never enrolls or calls a model.
import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const scriptPath = fileURLToPath(new URL('../fabric_session.py', import.meta.url));
const hosts = new Set(['opencode', 'pi', 'openclaw']);
const cap = 64 * 1024;

export async function readContext(host, cwd, options = {}) {
  if (!hosts.has(host) || typeof cwd !== 'string' || !cwd || cwd.includes('\0')) return '';
  const payload = {cwd};
  if (options.fabricRegistered === true) payload.fabric_registered = true;
  const input = JSON.stringify(payload);
  if (Buffer.byteLength(input) > cap) return '';
  const timeout = Number.isFinite(options.timeoutMs)
    ? Math.max(1, Math.min(4000, options.timeoutMs)) : 4000;
  return new Promise(resolve => {
    try {
      const child = execFile(options.python || 'python3',
        ['-S', options.script || scriptPath, 'hook', 'session-start', '--host', host],
        {timeout, killSignal:'SIGKILL', maxBuffer:cap, encoding:'utf8', windowsHide:true},
        (error, stdout) => {
          if (error || typeof stdout !== 'string' || /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(stdout)) return resolve('');
          resolve(stdout.trim());
        });
      // A missing executable or early exit may close stdin before it is written.
      child.stdin?.on('error', () => {});
      child.stdin?.end(input);
    } catch { resolve(''); }
  });
}
// #endregion native-host-context
